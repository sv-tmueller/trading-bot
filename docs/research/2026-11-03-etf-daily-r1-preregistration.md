# Research round `etf-daily-r1`: multi-ETF momentum on a cross-asset basket -- pre-registration

**Question:** Does a daily-bar momentum allocation rule on a fixed 14-ETF cross-asset basket, sized to a 10% portfolio volatility target with no leverage, clear the five-criterion pass bar of the AI research pipeline (design spec section 5.2) on development data (to 2021-12-31) and on the one-shot holdout (2022-01-01 onward)? Two constructions of the signal are tested: time-series momentum (each ETF on its own trend) and cross-sectional momentum (the strongest ETFs relative to the others).

**Round issue:** #737. **Candidate issues (operator pick, 2026-11-03: "test #750 and #751"):** #750 (`etf-daily-r1-tsmom-basket`), #751 (`etf-daily-r1-xs-momentum`). Not picked: #752, #753.
**Date:** 2026-11-03. **Author:** Claude Code research-round session (research-only; `CLAUDE_AGENT_NO_BROKER=1` in every shell; no broker call, no production code touched). **Branch:** `docs/etf-daily-r1-preregistration`.
**Design authority:** `docs/superpowers/specs/2026-10-23-ai-research-pipeline-design.md` (sections 5.1 to 5.7). **Procedure:** `.claude/skills/research-round/SKILL.md`. **Gate conventions inherited:** `docs/research/2026-07-21-overfitting-gate-usage.md`.

This document is committed and merged **before** any candidate's returns, Sharpe or equity curve exist. No bars have been loaded for either candidate (section 11 lists the only data contact allowed before the merge). The results PR adds a dated addendum under the freeze banner at the end of this file and never edits the frozen text.

---

## 0. Invariant framing

CLAUDE.md "Architectural invariants" and "Writing conventions" apply by reference. This round is research only: it edits nothing under `supabase/functions/`, makes no broker or Supabase call, and promotes nothing. A candidate that passes is a *replacement* candidate for the single live decision rule, to be taken through its own brainstorm, design spec and ADR; it is never a second live rule.

## 1. Identifiers (frozen)

| Item | Value |
|---|---|
| `round_id` | `etf-daily-r1` |
| `candidate_id` (#750) | `etf-daily-r1-tsmom-basket` |
| `candidate_id` (#751) | `etf-daily-r1-xs-momentum` |
| `trial_id` | `<candidate_id>-NN`, `NN` two digits from `01`, in the grid order of section 6 |
| `TrialRecord.space` | `DAILY_ALLOCATION` (`backtest/trial_store.py`) |
| `TrialRecord.source` | `docs/research/2026-11-03-etf-daily-r1-preregistration.md` |
| `TrialRecord.date` | the date the development run is made |
| Ledger family / cadence / vehicle (#750) | `tsmom_timeseries` / `daily` / `ETF_BASKET_XA14` |
| Ledger family / cadence / vehicle (#751) | `cross_sectional_rv` / `daily` / `ETF_BASKET_XA14` |
| Study directory | `docs/research/2026-11-03-etf-daily-r1-study/` |

## 2. Universe and data (frozen)

- **Basket `ETF_BASKET_XA14`** (14 tradable ETFs): `SPY`, `QQQ`, `IWM`, `EFA`, `EEM`, `VNQ`, `TLT`, `IEF`, `LQD`, `HYG`, `TIP`, `GLD`, `DBC`, `UUP`. US equity (3), international and emerging equity (2), real estate (1), Treasuries of two durations (2), investment-grade and high-yield credit (2), inflation-linked (1), gold (1), broad commodities (1), US dollar (1).
- **Cash series:** `BIL` (1-3 month T-bills). Never traded. Its daily simple return is the `cash_returns` series of the simulator and the hurdle in the #750 signal.
- **Benchmark symbol:** `SPY` (section 7).
- **Source:** yfinance adjusted daily OHLC (`auto_adjust=True`) through `load_daily_bars` in `backtest/etf_data.py`, which is the only loader the study may use and which enforces the holdout lock. No other price source, no local CSV, no `yf.download` call outside that loader.
- **Data start:** the first date on which all 15 tickers have a bar. Expected 2007-05-30 (BIL inception; UUP 2007-03-01 and HYG 2007-04-11 are the next-latest). The study prints the actual first date; it is a fact of the data, not a choice.
- **Calendar:** SPY's trading days from the data start are the master index. Every other ticker is reindexed to it. For **signal computation only**, closes are forward-filled across a ticker's missing days; for **trading**, the simulator's own rule applies (an asset with a missing open or close is not traded that day and keeps its position).
- **Development period:** data start to `DEV_END` = 2021-12-31 (the loader cuts it mechanically). Expected scored calendar years 2008 to 2021, n_w = 14 (the scorecard's full-year rule: index starts by Y-01-07 and ends on or after Y-12-25), above the repo's n_w = 13 promotion bar.
- **Holdout period:** `HOLDOUT_START` = 2022-01-01 to the data end at run time. Released once per candidate by the lock in `backtest/etf_data.py` and by the Phase 4 procedure in the skill.
- **Warm-up:** signals and volatility estimates are computed from the data start; warm-up rows (zero weights) stay in the development scorecard, as the backfilled trials' do.

## 3. Rules (frozen)

Both candidates produce a signal frame in {-1, 0, +1} per ETF per day at close T. Sizing (section 4) turns it into target weights at T; the simulator fills at the open of T+1. There is no stop, target or time stop in either rule: the signal is the exit.

### 3.1 `etf-daily-r1-tsmom-basket` (#750): time-series momentum

For each ETF i and lookback `L` (trading rows on the master index):

- `excess_i(T) = Close_i(T) / Close_i(T-L) - 1 - (Close_BIL(T) / Close_BIL(T-L) - 1)`.
- Variant `long_short`: signal `+1` if `excess > 0`, `-1` if `excess < 0`, `0` if exactly 0 or not computable.
- Variant `long_flat`: signal `+1` if `excess > 0`, else `0`.
- The signal is re-evaluated at every close. A position opens when the signal leaves 0, closes when it returns to 0, and reverses when it flips sign.

### 3.2 `etf-daily-r1-xs-momentum` (#751): cross-sectional momentum

- **Ranking days:** the last trading day of each calendar week (Monday to Sunday) on the master index. Signals set on a ranking day are held unchanged until the next ranking day.
- **Score** for each ETF i, lookback `L`, skip `S` = 21 rows: `score_i(T) = Close_i(T-S) / Close_i(T-S-L) - 1`.
- If any of the 14 scores is not computable (warm-up), every signal is `0` that week.
- Rank the 14 scores descending; ties broken by ticker in alphabetical order (deterministic).
- Variant `long_only`: top 4 get `+1`, the rest `0`.
- Variant `long_short`: top 4 get `+1`, bottom 4 get `-1`, the middle 6 get `0`.
- A round trip is one ETF entering a group and later leaving it (or switching groups, which the simulator records as a reversal).

## 4. Sizing and simulation (frozen)

Applied identically to both candidates, the benchmark and the two information re-runs.

- `asset_returns` = `Close.pct_change()` of the 14 ETFs on the master index (row 0 NaN).
- `raw = inverse_vol_weights(signals, asset_returns, lookback=60)` (`backtest/vol_target.py`).
- `target_weights = vol_target_weights(raw, asset_returns, target_vol=0.10, lookback=60, gross_cap=1.0)`.
- `simulate_portfolio(target_weights, opens, closes, cash_returns, starting_equity=100_000.0, costs=<section 5>, gross_cap=1.0, rebalance_band=0.02)` (`backtest/portfolio.py`), with `opens` and `closes` the 14 ETFs' Open and Close frames on the master index and `cash_returns = Close_BIL.pct_change()` (the simulator fills its NaN with 0).
- The vol target 0.10 is the `target_vol` passed to `vol_target_weights`, `benchmark_weights` and `compute_scorecard`. It is a ceiling: with the gross cap at 1.0 a calm basket runs below it, and the scorecard reports the realised volatility.
- `rebalance_band` 0.02 is the simulator's default; resizes it triggers are `partial` trades and never count as round trips.
- Gross cap: **1.0 for every verdict run** (both candidates, the benchmark, the double-cost line). **1.5 only for the `leverage_info` line** (section 7), passed to both `vol_target_weights` and `simulate_portfolio` of that run.

## 5. Costs (frozen)

- Verdict runs: `CostModel(slippage_bps=5.0, commission_bps=0.0, borrow_bps_annual=50.0, financing_spread_bps_annual=100.0)`. Slippage is the repo's 0.05% per side; commission is 0 (the broker is commission-free; the pipeline's backfill note records 5 + 0 bps as the pipeline convention). Issues #750 and #751 wrote "5 + 5 bps per side" as a proposal; this frozen value supersedes it.
- Short borrow: 50 bps a year on short notional (the `CostModel` default).
- Cash: idle cash net of short notional earns the BIL daily return (`cash_returns`); short proceeds earn nothing (retail model in the simulator docstring).
- Financing (1.5x information line only): negative cash pays BIL plus 100 bps a year (`financing_spread_bps_annual`).
- `double_cost` re-run: the selected configuration at `CostModel(slippage_bps=10.0, commission_bps=0.0, borrow_bps_annual=100.0, financing_spread_bps_annual=200.0)`, gross cap 1.0.
- German tax: `apply_annual_netting_tax` at its default rate, applied inside `compute_scorecard` (after-tax CAGR and the per-year window Calmars). Not a parameter of this document.

## 6. Grids, N, and the selection rule (frozen)

**#750 `etf-daily-r1-tsmom-basket`, N = 8.** Trial ids in this order:

| trial_id | `L` | variant |
|---|---|---|
| `etf-daily-r1-tsmom-basket-01` | 21 | long_short |
| `etf-daily-r1-tsmom-basket-02` | 21 | long_flat |
| `etf-daily-r1-tsmom-basket-03` | 63 | long_short |
| `etf-daily-r1-tsmom-basket-04` | 63 | long_flat |
| `etf-daily-r1-tsmom-basket-05` | 126 | long_short |
| `etf-daily-r1-tsmom-basket-06` | 126 | long_flat |
| `etf-daily-r1-tsmom-basket-07` | 252 | long_short |
| `etf-daily-r1-tsmom-basket-08` | 252 | long_flat |

**#751 `etf-daily-r1-xs-momentum`, N = 6.** Trial ids in this order (skip `S` = 21 and top/bottom size 4 are fixed, not gridded):

| trial_id | `L` | variant |
|---|---|---|
| `etf-daily-r1-xs-momentum-01` | 63 | long_only |
| `etf-daily-r1-xs-momentum-02` | 63 | long_short |
| `etf-daily-r1-xs-momentum-03` | 126 | long_only |
| `etf-daily-r1-xs-momentum-04` | 126 | long_short |
| `etf-daily-r1-xs-momentum-05` | 252 | long_only |
| `etf-daily-r1-xs-momentum-06` | 252 | long_short |

- **Round total N = 14** of the 50-configuration round budget (`ROUND_BUDGET`). No budget authorization is needed and `round_budget=` is not passed to `append_trials`.
- Nothing outside these 14 configurations is evaluated. Every one of the 14 is appended to `docs/research/pipeline/trials.json` as a `TrialRecord` (losers included) with `sharpe_daily` = the development scorecard's `sharpe_daily` of that trial (mean / std(ddof=1) of its finite development daily returns, not annualised, not excess) and `n_periods` = its finite return count. The `double_cost` and `leverage_info` re-runs are not trials and are not appended.
- **Selection rule (development data only):** the configuration with the highest `sharpe_daily`; a tie goes to the lowest `trial_id`. Drawdown, activity and the benchmark comparison are pass criteria (section 8), never selection filters. The selected configuration is the only one run on the holdout.
- The `config` stored per trial is `{"L": <int>, "variant": "<str>", "skip": 21, "k": 4}` for #751 and `{"L": <int>, "variant": "<str>"}` for #750, plus `"vol_lookback": 60, "target_vol": 0.10, "gross_cap": 1.0, "rebalance_band": 0.02`.

## 7. Scorecard, benchmark, uplift, and gate inputs (frozen)

- **Benchmark:** `benchmark_weights(asset_returns, symbol="SPY", target_vol=0.10, lookback=60, gross_cap=1.0)` through the same `simulate_portfolio` call (same costs, band, cash series, master index) as the candidate. This is the baseline for criterion 2 and for the bootstrap uplift (spec 5.2 criterion 2).
- **Scorecard:** `compute_scorecard(result, benchmark, target_vol=0.10, double_cost=<section 5 re-run>, leverage_info=<gross cap 1.5 re-run>)` (`backtest/scorecard.py`), once per phase. `development_result.json` stores it under `scorecard` together with `round_id`, `candidate_id`, `trial_ids`, `selected_trial_id`, `config`, `commit`; `holdout_result.json` the same minus `trial_ids`.
- **Returns file:** `<study dir>/<candidate_id>-development-returns.csv`, one row per development day on the master index, one column per `trial_id` (the simulator's `daily_returns`) plus `benchmark`. Committed with `development_result.json`. The gate inputs below are built from this file and never recomputed after the holdout.
- **`perf_matrix`:** the (T, N) array of the N trial columns in `trial_ids` order, finite rows only. T is the development day count (about 3,670 rows), far above `pbo_n_splits`.
- **`returns_best`:** the `selected_trial_id` column.
- **`uplifts` (the frozen uplift definition):** one value per scored development calendar year Y: `Calmar_Y(selected) - Calmar_Y(benchmark)`, where `Calmar_Y` is the pre-tax Calmar of that column's returns within Y (equity rebased to 1.0 at the first row of Y; Calmar = year return / max drawdown magnitude within Y), using the scorecard's full-year rule for which years count. A year in which either side has zero drawdown is dropped. The candidate's expected n_w is 14; the bootstrap sample is this vector in year order.
- **`all_trial_sharpes`:** `programme_sharpes()` called once after both candidates' trials are appended (expected size 5 backfilled + 14 = 19).
- **`gate_kwargs` for `evaluate_candidate`** (forwarded unchanged to `evaluate_gate`): `pbo_n_splits=16`, `bootstrap_block_length=2` (= `round(14 ** (1/3))`, the module's own rule stated explicitly), `bootstrap_n_boot=1000`, `bootstrap_seed=0`, `bootstrap_alpha=0.05`, `dsr_sr_benchmark=0.0`. Thresholds stay at the module constants (DSR >= 0.95, PBO < 0.5, `ci_low` > 0).
- **Continuity line (not a gate):** the verdict document also reports each candidate's median development-year after-tax Calmar next to the repo's older bar of 1.3085 median-window after-tax Calmar vs unscaled SPY (spec 5.2, last paragraph).

## 8. Pass bar, split, and holdout policy (frozen)

- **Pass bar:** spec 5.2, as implemented by `evaluate_candidate` in `backtest/pipeline_gate.py`: (1) max drawdown at most `MAX_DRAWDOWN` = 0.20 in development and holdout; (2) median development window Calmar strictly above the benchmark's; (3) the overfitting gate passes on all three legs with the programme trial vector; (4) holdout CAGR after costs > 0 and holdout max drawdown at most 0.20; (5) at least `MIN_ROUND_TRIPS_PER_YEAR` = 20 round trips per year and `max_time_share_one_etf` at most `MAX_TIME_SHARE_ONE_ETF` = 0.90, both on development data. The operator confirms this bar by merging this document.
- **Split:** `DEV_END` = 2021-12-31, `HOLDOUT_START` = 2022-01-01 (`backtest/etf_data.py`).
- **Holdout policy:** both candidates are first tests. The holdout runs for both, exactly once each, whatever the development numbers say; no choice is made after seeing development results. Neither candidate is a retest under Phase 4 (h) of the skill, so no earlier `candidate_id`'s holdout has been seen.
- **Holdout method:** the selected configuration is simulated over the full series from the data start (so positions, signals and volatility estimates at 2022-01-01 are the natural carry-in), then cut to rows on or after `HOLDOUT_START`: `equity`, `daily_returns`, `gross_exposure` and `held_weights` sliced to those rows; `trades` restricted to `exit_date` on or after `HOLDOUT_START`; `costs` per key = full-series costs minus the development-only run's costs (the two runs are identical through 2021-12-31). The benchmark, `double_cost` and `leverage_info` runs are cut the same way. The holdout scorecard is `compute_scorecard` on those sliced results. The holdout path appends no trial.
- **Verdict vocabulary:** per the skill's Phase 5 step 5 (`PASS` only with `power="PROMOTABLE"` and `len(window_calmars) >= 13`; otherwise `NO_GO` at PROMOTABLE power when n_w >= 13, else `DIRECTIONAL_NO_GO`). `n_cells` is the candidate's N above.

## 9. Study contract (frozen; the analyst implements it, the orchestrator runs the holdout)

- One script per candidate in the study directory, `--phase development|holdout`, repo root on `sys.path`, imports from `backtest/` read-only: `load_daily_bars` (`etf_data`), `inverse_vol_weights` and `vol_target_weights` and `benchmark_weights` (`vol_target`), `simulate_portfolio`, `CostModel`, `round_trips_per_year` (`portfolio`), `compute_scorecard` (`scorecard`), `TrialRecord` and `append_trials` (`trial_store`), `record_result` (`etf_data`, holdout path only).
- Development path: loads bars with `phase="development"`, evaluates exactly the grid of section 6, appends the N trials with one `append_trials` call, writes `<candidate_id>-development-returns.csv` and `<candidate_id>-development-payload.json`, and never calls `record_result`.
- Holdout path: reads `selected_trial_id` and `config` from `development_result.json`, loads bars with `phase="holdout"` and `candidate_id`, runs only that configuration plus the benchmark and the two re-runs as section 8 says, and calls `record_result(candidate_id, "holdout", payload)` in the same process. It is written and committed by the analyst and run only by the orchestrating session.
- The analyst never runs `python3` outside the worktree root, never writes outside the study directory, and never loads holdout bars.

## 10. Parity check (spec 5.6)

`python3 -m backtest.run_etf_parity --tickers SPY,QQQ,IWM,EFA,EEM,VNQ,TLT,IEF,LQD,HYG,TIP,GLD,DBC,UUP,BIL` compares yfinance adjusted closes with Alpaca `1Day` bars (`adjustment=all`) over 2019-01-01 to 2021-12-31 and passes a ticker when the median absolute daily-return difference is below 1 bp and the 99th percentile below 10 bps. It is a GET-only market-data read, not a broker call, and the only data contact allowed before this document merges. The session that wrote this document has no Alpaca data keys, so the operator runs it and its output is pasted into the freeze PR. A failing ticker is discussed on the PR before the merge; the basket is not changed silently.

### 10.1 Parity check result (operator-run, 2026-11-03, recorded before the merge)

`venv/bin/python3 -m backtest.run_etf_parity --tickers SPY,QQQ,IWM,EFA,EEM,VNQ,TLT,IEF,LQD,HYG,TIP,GLD,DBC,UUP,BIL`, verbatim:

```
ticker    n_days  median_bps   p99_bps   n_yf  n_alpaca verdict
SPY          756       1.410    37.866    757       757 FAIL
QQQ          756       0.117     2.682    757       757 PASS
IWM          756       1.555    35.762    757       757 FAIL
EFA          756       0.727     7.627    757       757 PASS
EEM          756       1.112    11.739    757       757 FAIL
VNQ          756       0.549    15.581    757       757 FAIL
TLT          756       0.242     0.807    757       757 PASS
IEF          756       0.321     0.978    757       757 PASS
LQD          756       0.336    11.007    757       757 FAIL
HYG          756       0.518     7.225    757       757 PASS
TIP          756       0.321     1.051    757       757 PASS
GLD          756       0.000     9.788    757       757 PASS
DBC          756       2.062     7.963    757       757 FAIL
UUP          756       1.402     4.265    757       757 FAIL
BIL          756       0.219     1.095    757       757 PASS
```

7 PASS, 8 FAIL against the script's thresholds (median < 1 bp, p99 < 10 bps); 757 sessions on both sides for every ticker. A read-only follow-up (largest-difference sessions per failing ticker, ex-dividend dates flagged from yfinance's dividend series; output on freeze PR #754) found two causes, neither of which touches the research data:

1. **The p99 failures are 4 to 6 sessions in March 2020** (the circuit-breaker sessions 2020-03-09 to 2020-03-19, plus 03-30/31 for DBC), where Alpaca's `1Day` close differs from the official close that yfinance carries by up to 10% (VNQ 2020-03-16: yfinance 51.07, Alpaca 56.15; LQD 2020-03-16: 95.23 vs 91.18; GLD 2020-03-16: 141.64 vs 137.56; SPY 2020-03-12: 225.60 vs 232.07). Each bad close produces two offsetting return differences (that day and the next). Ex-dividend days are not the cause: the median absolute difference on ex-dividend days is the same as or smaller than on other days for every ticker checked. The same sessions were flagged as a first-run deviation in `docs/research/2026-10-22-spy-intraday-momentum-verdict.md`. The research runs on yfinance's official closes; the artefact sits on the Alpaca side and is a live-trading data-quality note for Project 2, not a research input.
2. **The median failures are cent rounding of Alpaca's adjusted prices on low-priced ETFs** (UUP at about $21 and DBC at about $10 to $13: one cent is 4 to 8 bps, and UUP's largest off-March-2020 differences are all 4.3 to 4.6 bps with yfinance carrying sub-cent adjusted values) plus sub-cent adjustment differences elsewhere (SPY, IWM at 1.4 to 1.6 bps). The mean signed difference off the March 2020 sessions is within 0.15 bps of zero for every ticker, so there is no drift between the sources.

**Decision recorded here (the operator confirms it by merging):** the basket is unchanged. The frozen rules use 21 to 252 day cumulative returns and 60-day volatility windows, which the two effects above cannot move except when a signal is already at zero; both effects are below the frozen 5 bps per-side slippage. The verdict document cites this section as the data-quality caveat, and any promoted rule's Project 2 design must re-run the parity check on the bars it will trade on, with the March 2020 sessions as a known Alpaca-side artefact. The `run_etf_parity` thresholds themselves (set before any real basket was run through the script) are a separate issue, not changed in this round.

## 11. What exists before this commit

- The four candidate issues (#750 to #753) and the novelty-check output they carry (`python3 -m backtest.tested_cells --check ...`), which reads only the ledger.
- `programme_sharpes().size == 5` (the backfilled trials).
- No bars loaded, no returns, Sharpe, equity curve, weight or trade computed for either candidate or for the benchmark on this basket.

## 12. Non-goals

Per the skill's Non-goals: no live change, no edits under `supabase/functions/`, no broker or Supabase call, no re-opened holdout, no budget beyond 50 without an authorizing comment on #737, no merging of the freeze or results PR by the session, no closing of candidate issues, no new gate criteria, ledger verdict values or scorecard rows inside the round.

---

**Freeze banner.** Everything above this line is the frozen pre-registration. Results land as dated addenda below this line (results PR), never as edits above it.
