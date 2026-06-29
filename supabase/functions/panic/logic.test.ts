import { assertEquals, assertRejects } from "@std/assert";
import { type PanicDeps, runPanic } from "./logic.ts";

function makeDeps(
  over: Partial<PanicDeps> = {},
): { deps: PanicDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const defaultAlpaca: PanicDeps["alpaca"] = {
    cancelAllOrders: () => {
      calls.cancel = true;
      return Promise.resolve(3);
    },
    liquidate: () => {
      calls.liquidate = true;
      return Promise.resolve({ orderId: "o1", fillPrice: 70, qty: 99, fillTime: "t" });
    },
  };
  const defaultDb: PanicDeps["db"] = {
    setConfig: (k, v) => {
      calls.setConfig = [k, v];
      return Promise.resolve();
    },
    insertTrade: (p) => {
      calls.insertTrade = p;
      return Promise.resolve(1);
    },
    insertAuditLog: () => Promise.resolve(5),
    updateAuditLog: (p) => {
      calls.audit = p;
      return Promise.resolve();
    },
  };
  const deps: PanicDeps = {
    config: {
      regimeSmaDays: 200,
      killSwitchDrawdownPct: 0.25,
      killSwitchLookbackDays: 30,
      botTicker: "UPRO",
      botBenchmark: "SPY",
    },
    now: () => new Date(Date.UTC(2026, 5, 5, 15, 0)),
    alpaca: { ...defaultAlpaca, ...(over.alpaca as unknown as PanicDeps["alpaca"]) },
    db: { ...defaultDb, ...(over.db as unknown as PanicDeps["db"]) },
    notifications: {
      notifyPanic: () => {
        calls.panic = true;
        return Promise.resolve();
      },
    },
    ...over,
  };
  // Re-apply merges: spread over captured defaults (not over itself)
  if (over.alpaca) {
    deps.alpaca = { ...defaultAlpaca, ...over.alpaca as unknown as PanicDeps["alpaca"] };
  }
  if (over.db) deps.db = { ...defaultDb, ...over.db as unknown as PanicDeps["db"] };
  return { deps, calls };
}

Deno.test("pause sets bot_config.paused=true", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "pause");
  assertEquals(calls.setConfig, ["paused", "true"]);
  assertEquals(r.ok, true);
  assertEquals(r.result, "paused");
});

Deno.test("resume sets bot_config.paused=false", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "resume");
  assertEquals(calls.setConfig, ["paused", "false"]);
  assertEquals(r.ok, true);
  assertEquals(r.result, "resumed");
});

Deno.test("cancel-orders cancels and reports count", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "cancel-orders");
  assertEquals(calls.cancel, true);
  assertEquals(r.ok, true);
  assertEquals(r.result, "cancelled 3 orders");
});

Deno.test("liquidate sells + writes panic_cli trade", async () => {
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "liquidate");
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "panic_cli");
  assertEquals(r.ok, true);
  assertEquals(r.result.includes("liquidated"), true);
});

Deno.test("liquidate also pauses trading by default (finding 13 / #185 option 1)", async () => {
  // Without the pause, a still-bullish SPY would make the next daily-check
  // re-buy the position the operator just dumped.
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "liquidate");
  assertEquals(calls.setConfig, ["paused", "true"]);
  assertEquals(r.ok, true);
  assertEquals(r.result.includes("trading paused"), true);
});

Deno.test("liquidate with pauseOnLiquidate=false does NOT pause and says so", async () => {
  // #185 option 1 opt-out (?pause=false): brief flatten without locking the bot
  // out; the result string makes the choice explicit.
  const { deps, calls } = makeDeps();
  const r = await runPanic(deps, "liquidate", { pauseOnLiquidate: false });
  assertEquals(calls.setConfig, undefined);
  assertEquals(r.ok, true);
  assertEquals(r.result.includes("NOT paused"), true);
});

Deno.test("liquidate with no position reports no position and still pauses", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { liquidate: () => Promise.resolve(null) } as unknown as PanicDeps["alpaca"],
  });
  const r = await runPanic(deps, "liquidate");
  assertEquals(r.ok, true);
  assertEquals(r.result, "no position to liquidate; trading paused");
  assertEquals(calls.insertTrade, undefined);
  assertEquals(calls.setConfig, ["paused", "true"]);
});

Deno.test("unknown action -> error", async () => {
  const { deps } = makeDeps();
  // deno-lint-ignore no-explicit-any
  const r = await runPanic(deps, "boom" as any);
  assertEquals(r.ok, false);
});

Deno.test("notify failure does not corrupt a successful outcome", async () => {
  const { deps, calls } = makeDeps({
    notifications: {
      notifyPanic: () => Promise.reject(new Error("n8n down")),
    } as unknown as PanicDeps["notifications"],
  });
  const r = await runPanic(deps, "pause");
  assertEquals(r.ok, true);
  assertEquals(r.result, "paused");
  assertEquals((calls.audit as { outcome: string }).outcome, "success:panic");
});

Deno.test("liquidate broker failure -> ok:false + error audit outcome, no trade", async () => {
  // liquidate throws; runPanic returns ok:false (which index.ts maps to HTTP 500)
  // and the audit row outcome is error-prefixed. No trade is recorded because the
  // throw precedes insertTrade.
  const { deps, calls } = makeDeps({
    alpaca: {
      liquidate: () => Promise.reject(new Error("alpaca timeout")),
    } as unknown as PanicDeps["alpaca"],
  });
  const r = await runPanic(deps, "liquidate");
  assertEquals(r.ok, false);
  assertEquals((calls.audit as { outcome: string }).outcome.startsWith("error:"), true);
  assertEquals(calls.insertTrade, undefined);
  // A failed liquidation must NOT pause (finding 13): the throw precedes the
  // pause write, so the operator retries from a known state.
  assertEquals(calls.setConfig, undefined);
});

Deno.test("cancel-orders broker failure -> ok:false + error audit outcome", async () => {
  // cancelAllOrders now throws on a partial/failed cancel; panic must surface it
  // as ok:false (which index.ts maps to HTTP 500), not a false success.
  const { deps, calls } = makeDeps({
    alpaca: {
      cancelAllOrders: () => Promise.reject(new Error("cancel-all: 1 cancelled, 1 failed of 2")),
    } as unknown as PanicDeps["alpaca"],
  });
  const r = await runPanic(deps, "cancel-orders");
  assertEquals(r.ok, false);
  assertEquals((calls.audit as { outcome: string }).outcome.startsWith("error:"), true);
});

// Test A: updateAuditLog rejecting in finally must not mask the typed return.
// Red before change 3 (the unguarded await throws, replacing the pending return),
// green after (try/catch swallows the audit-close error).
Deno.test("updateAuditLog failure in finally does not mask ok:true return", async () => {
  const { deps } = makeDeps({
    db: {
      updateAuditLog: () => Promise.reject(new Error("db write failed")),
    } as unknown as PanicDeps["db"],
  });
  const r = await runPanic(deps, "pause");
  assertEquals(r.ok, true);
  assertEquals(r.result, "paused");
});

// Test B: insertAuditLog rejecting before the try must propagate (characterization
// guard — green before and after change 3; pins that swallow never reaches insertAuditLog).
Deno.test("insertAuditLog failure propagates and is not swallowed", async () => {
  const { deps } = makeDeps({
    db: {
      insertAuditLog: () => Promise.reject(new Error("audit open failed")),
    } as unknown as PanicDeps["db"],
  });
  await assertRejects(() => runPanic(deps, "pause"), Error, "audit open failed");
});
