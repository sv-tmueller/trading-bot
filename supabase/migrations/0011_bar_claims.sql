-- Bar-level concurrency guard for the hourly bot's kill-switch/panic safety
-- stack (spec docs/superpowers/specs/2026-07-27-hourly-bot-design.md §8.4,
-- §9). trade_claims (0008) is keyed on a `date` column and cannot express
-- multiple claims on the same trading day, which an hourly bot needs
-- (multiple entries + session-close flattens per day). This table is keyed
-- on the completed bar's timestamp instead. Same first-INSERT-wins /
-- 23505-conflict-backs-off pattern: the first INSERT wins; any concurrent
-- INSERT on the same row gets a unique-violation (23505) and backs off.
--
-- Ownership (spec §14): this migration belongs to the short-side
-- safety-stack retrofit package. The feature package (`hourly-check`) is a
-- consumer only -- it inserts a claim row per bar and reads back
-- skipped:duplicate_run on conflict -- and does not own this schema.
--
-- trade_claims itself is untouched: the incumbent bot (while its cron
-- remains active) keeps using the existing date-keyed claim unchanged.
--
-- Plain RLS deny-all table (no policies, no grant/revoke) -- Edge Functions
-- connect with the service-role key which bypasses RLS.

create table if not exists bar_claims (
    script_name text        not null,
    bar_ts      timestamptz not null,
    claimed_at  timestamptz not null default now(),
    primary key (script_name, bar_ts)
);

alter table bar_claims enable row level security;
