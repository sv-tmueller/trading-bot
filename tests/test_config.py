from __future__ import annotations

import pytest


def test_watchlist_not_empty():
    from config.watchlist import WATCHLIST
    assert len(WATCHLIST) > 0
    assert all(isinstance(t, str) for t in WATCHLIST)


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


# --- DAILY_CHECK_DRY_RUN (review #3 — lift inline env read into settings) ---


def test_daily_check_dry_run_default_off(monkeypatch):
    """Default is OFF — daily_check.py must place real orders when nothing
    in the env or CLI says otherwise."""
    monkeypatch.delenv("DAILY_CHECK_DRY_RUN", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.DAILY_CHECK_DRY_RUN is False


def test_daily_check_dry_run_truthy_values(monkeypatch):
    """"1", "true", "yes" (case-insensitive) all activate dry-run — same
    semantics as the inline _is_truthy that previously lived in
    daily_check.py."""
    import importlib
    import config.settings as s
    for val in ("1", "true", "TRUE", "yes", "Yes"):
        monkeypatch.setenv("DAILY_CHECK_DRY_RUN", val)
        importlib.reload(s)
        assert s.DAILY_CHECK_DRY_RUN is True, f"failed for {val!r}"


def test_daily_check_dry_run_falsy_values(monkeypatch):
    """Empty / 0 / false / no / arbitrary-text must NOT activate dry-run."""
    import importlib
    import config.settings as s
    for val in ("", "0", "false", "no", "FALSE", "anything-else"):
        monkeypatch.setenv("DAILY_CHECK_DRY_RUN", val)
        importlib.reload(s)
        assert s.DAILY_CHECK_DRY_RUN is False, f"failed for {val!r}"
