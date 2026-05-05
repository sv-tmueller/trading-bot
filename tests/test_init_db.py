from __future__ import annotations

import sqlite3

from storage.init_db import get_connection, init_db


EXPECTED_TABLES = {
    "trades",
    "signals",
    "agent_logs",
    "daily_stats",
    "weekly_stats",
    "suggestions",
    "parameters",
    "monitor_actions",
}

EXPECTED_MONITOR_ACTIONS_COLUMNS = {
    "id",
    "trade_id",
    "ticker",
    "action_time",
    "action_type",
    "reason",
    "current_price",
    "stop_price",
    "take_profit_price",
}

EXPECTED_TRADES_COLUMNS = {
    "id",
    "ticker",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "shares",
    "stop_loss",
    "take_profit",
    "exit_reason",
    "pnl_dollars",
    "pnl_pct",
    "hold_days",
    "r_multiple",
    "trailing_high",
}


def _list_tables(conn: sqlite3.Connection) -> set[str]:
    """Return all user-defined table names."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r[0] for r in rows}


def _list_indexes(conn: sqlite3.Connection) -> set[str]:
    """Return all user-defined index names."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    return {r[0] for r in rows}


def test_fresh_init_creates_expected_tables(tmp_path):
    """Fresh init_db creates every documented table and key index."""
    db_path = tmp_path / "fresh.db"
    init_db(str(db_path))

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        tables = _list_tables(conn)
        assert EXPECTED_TABLES.issubset(tables), (
            f"Missing tables: {EXPECTED_TABLES - tables}"
        )
        indexes = _list_indexes(conn)
        assert "idx_trades_open" in indexes
    finally:
        conn.close()


def test_init_is_idempotent(tmp_path):
    """Calling init_db twice on the same path is safe and leaves tables unchanged."""
    db_path = tmp_path / "idem.db"
    init_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    try:
        first = _list_tables(conn)
    finally:
        conn.close()

    init_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    try:
        second = _list_tables(conn)
    finally:
        conn.close()

    assert first == second
    assert EXPECTED_TABLES.issubset(second)


def test_get_connection_enables_foreign_keys(tmp_path):
    """get_connection enables PRAGMA foreign_keys on each connection."""
    db_path = tmp_path / "fk.db"
    init_db(str(db_path))

    conn = get_connection(str(db_path))
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        conn.close()


def test_trades_table_columns_match_expectations(tmp_path):
    """trades table schema matches expected columns to guard against drift."""
    db_path = tmp_path / "schema.db"
    init_db(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA table_info(trades)").fetchall()
    finally:
        conn.close()

    cols = {row[1] for row in rows}
    assert cols == EXPECTED_TRADES_COLUMNS, (
        f"Schema drift on trades: missing={EXPECTED_TRADES_COLUMNS - cols} "
        f"extra={cols - EXPECTED_TRADES_COLUMNS}"
    )


def test_monitor_actions_table_columns_match_expectations(tmp_path):
    """monitor_actions table schema matches expected columns (issue #131)."""
    db_path = tmp_path / "schema.db"
    init_db(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA table_info(monitor_actions)").fetchall()
    finally:
        conn.close()

    cols = {row[1] for row in rows}
    assert cols == EXPECTED_MONITOR_ACTIONS_COLUMNS, (
        f"Schema drift on monitor_actions: "
        f"missing={EXPECTED_MONITOR_ACTIONS_COLUMNS - cols} "
        f"extra={cols - EXPECTED_MONITOR_ACTIONS_COLUMNS}"
    )


def test_monitor_actions_indexes_present(tmp_path):
    """monitor_actions has the trade_id and action_time indexes for analyst queries."""
    db_path = tmp_path / "idx.db"
    init_db(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        indexes = _list_indexes(conn)
    finally:
        conn.close()

    assert "idx_monitor_actions_trade_id" in indexes
    assert "idx_monitor_actions_action_time" in indexes
