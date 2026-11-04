# Research round `etf-daily-r1`: multi-ETF momentum on a cross-asset basket -- verdict

**Pre-registration (frozen, merged first):** `docs/research/2026-11-03-etf-daily-r1-preregistration.md` (freeze PR #754, merged 2026-11-03 as commit `7d829a7`). **Round issue:** #737. **Candidates:** #750 `etf-daily-r1-tsmom-basket`, #751 `etf-daily-r1-xs-momentum`. **Results PR:** #755.
**Date:** 2026-11-03. **Author:** Claude Code research-round session (research-only; `CLAUDE_AGENT_NO_BROKER=1` in every shell; no broker call, no production code touched). **Branch:** `docs/etf-daily-r1-results`.

Every number below comes from the committed result files (`docs/research/pipeline/<candidate_id>/development_result.json` and `holdout_result.json`), the committed development returns files, and one run of `docs/research/2026-11-03-etf-daily-r1-study/evaluate_round.py` per candidate (its outputs `<candidate_id>-verdict.json` and `<candidate_id>-scorecard.md` are committed beside it). Nothing was re-picked or re-run after a holdout number was seen; both holdouts ran exactly once.

CLAUDE.md "Architectural invariants" apply by reference: this document changes nothing live and promotes nothing.

---

## 1. Verdict in one line

**Both candidates fail the five-criterion bar and are recorded as `NO_GO` at PROMOTABLE power** (n_w = 14 development calendar years, above the n_w = 13 promotion bar). Neither beats the vol-targeted SPY benchmark on median development-year after-tax Calmar, and neither survives the luck tests (DSR 0.88 and 0.85 against the 0.95 threshold over the programme's 19 stored trials; bootstrap uplift intervals that include zero). The time-series candidate also loses money on the holdout. The cross-sectional candidate holds up on the holdout (positive, inside the drawdown cap) but does not add anything the vol-targeted benchmark did not already give.

## 2. What ran

- Data: 15 tickers through `load_daily_bars`, data start 2007-05-30 (first common bar; BIL's inception), master index = SPY trading days, 0 missing open or close rows for any ticker on that index. Development 2007-05-30 to 2021-12-31: 3,676 rows, 14 scored calendar years (2008 to 2021). Holdout 2022-01-03 to 2026-11-03: 1,214 rows, 4 scored years (2022 to 2025); 2026 is a partial year and is not scored.
- Grid: exactly the frozen 8 + 6 = 14 configurations, all stored in `docs/research/pipeline/trials.json` (programme store 5 to 19). Selection by highest development `sharpe_daily`, as frozen.
- Benchmark: SPY through the same `inverse_vol_weights` / `vol_target_weights` chain (10% target, 60-day window, gross cap 1.0), same simulator, costs and cash series. Identical for both candidates (shared code and data): development CAGR 7.3%, max drawdown 22.3%, annualised Sharpe 0.74, median after-tax year Calmar 0.96.
- Gate inputs as frozen: `pbo_n_splits=16`, `bootstrap_block_length=2`, `bootstrap_n_boot=1000`, `bootstrap_seed=0`, `bootstrap_alpha=0.05`, `dsr_sr_benchmark=0.0`; `perf_matrix` (3676, N); uplift vector of 14 per-year pre-tax Calmar differences (no year dropped for either candidate).
- Parity caveat: pre-registration section 10.1 (8 of 15 tickers fail the `run_etf_parity` thresholds because of March 2020 closes on the Alpaca side and cent rounding on low-priced ETFs; the research data are yfinance's official closes and are unaffected).

## 3. Candidate #750 `etf-daily-r1-tsmom-basket` (time-series momentum, N = 8)

Selected: `etf-daily-r1-tsmom-basket-04`, L = 63, `long_flat`. Development Sharpe of the 8 trials ranged from -0.10 (L = 21 `long_short`) to 0.80 (the selected); every `long_short` variant was weaker than its `long_flat` twin.

| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 5.1% | -0.5% |
| CAGR after German tax | 3.9% | -1.1% |
| Max drawdown, and its dates | 17.0% (2015-04-24 to 2016-01-11) | 18.7% (2022-04-18 to 2023-11-16) |
| Calmar (return / max drawdown) | 0.30 | -0.02 |
| Sharpe; target and realised annualised volatility | Sharpe 0.80; target 10.0%, realised 6.4% | Sharpe -0.03; target 10.0%, realised 7.2% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2015 -10.4%; 2008 5.2%; 2020 3.6% | worst 2022 -12.4%; 2022 -12.4% |
| Round trips per year, average holding days, max share of time in one ETF | 85.7 round trips/yr; 37.2 avg holding days; 74.5% max share in one ETF | 108.4 round trips/yr; 25.6 avg holding days; 69.7% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 1.6%/yr (borrow 0.0%/yr); double cost: CAGR 3.5%, max DD 19.5%, Calmar 0.18 | cost drag 2.8%/yr (borrow 0.0%/yr); double cost: CAGR -3.1%, max DD 22.3%, Calmar -0.14 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 0.79 vs 0.96 (n_w=14) | benchmark Calmar 0.58, CAGR 7.8%, max DD 13.6%; median after-tax year Calmar 0.32 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.8843 over N=19 trials; PBO 0.2037; uplift CI [-1.1400, 1.0993]; dsr 0.8843 < threshold 0.95; bootstrap ci_low -1.140015 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 6.6%, max DD 20.9%, Calmar 0.32 | CAGR -2.4%, max DD 24.4%, Calmar -0.10 |

**Verdict: FAIL** (2 of 5 criteria pass)

- drawdown: pass (development 0.1698; holdout 0.1872; cap 0.2000)
- beats_benchmark: fail (median window Calmar candidate 0.7883 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.8843 over N=19 trials; PBO 0.2037; uplift CI [-1.1400, 1.0993]; dsr 0.8843 < threshold 0.95; bootstrap ci_low -1.140015 <= 0)
- holdout: fail (holdout CAGR -0.0046 (need > 0); max drawdown 0.1872)
- activity: pass (round trips per year 85.7436 (min 20); max time share in one ETF 0.7454 (max 0.9000))

**Reading.** The rule did what trend following is supposed to do in 2008 (+5.2% while the benchmark's year Calmar was -0.88) and 2011, and it kept every drawdown under the cap. But it bought that protection with return: 5.1% a year against the benchmark's 7.3% on the same risk budget, with realised volatility only 6.4% because a 1.0 gross cap on a calm, mostly-flat basket cannot reach the 10% target. The holdout is the decisive miss: -0.5% a year over 2022 to 2026 while vol-targeted SPY made 7.8%, and 2022 (the trend-following showcase year in the CTA indices) was its worst year at -12.4%. Cost drag of 1.6% a year on 86 round trips is a material share of the gap; at double cost the development Calmar halves. The per-year uplift vector swings from +3.9 to -5.1, so the bootstrap interval is wide and includes zero.

**Continuity line (not a gate):** median development-year after-tax Calmar 0.79 vs the repo's older 1.3085 bar: below it.

**Recommendation (mine, not the renderer's): reject.** Not a retest: the test ran at full power (n_w = 14), the holdout has been seen, and the failure is in the sign of the holdout and the size of the benchmark gap, not in the sample size. Ledger row: `tsmom_timeseries` / `daily` / `ETF_BASKET_XA14`, `NO_GO`, `PROMOTABLE`, 8 cells.

**What would change the recommendation:** a pre-registered variant with a materially different economic content, for example a basket of futures-like exposures with true breadth (the ETF basket's 14 names are dominated by a few correlated risk-on sleeves) or a long-short construction that is not a plain sign rule, tested as a new candidate without a holdout under the Phase 4 (h) rule. Re-running the same grid on more data would not change the sign of the 2022 to 2026 result.

## 4. Candidate #751 `etf-daily-r1-xs-momentum` (cross-sectional momentum, N = 6)

Selected: `etf-daily-r1-xs-momentum-03`, L = 126, `long_only` (skip 21, top 4 of 14, weekly ranking). Development Sharpe of the 6 trials ranged from 0.09 (L = 252 `long_short`) to 0.76 (the selected); every `long_short` variant was weaker than its `long_only` twin, and three unselected trials sat at or above the 20% drawdown cap.

| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 7.0% | 5.0% |
| CAGR after German tax | 5.8% | 3.3% |
| Max drawdown, and its dates | 16.3% (2008-03-14 to 2008-10-30) | 10.6% (2024-10-18 to 2025-04-08) |
| Calmar (return / max drawdown) | 0.43 | 0.47 |
| Sharpe; target and realised annualised volatility | Sharpe 0.76; target 10.0%, realised 9.6% | Sharpe 0.56; target 10.0%, realised 9.6% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2015 -7.4%; 2008 0.0%; 2020 10.1% | worst 2022 -5.5%; 2022 -5.5% |
| Round trips per year, average holding days, max share of time in one ETF | 25.9 round trips/yr; 51.8 avg holding days; 58.5% max share in one ETF | 30.0 round trips/yr; 53.4 avg holding days; 64.7% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 0.8%/yr (borrow 0.0%/yr); double cost: CAGR 6.2%, max DD 16.8%, Calmar 0.37 | cost drag 0.8%/yr (borrow 0.0%/yr); double cost: CAGR 4.2%, max DD 11.1%, Calmar 0.38 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 0.70 vs 0.96 (n_w=14) | benchmark Calmar 0.58, CAGR 7.8%, max DD 13.6%; median after-tax year Calmar 0.85 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.8496 over N=19 trials; PBO 0.0869; uplift CI [-1.0565, 0.1874]; dsr 0.8496 < threshold 0.95; bootstrap ci_low -1.056466 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 8.0%, max DD 17.8%, Calmar 0.45 | CAGR 4.5%, max DD 13.6%, Calmar 0.33 |

**Verdict: FAIL** (3 of 5 criteria pass)

- drawdown: pass (development 0.1626; holdout 0.1061; cap 0.2000)
- beats_benchmark: fail (median window Calmar candidate 0.6978 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.8496 over N=19 trials; PBO 0.0869; uplift CI [-1.0565, 0.1874]; dsr 0.8496 < threshold 0.95; bootstrap ci_low -1.056466 <= 0)
- holdout: pass (holdout CAGR 0.0503 (need > 0); max drawdown 0.1061)
- activity: pass (round trips per year 25.9081 (min 20); max time share in one ETF 0.5851 (max 0.9000))

**Reading.** This is the better of the two and a more honest failure. It is cheap to run (26 round trips a year, 0.8% cost drag, the double-cost line barely moves), it reaches its volatility target (9.6% realised), it kept 2008 flat, and it made 5.0% a year on the holdout with a 10.6% worst drawdown, inside the cap, with its worst year (2022) at -5.5% against the benchmark's much larger 2022 loss. What it does not do is beat the benchmark: in 9 of 14 development years its Calmar sat below vol-targeted SPY's, the bootstrap interval on the uplift is [-1.06, +0.19], and the PBO of 0.09 says the selection was not a lucky pick so much as the whole grid being a little short of the bar. The DSR of 0.85 reflects a modest Sharpe (0.76 annualised) deflated by 19 stored trials.

**Continuity line (not a gate):** median development-year after-tax Calmar 0.70 vs the repo's older 1.3085 bar: below it.

**Recommendation (mine, not the renderer's): reject.** Not a retest for the same reasons as #750: full power, holdout seen, and the gap to the benchmark is a level, not a noise, problem. Ledger row: `cross_sectional_rv` / `daily` / `ETF_BASKET_XA14`, `NO_GO`, `PROMOTABLE`, 6 cells.

**What would change the recommendation:** evidence that the right comparison for a diversifier is not stand-alone Calmar against vol-targeted SPY (roadmap C.2b raised exactly this question and the operator confirmed the stand-alone bar by merging #754). A pre-registered blend test (candidate plus SPY under one risk budget, with a positive stand-alone mean still required) would be a new candidate and a new pipeline criterion, both outside this round. Nothing in this round's numbers suggests the rule has a stand-alone edge over the benchmark.

## 5. Round summary and multiplicity

| Candidate | N | Selected | Criteria passed | Verdict | Power | Recommendation |
|---|---|---|---|---|---|---|
| #750 `etf-daily-r1-tsmom-basket` | 8 | `-04` (L=63, long_flat) | 2 of 5 (drawdown, activity) | NO_GO | PROMOTABLE | reject |
| #751 `etf-daily-r1-xs-momentum` | 6 | `-03` (L=126, long_only) | 3 of 5 (drawdown, holdout, activity) | NO_GO | PROMOTABLE | reject |

- Programme trial store: 19 trials after this round (5 backfilled + 14). The DSR of any later candidate in the daily-allocation space deflates against these 19.
- Ledger: two `NO_GO` rows added to `backtest/tested_cells.py` (sources: this document). Family multiplicity after this round: `tsmom_timeseries` 10 run cells, `cross_sectional_rv` 6. The `cross_sectional_rv` row is the first ledger record for a family listed in `backtest/weekly_review.py::UNTESTED_CANDIDATES`; per the skill, the candidate-list update is raised on #737 as its own issue and is not made inside this round.
- Both long/short constructions underperformed their long-only twins at every lookback, in both families. On this basket over 2007 to 2021 the short side cost return without buying drawdown protection (the long-only variants already met the 20% cap).

## 6. Honest notes

- The analysts (two dispatches of the `analyst` agent) implemented the frozen text and reported no deviation. Two interpretation details are recorded in the runner docstrings: the last row of a series counts as a ranking day for #751 (no effect on equity, since its signal would fill on a row that does not exist), and a ranking day's row carries the newly set signal (the only reading consistent with "set at close T, filled at T+1").
- Section 10 of the study scripts' shared module emits a pandas `FutureWarning` on `pct_change` (default fill); it has no numeric effect on this gap-free data.
- The selected #750 run shows a small financing charge (603 currency units over 14.6 years at gross cap 1.0) from cash drifting slightly negative between band-triggered rebalances; the simulator documents this and the amount is immaterial.
- The holdout period ends 2026-11-03, the run date; its scorecard scores 2022 to 2025 as full years.
- The 2026-10-23 design spec's worry that a 1.0 gross cap makes the 10% vol target a ceiling is visible in #750 (6.4% realised) and not in #751 (9.6%), so the two candidates were compared against the benchmark at different realised risk; the bar (median year Calmar) is risk-adjusted, which is why the comparison is still fair.

## 7. Reproduction

From the worktree root, with `CLAUDE_AGENT_NO_BROKER=1` and a venv holding `requirements.txt`:

```
venv/bin/python3 docs/research/2026-11-03-etf-daily-r1-study/run_tsmom_basket.py --phase development   # already run; re-running refuses duplicate trial ids
venv/bin/python3 docs/research/2026-11-03-etf-daily-r1-study/run_xs_momentum.py --phase development     # same
venv/bin/python3 docs/research/2026-11-03-etf-daily-r1-study/evaluate_round.py --candidate etf-daily-r1-tsmom-basket --out <dir>
venv/bin/python3 docs/research/2026-11-03-etf-daily-r1-study/evaluate_round.py --candidate etf-daily-r1-xs-momentum --out <dir>
```

The holdout commands (`--phase holdout --i-am-the-orchestrator`) were run once each from the orchestrating session and are refused by the lock in `backtest/etf_data.py` from now on.
