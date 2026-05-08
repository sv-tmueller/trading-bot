"""Tests for ``main.py`` mode dispatcher.

The ``scan`` and ``monitor`` modes were removed in the 2026-05-07 pivot
(#200) — they used to drive the LLM agent pipeline and the legacy hourly
position monitor, both of which are now deleted. The dispatcher returns 2
with a deprecation message so any leftover cron entry pointing at
``main.py scan`` exits cleanly instead of raising ImportError.

``panic`` mode tests live in ``tests/test_main_panic.py``. The
``backtest`` regime engine itself is covered by
``tests/test_backtest_regime.py``; the delegation from ``main.py backtest``
into ``backtest.regime.main_cli`` (including the ``sys.argv`` save/restore)
is covered below.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


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


def test_backtest_mode_delegates_and_restores_argv():
    """``main.py backtest`` must delegate to ``backtest.regime.main_cli`` and
    restore ``sys.argv`` to its pre-call value — the ``_run_backtest`` helper
    swaps ``sys.argv`` so the regime CLI's ``argparse`` sees the forwarded
    args, and any callers (or other tests in the same process) MUST see the
    original ``sys.argv`` after we return."""
    fake_main_cli = MagicMock()
    saved_argv_before = sys.argv  # capture the current list reference

    with patch("backtest.regime.main_cli", fake_main_cli):
        from main import main as run
        rc = run(["backtest", "--years", "1"])

    # 1. The CLI was invoked exactly once.
    fake_main_cli.assert_called_once_with()
    # 2. sys.argv was restored to the same list object we started with.
    #    `is` check (not just `==`) — restoration must put the original list
    #    back, not assign a copy. _run_backtest stores `saved_argv = sys.argv`
    #    and restores `sys.argv = saved_argv` in finally, so identity must hold.
    assert sys.argv is saved_argv_before
    # 3. _run_backtest returns 0 on success.
    assert rc == 0


def test_backtest_mode_restores_argv_on_exception():
    """If the regime CLI raises, ``_run_backtest``'s ``finally`` block must
    still restore ``sys.argv``. Without this, a backtest crash would leak the
    swapped argv into the rest of the process."""
    fake_main_cli = MagicMock(side_effect=RuntimeError("boom"))
    saved_argv_before = sys.argv

    with patch("backtest.regime.main_cli", fake_main_cli):
        from main import main as run
        try:
            run(["backtest", "--years", "1"])
        except RuntimeError:
            pass  # expected — we want to verify the finally fired

    assert sys.argv is saved_argv_before
