from __future__ import annotations

import sqlite3


def insert_trade(conn: sqlite3.Connection, trade: dict) -> int:
    cur = conn.execute(
        """INSERT INTO trades (ticker, entry_date, entry_price, shares, stop_loss, take_profit)
           VALUES (:ticker, :entry_date, :entry_price, :shares, :stop_loss, :take_profit)""",
        trade,
    )
    conn.commit()
    return cur.lastrowid


def get_open_trades(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT * FROM trades WHERE exit_date IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def close_trade(conn: sqlite3.Connection, trade_id: int, close_data: dict) -> None:
    conn.execute(
        """UPDATE trades SET
               exit_date = :exit_date,
               exit_price = :exit_price,
               exit_reason = :exit_reason,
               pnl_dollars = :pnl_dollars,
               pnl_pct = :pnl_pct,
               hold_days = :hold_days,
               r_multiple = :r_multiple
           WHERE id = :id""",
        {**close_data, "id": trade_id},
    )
    conn.commit()


def insert_signal(conn: sqlite3.Connection, signal: dict) -> None:
    conn.execute(
        """INSERT INTO signals
               (trade_id, ticker, date, ema_fast, ema_slow, rsi, volume_ratio, signal_score, triggered_entry)
           VALUES
               (:trade_id, :ticker, :date, :ema_fast, :ema_slow, :rsi, :volume_ratio, :signal_score, :triggered_entry)""",
        signal,
    )
    conn.commit()


def log_agent_output(conn: sqlite3.Connection, log: dict) -> None:
    conn.execute(
        """INSERT INTO agent_logs
               (cycle_date, agent_name, input_summary, output_summary, full_reasoning,
                tokens_used, input_tokens, output_tokens)
           VALUES
               (:cycle_date, :agent_name, :input_summary, :output_summary, :full_reasoning,
                :tokens_used, :input_tokens, :output_tokens)""",
        log,
    )
    conn.commit()


def get_daily_token_costs(conn: sqlite3.Connection, cycle_date: str) -> dict:
    row = conn.execute(
        """SELECT
               SUM(input_tokens)  AS total_input,
               SUM(output_tokens) AS total_output,
               SUM(tokens_used)   AS total_tokens
           FROM agent_logs
           WHERE cycle_date = ?""",
        (cycle_date,),
    ).fetchone()
    total_input = row["total_input"] or 0
    total_output = row["total_output"] or 0
    total_tokens = row["total_tokens"] or 0
    # claude-sonnet-4-6: $3.00 / 1M input, $15.00 / 1M output
    cost_usd = (total_input / 1_000_000 * 3.0) + (total_output / 1_000_000 * 15.0)
    return {
        "date": cycle_date,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_tokens,
        "cost_usd": round(cost_usd, 6),
    }


def insert_parameters(conn: sqlite3.Connection, params: dict) -> None:
    conn.execute(
        """INSERT INTO parameters
               (applied_date, rsi_lower, rsi_upper, ema_fast, ema_slow,
                volume_multiplier, risk_pct, max_positions, r_ratio_min)
           VALUES
               (:applied_date, :rsi_lower, :rsi_upper, :ema_fast, :ema_slow,
                :volume_multiplier, :risk_pct, :max_positions, :r_ratio_min)""",
        params,
    )
    conn.commit()


def get_active_parameters(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT * FROM parameters ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else {}
