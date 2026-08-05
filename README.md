# Trading Bot

A deterministic rules-engine swing trading bot. Each trading day shortly after the US open it computes a 200-day SMA on SPY as of the previous completed close, decides whether to be LONG (in UPRO, a 3x leveraged S&P 500 ETF) or in CASH, reconciles with Alpaca, and flips the position via a market order if needed. A 5-minute kill switch liquidates intraday if drawdown breaches a threshold. The bot runs serverlessly on Supabase (`pg_cron` -> Edge Functions -> Postgres) and trades through Alpaca's REST API.

No LLM is in the trading path. The strategy is a pure function (`computeTargetState` in `supabase/functions/_shared/regime.ts`); every decision is reproducible from the SPY history alone.

## Architecture

```
pg_cron (37 13&14 * * 1-5 UTC)  -> Edge Fn: daily-check --+
pg_cron (*/5 13-21 * * 1-5 UTC) -> Edge Fn: kill-switch --+-> shared TS modules -> Alpaca REST (read/write)
operator HTTP + x-panic-token   -> Edge Fn: panic       --+                       -> Postgres (read/write)
                                                                                   -> Discord webhook

operator HTTP + x-status-token  -> Edge Fn: status (read-only, no writes)
                                    -> Alpaca REST (read-only) + Postgres (read-only)
```

Everything runs inside one Supabase project: `pg_cron` schedules the jobs, which invoke
TypeScript/Deno **Edge Functions**, which persist to **Postgres** and trade through **Alpaca**
REST (broker + market data). Notifications go directly to a Discord incoming webhook. There is
no always-on gateway, no VPS, and no host cron.

Each function (`supabase/functions/<name>/`) is split into `logic.ts` (pure, testable) and
`index.ts` (HTTP entry) over shared modules in `supabase/functions/_shared/`:
`regime`, `config`, `alpaca`, `marketdata`, `db`, `notifications`, `num`, `supabase_client`.

**Decision rule.** `daily-check` runs shortly after the US open — two pg_cron slots (`37 13 * * 1-5`
and `37 14 * * 1-5` UTC) cover US DST; the function calls Alpaca `/v2/clock` and exits
`skipped:market_closed` when the market is closed. During EDT (open 13:30 UTC) the 13:37 run acts
and the 14:37 run, with the market already open, repeats the pipeline as an idempotent no-op
(`success`, no second trade); during EST (open 14:30 UTC) the 13:37 run gate-exits and the 14:37
run acts; on market holidays both runs gate-exit. It fetches SPY daily bars from Alpaca, drops today's
in-progress bar, computes the 200-day SMA on the previous completed trading day's close (the same
information set as a post-close run, with execution at the next open — exactly what the backtest
models), and calls `computeTargetState({ spyClose, spySma200, currentState, killSwitchActive })`:

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

**Panic kill button.** `panic` is a token-authenticated Edge Function (header `x-panic-token`,
POST only). `action=pause|resume|cancel-orders|liquidate`. The `pause` flag lives in the
`bot_config` DB row (serverless env vars are not runtime-writable), so `pause`/`resume` toggle it;
`cancel-orders` and `liquidate` call Alpaca directly. A successful `liquidate` **also sets
`paused=true`** so the next daily-check cannot re-buy the position you just dumped — clear it with
`action=resume` when you want the bot trading again. No LLM is in this path.

**Status visibility.** `status` is a token-authenticated, GET-only, strictly read-only Edge
Function (header `x-status-token`) for on-demand operator/advisor visibility. It returns a single
JSON digest: latest regime state, 7-day `audit_log` outcome counts plus any `error:*` rows
verbatim, the last trade, the `paused` flag, and the Alpaca paper equity + open position. An
optional `?days=N` query param (1-60, default 7) widens the `audit_log` window and adds two arrays
to the digest — `trades` and `regime_history`, covering the window — while the no-param response
stays shape-identical to the default digest. It reads only — no mutating broker helper, no writes,
not even its own `audit_log` row, so that table stays a clean record of trading actions. See
`docs/runbooks/status-check.md` and `scripts/status.sh`.

## Database

Postgres in Supabase (`supabase/migrations/0001_init.sql`). Tables:

- `regime_state` — one row per trading day (`spy_close`, `spy_sma200`, `target_state`,
  `current_state`, `position_drawdown_pct`, `kill_switch_active`, `kill_switch_fired_at`);
  `spy_close`/`spy_sma200` hold the previous completed session's values (the signal bar).
- `trades` — broker fills (`symbol`, `side`, `qty`, `fill_price`, `fill_time`,
  `broker_order_id`, `reason`).
- `audit_log` — one row per function invocation (`script_name`, `started_at`, `finished_at`,
  `outcome`, `notes`). `outcome` is written before exit so a crashed run leaves a forensic row.
  `status` deliberately writes no row here — it only reads this table.
- `bot_config` — key/value config; holds the runtime `paused` flag.

All tables are RLS-deny-all; the Edge Functions connect with the service-role key (which bypasses
RLS). The cron jobs (`0002_schedule.sql`; daily-check rescheduled by
`0006_daily_check_open_schedule.sql`) read the service-role key and the functions base URL from
**Vault** secrets (`service_role_key`, `functions_base_url`), so the same committed migrations work
for both dev and prod — only the Vault values differ.

## Configuration

Secrets are set per Supabase project via `supabase secrets set` (not a local `.env`):

| Secret | Value / default | Notes |
|---|---|---|
| `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | — | Alpaca broker + data credentials |
| `ALPACA_PAPER` | `true` | `true` = paper, `false` = live |
| `ALPACA_DATA_FEED` | `iex` | Alpaca market-data feed for daily bars, latest trade, and latest quote: `iex` (free) or `sip` (live feed) |
| `BOT_TICKER` | `UPRO` | Instrument the bot trades (3x S&P 500 ETF) |
| `BOT_BENCHMARK` | `SPY` | Instrument used for the regime decision |
| `REGIME_SMA_DAYS` | `200` | SMA window (validated 20–500) |
| `KILL_SWITCH_DRAWDOWN_PCT` | `0.25` | Drawdown from rolling high that fires the kill switch |
| `KILL_SWITCH_LOOKBACK_DAYS` | `30` | Trading-day window for the rolling high |
| `PANIC_TOKEN` | — | `x-panic-token` header value for the panic function |
| `STATUS_TOKEN` | — | `x-status-token` header value for the read-only status function; no default — unset/blank throws |
| `NOTIFY_WEBHOOK_URL` | — (optional) | Discord incoming-webhook URL; unset = notifications skipped |
| `HOURLY_BOT_TICKER` | `SPY` | Instrument the hourly-candlestick bot trades (#475) |
| `SIZING_RISK_PCT` | `0.01` | Hourly bot risk budget per trade as a fraction of equity (0, 0.05] |
| `SIZING_NOTIONAL_CAP_PCT` | `0.10` | Hourly bot notional cap per position as a fraction of equity (0, 1.0] |
| `HOURLY_BRACKET_R_MULTIPLE` | `2` | Bracket target multiple; fixed at 2 for v1 (spec revision required to change) |
| `HOURLY_STOP_BUFFER_PCT` | `0.05` | Stop buffer as a fraction of the signal bar's range (0, 0.5] |
| `HOURLY_MIN_STOP_DISTANCE` | `0.05` | Minimum entry/stop distance in USD; below this `skipped:geometry_invalid` |
| `HOURLY_MAX_ENTRIES_PER_DAY` | `3` | Max new entries per symbol per day (1 - 10) |
| `HOURLY_STALENESS_TOLERANCE_MIN` | `10` | Minutes past a completed bar's end before it is stale (1 - 60) |
| `HOURLY_CONTEXT_MODE` | `none` | `none` \| `reversal` \| `continuation` trend-context mask |
| `HOURLY_SHORTS_ENABLED` | `false` | Short entries; fail-closed, so unset means off and only an explicit `true` enables them (#493); blank or otherwise unparseable throws at function start |
| `HOURLY_BOT_PAPER_ONLY` | — | MUST be `true`; unset or `false` throws — the mechanical paper-only gate (§8.3) |

See `docs/CURRENT_CONFIG.md` for the current deployed values.

## Deploy & run

The bot has no install step on the operator side — it runs in Supabase. To deploy or go live,
follow [`docs/runbooks/mvp2-deploy-and-decommission.md`](docs/runbooks/mvp2-deploy-and-decommission.md).
The short version:

```bash
supabase link --project-ref <ref>
supabase secrets set ALPACA_API_KEY=... ALPACA_SECRET_KEY=... ALPACA_PAPER=true \
  PANIC_TOKEN=... STATUS_TOKEN=... BOT_TICKER=UPRO BOT_BENCHMARK=SPY
supabase db push                                          # applies migrations 0001-0006 (schema + cron schedule)
supabase functions deploy daily-check kill-switch         # JWT-verified; cron sends the bearer
supabase functions deploy panic --no-verify-jwt           # auth = x-panic-token header
supabase functions deploy status --no-verify-jwt          # auth = x-status-token header (read-only)
```

Then store the two Vault secrets (`service_role_key`, `functions_base_url`) once per project in the
SQL editor — see the runbook for the exact statements.

Invoke the panic kill button over HTTP:

```bash
curl -i -X POST "https://<ref>.supabase.co/functions/v1/panic?action=pause" \
  -H "x-panic-token: <token>"
# actions: pause | resume | cancel-orders | liquidate (liquidate also sets paused=true)
# 200 = success; 500 with an error: result = the action failed (don't treat it as success)
```

Check the bot's runtime status (read-only, no writes):

```bash
bash scripts/status.sh   # renders the digest via jq, from .env.status (see docs/runbooks/status-check.md)
bash scripts/status.sh --days 30   # widen the window; adds trades + regime_history arrays (1-60, default 7)
# or directly:
curl -s "https://<ref>.supabase.co/functions/v1/status?days=30" -H "x-status-token: <token>" | jq .
```

### Tests

```bash
deno task test       # all TS unit tests (Alpaca + DB mocked; the broker guard fails fast)
deno task test:db    # DB integration tests — needs a local Postgres (gated behind RUN_DB_TESTS)
# test:db is destructive and local-only: it refuses any SUPABASE_URL whose host is not a
# local-machine host (localhost, 127.0.0.0/8, ::1, host.docker.internal), naming the host it
# refused, and its --allow-net grant is scoped to those hosts as a second layer.
```

## Dashboard

A read-only Next.js status page lives in `web/` and is deployed on Vercel. It reads Supabase
server-side with the service-role key and shows the hourly bot's latest scan (bar timestamp and
decision), its open position with bracket levels, the paused flag, equity against the -15% floor,
recent scans, recent `hourly_*` trades, and recent `hourly-check` audit runs. There are no
controls — the panic kill button stays the token-auth Edge Function. A GitHub Actions job
(`web-ci.yml`) typechecks and builds it on every change. See [`web/README.md`](web/README.md).

## Backtest (research)

The Python backtester is kept for offline research (it is not in the trading path):

```bash
venv/bin/python main.py backtest --years 5
```

This forwards to `backtest/regime.py` (UPRO vehicle, SPY benchmark, 200-day SMA). Set up the
research venv with `python3 -m venv venv && venv/bin/pip install -r requirements.txt`.

## Discord notifications

The bot posts structured event payloads (`event_type: regime_flip`, `kill_switch_fired`,
`trade_failed`, `state_desync`, `broker_error`, `panic`, `error`) directly to a Discord incoming
webhook — no forwarder in between. Each payload carries a `content` field (derived from the
event's `message`, codepoint-safe-truncated to Discord's 2,000-character limit) that Discord
renders natively, plus the full structured fields for any future JSON-consuming forwarder. Set
`NOTIFY_WEBHOOK_URL` via `supabase secrets set` — see
[`docs/runbooks/discord-notifications.md`](docs/runbooks/discord-notifications.md) for the setup
steps. If unset, notifications are skipped and the bot keeps trading; the skip (and any fetch
rejection or non-2xx webhook response) is logged via `console.warn` — visible in Supabase function
logs — without ever logging the webhook URL or the full payload (#366).

Note: the webhook must be reachable from Supabase's cloud — a `localhost` URL will not work.
Notifications are best-effort, so the bot runs fine without them (they are intentionally unset
during the paper soak). A failed post (non-2xx or a fetch rejection) is persisted to the
`notification_outbox` table and retried on subsequent `daily-check`/`kill-switch` runs, bounded by a
72-hour TTL and a 500-attempt cap (#397); if the DB itself is unavailable, delivery degrades to
warn-only rather than blocking the trading pipeline.

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
|   |   |-- ...
|   |   |-- 0006_daily_check_open_schedule.sql  # daily-check post-open slots (13:37/14:37 UTC)
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
|-- docs/
|   |-- CURRENT_CONFIG.md          # Current deployed secrets/values
|   |-- runbooks/                  # Deploy & decommission runbook
```

## License

**Copyright © 2026 Thomas Mueller. All rights reserved.**

This is proprietary software. No license is granted to use, copy, modify, merge, publish, distribute, sublicense, or sell any part of this software, in whole or in part, in any other project — public or private — without prior written permission from the copyright holder.

Unauthorized reuse of any portion of this code constitutes copyright infringement and will be pursued accordingly.
