# Current Configuration

(Last reviewed: 2026-07-13 — `NOTIFY_WEBHOOK_URL` now set on dev + prod, #362.)

The bot runs on Supabase (`pg_cron` -> Edge Functions -> Postgres) + Alpaca. Settings are stored
as Supabase secrets (`supabase secrets set`), not a local `.env`.

## Schedule (UTC)

Registered by `supabase/migrations/0002_schedule.sql`; daily-check rescheduled by
`0006_daily_check_open_schedule.sql` (`pg_cron`):

- `37 13 * * 1-5` + `37 14 * * 1-5` — `daily-check` Edge Function, jobs `daily-check-1337`/`daily-check-1437` (post-open; calls Alpaca `/v2/clock` and exits `skipped:market_closed` when the US market is closed. During EDT (open 13:30 UTC) the 13:37 run acts and the 14:37 run is an idempotent no-op `success`; during EST (open 14:30 UTC) the 13:37 run gate-exits and the 14:37 run acts; on holidays both runs gate-exit. Signals on the previous completed trading day's SPY close; if the last completed bar doesn't match the most recent trading day from Alpaca's calendar, it exits `skipped:stale_data`)
- `*/5 13-21 * * 1-5` — `kill-switch` Edge Function (every 5 min; calls `getOpenPositions()` first and exits `success:no_position` when flat, then gates on Alpaca `/v2/clock` per-position inside `checkOnePosition` exiting `skipped:market_closed` when the market is shut)

## Secrets (`supabase secrets set`)

| Secret | Default | What it does |
|---|---|---|
| `ALPACA_API_KEY` | — | Alpaca broker + data key |
| `ALPACA_SECRET_KEY` | — | Alpaca broker + data secret |
| `ALPACA_PAPER` | `true` | `true` = paper trading, `false` = live |
| `ALPACA_DATA_FEED` | `iex` | Alpaca market-data feed for daily bars, latest trade, and latest quote: `iex` (free) or `sip` (live feed) |
| `BOT_TICKER` | `UPRO` | Instrument the bot trades (3x leveraged S&P 500 ETF) |
| `BOT_BENCHMARK` | `SPY` | Instrument used for the regime decision |
| `REGIME_SMA_DAYS` | `200` | SMA window for the regime decision (validated 20–500) |
| `KILL_SWITCH_DRAWDOWN_PCT` | `0.25` | Drawdown from rolling high that triggers the kill switch |
| `KILL_SWITCH_LOOKBACK_DAYS` | `30` | Trading-day window for the rolling high |
| `PANIC_TOKEN` | — | `x-panic-token` header value for the panic Edge Function |
| `STATUS_TOKEN` | — | `x-status-token` header value for the read-only status Edge Function (#354); no default — unset/blank throws |
| `NOTIFY_WEBHOOK_URL` | — (optional) | Discord incoming-webhook URL; unset = notifications skipped |

Account currency is **USD** (Alpaca accounts are USD-denominated). The runtime pause flag is not a
secret — it lives in the `bot_config` row (`key='paused'`, seeded `false`), toggled via the `panic`
Edge Function.

## Vault secrets (per project, one-time, in the SQL editor)

Read by the cron jobs in `0002_schedule.sql` (so the same committed migration works for dev and prod):

- `service_role_key` — the project's service-role key (cron sends it as the bearer to JWT-verified functions)
- `functions_base_url` — `https://<ref>.supabase.co/functions/v1`

## Supabase projects

- **dev / paper:** `trading-bot-dev` — ref `qdaxxsuicyiscdvsdowc` — `ALPACA_PAPER=true`, deployed and soaking.
- **prod / live:** `trading-bot` — ref `yomamlrozydhgleumnon` — not yet deployed (go-live target; uses live keys + `ALPACA_PAPER=false`).

## Dashboard (`web/`)

Read-only Next.js status page on Vercel. Env vars (Vercel -> Settings -> Environment Variables,
server-side only): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. Point at dev during the soak; switch
to prod at go-live. See `web/.env.example`.

## Hourly-check bot settings (dev/paper)

The hourly candlestick bot (`hourly-check`, #475/#477) has been live on the dev/paper
project (`qdaxxsuicyiscdvsdowc`) since 2026-07-30. Its settings are stored as Supabase
secrets, same as the daily bot's above. Below is the deployed value of every `HOURLY_*`
and `SIZING_*` setting, with the source each value was derived from.

> **Note: `supabase secrets list` returns SHA-256 digests, not plaintext values.**
> Supabase stores secret values hashed; `supabase secrets list` shows only the digest,
> so a deployed value cannot be read back directly from the project. The values below
> are inferred from the code defaults, `.env.example`, and the rollout runbook's
> `supabase secrets set` command — not read from the live project. A future operator
> should not assume `supabase secrets list` will echo the value they (or a predecessor)
> set.

| Setting | Value | Source |
|---|---|---|
| `HOURLY_BOT_TICKER` | `SPY` | Code default (`config.ts` `strEnv("HOURLY_BOT_TICKER", "SPY")`); `.env.example` agrees; runbook §4 `supabase secrets set` command sets `HOURLY_BOT_TICKER=SPY` |
| `HOURLY_BOT_PAPER_ONLY` | `true` | Code default: `getHourlyConfig()` throws unless explicitly `"true"` (`config.ts`); `.env.example` documents `HOURLY_BOT_PAPER_ONLY=true`; runbook §4 sets `HOURLY_BOT_PAPER_ONLY=true` |
| `HOURLY_SHORTS_ENABLED` | `false` | Code default: `getHourlyShortsEnabled()` defaults to `"false"`, fail-closed (`config.ts`); `.env.example` documents `HOURLY_SHORTS_ENABLED=false`; runbook §1 states `false` is non-negotiable; runbook §4 sets `HOURLY_SHORTS_ENABLED=false`; runbook §9 gate 7 closes on operator attestation (2026-07-29, #479) |
| `HOURLY_SCAN_START_HOUR` | `13` | Code default (`config.ts` `intEnv("HOURLY_SCAN_START_HOUR", 13)`); `.env.example` agrees; cron envelope is 13-21 UTC; defaults match envelope so existing `isBarPartial`/`isFlattenScan` logic does the actual narrowing (#628) |
| `HOURLY_SCAN_END_HOUR` | `21` | Code default (`config.ts` `intEnv("HOURLY_SCAN_END_HOUR", 21)`); `.env.example` agrees; hours >= this value are flatten-only; defaults match cron envelope (#628) |
| `HOURLY_BRACKET_R_MULTIPLE` | `2` | Code default (`config.ts` `floatEnv("HOURLY_BRACKET_R_MULTIPLE", 2)`); code enforces exactly `2` for v1 (spec §7); `.env.example` agrees; runbook §4 sets `HOURLY_BRACKET_R_MULTIPLE=2` |
| `HOURLY_STOP_BUFFER_PCT` | `0.05` | Code default (`config.ts` `floatEnv("HOURLY_STOP_BUFFER_PCT", 0.05)`); `.env.example` agrees; runbook §4 sets `HOURLY_STOP_BUFFER_PCT=0.05` |
| `HOURLY_MIN_STOP_DISTANCE` | `0.05` | Code default (`config.ts` `floatEnv("HOURLY_MIN_STOP_DISTANCE", 0.05)`); `.env.example` agrees; runbook §4 sets `HOURLY_MIN_STOP_DISTANCE=0.05` |
| `HOURLY_MAX_ENTRIES_PER_DAY` | `3` | Code default (`config.ts` `intEnv("HOURLY_MAX_ENTRIES_PER_DAY", 3)`); `.env.example` agrees; runbook §4 sets `HOURLY_MAX_ENTRIES_PER_DAY=3` |
| `HOURLY_STALENESS_TOLERANCE_MIN` | `10` | Code default (`config.ts` `intEnv("HOURLY_STALENESS_TOLERANCE_MIN", 10)`); `.env.example` agrees; runbook §4 sets `HOURLY_STALENESS_TOLERANCE_MIN=10`; runbook §8 T10 verified `7 + 1 = 8 < 10` with 2 min headroom |
| `HOURLY_CONTEXT_MODE` | `none` | Code default (`config.ts` `strEnv("HOURLY_CONTEXT_MODE", "none")`); `.env.example` agrees; runbook §4 sets `HOURLY_CONTEXT_MODE=none` |
| `SIZING_RISK_PCT` | `0.01` | Code default (`config.ts` `floatEnv("SIZING_RISK_PCT", 0.01)`); `.env.example` agrees; runbook §4 sets `SIZING_RISK_PCT=0.01` |
| `SIZING_NOTIONAL_CAP_PCT` | `0.10` | Code default (`config.ts` `floatEnv("SIZING_NOTIONAL_CAP_PCT", 0.10)`); `.env.example` agrees; runbook §4 sets `SIZING_NOTIONAL_CAP_PCT=0.10` |

All three derivation sources (code default, `.env.example`, runbook §4 `supabase secrets set`
command) agree on every value. No source contradicts another. The runbook's §4 command
was executed against `qdaxxsuicyiscdvsdowc` on 2026-07-29 (§2 ledger, "Capture evidence"
comment on #479).

## Operational state

- Deployment: dev (`qdaxxsuicyiscdvsdowc`) paper, soaking; prod not yet deployed.
- `NOTIFY_WEBHOOK_URL` set on **dev and prod** since 2026-07-13 (direct Discord webhook, #362 —
  verified end-to-end with a panic-resume test). Notifications remain best-effort/fire-and-forget.
- **Heartbeat (#361, #400):** `.github/workflows/heartbeat.yml` pings the `status` Edge Function on
  weekdays so Supabase sees real API traffic — `pg_cron` alone does not count toward the free-tier
  inactivity/pause criterion. Dev is covered now (reuses the existing `STATUS_URL`/`STATUS_TOKEN`
  repo secrets). Prod has been covered since 2026-07-20 via an interim keep-alive (`KEEPALIVE_URL_PROD`/
  `KEEPALIVE_ANON_KEY_PROD` — an anon REST read of the RLS-deny-all `public.keepalive` table); setting
  `STATUS_URL_PROD`/`STATUS_TOKEN_PROD` at go-live (#230) takes precedence over the keep-alive and lets
  it be retired. The optional `HEARTBEAT_REQUIRE_PROD` repo variable (default unset) makes a prod leg
  with neither pair configured fail the run red instead of an inert skip. See
  `docs/runbooks/status-check.md`.
