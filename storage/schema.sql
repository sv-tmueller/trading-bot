CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    shares REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    exit_reason TEXT CHECK (exit_reason IN ('stop_loss', 'take_profit', 'trend_reversal', 'max_hold', 'manual')),
    pnl_dollars REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    r_multiple REAL,
    trailing_high REAL
);

-- Future work: signals, daily_stats, weekly_stats, suggestions are defined but not yet
-- written to by the pipeline. signals should be populated at trade entry (insert_signal
-- in tools/database.py). daily_stats/weekly_stats are intended for performance tracking.
-- suggestions is for parameter-tuning feedback. Implement when reporting is prioritised.
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER REFERENCES trades(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    ema_fast REAL,
    ema_slow REAL,
    rsi REAL,
    volume_ratio REAL,
    signal_score REAL,
    triggered_entry INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_date TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    full_reasoning TEXT,
    tokens_used INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    trades_opened INTEGER DEFAULT 0,
    trades_closed INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    win_rate REAL,
    avg_r_multiple REAL,
    portfolio_value REAL,
    daily_pnl REAL,
    drawdown REAL
);

CREATE TABLE IF NOT EXISTS weekly_stats (
    week_start TEXT PRIMARY KEY,
    week_end TEXT NOT NULL,
    total_trades INTEGER DEFAULT 0,
    win_rate REAL,
    avg_r_multiple REAL,
    best_ticker TEXT,
    worst_ticker TEXT,
    portfolio_value REAL,
    weekly_pnl REAL
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_date TEXT NOT NULL,
    parameter TEXT NOT NULL,
    current_value TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    evidence TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    applied_date TEXT
);

CREATE TABLE IF NOT EXISTS parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    applied_date TEXT NOT NULL,
    rsi_lower REAL NOT NULL,
    rsi_upper REAL NOT NULL,
    ema_fast INTEGER NOT NULL,
    ema_slow INTEGER NOT NULL,
    volume_multiplier REAL NOT NULL,
    risk_pct REAL NOT NULL,
    max_positions INTEGER NOT NULL,
    r_ratio_min REAL NOT NULL
);

-- Per-iteration audit trail for the hourly position monitor (issue #131).
-- One row per evaluated trade per cycle. Lets analysts reconstruct what the
-- monitor saw and decided without grepping /var/log/trading-bot/monitor.log.
-- action_type values:
--   stop_loss / take_profit / max_hold — soft-stop check fired and the
--     monitor closed the position locally (broker_close was called).
--   reconciled — Alpaca had already closed the position server-side
--     (bracket child fired between cycles); the monitor reconciled the DB.
--   hold — in-range, no action.
--   skipped_error — per-iteration try/except caught a transient failure
--     (broker/network blip); loop continued to the next ticker.
CREATE TABLE IF NOT EXISTS monitor_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER REFERENCES trades(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    action_time TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN (
        'stop_loss', 'take_profit', 'max_hold', 'reconciled', 'hold', 'skipped_error'
    )),
    reason TEXT,
    current_price REAL,
    stop_price REAL,
    take_profit_price REAL
);

-- Indexes for frequent query patterns
CREATE INDEX IF NOT EXISTS idx_trades_open ON trades (exit_date) WHERE exit_date IS NULL;
CREATE INDEX IF NOT EXISTS idx_trades_exit_date ON trades (exit_date);
CREATE INDEX IF NOT EXISTS idx_signals_ticker_date ON signals (ticker, date);
CREATE INDEX IF NOT EXISTS idx_agent_logs_cycle_date ON agent_logs (cycle_date);
CREATE INDEX IF NOT EXISTS idx_monitor_actions_trade_id ON monitor_actions (trade_id);
CREATE INDEX IF NOT EXISTS idx_monitor_actions_action_time ON monitor_actions (action_time);
