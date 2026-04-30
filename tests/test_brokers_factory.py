from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from tools.brokers import BaseBroker, AlpacaBroker, get_broker


def test_get_broker_returns_alpaca_by_default():
    broker = get_broker()
    assert isinstance(broker, AlpacaBroker)
    assert isinstance(broker, BaseBroker)


def test_get_broker_unknown_name_raises():
    with patch("tools.brokers.settings.BROKER", "schwab"):
        with pytest.raises(ValueError, match="Unknown broker 'schwab'"):
            get_broker()


def test_alpaca_broker_implements_full_contract():
    """Every abstract method on BaseBroker must be implemented on AlpacaBroker."""
    abstract_methods = BaseBroker.__abstractmethods__
    assert abstract_methods, "BaseBroker should declare abstract methods"
    for name in abstract_methods:
        attr = getattr(AlpacaBroker, name, None)
        assert callable(attr), f"AlpacaBroker missing implementation of {name!r}"
        assert name not in getattr(AlpacaBroker, "__abstractmethods__", set()), (
            f"AlpacaBroker did not concretely implement {name!r}"
        )


def test_base_broker_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseBroker()  # type: ignore[abstract]


def test_alpaca_broker_place_market_order_delegates():
    broker = AlpacaBroker()
    with patch("tools.broker.place_market_order", return_value={"order_id": "x", "fill_price": 1.0}) as m:
        result = broker.place_market_order("AMD", 10, "buy", stop_price=1.0, take_profit_price=2.0)
    m.assert_called_once_with("AMD", 10, "buy", stop_price=1.0, take_profit_price=2.0)
    assert result == {"order_id": "x", "fill_price": 1.0}


def test_alpaca_broker_close_position_delegates():
    broker = AlpacaBroker()
    with patch("tools.broker.close_position", return_value="ord-9") as m:
        result = broker.close_position("AMD")
    m.assert_called_once_with("AMD")
    assert result == "ord-9"


def test_alpaca_broker_get_portfolio_value_delegates():
    broker = AlpacaBroker()
    with patch("tools.broker.get_portfolio_value", return_value=12345.67) as m:
        assert broker.get_portfolio_value() == pytest.approx(12345.67)
    m.assert_called_once_with()


def test_alpaca_broker_get_positions_delegates_to_alpaca_positions():
    """``get_positions`` is the contract name; the underlying Alpaca helper
    is ``get_alpaca_positions`` — adapter must bridge the rename."""
    broker = AlpacaBroker()
    fake = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    with patch("tools.broker.get_alpaca_positions", return_value=fake) as m:
        assert broker.get_positions() == fake
    m.assert_called_once_with()


def test_alpaca_broker_get_current_price_delegates():
    broker = AlpacaBroker()
    with patch("tools.broker.get_current_price", return_value=151.5) as m:
        assert broker.get_current_price("AMD") == pytest.approx(151.5)
    m.assert_called_once_with("AMD")


def test_settings_rejects_unknown_broker(monkeypatch):
    """Invalid BROKER env var raises at settings import time."""
    import importlib
    monkeypatch.setenv("BROKER", "nonexistent_broker")
    import config.settings as settings_module
    with pytest.raises(ValueError, match="BROKER must be one of"):
        importlib.reload(settings_module)
    # Restore default so other tests aren't affected.
    monkeypatch.setenv("BROKER", "alpaca")
    importlib.reload(settings_module)
