/**
 * Golden-parity test (T-26) -- checks candlestick.ts against the Python-exported
 * fixtures in testdata/candlestick-golden-{shapes,spy}.json. Written last, after the
 * implementation and the ordinary unit tests, so it is a genuine independent check
 * rather than the thing the implementation was shaped around.
 *
 * See backtest/run_candlestick_fixture_export.py's module docstring for why the SPY
 * case is a deterministic synthetic series rather than a real data/SPY_daily.csv
 * slice (that file is not committed in this checkout).
 */
import { assertEquals, assertThrows } from "@std/assert";
import {
  _rollingMean,
  BEARISH,
  BULLISH,
  CONTEXT_SMA_WINDOW,
  contextMask,
  detect,
  DOJI_BODY_MAX,
  FIRING_RATE_MAX,
  FIRING_RATE_MIN,
  firingRates,
  HAMMER_OPP_WICK_MAX,
  HAMMER_WICK_MIN,
  MARUBOZU_BODY_MIN,
  PATTERN_DIRECTIONS,
  PATTERN_NAMES,
  PIN_WICK_MIN,
  scanCandles,
  STAR_BODY_MAX,
} from "./candlestick.ts";
import type { Bar, ContextMode, Direction, PatternName } from "./candlestick.ts";

interface FixtureCase {
  name: string;
  bars: { o: number; h: number; l: number; c: number }[];
  fires: Record<string, number[]>;
  counts: Record<string, number>;
  firing_rates?: Record<string, { count: number; rate: number; verdict: string }>;
  context?: {
    mode: ContextMode;
    direction: Direction;
    window: number;
    admitted: number[];
  }[];
  sma?: { window: number; min_margin: number | null; values: (number | null)[] };
}

interface Fixture {
  schema: number;
  thresholds: Record<string, number>;
  pattern_order: string[];
  directions: Record<string, string>;
  cases: FixtureCase[];
}

async function loadFixture(name: string): Promise<Fixture> {
  const url = new URL(`./testdata/${name}`, import.meta.url);
  const path = decodeURIComponent(url.pathname);
  const text = await Deno.readTextFile(path);
  return JSON.parse(text) as Fixture;
}

function toBars(raw: FixtureCase["bars"]): Bar[] {
  return raw.map((b) => ({ open: b.o, high: b.h, low: b.l, close: b.c }));
}

function expandFires(indices: number[], n: number): boolean[] {
  const out = new Array<boolean>(n).fill(false);
  for (const i of indices) out[i] = true;
  return out;
}

const SHAPES_FILE = "candlestick-golden-shapes.json";
const SPY_FILE = "candlestick-golden-spy.json";

// ---------------------------------------------------------------------------
// Threshold-drift gate: every fixture threshold === the imported TS constant,
// and pattern_order / directions === the TS registry (checked once per fixture).
// ---------------------------------------------------------------------------

Deno.test("golden: threshold and registry blocks match the TS constants (shapes fixture)", async () => {
  const fixture = await loadFixture(SHAPES_FILE);
  assertEquals(fixture.thresholds.DOJI_BODY_MAX, DOJI_BODY_MAX);
  assertEquals(fixture.thresholds.HAMMER_WICK_MIN, HAMMER_WICK_MIN);
  assertEquals(fixture.thresholds.HAMMER_OPP_WICK_MAX, HAMMER_OPP_WICK_MAX);
  assertEquals(fixture.thresholds.PIN_WICK_MIN, PIN_WICK_MIN);
  assertEquals(fixture.thresholds.MARUBOZU_BODY_MIN, MARUBOZU_BODY_MIN);
  assertEquals(fixture.thresholds.STAR_BODY_MAX, STAR_BODY_MAX);
  assertEquals(fixture.thresholds.CONTEXT_SMA_WINDOW, CONTEXT_SMA_WINDOW);
  assertEquals(fixture.thresholds.FIRING_RATE_MAX, FIRING_RATE_MAX);
  assertEquals(fixture.thresholds.FIRING_RATE_MIN, FIRING_RATE_MIN);
  assertEquals(fixture.pattern_order, [...PATTERN_NAMES]);
  for (const name of PATTERN_NAMES) {
    assertEquals(fixture.directions[name], PATTERN_DIRECTIONS[name]);
  }
});

Deno.test("golden: threshold and registry blocks match the TS constants (spy fixture)", async () => {
  const fixture = await loadFixture(SPY_FILE);
  assertEquals(fixture.thresholds.DOJI_BODY_MAX, DOJI_BODY_MAX);
  assertEquals(fixture.pattern_order, [...PATTERN_NAMES]);
  for (const name of PATTERN_NAMES) {
    assertEquals(fixture.directions[name], PATTERN_DIRECTIONS[name]);
  }
});

// ---------------------------------------------------------------------------
// Per-case, per-detector element-wise parity (both fixtures)
// ---------------------------------------------------------------------------

async function runCaseParity(fileName: string) {
  const fixture = await loadFixture(fileName);
  for (const c of fixture.cases) {
    const bars = toBars(c.bars);
    for (const name of fixture.pattern_order as PatternName[]) {
      const expected = expandFires(c.fires[name], bars.length);
      const got = detect(name, bars);
      assertEquals(got, expected, `${fileName}:${c.name}:${name} fires mismatch`);
      assertEquals(
        got.filter(Boolean).length,
        c.counts[name],
        `${fileName}:${c.name}:${name} count mismatch`,
      );
    }
  }
}

Deno.test("golden: shapes fixture -- element-wise parity for all 14 detectors", async () => {
  await runCaseParity(SHAPES_FILE);
});

Deno.test("golden: spy fixture -- element-wise parity for all 14 detectors", async () => {
  await runCaseParity(SPY_FILE);
});

// ---------------------------------------------------------------------------
// Context masks -- spy fixture carries the 8 realistic-series masks (mode x
// direction x window); the shapes fixture carries one deliberate exact-tie case
// (fix round 1, tester finding 1) pinning Python's `below = NOT above` semantics.
// ---------------------------------------------------------------------------

async function runContextParity(fileName: string) {
  const fixture = await loadFixture(fileName);
  for (const c of fixture.cases) {
    const bars = toBars(c.bars);
    for (const ctx of c.context ?? []) {
      const expected = expandFires(ctx.admitted, bars.length);
      const got = contextMask(bars, ctx.direction, ctx.mode, ctx.window);
      assertEquals(
        got,
        expected,
        `${fileName}:${c.name}:context(mode=${ctx.mode},dir=${ctx.direction},window=${ctx.window}) mismatch`,
      );
    }
  }
}

Deno.test("golden: every recorded context mask matches contextMask() exactly (spy fixture)", async () => {
  await runContextParity(SPY_FILE);
});

Deno.test("golden: every recorded context mask matches contextMask() exactly (shapes fixture, incl. the deliberate tie case)", async () => {
  await runContextParity(SHAPES_FILE);
});

// ---------------------------------------------------------------------------
// firingRates -- keyed map match, NOT ordering (Python sorts non-stably by rate)
// ---------------------------------------------------------------------------

Deno.test("golden: firingRates(scan) matches the fixture's keyed map", async () => {
  const fixture = await loadFixture(SPY_FILE);
  for (const c of fixture.cases) {
    if (!c.firing_rates) continue;
    const bars = toBars(c.bars);
    const scan = scanCandles(bars);
    const rates = firingRates(scan);
    for (const name of fixture.pattern_order as PatternName[]) {
      const expected = c.firing_rates[name];
      assertEquals(rates[name].count, expected.count, `${c.name}:${name} count`);
      assertEquals(rates[name].rate, expected.rate, `${c.name}:${name} rate`);
      assertEquals(rates[name].verdict, expected.verdict, `${c.name}:${name} verdict`);
    }
  }
});

// ---------------------------------------------------------------------------
// SMA numeric agreement (T-21) -- within 1e-9 * max(1, |py|), null <-> NaN
// ---------------------------------------------------------------------------

Deno.test("golden: rollingMean agrees with the fixture's sma.values within tolerance", async () => {
  const fixture = await loadFixture(SPY_FILE);
  for (const c of fixture.cases) {
    if (!c.sma) continue;
    const bars = toBars(c.bars);
    const closes = bars.map((b) => b.close);
    const got = _rollingMean(closes, c.sma.window);
    assertEquals(got.length, c.sma.values.length, `${c.name} sma length mismatch`);
    for (let i = 0; i < got.length; i++) {
      const expected = c.sma.values[i];
      if (expected === null) {
        assertEquals(Number.isNaN(got[i]), true, `${c.name} sma[${i}] expected NaN`);
      } else {
        const tolerance = 1e-9 * Math.max(1, Math.abs(expected));
        const diff = Math.abs(got[i] - expected);
        if (diff > tolerance) {
          throw new Error(
            `${c.name} sma[${i}] got=${
              got[i]
            } expected=${expected} diff=${diff} > tol=${tolerance}`,
          );
        }
      }
    }
  }
});

Deno.test("golden: no committed SPY bar violates the SMA guard band", async () => {
  const fixture = await loadFixture(SPY_FILE);
  for (const c of fixture.cases) {
    if (!c.sma) continue;
    if (c.sma.min_margin === null) continue;
    // The exporter itself raises if this is violated; re-assert here so a future
    // hand-edit of the committed JSON (bypassing the exporter) is still caught.
    if (c.sma.min_margin < 1e-9) {
      throw new Error(`${c.name} sma guard band violated: min_margin=${c.sma.min_margin}`);
    }
  }
});

// ---------------------------------------------------------------------------
// Sanity: the golden coverage rule holds from the TS side too (mirrors the
// Python exporter test's test_every_detector_fires_and_does_not_fire_somewhere).
// ---------------------------------------------------------------------------

Deno.test("golden: every detector fires >=1 and does not fire >=1 across both fixtures", async () => {
  const hasFire: Record<string, boolean> = {};
  const hasNonFire: Record<string, boolean> = {};
  for (const name of PATTERN_NAMES) {
    hasFire[name] = false;
    hasNonFire[name] = false;
  }
  for (const fileName of [SHAPES_FILE, SPY_FILE]) {
    const fixture = await loadFixture(fileName);
    for (const c of fixture.cases) {
      const n = c.bars.length;
      for (const name of PATTERN_NAMES) {
        const fired = c.fires[name] ?? [];
        if (fired.length > 0) hasFire[name] = true;
        if (fired.length < n) hasNonFire[name] = true;
      }
    }
  }
  const missingFire = PATTERN_NAMES.filter((n) => !hasFire[n]);
  const missingNonFire = PATTERN_NAMES.filter((n) => !hasNonFire[n]);
  assertEquals(missingFire, [], `detectors with zero fires: ${missingFire}`);
  assertEquals(missingNonFire, [], `detectors with zero non-fires: ${missingNonFire}`);
});

Deno.test("golden: contextMask still throws on neutral / unknown mode against fixture-shaped bars", async () => {
  const fixture = await loadFixture(SPY_FILE);
  const bars = toBars(fixture.cases[0].bars.slice(0, 10));
  assertThrows(() => contextMask(bars, "neutral" as Direction, "reversal"));
  assertThrows(() => contextMask(bars, BULLISH, "sideways" as ContextMode));
  // sanity: BULLISH/BEARISH still work on the same bars
  contextMask(bars, BULLISH, "none");
  contextMask(bars, BEARISH, "none");
});
