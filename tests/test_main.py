"""Tests for ``main.py`` mode dispatcher.

The ``scan`` and ``monitor`` modes were removed in the 2026-05-07 pivot
(#200) — they used to drive the LLM agent pipeline and the legacy hourly
position monitor, both of which are now deleted. The dispatcher returns 2
with a deprecation message so any leftover cron entry pointing at
``main.py scan`` exits cleanly instead of raising ImportError.

``panic`` mode tests live in ``tests/test_main_panic.py``. ``backtest`` is
covered by ``tests/test_backtest_regime.py``.
"""
from __future__ import annotations

import sys
from unittest.mock import patch


def test_scan_mode_returns_deprecated(capsys):
    """`main.py scan` must exit 2 with a deprecation message — never reach an
    agent pipeline (which no longer exists)."""
    from main import main as run
    rc = run(["scan"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "removed" in out


def test_monitor_mode_returns_deprecated(capsys):
    """`main.py monitor` must exit 2 with a deprecation message that points
    at the new kill-switch entry point."""
    from main import main as run
    rc = run(["monitor"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "removed" in out
    assert "kill_switch" in out


def test_unknown_mode_returns_2(capsys):
    """Unknown modes get a usage hint (no crash, no panic, no scan)."""
    from main import main as run
    rc = run(["this-is-not-a-mode"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "Unknown mode" in out


def test_no_mode_returns_usage(capsys):
    """No args at all prints usage and exits 2."""
    from main import main as run
    rc = run([])
    assert rc == 2
    out = capsys.readouterr().out
    assert "Usage" in out


def test_summary_mode_runs_via_simplified_query(capsys, db_conn, tmp_path, monkeypatch):
    """`main.py summary` must execute the trade-stat query and exit 0 — no
    LLM, no token costs (those columns were dropped with the agent pipeline)."""
    # Insert a few post-pivot trades so the query sees something to count.
    from tools.database import insert_trade
    insert_trade(
        db_conn, symbol="WSPL.DE", side="BUY", qty=10, fill_price=100.0,
        fill_time="2026-05-08T12:00:00", ibkr_order_id="X1", reason="regime_flip_long",
    )
    insert_trade(
        db_conn, symbol="WSPL.DE", side="SELL", qty=10, fill_price=110.0,
        fill_time="2026-05-08T13:00:00", ibkr_order_id="X2", reason="kill_switch",
    )

    with patch("main.get_db", return_value=db_conn):
        from main import main as run
        rc = run(["summary"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Trailing 30d" in out
    assert "2 trades" in out
    assert "1 kill-switch" in out
