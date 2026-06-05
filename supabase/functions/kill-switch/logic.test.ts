import { assertEquals } from "@std/assert";
import { runKillSwitch, type KillSwitchDeps } from "./logic.ts";
import type { DailyBar } from "../_shared/marketdata.ts";

function bars(highs: number[]): DailyBar[] {
  return highs.map((h, i) => ({ date: `2026-05-${String(i + 1).padStart(2, "0")}`, close: h, high: h }));
}

function makeDeps(over: Partial<KillSwitchDeps> = {}): { deps: KillSwitchDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const defaultMarketdata: KillSwitchDeps["marketdata"] = {
    getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
    getLatestTradePrice: () => Promise.resolve(100),
  };
  const defaultAlpaca: KillSwitchDeps["alpaca"] = {
    getClock: () => Promise.resolve({ isOpen: true }),
    liquidate: () => {
      calls.liquidate = true;
      return Promise.resolve({ orderId: "o1", fillPrice: 70, qty: 99, fillTime: "t" });
    },
  };
  const defaultDb: KillSwitchDeps["db"] = {
    getLatestRegimeState: () =>
      Promise.resolve({
        current_state: "LONG",
        kill_switch_active: false,
        spy_close: 400,
        spy_sma200: 380,
        target_state: "LONG",
        kill_switch_fired_at: null,
      } as never),
    upsertRegimeState: (p) => {
      calls.upsert = p;
      return Promise.resolve();
    },
    insertTrade: (p) => {
      calls.insertTrade = p;
      return Promise.resolve(1);
    },
    insertAuditLog: () => Promise.resolve(7),
    updateAuditLog: (p) => {
      calls.audit = p;
      return Promise.resolve();
    },
  };
  const deps: KillSwitchDeps = {
    config: {
      regimeSmaDays: 200,
      killSwitchDrawdownPct: 0.25,
      killSwitchLookbackDays: 5,
      botTicker: "UPRO",
      botBenchmark: "SPY",
    },
    now: () => new Date(Date.UTC(2026, 5, 5, 15, 0)),
    marketdata: defaultMarketdata,
    alpaca: defaultAlpaca,
    db: defaultDb,
    notifications: {
      notifyKillSwitchFired: () => {
        calls.fired = true;
        return Promise.resolve();
      },
      notifyTradeFailed: () => Promise.resolve(),
      notifyBrokerError: () => Promise.resolve(),
    },
    ...over,
  };
  if (over.marketdata) deps.marketdata = { ...defaultMarketdata, ...over.marketdata };
  if (over.alpaca) deps.alpaca = { ...defaultAlpaca, ...over.alpaca };
  if (over.db) deps.db = { ...defaultDb, ...over.db };
  return { deps, calls };
}

Deno.test("not LONG -> success:no_position", async () => {
  const { deps } = makeDeps({
    db: {
      getLatestRegimeState: () => Promise.resolve({ current_state: "CASH" } as never),
    } as unknown as KillSwitchDeps["db"],
  });
  assertEquals(await runKillSwitch(deps), "success:no_position");
});

Deno.test("market closed -> skipped:market_closed", async () => {
  const { deps } = makeDeps({
    alpaca: { getClock: () => Promise.resolve({ isOpen: false }) } as unknown as KillSwitchDeps["alpaca"],
  });
  assertEquals(await runKillSwitch(deps), "skipped:market_closed");
});

Deno.test("within threshold -> success:within_threshold, persists drawdown", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(90),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:within_threshold");
  assertEquals(calls.liquidate, undefined);
  // drawdown = 90/100 - 1 = -0.10
  assertEquals(
    Math.round(((calls.upsert as { positionDrawdownPct: number }).positionDrawdownPct) * 100) / 100,
    -0.10,
  );
});

Deno.test("breach -> liquidate + success:kill_switch_fired", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  assertEquals(calls.fired, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "kill_switch");
  assertEquals((calls.upsert as { currentState: string }).currentState, "CASH");
  assertEquals((calls.upsert as { killSwitchActive: boolean }).killSwitchActive, true);
});

Deno.test("breach but position vanished -> success:no_position_to_liquidate", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as KillSwitchDeps["marketdata"],
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: true }),
      liquidate: () => Promise.resolve(null),
    } as unknown as KillSwitchDeps["alpaca"],
  });
  assertEquals(await runKillSwitch(deps), "success:no_position_to_liquidate");
  assertEquals((calls.upsert as { currentState: string }).currentState, "CASH");
});
