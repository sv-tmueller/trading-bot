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


def test_max_hold_days_env_override(monkeypatch):
    monkeypatch.setenv("MAX_HOLD_DAYS", "10")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.MAX_HOLD_DAYS == 10


def test_rr_ratio_min_env_override(monkeypatch):
    monkeypatch.setenv("RR_RATIO_MIN", "2.5")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.RR_RATIO_MIN == pytest.approx(2.5)


def test_max_portfolio_exposure_env_override(monkeypatch):
    monkeypatch.setenv("MAX_PORTFOLIO_EXPOSURE", "0.30")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.MAX_PORTFOLIO_EXPOSURE == pytest.approx(0.30)


def test_max_hold_days_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("MAX_HOLD_DAYS", "0")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="MAX_HOLD_DAYS"):
        importlib.reload(s)


def test_rr_ratio_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("RR_RATIO_MIN", "0.5")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="RR_RATIO_MIN"):
        importlib.reload(s)


def test_max_portfolio_exposure_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("MAX_PORTFOLIO_EXPOSURE", "0.99")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="MAX_PORTFOLIO_EXPOSURE"):
        importlib.reload(s)


def test_daily_drawdown_limit_env_override(monkeypatch):
    monkeypatch.setenv("DAILY_DRAWDOWN_LIMIT", "0.05")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.DAILY_DRAWDOWN_LIMIT == pytest.approx(0.05)


def test_daily_drawdown_limit_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("DAILY_DRAWDOWN_LIMIT", "0.001")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="DAILY_DRAWDOWN_LIMIT"):
        importlib.reload(s)
    monkeypatch.setenv("DAILY_DRAWDOWN_LIMIT", "0.5")
    with pytest.raises(ValueError, match="DAILY_DRAWDOWN_LIMIT"):
        importlib.reload(s)


def test_watchlist_not_empty():
    from config.watchlist import WATCHLIST
    assert len(WATCHLIST) > 0
    assert all(isinstance(t, str) for t in WATCHLIST)
