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
    throw new WeekLabelError(
      `malformed week label, week out of range 01-53: ${JSON.stringify(label)}`,
    );
  }
  const weeksInYear = isoWeeksInYear(isoYear);
  if (isoWeek > weeksInYear) {
    throw new WeekLabelError(
      `malformed week label, ${isoYear} has only ${weeksInYear} ISO weeks: ${
        JSON.stringify(label)
      }`,
    );
  }
  return { isoYear, isoWeek };
}

export function formatWeekLabel(week: WeekId): string {
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
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
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
 * The number of ISO weeks (52 or 53) in `isoYear` (finding 9, PR #482 fix
 * round 1). 28 December always falls in that ISO year's last week by
 * construction (ISO 8601's "the week containing the year's first Thursday"
 * rule), so its ISO week number is the answer.
 */
function isoWeeksInYear(isoYear: number): number {
  return isoWeekOfUtcDate(new Date(Date.UTC(isoYear, 11, 28))).isoWeek;
}

/**
 * The default `--week` target: the most recent FULLY-ELAPSED Mon-Sat ET
 * window as of `now`, resolved here (main()'s only clock read) so the
 * render layer below never sees a clock (D4).
 *
 * The ISO week containing `now`'s UTC calendar date runs Mon-Sun, which is a
 * superset of the trading window's Mon-Sat ET span -- so if `now` has
 * already reached that week's Saturday-00:00-ET window end (i.e. `now` is
 * Saturday or Sunday ET), the containing week itself is the most recently
 * elapsed one (finding 3, PR #482 fix round 1: a flat 7-day subtraction
 * under-counts by exactly one week on and after the Saturday a week ends,
 * leaving the review loop permanently a week behind the runbook's "run it on
 * or after the Saturday" cadence). Otherwise the containing week hasn't
 * ended yet, so step back a flat 7 calendar days (exact, since ISO weeks are
 * 7-day-aligned) to the previous ISO week -- this also handles ISO-year
 * rollovers for free.
 */
export function previousCompletedWeek(now: Date): WeekId {
  const containing = isoWeekOfUtcDate(now);
  const containingWindow = weekWindowUtc(containing.isoYear, containing.isoWeek);
  if (now.getTime() >= Date.parse(containingWindow.endIsoExclusive)) {
    return containing;
  }
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

// ---------------------------------------------------------------------------
// T5 -- proposal rule (D5). Structurally caps the review at <=1 proposal:
// proposeParamChange evaluates a ranked candidate list and returns the FIRST
// triggered candidate, never more than one. A minimum-sample gate
// short-circuits below PROPOSAL_MIN_CLOSED_TRADES, rendering an explicit
// "no proposal permitted" line even when a candidate's statistic would
// otherwise have fired -- the two §11 constraints, mechanically enforced.
//
// These numbers (the sample floor, the hit-rate floor, and the single
// default candidate) are the operator's to amend -- disclosed as defaults
// in the PR, same pattern as §11's own 4-week/30-trade stopping rule.
// ---------------------------------------------------------------------------

export const PROPOSAL_MIN_CLOSED_TRADES = 30;
export const TARGET_HIT_RATE_FLOOR = 0.25;

export interface ProposalCandidate {
  name: string;
  check: (stats: CumulativeStats) => boolean;
  render: (stats: CumulativeStats) => string;
}

// §11's own worked example: break-even at a 2:1 bracket is 33.3%, so a 25%
// floor is comfortably below break-even before it fires.
export const DEFAULT_PROPOSAL_CANDIDATES: ProposalCandidate[] = [
  {
    name: "target_hit_rate_floor",
    check: (s) => s.targetHitRate !== null && s.targetHitRate < TARGET_HIT_RATE_FLOOR,
    render: (s) =>
      `§7 HOURLY_BRACKET_R_MULTIPLE: 2 -> 3 (target hit rate ${
        ((s.targetHitRate ?? 0) * 100).toFixed(1)
      }% over N=${s.closedTradeCount} trades, below the ${
        (TARGET_HIT_RATE_FLOOR * 100).toFixed(0)
      }% floor; minimum sample N>=${PROPOSAL_MIN_CLOSED_TRADES})`,
  },
];

export type ProposalOutcome =
  | { gated: true; reason: string }
  | { gated: false; proposal: string | null };

export function proposeParamChange(
  cumulative: CumulativeStats,
  candidates: ProposalCandidate[] = DEFAULT_PROPOSAL_CANDIDATES,
): ProposalOutcome {
  if (cumulative.closedTradeCount < PROPOSAL_MIN_CLOSED_TRADES) {
    return {
      gated: true,
      reason:
        `no proposal permitted (N=${cumulative.closedTradeCount} < ${PROPOSAL_MIN_CLOSED_TRADES})`,
    };
  }
  for (const c of candidates) {
    if (c.check(cumulative)) return { gated: false, proposal: c.render(cumulative) };
  }
  return { gated: false, proposal: null };
}

// ---------------------------------------------------------------------------
// T6 -- renderer (pure). renderJournal is a straight function of its input;
// it never reads a clock (D4 -- "No Date.now() in rendered content; the only
// as-of-run value is the trial-count read, labelled in the footer").
// ---------------------------------------------------------------------------

export interface RenderData {
  title: string;
  agg: WeeklyAggregates;
  closedTradesInWeek: ClosedTradeResult[];
  openEntries: TradeRow[];
  orphanExitsInWeek: TradeRow[];
  manualInterventionsInWeek: TradeRow[];
  cumulative: CumulativeStats;
  proposal: ProposalOutcome;
  trialCount: number;
}

function fmtMoney(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Null-aware money formatting, mirroring fmtPct's null -> "n/a" convention
// (finding 1, PR #482 fix round 1): a week with audit rows but zero
// hourly_scans rows carries genuine nulls for first/min/last equity -- never
// coerce those to $0.00.
function fmtMoneyOrNa(n: number | null): string {
  return n === null ? "n/a (no scans this week)" : `$${fmtMoney(n)}`;
}

function fmtPct(n: number | null): string {
  return n === null ? "n/a" : `${(n * 100).toFixed(1)}%`;
}

function fmtR(n: number | null): string {
  return n === null ? "n/a" : n.toFixed(2);
}

function table(header: string[], rows: string[][]): string {
  const headerLine = `| ${header.join(" | ")} |`;
  const sepLine = `|${header.map(() => "---").join("|")}|`;
  const rowLines = rows.map((r) => `| ${r.join(" | ")} |`);
  return [headerLine, sepLine, ...rowLines].join("\n");
}

function renderIsQuietWeek(data: RenderData): boolean {
  return data.agg.scansInWeek === 0 &&
    data.closedTradesInWeek.length === 0 &&
    data.openEntries.length === 0 &&
    data.orphanExitsInWeek.length === 0 &&
    data.manualInterventionsInWeek.length === 0 &&
    Object.keys(data.agg.auditOutcomeCounts).length === 0;
}

function renderProposalSection(proposal: ProposalOutcome): string {
  if (proposal.gated) return proposal.reason;
  return proposal.proposal ?? "No proposal triggered this week.";
}

function renderCumulativeSection(cumulative: CumulativeStats): string {
  return [
    `- Closed trades (N): ${cumulative.closedTradeCount}`,
    `- Win rate: ${fmtPct(cumulative.winRate)}`,
    `- Target-hit rate: ${fmtPct(cumulative.targetHitRate)}`,
    `- Mean R: ${fmtR(cumulative.meanR)}`,
    `- Sum R: ${fmtR(cumulative.sumR)}`,
    "",
    "Target-hit is a proxy (`hourly_bracket_exit` exit reason AND R > 0 -- the schema does not " +
    "record which bracket leg filled), and both rates divide by a denominator that includes " +
    "R-unavailable trades, so both are floors, not point estimates.",
  ].join("\n");
}

function renderFooter(trialCount: number): string {
  return `**Trial counter (as of this run):** \`hourly_param_trial_count\` = ${trialCount}`;
}

/**
 * Renders the full hourly-era journal entry as markdown. Fixed section set
 * (D7): detector firing rates, decisions, entries/exits, open positions,
 * manual interventions, gate-skip distribution (two sources: bar-level
 * `hourly_scans.skip_reason` and run-level `audit_log` outcomes -- disclosed
 * separately since they answer different questions), equity vs the -15%
 * floor, cumulative stats, the PROPOSAL_RULE result, and an empty
 * "Notes (operator)" section for the human to fill in.
 *
 * An all-quiet week (no scans, no trades, no audit rows) renders the
 * journal README's brief style instead of a page of empty tables.
 */
export function renderJournal(data: RenderData): string {
  const { agg } = data;

  if (renderIsQuietWeek(data)) {
    return [
      `# ${data.title}`,
      "",
      "No scans recorded and no trades filed this week -- the bot appears to have been paused " +
      "or not deployed for the full week. See `bot_config.paused` and `audit_log` for the reason.",
      "",
      "---",
      "",
      "## Cumulative stats (since experiment start)",
      "",
      renderCumulativeSection(data.cumulative),
      "",
      "## Proposal (PROPOSAL_RULE)",
      "",
      renderProposalSection(data.proposal),
      "",
      "## Notes (operator)",
      "",
      "_None yet._",
      "",
      "---",
      "",
      renderFooter(data.trialCount),
      "",
    ].join("\n");
  }

  const detectorTable = agg.detectorRates.length > 0
    ? table(
      ["Detector", "Fired", "Scanned", "Rate"],
      agg.detectorRates.map((d) => [d.name, String(d.fired), String(d.scanned), fmtPct(d.rate)]),
    )
    : "_No scans recorded this week._";

  const closedTable = data.closedTradesInWeek.length > 0
    ? table(
      ["Symbol", "Side", "Entry fill", "Exit fill", "Qty", "R", "Holding (bars)", "Exit reason"],
      data.closedTradesInWeek.map((t) => [
        t.symbol,
        t.side,
        fmtMoney(t.entryFillPrice),
        fmtMoney(t.exitFillPrice),
        String(t.qty),
        t.rMultiple !== null ? fmtR(t.rMultiple) : `n/a (${t.rMultipleNaReason})`,
        String(t.holdingBars),
        t.exitReason,
      ]),
    )
    : "_No closed trades this week._";

  const openTable = data.openEntries.length > 0
    ? table(
      ["Symbol", "Side", "Entry fill", "Entry time", "Broker order id"],
      data.openEntries.map((t) => [
        t.symbol,
        t.reason === "hourly_short_entry" ? "SHORT" : "LONG",
        fmtMoney(t.fill_price),
        t.fill_time,
        t.broker_order_id,
      ]),
    )
    : "_None._";

  const orphanTable = data.orphanExitsInWeek.length > 0
    ? table(
      ["Symbol", "Fill price", "Fill time", "Reason", "Broker order id"],
      data.orphanExitsInWeek.map((t) => [
        t.symbol,
        fmtMoney(t.fill_price),
        t.fill_time,
        t.reason,
        t.broker_order_id,
      ]),
    )
    : "_None._";

  const manualTable = data.manualInterventionsInWeek.length > 0
    ? table(
      ["Symbol", "Side", "Fill price", "Fill time", "Broker order id"],
      data.manualInterventionsInWeek.map((t) => [
        t.symbol,
        t.side,
        fmtMoney(t.fill_price),
        t.fill_time,
        t.broker_order_id,
      ]),
    )
    : "_None._";

  const skipReasonEntries = Object.entries(agg.skipReasonCounts).sort(([a], [b]) =>
    a.localeCompare(b)
  );
  const skipTable = skipReasonEntries.length > 0
    ? table(["Skip reason", "Count"], skipReasonEntries.map(([k, v]) => [k, String(v)]))
    : "_No skips this week._";

  const auditEntries = Object.entries(agg.auditOutcomeCounts).sort(([a], [b]) =>
    a.localeCompare(b)
  );
  const auditTable = auditEntries.length > 0
    ? table(["Outcome", "Count"], auditEntries.map(([k, v]) => [k, String(v)]))
    : "_No hourly-check audit_log rows this week._";

  const autoPausedLine = agg.autoPausedTimestamps.length > 0
    ? agg.autoPausedTimestamps.join(", ")
    : "_None._";

  return [
    `# ${data.title}`,
    "",
    "---",
    "",
    "## Detector firing rates",
    "",
    "Only detectors that fired at least once this week are listed; a detector's absence means it " +
    "did not fire this week, not that it was retired -- see `_shared/candlestick.ts` for the " +
    "canonical registry.",
    "",
    detectorTable,
    "",
    "---",
    "",
    "## Decisions",
    "",
    `- LONG: ${agg.decisionCounts.LONG}`,
    `- SHORT: ${agg.decisionCounts.SHORT}`,
    `- SKIP: ${agg.decisionCounts.SKIP}`,
    "",
    "---",
    "",
    "## Entries & exits (closed this week)",
    "",
    closedTable,
    "",
    "## Open positions at week end",
    "",
    openTable,
    "",
    "## Orphan exits (no matching queued entry)",
    "",
    orphanTable,
    "",
    "## Manual interventions (`panic_cli`)",
    "",
    manualTable,
    "",
    "---",
    "",
    "## Gate-skip distribution",
    "",
    "Two sources (sub-plan's disclosed two-source gate-skip distribution): bar-level skips " +
    "from `hourly_scans.skip_reason`, and run-level exits from `audit_log` " +
    "(`script_name='hourly-check'`) -- a bar can be scanned and skipped without the run " +
    "itself being a gate exit, and vice versa.",
    "",
    "### Bar-level (`hourly_scans.skip_reason`)",
    "",
    skipTable,
    "",
    "### Run-level (`audit_log.outcome`)",
    "",
    auditTable,
    "",
    "---",
    "",
    "## Equity vs the -15% floor",
    "",
    `- First: ${fmtMoneyOrNa(agg.equity.first)}`,
    `- Min: ${fmtMoneyOrNa(agg.equity.min)}`,
    `- Last: ${fmtMoneyOrNa(agg.equity.last)}`,
    `- Floor baseline (\`hourly_experiment_start_equity\`): $${fmtMoney(agg.equity.floorBaseline)}`,
    `- Floor price (-15%): $${fmtMoney(agg.equity.floorPrice)}`,
    `- Breached this week: ${
      agg.equity.first === null ? "n/a" : (agg.equity.breached ? "yes" : "no")
    }`,
    `- Auto-paused events (\`success:auto_paused\`): ${autoPausedLine}`,
    "",
    "---",
    "",
    "## Cumulative stats (since experiment start)",
    "",
    renderCumulativeSection(data.cumulative),
    "",
    "## Proposal (PROPOSAL_RULE)",
    "",
    renderProposalSection(data.proposal),
    "",
    "## Notes (operator)",
    "",
    "_None yet._",
    "",
    "---",
    "",
    renderFooter(data.trialCount),
    "",
  ].join("\n");
}

// ---------------------------------------------------------------------------
// T7 -- orchestration (deps-injected), thin PostgREST adapters, and main().
// Every query is upper-bounded by the week window's end (D4); the render
// layer above never sees a clock -- `deps.now()` is read exactly once, here,
// to resolve the default `--week`.
// ---------------------------------------------------------------------------

export class JournalExistsError extends Error {
  override name = "JournalExistsError";
}
export class MissingBaselineError extends Error {
  override name = "MissingBaselineError";
}

export interface WeeklyReviewDeps {
  now: () => Date;
  db: {
    getScansUntil: (untilIsoExclusive: string) => Promise<HourlyScanRow[]>;
    // Takes the scans already fetched by getScansUntil above (same window)
    // so the traded symbol can be derived without a second hourly_scans
    // select (finding 10, PR #482 fix round 1).
    getHourlyTradesUntil: (
      untilIsoExclusive: string,
      scansInWindow: HourlyScanRow[],
    ) => Promise<TradeRow[]>;
    getAuditOutcomesUntil: (untilIsoExclusive: string) => Promise<AuditLogRow[]>;
    getConfig: (key: string) => Promise<string | null>;
    setConfig: (key: string, value: string) => Promise<void>;
  };
  fileExists: (path: string) => Promise<boolean>;
  writeFile: (path: string, content: string) => Promise<void>;
  log: (line: string) => void;
}

export type RunOpts =
  | { mode: "render"; week?: string; out?: string; force: boolean }
  | { mode: "bump"; ref: string };

export interface RenderSummary {
  mode: "render";
  weekLabel: string;
  outPath: string;
  markdown: string;
}

export interface BumpSummary {
  mode: "bump";
  oldCount: number;
  newCount: number;
  ref: string;
}

// PostgREST returns timestamps with a `+00:00` offset suffix rather than
// `.000Z`; comparing those raw ISO strings against toISOString() bounds is
// wrong at an exact bound because '+' (0x2B) sorts before '.' (0x2E) in
// ASCII, inverting both boundary senses (finding 4, PR #482 fix round 1).
// Comparing parsed epoch milliseconds against precomputed bounds is correct
// regardless of the source string's offset formatting.
function withinWindow(iso: string, bounds: { startMs: number; endMsExclusive: number }): boolean {
  const t = Date.parse(iso);
  return t >= bounds.startMs && t < bounds.endMsExclusive;
}

async function runBumpMode(deps: WeeklyReviewDeps, ref: string): Promise<BumpSummary> {
  const raw = await deps.db.getConfig("hourly_param_trial_count");
  const oldCount = raw == null ? 0 : requireNumber(raw, "hourly_param_trial_count");
  const newCount = oldCount + 1;
  await deps.db.setConfig("hourly_param_trial_count", String(newCount));
  deps.log(`hourly_param_trial_count: ${oldCount} -> ${newCount} (ref: ${ref})`);
  return { mode: "bump", oldCount, newCount, ref };
}

async function runRenderMode(
  deps: WeeklyReviewDeps,
  opts: { week?: string; out?: string; force: boolean },
): Promise<RenderSummary> {
  const week = opts.week !== undefined
    ? parseWeekLabel(opts.week)
    : previousCompletedWeek(deps.now());
  const weekLabel = formatWeekLabel(week);
  const win = weekWindowUtc(week.isoYear, week.isoWeek);
  const outPath = opts.out ?? `docs/trading-journal/${weekLabel}.md`;

  if (!opts.force && await deps.fileExists(outPath)) {
    throw new JournalExistsError(
      `${outPath} already exists -- pass --force to overwrite (journal entries are never ` +
        "overwritten silently)",
    );
  }

  const baselineRaw = await deps.db.getConfig("hourly_experiment_start_equity");
  if (baselineRaw == null) {
    throw new MissingBaselineError(
      "bot_config.hourly_experiment_start_equity is not set -- required before any weekly " +
        "review can be rendered (set once at paper-experiment start, spec §11).",
    );
  }
  const floorBaseline = requireNumber(baselineRaw, "hourly_experiment_start_equity");

  const trialCountRaw = await deps.db.getConfig("hourly_param_trial_count");
  const trialCount = trialCountRaw == null
    ? 0
    : requireNumber(trialCountRaw, "hourly_param_trial_count");

  // Every read is bounded above by the window's end (D4) -- re-running this
  // report weeks later reproduces the identical file.
  const allScans = await deps.db.getScansUntil(win.endIsoExclusive);
  // Reuses `allScans` (already fetched above) to derive the traded symbol,
  // instead of re-issuing the full hourly_scans select a second time just
  // for that (finding 10, PR #482 fix round 1) -- see the main() adapter
  // wiring below.
  const allTrades = await deps.db.getHourlyTradesUntil(win.endIsoExclusive, allScans);
  const allAuditRows = await deps.db.getAuditOutcomesUntil(win.endIsoExclusive);

  const winBounds = {
    startMs: Date.parse(win.startIso),
    endMsExclusive: Date.parse(win.endIsoExclusive),
  };
  const scansInWeek = allScans.filter((s) => withinWindow(s.bar_ts, winBounds));
  const auditRowsInWeek = allAuditRows.filter((r) => withinWindow(r.started_at, winBounds));

  // Pairing runs over the FULL history up to week end (not just this week's
  // trades), so a position opened last week and closed this week pairs
  // correctly, and "open at week end" reflects true end-of-week state.
  const pairing = pairHourlyTrades(allTrades, allScans);
  const closedTradesInWeek = pairing.closedTrades.filter((t) =>
    withinWindow(t.exitFillTime, winBounds)
  );
  const orphanExitsInWeek = pairing.orphanExits.filter((t) => withinWindow(t.fill_time, winBounds));
  const manualInterventionsInWeek = pairing.manualInterventions.filter((t) =>
    withinWindow(t.fill_time, winBounds)
  );

  const agg = computeWeeklyAggregates(scansInWeek, auditRowsInWeek, floorBaseline);
  const cumulative = computeCumulativeStats(pairing.closedTrades);
  const proposal = proposeParamChange(cumulative);

  const markdown = renderJournal({
    title: win.title,
    agg,
    closedTradesInWeek,
    openEntries: pairing.openEntries,
    orphanExitsInWeek,
    manualInterventionsInWeek,
    cumulative,
    proposal,
    trialCount,
  });

  await deps.writeFile(outPath, markdown);
  deps.log(`wrote ${outPath}`);

  return { mode: "render", weekLabel, outPath, markdown };
}

export function runWeeklyReview(
  deps: WeeklyReviewDeps,
  opts: RunOpts,
): Promise<RenderSummary | BumpSummary> {
  return opts.mode === "bump" ? runBumpMode(deps, opts.ref) : runRenderMode(deps, opts);
}

// ---------------------------------------------------------------------------
// Real-deps adapters (untested, per the backfill precedent -- thin wrappers
// over `sb`, reusing coerceHourlyScanRow/coerceTradeRow so no business logic
// lives here). Every select is upper-bounded by `untilIsoExclusive` plus a
// defensive `.limit()`, mirroring _shared/db.ts's existing windowed reads.
// ---------------------------------------------------------------------------

// A conservative cap: an hourly bot scans at most ~7 bars/session x 5
// sessions/week; even several years of history stays well under this.
const SCANS_ROW_CAP = 20000;
const TRADES_ROW_CAP = 5000;
const AUDIT_ROW_CAP = 20000;

export async function getScansUntilAdapter(
  sb: SupabaseClient,
  untilIsoExclusive: string,
): Promise<HourlyScanRow[]> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("*")
    .lt("bar_ts", untilIsoExclusive)
    .order("bar_ts", { ascending: true })
    .limit(SCANS_ROW_CAP);
  if (error) throw new Error(`getScansUntil: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceHourlyScanRow);
}

// hourly_* reasons are unique to this bot's own trades. `panic_cli` is
// shared with the retired daily bot's own liquidate path, so it is scoped
// to `symbol` (derived by the caller from the scans it already read) to
// avoid pulling in an unrelated bot's manual interventions -- disclosed in
// the PR as the two-source-gate-skip-style scoping this script relies on.
const HOURLY_TRADE_REASONS = [
  "hourly_long_entry",
  "hourly_short_entry",
  "hourly_bracket_exit",
  "hourly_session_close_exit",
  "hourly_kill_switch",
];

export async function getHourlyTradesUntilAdapter(
  sb: SupabaseClient,
  untilIsoExclusive: string,
  symbol: string,
): Promise<TradeRow[]> {
  const { data: hourlyRows, error: hourlyError } = await sb
    .from("trades")
    .select("symbol, side, qty, fill_price, fill_time, reason, broker_order_id")
    .in("reason", HOURLY_TRADE_REASONS)
    .lt("fill_time", untilIsoExclusive)
    .order("fill_time", { ascending: true })
    .limit(TRADES_ROW_CAP);
  if (hourlyError) throw new Error(`getHourlyTradesUntil: ${hourlyError.message}`);

  const { data: panicRows, error: panicError } = await sb
    .from("trades")
    .select("symbol, side, qty, fill_price, fill_time, reason, broker_order_id")
    .eq("reason", "panic_cli")
    .eq("symbol", symbol)
    .lt("fill_time", untilIsoExclusive)
    .order("fill_time", { ascending: true })
    .limit(TRADES_ROW_CAP);
  if (panicError) throw new Error(`getHourlyTradesUntil (panic_cli): ${panicError.message}`);

  return [
    ...((hourlyRows ?? []) as Record<string, unknown>[]).map(coerceTradeRow),
    ...((panicRows ?? []) as Record<string, unknown>[]).map(coerceTradeRow),
  ];
}

export async function getAuditOutcomesUntilAdapter(
  sb: SupabaseClient,
  untilIsoExclusive: string,
): Promise<AuditLogRow[]> {
  const { data, error } = await sb
    .from("audit_log")
    .select("script_name, started_at, finished_at, outcome, notes")
    .eq("script_name", "hourly-check")
    .lt("started_at", untilIsoExclusive)
    .order("started_at", { ascending: true })
    .limit(AUDIT_ROW_CAP);
  if (error) throw new Error(`getAuditOutcomesUntil: ${error.message}`);
  return (data ?? []) as AuditLogRow[];
}

async function getConfigAdapter(sb: SupabaseClient, key: string): Promise<string | null> {
  const { data, error } = await sb.from("bot_config").select("value").eq("key", key).maybeSingle();
  if (error) throw new Error(`getConfig: ${error.message}`);
  return (data as { value: string } | null)?.value ?? null;
}

async function setConfigAdapter(sb: SupabaseClient, key: string, value: string): Promise<void> {
  const { error } = await sb.from("bot_config").upsert(
    { key, value, updated_at: new Date().toISOString() },
    { onConflict: "key" },
  );
  if (error) throw new Error(`setConfig: ${error.message}`);
}

// The traded symbol is derived from hourly_scans itself (one bot instance,
// one symbol) rather than read from _shared/config.ts -- this script's
// allowed _shared surface is db.ts/supabase_client.ts/num.ts only. Falls
// back to "SPY" (the documented HOURLY_BOT_TICKER default) when no scan
// has ever been recorded.
const DEFAULT_SYMBOL = "SPY";

function deriveSymbol(scans: HourlyScanRow[]): string {
  return scans[0]?.symbol ?? DEFAULT_SYMBOL;
}

// ---------------------------------------------------------------------------
// CLI entry point. Not exercised by any test, per the backfill precedent --
// everything above this point is unit-tested with injected deps/mocks.
// ---------------------------------------------------------------------------

function usage(): string {
  return [
    "Usage: deno run --allow-env --allow-net --allow-write=docs/trading-journal \\",
    "  --env-file=.env.weekly scripts/render_weekly_journal.ts [options]",
    "",
    "Renders the operator-run weekly review journal from hourly_scans + trades.",
    "",
    "Render mode (default):",
    "  --week YYYY-Www     ISO week to render (default: the previous completed week)",
    "  --out PATH          output path (default: docs/trading-journal/<week>.md)",
    "  --force              overwrite an existing journal file (refused by default)",
    "",
    "Trial-counter mode (the only DB write this script ever makes):",
    "  --record-accepted-bump --ref <ADR-path-or-issue>",
    "                       increments bot_config.hourly_param_trial_count by 1",
    "",
    "  -h, --help           show this help",
    "",
    "See docs/runbooks/weekly-review.md for the full procedure.",
  ].join("\n");
}

async function main(): Promise<void> {
  let parsed: ParsedArgs;
  try {
    parsed = parseArgs(Deno.args);
  } catch (e) {
    console.error(`error: ${(e as Error).message}`);
    if (e instanceof UnknownArgError) {
      console.error("");
      console.error(usage());
    }
    Deno.exit(1);
    return;
  }

  if (parsed.help) {
    console.log(usage());
    Deno.exit(0);
    return;
  }

  try {
    const sb = getServiceClient();
    const deps: WeeklyReviewDeps = {
      now: () => new Date(),
      db: {
        getScansUntil: (untilIso) => getScansUntilAdapter(sb, untilIso),
        getHourlyTradesUntil: (untilIso, scans) => {
          return getHourlyTradesUntilAdapter(sb, untilIso, deriveSymbol(scans));
        },
        getAuditOutcomesUntil: (untilIso) => getAuditOutcomesUntilAdapter(sb, untilIso),
        getConfig: (key) => getConfigAdapter(sb, key),
        setConfig: (key, value) => setConfigAdapter(sb, key, value),
      },
      fileExists: async (path) => {
        try {
          await Deno.stat(path);
          return true;
        } catch (e) {
          if (e instanceof Deno.errors.NotFound) return false;
          throw e;
        }
      },
      writeFile: (path, content) => Deno.writeTextFile(path, content),
      log: (line) => console.log(line),
    };

    const opts: RunOpts = parsed.mode === "bump"
      ? { mode: "bump", ref: parsed.ref }
      : { mode: "render", week: parsed.week, out: parsed.out, force: parsed.force };

    await runWeeklyReview(deps, opts);
    Deno.exit(0);
  } catch (e) {
    console.error(`error: ${(e as Error).message}`);
    Deno.exit(1);
  }
}

if (import.meta.main) {
  main();
}
