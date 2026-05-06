# Current Production Config

Pinned snapshot of the live trading bot configuration. Update this file whenever strategy parameters, watchlist, or risk rules change so a fresh VPS can be brought up to production parity with a single copy-paste.

> **Why this file exists:** the `README.md` documents the *baseline defaults* (what a fresh clone of the repo starts with). This file documents what the *deployed bot actually runs*. The two diverge as strategy tuning accumulates.

---

## Last updated

**2026-05-06** — v1.14.0 lights up the previously-dormant analytical tables (`monitor_actions`, `signals`, `daily_stats`), anchors bracket children to the actual broker fill (`filled_avg_price`) instead of the pre-order quote, and makes the Discord summary line deterministic. Two new env vars introduced: `FILL_POLL_TIMEOUT_S=10` and `FILL_POLL_INTERVAL_S=0.5`. **Operator deploy step:** run `python -c "from storage.init_db import init_db; init_db()"` once after pulling to materialise the new `monitor_actions` table. See the *Change Log* section below.

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
- **OCO bracket orders post-fill (v1.14).** When the Team Leader has both a stop and a take-profit, `tools/broker.place_market_order` submits a parent market order, polls `get_order_by_id` for the actual `filled_avg_price` (`FILL_POLL_TIMEOUT_S` / `FILL_POLL_INTERVAL_S`), then submits a separate sell-side `OrderClass.OCO` LimitOrderRequest with both legs anchored to that fill price. Realised R:R drift is now ±1% of `RR_RATIO_MIN` regardless of fill slippage (was ±5% with the atomic BRACKET class). Stops and targets still live broker-side; exits keep firing even if the local monitor cron is down. The fill-to-OCO unprotected window is typically <1s; if the OCO submit fails (broker outage), `position_monitor`'s soft-stop is the recovery layer (`trades.stop_loss` is written anchored to the fill so the soft-stop has the right reference). The position monitor reconciles broker-side closes back into the DB.
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

### 2026-05-06 — v1.14.0 observability + accuracy sprint

- Analytical tables now populated (specced in v1.5.0, dormant until now): `monitor_actions` (every per-trade outcome from `position_monitor`), `signals` (every fill *and* every rejection from `team_leader.place_order`, with `triggered_entry=1/0`), `daily_stats` (end-of-pass summary upserted by `position_monitor`). `weekly_stats` is intentionally deferred — no writer yet (#140 #141 #142, closes #131 #136 #137).
- **Operator deploy step:** run `python -c "from storage.init_db import init_db; init_db()"` once on the VPS to materialise the new `monitor_actions` table. The other tables were already in `storage/schema.sql` since v1.0; `init_db()` is idempotent.
- `trades.entry_price` is now the broker's `filled_avg_price`, not the pre-order quote. New env vars `FILL_POLL_TIMEOUT_S=10` and `FILL_POLL_INTERVAL_S=0.5` control the `_poll_for_fill` loop in `tools/broker.place_market_order`. Falls back to the pre-order quote on poll timeout (#143, closes #132).
- Bracket flow changed: was atomic Alpaca BRACKET (children committed to pre-order quote, ±5% R:R drift under typical slippage); is now parent → poll for fill → sell-side OCO LimitOrderRequest with both legs anchored to `filled_avg_price` (±1% R:R drift, invariant to fill slippage). Brief fill-to-OCO unprotected window (<1s typical); position monitor's soft-stop is the recovery layer (#144, closes #133).
- `position_monitor.run_monitor` wraps the top-of-loop `get_alpaca_positions()` call in its own try/except — fail-CLOSED on broker outage. The cycle returns an empty action list, the `daily_stats` upsert is skipped, `notify_error` fires, and the next hourly cron fire retries (#145, closes #134).
- Team Leader Discord summary line and `agent_logs.output_summary` are now derived deterministically from `place_order` tool_results (a per-run `_order_outcomes` ledger), not from LLM prose. Two named regression tests lock the 2026-05-04 ("executed" with no trade) and 2026-05-05 ("0 rejected" when 2 were rejected) misreports (#146, closes #139).
- Live strategy block above unchanged. Watchlist unchanged.

### 2026-05-04 — v1.13.0 panic CLI + honest dry-run

- New `python main.py panic` deterministic incident-response CLI: `--cancel-orders`, `--liquidate --confirm`, `--pause` (atomic write to `/opt/trading-bot/.env`, anchored to repo root via `Path(__file__).resolve().parent`). No LLM in the path. Single `agent_logs` row per invocation, written before broker call and updated in `finally` with per-action result. Discord 🛑 alert on every action; tracebacks captured on exception (#128, closes #103). Closes roadmap candidate 9.1 from `docs/research/swing-trading/roadmap.md`.
- `team_leader.place_order(dry_run=True)` now runs the deterministic safety stack (`check_exposure_for_new_order` against broker truth, `validate_bracket_params`) — only the broker SUBMIT and DB INSERT are skipped. `--dry-run` is now a true smoke test: an over-cap or malformed candidate is rejected the same as live (#127, closes #123).
- Discord scan-complete header swaps to `🧪 **Morning Scan (DRY RUN) — {date}**` for dry-run scans; live output unchanged (#126, closes #122).
- Test fixture for earnings blackout relativized to `date.today() + timedelta(days=1)` so it survives wall-clock drift; production logic unchanged (#125, closes #120).
- No env-var or settings change. Live `.env` and watchlist unchanged.

### 2026-05-04 — v1.12.1 reliability patch

- `BaseAgent._handle_tool_calls` wraps tool calls in try/except — failures (and unknown tools) return as `tool_result` with `is_error: True` instead of crashing the scan (#119, closes #113). Defensive validation in `tools/risk.calculate_position` rejects non-positive inputs with a clear `ValueError` instead of `ZeroDivisionError`.
- `run_monitor` isolates each per-trade iteration: a transient broker/network blip on one ticker fires `notify_error` and records a `hold/skipped_error` action; the loop continues so the rest of the book still gets its soft-stop check (#118, closes #115).
- `notify_error` keeps both ends of long tracebacks (`head[:240] + "\n...\n" + tail[-240:]`) so the exception type and message survive the Discord cutoff (#117, closes #114).
- No env-var or settings change. Live `.env` and watchlist unchanged.

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
