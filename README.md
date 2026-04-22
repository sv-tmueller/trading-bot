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
0 14-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

| Schedule | UTC | ET | German (CEST) | Purpose |
|---|---|---|---|---|
| Scan | 13:35 | 09:35 | 15:35 | Morning agent pipeline (5 min after open) |
| Monitor | :00 14–20 | 10:00–16:00 | 16:00–22:00 | Hourly position check |
| Final check | 21:00 | 17:00 | 23:00 | End-of-day close |

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
| Position closed (monitor) | Ticker, reason, silent if nothing closed |
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
