-- Hygiene follow-ups (issue #242). Additive and idempotent.

-- 1. Index the kill-switch / forensics hot path on trades. The rolling-high and
--    recent-trade lookups filter by symbol and order by fill_time; without this
--    they degrade to a sequential scan as the table grows.
create index if not exists trades_symbol_fill_time_idx
    on trades (symbol, fill_time desc);

-- 2. Pin set_updated_at()'s search_path (Supabase linter hardening). With an
--    empty search_path, now() must be schema-qualified as pg_catalog.now().
create or replace function set_updated_at() returns trigger
    language plpgsql
    set search_path = ''
as $$
begin
    new.updated_at = pg_catalog.now();
    return new;
end;
$$;
