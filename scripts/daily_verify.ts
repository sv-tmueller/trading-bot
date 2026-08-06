// Daily verification (#547, batch #545 Package B; spec
// docs/superpowers/specs/2026-08-06-daily-verification-design.md). Shaped
// exactly like scripts/deadman_check.ts and scripts/render_weekly_journal.ts:
// a pure evaluation-and-rendering core plus a thin CLI. Unlike
// deadman_check.ts's zero-permission CLI, this one's main() DOES touch disk
// (cross-day ledger state and both artifacts live under
// docs/trading-journal/), per §5.5's lead ruling -- but every judgment still
// lives in a pure function with no I/O, so "re-running a date reproduces
// byte-identical output" is a unit-testable claim, not a workflow-run
// assertion.
//
// CLI contract (§5.5, frozen -- .github/workflows/daily-verification.yml
// (#549) is written against this exact shape):
//
//   deno run --allow-read=docs/trading-journal --allow-write=docs/trading-journal \
//     scripts/daily_verify.ts --date=YYYY-MM-DD < digest.json
//
// stdin: the full `status` response; only `.verification` is read. stdout: a
// single JSON envelope (see `main` below). Exit 0 (PASS/WARN/SKIPPED_WEEKEND),
// 2 (FAIL), 1 (malformed input -- nothing printed, nothing written).
//
// D9: imports pairHourlyTrades/findUnmatchedEntryTrades from
// render_weekly_journal.ts rather than reimplementing them, per the spec's
// explicit instruction. Those two functions are typed over db.ts's
// HourlyScanRow/TradeRow, so `verification.scans`/`.trades` below use the
// SAME types (via `import type`, fully erased at compile time -- no runtime
// import, so this costs nothing at either permission or dependency-graph
// level) rather than a hand-duplicated shape that could drift out of sync
// with what §4.3 actually puts on the wire ("scans are full HourlyScanRow
// values").
// ---------------------------------------------------------------------------
import { findUnmatchedEntryTrades, pairHourlyTrades } from "./render_weekly_journal.ts";
import type { HourlyScanRow, TradeRow } from "../supabase/functions/_shared/db.ts";

export interface VerifyHourlyCheckRun {
  started_at: string;
  finished_at: string | null;
  outcome: string | null;
  notes: string | null;
}

export interface VerifyKillSwitchRuns {
  count: number;
  outcome_counts: Record<string, number>;
}

export interface VerifyConfig {
  paused: string | null;
  hourly_experiment_start_equity: string | null;
  hourly_experiment_baseline_verified: string | null;
}

export interface VerificationBlock {
  date: string;
  window: { since: string; until: string };
  shorts_enabled: boolean;
  hourly_check_runs: VerifyHourlyCheckRun[];
  kill_switch_runs: VerifyKillSwitchRuns;
  scans: HourlyScanRow[];
  trades: TradeRow[];
  config: VerifyConfig;
}

// ---------------------------------------------------------------------------
// §5.4 date resolution. Pure -- `now` is always an argument, never read here.
// ---------------------------------------------------------------------------

/**
 * The workflow's target-date rule (§5.4), exported so the workflow (or an
 * inline script step within it) can resolve the default date the same way
 * this file tests it: an explicit `--date`/`workflow_dispatch` value wins
 * verbatim; otherwise today in UTC once the UTC hour reaches 12, else the
 * previous UTC day (Actions schedule jitter only ever delays, so a run
 * pushed past midnight still evaluates the day it was scheduled for).
 */
export function resolveTargetDate(now: Date, explicitDate?: string): string {
  if (explicitDate !== undefined) return explicitDate;
  if (now.getUTCHours() >= 12) {
    return now.toISOString().slice(0, 10);
  }
  const prev = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  return prev.toISOString().slice(0, 10);
}

/** A Saturday or Sunday target date (§5.4/D12), by the UTC calendar. */
export function isWeekendYmd(dateYmd: string): boolean {
  const [y, m, d] = dateYmd.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return day === 0 || day === 6;
}

// ---------------------------------------------------------------------------
// Derived constants (§5.2), named with the derivation in a comment, per
// deadman_check.ts's own convention.
// ---------------------------------------------------------------------------

// pg_cron "7 13-21 * * 1-5" UTC (migration 0014_hourly_check_cron_activation)
// -- 9 daily slots, :07 past each hour, 13:07 through 21:07 UTC.
export const HOURLY_SLOTS_PER_WEEKDAY = 9;
// kill-switch's "*/5 13-21 * * 1-5" UTC -- 13:00 through 21:55 UTC inclusive,
// every 5 minutes: (21*60+55 - 13*60) / 5 + 1 = 108.
export const KILL_SWITCH_SLOTS_PER_WEEKDAY = 108;
// #511's per-request Alpaca deadline.
export const LATENCY_WARN_MS = 10_000;
// Migration 0015's documented pg_net budget.
export const LATENCY_FAIL_MS = 120_000;

// The set of hourly-check outcomes that write NO hourly_scans row for the
// run's own candidate bar -- traced against every return path in
// supabase/functions/hourly-check/logic.ts's runHourlyCheck/reconcile()
// (issue #547 SUB_PLAN; the full per-outcome derivation, with line numbers,
// is pinned by the test of the same name in daily_verify.test.ts -- keep the
// two comments in sync on any hourly-check gate-order change).
//
// error:* outcomes are deliberately excluded from this static set: they are
// dynamic (err.name-derived), not enumerable, and the `slots` check already
// FAILs any error:* regardless of how the `scans` check would otherwise
// classify it.
//
// Disclosed residual, NOT folded into this set either way (kept out, exactly
// as it is today): the completed.length === 0 branch (gate 7, hourly-check's
// bars fetch returning zero completed bars) returns via done() before any
// journal call, and surfaces as either "skipped:stale_data" (the dominant,
// journaled case elsewhere) or, rarely, "success:legs_replaced" (when a
// same-run naked-position re-leg had already set the supersede outcome). Both
// strings are dominantly journaled through OTHER gates, so this one narrow
// anomaly can produce a scan-count mismatch (a FAIL on the `scans` check)
// without either outcome being folded into NON_SCANNING_OUTCOMES. See the
// dedicated `zero-completed-bars-residual` fixture.
export const NON_SCANNING_OUTCOMES: ReadonlySet<string> = new Set([
  "skipped:trading_paused",
  "skipped:market_closed",
  "error:naked_position_flattened",
  "success:auto_paused",
  "skipped:duplicate_run",
]);

// ---------------------------------------------------------------------------
// The seven checks (§5.3). Each is a pure function of its own slice of the
// digest, returning the check's severity plus human-readable findings (empty
// findings on PASS). A day's overall verdict is the highest severity across
// all seven (mergeStatus below).
// ---------------------------------------------------------------------------

export type CheckStatus = "PASS" | "WARN" | "FAIL";

export interface CheckOutcome {
  status: CheckStatus;
  findings: string[];
}

const SEVERITY: Record<CheckStatus, number> = { PASS: 0, WARN: 1, FAIL: 2 };

/** The highest-severity status among `statuses` (FAIL > WARN > PASS). */
export function mergeStatus(statuses: CheckStatus[]): CheckStatus {
  let worst: CheckStatus = "PASS";
  for (const s of statuses) {
    if (SEVERITY[s] > SEVERITY[worst]) worst = s;
  }
  return worst;
}

/** Check 1 (replaces manual check 1): every daily slot ran to completion, cleanly. */
export function checkSlots(runs: VerifyHourlyCheckRun[]): CheckOutcome {
  const findings: string[] = [];
  if (runs.length !== HOURLY_SLOTS_PER_WEEKDAY) {
    findings.push(
      `slots: expected ${HOURLY_SLOTS_PER_WEEKDAY} hourly-check runs, found ${runs.length}`,
    );
  }
  for (const r of runs) {
    if (r.finished_at === null) {
      findings.push(`slots: run started_at=${r.started_at} never finished (finished_at is null)`);
    }
    if (r.outcome === null) {
      findings.push(`slots: run started_at=${r.started_at} has no outcome`);
    } else if (r.outcome.startsWith("error:")) {
      findings.push(`slots: run started_at=${r.started_at} outcome=${r.outcome}`);
    }
  }
  return { status: findings.length > 0 ? "FAIL" : "PASS", findings };
}

/** Check 5 (replaces manual check 5): per-run finished_at - started_at latency. */
export function checkLatency(runs: VerifyHourlyCheckRun[]): CheckOutcome {
  const findings: string[] = [];
  const statuses: CheckStatus[] = [];
  for (const r of runs) {
    // A never-finished run is checkSlots's finding, not a latency measurement.
    if (r.finished_at === null) continue;
    const ms = Date.parse(r.finished_at) - Date.parse(r.started_at);
    if (ms > LATENCY_FAIL_MS) {
      statuses.push("FAIL");
      findings.push(
        `latency: run started_at=${r.started_at} took ${ms}ms (over the ${LATENCY_FAIL_MS}ms FAIL threshold)`,
      );
    } else if (ms > LATENCY_WARN_MS) {
      statuses.push("WARN");
      findings.push(
        `latency: run started_at=${r.started_at} took ${ms}ms (over the ${LATENCY_WARN_MS}ms WARN threshold)`,
      );
    }
  }
  return { status: mergeStatus(statuses), findings };
}

export interface ScansCheckInput {
  shorts_enabled: boolean;
  hourly_check_runs: VerifyHourlyCheckRun[];
  scans: HourlyScanRow[];
}

/** Check 2 (replaces manual check 2): scan-row count vs. scanning-run count, plus per-scan sanity. */
export function checkScans(v: ScansCheckInput): CheckOutcome {
  const findings: string[] = [];
  const statuses: CheckStatus[] = [];

  const expectedScans = v.hourly_check_runs.filter(
    (r) => r.outcome === null || !NON_SCANNING_OUTCOMES.has(r.outcome),
  ).length;
  if (v.scans.length !== expectedScans) {
    statuses.push("FAIL");
    findings.push(
      `scans: expected ${expectedScans} hourly_scans row(s) (runs outside NON_SCANNING_OUTCOMES), found ${v.scans.length}`,
    );
  }

  for (const s of v.scans) {
    if (s.decision === "SHORT" && !v.shorts_enabled) {
      statuses.push("FAIL");
      findings.push(`scans: SHORT decision at bar_ts=${s.bar_ts} while shorts_enabled=false`);
    }
    if (s.decision === "LONG" && s.entry_order_id === null) {
      statuses.push("WARN");
      findings.push(
        `scans: LONG decision at bar_ts=${s.bar_ts} has a null entry_order_id (a later scan's reconcile may still adopt it)`,
      );
    }
  }

  return { status: mergeStatus(statuses), findings };
}

function isWholeCents(x: number): boolean {
  return Math.abs(Math.round(x * 100) - x * 100) <= 1e-6;
}

/** Check 3 (replaces manual check 3): stop/target prices quantized to whole cents. */
export function checkGeometry(scans: HourlyScanRow[]): CheckOutcome {
  const findings: string[] = [];
  for (const s of scans) {
    if (s.stop_price !== null && !isWholeCents(s.stop_price)) {
      findings.push(`geometry: bar_ts=${s.bar_ts} stop_price=${s.stop_price} is not whole cents`);
    }
    if (s.target_price !== null && !isWholeCents(s.target_price)) {
      findings.push(
        `geometry: bar_ts=${s.bar_ts} target_price=${s.target_price} is not whole cents`,
      );
    }
  }
  return { status: findings.length > 0 ? "FAIL" : "PASS", findings };
}

/** Check 4 (replaces manual check 4): every hourly% entry fill has a matching scan. */
export function checkJournal(trades: TradeRow[], scans: HourlyScanRow[]): CheckOutcome {
  const hourlyTrades = trades.filter((t) => t.reason.startsWith("hourly_"));
  const unmatched = findUnmatchedEntryTrades(hourlyTrades, scans);
  if (unmatched.length === 0) return { status: "PASS", findings: [] };
  return {
    status: "FAIL",
    findings: unmatched.map(
      (t) =>
        `journal: unmatched entry fill broker_order_id=${t.broker_order_id} (${t.symbol} ${t.reason} @ ${t.fill_time})`,
    ),
  };
}

export interface PreviousLedgerRowForState {
  /** Mirrors Metrics.floor_baseline_raw's own type -- the previous day can itself be day-zero. */
  floor_baseline_raw: string | null;
}

/** Check 6 (replaces manual check 6): pause flag + baseline byte-identity, both directions. */
export function checkState(
  config: VerifyConfig,
  previousRow: PreviousLedgerRowForState | null,
): CheckOutcome {
  const findings: string[] = [];
  const statuses: CheckStatus[] = [];

  if (config.paused !== "false") {
    statuses.push("FAIL");
    findings.push(`state: bot_config.paused=${JSON.stringify(config.paused)}, expected "false"`);
  }

  if (config.hourly_experiment_start_equity === null) {
    statuses.push("WARN");
    findings.push("state: hourly_experiment_start_equity is unset (day-zero)");
  } else {
    if (config.hourly_experiment_baseline_verified !== config.hourly_experiment_start_equity) {
      statuses.push("FAIL");
      findings.push(
        `state: hourly_experiment_baseline_verified=${
          JSON.stringify(config.hourly_experiment_baseline_verified)
        } is not byte-identical to hourly_experiment_start_equity=${
          JSON.stringify(config.hourly_experiment_start_equity)
        }`,
      );
    }
    // Only compares when the previous day itself had a baseline recorded --
    // a previous day that was ITSELF day-zero (unset) has nothing valid to
    // compare against, and the unset->set transition is the ordinary
    // first-baseline case, not a "baseline moved" anomaly.
    if (
      previousRow !== null &&
      previousRow.floor_baseline_raw !== null &&
      previousRow.floor_baseline_raw !== config.hourly_experiment_start_equity
    ) {
      statuses.push("FAIL");
      findings.push(
        `state: baseline moved -- was ${JSON.stringify(previousRow.floor_baseline_raw)}, now ${
          JSON.stringify(config.hourly_experiment_start_equity)
        }`,
      );
    }
  }

  return { status: mergeStatus(statuses), findings };
}

/** Check 7 (replaces manual check 7): kill-switch slot count, outcome shape, and position contradiction. */
export function checkKillSwitch(
  killSwitchRuns: VerifyKillSwitchRuns,
  scans: HourlyScanRow[],
): CheckOutcome {
  const findings: string[] = [];
  const statuses: CheckStatus[] = [];

  if (killSwitchRuns.count !== KILL_SWITCH_SLOTS_PER_WEEKDAY) {
    statuses.push("FAIL");
    findings.push(
      `kill_switch: expected ${KILL_SWITCH_SLOTS_PER_WEEKDAY} runs, found ${killSwitchRuns.count}`,
    );
  }

  const outcomeEntries = Object.entries(killSwitchRuns.outcome_counts);
  for (const [outcome, count] of outcomeEntries) {
    if (!outcome.startsWith("success:") && !outcome.startsWith("skipped:")) {
      statuses.push("FAIL");
      findings.push(
        `kill_switch: outcome=${outcome} (count=${count}) is neither success:* nor skipped:*`,
      );
    }
  }

  const isUniformNoPosition = outcomeEntries.length === 1 &&
    outcomeEntries[0][0] === "success:no_position" &&
    outcomeEntries[0][1] === killSwitchRuns.count;
  const hasLongScan = scans.some((s) => s.decision === "LONG");
  if (isUniformNoPosition && hasLongScan) {
    statuses.push("FAIL");
    findings.push(
      "kill_switch: every run reported success:no_position, but a LONG scan exists for this day (contradiction)",
    );
  }

  return { status: mergeStatus(statuses), findings };
}

// ---------------------------------------------------------------------------
// Metrics (§6.1) -- a straight function of the verification block, key order
// fixed to match the ledger row's own §6.1 example (D6: no clock-derived
// field anywhere here).
// ---------------------------------------------------------------------------

// Duplicated from hourly-check/logic.ts's own EQUITY_FLOOR_PCT (and
// render_weekly_journal.ts's copy of the same constant) rather than imported
// -- hourly-check/logic.ts is an Edge Function module outside this script's
// dependency surface, per D9's own precedent. Kept in sync manually; a
// mismatch here would only affect this script's rendered numbers, never the
// live floor enforcement.
const EQUITY_FLOOR_PCT = 0.15;

const UNFINISHED_OUTCOME_LABEL = "(unfinished)";

function median(sorted: number[]): number {
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export interface LatencyMs {
  max: number | null;
  median: number | null;
}

export interface Metrics {
  hourly_runs: number;
  hourly_outcome_counts: Record<string, number>;
  latency_ms: LatencyMs;
  scan_rows: number;
  evaluated_bars: number;
  decision_counts: { LONG: number; SHORT: number; SKIP: number };
  skip_reason_counts: Record<string, number>;
  detector_fire_counts: Record<string, number>;
  entries: number;
  fills: number;
  closed_trades: number;
  r_multiples: number[];
  equity_usd: number | null;
  floor_baseline_raw: string | null;
  floor_price_usd: number | null;
  headroom_pct: number | null;
  kill_switch_runs: number;
  kill_switch_outcome_counts: Record<string, number>;
}

/**
 * Duplicated from status/logic.ts's computeEquityHeadroomPct (D9, per batch
 * #534's decision 5: "the published formula" -- reimplemented here rather
 * than imported, for the same reason EQUITY_FLOOR_PCT above is duplicated
 * rather than imported: status/logic.ts is an Edge Function module outside
 * this script's dependency surface). `(equity - floorPrice) / equity`, as a
 * percentage. Guards the same non-finite/<=0 domain, returning null rather
 * than Infinity/NaN.
 */
function computeEquityHeadroomPct(equityUsd: number, floorPriceUsd: number): number | null {
  if (!Number.isFinite(equityUsd) || !Number.isFinite(floorPriceUsd) || equityUsd <= 0) {
    return null;
  }
  return ((equityUsd - floorPriceUsd) / equityUsd) * 100;
}

function computeMetrics(v: VerificationBlock): Metrics {
  const hourly_outcome_counts: Record<string, number> = {};
  const latencies: number[] = [];
  for (const r of v.hourly_check_runs) {
    const key = r.outcome ?? UNFINISHED_OUTCOME_LABEL;
    hourly_outcome_counts[key] = (hourly_outcome_counts[key] ?? 0) + 1;
    if (r.finished_at !== null) {
      latencies.push(Date.parse(r.finished_at) - Date.parse(r.started_at));
    }
  }
  latencies.sort((a, b) => a - b);
  const latency_ms: LatencyMs = {
    max: latencies.length > 0 ? latencies[latencies.length - 1] : null,
    median: latencies.length > 0 ? median(latencies) : null,
  };

  // gate 7's two pre-decision skip reasons (partial_bar, stale_data) are the
  // only ones where decideHourly never ran and detectors_fired is always
  // empty by construction -- "evaluated" means the detector engine actually
  // saw the bar, matching #535's original "candidate bars" count.
  const evaluated_bars = v.scans.filter(
    (s) => s.skip_reason !== "partial_bar" && s.skip_reason !== "stale_data",
  ).length;

  const decision_counts = { LONG: 0, SHORT: 0, SKIP: 0 };
  const skip_reason_counts: Record<string, number> = {};
  const detector_fire_counts: Record<string, number> = {};
  for (const s of v.scans) {
    decision_counts[s.decision]++;
    if (s.decision === "SKIP") {
      const reason = s.skip_reason ?? "unspecified";
      skip_reason_counts[reason] = (skip_reason_counts[reason] ?? 0) + 1;
    }
    for (const d of s.detectors_fired) {
      detector_fire_counts[d] = (detector_fire_counts[d] ?? 0) + 1;
    }
  }

  // The `hourly%` filter (§4.3: "trades are unfiltered by reason ... the
  // evaluator applies the hourly% filter, so a future reason string needs no
  // redeploy") -- a plain prefix check is this practical equivalent of a SQL
  // LIKE 'hourly%'.
  const hourlyTrades = v.trades.filter((t) => t.reason.startsWith("hourly_"));
  const entries = hourlyTrades.filter(
    (t) => t.reason === "hourly_long_entry" || t.reason === "hourly_short_entry",
  ).length;
  const fills = hourlyTrades.length;

  // D9: pairHourlyTrades/findUnmatchedEntryTrades, imported rather than
  // reimplemented. Pairing is scoped to THIS day's own trades/scans only
  // (unlike the weekly journal's full-history pairing) -- an exit whose
  // entry landed on a prior day is reported as an orphan exit here, not a
  // closed trade, which is the right within-day answer for a daily sanity
  // check that has no access to prior days' trades.
  const pairing = pairHourlyTrades(hourlyTrades, v.scans);
  const closed_trades = pairing.closedTrades.length;
  const r_multiples = pairing.closedTrades
    .map((t) => t.rMultiple)
    .filter((r): r is number => r !== null);

  const sortedScans = [...v.scans].sort((a, b) => a.bar_ts.localeCompare(b.bar_ts));
  const equity_usd = sortedScans.length > 0 ? sortedScans[sortedScans.length - 1].equity_usd : null;

  const floor_baseline_raw = v.config.hourly_experiment_start_equity;
  let floor_price_usd: number | null = null;
  let headroom_pct: number | null = null;
  if (floor_baseline_raw !== null) {
    const baseline = Number(floor_baseline_raw);
    if (Number.isFinite(baseline)) {
      floor_price_usd = baseline * (1 - EQUITY_FLOOR_PCT);
      if (equity_usd !== null) {
        headroom_pct = computeEquityHeadroomPct(equity_usd, floor_price_usd);
      }
    }
  }

  return {
    hourly_runs: v.hourly_check_runs.length,
    hourly_outcome_counts,
    latency_ms,
    scan_rows: v.scans.length,
    evaluated_bars,
    decision_counts,
    skip_reason_counts,
    detector_fire_counts,
    entries,
    fills,
    closed_trades,
    r_multiples,
    equity_usd,
    floor_baseline_raw,
    floor_price_usd,
    headroom_pct,
    kill_switch_runs: v.kill_switch_runs.count,
    kill_switch_outcome_counts: v.kill_switch_runs.outcome_counts,
  };
}

// ---------------------------------------------------------------------------
// evaluateVerification -- composes the seven checks into a verdict, plus the
// metrics block. Cross-day state (the previous ledger row) is an argument,
// never read from disk here (§5.3: "Cross-day state ... is passed into the
// pure evaluator as an argument. It is never read from disk by the
// evaluation core.").
// ---------------------------------------------------------------------------

export interface EvaluationChecks {
  slots: CheckStatus;
  latency: CheckStatus;
  scans: CheckStatus;
  geometry: CheckStatus;
  journal: CheckStatus;
  state: CheckStatus;
  kill_switch: CheckStatus;
}

export interface EvaluationResult {
  verdict: CheckStatus;
  checks: EvaluationChecks;
  metrics: Metrics;
  findings: string[];
}

export function evaluateVerification(
  v: VerificationBlock,
  previousRow: PreviousLedgerRowForState | null,
): EvaluationResult {
  const slots = checkSlots(v.hourly_check_runs);
  const latency = checkLatency(v.hourly_check_runs);
  const scans = checkScans({
    shorts_enabled: v.shorts_enabled,
    hourly_check_runs: v.hourly_check_runs,
    scans: v.scans,
  });
  const geometry = checkGeometry(v.scans);
  const journal = checkJournal(v.trades, v.scans);
  const state = checkState(v.config, previousRow);
  const killSwitch = checkKillSwitch(v.kill_switch_runs, v.scans);

  const checks: EvaluationChecks = {
    slots: slots.status,
    latency: latency.status,
    scans: scans.status,
    geometry: geometry.status,
    journal: journal.status,
    state: state.status,
    kill_switch: killSwitch.status,
  };

  const verdict = mergeStatus(Object.values(checks));
  const findings = [
    ...slots.findings,
    ...latency.findings,
    ...scans.findings,
    ...geometry.findings,
    ...journal.findings,
    ...state.findings,
    ...killSwitch.findings,
  ];

  return { verdict, checks, metrics: computeMetrics(v), findings };
}

// ---------------------------------------------------------------------------
// Ledger row (§6.1) + JSONL upsert + previous-row selection. Pure text
// transforms -- D6's byte-identity guarantee is a property of these
// functions, not of the workflow that calls them.
// ---------------------------------------------------------------------------

export interface LedgerRow {
  date: string;
  verdict: CheckStatus;
  checks: EvaluationChecks;
  metrics: Metrics;
  findings: string[];
}

export function buildLedgerRow(date: string, evaluation: EvaluationResult): LedgerRow {
  return {
    date,
    verdict: evaluation.verdict,
    checks: evaluation.checks,
    metrics: evaluation.metrics,
    findings: evaluation.findings,
  };
}

function parseLedgerJsonl(text: string): LedgerRow[] {
  return text
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as LedgerRow);
}

/**
 * Upserts `newRow` into the JSONL ledger text: replaces any existing line for
 * the same date, inserts otherwise, and always re-serializes every row in
 * ascending date order (D6: makes backfill order-independent and a repeat
 * run byte-identical). Pure text in, text out -- main() owns the disk read
 * and write around this call.
 */
export function upsertLedgerJsonl(existingText: string, newRow: LedgerRow): string {
  const rows = parseLedgerJsonl(existingText);
  const byDate = new Map<string, LedgerRow>();
  for (const row of rows) byDate.set(row.date, row);
  byDate.set(newRow.date, newRow);
  const sorted = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  return sorted.map((row) => JSON.stringify(row)).join("\n") + "\n";
}

/** The newest ledger row with a date strictly before `targetDate`, or null (day zero). */
export function selectPreviousRow(rows: LedgerRow[], targetDate: string): LedgerRow | null {
  let best: LedgerRow | null = null;
  for (const row of rows) {
    if (row.date < targetDate && (best === null || row.date > best.date)) {
      best = row;
    }
  }
  return best;
}
