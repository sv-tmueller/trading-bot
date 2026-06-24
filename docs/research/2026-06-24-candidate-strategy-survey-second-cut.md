# Candidate strategy survey (second cut): volatility-targeting on after-tax Calmar

Date: 2026-06-24
Author: Analyst (research-only; no production code or live-bot settings touched)
Issue: #315 (batch #317). Companion to the first cut
(`docs/research/2026-06-24-candidate-strategy-survey-first-cut.md`, #314). Upstream goal: #255 / PR #306.

## Question

Same bar as the first cut: does **volatility-targeting** — the last named low-turnover family — beat
plain 1x SPY buy-and-hold on out-of-sample **after-tax Calmar** (CAGR / |max drawdown|), net of cost
and tax, while also beating the four dumb baselines and surviving the 2020 + 2022 bear stress? The
first cut screened GEM dual-momentum and Faber MA-timing (single-asset + GTAA-lite); none cleared.
This cut adds the last family so #255's low-turnover survey can conclude.

## Method

Identical foundation and conventions to the first cut: the same weighted simulator
(`simulate_from_signal`), per-window CAGR + Calmar, the `backtest/tax.py` US/DE after-tax layer, the
0.05% + 0.05% per-side cost model, no look-ahead (signal on the completed bar, executed next open),
full-history after-tax Calmar as the ranking basis, the per-window 12-month OOS pass as the
stability gate, and the 2020 / 2022 bear stress. Real yfinance total-return-adjusted daily bars;
SPY-only window 1993-01-29 -> 2026-06-23 (~33.4y). Reproduce with
`python3 -m backtest.run_candidate_survey`.

The one new family:

- **Vol-target 10% (single-asset SPY):** daily target weight = `min(target_vol / realized_vol, 1.0)`,
  `target_vol = 10%` annualized, `realized_vol` from a 20-trading-day rolling window
  (`pct_change().rolling(20).std(ddof=1) * sqrt(252)`), remainder in cash, no leverage (cap 1.0).
  Published defaults, fixed before any result was seen (no in-sample tuning).

## Results

Vol-target vs 1x SPY + the dumb baselines, full window 1993-01-29 -> 2026-06-23 (~33.4y):

| strategy | Calmar US | Calmar DE | CAGR | max DD | trd/yr | >1x SPY? |
|---|---|---|---|---|---|---|
| **Vol-target 10% (SPY)** | **n/a** | **n/a** | +7.1% | -34.7% | **93.7** | n/a |
| 1x SPY (buy & hold) | 0.18 | 0.18 | +10.8% | -55.2% | 0.03 | -- |
| baseline: persistence | n/a | n/a | -9.4% | -96.4% | 64.0 | n/a |
| baseline: faber 10mo | 0.21 | 0.18 | +8.6% | -25.8% | 0.72 | YES |
| baseline: tsmom 12mo | 0.24 | 0.22 | +10.4% | -33.7% | 0.27 | YES |

`Calmar US` / `Calmar DE` are **after-tax**; `CAGR` / `max DD` are pre-tax. `n/a` = the after-tax
curve went non-positive (see Findings 2).

- **Per-window after-tax (US) stability gate** (12-month OOS windows): vol-target median Calmar
  **-0.54** (11 / 34 windows positive) vs 1x SPY **0.85** (25 / 34 positive).
- **Bear stress** (max DD / window return vs 1x SPY same window): 2020 COVID vol-target
  -11.8% / +9.2% (SPY -33.7% / +17.4%) -> SURVIVES; 2022 bear vol-target -13.3% / -10.9%
  (SPY -24.5% / -18.7%) -> SURVIVES.

## Findings

1. **Vol-targeting does not clear the #255 bar on any basis.** After-tax Calmar US = n/a, DE = n/a,
   per-window median = -0.54 — all below 1x SPY (0.18 / 0.18 / 0.85). It is also beaten outright by
   the dumb tsmom-12mo and faber-10mo baselines, repeating the first cut's pattern: the strongest
   single signal in the set is a dumb baseline, not a screened "candidate."

2. **The `n/a` is after-tax ruin, not a missing number.** The ~93.7 trades/yr churn, taxed at each
   winning exit with **no credit for losing exits** (the survey's tax model), drives both the US and
   DE after-tax equity curves non-positive; `_curve_metrics` reports CAGR / Calmar as `n/a` with max
   DD clamped to -100% (capital ruined) rather than crash. **Honest caveat:** the no-loss-credit
   model is **punitive for a high-churn strategy** — real US (short-term loss offset) and DE
   (Verlustverrechnung) both credit offsetting losses, so under a loss-crediting model vol-target
   would *underperform* rather than *ruin*. The conclusion is unchanged: it does not beat SPY. Even
   **pre-tax** its Calmar is approximately 0.20 (7.1% / 34.7%) on a lower return than SPY (10.8%) —
   there is no edge to tax away in the first place.

3. **The lot-accounting artifact is immaterial to this verdict.** The foundation's
   `_simulate_weighted` keeps a single lot anchor for a continuous strictly-positive weight (partial
   trims book against the original `entry_date` / cost basis — pinned by a new regression test on
   this branch, `tests/test_weighted_simulator.py`). That would *inflate* a continuous strategy's
   full-history **US** after-tax Calmar by classifying late trims long-term against a stale basis.
   Here there is no positive after-tax Calmar to inflate, and the **artifact-free gates fail
   independently**: DE (flat rate, no holding-period split) is also ruined, and the per-window pass
   (each window an independent simulation, holds < 365 days) gives -0.54. The artifact remains a real
   foundation limitation for any *future* continuous-weight candidate that survives after tax —
   flagged for a separate operator decision on batch #317, not acted on here.

4. **Drawdown was cut, as designed** (-34.7% vs SPY -55.2%; survives both 2020 and 2022), but cutting
   drawdown by near-daily rebalancing is exactly the after-tax-expensive pattern #255 predicts will
   not beat SPY — and it does not.

## Verdict

**Vol-targeting does not clear the #255 after-tax Calmar bar.** It joins GEM dual-momentum, Faber,
and GTAA-lite from the first cut: **nothing in the low-turnover survey beats 1x SPY buy-and-hold
after tax.** The named low-turnover families are now exhausted; #255's survey is complete and the
answer is no. The strongest single signal across both cuts remains the dumb **tsmom-12mo** baseline
(after-tax Calmar 0.24 US / 0.22 DE), not any of the screened candidates.

Research only. No live-bot change; the operator's "do not deleverage" stands; the live 3x UPRO bot
is untouched. Next-step options for the #255 decision (whether to evaluate tsmom-12mo itself as a
first-class candidate, or to accept 1x SPY as the documented floor) are a separate operator
decision, not actioned here.
