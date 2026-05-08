# Rules-Engine Pivot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 4-agent LLM swing trader (12 US stocks) with a deterministic rules engine that holds 3USL UCITS (`WSPL.DE`, 3× S&P leveraged ETP, EUR on Xetra) when SPY closes above its 200-day SMA, with a 30-trading-day drawdown kill-switch as defense-in-depth.

**Architecture:** Single Python application, no LLM. Daily cron runs `daily_check.py` to compute the regime filter and flip the IBKR position if needed. Hourly cron runs `monitor/kill_switch.py` to exit if 3USL draws down >25% from its rolling 30-trading-day high. SQLite tracks state and audit trail. All trade-decision logic is pure-function-testable; broker is wrapped in `tools/ibkr_broker.py` and gated by the existing `CLAUDE_AGENT_NO_BROKER` test guard.

**Tech Stack:** Python 3.9 (`from __future__ import annotations` required in every module), SQLite, `ib_insync` (IBKR API), `yfinance` (market data), `pytest` + `pytest-mock`, n8n+Discord webhook.

**Spec:** `docs/superpowers/specs/2026-05-07-rules-engine-pivot-design.md` (PR #193)

---

## Pre-flight (operator tasks — not part of this plan)

These are user/operator responsibilities and must be done **before Task 9** (which is the first task that actually places a paper-trading order):

1. Open an IBKR retail account (paper account suffices for development; live for production).
2. Install IB Gateway on the VPS, configure it as a systemd service, point it at the paper port (4002) initially.
3. In IB Gateway / TWS settings: enable API, allow connections from `127.0.0.1`, set "Trusted IPs" to localhost.
4. Verify `ib_insync` can connect with `python -c "from ib_insync import IB; ib = IB(); ib.connect('127.0.0.1', 4002, clientId=99); print(ib.isConnected()); ib.disconnect()"`.

If TWS/Gateway is not available when Task 9 begins, that task will block.

---

## File map

| File | Tasks |
|---|---|
| `config/settings.py` | Task 1 — add new env vars; Task 12 — remove obsolete vars |
| `.env.example` | Task 1 — document new vars; Task 16 — final pass |
| `storage/schema.sql` | Task 2 — schema migration |
| `storage/init_db.py` | Task 2 — migration runner |
| `tools/database.py` | Task 2 — helpers for new tables; Task 14 — drop obsolete helpers |
| `strategy/regime.py` | Task 3 — pure-function regime filter (NEW) |
| `tests/test_strategy_regime.py` | Task 3 — pure-function tests (NEW) |
| `backtest/regime.py` | Task 4 — new backtester (NEW) |
| `tests/test_backtest_regime.py` | Task 4 — regression test (NEW) |
| `tools/ibkr_broker.py` | Tasks 5, 6, 7 (NEW) |
| `tests/test_tools_ibkr_broker.py` | Tasks 5, 6, 7 (NEW) |
| `tools/notifications.py` | Task 8 — new event types |
| `tests/test_notifications.py` | Task 8 — new event tests |
| `daily_check.py` | Task 9 (NEW) — top-level entry script |
| `tests/test_daily_check.py` | Task 9 (NEW) |
| `monitor/kill_switch.py` | Task 10 (NEW) |
| `tests/test_monitor_kill_switch.py` | Task 10 (NEW) |
| `monitor/position_monitor.py` | Task 14 — DELETE |
| `main.py` | Task 11 — panic migration; Task 15 — drop scan/monitor modes |
| `tests/test_main_panic.py` | Task 11 — IBKR panic tests |
| `tests/test_main.py` | Task 15 — drop scan/monitor mode tests |
| `agents/` (entire directory) | Task 13 — DELETE |
| `tests/test_*_agent.py`, `tests/test_team_leader_*.py`, `tests/test_base_agent.py` | Task 13 — DELETE |
| `tools/risk.py`, `tools/broker.py` | Task 14 — DELETE |
| `tests/test_risk.py`, `tests/test_tools_broker.py` | Task 14 — DELETE |
| `requirements.txt` | Task 16 — drop `anthropic`, add `ib_insync` |
| `README.md` | Task 16 — rewrite for new architecture |
| `CLAUDE.md` | Task 16 — simplify invariants section |
| `scripts/cron_setup.sh`, `docs/CURRENT_CONFIG.md` | Task 17 — cron migration |

---

## Task 1: Add new env-driven settings

**Files:**
- Modify: `config/settings.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Context:** New env vars for IBKR connection, kill-switch behaviour, and the bot's instruments. Old vars stay in place for now — Task 12 removes them after the new bot is wired. This task adds new vars with sane defaults so the new code in later tasks has something to read.

- [ ] **Step 1: Read current `config/settings.py` to understand the existing pattern**

Run: `wc -l config/settings.py && head -40 config/settings.py`
Expected: ~123 lines, validation-at-import pattern using `os.getenv()` then `raise ValueError` for out-of-range.

- [ ] **Step 2: Write failing test for new IBKR settings**

Add to `tests/test_config.py`:

```python
def test_ibkr_host_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.IBKR_HOST == "127.0.0.1"


def test_ibkr_port_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.IBKR_PORT == 4002  # paper default


def test_ibkr_port_validation_low(monkeypatch):
    monkeypatch.setenv("IBKR_PORT", "0")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="IBKR_PORT"):
        importlib.reload(s)


def test_ibkr_port_validation_high(monkeypatch):
    monkeypatch.setenv("IBKR_PORT", "70000")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="IBKR_PORT"):
        importlib.reload(s)


def test_kill_switch_drawdown_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.KILL_SWITCH_DRAWDOWN_PCT == 0.25


def test_kill_switch_drawdown_validation(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH_DRAWDOWN_PCT", "1.5")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="KILL_SWITCH_DRAWDOWN_PCT"):
        importlib.reload(s)


def test_regime_sma_days_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.REGIME_SMA_DAYS == 200


def test_kill_switch_lookback_days_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.KILL_SWITCH_LOOKBACK_DAYS == 30


def test_bot_ticker_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.BOT_TICKER == "WSPL.DE"


def test_bot_benchmark_default():
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.BOT_BENCHMARK == "SPY"


def test_bot_ticker_empty_rejected(monkeypatch):
    monkeypatch.setenv("BOT_TICKER", "")
    import importlib
    import config.settings as s
    with pytest.raises(ValueError, match="BOT_TICKER"):
        importlib.reload(s)
```

- [ ] **Step 3: Run failing tests**

Run: `python3 -m pytest tests/test_config.py -v -k "ibkr or kill_switch or regime_sma or bot_ticker or bot_benchmark or kill_switch_lookback"`
Expected: All new tests FAIL with `AttributeError` (settings don't exist yet).

- [ ] **Step 4: Add the new settings to `config/settings.py`**

Append at the bottom of `config/settings.py` (just before the final `CLAUDE_AGENT_NO_BROKER` block):

```python
# --- IBKR connection (replaces Alpaca) ----------------------------------
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "4002"))  # 4002=paper, 4001=live
if not 1 <= IBKR_PORT <= 65535:
    raise ValueError(f"IBKR_PORT={IBKR_PORT} outside valid TCP range [1, 65535]")
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
if not 0 <= IBKR_CLIENT_ID <= 999:
    raise ValueError(f"IBKR_CLIENT_ID={IBKR_CLIENT_ID} outside safe bounds [0, 999]")

# --- Bot strategy parameters --------------------------------------------
BOT_TICKER = os.getenv("BOT_TICKER", "WSPL.DE")  # 3USL UCITS on Xetra
if not BOT_TICKER.strip():
    raise ValueError("BOT_TICKER must be a non-empty ticker symbol")
BOT_BENCHMARK = os.getenv("BOT_BENCHMARK", "SPY")  # regime-filter input
if not BOT_BENCHMARK.strip():
    raise ValueError("BOT_BENCHMARK must be a non-empty ticker symbol")

REGIME_SMA_DAYS = int(os.getenv("REGIME_SMA_DAYS", "200"))
if not 20 <= REGIME_SMA_DAYS <= 500:
    raise ValueError(f"REGIME_SMA_DAYS={REGIME_SMA_DAYS} outside safe bounds [20, 500]")

KILL_SWITCH_DRAWDOWN_PCT = float(os.getenv("KILL_SWITCH_DRAWDOWN_PCT", "0.25"))
if not 0.05 <= KILL_SWITCH_DRAWDOWN_PCT <= 0.50:
    raise ValueError(f"KILL_SWITCH_DRAWDOWN_PCT={KILL_SWITCH_DRAWDOWN_PCT} outside safe bounds [0.05, 0.50]")

KILL_SWITCH_LOOKBACK_DAYS = int(os.getenv("KILL_SWITCH_LOOKBACK_DAYS", "30"))
if not 5 <= KILL_SWITCH_LOOKBACK_DAYS <= 252:
    raise ValueError(f"KILL_SWITCH_LOOKBACK_DAYS={KILL_SWITCH_LOOKBACK_DAYS} outside safe bounds [5, 252]")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -v -k "ibkr or kill_switch or regime_sma or bot_ticker or bot_benchmark or kill_switch_lookback"`
Expected: All new tests PASS.

- [ ] **Step 6: Update `.env.example` with the new vars**

Append to `.env.example`:

```
# --- IBKR connection (replaces Alpaca) ----------------------------------
IBKR_HOST=127.0.0.1
IBKR_PORT=4002         # 4002=paper, 4001=live
IBKR_CLIENT_ID=1

# --- Bot strategy parameters --------------------------------------------
BOT_TICKER=WSPL.DE     # 3USL UCITS on Xetra
BOT_BENCHMARK=SPY
REGIME_SMA_DAYS=200
KILL_SWITCH_DRAWDOWN_PCT=0.25
KILL_SWITCH_LOOKBACK_DAYS=30
```

- [ ] **Step 7: Run full test suite to confirm nothing else broke**

Run: `python3 -m pytest -x -q`
Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add config/settings.py .env.example tests/test_config.py
git commit -m "feat(settings): add IBKR + regime-filter env vars"
```

---

## Task 2: Schema migration — `regime_state` table, simplified `trades`, rename `agent_logs` → `audit_log`

**Files:**
- Modify: `storage/schema.sql`
- Create: `storage/migrations/2026_05_07_rules_engine_pivot.sql`
- Modify: `storage/init_db.py`
- Modify: `tools/database.py`
- Test: `tests/test_storage.py`

**Context:** New `regime_state` table stores one row per trading day with regime decision and kill-switch state. `trades` is simplified (drop `stop_loss`, `take_profit`, `r_multiple` — bot is binary in/out). `agent_logs` → `audit_log` and drop the token-cost columns. Old tables (`signals`, `monitor_actions`, `daily_stats`, `weekly_stats`, `suggestions`) are dropped — they're not used by the new bot.

The migration must be **idempotent** (safe to re-run) and **forward-only** (no down-migration). It runs once on the existing DB to transform schema in-place.

- [ ] **Step 1: Inspect current schema**

Run: `sqlite3 trading_bot.db .schema | head -80`
Expected: Output shows existing tables.

- [ ] **Step 2: Write migration script**

Create `storage/migrations/2026_05_07_rules_engine_pivot.sql`:

```sql
-- Migration: drop pre-pivot tables. Schema is then recreated by `schema.sql`.
-- Old data is intentionally NOT migrated:
--   * `agent_logs` is per-LLM-agent runs (different domain than the new `audit_log`).
--   * `trades` had different fields and reason taxonomy.
--   * `signals`/`monitor_actions`/`daily_stats`/`weekly_stats`/`suggestions` are unused.
--
-- This script is only run by `init_db.py` when it detects pre-pivot tables.
-- It drops everything; `schema.sql` then runs and creates the new shape.

BEGIN TRANSACTION;

DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS monitor_actions;
DROP TABLE IF EXISTS daily_stats;
DROP TABLE IF EXISTS weekly_stats;
DROP TABLE IF EXISTS suggestions;
DROP TABLE IF EXISTS agent_logs;
DROP TABLE IF EXISTS trades;

COMMIT;
```

- [ ] **Step 3: Update `storage/schema.sql` to match the new shape**

Replace the entire contents of `storage/schema.sql` with:

```sql
-- Schema for rules-engine bot (post-2026-05-07 pivot).
-- See docs/superpowers/specs/2026-05-07-rules-engine-pivot-design.md

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS regime_state (
    date TEXT PRIMARY KEY,
    spy_close REAL NOT NULL,
    spy_sma200 REAL NOT NULL,
    target_state TEXT NOT NULL CHECK(target_state IN ('LONG','CASH')),
    current_state TEXT NOT NULL CHECK(current_state IN ('LONG','CASH')),
    position_drawdown_pct REAL,
    kill_switch_active INTEGER NOT NULL DEFAULT 0 CHECK(kill_switch_active IN (0,1)),
    kill_switch_fired_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    qty INTEGER NOT NULL,
    fill_price REAL NOT NULL,
    fill_time TEXT NOT NULL,
    ibkr_order_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('regime_flip_long','regime_flip_cash','kill_switch','panic_cli')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    notes TEXT
);
```

- [ ] **Step 4: Update `storage/init_db.py` to apply migrations**

Modify `storage/init_db.py` to detect "already-migrated" state and run the migration if needed:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = :name",
        {"name": name},
    )
    return cur.fetchone() is not None


def init_db(db_path: str | Path = "trading_bot.db") -> None:
    """Initialise (or migrate) the SQLite database in-place.

    - Fresh DB: apply `schema.sql` directly.
    - Existing DB with pre-pivot tables: apply migration to reshape.
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
    print("DB initialised / migrated.")
```

- [ ] **Step 5: Write tests for the migration**

Add to `tests/test_storage.py`:

```python
from __future__ import annotations

import sqlite3
import pytest
from storage.init_db import init_db


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


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
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_storage.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Add helper functions in `tools/database.py`**

Add these functions to `tools/database.py` (alongside existing helpers — old helpers stay for now, removed in Task 14):

```python
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
    """Insert or replace today's regime_state row."""
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
    """Return the most recent regime_state row as a dict, or None if empty."""
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
    """Insert a trade row; return rowid."""
    cur = conn.execute(
        """
        INSERT INTO trades (symbol, side, qty, fill_price, fill_time, ibkr_order_id, reason)
        VALUES (:symbol, :side, :qty, :fill_price, :fill_time, :ibkr_order_id, :reason)
        """,
        dict(symbol=symbol, side=side, qty=qty, fill_price=fill_price,
             fill_time=fill_time, ibkr_order_id=ibkr_order_id, reason=reason),
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
    """Insert an audit_log row; return rowid."""
    cur = conn.execute(
        """
        INSERT INTO audit_log (script_name, started_at, finished_at, outcome, notes)
        VALUES (:script_name, :started_at, :finished_at, :outcome, :notes)
        """,
        dict(script_name=script_name, started_at=started_at,
             finished_at=finished_at, outcome=outcome, notes=notes),
    )
    conn.commit()
    return cur.lastrowid


def update_audit_log(conn, *, rowid: int, finished_at: str, outcome: str, notes: str | None = None) -> None:
    conn.execute(
        "UPDATE audit_log SET finished_at = :f, outcome = :o, notes = :n WHERE id = :id",
        dict(f=finished_at, o=outcome, n=notes, id=rowid),
    )
    conn.commit()
```

- [ ] **Step 8: Test the helpers**

Add to `tests/test_storage.py`:

```python
from tools.database import (
    upsert_regime_state, get_latest_regime_state,
    insert_trade, insert_audit_log, update_audit_log,
)


def _conn(tmp_path):
    init_db(tmp_path / "h.db")
    conn = sqlite3.connect(str(tmp_path / "h.db"))
    conn.row_factory = sqlite3.Row
    return conn


def test_upsert_regime_state_inserts(tmp_path):
    conn = _conn(tmp_path)
    upsert_regime_state(conn, date="2026-05-07", spy_close=400.0, spy_sma200=380.0,
                        target_state="LONG", current_state="CASH",
                        position_drawdown_pct=None, kill_switch_active=False,
                        kill_switch_fired_at=None)
    state = get_latest_regime_state(conn)
    assert state["target_state"] == "LONG"
    assert state["kill_switch_active"] == 0


def test_upsert_regime_state_replaces_same_date(tmp_path):
    conn = _conn(tmp_path)
    for ts in ("CASH", "LONG"):
        upsert_regime_state(conn, date="2026-05-07", spy_close=400.0, spy_sma200=380.0,
                            target_state=ts, current_state="CASH",
                            position_drawdown_pct=None, kill_switch_active=False,
                            kill_switch_fired_at=None)
    state = get_latest_regime_state(conn)
    assert state["target_state"] == "LONG"  # last write wins
    n = conn.execute("SELECT COUNT(*) FROM regime_state").fetchone()[0]
    assert n == 1


def test_insert_trade(tmp_path):
    conn = _conn(tmp_path)
    rowid = insert_trade(conn, symbol="WSPL.DE", side="BUY", qty=100,
                         fill_price=50.0, fill_time="2026-05-07T13:30:01",
                         ibkr_order_id="ORD-1", reason="regime_flip_long")
    assert rowid == 1


def test_audit_log_lifecycle(tmp_path):
    conn = _conn(tmp_path)
    rowid = insert_audit_log(conn, script_name="daily_check", started_at="2026-05-07T22:30:00")
    update_audit_log(conn, rowid=rowid, finished_at="2026-05-07T22:30:05", outcome="success")
    row = conn.execute("SELECT outcome FROM audit_log WHERE id=?", (rowid,)).fetchone()
    assert row["outcome"] == "success"
```

- [ ] **Step 9: Run all storage tests**

Run: `python3 -m pytest tests/test_storage.py -v`
Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add storage/schema.sql storage/migrations/2026_05_07_rules_engine_pivot.sql \
        storage/init_db.py tools/database.py tests/test_storage.py
git commit -m "feat(storage): regime_state schema + audit_log rename migration"
```

---

## Task 3: Pure-function regime filter (`strategy/regime.py`)

**Files:**
- Create: `strategy/__init__.py` (empty)
- Create: `strategy/regime.py`
- Test: `tests/test_strategy_regime.py`

**Context:** The whole trading-decision logic is one pure function. No I/O, no globals, no side effects — just `(spy_close, spy_sma200, current_state, kill_switch_active) -> ("LONG"|"CASH", new_kill_switch_active)`. This is the most-tested module in the codebase because everything else trusts it.

- [ ] **Step 1: Create the strategy package**

Run: `mkdir -p strategy && touch strategy/__init__.py`

- [ ] **Step 2: Write the failing test suite**

Create `tests/test_strategy_regime.py`:

```python
from __future__ import annotations

import math
import pytest
from strategy.regime import compute_target_state


# --- Bullish regime (SPY > SMA200) ---

def test_bullish_no_ks_from_cash_returns_long():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=380.0,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "LONG"
    assert ks is False


def test_bullish_no_ks_already_long_stays_long():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=380.0,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "LONG"
    assert ks is False


def test_bullish_with_ks_clears_flag_and_re_enters():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=380.0,
                                       current_state="CASH", kill_switch_active=True)
    assert target == "LONG"
    assert ks is False  # flag cleared on bullish re-entry


# --- Bearish regime (SPY <= SMA200) ---

def test_bearish_no_ks_from_long_exits():
    target, ks = compute_target_state(spy_close=380.0, spy_sma200=400.0,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_bearish_no_ks_already_cash_stays_cash():
    target, ks = compute_target_state(spy_close=380.0, spy_sma200=400.0,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_bearish_with_ks_keeps_flag_set():
    target, ks = compute_target_state(spy_close=380.0, spy_sma200=400.0,
                                       current_state="CASH", kill_switch_active=True)
    assert target == "CASH"
    assert ks is True  # flag stays — bearish, no re-entry


# --- Boundary: SPY == SMA200 (strictly greater than required for LONG) ---

def test_boundary_equal_sma_returns_cash():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=400.0,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_boundary_equal_sma_from_long_exits():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=400.0,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


# --- Defensive: NaN SMA (insufficient history) ---

def test_nan_sma_returns_cash_defensively():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=math.nan,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_nan_sma_with_existing_long_exits_to_cash():
    """If SMA goes NaN unexpectedly mid-strategy (data issue), bot must exit defensively."""
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=math.nan,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


# --- Validation ---

def test_invalid_current_state_raises():
    with pytest.raises(ValueError, match="current_state"):
        compute_target_state(spy_close=400.0, spy_sma200=380.0,
                             current_state="HOLDING", kill_switch_active=False)


def test_negative_spy_close_raises():
    with pytest.raises(ValueError, match="spy_close"):
        compute_target_state(spy_close=-1.0, spy_sma200=380.0,
                             current_state="CASH", kill_switch_active=False)


def test_negative_sma_raises():
    with pytest.raises(ValueError, match="spy_sma200"):
        compute_target_state(spy_close=400.0, spy_sma200=-380.0,
                             current_state="CASH", kill_switch_active=False)


# --- Truth-table coverage (all 8 combos: regime × current × ks) ---

@pytest.mark.parametrize("spy,sma,cur,ks_in,expected_target,expected_ks", [
    (400, 380, "CASH",  False, "LONG", False),
    (400, 380, "CASH",  True,  "LONG", False),  # ks cleared on bullish
    (400, 380, "LONG",  False, "LONG", False),
    (400, 380, "LONG",  True,  "LONG", False),  # ks cleared on bullish (edge case)
    (380, 400, "CASH",  False, "CASH", False),
    (380, 400, "CASH",  True,  "CASH", True),   # ks preserved
    (380, 400, "LONG",  False, "CASH", False),
    (380, 400, "LONG",  True,  "CASH", True),
])
def test_truth_table(spy, sma, cur, ks_in, expected_target, expected_ks):
    target, ks_out = compute_target_state(spy_close=spy, spy_sma200=sma,
                                           current_state=cur, kill_switch_active=ks_in)
    assert target == expected_target
    assert ks_out == expected_ks
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_strategy_regime.py -v`
Expected: All tests FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `strategy/regime.py`**

Create `strategy/regime.py`:

```python
"""Pure regime-filter logic. The entire trading decision lives in one function.

Decision rule (Mebane Faber, 2007):
    if SPY > SMA(200):  target = LONG    (kill-switch flag cleared if previously set)
    else:               target = CASH   (kill-switch flag preserved if set)

This module is intentionally I/O-free. All I/O happens in callers (`daily_check.py`,
`monitor/kill_switch.py`). That makes the function trivially testable and removes
any path where business logic could be perturbed by network/clock/DB state.
"""
from __future__ import annotations

import math
from typing import Literal

State = Literal["LONG", "CASH"]


def compute_target_state(
    *,
    spy_close: float,
    spy_sma200: float,
    current_state: State,
    kill_switch_active: bool,
) -> tuple[State, bool]:
    """Compute target portfolio state and updated kill-switch flag.

    Args:
        spy_close: Today's SPY closing price. Must be > 0.
        spy_sma200: Today's 200-day SMA of SPY. NaN is acceptable (insufficient
            history) and triggers defensive CASH. Must be >= 0 if not NaN.
        current_state: The bot's current position state ('LONG' or 'CASH').
        kill_switch_active: Whether a recent kill-switch event is suppressing
            re-entry. Cleared automatically when SPY > SMA200.

    Returns:
        (target_state, new_kill_switch_active).

    Raises:
        ValueError: on invalid inputs (negative prices, unknown state).
    """
    if spy_close <= 0:
        raise ValueError(f"spy_close must be > 0, got {spy_close}")
    if not math.isnan(spy_sma200) and spy_sma200 < 0:
        raise ValueError(f"spy_sma200 must be >= 0 or NaN, got {spy_sma200}")
    if current_state not in ("LONG", "CASH"):
        raise ValueError(f"current_state must be LONG or CASH, got {current_state!r}")

    # Defensive: if SMA200 unavailable, force CASH and preserve any kill-switch flag.
    if math.isnan(spy_sma200):
        return "CASH", kill_switch_active

    # Strictly greater than — exact equality treated as bearish.
    is_bullish = spy_close > spy_sma200

    if is_bullish:
        return "LONG", False  # bullish always clears the kill-switch flag

    # Bearish: stay in / move to CASH; preserve any existing flag.
    return "CASH", kill_switch_active
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_strategy_regime.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run full suite to confirm no regressions**

Run: `python3 -m pytest -x -q`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add strategy/__init__.py strategy/regime.py tests/test_strategy_regime.py
git commit -m "feat(strategy): pure-function 200-DMA regime filter"
```

---

## Task 4: New backtester (`backtest/regime.py`)

**Files:**
- Create: `backtest/regime.py`
- Test: `tests/test_backtest_regime.py`

**Context:** The current per-ticker and portfolio backtesters are wrong shape for the new strategy. Write a small dedicated backtester that fetches SPY + the bot's vehicle (`BOT_TICKER`) history, applies the regime filter daily, simulates trade execution at next-day open, and reports CAGR / total return / max drawdown / trade list.

3USL has a shorter price history than SPY. The backtester must handle the case where 3USL data starts mid-window — it backtests on the intersection of available dates.

- [ ] **Step 1: Write a regression test on a known historical window**

Create `tests/test_backtest_regime.py`:

```python
"""Regression test for backtest/regime.py.

Pinned to the 2021-05-07 → 2026-05-07 window with UPRO as the vehicle (since
3USL data history may be insufficient on yfinance). The 200-DMA filter on UPRO
over this window produced ~+150% total / ~−35% max DD in our brainstorming
session. Exact numbers will vary with yfinance data revisions, so we assert
loose bounds rather than equality.
"""
from __future__ import annotations

from datetime import date
import pytest
from backtest.regime import run_regime_backtest


@pytest.mark.slow
def test_upro_2021_2026_filter_within_expected_envelope():
    result = run_regime_backtest(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2021, 5, 7),
        end=date(2026, 5, 7),
        sma_days=200,
    )
    # Headline metrics
    assert 0.80 < result["total_return"] < 2.50, f"total_return={result['total_return']!r}"
    assert -0.55 < result["max_drawdown"] < -0.20, f"max_dd={result['max_drawdown']!r}"
    # Trade count: regime filter on a 5y window typically produces 4-12 round trips
    assert 2 <= result["trade_count"] <= 20, f"trade_count={result['trade_count']!r}"
    # Sanity: starting and ending equity
    assert result["starting_cash"] == pytest.approx(100_000.0)
    assert result["ending_equity"] > 0


def test_handles_short_history_vehicle(monkeypatch):
    """If vehicle data starts mid-window, backtest skips pre-data days."""
    # Synthetic test: ask for a window that's longer than available data.
    # We can't easily fake yfinance — instead, run with a very short window
    # and verify the structure of the result.
    result = run_regime_backtest(
        benchmark_ticker="SPY",
        vehicle_ticker="SPY",  # same as benchmark for this test
        start=date(2024, 1, 1),
        end=date(2024, 6, 1),
        sma_days=200,
    )
    assert "total_return" in result
    assert "max_drawdown" in result
    assert "trade_count" in result
```

- [ ] **Step 2: Run failing test**

Run: `python3 -m pytest tests/test_backtest_regime.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backtest/regime.py`**

Create `backtest/regime.py`:

```python
"""Backtest the 200-DMA regime filter on a single vehicle.

Simulation rules (matching the live bot's behaviour as closely as possible):
- Daily decision: at end of day, compute SMA(sma_days) on benchmark closes.
- Trade execution: next day's open. Slippage modeled via `slippage_bps`.
- Commission: bps of notional, applied per round trip.
- Binary in/out: on LONG, deploy 100% of available cash into the vehicle.
- Cash earns 0% (conservative).
- Kill-switch: NOT modelled here. Backtest is for the regime rule alone;
  kill-switch is a separate operational protection. Modelling it would
  require intraday data we don't have in the daily-bar yfinance feed.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    exit_reason: str  # "regime_flip"


STARTING_CASH = 100_000.0
SLIPPAGE_BPS = 5  # 0.05% per side
COMMISSION_BPS = 5  # 0.05% per side


def _fetch(ticker: str, start: date, end: date) -> pd.Series:
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def run_regime_backtest(
    *,
    benchmark_ticker: str = "SPY",
    vehicle_ticker: str = "UPRO",
    start: date,
    end: date,
    sma_days: int = 200,
    starting_cash: float = STARTING_CASH,
) -> dict:
    """Run the regime-filter backtest. Returns headline metrics + trade list.

    Result keys: total_return, cagr, max_drawdown, trade_count, ending_equity,
                 starting_cash, trades (list of dicts), equity_curve (pd.Series).
    """
    benchmark = _fetch(benchmark_ticker, start, end)
    vehicle = _fetch(vehicle_ticker, start, end)

    # Align on common dates
    common = benchmark.index.intersection(vehicle.index)
    benchmark = benchmark.loc[common]
    vehicle = vehicle.loc[common]

    # SMA on benchmark close
    sma = benchmark["Close"].rolling(sma_days).mean()
    is_bullish = (benchmark["Close"] > sma).fillna(False)

    # Trade at next open after the signal day
    signal = is_bullish.shift(1).fillna(False)

    # Simulation
    equity_curve = []
    cash = starting_cash
    qty = 0
    entry_price = 0.0
    entry_date: Optional[pd.Timestamp] = None
    trades: list[Trade] = []

    for i, ts in enumerate(common):
        open_px = float(vehicle["Open"].iloc[i])
        close_px = float(vehicle["Close"].iloc[i])
        want_long = bool(signal.iloc[i])

        # Open-of-day execution
        if want_long and qty == 0 and not np.isnan(sma.iloc[i - 1] if i > 0 else np.nan):
            # Buy at open, with slippage + commission
            execution_px = open_px * (1 + SLIPPAGE_BPS / 10_000)
            qty = int(cash / execution_px / (1 + COMMISSION_BPS / 10_000))
            cost = qty * execution_px * (1 + COMMISSION_BPS / 10_000)
            cash -= cost
            entry_price = execution_px
            entry_date = ts
        elif not want_long and qty > 0:
            # Sell at open
            execution_px = open_px * (1 - SLIPPAGE_BPS / 10_000)
            proceeds = qty * execution_px * (1 - COMMISSION_BPS / 10_000)
            cash += proceeds
            pnl = proceeds - (qty * entry_price * (1 + COMMISSION_BPS / 10_000))
            trades.append(Trade(
                entry_date=entry_date, exit_date=ts,
                entry_price=entry_price, exit_price=execution_px,
                qty=qty, pnl=pnl,
                return_pct=(execution_px / entry_price - 1),
                exit_reason="regime_flip",
            ))
            qty = 0
            entry_price = 0.0
            entry_date = None

        # Mark equity to close
        eq = cash + qty * close_px
        equity_curve.append((ts, eq))

    # Close any open position at last close
    if qty > 0:
        last_ts = common[-1]
        last_close = float(vehicle["Close"].iloc[-1])
        execution_px = last_close * (1 - SLIPPAGE_BPS / 10_000)
        proceeds = qty * execution_px * (1 - COMMISSION_BPS / 10_000)
        cash += proceeds
        pnl = proceeds - (qty * entry_price * (1 + COMMISSION_BPS / 10_000))
        trades.append(Trade(
            entry_date=entry_date, exit_date=last_ts,
            entry_price=entry_price, exit_price=execution_px,
            qty=qty, pnl=pnl,
            return_pct=(execution_px / entry_price - 1),
            exit_reason="end_of_window",
        ))

    eq_series = pd.Series(dict(equity_curve))
    total_return = float(eq_series.iloc[-1] / starting_cash - 1)
    n_years = (end - start).days / 365.25
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
    rolling_max = eq_series.cummax()
    max_dd = float(((eq_series - rolling_max) / rolling_max).min())

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
        "ending_equity": float(eq_series.iloc[-1]),
        "starting_cash": starting_cash,
        "trades": [t.__dict__ for t in trades],
        "equity_curve": eq_series,
    }


def main_cli() -> None:
    """Command-line wrapper for ad-hoc runs (called by main.py backtest)."""
    import argparse
    from datetime import date as _date

    parser = argparse.ArgumentParser(prog="backtest.regime")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--vehicle", default="UPRO")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--sma", type=int, default=200)
    args = parser.parse_args()

    end = _date.today()
    try:
        start = _date(end.year - args.years, end.month, end.day)
    except ValueError:
        start = _date(end.year - args.years, end.month, 28)

    result = run_regime_backtest(
        benchmark_ticker=args.benchmark,
        vehicle_ticker=args.vehicle,
        start=start, end=end,
        sma_days=args.sma,
    )
    print(f"Period: {start} → {end}  ({args.years}y)")
    print(f"Vehicle: {args.vehicle}  Benchmark: {args.benchmark}  SMA: {args.sma}")
    print(f"Total return:    {result['total_return']*100:+.2f}%")
    print(f"CAGR:            {result['cagr']*100:+.2f}%")
    print(f"Max drawdown:    {result['max_drawdown']*100:+.2f}%")
    print(f"Trade count:     {result['trade_count']}")
    print(f"Ending equity:   ${result['ending_equity']:,.2f}")


if __name__ == "__main__":
    main_cli()
```

- [ ] **Step 4: Run regression test (network-bound — may take ~30s)**

Run: `python3 -m pytest tests/test_backtest_regime.py -v -m slow`
Expected: PASS. Both tests in the file.

- [ ] **Step 5: Manual sanity check vs spec figures**

Run: `python3 backtest/regime.py --benchmark SPY --vehicle UPRO --years 5 --sma 200`
Expected output (loose bounds): total return between +80% and +250%, max DD between −55% and −20%, trade count 2-20.

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest -x -q`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backtest/regime.py tests/test_backtest_regime.py
git commit -m "feat(backtest): regime-filter backtester with regression test"
```

---

## Task 5: IBKR broker — connection & read-only ops

**Files:**
- Create: `tools/ibkr_broker.py`
- Test: `tests/test_tools_ibkr_broker.py`

**Context:** First slice of the IBKR wrapper: connect/disconnect, position queries, account-value queries. Mock `ib_insync.IB` at the import path so all broker tests run without TWS. The `CLAUDE_AGENT_NO_BROKER` env-var guard from issue #168 is preserved — every submission helper checks it (we don't have submission helpers yet, but the connection helpers gain the same guard for consistency).

`ib_insync` reference (verify against installed version during implementation):
- `from ib_insync import IB, Stock, MarketOrder, util`
- `ib = IB(); ib.connect(host, port, clientId)`
- `ib.positions()` — list of `Position` namedtuples; `.contract.symbol`, `.position` (qty)
- `ib.accountSummary()` — list of `AccountValue` namedtuples; `.tag`, `.value`, `.currency`

- [ ] **Step 1: Add `ib_insync` dependency**

Run: `echo "ib_insync>=0.9.86" >> requirements.txt`

Then install in venv:
Run: `venv/bin/pip install -r requirements.txt`
Expected: `ib_insync` installed without conflicts.

- [ ] **Step 2: Write failing tests for `connect_ibkr` / `get_position` / `get_account_value`**

Create `tests/test_tools_ibkr_broker.py`:

```python
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

# Ensure the global guard is OFF for these specific tests (we'll re-enable
# selectively to test the guard behaviour).
@pytest.fixture(autouse=True)
def _guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)


def test_connect_ibkr_returns_connected_client():
    with patch("tools.ibkr_broker.IB") as MockIB:
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr
        ib = connect_ibkr(host="127.0.0.1", port=4002, client_id=1)

        mock_ib.connect.assert_called_once_with("127.0.0.1", 4002, clientId=1, timeout=10)
        assert ib is mock_ib


def test_connect_ibkr_retries_on_failure():
    """Two failures, then success, should still return a connected client."""
    from ib_insync import Forex  # ensure import path works
    with patch("tools.ibkr_broker.IB") as MockIB:
        mock_ib = MagicMock()
        # First two connects raise, third succeeds
        mock_ib.connect.side_effect = [ConnectionError("first"), ConnectionError("second"), None]
        mock_ib.isConnected.return_value = True
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr
        ib = connect_ibkr(host="127.0.0.1", port=4002, client_id=1, max_retries=3, backoff_s=0.01)

        assert mock_ib.connect.call_count == 3
        assert ib is mock_ib


def test_connect_ibkr_raises_after_max_retries():
    with patch("tools.ibkr_broker.IB") as MockIB:
        mock_ib = MagicMock()
        mock_ib.connect.side_effect = ConnectionError("nope")
        MockIB.return_value = mock_ib

        from tools.ibkr_broker import connect_ibkr, IBKRConnectionError
        with pytest.raises(IBKRConnectionError):
            connect_ibkr(host="127.0.0.1", port=4002, client_id=1, max_retries=2, backoff_s=0.01)
        assert mock_ib.connect.call_count == 2


def test_get_position_returns_zero_when_no_positions():
    mock_ib = MagicMock()
    mock_ib.positions.return_value = []
    from tools.ibkr_broker import get_position
    qty = get_position(mock_ib, "WSPL.DE")
    assert qty == 0


def test_get_position_returns_quantity_when_held():
    mock_ib = MagicMock()
    mock_pos = MagicMock()
    mock_pos.contract.symbol = "WSPL"
    mock_pos.position = 100
    mock_ib.positions.return_value = [mock_pos]
    from tools.ibkr_broker import get_position
    qty = get_position(mock_ib, "WSPL.DE")
    assert qty == 100


def test_get_position_ignores_other_symbols():
    mock_ib = MagicMock()
    other = MagicMock(); other.contract.symbol = "AAPL"; other.position = 50
    target = MagicMock(); target.contract.symbol = "WSPL"; target.position = 200
    mock_ib.positions.return_value = [other, target]
    from tools.ibkr_broker import get_position
    qty = get_position(mock_ib, "WSPL.DE")
    assert qty == 200


def test_get_account_value_returns_eur_net_liquidation():
    mock_ib = MagicMock()
    av_eur = MagicMock(); av_eur.tag = "NetLiquidation"; av_eur.value = "12345.67"; av_eur.currency = "EUR"
    av_usd = MagicMock(); av_usd.tag = "NetLiquidation"; av_usd.value = "999.00"; av_usd.currency = "USD"
    mock_ib.accountSummary.return_value = [av_eur, av_usd]
    from tools.ibkr_broker import get_account_value
    val = get_account_value(mock_ib, currency="EUR")
    assert val == pytest.approx(12345.67)


def test_guard_blocks_connect(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    with patch("tools.ibkr_broker.IB") as MockIB:
        from tools.ibkr_broker import connect_ibkr, BrokerCallBlockedError
        with pytest.raises(BrokerCallBlockedError):
            connect_ibkr(host="127.0.0.1", port=4002, client_id=1)
        # The IB() class should never have been instantiated
        MockIB.assert_not_called()
```

- [ ] **Step 3: Run failing tests**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v`
Expected: FAIL with `ModuleNotFoundError: tools.ibkr_broker`.

- [ ] **Step 4: Implement the connection layer**

Create `tools/ibkr_broker.py`:

```python
"""IBKR broker wrapper using `ib_insync`.

This module owns all interaction with TWS / IB Gateway. It enforces the
`CLAUDE_AGENT_NO_BROKER` guard at the top of every submission/connection
helper so any forgotten mock in a test fails fast instead of reaching live
broker (per the lessons in CLAUDE.md issues #149, #168).
"""
from __future__ import annotations

import time
from typing import Optional

from ib_insync import IB, Stock, MarketOrder

from config.settings import is_claude_agent_no_broker


class BrokerCallBlockedError(RuntimeError):
    """Raised when a broker call is attempted with the agent-context guard active."""


class IBKRConnectionError(RuntimeError):
    """Raised when we can't establish a TWS connection after retries."""


def _check_guard(op: str) -> None:
    if is_claude_agent_no_broker():
        raise BrokerCallBlockedError(
            f"CLAUDE_AGENT_NO_BROKER is set; refusing to perform {op!r}. "
            "Mock the broker in tests."
        )


def connect_ibkr(
    *,
    host: str,
    port: int,
    client_id: int,
    max_retries: int = 3,
    backoff_s: float = 5.0,
    timeout_s: int = 10,
) -> IB:
    """Connect to TWS / IB Gateway with retries and exponential-ish backoff.

    Returns a connected ``IB`` instance. Caller is responsible for calling
    ``ib.disconnect()`` (use ``with`` block via ``ibkr_session()``).
    """
    _check_guard("connect_ibkr")
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        ib = IB()
        try:
            ib.connect(host, port, clientId=client_id, timeout=timeout_s)
            if ib.isConnected():
                return ib
            last_err = ConnectionError(f"connect succeeded but isConnected() == False")
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries:
                time.sleep(backoff_s)
    raise IBKRConnectionError(
        f"Failed to connect to IBKR at {host}:{port} after {max_retries} attempts: {last_err}"
    )


def get_position(ib: IB, symbol: str) -> int:
    """Return the integer share count for ``symbol`` (0 if no position).

    Matches by contract symbol prefix — Xetra symbols like ``WSPL.DE`` come
    back from IBKR as ``WSPL`` (no exchange suffix), so we strip the suffix
    when comparing.
    """
    short = symbol.split(".")[0]
    for pos in ib.positions():
        if pos.contract.symbol == short:
            return int(pos.position)
    return 0


def get_account_value(ib: IB, currency: str = "EUR") -> float:
    """Return Net Liquidation value in the requested currency."""
    for av in ib.accountSummary():
        if av.tag == "NetLiquidation" and av.currency == currency:
            return float(av.value)
    raise RuntimeError(f"No NetLiquidation entry in {currency} found in accountSummary")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/ibkr_broker.py tests/test_tools_ibkr_broker.py requirements.txt
git commit -m "feat(broker): IBKR connect + read-only helpers (with #168 guard)"
```

---

## Task 6: IBKR broker — order placement with fill polling

**Files:**
- Modify: `tools/ibkr_broker.py`
- Modify: `tests/test_tools_ibkr_broker.py`

**Context:** Add `place_market_order(ib, symbol, side, qty)`. Submits a market order, waits up to 30s for fill, returns `{"order_id": ..., "fill_price": ..., "fill_time": ...}`. Honors `CLAUDE_AGENT_NO_BROKER`. On timeout, cancels the order and raises `OrderTimeoutError`.

`ib_insync` order flow (verify during impl):
- `contract = Stock(symbol_short, exchange='SMART', currency='EUR')` — for WSPL, exchange may need to be `IBIS` or `XETRA`; verify via `ib.qualifyContracts`.
- `order = MarketOrder(action='BUY', totalQuantity=qty)`
- `trade = ib.placeOrder(contract, order)`
- Block on fill: `ib.sleep(0.5)` in a loop, check `trade.isDone()`, then `trade.fills[0].execution.price`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tools_ibkr_broker.py`:

```python
def _mock_filled_trade(price: float, qty: int, order_id: str = "ORD-1"):
    trade = MagicMock()
    trade.isDone.return_value = True
    fill = MagicMock()
    fill.execution.price = price
    fill.execution.shares = qty
    fill.execution.execId = "EXEC-1"
    fill.time = "2026-05-07T14:30:01"
    trade.fills = [fill]
    trade.order.orderId = order_id
    return trade


def test_place_market_order_returns_fill_dict_on_buy():
    mock_ib = MagicMock()
    qualified = MagicMock(); qualified.symbol = "WSPL"
    mock_ib.qualifyContracts.return_value = [qualified]
    mock_ib.placeOrder.return_value = _mock_filled_trade(price=50.0, qty=100, order_id="42")
    mock_ib.sleep = MagicMock()  # no real sleep

    from tools.ibkr_broker import place_market_order
    result = place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=100,
                                 fill_timeout_s=5, poll_interval_s=0.01)
    assert result["order_id"] == "42"
    assert result["fill_price"] == 50.0
    assert result["qty"] == 100
    assert mock_ib.placeOrder.called


def test_place_market_order_timeout_cancels_and_raises():
    mock_ib = MagicMock()
    qualified = MagicMock(); qualified.symbol = "WSPL"
    mock_ib.qualifyContracts.return_value = [qualified]
    pending = MagicMock(); pending.isDone.return_value = False
    pending.fills = []
    mock_ib.placeOrder.return_value = pending
    mock_ib.sleep = MagicMock()

    from tools.ibkr_broker import place_market_order, OrderTimeoutError
    with pytest.raises(OrderTimeoutError):
        place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=100,
                           fill_timeout_s=0.05, poll_interval_s=0.01)
    mock_ib.cancelOrder.assert_called_once()


def test_place_market_order_validates_side():
    mock_ib = MagicMock()
    from tools.ibkr_broker import place_market_order
    with pytest.raises(ValueError, match="side"):
        place_market_order(mock_ib, symbol="WSPL.DE", side="HOLD", qty=100)


def test_place_market_order_validates_qty():
    mock_ib = MagicMock()
    from tools.ibkr_broker import place_market_order
    with pytest.raises(ValueError, match="qty"):
        place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=0)


def test_place_market_order_blocked_by_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    mock_ib = MagicMock()
    from tools.ibkr_broker import place_market_order, BrokerCallBlockedError
    with pytest.raises(BrokerCallBlockedError):
        place_market_order(mock_ib, symbol="WSPL.DE", side="BUY", qty=100)
    mock_ib.placeOrder.assert_not_called()
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v -k "place_market"`
Expected: FAIL with `ImportError: cannot import name 'place_market_order'`.

- [ ] **Step 3: Implement `place_market_order`**

Append to `tools/ibkr_broker.py`:

```python
class OrderTimeoutError(RuntimeError):
    """Raised when a market order does not fill within the polling window."""


def _qualify_contract(ib: IB, symbol: str):
    """Resolve the IBKR contract for a given Xetra/SMART symbol."""
    short = symbol.split(".")[0]
    suffix = symbol.split(".")[1] if "." in symbol else ""
    # Xetra-listed UCITS: exchange='IBIS', currency='EUR' (verify with TWS)
    # Generic fallback: exchange='SMART'
    if suffix.upper() == "DE":
        contract = Stock(short, exchange="IBIS", currency="EUR")
    else:
        contract = Stock(short, exchange="SMART", currency="USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise RuntimeError(f"Could not qualify contract for {symbol!r}")
    return qualified[0]


def place_market_order(
    ib: IB,
    *,
    symbol: str,
    side: str,
    qty: int,
    fill_timeout_s: float = 30.0,
    poll_interval_s: float = 0.5,
) -> dict:
    """Submit a market order and wait for fill. Returns fill details on success.

    Raises:
        OrderTimeoutError: if the order doesn't fill within ``fill_timeout_s``.
                          The order is cancelled before raising.
        BrokerCallBlockedError: if the agent-context guard is active.
        ValueError: if ``side`` is not BUY/SELL or ``qty`` <= 0.
    """
    _check_guard("place_market_order")
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be 'BUY' or 'SELL', got {side!r}")
    if qty <= 0:
        raise ValueError(f"qty must be > 0, got {qty}")

    contract = _qualify_contract(ib, symbol)
    order = MarketOrder(side, qty)
    trade = ib.placeOrder(contract, order)

    # Poll for fill
    waited = 0.0
    while waited < fill_timeout_s:
        if trade.isDone() and trade.fills:
            fill = trade.fills[0]
            return {
                "order_id": str(trade.order.orderId),
                "fill_price": float(fill.execution.price),
                "qty": int(fill.execution.shares),
                "fill_time": str(fill.time),
            }
        ib.sleep(poll_interval_s)
        waited += poll_interval_s

    # Timed out — cancel and raise
    try:
        ib.cancelOrder(order)
    except Exception:  # noqa: BLE001
        pass  # Best-effort cancel
    raise OrderTimeoutError(
        f"{side} {qty} {symbol} did not fill within {fill_timeout_s}s; cancelled"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v -k "place_market"`
Expected: All 5 tests PASS.

- [ ] **Step 5: Run full broker suite**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v`
Expected: All tests (from Tasks 5 and 6) PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/ibkr_broker.py tests/test_tools_ibkr_broker.py
git commit -m "feat(broker): IBKR market-order placement with fill polling + timeout"
```

---

## Task 7: IBKR broker — liquidate, cancel-all, OCO stop

**Files:**
- Modify: `tools/ibkr_broker.py`
- Modify: `tests/test_tools_ibkr_broker.py`

**Context:** Add `liquidate(ib, symbol)` (sell-all market order) and `cancel_all_orders(ib)` (used by panic CLI). All gated by the guard.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tools_ibkr_broker.py`:

```python
def test_liquidate_sells_existing_position():
    mock_ib = MagicMock()
    qualified = MagicMock(); qualified.symbol = "WSPL"
    mock_ib.qualifyContracts.return_value = [qualified]
    pos = MagicMock(); pos.contract.symbol = "WSPL"; pos.position = 100
    mock_ib.positions.return_value = [pos]
    mock_ib.placeOrder.return_value = _mock_filled_trade(price=49.0, qty=100, order_id="L1")
    mock_ib.sleep = MagicMock()

    from tools.ibkr_broker import liquidate
    result = liquidate(mock_ib, symbol="WSPL.DE", fill_timeout_s=5, poll_interval_s=0.01)
    assert result["fill_price"] == 49.0
    args, kwargs = mock_ib.placeOrder.call_args
    submitted_order = args[1]
    assert submitted_order.action == "SELL"
    assert submitted_order.totalQuantity == 100


def test_liquidate_no_position_returns_none():
    mock_ib = MagicMock()
    mock_ib.positions.return_value = []
    from tools.ibkr_broker import liquidate
    result = liquidate(mock_ib, symbol="WSPL.DE")
    assert result is None
    mock_ib.placeOrder.assert_not_called()


def test_liquidate_blocked_by_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    mock_ib = MagicMock()
    from tools.ibkr_broker import liquidate, BrokerCallBlockedError
    with pytest.raises(BrokerCallBlockedError):
        liquidate(mock_ib, symbol="WSPL.DE")


def test_cancel_all_orders_calls_cancel_for_each_open():
    mock_ib = MagicMock()
    o1 = MagicMock(); o1.orderId = 1
    o2 = MagicMock(); o2.orderId = 2
    trade1 = MagicMock(); trade1.order = o1; trade1.isDone.return_value = False
    trade2 = MagicMock(); trade2.order = o2; trade2.isDone.return_value = False
    mock_ib.openTrades.return_value = [trade1, trade2]

    from tools.ibkr_broker import cancel_all_orders
    n = cancel_all_orders(mock_ib)
    assert n == 2
    assert mock_ib.cancelOrder.call_count == 2


def test_cancel_all_orders_blocked_by_guard(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "true")
    mock_ib = MagicMock()
    from tools.ibkr_broker import cancel_all_orders, BrokerCallBlockedError
    with pytest.raises(BrokerCallBlockedError):
        cancel_all_orders(mock_ib)
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v -k "liquidate or cancel_all"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `liquidate` and `cancel_all_orders`**

Append to `tools/ibkr_broker.py`:

```python
def liquidate(
    ib: IB,
    *,
    symbol: str,
    fill_timeout_s: float = 30.0,
    poll_interval_s: float = 0.5,
) -> Optional[dict]:
    """Sell all of `symbol`. Returns fill dict on success, None if no position.

    Wraps `place_market_order` with side=SELL and qty=current position.
    """
    _check_guard("liquidate")
    qty = get_position(ib, symbol)
    if qty <= 0:
        return None
    return place_market_order(
        ib,
        symbol=symbol,
        side="SELL",
        qty=qty,
        fill_timeout_s=fill_timeout_s,
        poll_interval_s=poll_interval_s,
    )


def cancel_all_orders(ib: IB) -> int:
    """Cancel every open order. Returns count cancelled."""
    _check_guard("cancel_all_orders")
    open_trades = [t for t in ib.openTrades() if not t.isDone()]
    for trade in open_trades:
        try:
            ib.cancelOrder(trade.order)
        except Exception:  # noqa: BLE001
            pass  # Best-effort
    return len(open_trades)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tools_ibkr_broker.py -v`
Expected: All tests (Tasks 5+6+7) PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/ibkr_broker.py tests/test_tools_ibkr_broker.py
git commit -m "feat(broker): IBKR liquidate + cancel-all-orders (panic-CLI primitives)"
```

---

## Task 8: Notifications — new event types

**Files:**
- Modify: `tools/notifications.py`
- Modify: `tests/test_notifications.py`

**Context:** The Discord/n8n notifier needs new event types: `regime_flip`, `kill_switch_fired`, `trade_filled`, `trade_failed`, `tws_disconnected`, `state_desync`. Each builds a JSON payload with consistent shape and posts to `N8N_WEBHOOK_URL`. Existing helpers (`notify_error`, `notify_performance_summary`, etc.) stay — they're still used by panic CLI / summary mode.

- [ ] **Step 1: Inspect current notification helpers**

Run: `head -80 tools/notifications.py`

Note the JSON shape: `{event_type, ...event_specific_fields}`.

- [ ] **Step 2: Write failing tests for each new event type**

Add to `tests/test_notifications.py`:

```python
def test_notify_regime_flip_long_payload():
    captured = {}
    def fake_post(url, data, headers):
        captured["url"] = url
        captured["data"] = json.loads(data)
        return MagicMock(status=200)

    with patch("urllib.request.urlopen", side_effect=lambda req, timeout=None:
               fake_post(req.full_url, req.data, req.headers)):
        from tools.notifications import notify_regime_flip
        notify_regime_flip(target_state="LONG", spy_close=400.0, spy_sma200=380.0,
                           ticker="WSPL.DE", fill_price=50.0, qty=100, account_value=10000.0)

    payload = captured["data"]
    assert payload["event_type"] == "regime_flip"
    assert payload["target_state"] == "LONG"
    assert payload["ticker"] == "WSPL.DE"
    assert payload["fill_price"] == 50.0


def test_notify_kill_switch_fired_payload():
    captured = {}
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.side_effect = lambda req, timeout=None: captured.update(
            data=json.loads(req.data)) or MagicMock(status=200)
        from tools.notifications import notify_kill_switch_fired
        notify_kill_switch_fired(ticker="WSPL.DE", drawdown_pct=-0.27,
                                 ref_high=68.5, last_price=50.0, qty=100,
                                 fill_price=49.5)
    payload = captured["data"]
    assert payload["event_type"] == "kill_switch_fired"
    assert payload["drawdown_pct"] == -0.27
    assert payload["fill_price"] == 49.5


def test_notify_trade_failed_payload():
    captured = {}
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.side_effect = lambda req, timeout=None: captured.update(
            data=json.loads(req.data)) or MagicMock(status=200)
        from tools.notifications import notify_trade_failed
        notify_trade_failed(symbol="WSPL.DE", side="BUY", qty=100,
                            reason="insufficient_buying_power")
    payload = captured["data"]
    assert payload["event_type"] == "trade_failed"
    assert payload["reason"] == "insufficient_buying_power"


def test_notify_tws_disconnected_payload():
    captured = {}
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.side_effect = lambda req, timeout=None: captured.update(
            data=json.loads(req.data)) or MagicMock(status=200)
        from tools.notifications import notify_tws_disconnected
        notify_tws_disconnected(host="127.0.0.1", port=4002,
                                attempts=3, error_msg="connect refused")
    payload = captured["data"]
    assert payload["event_type"] == "tws_disconnected"
    assert payload["attempts"] == 3


def test_notify_state_desync_payload():
    captured = {}
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.side_effect = lambda req, timeout=None: captured.update(
            data=json.loads(req.data)) or MagicMock(status=200)
        from tools.notifications import notify_state_desync
        notify_state_desync(db_state="LONG", broker_state="CASH",
                            symbol="WSPL.DE", action_taken="DB updated to CASH")
    payload = captured["data"]
    assert payload["event_type"] == "state_desync"
    assert payload["db_state"] == "LONG"
    assert payload["broker_state"] == "CASH"


def test_silent_when_webhook_unset(monkeypatch):
    """Notifier must not raise if N8N_WEBHOOK_URL is empty."""
    monkeypatch.setenv("N8N_WEBHOOK_URL", "")
    import importlib, tools.notifications as n
    importlib.reload(n)
    n.notify_regime_flip(target_state="LONG", spy_close=400.0, spy_sma200=380.0,
                          ticker="WSPL.DE", fill_price=50.0, qty=100, account_value=10000.0)
    # No exception — passing test.
```

- [ ] **Step 3: Run failing tests**

Run: `python3 -m pytest tests/test_notifications.py -v -k "regime_flip or kill_switch or trade_failed or tws_disconnected or state_desync or silent_when_webhook"`
Expected: FAIL with `ImportError` for the new helpers.

- [ ] **Step 4: Implement the new helpers**

Append to `tools/notifications.py`:

```python
def notify_regime_flip(
    *,
    target_state: str,
    spy_close: float,
    spy_sma200: float,
    ticker: str,
    fill_price: float,
    qty: int,
    account_value: float,
) -> None:
    _post({
        "event_type": "regime_flip",
        "target_state": target_state,
        "spy_close": spy_close,
        "spy_sma200": spy_sma200,
        "ticker": ticker,
        "fill_price": fill_price,
        "qty": qty,
        "account_value": account_value,
    })


def notify_kill_switch_fired(
    *,
    ticker: str,
    drawdown_pct: float,
    ref_high: float,
    last_price: float,
    qty: int,
    fill_price: float,
) -> None:
    _post({
        "event_type": "kill_switch_fired",
        "ticker": ticker,
        "drawdown_pct": drawdown_pct,
        "ref_high": ref_high,
        "last_price": last_price,
        "qty": qty,
        "fill_price": fill_price,
    })


def notify_trade_failed(
    *,
    symbol: str,
    side: str,
    qty: int,
    reason: str,
) -> None:
    _post({
        "event_type": "trade_failed",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "reason": reason,
    })


def notify_tws_disconnected(
    *,
    host: str,
    port: int,
    attempts: int,
    error_msg: str,
) -> None:
    _post({
        "event_type": "tws_disconnected",
        "host": host,
        "port": port,
        "attempts": attempts,
        "error_msg": error_msg,
    })


def notify_state_desync(
    *,
    db_state: str,
    broker_state: str,
    symbol: str,
    action_taken: str,
) -> None:
    _post({
        "event_type": "state_desync",
        "db_state": db_state,
        "broker_state": broker_state,
        "symbol": symbol,
        "action_taken": action_taken,
    })
```

(`_post` is the existing private helper that does the URL POST and silently swallows errors.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_notifications.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/notifications.py tests/test_notifications.py
git commit -m "feat(notify): regime_flip / kill_switch / trade_failed / tws_disconnected / state_desync events"
```

---

## Task 9: Daily check entry point (`daily_check.py`)

**Files:**
- Create: `daily_check.py`
- Test: `tests/test_daily_check.py`

**Context:** Top-level script that ties everything together. Wraps the entire flow in an `audit_log` row (started_at on entry, finished_at + outcome in `finally`). Mocks needed for tests: `yfinance.download`, `tools.ibkr_broker` functions, `tools.notifications` functions, the DB.

This script is what cron runs once per weekday after US close.

- [ ] **Step 1: Write the integration test suite**

Create `tests/test_daily_check.py`:

```python
"""Integration tests for daily_check.py.

All external dependencies (yfinance, IBKR, notifications, DB) are mocked.
The CLAUDE_AGENT_NO_BROKER conftest fixture ensures any forgotten mock
fails fast.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from storage.init_db import init_db


def _seed_spy_history(close=400.0, sma_value=380.0, days=210):
    """Build a fake SPY OHLC frame whose 200-day SMA equals `sma_value` and
    today's close equals `close`."""
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    closes = np.full(days, sma_value, dtype=float)
    closes[-1] = close
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                       "Close": closes, "Volume": 1_000_000}, index=dates)
    return df


def _patch_all(yf_df, broker_overrides=None):
    """Patch yfinance + ibkr_broker + notifications. Returns ctxs as list."""
    broker_overrides = broker_overrides or {}
    return [
        patch("daily_check.yf.download", return_value=yf_df),
        patch("daily_check.connect_ibkr", return_value=MagicMock()),
        patch("daily_check.get_position",
              return_value=broker_overrides.get("get_position", 0)),
        patch("daily_check.get_account_value",
              return_value=broker_overrides.get("get_account_value", 10000.0)),
        patch("daily_check.place_market_order",
              return_value=broker_overrides.get(
                  "place_market_order",
                  {"order_id": "ORD-1", "fill_price": 50.0, "qty": 100,
                   "fill_time": "2026-05-07T13:30:01"})),
        patch("daily_check.liquidate",
              return_value=broker_overrides.get(
                  "liquidate",
                  {"order_id": "ORD-2", "fill_price": 49.0, "qty": 100,
                   "fill_time": "2026-05-07T13:30:01"})),
        patch("daily_check.notify_regime_flip"),
        patch("daily_check.notify_state_desync"),
        patch("daily_check.notify_tws_disconnected"),
        patch("daily_check.notify_trade_failed"),
    ]


def test_bullish_first_run_buys(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    yf_df = _seed_spy_history(close=400.0, sma_value=380.0)
    ctxs = _patch_all(yf_df)
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3], ctxs[4], ctxs[5], ctxs[6], ctxs[7], ctxs[8], ctxs[9]:
        from daily_check import main
        rc = main()
        assert rc == 0

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    trade = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    assert state["target_state"] == "LONG"
    assert state["current_state"] == "LONG"
    assert trade["reason"] == "regime_flip_long"
    assert audit["script_name"] == "daily_check"
    assert audit["outcome"] == "success"


def test_bearish_with_position_sells(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    # Seed DB with current_state=LONG
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=370.0, sma_value=400.0)
    ctxs = _patch_all(yf_df, broker_overrides={"get_position": 100})
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3], ctxs[4], ctxs[5], ctxs[6], ctxs[7], ctxs[8], ctxs[9]:
        from daily_check import main
        rc = main()
        assert rc == 0

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trade = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    assert trade["reason"] == "regime_flip_cash"
    assert state["current_state"] == "CASH"


def test_no_change_no_trade(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=410.0, sma_value=380.0)  # still bullish
    ctxs = _patch_all(yf_df, broker_overrides={"get_position": 100})
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3], ctxs[4], ctxs[5], ctxs[6], ctxs[7], ctxs[8], ctxs[9]:
        from daily_check import main
        place_mock = ctxs[4].new
        rc = main()
        assert rc == 0
        place_mock.assert_not_called()  # no order

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    trades = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
    conn.close()
    assert trades["n"] == 0


def test_state_desync_auto_reconciles(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    # DB says LONG, broker says zero position
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit(); conn.close()

    yf_df = _seed_spy_history(close=410.0, sma_value=380.0)  # bullish
    ctxs = _patch_all(yf_df, broker_overrides={"get_position": 0})  # broker: no position
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3], ctxs[4], ctxs[5], ctxs[6], ctxs[7], ctxs[8], ctxs[9]:
        from daily_check import main
        desync_mock = ctxs[7].new
        rc = main()
        assert rc == 0
        desync_mock.assert_called_once()  # desync notification fired

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    # After reconcile, DB will buy back to LONG since regime is bullish
    assert state["current_state"] == "LONG"


def test_tws_connection_failure_aborts_cycle(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    yf_df = _seed_spy_history(close=400.0, sma_value=380.0)
    from tools.ibkr_broker import IBKRConnectionError
    with patch("daily_check.yf.download", return_value=yf_df), \
         patch("daily_check.connect_ibkr", side_effect=IBKRConnectionError("no TWS")), \
         patch("daily_check.notify_tws_disconnected") as notify_mock:
        from daily_check import main
        rc = main()
        assert rc == 1  # non-zero exit
        notify_mock.assert_called_once()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"].startswith("error:")


def test_stale_data_skips(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr("daily_check.DB_PATH", str(db))

    # Build a frame whose last bar is 2 days old
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=2), periods=210)
    closes = np.full(210, 380.0)
    yf_df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                          "Close": closes, "Volume": 1_000_000}, index=dates)

    with patch("daily_check.yf.download", return_value=yf_df), \
         patch("daily_check.connect_ibkr", return_value=MagicMock()), \
         patch("daily_check.place_market_order") as place_mock:
        from daily_check import main
        rc = main()
        assert rc == 0  # not an error, but no trade
        place_mock.assert_not_called()
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_daily_check.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `daily_check.py`**

Create `daily_check.py` (in repo root):

```python
"""Daily regime-filter check + IBKR position flip.

Scheduled by cron `30 22 * * 1-5` UTC (≥1.5h after US close, gives yfinance
time to publish the daily bar).

Flow:
    1. Fetch SPY history.
    2. Compute 200-day SMA and today's regime decision.
    3. Reconcile bot DB state with IBKR broker truth (auto-reconcile on desync).
    4. If target != current, place market order on BOT_TICKER via IBKR.
    5. Update DB rows (regime_state, trades, audit_log).
    6. Notify Discord.

Designed to be idempotent: a second run on the same trading day computes the
same target_state, sees current_state already matches, and writes a no-op
regime_state row.
"""
from __future__ import annotations

import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import settings
from strategy.regime import compute_target_state
from tools.ibkr_broker import (
    BrokerCallBlockedError,
    IBKRConnectionError,
    OrderTimeoutError,
    cancel_all_orders,
    connect_ibkr,
    get_account_value,
    get_position,
    liquidate,
    place_market_order,
)
from tools.notifications import (
    notify_regime_flip,
    notify_state_desync,
    notify_trade_failed,
    notify_tws_disconnected,
)
from tools.database import (
    get_latest_regime_state,
    insert_audit_log,
    insert_trade,
    update_audit_log,
    upsert_regime_state,
)

DB_PATH = "trading_bot.db"


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    """Entry point. Returns 0 on success, 1 on error."""
    started = _now_iso()
    conn = _open_db()
    audit_id = insert_audit_log(conn, script_name="daily_check", started_at=started)

    try:
        # 1. Fetch SPY data
        spy_df = yf.download(
            settings.BOT_BENCHMARK,
            period="2y",
            auto_adjust=True,
            progress=False,
        )
        if isinstance(spy_df.columns, pd.MultiIndex):
            spy_df.columns = spy_df.columns.get_level_values(0)
        spy_df = spy_df.dropna()

        # Stale-data check: is the last bar from today (UTC)?
        last_bar_date = spy_df.index[-1].date()
        today_utc = datetime.now(timezone.utc).date()
        if last_bar_date < today_utc:
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="skipped:stale_data",
                             notes=f"last bar={last_bar_date}, today={today_utc}")
            return 0

        spy_close = float(spy_df["Close"].iloc[-1])
        spy_sma = float(spy_df["Close"].rolling(settings.REGIME_SMA_DAYS).mean().iloc[-1])

        # 2. Compute regime decision
        latest = get_latest_regime_state(conn)
        current_state = latest["current_state"] if latest else "CASH"
        kill_switch_active = bool(latest["kill_switch_active"]) if latest else False

        target_state, new_ks = compute_target_state(
            spy_close=spy_close, spy_sma200=spy_sma,
            current_state=current_state, kill_switch_active=kill_switch_active,
        )

        # 3. Connect to IBKR + reconcile
        try:
            ib = connect_ibkr(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                              client_id=settings.IBKR_CLIENT_ID)
        except IBKRConnectionError as e:
            notify_tws_disconnected(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                                    attempts=3, error_msg=str(e))
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome=f"error:tws_disconnect", notes=str(e))
            return 1

        try:
            qty = get_position(ib, settings.BOT_TICKER)
            broker_state = "LONG" if qty > 0 else "CASH"

            if broker_state != current_state:
                notify_state_desync(
                    db_state=current_state,
                    broker_state=broker_state,
                    symbol=settings.BOT_TICKER,
                    action_taken=f"DB updated to {broker_state}",
                )
                current_state = broker_state
                # Re-compute target with reconciled current state
                target_state, new_ks = compute_target_state(
                    spy_close=spy_close, spy_sma200=spy_sma,
                    current_state=current_state, kill_switch_active=kill_switch_active,
                )

            # 4. Flip position if needed
            position_dd_pct = None
            if target_state != current_state:
                if target_state == "LONG":
                    account_value = get_account_value(ib, currency="EUR")
                    # Buy size: (account_value * 0.99) / vehicle_price
                    # Need a fresh quote — use SPY's last close as proxy is wrong.
                    # Fetch BOT_TICKER's latest close from yfinance.
                    vehicle_df = yf.download(
                        settings.BOT_TICKER, period="5d",
                        auto_adjust=True, progress=False,
                    )
                    if isinstance(vehicle_df.columns, pd.MultiIndex):
                        vehicle_df.columns = vehicle_df.columns.get_level_values(0)
                    vehicle_close = float(vehicle_df["Close"].dropna().iloc[-1])
                    target_qty = int((account_value * 0.99) / vehicle_close)
                    if target_qty <= 0:
                        notify_trade_failed(symbol=settings.BOT_TICKER, side="BUY",
                                            qty=0, reason="insufficient_buying_power")
                        update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                                         outcome="error:insufficient_funds")
                        return 1
                    fill = place_market_order(ib, symbol=settings.BOT_TICKER,
                                              side="BUY", qty=target_qty)
                    insert_trade(conn,
                                 symbol=settings.BOT_TICKER, side="BUY",
                                 qty=fill["qty"], fill_price=fill["fill_price"],
                                 fill_time=fill["fill_time"],
                                 ibkr_order_id=fill["order_id"],
                                 reason="regime_flip_long")
                    notify_regime_flip(
                        target_state="LONG", spy_close=spy_close, spy_sma200=spy_sma,
                        ticker=settings.BOT_TICKER, fill_price=fill["fill_price"],
                        qty=fill["qty"], account_value=account_value,
                    )
                    current_state = "LONG"
                else:  # CASH — sell all
                    fill = liquidate(ib, symbol=settings.BOT_TICKER)
                    if fill:
                        insert_trade(conn,
                                     symbol=settings.BOT_TICKER, side="SELL",
                                     qty=fill["qty"], fill_price=fill["fill_price"],
                                     fill_time=fill["fill_time"],
                                     ibkr_order_id=fill["order_id"],
                                     reason="regime_flip_cash")
                        notify_regime_flip(
                            target_state="CASH", spy_close=spy_close, spy_sma200=spy_sma,
                            ticker=settings.BOT_TICKER, fill_price=fill["fill_price"],
                            qty=fill["qty"], account_value=get_account_value(ib, currency="EUR"),
                        )
                    current_state = "CASH"

            # 5. Update DB
            upsert_regime_state(
                conn,
                date=_today_iso(),
                spy_close=spy_close, spy_sma200=spy_sma,
                target_state=target_state, current_state=current_state,
                position_drawdown_pct=position_dd_pct,
                kill_switch_active=new_ks,
                kill_switch_fired_at=(latest["kill_switch_fired_at"]
                                       if latest and new_ks else None),
            )
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success",
                             notes=f"target={target_state} current={current_state}")
            return 0
        finally:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                         outcome=f"error:{type(e).__name__}", notes=tb[:500])
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_daily_check.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -x -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add daily_check.py tests/test_daily_check.py
git commit -m "feat: daily_check.py — regime-filter entry point with auto-reconcile"
```

---

## Task 10: Hourly kill-switch (`monitor/kill_switch.py`)

**Files:**
- Create: `monitor/kill_switch.py`
- Test: `tests/test_monitor_kill_switch.py`

**Context:** Hourly cron during US market hours. Reads current state from DB. If LONG, fetches the vehicle's last price + 30-trading-day rolling high, computes drawdown. If drawdown exceeds threshold, liquidates and sets `kill_switch_active=1`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_monitor_kill_switch.py`:

```python
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from storage.init_db import init_db


def _seed_vehicle_history(prices):
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(prices))
    df = pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                       "Close": prices, "Volume": 1_000_000}, index=dates)
    return df


def _seed_db_with_long_position(db_path):
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit()
    conn.close()


def test_no_op_when_in_cash(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    init_db(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))
    # No regime_state row — defaults to CASH

    with patch("monitor.kill_switch.connect_ibkr") as connect_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        connect_mock.assert_not_called()


def test_no_op_when_drawdown_within_threshold(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    # 30 days of slowly rising prices, today only -10% from high
    prices = np.concatenate([np.linspace(50, 60, 25), [54.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr") as connect_mock, \
         patch("monitor.kill_switch.liquidate") as liq_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        connect_mock.assert_not_called()  # no IBKR call needed
        liq_mock.assert_not_called()


def test_kill_switch_fires_on_threshold_breach(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    # 30 days where high was 100, now 70 (-30% drawdown)
    prices = np.concatenate([np.linspace(50, 100, 25), [70.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr", return_value=MagicMock()), \
         patch("monitor.kill_switch.liquidate") as liq_mock, \
         patch("monitor.kill_switch.get_position", return_value=100), \
         patch("monitor.kill_switch.notify_kill_switch_fired") as notify_mock:
        liq_mock.return_value = {"order_id": "K1", "fill_price": 69.5,
                                  "qty": 100, "fill_time": "2026-05-07T15:30:00"}
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        liq_mock.assert_called_once()
        notify_mock.assert_called_once()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    trade = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert state["kill_switch_active"] == 1
    assert state["current_state"] == "CASH"
    assert trade["reason"] == "kill_switch"


def test_liquidate_failure_escalates(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    prices = np.concatenate([np.linspace(50, 100, 25), [70.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    from tools.ibkr_broker import OrderTimeoutError
    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr", return_value=MagicMock()), \
         patch("monitor.kill_switch.liquidate", side_effect=OrderTimeoutError("oops")), \
         patch("monitor.kill_switch.get_position", return_value=100), \
         patch("monitor.kill_switch.notify_kill_switch_fired"), \
         patch("monitor.kill_switch.notify_trade_failed") as fail_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 1  # error exit
        fail_mock.assert_called()
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_monitor_kill_switch.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `monitor/kill_switch.py`**

Create `monitor/kill_switch.py`:

```python
"""Hourly drawdown kill-switch.

Scheduled by cron `5 14-21 * * 1-5` UTC (8 fires across US market hours).

Flow:
    1. Read latest regime_state from DB.
    2. If current_state != LONG: exit (nothing to protect).
    3. Fetch vehicle's last KILL_SWITCH_LOOKBACK_DAYS bars; compute rolling high.
    4. drawdown = (last_price / high) - 1
    5. If drawdown <= -KILL_SWITCH_DRAWDOWN_PCT: liquidate, notify, update DB.
"""
from __future__ import annotations

import sqlite3
import sys
import traceback
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from config import settings
from tools.ibkr_broker import (
    IBKRConnectionError, OrderTimeoutError,
    connect_ibkr, get_position, liquidate,
)
from tools.notifications import (
    notify_kill_switch_fired,
    notify_trade_failed,
    notify_tws_disconnected,
)
from tools.database import (
    get_latest_regime_state,
    insert_audit_log,
    insert_trade,
    update_audit_log,
    upsert_regime_state,
)

DB_PATH = "trading_bot.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    started = _now_iso()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    audit_id = insert_audit_log(conn, script_name="kill_switch", started_at=started)

    try:
        latest = get_latest_regime_state(conn)
        if not latest or latest["current_state"] != "LONG":
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success:no_position")
            return 0

        # Fetch vehicle history
        df = yf.download(settings.BOT_TICKER, period="60d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df["Close"].dropna()
        if len(df) < settings.KILL_SWITCH_LOOKBACK_DAYS:
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="skipped:insufficient_data",
                             notes=f"only {len(df)} bars, need {settings.KILL_SWITCH_LOOKBACK_DAYS}")
            return 0

        last_price = float(df.iloc[-1])
        ref_high = float(df.iloc[-settings.KILL_SWITCH_LOOKBACK_DAYS:].max())
        drawdown = last_price / ref_high - 1

        # Update position_drawdown_pct in regime_state for visibility
        upsert_regime_state(
            conn,
            date=_today_iso(),
            spy_close=latest["spy_close"], spy_sma200=latest["spy_sma200"],
            target_state=latest["target_state"], current_state="LONG",
            position_drawdown_pct=drawdown,
            kill_switch_active=bool(latest["kill_switch_active"]),
            kill_switch_fired_at=latest["kill_switch_fired_at"],
        )

        if drawdown > -settings.KILL_SWITCH_DRAWDOWN_PCT:
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success:within_threshold",
                             notes=f"dd={drawdown:.4f}")
            return 0

        # Threshold breached — connect, liquidate
        try:
            ib = connect_ibkr(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                              client_id=settings.IBKR_CLIENT_ID)
        except IBKRConnectionError as e:
            notify_tws_disconnected(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                                    attempts=3, error_msg=str(e))
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="error:tws_disconnect_during_kill_switch",
                             notes=str(e))
            return 1

        try:
            qty = get_position(ib, settings.BOT_TICKER)
            try:
                fill = liquidate(ib, symbol=settings.BOT_TICKER)
            except OrderTimeoutError as e:
                notify_trade_failed(symbol=settings.BOT_TICKER, side="SELL",
                                    qty=qty, reason=f"kill_switch_timeout:{e}")
                update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                                 outcome="error:kill_switch_liquidate_failed",
                                 notes=str(e))
                return 1

            if fill is None:
                # Position vanished between our position read and liquidate — auto-reconcile
                upsert_regime_state(
                    conn,
                    date=_today_iso(),
                    spy_close=latest["spy_close"], spy_sma200=latest["spy_sma200"],
                    target_state="CASH", current_state="CASH",
                    position_drawdown_pct=drawdown,
                    kill_switch_active=True, kill_switch_fired_at=_now_iso(),
                )
                update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                                 outcome="success:no_position_to_liquidate")
                return 0

            insert_trade(
                conn,
                symbol=settings.BOT_TICKER, side="SELL",
                qty=fill["qty"], fill_price=fill["fill_price"],
                fill_time=fill["fill_time"], ibkr_order_id=fill["order_id"],
                reason="kill_switch",
            )
            upsert_regime_state(
                conn,
                date=_today_iso(),
                spy_close=latest["spy_close"], spy_sma200=latest["spy_sma200"],
                target_state="CASH", current_state="CASH",
                position_drawdown_pct=drawdown,
                kill_switch_active=True, kill_switch_fired_at=_now_iso(),
            )
            notify_kill_switch_fired(
                ticker=settings.BOT_TICKER,
                drawdown_pct=drawdown,
                ref_high=ref_high,
                last_price=last_price,
                qty=fill["qty"],
                fill_price=fill["fill_price"],
            )
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success:kill_switch_fired",
                             notes=f"dd={drawdown:.4f}")
            return 0
        finally:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                         outcome=f"error:{type(e).__name__}", notes=tb[:500])
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_monitor_kill_switch.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -x -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add monitor/kill_switch.py tests/test_monitor_kill_switch.py
git commit -m "feat(monitor): hourly drawdown kill-switch with auto-liquidate"
```

---

## Task 11: Migrate panic CLI to IBKR

**Files:**
- Modify: `main.py` (panic mode block)
- Modify: `tests/test_main_panic.py`

**Context:** The existing `main.py panic` calls `tools.broker.cancel_all_orders` and `tools.broker.liquidate_all_positions` (Alpaca). Replace with `tools.ibkr_broker.cancel_all_orders` and `tools.ibkr_broker.liquidate(BOT_TICKER)`. Same flags, same audit-log behaviour, same `.env` write.

- [ ] **Step 1: Inspect current panic implementation**

Run: `grep -n "panic\|cancel_all_orders\|liquidate_all" main.py | head -20`

Note the current structure of the `elif mode == "panic":` block.

- [ ] **Step 2: Update panic-mode tests**

Replace the contents of `tests/test_main_panic.py` (or the relevant section) with:

```python
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from storage.init_db import init_db


def test_panic_cancel_orders_uses_ibkr(tmp_path, monkeypatch):
    db = tmp_path / "p.db"
    init_db(db)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("main.DB_PATH", str(db), raising=False)

    with patch("main.connect_ibkr", return_value=MagicMock()) as connect_mock, \
         patch("main.cancel_all_orders", return_value=2) as cancel_mock, \
         patch("sys.argv", ["main.py", "panic", "--cancel-orders"]):
        from main import main as run
        rc = run()
        assert rc == 0
        cancel_mock.assert_called_once()


def test_panic_liquidate_requires_confirm(tmp_path, monkeypatch):
    db = tmp_path / "p.db"
    init_db(db)
    monkeypatch.chdir(tmp_path)

    with patch("sys.argv", ["main.py", "panic", "--liquidate"]):
        from main import main as run
        rc = run()
        assert rc != 0  # rejected without --confirm


def test_panic_liquidate_with_confirm_uses_ibkr(tmp_path, monkeypatch):
    db = tmp_path / "p.db"
    init_db(db)
    monkeypatch.chdir(tmp_path)

    with patch("main.connect_ibkr", return_value=MagicMock()), \
         patch("main.liquidate",
               return_value={"order_id": "P1", "fill_price": 49.0,
                             "qty": 100, "fill_time": "2026-05-07T15:00:00"}) as liq_mock, \
         patch("sys.argv", ["main.py", "panic", "--liquidate", "--confirm"]):
        from main import main as run
        rc = run()
        assert rc == 0
        liq_mock.assert_called_once()


def test_panic_pause_writes_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TRADING_MODE=paper\nTRADING_PAUSED=false\n")

    with patch("sys.argv", ["main.py", "panic", "--pause"]):
        from main import main as run
        rc = run()
        assert rc == 0

    text = (tmp_path / ".env").read_text()
    assert "TRADING_PAUSED=true" in text
```

- [ ] **Step 3: Run failing tests**

Run: `python3 -m pytest tests/test_main_panic.py -v`
Expected: Some FAIL (panic block still calls Alpaca).

- [ ] **Step 4: Update `main.py` panic block**

Find the `elif mode == "panic":` block in `main.py` and replace its contents (preserving the argparse and audit-log structure):

```python
    elif mode == "panic":
        import argparse
        from tools.ibkr_broker import (
            connect_ibkr, cancel_all_orders, liquidate, IBKRConnectionError,
        )
        from tools.database import insert_audit_log, update_audit_log
        from datetime import datetime, timezone
        from pathlib import Path

        parser = argparse.ArgumentParser(prog="main.py panic")
        parser.add_argument("--cancel-orders", action="store_true",
                            help="Cancel all open orders.")
        parser.add_argument("--liquidate", action="store_true",
                            help="Market-close all positions (requires --confirm).")
        parser.add_argument("--confirm", action="store_true",
                            help="Confirm destructive --liquidate.")
        parser.add_argument("--pause", action="store_true",
                            help="Set TRADING_PAUSED=true in .env (no broker call).")
        args = parser.parse_args(sys.argv[2:])

        if args.liquidate and not args.confirm:
            print("ERROR: --liquidate requires --confirm")
            return 2

        conn = get_db()
        audit_id = insert_audit_log(
            conn, script_name="panic",
            started_at=datetime.now(timezone.utc).isoformat(),
            notes=f"args: {vars(args)}",
        )
        outcome_parts = []
        try:
            ib = None
            if args.cancel_orders or args.liquidate:
                try:
                    ib = connect_ibkr(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                                      client_id=settings.IBKR_CLIENT_ID)
                except IBKRConnectionError as e:
                    print(f"ERROR: TWS connection failed: {e}")
                    update_audit_log(conn, rowid=audit_id,
                                     finished_at=datetime.now(timezone.utc).isoformat(),
                                     outcome="error:tws_disconnect", notes=str(e))
                    return 1

            if args.cancel_orders:
                n = cancel_all_orders(ib)
                outcome_parts.append(f"cancelled={n}")
                print(f"Cancelled {n} open orders.")
            if args.liquidate:
                fill = liquidate(ib, symbol=settings.BOT_TICKER)
                if fill:
                    outcome_parts.append(f"liquidated qty={fill['qty']} @ {fill['fill_price']}")
                    print(f"Liquidated {fill['qty']} @ {fill['fill_price']}")
                else:
                    outcome_parts.append("liquidate:no_position")
                    print("No position to liquidate.")
            if args.pause:
                # Anchored at repo root, not cwd
                env_path = Path(__file__).resolve().parent / ".env"
                text = env_path.read_text() if env_path.exists() else ""
                if "TRADING_PAUSED=" in text:
                    new_text = "\n".join(
                        "TRADING_PAUSED=true" if line.startswith("TRADING_PAUSED=") else line
                        for line in text.splitlines()
                    ) + "\n"
                else:
                    new_text = text + "TRADING_PAUSED=true\n"
                env_path.write_text(new_text)
                outcome_parts.append("paused")
                print(f"Wrote TRADING_PAUSED=true to {env_path}")

            update_audit_log(conn, rowid=audit_id,
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             outcome="success", notes=" | ".join(outcome_parts))
            if ib:
                try: ib.disconnect()
                except Exception: pass
            return 0
        except Exception as e:  # noqa: BLE001
            update_audit_log(conn, rowid=audit_id,
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             outcome=f"error:{type(e).__name__}", notes=str(e)[:500])
            print(f"ERROR: {e}")
            return 1
        finally:
            conn.close()
```

(Note: `main()` may need refactoring to a function returning an int — wrap the existing `if __name__ == "__main__":` body. The tests assume `from main import main as run`. If `main()` doesn't exist yet, create it as a thin wrapper.)

- [ ] **Step 5: Run panic tests**

Run: `python3 -m pytest tests/test_main_panic.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_panic.py
git commit -m "feat(panic): migrate panic CLI to IBKR broker"
```

---

## Task 12: Remove obsolete settings vars

**Files:**
- Modify: `config/settings.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py` (drop tests for removed vars)

**Context:** Now that the new settings (Task 1) work and the new code (Tasks 3-11) doesn't read the old vars, drop them. List below — anything not deleted goes through one more sweep in Task 16.

- [ ] **Step 1: Identify what reads each old setting**

Run: `grep -rn "MAX_POSITIONS\|MAX_PORTFOLIO_EXPOSURE\|RISK_PER_TRADE\|RR_RATIO_MIN\|MAX_HOLD_DAYS\|STRICT_CROSSOVER\|EMA_FAST\|EMA_SLOW\|RSI_PERIOD\|RSI_LOWER\|RSI_UPPER\|VOLUME_MULTIPLIER\|ATR_PERIOD\|ATR_STOP_MULTIPLIER\|EARNINGS_BLACKOUT_DAYS\|TRAILING_STOP\|FILL_POLL\|ANTHROPIC_API_KEY\|CLAUDE_MODEL" --include="*.py" .`

Expected: only references in `config/settings.py`, deleted/about-to-be-deleted modules (`agents/*.py`, `tools/risk.py`, `monitor/position_monitor.py`, `tools/broker.py`), and their tests. Anything else needs handling before dropping.

- [ ] **Step 2: Remove the obsolete blocks from `config/settings.py`**

Delete from `config/settings.py`:
- `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`
- `RISK_PER_TRADE` validation block
- `MAX_POSITIONS`, `MAX_PORTFOLIO_EXPOSURE`
- `DAILY_DRAWDOWN_LIMIT` (was unused even before)
- `MAX_HOLD_DAYS`
- `RR_RATIO_MIN`
- `EMA_FAST`, `EMA_SLOW`, `RSI_PERIOD`
- `RSI_LOWER`, `RSI_UPPER` validation block
- `VOLUME_MULTIPLIER` block
- `ATR_PERIOD`, `ATR_STOP_MULTIPLIER` block
- `STRICT_CROSSOVER`
- `TRAILING_STOP_ENABLED`, `TRAILING_STOP_ATR_MULT`
- `EARNINGS_BLACKOUT_DAYS`
- `FILL_POLL_TIMEOUT_S`, `FILL_POLL_INTERVAL_S`

Keep:
- `TRADING_MODE`, `ALPACA_*` (until Task 14 deletes the Alpaca broker entirely; see note below)
- `N8N_WEBHOOK_URL`, `DATA_FEED`
- `TRADING_PAUSED`
- All Task-1-added IBKR / regime / kill-switch / bot vars
- The `is_claude_agent_no_broker()` function and its module-level snapshot

**Note on `ALPACA_*`:** these stay until Task 14 deletes `tools/broker.py`. Order matters — keep settings around so Task 14 can clean up both at once.

- [ ] **Step 3: Update `.env.example` to drop the same keys**

Open `.env.example` and remove lines for the dropped keys.

- [ ] **Step 4: Drop tests for removed settings**

Open `tests/test_config.py` and delete tests for `RISK_PER_TRADE`, `MAX_POSITIONS`, etc. Keep tests for `TRADING_MODE`, `DATA_FEED`, all new IBKR/regime tests from Task 1.

- [ ] **Step 5: Run config tests**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run full suite — expect failures in agent tests, broker tests**

Run: `python3 -m pytest -q 2>&1 | tail -40`
Expected: Failures in `tests/test_*_agent.py`, `tests/test_risk.py`, `tests/test_tools_broker.py`, `tests/test_position_monitor.py`. These will be deleted in Tasks 13/14. **Do not fix them — they're going away.**

- [ ] **Step 7: Commit**

```bash
git add config/settings.py .env.example tests/test_config.py
git commit -m "chore(settings): drop LLM/strategy vars from old bot"
```

---

## Task 13: Delete `agents/` directory and tests

**Files:**
- Delete: `agents/` (entire directory)
- Delete: `tests/test_*_agent.py`, `tests/test_team_leader_*.py`, `tests/test_base_agent.py`

**Context:** With the new bot working end-to-end (Tasks 9, 10, 11), the LLM agents are dead code. Delete them.

- [ ] **Step 1: Final import check**

Run: `grep -rn "from agents\." --include="*.py" .`

Expected: only references in `agents/*.py` themselves and the agent test files. If anything else still imports from `agents/`, that's a bug — fix the importing module first (or move that work into a new task).

- [ ] **Step 2: Delete the agents directory and tests**

```bash
rm -rf agents/
rm -f tests/test_market_intelligence_agent.py \
      tests/test_strategy_agent.py \
      tests/test_risk_review_agent.py \
      tests/test_team_leader_agent.py \
      tests/test_team_leader_dry_run.py \
      tests/test_team_leader_*.py \
      tests/test_base_agent.py
```

- [ ] **Step 3: Run full suite**

Run: `python3 -m pytest -x -q`
Expected: All remaining tests PASS. (If anything imports from a deleted file, fix before committing.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete LLM agents (replaced by deterministic rules engine)"
```

---

## Task 14: Delete `tools/risk.py`, `tools/broker.py`, `monitor/position_monitor.py`

**Files:**
- Delete: `tools/risk.py`
- Delete: `tools/broker.py`
- Delete: `monitor/position_monitor.py`
- Delete: corresponding tests
- Modify: `config/settings.py` (drop ALPACA_* now that broker is gone)
- Modify: `.env.example`
- Modify: `requirements.txt` (drop `alpaca-py`)

**Context:** With agents gone (Task 13), the Alpaca broker, ATR-based risk module, and old position monitor are no longer used. Delete them.

- [ ] **Step 1: Final import check**

Run: `grep -rn "from tools.risk\|from tools.broker\|from monitor.position_monitor\|import alpaca" --include="*.py" .`

Expected: only references in the files about to be deleted. Anything else needs handling first.

- [ ] **Step 2: Delete the modules and their tests**

```bash
rm -f tools/risk.py tools/broker.py monitor/position_monitor.py
rm -f tests/test_risk.py tests/test_tools_broker.py tests/test_position_monitor.py
```

- [ ] **Step 3: Drop `ALPACA_*` from settings**

Edit `config/settings.py`: remove `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL`, `TRADING_MODE` (the new bot doesn't have a paper/live distinction at code level — the IBKR_PORT distinguishes). Or keep `TRADING_MODE` if you find references.

Run: `grep -rn "TRADING_MODE\|ALPACA_" --include="*.py" .` — should find only `config/settings.py` and possibly some doc strings.

Remove the matching blocks. Also drop these from `.env.example`.

- [ ] **Step 4: Drop alpaca-py from requirements.txt**

Edit `requirements.txt`, remove the `alpaca-py>=...` line.

Run: `venv/bin/pip uninstall -y alpaca-py`

- [ ] **Step 5: Drop helpers in `tools/database.py` that referenced old tables**

Edit `tools/database.py` and remove any of these (if present):
- `record_monitor_action`
- `upsert_daily_stat`
- `insert_signal`
- `get_closed_trade_stats`
- `get_daily_token_costs`
- Anything else that references `signals`, `monitor_actions`, `daily_stats`, `weekly_stats`, `suggestions`, `agent_logs`

Update `tests/test_database.py` to drop tests for removed helpers.

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest -x -q`
Expected: All remaining tests PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: delete Alpaca broker, ATR risk module, old position monitor"
```

---

## Task 15: Update `main.py` — drop `scan` and `monitor` modes

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

**Context:** `main.py scan` ran the LLM agent pipeline (deleted). `main.py monitor` ran `monitor.position_monitor` (deleted). Replace both with deprecation messages that point at the new entry points.

Keep: `panic`, `summary`, `backtest`. (Note: `summary` may need updating since it queried `agent_logs` for token costs — those columns are gone. Drop the token-cost piece, keep the trade-stat piece.)

- [ ] **Step 1: Inspect current main.py**

Run: `grep -n 'mode == ' main.py`

Note all mode strings.

- [ ] **Step 2: Update mode dispatcher**

In `main.py`, replace `elif mode == "scan":` and `elif mode == "monitor":` blocks with:

```python
    elif mode == "scan":
        print("'scan' mode removed in 2026-05-07 pivot.")
        print("The bot now runs daily_check.py directly via cron — no LLM agents.")
        print("See: docs/superpowers/specs/2026-05-07-rules-engine-pivot-design.md")
        return 2

    elif mode == "monitor":
        print("'monitor' mode removed in 2026-05-07 pivot.")
        print("Hourly drawdown protection now lives in monitor/kill_switch.py")
        print("(invoked directly by cron). See spec for details.")
        return 2
```

Also update the `else` branch's usage hint:

```python
    else:
        print(f"Unknown mode: {mode}. Use 'backtest', 'summary', or 'panic'")
        return 2
```

- [ ] **Step 3: Update `summary` mode to drop token-cost query**

In the `elif mode == "summary":` block, remove any references to `get_daily_token_costs`, `agent_logs.input_tokens`, `agent_logs.output_tokens`. Keep only the closed-trade stats from `tools.database.get_closed_trade_stats` IF that helper still exists; otherwise inline a simple aggregate query.

If `get_closed_trade_stats` was removed in Task 14, replace the body with:

```python
    elif mode == "summary":
        conn = None
        try:
            conn = get_db()
            stats = conn.execute("""
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN reason = 'kill_switch' THEN 1 ELSE 0 END) AS ks_count
                FROM trades
                WHERE created_at >= datetime('now', '-30 days')
            """).fetchone()
            print(f"Trailing 30d: {stats['n']} trades  ({stats['ks_count']} kill-switch)")
        finally:
            if conn:
                conn.close()
        return 0
```

- [ ] **Step 4: Update tests to expect the new behaviour**

Edit `tests/test_main.py`:

```python
def test_scan_mode_returns_deprecated(capsys):
    with patch("sys.argv", ["main.py", "scan"]):
        from main import main as run
        rc = run()
        assert rc == 2
        out = capsys.readouterr().out
        assert "removed" in out


def test_monitor_mode_returns_deprecated(capsys):
    with patch("sys.argv", ["main.py", "monitor"]):
        from main import main as run
        rc = run()
        assert rc == 2
```

(Drop any pre-existing tests that exercised the old `scan`/`monitor` flow against agent mocks.)

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_main.py tests/test_main_panic.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "chore(main): deprecate scan/monitor modes; simplify summary"
```

---

## Task 16: Update docs and dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `.env.example`
- Modify: `docs/CURRENT_CONFIG.md`

**Context:** Final docs sweep. README needs a top-to-bottom rewrite for the new architecture. CLAUDE.md needs the architectural-invariants section trimmed (LLM-related ones go away). `.env.example` and CURRENT_CONFIG.md should reflect what's actually configured.

- [ ] **Step 1: Drop `anthropic` from requirements.txt**

Edit `requirements.txt`:
- Remove: `anthropic>=...`
- Already removed (Task 14): `alpaca-py>=...`
- Already added (Task 5): `ib_insync>=0.9.86`

Run: `venv/bin/pip uninstall -y anthropic`
Run: `venv/bin/pip check`
Expected: no broken dependencies.

- [ ] **Step 2: Rewrite the top half of README.md**

Replace the architecture / commands / agents sections with content describing:
- The new rules-engine architecture (200-DMA filter on 3USL, kill-switch)
- New entry points: `python daily_check.py`, `python monitor/kill_switch.py`, `python main.py panic`
- New env vars (point to `.env.example`)
- IBKR setup notes (TWS/Gateway daemon required)
- The deleted features (LLM agents, 12-stock watchlist, ATR sizing) noted in a "Migration from v1.14" section

Aim for ~150-250 lines total. Strip anything that no longer applies.

- [ ] **Step 3: Update CLAUDE.md**

In the "Architectural invariants" section:
- Delete the entire "LLM must never control risk" subsection (no LLM)
- Delete references to `tools/risk.py`, `team_leader.place_order`, `pending_stops`, `pending_targets`, OCO brackets, `_poll_for_fill`, ATR-anchored brackets, `_order_outcomes` ledger
- Keep: `CLAUDE_AGENT_NO_BROKER` guard rule (preserved across pivot, now applies to `tools/ibkr_broker.py`)
- Keep: panic CLI is the deterministic kill button
- Keep: TRADING_PAUSED operational kill switch
- Add: "The bot has one decision rule. It is testable as a pure function. Do not add second decision rules without a fresh brainstorm and spec."

In "Architecture" → "Agent pipeline (daily)" — delete that whole subsection. Replace with:

```markdown
### Daily flow

`daily_check.py` runs once per weekday (cron, post-US-close). It computes the 200-DMA regime
filter on SPY, reconciles with IBKR, and flips between LONG (3USL) and CASH if needed.

### Hourly kill-switch

`monitor/kill_switch.py` runs hourly during US market hours. If 3USL drawdown from its
30-trading-day rolling high exceeds `KILL_SWITCH_DRAWDOWN_PCT`, it liquidates and sets
`kill_switch_active=1` in `regime_state`.
```

In the commands section, remove `scan`, `monitor`. Add `daily_check`, `monitor/kill_switch`.

- [ ] **Step 4: Update `docs/CURRENT_CONFIG.md`**

Replace with the actual `.env` shape after the pivot. Document:
- IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID
- BOT_TICKER, BOT_BENCHMARK
- REGIME_SMA_DAYS, KILL_SWITCH_DRAWDOWN_PCT, KILL_SWITCH_LOOKBACK_DAYS
- N8N_WEBHOOK_URL, DATA_FEED, TRADING_PAUSED

Drop everything else.

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt README.md CLAUDE.md .env.example docs/CURRENT_CONFIG.md
git commit -m "docs: rewrite for rules-engine architecture; drop anthropic dep"
```

---

## Task 17: Cron migration script and VPS ops doc

**Files:**
- Modify: `scripts/cron_setup.sh`
- Create: `docs/operations/ibkr-vps-setup.md`

**Context:** New cron entries (replace old `scan` and `monitor` lines). Docs for the operator on how to install IB Gateway as a systemd service on the VPS.

- [ ] **Step 1: Update `scripts/cron_setup.sh`**

Replace the cron entries with:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Install / update cron jobs for the rules-engine bot.
# Run as the trader user (not root): bash scripts/cron_setup.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$REPO_ROOT/venv/bin/python"

CRON_LINES=$(cat <<EOF
# Trading bot — rules-engine architecture (post-2026-05-07 pivot)
30 22 * * 1-5 cd $REPO_ROOT && $PYTHON daily_check.py >> $REPO_ROOT/logs/daily_check.log 2>&1
5 14-21 * * 1-5 cd $REPO_ROOT && $PYTHON -m monitor.kill_switch >> $REPO_ROOT/logs/kill_switch.log 2>&1
EOF
)

mkdir -p "$REPO_ROOT/logs"

# Replace any existing trading-bot block in current crontab
EXISTING=$(crontab -l 2>/dev/null || true)
WITHOUT_OLD=$(echo "$EXISTING" | sed '/# Trading bot/,/^[^#].*$/d' | sed '/daily_check.py\|kill_switch\|main.py scan\|main.py monitor/d')

(echo "$WITHOUT_OLD"; echo ""; echo "$CRON_LINES") | crontab -

echo "Crontab updated:"
crontab -l | grep -A1 "Trading bot" || crontab -l
```

- [ ] **Step 2: Create the VPS ops doc**

Create `docs/operations/ibkr-vps-setup.md`:

```markdown
# IBKR Gateway on the VPS — Setup Notes

The rules-engine bot requires IB Gateway (or TWS) running as a long-lived
process on the VPS. The bot's cron jobs (`daily_check.py`, `monitor/kill_switch.py`)
connect to it via `ib_insync` on `127.0.0.1`.

## 1. Install IB Gateway

Download from https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

The "stable" build is sufficient. Install in `/opt/ibgateway/`.

## 2. Configure auto-login

Recommended: use the IBC project (https://github.com/IbcAlpha/IBC) to auto-login
non-interactively. Without IBC, you'll need to type credentials each restart.

Configure `IBC/config.ini`:
- `IbLoginId=<your-username>`
- `IbPassword=<your-password>` (or use an environment variable)
- `TradingMode=paper` (or `live`)
- `ReadOnlyApi=no`

## 3. Configure API in IB Gateway

Once running:
- File → Global Configuration → API → Settings
- Enable: "Enable ActiveX and Socket Clients"
- Set: "Socket port" = `4002` (paper) or `4001` (live)
- "Trusted IPs" → add `127.0.0.1`
- Disable: "Read-Only API" (the bot needs to place orders)

## 4. systemd service

Create `/etc/systemd/system/ibgateway.service`:

```ini
[Unit]
Description=IB Gateway (auto-login via IBC)
After=network.target

[Service]
Type=simple
User=trader
ExecStart=/opt/ibgateway/IBC/scripts/ibcstart.sh PAPER
Restart=on-failure
RestartSec=30s

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ibgateway
sudo systemctl start ibgateway
sudo systemctl status ibgateway
```

## 5. Verify connectivity

From the trader user:
```bash
cd /opt/trading-bot
venv/bin/python -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=99)
print('connected:', ib.isConnected())
print('account:', ib.managedAccounts())
ib.disconnect()
"
```

Expected: `connected: True`, account list non-empty.

## 6. Daily reset

IB Gateway forces a daily logout around 22:30 ET (~03:30 UTC). With IBC + the
systemd service above, it will auto-login again within ~30 seconds. Our cron
windows (`30 22 * * 1-5` UTC daily, `5 14-21 * * 1-5` UTC hourly) avoid this
window entirely.

If you see `tws_disconnected` notifications outside the reset window, check
`journalctl -u ibgateway -n 100` for the cause.
```

- [ ] **Step 3: Verify the cron script syntax**

Run: `bash -n scripts/cron_setup.sh`
Expected: no syntax errors.

(**Do NOT actually run the script in this development session** — it would mutate the host's crontab. Only the operator runs it on the VPS during cutover.)

- [ ] **Step 4: Commit**

```bash
git add scripts/cron_setup.sh docs/operations/ibkr-vps-setup.md
git commit -m "ops: cron setup script + IBKR/VPS setup doc"
```

---

## Final verification

After all tasks complete:

- [ ] **Full test suite passes**

Run: `python3 -m pytest -q`
Expected: All tests PASS, ~40 tests total, runtime < 30s.

- [ ] **Codebase size check**

Run: `find . -path ./venv -prune -o -path ./.claude -prune -o -name '*.py' -print | xargs wc -l | tail -1`
Expected: total Python LOC < 2,500 (was ~8,000).

- [ ] **Settings sanity check**

Run: `python3 -c "from config import settings; print('OK')"`
Expected: `OK` — no validation errors with the default `.env.example`.

- [ ] **Backtest CLI sanity check**

Run: `python3 backtest/regime.py --benchmark SPY --vehicle UPRO --years 5 --sma 200`
Expected: Output table with total return, CAGR, max DD, trade count.

- [ ] **Final commit (if anything pending)**

```bash
git status
# If clean, nothing more to commit.
```

The PR for this branch (PR #193) is now the spec + plan + full implementation.
