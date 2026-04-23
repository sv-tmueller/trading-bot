from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from tools.broker import place_market_order, close_position, get_portfolio_value, get_current_price


def test_place_market_order_buy():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-123"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    mock_client.submit_order.assert_called_once()
    assert result == "order-123"


def test_place_market_order_sell():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "sell")

    assert result == "order-456"


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
