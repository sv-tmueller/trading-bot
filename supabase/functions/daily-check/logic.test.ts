import { assertEquals } from "@std/assert";
import { runDailyCheck } from "./logic.ts";
import type { DailyCheckDeps } from "./logic.ts";
import { AlpacaError, OrderTimeoutError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";

function bars(closes: number[]): DailyBar[] {
  // oldest-first; dates ascending ending 2026-06-04 — the most recent
  // COMPLETED session relative to the test clock (2026-06-05 13:37 UTC).
  return closes.map((c, i) => ({
    date: new Date(Date.UTC(2026, 5, 4) - (closes.length - 1 - i) * 86400000).toISOString().slice(
      0,
      10,
    ),
    close: c,
    high: c,
  }));
}

function makeDeps(
  over: Partial<DailyCheckDeps> = {},
): { deps: DailyCheckDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const defaultMarketdata: DailyCheckDeps["marketdata"] = {
    // default: bullish (last close 410 > sma of [390,400,410]=400)
    getDailyCloses: () => Promise.resolve(bars([390, 400, 410])),
    getLatestTradePrice: () => Promise.resolve(70),
  };
  let accountValueCalls = 0;
  const defaultAlpaca: DailyCheckDeps["alpaca"] = {
    getClock: () => Promise.resolve({ isOpen: true }),
    getCalendar: () => Promise.resolve(["2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]),
    getPosition: () => Promise.resolve(0),
    getAccountValue: () => {
      accountValueCalls++;
      calls.accountValueCalls = accountValueCalls;
      return Promise.resolve(7000);
    },
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
    claimTradeDate: (scriptName, tradeDate) => {
      calls.claim = { scriptName, tradeDate };
      return Promise.resolve(true);
    },
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
    upsertEquitySnapshot: (p) => {
      calls.equitySnapshot = p;
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
    now: () => new Date(Date.UTC(2026, 5, 5, 13, 37)),
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
  const { deps, calls } = makeDeps({
    db: { getConfig: () => Promise.resolve("true") } as unknown as DailyCheckDeps["db"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "skipped:trading_paused");
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("stale data -> skipped:stale_data", async () => {
  const { deps } = makeDeps({
    marketdata: {
      getDailyCloses: () =>
        Promise.resolve(bars([390, 400, 410]).map((b) => ({ ...b, date: "2026-06-03" }))),
    } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
});

Deno.test("no bars -> skipped:stale_data", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve([]),
    } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("insufficient history (bars < SMA window) -> skipped:insufficient_history", async () => {
  // config.regimeSmaDays is 3 in makeDeps; supply only 2 bars (last dated today).
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([400, 410])),
    } as unknown as DailyCheckDeps["marketdata"],
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

Deno.test("partial fill: trades row records the actually-filled qty (#267)", async () => {
  // placeMarketOrder asked for 99 shares but only 40 filled before the order
  // timed out and was cancelled; the broker layer returns the real fill.
  const { deps, calls } = makeDeps({
    alpaca: {
      placeMarketOrder: () =>
        Promise.resolve({ orderId: "o1", fillPrice: 70, qty: 40, fillTime: "t" }),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals((calls.insertTrade as { qty: number }).qty, 40);
});

Deno.test("no flip needed -> success, idempotent no-op", async () => {
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
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
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([410, 400, 390])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
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

Deno.test("same-day re-entry preserves kill_switch_fired_at (finding 10)", async () => {
  // The kill switch fired earlier today (flag set, forensic timestamp written);
  // SPY is still bullish so daily-check clears the flag and re-enters LONG.
  // The fired_at timestamp must be carried through, not nulled out.
  const firedAt = "2026-06-05T14:05:00Z";
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({
          current_state: "CASH",
          kill_switch_active: true,
          kill_switch_fired_at: firedAt,
        } as never),
    } as unknown as DailyCheckDeps["db"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals((calls.upsert as { currentState: string }).currentState, "LONG");
  assertEquals((calls.upsert as { killSwitchActive: boolean }).killSwitchActive, false);
  assertEquals((calls.upsert as { killSwitchFiredAt: string | null }).killSwitchFiredAt, firedAt);
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
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([410, 400, 390])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
    alpaca: {
      getPosition: () => Promise.resolve(99),
      liquidate: () => Promise.resolve(null),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "error:liquidate_failed");
  assertEquals(calls.tradeFailed, true);
  // current_state must be pinned: no regime_state row is written on a failed liquidation.
  assertEquals(calls.upsert, undefined);
});

Deno.test("broker error -> error outcome + notifyBrokerError(daily-check)", async () => {
  // getPosition throws AlpacaError during reconciliation; the catch reports the
  // error and fires notifyBrokerError with context "daily-check". Since #242 set
  // .name on AlpacaError, the outcome is "error:AlpacaError".
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
  assertEquals(await runDailyCheck(deps), "error:AlpacaError");
  assertEquals(brokerError?.context, "daily-check");
});

Deno.test("placeMarketOrder times out (cancel UNVERIFIED) -> error:OrderTimeoutError + notifyBrokerError (#342/#262)", async () => {
  // OrderTimeoutError now extends AlpacaError (#342), so the existing
  // `instanceof AlpacaError -> notifyBrokerError` catch surfaces an UNVERIFIED
  // cancel to the operator with zero caller-side changes.
  let brokerError: { context: string; errorMsg: string } | undefined;
  const { deps } = makeDeps({
    alpaca: {
      placeMarketOrder: () =>
        Promise.reject(
          new OrderTimeoutError(
            "BUY 99 UPRO did not fill within 30000ms; cancel UNVERIFIED — order o1 may still be live (status 'pending_cancel')",
          ),
        ),
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
  assertEquals(await runDailyCheck(deps), "error:OrderTimeoutError");
  assertEquals(brokerError?.context, "daily-check");
  assertEquals(brokerError?.errorMsg.includes("cancel UNVERIFIED"), true);
});

Deno.test("getConfig (paused read) failure -> error outcome, no trade (#238)", async () => {
  // The paused read now lives inside the try; a DB failure there must produce an
  // error:* audit outcome, not an unhandled throw that escapes with no outcome.
  const { deps, calls } = makeDeps({
    db: {
      getConfig: () => Promise.reject(new Error("db down")),
    } as unknown as DailyCheckDeps["db"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome.startsWith("error:"), true);
  assertEquals((calls.audit as { outcome: string }).outcome.startsWith("error:"), true);
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("account-value read fails before liquidate -> error, no trade, no state write (#238)", async () => {
  // accountValue is read once before any order. On a CASH flip a read failure
  // must error pre-trade (liquidate not called, no regime_state row) rather than
  // after a fill — which would mislabel a completed SELL as error.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([410, 400, 390])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
    alpaca: {
      getPosition: () => Promise.resolve(99),
      getAccountValue: () => Promise.reject(new Error("acct read failed")),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome.startsWith("error:"), true);
  assertEquals(calls.liquidate, undefined);
  assertEquals(calls.upsert, undefined);
});

Deno.test("market closed -> skipped:market_closed, no broker mutation, no state write (#256)", async () => {
  const { deps, calls } = makeDeps({
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: false }),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:market_closed");
  assertEquals(calls.placeMarketOrder, undefined);
  assertEquals(calls.upsert, undefined);
  assertEquals((calls.audit as { outcome: string }).outcome, "skipped:market_closed");
});

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
    marketdata: {
      getDailyCloses: () => Promise.resolve(staleBars),
    } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
  assertEquals(calls.placeMarketOrder, undefined);
});

Deno.test("BUY filled but insertTrade throws -> error outcome, state NOT flipped (#269 finding 15)", async () => {
  // The fill succeeded at the broker but the trades write failed. The run must
  // close the audit row with error:* and must NOT flip regime_state to LONG
  // (upsertRegimeState runs after the trade write), leaving the DB/broker
  // desync to the kill-switch broker-truth backstop (#237/#266) and the next
  // daily-check reconcile.
  const { deps, calls } = makeDeps({
    db: {
      insertTrade: () => Promise.reject(new Error("db write failed")),
    } as unknown as DailyCheckDeps["db"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "error:Error");
  assertEquals(calls.placeMarketOrder !== undefined, true); // the order really filled
  assertEquals(calls.upsert, undefined); // DB still says CASH — kill-switch protects the live position
  assertEquals((calls.audit as { outcome: string }).outcome, "error:Error");
});

Deno.test("trade recorded but upsertRegimeState throws -> error outcome, trade row intact (#269 finding 15)", async () => {
  // Inverse seam: the trades row landed but the state flip write failed. The
  // audit row must close with error:*; the recorded fill is the forensic
  // anchor for the partial-recovery described in CLAUDE.md.
  const { deps, calls } = makeDeps({
    db: {
      upsertRegimeState: () => Promise.reject(new Error("db write failed")),
    } as unknown as DailyCheckDeps["db"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "error:Error");
  assertEquals((calls.insertTrade as { reason: string }).reason, "regime_flip_long");
  assertEquals((calls.audit as { outcome: string }).outcome, "error:Error");
});

// ---------------------------------------------------------------------------
// Concurrency guard (#293): claimTradeDate
// ---------------------------------------------------------------------------

Deno.test("concurrency: first invoke claims and places order; second sees conflict -> skipped:duplicate_run, no order", async () => {
  // Simulate a duplicate invocation on the same trading day by having
  // claimTradeDate return false (another invocation already claimed the date).
  const { deps, calls } = makeDeps({
    db: {
      claimTradeDate: () => {
        calls.claim = true;
        return Promise.resolve(false); // conflict — another invocation already claimed
      },
    } as unknown as DailyCheckDeps["db"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "skipped:duplicate_run");
  assertEquals(calls.placeMarketOrder, undefined);
  assertEquals(calls.liquidate, undefined);
  assertEquals((calls.audit as { outcome: string }).outcome, "skipped:duplicate_run");
});

Deno.test("concurrency: no-op day (no flip) does NOT call claimTradeDate", async () => {
  // When targetState === currentState no order is needed; the claim must NOT
  // be consumed so a concurrent no-op doesn't block a real re-run.
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"],
  });
  const outcome = await runDailyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals(calls.claim, undefined); // no claim on a no-op day
});

Deno.test("concurrency: claim uses script_name='daily-check' and today's date", async () => {
  // The claim key must identify the script and the trading day correctly so
  // daily-check and kill-switch do not share a namespace.
  const { deps, calls } = makeDeps();
  await runDailyCheck(deps);
  const claim = calls.claim as { scriptName: string; tradeDate: string };
  assertEquals(claim.scriptName, "daily-check");
  assertEquals(claim.tradeDate, "2026-06-05"); // today per the test clock
});

Deno.test("concurrency: skipped:* run (market_closed) before claim gate — claim never called", async () => {
  // Market-closed exits before the targetState !== currentState block,
  // so no claim is ever consumed.
  const { deps, calls } = makeDeps({
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: false }),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:market_closed");
  assertEquals(calls.claim, undefined);
});

// ---------------------------------------------------------------------------
// #383 T3: daily equity snapshot (D1 hoist-and-reuse, D2 write point after
// upsertRegimeState).
// ---------------------------------------------------------------------------

Deno.test("no-flip day: writes equity snapshot, getAccountValue called exactly once", async () => {
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.equitySnapshot, { date: "2026-06-05", equityUsd: 7000 });
  assertEquals(calls.accountValueCalls, 1);
});

Deno.test("BUY flip day: writes equity snapshot, reuses the same accountValue (getAccountValue called exactly once)", async () => {
  const { deps, calls } = makeDeps();
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.equitySnapshot, { date: "2026-06-05", equityUsd: 7000 });
  assertEquals(calls.accountValueCalls, 1);
});

Deno.test("SELL flip day: writes equity snapshot, reuses the same accountValue (getAccountValue called exactly once)", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([410, 400, 390])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "success");
  assertEquals(calls.equitySnapshot, { date: "2026-06-05", equityUsd: 7000 });
  assertEquals(calls.accountValueCalls, 1);
});

function stubWarn(): { calls: unknown[][]; restore: () => void } {
  const original = console.warn;
  const calls: unknown[][] = [];
  console.warn = (...args: unknown[]) => {
    calls.push(args);
  };
  return { calls, restore: () => (console.warn = original) };
}

Deno.test("no-flip day: upsertEquitySnapshot throws -> outcome stays success, warning logged (#383 D4)", async () => {
  const { deps, calls } = makeDeps({
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
      upsertEquitySnapshot: () => Promise.reject(new Error("db unavailable")),
    } as unknown as DailyCheckDeps["db"],
    alpaca: { getPosition: () => Promise.resolve(99) } as unknown as DailyCheckDeps["alpaca"],
  });
  const warn = stubWarn();
  try {
    const outcome = await runDailyCheck(deps);
    assertEquals(outcome, "success");
    assertEquals(calls.audit, {
      id: 42,
      finishedAt: "2026-06-05T13:37:00.000Z",
      outcome: "success",
      notes: "target=LONG current=LONG",
    });
    assertEquals(warn.calls.length > 0, true);
  } finally {
    warn.restore();
  }
});

Deno.test("BUY flip day: upsertEquitySnapshot throws -> outcome stays success, warning logged (#383 D4)", async () => {
  const { deps, calls } = makeDeps({
    db: {
      upsertEquitySnapshot: () => Promise.reject(new Error("db unavailable")),
    } as unknown as DailyCheckDeps["db"],
  });
  const warn = stubWarn();
  try {
    const outcome = await runDailyCheck(deps);
    assertEquals(outcome, "success");
    assertEquals(calls.placeMarketOrder, { symbol: "UPRO", side: "BUY", qty: 99 });
    assertEquals(warn.calls.length > 0, true);
  } finally {
    warn.restore();
  }
});

Deno.test("skipped:trading_paused -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    db: { getConfig: () => Promise.resolve("true") } as unknown as DailyCheckDeps["db"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:trading_paused");
  assertEquals(calls.equitySnapshot, undefined);
});

Deno.test("skipped:market_closed -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    alpaca: {
      getClock: () => Promise.resolve({ isOpen: false }),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:market_closed");
  assertEquals(calls.equitySnapshot, undefined);
});

Deno.test("skipped:stale_data -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve([]),
    } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:stale_data");
  assertEquals(calls.equitySnapshot, undefined);
});

Deno.test("skipped:insufficient_history -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([400, 410])),
    } as unknown as DailyCheckDeps["marketdata"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:insufficient_history");
  assertEquals(calls.equitySnapshot, undefined);
});

Deno.test("skipped:duplicate_run -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    db: {
      claimTradeDate: () => Promise.resolve(false),
    } as unknown as DailyCheckDeps["db"],
  });
  assertEquals(await runDailyCheck(deps), "skipped:duplicate_run");
  assertEquals(calls.equitySnapshot, undefined);
});

Deno.test("error:insufficient_funds -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    alpaca: { getAccountValue: () => Promise.resolve(10) } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "error:insufficient_funds");
  assertEquals(calls.equitySnapshot, undefined);
});

Deno.test("error:liquidate_failed -> no equity snapshot", async () => {
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([410, 400, 390])),
      getLatestTradePrice: () => Promise.resolve(70),
    } as unknown as DailyCheckDeps["marketdata"],
    db: {
      getLatestRegimeState: () =>
        Promise.resolve({ current_state: "LONG", kill_switch_active: false } as never),
    } as unknown as DailyCheckDeps["db"],
    alpaca: {
      getPosition: () => Promise.resolve(99),
      liquidate: () => Promise.resolve(null),
    } as unknown as DailyCheckDeps["alpaca"],
  });
  assertEquals(await runDailyCheck(deps), "error:liquidate_failed");
  assertEquals(calls.equitySnapshot, undefined);
});
