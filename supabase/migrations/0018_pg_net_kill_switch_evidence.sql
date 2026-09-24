-- Kill-switch slot pg_net evidence RPC (#660).
--
-- #562 named the kill-switch grid's missing 5-minute slots (a gap between
-- the expected 108 audit_log rows and the ones actually written), but named
-- them blind -- it has no way to say WHY a slot is missing. This migration
-- adds a second security-definer RPC (alongside migration 0016's
-- pg_net_timeout_count) that hands the evaluator (scripts/daily_verify.ts)
-- the raw pg_net evidence for the day's kill-switch cron window, so a missing
-- slot can be tagged with what pg_net actually saw (a timeout, a non-2xx
-- response, a null-status error, a 2xx with no audit row) or explained by
-- retention (no request recorded within the retained window, or the window
-- has already expired).
--
-- Retention findings (recorded here per the #660 sub-plan's acceptance
-- criterion -- these numbers drove ND2's "ship the evidence-expired path,
-- defer the pg_net.ttl bump" call):
--   * The kill-switch cron is `*/5 13-21 * * 1-5` UTC -- 108 slots per
--     weekday, 13:00-21:55Z. `net.http_post` is called with no explicit
--     timeout, so pg_net's own 5000ms default applies to every request.
--   * `net._http_response` rows are deleted once older than `pg_net.ttl`.
--     The upstream default is 6 hours and this repo has never overridden
--     it -- the live value on dev/prod is unverified; an operator should run
--     `show pg_net.ttl;` after this migration lands (see the runbook
--     subsection this PR adds).
--   * `daily-verification.yml` is scheduled for 22:15Z, but its last 12
--     scheduled runs actually started 00:06-00:47Z the next day -- a
--     window that only reliably covers kill-switch slots from ~18:xx
--     onward (roughly slots 38-46 of 108) at a 6-hour retention. That
--     window (8h55m) is longer than any 6-hour retention can cover, so
--     **`evidence expired` is the expected, normal case for early-day
--     slots**, not a bug in this RPC.
--   * Against known history, 7 of the 8 past missing slots would have been
--     covered by a 6-hour retention; the 8th (2026-09-21 17:10Z) would show
--     expired.
--   * Backfills are always expired (they run long after the fact); a re-run
--     overwrites the date's ledger row and digest, so the FIRST scheduled
--     run's artifact is the evidence of record, not a later backfill's.
--
-- Matching a row to a slot: `net._http_response` has no URL column (the
-- pg_net request queue row is deleted once dequeued, and pg_cron never
-- records the request id), so this RPC can't join back to "which cron job
-- fired this". Instead it filters on `created`'s UTC hour/minute: the
-- kill-switch grid's slots are exactly the minutes that are multiples of 5
-- within hours 13-21 UTC, and hourly-check's own `:07` cron slot never lands
-- on a multiple of 5 -- so filtering `extract(minute from created) % 5 = 0`
-- already excludes every hourly-check row, symmetric to migration 0016's own
-- `extract(minute from created) = 7` filter picking out hourly-check rows
-- only. Disclosed gap: a kill-switch request that pg_net doesn't process
-- until 60+ seconds after its slot boundary lands in the NEXT non-multiple-
-- of-5 minute and is silently excluded by this filter -- the caller
-- (scripts/daily_verify.ts's tagMissingKillSwitchSlots) then reads that slot
-- as "no request recorded" (or "evidence expired") instead of matching its
-- true, late response. This is a known, accepted blind spot, not a bug.
--
-- Security posture (deliberately tighter than migration 0016's own
-- pg_net_timeout_count, which grants anon/authenticated -- this function is
-- called only from the status Edge Function's service-role client):
--   * `security definer`, `strict` (a null range_start/range_end returns
--     null immediately, no query executed), a single SELECT.
--   * `set search_path = ''` -- every schema-resolvable function call below
--     is qualified `pg_catalog.<fn>` (mirrors migration 0003_hygiene.sql's
--     own set_updated_at() precedent). COALESCE/NULLIF/GREATEST/EXTRACT and
--     the `interval '...'` literal are SQL-grammar special forms, not
--     schema-resolvable function calls, so they are intentionally left
--     unqualified (schema-qualifying them is a syntax error).
--   * `set timezone = 'UTC'` -- EXTRACT(hour/minute FROM ...) on a
--     timestamptz is timezone-dependent; this pins it regardless of the
--     calling session's own setting.
--   * Returns ONLY `created`, `status_code`, `timed_out` per response row,
--     plus the computed `evidence_from` cutoff -- never `content`,
--     `headers`, or `error_msg` (migration 0016's own documented invariant,
--     carried over verbatim: this function cannot be used to read response
--     bodies or request headers).
--   * EXECUTE is revoked from public/anon/authenticated and granted to
--     service_role only -- the `status` Edge Function is the only caller,
--     and it always connects with the service-role key.

create or replace function public.pg_net_kill_switch_evidence(
  range_start timestamptz,
  range_end timestamptz
) returns jsonb
  language sql
  security definer
  strict
  set search_path = ''
  set timezone = 'UTC'
  as $$
    select jsonb_build_object(
      'evidence_from', greatest(
        pg_catalog.now() - coalesce(
          nullif(pg_catalog.current_setting('pg_net.ttl', true), '')::interval,
          interval '6 hours'
        ),
        (select min(r.created) from net._http_response r)
      ),
      'responses', coalesce(
        (
          select jsonb_agg(
            jsonb_build_object(
              'created', r.created,
              'status_code', r.status_code,
              'timed_out', r.timed_out
            )
            order by r.created
          )
          from net._http_response r
          where r.created >= range_start
            and r.created < range_end
            and extract(hour from r.created) between 13 and 21
            and extract(minute from r.created)::int % 5 = 0
        ),
        '[]'::jsonb
      )
    )
  $$;

revoke all on function public.pg_net_kill_switch_evidence(timestamptz, timestamptz) from public;
revoke all on function public.pg_net_kill_switch_evidence(timestamptz, timestamptz) from anon;
revoke all on function public.pg_net_kill_switch_evidence(timestamptz, timestamptz) from authenticated;
grant execute on function public.pg_net_kill_switch_evidence(timestamptz, timestamptz) to service_role;
