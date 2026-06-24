# Candidate strategy survey (second cut): volatility-targeting on after-tax Calmar

Date: 2026-06-24
Author: Analyst role (research-only; no production code or live-bot settings touched).
Provenance: the survey run and writeup were completed by the lead session as a fallback after
repeated agent-dispatch timeouts; the branch is independently gated by the tester + reviewer.
Issue: #315 (batch #317). Companion to the first cut
(`docs/research/2026-06-24-candidate-strategy-survey-first-cut.md`, #314). Upstream goal: #255 / PR #306.

## Question

Same bar as the first cut: does **volatility-targeting** (the last named family, and the
highest-turnover, weakest "low-turnover" fit) beat plain 1x SPY buy-and-hold on out-of-sample
**after-tax Calmar** (CAGR / |max drawdown|), net of cost and tax, while also beating the dumb
baselines and surviving the 2020 + 2022 bear stress? The first cut screened GEM dual-momentum and
Faber MA-timing (single-asset + GTAA-lite); none cleared. This cut adds the last family so #255's
survey can conclude.

## Method

Identical foundation and conventions to the first cut: the same weighted simulator
(`simulate_from_signal`), per-window CAGR + Calmar, the `backtest/tax.py` US/DE after-tax layer, the
0.05% + 0.05% per-side cost model, no look-ahead (signal on the completed bar, executed next open),
full-history after-tax Calmar as the ranking basis, the per-window 12-month OOS pass as the
stability gate, and the 2020 / 2022 bear stress. Real yfinance total-return-adjusted daily bars;
SPY-only window 1993-01-29 to 2026-06-23 (~33.4y). Reproduce with
`python3 -m backtest.run_candidate_survey`.

The one new family:

- **Vol-target 10% (single-asset SPY):** daily target weight = `min(target_vol / realized_vol, 1.0)`,
  `target_vol = 10%` annualized, `realized_vol` from a 20-trading-day rolling window
  (`pct_change().rolling(20).std(ddof=1) * sqrt(252)`), remainder in cash, no leverage (cap 1.0).
  Published defaults, fixed before any result was seen (no in-sample tuning).

## Results

Vol-target vs 1x SPY + the dumb baselines, full window 1993-01-29 to 2026-06-23 (~33.4y):

| strategy | Calmar US | Calmar DE | CAGR | max DD | trd/yr | >1x SPY? |
|---|---|---|---|---|---|---|
| **Vol-target 10% (SPY)** | **n/a** | **n/a** | +7.1% | -34.7% | **93.7** | n/a |
| 1x SPY (buy & hold) | 0.18 | 0.18 | +10.8% | -55.2% | 0.03 | -- |
| baseline: persistence | n/a | n/a | -9.4% | -96.4% | 64.0 | n/a |
| baseline: faber 10mo | 0.21 | 0.18 | +8.6% | -25.8% | 0.72 | YES |
| baseline: tsmom 12mo | 0.24 | 0.22 | +10.4% | -33.7% | 0.27 | YES |

`Calmar US` / `Calmar DE` are **after-tax**; `CAGR` / `max DD` are pre-tax. `n/a` = the after-tax
curve went non-positive (see Findings 3).

- **Per-window after-tax (US) stability gate** (12-month OOS windows): vol-target median Calmar
  **-0.54** (11 / 34 windows positive) vs 1x SPY **0.85** (25 / 34 positive).
- **Bear stress** (max DD / window return vs 1x SPY same window): 2020 COVID vol-target
  -11.8% / +9.2% (SPY -33.7% / +17.4%) -> SURVIVES; 2022 bear vol-target -13.3% / -10.9%
  (SPY -24.5% / -18.7%) -> SURVIVES.

## Findings

1. **Pre-tax, vol-targeting is at parity with SPY, marginally ahead.** Pre-tax Calmar:
   vol-target 7.1% / 34.7% = **0.205** vs SPY 10.8% / 55.2% = **0.196**. It cuts drawdown
   (-34.7% vs -55.2%) more than it cuts return, so before tax it has a slim 0.009 edge. The #255 bar
   is **after-tax**, and that is where it fails; a marginal pre-tax edge does not clear an after-tax
   bar.

2. **After tax, SPY wins on structural tax deferral, and it is decisive.** This is the load-bearing
   reason, independent of any tax-model quirk: a strategy trading **93.7x/year** realizes gains at
   the short-term rate continuously, while 1x SPY buy-and-hold (0.03 trades/yr) defers its entire
   gain to a single long-term realization. That deferral gap is large and dominates the 0.009 pre-tax
   Calmar edge under any reasonable tax model. After tax, vol-target clears the bar on zero computed
   bases: US n/a, DE n/a, per-window median -0.54 vs SPY 0.85.

3. **The three after-tax signals are NOT independent confirmations; they share one tax model.** US,
   DE, and the per-window pass all run through the **same no-loss-credit tax layer**: it taxes every
   winning exit and credits no losing exit. That is **punitive for a high-churn strategy** and drives
   the US and DE full-history after-tax curves non-positive; `_curve_metrics` reports CAGR / Calmar
   as `n/a` with max DD clamped to -100% ("ruin") rather than crashing. Real US (short-term loss
   offset) and DE (Verlustverrechnung) both credit offsetting losses, so under a loss-crediting model
   vol-target would **underperform, not ruin**: the *sign* of the verdict is robust (it rests on the
   structural deferral gap in Finding 2), but the *magnitude* ("ruin", and the per-window -0.54) is
   exaggerated by this model. **Consequence: the no-loss-credit model cannot fairly rank ANY
   high-turnover candidate; a loss-crediting tax layer is a prerequisite before screening
   churn-heavy strategies.** (Flagged for batch #317 as a foundation limitation; not fixed here.)

4. **The lot-accounting artifact is immaterial to this verdict.** The foundation's
   `_simulate_weighted` keeps a single lot anchor for a continuous strictly-positive weight: partial
   trims book against the original `entry_date` AND original cost basis (pinned by a new regression
   test, `tests/test_weighted_simulator.py`). This has **two opposing tax effects**, easily
   conflated: (a) the stale **entry-date** misclassifies late trims as US long-term, lowering the US
   rate, which *inflates* US after-tax Calmar (US-only; DE has no holding-period split); (b) the
   stale **cost basis** books later, higher-priced adds at the original lower basis, *overstating*
   the realized gain so more tax is paid, which *deflates* both US and DE after-tax. The net US
   direction is therefore ambiguous; DE is unambiguously deflated by (b). Either way it is
   **immaterial here**: the US and DE after-tax curves are non-positive regardless (no positive
   Calmar to inflate), the per-window pass resets each window (no single anchor), and the verdict
   rests on the artifact-independent structural deferral gap (Finding 2). Because (a) and (b) push
   opposite ways on US, the artifact is not a clean "flattering" bias; it needs a real fix before any
   future continuous-weight candidate can be ranked on US after-tax Calmar (flagged on #317).

5. **Drawdown was cut, as designed** (-34.7% vs SPY -55.2%; survives both 2020 and 2022), but cutting
   drawdown by near-daily rebalancing is exactly the after-tax-expensive pattern #255 predicts will
   not beat SPY, and it does not.

## Verdict

**Vol-targeting does not clear the #255 after-tax Calmar bar.** Pre-tax it is at parity with SPY
(marginally ahead, 0.205 vs 0.196); after tax, SPY wins decisively on structural tax deferral: a
93.7x/year churner realizes short-term continuously while buy-and-hold defers to a single long-term
realization, a gap that dominates the slim pre-tax edge under any reasonable tax model. It joins GEM
dual-momentum, Faber, and GTAA-lite from the first cut: **nothing in the survey beats 1x SPY
buy-and-hold after tax.** The named families are now exhausted; #255's survey is complete and the
answer is no. The strongest single signal across both cuts remains the dumb **tsmom-12mo** baseline
(after-tax Calmar 0.24 US / 0.22 DE), not any of the screened candidates.

Research only. No live-bot change; the operator's "do not deleverage" stands; the live 3x UPRO bot
is untouched. Next-step options for the #255 decision (whether to evaluate tsmom-12mo itself as a
first-class candidate, or to accept 1x SPY as the documented floor) are a separate operator
decision, not actioned here.
