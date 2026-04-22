from __future__ import annotations

import pytest


def test_alpaca_base_url_paper(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert "paper-api" in s.ALPACA_BASE_URL


def test_alpaca_base_url_live(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert "paper-api" not in s.ALPACA_BASE_URL


def test_risk_per_trade_default(monkeypatch):
    monkeypatch.delenv("RISK_PER_TRADE", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.RISK_PER_TRADE == 0.01


def test_risk_per_trade_env_override(monkeypatch):
    monkeypatch.setenv("RISK_PER_TRADE", "0.02")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.RISK_PER_TRADE == 0.02


def test_trading_mode_invalid_raises(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "staging")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="TRADING_MODE"):
        importlib.reload(s)


def test_trading_mode_case_insensitive(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert "paper-api" in s.ALPACA_BASE_URL


def test_risk_per_trade_out_of_bounds_raises(monkeypatch):
    monkeypatch.setenv("RISK_PER_TRADE", "0.5")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="RISK_PER_TRADE"):
        importlib.reload(s)


def test_watchlist_not_empty():
    from config.watchlist import WATCHLIST
    assert len(WATCHLIST) > 0
    assert all(isinstance(t, str) for t in WATCHLIST)
