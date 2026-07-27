/**
 * Classic candlestick PATTERN detectors -- a 1:1 TypeScript port of
 * backtest/candlestick.py (#467, batch #464).
 *
 * This module is currently DEAD CODE: it is not imported by any Edge Function
 * entrypoint (daily-check, kill-switch, panic, status). CLAUDE.md's "One decision
 * rule" invariant permits adding the raw material for a second decision rule to
 * `_shared/` only via a fresh brainstorm + design spec (batch #464 / #466). #467
 * stays clean only as long as this module is unreachable from any Edge Function --
 * mechanically enforced by the "not yet wired" test in candlestick.test.ts (removed
 * in Batch 2 when the module is actually wired up).
 *
 * Purity: the only import is `./num.ts`. No network calls, no runtime filesystem/serve
 * APIs, no broker/DB/notify imports -- this module does no I/O of any kind.
 *
 * Intentional deviation from the Python source (D1(b), batch #464 lead decision)
 * -----------------------------------------------------------------------------
 * `backtest/candlestick.py::context_mask` computes `bullish = direction in (BULLISH,
 * "long")`, so a `"neutral"` direction silently falls into the BEARISH branch. The
 * Python runner never exercises this path (its ARMS registry names a concrete side
 * for every neutral-registered pattern). `contextMask` here THROWS on a `"neutral"`
 * direction instead of replicating the silent-bearish fallthrough: that path is
 * unreachable in the source and a real foot-gun in a live long/short bot. This is
 * the module's single intentional behavior deviation from the Python source --
 * everything else is a strict 1:1 port.
 *
 * No-look-ahead contract (unchanged from the Python source)
 * ------------------------------------------------------------
 * A detector's value at bar `t` is a function of bars `t`, `t-1`, `t-2` only -- never
 * `t+1`. Warm-up rows (no `t-1`/`t-2`) are `false`, never absent/NaN.
 *
 * Degenerate bars
 * ----------------
 * A zero-range bar (`high === low`) makes every ratio undefined; such bars return
 * `false` for every pattern rather than comparing against NaN.
 *
 * Cadence / ordering
 * -------------------
 * `timestamp` is carried on `Bar` but never read by this module -- the detectors are
 * cadence- and index-agnostic by construction. Timestamp/ordering validation and
 * cadence choice are the caller's job (Batch 2), not this module's.
 */
import { requireNumber } from "./num.ts";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface Bar {
  open: number;
  high: number;
  low: number;
  close: number;
  timestamp?: string;
}

export type Direction = "long" | "short" | "neutral";
export type ContextMode = "none" | "reversal" | "continuation";

export type PatternName =
  | "bullish_engulfing"
  | "bearish_engulfing"
  | "hammer"
  | "shooting_star"
  | "bullish_pin_bar"
  | "bearish_pin_bar"
  | "bullish_marubozu"
  | "bearish_marubozu"
  | "bullish_harami"
  | "bearish_harami"
  | "morning_star"
  | "evening_star"
  | "doji"
  | "inside_bar";

// ---------------------------------------------------------------------------
// Direction labels (mirror backtest.candlestick's BULLISH/BEARISH/NEUTRAL)
// ---------------------------------------------------------------------------

export const BULLISH: Direction = "long";
export const BEARISH: Direction = "short";
export const NEUTRAL: Direction = "neutral"; // direction comes from a breakout, not the pattern

// ---------------------------------------------------------------------------
// Frozen default thresholds -- exact 1:1 with backtest/candlestick.py (no drift).
// ---------------------------------------------------------------------------

export const DOJI_BODY_MAX = 0.10; // body <= 10% of range -> indecision bar
export const HAMMER_WICK_MIN = 2.0; // lower wick >= 2x body (conventional hammer proportion)
export const HAMMER_OPP_WICK_MAX = 0.10; // opposing wick <= 10% of range
export const PIN_WICK_MIN = 0.66; // dominant wick >= 2/3 of the whole range
export const MARUBOZU_BODY_MIN = 0.90; // body >= 90% of range -> effectively wickless
export const STAR_BODY_MAX = 0.30; // middle bar of a star: body <= 30% of its own range

export const CONTEXT_NONE: ContextMode = "none";
export const CONTEXT_REVERSAL: ContextMode = "reversal";
export const CONTEXT_CONTINUATION: ContextMode = "continuation";
export const CONTEXT_MODES: readonly ContextMode[] = [
  CONTEXT_NONE,
  CONTEXT_REVERSAL,
  CONTEXT_CONTINUATION,
];

export const CONTEXT_SMA_WINDOW = 200; // the incumbent 200-DMA, reused rather than re-tuned

export const FIRING_RATE_MAX = 0.25;
export const FIRING_RATE_MIN = 0.005;

// ---------------------------------------------------------------------------
// Internal primitives (exported with a leading underscore -- not part of the
// public surface, but unit-tested directly per the sub-plan's T-10/T-11).
// ---------------------------------------------------------------------------

interface Parts {
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  body: number[];
  upper: number[];
  lower: number[];
  rng: number[];
  bull: boolean[];
  bear: boolean[];
  valid: boolean[];
}

/**
 * Decompose an OHLC array into the body/wick primitives every detector uses.
 * 1:1 port of backtest/candlestick.py::_parts.
 */
export function _parts(bars: readonly Bar[]): Parts {
  const n = bars.length;
  const open = new Array<number>(n);
  const high = new Array<number>(n);
  const low = new Array<number>(n);
  const close = new Array<number>(n);
  const body = new Array<number>(n);
  const upper = new Array<number>(n);
  const lower = new Array<number>(n);
  const rng = new Array<number>(n);
  const bull = new Array<boolean>(n);
  const bear = new Array<boolean>(n);
  const valid = new Array<boolean>(n);

  for (let i = 0; i < n; i++) {
    const b = bars[i];
    const o = b.open;
    const h = b.high;
    const l = b.low;
    const c = b.close;
    const top = Math.max(o, c);
    const bottom = Math.min(o, c);
    open[i] = o;
    high[i] = h;
    low[i] = l;
    close[i] = c;
    body[i] = Math.abs(c - o);
    upper[i] = h - top;
    lower[i] = bottom - l;
    rng[i] = h - l;
    bull[i] = c > o;
    bear[i] = c < o;
    valid[i] = rng[i] > 0;
  }

  return { open, high, low, close, body, upper, lower, rng, bull, bear, valid };
}

/**
 * `num/den` with a zero-or-negative denominator returning NaN instead of Infinity.
 * 1:1 port of backtest/candlestick.py::_safe_ratio. THE trap: `x / 0` is `Infinity`
 * in JS, and `Infinity >= 0.66` is `true` -- a naive division would make e.g.
 * bearishPinBar fire on a zero-range halt bar. Always guard the denominator first.
 */
export function _safeRatio(num: number, den: number): number {
  return den > 0 ? num / den : NaN;
}

// ---------------------------------------------------------------------------
// One-bar patterns
// ---------------------------------------------------------------------------

/** Indecision bar: body is at most `bodyMax` of the bar's range. NEUTRAL. */
export function doji(bars: readonly Bar[], bodyMax: number = DOJI_BODY_MAX): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    out[i] = _safeRatio(p.body[i], p.rng[i]) <= bodyMax;
  }
  return out;
}

/**
 * Bullish single-bar reversal: long LOWER wick, small body parked at the top.
 * A zero-body bar with a long lower wick qualifies (the wick/body test is a
 * product, so a zero body never divides).
 */
export function hammer(
  bars: readonly Bar[],
  wickMin: number = HAMMER_WICK_MIN,
  oppWickMax: number = HAMMER_OPP_WICK_MAX,
): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const longLower = p.lower[i] >= wickMin * p.body[i];
    const smallUpper = _safeRatio(p.upper[i], p.rng[i]) <= oppWickMax;
    out[i] = p.valid[i] && longLower && smallUpper && p.lower[i] > 0;
  }
  return out;
}

/** Bearish single-bar reversal: the exact mirror of hammer (long UPPER wick). */
export function shootingStar(
  bars: readonly Bar[],
  wickMin: number = HAMMER_WICK_MIN,
  oppWickMax: number = HAMMER_OPP_WICK_MAX,
): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const longUpper = p.upper[i] >= wickMin * p.body[i];
    const smallLower = _safeRatio(p.lower[i], p.rng[i]) <= oppWickMax;
    out[i] = p.valid[i] && longUpper && smallLower && p.upper[i] > 0;
  }
  return out;
}

/** Lower wick alone is at least `wickMin` of the whole range (rejection of lows). */
export function bullishPinBar(bars: readonly Bar[], wickMin: number = PIN_WICK_MIN): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    out[i] = p.valid[i] && _safeRatio(p.lower[i], p.rng[i]) >= wickMin;
  }
  return out;
}

/** Upper wick alone is at least `wickMin` of the whole range (rejection of highs). */
export function bearishPinBar(bars: readonly Bar[], wickMin: number = PIN_WICK_MIN): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    out[i] = p.valid[i] && _safeRatio(p.upper[i], p.rng[i]) >= wickMin;
  }
  return out;
}

/** Effectively wickless up bar: bullish and body >= bodyMin * range. */
export function bullishMarubozu(
  bars: readonly Bar[],
  bodyMin: number = MARUBOZU_BODY_MIN,
): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const big = _safeRatio(p.body[i], p.rng[i]) >= bodyMin;
    out[i] = p.valid[i] && p.bull[i] && big;
  }
  return out;
}

/** Effectively wickless down bar: bearish and body >= bodyMin * range. */
export function bearishMarubozu(
  bars: readonly Bar[],
  bodyMin: number = MARUBOZU_BODY_MIN,
): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const big = _safeRatio(p.body[i], p.rng[i]) >= bodyMin;
    out[i] = p.valid[i] && p.bear[i] && big;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Two-bar patterns
// ---------------------------------------------------------------------------

/**
 * Prior bar bearish, current bar bullish and its body engulfs the prior's.
 * Containment is INCLUSIVE at both ends, deliberately (see backtest/candlestick.py's
 * bullish_engulfing docstring): a strict `<` test would make this fire only on gap
 * days, which would make the gap -- not the engulfing geometry -- carry the signal.
 */
export function bullishEngulfing(bars: readonly Bar[]): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 1) {
      out[i] = false;
      continue;
    }
    const prevBear = p.bear[i - 1];
    const engulf = p.open[i] <= p.close[i - 1] && p.close[i] >= p.open[i - 1];
    out[i] = prevBear && p.bull[i] && engulf;
  }
  return out;
}

/** Prior bar bullish, current bar bearish and its body engulfs the prior's (inclusive). */
export function bearishEngulfing(bars: readonly Bar[]): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 1) {
      out[i] = false;
      continue;
    }
    const prevBull = p.bull[i - 1];
    const engulf = p.open[i] >= p.close[i - 1] && p.close[i] <= p.open[i - 1];
    out[i] = prevBull && p.bear[i] && engulf;
  }
  return out;
}

/**
 * Inverse of engulfing: prior bar bearish, current bullish body INSIDE the prior's
 * (inclusive bounds). The `prevBear`/`bull` guard is what separates this from
 * bearishEngulfing, which carries the same body inequalities under the opposite
 * prior-bar direction.
 */
export function bullishHarami(bars: readonly Bar[]): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 1) {
      out[i] = false;
      continue;
    }
    const prevBear = p.bear[i - 1];
    const inside = p.open[i] >= p.close[i - 1] && p.close[i] <= p.open[i - 1];
    out[i] = prevBear && p.bull[i] && inside;
  }
  return out;
}

/** Prior bar bullish, current bearish body INSIDE the prior's (inclusive bounds). */
export function bearishHarami(bars: readonly Bar[]): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 1) {
      out[i] = false;
      continue;
    }
    const prevBull = p.bull[i - 1];
    const inside = p.open[i] <= p.close[i - 1] && p.close[i] >= p.open[i - 1];
    out[i] = prevBull && p.bear[i] && inside;
  }
  return out;
}

/**
 * Current bar's whole RANGE is contained by the prior bar's. NEUTRAL (compression) --
 * direction comes from the caller's breakout side, not the pattern itself. The
 * `valid` guard applies even though containment is well-defined on a zero-range bar:
 * a halted print is an absence of trading, not a compression setup.
 */
export function insideBar(bars: readonly Bar[]): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 1) {
      out[i] = false;
      continue;
    }
    const contained = p.high[i] <= p.high[i - 1] && p.low[i] >= p.low[i - 1];
    out[i] = p.valid[i] && contained;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Three-bar patterns
// ---------------------------------------------------------------------------

/**
 * Bullish 3-bar reversal: big down bar, small-bodied star, big up bar recovering
 * past the first bar's body midpoint. Gaps are not required.
 */
export function morningStar(bars: readonly Bar[], starBodyMax: number = STAR_BODY_MAX): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 2) {
      out[i] = false;
      continue;
    }
    const mid2 = (p.open[i - 2] + p.close[i - 2]) / 2.0;
    const starTop = Math.max(p.open[i - 1], p.close[i - 1]);
    const smallStar = _safeRatio(p.body[i - 1], p.rng[i - 1]) <= starBodyMax;
    out[i] = p.bear[i - 2] && smallStar && starTop < mid2 && p.bull[i] && p.close[i] > mid2;
  }
  return out;
}

/** Bearish 3-bar reversal: the exact mirror of morningStar. */
export function eveningStar(bars: readonly Bar[], starBodyMax: number = STAR_BODY_MAX): boolean[] {
  const p = _parts(bars);
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    if (i < 2) {
      out[i] = false;
      continue;
    }
    const mid2 = (p.open[i - 2] + p.close[i - 2]) / 2.0;
    const starBottom = Math.min(p.open[i - 1], p.close[i - 1]);
    const smallStar = _safeRatio(p.body[i - 1], p.rng[i - 1]) <= starBodyMax;
    out[i] = p.bull[i - 2] && smallStar && starBottom > mid2 && p.bear[i] && p.close[i] < mid2;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Registry -- table-driven, mirrors PATTERNS in backtest/candlestick.py exactly.
// Its size IS the frozen multiplicity count; order matches the Python dict order.
// ---------------------------------------------------------------------------

type DetectorFn = (bars: readonly Bar[]) => boolean[];

interface Registration {
  fn: DetectorFn;
  direction: Direction;
}

const PATTERNS: Readonly<Record<PatternName, Registration>> = Object.freeze({
  bullish_engulfing: { fn: bullishEngulfing, direction: BULLISH },
  bearish_engulfing: { fn: bearishEngulfing, direction: BEARISH },
  hammer: { fn: hammer, direction: BULLISH },
  shooting_star: { fn: shootingStar, direction: BEARISH },
  bullish_pin_bar: { fn: bullishPinBar, direction: BULLISH },
  bearish_pin_bar: { fn: bearishPinBar, direction: BEARISH },
  bullish_marubozu: { fn: bullishMarubozu, direction: BULLISH },
  bearish_marubozu: { fn: bearishMarubozu, direction: BEARISH },
  bullish_harami: { fn: bullishHarami, direction: BULLISH },
  bearish_harami: { fn: bearishHarami, direction: BEARISH },
  morning_star: { fn: morningStar, direction: BULLISH },
  evening_star: { fn: eveningStar, direction: BEARISH },
  doji: { fn: doji, direction: NEUTRAL },
  inside_bar: { fn: insideBar, direction: NEUTRAL },
});

export const PATTERN_NAMES: readonly PatternName[] = Object.freeze(
  Object.keys(PATTERNS) as PatternName[],
);

export const PATTERN_DIRECTIONS: Readonly<Record<PatternName, Direction>> = Object.freeze(
  Object.fromEntries(
    PATTERN_NAMES.map((name) => [name, PATTERNS[name].direction]),
  ) as Record<PatternName, Direction>,
);

function _assertKnownPattern(name: string): name is PatternName {
  if (!(name in PATTERNS)) {
    throw new Error(
      `unknown pattern ${JSON.stringify(name)}; registered: ${
        [...PATTERN_NAMES].sort().join(", ")
      }`,
    );
  }
  return true;
}

/** Run one registered detector by name. Throws on an unknown name. */
export function detect(name: PatternName, bars: readonly Bar[]): boolean[] {
  _assertKnownPattern(name);
  return PATTERNS[name].fn(bars);
}

/** Direction a registered pattern trades (BULLISH/BEARISH/NEUTRAL). Throws on an unknown name. */
export function directionOf(name: PatternName): Direction {
  _assertKnownPattern(name);
  return PATTERNS[name].direction;
}

// ---------------------------------------------------------------------------
// Trend context
// ---------------------------------------------------------------------------

/**
 * Neumaier-compensated rolling mean over `window`-length windows, recomputed fresh
 * per window (not an incremental add/remove running sum, which drifts far more).
 * NaN for the first `window - 1` indices (matches pandas' `min_periods=window`
 * default). This is the real numeric hazard in the module: a naive `sum/window`
 * can differ from pandas' compensated sum by 1-2 ULP, and `close > sma` is a strict
 * comparison -- see the fixture's guard-band assertion in candlestick.golden.test.ts.
 */
export function _rollingMean(values: readonly number[], window: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  for (let end = window - 1; end < n; end++) {
    let sum = 0;
    let comp = 0; // running compensation (Neumaier / Kahan-Babuska variant)
    for (let i = end - window + 1; i <= end; i++) {
      const v = values[i];
      const t = sum + v;
      if (Math.abs(sum) >= Math.abs(v)) {
        comp += (sum - t) + v;
      } else {
        comp += (v - t) + sum;
      }
      sum = t;
    }
    out[end] = (sum + comp) / window;
  }
  return out;
}

/**
 * Boolean mask of bars whose trend context admits a `direction` entry. Reuses the
 * same window-N-day SMA rule as the incumbent 200-DMA regime filter (`regime.ts`
 * computes its own; this module does not import it, to keep this module's only
 * import `./num.ts` -- the SMA math is 1:1 duplicated, not shared, deliberately).
 *
 * A bar with no established context (SMA warm-up) is masked OUT, not admitted:
 * admitting an unknown context would silently make the first `window` bars behave
 * like CONTEXT_NONE and quietly contaminate the caller's arm.
 *
 * THROWS on `direction === NEUTRAL` -- see the module docstring's D1(b) deviation.
 */
export function contextMask(
  bars: readonly Bar[],
  direction: Direction,
  mode: ContextMode = CONTEXT_NONE,
  window: number = CONTEXT_SMA_WINDOW,
): boolean[] {
  if (!CONTEXT_MODES.includes(mode)) {
    throw new Error(
      `mode must be one of ${JSON.stringify(CONTEXT_MODES)}, got ${JSON.stringify(mode)}`,
    );
  }
  if (mode === CONTEXT_NONE) {
    return new Array(bars.length).fill(true);
  }
  if (direction === NEUTRAL) {
    throw new Error(
      `contextMask does not accept direction="neutral" (intentional deviation from ` +
        `backtest/candlestick.py, which falls through to the bearish branch -- see ` +
        `the module docstring's D1(b) note); pass "long" or "short" explicitly.`,
    );
  }

  const closes = bars.map((b) => b.close);
  const sma = _rollingMean(closes, window);

  const bullish = direction === BULLISH;
  const out = new Array<boolean>(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const s = sma[i];
    if (Number.isNaN(s)) {
      out[i] = false;
      continue;
    }
    // `isAbove` is a positive comparison (never a negation over a possibly-NaN
    // value): NaN is filtered out by the `Number.isNaN(s)` guard above, so once
    // we reach here `s` is a valid number and `isBelow = !isAbove` is exactly
    // Python's `below = NOT above` (candlestick.py:358-359) -- an exact tie
    // (`close === s`) is admitted into "below", not excluded from both. This is
    // NOT a partition of "above" and "below" in the strict-inequality sense;
    // it is Python's two-valued (above / not-above) split once NaN is removed.
    const isAbove = closes[i] > s;
    const isBelow = !isAbove;
    if (mode === CONTEXT_REVERSAL) {
      out[i] = bullish ? isBelow : isAbove;
    } else {
      out[i] = bullish ? isAbove : isBelow;
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Aggregate surface -- new (Batch #467), not a straight port. scanCandles returns
// raw fires + both context masks; composition and the neutral-arm side are the
// caller's (Batch 2's) choice, exactly mirroring how backtest/run_candlestick_study.py
// composes cs.detect(...) & cs.context_mask(...) itself rather than baking a mode in.
// ---------------------------------------------------------------------------

export interface CandleScan {
  bars: number;
  patterns: Record<PatternName, boolean[]>;
  context: { long: boolean[]; short: boolean[] };
  latest: { index: number; fired: PatternName[] } | null;
}

export function scanCandles(
  bars: readonly Bar[],
  opts: { context?: ContextMode; smaWindow?: number } = {},
): CandleScan {
  const mode = opts.context ?? CONTEXT_NONE;
  const smaWindow = opts.smaWindow ?? CONTEXT_SMA_WINDOW;

  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    requireNumber(b.open, `bars[${i}].open`);
    requireNumber(b.high, `bars[${i}].high`);
    requireNumber(b.low, `bars[${i}].low`);
    requireNumber(b.close, `bars[${i}].close`);
  }

  const patterns = Object.fromEntries(
    PATTERN_NAMES.map((name) => [name, detect(name, bars)]),
  ) as Record<PatternName, boolean[]>;

  const context = {
    long: contextMask(bars, BULLISH, mode, smaWindow),
    short: contextMask(bars, BEARISH, mode, smaWindow),
  };

  let latest: CandleScan["latest"] = null;
  if (bars.length > 0) {
    const lastIdx = bars.length - 1;
    const fired = PATTERN_NAMES.filter((name) => patterns[name][lastIdx]);
    latest = { index: lastIdx, fired };
  }

  return { bars: bars.length, patterns, context, latest };
}

export interface FiringRateEntry {
  count: number;
  rate: number;
  direction: Direction;
  verdict: "ok" | "TOO_COMMON" | "TOO_RARE";
}

/**
 * Per-pattern firing count and rate over a CandleScan, with a calibration verdict.
 * Operates on the already-computed CandleScan (not a re-run of the detectors, unlike
 * the Python version) -- it cannot drift from `scan.patterns`. Diagnostic only: gates
 * nothing, changes no result. `n === 0` gives rate `0.0` and verdict `TOO_RARE` for
 * every pattern, matching backtest/candlestick.py::firing_rates exactly.
 *
 * Does NOT assert or rely on any particular key order -- Python sorts by descending
 * rate with a non-stable quicksort, so tie order there is not a contract either.
 */
export function firingRates(scan: CandleScan): Record<PatternName, FiringRateEntry> {
  const n = scan.bars;
  const out: Partial<Record<PatternName, FiringRateEntry>> = {};
  for (const name of PATTERN_NAMES) {
    const count = scan.patterns[name].filter(Boolean).length;
    const rate = n > 0 ? count / n : 0.0;
    let verdict: FiringRateEntry["verdict"];
    if (rate > FIRING_RATE_MAX) {
      verdict = "TOO_COMMON";
    } else if (rate < FIRING_RATE_MIN) {
      verdict = "TOO_RARE";
    } else {
      verdict = "ok";
    }
    out[name] = { count, rate, direction: PATTERN_DIRECTIONS[name], verdict };
  }
  return out as Record<PatternName, FiringRateEntry>;
}
