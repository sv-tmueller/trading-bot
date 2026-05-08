from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

# Ensure the global guard is OFF for these specific tests (we'll re-enable
# selectively to test the guard behaviour).
@pytest.fixture(autouse=True)
def _guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)


def test_connect_ibkr_returns_connected_client():
    with patch("tools.ibkr_broker.IB") as MockIB:
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr
        ib = connect_ibkr(host="127.0.0.1", port=4002, client_id=1)

        mock_ib.connect.assert_called_once_with("127.0.0.1", 4002, clientId=1, timeout=10)
        assert ib is mock_ib


def test_connect_ibkr_retries_on_failure():
    """Two failures, then success, should still return a connected client."""
    with patch("tools.ibkr_broker.IB") as MockIB:
        mock_ib = MagicMock()
        # First two connects raise, third succeeds
        mock_ib.connect.side_effect = [ConnectionError("first"), ConnectionError("second"), None]
        mock_ib.isConnected.return_value = True
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr
        ib = connect_ibkr(host="127.0.0.1", port=4002, client_id=1, max_retries=3, backoff_s=0.01)

        assert mock_ib.connect.call_count == 3
        assert ib is mock_ib


def test_connect_ibkr_raises_after_max_retries():
    with patch("tools.ibkr_broker.IB") as MockIB:
        mock_ib = MagicMock()
        mock_ib.connect.side_effect = ConnectionError("nope")
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr, IBKRConnectionError
        with pytest.raises(IBKRConnectionError):
            connect_ibkr(host="127.0.0.1", port=4002, client_id=1, max_retries=2, backoff_s=0.01)
        assert mock_ib.connect.call_count == 2


def test_connect_ibkr_sleeps_between_retries_not_after_final():
    """Sleep must be called max_retries - 1 times, not max_retries."""
    with patch("tools.ibkr_broker.IB") as MockIB, \
         patch("tools.ibkr_broker.time.sleep") as mock_sleep:
        mock_ib = MagicMock()
        mock_ib.connect.side_effect = ConnectionError("nope")
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr, IBKRConnectionError
        with pytest.raises(IBKRConnectionError):
            connect_ibkr(host="127.0.0.1", port=4002, client_id=1,
                         max_retries=3, backoff_s=0.5)
        assert mock_sleep.call_count == 2  # 3 attempts → 2 sleeps between them
        mock_sleep.assert_called_with(0.5)


def test_connect_ibkr_sleeps_on_soft_failure_path():
    """If isConnected() returns False, retry path must still sleep before re-attempting."""
    with patch("tools.ibkr_broker.IB") as MockIB, \
         patch("tools.ibkr_broker.time.sleep") as mock_sleep:
        mock_ib = MagicMock()
        mock_ib.connect.return_value = None  # connect succeeds (no exception)
        mock_ib.isConnected.side_effect = [False, False, True]  # third attempt true
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr
        ib = connect_ibkr(host="127.0.0.1", port=4002, client_id=1,
                          max_retries=3, backoff_s=0.5)
        assert ib is mock_ib
        assert mock_sleep.call_count == 2  # 2 soft failures → 2 sleeps before 3rd attempt


def test_get_position_returns_zero_when_no_positions():
    mock_ib = MagicMock()
    mock_ib.positions.return_value = []
    from tools.ibkr_broker import get_position
    qty = get_position(mock_ib, "WSPL.DE")
    assert qty == 0


def test_get_position_returns_quantity_when_held():
    mock_ib = MagicMock()
    mock_pos = MagicMock()
    mock_pos.contract.symbol = "WSPL"
    mock_pos.position = 100
    mock_ib.positions.return_value = [mock_pos]
    from tools.ibkr_broker import get_position
    qty = get_position(mock_ib, "WSPL.DE")
    assert qty == 100


def test_get_position_ignores_other_symbols():
    mock_ib = MagicMock()
    other = MagicMock(); other.contract.symbol = "AAPL"; other.position = 50
    target = MagicMock(); target.contract.symbol = "WSPL"; target.position = 200
    mock_ib.positions.return_value = [other, target]
    from tools.ibkr_broker import get_position
    qty = get_position(mock_ib, "WSPL.DE")
    assert qty == 200


def test_get_account_value_returns_eur_net_liquidation():
    mock_ib = MagicMock()
    av_eur = MagicMock(); av_eur.tag = "NetLiquidation"; av_eur.value = "12345.67"; av_eur.currency = "EUR"
    av_usd = MagicMock(); av_usd.tag = "NetLiquidation"; av_usd.value = "999.00"; av_usd.currency = "USD"
    mock_ib.accountSummary.return_value = [av_eur, av_usd]
    from tools.ibkr_broker import get_account_value
    val = get_account_value(mock_ib, currency="EUR")
    assert val == pytest.approx(12345.67)


def test_guard_blocks_connect(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    with patch("tools.ibkr_broker.IB") as MockIB:
        from tools.ibkr_broker import connect_ibkr, BrokerCallBlockedError
        with pytest.raises(BrokerCallBlockedError):
            connect_ibkr(host="127.0.0.1", port=4002, client_id=1)
        # The IB() class should never have been instantiated
        MockIB.assert_not_called()


def _mock_filled_trade(price: float, qty: int, order_id: str = "ORD-1"):
    trade = MagicMock()
    trade.isDone.return_value = True
    fill = MagicMock()
    fill.execution.price = price
    fill.execution.shares = qty
    fill.execution.execId = "EXEC-1"
    fill.time = "2026-05-07T14:30:01"
    trade.fills = [fill]
    trade.order.orderId = order_id
    return trade


def test_place_market_order_returns_fill_dict_on_buy():
    mock_ib = MagicMock()
    qualified = MagicMock(); qualified.symbol = "WSPL"
    mock_ib.qualifyContracts.return_value = [qualified]
    mock_ib.placeOrder.return_value = _mock_filled_trade(price=50.0, qty=100, order_id="42")
    mock_ib.sleep = MagicMock()  # no real sleep

    from tools.ibkr_broker import place_market_order
    result = place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=100,
                                 fill_timeout_s=5, poll_interval_s=0.01)
    assert result["order_id"] == "42"
    assert result["fill_price"] == 50.0
    assert result["qty"] == 100
    assert mock_ib.placeOrder.called


def test_place_market_order_timeout_cancels_and_raises():
    mock_ib = MagicMock()
    qualified = MagicMock(); qualified.symbol = "WSPL"
    mock_ib.qualifyContracts.return_value = [qualified]
    pending = MagicMock(); pending.isDone.return_value = False
    pending.fills = []
    mock_ib.placeOrder.return_value = pending
    mock_ib.sleep = MagicMock()

    from tools.ibkr_broker import place_market_order, OrderTimeoutError
    with pytest.raises(OrderTimeoutError):
        place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=100,
                           fill_timeout_s=0.05, poll_interval_s=0.01)
    mock_ib.cancelOrder.assert_called_once()


def test_place_market_order_validates_side():
    mock_ib = MagicMock()
    from tools.ibkr_broker import place_market_order
    with pytest.raises(ValueError, match="side"):
        place_market_order(mock_ib, symbol="WSPL.DE", side="HOLD", qty=100)


def test_place_market_order_validates_qty():
    mock_ib = MagicMock()
    from tools.ibkr_broker import place_market_order
    with pytest.raises(ValueError, match="qty"):
        place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=0)


def test_place_market_order_blocked_by_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    mock_ib = MagicMock()
    from tools.ibkr_broker import place_market_order, BrokerCallBlockedError
    with pytest.raises(BrokerCallBlockedError):
        place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=100)
    mock_ib.placeOrder.assert_not_called()


def test_liquidate_sells_existing_position():
    mock_ib = MagicMock()
    qualified = MagicMock(); qualified.symbol = "WSPL"
    mock_ib.qualifyContracts.return_value = [qualified]
    pos = MagicMock(); pos.contract.symbol = "WSPL"; pos.position = 100
    mock_ib.positions.return_value = [pos]
    mock_ib.placeOrder.return_value = _mock_filled_trade(price=49.0, qty=100, order_id="L1")
    mock_ib.sleep = MagicMock()

    from tools.ibkr_broker import liquidate
    result = liquidate(mock_ib, symbol="WSPL.DE", fill_timeout_s=5, poll_interval_s=0.01)
    assert result["fill_price"] == 49.0
    args, kwargs = mock_ib.placeOrder.call_args
    submitted_order = args[1]
    assert submitted_order.action == "SELL"
    assert submitted_order.totalQuantity == 100


def test_liquidate_no_position_returns_none():
    mock_ib = MagicMock()
    mock_ib.positions.return_value = []
    from tools.ibkr_broker import liquidate
    result = liquidate(mock_ib, symbol="WSPL.DE")
    assert result is None
    mock_ib.placeOrder.assert_not_called()


def test_liquidate_blocked_by_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    mock_ib = MagicMock()
    from tools.ibkr_broker import liquidate, BrokerCallBlockedError
    with pytest.raises(BrokerCallBlockedError):
        liquidate(mock_ib, symbol="WSPL.DE")
    mock_ib.positions.assert_not_called()


def test_cancel_all_orders_calls_cancel_for_each_open():
    mock_ib = MagicMock()
    o1 = MagicMock(); o1.orderId = 1
    o2 = MagicMock(); o2.orderId = 2
    trade1 = MagicMock(); trade1.order = o1; trade1.isDone.return_value = False
    trade2 = MagicMock(); trade2.order = o2; trade2.isDone.return_value = False
    mock_ib.openTrades.return_value = [trade1, trade2]

    from tools.ibkr_broker import cancel_all_orders
    n = cancel_all_orders(mock_ib)
    assert n == 2
    assert mock_ib.cancelOrder.call_count == 2


def test_cancel_all_orders_returns_success_count_only():
    """If a cancel raises, it must be excluded from the returned count."""
    mock_ib = MagicMock()
    o1 = MagicMock(); o1.orderId = 1
    o2 = MagicMock(); o2.orderId = 2
    trade1 = MagicMock(); trade1.order = o1; trade1.isDone.return_value = False
    trade2 = MagicMock(); trade2.order = o2; trade2.isDone.return_value = False
    mock_ib.openTrades.return_value = [trade1, trade2]
    mock_ib.cancelOrder.side_effect = [None, RuntimeError("broker hiccup")]

    from tools.ibkr_broker import cancel_all_orders
    n = cancel_all_orders(mock_ib)
    assert n == 1  # only the first succeeded
    assert mock_ib.cancelOrder.call_count == 2  # both were attempted


def test_cancel_all_orders_blocked_by_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    mock_ib = MagicMock()
    from tools.ibkr_broker import cancel_all_orders, BrokerCallBlockedError
    with pytest.raises(BrokerCallBlockedError):
        cancel_all_orders(mock_ib)
    mock_ib.openTrades.assert_not_called()
