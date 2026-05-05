from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from tools.broker import (
    place_market_order,
    close_position,
    get_portfolio_value,
    get_current_price,
    cancel_all_orders,
    liquidate_all_positions,
    BrokerSubmitError,
)


def test_place_market_order_buy():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-123"
    mock_order.filled_avg_price = "150.00"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    mock_client.submit_order.assert_called_once()
    assert result["order_id"] == "order-123"
    assert result["fill_price"] == pytest.approx(150.00)


def test_place_market_order_sell():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_order.filled_avg_price = "148.50"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "sell")

    assert result["order_id"] == "order-456"
    assert result["fill_price"] == pytest.approx(148.50)


def test_place_market_order_fill_price_zero_when_zero_filled():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-789"
    mock_order.filled_avg_price = "0.0"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    assert result["fill_price"] == pytest.approx(0.0)


def test_place_market_order_fill_price_none_when_not_filled():
    """Issue #132: submit returns no avg_price → poll → poll never sees a terminal status
    within the timeout → returns fill_price=None so the caller can fall back to the pre-order quote.
    """
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_order.filled_avg_price = None
    mock_client.submit_order.return_value = mock_order

    # Polling sees a non-terminal "new" status forever; the short timeout cuts the loop.
    polled = MagicMock()
    polled.status = "new"
    polled.filled_avg_price = None
    mock_client.get_order_by_id.return_value = polled

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 0.1), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.05):
        result = place_market_order("AMD", 100, "buy")

    assert result["order_id"] == "order-456"
    assert result["fill_price"] is None


def test_get_portfolio_value():
    mock_client = MagicMock()
    mock_account = MagicMock()
    mock_account.portfolio_value = "98500.50"
    mock_client.get_account.return_value = mock_account

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        value = get_portfolio_value()

    assert value == pytest.approx(98500.50)


def test_close_position():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "close-789"
    mock_client.close_position.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = close_position("AMD")

    mock_client.close_position.assert_called_once_with("AMD")
    assert result == "close-789"


def test_place_market_order_invalid_side_raises():
    with pytest.raises(ValueError, match="Invalid order side"):
        place_market_order("AMD", 100, "BUY")


def test_get_current_price_raises_on_zero_quote():
    mock_data_client = MagicMock()
    mock_quote = MagicMock()
    mock_quote.bid_price = "0.0"
    mock_quote.ask_price = "0.0"
    mock_data_client.get_stock_latest_quote.return_value = {"AMD": mock_quote}

    with patch("tools.broker.StockHistoricalDataClient", return_value=mock_data_client):
        with pytest.raises(ValueError, match="No valid quote for AMD"):
            get_current_price("AMD")


def test_place_market_order_bracket_request_shape():
    """When both stop_price and take_profit_price are given, submit as a BRACKET order."""
    from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
    from alpaca.trading.enums import OrderClass, TimeInForce

    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "ord-bracket-1"
    mock_order.filled_avg_price = "150.05"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy", stop_price=145.50, take_profit_price=160.00)

    assert result["order_id"] == "ord-bracket-1"
    assert result["fill_price"] == pytest.approx(150.05)
    args, _ = mock_client.submit_order.call_args
    request = args[0]
    assert isinstance(request, MarketOrderRequest)
    assert request.order_class == OrderClass.BRACKET
    assert request.time_in_force == TimeInForce.GTC
    assert isinstance(request.stop_loss, StopLossRequest)
    assert isinstance(request.take_profit, TakeProfitRequest)
    assert float(request.stop_loss.stop_price) == pytest.approx(145.50)
    assert float(request.take_profit.limit_price) == pytest.approx(160.00)


def test_place_market_order_plain_when_no_bracket_params():
    """Without bracket params, the request must be plain DAY market order (no order_class=BRACKET)."""
    from alpaca.trading.enums import OrderClass, TimeInForce

    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "ord-plain"
    mock_order.filled_avg_price = "150.0"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        place_market_order("AMD", 100, "buy")

    args, _ = mock_client.submit_order.call_args
    request = args[0]
    assert request.time_in_force == TimeInForce.DAY
    # Bracket-only attributes must not be set on plain orders.
    assert request.order_class != OrderClass.BRACKET
    assert request.stop_loss is None
    assert request.take_profit is None


def test_place_market_order_raises_broker_submit_error_on_plain_path():
    """Plain (non-bracket) submit failure → BrokerSubmitError with original message embedded."""
    mock_client = MagicMock()
    mock_client.submit_order.side_effect = Exception("insufficient buying power")

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(BrokerSubmitError, match="insufficient buying power"):
            place_market_order("AMD", 100, "buy")


def test_place_market_order_raises_broker_submit_error_on_bracket_path():
    """Bracket submit failure → BrokerSubmitError with original message embedded."""
    mock_client = MagicMock()
    mock_client.submit_order.side_effect = Exception("wash trade detected")

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(BrokerSubmitError, match="wash trade detected"):
            place_market_order("AMD", 100, "buy", stop_price=145.0, take_profit_price=160.0)


def test_place_market_order_partial_bracket_falls_back_to_plain():
    """Only one of stop_price/take_profit_price → not enough for a bracket — must submit plain order."""
    from alpaca.trading.enums import TimeInForce, OrderClass

    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "ord-partial"
    mock_order.filled_avg_price = "150.0"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        place_market_order("AMD", 100, "buy", stop_price=145.0)   # missing take_profit

    args, _ = mock_client.submit_order.call_args
    request = args[0]
    assert request.time_in_force == TimeInForce.DAY
    assert request.order_class != OrderClass.BRACKET


# --- Panic CLI primitives (issue #103) ---


def test_cancel_all_orders_calls_client_and_returns_summaries():
    """cancel_all_orders must delegate to client.cancel_orders and shape the response."""
    mock_client = MagicMock()
    resp_a = MagicMock()
    resp_a.id = "ord-1"
    resp_a.status = 207
    resp_b = MagicMock()
    resp_b.id = "ord-2"
    resp_b.status = 207
    mock_client.cancel_orders.return_value = [resp_a, resp_b]

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        out = cancel_all_orders()

    mock_client.cancel_orders.assert_called_once_with()
    assert out == [
        {"order_id": "ord-1", "status": 207},
        {"order_id": "ord-2", "status": 207},
    ]


def test_cancel_all_orders_returns_empty_list_when_none_open():
    """No open orders → client returns empty/None → we return []."""
    mock_client = MagicMock()
    mock_client.cancel_orders.return_value = []

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        assert cancel_all_orders() == []


def test_cancel_all_orders_propagates_broker_error():
    """A broker failure must NOT be swallowed — panic CLI relies on the exception to exit non-zero."""
    mock_client = MagicMock()
    mock_client.cancel_orders.side_effect = RuntimeError("alpaca 503")

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="alpaca 503"):
            cancel_all_orders()


def test_liquidate_all_positions_calls_client_with_cancel_orders_true():
    """liquidate_all_positions must call client.close_all_positions(cancel_orders=True)."""
    mock_client = MagicMock()
    resp = MagicMock()
    resp.symbol = "AMD"
    resp.order_id = "close-1"
    resp.status = 207
    mock_client.close_all_positions.return_value = [resp]

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        out = liquidate_all_positions()

    mock_client.close_all_positions.assert_called_once_with(cancel_orders=True)
    assert out == [{"symbol": "AMD", "order_id": "close-1", "status": 207}]


def test_liquidate_all_positions_handles_none_response():
    """Some Alpaca SDK paths can return None — must coerce to []."""
    mock_client = MagicMock()
    mock_client.close_all_positions.return_value = None

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        assert liquidate_all_positions() == []


def test_liquidate_all_positions_propagates_broker_error():
    """Errors must propagate so panic CLI exits non-zero and Discord shows the failure."""
    mock_client = MagicMock()
    mock_client.close_all_positions.side_effect = RuntimeError("alpaca 500")

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="alpaca 500"):
            liquidate_all_positions()


# --- Fill-polling tests (issue #132) ---


def test_place_market_order_polls_for_fill_when_submit_avg_price_none():
    """Submit returns avg_price=None → poll → first poll reports filled with avg_price.

    Mirrors the real Alpaca flow: submit_order accepts immediately, the actual fill
    confirmation arrives on a subsequent get_order_by_id call. The returned fill_price
    must be the broker's filled_avg_price, not None.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-fill-1"
    submitted.filled_avg_price = None  # not yet filled when submit returns
    mock_client.submit_order.return_value = submitted

    # First poll already reports filled with the actual broker fill.
    polled = MagicMock()
    polled.status = "filled"
    polled.filled_avg_price = "350.47"   # AMD example from #132
    mock_client.get_order_by_id.return_value = polled

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        result = place_market_order("AMD", 41, "buy")

    mock_client.get_order_by_id.assert_called()
    assert result["order_id"] == "order-fill-1"
    assert result["fill_price"] == pytest.approx(350.47)


def test_place_market_order_polls_through_pending_then_filled():
    """Polls a few "new"/"accepted" ticks before reporting "filled" — common on busy paper."""
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-fill-2"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted

    pending = MagicMock()
    pending.status = "accepted"
    pending.filled_avg_price = None

    filled = MagicMock()
    filled.status = "filled"
    filled.filled_avg_price = "151.23"

    mock_client.get_order_by_id.side_effect = [pending, pending, filled]

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        result = place_market_order("AMD", 100, "buy")

    assert mock_client.get_order_by_id.call_count == 3
    assert result["fill_price"] == pytest.approx(151.23)


def test_place_market_order_partial_fill_returns_partial_avg_price():
    """A partial fill IS a fill — return the broker's filled_avg_price for the shares we got.

    Documented behaviour (#132): partial_filled is treated as terminal-fill, not as
    rejection, because we want the trade row to exist with the actual partial-fill price
    rather than be lost. The position monitor will manage the partial position from there.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-partial"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted

    partial = MagicMock()
    partial.status = "partially_filled"
    partial.filled_avg_price = "200.10"
    mock_client.get_order_by_id.return_value = partial

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        result = place_market_order("AMD", 100, "buy")

    assert result["fill_price"] == pytest.approx(200.10)


def test_place_market_order_terminal_rejection_raises_broker_submit_error():
    """If polling reveals a terminal non-fill status (canceled/expired/rejected/...),
    raise BrokerSubmitError so the existing rejection path in team_leader fires.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-rej"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted

    rejected = MagicMock()
    rejected.status = "rejected"
    rejected.filled_avg_price = None
    mock_client.get_order_by_id.return_value = rejected

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        with pytest.raises(BrokerSubmitError, match="rejected"):
            place_market_order("AMD", 100, "buy")


def test_place_market_order_canceled_status_raises_broker_submit_error():
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-can"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted

    canceled = MagicMock()
    canceled.status = "canceled"
    canceled.filled_avg_price = None
    mock_client.get_order_by_id.return_value = canceled

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        with pytest.raises(BrokerSubmitError, match="canceled"):
            place_market_order("AMD", 100, "buy")


def test_place_market_order_handles_alpaca_orderstatus_enum_value():
    """The Alpaca SDK returns an OrderStatus enum, not a raw string — _order_status_str must
    coerce both. Use the actual enum to lock in the behaviour against SDK changes.
    """
    from alpaca.trading.enums import OrderStatus
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-enum"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted

    polled = MagicMock()
    polled.status = OrderStatus.FILLED   # enum, like the real SDK
    polled.filled_avg_price = "175.55"
    mock_client.get_order_by_id.return_value = polled

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        result = place_market_order("AMD", 100, "buy")

    assert result["fill_price"] == pytest.approx(175.55)


def test_place_market_order_poll_transient_error_then_recovers():
    """A transient `get_order_by_id` exception mid-loop must NOT crash the order — the
    loop swallows it, sleeps, and tries again. (We already submitted; we want to know the fill.)
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-flaky"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted

    filled = MagicMock()
    filled.status = "filled"
    filled.filled_avg_price = "99.99"
    mock_client.get_order_by_id.side_effect = [
        ConnectionError("temporary"),
        filled,
    ]

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 1.0), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.01):
        result = place_market_order("AMD", 100, "buy")

    assert mock_client.get_order_by_id.call_count == 2
    assert result["fill_price"] == pytest.approx(99.99)


def test_place_market_order_skip_poll_when_submit_already_has_avg_price():
    """If Alpaca populates filled_avg_price on the submit response (rare on paper, common
    enough on live), don't bother polling — just use it.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "order-fast"
    submitted.filled_avg_price = "150.05"   # already populated
    mock_client.submit_order.return_value = submitted

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    mock_client.get_order_by_id.assert_not_called()
    assert result["fill_price"] == pytest.approx(150.05)
