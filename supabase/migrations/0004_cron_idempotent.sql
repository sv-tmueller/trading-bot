-- Make the cron scheduling explicitly idempotent / re-runnable (issue #242).
-- cron.schedule already upserts by job name in modern pg_cron, but this makes
-- re-application unambiguous and self-correcting if a job's command or schedule
-- ever changes: unschedule the existing job (guarded) before (re)scheduling.
-- The job bodies are identical to 0002_schedule.sql and reuse the same Vault
-- helper functions (_functions_base_url / _service_role_key).

do $$
begin
  if exists (select 1 from cron.job where jobname = 'daily-check') then
    perform cron.unschedule('daily-check');
  end if;
  if exists (select 1 from cron.job where jobname = 'kill-switch') then
    perform cron.unschedule('kill-switch');
  end if;
end;
$$;

-- daily-check: 22:30 UTC, Mon-Fri (post-US-close).
select cron.schedule(
  'daily-check',
  '30 22 * * 1-5',
  $$
  select net.http_post(
    url := _functions_base_url() || '/daily-check',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || _service_role_key(),
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb
  );
  $$
);

-- kill-switch: every 5 min within a wide US-market-hours window, Mon-Fri.
select cron.schedule(
  'kill-switch',
  '*/5 13-21 * * 1-5',
  $$
  select net.http_post(
    url := _functions_base_url() || '/kill-switch',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || _service_role_key(),
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb
  );
  $$
);
