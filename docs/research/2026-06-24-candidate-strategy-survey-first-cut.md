# Candidate strategy survey (first cut): low-turnover families on after-tax Calmar

Date: 2026-06-24
Author: Analyst (research-only; no production code or live-bot settings touched)
Issue: #314 (batch #313). Upstream goal: #255 / PR #306. Vol-targeting deferred to #315.

## Question

Does any low-turnover deterministic strategy beat plain 1x SPY buy-and-hold on the
**#255 bar** — out-of-sample after-tax Calmar (CAGR / |max drawdown|), net of cost and tax,
also beating the four dumb baselines and surviving the 2020 + 2022 bear stress? If yes, that
family earns its own implementation spec. If nothing clears, the documented #255 position is to
hold 1x SPY (the operator has separately said: do not deleverage in this batch, so the survey
recommends options, it does not act).

This first cut screens two families. Volatility-targeting (the highest-turnover, weakest
"low-turnover" fit) is the follow-up #315 on the same foundation.

## Method

- **Harness:** the #263 walk-forward machinery (`backtest/walkforward.py`, `_slice_windows`) plus
  this batch's new foundation: a weighted multi-asset simulator (`simulate_from_signal`), per-window
  CAGR + Calmar, and an after-tax tax layer (`backtest/tax.py`).
- **Data:** real yfinance total-return-adjusted daily bars (`auto_adjust=True`). Each family is
  screened over its **own longest-common-window** (bound by the deepest-inception asset it needs),
  and 1x SPY plus the four baselines are recomputed inside that same window so every "beats SPY?"
  verdict is within-window. Windows: GEM 2007-2026 (BIL inception), Faber-single 1993-2026 (SPY),
  GTAA 2006-2026 (DBC inception).
- **Cost:** the existing 0.05% + 0.05% per-side model. **No look-ahead:** signals on completed bars,
  executed next open; monthly families forward-filled so transitions land only at month boundaries.
- **Two tax passes (the #313 decision):** (i) a **full-history** after-tax equity curve, where a
  buy-and-hold lot can qualify for the US long-term rate while churning families realize short-term —
  the **recommendation is ranked on full-history after-tax Calmar**; and (ii) a **per-window** pass
  (each 12-month OOS window simulated independently) as the no-curve-fit **stability gate**. Both US
  (short-term 35% / long-term 18.8%) and DE (flat 26.375%, no holding-period split) are reported,
  carrying the #308 jurisdiction caveat.
- **Params are published defaults, fixed before any result was seen** (no in-sample tuning):
  GEM = 12-month absolute + relative momentum, monthly; Faber = 10-month SMA risk-on/off, monthly;
  GTAA-lite = five sleeves each on their own 10-month SMA, monthly.

## Results (full-history after-tax Calmar, ranked within each family's window)

**GEM dual-momentum** (SPY/EFA/AGG, BIL hurdle) - window 2007-05-30 to 2026-06-23 (~19.1y)

| strategy | Calmar US | Calmar DE | CAGR | max DD | trd/yr | beats SPY? |
|---|---|---|---|---|---|---|
| **GEM family** | **0.14** | 0.14 | +7.2% | -33.7% | 1.73 | **no** |
| 1x SPY (buy & hold) | 0.17 | 0.16 | +10.6% | -55.1% | 0.05 | - |
| baseline: persistence | n/a | n/a | -10.2% | -87.5% | 63.6 | n/a |
| baseline: faber 10mo | 0.17 | 0.15 | +7.4% | -25.8% | 0.84 | no |
| baseline: tsmom 12mo | 0.23 | 0.20 | +9.5% | -33.7% | 0.37 | yes |

Per-window stability (US): GEM median Calmar 0.39 (11/19 windows positive) vs 1x SPY 0.55 (14/20).
Bear: 2020 DD -33.7% / ret -3.4% (worse than SPY's -33.7%/+17.4%); 2022 DD -20.6% (survives vs SPY -24.5%).

**Faber 10-month SMA** (single-asset SPY) - window 1993-01-29 to 2026-06-23 (~33.4y)

| strategy | Calmar US | Calmar DE | CAGR | max DD | trd/yr | beats SPY? |
|---|---|---|---|---|---|---|
| **Faber family** | **0.21** | 0.18 | +8.6% | -25.8% | 0.72 | **yes** |
| 1x SPY (buy & hold) | 0.18 | 0.18 | +10.8% | -55.2% | 0.03 | - |
| baseline: persistence | n/a | n/a | -9.4% | -96.4% | 64.0 | n/a |
| baseline: faber 10mo | 0.21 | 0.18 | +8.6% | -25.8% | 0.72 | yes |
| baseline: tsmom 12mo | 0.24 | 0.22 | +10.4% | -33.7% | 0.27 | yes |

Per-window stability (US): Faber median Calmar 0.67 (22/32 positive) vs 1x SPY 0.85 (25/34).
Bear: 2020 DD -12.4% / ret +17.6% (survives); 2022 DD -23.1% (survives vs SPY -24.5%).

**Faber GTAA-lite** (SPY/EFA/AGG/DBC/VNQ) - window 2006-02-06 to 2026-06-23 (~20.4y)

| strategy | Calmar US | Calmar DE | CAGR | max DD | trd/yr | beats SPY? |
|---|---|---|---|---|---|---|
| **GTAA family** | **0.18** | 0.16 | +4.3% | -15.3% | 14.3 | **no** |
| 1x SPY (buy & hold) | 0.18 | 0.17 | +11.0% | -55.2% | 0.05 | - |
| baseline: persistence | n/a | n/a | -9.2% | -87.5% | 63.4 | n/a |
| baseline: faber 10mo | 0.17 | 0.15 | +7.2% | -25.8% | 0.83 | no |
| baseline: tsmom 12mo | 0.21 | 0.19 | +8.9% | -33.7% | 0.39 | yes |

Per-window stability (US): GTAA median Calmar 0.48 (12/21 positive) vs 1x SPY 0.85 (15/21).
Bear: 2020 DD -6.7% / ret +6.3% (survives); 2022 DD -7.7% (survives vs SPY -24.5%).

(`persistence` shows n/a Calmar because its high-churn after-tax curve goes non-positive under the
no-loss-credit tax model - capital ruin, recorded honestly rather than crashed.)

## Recommendation: nothing clears the #255 bar

A family clears only if it beats 1x SPY on full-history after-tax Calmar **and** beats the four dumb
baselines **and** survives the bear stress. Applying that rule to the numbers:

- **GEM** - after-tax Calmar 0.14 < SPY 0.17. Fails at the first gate. **Does not clear.**
- **Faber single** - 0.21 > SPY 0.18 (beats SPY, and cuts max drawdown from -55% to -26%), **but**
  loses to the tsmom-12mo baseline (0.24) and falls below SPY on the per-window stability gate
  (0.67 vs 0.85). **Does not clear.**
- **GTAA-lite** - 0.18 ties SPY 0.18, with high turnover (14 trades/yr) and the weakest stability
  (0.48 vs 0.85). **Does not clear.**

**No surveyed family clears.** This is the informative negative result #255 was built to surface.

Three honest reads of why:

1. **The trend families buy drawdown relief at a steep return cost.** Faber cuts max drawdown to -26%
   (from SPY's -55%) and GTAA to -15%, which is real and large. But they give up so much CAGR (Faber
   +8.6% vs +10.8%; GTAA +4.3% vs +11.0%) that the risk-adjusted ratio lands at or below SPY. After
   tax, the timing trades' realized gains are taxed along the way, which erodes the edge further.
2. **The strongest single thing in the survey is a dumb baseline.** Simple 12-month time-series
   momentum on SPY (tsmom) beats SPY on after-tax Calmar in all three windows (0.23-0.24 vs ~0.18).
   But it is the floor a real candidate must exceed, not a cleared candidate, and its margin over SPY
   is modest. It is worth carrying into the second cut, not shipping.
3. **US vs DE barely separates here.** Because buy-and-hold realizes mostly long-term in both regimes
   and the active families' edge is small, the tax-deferral advantage is a fraction of a Calmar point,
   not a decider. The jurisdiction question stays open for a future build, but it does not change this
   verdict.

### Options for the operator (the survey recommends, it does not act)

The operator's locked decision is **do not deleverage in this batch**, so these are laid out with
evidence, not prescribed:

- **Keep the current 3x UPRO regime bot (status quo).** No evidence-backed 1x replacement emerged.
  The live bot is unchanged regardless; this survey shipped nothing.
- **If drawdown comfort is the real goal:** a Faber-style 10-month trend overlay cut SPY's worst
  drawdown roughly in half (and a 2-of-3 cut for GTAA). It does **not** beat SPY on after-tax Calmar,
  so it is a drawdown-comfort choice, not a return-improvement one - an honest trade, not a free lunch.
- **The #255 floor (1x SPY)** remains the documented fallback, which the operator has declined for now.

### Next

- **Second cut (#315):** add volatility-targeting on this foundation, and carry **tsmom-12mo** in as a
  first-class candidate (it was the strongest baseline). Neither has cleared anything yet; this is the
  next screen, not a recommendation to build.
- Nothing here ships. Any future survivor gets its own brainstorm -> spec -> plan. Invariants #1
  (one decision rule) and #2 (no LLM in the trading path) apply at that implement-time, not to this
  research screen, which lives entirely in `backtest/` and is never imported by `supabase/functions/`.

## Caveats

- **Faithful standard params, not tuned.** GEM/Faber/GTAA use published defaults fixed before any
  result was seen. No grid search. A different parameter set would move the absolute numbers; the
  qualitative verdict (drawdown-relief-at-a-return-cost, none clearing after-tax Calmar) is what the
  screen establishes.
- **Per-family windows are not cross-comparable.** A Calmar from a 2007-start window is not the same
  as one from 1993; each "beats SPY?" verdict is strictly within its own window, which is why the SPY
  and baseline rows differ per family block.
- **1x screen.** All rows are unleveraged, so this compares risk-adjusted shape, not the absolute
  return of the leveraged incumbent. A leveraged version of any signal would re-introduce the drawdown
  problem and is a separate future question.

Reproduce: `python3 -m backtest.run_candidate_survey` (fetches live yfinance data; a pinned past
window reproduces within rounding).
