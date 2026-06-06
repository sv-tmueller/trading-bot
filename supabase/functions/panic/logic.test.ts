import { assertEquals } from "@std/assert";
import { runPanic, type PanicDeps } from "./logic.ts";

function makeDeps(over: Partial<PanicDeps> = {}): { deps: PanicDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const defaultAlpaca: PanicDeps["alpaca"] = {
    cancelAllOrders: () => { calls.cancel = true; return Promise.resolve(3); },
    liquidate: () => { calls.liquidate = true; return Promise.resolve({ orderId: "o1", fillPrice: 70, qty: 99, fillTime: "t" }); },
  };
  const defaultDb: PanicDeps["db"] = {
    setConfig: (k, v) => { calls.setConfig = [k, v]; return Promise.resolve(); },
    insertTrade: (p) => { calls.insertTrade = p; return Promise.resolve(1); },
    insertAuditLog: () => Promise.resolve(5),
    updateAuditLog: (p) => { calls.audit = p; return Promise.resolve(); },
  };
  const deps: PanicDeps = {
    config: { regimeSmaDays: 200, killSwitchDrawdownPct: 0.25, killSwitchLookbackDays: 30, botTicker: "UPRO", botBenchmark: "SPY" },
    now: () => new Date(Date.UTC(2026, 5, 5, 15, 0)),
    alpaca: { ...defaultAlpaca, ...(over.alpaca as unknown as PanicDeps["alpaca"]) },
    db: { ...defaultDb, ...(over.db as unknown as PanicDeps["db"]) },
    notifications: { notifyPanic: () => { calls.panic = true; return Promise.resolve(); } },
    ...over,
  };
  // Re-apply merges: spread over captured defaults (not over itself)
  if (over.alpaca) deps.alpaca = { ...defaultAlpaca, ...over.alpaca as unknown as PanicDeps["alpaca"] };
  if (over.db) deps.db = { ...defaultDb, ...over.db as unknown as PanicDeps["db"] };
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
  const { deps, calls } = makeDeps({ alpaca: { liquidate: () => Promise.resolve(null) } as unknown as PanicDeps["alpaca"] });
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

Deno.test("notify failure does not corrupt a successful outcome", async () => {
  const { deps, calls } = makeDeps({
    notifications: {
      notifyPanic: () => Promise.reject(new Error("n8n down")),
    } as unknown as PanicDeps["notifications"],
  });
  const r = await runPanic(deps, "pause");
  assertEquals(r, "paused");
  assertEquals((calls.audit as { outcome: string }).outcome, "success:panic");
});

Deno.test("liquidate broker failure -> error result + error audit outcome, no trade", async () => {
  // liquidate throws; runPanic returns an error:-prefixed string (which index.ts
  // maps to HTTP 500) and the audit row outcome is error-prefixed. No trade is
  // recorded because the throw precedes insertTrade.
  const { deps, calls } = makeDeps({
    alpaca: {
      liquidate: () => Promise.reject(new Error("alpaca timeout")),
    } as unknown as PanicDeps["alpaca"],
  });
  const r = await runPanic(deps, "liquidate");
  assertEquals(r.startsWith("error:"), true);
  assertEquals((calls.audit as { outcome: string }).outcome.startsWith("error:"), true);
  assertEquals(calls.insertTrade, undefined);
});

Deno.test("cancel-orders broker failure -> error result + error audit outcome", async () => {
  // cancelAllOrders now throws on a partial/failed cancel; panic must surface it
  // as an error: outcome (which index.ts maps to HTTP 500), not a false success.
  const { deps, calls } = makeDeps({
    alpaca: {
      cancelAllOrders: () => Promise.reject(new Error("cancel-all: 1 cancelled, 1 failed of 2")),
    } as unknown as PanicDeps["alpaca"],
  });
  const r = await runPanic(deps, "cancel-orders");
  assertEquals(r.startsWith("error:"), true);
  assertEquals((calls.audit as { outcome: string }).outcome.startsWith("error:"), true);
});
