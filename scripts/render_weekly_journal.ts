// Weekly-review aggregator (#481, batch #478 Package C, spec
// docs/superpowers/specs/2026-07-27-hourly-bot-design.md §11/§14 finding
// 10). A standalone, read-only, operator-run script over `hourly_scans` +
// `trades` rendering `docs/trading-journal/YYYY-Www.md` -- per-detector
// firing rates, entries/exits with R-multiples, gate-skip distribution,
// equity trajectory vs the -15% floor, and the PROPOSAL_RULE trigger
// statistics. Not a cron, not an Edge Function.
//
// D1: TypeScript under scripts/, run via `deno run`, following
// scripts/backfill_equity_snapshots.ts's shape. D2: PostgREST via
// getServiceClient() + a gitignored .env.weekly. D3: DB-only equity
// sourcing -- this file MUST NOT import _shared/alpaca.ts or read any
// ALPACA_* env var. Allowed _shared imports: db.ts, supabase_client.ts,
// num.ts only (no Edge Function modules, no backtest/strategy imports).
import type { SupabaseClient } from "@supabase/supabase-js";
import { getServiceClient } from "../supabase/functions/_shared/supabase_client.ts";
import {
  type AuditLogRow,
  coerceHourlyScanRow,
  coerceTradeRow,
  type HourlyScanRow,
  type TradeRow,
} from "../supabase/functions/_shared/db.ts";
import { requireNumber } from "../supabase/functions/_shared/num.ts";

// ---------------------------------------------------------------------------
// T1 -- week-window math (pure, D4: every render-layer read is upper-bounded
// by the week window's end; the clock is only ever read in main()).
// ---------------------------------------------------------------------------

const WEEK_LABEL_RE = /^(\d{4})-W(\d{2})$/;

export interface WeekId {
  isoYear: number;
  isoWeek: number;
}

export class WeekLabelError extends Error {
  override name = "WeekLabelError";
}

/** Parses a `YYYY-Www` label. Throws WeekLabelError on any malformed input. */
export function parseWeekLabel(label: string): WeekId {
  const m = WEEK_LABEL_RE.exec(label);
  if (!m) {
    throw new WeekLabelError(`malformed week label, expected YYYY-Www: ${JSON.stringify(label)}`);
  }
  const isoYear = Number(m[1]);
  const isoWeek = Number(m[2]);
  if (isoWeek < 1 || isoWeek > 53) {
    throw new WeekLabelError(`malformed week label, week out of range 01-53: ${JSON.stringify(label)}`);
  }
  return { isoYear, isoWeek };
}

function formatWeekLabel(week: WeekId): string {
  return `${week.isoYear}-W${String(week.isoWeek).padStart(2, "0")}`;
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** ISO week 1's Monday is the Monday of the week containing 4 Jan (ISO 8601 rule). */
function isoWeekMondayYmd(week: WeekId): string {
  const jan4 = new Date(Date.UTC(week.isoYear, 0, 4));
  const jan4Dow = (jan4.getUTCDay() + 6) % 7; // Mon=0 .. Sun=6
  const week1Monday = jan4.getTime() - jan4Dow * MS_PER_DAY;
  const monday = new Date(week1Monday + (week.isoWeek - 1) * 7 * MS_PER_DAY);
  return monday.toISOString().slice(0, 10);
}

function addDaysYmd(ymd: string, days: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

const SHORT_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function formatDayMonth(ymd: string): string {
  const [, m, d] = ymd.split("-").map(Number);
  return `${d} ${SHORT_MONTHS[m - 1]}`;
}

// America/New_York's UTC offset (in minutes, positive = ET behind UTC) for a
// given calendar date. Probed at noon UTC (same technique
// supabase/functions/hourly-check/logic.ts's etOffsetMinutes uses) --
// reimplemented locally rather than imported, since hourly-check is an Edge
// Function module and this script's allowed _shared surface is db.ts /
// supabase_client.ts / num.ts only.
function etOffsetMinutes(dateYmd: string): number {
  const probe = new Date(`${dateYmd}T12:00:00Z`);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    hour12: false,
  }).formatToParts(probe);
  const hourPart = parts.find((p) => p.type === "hour")?.value ?? "12";
  const localHour = Number(hourPart) % 24;
  return (12 - localHour) * 60;
}

/** Converts an exchange-local HH:MM on `dateYmd` (ET) to a UTC ISO instant. */
function etHHMMToUtcIso(dateYmd: string, hhmm: string): string {
  const offsetMin = etOffsetMinutes(dateYmd);
  const [hh, mm] = hhmm.split(":").map(Number);
  const base = new Date(`${dateYmd}T00:00:00Z`).getTime();
  return new Date(base + (hh * 60 + mm + offsetMin) * 60 * 1000).toISOString();
}

export interface WeekWindow {
  /** Inclusive lower bound, UTC ISO instant for Monday 00:00 ET. */
  startIso: string;
  /** Exclusive upper bound, UTC ISO instant for Saturday 00:00 ET. */
  endIsoExclusive: string;
  /** Human title, e.g. "Week 2026-W31 (Mon 27 Jul -- Fri 31 Jul 2026)". */
  title: string;
}

/**
 * The ISO week's [Monday 00:00 ET, Saturday 00:00 ET) window, converted to
 * UTC (D4). The Saturday exclusive bound covers the full Friday ET calendar
 * day regardless of DST, without ever admitting the following week's data.
 */
export function weekWindowUtc(isoYear: number, isoWeek: number): WeekWindow {
  const week: WeekId = { isoYear, isoWeek };
  const mondayYmd = isoWeekMondayYmd(week);
  const fridayYmd = addDaysYmd(mondayYmd, 4);
  const saturdayYmd = addDaysYmd(mondayYmd, 5);
  const startIso = etHHMMToUtcIso(mondayYmd, "00:00");
  const endIsoExclusive = etHHMMToUtcIso(saturdayYmd, "00:00");
  const fridayYear = Number(fridayYmd.slice(0, 4));
  const title = `Week ${formatWeekLabel(week)} (Mon ${formatDayMonth(mondayYmd)} -- ` +
    `Fri ${formatDayMonth(fridayYmd)} ${fridayYear})`;
  return { startIso, endIsoExclusive, title };
}

/** The ISO week of a plain UTC-calendar date (used only to derive `previousCompletedWeek`). */
function isoWeekOfUtcDate(d: Date): WeekId {
  const date = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const isoWeek = Math.ceil(((date.getTime() - yearStart.getTime()) / MS_PER_DAY + 1) / 7);
  return { isoYear: date.getUTCFullYear(), isoWeek };
}

/**
 * The default `--week` target: the ISO week immediately before the one
 * containing `now`, resolved here (main()'s only clock read) so the render
 * layer below never sees a clock (D4). Subtracting a flat 7 calendar days
 * from `now`'s UTC date and taking *that* date's ISO week is exact because
 * ISO weeks are 7-day-aligned -- it also handles ISO-year rollovers for free.
 */
export function previousCompletedWeek(now: Date): WeekId {
  const sevenDaysAgo = new Date(now.getTime() - 7 * MS_PER_DAY);
  return isoWeekOfUtcDate(sevenDaysAgo);
}

// ---------------------------------------------------------------------------
// T2 -- arg parsing. Same ArgError/UnknownArgError split as
// scripts/backfill_equity_snapshots.ts (D6/D7): render mode is the default;
// `--record-accepted-bump --ref <...>` is a separate, mutually-exclusive
// mode that is the ONLY DB write in this script (D6).
// ---------------------------------------------------------------------------

export class ArgError extends Error {
  override name = "ArgError";
}
export class UnknownArgError extends ArgError {
  override name = "UnknownArgError";
}

export interface RenderArgs {
  mode: "render";
  help: boolean;
  week: string | undefined;
  out: string | undefined;
  force: boolean;
}

export interface BumpArgs {
  mode: "bump";
  help: boolean;
  ref: string;
}

export type ParsedArgs = RenderArgs | BumpArgs;

export function parseArgs(argv: string[]): ParsedArgs {
  let help = false;
  let week: string | undefined;
  let out: string | undefined;
  let force = false;
  let bump = false;
  let ref: string | undefined;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case "-h":
      case "--help":
        help = true;
        break;
      case "--week": {
        const val = argv[++i];
        if (val === undefined) throw new ArgError("--week requires a value (YYYY-Www)");
        week = val;
        break;
      }
      case "--out": {
        const val = argv[++i];
        if (val === undefined) throw new ArgError("--out requires a value (a file path)");
        out = val;
        break;
      }
      case "--force":
        force = true;
        break;
      case "--record-accepted-bump":
        bump = true;
        break;
      case "--ref": {
        const val = argv[++i];
        if (val === undefined) throw new ArgError("--ref requires a value");
        ref = val;
        break;
      }
      default:
        throw new UnknownArgError(`unknown argument: ${arg}`);
    }
  }

  // Help short-circuits before any mode-specific validation, so `-h` always
  // works regardless of what else was passed alongside it.
  if (help) {
    return bump ? { mode: "bump", help: true, ref: ref ?? "" } : {
      mode: "render",
      help: true,
      week,
      out,
      force,
    };
  }

  if (bump) {
    if (week !== undefined || out !== undefined || force) {
      throw new ArgError(
        "--record-accepted-bump is mutually exclusive with --week/--out/--force",
      );
    }
    if (ref === undefined) {
      throw new ArgError("--record-accepted-bump requires --ref <ADR-path-or-issue>");
    }
    return { mode: "bump", help: false, ref };
  }

  if (ref !== undefined) {
    throw new ArgError("--ref is only valid together with --record-accepted-bump");
  }

  return { mode: "render", help: false, week, out, force };
}

// ---------------------------------------------------------------------------
// T3 -- pairing + R-multiples (pure, spec §11/sub-plan). Entries/exits are
// paired sequentially per symbol (FIFO), keyed off `trades.reason`
// (ENTRY_REASONS/EXIT_REASONS) -- not `trades.side`, since BUY/SELL alone
// can't distinguish a long entry from a short exit. `panic_cli` fills are
// never paired (sub-plan's explicit rule): they are reported as manual
// interventions regardless of any open entry queued for that symbol.
// ---------------------------------------------------------------------------

const ENTRY_REASONS = new Set(["hourly_long_entry", "hourly_short_entry"]);
const EXIT_REASONS = new Set([
  "hourly_bracket_exit",
  "hourly_session_close_exit",
  "hourly_kill_switch",
]);

export interface ClosedTradeResult {
  symbol: string;
  side: "LONG" | "SHORT";
  entryFillPrice: number;
  entryFillTime: string;
  entryOrderId: string;
  exitFillPrice: number;
  exitFillTime: string;
  exitOrderId: string;
  exitReason: string;
  qty: number;
  /** Whole hours between entry and exit fills -- "holding bars" for an hourly bot. */
  holdingBars: number;
  rMultiple: number | null;
  /** Set only when rMultiple is null -- degrade-not-throw per the sub-plan. */
  rMultipleNaReason?: string;
}

export interface PairingResult {
  closedTrades: ClosedTradeResult[];
  openEntries: TradeRow[];
  orphanExits: TradeRow[];
  manualInterventions: TradeRow[];
}

const HOUR_MS = 60 * 60 * 1000;

function sideForEntryReason(reason: string): "LONG" | "SHORT" {
  return reason === "hourly_short_entry" ? "SHORT" : "LONG";
}

/**
 * Pairs a (bounded-by-week-end) trades list into closed round-trips, open
 * entries, orphan exits, and manual (`panic_cli`) interventions. `scans` is
 * matched by `entry_order_id` (spec §9/§14: `trades` has no `bar_ts`
 * column, so provenance is keyed on the entry's own broker order id).
 */
export function pairHourlyTrades(trades: TradeRow[], scans: HourlyScanRow[]): PairingResult {
  const scanByEntryOrderId = new Map<string, HourlyScanRow>();
  for (const s of scans) {
    if (s.entry_order_id) scanByEntryOrderId.set(s.entry_order_id, s);
  }

  const openQueueBySymbol = new Map<string, TradeRow[]>();
  const closedTrades: ClosedTradeResult[] = [];
  const orphanExits: TradeRow[] = [];
  const manualInterventions: TradeRow[] = [];

  const ordered = [...trades].sort((a, b) => a.fill_time.localeCompare(b.fill_time));
  for (const t of ordered) {
    if (t.reason === "panic_cli") {
      manualInterventions.push(t);
      continue;
    }
    if (ENTRY_REASONS.has(t.reason)) {
      const queue = openQueueBySymbol.get(t.symbol) ?? [];
      queue.push(t);
      openQueueBySymbol.set(t.symbol, queue);
      continue;
    }
    if (EXIT_REASONS.has(t.reason)) {
      const queue = openQueueBySymbol.get(t.symbol) ?? [];
      const entryTrade = queue.shift();
      if (!entryTrade) {
        orphanExits.push(t);
        continue;
      }
      const scanRow = scanByEntryOrderId.get(entryTrade.broker_order_id);
      const riskPerShare = scanRow?.risk_per_share ?? null;
      let rMultiple: number | null = null;
      let rMultipleNaReason: string | undefined;
      if (!scanRow) {
        rMultipleNaReason = `missing scan row for entry ${entryTrade.broker_order_id}`;
      } else if (riskPerShare == null || riskPerShare <= 0) {
        rMultipleNaReason = "risk_per_share unavailable";
      } else {
        const sign = sideForEntryReason(entryTrade.reason) === "LONG" ? 1 : -1;
        rMultiple = sign * (t.fill_price - entryTrade.fill_price) / riskPerShare;
      }
      const holdingBars = Math.round(
        (new Date(t.fill_time).getTime() - new Date(entryTrade.fill_time).getTime()) / HOUR_MS,
      );
      closedTrades.push({
        symbol: t.symbol,
        side: sideForEntryReason(entryTrade.reason),
        entryFillPrice: entryTrade.fill_price,
        entryFillTime: entryTrade.fill_time,
        entryOrderId: entryTrade.broker_order_id,
        exitFillPrice: t.fill_price,
        exitFillTime: t.fill_time,
        exitOrderId: t.broker_order_id,
        exitReason: t.reason,
        qty: entryTrade.qty,
        holdingBars,
        rMultiple,
        ...(rMultipleNaReason !== undefined ? { rMultipleNaReason } : {}),
      });
    }
  }

  const openEntries: TradeRow[] = [];
  for (const queue of openQueueBySymbol.values()) openEntries.push(...queue);

  return { closedTrades, openEntries, orphanExits, manualInterventions };
}

// ---------------------------------------------------------------------------
// T4 -- aggregation (pure). Per-detector firing counts/rates over scanned
// bars, decision/skip/audit-outcome distributions, and equity vs the -15%
// floor -- all restricted to the caller's already-windowed inputs (D4: the
// week window is enforced by the orchestration layer, T7).
// ---------------------------------------------------------------------------

// Mirrors supabase/functions/hourly-check/logic.ts's own EQUITY_FLOOR_PCT
// (spec §11's hard floor). Duplicated rather than imported: hourly-check is
// an Edge Function module, outside this script's allowed _shared surface
// (db.ts / supabase_client.ts / num.ts only). Kept in sync manually; a
// mismatch here would only affect this report's rendered text, never the
// live floor enforcement in hourly-check itself.
const EQUITY_FLOOR_PCT = 0.15;

export interface DetectorRate {
  name: string;
  fired: number;
  scanned: number;
  rate: number;
}

export interface WeeklyEquity {
  first: number | null;
  min: number | null;
  last: number | null;
  floorBaseline: number;
  floorPrice: number;
  breached: boolean;
}

export interface WeeklyAggregates {
  scansInWeek: number;
  detectorRates: DetectorRate[];
  decisionCounts: { LONG: number; SHORT: number; SKIP: number };
  skipReasonCounts: Record<string, number>;
  auditOutcomeCounts: Record<string, number>;
  autoPausedTimestamps: string[];
  equity: WeeklyEquity;
}

export function computeWeeklyAggregates(
  scansInWeek: HourlyScanRow[],
  auditRowsInWeek: AuditLogRow[],
  floorBaseline: number,
): WeeklyAggregates {
  const scans = [...scansInWeek].sort((a, b) => a.bar_ts.localeCompare(b.bar_ts));

  const firedCounts = new Map<string, number>();
  const decisionCounts = { LONG: 0, SHORT: 0, SKIP: 0 };
  const skipReasonCounts: Record<string, number> = {};
  for (const s of scans) {
    decisionCounts[s.decision]++;
    for (const name of s.detectors_fired) {
      firedCounts.set(name, (firedCounts.get(name) ?? 0) + 1);
    }
    if (s.decision === "SKIP") {
      const reason = s.skip_reason ?? "unspecified";
      skipReasonCounts[reason] = (skipReasonCounts[reason] ?? 0) + 1;
    }
  }
  const detectorRates: DetectorRate[] = [...firedCounts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, fired]) => ({ name, fired, scanned: scans.length, rate: fired / scans.length }));

  const auditOutcomeCounts: Record<string, number> = {};
  const autoPausedTimestamps: string[] = [];
  for (const row of auditRowsInWeek) {
    const outcome = row.outcome ?? "unfinished";
    auditOutcomeCounts[outcome] = (auditOutcomeCounts[outcome] ?? 0) + 1;
    if (row.outcome === "success:auto_paused") autoPausedTimestamps.push(row.started_at);
  }

  const equities = scans.map((s) => s.equity_usd);
  const floorPrice = floorBaseline * (1 - EQUITY_FLOOR_PCT);
  const equity: WeeklyEquity = {
    first: equities.length > 0 ? equities[0] : null,
    min: equities.length > 0 ? Math.min(...equities) : null,
    last: equities.length > 0 ? equities[equities.length - 1] : null,
    floorBaseline,
    floorPrice,
    breached: equities.some((e) => e <= floorPrice),
  };

  return {
    scansInWeek: scans.length,
    detectorRates,
    decisionCounts,
    skipReasonCounts,
    auditOutcomeCounts,
    autoPausedTimestamps,
    equity,
  };
}

export interface CumulativeStats {
  closedTradeCount: number;
  winRate: number | null;
  targetHitRate: number | null;
  meanR: number | null;
  sumR: number | null;
}

/**
 * Cumulative [experiment start, weekEnd) stats over ALL closed trades
 * (T7 passes the full pairing result, not just this week's). A trade with
 * a degraded (n/a) R still counts toward `closedTradeCount` -- the sample
 * size the PROPOSAL_RULE's minimum-sample gate cares about -- but is
 * excluded from the win/target-hit numerators and the mean/sum R, so a
 * missing-data trade can never be silently counted as a win.
 *
 * "Target hit" is this script's own operational definition, disclosed in
 * the PR: a closed trade whose exit was `hourly_bracket_exit` (the bracket's
 * take-profit or stop-loss leg, as opposed to a forced session-close/
 * kill-switch exit) AND whose R is positive -- i.e. the take-profit leg
 * specifically filled, not the stop. `trades`/`hourly_scans` don't record
 * which bracket leg filled directly, so this R-sign proxy is the closest
 * derivable signal.
 */
export function computeCumulativeStats(closedTrades: ClosedTradeResult[]): CumulativeStats {
  const n = closedTrades.length;
  if (n === 0) {
    return { closedTradeCount: 0, winRate: null, targetHitRate: null, meanR: null, sumR: null };
  }
  const withR = closedTrades.filter((t): t is ClosedTradeResult & { rMultiple: number } =>
    t.rMultiple !== null
  );
  const winners = withR.filter((t) => t.rMultiple > 0).length;
  const targetHits = closedTrades.filter(
    (t) => t.exitReason === "hourly_bracket_exit" && t.rMultiple !== null && t.rMultiple > 0,
  ).length;
  const sumR = withR.length > 0 ? withR.reduce((s, t) => s + t.rMultiple, 0) : null;
  const meanR = withR.length > 0 && sumR !== null ? sumR / withR.length : null;

  return {
    closedTradeCount: n,
    winRate: winners / n,
    targetHitRate: targetHits / n,
    meanR,
    sumR,
  };
}
