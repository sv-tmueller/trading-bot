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
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_order.filled_avg_price = None
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
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
