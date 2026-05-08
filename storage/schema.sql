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
