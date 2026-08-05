# Retire the DB backup workflow

Remove `.github/workflows/backup-db.yml` instead of keeping it as inert scaffolding.

**Date:** 2026-08-04
**Status:** accepted

---

## Context

`docs/decisions/2026-07-07-supabase-row-data-backup.md` decided to back up
Supabase row data with a weekly `backup-db.yml` workflow: `supabase db dump
--data-only`, encrypt with `openssl`, commit the result to
`backups/db-dump-latest.sql.enc`. The workflow was inert until three repo
secrets were set (`SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD`,
`BACKUP_ENCRYPTION_KEY`).

Those secrets were never set. `git log --all -- backups/` returns no commits
— the workflow never landed a single dump in its lifetime. The operator does
not rely on a repo-committed dump as a data-recovery channel; `audit_log`
history and the weekly trading journal already reconstruct the timeline the
2026-07-07 ADR cited as the diagnostic value being protected. `backup-db.yml`
carried its own `permissions: contents: write` grant (needed to push the
encrypted dump to `main`) — removing the workflow drops that grant along
with the dead code. `weekly-research-review.yml` carries the same grant for
an unrelated purpose (committing the rendered research review and pushing
it, see its own workflow file) and is unaffected by this change.

`.github/workflows/soak-digest.yml` and `scripts/render_soak_digest.sh` are
removed in the same change. They posted a weekly digest comment to the
paper-soak tracking issue (#229) for the UPRO regime bot, which
`docs/decisions/2026-07-27-deprecate-upro-regime-bot.md` already retired in
favor of the hourly candlestick bot; the hourly bot reports through the
weekly-review journal instead. The soak-digest side needs no ADR of its own
— it is a straightforward removal of a target that no longer exists, not a
reversal of a standing risk decision the way the backup workflow is.

## Decision

Delete `.github/workflows/backup-db.yml` rather than leave it
merged-but-unconfigured. Accept the risk the 2026-07-07 ADR was written to cover:
Supabase Free/Hobby tier row data (regime_state, trades, audit_log,
bot_config on the dev/paper project) has no off-platform copy going forward.

This supersedes `docs/decisions/2026-07-07-supabase-row-data-backup.md`
outright rather than amending it — the original decision's premise (the
workflow would be enabled and would run weekly) never held in practice, and
the immutability rule for merged ADR entries means the record stays as it
was written, corrected only by this superseding entry and the one-field
`Status:` flip on the original.

## Consequences

### Positive

- Removes dead, unconfigured CI surface and its `contents: write` grant —
  fewer standing permissions in the workflow set, nothing to explain to a
  future reader wondering why an inert workflow exists.
- No behavior change for anyone: the workflow never ran successfully, so
  there is no dump to lose and no schedule to miss.
- Simplifies `docs/runbooks/status-check.md` and
  `docs/runbooks/deadman-watchdog.md`, which had grown comparisons anchored
  on a workflow that was never actually operating.

### Negative

- The diagnostic value the 2026-07-07 ADR identified (row-history evidence
  for a future incident investigation, as happened once with the June-5
  stale kill-switch state) is no longer covered by any backup channel.
  `audit_log` inside Supabase itself remains the only record, and it does
  not survive project deletion or a region-level incident.
- If prod goes live (#230) and this risk calculus needs revisiting, that is
  a fresh decision, not a resurrection of this one — the same scoping caveat
  the original ADR already carried.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep the workflow merged but unconfigured, as a "ready when needed" scaffold | This is exactly the state that persisted for a month with zero dumps landed — an unconfigured workflow does not get configured by existing, it gets forgotten. Removing it is honest about the actual state: no backup exists today. |
| Actually configure the three secrets and start running it | Out of scope for this change — no fresh brainstorm has re-established that the diagnostic value justifies the setup cost and the `contents: write` grant today; a future decision can revisit this if the need resurfaces. |
| Amend the 2026-07-07 entry in place instead of writing a new one | Violates the decision log's immutability rule (`docs/decisions/README.md`) — merged entries only get their `Status:` field edited; the correction and its reasoning belong in a new dated entry. |
