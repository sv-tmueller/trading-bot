# Trading Bot

A self-reflecting, multi-agent LLM-powered swing trading bot for US equities. Four Claude AI agents collaborate each morning to scan the market, propose trades, review risk, and execute orders — all on Alpaca paper trading by default.

## How It Works

Each trading day the bot runs a sequential four-agent pipeline:

```
Market Intelligence → Strategy → Risk Review → Team Leader
```

1. **Market Intelligence** — Scans the watchlist, reviews open positions, summarises market context, flags anything within 5% of stop-loss.
2. **Strategy** — Analyses each ticker's EMA crossover, RSI, and volume signals. Scores candidates 0–1 and returns ranked trade ideas.
3. **Risk Review** — Calculates exact position sizes using ATR-based stop distances. Enforces portfolio guardrails (max positions, max exposure, daily drawdown limit). Approves or rejects each candidate.
4. **Team Leader** — Final decision-maker. Places orders via Alpaca, records trades in the database, and writes a session summary.

Between agent cycles, a lightweight **position monitor** runs hourly and closes positions that hit their stop-loss, take-profit, or max hold limit — no LLM cost.

### Entry Conditions (all three required)

- EMA 20 crossed above EMA 50 (trend confirmation)
- RSI(14) between 40–60 (not overextended)
- Volume > 1.5× 20-day average (conviction)

### Risk Rules

| Parameter | Default |
|---|---|
| Risk per trade | 1% of portfolio |
| Max open positions | 5 |
| Max portfolio exposure | 20% |
| Daily drawdown limit | 3% |
| Max hold days | 5 |
| Min reward:risk ratio | 2:1 |
| Stop distance | 1.5× ATR |

## Setup

### Prerequisites

- Python 3.9+
- [Alpaca account](https://alpaca.markets) (free paper trading)
- [Anthropic API key](https://console.anthropic.com)

### Install

```bash
git clone https://github.com/sv-tmueller/trading-bot
cd trading-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

Create a `.env` file in the project root:

```env
TRADING_MODE=paper

ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret

ANTHROPIC_API_KEY=your_anthropic_key
CLAUDE_MODEL=claude-sonnet-4-6

# Optional overrides (safe defaults shown)
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
```

### Initialise the database

```bash
python3 -c "from storage.init_db import init_db; init_db()"
```

## Running

### Morning scan (once per day)

```bash
python3 main.py scan
```

### Hourly position monitor

```bash
python3 main.py monitor
```

## VPS Deployment

### 1. SSH in and install dependencies

```bash
ssh user@your-vps-ip
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
```

### 2. Clone the repo

```bash
git clone https://github.com/sv-tmueller/trading-bot /opt/trading-bot
cd /opt/trading-bot
```

### 3. Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Create your `.env` file on the VPS

```bash
nano /opt/trading-bot/.env
```

```env
TRADING_MODE=paper
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
ANTHROPIC_API_KEY=your_anthropic_key
CLAUDE_MODEL=claude-sonnet-4-6
```

Save with `Ctrl+O`, exit with `Ctrl+X`.

### 5. Initialise the database

```bash
cd /opt/trading-bot
source venv/bin/activate
python3 -c "from storage.init_db import init_db; init_db()"
```

### 6. Create the log directory

```bash
sudo mkdir -p /var/log/trading-bot
sudo chown $USER /var/log/trading-bot
```

### 7. Test manually before scheduling

```bash
python3 main.py scan
```

### 8. Set up cron

```bash
crontab -e
```

Add these lines (all times UTC):

```
35 14 * * 1-5 /opt/trading-bot/scripts/run_scan.sh
0 15-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

| Schedule | Purpose |
|---|---|
| 14:35 Mon–Fri | Morning agent pipeline (09:35 ET) |
| :00 15–20 Mon–Fri | Hourly position check |
| 21:00 Mon–Fri | End-of-day final check |

### Updating the bot

When you push code changes to GitHub, on the VPS run:

```bash
cd /opt/trading-bot && git pull
```

No restart needed — cron picks up the latest code on each run.

## Watchlist

Default tickers: `AMD, NOW, SHEL, NVDA, MSFT, GOOGL, META, AMZN`

Edit `config/watchlist.py` to change the list. Tickers should be S&P 500 constituents with high liquidity.

## Switching to Live Trading

Change one env var:

```env
TRADING_MODE=live
```

The bot will route to `api.alpaca.markets` and place real orders. Test thoroughly on paper first.

## Development

```bash
# Run all tests
python3 -m pytest

# Run a specific test file
python3 -m pytest tests/test_monitor.py -v
```

## Project Structure

```
├── main.py                  # Entry point — scan and monitor modes
├── config/
│   ├── settings.py          # All parameters (env-driven)
│   └── watchlist.py         # Tickers to scan
├── storage/
│   ├── schema.sql           # SQLite schema
│   └── init_db.py           # One-time DB setup
├── tools/
│   ├── database.py          # Trade and signal storage
│   ├── market_data.py       # OHLCV + signal computation
│   ├── portfolio.py         # Open positions and stats
│   ├── risk.py              # Position sizing, stop/target
│   └── broker.py            # Alpaca order wrapper
├── monitor/
│   └── position_monitor.py  # Hourly rule-based exit check
├── agents/
│   ├── base.py              # BaseAgent with tool-use loop
│   ├── market_intelligence.py
│   ├── strategy.py
│   ├── risk_review.py
│   └── team_leader.py
└── scripts/
    ├── run_scan.sh
    ├── run_monitor.sh
    └── cron_setup.sh
```
