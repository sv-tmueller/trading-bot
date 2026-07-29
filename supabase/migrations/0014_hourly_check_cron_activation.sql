-- Activate the hourly-check cron (#479 T11, PR-B). This is the one migration
-- that turns the hourly bot on: from the next :07 of any hour in the 13-21
-- UTC window, Mon-Fri (within the hour if this migration applies during that
-- window, not specifically the next day's 13:07 -- see the runbook's §9/§10
-- correction), this job posts to hourly-check every hour, and the function
-- can place a real (paper) bracket order once its own gates pass.
--
-- Uncomments the block 0012_hourly_scans.sql shipped fully commented out
-- (decision C3's fallback -- no cron.job row of any kind existed until this
-- migration). The job name, schedule, URL expression, headers and body are
-- reproduced verbatim from that commented block. Two things differ, both
-- deliberately, so an auditor diffing the two blocks does not mistake either
-- for a discrepancy: the dollar-quote delimiter is `$$` here instead of the
-- source block's `$cron$` (cosmetic, no nested `$$` in the body to collide
-- with); and 0012's trailing `update cron.job set active = false ...` line is
-- not reproduced -- this migration activates the job, so shipping it
-- pre-disabled would defeat the point. The surrounding do-block guard is new,
-- added to match 0004_cron_idempotent.sql's guarded unschedule-then-schedule
-- pattern, so re-running this migration (e.g. a second `supabase db push`
-- with no changes) is a no-op rather than an error on a job name that
-- already exists.
--
-- Minute :07 -- why it is correct, not merely "not on the kill-switch's */5
-- grid":
--
-- Spec §4's hard inequality is
--   cronMinuteOffset + observedFeedLatencyMin < HOURLY_STALENESS_TOLERANCE_MIN (10)
-- T10's live RTH measurement (evidence comment on #479, "T10 evidence: bar
-- alignment") sampled the same completed bar repeatedly across the cron's
-- firing offset and found it byte-identical (OHLC, volume, trade count) from
-- 61 seconds after its close onward -- observed feed latency <= 1 minute.
-- That gives 7 + 1 = 8 < 10, two minutes of headroom.
--
-- Per spec §4 and T10's own instruction: if a future run of this inequality
-- ever fails (feed latency regresses, tolerance changes, etc.), the fix is a
-- later cron minute in a follow-up migration -- never raising
-- HOURLY_STALENESS_TOLERANCE_MIN to paper over a bad minute pick. That
-- remedy was not needed here; T10 measured comfortable headroom at :07.

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
    body := '{}'::jsonb
  );
  $$
);
