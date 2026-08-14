---
name: weekly-reflection
description: Use this skill to run the weekly critique of the hourly bot's trading week -- reads the week's daily reflections, verification data, and open/closed hypothesis issues, then writes a reflections doc and (outside dry-run) files or updates hypothesis issues. Invoke when the operator or advisor session says "run the weekly critique", "weekly reflection for W<week>", "critique this week's trading", or "dry-run the weekly reflection".
---

# Weekly Reflection

Write the weekly qualitative critique of the hourly bot's trading week and, where the deterministic
nightly triggers (design doc §3) warrant it, propose or update `hypothesis`-labeled issues for the
operator to dispose of at the weekly review gate. This is stage 2 of the reflection loop; stage 1
(nightly, deterministic, per-trade counterfactuals) and stage 3 (the operator gate) are described in
[`docs/superpowers/specs/2026-08-14-reflection-loop-design.md`](../../../docs/superpowers/specs/2026-08-14-reflection-loop-design.md)
(§2 stage 2, stage 3, §4). Read that design doc before running this skill -- it is the design
authority; this skill is the operating procedure.

Pure documentation and issue-tracker output. No code changes, no config changes, no broker or DB
writes -- everything this skill touches is a Markdown file or a GitHub issue.

## Inputs

- `<week>` (required) -- the ISO week to critique, e.g. `2026-W32`. Use `date +%G-W%V` for "this
  week" if the operator says "run the weekly critique" without naming one; critique the last
  *completed* ISO week (Monday-Friday) unless told otherwise.
- `<dry-run scratch path>` (optional) -- see [Dry-run mode](#dry-run-mode). When absent, run live:
  write to `docs/trading-journal/reflections/<week>.md` and use `gh issue` for real.

## Sources (read all of these before writing anything)

1. **The week's daily digests**, `docs/trading-journal/daily/<date>.md` for every trading day in
   `<week>` (Monday through Friday, skipping days the market was closed) -- specifically each
   digest's `## Reflection` section (stage 1 output). A day with no `## Reflection` section means
   stage 1 has not run for that day yet; see [Data-availability rule](#data-availability-rule). If
   the digest file itself does not exist for a trading day in the week -- distinct from a day the
   market was closed, which is already skipped above -- because that day has not yet closed or been
   verified (a mid-week invocation), note it as "not yet verified" in section 1's data-availability
   line, read nothing for that day, invent nothing for it, and file nothing on its account.
2. **`docs/trading-journal/daily-verification.jsonl`** -- the per-day machine-readable record
   (entries, fills, closed trades, R-multiples where present). Use it to fill in the per-trade table
   even in weeks with no `## Reflection` sections yet -- it is the only source that predates stage 1.
3. **The prior week's reflection doc**, `docs/trading-journal/reflections/<prior week>.md`, if one
   exists -- needed to judge whether a trigger firing this week is persistent or one-week noise
   (design §2 stage 2, item 2). If it does not exist, say so plainly; do not infer a trend from one
   week.
4. **The weekly journal entry**, `docs/trading-journal/<week>.md`, if one has been rendered for the
   week (`scripts/render_weekly_journal.ts`, see
   [`docs/runbooks/weekly-review.md`](../../../docs/runbooks/weekly-review.md)). If it does not
   exist yet, say so; do not block on it -- the daily digests and JSONL are sufficient to write the
   evidence section.
5. **Open AND closed `hypothesis` issues** -- `gh issue list --label hypothesis --state all`. This is
   load-bearing, not optional: reading only open issues makes the no-re-filing-after-closure rule
   (below) unenforceable, because a closed issue would look identical to one that was never filed.

Never re-derive or restate the three deterministic trigger thresholds, the counterfactual
definitions, or the CLAUDE.md Architectural invariants here -- read the printed trigger lines from
the daily digests and cite the design doc (§3) and CLAUDE.md by reference. Only the nightly
reflection engine (#578) owns those numbers; this skill drifting a second copy of them is the
principal risk called out in the architect's plan for this issue.

## Writing the reflections doc

Write `docs/trading-journal/reflections/<week>.md` (or the dry-run scratch path -- see below) with
exactly three sections. **These headings are the contract between this skill and
[`docs/trading-journal/reflections/TEMPLATE.md`](../../../docs/trading-journal/reflections/TEMPLATE.md)
-- keep them byte-identical in both places:**

### `## 1. What the week's evidence shows`

A per-trade table (date, exit type, nominal vs realized R) for every closed trade in the week, plus
the trailing-20 table **carried over verbatim from the latest daily `## Reflection` section of the
week** (realized R cumulative, 1.0R/1.5R counterfactual cumulative, stop-width survival rate, cost
vs the 5bps model). Print the sample size next to every number (design §3's restraint: sample sizes
are printed next to every number, never implied).

#### Data-availability rule

If no daily digest in the week has a `## Reflection` section yet (the pre-engine period, true for
every week before #578 ships), write one explicit line stating that: only entries, fills, and
R-multiples from `daily-verification.jsonl` and the daily digests are available for this week, and
that every counterfactual column (R-target replay, stop-width survival, cost-vs-5bps) is `n/a`. Do
not compute or estimate counterfactuals from data that was not designed to carry them.

### `## 2. Deterministic triggers`

List which of the three v1 triggers (design §3) fired on which days, **read from the trigger lines
each daily digest's `## Reflection` section already prints -- never recomputed here**. For each
trigger that fired, give a persistent-vs-one-week-noise judgment against the prior week's
reflection doc if one exists (same trigger firing two weeks running is the persistence signal;
firing once with no prior-week doc to compare against is noise until proven otherwise).

If the week has no `## Reflection` sections, write: "no trigger data; reflection engine not yet
wired" and stop there -- do not guess at which triggers might have fired.

### `## 3. Recommendations (ranked)`

A ranked list. Each entry is one of:

- **file new** -- a new hypothesis issue is warranted (see [Hypothesis-issue
  format](#hypothesis-issue-format)).
- **strengthen existing #N** -- new evidence supports an already-open hypothesis issue.
- **close stale #N** -- an open hypothesis issue's premise no longer holds, or repeated weeks of
  data have not reproduced it.
- **no action** -- the expected outcome most weeks.

Every entry carries its evidence lines (dated, from section 1 or 2 -- never a bare assertion).

Close the section with a footer restating, by reference only, the two standing restraints from the
design doc: the critique never proposes bypassing a pre-registered study, and every recommendation
here is an input to the operator gate (design §2 stage 3), never a decision this skill makes itself.

## Hypothesis-issue format

One source of truth for the issue shape -- this section, not duplicated anywhere else. When section
3 recommends "file new", open an issue with:

- **Title:** `Hypothesis: <one-liner>`
- **Label:** `hypothesis`
- **Body**, exactly three required sections:

```markdown
## Evidence

<!-- The exact dated evidence lines from section 1/2 of the reflections doc that triggered this
     hypothesis. Quote them, do not paraphrase. -->

## Proposed pre-registerable test

<!-- Arm grid, data window, metric -- follow the #571 harness conventions (pre-registration commit
     before results, frozen grid, explicit stopping rule). This section proposes the study; it does
     not run it. -->

## What would change live

<!-- The named config or spec parameter this hypothesis is about, and the direction of the proposed
     change (e.g. "HOURLY_BRACKET_R_MULTIPLE: 2 -> 3"). One sentence. -->
```

### Lifecycle rules

- **Read open and closed issues first** (`gh issue list --label hypothesis --state all`, per
  [Sources](#sources-read-all-of-these-before-writing-anything) above).
- **Never re-file after gate closure** unless the new evidence lines postdate the closure date. A
  closed hypothesis issue represents an operator decision (design §2 stage 3); re-filing the same
  premise on the same evidence re-litigates a decision that was already made. If the evidence is
  genuinely new (dated after the issue's closed-at timestamp), file a fresh issue that references the
  closed one and states what changed.
- **Strengthen = comment.** Add the new evidence as a comment on the existing open issue. Do not
  close and re-open, do not file a duplicate.
- **Close stale = comment the reason, then close.** Always comment the reason before closing -- the
  comment is the record a future critique reads to know why it should not re-file.
- Per design §4: **if the week has no daily reflections, write the gap notice (section 2's "no
  trigger data" line) and file nothing.** This is the rule that keeps the pre-engine period safe --
  without it, a run against weeks with no counterfactual data could file evidence-free hypotheses.

## Dry-run mode

When the operator gives a scratch path instead of running live:

- Write the reflections doc to that scratch path, **never** to
  `docs/trading-journal/reflections/<week>.md`.
- **No mutating `gh` command runs** -- no `gh issue create`, `gh issue comment`, `gh issue close`,
  `gh label create`, or similar. Read-only `gh issue list ... --state all` still runs, because the
  lifecycle rules need real issue state to reason about correctly, even in a dry run.
- Every issue action section 3 would otherwise have taken (file new / strengthen / close stale, with
  the issue body or comment text each would have used) is instead rendered as a trailing appendix
  titled `## Dry-run: intended issue actions`, so the operator can review exactly what a live run
  would have done without anything actually happening on the tracker.

## Non-goals

- No code changes, no test changes, nothing under `supabase/`.
- No autonomous parameter changes -- every recommendation this skill produces is an input to the
  operator gate (design §2 stage 3), never applied by this skill or by any agent running it.
- No restating of the CLAUDE.md Architectural invariants or the #578 nightly trigger thresholds --
  reference both, never copy them.
- No filing of hypothesis issues in dry-run mode, and none at all for a week with no daily
  reflections (design §4).
