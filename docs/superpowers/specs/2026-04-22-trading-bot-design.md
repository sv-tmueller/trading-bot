# Trading Bot — Design Spec
**Date:** 2026-04-22
**Status:** Approved

---

## Overview

A self-reflecting Python swing trading bot for US equities, paper trading on Alpaca with a clear path to live trading. The bot trades autonomously within a defined ruleset, analyzes its own performance daily and weekly, and proposes strategy parameter changes for human approval.

**Core philosophy:** Slightly above 50% win rate with a minimum 1:2 reward/risk ratio. Consistent edge beats high win rate.

---

## Key Decisions

| Dimension | Decision |
|---|---|
| Asset class | US Stocks (large-cap / S&P 500) |
| Style | Swing trading, 1–5 day holds |
| Language | Python |
| Broker | Alpaca (paper initially, live via env toggle) |
| Universe | Curated watchlist (~20–50 tickers, e.g. AMD, NOW, SHEL) |
| Strategy | Multi-signal hybrid (EMA + RSI + Volume), tunable over time |
| Risk | 1% portfolio per trade, ATR-based stops, 1:2+ R:R minimum |
| Autonomy | Trades placed autonomously; strategy param changes require approval |

---

## Architecture

Modular monolith — single Python application with clearly separated modules. Deployed on a VPS as a systemd service, scheduled via cron.

```
trading-bot/
├── main.py                  # Entry point, orchestrates the daily run
├── config/
│   ├── settings.py          # All tunable parameters
│   └── watchlist.py         # Curated ticker list
├── data/
│   └── fetcher.py           # OHLCV data from Alpaca
├── strategy/
│   ├── signals.py           # Indicator computation (EMA, RSI, Volume)
│   └── screener.py          # Scores and ranks trade candidates
├── risk/
│   └── manager.py           # Position sizing, stop-loss, take-profit
├── broker/
│   └── alpaca.py            # Alpaca API wrapper (paper/live toggle)
├── portfolio/
│   └── tracker.py           # Open positions, P&L, trade log
├── reflection/
│   ├── analyzer.py          # Post-trade performance analysis
│   ├── reporter.py          # Daily/weekly report generation
│   └── suggestions.py      # Parameter change proposals
├── storage/
│   └── trades.db            # SQLite — all trade and performance data
└── reports/                 # Generated Markdown reports (gitignored)
```

---

## Strategy & Signals

### Entry — all three must agree

| Indicator | Role | Default |
|---|---|---|
| EMA crossover (20/50) | Trend direction | EMA20 crosses above EMA50 |
| RSI (14) | Momentum filter | RSI between 40–60 at entry |
| Volume | Conviction filter | Volume > 1.5x 20-day average |

### Exit conditions (whichever triggers first)
- Stop-loss hit
- Take-profit hit (minimum 1:2 R:R)
- EMA trend reversal
- Max hold duration reached (5 days)

### Adaptability
All indicator parameters live in `config/settings.py` and in the `parameters` DB table (versioned). The reflection engine proposes changes to these values — they never change without explicit approval.

---

## Risk Management

**Position sizing:**
```
Max risk per trade = 1% of portfolio value
Stop distance = ATR-based (adapts to ticker volatility)
Position size = Max risk / Stop distance (in dollars/share)
```

**Per-trade structure:**
- ATR-based stop-loss set at entry
- Take-profit at minimum 1:2 R:R from entry
- Trailing stop: once trade is up 1R, stop moves to breakeven

**Portfolio-level guardrails:**
- Max 5 open positions simultaneously
- Max 20% of portfolio deployed at once
- Daily drawdown > 3% → pause new entries for remainder of day, log event

All thresholds are config-driven and subject to reflection engine suggestions.

---

## Autonomy Model

| Action | Autonomous |
|---|---|
| Place trades based on current signals | Yes |
| Execute stop-loss / take-profit | Yes |
| Exit on trend reversal or max hold | Yes |
| Pause trading on daily drawdown breach | Yes |
| Change strategy parameters | No — suggest + human approves |
| Change risk thresholds | No — suggest + human approves |
| Add/remove tickers from watchlist | No — human decision |

---

## Reflection Engine

### Daily analysis (runs ~4:30pm ET)
- Win/loss count and rate for the session
- Average R:R achieved vs. targeted
- Per-ticker performance breakdown
- Indicator signal quality (which signals led to wins vs. losses)
- Report written to `reports/daily/YYYY-MM-DD.md` and stored in DB

### Weekly analysis (runs Friday ~4:45pm ET)
- Rolling 4-week win rate and R:R trend
- Strategy parameter performance breakdown
- Best/worst performing tickers with reasoning
- Drawdown analysis
- Concrete parameter suggestions with evidence:

```
SUGGESTION #2026-04-25-01
Parameter:    rsi_upper_bound
Current:      60 → Proposed: 55
Reason:       14 trades entered with RSI 55-60 this week.
              Win rate: 35% vs 61% for RSI < 55 entries.
              Changing would have avoided 4 losing trades.
Status:       PENDING_APPROVAL
```

Human reviews suggestions in the DB or report file. Approval sets status to `approved` — applied on next run.

---

## Data Storage Schema

**`trades`**
```sql
id, ticker, entry_date, exit_date, entry_price, exit_price,
shares, stop_loss, take_profit, exit_reason,
pnl_dollars, pnl_pct, hold_days, r_multiple
```
`exit_reason`: `stop_loss` | `take_profit` | `trend_reversal` | `max_hold` | `manual`

**`signals`**
```sql
id, trade_id, ticker, date, ema_20, ema_50, rsi, volume_ratio,
signal_score, triggered_entry
```

**`daily_stats`**
```sql
date, trades_opened, trades_closed, win_count, loss_count,
win_rate, avg_r_multiple, portfolio_value, daily_pnl, drawdown
```

**`weekly_stats`**
```sql
week_start, week_end, total_trades, win_rate, avg_r_multiple,
best_ticker, worst_ticker, portfolio_value, weekly_pnl
```

**`suggestions`**
```sql
id, created_date, parameter, current_value, proposed_value,
evidence, status, applied_date
```

**`parameters`** (versioned — full history of every strategy config)
```sql
id, applied_date, rsi_lower, rsi_upper, ema_fast, ema_slow,
volume_multiplier, risk_pct, max_positions, r_ratio_min
```

---

## Scheduling (all times ET)

```
09:35          Morning scan — signals, entries
10:00–15:00    Hourly — position monitor (stops/targets)
16:00          Final position check before close
16:30          Daily reflection + report
Fri 16:45      Weekly reflection + suggestions
```

Market calendar awareness via `pandas_market_calendars` — no action on weekends or US holidays.

---

## Infrastructure

**VPS:**
- Python process managed by `systemd` (auto-restart on crash)
- Scheduled via `cron`

**Environment variables (`.env`, never committed):**
```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
TRADING_MODE=paper          # swap to 'live' when ready
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
```

**Paper → Live switch:** Change `TRADING_MODE=live` and swap API keys. Zero code changes.

**GitHub:**
- Private repo, code deployed to VPS via `git pull`
- `reports/`, `storage/trades.db`, `.env` are gitignored

---

## Key Libraries

| Library | Purpose |
|---|---|
| `alpaca-trade-api` | Broker integration |
| `pandas` | Data manipulation |
| `pandas_market_calendars` | US market calendar |
| `ta` (technical-analysis) | EMA, RSI, ATR computation |
| `sqlite3` | Built-in, no extra dependency |
| `schedule` or `cron` | Job scheduling |
| `python-dotenv` | Environment variable loading |
