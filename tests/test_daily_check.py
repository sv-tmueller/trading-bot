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

from storage.init_db import init_db


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


# ---------------------------------------------------------------------------
# Dry-run mode tests (extension to base spec)
# ---------------------------------------------------------------------------


def test_dry_run_bullish_no_order_no_trade_row(tmp_path, monkeypatch):
    """Env-var dry-run: bullish regime with no position should NOT call
    place_market_order, NOT write a trades row, mark audit_log
    outcome='dry_run:would_flip_long', NOT advance current_state, and call
    notify_regime_flip with dry_run=True.
    """
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setenv("DAILY_CHECK_DRY_RUN", "true")

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
    """Env-var dry-run: bearish regime with 100-share position should NOT
    call liquidate, NOT write a trades row, current_state stays at LONG,
    audit outcome starts with 'dry_run:'."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setenv("DAILY_CHECK_DRY_RUN", "1")

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
        assert mocks["notify_regime_flip"].call_args.kwargs.get("dry_run") is True

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
    """CLI --dry-run takes precedence over DAILY_CHECK_DRY_RUN=false."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setenv("DAILY_CHECK_DRY_RUN", "false")

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
    """Env-var dry-run, regime stays bullish, position already LONG.
    Audit outcome must be 'dry_run:no_change' (no flip would occur)."""
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))
    monkeypatch.setenv("DAILY_CHECK_DRY_RUN", "yes")

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
