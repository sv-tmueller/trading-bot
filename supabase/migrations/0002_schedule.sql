-- Requires extensions pg_cron + pg_net (Supabase: enable in Dashboard or here).
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Two secrets are read from Vault at call time (set once per project in the SQL
-- editor, NOT committed — same migration works for dev and prod, only the
-- secrets differ):
--   select vault.create_secret('<SERVICE_ROLE_KEY>', 'service_role_key');
--   select vault.create_secret('https://<ref>.supabase.co/functions/v1', 'functions_base_url');

create or replace function _service_role_key() returns text language sql stable as $$
  select decrypted_secret from vault.decrypted_secrets where name = 'service_role_key' limit 1;
$$;

create or replace function _functions_base_url() returns text language sql stable as $$
  select decrypted_secret from vault.decrypted_secrets where name = 'functions_base_url' limit 1;
$$;

-- Defence in depth: pg_cron runs as superuser (unaffected), but no anon/
-- authenticated caller should be able to invoke these Vault-read helpers.
revoke execute on function _service_role_key() from public;
revoke execute on function _functions_base_url() from public;

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
