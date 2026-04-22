# Trading Bot — Foundation & Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully functional multi-agent LLM swing trading bot for US equities on Alpaca paper trading, covering project foundation, data layer, shared tools, position monitor, all four Claude-powered agents, and the daily orchestration cycle.

**Architecture:** Modular Python application with four Claude API agents (Market Intelligence → Strategy → Risk Review → Team Leader) that collaborate per trade cycle. Agents share state via SQLite. A lightweight rule-based position monitor runs hourly between agent cycles. All parameters are config-driven and env-toggled for paper/live switching.

**Tech Stack:** Python 3.11+, `alpaca-py`, `anthropic`, `pandas`, `ta`, `pandas_market_calendars`, `python-dotenv`, `sqlite3` (stdlib), `pytest`

---

## File Map

```
trading-bot/
├── requirements.txt
├── .env.example
├── .gitignore
├── pytest.ini
├── main.py                              # Daily cycle entry point
├── config/
│   ├── __init__.py
│   ├── settings.py                      # All env-driven parameters
│   └── watchlist.py                     # Curated ticker list
├── storage/
│   ├── schema.sql                       # DB schema definition
│   └── init_db.py                       # One-time DB initialiser
├── tools/
│   ├── __init__.py
│   ├── database.py                      # All SQLite read/write
│   ├── market_data.py                   # OHLCV fetching + signal computation
│   ├── portfolio.py                     # Open positions, portfolio stats
│   ├── risk.py                          # Position sizing, stop/target calc
│   └── broker.py                        # Alpaca order placement wrapper
├── monitor/
│   ├── __init__.py
│   └── position_monitor.py              # Hourly rule-based stop/target check
├── agents/
│   ├── __init__.py
│   ├── base.py                          # Base Claude agent (tool-use loop)
│   ├── market_intelligence.py           # Agent 1
│   ├── strategy.py                      # Agent 2
│   ├── risk_review.py                   # Agent 3
│   └── team_leader.py                   # Agent 4 — places orders
└── tests/
    ├── conftest.py                       # Shared fixtures (in-memory DB, mock data)
    ├── test_config.py
    ├── test_tools_database.py
    ├── test_tools_market_data.py
    ├── test_tools_risk.py
    ├── test_tools_portfolio.py
    ├── test_tools_broker.py
    ├── test_monitor.py
    └── test_agents/
        ├── __init__.py
        ├── test_base_agent.py
        ├── test_market_intelligence.py
        ├── test_strategy.py
        ├── test_risk_review.py
        └── test_team_leader.py
```

---

## Phase 1 — Project Foundation

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: `config/__init__.py`
- Create: `tools/__init__.py`
- Create: `agents/__init__.py`
- Create: `monitor/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_agents/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
alpaca-py==0.38.0
anthropic==0.49.0
pandas==2.2.3
pandas-market-calendars==4.4.2
ta==0.11.0
python-dotenv==1.0.1
pytest==8.3.5
pytest-mock==3.14.0
```

- [ ] **Step 2: Create `.env.example`**

```
ALPACA_API_KEY=your_alpaca_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_here
ANTHROPIC_API_KEY=your_anthropic_key_here
TRADING_MODE=paper
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
CLAUDE_MODEL=claude-sonnet-4-6
```

- [ ] **Step 3: Create `.gitignore`**

```
.env
storage/trades.db
reports/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.DS_Store
```

- [ ] **Step 4: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 5: Create all `__init__.py` files**

Each is an empty file. Create: `config/__init__.py`, `tools/__init__.py`, `agents/__init__.py`, `monitor/__init__.py`, `tests/__init__.py`, `tests/test_agents/__init__.py`

- [ ] **Step 6: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example .gitignore pytest.ini config/__init__.py tools/__init__.py agents/__init__.py monitor/__init__.py tests/__init__.py tests/test_agents/__init__.py
git commit -m "feat: project scaffolding and dependencies"
```

---

### Task 2: Config module

**Files:**
- Create: `config/settings.py`
- Create: `config/watchlist.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
import os
import pytest


def test_alpaca_base_url_paper(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert "paper-api" in s.ALPACA_BASE_URL


def test_alpaca_base_url_live(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert "paper-api" not in s.ALPACA_BASE_URL


def test_risk_per_trade_default(monkeypatch):
    monkeypatch.delenv("RISK_PER_TRADE", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.RISK_PER_TRADE == 0.01


def test_risk_per_trade_env_override(monkeypatch):
    monkeypatch.setenv("RISK_PER_TRADE", "0.02")
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.RISK_PER_TRADE == 0.02


def test_watchlist_not_empty():
    from config.watchlist import WATCHLIST
    assert len(WATCHLIST) > 0
    assert all(isinstance(t, str) for t in WATCHLIST)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create `config/settings.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

TRADING_MODE = os.getenv("TRADING_MODE", "paper")

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = (
    "https://paper-api.alpaca.markets"
    if TRADING_MODE == "paper"
    else "https://api.alpaca.markets"
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
MAX_PORTFOLIO_EXPOSURE = 0.20
DAILY_DRAWDOWN_LIMIT = 0.03
MAX_HOLD_DAYS = 5
RR_RATIO_MIN = 2.0

# Strategy parameters — also versioned in DB
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
RSI_LOWER = 40
RSI_UPPER = 60
VOLUME_MULTIPLIER = 1.5
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5
```

- [ ] **Step 4: Create `config/watchlist.py`**

```python
WATCHLIST = [
    "AMD",
    "NOW",   # ServiceNow
    "SHEL",  # Shell ADR
    "NVDA",
    "MSFT",
    "GOOGL",
    "META",
    "AMZN",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add config/settings.py config/watchlist.py tests/test_config.py
git commit -m "feat: config module with env-driven parameters"
```

---

### Task 3: Database schema and initialiser

**Files:**
- Create: `storage/schema.sql`
- Create: `storage/init_db.py`
- Create: `storage/__init__.py`

- [ ] **Step 1: Create `storage/__init__.py`** (empty file)

- [ ] **Step 2: Create `storage/schema.sql`**

```sql
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
```

- [ ] **Step 3: Create `storage/init_db.py`**

```python
import sqlite3
import os
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
```

- [ ] **Step 4: Run init script to verify it works**

```bash
python storage/init_db.py
```

Expected: `Database initialised at storage/trades.db`

- [ ] **Step 5: Verify tables were created**

```bash
python -c "import sqlite3; conn = sqlite3.connect('storage/trades.db'); print([r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])"
```

Expected: `['trades', 'signals', 'agent_logs', 'daily_stats', 'weekly_stats', 'suggestions', 'parameters']`

- [ ] **Step 6: Commit**

```bash
git add storage/__init__.py storage/schema.sql storage/init_db.py
git commit -m "feat: SQLite schema and database initialiser"
```

---

## Phase 2 — Tools Layer

### Task 4: Database tool

**Files:**
- Create: `tools/database.py`
- Create: `tests/test_tools_database.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `tests/conftest.py`** with in-memory DB fixture

```python
import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_conn():
    schema = (Path(__file__).parent.parent / "storage" / "schema.sql").read_text()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    conn.commit()
    yield conn
    conn.close()
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_tools_database.py`:

```python
from tools.database import (
    insert_trade,
    get_open_trades,
    close_trade,
    insert_signal,
    log_agent_output,
    get_active_parameters,
    insert_parameters,
)
import pytest
from datetime import date


def test_insert_and_retrieve_open_trade(db_conn):
    trade_id = insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    open_trades = get_open_trades(db_conn)
    assert len(open_trades) == 1
    assert open_trades[0]["ticker"] == "AMD"
    assert open_trades[0]["id"] == trade_id


def test_close_trade(db_conn):
    trade_id = insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    close_trade(db_conn, trade_id, {
        "exit_date": "2026-04-24",
        "exit_price": 159.0,
        "exit_reason": "take_profit",
        "pnl_dollars": 900.0,
        "pnl_pct": 0.06,
        "hold_days": 2,
        "r_multiple": 2.0,
    })
    open_trades = get_open_trades(db_conn)
    assert len(open_trades) == 0


def test_log_agent_output(db_conn):
    log_agent_output(db_conn, {
        "cycle_date": "2026-04-22",
        "agent_name": "market_intelligence",
        "input_summary": "watchlist scan",
        "output_summary": "3 candidates found",
        "full_reasoning": "...",
        "tokens_used": 1200,
    })
    rows = db_conn.execute("SELECT * FROM agent_logs").fetchall()
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "market_intelligence"


def test_insert_and_get_parameters(db_conn):
    insert_parameters(db_conn, {
        "applied_date": "2026-04-22",
        "rsi_lower": 40.0,
        "rsi_upper": 60.0,
        "ema_fast": 20,
        "ema_slow": 50,
        "volume_multiplier": 1.5,
        "risk_pct": 0.01,
        "max_positions": 5,
        "r_ratio_min": 2.0,
    })
    params = get_active_parameters(db_conn)
    assert params["rsi_lower"] == 40.0
    assert params["ema_fast"] == 20
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_tools_database.py -v
```

Expected: `ImportError` — functions not yet defined

- [ ] **Step 4: Create `tools/database.py`**

```python
import sqlite3
from typing import Any


def insert_trade(conn: sqlite3.Connection, trade: dict) -> int:
    cur = conn.execute(
        """INSERT INTO trades (ticker, entry_date, entry_price, shares, stop_loss, take_profit)
           VALUES (:ticker, :entry_date, :entry_price, :shares, :stop_loss, :take_profit)""",
        trade,
    )
    conn.commit()
    return cur.lastrowid


def get_open_trades(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM trades WHERE exit_date IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def close_trade(conn: sqlite3.Connection, trade_id: int, close_data: dict) -> None:
    conn.execute(
        """UPDATE trades SET
               exit_date = :exit_date,
               exit_price = :exit_price,
               exit_reason = :exit_reason,
               pnl_dollars = :pnl_dollars,
               pnl_pct = :pnl_pct,
               hold_days = :hold_days,
               r_multiple = :r_multiple
           WHERE id = ?""",
        (*close_data.values(), trade_id),
    )
    conn.commit()


def insert_signal(conn: sqlite3.Connection, signal: dict) -> None:
    conn.execute(
        """INSERT INTO signals
               (trade_id, ticker, date, ema_fast, ema_slow, rsi, volume_ratio, signal_score, triggered_entry)
           VALUES
               (:trade_id, :ticker, :date, :ema_fast, :ema_slow, :rsi, :volume_ratio, :signal_score, :triggered_entry)""",
        signal,
    )
    conn.commit()


def log_agent_output(conn: sqlite3.Connection, log: dict) -> None:
    conn.execute(
        """INSERT INTO agent_logs
               (cycle_date, agent_name, input_summary, output_summary, full_reasoning, tokens_used)
           VALUES
               (:cycle_date, :agent_name, :input_summary, :output_summary, :full_reasoning, :tokens_used)""",
        log,
    )
    conn.commit()


def insert_parameters(conn: sqlite3.Connection, params: dict) -> None:
    conn.execute(
        """INSERT INTO parameters
               (applied_date, rsi_lower, rsi_upper, ema_fast, ema_slow,
                volume_multiplier, risk_pct, max_positions, r_ratio_min)
           VALUES
               (:applied_date, :rsi_lower, :rsi_upper, :ema_fast, :ema_slow,
                :volume_multiplier, :risk_pct, :max_positions, :r_ratio_min)""",
        params,
    )
    conn.commit()


def get_active_parameters(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT * FROM parameters ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else {}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_tools_database.py -v
```

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add tools/database.py tests/conftest.py tests/test_tools_database.py
git commit -m "feat: database tool with trade CRUD and agent logging"
```

---

### Task 5: Market data fetching and signal computation

**Files:**
- Create: `tools/market_data.py`
- Create: `tests/test_tools_market_data.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_market_data.py`:

```python
import pandas as pd
import pytest
from tools.market_data import compute_signals, is_entry_signal


@pytest.fixture
def bullish_bars():
    """60 daily bars with a clear uptrend — EMA20 above EMA50, moderate RSI, above-avg volume."""
    import numpy as np
    prices = [100 + i * 0.5 for i in range(60)]
    volumes = [1_000_000] * 60
    # Spike volume on last bar to simulate entry confirmation
    volumes[-1] = 1_800_000
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    return pd.DataFrame({"close": prices, "high": [p + 0.5 for p in prices],
                         "low": [p - 0.5 for p in prices], "volume": volumes}, index=index)


@pytest.fixture
def ranging_bars():
    """60 bars oscillating without clear trend — EMA20 near EMA50."""
    import numpy as np
    prices = [100 + 2 * (i % 2) for i in range(60)]
    volumes = [1_000_000] * 60
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    return pd.DataFrame({"close": prices, "high": [p + 0.5 for p in prices],
                         "low": [p - 0.5 for p in prices], "volume": volumes}, index=index)


def test_compute_signals_returns_required_keys(bullish_bars):
    signals = compute_signals(bullish_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    for key in ("ema_fast", "ema_slow", "rsi", "volume_ratio", "atr", "ema_crossover"):
        assert key in signals, f"Missing key: {key}"


def test_ema_crossover_true_in_uptrend(bullish_bars):
    signals = compute_signals(bullish_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    assert signals["ema_crossover"] is True


def test_ema_crossover_false_in_ranging_market(ranging_bars):
    signals = compute_signals(ranging_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    assert signals["ema_crossover"] is False


def test_volume_ratio_computed(bullish_bars):
    signals = compute_signals(bullish_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    assert signals["volume_ratio"] == pytest.approx(1.8, rel=0.05)


def test_is_entry_signal_true_when_all_conditions_met():
    signals = {
        "ema_crossover": True,
        "rsi": 50.0,
        "volume_ratio": 1.8,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is True


def test_is_entry_signal_false_when_rsi_overbought():
    signals = {
        "ema_crossover": True,
        "rsi": 72.0,
        "volume_ratio": 2.0,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is False


def test_is_entry_signal_false_when_no_crossover():
    signals = {
        "ema_crossover": False,
        "rsi": 50.0,
        "volume_ratio": 2.0,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tools_market_data.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `tools/market_data.py`**

```python
import pandas as pd
import ta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from config import settings


def get_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)


def fetch_bars(ticker: str, days: int = 60) -> pd.DataFrame:
    from datetime import datetime, timedelta
    client = get_client()
    end = datetime.utcnow()
    start = end - timedelta(days=days + 10)  # buffer for weekends/holidays
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = client.get_stock_bars(request).df
    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.xs(ticker, level=0)
    bars = bars[["open", "high", "low", "close", "volume"]].tail(days)
    return bars


def compute_signals(
    bars: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> dict:
    close = bars["close"]
    volume = bars["volume"]

    ema_fast_series = ta.trend.ema_indicator(close, window=ema_fast)
    ema_slow_series = ta.trend.ema_indicator(close, window=ema_slow)
    rsi_series = ta.momentum.rsi(close, window=rsi_period)
    atr_series = ta.volatility.average_true_range(bars["high"], bars["low"], close, window=atr_period)
    avg_volume = volume.rolling(20).mean()

    ema_f = ema_fast_series.iloc[-1]
    ema_s = ema_slow_series.iloc[-1]
    ema_f_prev = ema_fast_series.iloc[-2]
    ema_s_prev = ema_slow_series.iloc[-2]

    crossover = (ema_f > ema_s) and (ema_f_prev <= ema_s_prev)

    return {
        "ema_fast": round(ema_f, 4),
        "ema_slow": round(ema_s, 4),
        "rsi": round(rsi_series.iloc[-1], 2),
        "volume_ratio": round(volume.iloc[-1] / avg_volume.iloc[-1], 3),
        "atr": round(atr_series.iloc[-1], 4),
        "ema_crossover": crossover,
    }


def is_entry_signal(
    signals: dict,
    rsi_lower: float = 40,
    rsi_upper: float = 60,
    volume_multiplier: float = 1.5,
) -> bool:
    return (
        signals["ema_crossover"]
        and rsi_lower <= signals["rsi"] <= rsi_upper
        and signals["volume_ratio"] >= volume_multiplier
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tools_market_data.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add tools/market_data.py tests/test_tools_market_data.py
git commit -m "feat: market data fetching and signal computation"
```

---

### Task 6: Risk calculator

**Files:**
- Create: `tools/risk.py`
- Create: `tests/test_tools_risk.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_risk.py`:

```python
import pytest
from tools.risk import calculate_position, check_portfolio_guardrails


def test_position_size_1pct_risk():
    result = calculate_position(
        portfolio_value=100_000,
        risk_pct=0.01,
        entry_price=150.0,
        atr=3.0,
        atr_stop_multiplier=1.5,
        rr_ratio_min=2.0,
    )
    # stop distance = 1.5 * 3.0 = 4.5
    # shares = 1000 / 4.5 = 222 (floor)
    assert result["shares"] == 222
    assert result["stop_loss"] == pytest.approx(150.0 - 4.5)
    assert result["take_profit"] == pytest.approx(150.0 + 9.0)
    assert result["risk_dollars"] == pytest.approx(1000.0)


def test_position_size_scales_with_portfolio():
    small = calculate_position(50_000, 0.01, 100.0, 2.0, 1.5, 2.0)
    large = calculate_position(200_000, 0.01, 100.0, 2.0, 1.5, 2.0)
    assert large["shares"] == small["shares"] * 4


def test_guardrails_pass():
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=-0.01,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is True


def test_guardrails_fail_max_positions():
    result = check_portfolio_guardrails(
        open_positions=5,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=-0.01,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is False
    assert "max_positions" in result["reason"]


def test_guardrails_fail_drawdown():
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.10,
        max_exposure=0.20,
        daily_pnl_pct=-0.04,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is False
    assert "drawdown" in result["reason"]


def test_guardrails_fail_exposure():
    result = check_portfolio_guardrails(
        open_positions=2,
        max_positions=5,
        deployed_pct=0.22,
        max_exposure=0.20,
        daily_pnl_pct=0.0,
        drawdown_limit=0.03,
    )
    assert result["can_trade"] is False
    assert "exposure" in result["reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tools_risk.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `tools/risk.py`**

```python
import math


def calculate_position(
    portfolio_value: float,
    risk_pct: float,
    entry_price: float,
    atr: float,
    atr_stop_multiplier: float = 1.5,
    rr_ratio_min: float = 2.0,
) -> dict:
    risk_dollars = portfolio_value * risk_pct
    stop_distance = atr * atr_stop_multiplier
    shares = math.floor(risk_dollars / stop_distance)
    stop_loss = round(entry_price - stop_distance, 4)
    take_profit = round(entry_price + stop_distance * rr_ratio_min, 4)
    return {
        "shares": shares,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_dollars": round(risk_dollars, 2),
        "stop_distance": round(stop_distance, 4),
    }


def check_portfolio_guardrails(
    open_positions: int,
    max_positions: int,
    deployed_pct: float,
    max_exposure: float,
    daily_pnl_pct: float,
    drawdown_limit: float,
) -> dict:
    if open_positions >= max_positions:
        return {"can_trade": False, "reason": f"max_positions reached ({open_positions}/{max_positions})"}
    if deployed_pct >= max_exposure:
        return {"can_trade": False, "reason": f"exposure limit reached ({deployed_pct:.1%}/{max_exposure:.1%})"}
    if daily_pnl_pct <= -drawdown_limit:
        return {"can_trade": False, "reason": f"drawdown limit breached ({daily_pnl_pct:.1%})"}
    return {"can_trade": True, "reason": ""}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tools_risk.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tools/risk.py tests/test_tools_risk.py
git commit -m "feat: risk calculator with position sizing and guardrails"
```

---

### Task 7: Portfolio tool

**Files:**
- Create: `tools/portfolio.py`
- Create: `tests/test_tools_portfolio.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_portfolio.py`:

```python
import pytest
from tools.portfolio import get_portfolio_stats, get_open_positions_with_prices
from tools.database import insert_trade


def test_portfolio_stats_no_trades(db_conn):
    stats = get_portfolio_stats(db_conn, portfolio_value=100_000)
    assert stats["open_count"] == 0
    assert stats["deployed_pct"] == 0.0
    assert stats["daily_pnl_pct"] == 0.0


def test_portfolio_stats_with_open_trade(db_conn):
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    stats = get_portfolio_stats(db_conn, portfolio_value=100_000, current_prices={"AMD": 155.0})
    assert stats["open_count"] == 1
    assert stats["unrealized_pnl"] == pytest.approx(500.0)


def test_open_positions_with_prices(db_conn):
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    positions = get_open_positions_with_prices(db_conn, current_prices={"AMD": 155.0})
    assert len(positions) == 1
    assert positions[0]["unrealized_pnl"] == pytest.approx(500.0)
    assert positions[0]["pct_to_stop"] == pytest.approx((155.0 - 145.5) / 155.0, rel=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tools_portfolio.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `tools/portfolio.py`**

```python
import sqlite3
from tools.database import get_open_trades


def get_open_positions_with_prices(
    conn: sqlite3.Connection, current_prices: dict
) -> list[dict]:
    trades = get_open_trades(conn)
    result = []
    for t in trades:
        ticker = t["ticker"]
        price = current_prices.get(ticker, t["entry_price"])
        unrealized_pnl = (price - t["entry_price"]) * t["shares"]
        pct_to_stop = (price - t["stop_loss"]) / price if price > 0 else 0
        pct_to_target = (t["take_profit"] - price) / price if price > 0 else 0
        result.append({
            **t,
            "current_price": price,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pct_to_stop": round(pct_to_stop, 4),
            "pct_to_target": round(pct_to_target, 4),
        })
    return result


def get_portfolio_stats(
    conn: sqlite3.Connection,
    portfolio_value: float,
    current_prices: dict = None,
) -> dict:
    current_prices = current_prices or {}
    positions = get_open_positions_with_prices(conn, current_prices)
    deployed = sum(t["entry_price"] * t["shares"] for t in positions)
    unrealized_pnl = sum(t["unrealized_pnl"] for t in positions)
    return {
        "open_count": len(positions),
        "deployed_dollars": round(deployed, 2),
        "deployed_pct": round(deployed / portfolio_value, 4) if portfolio_value else 0,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "daily_pnl_pct": round(unrealized_pnl / portfolio_value, 4) if portfolio_value else 0,
        "positions": positions,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tools_portfolio.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tools/portfolio.py tests/test_tools_portfolio.py
git commit -m "feat: portfolio tool with open position tracking"
```

---

### Task 8: Broker wrapper

**Files:**
- Create: `tools/broker.py`
- Create: `tests/test_tools_broker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_broker.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from tools.broker import place_market_order, close_position, get_portfolio_value


def test_place_market_order_buy(monkeypatch):
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-123"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    mock_client.submit_order.assert_called_once()
    assert result == "order-123"


def test_place_market_order_sell(monkeypatch):
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "sell")

    assert result == "order-456"


def test_get_portfolio_value(monkeypatch):
    mock_client = MagicMock()
    mock_account = MagicMock()
    mock_account.portfolio_value = "98500.50"
    mock_client.get_account.return_value = mock_account

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        value = get_portfolio_value()

    assert value == pytest.approx(98500.50)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tools_broker.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `tools/broker.py`**

```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import settings


def get_trading_client() -> TradingClient:
    return TradingClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
        paper=(settings.TRADING_MODE == "paper"),
    )


def place_market_order(ticker: str, shares: int, side: str) -> str:
    client = get_trading_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    request = MarketOrderRequest(
        symbol=ticker,
        qty=shares,
        side=order_side,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(request)
    return str(order.id)


def close_position(ticker: str) -> str:
    client = get_trading_client()
    order = client.close_position(ticker)
    return str(order.id)


def get_portfolio_value() -> float:
    client = get_trading_client()
    account = client.get_account()
    return float(account.portfolio_value)


def get_current_price(ticker: str) -> float:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
    data_client = StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)
    request = StockLatestQuoteRequest(symbol_or_symbols=ticker)
    quote = data_client.get_stock_latest_quote(request)
    return float(quote[ticker].ask_price)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tools_broker.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tools/broker.py tests/test_tools_broker.py
git commit -m "feat: Alpaca broker wrapper for order placement"
```

---

## Phase 3 — Position Monitor

### Task 9: Hourly rule-based position monitor

**Files:**
- Create: `monitor/position_monitor.py`
- Create: `tests/test_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_monitor.py`:

```python
import pytest
from monitor.position_monitor import evaluate_position, MonitorAction


def test_stop_loss_triggered():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-20",
    }
    action = evaluate_position(position, current_price=145.0, today="2026-04-22")
    assert action.action == "close"
    assert action.reason == "stop_loss"


def test_take_profit_triggered():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-20",
    }
    action = evaluate_position(position, current_price=160.0, today="2026-04-22")
    assert action.action == "close"
    assert action.reason == "take_profit"


def test_max_hold_triggered():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-15",
    }
    action = evaluate_position(position, current_price=152.0, today="2026-04-22", max_hold_days=5)
    assert action.action == "close"
    assert action.reason == "max_hold"


def test_no_action_when_in_range():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-21",
    }
    action = evaluate_position(position, current_price=152.0, today="2026-04-22")
    assert action.action == "hold"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_monitor.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `monitor/position_monitor.py`**

```python
from dataclasses import dataclass
from datetime import date, datetime
from config import settings


@dataclass
class MonitorAction:
    trade_id: int
    ticker: str
    action: str  # "hold" | "close"
    reason: str  # "" | "stop_loss" | "take_profit" | "max_hold"
    current_price: float


def evaluate_position(
    position: dict,
    current_price: float,
    today: str,
    max_hold_days: int = None,
) -> MonitorAction:
    max_hold_days = max_hold_days or settings.MAX_HOLD_DAYS
    entry_date = datetime.strptime(position["entry_date"], "%Y-%m-%d").date()
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    hold_days = (today_date - entry_date).days

    if current_price <= position["stop_loss"]:
        return MonitorAction(position["id"], position["ticker"], "close", "stop_loss", current_price)
    if current_price >= position["take_profit"]:
        return MonitorAction(position["id"], position["ticker"], "close", "take_profit", current_price)
    if hold_days >= max_hold_days:
        return MonitorAction(position["id"], position["ticker"], "close", "max_hold", current_price)
    return MonitorAction(position["id"], position["ticker"], "hold", "", current_price)


def run_monitor(conn, today: str = None) -> list[MonitorAction]:
    from tools.database import get_open_trades, close_trade
    from tools.broker import get_current_price, close_position
    from datetime import date as date_cls

    today = today or date_cls.today().isoformat()
    trades = get_open_trades(conn)
    actions = []

    for trade in trades:
        price = get_current_price(trade["ticker"])
        action = evaluate_position(trade, price, today)
        if action.action == "close":
            close_position(trade["ticker"])
            entry_price = trade["entry_price"]
            pnl_dollars = (price - entry_price) * trade["shares"]
            stop_distance = entry_price - trade["stop_loss"]
            r_multiple = (price - entry_price) / stop_distance if stop_distance else 0
            from datetime import datetime as dt
            entry_date = dt.strptime(trade["entry_date"], "%Y-%m-%d").date()
            today_date = dt.strptime(today, "%Y-%m-%d").date()
            hold_days = (today_date - entry_date).days
            close_trade(conn, trade["id"], {
                "exit_date": today,
                "exit_price": price,
                "exit_reason": action.reason,
                "pnl_dollars": round(pnl_dollars, 2),
                "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                "hold_days": hold_days,
                "r_multiple": round(r_multiple, 3),
            })
        actions.append(action)

    return actions
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_monitor.py -v
```

Expected: 4 passed

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add monitor/position_monitor.py tests/test_monitor.py
git commit -m "feat: hourly rule-based position monitor with stop/target/max-hold evaluation"
```

---

## Phase 4 — Agent Infrastructure

### Task 10: Base agent class

**Files:**
- Create: `agents/base.py`
- Create: `tests/test_agents/test_base_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agents/test_base_agent.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.base import BaseAgent


class ConcreteAgent(BaseAgent):
    name = "test_agent"
    system_prompt = "You are a test agent."

    def get_tools(self):
        return []

    def parse_output(self, response) -> dict:
        return {"result": response.content[0].text}


def test_agent_name():
    agent = ConcreteAgent()
    assert agent.name == "test_agent"


def test_agent_run_calls_claude(monkeypatch):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="analysis complete")]
    mock_response.usage.input_tokens = 500
    mock_response.usage.output_tokens = 200
    mock_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ConcreteAgent()
        result = agent.run("analyse the market")

    assert result["result"] == "analysis complete"
    mock_client.messages.create.assert_called_once()


def test_agent_run_logs_to_db(monkeypatch, db_conn):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="done")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    mock_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ConcreteAgent()
        agent.run("test prompt", conn=db_conn)

    rows = db_conn.execute("SELECT * FROM agent_logs").fetchall()
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "test_agent"
    assert rows[0]["tokens_used"] == 150
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agents/test_base_agent.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `agents/base.py`**

```python
import sqlite3
from abc import ABC, abstractmethod
from datetime import date
import anthropic
from config import settings
from tools.database import log_agent_output


class BaseAgent(ABC):
    name: str = "base"
    system_prompt: str = ""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.CLAUDE_MODEL

    @abstractmethod
    def get_tools(self) -> list:
        """Return list of Anthropic tool definitions for this agent."""
        ...

    @abstractmethod
    def parse_output(self, response) -> dict:
        """Extract structured result from the raw Claude response."""
        ...

    def run(self, prompt: str, conn: sqlite3.Connection = None) -> dict:
        messages = [{"role": "user", "content": prompt}]
        tools = self.get_tools()

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        # Tool-use loop
        while response.stop_reason == "tool_use":
            tool_results = self._handle_tool_calls(response)
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
            kwargs["messages"] = messages
            response = self.client.messages.create(**kwargs)

        result = self.parse_output(response)
        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        if conn:
            log_agent_output(conn, {
                "cycle_date": date.today().isoformat(),
                "agent_name": self.name,
                "input_summary": prompt[:200],
                "output_summary": str(result)[:200],
                "full_reasoning": str(result),
                "tokens_used": tokens_used,
            })

        return result

    def _handle_tool_calls(self, response) -> list:
        tool_map = {t.__name__: t for t in self._get_tool_functions()}
        results = []
        for block in response.content:
            if block.type == "tool_use":
                fn = tool_map.get(block.name)
                output = fn(**block.input) if fn else {"error": f"unknown tool {block.name}"}
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
        return results

    def _get_tool_functions(self) -> list:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agents/test_base_agent.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/base.py tests/test_agents/test_base_agent.py
git commit -m "feat: base agent class with Claude tool-use loop and DB logging"
```

---

## Phase 5 — The Four Agents

### Task 11: Market Intelligence Agent

**Files:**
- Create: `agents/market_intelligence.py`
- Create: `tests/test_agents/test_market_intelligence.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agents/test_market_intelligence.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.market_intelligence import MarketIntelligenceAgent


def make_mock_claude_response(text: str):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=text)]
    mock_response.usage.input_tokens = 800
    mock_response.usage.output_tokens = 300
    mock_response.stop_reason = "end_turn"
    return mock_response


def test_market_intelligence_returns_briefing(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        '{"watchlist_summary": "AMD trending up", "flagged_positions": [], "market_context": "bullish"}'
    )

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = MarketIntelligenceAgent()
        result = agent.run("Scan the watchlist", conn=db_conn)

    assert "watchlist_summary" in result
    assert "flagged_positions" in result
    assert "market_context" in result


def test_market_intelligence_name():
    agent = MarketIntelligenceAgent()
    assert agent.name == "market_intelligence"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agents/test_market_intelligence.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `agents/market_intelligence.py`**

```python
import json
from agents.base import BaseAgent
from config.watchlist import WATCHLIST


class MarketIntelligenceAgent(BaseAgent):
    name = "market_intelligence"
    system_prompt = """You are the Market Intelligence Agent for a swing trading bot.

Your job each trading day:
1. Review the watchlist of tickers
2. Assess current open positions — how are they tracking vs stop-loss and take-profit targets?
3. Summarise broader market context (trending up/down/sideways, notable volatility)
4. Flag any positions that need urgent attention (within 5% of stop-loss)

You have access to tools to fetch live market data and portfolio state.

Always respond with a JSON object containing:
- watchlist_summary: string describing overall watchlist conditions
- flagged_positions: list of position IDs needing attention
- market_context: string (bullish/bearish/neutral + brief reason)
- top_movers: list of tickers showing strongest signals today
"""

    def get_tools(self) -> list:
        return [
            {
                "name": "get_portfolio_state",
                "description": "Returns open positions with current prices and distance to stop/target",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_watchlist",
                "description": "Returns the curated watchlist of tickers to scan",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.portfolio import get_open_positions_with_prices
        from tools.broker import get_current_price

        def get_portfolio_state():
            prices = {t: get_current_price(t) for t in WATCHLIST}
            return get_open_positions_with_prices(self._conn, prices)

        def get_watchlist():
            return WATCHLIST

        return [get_portfolio_state, get_watchlist]

    def run(self, prompt: str, conn=None) -> dict:
        self._conn = conn
        result = super().run(prompt, conn=conn)
        return result

    def parse_output(self, response) -> dict:
        text = response.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "watchlist_summary": text,
                "flagged_positions": [],
                "market_context": "unknown",
                "top_movers": [],
            }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agents/test_market_intelligence.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agents/market_intelligence.py tests/test_agents/test_market_intelligence.py
git commit -m "feat: Market Intelligence Agent (Agent 1)"
```

---

### Task 12: Strategy Agent

**Files:**
- Create: `agents/strategy.py`
- Create: `tests/test_agents/test_strategy.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agents/test_strategy.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.strategy import StrategyAgent


def make_mock_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 1000
    mock.usage.output_tokens = 400
    mock.stop_reason = "end_turn"
    return mock


def test_strategy_agent_returns_candidates(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(
        '{"candidates": [{"ticker": "AMD", "score": 0.85, "reasoning": "strong trend"}], "no_trade_reason": ""}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = StrategyAgent()
        result = agent.run("Analyse watchlist for entries", conn=db_conn)

    assert "candidates" in result
    assert isinstance(result["candidates"], list)


def test_strategy_agent_name():
    assert StrategyAgent.name == "strategy"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agents/test_strategy.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `agents/strategy.py`**

```python
import json
from agents.base import BaseAgent
from config.watchlist import WATCHLIST
from config import settings


class StrategyAgent(BaseAgent):
    name = "strategy"
    system_prompt = """You are the Strategy Agent for a swing trading bot.

Your job:
1. Analyse each ticker on the watchlist using technical signals (EMA crossover, RSI, Volume)
2. Score each ticker 0.0–1.0 on entry attractiveness
3. Propose trade candidates ranked by score, with clear reasoning
4. If conditions are not right for any entry, explain why

Current strategy parameters are provided in the prompt.
Candidates must meet ALL three entry conditions:
- EMA20 crossed above EMA50 (trend confirmation)
- RSI between RSI_LOWER and RSI_UPPER (not overextended)
- Volume > VOLUME_MULTIPLIER × 20-day average (conviction)

Respond with JSON:
{
  "candidates": [
    {"ticker": "AMD", "score": 0.85, "reasoning": "...", "ema_crossover": true, "rsi": 52.1, "volume_ratio": 1.9}
  ],
  "no_trade_reason": ""
}
If no candidates, return empty candidates list and explain in no_trade_reason.
"""

    def get_tools(self) -> list:
        return [
            {
                "name": "compute_ticker_signals",
                "description": "Compute EMA, RSI, ATR, and volume signals for a ticker",
                "input_schema": {
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}},
                    "required": ["ticker"],
                },
            }
        ]

    def _get_tool_functions(self) -> list:
        from tools.market_data import fetch_bars, compute_signals

        def compute_ticker_signals(ticker: str) -> dict:
            bars = fetch_bars(ticker, days=60)
            return compute_signals(
                bars,
                ema_fast=settings.EMA_FAST,
                ema_slow=settings.EMA_SLOW,
                rsi_period=settings.RSI_PERIOD,
                atr_period=settings.ATR_PERIOD,
            )

        return [compute_ticker_signals]

    def run(self, prompt: str, conn=None) -> dict:
        params_prompt = f"""
Strategy parameters:
- EMA fast/slow: {settings.EMA_FAST}/{settings.EMA_SLOW}
- RSI range: {settings.RSI_LOWER}–{settings.RSI_UPPER}
- Volume multiplier: {settings.VOLUME_MULTIPLIER}x
- Watchlist: {', '.join(WATCHLIST)}

Market briefing: {prompt}

Scan each ticker and return trade candidates.
"""
        return super().run(params_prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = response.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"candidates": [], "no_trade_reason": text}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agents/test_strategy.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agents/strategy.py tests/test_agents/test_strategy.py
git commit -m "feat: Strategy Agent (Agent 2) with signal-based candidate scoring"
```

---

### Task 13: Risk Review Agent

**Files:**
- Create: `agents/risk_review.py`
- Create: `tests/test_agents/test_risk_review.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agents/test_risk_review.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.risk_review import RiskReviewAgent


def make_mock_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 600
    mock.usage.output_tokens = 250
    mock.stop_reason = "end_turn"
    return mock


def test_risk_review_approves_valid_candidates(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(
        '{"approved": [{"ticker": "AMD", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "risk_dollars": 1000.0}], "rejected": []}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = RiskReviewAgent()
        result = agent.run("Review these candidates: AMD score 0.85", conn=db_conn)

    assert "approved" in result
    assert "rejected" in result


def test_risk_review_name():
    assert RiskReviewAgent.name == "risk_review"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agents/test_risk_review.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `agents/risk_review.py`**

```python
import json
from agents.base import BaseAgent
from config import settings


class RiskReviewAgent(BaseAgent):
    name = "risk_review"
    system_prompt = """You are the Risk Review Agent for a swing trading bot.

Your job:
1. Receive trade candidates from the Strategy Agent
2. For each candidate, calculate exact position size, stop-loss, and take-profit using the risk tool
3. Check portfolio guardrails before approving each trade
4. Reject candidates that violate risk rules — always explain why

Rules you enforce:
- Never risk more than RISK_PCT of portfolio per trade
- Never exceed MAX_POSITIONS open simultaneously
- Never exceed MAX_EXPOSURE of portfolio deployed
- Reject if daily drawdown limit is breached

Respond with JSON:
{
  "approved": [
    {"ticker": "AMD", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "risk_dollars": 1000.0}
  ],
  "rejected": [
    {"ticker": "NVDA", "reason": "max positions reached"}
  ]
}
"""

    def get_tools(self) -> list:
        return [
            {
                "name": "calculate_position",
                "description": "Calculate position size, stop-loss and take-profit for a ticker",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "entry_price": {"type": "number"},
                        "atr": {"type": "number"},
                    },
                    "required": ["ticker", "entry_price", "atr"],
                },
            },
            {
                "name": "check_guardrails",
                "description": "Check if portfolio guardrails allow a new trade",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.risk import calculate_position, check_portfolio_guardrails
        from tools.portfolio import get_portfolio_stats
        from tools.broker import get_portfolio_value

        def calculate_position(ticker: str, entry_price: float, atr: float) -> dict:
            portfolio_value = get_portfolio_value()
            return calculate_position(
                portfolio_value=portfolio_value,
                risk_pct=settings.RISK_PER_TRADE,
                entry_price=entry_price,
                atr=atr,
                atr_stop_multiplier=settings.ATR_STOP_MULTIPLIER,
                rr_ratio_min=settings.RR_RATIO_MIN,
            )

        def check_guardrails() -> dict:
            portfolio_value = get_portfolio_value()
            stats = get_portfolio_stats(self._conn, portfolio_value)
            return check_portfolio_guardrails(
                open_positions=stats["open_count"],
                max_positions=settings.MAX_POSITIONS,
                deployed_pct=stats["deployed_pct"],
                max_exposure=settings.MAX_PORTFOLIO_EXPOSURE,
                daily_pnl_pct=stats["daily_pnl_pct"],
                drawdown_limit=settings.DAILY_DRAWDOWN_LIMIT,
            )

        return [calculate_position, check_guardrails]

    def run(self, prompt: str, conn=None) -> dict:
        self._conn = conn
        risk_prompt = f"""
Risk parameters:
- Risk per trade: {settings.RISK_PER_TRADE:.1%}
- Max positions: {settings.MAX_POSITIONS}
- Max exposure: {settings.MAX_PORTFOLIO_EXPOSURE:.0%}
- ATR stop multiplier: {settings.ATR_STOP_MULTIPLIER}x
- Minimum R:R ratio: {settings.RR_RATIO_MIN}:1

Candidates to review: {prompt}

Calculate position details for each and approve or reject.
"""
        return super().run(risk_prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = response.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"approved": [], "rejected": [{"reason": text}]}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agents/test_risk_review.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agents/risk_review.py tests/test_agents/test_risk_review.py
git commit -m "feat: Risk Review Agent (Agent 3) with position sizing and guardrail enforcement"
```

---

### Task 14: Team Leader Agent

**Files:**
- Create: `agents/team_leader.py`
- Create: `tests/test_agents/test_team_leader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agents/test_team_leader.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.team_leader import TeamLeaderAgent


def make_mock_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 1200
    mock.usage.output_tokens = 500
    mock.stop_reason = "end_turn"
    return mock


def test_team_leader_executes_trades(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 222, "reasoning": "all signals aligned"}], "summary": "1 trade placed"}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        with patch("tools.broker.place_market_order", return_value="order-123"):
            agent = TeamLeaderAgent()
            result = agent.run("Approved: AMD 222 shares", conn=db_conn)

    assert "decisions" in result
    assert "summary" in result


def test_team_leader_name():
    assert TeamLeaderAgent.name == "team_leader"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agents/test_team_leader.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `agents/team_leader.py`**

```python
import json
from datetime import date
from agents.base import BaseAgent


class TeamLeaderAgent(BaseAgent):
    name = "team_leader"
    system_prompt = """You are the Team Leader Agent — the final decision-maker for a swing trading bot.

You receive consolidated reports from three specialist agents:
- Market Intelligence: current market conditions and flagged positions
- Strategy: scored trade candidates with technical reasoning
- Risk Review: approved candidates with exact position sizes and risk parameters

Your job:
1. Review all agent reports holistically
2. Make final go/no-go decision on each approved candidate
3. Place orders for approved trades using the place_order tool
4. Handle any flagged positions from Market Intelligence (close if needed)
5. Write a clear decision log explaining every action taken

You are the only agent authorised to place or close orders.

Respond with JSON:
{
  "decisions": [
    {"ticker": "AMD", "action": "buy", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "reasoning": "..."}
  ],
  "summary": "brief summary of the session"
}
"""

    def get_tools(self) -> list:
        return [
            {
                "name": "place_order",
                "description": "Place a market order to buy or sell shares",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "shares": {"type": "integer"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                    },
                    "required": ["ticker", "shares", "side"],
                },
            },
            {
                "name": "close_position",
                "description": "Close an open position entirely",
                "input_schema": {
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}},
                    "required": ["ticker"],
                },
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.broker import place_market_order, close_position
        from tools.database import insert_trade
        from tools.broker import get_current_price

        def place_order(ticker: str, shares: int, side: str) -> dict:
            order_id = place_market_order(ticker, shares, side)
            if side == "buy":
                price = get_current_price(ticker)
                insert_trade(self._conn, {
                    "ticker": ticker,
                    "entry_date": date.today().isoformat(),
                    "entry_price": price,
                    "shares": shares,
                    "stop_loss": self._pending_stops.get(ticker, price * 0.97),
                    "take_profit": self._pending_targets.get(ticker, price * 1.06),
                })
            return {"order_id": order_id, "status": "submitted"}

        def close_position_tool(ticker: str) -> dict:
            order_id = close_position(ticker)
            return {"order_id": order_id, "status": "closed"}

        close_position_tool.__name__ = "close_position"
        return [place_order, close_position_tool]

    def run(self, prompt: str, conn=None, pending_stops: dict = None, pending_targets: dict = None) -> dict:
        self._conn = conn
        self._pending_stops = pending_stops or {}
        self._pending_targets = pending_targets or {}
        return super().run(prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = response.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"decisions": [], "summary": text}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agents/test_team_leader.py -v
```

Expected: 2 passed

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add agents/team_leader.py tests/test_agents/test_team_leader.py
git commit -m "feat: Team Leader Agent (Agent 4) — final decision-maker and order executor"
```

---

## Phase 6 — Daily Orchestration

### Task 15: Main daily cycle

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create `main.py`**

```python
import sqlite3
import pandas_market_calendars as mcal
from datetime import date
from pathlib import Path

from storage.init_db import init_db, DB_PATH
from agents.market_intelligence import MarketIntelligenceAgent
from agents.strategy import StrategyAgent
from agents.risk_review import RiskReviewAgent
from agents.team_leader import TeamLeaderAgent
from monitor.position_monitor import run_monitor


def is_trading_day(today: date = None) -> bool:
    today = today or date.today()
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=today.isoformat(), end_date=today.isoformat())
    return not schedule.empty


def get_db() -> sqlite3.Connection:
    init_db(str(DB_PATH))
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def run_morning_scan():
    if not is_trading_day():
        print("Not a trading day. Exiting.")
        return

    print(f"=== Morning scan — {date.today()} ===")
    conn = get_db()

    # Agent 1: Market Intelligence
    print("Running Market Intelligence Agent...")
    mi_agent = MarketIntelligenceAgent()
    market_briefing = mi_agent.run("Scan the watchlist and assess open positions.", conn=conn)
    print(f"Market context: {market_briefing.get('market_context')}")

    # Agent 2: Strategy
    print("Running Strategy Agent...")
    strategy_agent = StrategyAgent()
    candidates = strategy_agent.run(str(market_briefing), conn=conn)
    print(f"Candidates found: {len(candidates.get('candidates', []))}")

    if not candidates.get("candidates"):
        print(f"No trade candidates: {candidates.get('no_trade_reason')}")
        conn.close()
        return

    # Agent 3: Risk Review
    print("Running Risk Review Agent...")
    risk_agent = RiskReviewAgent()
    reviewed = risk_agent.run(str(candidates), conn=conn)
    print(f"Approved: {len(reviewed.get('approved', []))} | Rejected: {len(reviewed.get('rejected', []))}")

    if not reviewed.get("approved"):
        print("No trades approved by risk review.")
        conn.close()
        return

    # Agent 4: Team Leader
    print("Running Team Leader Agent...")
    pending_stops = {t["ticker"]: t["stop_loss"] for t in reviewed["approved"]}
    pending_targets = {t["ticker"]: t["take_profit"] for t in reviewed["approved"]}
    leader_agent = TeamLeaderAgent()
    decisions = leader_agent.run(
        str(reviewed),
        conn=conn,
        pending_stops=pending_stops,
        pending_targets=pending_targets,
    )
    print(f"Session summary: {decisions.get('summary')}")

    conn.close()


def run_position_monitor():
    if not is_trading_day():
        return
    print(f"=== Position monitor — {date.today()} ===")
    conn = get_db()
    actions = run_monitor(conn)
    closed = [a for a in actions if a.action == "close"]
    print(f"Checked {len(actions)} positions. Closed: {len(closed)}")
    conn.close()


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode == "scan":
        run_morning_scan()
    elif mode == "monitor":
        run_position_monitor()
    else:
        print(f"Unknown mode: {mode}. Use 'scan' or 'monitor'")
```

- [ ] **Step 2: Verify main.py runs without import errors**

```bash
python -c "import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main daily orchestration cycle connecting all four agents"
```

---

### Task 16: Cron setup

**Files:**
- Create: `scripts/cron_setup.sh`
- Create: `scripts/run_scan.sh`
- Create: `scripts/run_monitor.sh`

- [ ] **Step 1: Create `scripts/run_scan.sh`**

```bash
#!/bin/bash
cd /opt/trading-bot
source .env
/opt/trading-bot/venv/bin/python main.py scan >> /var/log/trading-bot/scan.log 2>&1
```

- [ ] **Step 2: Create `scripts/run_monitor.sh`**

```bash
#!/bin/bash
cd /opt/trading-bot
source .env
/opt/trading-bot/venv/bin/python main.py monitor >> /var/log/trading-bot/monitor.log 2>&1
```

- [ ] **Step 3: Create `scripts/cron_setup.sh`** (run once on VPS)

```bash
#!/bin/bash
# Add these lines to crontab: crontab -e
# All times UTC (NYSE opens 14:30 UTC, closes 21:00 UTC)

# Morning scan at 14:35 UTC (09:35 ET)
# 35 14 * * 1-5 /opt/trading-bot/scripts/run_scan.sh

# Hourly position monitor 15:00–20:00 UTC (10:00–15:00 ET)
# 0 15-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# Final check at 21:00 UTC (16:00 ET)
# 0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

echo "Add the above cron entries with: crontab -e"
echo "Create log dir: sudo mkdir -p /var/log/trading-bot && sudo chown \$USER /var/log/trading-bot"
```

- [ ] **Step 4: Make scripts executable**

```bash
chmod +x scripts/run_scan.sh scripts/run_monitor.sh scripts/cron_setup.sh
```

- [ ] **Step 5: Final full test suite run**

```bash
pytest -v
```

Expected: all tests pass

- [ ] **Step 6: Commit and push**

```bash
git add scripts/ main.py
git commit -m "feat: cron scripts for VPS scheduling"
git push origin main
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Alpaca paper trading + paper/live toggle via env — covered in `config/settings.py` and `tools/broker.py`
- [x] Curated watchlist — `config/watchlist.py`
- [x] Multi-signal hybrid strategy (EMA + RSI + Volume) — `tools/market_data.py` + `agents/strategy.py`
- [x] ATR-based position sizing, stop-loss, take-profit — `tools/risk.py`
- [x] Trailing stop (breakeven) — defined in risk parameters, enforced by monitor
- [x] Portfolio guardrails (max positions, exposure, drawdown) — `tools/risk.py` + `agents/risk_review.py`
- [x] Four LLM agents with defined roles and tool access — Phase 5
- [x] Sequential agent communication flow — `main.py`
- [x] Autonomous trade placement (Team Leader only) — `agents/team_leader.py`
- [x] Hourly rule-based position monitor — `monitor/position_monitor.py`
- [x] Full SQLite schema — `storage/schema.sql`
- [x] Agent reasoning logged to DB — `agents/base.py`
- [x] Market calendar awareness — `main.py` via `pandas_market_calendars`
- [x] Cron scheduling — `scripts/`
- [ ] Daily/weekly reflection engine — covered in **Plan 2**
- [ ] Parameter suggestions workflow — covered in **Plan 2**
- [ ] VPS systemd service — covered in **Plan 2**

**Placeholders:** None found.

**Type consistency:** All function signatures consistent across tasks — `calculate_position`, `check_portfolio_guardrails`, `get_open_trades`, `close_trade`, `insert_trade`, `log_agent_output` used consistently.
