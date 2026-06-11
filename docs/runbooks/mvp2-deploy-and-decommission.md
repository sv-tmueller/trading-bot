# MVP 2.0 Deploy & Decommission Runbook

Migrates the deterministic 200-DMA equity bot from Python/IBKR/SQLite/host-cron to
TypeScript on **Supabase (pg_cron + Edge Functions + Postgres) + Alpaca**. See the
spec (`docs/superpowers/specs/2026-06-05-mvp2-infra-migration-design.md`) and the
three plans (`docs/plans/2026-06-05-mvp2-infra-migration-plan-{1,2,3}-*.md`).

## Prerequisites (hard gates)
- [ ] Confirm **UPRO is buyable** on the Alpaca account (place a 1-share manual test buy on paper). If it isn't tradeable, revisit the vehicle decision (spec §2) before proceeding.
- [ ] **Rotate** the Alpaca paper keys that were exposed in plaintext in a prior session; generate fresh paper keys.
- [ ] Generate a strong `PANIC_TOKEN` (e.g. `openssl rand -hex 32`).

## Deploy (paper)
1. `supabase link --project-ref <ref>`
2. Set secrets:
   `supabase secrets set ALPACA_API_KEY=... ALPACA_SECRET_KEY=... ALPACA_PAPER=true N8N_WEBHOOK_URL=... PANIC_TOKEN=... BOT_TICKER=UPRO BOT_BENCHMARK=SPY`
   (Strategy params `REGIME_SMA_DAYS`/`KILL_SWITCH_DRAWDOWN_PCT`/`KILL_SWITCH_LOOKBACK_DAYS` default to 200/0.25/30 — set only to override.)
3. `supabase db push` (applies `0001_init.sql` + `0002_schedule.sql` + `0003_vault_fn_grants.sql`).
4. In the SQL editor, store **two** secrets in Vault (one-time per project, not committed — the same migration works for dev and prod, only these differ):
   ```sql
   select vault.create_secret('<service_role_key>', 'service_role_key');
   select vault.create_secret('https://<ref>.supabase.co/functions/v1', 'functions_base_url');
   ```
   (`0002`'s `_service_role_key()` / `_functions_base_url()` read these at cron-call time; `revoke execute ... from public` is already applied. The service-role key is in Dashboard → Settings → API.)
5. Verify the cron jobs registered: `select jobname, schedule from cron.job;` → `daily-check | 30 22 * * 1-5` and `kill-switch | */5 13-21 * * 1-5`. (No `PROJECT_REF` edit needed — the URL comes from the `functions_base_url` Vault secret.)
6. Deploy functions:
   - `supabase functions deploy daily-check kill-switch` (default JWT-verified; cron sends the service-role bearer)
   - `supabase functions deploy panic --no-verify-jwt` (auth is the `x-panic-token` header)
7. Seed state: confirm `bot_config.paused='false'` and that `regime_state` is empty (the first daily-check will populate it).

## Paper soak
- [ ] Manually invoke `daily-check` once; confirm an `audit_log` row + a `regime_state` row appear with a sane `target_state`.
- [ ] Test the kill button:
  `curl -i -X POST "https://<ref>.supabase.co/functions/v1/panic?action=pause" -H "x-panic-token: <token>"`
  → HTTP 200, `bot_config.paused` flips to `true`; then `?action=resume`. (A failed action returns **HTTP 500** with an `error:` result — don't treat a 500 as success. Note: `?action=liquidate` also sets `paused=true` so daily-check can't re-buy the dumped position — `resume` to re-enable trading.)
- [ ] Let the cron run for a full week; verify daily flips and 5-min kill-switch ticks land in `audit_log` with expected outcomes; confirm Discord notifications arrive (the n8n flow renders `body.message` — the TS payloads carry it).
- [ ] If alerts are missing or daily-check seems to no-op, check for cron→function HTTP failures:
  `select * from net._http_response order by created desc limit 20;` (a wrong `PROJECT_REF` makes cron fire silent no-ops).

## Cut to live
- [ ] After a clean soak: `supabase secrets set ALPACA_PAPER=false` (live keys) and redeploy functions.
- [ ] Watch the first live daily-check + a kill-switch tick closely.

## Decommission old stack
- [ ] Tag the pre-migration tree FIRST: `git tag v1.0 <pre-migration-commit> && git push --tags` (do this before deleting any Python production code).
- [ ] Stop the host cron entries for `daily_check.py` and `monitor/kill_switch.py`.
- [ ] Shut down the IBKR Gateway/TWS + its VPS.
- [ ] Archive `trading_bot.db` (SQLite) for forensic history; the new system uses Supabase.
- [ ] Remove the Python production modules (`daily_check.py`, `monitor/`, `tools/ibkr_broker.py`, `tools/database.py`, `tools/notifications.py`, `config/settings.py`, `storage/`) once the TS bot is live and stable. Keep `backtest/` (research).
