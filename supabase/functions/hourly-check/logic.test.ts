import { assertEquals } from "@std/assert";
import type { ClosedOrderFill, Fill } from "../_shared/alpaca.ts";
import type { HourlyConfig } from "../_shared/config.ts";
import type { HourlyScanRow, TradeRow } from "../_shared/db.ts";
import type { CalendarSession, HourlyBar } from "../_shared/marketdata.ts";
import {
  computeBracketGeometry,
  computeSizing,
  etHHMMToUtcMs,
  etOffsetMinutes,
  type HourlyCheckDeps,
  isBarPartial,
  runHourlyCheck,
} from "./logic.ts";

// ---------------------------------------------------------------------------
// Test fixture: a fully-mocked, "happy path up to just before entering LONG"
// deps object matching the spec §6 worked example (entry 550.00, bar low
// 548/high 553 -> stop 547.75, qtyRisk 444, qtyCap 18, qty 18). Every test
// overrides only the piece(s) needed to exercise its gate.
// ---------------------------------------------------------------------------

const BASE_CONFIG: HourlyConfig = {
  hourlyBotTicker: "SPY",
  sizingRiskPct: 0.01,
  sizingNotionalCapPct: 0.10,
  hourlyBracketRMultiple: 2,
  hourlyStopBufferPct: 0.05,
  hourlyMinStopDistance: 0.05,
  hourlyMaxEntriesPerDay: 3,
  hourlyStalenessToleranceMin: 10,
  hourlyContextMode: "none",
  hourlyShortsEnabled: true,
  hourlyBotPaperOnly: true,
};

// bar0: flat prior bar (warmup only -- never bull nor bear, so no 2-bar
// pattern can fire off of it).
const BAR0: HourlyBar = {
  timestamp: "2026-07-27T13:00:00Z",
  open: 548,
  high: 548.5,
  low: 547.5,
  close: 548,
};
// bar1 (the candidate signal bar): a clean bullish_marubozu, low=548/high=553
// (range 5, buffer 0.25 -> stop 547.75, matching the spec §6 worked example).
const BAR1: HourlyBar = {
  timestamp: "2026-07-27T14:00:00Z",
  open: 548.1,
  high: 553,
  low: 548,
  close: 552.9,
};

const SESSION: CalendarSession = { date: "2026-07-27", open: "09:30", close: "16:00" };

function fill(over: Partial<Fill> = {}): Fill {
  return {
    orderId: "o1",
    fillPrice: 550,
    qty: 18,
    fillTime: "2026-07-27T14:05:00Z",
    ...over,
  };
}

interface Recorder {
  auditFinishes: Array<{ outcome: string; notes?: string | null }>;
  scans: Array<Parameters<HourlyCheckDeps["db"]["upsertHourlyScan"]>[0]>;
  trades: Array<Parameters<HourlyCheckDeps["db"]["insertTrade"]>[0]>;
  configSets: Array<[string, string]>;
  cancelledOrderIds: string[];
  claimCalls: string[];
}

function buildDeps(nowIso = "2026-07-27T15:07:00Z"): { deps: HourlyCheckDeps; rec: Recorder } {
  const rec: Recorder = {
    auditFinishes: [],
    scans: [],
    trades: [],
    configSets: [],
    cancelledOrderIds: [],
    claimCalls: [],
  };

  const configStore = new Map<string, string>([
    ["hourly_experiment_start_equity", "100000"],
  ]);

  const deps: HourlyCheckDeps = {
    config: { ...BASE_CONFIG },
    now: () => new Date(nowIso),
    marketdata: {
      getHourlyBars: (_symbol, _opts) => Promise.resolve([BAR0, BAR1]),
      getCalendarSessions: (_start, _end) => Promise.resolve([SESSION]),
      getLatestTradePrice: (_symbol) => Promise.resolve(550),
    },
    alpaca: {
      getClock: () =>
        Promise.resolve({ isOpen: true, nextClose: new Date("2026-07-27T20:00:00Z").getTime() }),
      getPosition: (_symbol) => Promise.resolve(0),
      assertPaperAccount: () => Promise.resolve({ equity: 100000 }),
      placeBracketOrder: (_args) => Promise.resolve(fill({ orderId: "bracket1" })),
      placeOcoExitPair: (_args) => Promise.resolve({ orderId: "oco1" }),
      placeMarketOrder: (_args) => Promise.resolve(fill({ orderId: "mkt1" })),
      cancelOrder: (orderId) => {
        rec.cancelledOrderIds.push(orderId);
        return Promise.resolve();
      },
      getAssetShortability: (_symbol) => Promise.resolve({ shortable: true, easyToBorrow: true }),
      listFilledOrdersSince: (_symbol, _sinceIso) => Promise.resolve([] as ClosedOrderFill[]),
      listOpenOrderIds: (_symbol) => Promise.resolve([] as string[]),
    },
    db: {
      getConfig: (key) => Promise.resolve(configStore.get(key) ?? null),
      setConfig: (key, value) => {
        configStore.set(key, value);
        rec.configSets.push([key, value]);
        return Promise.resolve();
      },
      getTradesSince: (_sinceIso) => Promise.resolve([] as TradeRow[]),
      upsertHourlyScan: (p) => {
        rec.scans.push(p);
        return Promise.resolve();
      },
      getHourlyScanByEntryOrderId: (_symbol, _orderId) =>
        Promise.resolve(null as HourlyScanRow | null),
      claimBar: (_scriptName, barTs) => {
        rec.claimCalls.push(barTs);
        return Promise.resolve(true);
      },
      insertTrade: (p) => {
        rec.trades.push(p);
        return Promise.resolve(rec.trades.length);
      },
      insertAuditLog: (_p) => Promise.resolve(1),
      updateAuditLog: (p) => {
        rec.auditFinishes.push({ outcome: p.outcome, notes: p.notes });
        return Promise.resolve();
      },
    },
    notifications: {
      notifyBrokerError: (_p) => Promise.resolve(),
    },
  };

  return { deps, rec };
}

function lastOutcome(rec: Recorder): string {
  return rec.auditFinishes[rec.auditFinishes.length - 1]?.outcome;
}

// ---------------------------------------------------------------------------
// ET<->UTC helper + partial-bar predicate (pure)
// ---------------------------------------------------------------------------

Deno.test("etOffsetMinutes: EDT (July) is 240 minutes behind UTC", () => {
  assertEquals(etOffsetMinutes("2026-07-27"), 240);
});

Deno.test("etOffsetMinutes: EST (January) is 300 minutes behind UTC", () => {
  assertEquals(etOffsetMinutes("2026-01-15"), 300);
});

Deno.test("etHHMMToUtcMs: 09:30 ET in EDT -> 13:30 UTC (spec's stated example)", () => {
  const ms = etHHMMToUtcMs("2026-07-27", "09:30");
  assertEquals(new Date(ms).toISOString(), "2026-07-27T13:30:00.000Z");
});

Deno.test("etHHMMToUtcMs: 16:00 ET in EDT -> 20:00 UTC (spec's stated close time)", () => {
  const ms = etHHMMToUtcMs("2026-07-27", "16:00");
  assertEquals(new Date(ms).toISOString(), "2026-07-27T20:00:00.000Z");
});

Deno.test("etHHMMToUtcMs: 16:00 ET in EST -> 21:00 UTC", () => {
  const ms = etHHMMToUtcMs("2026-01-15", "16:00");
  assertEquals(new Date(ms).toISOString(), "2026-01-15T21:00:00.000Z");
});

Deno.test("isBarPartial: a clean top-of-hour bar fully inside the session -> not partial", () => {
  assertEquals(isBarPartial(BAR1, SESSION), false);
});

Deno.test("isBarPartial: session-open stub (starts before session open) -> partial", () => {
  // 13:00Z starts before the 13:30Z (09:30 ET EDT) session open.
  assertEquals(isBarPartial(BAR0, SESSION), true);
});

Deno.test("isBarPartial: not top-of-hour -> partial", () => {
  assertEquals(isBarPartial({ timestamp: "2026-07-27T14:07:00Z" }, SESSION), true);
});

Deno.test("isBarPartial: session-close stub (ends after session close) -> partial", () => {
  // Session closes 20:00Z; a bar 19:30-20:30Z is not fully inside.
  assertEquals(isBarPartial({ timestamp: "2026-07-27T19:30:00Z" }, SESSION), true);
});

// ---------------------------------------------------------------------------
// Sizing / geometry (pure) -- spec §6 worked examples, verbatim
// ---------------------------------------------------------------------------

Deno.test("computeBracketGeometry: LONG stop = barLow - buffer, target = entry + 2*stopDistance", () => {
  const geom = computeBracketGeometry("LONG", { high: 553, low: 548 }, 550, {
    hourlyStopBufferPct: 0.05,
    hourlyBracketRMultiple: 2,
  });
  assertEquals(geom.stopPrice, 547.75);
  assertEquals(geom.targetPrice, 550 + 2 * (550 - 547.75));
});

Deno.test("computeBracketGeometry: SHORT stop = barHigh + buffer, target = entry - 2*stopDistance", () => {
  const geom = computeBracketGeometry("SHORT", { high: 553, low: 548 }, 550, {
    hourlyStopBufferPct: 0.05,
    hourlyBracketRMultiple: 2,
  });
  assertEquals(geom.stopPrice, 553.25);
});

Deno.test("computeSizing: §6 worked example verbatim -- notional cap binds (qty=18)", () => {
  const s = computeSizing("LONG", 550.00, 547.75, 100000, {
    sizingRiskPct: 0.01,
    sizingNotionalCapPct: 0.10,
    hourlyMinStopDistance: 0.05,
  });
  assertEquals(s.valid, true);
  assertEquals(s.qtyRisk, 444);
  assertEquals(s.qtyCap, 18);
  assertEquals(s.qty, 18);
});

Deno.test("computeSizing: §6 second example -- notional cap still binds at $550 with an $11 stop", () => {
  const s = computeSizing("LONG", 550.00, 539.00, 100000, {
    sizingRiskPct: 0.01,
    sizingNotionalCapPct: 0.10,
    hourlyMinStopDistance: 0.05,
  });
  assertEquals(s.qtyRisk, 90);
  assertEquals(s.qtyCap, 18);
  assertEquals(s.qty, 18);
});

Deno.test("computeSizing: low-price flip -- risk cap binds instead (qty=90)", () => {
  const s = computeSizing("LONG", 25.00, 14.00, 100000, {
    sizingRiskPct: 0.01,
    sizingNotionalCapPct: 0.10,
    hourlyMinStopDistance: 0.05,
  });
  assertEquals(s.qtyRisk, 90);
  assertEquals(s.qtyCap, 400);
  assertEquals(s.qty, 90);
});

Deno.test("computeSizing: inverted geometry (entry on the wrong side of stop) -> invalid", () => {
  const s = computeSizing("LONG", 546.00, 547.75, 100000, {
    sizingRiskPct: 0.01,
    sizingNotionalCapPct: 0.10,
    hourlyMinStopDistance: 0.05,
  });
  assertEquals(s.valid, false);
});

Deno.test("computeSizing: distance below HOURLY_MIN_STOP_DISTANCE -> invalid", () => {
  const s = computeSizing("LONG", 550.00, 549.98, 100000, {
    sizingRiskPct: 0.01,
    sizingNotionalCapPct: 0.10,
    hourlyMinStopDistance: 0.05,
  });
  assertEquals(s.valid, false);
});

Deno.test("computeSizing: wide stop + low equity -> qty=0 (size_too_small, not an error)", () => {
  const s = computeSizing("LONG", 550.00, 400.00, 500, {
    sizingRiskPct: 0.01,
    sizingNotionalCapPct: 0.10,
    hourlyMinStopDistance: 0.05,
  });
  assertEquals(s.valid, true);
  assertEquals(s.qty, 0);
});

// ---------------------------------------------------------------------------
// Gate ladder -- one test per row of the sub-plan's T9 table
// ---------------------------------------------------------------------------

Deno.test("gate 1: bot_config.paused -> skipped:trading_paused, no broker call", async () => {
  const { deps, rec } = buildDeps();
  deps.db.getConfig = (key) => Promise.resolve(key === "paused" ? "true" : null);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:trading_paused");
  assertEquals(lastOutcome(rec), "skipped:trading_paused");
});

Deno.test("gate 2: Layer-B paper assert fails -> error:PaperGuardFailed", async () => {
  const { deps, rec } = buildDeps();
  class PaperGuardFailedError extends Error {
    override name = "PaperGuardFailed";
  }
  deps.alpaca.assertPaperAccount = () => Promise.reject(new PaperGuardFailedError("nope"));
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "error:PaperGuardFailed");
  assertEquals(lastOutcome(rec), "error:PaperGuardFailed");
});

Deno.test("gate 3: market closed -> skipped:market_closed", async () => {
  const { deps } = buildDeps();
  deps.alpaca.getClock = () => Promise.resolve({ isOpen: false, nextClose: 0 });
  assertEquals(await runHourlyCheck(deps), "skipped:market_closed");
});

Deno.test("gate 4: naked position (no resting legs, no provenance) -> error:naked_position_flattened", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.getPosition = () => Promise.resolve(18); // open long position
  deps.alpaca.listOpenOrderIds = () => Promise.resolve([]); // no resting legs
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "error:naked_position_flattened");
  // market-closed the naked long via a SELL, journaled as hourly_bracket_exit.
  assertEquals(rec.trades.length, 1);
  assertEquals(rec.trades[0].side, "SELL");
  assertEquals(rec.trades[0].reason, "hourly_bracket_exit");
});

Deno.test("gate 4: naked position WITH provenance -> success:legs_replaced, supersedes the ordinary outcome", async () => {
  const { deps } = buildDeps();
  deps.alpaca.getPosition = () => Promise.resolve(18);
  deps.alpaca.listOpenOrderIds = () => Promise.resolve([]);
  deps.db.getTradesSince = () =>
    Promise.resolve([{
      symbol: "SPY",
      side: "BUY",
      qty: 18,
      fill_price: 550,
      fill_time: "2026-07-27T14:05:00Z",
      reason: "hourly_long_entry",
      broker_order_id: "bracket1",
    }]);
  deps.db.getHourlyScanByEntryOrderId = () =>
    Promise.resolve({
      symbol: "SPY",
      bar_ts: "2026-07-27T14:00:00Z",
      decision: "LONG",
      skip_reason: null,
      detectors_fired: ["bullish_marubozu"],
      context_mode: "none",
      entry_ref_price: 550,
      stop_price: 547.75,
      target_price: 554.5,
      risk_per_share: 2.25,
      equity_usd: 100000,
      qty: 18,
      entry_order_id: "bracket1",
    });
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:legs_replaced");
});

Deno.test("gate 6: missing hourly_experiment_start_equity baseline -> hard error, never silently inert", async () => {
  const { deps } = buildDeps();
  deps.db.getConfig = (key) =>
    Promise.resolve(key === "hourly_experiment_start_equity" ? null : null);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "error:DataError");
});

Deno.test("gate 6: equity <= 85% of baseline -> success:auto_paused, sets bot_config.paused=true", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.assertPaperAccount = () => Promise.resolve({ equity: 84999 }); // < 85000 = 15% down from 100000
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:auto_paused");
  assertEquals(rec.configSets, [["paused", "true"]]);
});

Deno.test("gate 7: no completed bars -> skipped:stale_data", async () => {
  const { deps } = buildDeps();
  deps.marketdata.getHourlyBars = () => Promise.resolve([]);
  assertEquals(await runHourlyCheck(deps), "skipped:stale_data");
});

Deno.test("gate 7: partial candidate bar -> skipped:partial_bar (precedence: before staleness)", async () => {
  // now=14:07Z: the session-open stub (13:00-14:00Z) is completed (its end,
  // 14:00Z, is <= now) but starts before the 13:30Z session open -- partial.
  // It would ALSO be within the staleness tolerance if that guard ran first
  // (7 min < 10 min default), so this only passes if partial-bar exclusion
  // truly runs before the staleness guard (spec §4's fixed precedence).
  const { deps, rec } = buildDeps("2026-07-27T14:07:00Z");
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([{
      timestamp: "2026-07-27T13:00:00Z",
      open: 548,
      high: 548.5,
      low: 547.5,
      close: 548,
    }]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:partial_bar");
  assertEquals(rec.scans.length, 0); // pre-bar-decision gate: audit only
});

Deno.test("gate 7: stale candidate bar (beyond tolerance) -> skipped:stale_data", async () => {
  // The candidate bar (14:00-15:00Z) is a clean, non-partial top-of-hour bar
  // fully inside the session -- but "now" is 15 minutes past its end,
  // beyond the 10-minute default tolerance.
  const { deps } = buildDeps("2026-07-27T15:15:00Z");
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:stale_data");
});

Deno.test("gate 9: flatten scan downgrades a would-be LONG entry -> skipped:session_close_flatten_only", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.getClock = () =>
    Promise.resolve({ isOpen: true, nextClose: new Date("2026-07-27T15:37:00Z").getTime() }); // 30 min away
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:session_close_flatten_only");
  assertEquals(rec.scans[0].decision, "SKIP");
  assertEquals(rec.scans[0].skipReason, "session_close_flatten_only");
});

Deno.test("gate 10: kill-switch active, same side -> skipped:kill_switch_active", async () => {
  const { deps } = buildDeps();
  deps.db.getConfig = (key) => {
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("LONG");
    return Promise.resolve(null);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:kill_switch_active");
});

Deno.test("gate 10: kill-switch active + SKIP decision -> still skipped:kill_switch_active (resolves the row-10-vs-11 ambiguity)", async () => {
  const { deps } = buildDeps();
  // A doji-only bar: no directional fire, decision=SKIP.
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      BAR0,
      { timestamp: "2026-07-27T14:00:00Z", open: 550, high: 550.5, low: 549.5, close: 550.25 },
    ]);
  deps.db.getConfig = (key) => {
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("SHORT");
    return Promise.resolve(null);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:kill_switch_active");
});

Deno.test("gate 10: kill-switch active, opposite side -> clears the flag atomically and enters", async () => {
  const { deps, rec } = buildDeps();
  deps.db.getConfig = (key) => {
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("SHORT"); // decision is LONG -> opposite
    return Promise.resolve(null);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals(
    rec.configSets.some(([k, v]) => k === "hourly_kill_switch_active" && v === "false"),
    true,
  );
});

Deno.test("gate 11: signal conflict -> skipped:signal_conflict", async () => {
  const { deps } = buildDeps();
  // bullish_harami + shooting_star on the same bar (§5 worked example).
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      { timestamp: "2026-07-27T13:00:00Z", open: 110, high: 111, low: 89, close: 90 },
      { timestamp: "2026-07-27T14:00:00Z", open: 100, high: 103.2, low: 99.8, close: 101 },
    ]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:signal_conflict");
});

Deno.test("gate 11: no detectors fired -> success:no_action", async () => {
  const { deps } = buildDeps();
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      BAR0,
      { timestamp: "2026-07-27T14:00:00Z", open: 550, high: 550.05, low: 549.95, close: 550.02 },
    ]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:no_action");
});

Deno.test("gate 12: broker-sourced position open blocks a new entry -> skipped:position_open", async () => {
  const { deps } = buildDeps();
  deps.alpaca.getPosition = () => Promise.resolve(5);
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["resting1"]); // legs present -- no naked-position path
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:position_open");
});

Deno.test("gate 13: cooldown -- signal bar not strictly after the last exit's fill_time -> skipped:cooldown", async () => {
  const { deps } = buildDeps();
  deps.db.getTradesSince = () =>
    Promise.resolve([{
      symbol: "SPY",
      side: "SELL",
      qty: 18,
      fill_price: 551,
      fill_time: "2026-07-27T14:30:00Z", // after bar1's 14:00Z start
      reason: "hourly_bracket_exit",
      broker_order_id: "exit1",
    }]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:cooldown");
});

Deno.test("gate 14: day cap reached -> skipped:max_entries_reached", async () => {
  const { deps } = buildDeps();
  deps.config.hourlyMaxEntriesPerDay = 1;
  deps.db.getTradesSince = () =>
    Promise.resolve([{
      symbol: "SPY",
      side: "BUY",
      qty: 18,
      fill_price: 549,
      fill_time: "2026-07-27T09:05:00Z",
      reason: "hourly_long_entry",
      broker_order_id: "earlier1",
    }]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:max_entries_reached");
});

Deno.test("gate 15: SHORT decision, shorts disabled -> skipped:shorts_disabled", async () => {
  const { deps } = buildDeps();
  deps.config.hourlyShortsEnabled = false;
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      BAR0,
      { timestamp: "2026-07-27T14:00:00Z", open: 552.9, high: 553, low: 548, close: 548.1 }, // bearish_marubozu
    ]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:shorts_disabled");
});

Deno.test("gate 16: SHORT decision, not shortable (fail-closed) -> skipped:not_shortable", async () => {
  const { deps } = buildDeps();
  deps.alpaca.getAssetShortability = () =>
    Promise.resolve({ shortable: false, easyToBorrow: false });
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      BAR0,
      { timestamp: "2026-07-27T14:00:00Z", open: 552.9, high: 553, low: 548, close: 548.1 },
    ]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:not_shortable");
});

Deno.test("gate 17: geometry invalid (entryRef moved to the wrong side of stop) -> skipped:geometry_invalid", async () => {
  const { deps, rec } = buildDeps();
  deps.marketdata.getLatestTradePrice = () => Promise.resolve(500); // below the 547.75 LONG stop
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:geometry_invalid");
  // sizing columns ARE computed and journaled ("null unless computed").
  assertEquals(rec.scans[0].entryRefPrice, 500);
  assertEquals(rec.scans[0].stopPrice, 547.75);
});

Deno.test("gate 18: qty <= 0 -> skipped:size_too_small (a normal skip, not an error)", async () => {
  const { deps, rec } = buildDeps();
  // Shrink both the risk budget and the notional cap so qty floors to 0
  // without touching the baseline (stays at the default 100000, matching
  // equityAtStart -- the -15% floor never fires here).
  deps.config.sizingNotionalCapPct = 0.0000001;
  deps.config.sizingRiskPct = 0.0000001;
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:size_too_small");
  assertEquals(rec.scans[0].qty, 0);
});

Deno.test("gate 19: duplicate claim -> skipped:duplicate_run, loser never upserts hourly_scans", async () => {
  const { deps, rec } = buildDeps();
  deps.db.claimBar = (_scriptName, barTs) => {
    rec.claimCalls.push(barTs);
    return Promise.resolve(false);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:duplicate_run");
  assertEquals(rec.scans.length, 0);
});

Deno.test("gate 20: happy path -- places a LONG bracket, journals the scan and the trade", async () => {
  const { deps, rec } = buildDeps();
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals(rec.trades.length, 1);
  assertEquals(rec.trades[0].reason, "hourly_long_entry");
  assertEquals(rec.trades[0].qty, 18);
  // journal called twice: pre-order (entryOrderId null) then post-order (set).
  assertEquals(rec.scans.length, 2);
  assertEquals(rec.scans[0].entryOrderId, null);
  assertEquals(rec.scans[1].entryOrderId, "bracket1");
  assertEquals(rec.scans[1].qty, 18);
});

Deno.test("gate 20: SHORT entry uses the plain-entry + OCO fallback (bracket-on-short unconfirmed)", async () => {
  const { deps, rec } = buildDeps();
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      BAR0,
      { timestamp: "2026-07-27T14:00:00Z", open: 552.9, high: 553, low: 548, close: 548.1 }, // bearish_marubozu
    ]);
  let ocoCalled = false;
  deps.alpaca.placeOcoExitPair = (_args) => {
    ocoCalled = true;
    return Promise.resolve({ orderId: "oco1" });
  };
  deps.alpaca.placeMarketOrder = (_args) =>
    Promise.resolve(fill({ orderId: "mkt-short1", qty: 18 }));
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals(ocoCalled, true);
  assertEquals(rec.trades[0].reason, "hourly_short_entry");
  assertEquals(rec.trades[0].side, "SELL");
});

// ---------------------------------------------------------------------------
// Flatten scan reconciliation ordering (T11)
// ---------------------------------------------------------------------------

Deno.test("flatten scan: cancels resting legs before closing the position, journals hourly_session_close_exit", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.getClock = () =>
    Promise.resolve({ isOpen: true, nextClose: new Date("2026-07-27T15:37:00Z").getTime() }); // <=1h away
  deps.alpaca.getPosition = () => Promise.resolve(18); // open long
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // legs resting -- not naked
  deps.alpaca.placeMarketOrder = (_args) => Promise.resolve(fill({ orderId: "flatten1", qty: 18 }));
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:session_close_flatten_only");
  assertEquals(rec.cancelledOrderIds, ["leg-tp", "leg-sl"]);
  assertEquals(rec.trades.some((t) => t.reason === "hourly_session_close_exit"), true);
});

Deno.test("duplicate claim never touches the hourly_scans row (winner already wrote it)", async () => {
  const { deps, rec } = buildDeps();
  let calls = 0;
  deps.db.claimBar = (_scriptName, barTs) => {
    calls++;
    rec.claimCalls.push(barTs);
    return Promise.resolve(calls === 1);
  };
  const first = await runHourlyCheck(deps);
  const scansAfterFirst = rec.scans.length;
  const second = await runHourlyCheck(deps);
  assertEquals(first, "success");
  assertEquals(second, "skipped:duplicate_run");
  assertEquals(rec.scans.length, scansAfterFirst); // no new row from the loser
});
