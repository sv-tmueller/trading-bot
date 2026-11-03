// Pure good/bad/neutral classification for the status page (#639). No imports
// on purpose (no `server-only`, which throws under plain Node, which runs
// tone.test.ts via `npm test`). Only TypeScript syntax Node can strip (no
// enums or namespaces). The module is semantic: it returns tone names, never
// Tailwind class names; web/app/page.tsx maps tones to its existing tokens.
//
// A null tone means "component default text". Direction (LONG/SHORT, BUY/SELL,
// quantity sign) is never a tone: it gets a marker via directionLabel/qtyLabel.

export type Tone = "pos" | "neg" | "warn" | "muted";

// PERCENT units, the same scale as the page's computeEquityHeadroomPct (so
// 5 here means 5%, not 0.05).
export const HEADROOM_WARN_PCT = 5;

// Money and return figures: green when made, red when lost, grey when nothing
// happened or the value is unknown.
export function signTone(n: number | null | undefined): "pos" | "neg" | "muted" {
  if (n == null || !Number.isFinite(n)) return "muted";
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "muted";
}

function hasPrefix(outcome: string, prefix: string): boolean {
  return outcome === prefix || outcome.startsWith(`${prefix}:`);
}

// Audit run outcome. Unknown strings get no tone rather than a guess.
export function outcomeTone(outcome: string | null | undefined): Tone | null {
  if (outcome == null || outcome === "") return "muted";
  // Checked before the generic success rule: the run itself succeeded but it
  // paused trading on a floor breach (red), or a fill went through while the
  // journal write failed (amber: needs attention, not a loss).
  if (outcome === "success:auto_paused") return "neg";
  if (outcome === "success:journal_degraded") return "warn";
  if (hasPrefix(outcome, "success")) return "pos";
  if (hasPrefix(outcome, "error")) return "neg";
  if (hasPrefix(outcome, "skipped")) return "muted";
  return null;
}

// Equity floor headroom. Never "pos": being near the start equity is not
// "good". floorBreached is checked first because headroomPct is null when
// equity <= 0, which must still read red.
export function headroomTone(headroomPct: number | null, floorBreached: boolean): Tone | null {
  if (floorBreached) return "neg";
  if (headroomPct == null || !Number.isFinite(headroomPct)) return "muted";
  if (headroomPct <= 0) return "neg";
  if (headroomPct < HEADROOM_WARN_PCT) return "warn";
  return null;
}

// SKIP means nothing happened; LONG/SHORT are direction, so no tone.
export function decisionTone(decision: string | null | undefined): Tone | null {
  if (decision == null || decision === "SKIP") return "muted";
  return null;
}

// Direction marker in front of the original text (case kept).
export function directionLabel(label: string): string {
  const key = label.toUpperCase();
  if (key === "LONG" || key === "BUY") return `▲ ${label}`;
  if (key === "SHORT" || key === "SELL") return `▼ ${label}`;
  return label;
}

// Signed quantity with a direction marker; the minus sign is kept.
export function qtyLabel(qty: number): string {
  if (qty > 0) return `▲ ${qty}`;
  if (qty < 0) return `▼ ${qty}`;
  return "0";
}
