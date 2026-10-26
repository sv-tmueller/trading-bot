# AI Research Pipeline (Project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the research-only tooling that lets AI agents propose, pre-register, test and score daily multi-ETF strategy candidates against the operator's 30%-drawdown-cap bar, with a mechanical holdout and programme-wide luck accounting, then run round 1.

**Architecture:** Small focused modules in `backtest/` (portfolio simulator, vol-target sizing, holdout-locked data loader, trial store, scorecard, five-criterion gate), ledger backfill in `backtest/tested_cells.py`, GitHub `candidate` label plus templates, and a `research-round` skill that orchestrates a round. Nothing touches `supabase/functions/` or a broker order path.

**Tech Stack:** Python 3.9, pandas, numpy, yfinance (existing research deps), pytest; `gh` CLI; Markdown skills.

**Spec:** `docs/superpowers/specs/2026-10-23-ai-research-pipeline-design.md` (section numbers below point at it).

## Global Constraints

- CLAUDE.md Architectural invariants are a hard review gate; any violation is a must-fix finding.
- Research-only: no file under `supabase/functions/` changes; no module here is imported by `supabase/functions/`.
- No broker order path. `CLAUDE_AGENT_NO_BROKER=1` for every session. The only Alpaca call allowed is the GET-only market-data fetch in Task 10.
- No LLM is called from any module; the AI's role is in the skill (Task 11), never in code paths that compute results.
- Every Python file starts with `from __future__ import annotations` (Python 3.9).
- Tests make no network calls: data fetchers are injected and faked.
- Test command: `python3 -m pytest tests/<file> -v` (system Python 3.9.6, pytest 8.4.2; `venv/` does not exist in fresh worktrees).
- Development period ends `2021-12-31`; holdout starts `2022-01-01` (spec 5.3).
- Gross exposure cap `1.0` for every verdict run; `1.5` only for the information line (spec 3, 5.5).
- Default cost: `5` bps per side slippage, `0` bps commission (= the repo's 0.05% per side; `backtest/regime.py` `SLIPPAGE_BPS`).
- Pass-bar constants (spec 5.2): vol target `0.10`, max drawdown `0.20`, min round trips per year `20`, max time share of one ETF `0.90`.
- Round budget `50` new configurations (spec 5.4).
- New prose avoids em dashes (CLAUDE.md "Writing conventions").

## Review Focus

1. **ETFs with different inception dates (NaN prices before listing).** Expect: an asset with a NaN open or close on a day gets weight 0 that day and is never traded or valued at NaN. Test in Task 1.
2. **Vol-target scaling pushing gross exposure over the cap.** Expect: `sum(|w|) <= gross_cap` on every row after scaling, including with shorts. Test in Task 2.
3. **Long-to-short flip in one step.** Expect: the long lot closes (one round trip), a short lot opens, and the short's P&L is positive when price falls. Test in Task 1.
4. **Holdout leakage through cached or wider fetches.** Expect: development-phase loads never return a row after `2021-12-31`, even if the fetcher returns more. Test in Task 3.
5. **Partial resizes and the tax layer.** Expect: a resize that reduces a position realizes P&L as a `partial` trade (counted by `apply_annual_netting_tax`) but is not counted as a round trip. Test in Task 1.

---

## Batch plan

| Batch | Tasks | Precondition |
|---|---|---|
| 1 | 1-6 (independent of each other) | none |
| 2 | 7-11 | batch 1 merged |
| 3 | Round 1 itself, run with the Task 11 skill | batch 2 merged; PR #676 merged; the two 2026-10-22 research branches (`research/multi-symbol-hourly`, `research/spy-intraday-momentum`) pushed and merged by the operator (they have no PRs today), each adding its own `tested_cells.py` records (spec 6 backfill; these intraday cells inform novelty checks only and never enter the daily-allocation DSR vector) |

---

### Task 1: Long/short portfolio simulator

**Files:**
- Create: `backtest/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `CostModel(slippage_bps: float = 5.0, commission_bps: float = 0.0, borrow_bps_annual: float = 50.0, financing_spread_bps_annual: float = 100.0)`, frozen dataclass.
  - `PortfolioResult` dataclass: `equity: pd.Series`, `daily_returns: pd.Series`, `gross_exposure: pd.Series`, `held_weights: pd.DataFrame`, `trades: list[dict]`, `costs: dict` (keys `trading`, `borrow`, `financing`, `cash_interest`, currency units).
  - Each trade dict has `regime.Trade` fields (`entry_date, exit_date, entry_price, exit_price, qty, pnl, return_pct, exit_reason`) plus `symbol: str`, `side: "long"|"short"`, `kind: "round_trip"|"partial"`.
  - `simulate_portfolio(target_weights: pd.DataFrame, opens: pd.DataFrame, closes: pd.DataFrame, cash_returns: pd.Series, *, starting_equity: float = 100_000.0, costs: CostModel = CostModel(), gross_cap: float = 1.0, rebalance_band: float = 0.02) -> PortfolioResult`
  - `round_trips_per_year(result: PortfolioResult) -> float`

Semantics to implement (decided here): weights in `[-1, 1]` per column, row `sum(|w|) <= gross_cap` (raise `ValueError` otherwise); close-T target fills at T+1 open; a position is changed only when `|target - held| > rebalance_band` or the target crosses zero; fractional quantities; a lot opens when weight leaves 0 or changes sign and closes (`round_trip`) when it returns to 0 or changes sign; a reduction without closing emits a `partial` trade for the reduced quantity; short P&L = `(entry - exit) * qty`; borrow accrues daily on short notional at `borrow_bps_annual / 252`; cash net of short-sale proceeds earns `cash_returns`, floored at zero (`interest_base = max(cash - short_notional, 0)`, short notional marked at the close; short proceeds earn nothing, as on a retail Alpaca account); negative cash (only possible when `gross_cap > 1`) pays `cash_returns + financing_spread_bps_annual / 252`.

**Amendment 2026-10-26 (#693): retail cash model.** This sentence originally read "positive cash earns `cash_returns`", which paid T-bill interest on short-sale proceeds. A retail Alpaca account pays nothing on short proceeds and the long-only vol-targeted SPY benchmark can never earn it, so a shorting candidate would have carried a tailwind in the 2022+ holdout (T-bills at 4 to 5 percent) that the live account cannot earn. Interest now accrues only on cash net of short notional, floored at zero. Borrow, financing on negative cash, the benchmark mechanism and vol-target sizing are unchanged; spec 5.6 ("idle cash earns a stated T-bill proxy") already matches, so the spec is not edited. This lands before any candidate or benchmark is scored, because the holdout runs once.

- [ ] **Step 1: Write the failing tests**

```python
def test_constant_long_weight_buys_once_and_holds(): ...
    # 1 asset, weight 0.5 every day -> exactly 1 entry fill, 0 round trips until end
def test_flip_long_to_short_closes_and_reopens():
    # weights [0.5, 0.5, -0.5, -0.5], price falls after the flip
    r = simulate_portfolio(...)
    rts = [t for t in r.trades if t["kind"] == "round_trip"]
    assert len(rts) == 1 and rts[0]["side"] == "long"
    # mark-to-market: equity rises while short and price falls
    assert r.equity.iloc[-1] > r.equity.iloc[2]
def test_partial_resize_emits_partial_not_round_trip():
    # weights [0.8, 0.8, 0.4, 0.4] -> one "partial" trade, round_trips_per_year counts 0 for it
def test_nan_price_asset_never_traded():
    # asset B NaN for first 3 days, target weight 0.3 throughout -> no B trade before day 4, no NaN in equity
def test_gross_cap_violation_raises():
    with pytest.raises(ValueError): simulate_portfolio(weights_with_row_sum_abs_1_2, ...)
def test_borrow_cost_accrues_on_shorts():
    # flat price, constant -0.5 weight, borrow 252 bps/yr over 252 days -> costs["borrow"] ~= 0.5 * equity * 0.0252 (rel tol 5%)
def test_trades_feed_annual_netting_tax():
    from backtest.tax import apply_annual_netting_tax
    after = apply_annual_netting_tax(r.trades, r.equity)
    assert after.iloc[-1] <= r.equity.iloc[-1]
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `python3 -m pytest tests/test_portfolio.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `backtest/portfolio.py` per the interfaces and semantics above.**

- [ ] **Step 4: Run tests, confirm they pass; also run `python3 -m pytest tests/test_weighted_simulator.py tests/test_tax.py -v` (unchanged modules still green).**

- [ ] **Step 5: Commit** `feat(backtest): long/short portfolio simulator for the research pipeline`

---

### Task 2: Volatility-target sizing and benchmark weights

**Files:**
- Create: `backtest/vol_target.py`
- Test: `tests/test_vol_target.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `inverse_vol_weights(signals: pd.DataFrame, asset_returns: pd.DataFrame, *, lookback: int = 60) -> pd.DataFrame`: `signals` in `{-1, 0, 1}`; weight `= signal / vol_i`, normalized so `sum(|w|) = 1` on rows with any signal; uses returns up to and including T only.
  - `vol_target_weights(raw_weights: pd.DataFrame, asset_returns: pd.DataFrame, *, target_vol: float = 0.10, lookback: int = 60, gross_cap: float = 1.0) -> pd.DataFrame`: scale `= target_vol / sqrt(w' Σ w * 252)` with `Σ` the rolling `lookback`-day covariance ending at T; then if `sum(|w|) > gross_cap`, rescale to the cap. Rows inside the warm-up window are 0.
  - `benchmark_weights(asset_returns: pd.DataFrame, *, symbol: str = "SPY", target_vol: float = 0.10, lookback: int = 60, gross_cap: float = 1.0) -> pd.DataFrame`: raw weight 1.0 on `symbol`, other columns 0, passed through `vol_target_weights` (spec 5.2 criterion 2: same mechanism, same cap).

- [ ] **Step 1: Write the failing tests**

```python
def test_gross_never_exceeds_cap_with_shorts():
    w = vol_target_weights(raw_with_mixed_signs, low_vol_returns, target_vol=0.10, gross_cap=1.0)
    assert (w.abs().sum(axis=1) <= 1.0 + 1e-12).all()
def test_scaling_hits_target_when_cap_not_binding():
    # synthetic iid returns, 30% annual vol, single asset -> scale ~ 1/3 (rel tol 15%)
def test_no_lookahead():
    # changing returns on day T+1 does not change weights on day T
def test_warmup_rows_are_zero(): ...
def test_benchmark_is_spy_only_and_capped():
    b = benchmark_weights(rets)
    assert (b.drop(columns="SPY") == 0).all().all() and (b["SPY"] <= 1.0).all()
```

- [ ] **Step 2: Run, confirm FAIL.** `python3 -m pytest tests/test_vol_target.py -v`
- [ ] **Step 3: Implement per the interfaces.**
- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** `feat(backtest): vol-target sizing and vol-targeted SPY benchmark`

---

### Task 3: Holdout-locked daily ETF data loader

**Files:**
- Create: `backtest/etf_data.py`
- Test: `tests/test_etf_data.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Constants `DEV_END = date(2021, 12, 31)`, `HOLDOUT_START = date(2022, 1, 1)`, `PIPELINE_DIR = Path("docs/research/pipeline")`.
  - `class HoldoutLockedError(RuntimeError)`.
  - `load_daily_bars(tickers: list[str], *, phase: str, candidate_id: Optional[str] = None, pipeline_dir: Path = PIPELINE_DIR, fetch: Optional[Callable[[str], pd.DataFrame]] = None) -> dict[str, pd.DataFrame]`: `fetch` defaults to a yfinance adjusted-daily fetch (OHLC columns `Open, High, Low, Close`). `phase="development"` truncates every frame to `<= DEV_END`. `phase="holdout"` requires `candidate_id`, requires `<pipeline_dir>/<candidate_id>/development_result.json` to exist and `holdout_result.json` to be absent, else raises `HoldoutLockedError`; returns full history (development rows are needed for indicator warm-up).
  - `record_result(candidate_id: str, phase: str, payload: dict, *, pipeline_dir: Path = PIPELINE_DIR) -> Path`: writes `<phase>_result.json` (sorted keys, indent 2); raises `HoldoutLockedError` if `holdout_result.json` already exists (the holdout runs once).

- [ ] **Step 1: Write the failing tests** (all use a fake `fetch` returning 2019-2023 rows, and `tmp_path` as `pipeline_dir`)

```python
def test_development_never_returns_post_2021_rows():
    bars = load_daily_bars(["SPY"], phase="development", fetch=fake, pipeline_dir=tmp_path)
    assert bars["SPY"].index.max() <= pd.Timestamp("2021-12-31")
def test_holdout_locked_without_development_result():
    with pytest.raises(HoldoutLockedError): load_daily_bars(["SPY"], phase="holdout", candidate_id="c1", fetch=fake, pipeline_dir=tmp_path)
def test_holdout_unlocks_after_development_result_recorded(): ...
def test_holdout_runs_once():
    record_result("c1", "development", {...}, pipeline_dir=tmp_path)
    record_result("c1", "holdout", {...}, pipeline_dir=tmp_path)
    with pytest.raises(HoldoutLockedError): record_result("c1", "holdout", {...}, pipeline_dir=tmp_path)
    with pytest.raises(HoldoutLockedError): load_daily_bars(["SPY"], phase="holdout", candidate_id="c1", fetch=fake, pipeline_dir=tmp_path)
def test_unknown_phase_raises_value_error(): ...
```

- [ ] **Step 2: Run, confirm FAIL.** `python3 -m pytest tests/test_etf_data.py -v`
- [ ] **Step 3: Implement per the interfaces.**
- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** `feat(backtest): holdout-locked daily ETF loader`

---

### Task 4: Programme trial store

**Files:**
- Create: `backtest/trial_store.py`, `docs/research/pipeline/trials.json` (initial content `[]`)
- Test: `tests/test_trial_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DAILY_ALLOCATION = "daily_allocation"`, `ROUND_BUDGET = 50`, `DEFAULT_PATH = Path("docs/research/pipeline/trials.json")`.
  - `TrialRecord` frozen dataclass: `trial_id: str, round_id: str, candidate_id: str, space: str, config: dict, sharpe_daily: float, n_periods: int, source: str, date: str`. `sharpe_daily` is non-annualized (the scale `overfitting_gate.deflated_sharpe_ratio` expects).
  - `class BudgetExceededError(RuntimeError)`.
  - `load_trials(path: Path = DEFAULT_PATH) -> list[TrialRecord]`
  - `append_trials(records: list[TrialRecord], *, path: Path = DEFAULT_PATH, round_budget: int = ROUND_BUDGET) -> None`: rejects duplicate `trial_id` (`ValueError`); raises `BudgetExceededError` if the round's total after appending exceeds `round_budget`, except for `round_id == "backfill"` (prior trials do not consume round budget). Writes sorted by `trial_id`, indent 2, so diffs stay reviewable.
  - `programme_sharpes(space: str = DAILY_ALLOCATION, path: Path = DEFAULT_PATH) -> np.ndarray`

- [ ] **Step 1: Write the failing tests**

```python
def test_roundtrip_load_append(tmp_path): ...
def test_duplicate_trial_id_rejected(tmp_path): ...
def test_round_budget_enforced(tmp_path):
    append_trials([rec(i, round_id="r1") for i in range(50)], path=p)
    with pytest.raises(BudgetExceededError): append_trials([rec(50, round_id="r1")], path=p)
def test_backfill_round_not_budgeted(tmp_path): ...
def test_programme_sharpes_filters_by_space(tmp_path):
    assert programme_sharpes(DAILY_ALLOCATION, path=p).shape == (n_daily,)
```

- [ ] **Step 2: Run, confirm FAIL.** `python3 -m pytest tests/test_trial_store.py -v`
- [ ] **Step 3: Implement per the interfaces; create `docs/research/pipeline/trials.json` as `[]`.**
- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** `feat(backtest): programme-wide trial store for DSR accounting`

---

### Task 5: Ledger backfill for the 2026-06-24 surveys

**Files:**
- Modify: `backtest/tested_cells.py` (append to `LEDGER`)
- Test: `tests/test_tested_cells.py`

**Interfaces:**
- Consumes: existing `TestedCell`, `check_novel`, `cumulative_trials`.
- Produces: new ledger records. Family names (fixed here so later tasks and the skill use them): `dual_momentum_gem`, `faber_ma_timing`, `tsmom_timeseries`, `vol_target`. Vehicles: `SPY` for single-asset cells; `ETF_BASKET_GEM` (SPY/EFA/AGG/BIL) and `ETF_BASKET_GTAA5` (SPY/EFA/AGG/DBC/VNQ) for basket cells. Cadence `daily`.

Read `docs/research/2026-06-24-candidate-strategy-survey-first-cut.md` and `...-second-cut.md` for each record's `n_cells`, `verdict`, `power`, `note`; cite the doc as `source`. The tsmom-12mo and Faber-10mo single-asset baselines count as tested cells.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("family,vehicle", [
    ("faber_ma_timing", "SPY"), ("faber_ma_timing", "ETF_BASKET_GTAA5"),
    ("dual_momentum_gem", "ETF_BASKET_GEM"), ("tsmom_timeseries", "SPY"), ("vol_target", "SPY")])
def test_june_survey_cells_not_novel(family, vehicle):
    assert check_novel(family, "daily", vehicle)["novel"] is False
```

- [ ] **Step 2: Run, confirm FAIL.** `python3 -m pytest tests/test_tested_cells.py -v`
- [ ] **Step 3: Append the records.**
- [ ] **Step 4: Run the full ledger test file, confirm PASS; run `python3 -m backtest.tested_cells` and confirm the new families appear in the table.**
- [ ] **Step 5: Commit** `docs(ledger): backfill 2026-06-24 survey cells`

---

### Task 6: `candidate` label, issue template, scorecard template

**Files:**
- Create: `.github/ISSUE_TEMPLATE/candidate.md`, `docs/research/pipeline/README.md`
- Modify: `docs/research/README.md` (one paragraph pointing at `pipeline/`)

**Interfaces:**
- Produces: label `candidate` (color `5319E7`, description "Strategy candidate from the AI research pipeline; operator decides"); the issue template body has exactly the seven headed sections of spec 5.1 in order (Idea, Why it might work, Evidence so far, Novelty check, Data feasibility, Proposed test, AI recommendation); `docs/research/pipeline/README.md` holds the directory layout (`trials.json`, `<candidate_id>/development_result.json`, `<candidate_id>/holdout_result.json`), the scorecard table of spec 5.5 verbatim as the template, and the verdict/recommendation footer.

- [ ] **Step 1: Create the two files.**
- [ ] **Step 2: Verify:** `grep -c '^## ' .github/ISSUE_TEMPLATE/candidate.md` prints `7`; front matter contains `labels: candidate`; no em dashes (`grep -c '—'` prints `0` on each new file).
- [ ] **Step 3: Create the label:** `gh label create candidate --color 5319E7 --description "Strategy candidate from the AI research pipeline; operator decides" --force`; verify with `gh label list | grep candidate`.
- [ ] **Step 4: Commit** `docs(pipeline): candidate issue template and scorecard template`

---

### Task 7: Scorecard metrics (batch 2)

**Files:**
- Create: `backtest/scorecard.py`
- Test: `tests/test_scorecard.py`

**Interfaces:**
- Consumes: `PortfolioResult`, `round_trips_per_year` (Task 1); `apply_annual_netting_tax` (`backtest/tax.py`).
- Produces:
  - `compute_scorecard(result: PortfolioResult, benchmark: PortfolioResult, *, target_vol: float, double_cost: Optional[PortfolioResult] = None, leverage_info: Optional[PortfolioResult] = None) -> dict` with keys: `cagr`, `cagr_after_tax`, `max_drawdown`, `max_drawdown_start`, `max_drawdown_end`, `calmar`, `sharpe_annual`, `sharpe_daily`, `target_vol`, `realized_vol`, `worst_year`, `year_returns` (dict year to return), `window_calmars` (after-tax Calmar per calendar year, the repo's n_w convention), `round_trips_per_year`, `avg_holding_days`, `max_time_share_one_etf`, `cost_drag_per_year`, `borrow_cost_per_year`, `benchmark` (same metric subset for `benchmark`), `double_cost` and `leverage_info` (`cagr`, `max_drawdown`, `calmar`, or `None`).
  - `render_scorecard_markdown(development: dict, holdout: Optional[dict], verdict: Optional[dict]) -> str`: the spec 5.5 table, holdout column `n/a` when `None`.

- [ ] **Step 1: Failing tests:** known synthetic equity curve gives exact `max_drawdown` and dates; a curve that is flat then -10% then recovers gives `calmar = cagr / 0.10`; `max_time_share_one_etf` is `1.0` for a single always-held asset; rendered markdown contains every row label of spec 5.5.
- [ ] **Step 2: Run, confirm FAIL.** `python3 -m pytest tests/test_scorecard.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** `feat(backtest): research pipeline scorecard`

---

### Task 8: Five-criterion candidate gate (batch 2)

**Files:**
- Create: `backtest/pipeline_gate.py`
- Test: `tests/test_pipeline_gate.py`

**Interfaces:**
- Consumes: scorecard dicts (Task 7); `programme_sharpes` (Task 4); `evaluate_gate` (`backtest/overfitting_gate.py`).
- Produces:
  - Constants `MAX_DRAWDOWN = 0.20`, `MIN_ROUND_TRIPS_PER_YEAR = 20`, `MAX_TIME_SHARE_ONE_ETF = 0.90`.
  - `evaluate_candidate(development: dict, holdout: Optional[dict], *, returns_best: np.ndarray, all_trial_sharpes: np.ndarray, perf_matrix: np.ndarray, uplifts: np.ndarray, gate_kwargs: Optional[dict] = None) -> dict` returning `{"passed": bool, "criteria": {"drawdown": {...}, "beats_benchmark": {...}, "luck": {...}, "holdout": {...}, "activity": {...}}}`, each `{"passed": bool, "detail": str}`. `holdout=None` makes `holdout.passed=False` with detail "holdout not yet run". Criterion mapping exactly as spec 5.2: drawdown on both columns; beats_benchmark = median `window_calmars` > benchmark median; luck = `evaluate_gate(...)["passed"]`; holdout = `cagr > 0` and `max_drawdown <= 0.20`; activity = both thresholds.

- [ ] **Step 1: Failing tests:** one passing fixture; one fixture per criterion that fails only that criterion and asserts the other four pass; `holdout=None` fails only `holdout`.
- [ ] **Step 2-4:** run FAIL, implement, run PASS (`python3 -m pytest tests/test_pipeline_gate.py -v`).
- [ ] **Step 5: Commit** `feat(backtest): five-criterion candidate gate`

---

### Task 9: Prior-trial Sharpe backfill (batch 2)

**Files:**
- Create: `backtest/run_trial_backfill.py`
- Modify: `docs/research/pipeline/trials.json`
- Test: `tests/test_run_trial_backfill.py`

**Interfaces:**
- Consumes: `load_daily_bars(phase="development")` (Task 3), `append_trials` with `round_id="backfill"` (Task 4), existing `backtest/baselines.py` signals and `backtest/run_candidate_survey.py` strategy definitions.
- Produces: one `TrialRecord` per prior same-space configuration (spec 5.4: TSMOM, Faber single and GTAA-lite, GEM, vol-target 10%), `space=DAILY_ALLOCATION`, Sharpe computed on the development period only, `source` citing the original verdict doc.

- [ ] **Step 1: Failing test** with a fake fetch: the script produces exactly the configured trial ids, every `sharpe_daily` finite, rerun is idempotent (no duplicates, no error).
- [ ] **Step 2-4:** FAIL, implement `main(argv) -> int` with `--dry-run`, PASS.
- [ ] **Step 5: Run for real** (`python3 -m backtest.run_trial_backfill`), commit the populated `trials.json` with the script: `feat(backtest): backfill prior daily-allocation trials`

---

### Task 10: Alpaca daily-bar parity check (batch 2)

**Files:**
- Create: `backtest/run_etf_parity.py`
- Test: `tests/test_run_etf_parity.py`

**Interfaces:**
- Consumes: `fetch_bars` from `backtest/run_fetch_spy_intraday.py` (GET-only, `timeframe="1Day"`), `load_daily_bars` (Task 3; the parity window is development-period only: `2019-01-01` to `2021-12-31`).
- Produces: `compare_daily_returns(yf_close: pd.Series, alpaca_close: pd.Series) -> dict` with `n_days`, `median_abs_diff_bps`, `p99_abs_diff_bps`, `passed` where `passed = median_abs_diff_bps < 1.0 and p99_abs_diff_bps < 10.0`; CLI prints one row per ticker and exits 1 if any ticker fails.

- [ ] **Step 1: Failing tests:** identical series pass; a series with one 50 bps outlier in 500 days still passes the median but reports the p99; a constant 2 bps daily offset fails.
- [ ] **Step 2-4:** FAIL, implement, PASS. Tests never call `fetch_bars` (inject a fake).
- [ ] **Step 5: Commit** `feat(backtest): yfinance vs Alpaca daily parity check`

---

### Task 11: `research-round` skill (batch 2)

**Files:**
- Create: `.claude/skills/research-round/SKILL.md`
- Modify: `CLAUDE.md` ("Current skills relevant to engineering work" list: one bullet)

**Interfaces:**
- Consumes: everything above by name.
- Produces: a skill that, when the operator says "start a research round", runs these steps in order and stops at each operator decision point:
  1. Pre-flight: read CLAUDE.md invariants, the spec, `docs/research/strategy-landscape-and-risk/strategies.md`; `CLAUDE_AGENT_NO_BROKER=1`.
  2. Propose 3-5 candidates; for each run `check_novel` and include its output; file one `candidate` issue each using the template. **Stop: operator picks.**
  3. Draft the freeze PR (pre-registration doc `docs/research/YYYY-MM-DD-<round>-preregistration.md` freezing ETF list, grid, N, costs, vol target, CSCV splits, bootstrap block length, `n_boot`, borrow/cash/financing rates). **Stop: operator merges.**
  4. After merge: dispatch the analyst agent per candidate (development phase only), append trials, record `development_result.json`, then run the holdout once, record `holdout_result.json`.
  5. Results PR: verdict doc, ledger rows, `trials.json`; post the rendered scorecard and `evaluate_candidate` verdict with a recommendation (promote / reject / retest at full power) on each issue. **Stop: operator decides.**
- Never: edit `supabase/functions/`, place broker calls, re-open a holdout, or exceed the round budget without an operator comment authorizing it on the round issue.

- [ ] **Step 1: Write the skill** following the `research-bundle` skill's structure (Inputs, Pre-flight, Phases, Quality bar, Non-goals).
- [ ] **Step 2: Verify:** every module and function name it cites exists (`grep` each against `backtest/`); no em dashes; CLAUDE.md bullet added.
- [ ] **Step 3: Commit** `docs(skill): research-round orchestrator`

---

## Batch 3 (not code): round 1

Run `/research-round` (the Task 11 skill) after the batch 3 preconditions above hold. Expected seed candidates per spec 5.7. Output: candidate issues, freeze PR, results PR, scorecards, operator decision per candidate.
