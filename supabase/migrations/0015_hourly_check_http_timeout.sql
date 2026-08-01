-- Give the hourly-check cron an explicit net.http_post timeout (#498).
--
-- 0014 scheduled the job without a `timeout_milliseconds` argument, so pg_net's
-- 5000 ms default applied. Observed live on 2026-07-31: the session-close
-- flatten that closed the bot's first real position ran 19:07:00.708 ->
-- 19:07:05.840 = 5.132s in `audit_log`, so its `net._http_response` row records
-- `timed_out: true` with null content while the function completed normally and
-- closed a 137-share position. pg_net timing out does not abort the Edge
-- Function and pg_net does not retry `http_post`, so this is an observability
-- defect, not a trading risk -- but it inverts on exactly the runs that matter:
-- skip-only scans (0.74-2.6s) stay clean and the scans that place or close
-- orders are the ones that breach 5s.
--
-- The job name, schedule, URL expression, headers and body are reproduced
-- verbatim from 0014 -- the added `timeout_milliseconds` argument is the only
-- change. In particular the `:07` minute is unchanged: 0014's comment proves it
-- against spec §4's staleness inequality, and re-picking it here is out of
-- scope. The guarded do-block is 0014's, itself matching
-- 0004_cron_idempotent.sql's unschedule-then-schedule pattern, so re-running
-- this migration is a no-op rather than an error on an existing job name.
--
-- 60000 ms -- why that number, and why not "5.132s plus a bit":
--
-- The requirement is
--   timeout_milliseconds > worst legitimate http_post elapsed
-- and 5.132s is a lower bound on that worst case, not the ceiling. It is one
-- sample of one flatten, measured from `started_at` (written after cold start
-- and after `insertAuditLog`) to `finished_at`, so it undercounts the elapsed
-- time pg_net sees at both ends. Sizing off it would rebuild the same false
-- alarm at a higher threshold.
--
-- The function's own poll budgets bound the worst case structurally instead.
-- On the flatten path (`hourly-check/logic.ts`, "3. Flatten scan") each resting
-- leg gets a verified `cancelOrder`, capped at 3s each by `alpaca.ts`'s
-- `timeoutMs = 3_000` default, and a bracket leaves an OCO pair, so ~6s; the
-- market close that follows is capped at 30s by `pollOrderUntilFilled`'s
-- `timeoutMs = 30_000` default, plus a post-timeout DELETE and one status
-- re-read. Add the scan's fixed overhead -- the 0.74-2.6s measured on
-- skip-only scans covers the clock call, bar fetch and the
-- `hourly_scans`/`trades`/`audit_log` writes -- and the cold start ahead of
-- `started_at`. A slow but entirely legitimate trading scan therefore lands
-- near 41s, roughly eight times the one flatten observed so far. The entry
-- path is strictly cheaper (one 30s-capped bracket entry poll).
--
-- 60000 clears that ~41s ceiling with ~19s of margin, so a timeout row now
-- means the function exceeded budgets it enforces on itself -- a real anomaly
-- worth investigating rather than a healthy trading session. It stays 1/60th of
-- the job's own 3600s period, so a slow scan can never overlap the next firing,
-- and it fires well before the Edge Function runtime's own wall-clock ceiling,
-- so a genuinely wedged invocation is still detected. It also does not weaken
-- what §10's `net._http_response` query was originally there to catch: a wrong
-- project ref or a bad bearer fails fast on DNS or an HTTP status, never by
-- timeout.
--
-- If this ever needs revisiting, the remedy is to tighten the function's poll
-- budgets or raise this number in a follow-up migration -- never to loosen the
-- runbook's health check so the false alarm stops being reported, and never to
-- touch HOURLY_STALENESS_TOLERANCE_MIN, which is a different problem entirely.

do $$
begin
  if exists (select 1 from cron.job where jobname = 'hourly-check') then
    perform cron.unschedule('hourly-check');
  end if;
end;
$$;

select cron.schedule(
  'hourly-check',
  '7 13-21 * * 1-5',
  $$
  select net.http_post(
    url := _functions_base_url() || '/hourly-check',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || _service_role_key(),
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 60000
  );
  $$
);
