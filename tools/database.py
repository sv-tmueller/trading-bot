"""Database helpers for the rules-engine bot.

Post-2026-05-07 pivot: only the four tables ``regime_state``, ``trades``
(simplified), and ``audit_log`` are written. Helpers for the legacy
``signals`` / ``monitor_actions`` / ``daily_stats`` / ``parameters`` /
``agent_logs`` tables were removed in #200 — those tables no longer
exist in ``storage/schema.sql`` and the migration in
``storage/init_db.py`` drops them on first run.

All writes use named parameters (``:key``) and an explicit ``conn.commit()``
before returning so callers don't need to manage transactions.
"""
from __future__ import annotations


def upsert_regime_state(
    conn,
    *,
    date: str,
    spy_close: float,
    spy_sma200: float,
    target_state: str,
    current_state: str,
    position_drawdown_pct: float | None,
    kill_switch_active: bool,
    kill_switch_fired_at: str | None,
) -> None:
    """Insert or replace today's ``regime_state`` row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO regime_state
            (date, spy_close, spy_sma200, target_state, current_state,
             position_drawdown_pct, kill_switch_active, kill_switch_fired_at)
        VALUES
            (:date, :spy_close, :spy_sma200, :target_state, :current_state,
             :position_drawdown_pct, :kill_switch_active, :kill_switch_fired_at)
        """,
        dict(
            date=date,
            spy_close=spy_close,
            spy_sma200=spy_sma200,
            target_state=target_state,
            current_state=current_state,
            position_drawdown_pct=position_drawdown_pct,
            kill_switch_active=1 if kill_switch_active else 0,
            kill_switch_fired_at=kill_switch_fired_at,
        ),
    )
    conn.commit()


def get_latest_regime_state(conn):
    """Return the most recent ``regime_state`` row as a dict, or ``None`` if empty."""
    row = conn.execute(
        "SELECT * FROM regime_state ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def insert_trade(
    conn,
    *,
    symbol: str,
    side: str,
    qty: int,
    fill_price: float,
    fill_time: str,
    ibkr_order_id: str,
    reason: str,
) -> int:
    """Insert a row into the post-pivot ``trades`` table; return rowid."""
    cur = conn.execute(
        """
        INSERT INTO trades (symbol, side, qty, fill_price, fill_time, ibkr_order_id, reason)
        VALUES (:symbol, :side, :qty, :fill_price, :fill_time, :ibkr_order_id, :reason)
        """,
        dict(
            symbol=symbol,
            side=side,
            qty=qty,
            fill_price=fill_price,
            fill_time=fill_time,
            ibkr_order_id=ibkr_order_id,
            reason=reason,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_audit_log(
    conn,
    *,
    script_name: str,
    started_at: str,
    finished_at: str | None = None,
    outcome: str | None = None,
    notes: str | None = None,
) -> int:
    """Insert an ``audit_log`` row; return rowid."""
    cur = conn.execute(
        """
        INSERT INTO audit_log (script_name, started_at, finished_at, outcome, notes)
        VALUES (:script_name, :started_at, :finished_at, :outcome, :notes)
        """,
        dict(
            script_name=script_name,
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome,
            notes=notes,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_audit_log(
    conn,
    *,
    rowid: int,
    finished_at: str,
    outcome: str,
    notes: str | None = None,
) -> None:
    """Update an existing ``audit_log`` row by id."""
    conn.execute(
        "UPDATE audit_log SET finished_at = :f, outcome = :o, notes = :n WHERE id = :id",
        dict(f=finished_at, o=outcome, n=notes, id=rowid),
    )
    conn.commit()
