# Research round `etf-daily-r2`: remaining daily-allocation landscape on the 14-ETF basket -- pre-registration

**Question:** Does a daily-bar allocation rule from the remaining landscape -- volatility-regime gating (the operator's vol-gating theme, the strongest-academic-evidence untested family) and a Turtle-style Donchian channel breakout with a separate exit channel (the operator's "trend rule with a materially different construction") -- on the frozen 14-ETF cross-asset basket, sized to a 10% portfolio volatility target with no leverage, clear the five-criterion pass bar of the AI research pipeline (design spec section 5.2) on development data (to 2021-12-31) and on the one-shot holdout (2022-01-01 onward)? The r1 constructions (`tsmom_timeseries`, `cross_sectional_rv`) are not re-proposed (operator constraint on round issue #762, both NO_GO in r1, #737).

**Round issue:** #762. **Candidate issues (operator pick, 2026-11-06: "test #763 and #764"):** #763 (`etf-daily-r2-vol-regime-gating`), #764 (`etf-daily-r2-donchian-trend-breakout`). Not picked: #765, #766 (their issues stay open; their grids are not run).
**Date:** 2026-11-06. **Author:** Claude Code research-round session (research-only; `CLAUDE_AGENT_NO_BROKER=1` in every shell; no broker call, no production code touched). **Branch:** `docs/etf-daily-r2-preregistration`.
**Design authority:** `docs/superpowers/specs/2026-10-23-ai-research-pipeline-design.md` (sections 5.1 to 5.7). **Procedure:** `.claude/skills/research-round/SKILL.md`. **Gate conventions inherited:** `docs/research/2026-07-21-overfitting-gate-usage.md`.

This document is committed and merged **before** any candidate's returns, Sharpe or equity curve exist. No bars have been loaded for either candidate (section 10 lists the only data contact allowed before the merge). The results PR adds a dated addendum under the freeze banner at the end of this file and never edits the frozen text.

---

## 0. Invariant framing

CLAUDE.md "Architectural invariants" and "Writing conventions" apply by reference. This round is research only: it edits nothing under `supabase/functions/`, makes no broker or Supabase call, and promotes nothing. A candidate that passes is a *replacement* candidate for the single live decision rule, to be taken through its own brainstorm, design spec and ADR; it is never a second live rule.

## 1. Identifiers (frozen)

| Item | Value |
|---|---|
| `round_id` | `etf-daily-r2` |
| `candidate_id` (#763) | `etf-daily-r2-vol-regime-gating` |
| `candidate_id` (#764) | `etf-daily-r2-donchian-trend-breakout` |
| `trial_id` | `<candidate_id>-NN`, `NN` two digits from `01`, in the grid order of section 6 |
| `TrialRecord.space` | `DAILY_ALLOCATION` (`backtest/trial_store.py`) |
| `TrialRecord.source` | `docs/research/2026-11-06-etf-daily-r2-preregistration.md` |
| `TrialRecord.date` | the date the development run is made |
| Ledger family / cadence / vehicle (#763) | `vol_regime_gating` / `daily` / `ETF_BASKET_XA14` |
| Ledger family / cadence / vehicle (#764) | `donchian_breakout` / `daily` / `ETF_BASKET_XA14` |
| Study directory | `docs/research/2026-11-06-etf-daily-r2-study/` |

The `vol_regime_gating` family name is the one `backtest/weekly_review.py::UNTESTED_CANDIDATES` carries (from #422), so the results-time ledger row for this family will trip `tests/test_weekly_review.py::test_untested_candidates_are_absent_from_the_ledger`. Per the skill, that pin is not edited inside the round; it is raised on #762 as its own issue. The `donchian_breakout` family name is reused (the rule is a Donchian channel system); the family is closed on daily SPY and daily ES as single-instrument rules (`docs/research/2026-07-24-turtle-breakout-verdict.md`), and this cell (breadth plus portfolio vol targeting on XA14) is new.

## 2. Universe and data (frozen -- inherited from r1, unchanged)

- **Basket `ETF_BASKET_XA14`** (14 tradable ETFs): `SPY`, `QQQ`, `IWM`, `EFA`, `EEM`, `VNQ`, `TLT`, `IEF`, `LQD`, `HYG`, `TIP`, `GLD`, `DBC`, `UUP`. US equity (3), international and emerging equity (2), real estate (1), Treasuries of two durations (2), investment-grade and high-yield credit (2), inflation-linked (1), gold (1), broad commodities (1), US dollar (1).
- **Cash series:** `BIL` (1-3 month T-bills). Never traded. Its daily simple return is the `cash_returns` series of the simulator.
- **Benchmark symbol:** `SPY` (section 7).
- **Source:** yfinance adjusted daily OHLC (`auto_adjust=True`) through `load_daily_bars` in `backtest/etf_data.py`, which is the only loader the study may use and which enforces the holdout lock. No other price source, no local CSV, no `yf.download` call outside that loader.
- **Data start:** the first date on which all 15 tickers have a bar. Expected 2007-05-30 (BIL inception; UUP 2007-03-01 and HYG 2007-04-11 are the next-latest). The study prints the actual first date; it is a fact of the data, not a choice.
- **Calendar:** SPY's trading days from the data start are the master index. Every other ticker is reindexed to it. For **signal computation only**, closes are forward-filled across a ticker's missing days; for **trading**, the simulator's own rule applies (an asset with a missing open or close is not traded that day and keeps its position).
- **Development period:** data start to `DEV_END` = 2021-12-31 (the loader cuts it mechanically). Expected scored calendar years 2008 to 2021, n_w = 14 (the scorecard's full-year rule: index starts by Y-01-07 and ends on or after Y-12-25), above the repo's n_w = 13 promotion bar.
- **Holdout period:** `HOLDOUT_START` = 2022-01-01 to the data end at run time. Released once per candidate by the lock in `backtest/etf_data.py` and by the Phase 4 procedure in the skill.
- **Warm-up:** signals and volatility estimates are computed from the data start; warm-up rows (zero weights) stay in the development scorecard, as the backfilled trials' do.

## 3. Rules (frozen)

Both candidates produce a signal frame on the master index at close T; sizing (section 4) turns it into target weights at T; the simulator fills at the open of T+1.

### 3.1 `etf-daily-r2-vol-regime-gating` (#763): volatility-regime-gated basket allocation

A *gating* rule: the underlying allocation is passive (all 14 ETFs, long-only); the only decision is the exposure fraction, driven by SPY's realised volatility.

- **Gate:** `realised_vol(T)` = annualised standard deviation (std with `ddof=1`, multiplied by `sqrt(252)`) of SPY's daily close-to-close returns over the prior `L_vol` trading rows on the master index (rows T-`L_vol`+1 to T, inclusive of T; forward-filled signal closes). The gate is **on** at T when `realised_vol(T) < V`, **off** otherwise. A not-computable `realised_vol` (warm-up) is off.
- **Exposure fraction:** the signal for every ETF i at T is `f(T)`: `f = 1.0` when the gate is on, `f = f_off` when it is off, with `f_off` in {0.25, 0.0} as a grid axis. Signals are in {0.0, 0.25, 1.0}: the sizing chain's `inverse_vol_weights` accepts them (it requires {-1, 0, +1}; **amendment**: see 3.1.1 below for the exact mechanism, which is frozen here).
- **Interpretation note (frozen):** the gate is evaluated on SPY's returns; SPY is also one of the 14 held ETFs. The gate variable and the basket are not independent (the basket contains SPY), which is stated up front as part of the rule, not a confound to remove: the gate is a *portfolio-level* exposure decision, not a per-ETF signal.

#### 3.1.1 Sizing-chain adaptation for fractional exposure (frozen)

`inverse_vol_weights` accepts signals in {-1, 0, +1} only. The fractional-exposure gate is implemented as a **two-step weight multiplication**, not a signal-value hack:

1. `signals_frame` = all-ones (14 columns, every row from the first row where the sizing chain can size, i.e. `inverse_vol_weights` warm-up aside, the gate does not add its own warm-up beyond `L_vol`); passed through `inverse_vol_weights(signals, asset_returns, lookback=60)` then `vol_target_weights(raw, asset_returns, target_vol=0.10, lookback=60, gross_cap=1.0)`, exactly as r1.
2. The resulting `target_weights` frame is then multiplied row-wise by `f(T)` (the gate's exposure fraction for that row), giving the final target weights, and passed to `simulate_portfolio` with `gross_cap=1.0` (the cap is unchanged: `f <= 1` so the multiplication can only shrink gross exposure below the cap).

The multiplication happens **after** the vol-target scaling, so the on-state weights are exactly r1's always-on basket and the off-state is that same basket scaled to `f_off`. This is the rule as stated in #763; it is frozen here with its mechanism so no interpretation choice is left to the study.

### 3.2 `etf-daily-r2-donchian-trend-breakout` (#764): Turtle-style Donchian channel with separate exit channel

A per-ETF trend rule: entry on a channel breakout, exit on a **shorter** opposite channel, with an optional short side.

- **Entry (long):** ETF i goes long when its close at T exceeds the highest close of the prior `L_e` trading rows (the channel excludes row T; closes are the forward-filled signal closes).
- **Exit channel (long):** the long closes when the close at T falls below the lowest close of the prior `L_x` trading rows, where `L_x = ceil(L_e / 2)` (28, 63, 126 for `L_e` = 55, 126, 252).
- **Variant `long_flat`:** long on the upper-channel breakout, flat after the exit-channel exit. **Variant `long_short`:** additionally short on the lower-channel breakout (close below the lowest close of the prior `L_e` rows), covered on the upper exit channel (close above the highest close of the prior `L_x` rows).
- **Per-ETF state machine (frozen):** each ETF's signal is a state in {+1, 0, -1} that changes only on the triggers above, evaluated at every close in master-index order. A not-computable channel (warm-up) leaves the state unchanged. The signal frame is exactly this state, row by row; there is no separate stop, target or time stop. The state machine is evaluated from the data start, so positions and states at the development/holdout boundary carry in naturally.
- **Turnover intent (stated, not gated):** the separate shorter exit channel exists to cut r1's measured cost drag (#750: 1.6%/yr at 86 round trips/yr); it is part of the rule, not a tuning knob.

## 4. Sizing and simulation (frozen -- inherited from r1, unchanged)

Applied identically to both candidates, the benchmark and the two information re-runs, except #763's post-scaling gate multiplication (3.1.1).

- `asset_returns` = `Close.pct_change()` of the 14 ETFs on the master index (row 0 NaN).
- `raw = inverse_vol_weights(signals, asset_returns, lookback=60)` (`backtest/vol_target.py`).
- `target_weights = vol_target_weights(raw, asset_returns, target_vol=0.10, lookback=60, gross_cap=1.0)`; then, for #763 only, the row-wise `f(T)` multiplication of section 3.1.1.
- `simulate_portfolio(target_weights, opens, closes, cash_returns, starting_equity=100_000.0, costs=<section 5>, gross_cap=1.0, rebalance_band=0.02)` (`backtest/portfolio.py`), with `opens` and `closes` the 14 ETFs' Open and Close frames on the master index and `cash_returns = Close_BIL.pct_change()` (the simulator fills its NaN with 0).
- The vol target 0.10 is the `target_vol` passed to `vol_target_weights`, `benchmark_weights` and `compute_scorecard`. It is a ceiling: with the gross cap at 1.0 a calm basket runs below it, and the scorecard reports the realised volatility.
- `rebalance_band` 0.02 is the simulator's default; resizes it triggers are `partial` trades and never count as round trips.
- Gross cap: **1.0 for every verdict run** (both candidates, the benchmark, the double-cost line). **1.5 only for the `leverage_info` line** (section 7), passed to both `vol_target_weights` and `simulate_portfolio` of that run.

## 5. Costs (frozen -- inherited from r1, unchanged)

- Verdict runs: `CostModel(slippage_bps=5.0, commission_bps=0.0, borrow_bps_annual=50.0, financing_spread_bps_annual=100.0)`. Slippage is the repo's 0.05% per side; commission is 0 (the broker is commission-free).
- Short borrow: 50 bps a year on short notional (the `CostModel` default).
- Cash: idle cash net of short notional earns the BIL daily return (`cash_returns`); short proceeds earn nothing (retail model in the simulator docstring).
- Financing (1.5x information line only): negative cash pays BIL plus 100 bps a year (`financing_spread_bps_annual`).
- `double_cost` re-run: the selected configuration at `CostModel(slippage_bps=10.0, commission_bps=0.0, borrow_bps_annual=100.0, financing_spread_bps_annual=200.0)`, gross cap 1.0.
- German tax: `apply_annual_netting_tax` at its default rate, applied inside `compute_scorecard` (after-tax CAGR and the per-year window Calmars). Not a parameter of this document.

## 6. Grids, N, and the selection rule (frozen)

**#763 `etf-daily-r2-vol-regime-gating`, N = 12.** Trial ids in this order (`L_vol`, `V`, `f_off`):

| trial_id | `L_vol` | `V` | `f_off` |
|---|---|---|---|
| `etf-daily-r2-vol-regime-gating-01` | 21 | 0.15 | 0.25 |
| `etf-daily-r2-vol-regime-gating-02` | 21 | 0.15 | 0.0 |
| `etf-daily-r2-vol-regime-gating-03` | 21 | 0.20 | 0.25 |
| `etf-daily-r2-vol-regime-gating-04` | 21 | 0.20 | 0.0 |
| `etf-daily-r2-vol-regime-gating-05` | 21 | 0.25 | 0.25 |
| `etf-daily-r2-vol-regime-gating-06` | 21 | 0.25 | 0.0 |
| `etf-daily-r2-vol-regime-gating-07` | 63 | 0.15 | 0.25 |
| `etf-daily-r2-vol-regime-gating-08` | 63 | 0.15 | 0.0 |
| `etf-daily-r2-vol-regime-gating-09` | 63 | 0.20 | 0.25 |
| `etf-daily-r2-vol-regime-gating-10` | 63 | 0.20 | 0.0 |
| `etf-daily-r2-vol-regime-gating-11` | 63 | 0.25 | 0.25 |
| `etf-daily-r2-vol-regime-gating-12` | 63 | 0.25 | 0.0 |

**#764 `etf-daily-r2-donchian-trend-breakout`, N = 6.** Trial ids in this order (`L_e`, variant; `L_x = ceil(L_e/2)` is derived, not gridded):

| trial_id | `L_e` | `L_x` | variant |
|---|---|---|---|
| `etf-daily-r2-donchian-trend-breakout-01` | 55 | 28 | long_flat |
| `etf-daily-r2-donchian-trend-breakout-02` | 55 | 28 | long_short |
| `etf-daily-r2-donchian-trend-breakout-03` | 126 | 63 | long_flat |
| `etf-daily-r2-donchian-trend-breakout-04` | 126 | 63 | long_short |
| `etf-daily-r2-donchian-trend-breakout-05` | 252 | 126 | long_flat |
| `etf-daily-r2-donchian-trend-breakout-06` | 252 | 126 | long_short |

- **Round total N = 18** of the 50-configuration round budget (`ROUND_BUDGET`), inside the operator's at-most-30 constraint recorded on #762. No budget authorization is needed and `round_budget=` is not passed to `append_trials`.
- Nothing outside these 18 configurations is evaluated. Every one of the 18 is appended to `docs/research/pipeline/trials.json` as a `TrialRecord` (losers included) with `sharpe_daily` = the development scorecard's `sharpe_daily` of that trial (mean / std(ddof=1) of its finite development daily returns, not annualised, not excess) and `n_periods` = its finite return count. The `double_cost` and `leverage_info` re-runs are not trials and are not appended.
- **Selection rule (development data only):** the configuration with the highest `sharpe_daily`; a tie goes to the lowest `trial_id`. Drawdown, activity and the benchmark comparison are pass criteria (section 8), never selection filters. The selected configuration is the only one run on the holdout.
- The `config` stored per trial is `{"L_vol": <int>, "V": <float>, "f_off": <float>}` for #763 and `{"L_e": <int>, "L_x": <int>, "variant": "<str>"}` for #764, plus `"vol_lookback": 60, "target_vol": 0.10, "gross_cap": 1.0, "rebalance_band": 0.02`.

## 7. Scorecard, benchmark, uplift, and gate inputs (frozen -- inherited from r1, unchanged)

- **Benchmark:** `benchmark_weights(asset_returns, symbol="SPY", target_vol=0.10, lookback=60, gross_cap=1.0)` through the same `simulate_portfolio` call (same costs, band, cash series, master index) as the candidate. This is the baseline for criterion 2 and for the bootstrap uplift (spec 5.2 criterion 2).
- **Scorecard:** `compute_scorecard(result, benchmark, target_vol=0.10, double_cost=<section 5 re-run>, leverage_info=<gross cap 1.5 re-run>)` (`backtest/scorecard.py`), once per phase. `development_result.json` stores it under `scorecard` together with `round_id`, `candidate_id`, `trial_ids`, `selected_trial_id`, `config`, `commit`; `holdout_result.json` the same minus `trial_ids`.
- **Returns file:** `<study dir>/<candidate_id>-development-returns.csv`, one row per development day on the master index, one column per `trial_id` (the simulator's `daily_returns`) plus `benchmark`. Committed with `development_result.json`. The gate inputs below are built from this file and never recomputed after the holdout.
- **`perf_matrix`:** the (T, N) array of the N trial columns in `trial_ids` order, finite rows only. T is the development day count (about 3,670 rows), far above `pbo_n_splits`.
- **`returns_best`:** the `selected_trial_id` column.
- **`uplifts` (the frozen uplift definition):** one value per scored development calendar year Y: `Calmar_Y(selected) - Calmar_Y(benchmark)`, where `Calmar_Y` is the pre-tax Calmar of that column's returns within Y (equity rebased to 1.0 at the first row of Y; Calmar = year return / max drawdown magnitude within Y), using the scorecard's full-year rule for which years count. A year in which either side has zero drawdown is dropped. The candidate's expected n_w is 14; the bootstrap sample is this vector in year order.
- **`all_trial_sharpes`:** `programme_sharpes()` called once after both candidates' trials are appended (expected size 19 backfilled-and-r1 + 18 = 37).
- **`gate_kwargs` for `evaluate_candidate`** (forwarded unchanged to `evaluate_gate`): `pbo_n_splits=16`, `bootstrap_block_length=2`, `bootstrap_n_boot=1000`, `bootstrap_seed=0`, `bootstrap_alpha=0.05`, `dsr_sr_benchmark=0.0`. Thresholds stay at the module constants (DSR >= 0.95, PBO < 0.5, `ci_low` > 0).
- **Continuity line (not a gate):** the verdict document also reports each candidate's median development-year after-tax Calmar next to the repo's older bar of 1.3085 median-window after-tax Calmar vs unscaled SPY (spec 5.2, last paragraph).

## 8. Pass bar, split, and holdout policy (frozen -- inherited from r1, unchanged)

- **Pass bar:** spec 5.2, as implemented by `evaluate_candidate` in `backtest/pipeline_gate.py`: (1) max drawdown at most `MAX_DRAWDOWN` = 0.20 in development and holdout; (2) median development window Calmar strictly above the benchmark's; (3) the overfitting gate passes on all three legs with the programme trial vector; (4) holdout CAGR after costs > 0 and holdout max drawdown at most 0.20; (5) at least `MIN_ROUND_TRIPS_PER_YEAR` = 20 round trips per year and `max_time_share_one_etf` at most `MAX_TIME_SHARE_ONE_ETF` = 0.90, both on development data. The operator confirms this bar by merging this document.
- **Split:** `DEV_END` = 2021-12-31, `HOLDOUT_START` = 2022-01-01 (`backtest/etf_data.py`).
- **Holdout policy:** both candidates are first tests. The holdout runs for both, exactly once each, whatever the development numbers say; no choice is made after seeing development results. Neither candidate is a retest under Phase 4 (h) of the skill: neither family's XA14 cell has had a holdout seen under any earlier `candidate_id` (the r1 holdouts belong to `tsmom_timeseries` and `cross_sectional_rv`, different families; the `donchian_breakout` kills on daily SPY/ES predate the pipeline and hold no XA14 holdout).
- **Holdout method:** the selected configuration is simulated over the full series from the data start (so positions, signals and volatility estimates at 2022-01-01 are the natural carry-in), then cut to rows on or after `HOLDOUT_START`: `equity`, `daily_returns`, `gross_exposure` and `held_weights` sliced to those rows; `trades` restricted to `exit_date` on or after `HOLDOUT_START`; `costs` per key = full-series costs minus the development-only run's costs (the two runs are identical through 2021-12-31). The benchmark, `double_cost` and `leverage_info` runs are cut the same way. The holdout scorecard is `compute_scorecard` on those sliced results. The holdout path appends no trial.
- **Verdict vocabulary:** per the skill's Phase 5 step 5 (`PASS` only with `power="PROMOTABLE"` and `len(window_calmars) >= 13`; otherwise `NO_GO` at PROMOTABLE power when n_w >= 13, else `DIRECTIONAL_NO_GO`). `n_cells` is the candidate's N above.

## 9. Study contract (frozen; the analyst implements it, the orchestrator runs the holdout)

- One script per candidate in the study directory, `--phase development|holdout`, repo root on `sys.path`, imports from `backtest/` read-only: `load_daily_bars` (`etf_data`), `inverse_vol_weights` and `vol_target_weights` and `benchmark_weights` (`vol_target`), `simulate_portfolio`, `CostModel`, `round_trips_per_year` (`portfolio`), `compute_scorecard` (`scorecard`), `TrialRecord` and `append_trials` (`trial_store`), `record_result` (`etf_data`, holdout path only). Shared conventions live in a shared module in the study directory (the r1 `etf_daily_r1_common.py` shape: the basket build, the sizing chain, the benchmark, the holdout slicing, the returns CSV, the payload helpers, with the r2 identifiers and the #763 gate multiplication as a per-candidate step in its runner).
- Development path: loads bars with `phase="development"`, evaluates exactly the grid of section 6, appends the N trials with one `append_trials` call, writes `<candidate_id>-development-returns.csv` and `<candidate_id>-development-payload.json`, and never calls `record_result`.
- Holdout path: reads `selected_trial_id` and `config` from `development_result.json`, loads bars with `phase="holdout"` and `candidate_id`, runs only that configuration plus the benchmark and the two re-runs as section 8 says, and calls `record_result(candidate_id, "holdout", payload)` in the same process. It is written and committed by the analyst and run only by the orchestrating session.
- The analyst never runs `python3` outside the worktree root, never writes outside the study directory, and never loads holdout bars. On this box the analyst runs `venv/bin/python` (the system `python3` lacks `requirements.txt`); the dispatch prompt states this explicitly.

## 10. Parity check (spec 5.6) and what exists before this commit

- **Parity (spec 5.6):** a fresh `run_etf_parity` run over the full frozen list (15 tickers, window 2019-01-01 to `DEV_END`, GET-only market-data read) was made this session, after #757's suspect-window gating and cent allowance landed. Verdict table, verbatim:

```
ticker    n_days  median_bps   p99_bps   n_yf  n_alpaca  n_gated  gated_med  gated_p99  med_max  mean_bps verdict
SPY          756       1.411    37.866    757       757      707      1.259     10.695    1.098    -0.011 FAIL median+p99
QQQ          756       0.118     2.685    757       757      707      0.118      2.735    1.120     0.021 PASS
IWM          756       1.553    35.763    757       757      707      1.394     15.957    1.201    -0.022 FAIL median+p99
EFA          756       0.727     7.628    757       757      707      0.721      7.168    1.536     0.003 PASS
EEM          756       1.115    11.740    757       757      707      1.075      9.904    1.761    -0.013 PASS
VNQ          756       0.548    15.579    757       757      707      0.524     11.193    1.424     0.012 FAIL p99
TLT          756       0.242     0.807    757       757      707      0.241      0.809    1.244     0.001 PASS
IEF          756       0.322     0.982    757       757      707      0.328      0.984    1.297    -0.001 PASS
LQD          756       0.336    11.002    757       757      707      0.335      3.172    1.278     0.000 PASS
HYG          756       0.519     7.226    757       757      707      0.499      5.144    1.480    -0.001 PASS
TIP          756       0.323     1.049    757       757      707      0.319      1.036    1.300     0.001 PASS
GLD          756       0.000     9.788    757       757      707      0.000      6.014    1.180    -0.000 PASS
DBC          756       2.063     7.963    757       757      707      2.092      7.477    3.195    -0.000 PASS
UUP          756       1.402     4.266    757       757      707      1.407      4.292    2.337     0.004 PASS
BIL          756       0.220     1.094    757       757      707      0.219      1.094    1.382    -0.001 PASS
```

  3 of 15 FAIL (SPY, IWM on median+p99; VNQ on p99), against 8 of 15 in r1's run. The improvement is mechanical, not data-side: #757 added the 2020-02-24 to 2020-04-30 suspect-window gating and the cent-price allowance that r1's run predated. The remaining failures are the same two causes r1 section 10.1 analysed and the operator adjudicated (Alpaca-side March 2020 closes: SPY's worst suspect days are 268.8, 263.8 and 221.5 bps against yfinance's official closes; cent-rounded Alpaca prints on low-priced names), plus p99 tails from a handful of quarter-end 2020 days. The research data are yfinance's official closes in both rounds and are unaffected; the basket is unchanged from the round the operator explicitly kept after seeing the same failures. The full per-ticker output is pasted in the freeze PR; a failing ticker is discussed there before the merge, and the basket is not changed silently.
- The two candidate issues (#763, #764) and the verbatim novelty-check output they carry (`venv/bin/python -m backtest.tested_cells --check ...`, run this session; reads only the ledger).
- `programme_sharpes().size == 19` (5 backfilled + 14 from r1).
- No bars loaded, no returns, Sharpe, equity curve, weight or trade computed for either r2 candidate or for the benchmark on this basket (the r1 runs are the committed record and are not recomputed).

## 11. Non-goals

Per the skill's Non-goals: no live change, no edits under `supabase/functions/`, no broker or Supabase call, no re-opened holdout, no budget beyond 50 without an authorizing comment on #762 (and none above the operator's 30 this round), no merging of the freeze or results PR by the session, no closing of candidate issues, no new gate criteria, ledger verdict values or scorecard rows inside the round. The `vol_regime_gating` ledger row expected at results will trip `tests/test_weekly_review.py::test_untested_candidates_are_absent_from_the_ledger`; per the skill that is raised on #762 as its own issue, not fixed inside the round. The unpicked candidates (#765, #766) are not run and their issues stay open.

---

**Freeze banner.** Everything above this line is the frozen pre-registration. Results land as dated addenda below this line (results PR), never as edits above it.
