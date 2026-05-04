# Trading Bot

A self-reflecting, multi-agent LLM-powered swing trading bot for US equities. Four Claude AI agents collaborate each morning to scan the market, propose trades, review risk, and execute orders — all on Alpaca paper trading by default.

## Quick Start — daily session on the VPS

The bot runs unattended via cron. You only need to log in when you want to inspect logs, debug, vibe-code, or push changes. Every session starts the same way:

```bash
# 1. SSH in (the -L port-forward lets the OAuth callback land on the VPS
#    but open in your laptop browser — needed for first-time Claude Code auth).
#    Most cloud VPS providers (Hetzner, IONOS, DigitalOcean) give you root by
#    default; a non-root sudo user works equally well — step 2 works from either.
ssh -L 54545:localhost:54545 root@your-vps-ip     # or: your-sudo-user@your-vps-ip

# 2. Become the `trader` user
#    /opt/trading-bot is owned by trader, and Claude Code refuses to start
#    as root because bypassPermissions is on in .claude/settings.json.
#    `sudo -u trader -i` works without a password whether you're root or a sudo user.
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

If a long-running command (backtest, scan) was in flight when SSH dropped, it was killed with the session. Check with `ps -u trader | grep python` and re-invoke if needed. For commands that need to survive disconnects, prefix with `nohup ... &` or run inside `tmux`.

> **First time on this VPS?** Jump to [Setting up a new VPS](#setting-up-a-new-vps) for the one-time install. Once that's done, daily access is the four steps above.

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
| Earnings blackout window | `EARNINGS_BLACKOUT_DAYS` | 0 (off) | [0, 14] — skip entries within N days of next/last earnings |
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

`--dry-run` runs the deterministic safety stack identically to a live scan (exposure gate against broker truth, bracket-leg validation, fail-closed on broker outage) — only the broker SUBMIT and DB INSERT are skipped. An over-cap or malformed candidate is rejected in dry-run too, so the smoke test reflects what the live path would actually do. The Discord scan-complete alert is prefixed `🧪 **Morning Scan (DRY RUN)**` and the Team Leader narrates outcomes in conditional tense ("would have bought") whenever it sees `status: "dry_run_simulated"` in a tool result.

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

For faster incident response (cancelling open orders, liquidating positions, atomically writing the pause flag without `nano`), see the [Panic CLI](#panic-cli-incident-response) below.

### Panic CLI (incident response)

For incidents where editing `.env` by hand is too slow, `python main.py panic` is a deterministic kill button — no LLM in the path, just direct broker calls.

```bash
python3 main.py panic --cancel-orders                       # cancel all open orders (parent + bracket children)
python3 main.py panic --liquidate                           # DRY RUN — prints what would be closed, exits non-zero
python3 main.py panic --liquidate --confirm                 # actually market-close every position
python3 main.py panic --pause                               # write TRADING_PAUSED=true to .env (atomic)
python3 main.py panic --cancel-orders --liquidate --pause --confirm   # full stop
```

Notes:
- `--liquidate` mandatorily requires `--confirm`. Without it, it's a dry preview that exits non-zero.
- Order of operations: `--cancel-orders` runs **before** `--liquidate` so unfilled bracket entries don't race the liquidation. `liquidate_all_positions` already passes `cancel_orders=True` to Alpaca, which sweeps the protective bracket-child legs (take-profit + stop-loss) before each market-close.
- Idempotent — safe to re-run. Cancelling already-cancelled orders, liquidating zero positions, and pausing already-paused are all no-ops.
- Every invocation writes an `agent_logs` row (`agent_name="panic"`) **before** any broker call so a partial run is recoverable from the DB; the row is updated in a `finally` block with the per-action result (`cancel-orders=ok(N)`, `liquidate=fail(BrokerError)`, etc.).
- `--pause` writes to `/opt/trading-bot/.env` regardless of the caller's cwd — the path is anchored to the repo root via `Path(__file__).resolve().parent`, so invocations from cron, monitoring scripts, or a stray shell all touch the same file.
- Every action posts a Discord 🛑 alert via the existing webhook; on exception, a full `traceback.format_exc()` is included so the Discord cutoff (head/tail slicing in `notify_error`) preserves the actual stack.

## Setting up a new VPS

A fresh Ubuntu 22.04+ box, end-to-end, takes about 15 minutes. Steps run as either root (the default on Hetzner / IONOS / DigitalOcean / most cloud VPS providers) or a non-root sudo user — drop the `sudo` prefix from the commands below if you're logged in as root. Steps that must run as the dedicated bot user are explicitly marked **(as trader)**.

### 1. SSH in and install OS packages

```bash
ssh root@your-vps-ip                              # or: your-sudo-user@your-vps-ip
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git gh curl
```

`gh` (GitHub CLI) is optional but recommended — it lets you open/merge PRs from the VPS. After install: `gh auth login` once, pick "Login with a web browser".

### 2. Create the `trader` user and own the project directory

The bot runs as a dedicated `trader` user so cron, the bot, and Claude Code all share the same UID. Claude Code refuses to start as root when `bypassPermissions` is set in `.claude/settings.json` (it is, in this repo).

```bash
sudo adduser --disabled-password --gecos "" trader
sudo mkdir -p /opt/trading-bot
sudo chown trader:trader /opt/trading-bot
```

### 3. Clone the repo **(as trader)**

```bash
sudo -u trader -i
git clone https://github.com/sv-tmueller/trading-bot /opt/trading-bot
cd /opt/trading-bot
```

> **Private repo?** GitHub no longer accepts passwords for git. Create a Personal Access Token at **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**, give it the `repo` scope, then embed it in the remote URL once:
> ```bash
> git remote set-url origin https://sv-tmueller:<YOUR_TOKEN>@github.com/sv-tmueller/trading-bot.git
> ```

### 4. Set up the Python environment **(as trader)**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Create the `.env` file **(as trader)**

```bash
nano /opt/trading-bot/.env
```

Paste in:

```env
TRADING_MODE=paper
TRADING_PAUSED=false
DATA_FEED=iex

ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret

ANTHROPIC_API_KEY=your_anthropic_key
CLAUDE_MODEL=claude-sonnet-4-6
```

Save with `Ctrl+O` (Enter), exit with `Ctrl+X`.

> **For production parity** — this minimal `.env` runs the baseline strategy. To match the current live bot's backtest-tuned parameters, also copy the strategy block from [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md). Baseline produces ~5 trades over 3 years; the tuned config produces ~470 with +8.7% aggregate return.

### 6. Initialise the database **(as trader)**

```bash
python3 -c "from storage.init_db import init_db; init_db()"
```

### 7. Create the log directory

Drop back out of the trader shell — `/var/log` needs root to create:

```bash
exit                                    # leaves the trader shell
sudo mkdir -p /var/log/trading-bot
sudo chown trader /var/log/trading-bot
```

### 8. Smoke-test the pipeline **(as trader)**

```bash
sudo -u trader -i
cd /opt/trading-bot
source venv/bin/activate
python3 main.py scan --dry-run
```

`--dry-run` runs the full four-agent pipeline without placing orders or writing to the DB. If it completes without errors and prints `[DRY RUN] would buy/sell ...` lines (or "no candidates"), you're good.

### 9. Install Claude Code **(as trader)**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

The binary lands at `~/.local/bin/claude`. The installer adds `~/.local/bin` to your PATH; if `claude --version` doesn't work in a new shell, add this to `~/.bashrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

> **Alternative — npm install (needs root):**
> ```bash
> curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
> sudo apt install -y nodejs
> sudo npm install -g @anthropic-ai/claude-code
> ```

**First-run auth on a headless VPS** — two options:

- **Easiest: reuse your laptop's Claude account.** Re-SSH with a port-forward so the OAuth callback opens in your laptop browser:
  ```bash
  ssh -L 54545:localhost:54545 root@your-vps-ip
  ```
  Then run `claude` on the VPS and click the URL it prints. The browser opens on your laptop, completes the OAuth dance, and Claude Code on the VPS picks up the credentials.

- **Fallback: API key.** Console-billed only (not Pro/Max plans). Add to `~/.bashrc`:
  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...
  ```

### 10. Set up cron

The bot scripts run via root's crontab — they use absolute paths (`/opt/trading-bot/venv/bin/python ...`) so the cron user doesn't matter, and root's crontab survives any user-level changes.

```bash
exit                  # back to your sudo user
sudo crontab -e
```

Pick **1** (nano) if prompted, then add (all times UTC):

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

Save: `Ctrl+O` → Enter → `Ctrl+X`. You should see `crontab: installing new crontab`.

> **Why pre-market, not after the open?** Signals are computed on **daily** bars (`EMA20/EMA50`, `RSI(14)`, `volume vs 20-day average`). Running after 13:30 UTC means today's daily bar is still forming — `volume_ratio` collapses toward zero (a few minutes of trading vs a 20-day full-day average) and every ticker fails the volume gate. Running before the open uses yesterday's fully-closed bar and orders fill at today's open.

### 11. Discord notifications (optional)

See [Discord Notifications (via n8n)](#discord-notifications-via-n8n) below.

### Updating the bot after deploy

When you push code changes to GitHub, on the VPS:

```bash
sudo -u trader -i
cd /opt/trading-bot && git pull
```

No restart — cron picks up the latest code on the next run.

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
| *(errors)* | Stack trace excerpt — short errors verbatim, long errors keep head + tail (240/.../240) so the exception line is never truncated |

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

### v1.13.0 (2026-05-04)

**Incident-response CLI + dry-run smoke test that actually tests the safety stack.**

Operational:
- `python main.py panic` — deterministic incident-response CLI. No LLM in the path. `--cancel-orders` cancels every open Alpaca order (parent + bracket children); `--liquidate --confirm` market-closes all positions (`--confirm` mandatory; without it, dry preview that exits non-zero); `--pause` atomically writes `TRADING_PAUSED=true` to `/opt/trading-bot/.env`. Flags compose; cancel runs before liquidate when both are passed. Single `agent_logs` row per invocation written before broker call and updated in `finally` with per-action result. Discord 🛑 alert on every action; exceptions include `traceback.format_exc()` for post-mortem. `--pause` path anchors `.env` to the repo root via `Path(__file__).resolve().parent`, so cron / arbitrary cwd invocations all touch the same file (#103, #128)

Quality (dry-run is now a real smoke test):
- `team_leader.place_order(dry_run=True)` now runs the full deterministic safety stack (`check_exposure_for_new_order` against broker truth, `validate_bracket_params`) before returning. Only `place_market_order` (broker SUBMIT) and `insert_trade` (DB INSERT) are skipped. Over-cap or malformed candidates are rejected in dry-run too — previously the dry-run path short-circuited the gate, so `--dry-run` could green-light orders the live path would reject. Dry-run payload is `{"order_id": "DRY_RUN", "fill_price": None, "status": "dry_run_simulated", "note": ...}` and the system prompt instructs the LLM to narrate in conditional tense ("would have bought") whenever it sees that status (#123, #127)
- `notify_scan_complete` accepts `dry_run: bool`; when True the Discord header swaps to `🧪 **Morning Scan (DRY RUN) — {date}**` instead of `🤖 **Morning Scan**`. Live-scan output is byte-identical (#122, #126)

Test fixture:
- `tests/test_agents/test_strategy.py` earnings-blackout fixture switched from a hardcoded `date(2026, 5, 1)` to `date.today() + timedelta(days=1)` so it always falls inside any reasonable blackout window. Test-only; production earnings logic unchanged. Restores the full-suite green baseline (#120, #125)

**Tests:** 231 → 260 passing (+29).

---

### v1.12.1 (2026-05-04)

**Reliability patch — three exception-isolation fixes from the post-v1.12 audit:**
- `BaseAgent._handle_tool_calls` now wraps tool invocation in try/except. A failing tool returns as a `tool_result` block with `is_error: True` (matching Anthropic's tool-use protocol) so the LLM can retry, skip, or explain in its final JSON instead of aborting the morning scan. Unknown-tool branch uses the same shape. Defensive validation added to `tools/risk.calculate_position` (rejects non-positive `atr`/`entry_price`/`portfolio_value`/`risk_pct` with `ValueError` rather than letting `ZeroDivisionError` surface) (#113, #119)
- `monitor/position_monitor.run_monitor` now isolates each per-trade iteration in try/except. A transient broker/network blip on one ticker no longer aborts the cycle: the failure is reported via `notify_error` with the failing ticker, the trade is recorded as a `hold/skipped_error` `MonitorAction` so accounting stays honest, and the loop continues. The next cycle re-evaluates from scratch. The reconcile step was already wrapped — unchanged (#115, #118)
- `tools/notifications.notify_error` now preserves both ends of long tracebacks: short errors (≤500 chars) are unchanged; longer errors are sliced as `head[:240] + "\n...\n" + tail[-240:]` so the exception type and message — the line that actually identifies the failure — survive the Discord cutoff (#114, #117)

**Tests:** 218 → 231 passing (+13 across the three PRs).

---

### v1.12.0 (2026-04-29)

**New strategy/risk knobs (opt-in, default OFF — no behaviour change for existing deployments):**
- Trailing stop-loss — `TRAILING_STOP_ENABLED=true` activates DB stop_loss ratchet-up logic in both the live position monitor and the portfolio backtest. Trail distance configurable via `TRAILING_STOP_ATR_MULT` (default 1.5×, range [0.5, 5.0]). Stops only ratchet up, never down. Idempotent schema migration adds `trailing_high` column to `trades` (#67, #91)
- Earnings blackout window — `EARNINGS_BLACKOUT_DAYS=N` (range [0, 14], default 0 = disabled) skips entries within N days before next or after last earnings, in both strategy agent and portfolio backtest. New `tools/earnings.py` wraps yfinance with `lru_cache` + graceful failure (returns `None` on any error). Strategy agent receives `earnings_blackout_reason` in signals so the LLM understands why an entry is skipped. Backtest fails open when earnings data is unavailable (#68, #92)

**Backlog research (no code change):**
- Cap-value sweep at 0.20/0.30/0.40/0.50 (#61) — 0.30 is the risk-adjusted winner over 5y (+31.4% vs +8.5% at 0.20, similar drawdown). Recommendation deferred until v1.10/v1.11 live data exists; issue moved to `status: blocked`
- Sector concentration analysis (#63) — found real concentration: Semiconductors 53.2% of trades, Tech mega-cap 34.8% of rejections at the 20% cap. Issue moved to `status: ready` for follow-up `MAX_PER_SECTOR` work
- Portfolio-mode parameter sweep (#65, 27 combos) — current `ATR_STOP_MULTIPLIER=1.5` is dominated by both `1.0` and `2.0` clusters on 3y data. Issue moved to `status: ready`; no setting change yet (5y + chop window re-run pending)
- Sim/live ranking proxy divergence (#62) — closed as expected design behaviour
- Validate live PnL after 30-60d (#64) — closed as deferred until enough live data exists

**Tests:** 194 → 218 passing (+24 from #67 and #68).

---

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
