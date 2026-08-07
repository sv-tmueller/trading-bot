# Daily Verification Runbook

`.github/workflows/daily-verification.yml` (#549) automates the soak-day SQL
ritual that used to be run by hand after each trading day (#535's closing
question). It fetches the `status?verify=YYYY-MM-DD` digest (#546), pipes it
through the pure evaluator `scripts/daily_verify.ts` (#547), commits the two
artifacts the evaluator writes, posts one Discord line, and opens a dated
issue when the day fails. See
`docs/superpowers/specs/2026-08-06-daily-verification-design.md` for the full
design and decision log.

## What it verifies

The evaluation logic (thresholds, expectations, pass/fail rules) lives in the
pure, unit-tested `scripts/daily_verify.ts` -- the workflow only resolves a
date, fetches the digest, pipes it through the script, and acts on the
result. The seven checks (from spec §5.3, replacing #535's manual queries of
the same numbers):

| Check | Replaces (#535) | Rule |
| --- | --- | --- |
| `slots` | check 1 | All 9 `hourly-check` runs for the day exist, every row has a non-null `finished_at`/`outcome`, and no `outcome` starts `error:`. Any breach FAILs. |
| `latency` | check 5 | Per run, `finished_at - started_at`. WARN above 10s (the per-request deadline, #511), FAIL above 120s (migration 0015's `pg_net` budget). |
| `scans` | check 2 | The number of `hourly_scans` rows must match the number of runs whose outcome actually scans (see `NON_SCANNING_OUTCOMES` in `scripts/daily_verify.ts`). A SHORT decision while `shorts_enabled` is false FAILs; a LONG row with no `entry_order_id` WARNs; a NEUTRAL-only `detectors_fired` alongside `no_detectors_fired` is never a finding (the `inside_bar` adjudication). |
| `geometry` | check 3 | Every bracket `stop_price`/`target_price` must be a whole cent. Any breach FAILs (vacuous pass on a no-trade day). |
| `journal` | check 4 | Every hourly fill must join a scan row via `entry_order_id` (`findUnmatchedEntryTrades`). An unmatched fill FAILs. |
| `state` | check 6 | `bot_config.paused` must be `"false"`; the equity baseline and its "verified" marker must be byte-identical to each other and to the previous verified day's baseline. An unset baseline WARNs (day-zero); any other breach FAILs. |
| `kill_switch` | check 7 | 108 kill-switch runs, every outcome `success:*`/`skipped:*`, and a uniform `success:no_position` alongside a LONG scan row is a contradiction. Any breach FAILs. |

A day's verdict is the highest severity across its checks: PASS, WARN (worth
a look, not broken -- opens no issue), or FAIL (opens the dated issue). A
Saturday or Sunday target is `SKIPPED_WEEKEND` and writes no artifact.

## Why weekends and holidays don't false-alarm

A weekend target is never evaluated at all -- the script returns
`SKIPPED_WEEKEND` outright. A holiday is not special-cased and needs none:
both `hourly-check` and `kill-switch` insert their `audit_log` row before any
gate (market-closed, paused, etc.), so a holiday still produces all nine
`hourly-check` rows (each `skipped:market_closed`) and all 108 kill-switch
rows, and zero `hourly_scans` rows -- which is exactly what the `slots` and
`scans` checks expect on that day, so it PASSes cleanly. This is the same
reasoning `docs/runbooks/deadman-watchdog.md` documents for its own staleness
checks; no trading calendar is needed anywhere in this evaluator.

## Required secrets

Settings → Secrets and variables → Actions. All three already exist for
`deadman-watchdog.yml` (`STATUS_URL`/`STATUS_TOKEN` also power
`heartbeat.yml`) -- this workflow introduces no new secret.

| Secret | Purpose |
| --- | --- |
| `STATUS_URL` | dev `status` function URL |
| `STATUS_TOKEN` | dev `status` function token |
| `NOTIFY_WEBHOOK_URL` | Discord incoming webhook |

Missing `STATUS_URL`/`STATUS_TOKEN` fails the run loudly (`::error::` + exit
1) -- a silently-skipping check is worthless. A missing or unreachable
`NOTIFY_WEBHOOK_URL` fails the run the same way, because exactly one Discord
line is required per run regardless of verdict (see "Green versus red"
below).

## Green versus red

Any verdict the evaluator reaches -- PASS, WARN, FAIL, or `SKIPPED_WEEKEND` --
exits the workflow **green**. The signal is the dated issue plus the Discord
line, not the run's own status, mirroring `deadman-watchdog.yml`'s rule for
the same reason: a red X on a routine FAIL day would train the operator to
ignore red runs.

Red is reserved for workflow-internal failure only:

- missing dev secrets (`STATUS_URL`/`STATUS_TOKEN`/`NOTIFY_WEBHOOK_URL`)
- a failed digest fetch -- deliberately **not** softened into a finding the
  way `deadman-watchdog.yml` does it, because the evaluator's frozen stdout
  envelope has no vocabulary for "could not fetch the digest"; a `curl`
  failure here propagates under Actions' default `bash -eo pipefail`
- `scripts/daily_verify.ts` exiting 1 (malformed input -- no JSON printed, no
  artifact written)
- a failed commit or push
- a failed Discord post

The evaluator's own exit code 2 (FAIL) is the one case that must **not**
propagate as a red run -- the workflow captures it with a `set +e`/`set -e`
idiom around the invocation (see the "Evaluate day" step), the same pattern
`deadman-watchdog.yml` uses for its own evaluation steps.

## How to read a FAIL

The run itself stays green. Two things carry the actual signal:

1. **The Discord line** -- one message per run, always, carrying the verdict,
   the headline numbers, and the findings when there are any.
2. **A dated issue**, titled `[daily-verify][dev] <date>: N finding(s)`,
   labelled `daily-verify`, deduped by exact title so a re-run of the same
   date never opens a duplicate. Its body lists the findings and links the
   committed digest and the triggering workflow run.

The detail behind both lives in the two committed artifacts:
`docs/trading-journal/daily-verification.jsonl` (the machine-readable ledger
row for the date, per-check verdicts and metrics) and
`docs/trading-journal/daily/YYYY-MM-DD.md` (the human-readable digest, in
#535's original seven-check layout). WARN opens no issue -- it is worth a
look in the digest, not an incident.

## Maintenance silence

Set the repo **variable** (not secret) `DAILY_VERIFY_SILENCED` to exactly
`true`. Every step short-circuits to an inert `::notice::` green exit -- no
fetch, no evaluation, no commit, no Discord post, no issue activity -- same
idiom as `deadman-watchdog.yml`'s `DEADMAN_SILENCED`. Unset it (or set it to
anything else) to re-arm.

## Backfilling a specific date

`workflow_dispatch` takes an optional `date` input (`YYYY-MM-DD`). Backfill one
date at a time; running two dates concurrently would race on the same commit.

**Backfill oldest date first, and re-run any date that already has a digest
rendered before its predecessor existed.** The ledger itself is upserted and
kept in date order, so its ordering is safe whatever sequence you use, but the
markdown digest's "Changed since the previous verified day" section is rendered
from the previous ledger row **at render time**. A day rendered while it had no
predecessor keeps saying so, permanently, even after earlier dates land.

That was demonstrated when this ledger was first backfilled (#545): 2026-08-06
was verified first and its digest read "No previous verified day to compare
against (day zero)" (commit `76e001b`). After 08-03 through 08-05 were
backfilled, re-running 08-06 re-rendered the same date as "Max latency: 2454ms
-> 8054ms" plus "First entry recorded since the previous verified day"
(`5888da9`). Same date, different content, from ordering alone.

```bash
# oldest first
gh workflow run daily-verification.yml -f date=2026-08-03
gh workflow run daily-verification.yml -f date=2026-08-04
# then re-run anything already rendered as day zero
gh workflow run daily-verification.yml -f date=2026-08-06
```

A re-run of a date whose comparison section does not change is a byte-identical
no-op and the commit step skips it, so re-running more dates than strictly
necessary costs nothing but a workflow run and one Discord line each.

Without `-f date=`, the workflow resolves today (UTC) when the UTC hour is
12 or later, otherwise yesterday (UTC) -- matching the 22:15 UTC schedule,
which always evaluates the day that just closed.

## Known caveats

- **The prod leg is inert, permanently, not just pre-go-live.** Unlike
  `deadman-watchdog.yml` and `heartbeat.yml`, whose prod legs become full
  symmetric pipelines the moment `STATUS_URL_PROD`/`STATUS_TOKEN_PROD` are
  set, this workflow's prod leg is a `::notice::` and nothing more, even
  once those secrets exist. The reason is the artifact schema: both
  `docs/trading-journal/daily-verification.jsonl` and
  `docs/trading-journal/daily/YYYY-MM-DD.md` are keyed by **date alone, with
  no environment dimension**. A live prod leg would write the same
  date-keyed ledger row and digest file as the dev leg for the same calendar
  day, and whichever leg ran second would silently clobber the other --
  nobody would notice until the ledger was used for the trend analysis it
  exists for. Activating a real prod leg needs the artifact schema
  namespaced per environment first, which is out of scope for this workflow
  and is filed as a follow-up that must land before anyone flips the prod
  switch at #230.
- **End-to-end verification needs three packages, not one.** The fetch step
  targets `status?verify=`, which the deployed `status` function does not
  recognise until #546 is merged **and deployed**. The full operator
  sequence before trusting the schedule: merge and deploy #546, merge #547,
  merge #549 (this workflow), then one `workflow_dispatch` against a
  known-good recent date to confirm the real pipeline before letting the
  22:15 schedule take over.
- **GitHub schedule jitter and the 60-day auto-disable** apply here exactly
  as documented in `docs/runbooks/deadman-watchdog.md`'s own caveats
  section.
- **Public repo.** Forks get none of the secrets above, and GitHub disables
  scheduled workflows on forks by default, so a fork's copy of this workflow
  is inert.

## Manual fallback

The manual SQL ritual this workflow automates is not deleted -- see
`docs/trading-journal/README.md`'s "Manual verification fallback" section
for the corrected, durable copy of the seven queries (originally #535).

## See also

- `docs/runbooks/status-check.md` -- the underlying `status` digest,
  including the `verification` block this workflow's fetch step reads.
- `docs/runbooks/deadman-watchdog.md` -- the sibling workflow this one is
  structurally modeled on (silence flag, loud-fail dev secrets,
  capture-then-branch evaluation, never printing the raw digest).
- `docs/runbooks/weekly-review.md` -- the weekly strategy-judgment journal;
  this workflow is daily plumbing verification, not strategy review.
