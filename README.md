# Trading Bot

A deterministic rules-engine swing trading bot. Each weekday after the US close it computes a 200-day SMA on SPY, decides whether to be LONG (in UPRO, a 3x leveraged S&P 500 ETF) or in CASH, reconciles with Alpaca, and flips the position via a market order if needed. A 5-minute kill switch liquidates intraday if drawdown breaches a threshold. The bot runs serverlessly on Supabase (`pg_cron` -> Edge Functions -> Postgres) and trades through Alpaca's REST API.

No LLM is in the trading path. The strategy is a pure function (`computeTargetState` in `supabase/functions/_shared/regime.ts`); every decision is reproducible from the SPY history alone.

## Architecture

```
pg_cron (30 22 * * 1-5 UTC)    -> Edge Fn: daily-check   --+
pg_cron (*/5 13-21 * * 1-5 UTC) -> Edge Fn: kill-switch   --+-> shared TS modules -> Alpaca REST
operator HTTP + x-panic-token   -> Edge Fn: panic         --+                       -> Postgres
                                                                                    -> n8n -> Discord
```

Everything runs inside one Supabase project: `pg_cron` schedules the jobs, which invoke
TypeScript/Deno **Edge Functions**, which persist to **Postgres** and trade through **Alpaca**
REST (broker + market data). Notifications go to the existing n8n webhook -> Discord. There is
no always-on gateway, no VPS, and no host cron.

Each function (`supabase/functions/<name>/`) is split into `logic.ts` (pure, testable) and
`index.ts` (HTTP entry) over shared modules in `supabase/functions/_shared/`:
`regime`, `config`, `alpaca`, `marketdata`, `db`, `notifications`, `num`, `supabase_client`.

**Decision rule.** `daily-check` fetches SPY daily bars from Alpaca, computes the 200-day SMA,
and calls `computeTargetState({ spyClose, spySma200, currentState, killSwitchActive })`:

- **LONG** when `spyClose > spySma200` (the kill-switch flag, if set, is cleared on this transition).
- **CASH** otherwise (when SPY is at or below the 200-DMA — the kill-switch flag, if set, is preserved).

If `targetState != currentState`, the bot places an Alpaca market order on `BOT_TICKER` (UPRO) —
either a BUY sized to ~99% of account value (USD), or a SELL of the entire position.

**Kill switch.** `kill-switch` runs every 5 minutes during US market hours (it calls Alpaca
`/v2/clock` and early-exits when the market is closed, so US DST is handled for free). If UPRO
drawdown from its `KILL_SWITCH_LOOKBACK_DAYS` rolling high — including today's running high / last
trade — exceeds `KILL_SWITCH_DRAWDOWN_PCT` (default 25%), it liquidates the position and sets
`kill_switch_active=true` in `regime_state`. While the flag is active **and SPY remains below the
200-DMA**, `daily-check` keeps the bot in CASH. The flag is cleared on the first day SPY closes
back above the 200-DMA, at which point the bot re-enters LONG — so a single bad-week kill-switch
fire does not lock the bot out of the next bull run.

**Panic kill button.** `panic` is a token-authenticated Edge Function (header `x-panic-token`).
`action=pause|resume|cancel-orders|liquidate`. The `pause` flag lives in the `bot_config` DB row
(serverless env vars are not runtime-writable), so `pause`/`resume` toggle it; `cancel-orders` and
`liquidate` call Alpaca directly. No LLM is in this path.

## Database

Postgres in Supabase (`supabase/migrations/0001_init.sql`). Tables:

- `regime_state` — one row per trading day (`spy_close`, `spy_sma200`, `target_state`,
  `current_state`, `position_drawdown_pct`, `kill_switch_active`, `kill_switch_fired_at`).
- `trades` — broker fills (`symbol`, `side`, `qty`, `fill_price`, `fill_time`,
  `broker_order_id`, `reason`).
- `audit_log` — one row per function invocation (`script_name`, `started_at`, `finished_at`,
  `outcome`, `notes`). `outcome` is written before exit so a crashed run leaves a forensic row.
- `bot_config` — key/value config; holds the runtime `paused` flag.

All tables are RLS-deny-all; the Edge Functions connect with the service-role key (which bypasses
RLS). The cron jobs (`0002_schedule.sql`) read the service-role key and the functions base URL from
**Vault** secrets (`service_role_key`, `functions_base_url`), so the same committed migration works
for both dev and prod — only the Vault values differ.

## Configuration

Secrets are set per Supabase project via `supabase secrets set` (not a local `.env`):

| Secret | Value / default | Notes |
|---|---|---|
| `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | — | Alpaca broker + data credentials |
| `ALPACA_PAPER` | `true` | `true` = paper, `false` = live |
| `BOT_TICKER` | `UPRO` | Instrument the bot trades (3x S&P 500 ETF) |
| `BOT_BENCHMARK` | `SPY` | Instrument used for the regime decision |
| `REGIME_SMA_DAYS` | `200` | SMA window (validated 20–500) |
| `KILL_SWITCH_DRAWDOWN_PCT` | `0.25` | Drawdown from rolling high that fires the kill switch |
| `KILL_SWITCH_LOOKBACK_DAYS` | `30` | Trading-day window for the rolling high |
| `PANIC_TOKEN` | — | `x-panic-token` header value for the panic function |
| `N8N_WEBHOOK_URL` | — (optional) | Discord notification webhook; unset = notifications skipped |

See `docs/CURRENT_CONFIG.md` for the current deployed values.

## Deploy & run

The bot has no install step on the operator side — it runs in Supabase. To deploy or go live,
follow [`docs/runbooks/mvp2-deploy-and-decommission.md`](docs/runbooks/mvp2-deploy-and-decommission.md).
The short version:

```bash
supabase link --project-ref <ref>
supabase secrets set ALPACA_API_KEY=... ALPACA_SECRET_KEY=... ALPACA_PAPER=true \
  PANIC_TOKEN=... BOT_TICKER=UPRO BOT_BENCHMARK=SPY
supabase db push                                          # applies 0001_init + 0002_schedule
supabase functions deploy daily-check kill-switch         # JWT-verified; cron sends the bearer
supabase functions deploy panic --no-verify-jwt           # auth = x-panic-token header
```

Then store the two Vault secrets (`service_role_key`, `functions_base_url`) once per project in the
SQL editor — see the runbook for the exact statements.

Invoke the panic kill button over HTTP:

```bash
curl -i -X POST "https://<ref>.supabase.co/functions/v1/panic?action=pause" \
  -H "x-panic-token: <token>"
# actions: pause | resume | cancel-orders | liquidate
# 200 = success; 500 with an error: result = the action failed (don't treat it as success)
```

### Tests

```bash
deno task test       # all TS unit tests (Alpaca + DB mocked; the broker guard fails fast)
deno task test:db    # DB integration tests — needs a local Postgres (gated behind RUN_DB_TESTS)
```

## Dashboard

A read-only Next.js status page lives in `web/` and is deployed on Vercel. It reads Supabase
server-side with the service-role key and shows the current position, regime, drawdown,
kill-switch flag, paused banner, recent trades, and recent audit runs. There are no controls — the
panic kill button stays the token-auth Edge Function. See [`web/README.md`](web/README.md).

## Backtest (research)

The Python backtester is kept for offline research (it is not in the trading path):

```bash
venv/bin/python main.py backtest --years 5
```

This forwards to `backtest/regime.py` (UPRO vehicle, SPY benchmark, 200-day SMA). Set up the
research venv with `python3 -m venv venv && venv/bin/pip install -r requirements.txt`.

## Discord notifications (via n8n)

The bot posts structured event payloads (`event_type: regime_flip`, `kill_switch_fired`,
`trade_failed`, `state_desync`, `broker_error`, `panic`, `error`) to an n8n webhook, which forwards
to Discord. Each payload carries a `message` field that the n8n flow renders. Set `N8N_WEBHOOK_URL`
via `supabase secrets set`. If unset, notifications are silently skipped and the bot keeps trading.

Note: the webhook must be reachable from Supabase's cloud — a `localhost` URL will not work, and a
Cloudflare-Access-protected n8n needs a **bypass** on the `/webhook/...` path (the bot sends no auth
header). Notifications are best-effort, so the bot runs fine without them (they are intentionally
unset during the paper soak).

## History

This repo previously ran a Python bot against Interactive Brokers, persisting to SQLite and driven
by host cron on a VPS (vehicle `WSPL.DE`, market data from yfinance). That stack was migrated to the
TypeScript / Supabase / Alpaca system described above (#220, PRs #226/#234) and the old Python
production code was **removed** on 2026-06-05 (#232). It survives in git history and is tagged
`v2.0.0`. The deterministic 200-DMA decision rule itself is unchanged — only the infrastructure and
the trading vehicle (`WSPL.DE` -> `UPRO`, forced by Alpaca being US-listed-only) changed.

Earlier still, v1.14 used a 4-LLM-agent pipeline; a 5-year backtest showing it was effectively a
coin flip vs cost prompted the pivot to the deterministic rules engine.

## Project structure

```
.
|-- supabase/
|   |-- migrations/
|   |   |-- 0001_init.sql          # Postgres schema (regime_state, trades, audit_log, bot_config)
|   |   |-- 0002_schedule.sql      # pg_cron jobs + Vault-backed cron auth
|   |-- functions/
|   |   |-- _shared/               # regime, config, alpaca, marketdata, db, notifications, num, ...
|   |   |-- daily-check/           # logic.ts + index.ts — daily regime flip (cron)
|   |   |-- kill-switch/           # logic.ts + index.ts — 5-min drawdown sweep (cron)
|   |   |-- panic/                 # logic.ts + index.ts — token-auth kill button (HTTP)
|-- web/                           # Read-only Next.js status dashboard (Vercel)
|-- backtest/                      # Python research backtester (regime.py — not in trading path)
|-- strategy/regime.py             # Kept Python reference port of the decision rule
|-- main.py                        # `python main.py backtest ...` research entry
|-- deno.json                      # Deno tasks (test, test:db)
|-- n8n/                           # n8n -> Discord workflow export
|-- docs/
|   |-- CURRENT_CONFIG.md          # Current deployed secrets/values
|   |-- runbooks/                  # Deploy & decommission runbook
```
