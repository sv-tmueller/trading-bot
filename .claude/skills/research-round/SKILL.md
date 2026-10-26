---
name: research-round
description: Use this skill to run one operator-gated round of the AI research pipeline -- proposes 3-5 strategy candidates as `candidate` issues, drafts the pre-registration freeze PR, runs the development study then the one-shot holdout per picked candidate, and posts a scorecard plus gate verdict with a recommendation on each issue. Stops at three operator decisions. Invoke when the operator says "start a research round", "run research round <round_id>", or `/research-round`.
---

# Research Round

Run one round of the AI research pipeline end to end, stopping at three operator decisions. The
design authority is
[`docs/superpowers/specs/2026-10-23-ai-research-pipeline-design.md`](../../../docs/superpowers/specs/2026-10-23-ai-research-pipeline-design.md)
(sections 5.1 to 5.7 are the flow this skill executes); this skill is the operating procedure. The
pipeline's file conventions are in
[`docs/research/pipeline/README.md`](../../../docs/research/pipeline/README.md).

Research only. The output is issues, Markdown, JSON records and Python study code under
`docs/research/`, plus ledger rows in `backtest/tested_cells.py`. It never edits `supabase/functions/`,
never places a broker call, and never changes what the live bot does (see [Non-goals](#non-goals)).

## Inputs

- `<round_id>` (required) -- kebab-case name of the round, e.g. `etf-trend-r1`. It is frozen and
  used in three places: as `TrialRecord.round_id`, in the pre-registration, verdict and
  study-directory names, and inside every `candidate_id`. It must not be `backfill`, and must not
  already appear in `docs/research/pipeline/trials.json` unless this is a resume.
- `<round issue>` (optional) -- the GitHub issue that carries this round (for example the batch
  issue the operator names). If absent, open `Research round <round_id>` with label `strategy`.
  Every stop marker, budget authorization and operator pick lives as a comment on this issue. On a
  resume, read this issue and its comments first and continue from the last marker posted.
- `<operator constraints>` (optional) -- themes to include or avoid, a candidate count within 3 to 5.

Identifiers, all frozen in the pre-registration and never changed afterwards:

- `candidate_id` = `<round_id>-<slug>`. It must match `^[A-Za-z0-9][A-Za-z0-9._-]*$` (enforced by
  `backtest/etf_data.py`).
- `trial_id` = `<candidate_id>-<NN>`, two digits, one per configuration.
- Every `TrialRecord` carries `space=DAILY_ALLOCATION` and `source=<pre-registration path>`.

## Pre-flight

Do all of these before the first phase. Stop and tell the operator if any fails.

1. **Safety contract.** Read CLAUDE.md "Architectural invariants" and "Writing conventions". Cite
   them by reference; do not restate them in any artifact this skill writes.
2. **Broker guard.** Start every Bash command this skill runs with `export CLAUDE_AGENT_NO_BROKER=1 &&`, and
   pass it to every dispatched agent. The pipeline needs no broker call at any step.
3. **Read the design inputs:** the spec above, `docs/research/strategy-landscape-and-risk/strategies.md`,
   `docs/research/2026-07-21-overfitting-gate-usage.md`, and `docs/research/README.md` (the two-PR
   rule: a freeze PR merged before any results PR, and results land as a dated addendum under the
   pre-registration's freeze banner, never as an edit to the frozen text).
4. **Trial store is non-empty.** The DSR trial vector is the programme's stored history, so an empty
   store would make every later DSR meaningless. Run from the worktree root:

   ```bash
   python3 -c 'import sys; from backtest.trial_store import programme_sharpes; n=programme_sharpes().size; print(n); sys.exit(0 if n>0 else 1)'
   ```

   Exit 1 means the store is empty: stop and tell the operator the programme history has not been
   loaded. Do not seed it yourself, and do not write `BACKFILL_ROUND` records.
5. **Label and template exist.** `gh label list` shows `candidate`, and
   `.github/ISSUE_TEMPLATE/candidate.md` is present.
6. **Clean worktree on a detached HEAD** from the current `origin/main`. Run `python3` from the
   worktree root: `DEFAULT_PATH` and `PIPELINE_DIR` are relative to the repo root. Publish to the
   round's branches with `git push origin HEAD:refs/heads/<branch>`. Never force-push a round branch;
   a rejected push means stop and inspect.
7. **Round id is fresh** (see Inputs), and the round issue exists or has been opened.

## Phases

### Phase 1 -- Propose candidates and file the issues

1. Draft 3 to 5 candidates from the strategy landscape doc and the spec's section 5.7 seeds. Each is
   one rule (entry, exit, sizing in plain words) on daily bars of SPY or an ETF basket.
2. **Novelty check that cannot be gamed by renaming.** For each candidate, run
   `python3 -m backtest.tested_cells --check FAMILY CADENCE VEHICLE` for the proposed family, and also
   for the nearest existing families (`tsmom_timeseries`, `faber_ma_timing`, `dual_momentum_gem`,
   `vol_target`) on each of `SPY`, `ETF_BASKET_GEM` and `ETF_BASKET_GTAA5`. Paste all output verbatim
   into the issue's Novelty check section. If the rule belongs to an existing family, reuse that
   family's name. Inventing a new family name to obtain a NOVEL result is the anti-goal in spec
   section 3; say plainly where the candidate overlaps a killed family.
3. File one issue per candidate:
   `gh issue create --label candidate --title "candidate: <name>" --body-file <file>`. Pass the label
   explicitly: a template only supplies body text and does not apply labels from the command line.
   The body holds the template's seven headings in order: Idea, Why it might work, Evidence so far,
   Novelty check, Data feasibility, Proposed test, AI recommendation. Give evidence a grade
   (academic, practitioner or marketing) and cite sources.
4. In each Proposed test section state the grid size N (each N >= 2: DSR and PBO raise `ValueError`
   below 2) and show the running total across candidates.
5. **Budget rule.** The round total must be at most `ROUND_BUDGET` (50 configurations, from
   `backtest/trial_store.py`). The only exception is an operator comment on the round issue that
   authorizes a specific higher number; the pre-registration links that comment. `round_budget=` is
   passed to `append_trials` only when that comment exists, and only with the authorized value.
6. Print and post on the round issue, verbatim, with the issue numbers and sum filled in:

   ```
   STOP 1 of 3 -- operator picks. Candidate issues filed: #A, #B, #C (round issue #R). Proposed grids total N = <sum> of the 50-configuration round budget. Reply on #R naming the candidates to test; I take no further step until you do.
   ```

   Take no further step until the operator replies on the round issue.

### Phase 2 -- Freeze PR (pre-registration)

1. Branch `docs/<round_id>-preregistration` off `origin/main`. Write
   `docs/research/YYYY-MM-DD-<round_id>-preregistration.md`, following the structure and freeze banner
   of the existing `*-preregistration.md` files in `docs/research/` (for example
   `docs/research/2026-10-22-spy-intraday-momentum-preregistration.md`).
2. **Freeze list.** The document states, for the picked candidates only:
   - `round_id` and every `candidate_id`;
   - the ETF list, the data source (and the data start date), and the `rebalance_band`;
   - each candidate's grid and its N, the round total, and (if above 50) a link to the authorizing
     comment on the round issue;
   - the rule that picks the best of the N configurations on development data;
   - costs as the `CostModel(...)` arguments, the cash-rate series passed as `cash_returns`, borrow
     and financing rates;
   - the vol target (`target_vol` in `vol_target_weights`, `benchmark_weights` and
     `compute_scorecard`), and the gross cap: 1.0 for every verdict run, 1.5 only for the
     `leverage_info` line;
   - the uplift definition: baseline is `benchmark_weights` on SPY, same mechanism and cap (spec 5.2
     criterion 2);
   - `gate_kwargs` for `evaluate_candidate`: `pbo_n_splits` (even, and no larger than the number of
     return rows T), `bootstrap_block_length`, `bootstrap_n_boot`, `bootstrap_seed`,
     `bootstrap_alpha`, `dsr_sr_benchmark`;
   - the pass bar (spec 5.2, which the operator confirms by merging) and the development and holdout
     split (`DEV_END`, `HOLDOUT_START` in `backtest/etf_data.py`);
   - the holdout policy: the holdout runs for every picked candidate that is a first test, so no
     choice is made after seeing development numbers; a retest under Phase 4 (h) has none, and the
     pre-registration names the `<old candidate_id>` whose holdout was seen.
3. **Parity check (spec 5.6).** Run
   `python3 -m backtest.run_etf_parity --tickers <comma-separated frozen list>` and paste its output into the freeze PR.
   It is a GET-only market-data read over the development window, not a broker call. If no read-only
   data keys are available in this environment, ask the operator to run it and paste the output.
4. Open the freeze PR as a draft, linking the round issue and the candidate issues (it closes none of
   them), and mark it ready when complete.
5. **No returns before the merge.** Compute no candidate's returns, Sharpe or equity curve, and load no
   bars for any candidate, before the freeze PR is merged. The parity check above is the only data
   contact allowed.
6. Print and post on the round issue, verbatim, with the PR number filled in:

   ```
   STOP 2 of 3 -- operator merges the freeze PR #P. No candidate's returns have been computed. I resume only after you merge #P to main.
   ```

   Phase 3 starts only when `gh pr view <P> --json state` reports `MERGED`. This skill never merges
   the freeze PR itself, even under a standing batch-merge delegation.

### Phase 3 -- Development runs (analyst, one candidate at a time)

Work on the results branch `docs/<round_id>-results`, created from the merged `origin/main`.

1. **Serial dispatch.** For each picked candidate in turn, dispatch the `analyst` agent
   (`subagent_type: analyst`, definition in `.claude/agents/analyst.md`). Never run analysts in
   parallel: `append_trials` reads, modifies and rewrites `trials.json`, so concurrent runs lose
   records.
2. The dispatch prompt overrides `analyst.md` in four ways, stated explicitly:
   - open no PR (skip playbook step 6) and file no issues;
   - run `python3` from the worktree root, not `venv/bin/python`;
   - development phase only: never call `load_daily_bars(phase="holdout")`;
   - write study code into `docs/research/YYYY-MM-DD-<round_id>-study/` (the only place the analyst
     may write) and import `backtest/` read-only.

   The prompt also passes the frozen pre-registration path, `CLAUDE_AGENT_NO_BROKER=1`, and the payload
   contract below.
3. **Study contract.** The study script loads bars only through `load_daily_bars` in
   `backtest/etf_data.py`, sizes with `vol_target_weights` and `inverse_vol_weights` from
   `backtest/vol_target.py`, simulates with `simulate_portfolio` and `CostModel` from
   `backtest/portfolio.py` (using `round_trips_per_year` for activity), and builds the scorecard with
   `compute_scorecard` from `backtest/scorecard.py` (with the `benchmark_weights` SPY run as
   benchmark, `double_cost=` (the selected configuration re-run at twice the frozen `CostModel`
   costs) and `leverage_info=` (the same configuration at gross cap 1.5 with the frozen financing
   rate); neither re-run is appended as a trial). It evaluates exactly the frozen grid, nothing outside
   it, and appends every evaluated configuration, losers included, as `TrialRecord` rows via
   `append_trials` from `backtest/trial_store.py`. The script takes `--phase development|holdout`. The
   holdout path reads `selected_trial_id` and `config` from `development_result.json`, runs only that
   configuration (with the `benchmark_weights` SPY benchmark and the `double_cost=` and
   `leverage_info=` re-runs, all cut to rows on or after `HOLDOUT_START` as Phase 4 (g) says) and records via `record_result(candidate_id, "holdout", payload)`. The analyst writes
   and commits this path but never runs it. The holdout path appends no trial: `trials.json`, and
   with it the DSR trial vector and the round budget, holds development-period configurations only
   (spec 5.3). The script also writes
   `<study dir>/<candidate_id>-development-returns.csv` (one row per development day; one column per
   `trial_id` plus `benchmark`), committed with `development_result.json`.
4. **Written payloads.** The analyst writes the development payload to
   `<study dir>/<candidate_id>-development-payload.json` and never calls `record_result`. After the
   step 5 post-checks pass, this session calls `record_result(candidate_id, "development", payload)`,
   so the holdout lock stays closed for the whole analyst run. `development_result.json` holds `round_id`,
   `candidate_id`, `trial_ids`, `selected_trial_id`, `config`, `scorecard` (the `compute_scorecard`
   dict) and `commit`. `holdout_result.json` holds the same keys minus `trial_ids`.
5. **Post-checks after each analyst returns** (the orchestrator, not the analyst, runs them):
   - no `holdout_result.json` exists for any candidate yet;
   - the number of stored trials for that candidate equals the frozen N:
     `python3 -c 'import sys; from backtest.trial_store import load_trials; n=sum(r.candidate_id=="<candidate_id>" for r in load_trials()); print(n); sys.exit(0 if n==<N> else 1)'` exits 0;
   - `grep -rnE 'yfinance|yf\.download|fetch_bars|run_fetch_spy_intraday' <study dir>` prints nothing.

   Any failure: stop, post on the round issue, wait.
6. **Budget enforcement (procedural, on top of the `append_trials` hard check).** Never edit or delete
   existing trials, never use `BACKFILL_ROUND`, never use a second `round_id` to get around the cap.
   On `BudgetExceededError`: stop, post it on the round issue, and wait for the operator.

### Phase 4 -- The holdout, exactly once per candidate

The code refuses a holdout load without `development_result.json` or after `holdout_result.json`
exists, and `record_result` refuses every write once `holdout_result.json` exists. That lock is only
a file, so a renamed id, a deleted file or another worktree could re-open it. Close that gap with
this procedure:

- (a) `development_result.json` and `trials.json` are committed and pushed on the results branch, and
  the results PR is opened as a draft, before any holdout runs.
- (b) Before each run, `git fetch origin && git log --all --oneline -- docs/research/pipeline/<candidate_id>/holdout_result.json`
  must print nothing.
- (c) The holdout is one invocation of the committed study script per candidate, run by this
  orchestrating session, not the analyst. The load and `record_result` happen in the same process.
  Commit and push `holdout_result.json` immediately afterwards.
- (d) If a run fails after holdout bars were loaded but before they were recorded, the holdout counts
  as consumed: stop, report on the round issue, and do not re-run.
- (e) Never delete, move or edit any `*_result.json`; never pass a non-default `pipeline_dir`; never
  load prices except through `load_daily_bars`.
- (f) The holdout runs for every picked candidate, as the pre-registration says.
- (g) The holdout scorecard covers rows on or after `HOLDOUT_START` only. Earlier rows only warm up
  signals and volatility estimates.
- (h) A retest after the holdout uses a new `candidate_id` and has no holdout: never call
  `load_daily_bars(phase="holdout")` for it, pass `holdout=None` to `evaluate_candidate`, and state in
  its pre-registration and verdict that the holdout was already seen under `<old candidate_id>` (spec
  5.3: a re-tested candidate loses its holdout). (f) applies to first tests only. Such a retest fails the gate's `holdout` criterion (detail
  `holdout not yet run`); the verdict document says the holdout was seen under `<old candidate_id>`,
  and any wish to waive the criterion is a separate issue (Non-goals).

### Phase 5 -- Verdicts and the results PR

1. After every candidate's trials are appended, call `programme_sharpes()` once and report its size
   as the DSR trial count. This ordering matters: the best trial must already be in the vector.
2. For each candidate, in this order: `evaluate_candidate(dev_card, hold_card, returns_best=...,
   all_trial_sharpes=..., perf_matrix=..., uplifts=..., gate_kwargs=<frozen>)` from
   `backtest/pipeline_gate.py`, then `render_scorecard_markdown(dev_card, hold_card, verdict)` from
   `backtest/scorecard.py`, then append your recommendation (promote, reject or retest at full power)
   and the footer "what would change the recommendation" from the scorecard template in
   `docs/research/pipeline/README.md`. The renderer emits no recommendation text; the recommendation is
   yours and is labelled as such. `evaluate_candidate` forwards `gate_kwargs` to `evaluate_gate` in
   `backtest/overfitting_gate.py` unchanged; use only the frozen values. Build `perf_matrix` (trial
   columns in `trial_ids` order), `returns_best` (the `selected_trial_id` column) and `uplifts` (the
   frozen uplift definition against `benchmark`) from `<study dir>/<candidate_id>-development-returns.csv` (Phase 3 step 3); never recompute them after the
   holdout. `dev_card` and `hold_card` are the `scorecard` values of `development_result.json` and
   `holdout_result.json` (`hold_card` is `None` for a retest under Phase 4 (h)).
3. A `ValueError` or `KeyError` from `evaluate_candidate` is an input error, not a failed verdict:
   stop and post no verdict.
4. Post the rendered scorecard, the verdict and the recommendation as a comment on each candidate
   issue.
5. **Results PR** from `docs/<round_id>-results`, containing:
   - the verdict document `docs/research/YYYY-MM-DD-<round_id>-verdict.md`;
   - a dated addendum to the pre-registration under its freeze banner (the frozen text is untouched);
   - the study directory, `docs/research/pipeline/trials.json`, and each candidate's two result files;
   - ledger rows in `backtest/tested_cells.py`, written by this orchestrating session (the analyst
     may not edit `backtest/`), with updated pins in `tests/test_tested_cells.py` if a pinned
     family's count changes;
   - for a candidate that fails, use `NO_GO` with `power="PROMOTABLE"` when its development scorecard
     has `len(window_calmars) >= 13` (the repo's n_w promotion bar), otherwise `DIRECTIONAL_NO_GO`
     with `power="DIRECTIONAL"`. Use `CLASS_KILL` only when the verdict document closes the whole
     family. `n_cells` is the candidate's frozen N. Never `PENDING`, `DATA_BLOCKED` or `SUPERSEDED`
     (uncounted);
   - `python3 -m pytest tests/test_tested_cells.py tests/test_trial_store.py -v` passing.
6. **Pass-verdict gap.** The ledger vocabulary (`VERDICTS` in `backtest/tested_cells.py`) has no pass
   value, and `PENDING` is not counted. If a candidate passes all five criteria, do not invent a
   verdict and do not stretch an existing one; write it up in the verdict document and raise the gap
   at the final stop for the operator to resolve.
7. Print and post on the round issue, verbatim, with the PR number filled in:

   ```
   STOP 3 of 3 -- operator decides. Results PR #Q is open; scorecard, gate verdict and my recommendation are on each candidate issue. Decide per candidate: promote, reject, or retest at full power. I take no further action on this round.
   ```

   This skill never merges the results PR and never closes candidate issues.

## Quality bar

- Every figure in an issue or document comes from a command whose output is pasted or linked; no
  figure is typed from memory. Sample sizes appear next to every number.
- Every claim of novelty, of a pass, or of an effect is backed by the verbatim `check_novel` output,
  the rendered scorecard or the gate's per-criterion detail.
- The pre-registration is complete before the freeze PR is opened: a missing frozen value is a
  reason to hold the PR, not to fill it in later.
- Nothing is evaluated outside the frozen grid, and nothing is hidden: losers are stored too.
- A candidate that fails is reported as failed. Do not soften a verdict, re-pick a configuration
  after seeing holdout numbers, or add a rescue variant.
- All new prose uses `--` or parentheses, never em dashes (CLAUDE.md "Writing conventions").
  Frozen records under `docs/research/` are never restyled.
- Commit messages use the conventional prefixes seen in `git log` (`docs(research):`, `feat(backtest):`).
  Push after each green step.

## Non-goals

- Not a live-trading change. "Promote" changes nothing live. Any live change needs a fresh brainstorm
  and spec, and it replaces the single decision rule (`decideHourly`); it is never added next to it.
  See CLAUDE.md "Architectural invariants".
- No edits to `supabase/functions/`, no broker or Supabase calls, no LLM inside any module that
  computes results (the AI's role is this orchestration, never the numbers).
- No re-opening a holdout, no editing or deleting stored trials or result files, no budget beyond the
  50-configuration round budget without the operator's authorizing comment on the round issue.
- No merging of the freeze PR or the results PR, and no closing of candidate issues. Those are the
  operator's decisions.
- No extension of the pipeline itself (new gate criteria, new ledger verdict values, new scorecard
  rows) inside a round. Raise them as separate issues.
- Not a survey. Product-direction research bundles are the `research-bundle` skill's job.
