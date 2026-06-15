-- Per-trading-day concurrency guard (#293). Prevents concurrent invocations of
-- daily-check or kill-switch on the same trading date from placing duplicate
-- orders. The primary key (script_name, trade_date) acts as the exclusive
-- claim token: the first INSERT wins; any concurrent INSERT on the same row
-- gets a unique-violation (23505) and backs off.
--
-- Plain RLS deny-all table (no policies, no grant/revoke) — Edge Functions
-- connect with the service-role key which bypasses RLS.

create table if not exists trade_claims (
    script_name text    not null,
    trade_date  date    not null,
    claimed_at  timestamptz not null default now(),
    primary key (script_name, trade_date)
);

alter table trade_claims enable row level security;
