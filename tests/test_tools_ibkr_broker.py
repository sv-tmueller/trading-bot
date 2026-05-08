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
