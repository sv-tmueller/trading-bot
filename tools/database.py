from __future__ import annotations

import sqlite3
from datetime import date, timedelta


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


def insert_signal(conn: sqlite3.Connection, signal: dict) -> int:
    """Persist one row to signals for the per-scan indicator audit trail (issue #136).

    Required keys: ticker, date, triggered_entry. Optional keys (passed as None
    when the upstream agent didn't surface them): trade_id, ema_fast, ema_slow,
    rsi, volume_ratio, signal_score. Returns lastrowid for symmetry with the
    other dict-in INSERT helpers (insert_trade, insert_monitor_action).
    """
    payload = {
        "trade_id": signal.get("trade_id"),
        "ticker": signal["ticker"],
        "date": signal["date"],
        "ema_fast": signal.get("ema_fast"),
        "ema_slow": signal.get("ema_slow"),
        "rsi": signal.get("rsi"),
        "volume_ratio": signal.get("volume_ratio"),
        "signal_score": signal.get("signal_score"),
        "triggered_entry": signal["triggered_entry"],
    }
    cur = conn.execute(
        """INSERT INTO signals
               (trade_id, ticker, date, ema_fast, ema_slow, rsi, volume_ratio, signal_score, triggered_entry)
           VALUES
               (:trade_id, :ticker, :date, :ema_fast, :ema_slow, :rsi, :volume_ratio, :signal_score, :triggered_entry)""",
        payload,
    )
    conn.commit()
    return cur.lastrowid


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


def insert_monitor_action(conn: sqlite3.Connection, action: dict) -> int:
    """Persist one row to monitor_actions for the per-trade audit trail (issue #131).

    Required keys: trade_id, ticker, action_time (ISO8601 UTC), action_type
    (one of 'stop_loss', 'take_profit', 'max_hold', 'reconciled', 'hold',
    'skipped_error'). Optional keys: reason, current_price, stop_price,
    take_profit_price — passed as None when not available so the row stays
    self-describing.
    """
    payload = {
        "trade_id": action["trade_id"],
        "ticker": action["ticker"],
        "action_time": action["action_time"],
        "action_type": action["action_type"],
        "reason": action.get("reason"),
        "current_price": action.get("current_price"),
        "stop_price": action.get("stop_price"),
        "take_profit_price": action.get("take_profit_price"),
    }
    cur = conn.execute(
        """INSERT INTO monitor_actions
               (trade_id, ticker, action_time, action_type, reason,
                current_price, stop_price, take_profit_price)
           VALUES
               (:trade_id, :ticker, :action_time, :action_type, :reason,
                :current_price, :stop_price, :take_profit_price)""",
        payload,
    )
    conn.commit()
    return cur.lastrowid


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


def get_closed_trade_stats(conn: sqlite3.Connection, days: int = 30) -> dict:
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT pnl_dollars, r_multiple
           FROM trades
           WHERE exit_date IS NOT NULL AND exit_date >= ?""",
        (since,),
    ).fetchall()
    trade_count = len(rows)
    if trade_count == 0:
        return {
            "days": days,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "total_pnl_dollars": 0.0,
            "avg_r_multiple": 0.0,
        }
    win_count = sum(1 for r in rows if r["pnl_dollars"] is not None and r["pnl_dollars"] > 0)
    loss_count = trade_count - win_count
    total_pnl = sum(r["pnl_dollars"] or 0.0 for r in rows)
    r_multiples = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0
    return {
        "days": days,
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_count / trade_count,
        "total_pnl_dollars": total_pnl,
        "avg_r_multiple": avg_r,
    }
