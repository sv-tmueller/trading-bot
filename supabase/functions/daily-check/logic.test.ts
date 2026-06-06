import { assertEquals } from "@std/assert";
import { runDailyCheck } from "./logic.ts";
import type { DailyCheckDeps } from "./logic.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
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
  const defaultMarketdata: DailyCheckDeps["marketdata"] = {
    // default: bullish (last close 410 > sma of [390,400,410]=400)
    getDailyCloses: () => Promise.resolve(bars([390, 400, 410])),
    getLatestTradePrice: () => Promise.resolve(70),
  };
  const defaultAlpaca: DailyCheckDeps["alpaca"] = {
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
  };
  const defaultDb: DailyCheckDeps["db"] = {
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
  };
  const deps: DailyCheckDeps = {
    config: {
      regimeSmaDays: 3,
      killSwitchDrawdownPct: 0.25,
      killSwitchLookbackDays: 30,
      botTicker: "UPRO",
      botBenchmark: "SPY",
    },
    now: () => new Date(Date.UTC(2026, 5, 5, 22, 30)),
    marketdata: defaultMarketdata,
    alpaca: defaultAlpaca,
    db: defaultDb,
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
  if (over.marketdata) deps.marketdata = { ...defaultMarketdata, ...over.marketdata };
  if (over.alpaca) deps.alpaca = { ...defaultAlpaca, ...over.alpaca };
  if (over.db) deps.db = { ...defaultDb, ...over.db };
  return { deps, calls };
}

Deno.test("paused -> skipped:trading_paused, no broker", async () => {
  const { deps, calls } = makeDeps({ db: { getConfig: () => Promise.resolve("true") } as unknown as DailyCheckDeps["db"] });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "skipped:trading_paused");
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("stale data -> skipped:stale_data", async () => {
  const { deps } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([390, 400, 410]).map((b) => ({ ...b, date: "2026-06-03" }))) } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
});

Deno.test("no bars -> skipped:stale_data", async () => {
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve([]) } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("insufficient history (bars < SMA window) -> skipped:insufficient_history", async () => {
  // config.regimeSmaDays is 3 in makeDeps; supply only 2 bars (last dated today).
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([400, 410])) } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:insufficient_history");
  assertEquals(calls.placeMarketOrder, undefined);
  assertEquals(calls.upsert, undefined); // no NaN row written
});

Deno.test("bullish from CASH -> BUY and success", async () => {
  const { deps, calls } = makeDeps();
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals((calls.placeMarketOrder as { side: string }).side, "BUY");
  // 7000*0.99/70 = 99 shares
  assertEquals((calls.placeMarketOrder as { qty: number }).qty, 99);
  assertEquals((calls.insertTrade as { reason: string }).reason, "regime_flip_long");
  assertEquals((calls.upsert as { currentState: string }).currentState, "LONG");
});

Deno.test("no flip needed -> success, idempotent no-op", async () => {
  const { deps, calls } = makeDeps({
    db: { getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never) } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.placeMarketOrder, undefined);
  assertEquals(calls.insertTrade, undefined); // no-op day must not record a trade
  assertEquals((calls.upsert as { currentState: string }).currentState, "LONG");
  assertEquals((calls.audit as { outcome: string }).outcome, "success");
});

Deno.test("bearish from LONG -> liquidate to CASH", async () => {
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([410, 400, 390])), getLatestTradePrice: () => Promise.resolve(70) } as unknown as DailyCheckDeps["marketdata"],
    db: { getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never) } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "regime_flip_cash");
  assertEquals((calls.upsert as { currentState: string }).currentState, "CASH");
});

Deno.test("desync (broker LONG, db CASH) reconciles + notifies", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"], // broker LONG
    // db has no row -> current CASH; bullish target LONG == broker LONG -> no flip
  });
  await runDailyCheck(deps);
  assertEquals(calls.desync, true);
  assertEquals(calls.placeMarketOrder, undefined); // already LONG after reconcile
  // The reconciled state (LONG, from broker truth) must be persisted.
  assertEquals((calls.upsert as { currentState: string }).currentState, "LONG");
});

Deno.test("insufficient buying power -> error:insufficient_funds", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { getAccountValue: () => Promise.resolve(10) } as unknown as DailyCheckDeps["alpaca"], // 10*0.99/70 = 0 shares
  });
  assertEquals(await runDailyCheck(deps), "error:insufficient_funds");
  assertEquals(calls.tradeFailed, true);
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("liquidate returns null -> error:liquidate_failed", async () => {
  const { deps, calls } = makeDeps({
    marketdata: { getDailyCloses: () => Promise.resolve(bars([410, 400, 390])), getLatestTradePrice: () => Promise.resolve(70) } as unknown as DailyCheckDeps["marketdata"],
    db: { getLatestRegimeState: () => Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never) } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99), liquidate: () => Promise.resolve(null) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "error:liquidate_failed");
  assertEquals(calls.tradeFailed, true);
  // current_state must be pinned: no regime_state row is written on a failed liquidation.
  assertEquals(calls.upsert, undefined);
});

Deno.test("broker error -> error outcome + notifyBrokerError(daily-check)", async () => {
  // getPosition throws AlpacaError during reconciliation; the catch reports the
  // error and fires notifyBrokerError with context "daily-check". NOTE: the
  // outcome is "error:Error" because the AlpacaError subclass does not set .name.
  let brokerError: { context: string; errorMsg: string } | undefined;
  const { deps } = makeDeps({
    alpaca: {
      getPosition: () => Promise.reject(new AlpacaError("alpaca down")),
    } as unknown as DailyCheckDeps["alpaca"],
    notifications: {
      notifyRegimeFlip: () => Promise.resolve(),
      notifyStateDesync: () => Promise.resolve(),
      notifyTradeFailed: () => Promise.resolve(),
      notifyBrokerError: (p: { context: string; errorMsg: string }) => {
        brokerError = p;
        return Promise.resolve();
      },
    } as unknown as DailyCheckDeps["notifications"],
  });
  assertEquals(await runDailyCheck(deps), "error:Error");
  assertEquals(brokerError?.context, "daily-check");
});
