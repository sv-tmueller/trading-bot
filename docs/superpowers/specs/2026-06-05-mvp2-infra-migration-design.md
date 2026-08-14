# MVP 2.0 — Core equity-bot migration to Supabase + Alpaca (infra-only)

**Date:** 2026-06-05
**Issue:** [#220](https://github.com/sv-tmueller/trading-bot/issues/220)
**Status:** Design (brainstorm complete; awaiting user spec review → writing-plans)
**Scope:** Core deterministic bot only. The LLM read-only advisor/reporter is explicitly **out of scope** and gets its own spec → plan → build cycle once this migration is proven on paper.

## 1. Problem & goal

The production bot is the deterministic 200-DMA equity regime bot: `daily_check.py` flips
between LONG and CASH once per weekday; `monitor/kill_switch.py` enforces a drawdown
kill-switch; both talk to **IBKR** via an always-on TWS/Gateway, persist to **SQLite**, and
are driven by **host cron**. The options layer explored earlier in #220 was killed (see
`docs/research/mvp2-pcs-riv-backtest.md`); MVP 2.0 was re-scoped to a pure **infrastructure
migration** of the existing deterministic bot.

**Goal:** run the *same* deterministic strategy on a serverless stack — **Supabase**
(`pg_cron` + Edge Functions + Postgres) + **Alpaca** (stateless REST broker + market data) —
with **no always-on gateway, no VPS, no host cron, no SQLite**. Behaviour is preserved except
where the broker switch forces a change (trading vehicle) or where the user opted into an
improvement (kill-switch cadence).

This is **not** a strategy change. The one decision rule is unchanged. There is no LLM in the
trading path.

## 2. Decisions (resolved in brainstorm 2026-06-05)

| Topic | Decision | Rationale |
|---|---|---|
| Scope | Core deterministic bot only; LLM advisor deferred to its own spec | Advisor only reads data this migration produces; ship + prove the bot first |
| Language | **TypeScript** (Deno runtime, Supabase Edge Functions) | Native to Supabase/Edge (Deno/TS-only); the bulk of I/O (broker + DB) is rewritten regardless, so the reusable Python core is tiny |
| Trading vehicle | **UPRO** (ProShares UltraPro S&P 500, 3×); benchmark stays **SPY** | Alpaca is US-listed-only, so `WSPL.DE` (Xetra UCITS 3×) cannot be held; UPRO is the closest US-listed 3× equivalent, keeping the strategy behaviour-preserving |
| Stack | **Supabase only** (`pg_cron` + Edge Functions + Postgres) + Alpaca REST; n8n→Discord unchanged. **No Vercel.** | No-UI bot; `pg_cron` gives free fine-grained scheduling and compute co-located with the DB; Vercel's free tier can't do sub-daily cron |
| Market data | **Alpaca data API** (drop `yfinance`) | Already integrating Alpaca; removes a Python-only, heavy dependency; works in TS |
| Kill-switch | **Every 5 min** during US market hours, last-*trade* price vs rolling high incl. today | User opted for max responsiveness on a 3× vehicle; `pg_cron` makes cadence free |
| Operator kill button | **Token-authenticated `panic` Edge Function** (pause/resume/cancel-orders/liquidate); pause flag moves to a DB row | Serverless env vars aren't runtime-writable and there's no always-on machine; an HTTP endpoint is callable immediately from anywhere |
| PR #93 (`BaseBroker`/`AlpacaBroker`) | **Not reusable** (it's Python); reference only for the Alpaca API surface | Language decision (TS) supersedes it |
| Repo layout | **Polyglot, replace-in-place**: TS production replaces the Python production bot; Python `backtest/` research stays | Cheap to keep research; tag the current tree `v1.0` first |
| `trades` order-id column | Rename `ibkr_order_id` → **`broker_order_id`** | Fresh DB; the column is now broker-agnostic |

### Hard prerequisites (must be confirmed before/early in implementation)
- **UPRO must be buyable on the user's Alpaca account.** US-domiciled leveraged ETFs are
  PRIIPs-blocked at most EU brokers; Alpaca is a US broker so access is likely but unverified.
  If UPRO is not tradeable, the vehicle decision must be revisited before building on it.
- **Rotate the Alpaca paper keys** that were pasted in plaintext in a prior session.

## 3. Architecture

Three Supabase Edge Functions (TypeScript/Deno) over a set of shared TS modules. All
scheduling is `pg_cron`; all persistence is Postgres; the broker and market data are Alpaca
REST; notifications are the existing n8n webhook → Discord.

```
pg_cron (30 22 * * 1-5 UTC) ─→ Edge Fn: daily-check ─┐
pg_cron (*/5 13-21 * * 1-5 UTC) ─→ Edge Fn: kill-switch ┤─→ shared TS modules ─→ Alpaca REST
operator HTTP + token ─────────→ Edge Fn: panic ───────┘                         ─→ Postgres
                                                                                  ─→ n8n→Discord
```

### Edge Functions
- **`daily-check`** — `pg_cron` `30 22 * * 1-5` UTC (post-US-close). Port of `daily_check.py`.
- **`kill-switch`** — `pg_cron` `*/5 13-21 * * 1-5` UTC. The window is intentionally wider than
  any single DST regime; the function calls Alpaca `/v2/clock` (`is_open`) and early-exits when
  the market is closed, so US DST is handled for free without changing the cron expression.
  Port of `monitor/kill_switch.py`, intraday variant.
- **`panic`** — HTTP-invoked, manual, token-authenticated. `action=pause|resume|cancel-orders|liquidate`.

### Shared TS modules
- **`regime.ts`** — pure `computeTargetState({ spyClose, spySma200, currentState, killSwitchActive })`
  → `{ targetState, killSwitchActive }`. 1:1 port of `strategy/regime.py`, including input
  validation and the NaN-SMA → defensive-CASH branch. I/O-free.
- **`alpaca.ts`** — broker client: `getPosition`, `getAccountValue`, `placeMarketOrder`,
  `liquidate`, `cancelAllOrders`, `getClock`. Carries the broker guard (§5).
- **`marketdata.ts`** — Alpaca data API: daily bars (SPY for SMA200, UPRO for kill-switch
  lookback), latest trade (UPRO intraday price).
- **`db.ts`** — Supabase/Postgres queries mirroring `tools/database.py`
  (`upsertRegimeState`, `getLatestRegimeState`, `insertTrade`, `insertAuditLog`,
  `updateAuditLog`, plus `getConfig`/`setConfig` for `bot_config`).
- **`notifications.ts`** — n8n webhook POST (same structured `event_type` payloads:
  `regime_flip`, `kill_switch_fired`, `trade_failed`, `state_desync`, plus the panic/error ones).
- **`config.ts`** — read + range-validate settings from Edge Function secrets, ported from
  `config/settings.py` (raise on out-of-range at function start).

## 4. Data flow

### daily-check
1. Insert `audit_log` row (`script_name='daily-check'`, `started_at`).
2. If `bot_config.paused` is truthy → `audit_log.outcome = skipped:trading_paused`, exit 0 (no
   Alpaca, no data).
3. Fetch SPY daily bars from Alpaca (≥ `REGIME_SMA_DAYS` + buffer).
4. **Stale-data guard:** if Alpaca's latest SPY daily bar predates today (UTC) →
   `outcome = skipped:stale_data`, exit 0.
5. Compute `spy_close`, `spy_sma200`; read latest `regime_state` for `current_state` +
   `kill_switch_active`; call `computeTargetState`.
6. Reconcile against Alpaca position truth: `broker_state = LONG if qty(UPRO) > 0 else CASH`.
   On desync, notify `state_desync`, adopt broker truth, recompute target.
7. If `target != current`: place Alpaca market order on UPRO (BUY sized to ~99% of account
   value / last UPRO price, or SELL-all for CASH), insert `trades`, notify `regime_flip`.
   Account value is read in **USD** (Alpaca accounts are USD-denominated — a change from the
   IBKR bot's EUR). Insufficient-buying-power and failed-liquidation paths mirror the current
   `error:*` outcomes.
8. Upsert `regime_state`; update `audit_log` (`finished_at`, `outcome`, `notes`).
9. **Idempotent:** a second run the same trading day recomputes the same target, sees
   `current_state` already matches, writes a no-op `regime_state` row.

### kill-switch
1. Insert `audit_log` row.
2. Read latest `regime_state`; if `current_state != LONG` → `success:no_position`, exit.
3. Call Alpaca `/v2/clock`; if closed → `skipped:market_closed`, exit.
4. Fetch UPRO last trade price + last `KILL_SWITCH_LOOKBACK_DAYS` daily bars; compute
   `rolling_high = max(lookback daily highs, today's running high/last trade)`;
   `drawdown = last_trade / rolling_high − 1`. Persist `position_drawdown_pct`.
5. If `drawdown > −KILL_SWITCH_DRAWDOWN_PCT` → `success:within_threshold`, exit.
6. Else liquidate UPRO via Alpaca; insert `trades`; set `kill_switch_active=true`,
   `kill_switch_fired_at`; notify `kill_switch_fired`. Mirror the existing
   no-position / liquidate-failed branches and their `outcome` strings.

### panic
1. Verify `PANIC_TOKEN`; reject otherwise (no DB/broker side effects on auth failure).
2. Insert `audit_log` row (`script_name='panic'`) **before** any broker call.
3. Dispatch on `action`:
   - `pause` / `resume` → set `bot_config.paused`.
   - `cancel-orders` → Alpaca `cancelAllOrders`.
   - `liquidate` → Alpaca `liquidate(UPRO)` (+ insert `trades` with `reason='panic_cli'`).
4. Update `audit_log` in a `finally` with the per-action result (recoverable from the DB on a
   partial run).

## 5. Safety invariants carried over (non-negotiable)

- **No LLM in the trading path.** None of the three Edge Functions import any model SDK.
- **One decision rule.** `regime.ts` is the only signal; pure and fully unit-tested; every
  decision reproducible from SPY history alone.
- **Broker guard (ported #168).** The mutating/connection helpers in `alpaca.ts`
  (`placeMarketOrder`, `liquidate`, `cancelAllOrders`, and any client init that can place
  orders) throw `BrokerCallBlockedError` when `CLAUDE_AGENT_NO_BROKER` is set. A test setup
  sets it so any forgotten mock fails fast instead of hitting the broker. Defense in depth:
  dev/test use Alpaca **paper** keys. All Alpaca calls are mocked in unit tests.
- **Deterministic kill button.** The `panic` function is LLM-free; writes its `audit_log` row
  before the broker call and updates it in `finally`.
- **Operational pause.** `bot_config.paused` halts new entries (`daily-check` exits
  `skipped:trading_paused`); the kill-switch is unaffected and keeps protecting an open
  position. This replaces `TRADING_PAUSED` env + `.env` writes.
- **Stale-data guard.** `daily-check` exits `skipped:stale_data` when Alpaca's latest SPY daily
  bar predates today.
- **Audit discipline.** `finish()` calls `updateAuditLog`, which sets `finished_at`,
  `outcome`, and `notes` in a single UPDATE (called in the catch block, since the code
  uses try/catch, not finally). On a crash that never reaches `finish()`, both
  `finished_at` and `outcome` stay null; the row's existence alone records that the run
  started. Outcome strings (`success`, `success:*`, `skipped:*`, `error:*`) are preserved
  for forensic continuity. `dry_run:*` is retained if a paper/dry-run soak mode is kept (§8).

## 6. Database (SQLite → Postgres)

Same three tables with Postgres-native types, plus a new `bot_config`.

- **`regime_state`** — `date DATE PRIMARY KEY`, `spy_close`/`spy_sma200` real,
  `target_state`/`current_state TEXT CHECK(... IN ('LONG','CASH'))`,
  `position_drawdown_pct` real null, `kill_switch_active BOOLEAN NOT NULL DEFAULT false`,
  `kill_switch_fired_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now()`.
  SQLite `INSERT OR REPLACE` → `INSERT … ON CONFLICT(date) DO UPDATE`.
- **`trades`** — `id BIGSERIAL PRIMARY KEY`, `symbol`, `side TEXT CHECK IN ('BUY','SELL')`,
  `qty INTEGER`, `fill_price` real, `fill_time TIMESTAMPTZ`,
  **`broker_order_id`** (renamed from `ibkr_order_id`),
  `reason TEXT CHECK IN ('regime_flip_long','regime_flip_cash','kill_switch','panic_cli')`,
  `created_at TIMESTAMPTZ DEFAULT now()`.
- **`audit_log`** — `id BIGSERIAL PRIMARY KEY`, `script_name`, `started_at TIMESTAMPTZ`,
  `finished_at TIMESTAMPTZ`, `outcome`, `notes`.
- **`bot_config`** — `key TEXT PRIMARY KEY`, `value TEXT NOT NULL`, `updated_at TIMESTAMPTZ
  DEFAULT now()`. Seeded with `paused=false`. Replaces `TRADING_PAUSED`.

Edge Functions connect with the **service-role key** (bypass RLS). RLS is enabled and anon/public
access is denied on all tables (no client-side reads). Bool replaces SQLite's 0/1 integer;
TIMESTAMPTZ replaces ISO-8601 text.

## 7. Config / secrets

Set via `supabase secrets set`:
`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER` (bool), `N8N_WEBHOOK_URL`, `PANIC_TOKEN`,
and strategy params `REGIME_SMA_DAYS`, `KILL_SWITCH_DRAWDOWN_PCT`, `KILL_SWITCH_LOOKBACK_DAYS`,
`BOT_TICKER=UPRO`, `BOT_BENCHMARK=SPY`. `config.ts` validates ranges at function start (same
bounds as `config/settings.py`) and throws on out-of-range. The Supabase service-role key and
DB URL are provided by the Edge Function runtime.

## 8. Testing

- **`regime.ts`** — port the existing pure-function tests 1:1 (bullish/bearish/equality/NaN-SMA/
  kill-switch clear/validation). Highest value, lowest cost.
- **`daily-check`** — flip-to-LONG, flip-to-CASH, no-op/idempotency, paused-honoring,
  stale-data, desync-reconcile, insufficient-buying-power, liquidate-failed. Alpaca + DB mocked.
- **`kill-switch`** — within-threshold, breach→liquidate, no-position, market-closed,
  liquidate-returned-none. Alpaca + DB mocked.
- **`panic`** — auth reject, pause/resume flag write, cancel-orders, liquidate (+ trades row),
  audit row written before broker call.
- **Guard test** — an unmocked Alpaca mutating call throws `BrokerCallBlockedError` under
  `CLAUDE_AGENT_NO_BROKER`.
- **Integration** — one gated smoke test against the Alpaca **paper** account (skipped in agent
  contexts).

A `dry_run`/soak mode (analogous to `DAILY_CHECK_DRY_RUN`) MAY be retained so the live cron can
run end-to-end on the paper account before committing real capital; if kept, its `dry_run:*`
outcome strings carry over. Decided during planning.

## 9. Rollout

1. Tag the current tree **`v1.0`**.
2. Build the TS app in the same repo (`supabase/functions/*`, shared `src/*`); Python
   `backtest/` research stays (repo becomes polyglot).
3. Confirm UPRO is tradeable on Alpaca; rotate the leaked paper keys.
4. **Paper-trade soak** end-to-end (cron live on paper) until the flip + kill-switch are
   observed behaving correctly.
5. Cut to live.
6. Decommission IBKR Gateway, host cron, and SQLite.

## 10. Out of scope (deferred)

- The LLM read-only start/end-of-day advisor/reporter (its own spec).
- Any change to the decision rule, additional signals, or sizing logic.
- Re-running options backtests (KILL verdict stands).
- Tighter intraday cadence is already the chosen kill-switch design, not a follow-up.

## 11. Open items to settle in the plan (not blockers)

- Exact Alpaca data feed (IEX free vs SIP) for daily bars and last trade — IEX is expected to
  suffice for daily bars and a coarse intraday last trade; confirm during planning.
- Whether to keep a `dry_run`/soak mode (§8).
- Precise `pg_cron`→Edge Function invocation mechanism (`pg_net`/HTTP) and auth.
- BUY sizing rounding for a 3× ETF (whole shares; ~99% of account value).
