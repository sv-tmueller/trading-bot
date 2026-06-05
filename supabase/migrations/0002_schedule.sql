-- Requires extensions pg_cron + pg_net (Supabase: enable in Dashboard or here).
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Store the service-role key in Vault once (run manually in the SQL editor, not
-- committed): select vault.create_secret('<SERVICE_ROLE_KEY>', 'service_role_key');

-- Helper: read the key from Vault at call time.
create or replace function _service_role_key() returns text language sql stable as $$
  select decrypted_secret from vault.decrypted_secrets where name = 'service_role_key' limit 1;
$$;

-- daily-check: 22:30 UTC, Mon-Fri (post-US-close).
select cron.schedule(
  'daily-check',
  '30 22 * * 1-5',
  $$
  select net.http_post(
    url := 'https://PROJECT_REF.supabase.co/functions/v1/daily-check',
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
    url := 'https://PROJECT_REF.supabase.co/functions/v1/kill-switch',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || _service_role_key(),
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb
  );
  $$
);
