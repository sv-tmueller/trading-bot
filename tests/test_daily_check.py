"""Integration tests for daily_check.py.

All external dependencies (yfinance, IBKR, notifications, DB) are mocked.
The CLAUDE_AGENT_NO_BROKER conftest fixture ensures any forgotten mock
fails fast.
"""
from __future__ import annotations

import contextlib
import sqlite3
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from storage.init_db import init_db


@pytest.fixture(autouse=True)
def _unpause_trading(monkeypatch):
    """Force-unpause trading for every test in this module so the pipeline
    actually runs. The repo's `.env` file may have `TRADING_PAUSED=true`
    set (operational kill switch) which would otherwise short-circuit every
    test before it could exercise the daily-check flow. The explicit
    `test_trading_paused_skips_cycle` test patches this back to True.
    """
    monkeypatch.setattr("daily_check.settings.TRADING_PAUSED", False)


def _seed_spy_history(close=400.0, sma_value=380.0, days=210):
    """Build a fake SPY OHLC frame whose 200-day SMA equals `sma_value` and
    today's close equals `close`."""
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    closes = np.full(days, sma_value, dtype=float)
    closes[-1] = close
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                       "Close": closes, "Volume": 1_000_000}, index=dates)
    return df


def _patch_all(yf_df, broker_overrides=None):
    """Patch yfinance + ibkr_broker + notifications.

    Returns ``(ExitStack, mocks_dict)`` — entering the stack starts every
    patcher and the dict gives test bodies named access to each mock without
    relying on positional `ctxs[i]` lookups (which return sentinel placeholders
    until the patcher has been entered).
    """
    broker_overrides = broker_overrides or {}
    patchers = {
        "yf_download": patch("daily_check.yf.download", return_value=yf_df),
        "connect_ibkr": patch("daily_check.connect_ibkr", return_value=MagicMock()),
        "get_position": patch(
            "daily_check.get_position",
            return_value=broker_overrides.get("get_position", 0),
        ),
        "get_account_value": patch(
            "daily_check.get_account_value",
            return_value=broker_overrides.get("get_account_value", 10000.0),
        ),
        "place_market_order": patch(
            "daily_check.place_market_order",
            return_value=broker_overrides.get(
                "place_market_order",
                {"order_id": "ORD-1", "fill_price": 50.0, "qty": 100,
                 "fill_time": "2026-05-07T13:30:01"},
            ),
        ),
        "liquidate": patch(
            "daily_check.liquidate",
            return_value=broker_overrides.get(
                "liquidate",
                {"order_id": "ORD-2", "fill_price": 49.0, "qty": 100,
                 "fill_time": "2026-05-07T13:30:01"},
            ),
        ),
        "notify_regime_flip": patch("daily_check.notify_regime_flip"),
        "notify_state_desync": patch("daily_check.notify_state_desync"),
        "notify_tws_disconnected": patch("daily_check.notify_tws_disconnected"),
        "notify_trade_failed": patch("daily_check.notify_trade_failed"),
    }
    stack = contextlib.ExitStack()
    return stack, patchers


def _enter(stack, patchers):
    """Enter every patcher inside the stack; return the dict of started mocks."""
    return {name: stack.enter_context(p) for name, p in patchers.items()}


def test_bullish_first_run_buys(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    yf_df = _seed_spy_history(close=400.0, sma_value=380.0)
    stack, patchers = _patch_all(yf_df)
    with stack:
        _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    trade = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    assert state["target_state"] == "LONG"
    assert state["current_state"] == "LONG"
    assert trade["reason"] == "regime_flip_long"
    assert audit["script_name"] == "daily_check"
    assert audit["outcome"] == "success"


def test_bearish_with_position_sells(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    # Seed DB with current_state=LONG
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=370.0, sma_value=400.0)
    stack, patchers = _patch_all(yf_df, broker_overrides={"get_position": 100})
    with stack:
        _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trade = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    assert trade["reason"] == "regime_flip_cash"
    assert state["current_state"] == "CASH"


def test_no_change_no_trade(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=410.0, sma_value=380.0)  # still bullish
    stack, patchers = _patch_all(yf_df, broker_overrides={"get_position": 100})
    with stack:
        mocks = _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0
        mocks["place_market_order"].assert_not_called()  # no order
        mocks["liquidate"].assert_not_called()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
    conn.close()
    assert trades["n"] == 0


def test_state_desync_auto_reconciles(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    # DB says LONG, broker says zero position
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=410.0, sma_value=380.0)  # bullish
    stack, patchers = _patch_all(
        yf_df, broker_overrides={"get_position": 0}
    )  # broker: no position
    with stack:
        mocks = _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0
        mocks["notify_state_desync"].assert_called_once()  # desync notification fired

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    # After reconcile, DB will buy back to LONG since regime is bullish
    assert state["current_state"] == "LONG"


def test_tws_connection_failure_aborts_cycle(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    yf_df = _seed_spy_history(close=400.0, sma_value=380.0)
    from tools.ibkr_broker import IBKRConnectionError
    with patch("daily_check.yf.download", return_value=yf_df), \
         patch("daily_check.connect_ibkr", side_effect=IBKRConnectionError("no TWS")), \
         patch("daily_check.notify_tws_disconnected") as notify_mock:
        from daily_check import main
        rc = main()
        assert rc == 1  # non-zero exit
        notify_mock.assert_called_once()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"].startswith("error:")


def test_stale_data_skips(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    # Build a frame whose last bar is 2 days old
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=2), periods=210)
    closes = np.full(210, 380.0)
    yf_df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                          "Close": closes, "Volume": 1_000_000}, index=dates)

    with patch("daily_check.yf.download", return_value=yf_df), \
         patch("daily_check.connect_ibkr", return_value=MagicMock()), \
         patch("daily_check.place_market_order") as place_mock:
        from daily_check import main
        rc = main()
        assert rc == 0  # not an error, but no trade
        place_mock.assert_not_called()

    # Review #5: assert the audit row records the stale-data skip with a
    # finished_at timestamp — without this the test would pass even if
    # daily_check returned 0 without writing anything to audit_log.
    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"] == "skipped:stale_data"
    assert audit["finished_at"] is not None


# ---------------------------------------------------------------------------
# Dry-run mode tests (extension to base spec)
# ---------------------------------------------------------------------------


def test_dry_run_bullish_no_order_no_trade_row(tmp_path, monkeypatch):
    """Settings-driven dry-run: bullish regime with no position should NOT
    call place_market_order, NOT write a trades row, mark audit_log
    outcome='dry_run:would_flip_long', NOT advance current_state, and call
    notify_regime_flip with dry_run=True.
    """
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setattr("daily_check.settings.DAILY_CHECK_DRY_RUN", True)

    yf_df = _seed_spy_history(close=400.0, sma_value=380.0)
    stack, patchers = _patch_all(yf_df)
    with stack:
        mocks = _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0
        mocks["place_market_order"].assert_not_called()
        mocks["notify_regime_flip"].assert_called_once()
        # dry_run=True kwarg passed through
        assert mocks["notify_regime_flip"].call_args.kwargs.get("dry_run") is True

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert trades["n"] == 0
    # current_state stays at CASH (not advanced to LONG even though target=LONG)
    assert state["target_state"] == "LONG"
    assert state["current_state"] == "CASH"
    assert audit["outcome"].startswith("dry_run:")
    assert "would_flip_long" in audit["outcome"]


def test_dry_run_bearish_no_liquidate_no_trade_row(tmp_path, monkeypatch):
    """Settings-driven dry-run: bearish regime with 100-share position should
    NOT call liquidate, NOT write a trades row, current_state stays at LONG,
    audit outcome starts with 'dry_run:'. Also asserts the bearish CASH-flip
    notify_regime_flip carries a non-zero fill_price (review minor #2)."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setattr("daily_check.settings.DAILY_CHECK_DRY_RUN", True)

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=370.0, sma_value=400.0)
    stack, patchers = _patch_all(yf_df, broker_overrides={"get_position": 100})
    with stack:
        mocks = _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0
        mocks["liquidate"].assert_not_called()
        mocks["notify_regime_flip"].assert_called_once()
        kwargs = mocks["notify_regime_flip"].call_args.kwargs
        assert kwargs.get("dry_run") is True
        # Minor #2: dry-run CASH flip must carry a meaningful fill_price (the
        # most recent close), not 0.0, so the operator alert is informative.
        assert kwargs.get("fill_price") > 0.0

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert trades["n"] == 0
    assert state["current_state"] == "LONG"  # NOT advanced to CASH
    assert audit["outcome"].startswith("dry_run:")
    assert "would_flip_cash" in audit["outcome"]


def test_dry_run_cli_flag_overrides_env(tmp_path, monkeypatch):
    """CLI --dry-run takes precedence over settings.DAILY_CHECK_DRY_RUN=False."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setattr("daily_check.settings.DAILY_CHECK_DRY_RUN", False)

    yf_df = _seed_spy_history(close=400.0, sma_value=380.0)
    stack, patchers = _patch_all(yf_df)
    with stack:
        mocks = _enter(stack, patchers)
        from daily_check import main
        rc = main(["--dry-run"])
        assert rc == 0
        mocks["place_market_order"].assert_not_called()  # CLI flag wins

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"].startswith("dry_run:")


def test_dry_run_no_change_audit_outcome(tmp_path, monkeypatch):
    """Settings-driven dry-run, regime stays bullish, position already LONG.
    Audit outcome must be 'dry_run:no_change' (no flip would occur)."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setattr("daily_check.settings.DAILY_CHECK_DRY_RUN", True)

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=410.0, sma_value=380.0)
    stack, patchers = _patch_all(yf_df, broker_overrides={"get_position": 100})
    with stack:
        _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 0

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"] == "dry_run:no_change"


# ---------------------------------------------------------------------------
# Pass-2 review fixes (Important #1, #2, #4)
# ---------------------------------------------------------------------------


def test_trading_paused_skips_cycle(tmp_path, monkeypatch):
    """Important #1: TRADING_PAUSED must short-circuit the entire pipeline
    BEFORE yfinance/IBKR/notifications. Without this, panic --pause becomes a
    no-op once #200 retires `main.py scan` (the only other honourer)."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setattr("daily_check.settings.TRADING_PAUSED", True)

    # If the early-exit works, none of these mocks should be called. We patch
    # them anyway so a failure manifests as an `assert_not_called` rather than
    # an unmocked-broker `BrokerCallBlockedError` from the conftest guard.
    with patch("daily_check.yf.download") as yf_mock, \
         patch("daily_check.connect_ibkr") as connect_mock, \
         patch("daily_check.place_market_order") as place_mock, \
         patch("daily_check.liquidate") as liq_mock:
        from daily_check import main
        rc = main()
        assert rc == 0
        yf_mock.assert_not_called()
        connect_mock.assert_not_called()
        place_mock.assert_not_called()
        liq_mock.assert_not_called()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
    state = conn.execute("SELECT COUNT(*) AS n FROM regime_state").fetchone()
    conn.close()
    assert audit["script_name"] == "daily_check"
    assert audit["outcome"] == "skipped:trading_paused"
    assert audit["finished_at"] is not None
    assert trades["n"] == 0
    assert state["n"] == 0  # no regime_state row written either


def test_bearish_liquidate_returns_none_aborts(tmp_path, monkeypatch):
    """Important #2: liquidate() returning None must NOT silently advance
    current_state to CASH — the broker still holds the position and tomorrow's
    idempotency check would lie about it. Expect rc=1, notify_trade_failed
    fired with reason='liquidate_returned_none', audit outcome
    'error:liquidate_failed', current_state pinned at 'LONG'.
    """
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=370.0, sma_value=400.0)
    # liquidate returns None — broker rejected / no fill
    stack, patchers = _patch_all(
        yf_df,
        broker_overrides={"get_position": 100, "liquidate": None},
    )
    with stack:
        mocks = _enter(stack, patchers)
        from daily_check import main
        rc = main()
        assert rc == 1
        mocks["liquidate"].assert_called_once()
        # No regime-flip alert (we didn't successfully flip)
        mocks["notify_regime_flip"].assert_not_called()
        # Trade-failed alert fired with the right reason
        mocks["notify_trade_failed"].assert_called_once()
        kwargs = mocks["notify_trade_failed"].call_args.kwargs
        assert kwargs["reason"] == "liquidate_returned_none"
        assert kwargs["side"] == "SELL"
        assert kwargs["qty"] == 100  # broker-truth qty was 100

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    assert trades["n"] == 0
    assert audit["outcome"].startswith("error:liquidate")
    # current_state pinned at LONG — NOT silently advanced to CASH (the bug).
    # The seeded row from before the run should still be the latest.
    assert state["current_state"] == "LONG"


def test_unexpected_exception_writes_error_audit(tmp_path, monkeypatch):
    """Important #4: the outer try/except must catch any uncaught exception,
    write `error:<ExceptionName>` to audit_log with finished_at set, and put
    a traceback excerpt in notes. yfinance.download blowing up is a realistic
    failure mode (network blip, schema change) that wasn't covered before."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    with patch("daily_check.yf.download", side_effect=RuntimeError("network down")):
        from daily_check import main
        rc = main()
        assert rc == 1

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"] == "error:RuntimeError"
    assert audit["finished_at"] is not None
    assert audit["notes"] is not None
    # Notes should hold a (truncated) traceback; the head of the trace is
    # always the literal "Traceback (most recent call last):" string.
    assert "Traceback" in audit["notes"]
    # And must be capped at 500 chars (per `tb[:500]` in daily_check.py).
    assert len(audit["notes"]) <= 500
