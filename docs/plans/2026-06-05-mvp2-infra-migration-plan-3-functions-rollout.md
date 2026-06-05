# MVP 2.0 Infra Migration — Plan 3: Edge Functions, Scheduling & Rollout

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compose the Plan 2 modules into the three Edge Functions (`daily-check`, `kill-switch`, `panic`), schedule them with `pg_cron`, and run the paper-soak → cut-live → decommission rollout.

**Architecture:** Each function splits into a pure-ish `logic.ts` that takes injected dependencies (so it is unit-testable with fakes — no live broker, no DB) and a thin `index.ts` that wires the real Alpaca/Supabase/market-data deps into `Deno.serve`. `pg_cron` + `pg_net` POST to the function URLs on schedule. The deterministic kill button is the token-authenticated `panic` function.

**Tech Stack:** Deno, TypeScript, Supabase Edge Functions, `pg_cron` + `pg_net`, Alpaca REST.

**Spec:** `docs/superpowers/specs/2026-06-05-mvp2-infra-migration-design.md`
**Issue:** [#220](https://github.com/sv-tmueller/trading-bot/issues/220)
**Plan 3 of 3** — depends on Plans 1 (scaffold/schema/regime/config) and 2 (alpaca/marketdata/db/notifications).

**Planning decisions resolved here (spec §11):**
- **No separate dry-run mode.** The paper account *is* the soak mechanism — running the real flow against `paper-api.alpaca.markets` is the dry run. This drops the `dry_run:*` complexity from `daily_check.py`. (Simplicity-first; spec §8 left this open.)
- **Data feed:** IEX (free) for daily bars (post-close, fully sufficient) and latest trade. The IEX latest-trade may lag ~15 min on the free tier; acceptable for a −25% kill-switch threshold. Revisit (SIP, paid) only if soak shows the lag matters.
- **`pg_cron`→Edge invocation:** `net.http_post` with the service-role key in the `Authorization` header, key stored in Supabase Vault.

---

## File Structure

- Create: `supabase/functions/_shared/supabase_client.ts` — `getServiceClient()`.
- Create: `supabase/functions/daily-check/logic.ts` + `logic.test.ts` + `index.ts`.
- Create: `supabase/functions/kill-switch/logic.ts` + `logic.test.ts` + `index.ts`.
- Create: `supabase/functions/panic/logic.ts` + `logic.test.ts` + `index.ts`.
- Create: `supabase/migrations/0002_schedule.sql` — `pg_cron` jobs.
- Create: `docs/runbooks/mvp2-deploy-and-decommission.md` — rollout checklist.
- Modify: `deno.json` test glob to include the function dirs.

**Safety:** The injected-deps design means `logic.test.ts` never constructs a real Alpaca client — fakes are passed in. The real client (with the `CLAUDE_AGENT_NO_BROKER` guard) is only built in `index.ts`, which is not imported by tests.

---

## Task 0: Service client + widen test glob

**Files:**
- Create: `supabase/functions/_shared/supabase_client.ts`
- Modify: `deno.json`

- [ ] **Step 1: Create the service client helper**

Create `supabase/functions/_shared/supabase_client.ts`:

```ts
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are auto-injected into Edge Functions.
export function getServiceClient(): SupabaseClient {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
  return createClient(url, key, { auth: { persistSession: false } });
}
```

- [ ] **Step 2: Widen the test task glob in `deno.json`**

Change the `test` task value to:

```
"test": "deno test --allow-env --allow-net supabase/functions/",
```

(Keep `test:db` as-is.)

- [ ] **Step 3: Verify the suite still runs**

Run: `deno task test`
Expected: PASS — all Plan 1/2 tests still green under the wider glob (db tests still skipped without `RUN_DB_TESTS`).

- [ ] **Step 4: Commit**

```bash
git add supabase/functions/_shared/supabase_client.ts deno.json
git commit -m "chore(mvp2): service client helper + widen test glob (#220)"
```

---

## Task 1: `daily-check` function

> **Post-review amendments (2026-06-05) — these also apply to the Task 2/3 test files (same `makeDeps` pattern):**
> - Partial dep casts must be `as unknown as DailyCheckDeps["db"]` (TS2352 rejects the direct cast).
> - `makeDeps` must merge each partial over a *captured default* (e.g. `{ ...defaultDb, ...over.db }`),
>   not re-spread `over` (the `...over` spread already replaced the nested object, making a re-merge a no-op).
> - Assertions on the captured `upsertRegimeState` arg use **camelCase** keys (`currentState`, `spyClose`, …),
>   matching the `DailyCheckDeps` interface — not snake_case.
> - Two extra assertions were added: desync test asserts `upsert.currentState === "LONG"` (reconciled state
>   persisted); liquidate-failed test asserts `calls.upsert === undefined` (current_state pinned, no row written).
> The committed files are the source of truth.

**Files:**
- Create: `supabase/functions/daily-check/logic.test.ts`
- Create: `supabase/functions/daily-check/logic.ts`
- Create: `supabase/functions/daily-check/index.ts`

- [ ] **Step 1: Write the failing tests**

Create `supabase/functions/daily-check/logic.test.ts`:

```ts
import { assertEquals } from "@std/assert";
import { runDailyCheck } from "./logic.ts";
import type { DailyCheckDeps } from "./logic.ts";
import type { DailyBar } from "../_shared/marketdata.ts";

function bars(closes: number[]): DailyBar[] {
  // oldest-first; dates ascending ending "today" 2026-06-05
  return closes.map((c, i) => ({
    date: new Date(Date.UTC(2026, 5, 5) - (closes.length - 1 - i) * 86400000).toISOString().slice(0, 10),
    close: c,
    high: c,
  }));
}

function makeDeps(over: Partial<DailyCheckDeps> = {}): { deps: DailyCheckDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const deps: DailyCheckDeps = {
    config: {
      regimeSmaDays: 3,
      killSwitchDrawdownPct: 0.25,
      killSwitchLookbackDays: 30,
      botTicker: "UPRO",
      botBenchmark: "SPY",
    },
    now: () => new Date(Date.UTC(2026, 5, 5, 22, 30)),
    marketdata: {
      // default: bullish (last close 410 > sma of [390,400,410]=400)
      getDailyCloses: () => Promise.resolve(bars([390, 400, 410])),
      getLatestTradePrice: () => Promise.resolve(70),
    },
    alpaca: {
      getPosition: () => Promise.resolve(0),
      getAccountValue: () => Promise.resolve(7000),
      placeMarketOrder: (a) => {
        calls.placeMarketOrder = a;
        return Promise.resolve({ orderId: "o1", fillPrice: 70, qty: a.qty, fillTime: "t" });
      },
      liquidate: () => {
        calls.liquidate = true;
        return Promise.resolve({ orderId: "o2", fillPrice: 70, qty: 100, fillTime: "t" });
      },
    },
    db: {
      getConfig: () => Promise.resolve("false"),
      getLatestRegimeState: () => Promise.resolve(null),
      upsertRegimeState: (p) => {
        calls.upsert = p;
        return Promise.resolve();
      },
      insertTrade: (p) => {
        calls.insertTrade = p;
        return Promise.resolve(1);
      },
      insertAuditLog: () => Promise.resolve(42),
      updateAuditLog: (p) => {
        calls.audit = p;
        return Promise.resolve();
      },
    },
    notifications: {
      notifyRegimeFlip: () => Promise.resolve(),
      notifyStateDesync: () => {
        calls.desync = true;
        return Promise.resolve();
      },
      notifyTradeFailed: () => {
        calls.tradeFailed = true;
        return Promise.resolve();
      },
      notifyBrokerError: () => Promise.resolve(),
    },
    ...over,
  };
  // shallow-merge nested objects when overridden
  if (over.marketdata) deps.marketdata = { ...deps.marketdata, ...over.marketdata };
  if (over.alpaca) deps.alpaca = { ...deps.alpaca, ...over.alpaca };
  if (over.db) deps.db = { ...deps.db, ...over.db };
  return { deps, calls };
}

Deno.test("paused -> skipped:trading_paused, no broker", async () => {
  const { deps, calls } = makeDeps({ db: { getConfig: () => Promise.resolve("true") } as DailyCheckDeps["db"] });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "skipped:trading_paused");
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("stale data -> skipped:stale_data", async () => {
  const { deps } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([390, 400, 410]).map((b) => ({ ...b, date: "2026-06-03" }))) } as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
});

Deno.test("bullish from CASH -> BUY and success", async () => {
  const { deps, calls } = makeDeps();
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals((calls.placeMarketOrder as { side: string }).side, "BUY");
  // 7000*0.99/70 = 99 shares
  assertEquals((calls.placeMarketOrder as { qty: number }).qty, 99);
  assertEquals((calls.insertTrade as { reason: string }).reason, "regime_flip_long");
  assertEquals((calls.upsert as { current_state: string }).current_state, "LONG");
});

Deno.test("no flip needed -> success, idempotent no-op", async () => {
  const { deps, calls } = makeDeps({
    db: { getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never) } as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.placeMarketOrder, undefined);
  assertEquals((calls.upsert as { current_state: string }).current_state, "LONG");
});

Deno.test("bearish from LONG -> liquidate to CASH", async () => {
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([410, 400, 390])), getLatestTradePrice: () => Promise.resolve(70) } as DailyCheckDeps["marketdata"],
    db: { getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never) } as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "regime_flip_cash");
  assertEquals((calls.upsert as { current_state: string }).current_state, "CASH");
});

Deno.test("desync (broker LONG, db CASH) reconciles + notifies", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { getPosition: () => Promise.resolve(99) } as DailyCheckDeps["alpaca"], // broker LONG
    // db has no row -> current CASH; bullish target LONG == broker LONG -> no flip
  });
  await runDailyCheck(deps);
  assertEquals(calls.desync, true);
  assertEquals(calls.placeMarketOrder, undefined); // already LONG after reconcile
});

Deno.test("insufficient buying power -> error:insufficient_funds", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { getAccountValue: () => Promise.resolve(10) } as DailyCheckDeps["alpaca"], // 10*0.99/70 = 0 shares
  });
  assertEquals(await runDailyCheck(deps), "error:insufficient_funds");
  assertEquals(calls.tradeFailed, true);
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("liquidate returns null -> error:liquidate_failed", async () => {
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([410, 400, 390])), getLatestTradePrice: () => Promise.resolve(70) } as DailyCheckDeps["marketdata"],
    db: { getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never) } as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99), liquidate: () => Promise.resolve(null) } as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "error:liquidate_failed");
  assertEquals(calls.tradeFailed, true);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `./logic.ts` not found.

- [ ] **Step 3: Implement the logic**

Create `supabase/functions/daily-check/logic.ts`:

```ts
import { computeTargetState, type State } from "../_shared/regime.ts";
import type { Fill } from "../_shared/alpaca.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";
import type { RegimeStateRow } from "../_shared/db.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export interface DailyCheckDeps {
  config: StrategyConfig;
  now: () => Date;
  marketdata: {
    getDailyCloses: (symbol: string, count: number) => Promise<DailyBar[]>;
    getLatestTradePrice: (symbol: string) => Promise<number>;
  };
  alpaca: {
    getPosition: (symbol: string) => Promise<number>;
    getAccountValue: () => Promise<number>;
    placeMarketOrder: (a: { symbol: string; side: "BUY" | "SELL"; qty: number }) => Promise<Fill>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    getConfig: (key: string) => Promise<string | null>;
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
    upsertRegimeState: (p: {
      date: string;
      spyClose: number;
      spySma200: number;
      targetState: State;
      currentState: State;
      positionDrawdownPct: number | null;
      killSwitchActive: boolean;
      killSwitchFiredAt: string | null;
    }) => Promise<void>;
    insertTrade: (p: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      fillPrice: number;
      fillTime: string;
      brokerOrderId: string;
      reason: "regime_flip_long" | "regime_flip_cash" | "kill_switch" | "panic_cli";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (p: { id: number; finishedAt: string; outcome: string; notes?: string | null }) => Promise<void>;
  };
  notifications: {
    notifyRegimeFlip: (p: {
      targetState: State; spyClose: number; spySma200: number; ticker: string;
      fillPrice: number; qty: number; accountValue: number; dryRun?: boolean;
    }) => Promise<void>;
    notifyStateDesync: (p: { dbState: State; brokerState: State; symbol: string; actionTaken: string }) => Promise<void>;
    notifyTradeFailed: (p: { symbol: string; side: "BUY" | "SELL"; qty: number; reason: string }) => Promise<void>;
    notifyBrokerError: (p: { context: string; errorMsg: string }) => Promise<void>;
  };
}

function sma(closes: number[], n: number): number {
  if (closes.length < n) return NaN;
  const slice = closes.slice(-n);
  return slice.reduce((a, b) => a + b, 0) / n;
}

export async function runDailyCheck(deps: DailyCheckDeps): Promise<string> {
  const { config, db, alpaca, marketdata, notifications } = deps;
  const iso = (d: Date) => d.toISOString();
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const startedAt = iso(deps.now());
  const auditId = await db.insertAuditLog({ scriptName: "daily-check", startedAt });

  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });

  // Operational pause.
  const paused = (await db.getConfig("paused"))?.toLowerCase() === "true";
  if (paused) {
    await finish("skipped:trading_paused", "bot_config.paused is true");
    return "skipped:trading_paused";
  }

  try {
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

    const closes = barsArr.map((b) => b.close);
    const spyClose = lastBar.close;
    const spySma200 = sma(closes, config.regimeSmaDays);

    const latest = await db.getLatestRegimeState();
    let currentState: State = (latest?.current_state as State) ?? "CASH";
    const killSwitchActive = latest?.kill_switch_active ?? false;

    let { targetState, killSwitchActive: newKs } = computeTargetState({
      spyClose, spySma200, currentState, killSwitchActive,
    });

    // Reconcile against broker truth.
    const qty = await alpaca.getPosition(config.botTicker);
    const brokerState: State = qty > 0 ? "LONG" : "CASH";
    if (brokerState !== currentState) {
      await notifications.notifyStateDesync({
        dbState: currentState, brokerState, symbol: config.botTicker,
        actionTaken: `DB updated to ${brokerState}`,
      });
      currentState = brokerState;
      ({ targetState, killSwitchActive: newKs } = computeTargetState({
        spyClose, spySma200, currentState, killSwitchActive,
      }));
    }

    let newCurrentState: State = currentState;
    let outcome = "success";

    if (targetState !== currentState) {
      if (targetState === "LONG") {
        const accountValue = await alpaca.getAccountValue();
        const vehiclePrice = await marketdata.getLatestTradePrice(config.botTicker);
        const targetQty = Math.floor((accountValue * 0.99) / vehiclePrice);
        if (targetQty <= 0) {
          await notifications.notifyTradeFailed({ symbol: config.botTicker, side: "BUY", qty: 0, reason: "insufficient_buying_power" });
          await finish("error:insufficient_funds");
          return "error:insufficient_funds";
        }
        const fill = await alpaca.placeMarketOrder({ symbol: config.botTicker, side: "BUY", qty: targetQty });
        await db.insertTrade({
          symbol: config.botTicker, side: "BUY", qty: fill.qty, fillPrice: fill.fillPrice,
          fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "regime_flip_long",
        });
        await notifications.notifyRegimeFlip({
          targetState: "LONG", spyClose, spySma200, ticker: config.botTicker,
          fillPrice: fill.fillPrice, qty: fill.qty, accountValue,
        });
        newCurrentState = "LONG";
      } else {
        const fill = await alpaca.liquidate(config.botTicker);
        if (fill) {
          await db.insertTrade({
            symbol: config.botTicker, side: "SELL", qty: fill.qty, fillPrice: fill.fillPrice,
            fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "regime_flip_cash",
          });
          await notifications.notifyRegimeFlip({
            targetState: "CASH", spyClose, spySma200, ticker: config.botTicker,
            fillPrice: fill.fillPrice, qty: fill.qty, accountValue: await alpaca.getAccountValue(),
          });
          newCurrentState = "CASH";
        } else {
          await notifications.notifyTradeFailed({ symbol: config.botTicker, side: "SELL", qty, reason: "liquidate_returned_null" });
          await finish("error:liquidate_failed", `liquidate(${config.botTicker}) returned null; current pinned at ${currentState}`);
          return "error:liquidate_failed";
        }
      }
    }

    await db.upsertRegimeState({
      date: ymd(deps.now()), spyClose, spySma200, targetState, currentState: newCurrentState,
      positionDrawdownPct: null, killSwitchActive: newKs,
      killSwitchFiredAt: latest && newKs ? latest.kill_switch_fired_at : null,
    });
    await finish(outcome, `target=${targetState} current=${newCurrentState}`);
    return outcome;
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await deps.notifications.notifyBrokerError({ context: "daily-check", errorMsg: err.message });
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `deno task test`
Expected: PASS — all 8 `daily-check/logic.test.ts` cases green.

- [ ] **Step 5: Create the HTTP wrapper**

Create `supabase/functions/daily-check/index.ts`:

```ts
import { runDailyCheck, type DailyCheckDeps } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getDailyCloses, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  getConfig, getLatestRegimeState, insertAuditLog, insertTrade, updateAuditLog, upsertRegimeState,
} from "../_shared/db.ts";
import {
  notifyBrokerError, notifyRegimeFlip, notifyStateDesync, notifyTradeFailed,
} from "../_shared/notifications.ts";

function buildDeps(): DailyCheckDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return {
    config: getStrategyConfig(),
    now: () => new Date(),
    marketdata: { getDailyCloses, getLatestTradePrice },
    alpaca: {
      getPosition: (s) => alpaca.getPosition(s),
      getAccountValue: () => alpaca.getAccountValue(),
      placeMarketOrder: (a) => alpaca.placeMarketOrder(a),
      liquidate: (s) => alpaca.liquidate(s),
    },
    db: {
      getConfig: (k) => getConfig(sb, k),
      getLatestRegimeState: () => getLatestRegimeState(sb),
      upsertRegimeState: (p) => upsertRegimeState(sb, p),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: { notifyRegimeFlip, notifyStateDesync, notifyTradeFailed, notifyBrokerError },
  };
}

Deno.serve(async () => {
  const outcome = await runDailyCheck(buildDeps());
  return new Response(JSON.stringify({ outcome }), {
    headers: { "content-type": "application/json" },
  });
});
```

- [ ] **Step 6: Commit**

```bash
git add supabase/functions/daily-check/
git commit -m "feat(mvp2): daily-check Edge Function (#220)"
```

---

## Task 2: `kill-switch` function

**Files:**
- Create: `supabase/functions/kill-switch/logic.test.ts`
- Create: `supabase/functions/kill-switch/logic.ts`
- Create: `supabase/functions/kill-switch/index.ts`

- [ ] **Step 1: Write the failing tests**

Create `supabase/functions/kill-switch/logic.test.ts`:

```ts
import { assertEquals } from "@std/assert";
import { runKillSwitch, type KillSwitchDeps } from "./logic.ts";
import type { DailyBar } from "../_shared/marketdata.ts";

function bars(highs: number[]): DailyBar[] {
  return highs.map((h, i) => ({ date: `2026-05-${String(i + 1).padStart(2, "0")}`, close: h, high: h }));
}

function makeDeps(over: Partial<KillSwitchDeps> = {}): { deps: KillSwitchDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const deps: KillSwitchDeps = {
    config: { regimeSmaDays: 200, killSwitchDrawdownPct: 0.25, killSwitchLookbackDays: 5, botTicker: "UPRO", botBenchmark: "SPY" },
    now: () => new Date(Date.UTC(2026, 5, 5, 15, 0)),
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(100),
    },
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: true }),
      liquidate: () => {
        calls.liquidate = true;
        return Promise.resolve({ orderId: "o1", fillPrice: 70, qty: 99, fillTime: "t" });
      },
    },
    db: {
      getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false, spy_close: 400, spy_sma200: 380, target_state: "LONG", kill_switch_fired_at: null } as never),
      upsertRegimeState: (p) => { calls.upsert = p; return Promise.resolve(); },
      insertTrade: (p) => { calls.insertTrade = p; return Promise.resolve(1); },
      insertAuditLog: () => Promise.resolve(7),
      updateAuditLog: (p) => { calls.audit = p; return Promise.resolve(); },
    },
    notifications: {
      notifyKillSwitchFired: () => { calls.fired = true; return Promise.resolve(); },
      notifyTradeFailed: () => Promise.resolve(),
      notifyBrokerError: () => Promise.resolve(),
    },
    ...over,
  };
  if (over.marketdata) deps.marketdata = { ...deps.marketdata, ...over.marketdata };
  if (over.alpaca) deps.alpaca = { ...deps.alpaca, ...over.alpaca };
  if (over.db) deps.db = { ...deps.db, ...over.db };
  return { deps, calls };
}

Deno.test("not LONG -> success:no_position", async () => {
  const { deps } = makeDeps({ db: { getLatestRegimeState: () => Promise.resolve({ current_state: "CASH" } as never) } as KillSwitchDeps["db"] });
  assertEquals(await runKillSwitch(deps), "success:no_position");
});

Deno.test("market closed -> skipped:market_closed", async () => {
  const { deps } = makeDeps({ alpaca: { getClock: () => Promise.resolve({ isOpen: false }) } as KillSwitchDeps["alpaca"] });
  assertEquals(await runKillSwitch(deps), "skipped:market_closed");
});

Deno.test("within threshold -> success:within_threshold, persists drawdown", async () => {
  const { deps, calls } = makeDeps({ marketdata: { getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])), getLatestTradePrice: () => Promise.resolve(90) } as KillSwitchDeps["marketdata"] });
  assertEquals(await runKillSwitch(deps), "success:within_threshold");
  assertEquals(calls.liquidate, undefined);
  // drawdown = 90/100 - 1 = -0.10
  assertEquals(Math.round(((calls.upsert as { positionDrawdownPct: number }).positionDrawdownPct) * 100) / 100, -0.10);
});

Deno.test("breach -> liquidate + success:kill_switch_fired", async () => {
  const { deps, calls } = makeDeps({ marketdata: { getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])), getLatestTradePrice: () => Promise.resolve(70) } as KillSwitchDeps["marketdata"] });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  assertEquals(calls.fired, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "kill_switch");
  assertEquals((calls.upsert as { current_state: string }).current_state, "CASH");
  assertEquals((calls.upsert as { killSwitchActive: boolean }).killSwitchActive, true);
});

Deno.test("breach but position vanished -> success:no_position_to_liquidate", async () => {
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])), getLatestTradePrice: () => Promise.resolve(70) } as KillSwitchDeps["marketdata"],
    alpaca: { getClock: () => Promise.resolve({ isOpen: true }), liquidate: () => Promise.resolve(null) } as KillSwitchDeps["alpaca"],
  });
  assertEquals(await runKillSwitch(deps), "success:no_position_to_liquidate");
  assertEquals((calls.upsert as { current_state: string }).current_state, "CASH");
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `./logic.ts` not found.

- [ ] **Step 3: Implement the logic**

Create `supabase/functions/kill-switch/logic.ts`:

```ts
import type { Fill } from "../_shared/alpaca.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";
import type { RegimeStateRow } from "../_shared/db.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export interface KillSwitchDeps {
  config: StrategyConfig;
  now: () => Date;
  marketdata: {
    getDailyCloses: (symbol: string, count: number) => Promise<DailyBar[]>;
    getLatestTradePrice: (symbol: string) => Promise<number>;
  };
  alpaca: {
    getClock: () => Promise<{ isOpen: boolean }>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
    upsertRegimeState: (p: {
      date: string; spyClose: number; spySma200: number;
      targetState: "LONG" | "CASH"; currentState: "LONG" | "CASH";
      positionDrawdownPct: number | null; killSwitchActive: boolean; killSwitchFiredAt: string | null;
    }) => Promise<void>;
    insertTrade: (p: {
      symbol: string; side: "BUY" | "SELL"; qty: number; fillPrice: number; fillTime: string;
      brokerOrderId: string; reason: "regime_flip_long" | "regime_flip_cash" | "kill_switch" | "panic_cli";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (p: { id: number; finishedAt: string; outcome: string; notes?: string | null }) => Promise<void>;
  };
  notifications: {
    notifyKillSwitchFired: (p: { ticker: string; drawdownPct: number; refHigh: number; lastPrice: number; qty: number; fillPrice: number }) => Promise<void>;
    notifyTradeFailed: (p: { symbol: string; side: "BUY" | "SELL"; qty: number; reason: string }) => Promise<void>;
    notifyBrokerError: (p: { context: string; errorMsg: string }) => Promise<void>;
  };
}

export async function runKillSwitch(deps: KillSwitchDeps): Promise<string> {
  const { config, db, alpaca, marketdata, notifications } = deps;
  const iso = (d: Date) => d.toISOString();
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const auditId = await db.insertAuditLog({ scriptName: "kill-switch", startedAt: iso(deps.now()) });
  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });

  try {
    const latest = await db.getLatestRegimeState();
    if (!latest || latest.current_state !== "LONG") {
      await finish("success:no_position");
      return "success:no_position";
    }

    if (!(await alpaca.getClock()).isOpen) {
      await finish("skipped:market_closed");
      return "skipped:market_closed";
    }

    const barsArr = await marketdata.getDailyCloses(config.botTicker, config.killSwitchLookbackDays + 10);
    if (barsArr.length < config.killSwitchLookbackDays) {
      await finish("skipped:insufficient_data", `only ${barsArr.length} bars, need ${config.killSwitchLookbackDays}`);
      return "skipped:insufficient_data";
    }

    const lastPrice = await marketdata.getLatestTradePrice(config.botTicker);
    const recentHighs = barsArr.slice(-config.killSwitchLookbackDays).map((b) => b.high);
    const refHigh = Math.max(...recentHighs, lastPrice);
    const drawdown = lastPrice / refHigh - 1;

    await db.upsertRegimeState({
      date: ymd(deps.now()), spyClose: latest.spy_close, spySma200: latest.spy_sma200,
      targetState: latest.target_state, currentState: "LONG",
      positionDrawdownPct: drawdown, killSwitchActive: latest.kill_switch_active,
      killSwitchFiredAt: latest.kill_switch_fired_at,
    });

    if (drawdown > -config.killSwitchDrawdownPct) {
      await finish("success:within_threshold", `dd=${drawdown.toFixed(4)}`);
      return "success:within_threshold";
    }

    const fill = await alpaca.liquidate(config.botTicker);
    if (fill === null) {
      await db.upsertRegimeState({
        date: ymd(deps.now()), spyClose: latest.spy_close, spySma200: latest.spy_sma200,
        targetState: "CASH", currentState: "CASH", positionDrawdownPct: drawdown,
        killSwitchActive: true, killSwitchFiredAt: iso(deps.now()),
      });
      await finish("success:no_position_to_liquidate");
      return "success:no_position_to_liquidate";
    }

    await db.insertTrade({
      symbol: config.botTicker, side: "SELL", qty: fill.qty, fillPrice: fill.fillPrice,
      fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "kill_switch",
    });
    await db.upsertRegimeState({
      date: ymd(deps.now()), spyClose: latest.spy_close, spySma200: latest.spy_sma200,
      targetState: "CASH", currentState: "CASH", positionDrawdownPct: drawdown,
      killSwitchActive: true, killSwitchFiredAt: iso(deps.now()),
    });
    await notifications.notifyKillSwitchFired({
      ticker: config.botTicker, drawdownPct: drawdown, refHigh, lastPrice, qty: fill.qty, fillPrice: fill.fillPrice,
    });
    await finish("success:kill_switch_fired", `dd=${drawdown.toFixed(4)}`);
    return "success:kill_switch_fired";
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await notifications.notifyBrokerError({ context: "kill-switch", errorMsg: err.message });
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `deno task test`
Expected: PASS — all `kill-switch/logic.test.ts` cases green.

- [ ] **Step 5: Create the HTTP wrapper**

Create `supabase/functions/kill-switch/index.ts`:

```ts
import { runKillSwitch, type KillSwitchDeps } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getDailyCloses, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { getLatestRegimeState, insertAuditLog, insertTrade, updateAuditLog, upsertRegimeState } from "../_shared/db.ts";
import { notifyBrokerError, notifyKillSwitchFired, notifyTradeFailed } from "../_shared/notifications.ts";

function buildDeps(): KillSwitchDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return {
    config: getStrategyConfig(),
    now: () => new Date(),
    marketdata: { getDailyCloses, getLatestTradePrice },
    alpaca: { getClock: () => alpaca.getClock(), liquidate: (s) => alpaca.liquidate(s) },
    db: {
      getLatestRegimeState: () => getLatestRegimeState(sb),
      upsertRegimeState: (p) => upsertRegimeState(sb, p),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: { notifyKillSwitchFired, notifyTradeFailed, notifyBrokerError },
  };
}

Deno.serve(async () => {
  const outcome = await runKillSwitch(buildDeps());
  return new Response(JSON.stringify({ outcome }), { headers: { "content-type": "application/json" } });
});
```

- [ ] **Step 6: Commit**

```bash
git add supabase/functions/kill-switch/
git commit -m "feat(mvp2): kill-switch Edge Function (5-min intraday) (#220)"
```

---

## Task 3: `panic` function (deterministic kill button)

> **Post-review amendments (2026-06-05):** (1) `logic.ts` closes the audit row (`updateAuditLog`)
> BEFORE calling `notifyPanic`, and wraps `notifyPanic` in its own try/catch — a notification
> failure must not flip a successful action's outcome to error. (2) `index.ts` returns HTTP **500**
> when the result starts with `error:` (so the operator can't mistake a failed liquidation for
> success), 200 otherwise. A test was added: notify-failure-does-not-corrupt-a-successful-outcome.
> Committed files are the source of truth.

**Files:**
- Create: `supabase/functions/panic/logic.test.ts`
- Create: `supabase/functions/panic/logic.ts`
- Create: `supabase/functions/panic/index.ts`

- [ ] **Step 1: Write the failing tests**

Create `supabase/functions/panic/logic.test.ts`:

```ts
import { assertEquals } from "@std/assert";
import { runPanic, type PanicDeps } from "./logic.ts";

function makeDeps(over: Partial<PanicDeps> = {}): { deps: PanicDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const deps: PanicDeps = {
    config: { regimeSmaDays: 200, killSwitchDrawdownPct: 0.25, killSwitchLookbackDays: 30, botTicker: "UPRO", botBenchmark: "SPY" },
    now: () => new Date(Date.UTC(2026, 5, 5, 15, 0)),
    alpaca: {
      cancelAllOrders: () => { calls.cancel = true; return Promise.resolve(3); },
      liquidate: () => { calls.liquidate = true; return Promise.resolve({ orderId: "o1", fillPrice: 70, qty: 99, fillTime: "t" }); },
    },
    db: {
      setConfig: (k, v) => { calls.setConfig = [k, v]; return Promise.resolve(); },
      insertTrade: (p) => { calls.insertTrade = p; return Promise.resolve(1); },
      insertAuditLog: () => Promise.resolve(5),
      updateAuditLog: (p) => { calls.audit = p; return Promise.resolve(); },
    },
    notifications: { notifyPanic: () => { calls.panic = true; return Promise.resolve(); } },
    ...over,
  };
  if (over.alpaca) deps.alpaca = { ...deps.alpaca, ...over.alpaca };
  if (over.db) deps.db = { ...deps.db, ...over.db };
  return { deps, calls };
}

Deno.test("pause sets bot_config.paused=true", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "pause");
  assertEquals(calls.setConfig, ["paused", "true"]);
  assertEquals(r, "paused");
});

Deno.test("resume sets bot_config.paused=false", async () => {
  const { deps, calls } = makeDeps();
  await runPanic(deps, "resume");
  assertEquals(calls.setConfig, ["paused", "false"]);
});

Deno.test("cancel-orders cancels and reports count", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "cancel-orders");
  assertEquals(calls.cancel, true);
  assertEquals(r, "cancelled 3 orders");
});

Deno.test("liquidate sells + writes panic_cli trade", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "liquidate");
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "panic_cli");
  assertEquals(r.includes("liquidated"), true);
});

Deno.test("liquidate with no position reports no position", async () => {
  const { deps, calls } = makeDeps({ alpaca: { liquidate: () => Promise.resolve(null) } as PanicDeps["alpaca"] });
  const r = await runPanic(deps, "liquidate");
  assertEquals(r, "no position to liquidate");
  assertEquals(calls.insertTrade, undefined);
});

Deno.test("unknown action -> error", async () => {
  const { deps } = makeDeps();
  // deno-lint-ignore no-explicit-any
  const r = await runPanic(deps, "boom" as any);
  assertEquals(r.startsWith("error:"), true);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `./logic.ts` not found.

- [ ] **Step 3: Implement the logic**

Create `supabase/functions/panic/logic.ts`:

```ts
import type { Fill } from "../_shared/alpaca.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export type PanicAction = "pause" | "resume" | "cancel-orders" | "liquidate";

export interface PanicDeps {
  config: StrategyConfig;
  now: () => Date;
  alpaca: {
    cancelAllOrders: () => Promise<number>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    setConfig: (key: string, value: string) => Promise<void>;
    insertTrade: (p: {
      symbol: string; side: "BUY" | "SELL"; qty: number; fillPrice: number; fillTime: string;
      brokerOrderId: string; reason: "regime_flip_long" | "regime_flip_cash" | "kill_switch" | "panic_cli";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (p: { id: number; finishedAt: string; outcome: string; notes?: string | null }) => Promise<void>;
  };
  notifications: { notifyPanic: (p: { action: string; result: string }) => Promise<void> };
}

export async function runPanic(deps: PanicDeps, action: PanicAction): Promise<string> {
  const { db, alpaca, config } = deps;
  const iso = (d: Date) => d.toISOString();
  // Audit row is written BEFORE any broker call (recoverable on partial run).
  const auditId = await db.insertAuditLog({ scriptName: "panic", startedAt: iso(deps.now()) });
  let result = "";
  try {
    switch (action) {
      case "pause":
        await db.setConfig("paused", "true");
        result = "paused";
        break;
      case "resume":
        await db.setConfig("paused", "false");
        result = "resumed";
        break;
      case "cancel-orders": {
        const n = await alpaca.cancelAllOrders();
        result = `cancelled ${n} orders`;
        break;
      }
      case "liquidate": {
        const fill = await alpaca.liquidate(config.botTicker);
        if (fill) {
          await db.insertTrade({
            symbol: config.botTicker, side: "SELL", qty: fill.qty, fillPrice: fill.fillPrice,
            fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "panic_cli",
          });
          result = `liquidated ${fill.qty} ${config.botTicker} @ ${fill.fillPrice}`;
        } else {
          result = "no position to liquidate";
        }
        break;
      }
      default:
        throw new Error(`unknown action: ${action}`);
    }
    await deps.notifications.notifyPanic({ action, result });
    await db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome: "success:panic", notes: `${action}: ${result}` });
    return result;
  } catch (e) {
    const err = e as Error;
    const outcome = `error:${err.name}`;
    await db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes: `${action}: ${err.message}`.slice(0, 500) });
    return `${outcome}: ${err.message}`;
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `deno task test`
Expected: PASS — all `panic/logic.test.ts` cases green.

- [ ] **Step 5: Create the token-authed HTTP wrapper**

Create `supabase/functions/panic/index.ts`:

```ts
import { runPanic, type PanicAction } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { insertAuditLog, insertTrade, setConfig, updateAuditLog } from "../_shared/db.ts";
import { notifyPanic } from "../_shared/notifications.ts";

const VALID: PanicAction[] = ["pause", "resume", "cancel-orders", "liquidate"];

Deno.serve(async (req) => {
  const token = req.headers.get("x-panic-token") ?? "";
  const expected = Deno.env.get("PANIC_TOKEN") ?? "";
  if (expected === "" || token !== expected) {
    return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
  }
  const url = new URL(req.url);
  const action = (url.searchParams.get("action") ?? "") as PanicAction;
  if (!VALID.includes(action)) {
    return new Response(JSON.stringify({ error: `action must be one of ${VALID.join("|")}` }), { status: 400 });
  }

  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  const result = await runPanic({
    config: getStrategyConfig(),
    now: () => new Date(),
    alpaca: { cancelAllOrders: () => alpaca.cancelAllOrders(), liquidate: (s) => alpaca.liquidate(s) },
    db: {
      setConfig: (k, v) => setConfig(sb, k, v),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: { notifyPanic },
  }, action);

  return new Response(JSON.stringify({ result }), { headers: { "content-type": "application/json" } });
});
```

- [ ] **Step 6: Commit**

```bash
git add supabase/functions/panic/
git commit -m "feat(mvp2): panic Edge Function (token-auth kill button) (#220)"
```

---

## Task 4: `pg_cron` scheduling migration

> **Post-review amendment (2026-06-05):** the committed `0002_schedule.sql` adds
> `revoke execute on function _service_role_key() from public;` after the helper definition —
> defence in depth so anon/authenticated roles can't invoke the key-retrieval helper (pg_cron runs
> as superuser and is unaffected). Committed file is the source of truth.

**Files:**
- Create: `supabase/migrations/0002_schedule.sql`

The cron jobs `POST` to the deployed function URLs via `pg_net`, authenticating with
the service-role key stored in Vault. The schedules use a wide UTC window; each
function early-exits when the market is closed (`daily-check` via the stale-data
guard, `kill-switch` via `getClock`), so US DST needs no cron change.

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/0002_schedule.sql`. Replace `PROJECT_REF` with the
project ref from `supabase projects list` before applying to the cloud project
(this is a deploy-time environment value, not code):

```sql
-- Requires extensions pg_cron + pg_net (Supabase: enable in Dashboard or here).
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Store the service-role key in Vault once (run manually in the SQL editor, not
-- committed): select vault.create_secret('<SERVICE_ROLE_KEY>', 'service_role_key');

-- Helper: read the key from Vault at call time.
create or replace function _service_role_key() returns text language sql stable as $$
  select decrypted_secret from vault.decrypted_secrets where name = 'service_role_key' limit 1;
$$;

-- daily-check: 22:30 UTC, Mon-Fri (post-US-close).
select cron.schedule(
  'daily-check',
  '30 22 * * 1-5',
  $$
  select net.http_post(
    url := 'https://PROJECT_REF.supabase.co/functions/v1/daily-check',
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
    url := 'https://PROJECT_REF.supabase.co/functions/v1/kill-switch',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || _service_role_key(),
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb
  );
  $$
);
```

- [ ] **Step 2: Verify locally (schedules register)**

With local stack running (`supabase start`), apply and inspect:

Run: `supabase db reset` then
`psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "select jobname, schedule from cron.job;"`
Expected: two rows — `daily-check | 30 22 * * 1-5` and `kill-switch | */5 13-21 * * 1-5`.
(Local `net.http_post` calls will fail against the placeholder URL — that's expected locally; the cron registration is what we verify here.)

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/0002_schedule.sql
git commit -m "feat(mvp2): pg_cron schedules for daily-check + kill-switch (#220)"
```

---

## Task 5: Rollout & decommission runbook

**Files:**
- Create: `docs/runbooks/mvp2-deploy-and-decommission.md`

This task is operational — no app code. The runbook captures the cut-over so it is
repeatable and the old stack is retired safely.

- [ ] **Step 1: Write the runbook**

Create `docs/runbooks/mvp2-deploy-and-decommission.md`:

```markdown
# MVP 2.0 Deploy & Decommission Runbook

## Prerequisites (hard gates)
- [ ] Confirm **UPRO is buyable** on the Alpaca account (place a 1-share manual test buy on paper).
- [ ] **Rotate** the Alpaca paper keys that were exposed in plaintext; generate fresh paper keys.
- [ ] Generate a strong `PANIC_TOKEN` (e.g. `openssl rand -hex 32`).

## Deploy (paper)
1. `supabase link --project-ref <ref>`
2. Set secrets:
   `supabase secrets set ALPACA_API_KEY=... ALPACA_SECRET_KEY=... ALPACA_PAPER=true N8N_WEBHOOK_URL=... PANIC_TOKEN=... BOT_TICKER=UPRO BOT_BENCHMARK=SPY`
3. `supabase db push` (applies 0001 + 0002).
4. In the SQL editor: `select vault.create_secret('<service_role_key>', 'service_role_key');`
5. Deploy functions:
   `supabase functions deploy daily-check kill-switch` (default JWT-verified; cron sends the service-role bearer)
   `supabase functions deploy panic --no-verify-jwt` (auth is the `x-panic-token` header)
6. Seed state: confirm `bot_config.paused='false'` and that `regime_state` is empty (first daily-check will set it).

## Paper soak
- [ ] Manually invoke `daily-check` once; confirm an `audit_log` row + a `regime_state` row appear with a sane `target_state`.
- [ ] Test the kill button: `curl -X POST "https://<ref>.supabase.co/functions/v1/panic?action=pause" -H "x-panic-token: <token>"` → `bot_config.paused` flips to `true`; then `?action=resume`.
- [ ] Let the cron run for a full week; verify daily flips and 5-min kill-switch ticks land in `audit_log` with expected outcomes; confirm Discord notifications arrive.

## Cut to live
- [ ] After a clean soak: `supabase secrets set ALPACA_PAPER=false` (live keys) and redeploy functions.
- [ ] Watch the first live daily-check + a kill-switch tick closely.

## Decommission old stack
- [ ] Stop the host cron entries for `daily_check.py` and `monitor/kill_switch.py`.
- [ ] Shut down the IBKR Gateway/TWS + its VPS.
- [ ] Archive `trading_bot.db` (SQLite) for forensic history; the new system uses Supabase.
- [ ] Tag the pre-migration tree: `git tag v1.0 <pre-migration-commit> && git push --tags` (do this at the START of execution, before deleting Python production code).
- [ ] Remove the Python production modules (`daily_check.py`, `monitor/`, `tools/ibkr_broker.py`, `tools/database.py`, `tools/notifications.py`, `config/settings.py`, `storage/`) once the TS bot is live and stable. Keep `backtest/` (research).
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/mvp2-deploy-and-decommission.md
git commit -m "docs(mvp2): deploy + decommission runbook (#220)"
```

---

## Plan 3 Self-Review (completed during authoring)

- **Spec coverage:** `daily-check` → spec §4 daily flow (pause, stale-data, reconcile, flip, idempotency) + §5 invariants; `kill-switch` → §4 kill-switch flow (5-min, clock gate, last-trade vs rolling high) + the new 5-min cadence decision; `panic` → §4 panic flow + §5 deterministic kill button (audit row before broker call, token auth, pause flag in DB); scheduling → §3; rollout → §9 (tag v1.0, paper soak, decommission) + the two hard prerequisites.
- **Placeholder scan:** the only non-literal tokens are deploy-time environment values (`PROJECT_REF`, secret values) explicitly marked operator-supplied — not code placeholders. Every code/test step has complete content + a command with expected output.
- **Type consistency:** `Fill`, `RegimeStateRow`, `StrategyConfig`, `State`, and the `*Deps` interfaces are imported/defined once and used identically across each `logic.ts`, its `index.ts`, and its tests. The `reason` enum values and DB column names match the schema (Plan 1) and `db.ts` (Plan 2). `getClock`/`liquidate`/`cancelAllOrders` signatures match the `AlpacaClient` from Plan 2.
- **Decisions logged:** no dry-run mode (paper = soak), IEX feed, Vault-stored service-role key for cron — all recorded at the top of this plan, resolving spec §11.

## Definition of done (Plan 3 → whole migration)

- `deno task test` green across `_shared` + all three functions; `deno task test:db` green.
- Three functions deploy; `pg_cron` shows two registered jobs.
- Paper soak runbook executed; kill button verified.
- Migration complete: live on Supabase + Alpaca; IBKR/SQLite/host-cron decommissioned; `v1.0` tagged.
```
