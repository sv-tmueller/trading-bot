from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_conn():
    schema = (Path(__file__).parent.parent / "storage" / "schema.sql").read_text()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    conn.commit()
    yield conn
    conn.close()
