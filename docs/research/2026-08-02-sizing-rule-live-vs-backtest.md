# Sizing rule: live hourly bot vs the research backtester

**Question:** Which sizing rule did the research backtest actually use, and does the live
hourly bot's `min(risk-based, notional-cap)` rule change the result that justified the strategy?
**Issue:** #499
**Date:** 2026-08-02

---

## Summary

The research engines size **all-in on available cash, unlevered**. They model **no risk budget
and no notional cap of any kind**. The live hourly bot's 10% notional cap is therefore a rule
the backtester never ran, and the live bot deploys **one tenth** the notional the research
figures were produced with.

That difference **does not touch the validated edge** — win rate, per-trade return and profit
factor are sizing-invariant (measured: profit factor moves by at most 0.036 across all 14 arms).
It **does** rescale every equity-curve headline: replaying the frozen candlestick family under
the live rule produced 0.07x-0.15x the all-in total return and drawdown.

Separately, the issue's hypothesis that a $1M paper account is what broke the risk leg is
**refuted**: equity cancels out of both terms, so the crossover is equity-invariant. The risk leg
binds only when `stopDistance > (SIZING_RISK_PCT / SIZING_NOTIONAL_CAP_PCT) x entryRef`
= 10% of price at the defaults. Across 1,484 daily-bar trades in the frozen family the largest
stop distance was 9.01% of price and **zero** trades had the risk leg bind — at $100k equity, not
just at $1M. The spec's own worked example (`2026-07-27-hourly-bot-design.md:410-429`) has the cap
binding in **both** of its $100k scenarios.

---

## Method

### 1. Code inspection (read-only)

Every candlestick/bracket cell in the research family runs through
`backtest/bracket.py::simulate_bracket`. Its one and only sizing line:

```python
# backtest/bracket.py:325
size = int(cash / exec_px / (1 + comm)) if exec_px > 0 else 0
```

All available cash, whole shares, no leverage, no cap, no reference to the stop. The docstring
states the convention explicitly for the short arm too (`bracket.py:210-212`): *"Sizing is the same
all-in, unlevered notional convention as the long side."* `starting_cash` defaults to
`STARTING_CASH = 100_000.0` (`backtest/regime.py:36`), which is what all three frozen candlestick
runners pass (`run_candlestick_study.py:185, 235, 250`).

The older 200-DMA engine is the same shape, with one fixed-fraction knob:

```python
# backtest/regime.py:164-165
investable = cash * alloc_frac
qty = int(investable / execution_px / (1 + commission_bps / 10_000))
```

`alloc_frac` defaults to `1.0` (`regime.py:57`) and is passed as anything else in exactly one
place, `run_longrun.py:107,123` (`0.5`, a half-UPRO comparison arm). It is a static fraction of
cash, not a per-trade risk budget, and it is not a per-position notional cap in the live sense
(it deploys a fraction of *cash*, and the residual is not reserved for a second position).

Live rule for comparison (`supabase/functions/hourly-check/logic.ts:280-283`):

```ts
const riskBudget = cfg.sizingRiskPct * equity;
const qtyRisk = Math.floor(riskBudget / stopDistance);
const qtyCap = Math.floor((cfg.sizingNotionalCapPct * equity) / entryRef);
const qty = Math.min(qtyRisk, qtyCap);
```

Defaults `SIZING_RISK_PCT = 0.01`, `SIZING_NOTIONAL_CAP_PCT = 0.10`
(`_shared/config.ts:99,104`).

### 2. Replay probe

Rebuilt the frozen v1 candlestick grid at R=2 (14 arms, `build_cell` imported unchanged from
`backtest/run_candlestick_study.py`) on the repo's local `data/SPY_daily.csv`
(3,409 daily bars, 2013-01-02 to 2026-07-23, `SLIPPAGE_BPS=5`, `COMMISSION_BPS=5`), then replayed
each arm's trade ledger under the **live** sizing rule — same entries, same exits, same costs, only
`qty` recomputed as `min(floor(0.01 x E / stopDistance), floor(0.10 x E / entryPrice))` with `E`
compounding trade by trade. Stop distances came from the study's own `bracket_levels()`, so the
geometry is the researched geometry, not a reconstruction.

Nothing under `backtest/`, `strategy/`, or `supabase/functions/` was modified. The probe script is
reproduced verbatim in the appendix. No broker call is reachable from any of this; the only network
touched was the `main.py` sanity run below (yfinance, read-only).

Commands:

```bash
venv/bin/python /tmp/sizing_sensitivity.py      # appendix A, replay probe
venv/bin/python main.py backtest --years 5      # sanity check that the research CLI still runs
```

The `main.py` sanity run (2021-08-02 -> 2026-08-02, UPRO/SPY/SMA200): total return +138.54%,
CAGR +18.99%, max DD -30.50%, 11 trades, ending equity $238,544.87. That is the *old* 200-DMA bot,
included only to confirm the research toolchain is healthy on this commit — it is not the hourly
bot's evidence base.

### 3. What actually validated the hourly bot

Nothing did, and this is on the record. `docs/decisions/2026-07-27-hourly-candlestick-signal.md`
states: *"The bot therefore ships with no pre-registered evidence of edge of any kind, favourable or
unfavourable, by explicit operator direction, with the Alpaca paper account as the accepted risk
container."* The three closed studies it cites are all **daily**; the candlestick family closed at
N=168 with 0/168 cells clearing the frozen after-tax-Calmar bar. There is no hourly SPY backtest
module in `backtest/` at all. So #499's first acceptance criterion — *"confirm against the research
backtest which sizing rule the validated strategy used"* — has to be read as **the sizing rule the
closest research family used**, because there is no validating backtest to confirm against.

---

## Results

### Frozen candlestick family, all-in (as researched) vs the live sizing rule

SPY daily bars 2013-01-02 to 2026-07-23, R=2, `starting_cash = $100,000`, no context filter, no
time stop (the frozen v1 grid). "ratio" is live-rule total return / all-in total return.

| Arm | Trades | All-in return | All-in max DD | Live-rule return | Live-rule max DD | ratio | Win rate | PF (all-in) | PF (live) | Trades where `qtyRisk` binds | Median stop / price |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bullish_engulfing | 74 | +10.86% | -17.97% | +1.30% | -1.90% | 0.12 | 35.1% | 1.149 | 1.181 | 0 | 1.076% |
| bearish_engulfing | 102 | -64.47% | -65.53% | -9.50% | -9.80% | 0.15 | 21.6% | 0.290 | 0.296 | 0 | 1.104% |
| hammer | 100 | -12.34% | -26.21% | -1.06% | -2.89% | 0.09 | 37.0% | 0.857 | 0.884 | 0 | 0.900% |
| shooting_star | 42 | -20.13% | -20.13% | -2.12% | -2.12% | 0.11 | 28.6% | 0.494 | 0.509 | 0 | 0.895% |
| bullish_pin_bar | 168 | -11.24% | -20.56% | -0.79% | -2.20% | 0.07 | 41.7% | 0.913 | 0.941 | 0 | 0.848% |
| bearish_pin_bar | 92 | -33.70% | -34.58% | -3.82% | -3.96% | 0.11 | 30.4% | 0.530 | 0.557 | 0 | 0.815% |
| bullish_marubozu | 62 | +25.71% | -14.58% | +2.45% | -1.49% | 0.10 | 45.2% | 1.449 | 1.471 | 0 | 1.137% |
| bearish_marubozu | 51 | -18.45% | -18.75% | -1.80% | -1.96% | 0.10 | 31.4% | 0.711 | 0.735 | 0 | 1.528% |
| bullish_harami | 91 | +13.54% | -21.69% | +1.50% | -2.37% | 0.11 | 40.7% | 1.164 | 1.194 | 0 | 0.962% |
| bearish_harami | 93 | -21.16% | -23.17% | -2.19% | -2.44% | 0.10 | 36.6% | 0.672 | 0.688 | 0 | 0.638% |
| morning_star | 70 | +27.87% | -24.59% | +2.83% | -2.67% | 0.10 | 44.3% | 1.285 | 1.341 | 0 | 1.736% |
| evening_star | 81 | -49.48% | -49.64% | -6.28% | -6.31% | 0.13 | 25.9% | 0.430 | 0.436 | 0 | 1.326% |
| inside_bar_long | 202 | -20.54% | -30.85% | -1.82% | -3.34% | 0.09 | 40.6% | 0.865 | 0.896 | 0 | 0.861% |
| inside_bar_short | 256 | -68.26% | -69.69% | -10.50% | -10.88% | 0.15 | 29.7% | 0.439 | 0.475 | 0 | 0.625% |

Win rate is identical under both rules by construction (`return_pct` does not depend on `qty`), so
one column serves both.

### Equity-scale check (same rule, two account sizes)

| Arm | Live-rule return at $100,000 | Live-rule return at $1,017,336 | `qtyRisk` binds (100k / 1.017M) |
|---|---|---|---|
| bullish_engulfing | +1.30% | +1.34% | 0 / 0 |
| bearish_engulfing | -9.50% | -9.63% | 0 / 0 |
| hammer | -1.06% | -1.07% | 0 / 0 |
| shooting_star | -2.12% | -2.14% | 0 / 0 |

The residual few-basis-point differences are whole-share rounding, nothing else.

### Stop-distance distribution, 1,484 trades across all 14 arms

| Statistic | stopDistance / entryPrice |
|---|---|
| min | 0.0018% |
| median | 0.9082% |
| p99 | 4.9882% |
| max | 9.0069% |
| trades above the 10% crossover | **0 / 1,484** |

Live geometry is tighter still: `computeBracketGeometry` (`logic.ts:240-243`) sets the stop at the
*hourly* bar's low minus 5% of that bar's range (`HOURLY_STOP_BUFFER_PCT = 0.05`,
`config.ts:120`), so `stopDistance <~ 1.05 x hourlyBarRange`. An hourly bar's range is bounded by
its parent daily bar's range; SPY daily range/close has median 0.858% (2013-2026) and exceeded 9.5%
on 8 of 8,427 sessions since 1993 (1 of 3,409 since 2013). The risk leg is therefore unreachable on
SPY hourly bars in practice, not merely inactive at present.

### The 2026-07-31 trade under each rule

Entry 742.1842, equity $1,017,336, `SIZING_RISK_PCT = 0.01`, `SIZING_NOTIONAL_CAP_PCT = 0.10`.

| Rule | Quantity | Notional | % of equity |
|---|---|---|---|
| Live, as filled (`qtyCap` bound) | **137** | $101,679 | 10.0% |
| Backtest all-in (`int(cash / px / 1.0005)`) | **1,370** | $1,016,795 | 99.9% |
| Live risk leg, `stopDistance = $0.75` | 13,564 | $10,066,986 | 989.5% |
| Live risk leg, `stopDistance = $1.50` | 6,782 | $5,033,493 | 494.8% |
| Live risk leg, `stopDistance = $3.00` | 3,391 | $2,516,747 | 247.4% |

Stated as a function of stop distance `d` (the actual stop is not available to this analysis):
`qtyRisk = floor(10,173.36 / d)`, and `qtyRisk >= qtyCap = 137` for every `d <= $74.26`.
The all-in figure is exactly 10x the live figure, which is just `1 / SIZING_NOTIONAL_CAP_PCT`.

Note what the risk leg implies if it ever became operative on an hourly SPY stop: 250%-990% of
equity in a single position, i.e. 2.5x-9.9x margin. That is outside anything
`simulate_bracket` can represent — its `int(cash / exec_px)` cannot exceed 100% of cash.

---

## Findings

- **The backtest sizes all-in on cash and models no notional cap and no risk budget**
  (`bracket.py:325`; `regime.py:164-165` with `alloc_frac` defaulting to 1.0). The live bot's
  `min(qtyRisk, qtyCap)` rule is not a rule any research run in this repo has executed. The one
  fractional-sizing precedent, `alloc_frac=0.5` in `run_longrun.py:107,123`, is a static
  fraction-of-cash comparison arm, not a per-trade risk budget.
- **The edge is sizing-invariant; the headline numbers are not.** This is the crux of #499.
  Per-trade statistics carry across unchanged — win rate is identical by construction, and profit
  factor moves by at most +0.036 (worst case `inside_bar_short`, 0.439 -> 0.475; the small uplift
  is linear-vs-compounded trade weighting, not an edge change). Equity-curve statistics do **not**
  carry across: live-rule total return and max drawdown came in at 0.07x-0.15x the all-in figures
  across all 14 arms. Any comparison of live paper results against a backtested return or drawdown
  must divide the backtest figure by ~10 first.
- **The $1M-account hypothesis is wrong.** Equity multiplies both `qtyRisk` and `qtyCap`, so it
  cancels: `qtyRisk < qtyCap` exactly when `stopDistance > (SIZING_RISK_PCT / SIZING_NOTIONAL_CAP_PCT)
  x entryRef` = 10% of price at the defaults, independent of account size. The replay confirms it
  empirically (1.30% at $100k vs 1.34% at $1.017M, same zero risk-leg binds), and the spec's own
  $100k worked examples already show the cap binding in both branches
  (`2026-07-27-hourly-bot-design.md:410-429`). The parameters were not "tuned for a smaller account"
  and re-scaling the account will not revive the risk leg.
- **No legal `SIZING_NOTIONAL_CAP_PCT` makes the risk leg reachable at 1% risk.** The cap is
  validated at `(0, 1.0]` (`config.ts:105`). Even at `1.0` the crossover is `stopDistance > 1% of
  price`, which SPY hourly bars clear only rarely (daily median range is 0.858%, and hourly is
  strictly tighter). Making both legs live requires lowering `SIZING_RISK_PCT`, not raising the cap.
- **The bot's actual risk per trade is what the cap implies, not what the config says.**
  Cap-bound sizing risks `SIZING_NOTIONAL_CAP_PCT x (stopDistance / price)` of equity =
  0.10 x ~0.3% ~ **0.03%** per trade on a typical hourly bar, versus the configured 1%. The
  issue's ~0.02% estimate for the 2026-07-31 fill is the same arithmetic.
- **A `qtyRisk`-binding unit test already exists** (`hourly-check/logic.test.ts:270-271`:
  `qtyRisk=90`, `qtyCap=400`, `qty=90`), using a hypothetical $25 instrument. So #499's third
  acceptance criterion is met at unit level; what does not exist, and cannot be constructed, is a
  reachable SPY case.

---

## Recommendation

**Document the cap as the operative rule. Do not re-parameterise as part of #499, and do not close
as working-as-intended without the doc change** — the settings as written misdescribe the bot's
risk posture by roughly 30x, which is a real documentation defect even though the behaviour is safe.

Concretely, for an Engineer to pick up (all docs/comments, no behaviour change):

1. `README.md:108` — restate `SIZING_RISK_PCT` as *"Hourly bot risk budget per trade as a fraction
   of equity. Upper bound only: it binds only when `stopDistance > (SIZING_RISK_PCT /
   SIZING_NOTIONAL_CAP_PCT) x entryRef` (10% of price at the defaults), which SPY hourly bars do not
   reach. `SIZING_NOTIONAL_CAP_PCT` is the operative sizer for SPY."*
2. `README.md:109` — mark `SIZING_NOTIONAL_CAP_PCT` as the operative sizer for SPY-class
   instruments.
3. `.env.example:22` — same one-line qualification next to `SIZING_RISK_PCT=0.01`.
4. `supabase/functions/hourly-check/logic.ts` — a comment above `computeSizing` recording the
   crossover condition, so the next reader does not re-derive it.
5. `docs/runbooks/hourly-bot-rollout.md:480` — the "order whose notional materially exceeds 10% of
   equity" alarm is correct and should be noted as the *primary* sizing check, since the risk leg
   provides no practical second bound.
6. Add a line to the weekly-review procedure (`docs/runbooks/weekly-review.md`): backtest return and
   drawdown figures are all-in; divide by ~10 before comparing against live paper results at
   `SIZING_NOTIONAL_CAP_PCT = 0.10`.

**Keep `SIZING_NOTIONAL_CAP_PCT = 0.10` for the paper experiment.** It is the only thing holding
live notional inside the unlevered envelope the research engine can even represent; the risk leg at
1% would demand 2.5x-9.9x margin on an hourly SPY stop.

**If the operator later wants both legs reachable** — that is a strategy change, not a fix, and
needs its own brainstorm and spec revision, because it makes position size vary inversely with stop
distance where today it is a constant 10% of equity. The evidence base being accumulated right now
is being accumulated under constant-10% sizing. For sizing purposes only, the arithmetic is:
`SIZING_RISK_PCT ~ 0.0003` with the cap at `0.10` puts the crossover at ~0.3% of price, i.e. at the
middle of the hourly stop-distance distribution, and approximately preserves today's realised
per-trade risk. It is inside the validated range `(0, 0.05]`, so no `config.ts` change would be
needed — which is exactly why it should not be done casually.

---

## Appendix A: replay probe

Written to a scratch path and run with `venv/bin/python`. Imports the frozen runners unchanged;
modifies nothing.

```python
"""Read-only sizing-rule sensitivity probe for issue #499."""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/TM/Desktop/github/trading-bot")

from backtest.bracket import LONG
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, STARTING_CASH
from backtest.run_candlestick_study import ARMS, PATTERN_SPAN, bracket_levels, build_cell
from backtest import candlestick as cs

RISK_PCT = 0.01
CAP_PCT = 0.10
COMM = COMMISSION_BPS / 10_000.0


def load(path: str, start: str = "2013-01-01") -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
    return df.loc[start:]


def stop_series(df: pd.DataFrame, arm, r: float) -> pd.Series:
    _, pattern, direction = arm
    span = PATTERN_SPAN[pattern]
    signal = cs.detect(pattern, df) & cs.context_mask(df, direction, cs.CONTEXT_NONE)
    entry_trigger = signal.shift(1, fill_value=False)
    stop, _ = bracket_levels(df, entry_trigger, direction, span, r)
    return stop


def dd(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def replay(trades, stops, direction, equity0, risk_pct, cap_pct):
    """Replay a ledger under min(risk, cap) sizing. Returns (curve, n_risk_binds)."""
    eq = float(equity0)
    curve = [eq]
    risk_binds = 0
    for t in trades:
        ep = t["entry_price"]
        xp = t["exit_price"]
        d = abs(ep - float(stops.loc[t["entry_date"]]))
        qty_risk = int(risk_pct * eq / d) if d > 0 else 10**12
        qty_cap = int(cap_pct * eq / ep)
        if qty_risk < qty_cap:
            risk_binds += 1
        qty = min(qty_risk, qty_cap)
        if direction == LONG:
            pnl = qty * xp * (1 - COMM) - qty * ep * (1 + COMM)
        else:
            pnl = qty * ep * (1 - COMM) - qty * xp * (1 + COMM)
        eq += pnl
        curve.append(eq)
    return np.array(curve), risk_binds
```

The driver loops `ARMS` at `r=2.0`, calls `build_cell(df, arm, 2.0)` for the all-in ledger
(`allin_equity = STARTING_CASH + cumsum(pnl)`, which already compounds because the engine sized off
live cash), calls `replay(...)` for the live-rule curve, and prints the table above.

## Appendix B: what was not done

- No parameter, config value, or line of trading logic was changed. Nothing under
  `supabase/functions/`, `backtest/`, `strategy/`, or `main.py` was edited.
- No Alpaca call was made. The replay probe reads a local CSV; `main.py backtest` reads yfinance.
- The live 2026-07-31 stop price was not available, so every risk-leg figure is stated as a function
  of `stopDistance` rather than assuming a value.
