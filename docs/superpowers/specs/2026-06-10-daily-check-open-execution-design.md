# daily-check post-open execution — design (#256)

**Date:** 2026-06-10
**Issue:** #256 — daily-check cannot execute trades in live: post-close market orders time out (30s poll) and get cancelled
**Status:** approved by operator 2026-06-10 (approach C of the three sketched in #256)

## Problem

`daily-check` computes its signal post-close (cron `30 22 * * 1-5` UTC) and immediately submits a
`market`/`day` order via `placeMarketOrder`, which polls 30s for a fill and then cancels + throws
`OrderTimeoutError`. A market order placed while the market is closed cannot fill — Alpaca queues
it for the next open — so every regime flip fails. Confirmed in the paper soak on 2026-06-09: the
first real flip attempt (BUY 7212 UPRO) ended `error:OrderTimeoutError`, and it will recur nightly
because the error path does not advance `regime_state`. The soak also established that Alpaca
**paper queues outside-hours orders exactly like live** — no paper/live false positive.

## Decision

Move the whole `daily-check` run to just after the US market open. The signal — SPY's most recent
**completed** daily close vs its 200-DMA — is unchanged: computing it at 13:37 UTC on yesterday's
bar uses the identical information set the 22:30 run had the evening before. Execution then happens
during regular hours, so the existing place-order/poll-fill/record-trade single-phase model is
preserved untouched.

This is exactly what the strategy backtest models: *"Execution at next day's open after the
signal"* with 0.05% slippage + 0.05% commission per side
(`docs/research/2026-06-05-regime-backtest-pl-winrate.md`). The old same-evening execution attempt
was never the backtested behaviour.

**Alternatives rejected:**
- *`opg` (market-on-open) order from the 22:30 run* — fills at the literal auction print, but
  breaks the "order placed → fill recorded in the same run" contract: needs pending-order state, a
  morning confirm step, and two-phase audit semantics. More machinery for an economically
  irrelevant fidelity gain at this flip frequency.
- *Night compute + separate morning executor* — most moving parts, and it makes persisted
  `target ≠ current` a normal overnight state, weakening the desync signal.

## Design

### 1. Scheduling

New migration `supabase/migrations/0003_daily_check_open_schedule.sql`:

- Unschedule the old `daily-check` job (guarded so the migration is re-runnable when the job is
  already gone — same idempotency bar as #248).
- Schedule two jobs with the same `net.http_post` body as 0002, reusing `_service_role_key()` /
  `_functions_base_url()`:
  - `daily-check-1337` — `37 13 * * 1-5` UTC
  - `daily-check-1437` — `37 14 * * 1-5` UTC

During EDT (US summer; open 13:30 UTC) the 13:37 run executes and the 14:37 run is an idempotent
no-op. During EST (open 14:30 UTC) the 13:37 run exits at the clock gate and the 14:37 run
executes. Market holidays: both exit at the clock gate. The second slot doubles as a free same-day
retry if the first run failed on a transient error (its `error:*` audit row stays for forensics;
the 14:37 run recomputes from scratch).

**Why :37:** the kill-switch cron runs on the `*/5` grid (:35, :40). Keeping daily-check off that
grid means its fill and `regime_state` write (seconds apart) complete between kill-switch ticks,
closing the race described in §4.

### 2. Clock gate

At the top of `runDailyCheck` (after the audit row and the `paused` check), call the broker clock
and exit when the market is not open:

- New dep: `alpaca.getClock` (already exists on the client; kill-switch uses the same gate).
- New deterministic outcome string: `skipped:market_closed`.

Order of operations becomes: audit row → `paused` check → **clock gate** → bars + staleness guard →
compute → broker reconcile → trade → `regime_state` upsert → finish. Everything after the gate is
unchanged.

### 3. Signal input: completed bars only

During market hours Alpaca's daily-bars endpoint can include today's **in-progress** bar. Before
any use, drop it:

```ts
const bars = barsArr.filter((b) => b.date < ymd(deps.now()));
```

The SMA and `spyClose` are then computed from completed bars only, with yesterday's close as the
latest. (At 13:37/14:37 UTC, the UTC date equals the US-Eastern date, so `ymd(now)` is a safe
"today" for this comparison.)

### 4. Stale-data guard, reworked

Old guard: `lastBar.date < today → skipped:stale_data` (run post-close, expect today's bar).
New guard: the last completed bar must be **the most recent trading day strictly before today**:

- New read-only helper `getCalendar(start, end)` in `supabase/functions/_shared/alpaca.ts`
  wrapping Alpaca `GET /v2/calendar` (read-only — no `checkGuard`, like `getClock`). Returns the
  session dates in range as `string[]` of `YYYY-MM-DD` (the response objects' `date` field; the
  open/close times are not needed).
- In `runDailyCheck`: fetch the calendar for `[today − 10 days, today]`, take the latest session
  date strictly before `ymd(now)` as `prevTradingDay`, and require
  `lastBar.date === prevTradingDay`, else `skipped:stale_data` (notes include both dates).

This stays correct across holidays and long weekends, and still catches genuine feed staleness
(yesterday's bar missing → skip, exactly as the old guard intended). Calendar dates from Alpaca
are US-Eastern session dates; per §3 the UTC/ET date alignment at run time makes the comparison
safe.

### 5. State and audit semantics

- `regime_state.date` stays `ymd(now)` — the run/trading day, one row per weekday run, idempotent
  re-runs upsert the same row. **Semantic shift:** `spy_close` / `spy_sma200` in that row now hold
  the *previous trading day's* values (the signal bar). No schema change; documented in CLAUDE.md
  and README.
- All existing outcome strings survive; `skipped:market_closed` is added.
- Fill recording, `trades` insert, `notifyRegimeFlip`, desync reconciliation, and the error paths
  are untouched.
- Kill-switch: no changes. It sources the position from the broker, so the morning flip is
  protected from the first tick after the fill. The only theoretical artifact is a spurious
  `notifyStateDesync` if a kill-switch tick landed between fill and `regime_state` write — the :37
  offset makes that window practically unhittable, and the worst case is one harmless
  notification, never a trading action.

### 6. Out of scope

- `panic` invoked outside market hours still hits the 30s timeout on `cancel-orders`/`liquidate`
  market orders. Documented limitation (operator-timed; retry during RTH); revisit alongside #185
  if it becomes a real incident-path concern.
- No strategy change of any kind (that is #255). `computeTargetState`, `regime.ts`, sizing, and
  the kill-switch rule are untouched.

## Change inventory

| File | Change |
|---|---|
| `supabase/migrations/0003_daily_check_open_schedule.sql` | new — unschedule `daily-check`, schedule `daily-check-1337` + `daily-check-1437` |
| `supabase/functions/_shared/alpaca.ts` | add read-only `getCalendar` |
| `supabase/functions/daily-check/logic.ts` | clock gate, completed-bars filter, calendar-based staleness guard, new deps (`getClock`, `getCalendar`) |
| `supabase/functions/daily-check/*.test.ts` | new/updated tests (see below) |
| `CLAUDE.md`, `README.md`, `docs/runbooks/mvp2-deploy-and-decommission.md`, `CURRENT_CONFIG` | "post-close" doctrine → "post-open on the previous completed bar"; cron times; outcome list |

Deploy after merge: `supabase db push` (0003) + `supabase functions deploy daily-check` on **dev**
first; prod picks it up at go-live (#230).

## Testing & acceptance

Unit tests (Alpaca/DB mocked via the `deps` object, as per testing conventions):

1. Market closed → `skipped:market_closed`, no broker mutation, audit row finished.
2. Today's partial bar present in the feed → excluded from SMA and `spyClose`.
3. Staleness: last bar == previous trading day (incl. a holiday-gap calendar) → proceeds; last bar
   older (missing yesterday) → `skipped:stale_data`.
4. Flip CASH→LONG during market hours → order placed, fill recorded, `trades` row, `regime_state`
   advanced, `success`.
5. Second run same day (target == current) → no-op `success`, same `regime_state` row upserted.
6. Existing tests for paused / desync / error paths updated for the new deps, still green.

**Acceptance criterion for closing #256** (verifies the exact sequence that failed on 2026-06-09):
on the dev paper soak, with SPY above its 200-DMA and the account flat, the next morning run buys
UPRO — `trades` row written, `regime_state` advanced to LONG, audit `success` — visible on the
dashboard. Until then the nightly failure simply stops occurring once the new schedule is pushed.

## References

- #256 (this fix), #248 (idempotent cron pattern), #229 (soak that surfaced it), #230 (go-live
  blocker), #255 (strategy direction — independent)
- `docs/research/2026-06-05-regime-backtest-pl-winrate.md` — next-open execution assumption
- `supabase/migrations/0002_schedule.sql` — cron/Vault invocation pattern being extended
