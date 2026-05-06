from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _block_live_broker_in_tests(monkeypatch):
    """Mechanical safety guard for the entire test suite (issue #168).

    Sets `CLAUDE_AGENT_NO_BROKER=1` for every test so any forgotten mock in a
    broker-touching test now raises `BrokerCallBlockedError` before reaching
    live Alpaca, instead of submitting a real paper-account order.

    Tests that intentionally exercise the guard-OFF path (i.e. the regression
    suite for the guard itself in `test_broker_guard.py`) call
    `monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)` inside the
    test body to opt out — autouse + monkeypatch is per-test, so the opt-out
    is scoped to that one test.

    Rationale: 2026-05-06 incident — a QA subagent's `pytest` reached live
    broker via an unmocked code path and submitted 5×100 AMD parent BUYs,
    accumulating 500 shares in a $-101k margin position. PR #150's docs/skill
    rule did not prevent this; the mechanical env-var guard does.
    """
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "1")


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
