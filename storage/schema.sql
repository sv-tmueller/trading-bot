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
    exit_reason TEXT,
    pnl_dollars REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    r_multiple REAL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER REFERENCES trades(id),
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
    tokens_used INTEGER DEFAULT 0
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
    status TEXT DEFAULT 'pending',
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
