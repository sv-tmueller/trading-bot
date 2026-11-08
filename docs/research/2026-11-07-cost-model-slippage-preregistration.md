# Cost-model slippage recalibration -- pre-registration

**Question:** The research pipeline's frozen `CostModel` charges 5.0bps of per-side slippage
(`backtest/portfolio.py::CostModel.slippage_bps`, re-exported as `SLIPPAGE_BPS` from
`backtest/regime.py`). The nightly reflection engine's trigger 3 ("cost divergence",
`backtest/reflection.py::TRIGGER_3_LOW_MULTIPLE = 0.5`) has fired every trading day since
2026-09-23, printing 0.08x to 0.16x (n=40) against that model. Should the per-side slippage
assumption be recalibrated to a value estimated from realized paper-account fills, and if so
to which value in {1, 2, 3, 5}bps?

**Hypothesis issue:** #772 ("Hypothesis: re-examine the frozen 5bps cost model (realized paper
slippage has run at 0.08-0.16x of it for six weeks)"). **Batch:** #774, size:M, full track.
**Date:** 2026-11-07. **Author:** Claude Code developer session (research only;
`CLAUDE_AGENT_NO_BROKER=1`; no broker call, no Supabase call, no production code touched).

This document is committed and merged **before** any windowed distributional statistic is
computed. It freezes the data source, the windows, the fill universe, the candidate grid, the
stopping rule, the tail quantiles and the reproduction gate. The results land in a sibling
verdict doc (`docs/research/2026-11-07-cost-model-slippage-verdict.md`), never as an edit here.

---

## 0. Invariant framing

CLAUDE.md "Architectural invariants" and "Writing conventions" apply by reference. This study is
research only: it edits nothing under `supabase/functions/`, makes no broker or Supabase call,
promotes nothing, and adds no decision rule to the trading path. It reads one committed JSONL
ledger and writes under `docs/research/`. `backtest/portfolio.py` (the `CostModel`),
`backtest/regime.py` (`SLIPPAGE_BPS`), `backtest/reflection.py` and everything under `supabase/`
are **not** touched; the verdict informs an operator gate decision, it does not make it. The
5.0bps model is a research-side convention, not a live-bot config value.

## 1. Data source (frozen)

- **The only data source:** `docs/trading-journal/daily-verification.jsonl`, the committed
  ledger appended daily by `.github/workflows/daily-verification.yml` through
  `scripts/apply_reflection.ts`. Read-only. The issue body's "plus audit_log/trades if needed
  for sample size" clause is **superseded** by the batch-scope refinement (#774): no Supabase
  read, no broker read, no network, no second source.
- 60 records, `environment: "dev"`, dates 2026-08-03 to 2026-11-06.
- Per-fill slippage lives at `reflection.trades[i].entry_slippage_bps` and
  `reflection.trades[i].exit_slippage_bps` (signed floats, bps).
- 52 of 60 records carry a `reflection` key (engine `reflection-v1`); the first is 2026-08-13,
  matching the issue's "reflection engine's start". The 8 pre-ship rows carry no `reflection`
  key and contribute nothing, mirroring `build_trailing_window`'s semantics (no backfill).
- **Freeze slice:** every test and the study itself slice the record set to `date <= 2026-11-06`.
  The ledger keeps growing while this PR is open; the slice pins the frozen numbers.
- Mechanical counts at the freeze (permitted here; no distributional statistic is computed
  before this document lands): 51 unique trades (no duplicated `entry_order_id` within the
  slice), 102 fills (every trade carries both an entry and an exit slippage), 2 fills per trade.

## 2. Windows and window assignment (frozen)

- **Assignment rule:** a fill belongs to the window of its **own JSONL record's `date` field**,
  not its `exit_fill_time`. Rationale: the record date is the ledger's own partition key and is
  what the append workflow controls; `exit_fill_time` can straddle a boundary and would make the
  split depend on a data detail the study does not model.
- **Calibration window:** records with `2026-08-13 <= date <= 2026-09-30`. Mechanical count:
  **56 fills**.
- **Validation window:** records with `2026-10-01 <= date <= 2026-11-06` (the freeze date).
  Mechanical count: **46 fills**.
- **Freeze date:** 2026-11-07. Records after it do not exist at freeze time and are excluded by
  the slice regardless.

## 3. Fill universe (frozen)

The model unit is a **per-side** cost, so the study pools both sides:

- For every trade in the window, include `abs(entry_slippage_bps)` when it is non-null and
  `abs(exit_slippage_bps)` when it is non-null. Null values are dropped, never zero-filled.
- 2 fills per trade in the current data; the pooling rule does not assume it.
- Absolute value, because the model charges a cost per side regardless of direction; the sign
  encodes which way the fill moved, not the magnitude the model needs.

## 4. Candidate grid (frozen)

`{1, 2, 3, 5}` bps per side. The grid is descriptive: for each candidate `c` and each window the
study reports the median with its bootstrap CI, the IQR, p90/p95/max, the fraction of fills
exceeding `c`, and trigger 3's ratio statistic recomputed with `model_bps = c` (showing how the
trigger's firing would change under each candidate). Those per-candidate numbers are output, not
the gate; the gate is section 5's stopping rule.

## 5. Stopping rule (frozen)

Answer **"recalibration proposed"** if and only if **both** clauses hold:

- **(a) Validation CI clause:** the validation-window median |slippage| has a **one-sided 95%
  bootstrap CI upper bound below 5.0bps**.
- **(b) Rolling clause:** **every** rolling window of 40 pooled fills whose **last fill comes
  from a validation-window record** has median |slippage| below 5.0bps.

If both hold, the **proposed per-side value** is the smallest candidate in {1, 2, 3, 5} that is
**>= the validation-window CI upper bound** (conservative: the proposed model never sits below
the plausible realized median). If either clause fails, **the 5.0bps model stands** and trigger
3's firing line is recorded as structurally expected (a conservative model always "diverges"
downward, so the trigger carries no information once the realized distribution is known).

### 5.1 Bootstrap (frozen verbatim)

- **Resampling unit:** the validation-window pooled fills (n = 46 at the freeze).
- **Procedure:** 10,000 resamples of size n with replacement; the statistic per resample is the
  median of the resampled fills.
- **RNG:** `numpy.random.default_rng(0)`, a single generator drawn from once for the whole run of
  10,000 resamples, in resample order. `seed = 0`.
- **Upper bound:** `numpy.percentile(boot_medians, 95)` with numpy's default linear
  interpolation, i.e. the **95th percentile** of the 10,000 resample medians (a one-sided 95%
  upper confidence bound by the percentile-bootstrap convention). No interpolated-tie
  alternative method, no BCa correction, no bias adjustment.
- **Determinism:** the seed and resample count are frozen so the CI is reproducible bit-for-bit
  from the committed script; a re-run on the frozen slice must produce the same bound.

### 5.2 Rolling clause operationalization (frozen)

- **Fill series:** all pooled fills in the freeze slice, ordered by the trade's `exit_fill_time`
  (Python's stable sort, the same key `build_trailing_window` uses), entry fill emitted before
  its own exit fill within a trade.
- **Windows:** every contiguous 40-fill block `series[i : i+40]` for `i` from 0 to `len - 40`
  inclusive. A block qualifies when its **final** fill belongs to a record whose `date` is in the
  validation window.
- **Clause (b)** requires the median of every qualifying block to be below 5.0bps.

## 6. Tail quantiles (frozen requirement, descriptive)

The median understates the tail. The study **must** report, for each window and each side
(entry, exit), the tail quantiles `p90`, `p95` and `max` of |slippage|, and the verdict **must**
discuss whether a per-side model near the bottom of the grid ({1, 2}bps) would badly understate
occasional fills. This section freezes the requirement; the values are computed only in the
results commit. The point is recorded up front so the verdict cannot present a headline median
without the tail beside it: a per-side cost model is charged on every fill, and a handful of
large fills (a fast market or a flatten exit) can dominate the average cost even when the median
sits near 1bps.

## 7. Rolling-statistic reproduction gate (frozen)

Before the study trusts any new statistic it must reproduce the known ones:

- The script replicates `backtest/reflection.py`'s **stateless trailing-window fold**
  (`build_trailing_window`: prior ledger rows' own `reflection.trades` plus today's records,
  ordered by `exit_fill_time`, window `min(n, 20)` trades; a row without a `reflection` key
  contributes nothing) and its pooled-fill median (`compute_cost_check`).
- For **all 52** records carrying a `reflection` key in the freeze slice, the reproduced
  `median_abs_slippage_bps`, `n` and `ratio` must match the stored `reflection.cost_check`
  values **exactly** (bit-for-bit float equality on a re-derivation from the same ledger data).
- The verdict additionally records whether the reproduced per-date ratios match the quoted daily
  digest trigger lines: **0.13x on 2026-11-02 and 2026-11-03**, **0.16x on 2026-11-04,
  2026-11-05 and 2026-11-06** (from `docs/trading-journal/daily/dev/2026-11-0N.md`, line
  "`3. cost divergence: ...`"). A mismatch is a finding to document in the verdict, never
  something to code around or tune the pipeline for.

## 8. Deliverables, commit order and verification (frozen)

The commit order is load-bearing (the #566/#571/#572 harness convention). Within one PR:

1. **Commit 1 (this file):** the pre-registration. No windowed distributional statistic is
   computed before it exists. Mechanical counts (56/46 fills, 51 trades) may appear here;
   medians, IQRs, quantiles and bootstrap bounds may not.
2. **Commit 2:** `backtest/run_cost_model_slippage_study.py` (Python 3.9-compatible,
   `from __future__ import annotations` first line; reads only the committed JSONL; no network,
   no Supabase, no broker import) plus `tests/test_run_cost_model_slippage_study.py` (small
   synthetic fixtures for correctness; any test that reads the real file slices to
   `date <= 2026-11-06` and asserts only frozen values). **No results in this commit.**
3. **Commit 3:** the study run, its artifacts under
   `docs/research/2026-11-07-cost-model-slippage-study/` (a results JSON and a per-date rolling
   CSV), and the verdict doc `docs/research/2026-11-07-cost-model-slippage-verdict.md`.

The PR body lists the three commit hashes in order and states that the pre-registration hash
strictly precedes the results hash.

**Verification:** `venv/bin/python -m pytest -m "not slow"` (CI-canonical; no `slow` marker on
any new test, no network). The reproduction gate (section 7) runs before the verdict is written;
its match is recorded in the verdict.

## 9. Scope caveat (verbatim from #772)

> The frozen 5bps `CostModel` is a research-side convention shared by the whole verdict history
> (etf-daily r1/r2, prior rounds). A recalibration changes the comparability bar for future rounds
> only; it never re-scores past verdicts. That scoping decision is the operator's, at the gate.

## 10. Non-goals (frozen)

No live change; no edit to `backtest/portfolio.py` (`CostModel`), `backtest/regime.py`
(`SLIPPAGE_BPS`), `backtest/reflection.py`, anything under `supabase/`, or
`docs/trading-journal/daily-verification.jsonl` (read-only input); no new gate criterion, ledger
verdict value or scorecard row; no broker, Supabase or network call; no change to the reflection
engine's trigger thresholds; the gate decision itself is the operator's.

---

**Freeze banner.** Everything above this line is the frozen pre-registration. Results land in the
sibling verdict doc, never as edits above this line.
