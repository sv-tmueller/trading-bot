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

- EMA 20 trend confirmation — `STRICT_CROSSOVER=true` requires the crossover event today; `false` accepts any day where EMA20 > EMA50 (trend-following)
- RSI(14) between `RSI_LOWER` and `RSI_UPPER` (default 40–60; widen to 35–70 for more signal)
- Volume > `VOLUME_MULTIPLIER` × 20-day average (default 1.5×; conviction filter)

All three thresholds are env-driven — see Configure below. The current tuned production values live in [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md).

### Risk Rules

| Parameter | Env var | Default | Safe bounds |
|---|---|---|---|
| Risk per trade | `RISK_PER_TRADE` | 1% | [0.1%, 5%] |
| Max open positions | `MAX_POSITIONS` | 5 | [1, 20] |
| Max portfolio exposure | `MAX_PORTFOLIO_EXPOSURE` | 20% | [5%, 50%] |
| Max hold days | `MAX_HOLD_DAYS` | 5 | [1, 30] |
| Min reward:risk ratio | `RR_RATIO_MIN` | 2.0 | [1.0, 5.0] |
| Stop distance (× ATR) | `ATR_STOP_MULTIPLIER` | 1.5 | [0.5, 5.0] |
| Daily drawdown limit | `DAILY_DRAWDOWN_LIMIT` | 3% | [0.5%, 20%] |
| Trailing stop (opt-in) | `TRAILING_STOP_ENABLED` | `false` | `true` ratchets DB stop_loss up as price makes new highs (live + backtest); default OFF |
| Trailing distance (× ATR) | `TRAILING_STOP_ATR_MULT` | 1.5 | [0.5, 5.0] |
| Trading kill switch | `TRADING_PAUSED` | `false` | `true` halts new entries; monitor still runs |

## Setup

### Prerequisites

- Python 3.9+ and git
- [Alpaca account](https://alpaca.markets) (free paper trading)
- [Anthropic API key](https://console.anthropic.com)

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
source venv/bin/activate        # macOS / Linux — see Windows note below
pip install -r requirements.txt
```

> **Windows users:** replace `source venv/bin/activate` with `venv\Scripts\activate` in PowerShell.
>
> **Every time you open a new terminal** to run the bot, re-run the activate command first — otherwise `python3 main.py ...` will fail with `ModuleNotFoundError`. Your prompt shows `(venv)` at the start when it's active.

### Configure

Create a `.env` file in the project root with your credentials and any overrides.

**On macOS / Linux** — use `nano` (a simple terminal editor):

```bash
nano .env
```

Paste in the block below, then save with `Ctrl+O` (Enter to confirm) and exit with `Ctrl+X`.

**On Windows** — open the `trading-bot` folder in Notepad or VS Code, create a new file called `.env`, paste the block below, and save.

```env
TRADING_MODE=paper
TRADING_PAUSED=false        # set to true to halt new entries; monitor keeps running
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
STRICT_CROSSOVER=true       # false = trend-following (EMA20 > EMA50 any day)
RSI_LOWER=40
RSI_UPPER=60
VOLUME_MULTIPLIER=1.5
ATR_STOP_MULTIPLIER=1.5
```

> These are the original baseline values. The production bot runs a backtest-tuned config — see [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md) for the current live values and their justification.

> **Note:** Free Alpaca paper trading accounts use the IEX data feed (`DATA_FEED=iex`). Paid live accounts use SIP (`DATA_FEED=sip`), which covers 100% of market volume vs ~60% for IEX.

### Initialise the database

```bash
python3 -c "from storage.init_db import init_db; init_db()"
```

## Running

### Morning scan (once per day)

```bash
python3 main.py scan

# Dry run — full agent pipeline, no orders placed or recorded
python3 main.py scan --dry-run
```

### Hourly position monitor

```bash
python3 main.py monitor
```

### Trailing performance summary

```bash
python3 main.py summary
```

Prints (and posts to Discord) the win rate, total PnL, and average R-multiple across trades closed in the last 30 days.

### Backtest (historical simulation)

```bash
# Default: 3 years, strategy parameters from settings.py
python3 main.py backtest

# Custom parameters
python3 main.py backtest --years 3 --rsi-lower 35 --rsi-upper 70
python3 main.py backtest --ema-fast 10 --ema-slow 30 --atr-multiplier 2.0 --rr-ratio 2.5
```

Runs the EMA crossover strategy against each watchlist ticker using `yfinance` data and prints a per-ticker results table to the terminal. Also sends a summary to Discord.

### Operational kill switch

Set `TRADING_PAUSED=true` in `.env` to halt new entries: the next `main.py scan` exits immediately (one Discord ping, no agents run, no orders placed). The position monitor is unaffected, so existing positions still get stop-loss, take-profit, and max-hold handling. Use this to wind down safely while a bug is investigated, instead of editing the root crontab under pressure.

## VPS Deployment

### 1. SSH in and install dependencies

```bash
ssh user@your-vps-ip
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git gh
```

`gh` (GitHub CLI) is optional but recommended — it lets you open/merge PRs directly from the VPS. After install, run `gh auth login` once and pick "Login with a web browser".

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

> **For production parity** — this minimal `.env` uses baseline strategy defaults. To match the current live bot (which runs backtest-tuned parameters), also copy the strategy block from [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md) into your `.env`. Backtesting showed the baseline produces ~5 trades over 3 years; the tuned config produces ~470 with +8.7% aggregate return.

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
25 13 * * 1-5 /opt/trading-bot/scripts/run_scan.sh
0 14-19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
55 19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

| Schedule | UTC | ET | German (CEST) | Purpose |
|---|---|---|---|---|
| Scan | 13:25 | 09:25 | 15:25 | Pre-market agent pipeline (5 min before open) |
| Monitor | :00 14–19 | 10:00–15:00 | 16:00–21:00 | Hourly position check |
| Pre-close | 19:55 | 15:55 | 21:55 | Final check 5 min before NYSE close |

> **Why pre-market, not after the open?** Signals are computed on **daily** bars
> (`EMA20/EMA50`, `RSI(14)`, `volume vs 20-day average`). If the scan runs after
> 13:30 UTC, today's daily bar is still being formed — `volume_ratio` collapses
> toward zero (a few minutes of trading vs a 20-day full-day average) and every
> ticker fails the volume gate. Running before the open means the strategy uses
> yesterday's fully-closed bar and Team Leader places market orders that fill at
> today's open.

Save and exit: `Ctrl+O` → Enter → `Ctrl+X`. You should see `crontab: installing new crontab` confirming it worked.

### Updating the bot

When you push code changes to GitHub, on the VPS run:

```bash
cd /opt/trading-bot && git pull
```

No restart needed — cron picks up the latest code on each run.

### Running Claude Code on the VPS

> **Run as a non-root user.** Claude Code refuses to start under `root` when the project has `bypassPermissions` enabled (it does, in `.claude/settings.json`). Create a dedicated user the first time:
> ```bash
> # As root, once:
> adduser --disabled-password --gecos "" trader
> chown -R trader:trader /opt/trading-bot
>
> # Switch to that user for all bot work
> su - trader
> ```
> Also move cron to this user: `crontab -u trader -e`.

To inspect scan history, DB state, or logs interactively on the VPS, install Claude Code (the `npm install` below needs root, the rest runs as `trader`):

```bash
# 1. Install Node 20+ (required by claude-code) — run as root
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 2. Install the Claude Code CLI globally — run as root
sudo npm install -g @anthropic-ai/claude-code

# 3. Launch from the repo — run as trader
cd /opt/trading-bot
claude
```

**Auth on a headless VPS** — two options:

- **Easiest: reuse your laptop login.** SSH in with a port forward so the OAuth callback lands on the VPS but opens in your laptop browser:
  ```bash
  ssh -L 54545:localhost:54545 user@your-vps
  ```
  Then run `claude` on the VPS and follow the URL it prints.

- **Fallback: API key.** Console-billed only (not Pro/Max). Add to `~/.bashrc`:
  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...
  ```

### Reconnecting after a dropped SSH session

If your internet blinks or you close the terminal by accident, here's the exact sequence to get back to a working Claude Code session — copy-paste line by line.

**1. SSH back into the VPS**

Open a new terminal and run your usual ssh command. If you use the port-forwarded form from the Auth section above, re-use it:

```bash
ssh -L 54545:localhost:54545 user@your-vps
```

**2. Switch to the `trader` user**

You'll land as your own user (the one your SSH key is for). Claude Code needs to run as `trader` — the user that owns `/opt/trading-bot`. Two ways to switch:

```bash
# Recommended — uses your sudo password, not trader's:
sudo -u trader -i

# Alternative, requires trader's password:
su - trader
```

If `sudo -u trader -i` complains about missing permissions, see the "Run as a non-root user" box above for the one-time setup.

**3. Go into the bot folder**

```bash
cd /opt/trading-bot
```

**4. Resume your previous Claude Code session**

```bash
claude --continue
```

`--continue` picks the most recent session in the current directory and replays the full conversation history so you land back exactly where you left off. If you want to see a list of recent sessions and pick one, use `claude --resume` instead (opens a session picker).

If there was no previous session — or Claude Code doesn't find one — just run `claude` to start a fresh session. No harm done; previous sessions aren't deleted, they're just not selected.

**5. If your screen was showing something running**

If a long-running command (backtest, scan, deploy) was in-flight when you disconnected, it may have been killed with the SSH session. Check with:

```bash
ps -u trader | grep -E "python|claude"
```

If nothing is running and you need that command again, just re-invoke it. For commands you want to survive disconnects, prefix with `nohup ... &` or use `tmux` / `screen`.

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
| Performance summary (`main.py summary`) | Trailing-30d win rate, PnL, avg R-multiple |
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

The list of tickers the bot scans each morning lives in [`config/watchlist.py`](config/watchlist.py) — that file is the source of truth.

For the current production watchlist and the reasoning behind which tickers are included or excluded, see [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md).

**When editing:** stick to S&P 500 constituents with high liquidity (≥ 5M average daily volume). The backtest (`python3 main.py backtest`) is a good way to sanity-check a new ticker before committing it.

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

### v1.11.0 (2026-04-29)

**Bug fixes (post-v1.10 audit):**
- Bracket pre-flight validation rejects malformed legs (stop ≥ entry, target ≤ entry, target ≤ stop, non-positive prices) before submission — closes the fallback path where a missing `pending_atrs` could ship inverted brackets to Alpaca (#79, #85)
- `tools/broker.place_market_order` now wraps `submit_order` in try/except and re-raises a typed `BrokerSubmitError`; `team_leader.place_order` catches it as a soft rejection so Alpaca rejections (insufficient buying power, wash-trade, halted symbol) no longer crash the morning scan mid-loop (#81, #86)
- Reconciled phantom closes infer `exit_reason` from the price's proximity to the stored stop/target levels (0.5% slippage tolerance) instead of hardcoding `stop_loss` for every broker-side close — restores accurate win/loss attribution (#80, #87)
- `notify_monitor` now counts `reconciled` actions as `closed` instead of `held`, fixing a cosmetic Discord misreport for broker-side bracket fills (#78, #88)

**Refactor:**
- `DAILY_DRAWDOWN_LIMIT` promoted from a hardcoded module constant to env-driven setting with bounds `[0.005, 0.20]`; default unchanged at `0.03` (#69, #89)

**Testing:**
- Direct test coverage added for `storage/init_db.py` (fresh-install entrypoint, idempotency, schema column verification) — previously bypassed by the in-memory `db_conn` fixture (#84, #90)

**Docs:**
- TEAM.md QA playbook extended with v1.10 smoke checks (kill switch, dry-run pipeline, doc-staleness scan); `docs/CURRENT_CONFIG.md` refreshed to reflect v1.10/v1.11 invariants (#82, #83)

**Tests:** 174 → 194 passing (+20).

---

### v1.10.0 (2026-04-29)

**Risk hardening:**
- Deterministic `MAX_PORTFOLIO_EXPOSURE` gate added to `team_leader.place_order` — computes post-trade exposure from broker truth (`get_alpaca_positions`) and rejects any buy that would breach the cap; LLM cannot bypass (#72, #75)
- Bracket orders replace bare market entries — entry + take_profit + stop_loss legs submitted in one call, executed server-side on Alpaca's matching engine; stop/target recomputed locally from a fresh quote at submission instead of the LLM's stale prior-close estimate (#73, #77)

**Reliability:**
- Server-side stops/targets close the 2-hour reliability gap observed on 2026-04-28 — exits fire regardless of monitor process or data-API reachability; soft-stop check in `position_monitor` retained as defense-in-depth, with broker-truth reconciliation to detect bracket-child closures (#73, #77)

**Operational:**
- `TRADING_PAUSED` kill switch — `TRADING_PAUSED=true` in `.env` halts new entries on the next scan (one Discord ping, no agents run); position monitor is unaffected so existing positions still get exit handling (#74, #76)

**Tests:** 147 → 174 passing (+27).

---

### v1.9.0 (2026-04-24)

**Strategy tuning (E3 — 10yr parameter sweep):**
- `RSI_LOWER=30`, `RSI_UPPER=75`, `VOLUME_MULTIPLIER=1.0`, `MAX_HOLD_DAYS=20`, `ATR_STOP_MULTIPLIER=1.5`, `RR_RATIO_MIN=3.0` on the live bot (`STRICT_CROSSOVER=false` unchanged). 10yr pooled backtest: **+42.1% return**, profit factor **1.42**, winner:loser ratio **2.08**, 1613 trades at 40.3% win rate, max per-ticker drawdown -21.1%
- Cross-validated on shorter windows: 3yr +7.8% / PF 1.32, 5yr +14.9% / PF 1.35 — metrics stable across regimes
- Selected from a 20-config sweep; chose E3 over the marginally higher F3 (RSI 25-80) because F3's deeper RSI bounds aren't robust to unmodeled slippage and gap risk
- Watchlist unchanged from v1.8.0 (12 tickers)

**Documentation:**
- [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md) updated with the E3 env block, refreshed "What each change does" table, new backtest results snapshot, and a change-log entry (#56)

---

### v1.8.0 (2026-04-24)

**Strategy tuning (3yr backtest driven):**
- `STRICT_CROSSOVER=false`, `MAX_HOLD_DAYS=10`, `RSI_LOWER=35`, `RSI_UPPER=70`, `VOLUME_MULTIPLIER=1.2`, `ATR_STOP_MULTIPLIER=1.3` on the live bot. 3yr aggregate backtest jumps from +0.2% / 5 trades (baseline) to +8.7% / 471 trades / 45.9% win rate
- `RSI_LOWER`, `RSI_UPPER`, `VOLUME_MULTIPLIER`, `ATR_STOP_MULTIPLIER` promoted from hardcoded constants in `config/settings.py` to env-driven with safety bounds
- Watchlist pruned from 16 to 12 tickers — removed `UNH`, `V`, `MSFT`, `MA` (all 4-5/5 negative across tested configs, avg -3.8% to -11.0%)

**Documentation:**
- New [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md) — pinned snapshot of the current live config, watchlist reasoning, and backtest results. Designed to accumulate tune entries rather than mutating the README each time.
- README § Prerequisites now includes per-OS install hints (macOS / Ubuntu / Windows)
- README § Setup clarifies venv activation (reactivate in each new terminal; Windows uses `venv\Scripts\activate`)
- README § Configure shows the `nano .env` command with Ctrl+O/Ctrl+X tip (previously just said "create a file")
- README § VPS Deployment step 1 installs `gh` so PR workflow is supported from the box

---

### v1.7.0 (2026-04-24)

**Strategy:**
- `STRICT_CROSSOVER` env var (default `true`) — when `false`, EMA entry condition switches from "EMA20 crossed above EMA50 today" to "EMA20 > EMA50 on any day" (trend-following mode). Entry signal is now enforced deterministically before the LLM sees results — LLM cannot override it (#40)
- Watchlist expanded from 8 to 16 tickers — adds TSLA, AAPL, JPM, V, MA, UNH, LLY, AVGO (all > 5M avg daily volume). Backtest: 5 trades / 60% win rate vs 4 trades / 50% baseline (#41)

---

### v1.6.0 (2026-04-24)

**Reliability:**
- Position reconciliation runs at scan startup — detects ghost positions (open on Alpaca but missing from DB) and phantom DB entries (DB thinks open but Alpaca closed). Alerts via Discord, never blocks the scan (#30)

**Developer experience:**
- `python3 main.py scan --dry-run` runs the full four-agent pipeline without placing any orders or writing to the DB — prints `[DRY RUN] would buy/sell N shares of TICKER` instead (#28)

---

### v1.5.1 (2026-04-24)

**Testing:**
- `notify_backtest` and all 5 other notification functions now covered by tests — 108 tests total (#23)
- Backtest single-year warning and default `years=3` asserted in tests (#24, #26)
- `MarketIntelligenceAgent` `get_portfolio_state` tool closure covered by a two-turn tool-use test, confirming prices are only fetched for open-position tickers (#25)

---

### v1.5.0 (2026-04-24)

**Bug fixes:**
- Morning scan is now idempotent — a duplicate cron run on the same day exits immediately without placing orders (#7)
- Position monitor pre-close check moved to 19:55 UTC (5 min before NYSE close); hourly runs stop at 19:00 UTC to avoid submitting orders at the close bell (#13)

**Performance:**
- `MarketIntelligenceAgent` now fetches prices only for tickers with open positions — eliminates up to 8 unnecessary Alpaca API calls on days with no open trades (#16)

**Strategy & backtest:**
- Backtest defaults to 3 years instead of 1 to avoid single-period cherry-picking; prints a warning when `--years 1` is used (#19)
- EMA crossover strict single-day behaviour documented as intentional (#11)
- RSI 40–60 conservative bounds documented with backtest comparison commands (#12)

**Documentation:**
- Added "Before going live" section covering slippage, spread costs, and liquidity filters (#18)
- Architectural invariant documented in `CLAUDE.md`: the LLM must never control stop-loss, take-profit, or risk parameters (#20)
- Unused DB tables (`signals`, `daily_stats`, `weekly_stats`, `suggestions`) documented as planned future work (#9)

**Testing:**
- `BaseAgent` tool-use loop and multi-turn token accumulation now covered by tests (#15)

---

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
