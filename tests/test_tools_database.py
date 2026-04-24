from __future__ import annotations

import pytest
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
