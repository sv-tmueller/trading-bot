-- #256: daily-check moves from post-close (22:30 UTC, where market/day orders
-- can never fill) to post-open. Two slots cover US DST without code changes:
-- during EDT (open 13:30 UTC) the 13:37 run executes and the 14:37 run is an
-- idempotent no-op; during EST (open 14:30 UTC) the 13:37 run exits at the
-- function's clock gate and the 14:37 run executes. Market holidays: both exit
-- at the gate. :37 keeps daily-check off the kill-switch's */5 grid so the
-- fill + regime_state write land between kill-switch ticks. The job bodies
-- reuse the Vault helpers from 0002 (_functions_base_url / _service_role_key).

-- Re-runnable (same idempotency bar as 0004 / #248): drop whichever of the
-- old and new jobs exist before (re)scheduling.
do $$
begin
  if exists (select 1 from cron.job where jobname = 'daily-check') then
    perform cron.unschedule('daily-check');
  end if;
  if exists (select 1 from cron.job where jobname = 'daily-check-1337') then
    perform cron.unschedule('daily-check-1337');
  end if;
  if exists (select 1 from cron.job where jobname = 'daily-check-1437') then
    perform cron.unschedule('daily-check-1437');
  end if;
end;
$$;

select cron.schedule(
  'daily-check-1337',
  '37 13 * * 1-5',
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

select cron.schedule(
  'daily-check-1437',
  '37 14 * * 1-5',
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
