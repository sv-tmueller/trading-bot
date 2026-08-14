# Weekly-Review Journal Runbook

Setup and execution for `scripts/render_weekly_journal.ts` (#481, batch #478 Package C, spec
[`docs/superpowers/specs/2026-07-27-hourly-bot-design.md`](../superpowers/specs/2026-07-27-hourly-bot-design.md)
§11/§14 finding 10) -- the operator-run, read-only aggregator over `hourly_scans` + `trades` that
renders `docs/trading-journal/YYYY-Www.md` for the hourly candlestick bot. Not a cron, not an Edge
Function -- run it manually once a week (or on demand).

It reports: per-detector firing rates, entries/exits with R-multiples, gate-skip distribution
(bar-level `hourly_scans.skip_reason` and run-level `audit_log` outcomes), equity trajectory vs the
spec's -15% floor, the `PROPOSAL_RULE` trigger statistics, and a "Journal integrity" section
surfacing the `success:journal_degraded` count, orphaned pending scan rows, and unmatched entry
trades (#486) -- see `docs/runbooks/hourly-bot-rollout.md` §10 for the manual-reconciliation
procedure. It never writes to `trades`,
`hourly_scans`, or `audit_log`, and it never places a broker order -- the only write it can ever
make is the trial-counter bump described below, and that only in its own separate mode.

When comparing the journal's live paper results against backtest figures, remember the backtest's
return and drawdown numbers are all-in, while live runs at `SIZING_NOTIONAL_CAP_PCT = 0.10` --
divide backtest figures by ~10 before comparing (#499).

## Prerequisites

- Migration `0012_hourly_scans.sql` applied (`supabase db push`).
- `bot_config.hourly_experiment_start_equity` set (the paper-experiment baseline the -15% floor is
  measured against, spec §11) -- the script exits with a clear one-line error naming the key if it
  is missing.
- [Deno](https://deno.com/) installed (same runtime the Edge Functions use).
- The Supabase project's `SUPABASE_URL` and **service-role** key (bypasses RLS -- treat it like a
  production secret, never commit it). No Alpaca credentials are needed or read (D3 -- equity comes
  from `hourly_scans.equity_usd`, journaled by every scan, not from a live broker call).

## One-time setup

```bash
cp .env.weekly.example .env.weekly
```

Edit `.env.weekly`:

```
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role key>
```

`.env.weekly` is gitignored -- never commit it.

## Rendering an entry

```bash
deno run --allow-env --allow-net --allow-write=docs/trading-journal \
  --env-file=.env.weekly scripts/render_weekly_journal.ts
```

With no flags, this renders the **previous completed ISO week** (Monday-Friday, computed from the
current date) to `docs/trading-journal/<week>.md`. Run it on or after the Saturday following a
trading week so the full week's data is available -- the same cadence the journal README already
documents for hand-written entries.

### `--week YYYY-Www`: render a specific week

```bash
deno run --allow-env --allow-net --allow-write=docs/trading-journal \
  --env-file=.env.weekly scripts/render_weekly_journal.ts --week 2026-W32
```

### `--out PATH`: write somewhere other than the default location

```bash
deno run --allow-env --allow-net --allow-write=/tmp \
  --env-file=.env.weekly scripts/render_weekly_journal.ts --week 2026-W32 --out /tmp/preview.md
```

### `--force`: overwrite an existing journal file

The script **refuses to overwrite** an existing `docs/trading-journal/YYYY-Www.md` by default (exit
1) -- hand-written entries are never silently clobbered. Pass `--force` only when you deliberately
want to re-render a week (e.g. after a data-entry correction upstream):

```bash
deno run --allow-env --allow-net --allow-write=docs/trading-journal \
  --env-file=.env.weekly scripts/render_weekly_journal.ts --week 2026-W32 --force
```

### Determinism

Every query the script issues is upper-bounded by the target week's end (Saturday 00:00 ET,
converted to UTC), so re-running the same `--week` later reproduces byte-identical output as long
as no `--force` re-render follows a change to the underlying data. There is no `Date.now()` in the
rendered content itself -- the one value that is inherently "as of this run" is the
`hourly_param_trial_count` reading in the footer, which is labelled as such.

## The PROPOSAL_RULE section

The rendered "Proposal (PROPOSAL_RULE)" section respects the spec's two constraints, enforced in
code (`scripts/render_weekly_journal.ts`'s `proposeParamChange`), not by convention:

- **At most one proposal per rendered week.** The rule evaluates a ranked candidate list and
  returns the first triggered candidate, or none.
- **A stated minimum sample before any proposal may fire.** Below `PROPOSAL_MIN_CLOSED_TRADES`
  (currently 30, aligned with the spec's own 30-closed-trade checkpoint) the section instead
  renders an explicit `no proposal permitted (N=x < 30)` line, even if a candidate's statistic
  would otherwise have triggered.

The shipped default candidate is the spec §11 worked example: cumulative target-hit rate below
`TARGET_HIT_RATE_FLOOR` (25%) proposes `§7 HOURLY_BRACKET_R_MULTIPLE: 2 -> 3`. **Both numbers, and
the single-candidate list itself, are defaults the operator owns and may amend** in
`scripts/render_weekly_journal.ts` -- the same operator-amendable-default pattern the spec already
uses for its 4-week/30-trade stopping rule. A proposal rendered here is **never** applied
automatically; it is an input to a human-approved version bump (a new spec revision + a new ADR),
exactly like every other parameter change in this repo.

## Weekly critique and hypothesis gate (#579)

Stage 2/3 of the self-reflection loop, spec
[`docs/superpowers/specs/2026-08-14-reflection-loop-design.md`](../superpowers/specs/2026-08-14-reflection-loop-design.md)
§2. Separate from rendering the journal entry above -- this is a qualitative critique, not a
data aggregation.

**Trigger.** After rendering the week's journal entry (above), the operator (or an advisor
session) invokes the `weekly-reflection` skill
(`.claude/skills/weekly-reflection/SKILL.md`) for the week just closed. Not a cron, not an
Edge Function -- like the render step, this is operator-initiated.

**What it produces.** `docs/trading-journal/reflections/YYYY-Www.md`, and where the week's
deterministic triggers warrant it, new or updated `hypothesis`-labeled GitHub issues. See the
skill for the full source list, the three-section doc contract, and the hypothesis-issue
format and lifecycle rules -- not restated here.

**The gate.** At the weekly review the operator disposes each open `hypothesis` issue:

- **Approved** -- the hypothesis moves through the normal advisor/kickoff pipeline as a study
  package (the #571 harness is reusable), then, on a positive verdict, an ADR plus a config
  change PR. Once that PR is merged, bump the trial counter via this runbook's **existing**
  `--record-accepted-bump --ref <ADR-path-or-issue>` mode (below) -- the same mechanism, no
  second counter path.
- **Rejected** -- close the issue with the stated reason as a comment. The next weekly
  critique respects the closure and will not re-file the same premise on the same evidence
  (see the skill's lifecycle rules).

**No action most weeks.** The expected outcome of most weekly critiques is "no action" --
treat a week with nothing to dispose of as normal, not as a gap in the process. The
pre-registered ~2026-08-26/28 experiment checkpoint (spec §11) is unaffected either way; the
critique and gate run alongside it, not in place of it.

## Recording an accepted version bump

`--record-accepted-bump` is a **separate mode**, mutually exclusive with the render flags above.
It is the **only** database write this script ever makes: it increments
`bot_config.hourly_param_trial_count` by 1 and prints the old and new values plus the reference you
gave it. It renders nothing.

```bash
deno run --allow-env --allow-net \
  --env-file=.env.weekly scripts/render_weekly_journal.ts \
  --record-accepted-bump --ref docs/decisions/2026-09-01-bump-bracket-r-multiple.md
```

`--ref` is required (an ADR path or an issue reference) -- the command refuses to run without it.

**Run this only after the operator has merged the version-bump ADR and the corresponding spec
revision/config change** -- not when a proposal first appears in a rendered journal entry. The
trial counter exists to keep the review loop honest about how many parameter changes have already
been tried against the same paper-trading history (the same discipline `backtest/tested_cells.py`
applies to research grids); incrementing it before the change is actually accepted and shipped
would misrecord the trial count.

## Troubleshooting

- **`bot_config.hourly_experiment_start_equity is not set`** -- the paper-experiment baseline
  hasn't been set yet. Set it once, at Batch 3 deploy time, via the same `bot_config` mechanism
  `panic action=pause` uses; see spec §11.
- **`<path> already exists -- pass --force to overwrite`** -- a journal entry for that week already
  exists. Re-render only with `--force` if you deliberately intend to replace it.
- **`--record-accepted-bump requires --ref <ADR-path-or-issue>`** -- the bump mode never runs
  without an explicit reference; supply the ADR path or issue.
