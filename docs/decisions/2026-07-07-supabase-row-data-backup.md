# Supabase row-data backup

Weekly encrypted `db dump --data-only` committed to the repo via a GitHub Action, in preference to Supabase Pro or accepting the risk.

**Date:** 2026-07-07
**Status:** accepted

---

## Context

The bot's Postgres data lives in Supabase Free/Hobby tier, which provides no
automated backups. Schema (DDL) is tracked in git (`supabase/migrations/`),
but table rows have no off-platform copy — if the project is lost or deleted,
the row data is unrecoverable.

Only one Supabase project is deployed today: `trading-bot-dev`
(`qdaxxsuicyiscdvsdowc`), running the Alpaca **paper** account
(`docs/CURRENT_CONFIG.md`). Prod (`trading-bot`, live keys) is not yet
deployed — go-live is a separate, manual runbook step (#230). So every row
currently at risk is paper-account data:

- `audit_log` — one row per function invocation; ~80 rows/trading day from
  the 5-minute kill-switch plus daily-check.
- `regime_state` — one row per trading day.
- `trades` — one row per broker fill (regime flips only — infrequent).
- `bot_config` — a handful of key/value flag rows.

Total volume is well under 1 MB/year of dumps. Supabase's free-tier pause
applies to *inactive* projects; this project is invoked continuously by
`pg_cron` (5-minute kill-switch during market hours, twice-daily
daily-check), so involuntary pause from inactivity is not the live risk here.
The realistic loss scenarios are accidental deletion, an account-level
Supabase incident, or a region-level outage — all low-probability but
non-zero, and all currently unrecoverable for row data.

**Irreplaceability, honestly assessed:** the data has no monetary
irreplaceability — it is paper-account forensics, not real trades or real
money. Its value is diagnostic: the soak has already relied on this exact
data once, to root-cause a stale June-5 kill-switch state that had protected
a phantom position for three sessions (soak post-mortem referenced from
`supabase/migrations/`-era commits, pre-#237). Losing the row history would
not cost money, but it would erase the ability to reconstruct *why* the bot
did what it did on any past day — which is the same evidence a future
incident investigation would need. That is a real but modest cost, not an
existential one.

## Decision

Implement the zero-new-cost option: a weekly GitHub Actions workflow
(`.github/workflows/backup-db.yml`) that runs `supabase db dump --data-only`
against the dev/paper project, encrypts the dump with a symmetric key
(`openssl enc -aes-256-cbc -pbkdf2`), and commits the encrypted file to the
repo at `backups/db-dump-latest.sql.enc`. The workflow is inert until three
repo secrets are set (two of which — `SUPABASE_ACCESS_TOKEN`,
`SUPABASE_DB_PASSWORD` — already exist for `deploy-dev.yml`; only
`BACKUP_ENCRYPTION_KEY` is new).

This wins on the evidence: the diagnostic value is real and already proven
(the June-5 post-mortem), the data volume is trivial, and the marginal cost
of the workflow is a few CI-minutes a week plus one new secret — no new
recurring spend, no new vendor. Supabase Pro's $25/mo daily-backup service is
disproportionate to what is, today, dev/paper forensics data; accepting the
risk outright would mean giving up the one channel that has already paid for
itself once, for a backup that costs nothing.

Storing the dump as a **committed repo file** rather than a GitHub Actions
artifact is deliberate: artifacts expire after 90 days and are still hosted
by GitHub-Supabase-adjacent infrastructure choices, not a true
survives-project-deletion copy in the sense this ADR cares about, whereas a
committed file is versioned, sits alongside the schema it belongs with, and
survives independently of Supabase entirely.

Keeping a single rolling `db-dump-latest.sql.enc` (not one file per run) was
chosen over dated snapshots to avoid unbounded repo growth for a "backup" use
case that only needs *the current* copy of the data at time of loss — the
existing `audit_log` history itself already reconstructs the timeline;
weekly snapshots do not add point-in-time recovery this project has asked
for.

This decision is scoped to today's reality (dev/paper is the only deployed
project). It should be revisited once prod goes live (#230) — a live-money
project changes the irreplaceability calculus and may justify Supabase Pro
or a per-environment backup, but that is a future decision, not this one.

## Consequences

### Positive

- Off-platform, encrypted, versioned copy of all row data, refreshed weekly, at zero new recurring cost.
- Reuses existing CI secrets (`SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD`) from `deploy-dev.yml` — only one new secret to manage.
- Inert by default (default-OFF pattern): merging the workflow does nothing until the operator opts in by setting `BACKUP_ENCRYPTION_KEY` (and confirming the other two secrets are present).
- No trading-path code touched; no LLM; nothing that can place, cancel, or affect an order.

### Negative

- Weekly cadence means up to a week of data loss in the worst case (acceptable given the data is diagnostic, not transactional).
- The encrypted dump's confidentiality now depends on `BACKUP_ENCRYPTION_KEY` being kept safe and never rotated without also re-encrypting (or discarding) the last committed dump.
- A bot commits directly to `main` weekly; this is a small, mechanical, additive commit (one file, always the same path) but is a new category of automated write to the default branch that did not exist before.
- Scope is dev/paper only; this ADR does not cover prod once it goes live, and will need revisiting at that point.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Supabase Pro ($25/mo, daily backups, 7-day retention, optional PITR) | New recurring spend for what is currently dev/paper forensics data with modest, non-monetary irreplaceability. Cost is disproportionate to the risk being covered today; revisit once prod is live and real trades are at stake. |
| Accept the risk, no backup | Legitimate in principle for low-value paper data, but rejected on the evidence: this exact data already resolved one real incident (the June-5 stale kill-switch post-mortem), and a weekly zero-cost workflow removes the risk for near-zero marginal effort — there's no honest case for paying zero cost to leave value on the table. |
| GitHub Actions artifact storage (instead of a committed repo file) | 90-day retention does not survive Supabase-project-deletion in the way a backup is meant to; a committed file is simpler and permanent for negligible size. |
