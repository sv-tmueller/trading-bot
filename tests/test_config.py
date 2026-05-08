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


def test_trailing_stop_default_off(monkeypatch):
    """Default behavior must be unchanged (TRAILING_STOP_ENABLED=false)."""
    monkeypatch.delenv("TRAILING_STOP_ENABLED", raising=False)
    monkeypatch.delenv("TRAILING_STOP_ATR_MULT", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.TRAILING_STOP_ENABLED is False
    assert s.TRAILING_STOP_ATR_MULT == 1.5


def test_trailing_stop_atr_mult_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("TRAILING_STOP_ATR_MULT", "0.1")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="TRAILING_STOP_ATR_MULT"):
        importlib.reload(s)
    monkeypatch.setenv("TRAILING_STOP_ATR_MULT", "10.0")
    with pytest.raises(ValueError, match="TRAILING_STOP_ATR_MULT"):
        importlib.reload(s)


# --- CLAUDE_AGENT_NO_BROKER (issue #168) -------------------------------------


def test_claude_agent_no_broker_default_off(monkeypatch):
    """Default (env var unset) must be OFF — production cron must not be impacted."""
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.CLAUDE_AGENT_NO_BROKER is False
    assert s.is_claude_agent_no_broker() is False


def test_claude_agent_no_broker_truthy_values(monkeypatch):
    """"1", "true", "yes" (case-insensitive) all activate the guard. Read fresh on
    each `is_claude_agent_no_broker()` call so pytest's monkeypatch is honoured
    without a settings reload — important so the suite-wide autouse fixture in
    `tests/conftest.py` works."""
    import config.settings as s
    for val in ("1", "true", "TRUE", "yes", "YES", "True"):
        monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", val)
        assert s.is_claude_agent_no_broker() is True, f"failed for {val!r}"


def test_claude_agent_no_broker_falsy_values(monkeypatch):
    """Empty string / "0" / "false" / "no" / random text must NOT activate the guard."""
    import config.settings as s
    for val in ("", "0", "false", "FALSE", "no", "anything-else"):
        monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", val)
        assert s.is_claude_agent_no_broker() is False, f"failed for {val!r}"


# --- IBKR + regime-filter env vars (rules-engine pivot, Task 1) --------------


def test_ibkr_host_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.IBKR_HOST == "127.0.0.1"


def test_ibkr_port_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.IBKR_PORT == 4002  # paper default


def test_ibkr_port_validation_low(monkeypatch):
    monkeypatch.setenv("IBKR_PORT", "0")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="IBKR_PORT"):
        importlib.reload(s)


def test_ibkr_port_validation_high(monkeypatch):
    monkeypatch.setenv("IBKR_PORT", "70000")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="IBKR_PORT"):
        importlib.reload(s)


def test_kill_switch_drawdown_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.KILL_SWITCH_DRAWDOWN_PCT == 0.25


def test_kill_switch_drawdown_validation(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH_DRAWDOWN_PCT", "1.5")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="KILL_SWITCH_DRAWDOWN_PCT"):
        importlib.reload(s)


def test_regime_sma_days_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.REGIME_SMA_DAYS == 200


def test_kill_switch_lookback_days_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.KILL_SWITCH_LOOKBACK_DAYS == 30


def test_bot_ticker_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.BOT_TICKER == "WSPL.DE"


def test_bot_benchmark_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.BOT_BENCHMARK == "SPY"


def test_bot_ticker_empty_rejected(monkeypatch):
    monkeypatch.setenv("BOT_TICKER", "")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="BOT_TICKER"):
        importlib.reload(s)
