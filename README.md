# Trading Bot

A deterministic rules-engine swing trading bot. Each weekday after the US close, it computes a 200-day SMA on SPY, decides whether to be LONG (in a 3x leveraged ETF) or in CASH, reconciles with Interactive Brokers, and flips the position via a market order if needed. An hourly kill switch liquidates if drawdown breaches a threshold.

No LLM is in the trading path. The strategy is a pure function (`strategy.regime.compute_target_state`); every decision is reproducible from the SPY history alone.

## Architecture

```
cron 22:30 UTC weekdays  ->  daily_check.py  ->  IBKR (place / liquidate)
                             |
                             v
                             regime_state, trades, audit_log (SQLite)
                             |
                             v
                             n8n webhook -> Discord

cron hourly market hours ->  monitor/kill_switch.py  ->  IBKR (liquidate on DD breach)
```

**Decision rule.** `daily_check.py` fetches 2y of SPY daily bars from yfinance, computes the 200-day SMA, and asks `compute_target_state(spy_close, spy_sma200, current_state, kill_switch_active)`:

- **LONG** when `spy_close > spy_sma200` (the kill-switch flag, if set, is cleared on this transition).
- **CASH** otherwise (when SPY is at or below the 200-DMA — the kill-switch flag, if set, is preserved).

If `target_state != current_state`, the bot places a market order on `BOT_TICKER` (a 3x leveraged ETF such as `WSPL.DE` / 3USL UCITS on Xetra) — either a BUY for ~99% of account value, or a SELL of the entire position.

**Kill switch.** `monitor/kill_switch.py` runs hourly during US market hours. If `BOT_TICKER` drawdown from its 30-trading-day rolling high exceeds `KILL_SWITCH_DRAWDOWN_PCT` (default 25%), it liquidates the position and sets `kill_switch_active=1` in `regime_state`. While the flag is active **and SPY remains below the 200-DMA**, `daily_check.py` keeps the bot in CASH. The flag is cleared on the first day SPY closes back above the 200-DMA, at which point the bot re-enters LONG — so a single bad-week kill-switch fire does not lock the bot out of the next bull run.

## Starting the bot — Monday 2026-05-11

This is the runbook for the first soak run. The bot has been built and tested but has not yet executed against a live broker. Plan: run `daily_check.py --dry-run` for a full week (Monday 2026-05-11 through Friday 2026-05-15), confirm the audit + Discord trail looks right, then flip the dry-run flag off the following Monday.

### Day zero pre-flight (Friday afternoon or Monday morning before US close)

1. SSH into the VPS:
   ```
   ssh -L 54545:localhost:54545 root@your-vps-ip
   sudo -u trader -i
   cd /opt/trading-bot
   ```

2. Pull the latest main:
   ```
   git pull origin main
   ```

3. Verify your `.env` has the right variables. Critical: `DAILY_CHECK_DRY_RUN=true` for the soak week (the bot runs the full pipeline but skips broker orders):
   ```
   grep -E '^(DAILY_CHECK_DRY_RUN|TRADING_PAUSED|IBKR_|BOT_|REGIME_|KILL_SWITCH_)' .env
   ```
   You should see at minimum:
   - `DAILY_CHECK_DRY_RUN=true`
   - `TRADING_PAUSED=false` (or absent — defaults to false)
   - `IBKR_HOST=127.0.0.1`
   - `IBKR_PORT=4002` (paper) or `4001` (live)
   - `IBKR_CLIENT_ID=<some integer>` (default: `1`)
   - `BOT_TICKER=<your-3x-etf>`, `BOT_BENCHMARK=SPY`
   - `REGIME_SMA_DAYS=200`
   - `KILL_SWITCH_DRAWDOWN_PCT=0.25`, `KILL_SWITCH_LOOKBACK_DAYS=30`

4. Verify IB Gateway / IBC daemon is running:
   ```
   sudo systemctl status ibgateway
   ```
   You want to see `Active: active (running)` in the output. If not, follow [`docs/operations/ibkr-vps-setup.md`](docs/operations/ibkr-vps-setup.md) to install or start it.

5. Verify TWS connectivity (read-only — no orders):
   ```
   venv/bin/python -c "from ib_insync import IB; ib = IB(); ib.connect('127.0.0.1', 4002, clientId=99); print('connected:', ib.isConnected()); print('account:', ib.managedAccounts()); ib.disconnect()"
   ```
   You want `connected: True` and a non-empty account list. We use `clientId=99` here so this diagnostic does not clash with cron's running connection (which uses `IBKR_CLIENT_ID`, default `1`). If TWS rejects the connection, your gateway is configured to allow only specific client IDs — see [`docs/operations/ibkr-vps-setup.md`](docs/operations/ibkr-vps-setup.md) for the API-config check, or substitute `clientId=settings.IBKR_CLIENT_ID + 99` to use the configured ID with an offset.

6. Verify the test suite still passes:
   ```
   venv/bin/python -m pytest -q
   ```
   Expected: every test passing, zero failures.

### First soak run (Monday 2026-05-11 evening, after 22:30 UTC ~ 18:30 ET)

7. Run a manual dry-run:
   ```
   venv/bin/python daily_check.py --dry-run
   ```
   What you should see:
   - First line on stdout: `[daily_check] DRY-RUN mode active — no broker orders will be placed.`
   - Discord card titled `[DRY-RUN] regime_flip <state>` (or no card if no flip).
   - Exit code 0.

8. Verify the audit row landed:
   ```
   sqlite3 trading_bot.db "SELECT id, started_at, finished_at, outcome, notes FROM audit_log ORDER BY id DESC LIMIT 1"
   ```
   `outcome` should start with `dry_run:` (one of `dry_run:would_flip_long`, `dry_run:would_flip_cash`, or `dry_run:no_change`).

9. Verify the regime_state row landed:
   ```
   sqlite3 trading_bot.db "SELECT date, spy_close, spy_sma200, target_state, current_state FROM regime_state ORDER BY date DESC LIMIT 1"
   ```
   `current_state` should be unchanged from before the run (dry-run does not advance it).

### Soak week (Tuesday 2026-05-12 -> Friday 2026-05-15)

10. Each weekday at any time after 22:30 UTC, repeat steps 7-9. Confirm the dry-run pipeline writes audit + regime_state rows and posts to Discord with `[DRY-RUN]` markers.

11. Mid-soak (Wednesday 2026-05-13 ideally), do a kill-switch smoke run. This is a real run, not a dry-run — `monitor/kill_switch.py` has no `--dry-run` mode — but it is a no-op when the bot is in CASH (it short-circuits before any broker action and ends with a `success:no_position` outcome in `audit_log`). If you happen to be in LONG and drawdown is small, it is also a no-op:
    ```
    venv/bin/python -m monitor.kill_switch
    ```
    Expected: cycle completes in <5 seconds, writes a row to `regime_state` (or updates the existing one), and writes a `success:no_position` (CASH) or `success:within_threshold` (LONG, DD below threshold) row to `audit_log`.

### Going live (Monday 2026-05-18 onward — after a clean soak week)

12. Flip the dry-run flag off:
    ```
    sed -i -E 's/^DAILY_CHECK_DRY_RUN=.*/DAILY_CHECK_DRY_RUN=false/' .env
    grep '^DAILY_CHECK_DRY_RUN' .env   # confirm it now reads "false"
    ```
    The `-E` enables extended regex; `.*` matches whatever value (or trailing comment) was there. The grep should now show `DAILY_CHECK_DRY_RUN=false`.

13. **Disable any legacy root crontab entries** from the v1.14 era. The old bot ran from root's crontab; the new bot runs from trader's. Leaving both active causes conflicts:
    ```
    sudo crontab -l | grep -v trading-bot | grep -v "main\.py scan" | grep -v "main\.py monitor" | sudo crontab -
    sudo crontab -l   # confirm trading-bot lines are gone from root
    ```
    (If `sudo crontab -l` says "no crontab for root", you're already clean — skip this step.)

14. Install the crontab:
    ```
    bash scripts/cron_setup.sh
    sudo crontab -u trader -l | grep trading-bot
    ```
    Expected: two cron lines for `daily_check.py` (22:30 UTC weekdays) and `monitor.kill_switch` (hourly during US market hours).

15. Watch the first live run on Monday 2026-05-18 evening:
    ```
    tail -f /opt/trading-bot/logs/daily_check.log
    ```

### If anything goes sideways

- Pause new entries (writes `TRADING_PAUSED=true` to `.env` atomically):
  ```
  venv/bin/python main.py panic --pause
  ```
- Cancel all open IBKR orders:
  ```
  venv/bin/python main.py panic --cancel-orders
  ```
- Liquidate all positions (real action — requires `--confirm`):
  ```
  venv/bin/python main.py panic --liquidate --confirm
  ```
- Disable cron (so the bot stops trying every cycle):
  ```
  sudo crontab -u trader -l | grep -v trading-bot | sudo crontab -u trader -
  ```
  Re-install with `bash scripts/cron_setup.sh` once you are ready to resume.

## Quick Start — daily session on the VPS

The bot runs unattended via cron. You only need to log in when you want to inspect logs, debug, vibe-code, or push changes. Every session starts the same way:

```bash
# 1. SSH in (the -L port-forward lets the OAuth callback land on the VPS
#    but open in your laptop browser — needed for first-time Claude Code auth).
ssh -L 54545:localhost:54545 root@your-vps-ip     # or: your-sudo-user@your-vps-ip

# 2. Become the `trader` user
#    /opt/trading-bot is owned by trader, so run Claude Code as trader to
#    keep file ownership consistent.
sudo -u trader -i

# 3. Go to the project
cd /opt/trading-bot

# 4. Resume your last Claude Code session
claude --continue
```

Variants of step 4:
- `claude --resume` — pick from a list of recent sessions
- `claude` — start a brand-new session
- `claude --help` — full flag reference

## Commands

```bash
# Run today's regime check + flip (cron does this automatically at 22:30 UTC)
venv/bin/python daily_check.py
venv/bin/python daily_check.py --dry-run    # full pipeline, no broker orders

# Hourly drawdown check (cron does this automatically during US market hours)
venv/bin/python -m monitor.kill_switch

# Backtest the regime strategy
venv/bin/python main.py backtest --years 5

# Trailing 30-day trade summary
venv/bin/python main.py summary

# Kill button (deterministic, no LLM)
venv/bin/python main.py panic --pause                   # halt new entries
venv/bin/python main.py panic --cancel-orders           # cancel all open orders
venv/bin/python main.py panic --liquidate --confirm     # close all positions

# Run all tests
venv/bin/python -m pytest

# Initialise the database (first time only)
venv/bin/python -c "from storage.init_db import init_db; init_db()"
```

## Setup

### Prerequisites

- Python 3.9+ and git
- An [Interactive Brokers](https://www.interactivebrokers.com/) account (paper or live) with IB Gateway running on the host
- An n8n instance (optional — for Discord notifications)

If Python and git aren't installed yet:

| OS | One-time install |
|---|---|
| macOS | `brew install python git` (requires [Homebrew](https://brew.sh)) |
| Ubuntu / Debian | `sudo apt install -y python3 python3-pip python3-venv git` |
| Windows | Install [Python](https://python.org/downloads) (check "Add to PATH") and [Git](https://git-scm.com/download/win), then use PowerShell for the rest |

### Install

```bash
git clone https://github.com/sv-tmueller/trading-bot
cd trading-bot
python3 -m venv venv
source venv/bin/activate        # macOS / Linux — use `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

### Configure

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
nano .env
```

The minimum required settings are the IBKR connection (`IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`) and `BOT_TICKER`. Everything else has a sensible default — see `.env.example` for the full list and `docs/CURRENT_CONFIG.md` for the current production values.

### Initialise the database

```bash
venv/bin/python -c "from storage.init_db import init_db; init_db()"
```

This creates `trading_bot.db` with the schema for `regime_state`, `trades`, and `audit_log`. Idempotent — safe to re-run after a `git pull`.

### IB Gateway setup

The bot connects to IB Gateway (or TWS) over a local TCP socket — by default `127.0.0.1:4002` for paper, `127.0.0.1:4001` for live. See [`docs/operations/ibkr-vps-setup.md`](docs/operations/ibkr-vps-setup.md) for the headless IB Gateway / IBC install on Ubuntu.

## Discord Notifications (via n8n)

The bot posts structured event payloads (`event_type: regime_flip`, `kill_switch_fired`, `trade_failed`, `tws_disconnected`, `state_desync`) to an n8n webhook, which forwards to Discord. Set `N8N_WEBHOOK_URL` in `.env`. If unset, notifications are silently skipped — the bot keeps trading.

### Setup

**1. Add the Discord webhook as an n8n credential**

In n8n: **Credentials -> New -> Discord Webhook API** -> paste your Discord channel webhook URL -> name it `Discord Webhook #trading-bot` -> save.

**2. Import the workflow**

In n8n: **Workflows -> Add workflow -> ... (top right) -> Import from JSON** -> paste the contents of `n8n/trading-bot-discord-notifications.json` -> save.

On the Discord node, select `Discord Webhook #trading-bot` as the credential, then **activate** the workflow.

**3. Copy the n8n webhook URL**

After activating, click the Webhook trigger node — copy the production URL (looks like `http://your-vps:5678/webhook/trading-bot-notify`).

**4. Add to `.env`**

```env
N8N_WEBHOOK_URL=http://localhost:5678/webhook/trading-bot-notify
```

> Use `http://localhost:5678` (not your public n8n URL) since the bot and n8n run on the same VPS. If your n8n is behind Cloudflare Access, the public URL will be blocked with a 302 redirect — localhost bypasses this entirely and is more secure.

**5. Test the connection**

```bash
curl -X POST http://localhost:5678/webhook/trading-bot-notify -H "Content-Type: application/json" -d '{"message": "Test from trading bot"}'
```

If a message appears in Discord, the setup is complete.

## Migration from v1.14

v1.14 (and earlier) used a 4-LLM-agent pipeline against Alpaca paper trading. After a 5-year backtest showing the LLM bot was effectively a coin flip vs. cost (8.5% over 5 years, -17% drawdown, 35% win rate), we pivoted to a deterministic rules-engine on Interactive Brokers. The 5-year backtest data is preserved in `docs/research/v1.14-backtest-baseline/` for reference.

## Project Structure

```
.
|-- daily_check.py             # Daily regime check + IBKR flip (cron entry)
|-- main.py                    # Operator CLI: panic, summary, backtest
|-- config/
|   |-- settings.py            # All env-driven parameters with validation
|-- storage/
|   |-- schema.sql             # SQLite schema (regime_state, trades, audit_log)
|   |-- init_db.py             # Idempotent DB setup
|-- strategy/
|   |-- regime.py              # compute_target_state — pure function
|-- tools/
|   |-- ibkr_broker.py         # ib_insync wrappers (connect, get_position, place, liquidate)
|   |-- database.py            # All SQLite reads/writes
|   |-- notifications.py       # n8n webhook publisher (Discord)
|-- monitor/
|   |-- kill_switch.py         # Hourly drawdown sweep (cron entry)
|-- backtest/
|   |-- regime.py              # Regime-filter backtester (`main.py backtest`)
|-- scripts/
|   |-- cron_setup.sh          # Idempotent crontab installer
|-- tests/                     # pytest suite — run with `venv/bin/python -m pytest`
|-- docs/
|   |-- CURRENT_CONFIG.md      # Production env values + operational notes
|   |-- operations/            # Operator runbooks (IBKR setup, etc.)
```
