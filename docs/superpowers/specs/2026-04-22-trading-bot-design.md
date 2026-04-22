# Trading Bot — Design Spec
**Date:** 2026-04-22
**Status:** Approved

---

## Overview

A self-reflecting, multi-agent LLM-powered swing trading bot for US equities, paper trading on Alpaca with a clear path to live trading. Four Claude-powered agents collaborate on every trade cycle: gathering market intelligence, developing strategy, reviewing risk, and making final decisions. The system trades autonomously within a defined ruleset and proposes strategy parameter changes for human approval.

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
| Decision layer | Four LLM agents (Claude API) collaborating per trade cycle |

---

## Multi-Agent Architecture

The decision-making layer consists of four Claude-powered agents, each with a defined role, system prompt, and tool access. They run sequentially per cycle, each passing structured output to the next.

### Agent 1 — Market Intelligence Agent
**Role:** Situational awareness. Runs first every cycle.
- Fetches latest OHLCV data for the full watchlist
- Checks all open positions: current price vs. stop-loss and take-profit levels
- Flags positions needing urgent attention (close to stop, extended hold duration)
- Summarises broader market context (trend, volatility)
- **Output:** Structured market briefing passed to Strategy Agent

**Tools available:** `fetch_market_data`, `get_open_positions`, `get_portfolio_stats`

---

### Agent 2 — Strategy Agent
**Role:** Signal generation and reflection. Receives market briefing.
- Computes technical signals (EMA crossover, RSI, Volume) for each watchlist ticker
- Scores and ranks trade candidates with reasoning
- Identifies why previous trades succeeded or failed
- After session: reflects on daily outcomes, proposes parameter changes
- **Output:** Ranked trade candidates with entry reasoning, passed to Risk Review Agent

**Tools available:** `compute_signals`, `get_trade_history`, `get_current_parameters`, `propose_parameter_change`

---

### Agent 3 — Risk Review Agent
**Role:** Gatekeeper. Receives trade candidates from Strategy Agent.
- Validates each candidate against risk rules (position sizing, max open positions, drawdown limits)
- Calculates exact position size, stop-loss price, take-profit price per trade
- Can reject candidates that violate thresholds — with written reasoning
- Checks portfolio-level exposure before approving
- **Output:** Approved trade list with full risk parameters, passed to Team Leader

**Tools available:** `calculate_position_size`, `check_portfolio_exposure`, `get_risk_parameters`

---

### Agent 4 — Team Leader Agent (Orchestrator)
**Role:** Final decision-maker and executor. Receives all agent reports.
- Weighs inputs from all three agents
- Makes final go/no-go decision on each trade with written rationale
- Places approved orders via Alpaca
- Handles position exits flagged by Market Intelligence Agent
- On weekly cycle: reviews Strategy Agent's parameter suggestions, flags for human approval
- Logs complete reasoning chain for every decision
- **Output:** Executed orders + decision log written to DB

**Tools available:** `place_order`, `close_position`, `write_decision_log`, `flag_suggestion_for_approval`

---

### Communication Flow

```
Market Intelligence Agent
        │ market briefing
        ▼
Strategy Agent
        │ trade candidates + reasoning
        ▼
Risk Review Agent
        │ approved candidates + risk params
        ▼
Team Leader Agent ──────────────► Alpaca (orders)
        │
        ▼
      SQLite DB (full audit trail of every agent's reasoning)
```

All agent outputs are persisted to the DB — every reasoning step is auditable.

---

### When LLM Agents Run

LLM agents engage on meaningful events only — not every minute. The hourly position monitor is lightweight rule-based Python (price vs. stop/target thresholds). Agents engage when:

| Trigger | Agents involved |
|---|---|
| Morning scan (09:35 ET) | All four |
| Position flagged by hourly monitor | Market Intelligence + Team Leader |
| End of day (16:30 ET) | Strategy Agent (reflection) + Team Leader (log) |
| End of week (Fri 16:45 ET) | Strategy Agent (full review + suggestions) |

---

## Project Structure

```
trading-bot/
├── main.py                      # Orchestrates the daily run
├── config/
│   ├── settings.py              # All tunable parameters
│   └── watchlist.py             # Curated ticker list
├── agents/
│   ├── market_intelligence.py   # Agent 1
│   ├── strategy.py              # Agent 2
│   ├── risk_review.py           # Agent 3
│   └── team_leader.py           # Agent 4 (orchestrator)
├── tools/                       # Tools available to agents
│   ├── market_data.py           # fetch_market_data, compute_signals
│   ├── portfolio.py             # get_open_positions, get_portfolio_stats
│   ├── risk.py                  # calculate_position_size, check_exposure
│   ├── broker.py                # place_order, close_position (Alpaca wrapper)
│   └── database.py              # write_decision_log, get_trade_history, etc.
├── monitor/
│   └── position_monitor.py      # Lightweight hourly rule-based checker
├── storage/
│   └── trades.db                # SQLite — all trade and agent reasoning data
└── reports/                     # Generated Markdown reports (gitignored)
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
All indicator parameters live in `config/settings.py` and in the `parameters` DB table (versioned). The Strategy Agent proposes changes — the Team Leader flags them for human approval. They never change without explicit approval.

---

## Risk Management

**Position sizing:**
```
Max risk per trade = 1% of portfolio value
Stop distance     = ATR-based (adapts to ticker volatility)
Position size     = Max risk / Stop distance (in dollars/share)
```

**Per-trade structure:**
- ATR-based stop-loss set at entry
- Take-profit at minimum 1:2 R:R from entry
- Trailing stop: once trade is up 1R, stop moves to breakeven

**Portfolio-level guardrails:**
- Max 5 open positions simultaneously
- Max 20% of portfolio deployed at once
- Daily drawdown > 3% → pause new entries for remainder of day, log event

All thresholds are config-driven and subject to Strategy Agent suggestions (with human approval).

---

## Autonomy Model

| Action | Autonomous |
|---|---|
| Place trades based on current signals | Yes |
| Execute stop-loss / take-profit | Yes |
| Exit on trend reversal or max hold | Yes |
| Pause trading on daily drawdown breach | Yes |
| Change strategy parameters | No — Strategy Agent suggests, human approves |
| Change risk thresholds | No — Strategy Agent suggests, human approves |
| Add/remove tickers from watchlist | No — human decision |

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

**`agent_logs`** — full reasoning chain per cycle
```sql
id, cycle_date, agent_name, input_summary, output_summary,
full_reasoning, tokens_used
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
09:35          Morning scan — all four agents run, entries placed
10:00–15:00    Hourly — lightweight rule-based position monitor
16:00          Final position check (rule-based)
16:30          Daily reflection — Strategy Agent + Team Leader log
Fri 16:45      Weekly reflection — full agent review + suggestions flagged
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
ANTHROPIC_API_KEY=...
TRADING_MODE=paper          # swap to 'live' when ready
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
CLAUDE_MODEL=claude-sonnet-4-6
```

**Paper → Live switch:** Change `TRADING_MODE=live` and swap Alpaca API keys. Zero code changes.

**GitHub:**
- Private repo, code deployed to VPS via `git pull`
- `reports/`, `storage/trades.db`, `.env` are gitignored

---

## Key Libraries

| Library | Purpose |
|---|---|
| `anthropic` | Claude API — powers all four agents |
| `alpaca-trade-api` | Broker integration |
| `pandas` | Data manipulation |
| `pandas_market_calendars` | US market calendar |
| `ta` (technical-analysis) | EMA, RSI, ATR computation |
| `sqlite3` | Built-in, no extra dependency |
| `python-dotenv` | Environment variable loading |
