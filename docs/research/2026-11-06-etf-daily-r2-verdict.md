# Research round `etf-daily-r2`: remaining daily-allocation landscape on the 14-ETF basket -- verdict

**Pre-registration (frozen, merged first):** `docs/research/2026-11-06-etf-daily-r2-preregistration.md` (freeze PR #767, merged 2026-11-06 as commit `f598f4d`). **Round issue:** #762. **Candidates (operator pick, STOP 1):** #763 `etf-daily-r2-vol-regime-gating`, #764 `etf-daily-r2-donchian-trend-breakout`. Unpicked (not run, issues open): #765, #766. **Results PR:** #768.
**Date:** 2026-11-06. **Author:** Claude Code research-round session (research-only; `CLAUDE_AGENT_NO_BROKER=1` in every shell; no broker call, no production code touched). **Branch:** `docs/etf-daily-r2-results`.

Every number below comes from the committed result files (`docs/research/pipeline/<candidate_id>/development_result.json` and `holdout_result.json`), the committed development returns files, and one run of `docs/research/2026-11-06-etf-daily-r2-study/evaluate_round.py` per candidate (its outputs `<candidate_id>-verdict.json` and `<candidate_id>-scorecard.md` are committed beside it). Nothing was re-picked or re-run after a holdout number was seen; both holdouts ran exactly once.

CLAUDE.md "Architectural invariants" apply by reference: this document changes nothing live and promotes nothing.

---

## 1. Verdict in one line

**Both candidates fail the five-criterion bar and are recorded as `NO_GO` at PROMOTABLE power** (n_w = 14 development calendar years, above the n_w = 13 promotion bar). Both clear the drawdown cap in both periods, both beat the vol-targeted SPY benchmark on median development-year Calmar (the first candidates in the programme to do so), and both survive the holdout (positive CAGR, drawdown inside the cap). Both fail the luck leg and the activity criterion. #763's luck failure is narrow (DSR and PBO pass; only the bootstrap uplift CI includes zero) while #764's is broad (DSR 0.56, PBO 0.71); both rules trade so rarely that neither reaches the 20 round trips/yr activity floor.

## 2. What ran

- Data: 15 tickers through `load_daily_bars`, data start 2007-05-30 (first common bar; BIL's inception), master index = SPY trading days, 0 missing close rows for any ticker on that index. Development 2007-05-30 to 2021-12-31: 3,676 rows, 14 scored calendar years (2008 to 2021). Holdout 2022-01-03 to 2026-11-06: 1,217 rows, 4 scored years (2022 to 2025); 2026 is a partial year and is not scored.
- Grid: exactly the frozen 12 + 6 = 18 configurations, all stored in `docs/research/pipeline/trials.json` (programme store 19 to 37; the DSR of any later candidate deflates against these 37). Selection by highest development `sharpe_daily`, as frozen.
- Benchmark: SPY through the same `inverse_vol_weights` / `vol_target_weights` chain (10% target, 60-day window, gross cap 1.0), same simulator, costs and cash series. Identical for both candidates (shared code and data): development CAGR 7.3%, max drawdown 22.3%, annualised Sharpe 0.74, median after-tax year Calmar 0.96; holdout CAGR 7.3%, max drawdown 13.6%, median after-tax year Calmar 1.17 (n_w = 4).
- Gate inputs as frozen: `pbo_n_splits=16`, `bootstrap_block_length=2`, `bootstrap_n_boot=1000`, `bootstrap_seed=0`, `bootstrap_alpha=0.05`, `dsr_sr_benchmark=0.0`; `perf_matrix` (3676, N); uplift vector of 14 per-year pre-tax Calmar differences (no year dropped for either candidate).
- Parity caveat: pre-registration section 10 (3 of 15 tickers fail the `run_etf_parity` thresholds after #757's suspect-window gating and cent allowance; the same March-2020 Alpaca-side closes and cent-rounding causes r1 section 10.1 analysed and the operator adjudicated; the research data are yfinance's official closes and are unaffected).

## 3. Candidate #763 `etf-daily-r2-vol-regime-gating` (volatility-regime gating, N = 12)

Selected: `etf-daily-r2-vol-regime-gating-06`, `L_vol=21`, `V=0.25`, `f_off=0.0`. Development Sharpe of the 12 trials ranged from 0.0420 (`L_vol=63`, `V=0.15`, `f_off=0.0`) to 0.0764 (the selected). Within the grid, `V=0.25` dominates `V=0.15` at both lookbacks, and at `V=0.25` full flight to cash (`f_off=0.0`) beats quarter exposure (`f_off=0.25`). The gate was on for 0.547 to 0.867 of development rows depending on the threshold. The `f_off=0.25` variants produce 0 round trips/yr (the gate scales weights down but never fully liquidates); all activity comes from the `f_off=0.0` variants.

| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 5.3% | 4.4% |
| CAGR after German tax | 4.4% | 3.3% |
| Max drawdown, and its dates | 8.3% (2008-05-19 to 2009-06-22) | 10.7% (2022-01-03 to 2022-09-27) |
| Calmar (return / max drawdown) | 0.64 | 0.41 |
| Sharpe; target and realised annualised volatility | Sharpe 1.21; target 10.0%, realised 4.3% | Sharpe 0.74; target 10.0%, realised 6.0% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2008 -4.6%; 2008 -4.6%; 2020 6.3% | worst 2022 -7.9%; 2022 -7.9% |
| Round trips per year, average holding days, max share of time in one ETF | 14.4 round trips/yr; 267.5 avg holding days; 85.3% max share in one ETF | 20.2 round trips/yr; 225.0 avg holding days; 89.5% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 0.1%/yr (borrow 0.0%/yr); double cost: CAGR 5.2%, max DD 8.5%, Calmar 0.61 | cost drag 0.3%/yr (borrow 0.0%/yr); double cost: CAGR 4.2%, max DD 11.0%, Calmar 0.38 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 2.18 vs 0.96 (n_w=14) | benchmark Calmar 0.54, CAGR 7.3%, max DD 13.6%; median after-tax year Calmar 1.57 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.9806 over N=37 trials; PBO 0.2204; uplift CI [-0.7994, 1.8997]; bootstrap ci_low -0.799434 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 7.1%, max DD 12.3%, Calmar 0.57 | CAGR 3.7%, max DD 13.7%, Calmar 0.27 |

**Verdict: FAIL** (3 of 5 criteria pass)

- drawdown: pass (development 0.0830; holdout 0.1072; cap 0.2000)
- beats_benchmark: pass (median window Calmar candidate 2.1835 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.9806 over N=37 trials; PBO 0.2204; uplift CI [-0.7994, 1.8997]; bootstrap ci_low -0.799434 <= 0)
- holdout: pass (holdout CAGR 0.0441 (need > 0); max drawdown 0.1072)
- activity: fail (round trips per year 14.3934 (min 20); max time share in one ETF 0.8534 (max 0.9000))

**Reading.** This is the closest any candidate in the programme has come to the bar, and the failure is instructive rather than decisive. The rule does exactly what Moreira-Muir predicts: it sidesteps the benchmark's two big drawdown years (its worst year is 2008 at -4.6% and 2022 at -7.9%, against the benchmark's much deeper losses), which is why its median development-year Calmar (2.18) more than doubles the benchmark's (0.96) -- the first beats-benchmark pass on this basket -- and why its DSR survives the now-37-trial programme history at 0.98 with a PBO of 0.22. What it does not do is earn enough while invested: 5.3% then 4.4% a year against the benchmark's 7.3% in both periods, because a 1.0 gross cap on a gate that sits in cash part of the time realises only 4.3% volatility against a 10% target. The per-year uplift vector swings from +6.6 (2019) to -5.3 (2015) and -3.4 (2018), so the bootstrap interval on the median uplift straddles zero; and at 14.4 round trips/yr the rule sits below the 20/yr activity floor (it trades only when the gate flips, which at `V=0.25`, `L_vol=21` is rare). The holdout passes but concedes the same trade: better drawdown shape (10.7% vs 13.6%), less return (4.4% vs 7.3%).

**Continuity line (not a gate):** median development-year after-tax Calmar 2.18 vs the repo's older 1.3085 bar: above it.

**Recommendation (mine, not the renderer's): reject, but flag for the operator.** Not a retest: the test ran at full power (n_w = 14), the holdout has been seen, and two criteria fail. The flag: this is the programme's first candidate to beat the benchmark on median year Calmar in both periods while passing the drawdown cap, and its luck failure is the narrowest possible (only the bootstrap leg; DSR and PBO both pass). If the operator wants a follow-up, the honest shape is a pre-registered variant that lifts invested exposure (a higher vol target with the gate as the risk budget, or leverage inside a capped gross), tested as a new candidate with no holdout under the Phase 4 (h) rule -- the 1.5x information line (dev CAGR 7.1%, max DD 12.3%, Calmar 0.57) hints the direction but proves nothing. Ledger row: `vol_regime_gating` / `daily` / `ETF_BASKET_XA14`, `NO_GO`, `PROMOTABLE`, 12 cells.

**What would change the recommendation:** a pre-registered variant whose failure mode is not "too little return while invested" -- i.e. an exposure-lifting construction -- clearing the bootstrap uplift CI above zero and the 20/yr activity floor. Re-running the same grid would not change either.

## 4. Candidate #764 `etf-daily-r2-donchian-trend-breakout` (Turtle-style channel breakout, N = 6)

Selected: `etf-daily-r2-donchian-trend-breakout-05`, `L_e=252`, `L_x=126`, `long_flat`. Development Sharpe of the 6 trials ranged from 0.0209 (`L_e=55`, `long_short`) to 0.0441 (the selected). Every `long_short` variant was weaker than its `long_flat` twin at every lookback, extending r1's finding that the short side of this basket costs return without buying protection.

| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 4.7% | 4.1% |
| CAGR after German tax | 3.7% | 3.0% |
| Max drawdown, and its dates | 19.0% (2015-03-20 to 2016-03-14) | 10.5% (2022-09-27 to 2023-10-27) |
| Calmar (return / max drawdown) | 0.25 | 0.39 |
| Sharpe; target and realised annualised volatility | Sharpe 0.70; target 10.0%, realised 6.9% | Sharpe 0.58; target 10.0%, realised 7.4% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2015 -9.6%; 2008 4.1%; 2020 2.3% | worst 2022 -3.9%; 2022 -3.9% |
| Round trips per year, average holding days, max share of time in one ETF | 6.2 round trips/yr; 382.1 avg holding days; 72.0% max share in one ETF | 7.9 round trips/yr; 355.9 avg holding days; 69.5% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 0.2%/yr (borrow 0.0%/yr); double cost: CAGR 4.5%, max DD 19.3%, Calmar 0.23 | cost drag 0.3%/yr (borrow 0.0%/yr); double cost: CAGR 3.8%, max DD 10.8%, Calmar 0.35 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 1.13 vs 0.96 (n_w=14) | benchmark Calmar 0.54, CAGR 7.3%, max DD 13.6%; median after-tax year Calmar 0.67 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.5574 over N=37 trials; PBO 0.7110; uplift CI [-0.8951, 0.8488]; dsr 0.5574 < threshold 0.95; pbo 0.7110 >= threshold 0.5; bootstrap ci_low -0.895085 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 5.7%, max DD 21.6%, Calmar 0.26 | CAGR 4.0%, max DD 11.7%, Calmar 0.34 |

**Verdict: FAIL** (3 of 5 criteria pass)

- drawdown: pass (development 0.1896; holdout 0.1054; cap 0.2000)
- beats_benchmark: pass (median window Calmar candidate 1.1289 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.5574 over N=37 trials; PBO 0.7110; uplift CI [-0.8951, 0.8488]; dsr 0.5574 < threshold 0.95; pbo 0.7110 >= threshold 0.5; bootstrap ci_low -0.895085 <= 0)
- holdout: pass (holdout CAGR 0.0411 (need > 0); max drawdown 0.1054)
- activity: fail (round trips per year 6.1686 (min 20); max time share in one ETF 0.7198 (max 0.9000))

**Reading.** The turnover intent held exactly as designed: the separate exit channel cut trading from r1 TSMOM's 86 round trips/yr to 6.2, cost drag from 1.6%/yr to 0.2%/yr, and the double-cost line barely moves. The selected 252-day channel also clears the drawdown cap in both periods (its 19.0% development drawdown is the round's closest call against the cap) and survives the holdout. But the luck leg fails on all three counts, and the PBO of 0.71 is the round's honest headline: the grid's best configuration was more likely than not a lucky pick, with the selected trial's development Sharpe (0.0441) only marginally above the worst in the grid (0.0209). The beats-benchmark pass (1.13 vs 0.96 median year Calmar) is thin, bought by drawdown shape rather than return (4.7% vs the benchmark's 7.3% CAGR). The 2022-to-2026 holdout repeats r1's trend verdict in miniature: positive, capped, and still behind the benchmark on return.

**Continuity line (not a gate):** median development-year after-tax Calmar 1.13 vs the repo's older 1.3085 bar: below it.

**Recommendation (mine, not the renderer's): reject.** Not a retest: full power, holdout seen. The channel construction did not rescue trend on this basket; the honest prior recorded on #764 (if the r1 verdict's real conclusion is "trend does not work on this basket at daily cadence", this candidate fails too) is confirmed. Ledger row: `donchian_breakout` / `daily` / `ETF_BASKET_XA14`, `NO_GO`, `PROMOTABLE`, 6 cells.

**What would change the recommendation:** nothing within this family and vehicle. The family now has `NO_GO` rows on daily SPY, daily ES (single-instrument, 2026-07-24) and this basket cell; a future trend test would need a different vehicle or a materially different risk mechanism, and the r1+r2 evidence says the benchmark gap is a level problem, not a construction problem.

## 5. Round summary and multiplicity

| Candidate | N | Selected | Criteria passed | Verdict | Power | Recommendation |
|---|---|---|---|---|---|---|
| #763 `etf-daily-r2-vol-regime-gating` | 12 | `-06` (L_vol=21, V=0.25, f_off=0.0) | 3 of 5 (drawdown, beats_benchmark, holdout) | NO_GO | PROMOTABLE | reject, flagged for the operator |
| #764 `etf-daily-r2-donchian-trend-breakout` | 6 | `-05` (L_e=252, L_x=126, long_flat) | 3 of 5 (drawdown, beats_benchmark, holdout) | NO_GO | PROMOTABLE | reject |

- Programme trial store: 37 trials after this round (5 backfilled + 14 r1 + 18 r2). The DSR of any later candidate in the daily-allocation space deflates against these 37.
- Ledger: two `NO_GO` rows added to `backtest/tested_cells.py` (sources: this document). Family multiplicity after this round: `donchian_breakout` 12 run cells (3 daily SPY + 3 daily ES from 2026-07-24, plus this round's 6). The `vol_regime_gating` row is the first ledger record for a family listed in `backtest/weekly_review.py::UNTESTED_CANDIDATES`; per the skill, the candidate-list update is raised on #762 as its own issue and is not made inside this round.
- Both candidates passed beats_benchmark, the first in the programme to do so; both failed the activity floor. The two r2 rules traded 6 to 20 times a year against r1 TSMOM's 86; on this basket, the activity floor and the drawdown-shape advantage pull in opposite directions, and both rounds' evidence says the benchmark's full-period return is what the basket actually pays for.
- The `long_short` underperformance of `long_flat` twins now holds across three families and 24 configurations (r1 tsmom 8, r1 xs 6 partial, this round's 6): on `ETF_BASKET_XA14`, 2007 to 2021, shorting the basket on breakdown signals has cost return without buying drawdown protection every time it was tried.

## 6. Honest notes

- The analysts (two dispatches of the `analyst` agent, plus one follow-up each for the holdout paths) implemented the frozen text and reported no deviation. One interpretation detail is recorded in the #764 runner docstring: because the `L_e` channel strictly contains the `L_x` channel, an entry trigger implies the opposite exit trigger on the same row, and the entry is evaluated first so the state flips directly rather than passing through 0 (the only reading consistent with the frozen state machine).
- #763's gate is evaluated on SPY's realised volatility while SPY is also one of the 14 held ETFs; this was frozen in the pre-registration (section 3.1) as part of the rule, not a confound to remove.
- The holdout period ends 2026-11-06, the run date; its scorecard scores 2022 to 2025 as full years.
- The parity check for this round (3 of 15 FAIL) is recorded in the pre-registration section 10 and the freeze PR #767 body; the basket is unchanged from r1, which the operator explicitly kept after seeing the same failures.
- The classifier outage that ran through this round's GitHub interactions (STOP 2 posting, the freeze PR create) was handled by handing exact commands to the operator; every artifact of record (issues, PRs, stop markers) exists on GitHub, posted by the operator's own hand.

## 7. Reproduction

From the worktree root, with `CLAUDE_AGENT_NO_BROKER=1` and a venv holding `requirements.txt`:

```
venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/run_vol_regime_gating.py --phase development        # already run; re-running refuses duplicate trial ids
venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/run_donchian_trend_breakout.py --phase development  # same
venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/evaluate_round.py --candidate etf-daily-r2-vol-regime-gating --out <dir>
venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/evaluate_round.py --candidate etf-daily-r2-donchian-trend-breakout --out <dir>
```

The holdout commands (`--phase holdout` / `--phase holdout --i-am-the-orchestrator`) were run once each from the orchestrating session and are refused by the lock in `backtest/etf_data.py` from now on.
