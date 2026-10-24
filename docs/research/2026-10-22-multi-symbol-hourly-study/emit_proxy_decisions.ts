// Proxy-harness decision emitter for the 2026-10-22 multi-symbol hourly study.
//
// Research-only, file-in/file-out, no network, no broker call. Run with
// CLAUDE_AGENT_NO_BROKER=1. Imports the LIVE rule's exports UNCHANGED --
// `decideHourly` (supabase/functions/_shared/hourly_signal.ts, frozen 14-detector
// registry) and `computeBracketGeometry` / `computeSizing`
// (supabase/functions/hourly-check/logic.ts). Nothing about the signal, the
// geometry, or the sizing gate is re-derived here.
//
// Why a second emitter exists: scripts/emit_hourly_decisions.ts (the #571
// emitter, reused UNCHANGED for the top-of-hour "H_live" harness) requires
// bars that start on the top of the period. Yahoo's 1h history -- the only
// multi-year intraday source reachable in this session (no Alpaca keys) --
// is aligned to :30 (09:30, 10:30, ... ET, with a 30-minute 15:30 stub). This
// "H_proxy" emitter applies the same live rule to that grid:
//
//   * a bar is FULL iff it starts at :30 and start+60min <= the session's close;
//     the session close per date is inferred as (last bar start + 30min), which
//     also catches half-days (12:30 stub -> 13:00 close). Non-full bars are
//     excluded from the series decideHourly sees (same hygiene as live's
//     isBarPartial) and never act.
//   * decideHourly sees the trailing 10 full bars (live's fetchCount for
//     hourlyContextMode="none"), contextMode "none".
//   * entryRef = the OPEN of the next bar in the file (the bar starting at the
//     signal bar's end). Live reads the latest trade at bar end + 7 min; with
//     1h-only data the nearest observable price is the next bar's open, 7
//     minutes earlier. Disclosed in the pre-registration (§4.2).
//   * stop/target/sizing validity from the live functions with the frozen
//     config.ts defaults (buffer 0.05, R=2, min stop 0.05, risk 0.01, cap 0.10).
//   * drift-control columns (pre-registration §6.4): the SAME live
//     geometry/sizing functions applied to EVERY full bar, both sides, whether
//     or not decideHourly fired. Not a decision rule -- an unconditional-entry
//     baseline that lets the study net symbol drift (survivorship) out of R.
//
// State-dependent gates (one position per symbol, cooldown, day cap, flatten
// scans) are owned by the Python simulator, exactly as in #571.
import type { Bar } from "../../../supabase/functions/_shared/candlestick.ts";
import { decideHourly } from "../../../supabase/functions/_shared/hourly_signal.ts";
import {
  computeBracketGeometry,
  computeSizing,
} from "../../../supabase/functions/hourly-check/logic.ts";

const FETCH_COUNT = 10;
const R_MULTIPLE = 2; // HOURLY_BRACKET_R_MULTIPLE, config.ts pins it to exactly 2
const STOP_BUFFER_PCT = 0.05; // HOURLY_STOP_BUFFER_PCT default
const MIN_STOP_DISTANCE = 0.05; // HOURLY_MIN_STOP_DISTANCE default
const SIZING_RISK_PCT = 0.01; // SIZING_RISK_PCT default
const SIZING_NOTIONAL_CAP_PCT = 0.10; // SIZING_NOTIONAL_CAP_PCT default
const NOMINAL_EQUITY = 1_000_000; // validity gate only; R stats are sizing-invariant
const HOUR_MS = 3_600_000;
const BLANK_CTRL = ",,,,,";

interface RawBar {
  ts: string;
  ms: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

function parseCsv(text: string): RawBar[] {
  const lines = text.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  const header = lines[0].split(",");
  const col = (n: string) => {
    const i = header.indexOf(n);
    if (i < 0) throw new Error(`missing column ${n}`);
    return i;
  };
  const [t, o, h, l, c] = ["timestamp", "Open", "High", "Low", "Close"].map(col);
  const out: RawBar[] = [];
  for (const line of lines.slice(1)) {
    const cols = line.split(",");
    const iso = cols[t].includes("T") ? cols[t] : cols[t].replace(" ", "T");
    out.push({
      ts: iso,
      ms: new Date(iso).getTime(),
      open: Number(cols[o]),
      high: Number(cols[h]),
      low: Number(cols[l]),
      close: Number(cols[c]),
    });
  }
  out.sort((a, b) => a.ms - b.ms);
  return out;
}

function nyDate(ms: number): string {
  // YYYY-MM-DD in America/New_York (the session's own date).
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(ms));
}

function controlColumns(b: RawBar, ref: number): string {
  const parts: string[] = [];
  for (const side of ["LONG", "SHORT"] as const) {
    const g = computeBracketGeometry(side, b, ref, {
      hourlyStopBufferPct: STOP_BUFFER_PCT,
      hourlyBracketRMultiple: R_MULTIPLE,
    });
    const sz = computeSizing(side, ref, g.stopPrice, NOMINAL_EQUITY, {
      sizingRiskPct: SIZING_RISK_PCT,
      sizingNotionalCapPct: SIZING_NOTIONAL_CAP_PCT,
      hourlyMinStopDistance: MIN_STOP_DISTANCE,
    });
    parts.push(`${g.stopPrice}`, `${g.targetPrice}`, `${sz.valid && sz.qty > 0}`);
  }
  return parts.join(",");
}

export function emitProxy(bars: RawBar[]): string[] {
  // Session close per NY date = last bar start + 30 min (Yahoo's :30 grid ends
  // with a 30-minute stub on both full and half days).
  const lastStart = new Map<string, number>();
  for (const b of bars) {
    const d = nyDate(b.ms);
    lastStart.set(d, Math.max(lastStart.get(d) ?? 0, b.ms));
  }
  const rows: string[] = [
    "timestamp,session_date,session_close_ms,is_full,action_raw,reason_raw,detectors_fired," +
    "fill_ts,entry_ref,stop_price,stop_distance,target_price,sizing_valid," +
    "ctrl_long_stop,ctrl_long_target,ctrl_long_valid,ctrl_short_stop,ctrl_short_target,ctrl_short_valid",
  ];
  const full: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const d = nyDate(b.ms);
    const closeMs = (lastStart.get(d) ?? b.ms) + 30 * 60_000;
    const minute = new Date(b.ms).getUTCMinutes();
    const isFull = minute === 30 && b.ms + HOUR_MS <= closeMs;
    if (!isFull) {
      rows.push(`${b.ts},${d},${closeMs},false,SKIP,partial_bar,,,,,,,false,${BLANK_CTRL}`);
      continue;
    }
    full.push({ open: b.open, high: b.high, low: b.low, close: b.close, timestamp: b.ts });
    const window = full.slice(-FETCH_COUNT);
    const dec = decideHourly(window, { contextMode: "none" });
    const fired = dec.detectorsFired.join(";");
    // Next bar in the file, same NY session, starting exactly at this bar's end.
    const nxt = i + 1 < bars.length ? bars[i + 1] : null;
    const hasFill = nxt !== null && nxt.ms === b.ms + HOUR_MS && nyDate(nxt.ms) === d;
    const ctrl = hasFill ? controlColumns(b, nxt!.open) : BLANK_CTRL;
    if (dec.action === "SKIP") {
      rows.push(`${b.ts},${d},${closeMs},true,SKIP,${dec.reason},${fired},,,,,,false,${ctrl}`);
      continue;
    }
    if (!hasFill) {
      rows.push(
        `${b.ts},${d},${closeMs},true,${dec.action},no_fill_bar,${fired},,,,,,false,${ctrl}`,
      );
      continue;
    }
    const entryRef = nxt!.open;
    const geom = computeBracketGeometry(dec.action, b, entryRef, {
      hourlyStopBufferPct: STOP_BUFFER_PCT,
      hourlyBracketRMultiple: R_MULTIPLE,
    });
    const sizing = computeSizing(dec.action, entryRef, geom.stopPrice, NOMINAL_EQUITY, {
      sizingRiskPct: SIZING_RISK_PCT,
      sizingNotionalCapPct: SIZING_NOTIONAL_CAP_PCT,
      hourlyMinStopDistance: MIN_STOP_DISTANCE,
    });
    const valid = sizing.valid && sizing.qty > 0;
    rows.push(
      `${b.ts},${d},${closeMs},true,${dec.action},${dec.reason},${fired},${nxt!.ts},${entryRef},` +
        `${geom.stopPrice},${sizing.stopDistance},${geom.targetPrice},${valid},${ctrl}`,
    );
  }
  return rows;
}

async function main(argv: string[]): Promise<void> {
  const get = (f: string) => {
    const i = argv.indexOf(f);
    return i < 0 ? undefined : argv[i + 1];
  };
  const inPath = get("--bars");
  const outPath = get("--out");
  if (!inPath || !outPath) throw new Error("usage: --bars <1h csv> --out <csv>");
  const rows = emitProxy(parseCsv(await Deno.readTextFile(inPath)));
  await Deno.writeTextFile(outPath, rows.join("\n") + "\n");
  console.log(`wrote ${rows.length - 1} rows to ${outPath}`);
}

if (import.meta.main) {
  await main(Deno.args);
}
