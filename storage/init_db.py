from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db(db_path: str = str(DB_PATH)) -> None:
    schema = SCHEMA_PATH.read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")
