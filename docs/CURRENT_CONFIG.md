# Current Production Config

Pinned snapshot of the live trading bot configuration. Update this file whenever strategy parameters, watchlist, or risk rules change so a fresh VPS can be brought up to production parity with a single copy-paste.

> **Why this file exists:** the `README.md` documents the *baseline defaults* (what a fresh clone of the repo starts with). This file documents what the *deployed bot actually runs*. The two diverge as strategy tuning accumulates.

---

## Last updated

**2026-04-24** — strategy params tuned and watchlist pruned based on 3-year backtest. See commit `49aa3ea` and the *Change Log* section below.

---

## Live strategy parameters

Set these in `/opt/trading-bot/.env` on the VPS. Values not listed here use the defaults from `config/settings.py`.

```env
# Strategy gates — loosened from baseline to produce tradeable signals
STRICT_CROSSOVER=false
RSI_LOWER=35
RSI_UPPER=70
VOLUME_MULTIPLIER=1.2
ATR_STOP_MULTIPLIER=1.3

# Hold period — longer than baseline so trends have room to run
MAX_HOLD_DAYS=10

# Risk — unchanged from baseline
RISK_PER_TRADE=0.01
MAX_POSITIONS=5
MAX_PORTFOLIO_EXPOSURE=0.20
RR_RATIO_MIN=2.0
```

### What each change does

| Var | Baseline | Live | Effect |
|---|---|---|---|
| `STRICT_CROSSOVER` | `true` | `false` | Accept EMA20 > EMA50 as trend state, not just the crossover event. Unblocks stale-signal days. |
| `RSI_LOWER` | `40` | `35` | Lets mildly oversold entries in — caught NOW at 37.60 in live data on 2026-04-23. |
| `RSI_UPPER` | `60` | `70` | Lets trending names in — previously rejected NVDA at 67.89. |
| `VOLUME_MULTIPLIER` | `1.5` | `1.2` | 1.5× was a breakout-only threshold; 1.2× accepts normal-conviction days. |
| `ATR_STOP_MULTIPLIER` | `1.5` | `1.3` | Tighter stops keep per-trade losses smaller — improved 3yr return by ~+1 point vs 1.5. |
| `MAX_HOLD_DAYS` | `5` | `10` | Single biggest return lever in backtest — let winners run. |

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

3-year window `2023-04-24 → 2026-04-24`, 1-year and 2-year cross-validated.

| Config | Trades | Win% | 3yr Return | 2yr Return | 1yr Return | Worst DD |
|---|---|---|---|---|---|---|
| Baseline (pre-tune) | 5 | 60% | +0.2% | ≈0% | +0.1% | -2.4% |
| **Live (D6 + prune)** | **471** | **45.9%** | **+8.7%** | **+3.4%** | **+2.6%** | **-10.4%** |

The win rate dropped because the strategy is now actively trading. With `RR_RATIO_MIN=2.0` the break-even win rate is ~33%, so 46% is comfortably positive expectancy.

Per-ticker 3yr returns (live config): GOOGL +30.4%, AVGO +24.8%, META +18.1%, JPM +9.4%, AAPL +7.0%, LLY +6.7%, AMD +4.6%, SHEL +4.0%, TSLA +0.9%, NVDA +0.2%, NOW -1.0%, AMZN -1.1%.

---

## Bringing up a fresh VPS at production parity

1. Follow `README.md` § "VPS Deployment" steps 1-3 (install deps, clone, venv).
2. For step 4, use the minimal `.env` from the README **plus** the strategy block from this document.
3. Continue README steps 5-8 (init DB, log dir, test, cron).

The first scan after `13:35 UTC` should produce trade candidates if market conditions allow. If three consecutive days return zero candidates again, tune further — this file becomes the source of truth for "what was tried".

---

## Change log

Keep this section chronological, newest entry on top. Each entry should fit in 1-5 lines.

### 2026-04-24 — D6 tune + watchlist prune

- Strategy params: `STRICT_CROSSOVER=false`, `MAX_HOLD_DAYS=10`, `RSI_LOWER=35`, `RSI_UPPER=70`, `VOLUME_MULTIPLIER=1.2`, `ATR_STOP_MULTIPLIER=1.3`.
- Watchlist: dropped `UNH`, `V`, `MSFT`, `MA` (16 → 12 tickers).
- Driver: 3 consecutive no-trade days (2026-04-22 → 24); strategy agent cited volume gate as the universal blocker.
- Landed in commit `49aa3ea`.
