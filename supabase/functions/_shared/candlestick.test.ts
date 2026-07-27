/**
 * Unit tests for candlestick.ts -- a 1:1 TypeScript port of backtest/candlestick.py
 * (#467). Frames here are hand-computed, lifted verbatim from tests/test_candlestick.py
 * where possible, so the expected classification is arithmetic, not eyeballed.
 *
 * Golden cross-language parity against the Python-exported fixtures lives in
 * candlestick.golden.test.ts, written last (T-26) so it is an independent check.
 */
import { assertEquals, assertFalse, assertThrows } from "@std/assert";
import {
  _parts,
  _safeRatio,
  BEARISH,
  bearishEngulfing,
  bearishHarami,
  bearishMarubozu,
  bearishPinBar,
  BULLISH,
  bullishEngulfing,
  bullishHarami,
  bullishMarubozu,
  bullishPinBar,
  CONTEXT_CONTINUATION,
  CONTEXT_NONE,
  CONTEXT_REVERSAL,
  CONTEXT_SMA_WINDOW,
  contextMask,
  detect,
  directionOf,
  doji,
  DOJI_BODY_MAX,
  eveningStar,
  FIRING_RATE_MAX,
  FIRING_RATE_MIN,
  firingRates,
  hammer,
  HAMMER_OPP_WICK_MAX,
  HAMMER_WICK_MIN,
  insideBar,
  MARUBOZU_BODY_MIN,
  morningStar,
  NEUTRAL,
  PATTERN_DIRECTIONS,
  PATTERN_NAMES,
  PIN_WICK_MIN,
  scanCandles,
  shootingStar,
  STAR_BODY_MAX,
} from "./candlestick.ts";
import type { Bar, CandleScan, PatternName } from "./candlestick.ts";
import { DataError } from "./num.ts";

// A neutral filler bar: small body, symmetric, matches no directional pattern.
// Mirrors tests/test_candlestick.py's FILLER exactly.
const FILLER: Bar = { open: 100.0, high: 100.5, low: 99.5, close: 100.0 };

function bar(o: number, h: number, l: number, c: number): Bar {
  return { open: o, high: h, low: l, close: c };
}

// ---------------------------------------------------------------------------
// Phase 1 -- constants, registry, primitives (T-09, T-10, T-11)
// ---------------------------------------------------------------------------

Deno.test("T-09: thresholds match the Python-frozen values", () => {
  assertEquals(DOJI_BODY_MAX, 0.10);
  assertEquals(HAMMER_WICK_MIN, 2.0);
  assertEquals(HAMMER_OPP_WICK_MAX, 0.10);
  assertEquals(PIN_WICK_MIN, 0.66);
  assertEquals(MARUBOZU_BODY_MIN, 0.90);
  assertEquals(STAR_BODY_MAX, 0.30);
  assertEquals(CONTEXT_SMA_WINDOW, 200);
  assertEquals(FIRING_RATE_MAX, 0.25);
  assertEquals(FIRING_RATE_MIN, 0.005);
  assertEquals(BULLISH, "long");
  assertEquals(BEARISH, "short");
  assertEquals(NEUTRAL, "neutral");
  assertEquals(CONTEXT_NONE, "none");
  assertEquals(CONTEXT_REVERSAL, "reversal");
  assertEquals(CONTEXT_CONTINUATION, "continuation");
});

Deno.test("T-09: registry has exactly 14 patterns, 6 bull / 6 bear", () => {
  assertEquals(PATTERN_NAMES.length, 14);
  const bulls = PATTERN_NAMES.filter((n) => PATTERN_DIRECTIONS[n] === BULLISH);
  const bears = PATTERN_NAMES.filter((n) => PATTERN_DIRECTIONS[n] === BEARISH);
  assertEquals(bulls.length, 6);
  assertEquals(bears.length, 6);
});

Deno.test("T-09: registry order mirrors the Python dict order", () => {
  assertEquals(PATTERN_NAMES, [
    "bullish_engulfing",
    "bearish_engulfing",
    "hammer",
    "shooting_star",
    "bullish_pin_bar",
    "bearish_pin_bar",
    "bullish_marubozu",
    "bearish_marubozu",
    "bullish_harami",
    "bearish_harami",
    "morning_star",
    "evening_star",
    "doji",
    "inside_bar",
  ]);
});

Deno.test("T-10: _parts decomposes a hand-checked bar", () => {
  // body=|106-100|=6, top=max(100,106)=106, bottom=min(100,106)=100
  // upper=107-106=1, lower=100-97=3, rng=107-97=10, bull, valid
  const p = _parts([bar(100, 107, 97, 106)]);
  assertEquals(p.body[0], 6);
  assertEquals(p.upper[0], 1);
  assertEquals(p.lower[0], 3);
  assertEquals(p.rng[0], 10);
  assertEquals(p.bull[0], true);
  assertEquals(p.bear[0], false);
  assertEquals(p.valid[0], true);
});

Deno.test("T-10: _parts flags a zero-range bar invalid", () => {
  const p = _parts([bar(100, 100, 100, 100)]);
  assertEquals(p.rng[0], 0);
  assertEquals(p.valid[0], false);
});

Deno.test("T-11: _safeRatio returns NaN (never Infinity) on a zero denominator", () => {
  assertEquals(Number.isNaN(_safeRatio(5, 0)), true);
  assertEquals(_safeRatio(5, 0) === Infinity, false);
});

Deno.test("T-11: _safeRatio returns NaN on a negative denominator too", () => {
  assertEquals(Number.isNaN(_safeRatio(5, -1)), true);
});

Deno.test("T-11: _safeRatio divides normally on a positive denominator", () => {
  assertEquals(_safeRatio(3, 12), 0.25);
});

// ---------------------------------------------------------------------------
// Phase 2 -- one-bar patterns (T-12), lifted verbatim from tests/test_candlestick.py
// ---------------------------------------------------------------------------

Deno.test("hammer: positive (long lower wick, small opposing wick)", () => {
  const bars = [FILLER, bar(100.0, 101.2, 97.0, 101.0)];
  assertEquals(hammer(bars)[1], true);
});

Deno.test("hammer: rejects a long upper wick", () => {
  const bars = [FILLER, bar(100.0, 104.0, 99.8, 101.0)];
  assertEquals(hammer(bars)[1], false);
});

Deno.test("hammer: rejects a body too large for the wick", () => {
  const bars = [FILLER, bar(100.0, 103.1, 99.0, 103.0)];
  assertEquals(hammer(bars)[1], false);
});

Deno.test("shootingStar: exact mirror of the hammer-positive frame", () => {
  const bars = [FILLER, bar(101.0, 104.0, 100.8, 100.0)];
  assertEquals(shootingStar(bars)[1], true);
  assertEquals(hammer(bars)[1], false);
});

Deno.test("pin bars: need two-thirds of the range in one wick", () => {
  const bars = [FILLER, bar(100.0, 100.6, 97.6, 100.2)];
  assertEquals(bullishPinBar(bars)[1], true);
  assertEquals(bearishPinBar(bars)[1], false);
});

Deno.test("marubozu: requires body to dominate the range", () => {
  const bars = [FILLER, bar(100.0, 110.0, 100.0, 109.5)];
  assertEquals(bullishMarubozu(bars)[1], true);
  assertEquals(bearishMarubozu(bars)[1], false);
  const bars2 = [FILLER, bar(100.0, 115.0, 95.0, 109.5)];
  assertEquals(bullishMarubozu(bars2)[1], false);
});

Deno.test("doji: small body relative to range", () => {
  const bars = [FILLER, bar(100.0, 102.0, 98.0, 100.05)];
  assertEquals(doji(bars)[1], true);
  const full = [FILLER, bar(100.0, 110.0, 100.0, 110.0)];
  assertEquals(doji(full)[1], false);
});

Deno.test("hammer: a zero-body bar with a long lower wick still qualifies", () => {
  // body=0, lower=5, rng=5 -- the ratio test is a product so a zero body doesn't divide.
  const bars = [FILLER, bar(100.0, 100.0, 95.0, 100.0)];
  assertEquals(hammer(bars)[1], true);
});

// ---------------------------------------------------------------------------
// Phase 2 -- two-bar patterns (T-13)
// ---------------------------------------------------------------------------

Deno.test("bullishEngulfing: positive", () => {
  const bars = [FILLER, bar(105.0, 105.5, 99.5, 100.0), bar(99.0, 106.5, 98.5, 106.0)];
  assertEquals(bullishEngulfing(bars)[2], true);
});

Deno.test("bullishEngulfing: rejects a non-engulfing body", () => {
  const bars = [FILLER, bar(105.0, 105.5, 99.5, 100.0), bar(101.0, 106.5, 100.5, 106.0)];
  assertEquals(bullishEngulfing(bars)[2], false);
});

Deno.test("engulfing: fires when the open equals the prior close (no gap, inclusive bound)", () => {
  const bullFrame = [
    FILLER,
    bar(105.0, 105.5, 99.5, 100.0),
    bar(100.0, 106.5, 99.5, 106.0),
  ];
  assertEquals(bullishEngulfing(bullFrame)[2], true);
  const bearFrame = [
    FILLER,
    bar(100.0, 105.5, 99.5, 105.0),
    bar(105.0, 105.5, 98.5, 99.0),
  ];
  assertEquals(bearishEngulfing(bearFrame)[2], true);
});

Deno.test("harami vs engulfing: separated only by the prior bar's direction", () => {
  const bearPrior = [
    FILLER,
    bar(110.0, 110.5, 99.5, 100.0),
    bar(102.0, 108.5, 101.5, 108.0),
  ];
  assertEquals(bullishHarami(bearPrior)[2], true);
  assertEquals(bearishEngulfing(bearPrior)[2], false);

  const bullPrior = [
    FILLER,
    bar(100.0, 110.5, 99.5, 110.0),
    bar(111.0, 111.5, 98.5, 99.0),
  ];
  assertEquals(bearishEngulfing(bullPrior)[2], true);
  assertEquals(bullishHarami(bullPrior)[2], false);
});

Deno.test("bullishEngulfing: requires the prior bar to be bearish", () => {
  const bars = [FILLER, bar(100.0, 105.5, 99.5, 105.0), bar(99.0, 106.5, 98.5, 106.0)];
  assertEquals(bullishEngulfing(bars)[2], false);
});

Deno.test("bearishEngulfing: is the mirror", () => {
  const bars = [FILLER, bar(100.0, 105.5, 99.5, 105.0), bar(106.0, 106.5, 98.5, 99.0)];
  assertEquals(bearishEngulfing(bars)[2], true);
  assertEquals(bullishEngulfing(bars)[2], false);
});

Deno.test("bullishHarami: is the inverse of engulfing", () => {
  const bars = [
    FILLER,
    bar(110.0, 110.5, 99.5, 100.0),
    bar(102.0, 108.5, 101.5, 108.0),
  ];
  assertEquals(bullishHarami(bars)[2], true);
  assertEquals(bullishEngulfing(bars)[2], false);
});

Deno.test("bearishHarami: positive", () => {
  const bars = [
    FILLER,
    bar(100.0, 110.5, 99.5, 110.0),
    bar(108.0, 108.5, 101.5, 102.0),
  ];
  assertEquals(bearishHarami(bars)[2], true);
});

Deno.test("insideBar: requires full-range containment", () => {
  const bars = [FILLER, bar(100.0, 110.0, 90.0, 105.0), bar(101.0, 108.0, 92.0, 103.0)];
  assertEquals(insideBar(bars)[2], true);
  const poke = [FILLER, bar(100.0, 110.0, 90.0, 105.0), bar(101.0, 111.0, 92.0, 103.0)];
  assertEquals(insideBar(poke)[2], false);
});

// ---------------------------------------------------------------------------
// Phase 2 -- three-bar patterns (T-14)
// ---------------------------------------------------------------------------

Deno.test("morningStar: positive", () => {
  const bars = [
    FILLER,
    bar(110.0, 110.5, 99.5, 100.0),
    bar(98.0, 99.0, 97.0, 97.5),
    bar(99.0, 107.5, 98.5, 107.0),
  ];
  assertEquals(morningStar(bars)[3], true);
});

Deno.test("morningStar: rejects a close below the prior midpoint", () => {
  const bars = [
    FILLER,
    bar(110.0, 110.5, 99.5, 100.0),
    bar(98.0, 99.0, 97.0, 97.5),
    bar(99.0, 104.5, 98.5, 104.0),
  ];
  assertEquals(morningStar(bars)[3], false);
});

Deno.test("morningStar: rejects a large middle body", () => {
  const bars = [
    FILLER,
    bar(110.0, 110.5, 99.5, 100.0),
    bar(98.0, 98.5, 94.0, 94.5),
    bar(99.0, 107.5, 98.5, 107.0),
  ];
  assertEquals(morningStar(bars)[3], false);
});

Deno.test("eveningStar: positive", () => {
  const bars = [
    FILLER,
    bar(100.0, 110.5, 99.5, 110.0),
    bar(112.0, 114.0, 111.0, 112.5),
    bar(111.0, 111.5, 102.5, 103.0),
  ];
  assertEquals(eveningStar(bars)[3], true);
});

// ---------------------------------------------------------------------------
// Phase 3 -- structural contracts, parametrized over all 14 (T-15..T-19)
// ---------------------------------------------------------------------------

Deno.test("T-15: warm-up rows are false, output length matches input, no NaN/undefined", () => {
  const bars = [FILLER, FILLER, FILLER];
  for (const name of PATTERN_NAMES) {
    const out = detect(name, bars);
    assertEquals(out.length, bars.length, `${name} length mismatch`);
    for (const v of out) {
      assertEquals(typeof v, "boolean", `${name} produced a non-boolean`);
    }
    const twoOrThreeBarOnly = ![
      "doji",
      "hammer",
      "shooting_star",
      "bullish_pin_bar",
      "bearish_pin_bar",
      "bullish_marubozu",
      "bearish_marubozu",
    ].includes(name);
    if (twoOrThreeBarOnly) {
      assertFalse(out[0], `${name} fired on the first bar with no history`);
    }
  }
});

Deno.test("T-16: a zero-range bar is never a setup, for every pattern", () => {
  const bars = [FILLER, bar(100.0, 100.0, 100.0, 100.0), FILLER];
  for (const name of PATTERN_NAMES) {
    assertFalse(detect(name, bars)[1], `${name} fired on a zero-range bar`);
  }
});

function _syntheticFrame(n: number, seed: number): Bar[] {
  // Deterministic LCG so this file needs no seeded-RNG import; the exact numbers
  // don't matter -- only that the same bars are reused across full vs. truncated.
  let state = seed;
  const rand = () => {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    return state / 0x7fffffff;
  };
  const out: Bar[] = [];
  let close = 100;
  for (let i = 0; i < n; i++) {
    const open = i === 0 ? 100 : out[i - 1].close;
    close = close + (rand() - 0.5) * 2;
    const hi = Math.max(open, close) + Math.abs(rand() - 0.5) * 1.2;
    const lo = Math.min(open, close) - Math.abs(rand() - 0.5) * 1.2;
    out.push({ open, high: hi, low: lo, close });
  }
  return out;
}

Deno.test("T-17: truncation invariance (no look-ahead), for every pattern", () => {
  const bars = _syntheticFrame(60, 7);
  for (const name of PATTERN_NAMES) {
    const full = detect(name, bars);
    for (const cut of [20, 35, 50]) {
      const truncated = detect(name, bars.slice(0, cut));
      assertEquals(
        truncated,
        full.slice(0, cut),
        `${name} truncated at ${cut} diverged from the full detection`,
      );
    }
  }
});

Deno.test("T-18: bull/bear arms are mutually exclusive on a bullish-engulfing bar", () => {
  const bars = [FILLER, bar(105.0, 105.5, 99.5, 100.0), bar(99.0, 106.5, 98.5, 106.0)];
  assertEquals(bullishEngulfing(bars)[2], true);
  for (const name of PATTERN_NAMES) {
    if (PATTERN_DIRECTIONS[name] === BEARISH) {
      assertFalse(detect(name, bars)[2], `${name} fired on a bullish engulfing bar`);
    }
  }
});

Deno.test("T-19: detect throws on an unknown pattern name", () => {
  assertThrows(() => detect("not_a_pattern" as never, [FILLER]));
});

Deno.test("T-19: directionOf throws on an unknown pattern name", () => {
  assertThrows(() => directionOf("not_a_pattern" as never));
});

Deno.test("insideBar / doji are registered NEUTRAL", () => {
  assertEquals(directionOf("inside_bar"), NEUTRAL);
  assertEquals(directionOf("doji"), NEUTRAL);
});

// ---------------------------------------------------------------------------
// Phase 4 -- trend context (T-20, T-21)
// ---------------------------------------------------------------------------

Deno.test("T-20: CONTEXT_NONE admits every bar for every direction", () => {
  const bars = Array(20).fill(FILLER);
  for (const direction of [BULLISH, BEARISH] as const) {
    const mask = contextMask(bars, direction, CONTEXT_NONE);
    assertEquals(mask.length, bars.length);
    assertEquals(mask.every((v) => v === true), true);
  }
});

Deno.test("T-20: contextMask throws on an unknown mode", () => {
  const bars = Array(5).fill(FILLER);
  assertThrows(
    () => contextMask(bars, BULLISH, "sideways" as never),
    Error,
    "mode must be one of",
  );
});

Deno.test("D1(b): contextMask throws on a neutral direction (the port's one intentional deviation)", () => {
  const bars = Array(5).fill(FILLER);
  assertThrows(() => contextMask(bars, NEUTRAL, CONTEXT_REVERSAL));
});

Deno.test("T-20: warm-up bars are masked out, not admitted, with window=200 on 40 bars", () => {
  const bars = Array(40).fill(FILLER);
  for (const mode of [CONTEXT_REVERSAL, CONTEXT_CONTINUATION] as const) {
    const mask = contextMask(bars, BULLISH, mode, 200);
    assertEquals(mask.some((v) => v === true), false, `${mode} admitted a warm-up bar`);
  }
});

Deno.test("T-20: reversal and continuation are exact complements after warm-up", () => {
  const n = 300;
  const bars: Bar[] = [];
  let close = 100;
  let state = 4;
  const rand = () => {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    return state / 0x7fffffff;
  };
  for (let i = 0; i < n; i++) {
    close = close * Math.exp((rand() - 0.5) * 0.02);
    bars.push({ open: close, high: close + 1, low: close - 1, close });
  }
  for (const direction of [BULLISH, BEARISH] as const) {
    const rev = contextMask(bars, direction, CONTEXT_REVERSAL, 50);
    const con = contextMask(bars, direction, CONTEXT_CONTINUATION, 50);
    for (let i = 50; i < n; i++) {
      assertEquals(rev[i] !== con[i], true, `bar ${i} not an exact complement`);
    }
  }
});

Deno.test("T-20: reversal context puts bullish below the SMA and bearish above (falling series)", () => {
  const n = 120;
  const bars: Bar[] = [];
  for (let i = 0; i < n; i++) {
    const c = 100.0 - i;
    bars.push({ open: c, high: c + 1, low: c - 1, close: c });
  }
  const w = 20;
  const bullRev = contextMask(bars, BULLISH, CONTEXT_REVERSAL, w);
  const bearRev = contextMask(bars, BEARISH, CONTEXT_REVERSAL, w);
  for (let i = w; i < n; i++) {
    assertEquals(bullRev[i], true, `bar ${i} bullish reversal should be admitted`);
    assertEquals(bearRev[i], false, `bar ${i} bearish reversal should not be admitted`);
  }
});

// ---------------------------------------------------------------------------
// Fix round 1 (tester finding 1) -- contextMask tie semantics. Python computes
// `below = NOT above` (candlestick.py:358-359): a bar with close === sma is
// admitted into "below", not excluded from both partitions. A constant-close
// frame makes every post-warm-up bar an exact tie, so it pins this directly.
// ---------------------------------------------------------------------------

Deno.test("T-20 (fix 1): a constant-close frame admits ties into 'below', matching Python NOT-above semantics", () => {
  // 5 bars, close=10 throughout, window=3 -- sma is NaN for indices 0,1 and
  // exactly 10.0 (an exact tie with every close) for indices 2,3,4.
  const bars: Bar[] = Array.from({ length: 5 }, () => bar(10.0, 10.0, 10.0, 10.0));
  const mask = contextMask(bars, BULLISH, CONTEXT_REVERSAL, 3);
  assertEquals(mask, [false, false, true, true, true]);
});

Deno.test("T-20 (fix 1): reversal/continuation stay exact complements on a constant-close (tie) frame", () => {
  const bars: Bar[] = Array.from({ length: 5 }, () => bar(10.0, 10.0, 10.0, 10.0));
  for (const direction of [BULLISH, BEARISH] as const) {
    const rev = contextMask(bars, direction, CONTEXT_REVERSAL, 3);
    const con = contextMask(bars, direction, CONTEXT_CONTINUATION, 3);
    for (let i = 3; i < bars.length; i++) {
      assertEquals(rev[i] !== con[i], true, `bar ${i} not an exact complement under ties`);
    }
  }
});

// ---------------------------------------------------------------------------
// Phase 5 -- scanCandles / firingRates (T-22, T-23)
// ---------------------------------------------------------------------------

Deno.test("T-22: scanCandles.patterns matches detect() for every registered name", () => {
  const bars = _syntheticFrame(80, 3);
  const scan = scanCandles(bars);
  assertEquals(scan.bars, bars.length);
  for (const name of PATTERN_NAMES) {
    assertEquals(scan.patterns[name], detect(name, bars));
  }
});

Deno.test("T-22: scanCandles on an empty array returns an empty surface, latest null", () => {
  const scan = scanCandles([]);
  assertEquals(scan.bars, 0);
  assertEquals(scan.latest, null);
  for (const name of PATTERN_NAMES) {
    assertEquals(scan.patterns[name], []);
  }
});

Deno.test("T-22: scanCandles.latest reports the last bar's fired patterns", () => {
  const bars = [FILLER, bar(105.0, 105.5, 99.5, 100.0), bar(99.0, 106.5, 98.5, 106.0)];
  const scan = scanCandles(bars);
  assertEquals(scan.latest?.index, 2);
  assertEquals(scan.latest?.fired.includes("bullish_engulfing"), true);
});

Deno.test("T-22: scanCandles is deterministic across two calls on the same input", () => {
  const bars = _syntheticFrame(40, 9);
  const a = scanCandles(bars);
  const b = scanCandles(bars);
  assertEquals(a, b);
});

Deno.test("T-22: scanCandles does not mutate its input array", () => {
  const bars = _syntheticFrame(10, 2);
  const copy = bars.map((b) => ({ ...b }));
  scanCandles(bars);
  assertEquals(bars, copy);
});

Deno.test("T-22: scanCandles throws DataError on a non-finite OHLC value", () => {
  const bars: Bar[] = [{ open: 100, high: 101, low: NaN, close: 100.5 }];
  assertThrows(() => scanCandles(bars), DataError);
});

Deno.test("T-23: firingRates matches a hand-checked count/rate on a small frame", () => {
  const bars = [
    FILLER,
    bar(105.0, 105.5, 99.5, 100.0),
    bar(99.0, 106.5, 98.5, 106.0),
  ];
  const scan = scanCandles(bars);
  const rates = firingRates(scan);
  assertEquals(rates.bullish_engulfing.count, 1);
  assertEquals(rates.bullish_engulfing.rate, 1 / 3);
  assertEquals(rates.bullish_engulfing.direction, BULLISH);
});

Deno.test("T-23: firingRates on an empty scan gives rate 0.0 and verdict TOO_RARE for every pattern", () => {
  const scan = scanCandles([]);
  const rates = firingRates(scan);
  for (const name of PATTERN_NAMES) {
    assertEquals(rates[name].count, 0);
    assertEquals(rates[name].rate, 0.0);
    assertEquals(rates[name].verdict, "TOO_RARE");
  }
});

Deno.test("T-23: firingRates keys match the registry regardless of order (no sort-order assertion)", () => {
  const scan = scanCandles(_syntheticFrame(200, 11));
  const rates = firingRates(scan);
  assertEquals(new Set(Object.keys(rates)), new Set(PATTERN_NAMES));
});

// ---------------------------------------------------------------------------
// Phase 6 -- purity + invariant guards (T-24, T-25). Mechanizes CLAUDE.md's "One
// decision rule" invariant for this module (see the module docstring's §0 note):
// this package lands as dead code, not reachable from any Edge Function entrypoint.
// ---------------------------------------------------------------------------

async function collectTsFiles(dir: string): Promise<string[]> {
  const results: string[] = [];
  for await (const entry of Deno.readDir(dir)) {
    const fullPath = `${dir}/${entry.name}`;
    if (entry.isDirectory) {
      results.push(...await collectTsFiles(fullPath));
    } else if (entry.isFile && entry.name.endsWith(".ts") && !entry.name.endsWith(".test.ts")) {
      results.push(fullPath);
    }
  }
  return results;
}

Deno.test(
  // T-24 (recommended by the sub-plan §3, included per batch #464 lead decision D3):
  // "candlestick.ts is not yet imported by any Edge Function (remove in Batch 2, #464)".
  // Named explicitly so Batch 2 knows to delete this test once the module is wired up.
  "T-24 [REMOVE IN BATCH 2 WHEN candlestick.ts IS WIRED UP]: not yet imported by any Edge Function entrypoint",
  async () => {
    // This file lives in supabase/functions/_shared/; "../" is supabase/functions/.
    const functionsRoot = decodeURIComponent(new URL("../", import.meta.url).pathname);
    const entrypointDirs = ["daily-check", "kill-switch", "panic", "status"];

    const violations: string[] = [];
    for (const dirName of entrypointDirs) {
      const dir = `${functionsRoot}${dirName}`;
      let files: string[];
      try {
        files = await collectTsFiles(dir);
      } catch {
        continue; // entrypoint directory doesn't exist -- nothing to scan
      }
      for (const file of files) {
        const source = await Deno.readTextFile(file);
        if (/candlestick\.ts/.test(source)) {
          violations.push(file);
        }
      }
    }

    assertEquals(
      violations,
      [],
      `candlestick.ts must not be imported by any Edge Function entrypoint yet ` +
        `(CLAUDE.md "One decision rule" invariant -- see #464/#466):\n${violations.join("\n")}`,
    );
  },
);

Deno.test("T-25: candlestick.ts's only import is ./num.ts, and it contains no I/O calls", async () => {
  const selfPath = decodeURIComponent(new URL("./candlestick.ts", import.meta.url).pathname);
  const source = await Deno.readTextFile(selfPath);

  const importRe = /(?:import|export)\s+(?:[^"';]*?\s+from\s+)?["']([^"']+)["']/g;
  const specifiers: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = importRe.exec(source)) !== null) {
    specifiers.push(m[1]);
  }
  assertEquals(specifiers, ["./num.ts"], `unexpected import specifiers: ${specifiers}`);

  // Strip comments before scanning for I/O tokens -- the module docstring legitimately
  // discusses "supabase/functions/" and "Deno.*" in prose (this is a self-scan, not the
  // full-tree invariants.test.ts scan, so there's no risk of missing another file).
  const withoutComments = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");

  for (const forbidden of ["fetch(", "Deno.", "createClient", "alpaca", "supabase"]) {
    assertEquals(
      withoutComments.toLowerCase().includes(forbidden.toLowerCase()),
      false,
      `candlestick.ts contains forbidden I/O token outside comments: ${forbidden}`,
    );
  }
});

// ---------------------------------------------------------------------------
// Phase 7 -- boundary test pairs (fix round 1, tester finding 2). Every frame is
// constructed with exact arithmetic (range=1.0, so `body/range === body` and
// `wick/range === wick` bit-exactly) so the "exactly at threshold" case pins the
// clause's inclusivity/exclusivity and the "epsilon outside" case cannot land on
// the threshold value itself by floating-point accident.
// ---------------------------------------------------------------------------

const EPS = Number.EPSILON;

Deno.test("boundary: doji fires when body/range is exactly DOJI_BODY_MAX (<=)", () => {
  // o=0, c=DOJI_BODY_MAX, h=1, l=0 -> body=DOJI_BODY_MAX, range=1, ratio=DOJI_BODY_MAX exactly.
  const bars = [bar(0, 1, 0, DOJI_BODY_MAX)];
  assertEquals(doji(bars)[0], true);
});

Deno.test("boundary: doji rejects a body an epsilon above DOJI_BODY_MAX", () => {
  const body = DOJI_BODY_MAX + EPS;
  const bars = [bar(0, 1, 0, body)];
  assertEquals(doji(bars)[0], false);
});

Deno.test("boundary: hammer fires when the opposing (upper) wick ratio is exactly HAMMER_OPP_WICK_MAX (<=)", () => {
  // body=0 (o=c=0) isolates the opposing-wick clause: longLower/valid/lower>0 all
  // hold trivially regardless of the exact wick split. o=c=0 keeps h/l as direct
  // literal assignments (not "0.5 + upper", which loses precision to rounding on
  // the intermediate add/subtract) so upperWick/rng === HAMMER_OPP_WICK_MAX bit-exactly.
  const upper = HAMMER_OPP_WICK_MAX;
  const lower = 1 - upper;
  const bars = [bar(0, upper, -lower, 0)];
  assertEquals(hammer(bars)[0], true);
});

Deno.test("boundary: hammer rejects an opposing (upper) wick ratio an epsilon above HAMMER_OPP_WICK_MAX", () => {
  const upper = HAMMER_OPP_WICK_MAX + EPS;
  const lower = 1 - upper;
  const bars = [bar(0, upper, -lower, 0)];
  assertEquals(hammer(bars)[0], false);
});

Deno.test("boundary: shootingStar fires when the opposing (lower) wick ratio is exactly HAMMER_OPP_WICK_MAX (<=)", () => {
  const lower = HAMMER_OPP_WICK_MAX;
  const upper = 1 - lower;
  const bars = [bar(0, upper, -lower, 0)];
  assertEquals(shootingStar(bars)[0], true);
});

Deno.test("boundary: shootingStar rejects an opposing (lower) wick ratio an epsilon above HAMMER_OPP_WICK_MAX", () => {
  const lower = HAMMER_OPP_WICK_MAX + EPS;
  const upper = 1 - lower;
  const bars = [bar(0, upper, -lower, 0)];
  assertEquals(shootingStar(bars)[0], false);
});

Deno.test("boundary: bullishMarubozu fires when body/range is exactly MARUBOZU_BODY_MIN (>=)", () => {
  // o=0, c=MARUBOZU_BODY_MIN (bullish), h=c, l=o-(1-body) -> range=1 always (see
  // derivation in the fix-round notes), body/range === MARUBOZU_BODY_MIN exactly.
  const body = MARUBOZU_BODY_MIN;
  const bars = [bar(0, body, 0 - (1 - body), body)];
  assertEquals(bullishMarubozu(bars)[0], true);
});

Deno.test("boundary: bullishMarubozu rejects a body an epsilon below MARUBOZU_BODY_MIN", () => {
  const body = MARUBOZU_BODY_MIN - EPS;
  const bars = [bar(0, body, 0 - (1 - body), body)];
  assertEquals(bullishMarubozu(bars)[0], false);
});

Deno.test("boundary: bearishMarubozu fires when body/range is exactly MARUBOZU_BODY_MIN (>=)", () => {
  // o=0, c=-MARUBOZU_BODY_MIN (bearish), h=o, l=c-(1-body) -> range=1 always.
  const body = MARUBOZU_BODY_MIN;
  const bars = [bar(0, 0, -body - (1 - body), -body)];
  assertEquals(bearishMarubozu(bars)[0], true);
});

Deno.test("boundary: bearishMarubozu rejects a body an epsilon below MARUBOZU_BODY_MIN", () => {
  const body = MARUBOZU_BODY_MIN - EPS;
  const bars = [bar(0, 0, -body - (1 - body), -body)];
  assertEquals(bearishMarubozu(bars)[0], false);
});

// morningStar/eveningStar middle-body boundary frames: bar0 is a big directional
// bar establishing mid2, bar2 recovers past mid2 with comfortable margin, and the
// star (bar1) is built around open=0 (NOT some large base like 98) specifically so
// an epsilon-sized body difference survives: adding STAR_BODY_MAX +/- epsilon to a
// large base (e.g. 98) rounds the epsilon away (98's ULP is ~1.4e-14, far coarser
// than Number.EPSILON at the 0.3 magnitude), silently collapsing the two cases to
// the same bar. Building the star at base 0 keeps body === starBody bit-exactly.

Deno.test("boundary: morningStar fires when the star's body/range is exactly STAR_BODY_MAX (<=)", () => {
  const starBody = STAR_BODY_MAX;
  const bars = [
    bar(20.0, 20.5, -0.5, 0.0), // bear, mid2=10
    bar(0.0, starBody, starBody - 1, starBody), // star (base 0), top=starBody << mid2=10
    bar(5.0, 15.0, 4.0, 12.0), // bull, close=12 > mid2=10
  ];
  assertEquals(morningStar(bars)[2], true);
});

Deno.test("boundary: morningStar rejects a star body/range an epsilon above STAR_BODY_MAX", () => {
  const starBody = STAR_BODY_MAX + EPS;
  const bars = [
    bar(20.0, 20.5, -0.5, 0.0),
    bar(0.0, starBody, starBody - 1, starBody),
    bar(5.0, 15.0, 4.0, 12.0),
  ];
  assertEquals(morningStar(bars)[2], false);
});

Deno.test("boundary: eveningStar fires when the star's body/range is exactly STAR_BODY_MAX (<=)", () => {
  const starBody = STAR_BODY_MAX;
  const bars = [
    bar(-20.0, 0.5, -20.5, 0.0), // bull, mid2=-10
    bar(0.0, 0.0, -1, -starBody), // star (base 0), bottom=-starBody >> mid2=-10
    bar(-5.0, -4.0, -15.0, -12.0), // bear, close=-12 < mid2=-10
  ];
  assertEquals(eveningStar(bars)[2], true);
});

Deno.test("boundary: eveningStar rejects a star body/range an epsilon above STAR_BODY_MAX", () => {
  const starBody = STAR_BODY_MAX + EPS;
  const bars = [
    bar(-20.0, 0.5, -20.5, 0.0),
    bar(0.0, 0.0, -1, -starBody),
    bar(-5.0, -4.0, -15.0, -12.0),
  ];
  assertEquals(eveningStar(bars)[2], false);
});

// ---------------------------------------------------------------------------
// Phase 8 -- firingRates verdicts (fix round 1, minor finding): TOO_COMMON was
// uncovered. Hand-constructed CandleScan (no need to run real detectors) so the
// rate is pinned exactly above FIRING_RATE_MAX.
// ---------------------------------------------------------------------------

Deno.test("firingRates: TOO_COMMON verdict when a detector's rate exceeds FIRING_RATE_MAX", () => {
  const n = 10;
  const allFalse = new Array<boolean>(n).fill(false);
  const patterns = Object.fromEntries(
    PATTERN_NAMES.map((name) => [name, [...allFalse]]),
  ) as Record<PatternName, boolean[]>;
  // doji fires on every bar -> rate 1.0, well above FIRING_RATE_MAX (0.25).
  patterns.doji = new Array<boolean>(n).fill(true);
  const scan: CandleScan = {
    bars: n,
    patterns,
    context: { long: [...allFalse], short: [...allFalse] },
    latest: null,
  };
  const rates = firingRates(scan);
  assertEquals(rates.doji.count, n);
  assertEquals(rates.doji.rate, 1.0);
  assertEquals(rates.doji.verdict, "TOO_COMMON");
  // sanity: an all-false pattern stays TOO_RARE, not accidentally TOO_COMMON.
  assertEquals(rates.hammer.verdict, "TOO_RARE");
});
