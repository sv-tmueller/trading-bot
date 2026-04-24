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
DATA_FEED=iex

ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret

ANTHROPIC_API_KEY=your_anthropic_key
CLAUDE_MODEL=claude-sonnet-4-6

# Optional overrides (safe defaults shown)
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
MAX_HOLD_DAYS=5
RR_RATIO_MIN=2.0
MAX_PORTFOLIO_EXPOSURE=0.20
```

> **Note:** Free Alpaca paper trading accounts use the IEX data feed (`DATA_FEED=iex`). Paid live accounts use SIP (`DATA_FEED=sip`), which covers 100% of market volume vs ~60% for IEX.

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

### Backtest (historical simulation)

```bash
# Default: 1 year, strategy parameters from settings.py
python3 main.py backtest

# Custom parameters
python3 main.py backtest --years 3 --rsi-lower 35 --rsi-upper 70
python3 main.py backtest --ema-fast 10 --ema-slow 30 --atr-multiplier 2.0 --rr-ratio 2.5
```

Runs the EMA crossover strategy against each watchlist ticker using `yfinance` data and prints a per-ticker results table to the terminal. Also sends a summary to Discord.

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
DATA_FEED=iex
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

If prompted to choose an editor, select **1** (nano). You'll see an empty file — scroll to the bottom and add these lines (all times UTC):

```
35 13 * * 1-5 /opt/trading-bot/scripts/run_scan.sh
0 14-19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
55 19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

| Schedule | UTC | ET | German (CEST) | Purpose |
|---|---|---|---|---|
| Scan | 13:35 | 09:35 | 15:35 | Morning agent pipeline (5 min after open) |
| Monitor | :00 14–19 | 10:00–15:00 | 16:00–21:00 | Hourly position check |
| Pre-close | 19:55 | 15:55 | 21:55 | Final check 5 min before NYSE close |

Save and exit: `Ctrl+O` → Enter → `Ctrl+X`. You should see `crontab: installing new crontab` confirming it worked.

### Updating the bot

When you push code changes to GitHub, on the VPS run:

```bash
cd /opt/trading-bot && git pull
```

No restart needed — cron picks up the latest code on each run.

### Private repository authentication

GitHub no longer accepts passwords for git operations. If the repo is private, create a **Personal Access Token (PAT)**:

1. GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)**
2. Select the **`repo`** scope, set an expiration, and generate
3. Embed the token in the remote URL on the VPS (do this once):

```bash
git remote set-url origin https://sv-tmueller:<YOUR_TOKEN>@github.com/sv-tmueller/trading-bot.git
```

Future `git pull` calls will work without any prompt.

## Discord Notifications (via n8n)

The bot sends trade summaries and alerts to a Discord channel through an n8n webhook.

### What gets posted

| Event | Notification |
|---|---|
| Scan complete with trades | Summary of market context, approved trades, token cost |
| No candidates found | Brief note with reason |
| No trades approved | Risk review rejection summary |
| Position monitor (hourly) | Heartbeat with position count; closures listed if any |
| *(errors)* | Stack trace excerpt |

### Setup

**1. Add the Discord webhook as an n8n credential**

In n8n: **Credentials → New → Discord Webhook API** → paste your Discord channel webhook URL → name it `Discord Webhook #trading-bot` → save.

**2. Import the workflow**

In n8n: **Workflows → Add workflow → ⋯ (top right) → Import from JSON** → paste the contents of `n8n/trading-bot-discord-notifications.json` → save.

On the Discord node, select `Discord Webhook #trading-bot` as the credential, then **activate** the workflow.

**3. Copy the n8n webhook URL**

After activating, click the Webhook trigger node — copy the production URL (looks like `http://your-vps:5678/webhook/trading-bot-notify`).

**4. Add to `.env`**

```env
N8N_WEBHOOK_URL=http://localhost:5678/webhook/trading-bot-notify
```

> **Important:** Use `http://localhost:5678` (not your public n8n URL) since the bot and n8n run on the same VPS. If your n8n is behind Cloudflare Access, the public URL will be blocked with a 302 redirect — localhost bypasses this entirely and is more secure.

The bot will silently skip notifications if `N8N_WEBHOOK_URL` is not set, so this is fully optional.

**5. Test the connection**

```bash
curl -X POST http://localhost:5678/webhook/trading-bot-notify -H "Content-Type: application/json" -d '{"message": "Test from trading bot"}'
```

If a message appears in Discord, the setup is complete.

## Watchlist

Default tickers: `AMD, NOW, SHEL, NVDA, MSFT, GOOGL, META, AMZN`

Edit `config/watchlist.py` to change the list. Tickers should be S&P 500 constituents with high liquidity.

## Before going live

Paper trading on Alpaca uses simulated fills at the mid-price with no market impact. Real trading will differ in several ways:

| Factor | Paper trading | Live trading |
|---|---|---|
| Fill price | Mid-price | Ask (buys) / Bid (sells) |
| Spread cost | None | Implicit in bid-ask spread |
| Market impact | None | Thin books can cause partial fills |
| Commission | Simulated (0.1%) | Zero (Alpaca US equities) |

**Checklist before switching to live capital:**
- [ ] Compare paper PnL vs backtest results to calibrate the gap
- [ ] Set a minimum liquidity filter — edit `config/watchlist.py` to remove tickers with average daily volume below 1M shares
- [ ] Run the backtest on 3 years of data (`python3 main.py backtest --years 3`) to confirm strategy robustness across different market regimes
- [ ] Review open positions and confirm stop-loss distances are acceptable at live spread widths

## Switching to Live Trading

Update two env vars in your `.env`:

```env
TRADING_MODE=live
DATA_FEED=sip
```

The bot will route to `api.alpaca.markets` and use the full SIP data feed. Test thoroughly on paper first — real orders will be placed immediately.

## Development

```bash
# Run all tests
python3 -m pytest

# Run a specific test file
python3 -m pytest tests/test_monitor.py -v
```

## Project Structure

```
├── main.py                  # Entry point — scan, monitor, and backtest modes
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
├── backtest/
│   ├── data.py              # yfinance OHLCV fetcher
│   ├── strategy.py          # EMAStrategy (backtesting.py subclass)
│   ├── report.py            # Terminal formatter + Discord notify
│   └── runner.py            # Per-ticker orchestration and aggregation
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

## Changelog

### v1.4.1 — pre-release (2026-04-23)

**Data integrity hardening:**
- `close_position` and `place_order` now fetch the current price **before** calling the broker, eliminating the ghost-position risk where a failed post-broker price lookup would leave the DB out of sync with the actual account state (#21)
- `place_market_order` returns the Alpaca fill price; entry price in the DB now uses the actual fill rather than a post-order quote (#8)
- Fill price falls back to the pre-order quote if the order isn't yet filled (common in paper trading)

**Operational reliability:**
- DB connection is now closed in a `finally` block — guaranteed even when an agent or the monitor raises mid-run (#22)
- `MAX_HOLD_DAYS`, `RR_RATIO_MIN`, and `MAX_PORTFOLIO_EXPOSURE` are now configurable via environment variables with validation at startup (#6)

### v1.4.0 (2026-04-23)

- Morning scan and position monitor wrapped in `try/except` — errors post to Discord and never crash the cron process (#2)
- Inter-agent data serialised with `json.dumps` instead of Python `repr` — downstream agents can now reliably parse the handoff (#4)
- `close_position` tool passes the LLM-supplied exit reason through to the DB (#14)
- `get_current_price` raises `ValueError` on a zero or missing quote instead of silently returning 0.0 (#3)
- `fetch_bars` requests a wider historical window to ensure EMA50 always has enough warmup data (#5)
- Position monitor heartbeat now fires every hour regardless of whether any positions were closed (#17)

### v1.3.0 (2026-04-22)

- Backtest module: run the EMA crossover strategy against historical data via `python3 main.py backtest` (#10)
- Configurable backtest parameters: `--years`, `--rsi-lower`, `--rsi-upper`, `--ema-fast`, `--ema-slow`, `--atr-multiplier`, `--rr-ratio`
- Backtest results posted to Discord

### v1.0.0 — initial release
