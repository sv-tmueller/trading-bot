# Dead-man Watchdog Runbook

`.github/workflows/deadman-watchdog.yml` (#396) detects a **stalled trading
pipeline** — `daily-check` and/or `kill-switch` have stopped being invoked by
`pg_cron` entirely — from outside Supabase. The alert path is the GitHub
Actions runner + `curl` against the read-only `status` Edge Function + a
Discord webhook, so it still fires even if every Supabase component (the
project itself, `pg_cron`, the Edge Functions) is dead. This complements
`heartbeat.yml` (keeps the project awake) and `soak-digest.yml` (weekly
summary) — neither of those alerts on a stalled pipeline on its own.

## What it monitors

The evaluation logic (armed windows, staleness thresholds, weekday/weekend
handling) lives in the pure, unit-tested `scripts/deadman_check.ts` — the
workflow only fetches the digest and latches on the result. Threshold table,
derived from the `pg_cron` schedules (CLAUDE.md "Daily flow" / "Intraday
kill-switch"):

| Script | Armed window (UTC, weekdays only) | Stale condition |
| --- | --- | --- |
| `daily-check` | `now >= 15:00` | latest `last_runs.daily_check` row started before today's `13:30` UTC, or absent |
| `kill-switch` | `13:20 <= now <= 22:10` | latest `last_runs.kill_switch` row is more than 20 minutes old (4 missed 5-minute slots), or absent |

- `daily-check`'s `pg_cron` fires at `37 13 * * 1-5` and `37 14 * * 1-5` UTC
  (two DST-covering slots) — the check only arms at 15:00 UTC, after both
  slots have had a chance to run, and one slot having run today is healthy
  by design (the second slot is pure DST redundancy).
- `kill-switch`'s `pg_cron` fires every 5 minutes, `13:00`-`21:55` UTC — the
  armed window starts a few minutes after the first slot (`13:20`, avoiding
  a false alarm at window start when yesterday's `21:55` row is still the
  latest) and ends a few minutes after the last slot (`22:10`).
- **Do not tighten the kill-switch threshold below 20 minutes.** GitHub
  Actions schedule jitter (typically a few minutes, occasionally up to ~1h)
  would otherwise false-alarm.

## Why weekends/holidays can't false-alarm

Both `daily-check` and `kill-switch` insert their `audit_log` row **before
any gate** (market-closed, `bot_config.paused`, etc.) — so even a market
holiday or a paused bot leaves a fresh row with a `skipped:*` outcome. The
watchdog only ever inspects `started_at` timestamps, never `outcome` content
— a `skipped:market_closed` row from today is exactly as healthy as a
`success` row. This is why **no holiday calendar is needed anywhere in this
package**: a real staleness finding only happens when the scheduled
invocation itself stops firing, which only a dead `pg_cron` job, a dead
Supabase project, or a crashed function (one that fails before it can write
its `audit_log` row) can cause. Weekends are excluded outright by UTC weekday
— `pg_cron`'s `1-5` day-of-week clause never fires on Sat/Sun, so a weekend
absence is expected, not a finding.

## Required secrets

Settings → Secrets and variables → Actions:

| Secret | Purpose |
| --- | --- |
| `STATUS_URL` | dev `status` function URL (same value as `.env.status` / `soak-digest.yml`) |
| `STATUS_TOKEN` | dev `status` function token |
| `NOTIFY_WEBHOOK_URL` | Discord incoming webhook — same value as the Supabase `NOTIFY_WEBHOOK_URL` secret (see `docs/runbooks/discord-notifications.md`) |
| `STATUS_URL_PROD` | prod `status` function URL — set at go-live (#230) |
| `STATUS_TOKEN_PROD` | prod `status` function token — set at go-live (#230) |

The dev leg is **required coverage**: missing `STATUS_URL`/`STATUS_TOKEN`
fails the run loudly (`::error::` + exit 1), same idiom as `soak-digest.yml`
— a silently-skipping watchdog would be worthless. The prod leg is an
**inert green skip** (`::notice::`) until both `STATUS_URL_PROD` and
`STATUS_TOKEN_PROD` are set (prod isn't deployed pre-go-live, #230); a red
dev leg never skips the prod leg (its steps are gated on `!cancelled()`, not
`success()`).

## Issue-latch semantics (dedup — at most one alarm per incident)

On a finding, the workflow ensures a `deadman-dev` (or `deadman-prod`) label
exists, then looks for an **open** issue carrying that label:

- **No open issue** → creates one (title, the finding text, and a link to
  the triggering workflow run) and posts the single Discord alert.
- **An open issue already exists** → no-op. That open issue **is** the
  dedup — the watchdog runs every ~30 minutes during market hours and must
  not re-alert every time.
- **Healthy evaluation, open issue exists** → closes it with a "recovered"
  comment. **Closing the issue re-arms the alarm** — the next finding (if
  any) opens a fresh issue.
- **Healthy evaluation, no open issue** → nothing happens.

A run that successfully delivers an alarm (creates the issue + posts to
Discord, or dedups against an already-open issue) exits **green** — the
open issue is the incident marker, and a red X on every poll while an
incident is open would be its own spam channel. **Red is reserved for
watchdog-internal failure**: dev secrets missing, or the Discord post
failing while there are findings and no issue was already open to dedup
against — in that failure case the latch issue is still created (the
incident is never silently unrecorded), but the run itself goes red so a
broken/missing webhook is loud, not silent.

## Silencing during maintenance

Set the repo **variable** (Settings → Secrets and variables → Actions →
Variables, not a secret) `DEADMAN_SILENCED` to the exact string `true`.
Every step short-circuits to an inert `::notice::` green exit — no fetch, no
evaluation, no latch activity (same idiom as `heartbeat.yml`'s
`HEARTBEAT_REQUIRE_PROD`). **Unset it** (or set it to anything else) to
re-arm. This does not touch any already-open latch issue — close it manually
if the underlying incident was addressed during the silenced window.

## Manual smoke test

Trigger the workflow from the Actions tab (`workflow_dispatch`, no inputs) —
or `gh workflow run deadman-watchdog.yml`. With a healthy stack this should
exit green with no issue activity. To exercise the alert path end-to-end
without waiting for a real incident, temporarily point `STATUS_URL`/
`STATUS_TOKEN` at a scratch/broken endpoint (or manually pipe a synthetic
digest through the evaluator: `echo '{"last_runs":{"daily_check":null,
"kill_switch":null}}' | deno run scripts/deadman_check.ts` — **during an
armed weekday window** (see the table under "What it monitors"; roughly
13:20–22:10 UTC) **this exits 2 with findings printed**, confirming the pure
evaluation path independent of any network call; **outside the armed
windows — nights, weekends — the same command exits 0 because nothing is
armed**), then revert.

## Caveats

- **GitHub schedule jitter.** Scheduled workflow runs are not guaranteed to
  fire at the exact cron minute — delays of a few minutes, and occasionally
  up to about an hour under load, are normal. Combined with the 20-minute
  kill-switch threshold and the ~30-minute poll cadence, worst-case
  detection latency for a real incident is on the order of ~1 hour. This is
  acceptable for a dead-man alarm (it is a backstop, not a real-time
  monitor) but is why the kill-switch threshold must not be tightened
  further (see above).
- **GitHub's 60-day auto-disable.** GitHub automatically disables a
  scheduled workflow after 60 days with no repository activity at all. This
  repo has frequent commits and other scheduled workflows
  (`backup-db.yml`, `heartbeat.yml`), so this is a low but non-zero residual
  risk — if it ever fires, `deadman-watchdog.yml` stops running silently (no
  notification from GitHub itself), and re-enabling requires a manual visit
  to the Actions tab.
- **Public repo.** Forks get none of the secrets above, and GitHub disables
  scheduled workflows on forks by default — a fork's watchdog is inert.

## See also

- `docs/runbooks/status-check.md` — the underlying `status` digest,
  including the `last_runs` field this watchdog consumes.
- `docs/runbooks/discord-notifications.md` — the Discord webhook used both
  by the bot itself and (with the same URL, as a separate repo secret) by
  this watchdog.
