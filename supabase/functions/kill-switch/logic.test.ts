import { assertEquals } from "@std/assert";
import { type KillSwitchDeps, runKillSwitch } from "./logic.ts";
import { AlpacaError, OrderTimeoutError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";
import { DataError } from "../_shared/num.ts";

function bars(highs: number[]): DailyBar[] {
  return highs.map((h, i) => ({
    date: `2026-05-${String(i + 1).padStart(2, "0")}`,
    close: h,
    high: h,
  }));
}

// Non-breaching quote: mid=100, refHigh=100 -> mid/refHigh - 1 = 0 (within threshold).
// This is the safe default — tests that expect a fire MUST override with a
// confirming (breaching) quote so the both-breach branch runs, not the catch.
const nonBreachingQuote = { bid: 100, ask: 100, mid: 100 };

// Confirming (breaching) quote helpers — mid matches the trade price so both breach.
function breachingQuote(mid: number) {
  return { bid: mid, ask: mid, mid };
}

function makeDeps(
  over: Partial<KillSwitchDeps> = {},
): { deps: KillSwitchDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = { upserts: [] };
  const defaultMarketdata: KillSwitchDeps["marketdata"] = {
    getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
    getLatestTradePrice: () => Promise.resolve(100),
    // Non-breaching default (#269 finding 8 test-integrity fix): a missing or
    // undefined getLatestQuote would route breach tests through the local catch
    // (undefined call throws -> fail-toward-protection -> liquidate) — green for
    // the wrong reason. The explicit non-breaching default means any breach test
    // that forgets a confirming override flips to skipped:breach_unconfirmed and
    // fails loudly, exposing the missing override immediately.
    getLatestQuote: () => Promise.resolve(nonBreachingQuote),
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
    claimTradeDate: (scriptName, tradeDate) => {
      calls.claim = { scriptName, tradeDate };
      return Promise.resolve(true);
    },
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
  // No position -> the qty gate returns before the qtyNote fragment is set, so
  // notes stay null (#342 — qty is only meaningful once a position exists).
  assertEquals((calls.audit as { notes?: string }).notes, undefined);
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
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("state_desync"), true);
  // Broker qty (#342) is carried exactly once — desyncNote no longer duplicates it.
  assertEquals(notes.match(/qty=/g)?.length, 1);
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
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
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
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.desync, true);
  assertEquals(calls.liquidate, true);
  assertEquals((calls.insertTrade as { reason: string }).reason, "kill_switch");
  // No regime_state writes — there is no SPY data here to seed one.
  assertEquals((calls.upserts as unknown[]).length, 0);
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("state_desync"), true);
  // Broker qty (#342) is carried exactly once — desyncNote no longer duplicates it.
  assertEquals(notes.match(/qty=/g)?.length, 1);
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
  // Audit notes carry both the drawdown and the broker-reported qty (#342 —
  // mock getPosition returns 99).
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("dd="), true);
  assertEquals(notes.includes("qty=99"), true);
});

Deno.test("breach -> liquidate + success:kill_switch_fired", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
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
  // NOTE: the implausibility guard fires BEFORE the quote fetch, so no quote
  // override needed here.
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
      getLatestQuote: () => Promise.resolve(breachingQuote(60)), // confirm breach
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
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
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
      getLatestQuote: () => Promise.resolve(breachingQuote(75)), // confirm breach (75/100-1=-0.25)
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
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
    } as unknown as KillSwitchDeps["marketdata"],
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: true }),
      liquidate: () => Promise.reject(new AlpacaError("alpaca 500")),
    } as unknown as KillSwitchDeps["alpaca"],
    notifications: {
      notifyKillSwitchFired: () => Promise.resolve(),
      notifyBrokerError: (p: { context: string; errorMsg: string }) => {
        brokerError = p;
        return Promise.resolve();
      },
    } as unknown as KillSwitchDeps["notifications"],
  });
  assertEquals(await runKillSwitch(deps), "error:AlpacaError");
  assertEquals(brokerError?.context, "kill-switch");
});

Deno.test("liquidate times out (cancel UNVERIFIED) -> error:OrderTimeoutError + notifyBrokerError (#342/#262)", async () => {
  // OrderTimeoutError now extends AlpacaError (#342), so the existing
  // `instanceof AlpacaError -> notifyBrokerError` catch surfaces an UNVERIFIED
  // cancel to the operator with zero caller-side changes.
  let brokerError: { context: string; errorMsg: string } | undefined;
  const { deps } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
    } as unknown as KillSwitchDeps["marketdata"],
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: true }),
      liquidate: () =>
        Promise.reject(
          new OrderTimeoutError(
            "SELL 99 UPRO did not fill within 30000ms; cancel UNVERIFIED — order o1 may still be live (status 'pending_cancel')",
          ),
        ),
    } as unknown as KillSwitchDeps["alpaca"],
    notifications: {
      notifyKillSwitchFired: () => Promise.resolve(),
      notifyBrokerError: (p: { context: string; errorMsg: string }) => {
        brokerError = p;
        return Promise.resolve();
      },
    } as unknown as KillSwitchDeps["notifications"],
  });
  assertEquals(await runKillSwitch(deps), "error:OrderTimeoutError");
  assertEquals(brokerError?.context, "kill-switch");
  assertEquals(brokerError?.errorMsg.includes("cancel UNVERIFIED"), true);
});

Deno.test("liquidate ok but insertTrade fails -> kill_switch flag persisted before the error (#238)", async () => {
  // The CASH flip + kill_switch_active is upserted BEFORE insertTrade, so a
  // failure recording the trade cannot erase the fact that the kill-switch fired.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
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

// ---------------------------------------------------------------------------
// Concurrency guard (#293): claimTradeDate
// ---------------------------------------------------------------------------

Deno.test("concurrency: breach but claimTradeDate returns false -> finishes without liquidating", async () => {
  // A second concurrent invocation on the same trading day finds the claim
  // already taken -> must NOT liquidate; another invocation already handled it.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // -30%, breach
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
    } as unknown as KillSwitchDeps["marketdata"],
    db: {
      claimTradeDate: () => {
        calls.claim = true;
        return Promise.resolve(false); // conflict — another invocation already claimed
      },
    } as unknown as KillSwitchDeps["db"],
  });
  const outcome = await runKillSwitch(deps);
  assertEquals(outcome, "skipped:duplicate_run");
  assertEquals(calls.liquidate, undefined);
  assertEquals((calls.audit as { outcome: string }).outcome, "skipped:duplicate_run");
});

Deno.test("concurrency: within-threshold tick does NOT call claimTradeDate", async () => {
  // A non-breaching run exits before the claim gate — must not consume a claim
  // so a later-that-day breach can still fire.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(90), // -10%, within threshold
    } as unknown as KillSwitchDeps["marketdata"],
  });
  const outcome = await runKillSwitch(deps);
  assertEquals(outcome, "success:within_threshold");
  assertEquals(calls.claim, undefined);
});

Deno.test("concurrency: claim uses script_name='kill-switch' and today's date", async () => {
  // The claim key must identify the script and the trading day; kill-switch
  // must NOT share a namespace with daily-check.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // breach
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
    } as unknown as KillSwitchDeps["marketdata"],
  });
  await runKillSwitch(deps);
  const claim = calls.claim as { scriptName: string; tradeDate: string };
  assertEquals(claim.scriptName, "kill-switch");
  assertEquals(claim.tradeDate, "2026-06-05"); // today per the test clock
});

Deno.test("concurrency: claimTradeDate throws non-23505 error -> error:* outcome, no liquidation", async () => {
  // Any non-conflict claim failure must propagate as an error, not silently
  // skip. This prevents a DB outage from masking a needed liquidation by
  // producing a silent skipped:duplicate_run instead of an alertable error.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // breach
      getLatestQuote: () => Promise.resolve(breachingQuote(70)), // confirm breach
    } as unknown as KillSwitchDeps["marketdata"],
    db: {
      claimTradeDate: () => Promise.reject(new Error("db connection failed")),
    } as unknown as KillSwitchDeps["db"],
  });
  const outcome = await runKillSwitch(deps);
  assertEquals(outcome.startsWith("error:"), true);
  assertEquals(calls.liquidate, undefined);
});

// ---------------------------------------------------------------------------
// B1b dual-breach price confirmation (#269 finding 8)
// ---------------------------------------------------------------------------

Deno.test("B1b: both trade and quote-mid breach -> success:kill_switch_fired (true fire)", async () => {
  // Both trade drawdown and quote-mid drawdown exceed the threshold -> the
  // dual-breach confirmation is satisfied and the kill-switch fires normally.
  // trade dd = 70/100-1 = -0.30, mid dd = 70/100-1 = -0.30, both breach -0.25.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve({ bid: 69, ask: 71, mid: 70 }),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
});

Deno.test("B1b: trade breaches but quote-mid does not -> skipped:breach_unconfirmed, no liquidation", async () => {
  // Classic false-fire suppression: a stale/thin IEX trade print is -30% but the
  // quote midpoint is only -10% (well within threshold). The kill-switch must NOT
  // fire; the suppressed fire is alerted; no claim is consumed so a real breach
  // later the same day can still fire; drawdown was persisted upstream.
  // trade dd = 70/100-1 = -0.30 (breach); mid dd = 90/100-1 = -0.10 (no breach).
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // -30%, breaches
      getLatestQuote: () => Promise.resolve({ bid: 89, ask: 91, mid: 90 }), // -10%, no breach
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "skipped:breach_unconfirmed");
  assertEquals(calls.liquidate, undefined); // did NOT liquidate
  assertEquals(calls.claim, undefined); // did NOT consume the trade claim
  assertEquals(typeof calls.error, "string"); // notifyError fired
  // The upstream drawdown upsert (still-LONG row) ran before the confirmation
  // branch — exactly 1 upsert (no second upsert added by the unconfirmed path).
  assertEquals((calls.upserts as unknown[]).length, 1);
  assertEquals(
    (calls.upserts as Array<{ currentState: string }>)[0].currentState,
    "LONG",
  );
});

Deno.test("B1b: quote fetch throws -> fail-toward-protection: liquidates on trade price alone", async () => {
  // A data outage must NEVER disarm the kill-switch. When the quote fetch throws,
  // the local catch falls through to claim + liquidate on the trade price alone,
  // and notifyError is called. Critically, the outer catch (which returns
  // error:* and would disarm the switch) is NOT reached.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // -30%, breach
      getLatestQuote: () => Promise.reject(new Error("quote service unavailable")),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  assertEquals(typeof calls.error, "string"); // notifyError called (outage alerted)
});

Deno.test(
  "B1b: crossed/non-positive quote (DataError) -> fail-toward-protection: liquidates on trade price alone",
  async () => {
    // A crossed or non-positive quote is now rejected in getLatestQuote (#330) as
    // DataError. The kill-switch's local catch handles DataError identically to any
    // other throw from the quote fetch: notifyError is called, then the run falls
    // through to claim + liquidate on the trade price alone. No logic.ts change
    // needed — this test documents the existing chain "DataError thrown by
    // getLatestQuote -> local catch -> fail-toward-protection".
    // Note: this test passes on the existing catch even before the #330 guard is
    // added to getLatestQuote, because getLatestQuote is mocked here to reject
    // directly. It is a regression test — if the local catch is accidentally removed
    // or weakened, this test fails.
    const { deps, calls } = makeDeps({
      marketdata: {
        getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
        getLatestTradePrice: () => Promise.resolve(70), // -30%, breach
        getLatestQuote: () =>
          Promise.reject(new DataError("implausible quote for UPRO: bid=11 ask=10")),
      } as unknown as KillSwitchDeps["marketdata"],
    });
    assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
    assertEquals(calls.liquidate, true);
    assertEquals(typeof calls.error, "string"); // notifyError called
  },
);

Deno.test("fire notes: confirmed dual-breach carries confirmation=confirmed and mid", async () => {
  // Both trade and quote breach -> the durable audit_log.notes must carry
  // confirmation=confirmed and mid=<quote.mid> so a confirmed fire is
  // distinguishable from a quote-outage fire in forensic queries.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve({ bid: 69, ask: 71, mid: 70 }), // both breach
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("confirmation=confirmed"), true);
  assertEquals(notes.includes("mid="), true);
  // Broker-reported qty (#342) carried on the fire path too.
  assertEquals(notes.includes("qty="), true);
});

Deno.test("fire notes: quote-outage fire carries confirmation=unverified_quote_outage", async () => {
  // Quote throws -> fail-toward-protection path fires. The durable audit_log.notes
  // must carry confirmation=unverified_quote_outage so this fire is distinguishable
  // from a confirmed dual-breach fire.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // -30%, breach
      getLatestQuote: () => Promise.reject(new Error("quote service unavailable")),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("confirmation=unverified_quote_outage"), true);
  // A quote-outage fire does NOT carry a numeric mid (there is none).
  assertEquals(notes.includes("confirmation=confirmed"), false);
});

Deno.test("B1b: neither breaches -> success:within_threshold (regression)", async () => {
  // Both trade and mid are within threshold -> unchanged behavior.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(90), // -10%, no breach
      getLatestQuote: () => Promise.resolve({ bid: 89, ask: 91, mid: 90 }),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:within_threshold");
  assertEquals(calls.liquidate, undefined);
  assertEquals(calls.claim, undefined);
});

Deno.test("B1b: quote fetch throws a non-Error -> still fail-toward-protection: liquidates on trade price alone", async () => {
  // A string rejection (e.g. a quote feed returning a raw error string rather
  // than an Error) must not disarm the kill-switch. Before the fix, the local
  // catch's `(e as Error).message.slice(0, 200)` threw a TypeError on a
  // non-Error rejection (message is undefined), escaping to the outer catch
  // and returning error:TypeError without liquidating.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70), // -30%, breach
      getLatestQuote: () => Promise.reject("quote feed returned garbage"),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  assertEquals(typeof calls.error, "string"); // notifyError fired
});

// ---------------------------------------------------------------------------
// #334: bound quote mid against lastPrice so a well-shaped but implausible
// mid can't suppress a kill-switch fire on a real trade-price breach.
// ---------------------------------------------------------------------------

Deno.test("#334: breaching trade + implausibly HIGH quote mid -> fires on trade price alone", async () => {
  // trade dd = 70/100-1 = -0.30 (breach). Quote is well-shaped (bid < ask, both
  // positive) but mid=700 is a 10x fat-fingered print (ratio 700/70=10 > 2).
  // Pre-fix: midDrawdown = 700/100-1 = +6.00 -> skipped:breach_unconfirmed (the
  // fail-open this issue closes). Post-fix: the bound throws before the
  // unconfirmed check, routing into the local catch -> fires on trade alone.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve({ bid: 690, ask: 710, mid: 700 }),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  assertEquals(typeof calls.error, "string"); // notifyError fired
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("confirmation=unverified_quote_outage"), true);
  assertEquals(notes.includes("confirmation=confirmed"), false);
});

Deno.test("#334: breaching trade + implausibly LOW quote mid -> fires as unverified, not confirmed", async () => {
  // trade dd = 70/100-1 = -0.30 (breach). Quote is well-shaped but mid=7 is a
  // 10x-low print (ratio 70/7=10 > 2). Pre-fix, mid=7 also breaches (dd=-0.93)
  // so the position was liquidated either way — but the fire was wrongly
  // recorded as a *confirmed* dual-breach (confirmation=confirmed mid=7) when
  // the "confirming" second source was itself implausible. Post-fix, the bound
  // throws before reaching the confirmed branch, so the fire is recorded as
  // confirmation=unverified_quote_outage instead.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve({ bid: 6.9, ask: 7.1, mid: 7 }),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("confirmation=unverified_quote_outage"), true);
  assertEquals(notes.includes("confirmation=confirmed"), false);
});

Deno.test("#334: ratio exactly 2 -> bound passes, confirmation proceeds (boundary: strict >)", async () => {
  // trade dd = 70/100-1 = -0.30 (breach). mid=140, lastPrice=70 -> ratio
  // exactly 2.0, not > 2 — the bound is `> 2` (strict), so this quote is NOT
  // rejected and confirmation proceeds normally: midDrawdown = 140/100-1 =
  // +0.40 -> within threshold -> skipped:breach_unconfirmed, no liquidation.
  // Pins the comparator: flipping `>` to `>=` would make this case throw.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(70),
      getLatestQuote: () => Promise.resolve(breachingQuote(140)),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "skipped:breach_unconfirmed");
  assertEquals(calls.liquidate, undefined);
  assertEquals(calls.claim, undefined);
});
