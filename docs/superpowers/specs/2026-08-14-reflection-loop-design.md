# Self-reflection and gated self-improvement loop

Date: 2026-08-14
Status: design approved in brainstorm (operator, 2026-08-13/14); packaging pending sign-off
Origin: operator request via /tm-advisor: the bot should document its trades, critique them,
and improve over time (risk, strategies, stop/limit settings).

## 1. Problem and framing decisions

What already exists: every trade is recorded (`trades`, `audit_log`, `hourly_scans`), the
daily-verification workflow writes per-day docs with entries, fills, and realized R-multiples,
and the weekly journal plus research studies cover episodic analysis. What does not exist is a
standing reflection loop: per-trade counterfactual critique, machine-surfaced improvement
hypotheses, and a regular decision cadence for them.

Three framing decisions were taken in the brainstorm, in this order:

1. **The gate stays human.** The bot reflects and proposes; it never changes its own risk,
   strategy, or geometry. Autonomous self-tuning was considered and rejected: it conflicts with
   the "one decision rule" and "no LLM in the trading path" invariants (CLAUDE.md,
   Architectural invariants) and repeats the v1.14 failure mode. Daily parameter adaptation on
   1-4 trades/day is fitting noise; the spec discipline of
   `2026-07-27-hourly-bot-design.md` §11 (registered trials, no post-hoc selection) applies to
   every change this loop produces.
2. **Deterministic daily, LLM weekly.** The nightly reflection is fully mechanical and
   reproducible. A weekly agent run writes the qualitative critique and files hypothesis
   issues. An LLM writing prose nightly about 1-4 trades was rejected as cost without signal
   and as pressure to react daily.
3. **Weekly decision cadence.** The operator decides on filed hypotheses at the weekly review.
   Most weeks the correct outcome is "no change". The pre-registered experiment checkpoint
   (~2026-08-26/28) is unaffected.

Approach chosen: extend existing rails (verification workflow + agent team + issue backlog).
A reflection Edge Function / DB table and agent-only nightly journaling were considered and
rejected (new production surface without need; non-reproducible nightly LLM).

## 2. Architecture

Three stages on three cadences; only stage 1 is code.

**Stage 1, nightly (deterministic).** After the existing seven verification checks, a
reflection step:

- loads the day's `hourly_scans` rows (decision, geometry, sizing per bar) and closed trades;
- fetches the day's 5-minute bars read-only from the Alpaca data host (SIP, `end` = previous
  UTC day, reusing the UTC-safe default from #575); the verification workflow already holds
  read-only data access and stays read-only toward broker and DB;
- computes the per-trade counterfactuals in section 3 with the study harness conventions
  (`_resolve_bar`: stop-first on both-touched bars, gap handling, flatten timing);
- appends a `## Reflection` section to `docs/trading-journal/daily/<date>.md` and structured
  fields to the JSONL record. A day with no closed trades writes one line: "no closed trades;
  no reflection".

**Stage 2, weekly (LLM, outside the trading path).** An agent run reads the week's daily
reflections, the weekly journal, and open `hypothesis` issues, then writes
`docs/trading-journal/reflections/<year>-W<week>.md` with three fixed sections:

1. what the week's evidence shows (trailing-20 tables carried over);
2. which deterministic triggers fired, and whether the pattern is persistent or one-week noise;
3. ranked recommendations: file new hypothesis / strengthen existing / close stale / no action.

It then files or updates `hypothesis`-labeled issues accordingly. Each issue carries the
evidence lines, a proposed pre-registerable test (arm grid, data, metric), and an explicit
"what would change live" statement. The critique never proposes bypassing a study.

**Stage 3, weekly (operator gate).** At the weekly review the operator approves or rejects
each hypothesis. Approved: a study package through the normal advisor/kickoff pipeline (the
#571 harness is reusable), then, on a positive verdict, an ADR plus config change PR; the
trial counter increments per §11. Rejected: the issue is closed with the reason, and the next
weekly critique respects it (no re-filing without new evidence).

## 3. Nightly reflection content

Per closed trade:

- **Trade record**: detectors fired, entry/exit fills, exit type (target / stop /
  session-flatten), nominal vs realized R, and the mechanical reason for the deviation (gap,
  slippage, flatten).
- **R-target counterfactuals**: same entry replayed on the day's 5-minute bars with targets at
  1.0R and 1.5R (live config is 2R), per trade and cumulative over the trailing 20 trades.
- **Stop-placement counterfactuals**: stop at 1.25x and 1.5x the frozen buffer distance, plus
  the maximum adverse excursion beyond the stop before reversal (stopped-then-reversed is the
  signature of a too-tight stop).
- **Flatten counterfactual**: the no-flatten replay (study convention), per trade.
- **Cost check**: realized slippage per fill vs the study's frozen 5bps assumption. This
  accumulates the live-vs-model evidence behind the study's NO_GO mechanism.
- **Trailing summary**: the same metrics over the last 20 closed trades, always printed next
  to the day's numbers so single-day noise sits beside its running context.

Standing restraints, printed in the doc each night: counterfactuals are diagnostic, not
trials; nothing is selected on them until a hypothesis is pre-registered and studied (§11,
#398); sample sizes are printed next to every number.

Deterministic hypothesis triggers, exactly three in v1, each printing a suggested hypothesis
line in the daily doc (only the weekly agent files issues):

1. at least 60% of the trailing-20 stop-outs would have survived at 1.25x stop width;
2. a closer R-target (1.0 or 1.5) beats 2R cumulatively over the trailing 20;
3. realized costs diverge from the 5bps model by more than 2x in either direction.

## 4. Error handling

- A reflection failure never fails verification: the step is wrapped, degrading to
  `Reflection: error -- <reason>` in the daily doc while the seven safety checks keep their
  own verdict.
- Missing or partial 5-minute bars: the reflection reports data-unavailable for the affected
  trades and computes nothing for them.
- The weekly agent finding no daily reflections writes a gap notice and files nothing.

## 5. Testing

- Counterfactual computations: unit tests against fixture bars, reusing the study's test
  patterns (tie-break, gap, flatten timing, trailing-window accounting).
- Workflow change: a dry-run mode over recorded fixtures (a known day's scans + bars) so the
  reflection section can be regression-tested without network or DB.
- Trigger rules: table-driven tests for each of the three triggers at, below, and above their
  thresholds.

## 6. Invariant compliance

Structural, verified by the reviewer gate on every package: nothing under
`supabase/functions/` changes; no LLM output ever reaches config or broker; all writes are
docs and issues; the decision rule, geometry, sizing, and cadence of the live bot are
untouched by stages 1 and 2. Stage 3 changes go through pre-registered studies and ADRs, per
the Architectural invariants section of CLAUDE.md (referenced, not restated).

## 7. Non-goals

- No autonomous parameter tuning, bounded or otherwise (a bounded-self-tuning rule would be a
  new frozen decision rule and needs its own brainstorm, study, and ADR).
- No LLM in the nightly path and no nightly prose.
- No new Edge Function, DB table, or migration.
- No change to the current experiment or its ~2026-08-26/28 checkpoint.
- No backfill of reflections for past days (the loop starts when it ships).

## 8. Packaging sketch (advisor slices at sign-off)

1. Nightly reflection engine + tests (counterfactuals, triggers, doc/JSONL emission), size:M.
2. Verification-workflow wiring + dry-run fixtures + runbook update, size:S.
3. Weekly critique agent definition (prompt, doc template, hypothesis-issue format, labels)
   + weekly-review runbook update, size:S.
