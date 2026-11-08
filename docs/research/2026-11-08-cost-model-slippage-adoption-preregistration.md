# Cost-model slippage adoption (5.0bps -> 2.0bps) -- pre-registration

**Change frozen:** the research pipeline's per-side slippage constant
`backtest/regime.py::SLIPPAGE_BPS` moves from `5` to `2` (0.05% -> 0.02% per side), for future
research rounds only.

**Evidence this rests on:** `docs/research/2026-11-07-cost-model-slippage-verdict.md` (study
#772, batch #774), reproduced from the committed artifacts
`docs/research/2026-11-07-cost-model-slippage-study/cost-model-slippage-results.json` and
`.../cost-model-slippage-rolling.csv` over the frozen ledger slice
(`docs/trading-journal/daily-verification.jsonl`, records `date <= 2026-11-06`):

- Validation-window (2026-10-01..2026-11-06, 46 pooled fills) median |slippage| **0.7229bps**.
- One-sided 95% percentile-bootstrap upper bound on that median **1.1728bps** (10,000 resamples,
  seed 0, `numpy.percentile` linear interpolation).
- All **46** qualifying rolling 40-fill blocks below 5.0bps; worst block median **0.9122bps**.
- Both frozen stopping-rule clauses hold, so the proposed value is the smallest grid candidate in
  {1, 2, 3, 5}bps at or above the CI upper bound -- **2.0bps per side**.

**Hypothesis issue:** #772 ("Hypothesis: re-examine the frozen 5bps cost model (realized paper
slippage has run at 0.08-0.16x of it for six weeks)"). **Batch:** #778, size:M.
**Date:** 2026-11-08. **Author:** Claude Code developer session (research only;
`CLAUDE_AGENT_NO_BROKER=1`; no broker call, no Supabase call, no production code touched).

This document is committed and merged **before** the constant changes. It freezes the value, the
evidence it rests on, the scope, what is deliberately NOT changing, and the non-comparability
rule. It is an adoption record, not a study: it computes no new statistic and re-runs no window.

---

## 0. Invariant framing

CLAUDE.md "Architectural invariants" and "Writing conventions" apply by reference. This is a
research-only change: it edits `backtest/regime.py::SLIPPAGE_BPS` and the tests that pin the old
value; it makes no broker or Supabase call, promotes nothing, and adds no decision rule to the
trading path. The production bot (`supabase/functions/`) is **not** touched -- it carries no
`SLIPPAGE_BPS` and its cost handling is out of scope for this package. The 5.0bps model has been a
research-side convention, not a live-bot config value; the 2.0bps value is the same kind of
convention, just recalibrated.

## 1. The change

- **One constant:** `backtest/regime.py::SLIPPAGE_BPS`, `5` -> `2` (0.05% -> 0.02% per side).
- **Why 2.0bps and not the realized median:** the pre-registered rule is deliberately
  conservative. The validation median is 0.7229bps, but a per-side model is charged on *every*
  fill, and the tail is real (validation exit p95 5.41bps, max 11.9bps; calibration pooled max
  31.7bps). The proposed value takes the smallest grid candidate at or above the 95% bootstrap
  upper bound (1.1728bps), which is 2.0bps -- above the median, inside the exit side's
  interquartile band, nowhere near the tail. Section 6 of the verdict carries the full argument.
- **Transitive pickups:** `backtest/reflection.py::COST_MODEL_BPS = float(SLIPPAGE_BPS)` picks the
  new value up automatically. Its comment (and two stale docstrings) said "frozen 5bps" and are
  updated for accuracy only -- no behavior change beyond the constant. `backtest/portfolio.py`'s
  `CostModel` is explicitly **not** touched (see section 4).

## 2. Scope (frozen)

- **Forward only:** the new value applies to research rounds whose pre-registration is filed on or
  after **2026-11-08**. Rounds already frozen, in flight, or merged keep the 5.0bps model in their
  records.
- **No re-scoring:** no past verdict, scorecard, trial-ledger entry or holdout is re-run or
  re-scored under 2.0bps. The historical artifacts under `docs/research/` are frozen evidence and
  are never edited to match the new number.
- **No re-scoring of the study that produced it:** the #772 study module
  (`backtest/run_cost_model_slippage_study.py::MODEL_BPS = 5.0`) and its artifacts stay exactly as
  committed. That module is the frozen reproducer of the 2026-11-07 verdict, not a live consumer
  of the constant.

## 3. What is deliberately NOT changing (frozen)

- **`COMMISSION_BPS` stays `5`.** The #772 study validated **slippage only**: it sampled realized
  per-fill slippage from the paper ledger. Commissions are a real, contractual cost, not a modeled
  one, and nothing in the evidence speaks to them. Lowering commissions alongside slippage would
  be an unsupported second change smuggled into the same PR.
- **The 5.0bps `CostModel` in the scorecard path** (`backtest/portfolio.py`,
  `tests/test_portfolio.py`). Aligning it is a separate operator decision, not implied by this
  adoption. The lead's batch-#778 decision keeps that path at 5.0bps; this package does not touch
  it.
- **Frozen historical artifacts** (every `docs/research/` file dated before 2026-11-08, the #772
  study module and its results JSON/CSV, `backtest/tested_cells.py` and `backtest/run_orb_probe.py`
  prose). Historical records state what was true when they were written.
- **Nothing under `supabase/`, `scripts/` or `web/`.** No production or live-bot setting changes;
  no new decision rule.

## 4. Non-comparability rule (frozen)

**Results produced under the 5.0bps model are not comparable to results produced under the
2.0bps model without re-running both sides of the comparison under one model.** A cost level is
part of a study's result, not a decoration on it: the same strategy can clear or miss a gate
depending on whether it is charged 5.0bps or 2.0bps per side, so a round's headline (a ratio, a
median, a pass/fail against a cost-related bar) carries its cost model with it. The boundary date
is **2026-11-08**: rounds pre-registered before it are 5.0bps rounds; rounds pre-registered on or
after it are 2.0bps rounds. Any cross-boundary comparison must re-run both sides at one setting
and say which one. The note in `docs/research/README.md` records this rule for readers who arrive
without the PR.

This is the same discipline as the #772 scope caveat: a recalibration changes the comparability
bar for future rounds only; it never re-scores past verdicts.

## 5. Known, expected behavior change (not a regression)

- The nightly reflection engine's trigger 3 ("cost divergence",
  `backtest/reflection.py::TRIGGER_3_LOW_MULTIPLE = 0.5`) compares the realized median |slippage|
  against `COST_MODEL_BPS`. Under the 5.0bps model the validation-window ratio was ~0.14x; under
  the 2.0bps model it becomes ~0.36x (median 0.7229 / 2.0). Both sit under the 0.5 low leg, so
  **trigger 3 keeps firing** -- by design, and documented in section 4 of the verdict. The trigger
  would only go quiet if the model were recalibrated to 1.0bps (ratio 0.72), which the stopping
  rule explicitly rejected.
- The golden reflection fixture (`tests/fixtures/reflection/golden-2026-08-06.md`) embeds computed
  numbers derived from `COST_MODEL_BPS`, so its trigger-3 line flips from "not fired" to **FIRED**
  at ratio 2.50x (that fixture's synthetic fills run at 5.0bps). It is regenerated from the CLI
  path the test uses, never hand-edited, and the new FIRED line is quoted in the PR body for human
  review.

## 6. Deliverables, commit order and verification (frozen)

The commit order is load-bearing (the #566/#571/#572 prereg-precedes-results discipline):

1. **Commit 1 (this file):** the pre-registration. No constant changes before it exists.
2. **Commit 2:** `backtest/regime.py::SLIPPAGE_BPS = 2`; `backtest/reflection.py` comment
   accuracy; every 5.0-pinning test updated to 2.0 (updated, never deleted); the regenerated
   golden fixture; the three cross-model tests in `tests/test_run_cost_model_slippage_study.py`
   rebased to pin the intended study-5.0/live-2.0 divergence; the stale `20bp` comment in
   `backtest/run_15min_candlestick_study.py`; and the `docs/research/README.md` non-comparability
   note.

**Verification:** `python3 -m pytest -m "not slow"` (CI-canonical) with keys unset, collected count
unchanged or higher; `backtest.regime.SLIPPAGE_BPS == 2.0` and `COMMISSION_BPS == 5`; and
`git merge-base --is-ancestor <commit1> <commit2>` on the PR branch.

## 7. Non-goals (frozen)

No live change; no edit to `backtest/portfolio.py` (`CostModel`), `backtest/run_cost_model_slippage_study.py`
(the frozen reproducer), any `docs/research/` file dated before 2026-11-08, anything under
`supabase/`, `scripts/` or `web/`, or `docs/trading-journal/daily-verification.jsonl` (read-only
input); no re-run or re-scoring of past studies; no change to `COMMISSION_BPS`; no touching of any
holdout or the DSR trial vector; no new gate criterion or scorecard row; no broker, Supabase or
network call.

---

**Freeze banner.** Everything above this line is the frozen pre-registration. The adoption itself
lands in commit 2 of this PR, never as edits above this line.
