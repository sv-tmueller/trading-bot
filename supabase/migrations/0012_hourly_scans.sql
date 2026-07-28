-- #475 (hourly-check feature package): hourly_scans table, the trades.reason
-- check extension, and the hourly-check cron job -- shipped OFF (see the
-- commented-out block at the end of this file; C3/finding below).
--
-- Ownership boundary (spec §8.4, §14): this migration does NOT create
-- bar_claims -- that table is 0011_bar_claims.sql, owned by the sibling #474
-- package (short-side safety-stack retrofit). Merge order: #474 first.

-- ---------------------------------------------------------------------------
-- hourly_scans -- one row per scan, including skips (spec §9). Money columns
-- are numeric(14,4) per 0005_numeric_money.sql's decimal-fidelity precedent;
-- qty stays integer (whole shares, same comment as 0001_init.sql's trades
-- table). PK (symbol, bar_ts): a re-run on the same bar upserts idempotently,
-- same pattern as regime_state's date PK.
-- ---------------------------------------------------------------------------

create table if not exists hourly_scans (
    symbol           text        not null,
    bar_ts           timestamptz not null,
    decision         text        not null check (decision in ('LONG','SHORT','SKIP')),
    skip_reason      text,
    detectors_fired  jsonb       not null default '[]'::jsonb,
    context_mode     text        not null,
    entry_ref_price  numeric(14,4),
    stop_price       numeric(14,4),
    target_price     numeric(14,4),
    risk_per_share   numeric(14,4),
    equity_usd       numeric(14,4) not null,
    qty              integer     not null default 0,
    entry_order_id   text,
    created_at       timestamptz not null default now(),
    primary key (symbol, bar_ts)
);

-- Edge Functions connect with the service-role key (bypasses RLS). Enable RLS
-- and add no policies so anon/public access is denied by default (same
-- deny-all pattern as 0001_init.sql / 0009_equity_snapshots.sql / 0010).
alter table hourly_scans enable row level security;

-- ---------------------------------------------------------------------------
-- trades.reason check extension (spec §9). The 0001_init.sql constraint is
-- inline and Postgres-auto-named -- looked up at apply time (not assumed)
-- via pg_catalog rather than hardcoding "trades_reason_check", per the
-- spec's own "confirm, don't assume" instruction made mechanical. Re-added
-- with the full superset: the four existing values plus the five hourly_*
-- values this package's trades rows use.
--
-- Coordination note for review time: if the sibling #474 package's 0011
-- migration also touches this constraint, this migration (0012) applies
-- second and must re-add the full superset covering both packages' values --
-- check the retrofit branch before merge.
-- ---------------------------------------------------------------------------

do $$
declare
  cname text;
begin
  select con.conname into cname
  from pg_constraint con
  join pg_class rel on rel.oid = con.conrelid
  where rel.relname = 'trades'
    and con.contype = 'c'
    and pg_get_constraintdef(con.oid) ilike '%reason%';

  if cname is not null then
    execute format('alter table trades drop constraint %I', cname);
  end if;
end;
$$;

alter table trades add constraint trades_reason_check check (reason in (
    'regime_flip_long',
    'regime_flip_cash',
    'kill_switch',
    'panic_cli',
    'hourly_long_entry',
    'hourly_short_entry',
    'hourly_bracket_exit',
    'hourly_session_close_exit',
    'hourly_kill_switch'
));

-- ---------------------------------------------------------------------------
-- hourly-check cron job -- SHIPPED OFF, not merely inactive (derived decision
-- C3, disclosed in the PR).
--
-- The sub-plan's preferred mechanism was: schedule the job at '7 13-21 * * 1-5'
-- (minute :07 satisfies spec §4's hard inequality --
-- cronMinuteOffset + expectedFeedLatencyMin < HOURLY_STALENESS_TOLERANCE_MIN
-- (default 10) -- and stays off the kill-switch's */5 grid), then immediately
-- `update cron.job set active = false where jobname = 'hourly-check'`, so the
-- job row exists (shipped) but pg_cron skips it (not activated) until Batch 3
-- flips it on with a one-line migration.
--
-- That mechanism requires verifying, against a real local Supabase Postgres,
-- that the active=false update actually sticks and is honored by pg_cron --
-- this agent session had no local Postgres available (no `supabase`/`psql`
-- CLI, no running instance) to perform that verification. Per the spec's own
-- documented fallback for an unverifiable mechanism: the cron.schedule block
-- ships FULLY COMMENTED OUT below, so nothing can execute it (not even an
-- inactive cron.job row is created). Activation ships as its own migration
-- once the mechanism has been verified (or once Batch 3 deploys this pattern
-- against a live project and confirms it there first).
--
-- select cron.schedule(
--   'hourly-check',
--   '7 13-21 * * 1-5',
--   $cron$
--   select net.http_post(
--     url := _functions_base_url() || '/hourly-check',
--     headers := jsonb_build_object(
--       'Authorization', 'Bearer ' || _service_role_key(),
--       'Content-Type', 'application/json'
--     ),
--     body := '{}'::jsonb
--   );
--   $cron$
-- );
-- update cron.job set active = false where jobname = 'hourly-check';
