import { assertEquals } from "@std/assert";
import { type ClosedOrderFill, type Fill, SubPennyPriceError } from "../_shared/alpaca.ts";
import type { HourlyConfig } from "../_shared/config.ts";
import { coerceHourlyScanRow, type HourlyScanRow, type TradeRow } from "../_shared/db.ts";
import { decideHourly } from "../_shared/hourly_signal.ts";
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

  // #480 T4: getTradesSince defaults to reading this array, and the default
  // insertTrade appends to it -- so a trade the pipeline inserts mid-run
  // (e.g. reconcile()'s recovery step, or exit-fill discovery) is visible to
  // a LATER getTradesSince call in the same run (gate 13/14's own lookback
  // read) without any test needing to hand-wire the two together. Starts
  // empty, matching every existing test's prior (constant-[]) expectation;
  // only tests that don't override getTradesSince/insertTrade observe it.
  const tradesDb: TradeRow[] = [];

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
      getTradesSince: (_sinceIso) => Promise.resolve([...tradesDb]),
      upsertHourlyScan: (p) => {
        rec.scans.push(p);
        return Promise.resolve();
      },
      getHourlyScanByEntryOrderId: (_symbol, _orderId) =>
        Promise.resolve(null as HourlyScanRow | null),
      getHourlyScansPendingEntry: (_symbol, _sinceIso) => Promise.resolve([] as HourlyScanRow[]),
      claimBar: (_scriptName, barTs) => {
        rec.claimCalls.push(barTs);
        return Promise.resolve(true);
      },
      insertTrade: (p) => {
        rec.trades.push(p);
        tradesDb.push({
          symbol: p.symbol,
          side: p.side,
          qty: p.qty,
          fill_price: p.fillPrice,
          fill_time: p.fillTime,
          reason: p.reason,
          broker_order_id: p.brokerOrderId,
        });
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
// #494 group B: bracket geometry is quantized to whole cents, stop first.
// The bar shape is the 2026-07-30 live session: a bar range on 2 decimals
// times the 0.05 buffer yields a 4-decimal stop, and the target's x2 then
// lands on a tenth of a cent.
// ---------------------------------------------------------------------------

const GEOM_CFG = { hourlyStopBufferPct: 0.05, hourlyBracketRMultiple: 2 };

/** The live 2026-07-30 bar shape that produced the rejected prices. */
const LIVE_BAR = { high: 745.73, low: 744.28 };
const LIVE_ENTRY_REF = 745.02;

/** at most two decimals, no float artifact */
const CENT_CLEAN = /^-?\d+(\.\d{1,2})?$/;

Deno.test("B7 computeBracketGeometry: every returned price serializes to at most two decimals", () => {
  // The serialization contract, which the exact-literal cases below cannot
  // express on their own.
  const cases: Array<[{ high: number; low: number }, number]> = [
    [LIVE_BAR, LIVE_ENTRY_REF],
    [{ high: 745.80, low: 744.30 }, 745.00],
    [{ high: 100.07, low: 99.93 }, 100.01],
    [{ high: 12.34, low: 12.11 }, 12.30],
    [{ high: 553, low: 548 }, 550],
  ];
  for (const action of ["LONG", "SHORT"] as const) {
    for (const [bar, entryRef] of cases) {
      const geom = computeBracketGeometry(action, bar, entryRef, GEOM_CFG);
      assertEquals(
        CENT_CLEAN.test(String(geom.stopPrice)),
        true,
        `${action} ${JSON.stringify(bar)} stop -> ${String(geom.stopPrice)}`,
      );
      assertEquals(
        CENT_CLEAN.test(String(geom.targetPrice)),
        true,
        `${action} ${JSON.stringify(bar)} target -> ${String(geom.targetPrice)}`,
      );
    }
  }
});

Deno.test("B8 computeBracketGeometry: the live 2026-07-30 LONG bar -> 744.21 / 746.64, not 744.2075 / 746.645", () => {
  const geom = computeBracketGeometry("LONG", LIVE_BAR, LIVE_ENTRY_REF, GEOM_CFG);
  assertEquals(geom.stopPrice, 744.21);
  assertEquals(geom.targetPrice, 746.64);
});

Deno.test("B9 computeBracketGeometry: the SHORT mirror of the same bar is quantized too", () => {
  const geom = computeBracketGeometry("SHORT", LIVE_BAR, LIVE_ENTRY_REF, GEOM_CFG);
  assertEquals(geom.stopPrice, 745.8);
  assertEquals(geom.targetPrice, 743.46);
});

Deno.test("B10 computeBracketGeometry: the target is derived from the ROUNDED stop (746.56, not 746.55)", () => {
  // Ordering pin, not a quantization pin. On this bar the raw stop is
  // 744.2249999999999 and the raw target 746.5500000000002. Rounding the two
  // independently gives 744.22 / 746.55; rounding the stop first and deriving
  // the target from it gives 744.22 / 746.56. Only the second keeps wire R at
  // exactly 2x the wire risk (see B11), which is why the ordering is frozen.
  const geom = computeBracketGeometry("LONG", { high: 745.80, low: 744.30 }, 745.00, GEOM_CFG);
  assertEquals(geom.stopPrice, 744.22);
  assertEquals(geom.targetPrice, 746.56);
});

Deno.test("B11 computeBracketGeometry: wire R holds in the numbers the broker receives", () => {
  // take_profit - entryRef == R * (entryRef - stop_loss), in whole cents, so
  // the journal's risk denominator matches what the broker is holding.
  const entryRef = 745.00;
  const geom = computeBracketGeometry("LONG", { high: 745.80, low: 744.30 }, entryRef, GEOM_CFG);
  const cents = (v: number) => Math.round(v * 100);
  assertEquals(cents(geom.targetPrice - entryRef), 2 * cents(entryRef - geom.stopPrice));
});

Deno.test("B12 computeBracketGeometry: quantization is a no-op on already-penny geometry (§6 example)", () => {
  const long = computeBracketGeometry("LONG", { high: 553, low: 548 }, 550, GEOM_CFG);
  assertEquals(String(long.stopPrice), "547.75");
  assertEquals(String(long.targetPrice), "554.5");
  const short = computeBracketGeometry("SHORT", { high: 553, low: 548 }, 550, GEOM_CFG);
  assertEquals(String(short.stopPrice), "553.25");
  assertEquals(String(short.targetPrice), "543.5");
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

Deno.test("gate 7: no completed bars -> skipped:stale_data, audit only (no hourly_scans row -- no candidate bar exists)", async () => {
  const { deps, rec } = buildDeps();
  deps.marketdata.getHourlyBars = () => Promise.resolve([]);
  assertEquals(await runHourlyCheck(deps), "skipped:stale_data");
  assertEquals(rec.scans.length, 0);
});

Deno.test("gate 7: partial candidate bar -> skipped:partial_bar (precedence: before staleness), journals a SKIP row keyed to the candidate bar", async () => {
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
  // must-fix round 1 finding 2: a bar-level skip (candidate bar known) is
  // journaled, not audit-only.
  assertEquals(rec.scans.length, 1);
  assertEquals(rec.scans[0].decision, "SKIP");
  assertEquals(rec.scans[0].skipReason, "partial_bar");
  assertEquals(rec.scans[0].barTs, "2026-07-27T13:00:00Z");
  assertEquals(rec.scans[0].detectorsFired, []);
  assertEquals(rec.scans[0].qty, 0);
  assertEquals(rec.scans[0].entryOrderId, null);
});

Deno.test("gate 7: stale candidate bar (beyond tolerance) -> skipped:stale_data, journals a SKIP row keyed to the candidate bar", async () => {
  // The candidate bar (14:00-15:00Z) is a clean, non-partial top-of-hour bar
  // fully inside the session -- but "now" is 15 minutes past its end,
  // beyond the 10-minute default tolerance.
  const { deps, rec } = buildDeps("2026-07-27T15:15:00Z");
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:stale_data");
  assertEquals(rec.scans.length, 1);
  assertEquals(rec.scans[0].decision, "SKIP");
  assertEquals(rec.scans[0].skipReason, "stale_data");
  assertEquals(rec.scans[0].barTs, "2026-07-27T14:00:00Z");
  assertEquals(rec.scans[0].detectorsFired, []);
});

// ---------------------------------------------------------------------------
// Partial-bar exclusion from the SIGNAL SERIES (must-fix round 1 finding 1):
// the candidate/signal bar is full, but a t-1 session-edge stub is present.
// Unlike BAR0 (deliberately flat/harmless), this stub is shaped so its
// inclusion actually changes what fires at the signal bar -- proving the old
// (candidate-only) exclusion would have differed.
// ---------------------------------------------------------------------------

const STUB_HARAMI_PRIOR: HourlyBar = {
  // Session-open stub (13:00-14:00Z, partial -- starts before the 13:30Z
  // EDT session open). Wide bearish body (560 -> 540) that fully contains
  // BAR1's bullish body (548.1 -> 552.9): if included as t-1, this fires
  // bullish_harami at BAR1 on top of BAR1's own bullish_marubozu.
  timestamp: "2026-07-27T13:00:00Z",
  open: 560,
  high: 561,
  low: 539,
  close: 540,
};

Deno.test("decideHourly series: a t-1 session-edge stub is excluded from the signal even though the candidate bar is full", async () => {
  const { deps, rec } = buildDeps(); // now=15:07Z, candidate=BAR1 (14:00-15:00Z, non-partial)
  deps.marketdata.getHourlyBars = () => Promise.resolve([STUB_HARAMI_PRIOR, BAR1]);
  const outcome = await runHourlyCheck(deps);
  // Fixed behavior: the stub is excluded from decideHourly's series (it is
  // partial against its own session), so bullish_harami -- a 2-bar pattern --
  // cannot fire at BAR1; only bullish_marubozu (single-bar) fires, and the
  // run enters LONG exactly as it does with the harmless BAR0 stub.
  assertEquals(outcome, "success");
  assertEquals(rec.scans[0].detectorsFired, ["bullish_marubozu"]);
});

Deno.test("decideHourly series: proves the OLD (candidate-only) exclusion would have differed -- the unfiltered series also fires bullish_harami", () => {
  // Direct proof against the pure function: feeding the UNFILTERED
  // [stub, BAR1] series (what the buggy code passed) into decideHourly fires
  // bullish_harami in addition to bullish_marubozu -- an observable
  // difference from the fixed series-filtered behavior above.
  const unfiltered = decideHourly([STUB_HARAMI_PRIOR, BAR1], { contextMode: "none" });
  assertEquals(unfiltered.detectorsFired.includes("bullish_harami"), true);
  assertEquals(unfiltered.detectorsFired.includes("bullish_marubozu"), true);
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

Deno.test("gate 10: kill-switch active, opposite side -> a SUCCESSFUL entry clears all three keys (lead ruling, fix round 1 finding 4)", async () => {
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
  assertEquals(
    rec.configSets.some(([k, v]) => k === "hourly_kill_switch_side" && v === ""),
    true,
  );
  assertEquals(
    rec.configSets.some(([k, v]) => k === "hourly_kill_switch_fired_at" && v === ""),
    true,
  );
});

Deno.test("gate 10: opposite-side decision BLOCKED by a later gate (shorts_disabled) leaves all three kill-switch keys untouched (lead ruling, fix round 1 finding 4)", async () => {
  const { deps, rec } = buildDeps();
  // Kill-switch side is LONG; the bar's own signal is SHORT (bearish
  // marubozu) -- opposite side, so gate 10 lets it through -- but
  // HOURLY_SHORTS_ENABLED=false blocks it at gate 15, before any order is
  // placed. The flag must NOT have been cleared: clearing is deferred to a
  // successfully placed entry order (step 20), never to merely passing
  // gate 10.
  deps.config.hourlyShortsEnabled = false;
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      BAR0,
      { timestamp: "2026-07-27T14:00:00Z", open: 552.9, high: 553, low: 548, close: 548.1 }, // bearish_marubozu
    ]);
  deps.db.getConfig = (key) => {
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("LONG");
    return Promise.resolve(null);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:shorts_disabled");
  assertEquals(rec.configSets.some(([k]) => k.startsWith("hourly_kill_switch_")), false);
});

Deno.test("gate 9/10 ordering: flatten scan + kill-switch active + opposite-side decision -> keys survive (gate 9 runs before gate 10)", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.getClock = () =>
    Promise.resolve({ isOpen: true, nextClose: new Date("2026-07-27T15:37:00Z").getTime() }); // <=1h away -> flatten scan
  deps.db.getConfig = (key) => {
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("SHORT"); // decision is LONG -> opposite
    return Promise.resolve(null);
  };
  const outcome = await runHourlyCheck(deps);
  // Flatten-scan downgrade (gate 9) fires before the kill-switch gate (gate
  // 10) ever runs, so an opposite-side decision on a flatten scan can never
  // clear the flag -- pinning the round-2 nit's stated ordering.
  assertEquals(outcome, "skipped:session_close_flatten_only");
  assertEquals(rec.configSets.some(([k]) => k.startsWith("hourly_kill_switch_")), false);
});

Deno.test("gate 11: signal conflict -> skipped:signal_conflict", async () => {
  // now=16:07Z so the candidate (15:00-16:00Z) is non-partial (fully inside
  // the 13:30-20:00Z session) -- both bars here must be non-partial per
  // their own session, since a partial t-1 bar is now excluded from the
  // signal series (must-fix round 1 finding 1) and this test's conflict
  // depends on the 2-bar bullish_harami pattern seeing its prior bar.
  const { deps } = buildDeps("2026-07-27T16:07:00Z");
  // bullish_harami + shooting_star on the same bar (§5 worked example).
  deps.marketdata.getHourlyBars = () =>
    Promise.resolve([
      { timestamp: "2026-07-27T14:00:00Z", open: 110, high: 111, low: 89, close: 90 },
      { timestamp: "2026-07-27T15:00:00Z", open: 100, high: 103.2, low: 99.8, close: 101 },
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

Deno.test("gate 13: cooldown boundary -- signal bar start EXACTLY EQUAL to the last exit's fill_time -> skipped:cooldown (should-fix finding 8)", async () => {
  const { deps } = buildDeps();
  // BAR1 (the candidate/signal bar) starts at 2026-07-27T14:00:00Z. An exit
  // fill_time of exactly that instant must still block re-entry -- "strictly
  // after" (spec §5) is a `<=` comparison, not `<`.
  deps.db.getTradesSince = () =>
    Promise.resolve([{
      symbol: "SPY",
      side: "SELL",
      qty: 18,
      fill_price: 551,
      fill_time: "2026-07-27T14:00:00Z",
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
// #494 group C: the quantized prices reach the wire, the journal, and the
// re-leg path. Same bar shape as group B, through the whole pipeline.
// ---------------------------------------------------------------------------

// Same wick/body proportions as BAR1 (a clean bullish_marubozu), scaled to the
// price level of the 2026-07-30 session so the raw stop lands on 4 decimals.
const LIVE_BAR0: HourlyBar = {
  timestamp: "2026-07-27T13:00:00Z",
  open: 744.30,
  high: 744.60,
  low: 744.00,
  close: 744.30,
};
const LIVE_BAR1: HourlyBar = {
  timestamp: "2026-07-27T14:00:00Z",
  open: 744.31,
  high: 745.73,
  low: 744.28,
  close: 745.70,
};

function buildLiveDeps(entryRef = 745.02) {
  const built = buildDeps();
  built.deps.marketdata.getHourlyBars = () => Promise.resolve([LIVE_BAR0, LIVE_BAR1]);
  built.deps.marketdata.getLatestTradePrice = () => Promise.resolve(entryRef);
  return built;
}

Deno.test("C13 entry path: placeBracketOrder receives whole-cent prices for the live bar", async () => {
  const { deps } = buildLiveDeps();
  let sent: { takeProfitPrice: number; stopLossPrice: number } | null = null;
  deps.alpaca.placeBracketOrder = (args) => {
    sent = { takeProfitPrice: args.takeProfitPrice, stopLossPrice: args.stopLossPrice };
    return Promise.resolve(fill({ orderId: "bracket1" }));
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success");
  const wire = sent as unknown as { takeProfitPrice: number; stopLossPrice: number };
  assertEquals(wire.stopLossPrice, 744.21);
  assertEquals(wire.takeProfitPrice, 746.64);
});

Deno.test("C14 journal: hourly_scans stop_price / target_price are whole cents on both writes", async () => {
  const { deps, rec } = buildLiveDeps();
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals(rec.scans.length, 2);
  for (const scan of rec.scans) {
    assertEquals(scan.stopPrice, 744.21);
    assertEquals(scan.targetPrice, 746.64);
  }
});

Deno.test("C15 re-leg path: journaled geometry survives the numeric(14,4) round-trip penny-clean", async () => {
  // The naked-position rule reads provenance back through PostgREST, which
  // renders numeric columns as strings. A sub-penny stored value round-trips
  // sub-penny and gets the OCO pair rejected, which drops the position into
  // the market-close flatten instead of re-protecting it (#494 scope item 3).
  const { deps: entryDeps, rec } = buildLiveDeps();
  assertEquals(await runHourlyCheck(entryDeps), "success");
  const journaled = rec.scans[1];

  // What Postgres stores in numeric(14,4) and PostgREST hands back.
  const raw = {
    symbol: "SPY",
    bar_ts: "2026-07-27T14:00:00Z",
    decision: "LONG",
    skip_reason: null,
    detectors_fired: ["bullish_marubozu"],
    context_mode: "none",
    entry_ref_price: "745.0200",
    stop_price: journaled.stopPrice?.toFixed(4),
    target_price: journaled.targetPrice?.toFixed(4),
    risk_per_share: "0.8100",
    equity_usd: "100000.00",
    qty: 13,
    entry_order_id: "bracket1",
  };
  assertEquals(raw.stop_price, "744.2100");
  assertEquals(raw.target_price, "746.6400");

  const provenance = coerceHourlyScanRow(raw as unknown as Record<string, unknown>);

  const { deps } = buildDeps();
  deps.alpaca.getPosition = () => Promise.resolve(13);
  deps.alpaca.listOpenOrderIds = () => Promise.resolve([]);
  deps.db.getTradesSince = () =>
    Promise.resolve([{
      symbol: "SPY",
      side: "BUY",
      qty: 13,
      fill_price: 745.02,
      fill_time: "2026-07-27T14:05:00Z",
      reason: "hourly_long_entry",
      broker_order_id: "bracket1",
    }]);
  deps.db.getHourlyScanByEntryOrderId = () => Promise.resolve(provenance);
  let sent: { takeProfitPrice: number; stopLossPrice: number } | null = null;
  deps.alpaca.placeOcoExitPair = (args) => {
    sent = { takeProfitPrice: args.takeProfitPrice, stopLossPrice: args.stopLossPrice };
    return Promise.resolve({ orderId: "oco1" });
  };
  assertEquals(await runHourlyCheck(deps), "success:legs_replaced");
  const wire = sent as unknown as { takeProfitPrice: number; stopLossPrice: number };
  assertEquals(String(wire.stopLossPrice), "744.21");
  assertEquals(String(wire.takeProfitPrice), "746.64");
});

Deno.test("C16 journal: entry_ref_price and risk_per_share are deliberately NOT quantized", async () => {
  // entry_ref_price is an observation (never on the wire) -- rounding it
  // falsifies the record of what the bot saw. risk_per_share is the weekly
  // review's R denominator, also never on the wire. Only the two wire values
  // are quantized; this pins that so nobody "helpfully" rounds the rest.
  const entryRef = 745.0234;
  const { deps, rec } = buildLiveDeps(entryRef);
  assertEquals(await runHourlyCheck(deps), "success");
  const scan = rec.scans[1];
  assertEquals(scan.entryRefPrice, entryRef);
  assertEquals(scan.riskPerShare, entryRef - 744.21);
  assertEquals(scan.stopPrice, 744.21);
});

Deno.test("a sub-penny rejection on the entry path still ALERTS (#494 review finding 1)", async () => {
  // The Alpaca 422 this check replaces raised notifyBrokerError, and that
  // alert is how #494 was found at all. SubPennyPriceError therefore extends
  // AlpacaError so logic.ts's `instanceof AlpacaError` catch keeps firing --
  // a silent audit row would make the next recurrence invisible.
  const { deps, rec } = buildLiveDeps();
  deps.alpaca.placeBracketOrder = () => {
    throw new SubPennyPriceError("takeProfitPrice must be a whole-cent price, got 746.173");
  };
  let alerted: { context: string; errorMsg: string } | null = null;
  deps.notifications.notifyBrokerError = (p) => {
    alerted = p;
    return Promise.resolve();
  };
  assertEquals(await runHourlyCheck(deps), "error:SubPennyPriceError");
  assertEquals(lastOutcome(rec), "error:SubPennyPriceError");
  const sent = alerted as unknown as { context: string; errorMsg: string } | null;
  assertEquals(sent?.context, "hourly-check");
  assertEquals(sent?.errorMsg.includes("whole-cent"), true);
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

Deno.test("recovery: a throwing getHourlyScansPendingEntry does not abort the scan -- the flatten close-out still runs (should-fix finding 3)", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.getClock = () =>
    Promise.resolve({ isOpen: true, nextClose: new Date("2026-07-27T15:37:00Z").getTime() }); // <=1h away -> flatten scan
  deps.alpaca.getPosition = () => Promise.resolve(18); // open long
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // legs resting -- not naked
  deps.alpaca.placeMarketOrder = (_args) => Promise.resolve(fill({ orderId: "flatten1", qty: 18 }));
  deps.db.getHourlyScansPendingEntry = (_symbol, _sinceIso) => {
    throw new Error("db down");
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:session_close_flatten_only");
  assertEquals(rec.cancelledOrderIds, ["leg-tp", "leg-sl"]);
  assertEquals(rec.trades.some((t) => t.reason === "hourly_session_close_exit"), true);
});

Deno.test("recovery: a throwing listFilledOrdersSince during recovery does not abort the scan -- the flatten close-out still runs (should-fix finding 3)", async () => {
  const { deps, rec } = buildDeps();
  deps.alpaca.getClock = () =>
    Promise.resolve({ isOpen: true, nextClose: new Date("2026-07-27T15:37:00Z").getTime() }); // <=1h away -> flatten scan
  deps.alpaca.getPosition = () => Promise.resolve(18); // open long
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // legs resting -- not naked
  deps.alpaca.placeMarketOrder = (_args) => Promise.resolve(fill({ orderId: "flatten1", qty: 18 }));
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pendingScanRow()]);
  deps.alpaca.listFilledOrdersSince = () => {
    throw new Error("broker down");
  };
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

// ---------------------------------------------------------------------------
// Reconciliation: exit-fill discovery bound by the 5-day lookback, not
// lastEntry.fill_time (must-fix round 1 finding 3); dedup across ALL
// journaled trades for the symbol regardless of reason (should-fix finding 5)
// ---------------------------------------------------------------------------

Deno.test("reconciliation: exit-fill discovery (bounded by the 5-day lookback) writes exactly one trade row; a second scan does not re-journal it", async () => {
  const { deps, rec } = buildDeps();
  const lastEntry: TradeRow = {
    symbol: "SPY",
    side: "BUY",
    qty: 18,
    fill_price: 550,
    fill_time: "2026-07-27T14:05:00Z",
    reason: "hourly_long_entry",
    broker_order_id: "entry1",
  };
  const tradesDb: TradeRow[] = [lastEntry];
  deps.config.hourlyMaxEntriesPerDay = 1; // lastEntry already counts today -> no fresh entry this scan
  deps.alpaca.getPosition = () => Promise.resolve(0); // the exit already happened at the broker
  deps.alpaca.listFilledOrdersSince = (_symbol, sinceIso) => {
    // Exercised with a non-empty result (finding 3): the bracket's exit leg
    // was SUBMITTED before the entry's fill_time, so a caller querying
    // `after=lastEntry.fill_time` (the pre-fix behavior) would never see it;
    // the fixed code queries the wider 5-day lookback instead.
    assertEquals(sinceIso < lastEntry.fill_time, true);
    return Promise.resolve([
      { orderId: "entry1", side: "BUY", qty: 18, fillPrice: 550, fillTime: "2026-07-27T14:05:00Z" }, // the entry itself -- must be skipped
      { orderId: "exit1", side: "SELL", qty: 18, fillPrice: 551, fillTime: "2026-07-27T14:50:00Z" },
    ] as ClosedOrderFill[]);
  };
  deps.db.getTradesSince = () => Promise.resolve([...tradesDb]);
  deps.db.insertTrade = (p) => {
    rec.trades.push(p);
    tradesDb.push({
      symbol: p.symbol,
      side: p.side,
      qty: p.qty,
      fill_price: p.fillPrice,
      fill_time: p.fillTime,
      reason: p.reason,
      broker_order_id: p.brokerOrderId,
    });
    return Promise.resolve(tradesDb.length);
  };

  const first = await runHourlyCheck(deps);
  assertEquals(typeof first, "string");
  assertEquals(rec.trades.length, 1);
  assertEquals(rec.trades[0].reason, "hourly_bracket_exit");
  assertEquals(rec.trades[0].brokerOrderId, "exit1");

  const second = await runHourlyCheck(deps);
  assertEquals(typeof second, "string");
  assertEquals(rec.trades.length, 1); // second scan does not re-journal the same exit fill
});

Deno.test("reconciliation: a panic_cli fill on the symbol is not re-journaled as hourly_bracket_exit (dedup across ALL trade reasons, should-fix finding 5)", async () => {
  const { deps, rec } = buildDeps();
  const lastEntry: TradeRow = {
    symbol: "SPY",
    side: "BUY",
    qty: 18,
    fill_price: 550,
    fill_time: "2026-07-27T14:05:00Z",
    reason: "hourly_long_entry",
    broker_order_id: "entry1",
  };
  // A panic_cli fill is NOT in ENTRY_REASONS/EXIT_REASONS, so it is invisible
  // to the entry/exit bookkeeping above -- but it must still be visible to
  // the dedup check, or discovery would re-journal it as hourly_bracket_exit.
  const panicTrade: TradeRow = {
    symbol: "SPY",
    side: "SELL",
    qty: 18,
    fill_price: 551,
    fill_time: "2026-07-27T14:50:00Z",
    reason: "panic_cli",
    broker_order_id: "panic1",
  };
  deps.config.hourlyMaxEntriesPerDay = 1; // stop a fresh entry from muddying the assertion
  deps.alpaca.getPosition = () => Promise.resolve(0); // already flat via panic
  deps.db.getTradesSince = () => Promise.resolve([lastEntry, panicTrade]);
  deps.alpaca.listFilledOrdersSince = (_symbol, _sinceIso) =>
    Promise.resolve([
      {
        orderId: "panic1",
        side: "SELL",
        qty: 18,
        fillPrice: 551,
        fillTime: "2026-07-27T14:50:00Z",
      },
    ] as ClosedOrderFill[]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(typeof outcome, "string");
  assertEquals(rec.trades.length, 0); // the already-journaled panic_cli fill must not be re-journaled
});

// ---------------------------------------------------------------------------
// #480 T1: bounded retry + deterministic degraded outcome at step 20's
// post-fill writes (PR #477 round-2 review finding 2 + corollary).
// ---------------------------------------------------------------------------

Deno.test("step 20: insertTrade fails all attempts -> success:journal_degraded; the journal group is skipped (not attempted), so entry_order_id stays NULL and the row keeps matching the recovery signature (must-fix round 1 finding 1)", async () => {
  const { deps, rec } = buildDeps();
  let insertCalls = 0;
  let journalPostOrderCalls = 0;
  const realUpsert = deps.db.upsertHourlyScan;
  deps.db.insertTrade = (_p) => {
    insertCalls++;
    return Promise.reject(new Error("db down"));
  };
  deps.db.upsertHourlyScan = (p) => {
    if (p.entryOrderId !== null) journalPostOrderCalls++;
    return realUpsert(p);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:journal_degraded");
  assertEquals(insertCalls, 3); // POST_FILL_WRITE_ATTEMPTS
  assertEquals(rec.trades.length, 0);
  assertEquals(journalPostOrderCalls, 0); // journal group never attempted -- no trades row landed
  const notes = rec.auditFinishes[rec.auditFinishes.length - 1].notes ?? "";
  assertEquals(notes, "failed=[insert_trade,journal] order=bracket1");
  // Only the pre-order journal ran; entry_order_id stays NULL, preserving
  // the recovery signature (decision IN ('LONG','SHORT') AND entry_order_id
  // IS NULL) T3's recovery step depends on.
  assertEquals(rec.scans.length, 1);
  assertEquals(rec.scans[0].entryOrderId, null);
});

Deno.test("recovery: an insert_trade-only fault leaves the scan row pending; the next scan's recovery adopts it (must-fix round 1 finding 1)", async () => {
  const { deps, rec } = buildDeps();
  deps.db.insertTrade = (_p) => Promise.reject(new Error("db down"));
  deps.alpaca.placeBracketOrder = (_args) =>
    Promise.resolve(fill({ orderId: "bracket1", fillTime: "2026-07-27T15:05:00Z" }));

  const outcome1 = await runHourlyCheck(deps);
  assertEquals(outcome1, "success:journal_degraded");
  assertEquals(rec.trades.length, 0);
  assertEquals(rec.scans[rec.scans.length - 1].entryOrderId, null);

  // --- Run 2: recovery adopts the pending row left by run 1. bar_ts is
  // BAR1's timestamp (14:00Z); the fill (15:05Z) sits inside the recovery
  // window [bar_ts+1h, bar_ts+2h) = [15:00Z, 16:00Z).
  deps.db.insertTrade = (p) => {
    rec.trades.push(p);
    return Promise.resolve(rec.trades.length);
  };
  deps.db.getHourlyScansPendingEntry = () =>
    Promise.resolve([pendingScanRow({ bar_ts: BAR1.timestamp, decision: "LONG" })]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "bracket1",
        side: "BUY",
        qty: 18,
        fillPrice: 550,
        fillTime: "2026-07-27T15:05:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(18); // still open at the broker
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // resting -- not naked
  deps.config.hourlyMaxEntriesPerDay = 0; // keep run 2's own decision from muddying the assertion

  const outcome2 = await runHourlyCheck(deps);
  assertEquals(typeof outcome2, "string");
  assertEquals(rec.trades.length, 1);
  assertEquals(rec.trades[0].brokerOrderId, "bracket1");
  const recoveredScan = rec.scans.find((s) =>
    s.barTs === BAR1.timestamp && s.entryOrderId === "bracket1"
  );
  assertEquals(recoveredScan?.entryOrderId, "bracket1");
});

Deno.test("step 20: insertTrade throws once then succeeds -> success, exactly 2 insertTrade calls", async () => {
  const { deps, rec } = buildDeps();
  let insertCalls = 0;
  const realInsert = deps.db.insertTrade;
  deps.db.insertTrade = (p) => {
    insertCalls++;
    if (insertCalls === 1) return Promise.reject(new Error("transient"));
    return realInsert(p);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success");
  assertEquals(insertCalls, 2);
  assertEquals(rec.trades.length, 1);
});

Deno.test("step 20: kill-switch clear-group fails every attempt while insertTrade/journal succeed -> success:journal_degraded, trades row present, keys untouched", async () => {
  const { deps, rec } = buildDeps();
  // Arm the flag opposite-side so this LONG entry is the clearing entry.
  deps.db.getConfig = (key) => {
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("SHORT");
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    return Promise.resolve(null);
  };
  let setCalls = 0;
  deps.db.setConfig = (key, _value) => {
    if (key.startsWith("hourly_kill_switch_")) {
      setCalls++;
      return Promise.reject(new Error("db down"));
    }
    return Promise.resolve();
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:journal_degraded");
  assertEquals(setCalls, 3); // the whole 3-key group is retried as one unit
  assertEquals(rec.trades.length, 1);
  const notes = rec.auditFinishes[rec.auditFinishes.length - 1].notes ?? "";
  assertEquals(notes, "failed=[kill_switch_clear] order=bracket1");
});

Deno.test("step 20: all three post-fill groups fail -> notes enumerate all three labels in fixed order (journal is skipped once insert_trade fails, not independently attempted -- must-fix round 1 finding 1)", async () => {
  const { deps, rec } = buildDeps();
  deps.db.getConfig = (key) => {
    if (key === "hourly_kill_switch_active") return Promise.resolve("true");
    if (key === "hourly_kill_switch_side") return Promise.resolve("SHORT");
    if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
    return Promise.resolve(null);
  };
  deps.db.setConfig = (key, _value) => {
    if (key.startsWith("hourly_kill_switch_")) return Promise.reject(new Error("boom"));
    return Promise.resolve();
  };
  deps.db.insertTrade = (_p) => Promise.reject(new Error("boom"));
  let postOrderJournalCalls = 0;
  const realUpsert = deps.db.upsertHourlyScan;
  deps.db.upsertHourlyScan = (p) => {
    if (p.entryOrderId !== null) postOrderJournalCalls++;
    return realUpsert(p);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:journal_degraded");
  assertEquals(postOrderJournalCalls, 0); // journal group never attempted -- insert_trade already failed
  const notes = rec.auditFinishes[rec.auditFinishes.length - 1].notes ?? "";
  assertEquals(notes, "failed=[kill_switch_clear,insert_trade,journal] order=bracket1");
});

Deno.test("step 20: journal group fails alone (insertTrade succeeds) -> success:journal_degraded, trades row present, notes=[journal]", async () => {
  const { deps, rec } = buildDeps();
  const realUpsert = deps.db.upsertHourlyScan;
  deps.db.upsertHourlyScan = (p) => {
    if (p.entryOrderId !== null) return Promise.reject(new Error("boom"));
    return realUpsert(p);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:journal_degraded");
  assertEquals(rec.trades.length, 1);
  const notes = rec.auditFinishes[rec.auditFinishes.length - 1].notes ?? "";
  assertEquals(notes, "failed=[journal] order=bracket1");
});

// ---------------------------------------------------------------------------
// #480 T3: reconciliation-side recovery of pending-entry hourly_scans rows
// (T1's post-fill degraded window, closed on the NEXT scan). Pending row
// signature: decision IN ('LONG','SHORT') AND entry_order_id IS NULL.
// ---------------------------------------------------------------------------

function pendingScanRow(over: Partial<HourlyScanRow> = {}): HourlyScanRow {
  return {
    symbol: "SPY",
    bar_ts: "2026-07-26T14:00:00Z",
    decision: "LONG",
    skip_reason: null,
    detectors_fired: ["hammer"],
    context_mode: "none",
    entry_ref_price: 550,
    stop_price: 547,
    target_price: 554,
    risk_per_share: 3,
    equity_usd: 100000,
    qty: 18,
    entry_order_id: null,
    ...over,
  };
}

Deno.test("recovery: double-fault replay -- pending LONG row + unjournaled entry BUY fill -> exactly one insertTrade (hourly_long_entry) with the fill's qty/price/time, plus one upsertHourlyScan with entryOrderId set", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-26T14:00:00Z", decision: "LONG" });
  deps.db.getHourlyScansPendingEntry = (_symbol, _sinceIso) => Promise.resolve([pending]);
  deps.alpaca.listFilledOrdersSince = (_symbol, _sinceIso) =>
    Promise.resolve([
      {
        orderId: "recovered1",
        side: "BUY",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-26T15:20:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(12); // still open at the broker
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // resting legs -- not naked
  const outcome = await runHourlyCheck(deps);
  assertEquals(typeof outcome, "string");
  assertEquals(rec.trades.length, 1);
  assertEquals(rec.trades[0].reason, "hourly_long_entry");
  assertEquals(rec.trades[0].qty, 12);
  assertEquals(rec.trades[0].fillPrice, 549.5);
  assertEquals(rec.trades[0].fillTime, "2026-07-26T15:20:00Z");
  const recoveredScan = rec.scans.find((s) => s.barTs === pending.bar_ts);
  assertEquals(recoveredScan?.entryOrderId, "recovered1");
});

Deno.test("recovery: SHORT twin -- pending SHORT row + unjournaled entry SELL fill -> insertTrade reason hourly_short_entry", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-26T14:00:00Z", decision: "SHORT" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "recovered2",
        side: "SELL",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-26T15:20:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(-12);
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(typeof outcome, "string");
  assertEquals(rec.trades.length, 1);
  assertEquals(rec.trades[0].reason, "hourly_short_entry");
  assertEquals(rec.trades[0].side, "SELL");
  const recoveredScan = rec.scans.find((s) => s.barTs === pending.bar_ts);
  assertEquals(recoveredScan?.entryOrderId, "recovered2");
});

Deno.test("recovery: partial-fault replay -- trades row already exists, provenance null -> no duplicate insertTrade, entry_order_id restored", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-26T14:00:00Z", decision: "LONG" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  const existingTrade: TradeRow = {
    symbol: "SPY",
    side: "BUY",
    qty: 12,
    fill_price: 549.5,
    fill_time: "2026-07-26T15:20:00Z",
    reason: "hourly_long_entry",
    broker_order_id: "recovered1",
  };
  deps.db.getTradesSince = () => Promise.resolve([existingTrade]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "recovered1",
        side: "BUY",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-26T15:20:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(12);
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]);
  const outcome = await runHourlyCheck(deps);
  assertEquals(typeof outcome, "string");
  assertEquals(rec.trades.length, 0); // no duplicate insertTrade
  const recoveredScan = rec.scans.find((s) => s.barTs === pending.bar_ts);
  assertEquals(recoveredScan?.entryOrderId, "recovered1");
});

Deno.test("recovery: a fill already journaled under an EXIT reason is not adopted as entry provenance, even same-side and in-window (must-fix round 1 finding 2)", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-26T14:00:00Z", decision: "SHORT" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  const exitJournaledFill: TradeRow = {
    symbol: "SPY",
    side: "SELL",
    qty: 5,
    fill_price: 551,
    fill_time: "2026-07-26T15:10:00Z", // inside [bar_ts+1h, bar_ts+2h)
    reason: "hourly_session_close_exit",
    broker_order_id: "exit-already-journaled",
  };
  deps.db.getTradesSince = () => Promise.resolve([exitJournaledFill]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "exit-already-journaled",
        side: "SELL",
        qty: 5,
        fillPrice: 551,
        fillTime: "2026-07-26T15:10:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.config.hourlyMaxEntriesPerDay = 0; // keep this run's own decision from muddying the assertion
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:max_entries_reached");
  assertEquals(rec.trades.length, 0); // no new insertTrade
  assertEquals(rec.scans.some((s) => s.barTs === pending.bar_ts), false); // row stays pending, untouched
});

Deno.test("recovery: no matching fill -> pending row untouched", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-26T14:00:00Z", decision: "LONG" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  deps.alpaca.listFilledOrdersSince = () => Promise.resolve([] as ClosedOrderFill[]);
  deps.config.hourlyMaxEntriesPerDay = 0; // keep the main pipeline's own entry from muddying the assertion
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:max_entries_reached");
  assertEquals(rec.trades.length, 0);
  assertEquals(rec.scans.some((s) => s.barTs === pending.bar_ts), false);
});

Deno.test("recovery: fast path -- no pending rows -> recovery makes zero listFilledOrdersSince calls", async () => {
  const { deps } = buildDeps();
  let calls = 0;
  deps.alpaca.listFilledOrdersSince = (_symbol, _sinceIso) => {
    calls++;
    return Promise.resolve([] as ClosedOrderFill[]);
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(typeof outcome, "string");
  assertEquals(calls, 0);
});

Deno.test("recovery: same-run knock-on -- after adoption entryConsideredOpen is true, the naked-position branch re-legs from the restored provenance -> success:legs_replaced", async () => {
  const { deps } = buildDeps();
  const pending = pendingScanRow({
    bar_ts: "2026-07-26T14:00:00Z",
    decision: "LONG",
    stop_price: 547,
    target_price: 554,
    qty: 12,
  });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "recovered1",
        side: "BUY",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-26T15:20:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(12); // open, no resting legs -- naked
  deps.alpaca.listOpenOrderIds = () => Promise.resolve([] as string[]);
  deps.db.getHourlyScanByEntryOrderId = (_symbol, orderId) =>
    Promise.resolve(
      orderId === "recovered1" ? { ...pending, entry_order_id: "recovered1" } : null,
    );
  let relegArgs: unknown = null;
  deps.alpaca.placeOcoExitPair = (args) => {
    relegArgs = args;
    return Promise.resolve({ orderId: "oco-releg" });
  };
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "success:legs_replaced");
  assertEquals(relegArgs, {
    symbol: "SPY",
    side: "SELL",
    qty: 12,
    takeProfitPrice: 554,
    stopLossPrice: 547,
  });
});

Deno.test("recovery: an adoption's discovered-fills read is reused by exit-fill discovery -- exactly one listFilledOrdersSince call (nit 7)", async () => {
  const { deps } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-26T14:00:00Z", decision: "LONG" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  let calls = 0;
  deps.alpaca.listFilledOrdersSince = () => {
    calls++;
    return Promise.resolve([
      {
        orderId: "recovered1",
        side: "BUY",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-26T15:20:00Z",
      },
    ] as ClosedOrderFill[]);
  };
  deps.alpaca.getPosition = () => Promise.resolve(12); // still open -- feeds exit-fill discovery too
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // resting -- not naked
  deps.config.hourlyMaxEntriesPerDay = 0; // keep this run's own decision out of the way
  await runHourlyCheck(deps);
  assertEquals(calls, 1);
});

// ---------------------------------------------------------------------------
// #480 T4: cooldown/day-cap correctness after recovery (end-to-end pipeline
// tests). Requires buildDeps' getTradesSince to be stateful, backed by the
// same array default insertTrade writes to, so a trade recovery inserts
// mid-run is visible to gate 13/14's own (separate) getTradesSince read --
// a harness extension, noted in the PR.
// ---------------------------------------------------------------------------

Deno.test("recovery + gate 14: an adopted entry counts toward today's entry cap -> skipped:max_entries_reached", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-27T09:00:00Z", decision: "LONG" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "recovered1",
        side: "BUY",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-27T10:15:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(0); // already flat at the broker
  deps.config.hourlyMaxEntriesPerDay = 1; // the adopted entry alone fills the cap
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:max_entries_reached");
  assertEquals(rec.trades.length, 1); // just the recovered entry -- no fresh entry placed
  assertEquals(rec.trades[0].reason, "hourly_long_entry");
});

Deno.test("recovery + gate 13: adopted entry + discovered bracket exit in the same pass -> cooldown fires against the exit's fill_time -> skipped:cooldown", async () => {
  const { deps, rec } = buildDeps();
  const pending = pendingScanRow({ bar_ts: "2026-07-27T09:00:00Z", decision: "LONG" });
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([pending]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "recovered1",
        side: "BUY",
        qty: 12,
        fillPrice: 549.5,
        fillTime: "2026-07-27T10:15:00Z",
      },
      // After the new candidate bar (14:00) -- cooldown must fire against it.
      { orderId: "exit1", side: "SELL", qty: 12, fillPrice: 552, fillTime: "2026-07-27T14:15:00Z" },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(0); // already flat -- the exit already happened at the broker
  const outcome = await runHourlyCheck(deps);
  assertEquals(outcome, "skipped:cooldown");
  assertEquals(
    rec.trades.some((t) => t.reason === "hourly_bracket_exit" && t.brokerOrderId === "exit1"),
    true,
  );
});

// ---------------------------------------------------------------------------
// #480 T5: pin the lead-ruled decision -- recovery NEVER clears stale
// hourly_kill_switch_* keys. Three-run scenario sharing one bot_config store:
// (1) a double fault (clear group + journal group both exhaust retries) on
// the would-be clearing entry leaves the flag stale AND the scan row
// pending; (2) the next scan's recovery adopts the pending entry (restoring
// entry_order_id) but must not touch the flag; (3) self-healing proof -- a
// later fully-successful opposite-side entry still clears it via the
// ordinary step 20 path, exactly as PR #477's round-2 review ratified.
// ---------------------------------------------------------------------------

Deno.test("recovery T5: double-fault leaves hourly_kill_switch_* stale through recovery; a later fully-successful opposite-side entry self-heals via the normal step 20 path", async () => {
  const { deps, rec } = buildDeps();
  const configStore = new Map<string, string>([
    ["hourly_experiment_start_equity", "100000"],
    ["hourly_kill_switch_active", "true"],
    ["hourly_kill_switch_side", "SHORT"], // opposite of the LONG decision every run below produces
  ]);
  deps.db.getConfig = (key) => Promise.resolve(configStore.get(key) ?? null);
  const realUpsert = deps.db.upsertHourlyScan;

  // --- Run 1: this scan's own LONG entry is the clearing entry, but BOTH
  // the clear group and the post-order journal group exhaust every retry
  // (T1 double fault) -- leaving the flag stale and the scan row pending.
  deps.db.setConfig = (key, _value) => {
    if (key.startsWith("hourly_kill_switch_")) return Promise.reject(new Error("db down"));
    return Promise.resolve();
  };
  deps.db.upsertHourlyScan = (p) => {
    if (p.entryOrderId !== null) return Promise.reject(new Error("boom")); // post-order journal fails
    return realUpsert(p);
  };
  deps.alpaca.placeBracketOrder = (_args) =>
    Promise.resolve(fill({ orderId: "bracket1", fillTime: "2026-07-27T15:05:00Z" }));

  const outcome1 = await runHourlyCheck(deps);
  assertEquals(outcome1, "success:journal_degraded");
  assertEquals(rec.trades.length, 1); // insertTrade group succeeded
  assertEquals(configStore.get("hourly_kill_switch_active"), "true");
  assertEquals(configStore.get("hourly_kill_switch_side"), "SHORT");

  // --- Run 2: recovery adopts the pending row left by run 1. This scan's
  // OWN decision is blocked at gate 12 (position_open) so the ordinary step
  // 20 path can't confound the assertion -- only recovery is exercised.
  deps.db.upsertHourlyScan = realUpsert;
  deps.db.setConfig = (key, value) => {
    configStore.set(key, value);
    rec.configSets.push([key, value]);
    return Promise.resolve();
  };
  deps.db.getHourlyScansPendingEntry = () =>
    Promise.resolve([pendingScanRow({ bar_ts: BAR1.timestamp, decision: "LONG" })]);
  deps.alpaca.listFilledOrdersSince = () =>
    Promise.resolve([
      {
        orderId: "bracket1",
        side: "BUY",
        qty: 18,
        fillPrice: 550,
        fillTime: "2026-07-27T15:05:00Z",
      },
    ] as ClosedOrderFill[]);
  deps.alpaca.getPosition = () => Promise.resolve(18); // still open -- forces skipped:position_open
  deps.alpaca.listOpenOrderIds = () => Promise.resolve(["leg-tp", "leg-sl"]); // resting -- not naked

  const outcome2 = await runHourlyCheck(deps);
  assertEquals(outcome2, "skipped:position_open");
  assertEquals(rec.trades.length, 1); // no duplicate insertTrade -- run 1's row is dedup-matched
  const recoveredScan = rec.scans.find((s) =>
    s.barTs === BAR1.timestamp && s.entryOrderId !== null
  );
  assertEquals(recoveredScan?.entryOrderId, "bracket1"); // provenance restored
  assertEquals(configStore.get("hourly_kill_switch_active"), "true"); // still untouched
  assertEquals(configStore.get("hourly_kill_switch_side"), "SHORT");

  // --- Run 3 (self-healing proof): no pending rows, position flat, a fresh
  // fully-successful opposite-side entry clears the flag via the ordinary
  // step 20 path -- proving recovery never needed to clear it itself.
  deps.db.getHourlyScansPendingEntry = () => Promise.resolve([]);
  deps.alpaca.getPosition = () => Promise.resolve(0);

  const outcome3 = await runHourlyCheck(deps);
  assertEquals(outcome3, "success");
  assertEquals(configStore.get("hourly_kill_switch_active"), "false");
  assertEquals(configStore.get("hourly_kill_switch_side"), "");
});
