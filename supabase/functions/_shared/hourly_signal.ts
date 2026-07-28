/**
 * The hourly bot's composite decision rule (#475, spec §5). This is the
 * single "one decision rule" CLAUDE.md's amended invariant #1 protects: one
 * pure function, one frozen configuration (P3's 14-detector registry + this
 * module's tie-break, both frozen together, mechanically invariant-scanned by
 * `invariants.test.ts`).
 *
 * Purity: the only import is `./candlestick.ts`. No fetch, no Date.now, no
 * env -- same discipline as `regime.ts`'s computeTargetState.
 */
import {
  type Bar,
  type ContextMode,
  type PatternName,
  PATTERN_DIRECTIONS,
  scanCandles,
} from "./candlestick.ts";

export type HourlyAction = "LONG" | "SHORT" | "SKIP";

export interface HourlyDecision {
  action: HourlyAction;
  reason: string;
  detectorsFired: PatternName[];
}

export interface DecideHourlyConfig {
  contextMode: ContextMode;
  // Test-only override of the trend-context SMA window; production callers
  // omit this and get candlestick.ts's frozen CONTEXT_SMA_WINDOW (200 bars).
  contextSmaWindow?: number;
}

/**
 * The composite decision rule sitting on top of P3's scanCandles(bars).
 *
 * Direction comes from the frozen PATTERN_DIRECTIONS registry. doji/inside_bar
 * are NEUTRAL (journal-only): recorded in detectorsFired, never voted.
 * Multiple same-direction fires collapse to one action (no confluence bonus).
 * A conflict (>=1 bullish AND >=1 bearish fire, after context masking) is
 * SKIP/signal_conflict -- no evidence in this repo ranks one detector above
 * another, so no priority order is invented.
 */
export function decideHourly(bars: readonly Bar[], cfg: DecideHourlyConfig): HourlyDecision {
  const scan = scanCandles(bars, { context: cfg.contextMode, smaWindow: cfg.contextSmaWindow });

  if (scan.latest === null) {
    return { action: "SKIP", reason: "no_detectors_fired", detectorsFired: [] };
  }

  const { index, fired } = scan.latest;
  // Raw fires (unmasked) are journaled in full -- §4 requires every fire, per
  // detector, per bar, to compute live firing rates; masking only affects the
  // vote below, not what gets recorded.
  const detectorsFired = [...fired];

  let bullishCount = 0;
  let bearishCount = 0;
  for (const name of fired) {
    const direction = PATTERN_DIRECTIONS[name];
    if (direction === "neutral") continue; // doji/inside_bar: journal-only, never voted
    const admitted = direction === "long" ? scan.context.long[index] : scan.context.short[index];
    if (!admitted) continue;
    if (direction === "long") bullishCount++;
    else bearishCount++;
  }

  if (bullishCount > 0 && bearishCount > 0) {
    return { action: "SKIP", reason: "signal_conflict", detectorsFired };
  }
  if (bullishCount === 0 && bearishCount === 0) {
    return { action: "SKIP", reason: "no_detectors_fired", detectorsFired };
  }
  return {
    action: bullishCount > 0 ? "LONG" : "SHORT",
    reason: bullishCount > 0 ? "bullish_fire" : "bearish_fire",
    detectorsFired,
  };
}
