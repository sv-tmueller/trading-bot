# Cost-model slippage recalibration -- verdict

**Pre-registration (frozen, committed first):** `docs/research/2026-11-07-cost-model-slippage-preregistration.md`
(hash `5cb9885`, committed before any windowed statistic was computed). **Hypothesis issue:** #772.
**Batch:** #774. **Date:** 2026-11-07. **Author:** Claude Code developer session (research only;
`CLAUDE_AGENT_NO_BROKER=1`; no broker call, no Supabase call, no production code touched).
**Branch:** `feat/772-cost-model-slippage-study`.

Every number below comes from one run of
`backtest/run_cost_model_slippage_study.py` over the frozen slice
(`docs/trading-journal/daily-verification.jsonl`, records `date <= 2026-11-06`) and from the
committed artifacts `docs/research/2026-11-07-cost-model-slippage-study/cost-model-slippage-results.json`
and `.../cost-model-slippage-rolling.csv`. Nothing was re-picked or re-run after the stopping rule
was evaluated.

CLAUDE.md "Architectural invariants" apply by reference: this document changes nothing live and
promotes nothing. The 5.0bps `CostModel` is a research-side convention, not a live-bot config.

---

## 1. Verdict in one line

**Recalibration is proposed: the per-side slippage model should move from 5.0bps to 2.0bps for
future research rounds.** Both frozen clauses of the stopping rule fire. The proposed value is the
smallest candidate in {1, 2, 3, 5}bps at or above the validation-window bootstrap CI upper bound
(1.1728bps), which is 2.0bps -- deliberately conservative, sitting above the realized validation
median of 0.72bps. The gate decision is the operator's (section 6).

## 2. Reproduction gate (ran before the verdict was written)

The script re-derives `backtest/reflection.py`'s stateless trailing-window fold
(`build_trailing_window`) and its pooled-fill median (`compute_cost_check`) from the same ledger
and compares to the stored values. Result: **52 of 52 reflection-bearing records reproduce
exactly** (bit-for-bit on `median_abs_slippage_bps`, integer equality on `n`; zero mismatches).
The per-date ratios also reproduce the quoted daily-digest trigger lines:

| Date | Digest line (verbatim) | Reproduced ratio | Match |
|---|---|---|---|
| 2026-11-02 | `3. cost divergence: 0.13x (n=40) -- FIRED` | 0.1333 | yes |
| 2026-11-03 | `3. cost divergence: 0.13x (n=40) -- FIRED` | 0.1333 | yes |
| 2026-11-04 | `3. cost divergence: 0.16x (n=40) -- FIRED` | 0.1633 | yes |
| 2026-11-05 | `3. cost divergence: 0.16x (n=40) -- FIRED` | 0.1633 | yes |
| 2026-11-06 | `3. cost divergence: 0.16x (n=40) -- FIRED` | 0.1633 | yes |

The digested ratios round to the printed 0.13x / 0.16x exactly. This is the study's built-in
sanity gate (the #572 pattern): the re-derivation is faithful before any new statistic is trusted.
No mismatch is a finding, and none occurred.

## 3. Description of the realized distribution

Frozen slice: 60 records, 51 unique trades, 102 fills (both sides present on every trade). Windows
assigned by the record's own `date`. Per-side unit, absolute bps, nulls dropped.

| Window | n fills | median | IQR | p90 | p95 | max |
|---|---|---|---|---|---|---|
| Calibration (2026-08-13..2026-09-30) | 56 | 0.3942 | 1.0138 | 2.613 | 3.641 | 31.715 |
| Validation (2026-10-01..2026-11-06) | 46 | 0.7229 | 1.5086 | 3.528 | 3.893 | 11.915 |

By side (the model is charged per side, so the sides are reported separately):

| Window | Side | n | median | q25 | q75 | p90 | p95 | max |
|---|---|---|---|---|---|---|---|---|
| Calibration | entry | 28 | 0.2597 | 0.1362 | 0.4035 | 0.712 | 0.893 | 1.464 |
| Calibration | exit | 28 | 1.1466 | 0.3812 | 2.4680 | 3.741 | 13.097 | 31.715 |
| Validation | entry | 23 | 0.5213 | 0.2929 | 1.1548 | 1.777 | 1.981 | 2.365 |
| Validation | exit | 23 | 1.1728 | 0.4028 | 2.8943 | 3.900 | 5.411 | 11.915 |

Two facts stand out. First, the median roughly doubles from calibration (0.39bps) to validation
(0.72bps) -- the divergence the issue tracked is real but sloping upward, not flat; the model is
still conservative against both. Second, and more important for a per-side charge, the **exit side
is systematically dearer than the entry side** at every quantile (validation exit median 1.17bps
vs entry 0.52bps; calibration exit p95 13.1bps vs entry p95 0.89bps). A single per-side number
has to cover both, so the pooled median is the right summary only alongside the side split.

## 4. Candidate grid (descriptive)

For each candidate `c`, the median ratio (`median / c`) and the fraction of fills exceeding `c`:

| Candidate | Calibration ratio | Calibration frac > c | Validation ratio | Validation frac > c |
|---|---|---|---|---|
| 1bps | 0.3942 | 30.4% | 0.7229 | 43.5% |
| 2bps | 0.1971 | 19.6% | 0.3615 | 19.6% |
| 3bps | 0.1314 | 7.1% | 0.2410 | 13.0% |
| 5bps | 0.0788 | 5.4% | 0.1446 | 4.3% |

The grid shows how trigger 3 would behave under each candidate. Trigger 3's low leg fires when
`ratio < 0.5`. Under a 1bps model the current validation ratio would be 0.72, so the trigger would
**stop firing** -- the "divergence" would be gone, which is the risk of recalibrating too far
down. Under 2bps (ratio 0.36) and above, the trigger would keep firing, shrinking as the model
rises. The trigger's real signal is the **trend** (0.08x in late September to 0.16x now), which
the window split reproduces: at the current 5bps model the calibration ratio is 0.079 and the
validation ratio 0.145.

## 5. Stopping rule (frozen) -- applied

- **Clause (a) -- validation CI:** validation-window median 0.7229bps; one-sided 95%
  percentile-bootstrap upper bound **1.1728bps** (10,000 resamples, seed 0, `numpy.percentile`
  linear interpolation), strictly below 5.0bps. **Holds.**
- **Clause (b) -- rolling:** 46 qualifying rolling 40-fill blocks (every block whose final fill is
  validation-dated; total contiguous blocks in the slice = 63). Worst qualifying block median
  **0.9122bps**, strictly below 5.0bps; every one of the 46 is below 5.0bps. **Holds.**
- **Proposed value:** smallest candidate >= 1.1728bps is **2.0bps**.

Both clauses hold, so **recalibration is proposed at 2.0bps per side** for future research rounds.
Note the chosen value is well above the realized validation median (0.72bps): the rule is
deliberately conservative, deliberately refusing to sit at the median. The 2.0bps value sits
inside the exit side's interquartile band in both windows (calibration q25-q75 0.38-2.47bps,
validation 0.40-2.89bps), but above the entry side's q75 (calibration 0.40bps, validation
1.15bps) and above the pooled q75 (calibration 1.24bps, validation 1.84bps): it is a
mid-band cost for the dearer exit side and a conservative one for the cheaper entry side,
not an outlier-driven value.

## 6. Tail discussion (why 1bps would be wrong) and scope

**The tail is the argument against the bottom of the grid.** The pooled medians (0.39bps
calibration, 0.72bps validation) are near 1bps, and a naive "use the median" reading would pick
1bps. The tail says no: the calibration pooled p95 is 3.64bps with a maximum of **31.7bps**, and
the validation exit p95 is 5.41bps with a maximum of **11.9bps** (the 2026-11-06 flatten exit).
A per-side model is charged on *every* fill, so occasional 10-30bps fills are not rare events to
drop -- they are the reason the mean per-side cost is not the median. A 1bps model would understate
30% of calibration fills and 43% of validation fills on a fraction-exceeding basis. 2.0bps covers
the validation median with a comfortable margin while still charging far less than the incumbents'
5.0bps. This is a **descriptive** statement; the gate is the stopping rule, not this table.

**Scope caveat, verbatim from #772:**

> The frozen 5bps `CostModel` is a research-side convention shared by the whole verdict history
> (etf-daily r1/r2, prior rounds). A recalibration changes the comparability bar for future rounds
> only; it never re-scores past verdicts. That scoping decision is the operator's, at the gate.

Nothing in this study changes `backtest/portfolio.py` (`CostModel`), `backtest/regime.py`
(`SLIPPAGE_BPS`) or `backtest/reflection.py`; all three are untouched, and the ledger is read
only. The gate decision, and any subsequent edit to the frozen `CostModel`, is the operator's at
the gate -- this document only informs it.

## 7. Honest notes and limitations

- The empirical distribution has a mostly one-sided story in *volume* but not in *drift*: the exit
  side is dearer than the entry side, so a single per-side number collapses a real asymmetry. A
  future refinement could split entry and exit costs, but that is a change to the model shape and
  is out of scope here (the pre-registration froze a single per-side value).
- This is paper-account slippage (`environment: "dev"`). Real fills under live liquidity
  conditions could differ; the drift from 0.08x to 0.16x over six weeks is also consistent with a
  liquidity/regime effect rather than a structural mis-estimate, and this study cannot separate the
  two. The 2.0bps proposal is a descriptive recalibration, not a causal finding.
- The rolling clause uses 46 of 63 contiguous blocks; the 17 excluded blocks end on
  calibration-dated fills and are not part of clause (b)'s denominator by design (they are not
  "validation windows"). Every one of the 46 qualifying blocks is below the model by a wide margin
  (worst 0.91bps vs 5.0bps), so the clause is not close to firing in the other direction.
- The pre-registration froze the confidence level (95%), the resample count (10,000) and the seed
  (0) precisely so this verdict could not be re-tuned after seeing the numbers; the CI
  (1.1728bps) is reproducible bit-for-bit from the committed script.

## 8. Deliverables, reproduction and commit order

Commit order (load-bearing, per the #566/#571/#572 convention):

1. `5cb9885` -- the frozen pre-registration (no windowed statistic computed before it).
2. `4202c68` -- `backtest/run_cost_model_slippage_study.py` + `tests/test_run_cost_model_slippage_study.py` (no results).
3. the results commit (this doc, the artifacts and the rolling CSV; its hash is the PR branch head,
   listed in the PR body).

The pre-registration hash strictly precedes the results hash. Reproduce from the worktree root:

```
venv/bin/python -m backtest.run_cost_model_slippage_study \
  --out docs/research/2026-11-07-cost-model-slippage-study
venv/bin/python -m pytest -m "not slow"
```

**Verdict: recalibration PROPOSED -- 5.0bps -> 2.0bps per side, for future research rounds only,
pending the operator's gate decision.**
