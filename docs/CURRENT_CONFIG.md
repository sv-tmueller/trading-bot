# Current Production Config

Pinned snapshot of the live trading bot configuration. Update this file whenever strategy parameters, watchlist, or risk rules change so a fresh VPS can be brought up to production parity with a single copy-paste.

> **Why this file exists:** the `README.md` documents the *baseline defaults* (what a fresh clone of the repo starts with). This file documents what the *deployed bot actually runs*. The two diverge as strategy tuning accumulates.

---

## Last updated

**2026-04-29** — v1.10 risk hardening (deterministic exposure gate, bracket orders, `TRADING_PAUSED` kill switch) and v1.11 promotion of `DAILY_DRAWDOWN_LIMIT` to env-driven. Strategy params and watchlist unchanged from the E3 tune. See the *Change Log* section below.

---

## Live strategy parameters

Set these in `/opt/trading-bot/.env` on the VPS. Values not listed here use the defaults from `config/settings.py`.

```env
# Strategy gates — loosened further in the E3 tune to maximise exposure to trending names
STRICT_CROSSOVER=false
RSI_LOWER=30
RSI_UPPER=75
VOLUME_MULTIPLIER=1.0
ATR_STOP_MULTIPLIER=1.5

# Hold period — doubled from D6 so winners can run through short-term chop
MAX_HOLD_DAYS=20

# Risk — asymmetry thesis: require 3:1 reward:risk at entry
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
MAX_PORTFOLIO_EXPOSURE=0.20
DAILY_DRAWDOWN_LIMIT=0.03
RR_RATIO_MIN=3.0

# Operational kill switch — set to `true` to skip the scan without removing cron
TRADING_PAUSED=false
```

### What each change does

| Var | Baseline | Live (E3) | Effect |
|---|---|---|---|
| `STRICT_CROSSOVER` | `true` | `false` | Accept EMA20 > EMA50 as trend state, not just the crossover event. Unblocks stale-signal days. |
| `RSI_LOWER` | `40` | `30` | Accepts mild oversold entries. Adds ~7pp return over the 10yr window vs RSI_LOWER=35. |
| `RSI_UPPER` | `60` | `75` | Catches strong-trending names earlier — key contributor for AVGO/GOOGL-style runners. |
| `VOLUME_MULTIPLIER` | `1.5` | `1.0` | Loosens conviction filter. Adds trade count without degrading PF — quality per trade is roughly unchanged. |
| `ATR_STOP_MULTIPLIER` | `1.5` | `1.5` | Counter-intuitively improves PF vs the D6 value of `1.3`. Wider stops survive noise; tighter stops (ATR 1.0 tested) blew drawdown to -39%. |
| `MAX_HOLD_DAYS` | `5` | `20` | Single biggest return lever in this sweep — doubling the hold window let winners run past short-term chop. |
| `RR_RATIO_MIN` | `2.0` | `3.0` | Core of the asymmetry thesis — winners should be ~3× the risk distance. W:L jumps from 1.59 (D6) to 2.08 (E3). |

---

## Risk invariants (v1.10/v1.11)

Risk hardening that lives in code, not in the `.env` block. These rules are enforced deterministically before any LLM output reaches the broker.

- **Deterministic `MAX_PORTFOLIO_EXPOSURE` gate.** `tools/risk.check_exposure_for_new_order` runs in `TeamLeaderAgent` immediately before order placement. An order that would push gross exposure above `MAX_PORTFOLIO_EXPOSURE` is rejected with `max_exposure` reason, regardless of what the LLM proposed.
- **Bracket orders by default.** When the Team Leader has both a stop and a take-profit, `tools/broker.place_market_order` submits an Alpaca bracket so stops and targets live broker-side. Exits keep firing even if the local monitor cron is down — the position monitor reconciles broker-side closes back into the DB.
- **`TRADING_PAUSED` kill switch.** Setting `TRADING_PAUSED=true` makes `main.py scan` print the pause message and exit 0 without instantiating any agent. Use it to halt new entries without removing cron; existing brackets keep managing open positions.
- **`DAILY_DRAWDOWN_LIMIT` is env-driven (v1.11).** Promoted out of code in PR #89. The pre-trade guardrail in `tools/risk.check_portfolio_guardrails` reads `settings.DAILY_DRAWDOWN_LIMIT` (default `0.03`); breaching it blocks new orders for the rest of the session.

---

## Live watchlist

`config/watchlist.py` is the source of truth — this section mirrors it for quick reference.

```python
WATCHLIST = [
    "AMD",
    "NOW",    # ServiceNow
    "SHEL",   # Shell ADR (only energy exposure)
    "NVDA",
    "GOOGL",
    "META",
    "AMZN",
    "TSLA",
    "AAPL",
    "JPM",
    "LLY",    # Eli Lilly
    "AVGO",   # Broadcom
]
```

### Dropped from the earlier 16-ticker list (2026-04-24)

All four were negative in 4-5 of 5 tested backtest configs (D1, D3, D6, D8, D9):

| Ticker | Avg return across configs | Verdict |
|---|---|---|
| `UNH` | -11.0% (5/5 negative) | Consistent loser with the largest drawdowns |
| `V`   | -6.0% (5/5 negative)  | Consistent loser |
| `MSFT`| -4.5% (5/5 negative)  | Surprising — but the data is unambiguous |
| `MA`  | -3.8% (4/5 negative)  | Consistent loser |

---

## Backtest results (how we got here)

The E3 tune was selected from a 20-config parameter sweep run across 1/3/5/10-year windows. Headline numbers below are pooled across all trades (ticker-independent simulator). Baseline and D6 rows kept for historical comparison.

| Config | Trades (10yr) | Win% | 10yr Return | PF | W:L | Expect | Worst DD |
|---|---|---|---|---|---|---|---|
| Baseline (pre-tune) | 5 | 60% | +0.2% (3yr) | — | — | — | -2.4% |
| D6 (previous live) | 471 (3yr) / pooled | 45.9% (3yr) | +16.6% (10yr) | 1.20 | 1.59 | +0.4% | -23.6% |
| **E3 (current live)** | **1613** | **40.3%** | **+42.1%** | **1.42** | **2.08** | **+1.0%** | **-21.1%** |

Cross-validation on shorter windows — metrics stable across regimes:

| Window | Return | PF | W:L |
|---|---|---|---|
| 3yr | +7.8% | 1.32 | 2.03 |
| 5yr | +14.9% | 1.35 | 1.99 |
| 10yr | +42.1% | 1.42 | 2.08 |

Win rate intentionally drops under E3: with `RR_RATIO_MIN=3.0` the break-even win rate is ~25%, so 40.3% leaves a healthy expectancy buffer (+1.0% per trade). The thesis is asymmetry — fewer wins, but each win is ~2× the size of each loss.

**Why E3 and not F3.** F3 (RSI 25-80) scored marginally higher (+45.9% / PF 1.43) but pushes entries into deep oversold/overbought territory. The backtest doesn't model slippage or gap risk in those regions, so E3 was chosen as the more conservative live config.

---

## Bringing up a fresh VPS at production parity

1. Follow `README.md` § "VPS Deployment" steps 1-3 (install deps, clone, venv).
2. For step 4, use the minimal `.env` from the README **plus** the strategy block from this document.
3. Continue README steps 5-8 (init DB, log dir, test, cron).

The first scan after `13:35 UTC` should produce trade candidates if market conditions allow. If three consecutive days return zero candidates again, tune further — this file becomes the source of truth for "what was tried".

---

## Change log

Keep this section chronological, newest entry on top. Each entry should fit in 1-5 lines.

### 2026-04-29 — v1.10/v1.11 risk hardening

- Deterministic `MAX_PORTFOLIO_EXPOSURE` gate now runs in `TeamLeaderAgent` before every order — LLM cannot bypass.
- Bracket orders: `place_market_order` submits Alpaca brackets when stop + target are set, so exits live broker-side.
- `TRADING_PAUSED` kill switch added — set to `true` in `.env` to halt new entries without touching cron.
- `DAILY_DRAWDOWN_LIMIT` promoted to env-driven (v1.11, PR #89). Default `0.03`; trips the daily guardrail in `tools/risk.py`.

### 2026-04-24 — E3 strategy tune

- Strategy params: `RSI_LOWER=30`, `RSI_UPPER=75`, `VOLUME_MULTIPLIER=1.0`, `MAX_HOLD_DAYS=20`, `ATR_STOP_MULTIPLIER=1.5`, `RR_RATIO_MIN=3.0` (`STRICT_CROSSOVER=false` unchanged).
- 10yr pooled: 1613 trades, 40.3% win rate, **+42.1% return**, PF **1.42**, W:L **2.08**, expectancy **+1.0%** per trade, max per-ticker DD -21.1%.
- Cross-validated: 3yr +7.8% / PF 1.32 / W:L 2.03 — 5yr +14.9% / PF 1.35 / W:L 1.99. Metrics stable across regimes.
- Driver: 20-config parameter sweep across 1/3/5/10yr windows; E3 chosen over F3 (RSI 25-80) because F3's deeper RSI bounds aren't robust to unmodeled slippage/gap risk.
- Watchlist unchanged from the D6 prune (12 tickers). Docs-only rollout — VPS `.env` updated separately.

### 2026-04-24 — D6 tune + watchlist prune

- Strategy params: `STRICT_CROSSOVER=false`, `MAX_HOLD_DAYS=10`, `RSI_LOWER=35`, `RSI_UPPER=70`, `VOLUME_MULTIPLIER=1.2`, `ATR_STOP_MULTIPLIER=1.3`.
- Watchlist: dropped `UNH`, `V`, `MSFT`, `MA` (16 → 12 tickers).
- Driver: 3 consecutive no-trade days (2026-04-22 → 24); strategy agent cited volume gate as the universal blocker.
- Landed in commit `49aa3ea`.
