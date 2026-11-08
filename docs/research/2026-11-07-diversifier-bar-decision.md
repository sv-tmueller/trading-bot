# Diversifier bar decision: keep the stand-alone Calmar criterion (roadmap C.2b) -- issue #758

**Date:** 2026-11-07. **Author:** Claude Code (developer, batch #774; research-only, `CLAUDE_AGENT_NO_BROKER=1` in every shell, no broker call, no production code touched). **Issue:** #758. **Roadmap item:** `docs/research/strategy-landscape-and-risk/roadmap.md` C.2b (settle the promotion bar for diversifier candidates before C.1's results exist). **Status:** decided; this note is an input to a *future* pre-registration, not a verdict on any candidate.

**Why this file lives in `docs/research/` and not `docs/decisions/`.** The decisions README explicitly excludes "a research artefact evaluating future options" from the ADR log, and CLAUDE.md scopes `docs/decisions/` to decisions that affect the safety stack or trading logic. This changes nothing live -- `backtest/pipeline_gate.py` and `backtest/scorecard.py` are research tooling and are **not** modified in this package. The ADR moment, if it ever comes, is the follow-up package that implements an accepted criterion.

CLAUDE.md "Architectural invariants" apply by reference: one decision rule stays `decideHourly`; no LLM enters any path; nothing here is live or promotable.

---

## 1. Decision

**Keep the stand-alone bar as THE gate criterion 2** (median development-year after-tax Calmar, candidate strictly above vol-targeted SPY). The candidate-plus-benchmark blend is recorded here as a **secondary, explicitly informational criterion only**: it may be *displayed* on a scorecard, and it may *never* flip a verdict on its own. A candidate that fails the stand-alone bar still fails, however flattering its blend number.

**The blend is specified on paper only and ships in no code in this package.** No edit is made to `backtest/pipeline_gate.py`, `backtest/scorecard.py`, `docs/research/pipeline/trials.json`, `backtest/tested_cells.py`, or anything under the r1/r2 study directories (frozen results artifacts). Section 2 is the specification a follow-up package would implement; this package stops at the note.

### Both sides, with the numbers

**For keeping the stand-alone bar.**

- *Pitfall 1 arithmetic* (`strategies.md`, "Pitfalls"). The mean of a blend is the weighted mean of its components. A Calmar-shaped bar rewards drawdown *shape*, so a stream with **no edge at all** can clear it: variance reduction shrinks the denominator while the numerator (CAGR) stays at the weighted mean. That is not hypothetical arithmetic, it is pinned mechanically by `tests/test_run_blend_illustration.py::test_pitfall1_zero_mean_stream_lifts_calmar_on_variance_reduction_alone`, where two exactly zero-mean streams blended 50/50 keep a blend mean of **exactly 0.0** and yet the blend's Calmar sits **above both** components' (`-0.073499` vs `-0.0779998` and `-0.0779903`) purely because its drawdown is shallower (`0.0832` vs `0.1752` and `0.2495`).
- *The r2 verdict's own finding.* `docs/research/2026-11-06-etf-daily-r2-verdict.md` section 5 records that both r2 candidates passed `beats_benchmark` and both failed for the same reason -- not construction, but **level**: 4.7%/yr and 5.3%/yr against the benchmark's 7.3%/yr in both periods. A blend criterion cannot fix a level problem: it can only average the candidate's lower return with the benchmark's higher one.
- *The blend's mean is never better than the benchmark's.* On the r2 data (section 3), the benchmark's mean daily return is `0.000303`; every blend's mean is strictly lower (`0.000247`, `0.000269`, `0.000255`, `0.000274`), because the blended-in leg earns less than the benchmark it is blended with. A blend bar therefore cannot be cleared by adding expected return; it can only be cleared on variance -- which is the Pitfall 1 shape, in a milder form.
- *Goalpost-creep risk.* `roadmap.md` C.2b's own "Cons" line: "Changing a bar after 364 failures looks like moving the goalposts. It must be argued on first principles and frozen before any C.1 number exists, or not at all." The r2 round already produced its numbers; a bar amended now would be read by any outside reviewer as post-hoc.

**For adding a blend criterion** (the C.2b original argument, recorded fairly).

- *A diversifier's value is low correlation to SPY, and a stand-alone test never measures it.* Dalio's "good, uncorrelated return streams" (*Principles*, 2017); trend as a crisis diversifier (MOP 2012); value plus momentum as the canonical negatively-correlated pair (AMP 2013). All cited in `roadmap.md` C.2b and `strategies.md` "Should we combine strategies?".
- *The r2 data does show a diversification effect.* Blending #764 at 50/50 takes the realised annualised vol from 10.37% (benchmark) to 7.46%, and the max drawdown from 22.35% to 14.17%; #763 goes to 6.79% and 12.86%. The candidate-benchmark daily-return correlations are 0.47 (#764) and 0.65 (#763) -- high, but low enough that the blend's vol is well below the benchmark's.
- *The measured effect is small and weight-sensitive.* Section 3 shows the blend's median-year Calmar crossing the benchmark's at 50/50 for #764 (`1.2773` vs `1.1078`) and **falling back below it at 30/70** (`1.0739` vs `1.1078`). A bar whose verdict flips on the choice of weight is a bar that encodes a second free parameter, and free parameters are exactly what the DSR/PBO machinery exists to police.

**Net.** The blend leg is worth *recording* -- it is the one honest measurement of the diversification argument -- but it is not worth *gating* on. Keeping it informational keeps the single, pre-committed bar as the only thing that decides, and keeps "one decision rule" intact at the gate level too.

## 2. Blend criterion spec (on paper only -- no code in this package)

### 2.1 Weights and the one risk budget

Two stated weights, both frozen if the criterion is ever adopted: **50/50** (candidate 50% / benchmark 50%) and **30/70** (candidate 30% / benchmark 70%). They are not tuned; they are read off the standard diversification table in `strategies.md` ("The diversification math"), which shows that at the observed correlations most of the benefit arrives by the time the second stream is half the book.

The weights are applied to the **already-vol-targeted** return streams (both the candidate and the benchmark run through the same 10% target, 60-day window, gross cap 1.0 chain). They are a capital split of **one risk budget**, not a re-leverage: `blend_t = w * candidate_t + (1 - w) * benchmark_t`, and the blend's **realised annualised vol is reported alongside** every blend figure so the reader can see what the risk budget actually bought. No second vol target is set on the blend.

### 2.2 The Pitfall 1 guard (mandatory sub-conditions)

Before any blend number is even *displayed*, the candidate must independently satisfy:

1. **A positive stand-alone mean.** The candidate's own mean daily return must be `> 0`. This is the direct Pitfall 1 guard: because the blend's mean is the weighted mean, a zero-or-negative-mean candidate can only lower the blend's mean while shrinking its variance.
2. **A corrected positive edge on the component.** `strategies.md` "What the invariants require" item 2: each component must show positive expectancy *with multiple-testing correction* (t ~ 3, DSR, PBO) **before** combination is considered -- "Combining is not a substitute for edge." On the current gate that means the candidate's own `luck` criterion has already passed.

If either sub-condition fails, the blend row is rendered `n/a`, not `fail`: the honest statement is "no blend was computed", because computing one would be computing a Pitfall 1 artefact.

### 2.3 How it would enter `backtest/pipeline_gate.py`

- `evaluate_candidate` keeps its signature and gains **one optional, non-gating** entry. The frozen five gate criteria stay the gate; `passed` stays `all(...)` **over exactly those five**, so it must be computed over an explicit `GATE_CRITERIA` tuple rather than over `criteria.values()`. That single line is the change that keeps the blend informational.
- The blend entry (name e.g. `blend_informational`) carries `{"passed": bool, "detail": str, "informational": True}` and is **appended after `activity`** so the renderer's fixed order is stable. It never participates in `passed`.
- Inputs are **supplied by the caller** from the pre-registration (the two stated weights and the two pre-computed blend metric dicts), preserving the module's pure-function / no-I/O contract: `pipeline_gate.py` does not read CSVs, does not import `scorecard`, and does not compute the blend itself.
- The entry reports, per stated weight: blend median-year Calmar, blend realised vol, and whether the blend median clears the benchmark's median. Because it is informational, "fails" here means "noted, not acted on".

### 2.4 How it would enter `backtest/scorecard.py`

- A new `ROW_LABELS` entry in the spec 5.5 table, e.g. `"Blend with vol-targeted SPY at the pre-registered weights (informational only)"`, rendered from a scorecard key the caller passes through.
- An extension of `_CRITERIA_ORDER` to include the informational row **after** `activity` -- `("drawdown", "beats_benchmark", "luck", "holdout", "activity", "blend_informational")` -- with the renderer suffixing it so a reader cannot mistake it for a gate criterion. (Note that `_CRITERIA_ORDER` lives in `scorecard.py`, and `_DSR_ROW = ROW_LABELS.index(...)` is positional but by-value, so inserting a row is safe as long as the pinned label text is not reworded.)
- Every weight present in the frozen list renders exactly once; a weight with a failed Pitfall 1 precondition renders `n/a`.

**Neither change ships in this package.** They are recorded here so that a future pre-registration can reference a fully specified criterion instead of an idea.

## 3. Illustrative blend computation (post-hoc / illustrative -- NOT a verdict, NOT a retest)

**This section re-scores nothing.** It reads the two already-committed development returns files from the finished `etf-daily-r2` round and re-weights each candidate's **already-selected** trial against that round's benchmark column. No round is re-opened, no holdout is read, no trial id is minted, no `evaluate_gate` / `programme_sharpes` call is made, and `docs/research/pipeline/trials.json` is untouched (see section 4b).

**One honest method caveat.** The r2 returns CSVs carry daily returns only -- no trade ledger -- so the median-year Calmar below is **pre-tax**. The gate's criterion 2 is the **after-tax** median-year Calmar (`scorecard._window_calmars` applies the annual-netting tax to each year's slice). The pre-tax figures inflate both sides roughly equally and the ordering is preserved (the r2 verdict records benchmark `0.9585` and #764 `1.1289` after tax, against `1.1078` and `1.4453` pre-tax here; #763 `2.1835` after tax against `2.2690` pre-tax). The illustration is therefore directionally faithful but is **not** the gate's own statistic, and is not presented as one.

Reference points: development window 2007-05-30 to 2021-12-31, 3,676 daily rows, 14 scored calendar years (2008-2021, the r2 `n_w` convention). Selected trials: `etf-daily-r2-donchian-trend-breakout-05` (#764) and `etf-daily-r2-vol-regime-gating-06` (#763). All figures below are the verbatim output of `backtest/run_blend_illustration.py`.

### 3.1 #764 `etf-daily-r2-donchian-trend-breakout` (`-05`)

Its near-miss on the r2 record: `beats_benchmark` pass but thin (after-tax median-year Calmar `1.1289` vs `0.9585`), broad `luck` failure (DSR `0.5574`, PBO `0.7110`), `activity` fail (6.2 round trips/yr).

| Stream | Mean daily | CAGR | Max DD | Calmar | Median-year Calmar (n_w) | Realised vol | Sharpe |
|---|---|---|---|---|---|---|---|
| stand-alone candidate | 0.000192 | 4.69% | 18.96% | 0.2475 | 1.4453 (14) | 6.90% | 0.6995 |
| benchmark (vol-tgt SPY) | 0.000303 | 7.34% | 22.35% | 0.3284 | 1.1078 (14) | 10.37% | 0.7353 |
| blend 50/50 (corr 0.4719) | 0.000247 | 6.12% | 14.17% | 0.4321 | **1.2773 (14)** | 7.46% | 0.8344 |
| blend 30/70 (corr 0.4719) | 0.000269 | 6.64% | 15.90% | 0.4175 | **1.0739 (14)** | 8.43% | 0.8044 |

**Would it have crossed a blend bar?** At 50/50, yes: the blend's median-year Calmar (`1.2773`) sits above the benchmark's (`1.1078`). At 30/70, **no**: it falls back below (`1.0739` vs `1.1078`). The verdict flips on the weight alone.

### 3.2 #763 `etf-daily-r2-vol-regime-gating` (`-06`)

The round's nearest miss overall: only the bootstrap leg of `luck` failed (DSR `0.9806`, PBO `0.2204`, uplift CI including zero), plus `activity` at 14.4 round trips/yr.

| Stream | Mean daily | CAGR | Max DD | Calmar | Median-year Calmar (n_w) | Realised vol | Sharpe |
|---|---|---|---|---|---|---|---|
| stand-alone candidate | 0.000208 | 5.29% | 8.30% | 0.6375 | 2.2690 (14) | 4.33% | 1.2124 |
| benchmark (vol-tgt SPY) | 0.000303 | 7.34% | 22.35% | 0.3284 | 1.1078 (14) | 10.37% | 0.7353 |
| blend 50/50 (corr 0.6470) | 0.000255 | 6.40% | 12.86% | 0.4979 | **1.8187 (14)** | 6.79% | 0.9482 |
| blend 30/70 (corr 0.6470) | 0.000274 | 6.80% | 16.60% | 0.4094 | **1.5192 (14)** | 8.16% | 0.8472 |

**Would it have crossed a blend bar?** Yes at both weights (`1.8187` and `1.5192`, both above `1.1078`). But #763 already passed the stand-alone `beats_benchmark` bar in the real round (`2.1835` vs `0.9585` after tax), so for this candidate the blend adds no information a gate would act on -- which is itself an argument against the extra criterion.

### 3.3 The Pitfall 1 trap, made explicit on this data

On the r2 data the components both have a **positive** mean, so this is not the zero-edge case the synthetic fixture pins. The milder form of the same trap is nonetheless present and visible in section 3.1: at 50/50 the blend's **mean** (`0.000247`) is *below* the benchmark's (`0.000303`), yet its **median-year Calmar** (`1.2773`) is *above* the benchmark's (`1.1078`). In other words, a Calmar-only blend bar would have been **cleared by a book that expected to earn less than the benchmark** -- purely on drawdown shape and variance reduction. The sub-conditions in section 2.2 (positive stand-alone mean, corrected positive edge) block the zero-edge limit of that; they do not make the shape-only reward a good idea, which is the deeper reason the criterion stays informational.

## 4. Constraint accounting

The three constraints the issue body names, each mapped to its treatment.

**(a) Pitfall 1 -- a positive stand-alone mean is still required.** Made a **hard sub-condition** of the blend criterion in section 2.2: no blend number is displayed unless the candidate's own mean daily return is `> 0` and its own `luck` criterion (DSR/PBO with multiple-testing correction) has passed. `strategies.md` Pitfall 1: "the mean of the blend is the weighted mean, so the bar must still require a positive stand-alone mean." Pinned mechanically in the test file.

**(b) The DSR vector and the round budget keep counting every configuration; a blend is not a second grid on the same data.** The 18 `etf-daily-r2` configurations are already in the programme store (37 trials: 5 backfilled + 14 r1 + 18 r2), so any later candidate in this space already deflates against them. A blend evaluation **re-uses one already-evaluated selected trial's returns** and linearly re-weights them against the benchmark: it introduces no new configuration, so it adds **nothing** to the round budget and **nothing** to the DSR vector, and it cannot raise the bar for later candidates. The illustration correspondingly **does not** re-run `evaluate_gate` or `programme_sharpes`, does not import `backtest.overfitting_gate`, and does not read or write `docs/research/pipeline/trials.json` (enforced by the module docstring, by the module's import list, and by `test_illustration_computes_no_dsr_or_pbo`). Only an adopted criterion's *implementation* package would touch the pipeline, and that package is not this one.

**(c) The no-holdout retest rule.** Any retest of #750 (`etf-daily-r1-tsmom-basket`) or #751 (`etf-daily-r1-xs-momentum`) is a **new `candidate_id` with no holdout**: the research-round skill Phase 4 (h) is explicit -- "A retest after the holdout uses a new `candidate_id` and has no holdout: never call `load_daily_bars(phase='holdout')` for it, pass `holdout=None` to `evaluate_candidate`, and state in its pre-registration and verdict that the holdout was already seen under `<old candidate_id>`". Both r1 holdouts have been seen, so such a retest **fails the `holdout` criterion by construction** (detail `holdout not yet run`), and its pre-registration must say so. A retest therefore only makes sense **if the gate is first amended** -- and this note is precisely the place that amendment would be specified, on paper: any wish to waive or replace the `holdout` criterion for a seen-holdout retest is a **separate issue** (the skill's own Non-goals), not part of this package and not part of the blend criterion. **No retest is run here, no round is opened, and no trial id is added.**

## 5. Reproduction

From the worktree root, with `CLAUDE_AGENT_NO_BROKER=1` and a venv holding `requirements.txt` (the checked-in convention; every command below is offline -- no network, no broker, no trial store):

```
venv/bin/python -m backtest.run_blend_illustration
```

That is the exact command whose output is reproduced in section 3. It reads only:

- `docs/research/2026-11-06-etf-daily-r2-study/etf-daily-r2-donchian-trend-breakout-development-returns.csv`
- `docs/research/2026-11-06-etf-daily-r2-study/etf-daily-r2-vol-regime-gating-development-returns.csv`

and writes nothing. `--study-dir` and `--weights` override the defaults if the illustration is ever reproduced against a different frozen study directory.

The pinned tests, which guard the section 3 numbers against silent drift:

```
venv/bin/python -m pytest tests/test_run_blend_illustration.py
```

Full suite (research-only; the new tests are pure pandas, no browser and no broker):

```
venv/bin/python -m pytest -m "not slow"
```

---

**Frozen-record note.** This document is a new dated decision note, not an edit to any pre-registration or verdict. The r1/r2 study directories, `docs/research/pipeline/trials.json`, `backtest/pipeline_gate.py`, `backtest/scorecard.py` and `backtest/tested_cells.py` are unchanged by this package. New prose uses `--` rather than em dashes (CLAUDE.md writing conventions).
