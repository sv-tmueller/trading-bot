from __future__ import annotations

import pytest
import sqlite3
from tools.database import (
    insert_trade,
    get_open_trades,
    close_trade,
    insert_signal,
    log_agent_output,
    get_active_parameters,
    insert_parameters,
    get_daily_token_costs,
    get_closed_trade_stats,
    insert_monitor_action,
)


def test_insert_and_retrieve_open_trade(db_conn):
    trade_id = insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    open_trades = get_open_trades(db_conn)
    assert len(open_trades) == 1
    assert open_trades[0]["ticker"] == "AMD"
    assert open_trades[0]["id"] == trade_id


def test_close_trade(db_conn):
    trade_id = insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    close_trade(db_conn, trade_id, {
        "exit_date": "2026-04-24",
        "exit_price": 159.0,
        "exit_reason": "take_profit",
        "pnl_dollars": 900.0,
        "pnl_pct": 0.06,
        "hold_days": 2,
        "r_multiple": 2.0,
    })
    open_trades = get_open_trades(db_conn)
    assert len(open_trades) == 0


def test_log_agent_output(db_conn):
    log_agent_output(db_conn, {
        "cycle_date": "2026-04-22",
        "agent_name": "market_intelligence",
        "input_summary": "watchlist scan",
        "output_summary": "3 candidates found",
        "full_reasoning": "...",
        "tokens_used": 1200,
        "input_tokens": 900,
        "output_tokens": 300,
    })
    rows = db_conn.execute("SELECT * FROM agent_logs").fetchall()
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "market_intelligence"
    assert rows[0]["input_tokens"] == 900
    assert rows[0]["output_tokens"] == 300


def test_get_daily_token_costs(db_conn):
    log_agent_output(db_conn, {
        "cycle_date": "2026-04-22",
        "agent_name": "strategy",
        "input_summary": "scan",
        "output_summary": "candidates",
        "full_reasoning": "...",
        "tokens_used": 1400,
        "input_tokens": 1000,
        "output_tokens": 400,
    })
    costs = get_daily_token_costs(db_conn, "2026-04-22")
    assert costs["input_tokens"] == 1000
    assert costs["output_tokens"] == 400
    assert costs["total_tokens"] == 1400
    # 1000/1M * $3 + 400/1M * $15 = $0.003 + $0.006 = $0.009
    assert costs["cost_usd"] == pytest.approx(0.009, rel=1e-3)


def test_get_closed_trade_stats_no_trades(db_conn):
    stats = get_closed_trade_stats(db_conn, days=30)
    assert stats["trade_count"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["total_pnl_dollars"] == 0.0
    assert stats["avg_r_multiple"] == 0.0
    assert stats["days"] == 30


def test_get_closed_trade_stats_with_wins_and_losses(db_conn):
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=5)).isoformat()
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("AMD", "2026-04-01", recent, 150.0, 160.0, 10, 145.0, 165.0, "take_profit", 100.0, 0.067, 9, 2.0),
    )
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("NVDA", "2026-04-01", recent, 200.0, 190.0, 5, 195.0, 210.0, "stop_loss", -50.0, -0.025, 4, -1.0),
    )
    db_conn.commit()
    stats = get_closed_trade_stats(db_conn, days=30)
    assert stats["trade_count"] == 2
    assert stats["win_count"] == 1
    assert stats["loss_count"] == 1
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["total_pnl_dollars"] == pytest.approx(50.0)
    assert stats["avg_r_multiple"] == pytest.approx(0.5)


def test_get_closed_trade_stats_filters_old_trades(db_conn):
    from datetime import date, timedelta
    old = (date.today() - timedelta(days=60)).isoformat()
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("AMD", "2026-02-01", old, 150.0, 160.0, 10, 145.0, 165.0, "take_profit", 100.0, 0.067, 9, 2.0),
    )
    db_conn.commit()
    stats = get_closed_trade_stats(db_conn, days=30)
    assert stats["trade_count"] == 0


def test_insert_signal_full_row_round_trip(db_conn):
    """Issue #136: a fully-populated signal row round-trips and lastrowid is returned."""
    trade_id = insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-05-05",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.0,
        "take_profit": 160.0,
    })
    row_id = insert_signal(db_conn, {
        "trade_id": trade_id,
        "ticker": "AMD",
        "date": "2026-05-05",
        "ema_fast": 152.3,
        "ema_slow": 148.1,
        "rsi": 55.0,
        "volume_ratio": 1.8,
        "signal_score": 0.85,
        "triggered_entry": 1,
    })
    assert isinstance(row_id, int) and row_id > 0
    row = db_conn.execute("SELECT * FROM signals WHERE id = ?", (row_id,)).fetchone()
    assert row["trade_id"] == trade_id
    assert row["ticker"] == "AMD"
    assert row["date"] == "2026-05-05"
    assert row["ema_fast"] == pytest.approx(152.3)
    assert row["ema_slow"] == pytest.approx(148.1)
    assert row["rsi"] == pytest.approx(55.0)
    assert row["volume_ratio"] == pytest.approx(1.8)
    assert row["signal_score"] == pytest.approx(0.85)
    assert row["triggered_entry"] == 1


def test_insert_signal_rejection_row_with_null_trade_id(db_conn):
    """Issue #136: a rejected candidate writes triggered_entry=0 with trade_id=NULL."""
    row_id = insert_signal(db_conn, {
        "trade_id": None,
        "ticker": "SHEL",
        "date": "2026-05-05",
        "rsi": 48.2,
        "volume_ratio": 1.6,
        "signal_score": 0.62,
        "triggered_entry": 0,
    })
    row = db_conn.execute("SELECT * FROM signals WHERE id = ?", (row_id,)).fetchone()
    assert row["trade_id"] is None
    assert row["ticker"] == "SHEL"
    assert row["triggered_entry"] == 0
    # ema_fast/ema_slow are optional — caller didn't supply them, so they are NULL.
    assert row["ema_fast"] is None
    assert row["ema_slow"] is None
    assert row["rsi"] == pytest.approx(48.2)


def test_insert_signal_returns_lastrowid_for_symmetry(db_conn):
    """Issue #136: insert_signal returns lastrowid (matches insert_trade / insert_monitor_action)."""
    row_id_1 = insert_signal(db_conn, {
        "ticker": "AMD",
        "date": "2026-05-05",
        "triggered_entry": 0,
    })
    row_id_2 = insert_signal(db_conn, {
        "ticker": "NVDA",
        "date": "2026-05-05",
        "triggered_entry": 0,
    })
    assert isinstance(row_id_1, int)
    assert isinstance(row_id_2, int)
    assert row_id_2 == row_id_1 + 1


def test_insert_and_get_parameters(db_conn):
    insert_parameters(db_conn, {
        "applied_date": "2026-04-22",
        "rsi_lower": 40.0,
        "rsi_upper": 60.0,
        "ema_fast": 20,
        "ema_slow": 50,
        "volume_multiplier": 1.5,
        "risk_pct": 0.01,
        "max_positions": 5,
        "r_ratio_min": 2.0,
    })
    params = get_active_parameters(db_conn)
    assert params["rsi_lower"] == 40.0
    assert params["ema_fast"] == 20


# --- insert_monitor_action helper tests (issue #131) ---


def _seed_open_trade(conn) -> int:
    return insert_trade(conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })


def test_insert_monitor_action_persists_full_row(db_conn):
    """Every documented column round-trips through insert_monitor_action."""
    trade_id = _seed_open_trade(db_conn)
    new_id = insert_monitor_action(db_conn, {
        "trade_id": trade_id,
        "ticker": "AMD",
        "action_time": "2026-04-22T14:00:00+00:00",
        "action_type": "stop_loss",
        "reason": "stop_loss",
        "current_price": 144.9,
        "stop_price": 145.5,
        "take_profit_price": 159.0,
    })
    assert isinstance(new_id, int) and new_id > 0

    row = db_conn.execute(
        "SELECT * FROM monitor_actions WHERE id = ?", (new_id,)
    ).fetchone()
    assert row["trade_id"] == trade_id
    assert row["ticker"] == "AMD"
    assert row["action_time"] == "2026-04-22T14:00:00+00:00"
    assert row["action_type"] == "stop_loss"
    assert row["reason"] == "stop_loss"
    assert row["current_price"] == 144.9
    assert row["stop_price"] == 145.5
    assert row["take_profit_price"] == 159.0


def test_insert_monitor_action_optional_fields_default_to_null(db_conn):
    """Optional keys (reason, prices) are persisted as NULL when not provided."""
    trade_id = _seed_open_trade(db_conn)
    insert_monitor_action(db_conn, {
        "trade_id": trade_id,
        "ticker": "AMD",
        "action_time": "2026-04-22T15:00:00+00:00",
        "action_type": "hold",
    })
    row = db_conn.execute(
        "SELECT reason, current_price, stop_price, take_profit_price FROM monitor_actions"
    ).fetchone()
    assert row["reason"] is None
    assert row["current_price"] is None
    assert row["stop_price"] is None
    assert row["take_profit_price"] is None


def test_insert_monitor_action_rejects_unknown_action_type(db_conn):
    """The CHECK constraint blocks action_type values outside the documented enum."""
    trade_id = _seed_open_trade(db_conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_monitor_action(db_conn, {
            "trade_id": trade_id,
            "ticker": "AMD",
            "action_time": "2026-04-22T16:00:00+00:00",
            "action_type": "panic",   # not in the enum
        })


def test_insert_monitor_action_accepts_every_enum_value(db_conn):
    """Every documented action_type round-trips without an IntegrityError."""
    trade_id = _seed_open_trade(db_conn)
    for at in ("stop_loss", "take_profit", "max_hold", "reconciled", "hold", "skipped_error"):
        insert_monitor_action(db_conn, {
            "trade_id": trade_id,
            "ticker": "AMD",
            "action_time": f"2026-04-22T17:00:00+00:00#{at}",
            "action_type": at,
        })
    rows = db_conn.execute(
        "SELECT action_type FROM monitor_actions ORDER BY id"
    ).fetchall()
    assert {r["action_type"] for r in rows} == {
        "stop_loss", "take_profit", "max_hold", "reconciled", "hold", "skipped_error"
    }
