from __future__ import annotations

import sqlite3
from pathlib import Path

# Repo-root SQLite file (matches the live `trading_bot.db` referenced in
# `CLAUDE.md` commands). Kept as a module-level export so callers like
# `main.py` and operational scripts can import `DB_PATH` without hard-coding.
DB_PATH = Path(__file__).parent.parent / "trading_bot.db"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Return a connection with FK enforcement enabled and row_factory set."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = :name",
        {"name": name},
    )
    return cur.fetchone() is not None


def init_db(db_path: str | Path = DB_PATH) -> None:
    """Initialise (or migrate) the SQLite database in-place.

    - Fresh DB: apply ``schema.sql`` directly.
    - Existing DB with pre-pivot tables: apply migration to reshape, then run
      ``schema.sql`` to create the new tables.

    The migration is idempotent and forward-only: re-running ``init_db`` on
    an already-migrated DB is a no-op (the pre-pivot detection returns False
    and ``schema.sql`` uses ``CREATE TABLE IF NOT EXISTS``).
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        is_pre_pivot = _has_table(conn, "agent_logs") and not _has_table(conn, "audit_log")
        if is_pre_pivot:
            migration_sql = (MIGRATIONS_DIR / "2026_05_07_rules_engine_pivot.sql").read_text()
            conn.executescript(migration_sql)
        # Always run schema.sql — it's idempotent (CREATE TABLE IF NOT EXISTS).
        conn.executescript(SCHEMA_FILE.read_text())
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialised / migrated at {DB_PATH}")
