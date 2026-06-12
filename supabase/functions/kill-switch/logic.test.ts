import { assertEquals } from "@std/assert";
import { type KillSwitchDeps, runKillSwitch } from "./logic.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";

function bars(highs: number[]): DailyBar[] {
  return highs.map((h, i) => ({
    date: `2026-05-${String(i + 1).padStart(2, "0")}`,
    close: h,
    high: h,
  }));
}

function makeDeps(
  over: Partial<KillSwitchDeps> = {},
): { deps: KillSwitchDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = { upserts: [] };
  const defaultMarketdata: KillSwitchDeps["marketdata"] = {
    getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
    getLatestTradePrice: () => Promise.resolve(100),
  };
  const defaultAlpaca: KillSwitchDeps["alpaca"] = {
    getClock: () => Promise.resolve({ isOpen: true }),
    getPosition: () => Promise.resolve(99),
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
      (calls.upserts as unknown[]).push(p);
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
      notifyStateDesync: () => {
        calls.desync = true;
        return Promise.resolve();
      },
      notifyError: (m) => {
        calls.error = m;
        return Promise.resolve();
      },
    },
    ...over,
  };
  if (over.marketdata) deps.marketdata = { ...defaultMarketdata, ...over.marketdata };
  if (over.alpaca) deps.alpaca = { ...defaultAlpaca, ...over.alpaca };
  if (over.db) deps.db = { ...defaultDb, ...over.db };
  return { deps, calls };
}

Deno.test("broker flat -> success:no_position (broker is source of truth)", async () => {
  // Gate is now the real broker position (#237), not the DB's current_state.
  const { deps, calls } = makeDeps({
    alpaca: { getPosition: () => Promise.resolve(0) } as unknown as KillSwitchDeps["alpaca"],
  });
  assertEquals(await runKillSwitch(deps), "success:no_position");
  assertEquals((calls.audit as { outcome: string }).outcome, "success:no_position");
  assertEquals(calls.liquidate, undefined);
});

Deno.test("DB says CASH but broker holds a position -> desync notified, drawdown check continues", async () => {
  // The desync alone must not fire the kill-switch: within the threshold the run
  // ends success:within_threshold, with the desync notified AND recorded in the
  // audit notes for forensics (#266).
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({
          current_state: "CASH",
          kill_switch_active: false,
          spy_close: 400,
          spy_sma200: 380,
          target_state: "CASH",
          kill_switch_fired_at: null,
        } as never),
    } as unknown as KillSwitchDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as KillSwitchDeps["alpaca"],
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(90), // -10%, within threshold
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:within_threshold");
  assertEquals(calls.desync, true);
  assertEquals(calls.liquidate, undefined);
  // Audit notes carry the desync for forensics.
  assertEquals(String((calls.audit as { notes: string }).notes).includes("state_desync"), true);
});

Deno.test("DB says CASH but broker holds a position -> protects it + notifies desync (#237)", async () => {
  // The intraday safety net must protect a real position the DB doesn't know
  // about. DB row exists with current_state=CASH; broker is LONG; price breaches
  // the threshold -> the kill-switch fires AND raises a desync notification.
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({
          current_state: "CASH",
          kill_switch_active: false,
          spy_close: 400,
          spy_sma200: 380,
          target_state: "CASH",
          kill_switch_fired_at: null,
        } as never),
    } as unknown as KillSwitchDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as KillSwitchDeps["alpaca"],
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // drawdown -0.30, breach
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.desync, true);
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "kill_switch");
  assertEquals((calls.upsert as { currentState: string }).currentState, "CASH");
  assertEquals((calls.upsert as { killSwitchActive: boolean }).killSwitchActive, true);
});

Deno.test("no regime_state row but broker holds a position -> still protects it (#266)", async () => {
  // With no regime_state row the kill-switch can't carry regime values forward
  // (NOT NULL spy_close/spy_sma200), but the live position must stay protected:
  // the drawdown check continues, the regime_state upserts are skipped, and a
  // breach still liquidates. daily-check resyncs the DB on its next run.
  const { deps, calls } = makeDeps({
    db: { getLatestRegimeState: () => Promise.resolve(null) } as unknown as KillSwitchDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as KillSwitchDeps["alpaca"],
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // -30%, breach
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.desync, true);
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "kill_switch");
  // No regime_state writes — there is no SPY data here to seed one.
  assertEquals((calls.upserts as unknown[]).length, 0);
  assertEquals(String((calls.audit as { notes: string }).notes).includes("state_desync"), true);
});

Deno.test("market closed -> skipped:market_closed", async () => {
  const { deps, calls } = makeDeps({
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: false }),
    } as unknown as KillSwitchDeps["alpaca"],
  });
  assertEquals(await runKillSwitch(deps), "skipped:market_closed");
  assertEquals((calls.audit as { outcome: string }).outcome, "skipped:market_closed");
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
  // Two upserts: the first persists the drawdown while still LONG (visibility),
  // the second flips to CASH on the fire.
  const upserts = calls.upserts as Array<{ currentState: string }>;
  assertEquals(upserts.length, 2);
  assertEquals(upserts[0].currentState, "LONG");
});

Deno.test("implausible ratio (refHigh/lastPrice > 2) -> error:implausible_drawdown, no liquidation", async () => {
  // 100 -> 40 is a -60% intraday move on a 3x ETF inside the lookback window —
  // impossible without a corporate action (e.g. an unadjusted forward split).
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(40),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "error:implausible_drawdown");
  assertEquals(calls.liquidate, undefined);
  assertEquals(typeof calls.error, "string"); // notifyError fired
  assertEquals((calls.audit as { outcome: string }).outcome, "error:implausible_drawdown");
  // No bogus drawdown row is persisted.
  assertEquals(calls.upsert, undefined);
});

Deno.test("plausible deep breach (ratio <= 2) still liquidates", async () => {
  // 100 -> 60 = -40% drawdown, ratio 1.67 — plausible for a 3x ETF, must fire.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(60),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
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
  assertEquals((calls.upsert as { killSwitchActive: boolean }).killSwitchActive, true);
});

Deno.test("exactly at threshold -> fires (boundary: drawdown === -pct)", async () => {
  // highs all 100, lastPrice 75 -> drawdown = 75/100 - 1 = -0.25, exactly
  // -killSwitchDrawdownPct. The guard is `drawdown > -pct`, which is false at
  // equality, so the kill-switch FIRES at exactly the configured limit. Pins the
  // comparator direction: flipping `>` to `>=` would make this case NOT fire.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(75),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
});

Deno.test("just inside threshold -> does not fire", async () => {
  // lastPrice 76 -> drawdown = -0.24 > -0.25, so within threshold (no liquidation).
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(76),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:within_threshold");
  assertEquals(calls.liquidate, undefined);
});

Deno.test("fresh high (lastPrice above recent highs) -> drawdown 0, cannot fire", async () => {
  // refHigh = max(recentHighs, lastPrice) includes today's last trade, so a new
  // high yields drawdown 0 and cannot fire. If lastPrice were dropped from the
  // max, refHigh would be 90 and the persisted drawdown would be +0.11 — asserting
  // the drawdown is exactly 0 pins the inclusivity of today's price in refHigh.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([90, 90, 90, 90, 90])),
      getLatestTradePrice: () => Promise.resolve(100),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:within_threshold");
  assertEquals(calls.liquidate, undefined);
  assertEquals((calls.upsert as { positionDrawdownPct: number }).positionDrawdownPct, 0);
});

Deno.test("insufficient data (bars < lookback) -> skipped:insufficient_data", async () => {
  // killSwitchLookbackDays is 5; supply only 4 bars.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "skipped:insufficient_data");
  assertEquals(calls.liquidate, undefined);
  assertEquals(calls.upsert, undefined);
});

Deno.test("broker error during liquidate -> error outcome + notifyBrokerError", async () => {
  // A breach reaches liquidate, which throws AlpacaError. The catch reports the
  // error and (because it's an AlpacaError) fires notifyBrokerError with the
  // kill-switch context. Since #242 set .name on AlpacaError, the outcome is
  // "error:AlpacaError".
  let brokerError: { context: string; errorMsg: string } | undefined;
  const { deps } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as KillSwitchDeps["marketdata"],
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: true }),
      liquidate: () => Promise.reject(new AlpacaError("alpaca 500")),
    } as unknown as KillSwitchDeps["alpaca"],
    notifications: {
      notifyKillSwitchFired: () => Promise.resolve(),
      notifyTradeFailed: () => Promise.resolve(),
      notifyBrokerError: (p: { context: string; errorMsg: string }) => {
        brokerError = p;
        return Promise.resolve();
      },
    } as unknown as KillSwitchDeps["notifications"],
  });
  assertEquals(await runKillSwitch(deps), "error:AlpacaError");
  assertEquals(brokerError?.context, "kill-switch");
});

Deno.test("liquidate ok but insertTrade fails -> kill_switch flag persisted before the error (#238)", async () => {
  // The CASH flip + kill_switch_active is upserted BEFORE insertTrade, so a
  // failure recording the trade cannot erase the fact that the kill-switch fired.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as KillSwitchDeps["marketdata"],
    db: {
      insertTrade: () => Promise.reject(new Error("insert failed")),
    } as unknown as KillSwitchDeps["db"],
  });
  const outcome = await runKillSwitch(deps);
  assertEquals(outcome.startsWith("error:"), true);
  const upserts = calls.upserts as Array<{ currentState: string; killSwitchActive: boolean }>;
  assertEquals(upserts.length, 2);
  assertEquals(upserts[1].currentState, "CASH");
  assertEquals(upserts[1].killSwitchActive, true);
});
