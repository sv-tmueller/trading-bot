from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from tools.broker import (
    place_market_order,
    place_parent_market_order,
    place_oco_brackets,
    close_position,
    get_portfolio_value,
    get_current_price,
    cancel_all_orders,
    liquidate_all_positions,
    BrokerSubmitError,
    BrokerOcoSubmitError,
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
    """Issue #133: bracket params are no longer submitted atomically with the parent.

    `place_market_order(..., stop_price=..., take_profit_price=...)` is now a thin
    orchestrator that submits the parent as a plain market order, polls for fill,
    then submits a separate OCO bracket pair. Two `submit_order` calls expected:
    (1) MarketOrderRequest (DAY, no bracket fields), (2) LimitOrderRequest (OCO, GTC).
    """
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        TakeProfitRequest,
        StopLossRequest,
    )
    from alpaca.trading.enums import OrderClass, TimeInForce, OrderSide

    mock_client = MagicMock()
    parent_order = MagicMock()
    parent_order.id = "ord-parent-1"
    parent_order.filled_avg_price = "150.05"   # already filled — skip poll
    oco_order = MagicMock()
    oco_order.id = "ord-oco-1"
    mock_client.submit_order.side_effect = [parent_order, oco_order]

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy", stop_price=145.50, take_profit_price=160.00)

    assert result["order_id"] == "ord-parent-1"   # parent order_id, not OCO's
    assert result["fill_price"] == pytest.approx(150.05)

    # Two broker calls: parent then OCO.
    assert mock_client.submit_order.call_count == 2
    parent_req = mock_client.submit_order.call_args_list[0].args[0]
    oco_req = mock_client.submit_order.call_args_list[1].args[0]

    # Parent: plain DAY market order, no bracket fields.
    assert isinstance(parent_req, MarketOrderRequest)
    assert parent_req.order_class != OrderClass.BRACKET
    assert parent_req.time_in_force == TimeInForce.DAY
    assert parent_req.stop_loss is None
    assert parent_req.take_profit is None

    # OCO: SELL-side limit order with both legs, GTC so the protective pair survives sessions.
    assert isinstance(oco_req, LimitOrderRequest)
    assert oco_req.order_class == OrderClass.OCO
    assert oco_req.side == OrderSide.SELL   # closes a long
    assert oco_req.time_in_force == TimeInForce.GTC
    assert isinstance(oco_req.stop_loss, StopLossRequest)
    assert isinstance(oco_req.take_profit, TakeProfitRequest)
    assert float(oco_req.stop_loss.stop_price) == pytest.approx(145.50)
    assert float(oco_req.take_profit.limit_price) == pytest.approx(160.00)
    assert int(oco_req.qty) == 100   # OCO sized to parent qty


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
    """Issue #133: parent submit failure on the bracket path → BrokerSubmitError with original message.

    The parent is now a plain market order (the OCO is a separate submission post-fill),
    so a parent rejection still raises BrokerSubmitError. OCO-side failures are covered
    by `test_place_market_order_raises_oco_submit_error_when_oco_leg_fails`.
    """
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


# --- place_parent_market_order helper tests (issue #133) ---


def test_place_parent_market_order_returns_order_id_and_fill_price():
    """The new (#133) parent-only helper submits a plain DAY market order, polls for fill,
    and returns `{"order_id", "fill_price"}` — same shape as the legacy place_market_order
    plain path. No bracket fields on the request.
    """
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderClass, TimeInForce

    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-parent-only"
    submitted.filled_avg_price = "150.10"
    mock_client.submit_order.return_value = submitted

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_parent_market_order("AMD", 100, "buy")

    assert result["order_id"] == "ord-parent-only"
    assert result["fill_price"] == pytest.approx(150.10)
    args, _ = mock_client.submit_order.call_args
    request = args[0]
    assert isinstance(request, MarketOrderRequest)
    assert request.time_in_force == TimeInForce.DAY
    assert request.order_class != OrderClass.BRACKET
    assert request.stop_loss is None
    assert request.take_profit is None


def test_place_parent_market_order_invalid_side_raises():
    with pytest.raises(ValueError, match="Invalid order side"):
        place_parent_market_order("AMD", 100, "BUY")


def test_place_parent_market_order_raises_broker_submit_error_on_failure():
    """Parent submit failure → BrokerSubmitError, same as legacy plain path."""
    mock_client = MagicMock()
    mock_client.submit_order.side_effect = Exception("insufficient buying power")

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(BrokerSubmitError, match="insufficient buying power"):
            place_parent_market_order("AMD", 100, "buy")


# --- place_oco_brackets helper tests (issue #133) ---


def test_place_oco_brackets_submits_sell_oco_for_long_entry():
    """For a long entry (parent_side='buy'), the OCO is a SELL-side LimitOrderRequest with
    OCO order_class, GTC time-in-force, and both legs (take_profit + stop_loss). The OCO
    qty matches the parent fill size, so the protective pair covers the whole position.
    """
    from alpaca.trading.requests import LimitOrderRequest, TakeProfitRequest, StopLossRequest
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce

    mock_client = MagicMock()
    oco = MagicMock()
    oco.id = "ord-oco-long"
    mock_client.submit_order.return_value = oco

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_oco_brackets(
            ticker="AMD",
            shares=100,
            parent_side="buy",
            take_profit_price=160.50,
            stop_price=145.25,
        )

    assert result["order_id"] == "ord-oco-long"
    assert result["status"] == "submitted"
    args, _ = mock_client.submit_order.call_args
    request = args[0]
    assert isinstance(request, LimitOrderRequest)
    assert request.order_class == OrderClass.OCO
    assert request.side == OrderSide.SELL
    assert request.time_in_force == TimeInForce.GTC
    assert int(request.qty) == 100
    assert isinstance(request.take_profit, TakeProfitRequest)
    assert isinstance(request.stop_loss, StopLossRequest)
    assert float(request.take_profit.limit_price) == pytest.approx(160.50)
    assert float(request.stop_loss.stop_price) == pytest.approx(145.25)


def test_place_oco_brackets_submits_buy_oco_for_short_entry():
    """For a short entry (parent_side='sell'), the OCO is a BUY-side cover order. We don't
    currently short, but the helper supports both shapes so a future short entry doesn't
    silently mis-submit a sell-side OCO that closes nothing.
    """
    from alpaca.trading.enums import OrderSide

    mock_client = MagicMock()
    oco = MagicMock()
    oco.id = "ord-oco-short"
    mock_client.submit_order.return_value = oco

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        place_oco_brackets(
            ticker="AMD",
            shares=50,
            parent_side="sell",
            take_profit_price=140.0,
            stop_price=155.0,
        )

    args, _ = mock_client.submit_order.call_args
    request = args[0]
    assert request.side == OrderSide.BUY


def test_place_oco_brackets_invalid_parent_side_raises():
    with pytest.raises(ValueError, match="Invalid parent_side"):
        place_oco_brackets(
            ticker="AMD",
            shares=100,
            parent_side="long",   # not "buy" or "sell"
            take_profit_price=160.0,
            stop_price=145.0,
        )


def test_place_oco_brackets_zero_shares_raises():
    with pytest.raises(ValueError, match="shares must be > 0"):
        place_oco_brackets(
            ticker="AMD",
            shares=0,
            parent_side="buy",
            take_profit_price=160.0,
            stop_price=145.0,
        )


def test_place_oco_brackets_non_positive_stop_raises():
    with pytest.raises(ValueError, match="stop_price must be > 0"):
        place_oco_brackets(
            ticker="AMD",
            shares=100,
            parent_side="buy",
            take_profit_price=160.0,
            stop_price=0.0,
        )


def test_place_oco_brackets_non_positive_target_raises():
    with pytest.raises(ValueError, match="take_profit_price must be > 0"):
        place_oco_brackets(
            ticker="AMD",
            shares=100,
            parent_side="buy",
            take_profit_price=-1.0,
            stop_price=145.0,
        )


def test_place_oco_brackets_raises_broker_oco_submit_error_on_alpaca_failure():
    """Alpaca rejection (insufficient qty, no position, etc.) → BrokerOcoSubmitError so
    the caller can distinguish OCO-side failure from parent-side failure and route to
    the correct recovery path (notify_error + position monitor as fallback, NOT the
    notify_order_rejected path which assumes the parent never opened).
    """
    mock_client = MagicMock()
    mock_client.submit_order.side_effect = Exception(
        '{"available":"0","existing_qty":"100","message":"insufficient qty available"}'
    )

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(BrokerOcoSubmitError, match="insufficient qty"):
            place_oco_brackets(
                ticker="AMD",
                shares=100,
                parent_side="buy",
                take_profit_price=160.0,
                stop_price=145.0,
            )


def test_place_oco_brackets_rounds_prices_to_2dp():
    """Alpaca rejects sub-penny prices for non-penny stocks. The helper must round legs
    to 2 decimal places before submission.
    """
    mock_client = MagicMock()
    oco = MagicMock()
    oco.id = "ord-oco-round"
    mock_client.submit_order.return_value = oco

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        place_oco_brackets(
            ticker="AMD",
            shares=100,
            parent_side="buy",
            take_profit_price=160.5678,   # would be rejected by Alpaca
            stop_price=145.1234,
        )

    args, _ = mock_client.submit_order.call_args
    request = args[0]
    # Both legs and the parent limit_price must be 2dp.
    assert float(request.take_profit.limit_price) == pytest.approx(160.57)
    assert float(request.stop_loss.stop_price) == pytest.approx(145.12)
    assert float(request.limit_price) == pytest.approx(160.57)


# --- place_market_order new orchestrator tests (issue #133) ---


def test_place_market_order_skips_oco_when_fill_price_none():
    """If the parent fills but the poll returns no fill_price (timeout fallback path),
    the orchestrator wrapper does NOT submit an OCO — it has nothing to anchor to.
    Only the parent submit_order call is made.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-no-fill-px"
    submitted.filled_avg_price = None
    mock_client.submit_order.return_value = submitted
    # Polling returns "new" forever; short timeout cuts the loop.
    polled = MagicMock()
    polled.status = "new"
    polled.filled_avg_price = None
    mock_client.get_order_by_id.return_value = polled

    with patch("tools.broker.get_trading_client", return_value=mock_client), \
         patch("config.settings.FILL_POLL_TIMEOUT_S", 0.1), \
         patch("config.settings.FILL_POLL_INTERVAL_S", 0.05):
        result = place_market_order("AMD", 100, "buy", stop_price=145.0, take_profit_price=160.0)

    # Only the parent submit; no OCO follow-up because we don't have a fill anchor.
    assert mock_client.submit_order.call_count == 1
    assert result["order_id"] == "ord-no-fill-px"
    assert result["fill_price"] is None


def test_place_market_order_skips_oco_when_no_bracket_params():
    """A plain (no bracket params) call must submit ONLY the parent — no OCO follow-up.
    Preserves the existing legacy plain-market behaviour for sells / closes.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-plain"
    submitted.filled_avg_price = "150.0"
    mock_client.submit_order.return_value = submitted

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        place_market_order("AMD", 100, "sell")   # no stop/target

    assert mock_client.submit_order.call_count == 1


def test_place_market_order_oco_failure_propagates():
    """If the OCO submission fails after a successful parent fill, the orchestrator
    raises BrokerOcoSubmitError so the caller (team_leader) can route to the
    OCO-failure recovery path.
    """
    mock_client = MagicMock()
    parent = MagicMock()
    parent.id = "ord-parent-then-oco-fails"
    parent.filled_avg_price = "150.0"
    # First submit (parent) succeeds; second submit (OCO) raises.
    mock_client.submit_order.side_effect = [parent, Exception("alpaca 503")]

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        with pytest.raises(BrokerOcoSubmitError, match="alpaca 503"):
            place_market_order("AMD", 100, "buy", stop_price=145.0, take_profit_price=160.0)

    # Both submit_order calls must have been attempted.
    assert mock_client.submit_order.call_count == 2
