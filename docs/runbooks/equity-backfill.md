# Equity Snapshots Backfill Runbook

One-time setup and execution for `scripts/backfill_equity_snapshots.ts` (#389,
batch #388 Package A) — an operator-run script that fetches the paper
account's daily equity from Alpaca's `/v2/account/portfolio/history` (GET,
read-only) and fills the gaps in `equity_snapshots`, so `since_inception_pct`
and the trailing-return windows in the status digest (see
`docs/runbooks/status-check.md`) are meaningful from day one instead of
accruing forward from whenever `daily-check` started writing snapshots
(#386/#387).

It inserts **only** dates missing from `equity_snapshots` — rows already
written by `daily-check` are canonical and are never overwritten (the two
sources measure equity at different times of day; the forward-written row
always wins). This is a one-time operator action, not a recurring job — there
is no cron for it.

## Prerequisites

- Migration `0009_equity_snapshots.sql` applied (`supabase db push`). If it
  isn't, the script fails with a clear message instead of a raw PostgREST
  error — see Troubleshooting below.
- [Deno](https://deno.com/) installed (same runtime the Edge Functions use).
- Alpaca **paper** API key/secret with portfolio-history read access (the
  script defaults to `ALPACA_PAPER=true`; this batch's scope is the paper
  account only — see #388's non-goals for live/#230).
- The Supabase project's `SUPABASE_URL` and **service-role** key (bypasses
  RLS — same as the Edge Functions; treat it like a production secret,
  never commit it).

## One-time setup

1. Copy the example env file and fill in the values:
   ```bash
   cp .env.backfill.example .env.backfill
   ```
   Edit `.env.backfill`:
   ```
   ALPACA_API_KEY=<paper key id>
   ALPACA_SECRET_KEY=<paper secret>
   ALPACA_PAPER=true
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<service-role key>
   ```
   `.env.backfill` is gitignored — never commit it.

## Running the backfill

Always dry-run first — the script never writes without `--execute`:

```bash
deno run --allow-env --allow-net --env-file=.env.backfill \
  scripts/backfill_equity_snapshots.ts
```

This prints a summary: the mode (`dry-run`), the backfill window (default:
from the bot's go-live — the earliest `audit_log.started_at` row — through
yesterday in America/New_York; `daily-check` owns today's row), the number of
days Alpaca returned, how many were dropped for zero/invalid equity, how many
dates were already present, and the dates it *would* insert (elided beyond 20
rows). It ends with `re-run with --execute to write` when there's anything to
insert.

Once the plan looks right, write it:

```bash
deno run --allow-env --allow-net --env-file=.env.backfill \
  scripts/backfill_equity_snapshots.ts --execute
```

The summary now reports `inserted` instead of `to insert`. Re-running the
script (dry-run or `--execute`) afterward is safe and idempotent — every date
already in `equity_snapshots` is skipped, never re-sent, even if Alpaca's
value for that date has since changed.

### `--since YYYY-MM-DD`: override the window start

```bash
deno run --allow-env --allow-net --env-file=.env.backfill \
  scripts/backfill_equity_snapshots.ts --since 2026-01-01 --execute
```

Overrides the default (earliest `audit_log` row). Useful to narrow the
window, or to supply an explicit start if `audit_log` is empty (the script
otherwise fails cleanly in that case — see Troubleshooting).

### `-h` / `--help`

Prints usage and exits.

## Verify

After a successful `--execute` run, confirm the digest picked it up:

```bash
bash scripts/status.sh
```

The `returns` block's `since_inception_pct` (and `trailing_7d_pct`/
`trailing_30d_pct`, once enough history exists) should now be populated
instead of showing `null` or a near-zero value computed from only a few
forward-accrued days.

## Troubleshooting

- **`equity_snapshots table not found — apply migration 0009 (supabase db
  push) first.`** — migration `0009_equity_snapshots.sql` hasn't been applied
  to this Supabase project yet. Run `supabase db push`, then re-run the
  script.
- **`audit_log is empty, so the bot's go-live date can't be inferred — pass
  --since YYYY-MM-DD explicitly.`** — no `--since` was given and `audit_log`
  has no rows (a fresh, never-run bot). Pass `--since` explicitly with the
  date you want the backfill to start from.
- **`--since must be a valid YYYY-MM-DD date, got ...`** — the value wasn't
  `YYYY-MM-DD`, or wasn't a real calendar date (e.g. `2026-02-30`).
- **`GET /v2/account/portfolio/history -> 401: ...`** — check
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` in `.env.backfill` and that
  `ALPACA_PAPER` matches the account the keys belong to.
- **`SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set`** — one or both
  are missing/blank in `.env.backfill`.
- Nothing to insert (`to insert: 0` / `inserted: 0`) is a normal, successful
  outcome — it means every date in the window is already covered by
  `daily-check`'s forward-written rows.

## What the script does not do

- No recurring cron — this is a one-time operator action per batch #388's
  non-goals.
- No TWR or SPY-benchmark math — still deferred (also a #388 non-goal).
- No changes to `daily-check`/`status` logic or the digest shape — `status`
  already renders whatever `equity_snapshots` data exists.
- No mutating Alpaca calls — the portfolio-history fetch is a plain GET, and
  the script adds no helper to `supabase/functions/_shared/alpaca.ts`.
