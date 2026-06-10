# daily-check Post-Open Execution Implementation Plan (#256)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `daily-check` from post-close (22:30 UTC, where its market orders can never fill) to just after the US open, per the approved spec `docs/superpowers/specs/2026-06-10-daily-check-open-execution-design.md`.

**Architecture:** The signal (SPY's last *completed* close vs 200-DMA) is unchanged — it is now computed the morning after the bar completes instead of the evening of. Three code changes: a read-only `getCalendar` broker helper, a market-open clock gate in `runDailyCheck`, and a completed-bars filter + calendar-aware staleness guard. One new migration replaces the 22:30 cron with clock-gated 13:37 + 14:37 UTC slots (DST handling, same pattern as kill-switch).

**Tech Stack:** TypeScript on Deno (Supabase Edge Functions), `Deno.test` + `@std/assert` with dependency-injected mocks, pg_cron SQL migrations.

**Worktree/branch:** `/Users/TM/Desktop/github/trading-bot-256`, branch `fix/256-daily-check-open-execution` (spec already committed there). All paths below are relative to that worktree root. Run everything from the worktree root.

**Safety:** Tests must pass with `CLAUDE_AGENT_NO_BROKER=1` exported in your shell — all broker calls in these tests are mocked via the `deps` object or `stubFetch`, so the guard must never trip. If a test trips `BrokerCallBlockedError`, you forgot a mock; fix the mock, never unset the var.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `supabase/functions/_shared/alpaca.ts` | Broker REST client | add read-only `getCalendar(start, end)` |
| `supabase/functions/_shared/alpaca.test.ts` | Client unit tests | 2 new tests |
| `supabase/functions/daily-check/logic.ts` | Pure orchestration (deps-injected) | clock gate; completed-bars filter; calendar staleness guard; 2 new deps |
| `supabase/functions/daily-check/logic.test.ts` | Logic unit tests | harness date rework + 4 new tests |
| `supabase/functions/daily-check/index.ts` | HTTP entry, real deps wiring | wire `getClock` + `getCalendar` |
| `supabase/migrations/0005_daily_check_open_schedule.sql` | Cron re-schedule | new file |
| `CLAUDE.md`, `README.md`, `docs/CURRENT_CONFIG.md`, `docs/runbooks/mvp2-deploy-and-decommission.md` | Docs | post-close → post-open doctrine |

Files NOT to touch: `kill-switch/*`, `panic/*`, `regime.ts`, `db.ts`, migrations 0001–0004, anything under `docs/superpowers/specs/` other than reading, and historical docs (`docs/operations/ibkr-vps-setup.md` describes the retired IBKR system — its 22:30 references are historical record, leave them).

---

### Task 1: `getCalendar` read-only helper in the Alpaca client

**Files:**
- Modify: `supabase/functions/_shared/alpaca.ts`
- Test: `supabase/functions/_shared/alpaca.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `supabase/functions/_shared/alpaca.test.ts` (after the `getClock maps is_open` test; `setKeys`/`clearKeys`/`stubFetch`/`jsonResponse`/`urlOf`/`assertRejects` are already imported/defined in this file):

```ts
Deno.test("getCalendar returns session dates in range", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/calendar?start=2026-06-01&end=2026-06-05"), true);
    return Promise.resolve(jsonResponse([
      { date: "2026-06-01", open: "09:30", close: "16:00" },
      { date: "2026-06-02", open: "09:30", close: "16:00" },
      { date: "2026-06-04", open: "09:30", close: "16:00" },
      { date: "2026-06-05", open: "09:30", close: "16:00" },
    ]));
  });
  try {
    assertEquals(await createAlpacaClient().getCalendar("2026-06-01", "2026-06-05"), [
      "2026-06-01",
      "2026-06-02",
      "2026-06-04",
      "2026-06-05",
    ]);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getCalendar throws AlpacaError on non-ok response", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "boom" }, 500)));
  try {
    await assertRejects(
      () => createAlpacaClient().getCalendar("2026-06-01", "2026-06-05"),
      AlpacaError,
    );
  } finally {
    restore();
    clearKeys();
  }
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `deno test --allow-env --allow-net supabase/functions/_shared/alpaca.test.ts`
Expected: type-check FAILS (`TS2339: Property 'getCalendar' does not exist on type 'AlpacaClient'`) — the whole file refuses to run until Step 3 lands. That is the red state.

- [ ] **Step 3: Implement `getCalendar`**

In `supabase/functions/_shared/alpaca.ts`, add to the `AlpacaClient` interface (after `getClock`):

```ts
  /** US trading-session dates (YYYY-MM-DD) in [start, end], oldest-first. */
  getCalendar(start: string, end: string): Promise<string[]>;
```

Add the implementation inside `createAlpacaClient()` (after the `getClock` function). Read-only like `getClock` — no `checkGuard`. The response is a JSON *array*, so use `trade()` directly (`tradeJson` returns a single object):

```ts
  async function getCalendar(start: string, end: string): Promise<string[]> {
    const res = await trade(`/v2/calendar?start=${start}&end=${end}`);
    if (!res.ok) {
      throw new AlpacaError(`GET calendar -> ${res.status}: ${await res.text()}`);
    }
    const arr = await res.json();
    if (!Array.isArray(arr)) {
      throw new AlpacaError("GET calendar -> unexpected non-array body");
    }
    return arr.map((e) => String((e as { date: unknown }).date));
  }
```

Add `getCalendar` to the returned object (last line of `createAlpacaClient`):

```ts
  return { getClock, getCalendar, getAccountValue, getPosition, placeMarketOrder, liquidate, cancelAllOrders };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `deno test --allow-env --allow-net supabase/functions/_shared/alpaca.test.ts`
Expected: ALL tests PASS (the 2 new ones plus all pre-existing).

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/_shared/alpaca.ts supabase/functions/_shared/alpaca.test.ts
git commit -m "feat(alpaca): add read-only getCalendar helper (#256)"
```

---

### Task 2: market-open clock gate in daily-check

**Files:**
- Modify: `supabase/functions/daily-check/logic.ts`
- Modify: `supabase/functions/daily-check/index.ts`
- Test: `supabase/functions/daily-check/logic.test.ts`

- [ ] **Step 1: Add `getClock` to the test harness and write the failing test**

In `supabase/functions/daily-check/logic.test.ts`, add a `getClock` default to `defaultAlpaca` in `makeDeps` (first property, before `getPosition`):

```ts
    getClock: () => Promise.resolve({ isOpen: true }),
```

Append the new test at the end of the file:

```ts
Deno.test("market closed -> skipped:market_closed, no broker mutation, no state write (#256)", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { getClock: () => Promise.resolve({ isOpen: false }) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:market_closed");
  assertEquals(calls.placeMarketOrder, undefined);
  assertEquals(calls.upsert, undefined);
});
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `deno test --allow-env --allow-net supabase/functions/daily-check/logic.test.ts`
Expected: type-check FAILS (excess property `getClock` on the `DailyCheckDeps["alpaca"]` literal). After adding only the dep type from Step 3, the new test fails properly with outcome `"success"` ≠ `"skipped:market_closed"` until the gate is implemented.

- [ ] **Step 3: Implement the gate**

In `supabase/functions/daily-check/logic.ts`, add to `DailyCheckDeps.alpaca` (first member, before `getPosition`):

```ts
    getClock: () => Promise<{ isOpen: boolean }>;
```

In `runDailyCheck`, insert directly after the `paused` block (after its closing `}` and before the `getDailyCloses` call):

```ts
    // Post-open execution (#256): the cron fires at 13:37 and 14:37 UTC
    // year-round; the off-season slot, weekends-after-holiday edge cases, and
    // market holidays all exit here. Same gate pattern as kill-switch.
    if (!(await alpaca.getClock()).isOpen) {
      await finish("skipped:market_closed");
      return "skipped:market_closed";
    }
```

In `supabase/functions/daily-check/index.ts`, add to the `alpaca` block of `buildDeps()` (before `getPosition`):

```ts
      getClock: () => alpaca.getClock(),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `deno test --allow-env --allow-net supabase/functions/daily-check/logic.test.ts`
Expected: ALL tests PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/daily-check/logic.ts supabase/functions/daily-check/logic.test.ts supabase/functions/daily-check/index.ts
git commit -m "feat(daily-check): gate runs on market-open clock (#256)"
```

---

### Task 3: completed-bars filter + calendar-aware staleness guard

This task moves the test clock from evening to morning and the bar fixtures from "ends today" to "ends yesterday" — the new reality. All existing assertions keep passing because the *signal values* are unchanged.

**Files:**
- Modify: `supabase/functions/daily-check/logic.ts`
- Modify: `supabase/functions/daily-check/index.ts`
- Test: `supabase/functions/daily-check/logic.test.ts`

- [ ] **Step 1: Rework the test harness dates**

In `supabase/functions/daily-check/logic.test.ts`:

(a) Replace the `bars` helper (dates now end **2026-06-04**, the last completed session relative to the new test clock):

```ts
function bars(closes: number[]): DailyBar[] {
  // oldest-first; dates ascending ending 2026-06-04 — the most recent
  // COMPLETED session relative to the test clock (2026-06-05 13:37 UTC).
  return closes.map((c, i) => ({
    date: new Date(Date.UTC(2026, 5, 4) - (closes.length - 1 - i) * 86400000).toISOString().slice(0, 10),
    close: c,
    high: c,
  }));
}
```

(b) In `makeDeps`, change the clock from `22, 30` to `13, 37`:

```ts
    now: () => new Date(Date.UTC(2026, 5, 5, 13, 37)),
```

(c) In `makeDeps`'s `defaultAlpaca`, add a calendar default directly after `getClock` (note it includes *today*, 2026-06-05 — the logic must pick the latest session *strictly before* today, i.e. 2026-06-04):

```ts
    getCalendar: () => Promise.resolve(["2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]),
```

(d) The existing `"stale data -> skipped:stale_data"` test maps all bar dates to `"2026-06-03"` — under the new guard that is still stale (last bar 2026-06-03 ≠ previous session 2026-06-04). Leave it as-is.

- [ ] **Step 2: Add the three new tests**

Append at the end of `logic.test.ts`:

```ts
Deno.test("today's in-progress bar is excluded from the signal (#256)", async () => {
  // Feed ends with a partial bar dated today whose close would poison the SMA
  // and trip the staleness guard if it were used. It must be dropped first.
  const withPartial = [...bars([390, 400, 410]), { date: "2026-06-05", close: 1, high: 1 }];
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(withPartial),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  // Signal used yesterday's completed close (410), not the partial bar.
  assertEquals((calls.upsert as { spyClose: number }).spyClose, 410);
  assertEquals((calls.placeMarketOrder as { side: string }).side, "BUY");
});

Deno.test("holiday gap: feed ends on the previous SESSION, not previous day -> proceeds (#256)", async () => {
  // 2026-06-04 is a holiday per the calendar; the most recent session before
  // today is 2026-06-03 and the feed ends there. Not stale.
  const holidayBars = [
    { date: "2026-06-01", close: 390, high: 390 },
    { date: "2026-06-02", close: 400, high: 400 },
    { date: "2026-06-03", close: 410, high: 410 },
  ];
  const { deps } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(holidayBars),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
    alpaca: {
      getCalendar: () => Promise.resolve(["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-05"]),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
});

Deno.test("yesterday's bar missing from the feed -> skipped:stale_data (#256)", async () => {
  // Default calendar says the most recent session before today is 2026-06-04,
  // but the feed ends 2026-06-03: genuine staleness, do not trade.
  const staleBars = [
    { date: "2026-06-01", close: 390, high: 390 },
    { date: "2026-06-02", close: 400, high: 400 },
    { date: "2026-06-03", close: 410, high: 410 },
  ];
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(staleBars) } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
  assertEquals(calls.placeMarketOrder, undefined);
});
```

- [ ] **Step 3: Run tests to verify the new ones fail**

Run: `deno test --allow-env --allow-net supabase/functions/daily-check/logic.test.ts`
Expected: type-check FAILS (excess property `getCalendar` on the `DailyCheckDeps["alpaca"]` literal). After adding only the dep type from Step 4(a), the bullish-path tests fail on the old guard (`lastBar.date < today` → bars ending 2026-06-04 read as "stale"). This confirms the harness now exercises the new reality.

- [ ] **Step 4: Implement filter + guard**

In `supabase/functions/daily-check/logic.ts`:

(a) Add to `DailyCheckDeps.alpaca` (after `getClock`):

```ts
    getCalendar: (start: string, end: string) => Promise<string[]>;
```

(b) Replace this block in `runDailyCheck` (the fetch + old guard, currently right after the clock gate added in Task 2):

```ts
    const barsArr = await marketdata.getDailyCloses(config.botBenchmark, config.regimeSmaDays + 10);
    if (barsArr.length === 0) {
      await finish("skipped:stale_data", "no bars returned");
      return "skipped:stale_data";
    }
    const lastBar = barsArr[barsArr.length - 1];
    if (lastBar.date < ymd(deps.now())) {
      await finish("skipped:stale_data", `last bar=${lastBar.date}, today=${ymd(deps.now())}`);
      return "skipped:stale_data";
    }
```

with:

```ts
    const barsRaw = await marketdata.getDailyCloses(config.botBenchmark, config.regimeSmaDays + 10);
    // The daily-bars feed can include today's in-progress bar during market
    // hours; the signal must only ever see completed sessions (#256).
    const today = ymd(deps.now());
    const barsArr = barsRaw.filter((b) => b.date < today);
    if (barsArr.length === 0) {
      await finish("skipped:stale_data", "no completed bars returned");
      return "skipped:stale_data";
    }
    const lastBar = barsArr[barsArr.length - 1];
    // Staleness: the last completed bar must be the most recent trading day
    // strictly before today (calendar-aware: holidays, long weekends). At
    // 13:37/14:37 UTC the UTC date equals the US-Eastern session date, so
    // `today` bounds both the filter above and the calendar query.
    const calStart = new Date(deps.now().getTime() - 10 * 86400000).toISOString().slice(0, 10);
    const sessions = await alpaca.getCalendar(calStart, today);
    const prevTradingDay = sessions.filter((d) => d < today).pop();
    if (!prevTradingDay || lastBar.date !== prevTradingDay) {
      await finish(
        "skipped:stale_data",
        `last bar=${lastBar.date}, prev trading day=${prevTradingDay ?? "none"}`,
      );
      return "skipped:stale_data";
    }
```

The lines that follow (`const closes = barsArr.map(...)` etc.) are unchanged — they now operate on completed bars only.

(c) In `supabase/functions/daily-check/index.ts`, add to the `alpaca` block (after `getClock`):

```ts
      getCalendar: (s, e) => alpaca.getCalendar(s, e),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `deno test --allow-env --allow-net supabase/functions/daily-check/logic.test.ts`
Expected: ALL 17 tests PASS (13 pre-existing + 1 from Task 2 + 3 new).

- [ ] **Step 6: Run the full suite**

Run: `deno task test`
Expected: ALL tests PASS across the repo (kill-switch, panic, shared modules untouched but verify).

- [ ] **Step 7: Commit**

```bash
git add supabase/functions/daily-check/logic.ts supabase/functions/daily-check/logic.test.ts supabase/functions/daily-check/index.ts
git commit -m "feat(daily-check): signal on last completed bar with calendar staleness guard (#256)"
```

---

### Task 4: migration 0005 — post-open cron slots

**Files:**
- Create: `supabase/migrations/0005_daily_check_open_schedule.sql`

No automated test (no CI; pg_cron is not available in the local Deno test setup — `deno task test:db` covers tables, not cron). Verification is review against 0004's pattern plus `supabase db push` at deploy time.

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/0005_daily_check_open_schedule.sql` with exactly:

```sql
-- #256: daily-check moves from post-close (22:30 UTC, where market/day orders
-- can never fill) to post-open. Two slots cover US DST without code changes:
-- during EDT (open 13:30 UTC) the 13:37 run executes and the 14:37 run is an
-- idempotent no-op; during EST (open 14:30 UTC) the 13:37 run exits at the
-- function's clock gate and the 14:37 run executes. Market holidays: both exit
-- at the gate. :37 keeps daily-check off the kill-switch's */5 grid so the
-- fill + regime_state write land between kill-switch ticks. The job bodies
-- reuse the Vault helpers from 0002 (_functions_base_url / _service_role_key).

-- Re-runnable (same idempotency bar as 0004 / #248): drop whichever of the
-- old and new jobs exist before (re)scheduling.
do $$
begin
  if exists (select 1 from cron.job where jobname = 'daily-check') then
    perform cron.unschedule('daily-check');
  end if;
  if exists (select 1 from cron.job where jobname = 'daily-check-1337') then
    perform cron.unschedule('daily-check-1337');
  end if;
  if exists (select 1 from cron.job where jobname = 'daily-check-1437') then
    perform cron.unschedule('daily-check-1437');
  end if;
end;
$$;

select cron.schedule(
  'daily-check-1337',
  '37 13 * * 1-5',
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

select cron.schedule(
  'daily-check-1437',
  '37 14 * * 1-5',
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
```

- [ ] **Step 2: Review against conventions**

Compare side-by-side with `supabase/migrations/0004_cron_idempotent.sql`: guarded unschedule shape, `cron.schedule` argument order, `net.http_post` body identical (only the job names and cron expressions differ). The kill-switch job is NOT touched by 0005.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/0005_daily_check_open_schedule.sql
git commit -m "feat(cron): reschedule daily-check to post-open 13:37/14:37 UTC slots (#256)"
```

---

### Task 5: docs sweep — post-close doctrine becomes post-open

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `docs/CURRENT_CONFIG.md`, `docs/runbooks/mvp2-deploy-and-decommission.md`

Do NOT touch: `docs/operations/ibkr-vps-setup.md` (retired system, historical), anything under `docs/superpowers/specs/` or `docs/plans/` (point-in-time records), `0002`/`0004` migration comments (historical).

- [ ] **Step 1: Find every live reference**

Run: `grep -rn "30 22 \* \* 1-5\|22:30\|post-US-close\|post-close" CLAUDE.md README.md docs/CURRENT_CONFIG.md docs/runbooks/mvp2-deploy-and-decommission.md`

- [ ] **Step 2: Update each hit**

Replace the old schedule/doctrine with the new one. Canonical wording (adapt grammar to each location, keep each doc's voice):

- Schedule: `daily-check` runs post-open — pg_cron `37 13 * * 1-5` **and** `37 14 * * 1-5` UTC; the function calls Alpaca `/v2/clock` and exits `skipped:market_closed` unless the US market is open, so exactly one slot executes per trading day (13:37 during EDT, 14:37 during EST) and the other is an idempotent no-op; holidays skip entirely.
- Signal doctrine: the signal uses the **previous completed trading day's** SPY close vs its 200-DMA (same information set as the old post-close run; execution at the next open is what the backtest models). The `regime_state` row for a given date carries the previous session's `spy_close`/`spy_sma200`.
- Stale-data guard: if the last completed SPY bar does not match the most recent trading day from Alpaca's calendar, the run exits `skipped:stale_data`.

In `CLAUDE.md` specifically: the Commands comment block, the "Daily flow" paragraph in Architecture, and the two "Key constraints" bullets (post-close timing + stale-data guard; the idempotency bullet stays true as written). Add `skipped:market_closed` wherever outcome strings are enumerated for daily-check.

- [ ] **Step 3: Verify no live references remain**

Run: `grep -rn "30 22 \* \* 1-5" CLAUDE.md README.md docs/CURRENT_CONFIG.md docs/runbooks/`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md docs/CURRENT_CONFIG.md docs/runbooks/mvp2-deploy-and-decommission.md
git commit -m "docs: daily-check post-open schedule and previous-close signal doctrine (#256)"
```

---

### Task 6: full verification

- [ ] **Step 1: Full test suite**

Run: `deno task test`
Expected: ALL PASS.

- [ ] **Step 2: Lint**

Run: `deno lint`
Expected: no problems. (Do NOT run `deno fmt` — the repo is not fmt-clean and has no fmt gate.)

- [ ] **Step 3: Spec cross-check**

Re-read `docs/superpowers/specs/2026-06-10-daily-check-open-execution-design.md` §§1–5 and confirm each maps to a landed commit (gate→Task 2, bars/guard→Tasks 1+3, cron→Task 4, docs→Task 5). Confirm `kill-switch/`, `panic/`, `regime.ts` have no diff: `git diff main --stat -- supabase/functions/kill-switch supabase/functions/panic supabase/functions/_shared/regime.ts` → empty.

---

## After the plan (Team Leader, not a plan task)

- `superpowers:finishing-a-development-branch` → PR referencing #256, lead-gated merge.
- Deploy to **dev**: `supabase db push` (applies 0005) + `supabase functions deploy daily-check`. Confirm in the dashboard/SQL editor that `cron.job` now lists `daily-check-1337`/`daily-check-1437` and no `daily-check`.
- Acceptance (closes #256): next trading morning on the dev paper soak, with SPY > 200-DMA and the account flat — `trades` row written, `regime_state` advanced to LONG, audit `success`. The off-slot run shows `skipped:market_closed`.
