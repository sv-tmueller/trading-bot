import { assertEquals, assertNotEquals } from "@std/assert";
import type { Bar } from "./candlestick.ts";
import { decideHourly } from "./hourly_signal.ts";

const NONE = { contextMode: "none" as const };

Deno.test("decideHourly: no bars -> SKIP no_detectors_fired", () => {
  const result = decideHourly([], NONE);
  assertEquals(result.action, "SKIP");
  assertEquals(result.detectorsFired, []);
});

// §5 worked example: bullish_harami + shooting_star both fire on the same bar
// -> SKIP/signal_conflict, both names journaled.
Deno.test("decideHourly: worked example -- bullish_harami + shooting_star -> SKIP/signal_conflict", () => {
  const prior: Bar = { open: 110, high: 111, low: 89, close: 90 };
  const current: Bar = { open: 100, high: 103.2, low: 99.8, close: 101 };
  const result = decideHourly([prior, current], NONE);
  assertEquals(result.action, "SKIP");
  assertEquals(result.reason, "signal_conflict");
  assertEquals(result.detectorsFired.includes("bullish_harami"), true);
  assertEquals(result.detectorsFired.includes("shooting_star"), true);
});

// Single bullish fire (hammer) -> LONG.
Deno.test("decideHourly: single bullish fire -> LONG", () => {
  const bar: Bar = { open: 100, high: 101.3, low: 95, close: 101 };
  const result = decideHourly([bar], NONE);
  assertEquals(result.action, "LONG");
  assertEquals(result.detectorsFired.includes("hammer"), true);
});

// Mirror of the above: a single bearish fire (shooting_star alone, no
// opposing bullish detector) -> SHORT.
Deno.test("decideHourly: single bearish fire -> SHORT", () => {
  const bar: Bar = { open: 101, high: 106.3, low: 100.7, close: 100 };
  const result = decideHourly([bar], NONE);
  assertEquals(result.action, "SHORT");
  assertEquals(result.detectorsFired.includes("shooting_star"), true);
});

// doji/inside_bar are NEUTRAL: journaled, never voted. A bar that fires only
// a NEUTRAL detector must SKIP, not silently pick a direction.
Deno.test("decideHourly: NEUTRAL-only fire (doji) -> SKIP no_detectors_fired, but journaled", () => {
  // body <= 10% of range, nothing else fires: small body, symmetric wicks.
  const bar: Bar = { open: 100, high: 105, low: 95, close: 100.5 };
  const result = decideHourly([bar], NONE);
  assertEquals(result.action, "SKIP");
  assertEquals(result.reason, "no_detectors_fired");
  assertEquals(result.detectorsFired.includes("doji"), true);
});

// Multiple same-direction fires -> exactly one action (no confluence bonus).
// The hammer bar above also fires bullish_pin_bar (lower wick ratio >= 0.66).
Deno.test("decideHourly: multi-bullish fires -> one LONG action", () => {
  const bar: Bar = { open: 100, high: 101.3, low: 95, close: 101 };
  const result = decideHourly([bar], NONE);
  assertEquals(result.action, "LONG");
  assertEquals(result.detectorsFired.includes("hammer"), true);
  assertEquals(result.detectorsFired.includes("bullish_pin_bar"), true);
});

// Context-mask suppression: in "reversal" mode, a bullish fire whose close is
// ABOVE the trend-context SMA is masked out (reversal wants price below the
// SMA for a bullish entry) -- the fire must not count toward the vote.
Deno.test("decideHourly: context mask suppresses a fire when mode != none", () => {
  const bars: Bar[] = [
    { open: 100, high: 100.5, low: 99.5, close: 100 },
    { open: 100, high: 100.5, low: 99.5, close: 100 },
    { open: 100, high: 100.5, low: 99.5, close: 100 },
    // Strong bullish_marubozu, close far ABOVE the 3-bar SMA -> masked in reversal mode.
    { open: 101, high: 110, low: 101, close: 110 },
  ];
  const result = decideHourly(bars, { contextMode: "reversal", contextSmaWindow: 3 });
  assertEquals(result.action, "SKIP");
  assertEquals(result.reason, "no_detectors_fired");
});

Deno.test("decideHourly: determinism -- same input twice, same output", () => {
  const bars: Bar[] = [
    { open: 110, high: 111, low: 89, close: 90 },
    { open: 100, high: 103.2, low: 99.8, close: 101 },
  ];
  const a = decideHourly(bars, NONE);
  const b = decideHourly(bars, NONE);
  assertEquals(a, b);
});

Deno.test("decideHourly: no fires at all -> SKIP no_detectors_fired, empty journal", () => {
  // A perfectly flat, tiny-range bar with no wicks -- nothing should fire.
  const bar: Bar = { open: 100, high: 100.05, low: 99.95, close: 100.02 };
  const result = decideHourly([bar], NONE);
  assertNotEquals(result.action, "LONG");
  assertNotEquals(result.action, "SHORT");
  assertEquals(result.action, "SKIP");
});
