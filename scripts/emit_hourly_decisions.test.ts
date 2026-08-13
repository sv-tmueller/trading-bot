// Tests for scripts/emit_hourly_decisions.ts (#571 step C). Every case here is
// in-memory only (string literals / array literals) -- no filesystem access --
// so this file runs cleanly under `deno task test`'s restricted
// `--allow-read=supabase/functions,scripts` permission set. The CLI's own
// Deno.readTextFile/writeTextFile wiring is exercised only by direct `deno run`
// invocation (documented in the pre-registration/verdict docs), never here.
import { assertEquals, assertNotEquals } from "@std/assert";
import { isBarPartial } from "../supabase/functions/hourly-check/logic.ts";
import {
  buildSessionsByDate,
  type DecisionRow,
  decisionsToCsv,
  emitDecisions,
  findFillOpen,
  isBarPartialForPeriod,
  parseBarsCsv,
  R_MULTIPLES,
  type RawBar,
} from "./emit_hourly_decisions.ts";

// ---------------------------------------------------------------------------
// parseBarsCsv
// ---------------------------------------------------------------------------

Deno.test("parseBarsCsv: parses the SPY_*.csv header/row shape", () => {
  const text = "timestamp,Open,High,Low,Close\n" +
    "2016-01-04 14:00:00+00:00,171.24,171.42,170.94,170.95\n" +
    "2016-01-04 15:00:00+00:00,170.97,171.19,170.87,171.18\n";
  const bars = parseBarsCsv(text);
  assertEquals(bars.length, 2);
  assertEquals(bars[0].open, 171.24);
  assertEquals(bars[0].high, 171.42);
  assertEquals(bars[0].low, 170.94);
  assertEquals(bars[0].close, 170.95);
  assertEquals(bars[1].close, 171.18);
});

Deno.test("parseBarsCsv: normalizes the timestamp to a parseable ISO string", () => {
  const text = "timestamp,Open,High,Low,Close\n2016-01-04 14:00:00+00:00,1,1,1,1\n";
  const bars = parseBarsCsv(text);
  assertEquals(new Date(bars[0].timestamp).getTime(), Date.parse("2016-01-04T14:00:00Z"));
});

// ---------------------------------------------------------------------------
// isBarPartialForPeriod -- generalizes logic.ts's isBarPartial (HOUR_MS ->
// an arbitrary period). Must be byte-identical to the real isBarPartial at
// periodMinutes=60 -- pinned directly against the frozen import, not a
// re-derivation.
// ---------------------------------------------------------------------------

const SESSION_2016_01_04 = { date: "2016-01-04", open: "09:30", close: "16:00" };

Deno.test("isBarPartialForPeriod: matches the real isBarPartial exactly at periodMinutes=60", () => {
  const cases: RawBar[] = [
    { timestamp: "2016-01-04T09:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // pre-market
    { timestamp: "2016-01-04T14:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // full inside
    { timestamp: "2016-01-04T15:00:00.000Z", open: 1, high: 1, low: 1, close: 1 },
    { timestamp: "2016-01-04T20:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // right at close
    { timestamp: "2016-01-04T21:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // after close
  ];
  for (const bar of cases) {
    assertEquals(
      isBarPartialForPeriod(bar, SESSION_2016_01_04, 60),
      isBarPartial(bar, SESSION_2016_01_04),
      `mismatch at ${bar.timestamp}`,
    );
  }
});

Deno.test("isBarPartialForPeriod: excludes the 30-min session-open stub bar", () => {
  // Session opens 13:30 UTC (EDT); a 13:00-13:30 UTC 30-min bar starts before
  // open -- partial. The 13:30-14:00 UTC bar is fully inside -- not partial.
  const session = { date: "2016-06-06", open: "09:30", close: "16:00" }; // EDT date
  const stub: RawBar = {
    timestamp: "2016-06-06T13:00:00.000Z",
    open: 1,
    high: 1,
    low: 1,
    close: 1,
  };
  const clean: RawBar = {
    timestamp: "2016-06-06T13:30:00.000Z",
    open: 1,
    high: 1,
    low: 1,
    close: 1,
  };
  assertEquals(isBarPartialForPeriod(stub, session, 30), true);
  assertEquals(isBarPartialForPeriod(clean, session, 30), false);
});

// ---------------------------------------------------------------------------
// buildSessionsByDate
// ---------------------------------------------------------------------------

Deno.test("buildSessionsByDate: a date with only pre-market bars gets no session", () => {
  const bars: RawBar[] = [
    { timestamp: "2016-01-02T09:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // Saturday-ish stray print, no RTH bar
  ];
  const sessions = buildSessionsByDate(bars, 60);
  assertEquals(sessions.has("2016-01-02"), false);
});

Deno.test("buildSessionsByDate: a date with a fully-inside RTH bar gets a session", () => {
  const bars: RawBar[] = [
    { timestamp: "2016-01-04T09:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // pre-market, excluded
    { timestamp: "2016-01-04T15:00:00.000Z", open: 1, high: 1, low: 1, close: 1 }, // fully inside
  ];
  const sessions = buildSessionsByDate(bars, 60);
  assertEquals(sessions.has("2016-01-04"), true);
});

// ---------------------------------------------------------------------------
// emitDecisions -- the per-bar gate ladder (signal, shorts_disabled,
// geometry_invalid, size_too_small). Position-state gates (cooldown, day cap,
// position_open, flatten-scan) are NOT computed here -- backtest/hourly_geometry.py
// owns those (sub-plan Q2: the emitter is stateless/bar-reproducible only).
// ---------------------------------------------------------------------------

function bar(ts: string, o: number, h: number, l: number, c: number): RawBar {
  return { timestamp: ts, open: o, high: h, low: l, close: c };
}

Deno.test("emitDecisions: a partial bar is SKIP/partial_bar with no geometry computed", () => {
  const bars = [bar("2016-01-04T09:00:00.000Z", 100, 101, 99, 100)]; // pre-market stub
  const rows = emitDecisions(bars, { periodMinutes: 60 });
  assertEquals(rows.length, 1);
  assertEquals(rows[0].actionFinal, "SKIP");
  assertEquals(rows[0].reasonFinal, "partial_bar");
  assertEquals(rows[0].stopPrice, null);
});

Deno.test("emitDecisions: a hammer (bullish fire) on a fully-inside bar enters LONG with geometry", () => {
  // Prior neutral bar, then a hammer: long lower wick, small body near the top.
  const bars = [
    bar("2016-01-04T14:00:00.000Z", 100, 100.5, 99.5, 100.2),
    bar("2016-01-04T15:00:00.000Z", 100, 101.3, 95, 101),
  ];
  const rows = emitDecisions(bars, { periodMinutes: 60 });
  const last = rows[rows.length - 1];
  assertEquals(last.actionRaw, "LONG");
  assertEquals(last.actionFinal, "LONG");
  assertNotEquals(last.stopPrice, null);
  assertEquals(last.detectorsFired.includes("hammer"), true);
  for (const r of R_MULTIPLES) {
    assertNotEquals(last.targetPrices[r.toFixed(1)], null);
  }
});

Deno.test("emitDecisions: stop price is identical across every R (R-independent geometry)", () => {
  const bars = [
    bar("2016-01-04T14:00:00.000Z", 100, 100.5, 99.5, 100.2),
    bar("2016-01-04T15:00:00.000Z", 100, 101.3, 95, 101),
  ];
  const rows = emitDecisions(bars, { periodMinutes: 60 });
  const last = rows[rows.length - 1];
  // Targets differ by R, but the underlying stop distance from entryRef must
  // be internally consistent: target - entryRef scales linearly with R.
  const d10 = (last.targetPrices["1.0"] as number) - (last.entryRef as number);
  const d20 = (last.targetPrices["2.0"] as number) - (last.entryRef as number);
  assertEquals(Math.round((d20 / d10) * 100) / 100, 2);
});

Deno.test("emitDecisions: a single bearish fire is SKIP/shorts_disabled when shortsEnabled is false", () => {
  const bars = [
    bar("2016-01-04T14:00:00.000Z", 100, 100.5, 99.5, 100.2),
    bar("2016-01-04T15:00:00.000Z", 101, 106.3, 100.7, 100),
  ];
  const rows = emitDecisions(bars, { periodMinutes: 60, shortsEnabled: false });
  const last = rows[rows.length - 1];
  assertEquals(last.actionRaw, "SHORT");
  assertEquals(last.actionFinal, "SKIP");
  assertEquals(last.reasonFinal, "shorts_disabled");
});

Deno.test("findFillOpen: returns the open of the first bar at/after the instant", () => {
  const fillBars = [
    bar("2024-06-03T15:00:00.000Z", 100, 100, 100, 100),
    bar("2024-06-03T15:05:00.000Z", 101, 101, 101, 101),
    bar("2024-06-03T15:10:00.000Z", 102, 102, 102, 102),
  ];
  const instant = Date.parse("2024-06-03T15:07:00.000Z");
  assertEquals(findFillOpen(fillBars, instant), 102);
});

Deno.test("findFillOpen: returns null when the instant is after every bar", () => {
  const fillBars = [bar("2024-06-03T15:00:00.000Z", 100, 100, 100, 100)];
  const instant = Date.parse("2024-06-03T16:00:00.000Z");
  assertEquals(findFillOpen(fillBars, instant), null);
});

Deno.test("emitDecisions: entryRef is the fill-instant 5Min-bar open, not the candidate's stale close", () => {
  const bars = [
    bar("2016-01-04T14:00:00.000Z", 100, 100.5, 99.5, 100.2),
    bar("2016-01-04T15:00:00.000Z", 100, 101.3, 95, 101), // candidate close = 101 (stale)
  ];
  // Action instant = 15:00 (bar end) + 60min(period) ... wait period IS 60 already
  // captured in bar end; the fill window is bar_end(16:00) + 7min = 16:07.
  const fillBars = [
    bar("2016-01-04T16:05:00.000Z", 103, 103, 103, 103),
    bar("2016-01-04T16:10:00.000Z", 104, 104, 104, 104), // first bar >= 16:07 -> open 104
  ];
  const rows = emitDecisions(bars, { periodMinutes: 60, fillBars });
  const last = rows[rows.length - 1];
  assertEquals(last.actionRaw, "LONG");
  assertEquals(last.entryRef, 104);
  assertNotEquals(last.entryRef, 101); // NOT the candidate bar's own close
});

Deno.test("emitDecisions: entryRef falls back to the candidate's close when fillBars is omitted", () => {
  const bars = [
    bar("2016-01-04T14:00:00.000Z", 100, 100.5, 99.5, 100.2),
    bar("2016-01-04T15:00:00.000Z", 100, 101.3, 95, 101),
  ];
  const rows = emitDecisions(bars, { periodMinutes: 60 });
  const last = rows[rows.length - 1];
  assertEquals(last.entryRef, 101);
});

Deno.test("emitDecisions: no detector fire is SKIP/no_detectors_fired with no geometry", () => {
  const bars = [bar("2016-01-04T15:00:00.000Z", 100, 100.1, 99.9, 100.05)];
  const rows = emitDecisions(bars, { periodMinutes: 60 });
  const last = rows[rows.length - 1];
  assertEquals(last.actionFinal, "SKIP");
  assertEquals(last.reasonFinal, "no_detectors_fired");
  assertEquals(last.stopPrice, null);
});

// ---------------------------------------------------------------------------
// decisionsToCsv
// ---------------------------------------------------------------------------

Deno.test("decisionsToCsv: round-trips a row's core fields into a parseable CSV", () => {
  const rows: DecisionRow[] = [
    {
      timestamp: "2016-01-04T15:00:00.000Z",
      actionRaw: "LONG",
      reasonRaw: "bullish_fire",
      detectorsFired: "hammer",
      entryRef: 101,
      stopPrice: 95.05,
      stopDistance: 5.95,
      targetPrices: { "1.0": 106.95, "1.5": 109.925, "2.0": 112.9 },
      sizingValid: true,
      actionFinal: "LONG",
      reasonFinal: "bullish_fire",
    },
  ];
  const csv = decisionsToCsv(rows);
  const lines = csv.trim().split("\n");
  assertEquals(lines.length, 2);
  assertEquals(lines[0].split(",")[0], "timestamp");
  assertEquals(lines[1].includes("LONG"), true);
  assertEquals(lines[1].includes("hammer"), true);
});
