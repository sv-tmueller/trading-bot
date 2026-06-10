# Current Configuration

(Last reviewed: 2026-06-10 for the daily-check post-open schedule change, #256.)

The bot runs on Supabase (`pg_cron` -> Edge Functions -> Postgres) + Alpaca. Settings are stored
as Supabase secrets (`supabase secrets set`), not a local `.env`.

## Schedule (UTC)

Registered by `supabase/migrations/0002_schedule.sql`; daily-check rescheduled by
`0006_daily_check_open_schedule.sql` (`pg_cron`):

- `37 13 * * 1-5` + `37 14 * * 1-5` — `daily-check` Edge Function, jobs `daily-check-1337`/`daily-check-1437` (post-open; calls Alpaca `/v2/clock` and exits `skipped:market_closed` unless the US market is open, so exactly one slot executes per trading day — 13:37 during EDT, 14:37 during EST — and holidays skip entirely. Signals on the previous completed trading day's SPY close; if the last completed bar doesn't match the most recent trading day from Alpaca's calendar, it exits `skipped:stale_data`)
- `*/5 13-21 * * 1-5` — `kill-switch` Edge Function (every 5 min; calls Alpaca `/v2/clock` and exits `skipped:market_closed` when the market is shut)

## Secrets (`supabase secrets set`)

| Secret | Default | What it does |
|---|---|---|
| `ALPACA_API_KEY` | — | Alpaca broker + data key |
| `ALPACA_SECRET_KEY` | — | Alpaca broker + data secret |
| `ALPACA_PAPER` | `true` | `true` = paper trading, `false` = live |
| `BOT_TICKER` | `UPRO` | Instrument the bot trades (3x leveraged S&P 500 ETF) |
| `BOT_BENCHMARK` | `SPY` | Instrument used for the regime decision |
| `REGIME_SMA_DAYS` | `200` | SMA window for the regime decision (validated 20–500) |
| `KILL_SWITCH_DRAWDOWN_PCT` | `0.25` | Drawdown from rolling high that triggers the kill switch |
| `KILL_SWITCH_LOOKBACK_DAYS` | `30` | Trading-day window for the rolling high |
| `PANIC_TOKEN` | — | `x-panic-token` header value for the panic Edge Function |
| `N8N_WEBHOOK_URL` | — (optional) | Discord notification webhook; unset = notifications skipped |

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

## Operational state

- Deployment: dev (`qdaxxsuicyiscdvsdowc`) paper, soaking; prod not yet deployed.
- `N8N_WEBHOOK_URL` intentionally unset on dev during the soak (notifications are best-effort).
