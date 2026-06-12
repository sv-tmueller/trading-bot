-- Finding 9 (2026-06-11 review): 0002 revoked EXECUTE on the Vault-read
-- helpers from PUBLIC, but Supabase's default privileges also grant EXECUTE
-- directly to the `anon` and `authenticated` roles — and a PUBLIC revoke does
-- not remove direct grants. That left both functions callable via PostgREST
-- RPC (no secret leaks today because they are SECURITY INVOKER and those roles
-- cannot read vault, but one `security definer` refactor away from exposing
-- the service-role key). Revoke the direct grants explicitly; pg_cron runs as
-- superuser and is unaffected.
revoke execute on function public._service_role_key() from anon, authenticated;
revoke execute on function public._functions_base_url() from anon, authenticated;
