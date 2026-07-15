-- #383: one row per trading day of account equity, sourced from
-- alpaca.getAccountValue() (read-only, unguarded helper) via daily-check.
-- Powers the status digest's trailing-return windows (7d/30d/since-inception).
create table if not exists equity_snapshots (
    date       date primary key,
    equity_usd numeric(14,4) not null,
    created_at timestamptz not null default now()
);

-- Edge Functions connect with the service-role key (bypasses RLS). Enable RLS
-- and add no policies so anon/public access is denied by default (same
-- deny-all pattern as 0001_init.sql).
alter table equity_snapshots enable row level security;
