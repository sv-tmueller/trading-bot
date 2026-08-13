// Signal emitter for the hourly geometry/cadence/sizing study (#571, step C of
// #566's SUB_PLAN steps 2-5). File-in/file-out, no network, no broker call --
// reads a bars CSV (data/intraday/SPY_{60min,30min}.csv's shape) and writes a
// per-bar decisions/geometry CSV that `backtest/hourly_geometry.py` replays.
//
// D1 (house precedent, per scripts/render_weekly_journal.ts): committed TS
// under scripts/, run via `deno run`, never wired into a cron or Edge
// Function.
//
// Q2 (sub-plan): drives the frozen TS detectors directly -- `decideHourly`,
// `computeBracketGeometry`, `computeSizing` are imported and called UNCHANGED,
// never re-derived in Python. Harness import-surface risk (sub-plan, "Risks"):
// `hourly-check/logic.ts` transitively imports `_shared/alpaca.ts` for the
// `AlpacaError` class only -- no client is ever constructed here, and every
// Alpaca-touching helper in that module is guarded by `CLAUDE_AGENT_NO_BROKER`
// regardless. Run this file (and its test) with `CLAUDE_AGENT_NO_BROKER=1`.
//
// What THIS module deliberately does NOT do (owned by backtest/hourly_geometry.py
// instead, per sub-plan Q2's "Python then owns simulation"): position-state
// gating (cooldown, day cap, position_open) and flatten-scan detection are all
// STATEFUL -- they depend on the simulated trade ledger, which differs by R
// arm (a wider R holds a position longer, shifting the next cooldown/day-cap
// window). This module only computes the STATELESS part of the gate ladder
// (signal, shorts_disabled, geometry_invalid, size_too_small), which is
// identical across every R arm because `computeBracketGeometry`'s stop price
// and `computeSizing`'s validity do not depend on `hourlyBracketRMultiple` at
// all -- only the target price does. So one emitter run per cadence (60m,
// 30m) suffices for the whole 3-R grid; Python replays it three times, one
// per R, applying its own state machine on top.
//
// entryRef fidelity (sub-plan "Risks": "live geometry uses the pre-fill
// latest-trade price ... the study uses next-5Min-bar opens"): the live bot
// calls `getLatestTradePrice()` at scan time (bar close + 7min), a fresh quote
// essentially contemporaneous with the fill. This module's proxy for that
// quote is the SAME 5Min bar whose open is the fill price (the first 5Min bar
// at/after the action instant) -- passing `fillBars` wires this in; entryRef
// falls back to the candidate bar's own close only when no 5Min bar covers the
// action instant (data-end edge, disclosed). Using the candidate bar's own
// (up to ~1h07m-stale) close instead would materially misstate a stop-distance
// -denominated R, since the tight hourly stop buffer is easily crossed by
// ordinary drift over that gap -- this is why the fill-instant price, not the
// signal-bar close, is the correct entryRef.
import type { Bar } from "../supabase/functions/_shared/candlestick.ts";
import {
  computeBracketGeometry,
  computeSizing,
  etHHMMToUtcMs,
} from "../supabase/functions/hourly-check/logic.ts";
import { decideHourly, type HourlyAction } from "../supabase/functions/_shared/hourly_signal.ts";

export interface RawBar {
  timestamp: string; // ISO-8601 UTC bar-start instant
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface Session {
  date: string; // YYYY-MM-DD, the UTC-date key convention `hourly-check/logic.ts` uses
  open: string; // exchange-local (ET) HH:MM
  close: string; // exchange-local (ET) HH:MM
}

// The frozen 3-cell R grid (data-feasibility doc §1 / pre-registration doc).
// Geometry (stop price, sizing validity) does not depend on R at all -- only
// the target price does -- so every R is computed per candidate bar in one
// pass rather than one emitter run per R.
export const R_MULTIPLES: readonly number[] = [1.0, 1.5, 2.0];

// The live scan-cadence offset (bar close -> scan instant), frozen across
// every cadence -- see the entryRef fidelity note above.
const SCAN_OFFSET_MIN = 7;

// Standard NYSE regular-session hours, assumed for every trading date this
// module infers from the data (disclosed modeling limitation, pre-registration
// doc: early closes/half-days are not specially modeled -- see that doc's
// conventions section). A half-day's actual last bar still ends at or before
// this assumed close, so it is never wrongly excluded; the only residual gap
// is that a half-day's true close is not itself detected as a flatten trigger
// here (backtest/hourly_geometry.py's session-end handling owns that).
const SESSION_OPEN_ET = "09:30";
const SESSION_CLOSE_ET = "16:00";

// Mirrors `hourly-check/logic.ts`'s own fetchCount for `hourlyContextMode ===
// "none"` (10) -- the trailing window `decideHourly` sees at each candidate
// bar. Context mode "none" is one of Q3's "modeled by assumption" conventions
// for this study, so no CONTEXT_SMA_WINDOW-sized window is ever needed.
const FETCH_COUNT = 10;

// A nominal, fixed starting equity for the geometry/sizing gate ONLY (not the
// equity-replay step, which backtest/hourly_geometry.py owns per sizing cap).
// #499's established method: per-trade R-denominated outcomes and the
// valid/invalid sizing gate are sizing-invariant, so any fixed nominal value
// produces the same gate decisions a live-equity read would at that instant.
const NOMINAL_EQUITY = 100_000;

const GEOMETRY_STOP_BUFFER_PCT = 0.05; // HOURLY_STOP_BUFFER_PCT's frozen default
const MIN_STOP_DISTANCE = 0.05; // HOURLY_MIN_STOP_DISTANCE's frozen default
const SIZING_RISK_PCT = 0.01; // SIZING_RISK_PCT's frozen default
const SIZING_NOTIONAL_CAP_PCT = 0.10; // SIZING_NOTIONAL_CAP_PCT's frozen default

export interface DecisionRow {
  timestamp: string;
  actionRaw: HourlyAction;
  reasonRaw: string;
  detectorsFired: string; // semicolon-joined PatternName list
  entryRef: number | null;
  stopPrice: number | null;
  stopDistance: number | null;
  targetPrices: Record<string, number | null>; // keyed by R multiple, e.g. "1.0"
  sizingValid: boolean;
  actionFinal: "LONG" | "SKIP";
  reasonFinal: string;
}

// ---------------------------------------------------------------------------
// CSV parsing (matches data/intraday/SPY_*.csv's exact header)
// ---------------------------------------------------------------------------

export function parseBarsCsv(text: string): RawBar[] {
  const lines = text.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  if (lines.length === 0) return [];
  const header = lines[0].split(",");
  const idx = (name: string) => {
    const i = header.indexOf(name);
    if (i === -1) throw new Error(`bars CSV missing column ${JSON.stringify(name)}`);
    return i;
  };
  const tsIdx = idx("timestamp");
  const oIdx = idx("Open");
  const hIdx = idx("High");
  const lIdx = idx("Low");
  const cIdx = idx("Close");
  const bars: RawBar[] = [];
  for (const line of lines.slice(1)) {
    const cols = line.split(",");
    // "2016-01-04 09:00:00+00:00" -> "2016-01-04T09:00:00+00:00", a form
    // Date.parse/`new Date(...)` reliably accepts as UTC.
    const rawTs = cols[tsIdx];
    const isoTs = rawTs.includes("T") ? rawTs : rawTs.replace(" ", "T");
    bars.push({
      timestamp: isoTs,
      open: Number(cols[oIdx]),
      high: Number(cols[hIdx]),
      low: Number(cols[lIdx]),
      close: Number(cols[cIdx]),
    });
  }
  return bars;
}

// ---------------------------------------------------------------------------
// Partial-bar predicate, generalized over an arbitrary bar period (sub-plan
// Q3: "this cadence mapping is itself a registered modeling decision"). Byte-
// identical to `hourly-check/logic.ts`'s own `isBarPartial` at
// periodMinutes=60 (pinned by this module's test suite against the real
// import, not a re-derivation of the frozen decision-rule surface -- this
// predicate is data hygiene, not part of decideHourly/computeBracketGeometry/
// computeSizing).
// ---------------------------------------------------------------------------

export function isBarPartialForPeriod(
  bar: RawBar,
  session: Session,
  periodMinutes: number,
): boolean {
  const periodMs = periodMinutes * 60_000;
  const startMs = new Date(bar.timestamp).getTime();
  const endMs = startMs + periodMs;
  const isTopOfPeriod = startMs % periodMs === 0;
  const sessionOpenMs = etHHMMToUtcMs(session.date, session.open);
  const sessionCloseMs = etHHMMToUtcMs(session.date, session.close);
  const fullyInside = startMs >= sessionOpenMs && endMs <= sessionCloseMs;
  return !isTopOfPeriod || !fullyInside;
}

// ---------------------------------------------------------------------------
// Session inference (disclosed simplification -- see SESSION_OPEN_ET/CLOSE_ET
// above). A UTC calendar date gets a session entry iff at least one raw bar on
// that date is fully inside the assumed 09:30-16:00 ET window; this correctly
// excludes weekends/holidays (no bar ever lands fully inside their "session")
// without a hardcoded holiday calendar.
// ---------------------------------------------------------------------------

export function buildSessionsByDate(
  bars: readonly RawBar[],
  periodMinutes: number,
): Map<string, Session> {
  const dates = new Set(bars.map((b) => b.timestamp.slice(0, 10)));
  const sessions = new Map<string, Session>();
  for (const date of dates) {
    const session: Session = { date, open: SESSION_OPEN_ET, close: SESSION_CLOSE_ET };
    const hasFullyInsideBar = bars.some(
      (b) => b.timestamp.slice(0, 10) === date && !isBarPartialForPeriod(b, session, periodMinutes),
    );
    if (hasFullyInsideBar) sessions.set(date, session);
  }
  return sessions;
}

function toCandlestickBar(b: RawBar): Bar {
  return { open: b.open, high: b.high, low: b.low, close: b.close, timestamp: b.timestamp };
}

// ---------------------------------------------------------------------------
// Fill-instant price lookup (entryRef fidelity -- see module docstring). Finds
// the open of the first `fillBars` bar at/after `actionInstantMs`, the same
// "first 5Min bar open at/after the action instant" convention the actual
// entry fill uses (Q3) -- so entryRef and the executed fill both key off the
// SAME price point, not a stale signal-bar close.
// ---------------------------------------------------------------------------

export function findFillOpen(
  fillBars: readonly RawBar[],
  actionInstantMs: number,
): number | null {
  // fillBars is assumed sorted ascending by timestamp (the staged CSVs are).
  let lo = 0;
  let hi = fillBars.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (new Date(fillBars[mid].timestamp).getTime() < actionInstantMs) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo < fillBars.length ? fillBars[lo].open : null;
}

// ---------------------------------------------------------------------------
// The per-bar decision + geometry/sizing pass (stateless -- see module
// docstring for what is deliberately left to backtest/hourly_geometry.py).
// ---------------------------------------------------------------------------

export function emitDecisions(
  bars: readonly RawBar[],
  opts: { periodMinutes: number; shortsEnabled?: boolean; fillBars?: readonly RawBar[] },
): DecisionRow[] {
  const { periodMinutes, fillBars } = opts;
  const shortsEnabled = opts.shortsEnabled ?? false; // HOURLY_SHORTS_ENABLED=false, Q3
  const sessionsByDate = buildSessionsByDate(bars, periodMinutes);

  const rows: DecisionRow[] = [];
  const nonPartial: RawBar[] = [];

  const blankTargets = (): Record<string, number | null> =>
    Object.fromEntries(R_MULTIPLES.map((r) => [r.toFixed(1), null]));

  for (const b of bars) {
    const date = b.timestamp.slice(0, 10);
    const session = sessionsByDate.get(date);
    if (!session || isBarPartialForPeriod(b, session, periodMinutes)) {
      rows.push({
        timestamp: b.timestamp,
        actionRaw: "SKIP",
        reasonRaw: "partial_bar",
        detectorsFired: "",
        entryRef: null,
        stopPrice: null,
        stopDistance: null,
        targetPrices: blankTargets(),
        sizingValid: false,
        actionFinal: "SKIP",
        reasonFinal: "partial_bar",
      });
      continue;
    }

    nonPartial.push(b);
    const window = nonPartial.slice(-FETCH_COUNT).map(toCandlestickBar);
    const decision = decideHourly(window, { contextMode: "none" });
    const detectorsFired = decision.detectorsFired.join(";");

    if (decision.action === "SKIP") {
      rows.push({
        timestamp: b.timestamp,
        actionRaw: "SKIP",
        reasonRaw: decision.reason,
        detectorsFired,
        entryRef: null,
        stopPrice: null,
        stopDistance: null,
        targetPrices: blankTargets(),
        sizingValid: false,
        actionFinal: "SKIP",
        reasonFinal: decision.reason,
      });
      continue;
    }

    if (decision.action === "SHORT" && !shortsEnabled) {
      rows.push({
        timestamp: b.timestamp,
        actionRaw: "SHORT",
        reasonRaw: decision.reason,
        detectorsFired,
        entryRef: null,
        stopPrice: null,
        stopDistance: null,
        targetPrices: blankTargets(),
        sizingValid: false,
        actionFinal: "SKIP",
        reasonFinal: "shorts_disabled",
      });
      continue;
    }

    // LONG (or an enabled SHORT, dead branch at shortsEnabled=false -- kept
    // symmetric rather than special-cased, since computeBracketGeometry/
    // computeSizing already handle both sides).
    //
    // entryRef = the fill-instant price (the same 5Min-bar-open the actual
    // entry executes at), not the candidate bar's own close -- see the
    // module docstring's "entryRef fidelity" note. Falls back to the
    // candidate's close only when no fillBars bar covers the action instant
    // (fillBars omitted, or the data ends before the fill instant).
    const actionInstantMs = new Date(b.timestamp).getTime() +
      periodMinutes * 60_000 + SCAN_OFFSET_MIN * 60_000;
    const entryRef = fillBars ? (findFillOpen(fillBars, actionInstantMs) ?? b.close) : b.close;
    const geomByR = R_MULTIPLES.map((r) => ({
      r,
      geom: computeBracketGeometry(decision.action as "LONG" | "SHORT", b, entryRef, {
        hourlyStopBufferPct: GEOMETRY_STOP_BUFFER_PCT,
        hourlyBracketRMultiple: r,
      }),
    }));
    const stopPrice = geomByR[0].geom.stopPrice; // R-independent; see module docstring
    const sizing = computeSizing(
      decision.action as "LONG" | "SHORT",
      entryRef,
      stopPrice,
      NOMINAL_EQUITY,
      {
        sizingRiskPct: SIZING_RISK_PCT,
        sizingNotionalCapPct: SIZING_NOTIONAL_CAP_PCT,
        hourlyMinStopDistance: MIN_STOP_DISTANCE,
      },
    );
    const targetPrices = Object.fromEntries(
      geomByR.map(({ r, geom }) => [r.toFixed(1), geom.targetPrice]),
    );

    if (!sizing.valid) {
      rows.push({
        timestamp: b.timestamp,
        actionRaw: decision.action,
        reasonRaw: decision.reason,
        detectorsFired,
        entryRef,
        stopPrice,
        stopDistance: sizing.stopDistance,
        targetPrices,
        sizingValid: false,
        actionFinal: "SKIP",
        reasonFinal: "geometry_invalid",
      });
      continue;
    }
    if (sizing.qty <= 0) {
      rows.push({
        timestamp: b.timestamp,
        actionRaw: decision.action,
        reasonRaw: decision.reason,
        detectorsFired,
        entryRef,
        stopPrice,
        stopDistance: sizing.stopDistance,
        targetPrices,
        sizingValid: false,
        actionFinal: "SKIP",
        reasonFinal: "size_too_small",
      });
      continue;
    }

    rows.push({
      timestamp: b.timestamp,
      actionRaw: decision.action,
      reasonRaw: decision.reason,
      detectorsFired,
      entryRef,
      stopPrice,
      stopDistance: sizing.stopDistance,
      targetPrices,
      sizingValid: true,
      actionFinal: decision.action === "LONG" ? "LONG" : "SKIP",
      reasonFinal: decision.action === "LONG" ? decision.reason : "shorts_disabled",
    });
  }

  return rows;
}

// ---------------------------------------------------------------------------
// CSV output
// ---------------------------------------------------------------------------

const CSV_HEADER = [
  "timestamp",
  "action_raw",
  "reason_raw",
  "detectors_fired",
  "entry_ref",
  "stop_price",
  "stop_distance",
  ...R_MULTIPLES.map((r) => `target_price_r${r.toFixed(1).replace(".", "_")}`),
  "sizing_valid",
  "action_final",
  "reason_final",
].join(",");

function cell(v: number | boolean | string | null): string {
  if (v === null) return "";
  return String(v);
}

export function decisionsToCsv(rows: readonly DecisionRow[]): string {
  const lines = [CSV_HEADER];
  for (const row of rows) {
    lines.push([
      row.timestamp,
      row.actionRaw,
      row.reasonRaw,
      row.detectorsFired,
      cell(row.entryRef),
      cell(row.stopPrice),
      cell(row.stopDistance),
      ...R_MULTIPLES.map((r) => cell(row.targetPrices[r.toFixed(1)])),
      cell(row.sizingValid),
      row.actionFinal,
      row.reasonFinal,
    ].join(","));
  }
  return lines.join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// CLI (file-in/file-out only -- no network, no broker, no env other than
// what Deno itself needs for --allow-read/--allow-write scoping)
// ---------------------------------------------------------------------------

function parseArgs(
  argv: string[],
): {
  bars: string;
  out: string;
  periodMinutes: number;
  shortsEnabled: boolean;
  bars5?: string;
} {
  const get = (flag: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i === -1 ? undefined : argv[i + 1];
  };
  const bars = get("--bars");
  const out = get("--out");
  const periodRaw = get("--period-minutes") ?? "60";
  if (!bars || !out) {
    throw new Error(
      "usage: emit_hourly_decisions.ts --bars <csv> --out <csv> [--period-minutes 60|30] " +
        "[--bars5 <csv>] [--shorts-enabled]",
    );
  }
  const periodMinutes = Number(periodRaw);
  if (!Number.isFinite(periodMinutes) || periodMinutes <= 0) {
    throw new Error(`--period-minutes must be a positive number, got ${JSON.stringify(periodRaw)}`);
  }
  return {
    bars,
    out,
    periodMinutes,
    shortsEnabled: argv.includes("--shorts-enabled"),
    bars5: get("--bars5"),
  };
}

async function main(argv: string[]): Promise<void> {
  const { bars: barsPath, out, periodMinutes, shortsEnabled, bars5: bars5Path } = parseArgs(argv);
  const text = await Deno.readTextFile(barsPath);
  const bars = parseBarsCsv(text);
  const fillBars = bars5Path ? parseBarsCsv(await Deno.readTextFile(bars5Path)) : undefined;
  const rows = emitDecisions(bars, { periodMinutes, shortsEnabled, fillBars });
  await Deno.writeTextFile(out, decisionsToCsv(rows));
  console.log(`wrote ${rows.length} decision rows to ${out} (period=${periodMinutes}m)`);
}

if (import.meta.main) {
  await main(Deno.args);
}
