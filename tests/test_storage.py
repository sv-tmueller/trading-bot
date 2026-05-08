from __future__ import annotations

import sqlite3

import pytest

from storage.init_db import init_db
from tools.database import (
    get_latest_regime_state,
    insert_audit_log,
    insert_trade,
    update_audit_log,
    upsert_regime_state,
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


# --- init_db / migration tests --------------------------------------------


def test_init_db_fresh_creates_new_tables(tmp_path):
    db = tmp_path / "fresh.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    try:
        assert _table_exists(conn, "regime_state")
        assert _table_exists(conn, "trades")
        assert _table_exists(conn, "audit_log")
        assert not _table_exists(conn, "agent_logs")
        assert not _table_exists(conn, "signals")
    finally:
        conn.close()


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "idem.db"
    init_db(db)
    init_db(db)  # second run must not error
    conn = sqlite3.connect(str(db))
    try:
        assert _table_exists(conn, "regime_state")
    finally:
        conn.close()


def test_init_db_migrates_pre_pivot_db(tmp_path):
    """Pre-pivot DB gets old tables dropped; new schema recreated. Old data not preserved."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE agent_logs (id INTEGER PRIMARY KEY, agent_name TEXT, started_at TEXT,
                                  finished_at TEXT, outcome TEXT, notes TEXT,
                                  input_tokens INTEGER, output_tokens INTEGER);
        CREATE TABLE signals (id INTEGER PRIMARY KEY, ticker TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker TEXT, stop_loss REAL);
        INSERT INTO agent_logs (agent_name, started_at, outcome) VALUES ('strategy', '2026-04-01', 'success');
    """)
    conn.commit()
    conn.close()

    init_db(db)

    conn = sqlite3.connect(str(db))
    try:
        # Old tables gone, new tables present
        assert not _table_exists(conn, "agent_logs")
        assert not _table_exists(conn, "signals")
        assert _table_exists(conn, "audit_log")
        assert _table_exists(conn, "regime_state")
        # New trades table is empty (old data intentionally dropped)
        n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert n == 0
        # New audit_log is also empty
        n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert n == 0
    finally:
        conn.close()


def test_regime_state_check_constraint(tmp_path):
    db = tmp_path / "ck.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, current_state) "
                "VALUES ('2026-05-07', 400, 380, 'INVALID', 'CASH')"
            )
    finally:
        conn.close()


def test_trades_check_constraint(tmp_path):
    db = tmp_path / "ck2.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trades (symbol, side, qty, fill_price, fill_time, ibkr_order_id, reason) "
                "VALUES ('WSPL.DE', 'BUY', 100, 50.0, '2026-05-07', 'O1', 'invalid_reason')"
            )
    finally:
        conn.close()


# --- helper-function tests ------------------------------------------------


def _conn(tmp_path) -> sqlite3.Connection:
    init_db(tmp_path / "h.db")
    conn = sqlite3.connect(str(tmp_path / "h.db"))
    conn.row_factory = sqlite3.Row
    return conn


def test_upsert_regime_state_inserts(tmp_path):
    conn = _conn(tmp_path)
    upsert_regime_state(
        conn,
        date="2026-05-07",
        spy_close=400.0,
        spy_sma200=380.0,
        target_state="LONG",
        current_state="CASH",
        position_drawdown_pct=None,
        kill_switch_active=False,
        kill_switch_fired_at=None,
    )
    state = get_latest_regime_state(conn)
    assert state["target_state"] == "LONG"
    assert state["kill_switch_active"] == 0


def test_upsert_regime_state_replaces_same_date(tmp_path):
    conn = _conn(tmp_path)
    for ts in ("CASH", "LONG"):
        upsert_regime_state(
            conn,
            date="2026-05-07",
            spy_close=400.0,
            spy_sma200=380.0,
            target_state=ts,
            current_state="CASH",
            position_drawdown_pct=None,
            kill_switch_active=False,
            kill_switch_fired_at=None,
        )
    state = get_latest_regime_state(conn)
    assert state["target_state"] == "LONG"  # last write wins
    n = conn.execute("SELECT COUNT(*) FROM regime_state").fetchone()[0]
    assert n == 1


def test_insert_trade(tmp_path):
    conn = _conn(tmp_path)
    rowid = insert_trade(
        conn,
        symbol="WSPL.DE",
        side="BUY",
        qty=100,
        fill_price=50.0,
        fill_time="2026-05-07T13:30:01",
        ibkr_order_id="ORD-1",
        reason="regime_flip_long",
    )
    assert rowid == 1


def test_audit_log_lifecycle(tmp_path):
    conn = _conn(tmp_path)
    rowid = insert_audit_log(
        conn,
        script_name="daily_check",
        started_at="2026-05-07T22:30:00",
    )
    update_audit_log(
        conn,
        rowid=rowid,
        finished_at="2026-05-07T22:30:05",
        outcome="success",
    )
    row = conn.execute(
        "SELECT outcome FROM audit_log WHERE id=?", (rowid,)
    ).fetchone()
    assert row["outcome"] == "success"
