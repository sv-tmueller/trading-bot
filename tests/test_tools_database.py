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
