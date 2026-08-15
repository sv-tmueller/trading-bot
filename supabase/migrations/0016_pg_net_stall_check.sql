-- Restore the pg_net stall check via a security-definer RPC (#554).
--
-- The daily verification (#547/#545) substituted a latency check (check 5,
-- scripts/daily_verify.ts) for the original pg_net stall check. The latency
-- check covers the observable half (slow runs that exceed 120s), but cannot
-- detect an invocation whose HTTP response never reached Postgres at all --
-- pg_net recorded a timeout (`timed_out: true`) while the Edge Function still
-- completed and wrote its audit row. That gap is exactly the case the original
-- manual check caught:
--
--   select count(*) from net._http_response
--   where timed_out and extract(minute from created) = 7;
--
-- The `minute = 7` filter is LOAD-BEARING. The hourly-check cron fires at :07
-- past each hour during US market hours (migration 0014/0015: `'7 13-21 * *
-- 1-5'`). Kill-switch rows, by contrast, fire every 5 minutes and run under
-- pg_net's 5s default -- a timed_out row at :10, :15, etc. is a different
-- problem (a kill-switch HTTP timeout), not an hourly-check stall. Filtering
-- to `extract(minute from created) = 7` isolates the hourly-check slots only,
-- excluding benign kill-switch rows that happen to time out under the shorter
-- default budget.
--
-- This migration wraps that query in a SECURITY DEFINER function in the public
-- schema, so anon/authenticated roles can call it without direct access to the
-- net schema (which is extensions-internal and not granted to either role).
-- The function accepts a [start, end) timestamptz range and returns the count
-- of timed_out rows at the :07 slots within that range -- nothing else. No
-- other column from net._http_response is exposed; the function returns a
-- scalar count, not a row set, so it cannot be used to read response bodies,
-- URLs, headers, or any other net-schema data.
--
-- Least privilege: EXECUTE is granted to anon and authenticated only. The
-- function's SEARCH_PATH is locked to public (pg_temp excluded) so a malicious
-- schema search-path cannot shadow the function's internals. The function is
-- declared IMMUTABLE-ish in spirit (it reads a static log table and filters by
-- a fixed predicate) but is marked STRICT (NULL args -> NULL result, no
-- execution) and VOLATILE (the default, since it reads a table that grows over
-- time -- marking it STABLE would be misleading for a query planner).

create or replace function public.pg_net_timeout_count(
  range_start timestamptz,
  range_end timestamptz
) returns bigint
  language sql
  security definer
  set search_path = public
  as $$
    select count(*)
    from net._http_response
    where timed_out
      and extract(minute from created) = 7
      and created >= range_start
      and created < range_end
  $$;

grant execute on function public.pg_net_timeout_count(timestamptz, timestamptz) to anon;
grant execute on function public.pg_net_timeout_count(timestamptz, timestamptz) to authenticated;
