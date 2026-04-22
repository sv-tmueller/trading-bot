from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: str = str(DB_PATH)) -> sqlite3.Connection:
    """Return a connection with FK enforcement enabled and row_factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = str(DB_PATH)) -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
    schema = SCHEMA_PATH.read_text()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")
