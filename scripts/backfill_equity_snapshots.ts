// One-time operator-run backfill of `equity_snapshots` from Alpaca's
// portfolio-history endpoint (#389, batch #388 Package A). Fetch lives here
// (not in _shared/alpaca.ts) so this stays zero new production surface (D1 —
// see the #389 SUB_PLAN on issue #389 for the full design). Imports only
// getAlpacaConfig()/getServiceClient() from _shared/ for identical env names
// and auth headers. The GET is read-only (parallel to the unguarded
// getAccountValue) — no checkGuard/CLAUDE_AGENT_NO_BROKER involvement, and no
// mutating broker helper is added anywhere.
//
// Insert-if-absent is enforced two ways (D2): a script-local read of existing
// dates in-window, plus (mechanically) `.upsert(rows, { onConflict: "date",
// ignoreDuplicates: true })` — PostgREST's `Prefer: resolution=ignore-
// duplicates`, i.e. `INSERT ... ON CONFLICT DO NOTHING`. This can never
// modify an existing row (daily-check's rows are canonical) and closes the
// TOCTOU window between the read and the write.
import { requireNumber } from "../supabase/functions/_shared/num.ts";
// ---------------------------------------------------------------------------
// T1 — arg parsing
// ---------------------------------------------------------------------------

export class ArgError extends Error {
  override name = "ArgError";
}
// Distinguished from a plain ArgError (e.g. a malformed --since) so main()
// can show full usage for a genuinely unknown flag while keeping a bad
// --since value to a one-line message (D5/T1).
export class UnknownArgError extends ArgError {
  override name = "UnknownArgError";
}

export interface ParsedArgs {
  help: boolean;
  since: string | undefined;
  execute: boolean;
}

const YMD_RE = /^\d{4}-\d{2}-\d{2}$/;

// Round-trip validation, not just regex: `new Date("2026-02-30")` silently
// rolls over to March 2 in JS, so a naive regex-only check would accept an
// invalid calendar date.
function isValidYmd(val: string): boolean {
  if (!YMD_RE.test(val)) return false;
  const d = new Date(`${val}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === val;
}

export function parseArgs(argv: string[]): ParsedArgs {
  let since: string | undefined;
  let execute = false;
  let help = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case "-h":
      case "--help":
        help = true;
        break;
      case "--execute":
        execute = true;
        break;
      case "--since": {
        const val = argv[++i];
        if (val === undefined || !isValidYmd(val)) {
          throw new ArgError(
            `--since must be a valid YYYY-MM-DD date, got ${JSON.stringify(val ?? "")}`,
          );
        }
        since = val;
        break;
      }
      default:
        throw new UnknownArgError(`unknown argument: ${arg}`);
    }
  }

  return { help, since, execute };
}

// ---------------------------------------------------------------------------
// T2 — pure mapping/filtering from Alpaca's portfolio-history response to
// candidate equity_snapshots rows.
// ---------------------------------------------------------------------------

export interface PortfolioHistory {
  timestamp: number[];
  equity: unknown[];
}

export interface MappedHistory {
  rows: { date: string; equity_usd: number }[];
  // Dropped for being non-finite or <= 0 (Alpaca pads pre-funding days with
  // zeros; a 0 anchor would poison since_inception_pct). Counted separately
  // from the "today (ET) and later" exclusion, which is not itself a data
  // problem — it's just out of this script's scope (daily-check owns today).
  zeroEquityDropped: number;
  // Raw count of entries Alpaca returned, pre-filter — one of the four
  // summary counts (D5).
  alpacaDays: number;
}

// Alpaca's portfolio-history `timestamp` values are Unix epoch seconds (not
// milliseconds) for every documented timeframe, including 1D.
const etDateFormatter = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

export function etDateOf(d: Date): string {
  return etDateFormatter.format(d);
}

export function mapHistoryToDailyRows(
  history: PortfolioHistory,
  todayEt: string,
): MappedHistory {
  const { timestamp, equity } = history;
  if (timestamp.length !== equity.length) {
    throw new Error(
      `portfolio-history: timestamp/equity length mismatch (${timestamp.length} vs ${equity.length})`,
    );
  }

  const rows: { date: string; equity_usd: number }[] = [];
  let zeroEquityDropped = 0;

  for (let i = 0; i < timestamp.length; i++) {
    const date = etDateOf(new Date(timestamp[i] * 1000));
    // Today (ET) and later belong exclusively to daily-check — its value can
    // be an in-progress intraday number (D3).
    if (date >= todayEt) continue;

    let value: number;
    try {
      value = requireNumber(equity[i], `equity[${i}]`);
    } catch {
      zeroEquityDropped++;
      continue;
    }
    if (value <= 0) {
      zeroEquityDropped++;
      continue;
    }
    rows.push({ date, equity_usd: value });
  }

  return { rows, zeroEquityDropped, alpacaDays: timestamp.length };
}

// ---------------------------------------------------------------------------
// T3 — runBackfill orchestration (D6 deps-injection, same style as the Edge
// Functions' logic.ts modules).
// ---------------------------------------------------------------------------

// Thrown by the getExistingSnapshotDates adapter when PostgREST reports
// 42P01 (relation does not exist) — i.e. migration 0009 hasn't been applied
// yet. runBackfill catches this and rethrows a friendly, single-line message
// (no stack trace reaches the operator).
export class EquitySnapshotsTableMissingError extends Error {
  override name = "EquitySnapshotsTableMissingError";
}

// Thrown when no --since is given and audit_log has no rows to infer the
// bot's go-live date from.
export class NoAuditHistoryError extends Error {
  override name = "NoAuditHistoryError";
}

export interface BackfillDeps {
  now: () => Date;
  fetchPortfolioHistory: (startYmd: string) => Promise<PortfolioHistory>;
  db: {
    getEarliestAuditStartedAt: () => Promise<string | null>;
    getExistingSnapshotDates: (since: string) => Promise<string[]>;
    insertSnapshotsIgnoreDuplicates: (
      rows: { date: string; equity_usd: number }[],
    ) => Promise<string[]>;
  };
  log: (line: string) => void;
}

export interface BackfillOpts {
  since?: string;
  execute: boolean;
}

export interface BackfillSummary {
  mode: "dry-run" | "execute";
  since: string;
  until: string;
  alpacaDays: number;
  zeroEquityDropped: number;
  alreadyPresent: number;
  // Missing dates found at read time (the backfill "plan"). In dry-run mode
  // this is what *would* be written; in execute mode it's what was attempted.
  candidateRows: { date: string; equity_usd: number }[];
  // Actually written this run. Always [] in dry-run mode. In execute mode,
  // shorter than candidateRows only if another process raced in a write
  // between the read and this run's insert (D2 — safely skipped, never an
  // error).
  insertedRows: { date: string; equity_usd: number }[];
}

async function resolveSince(deps: BackfillDeps, since: string | undefined): Promise<string> {
  if (since !== undefined) return since;
  const earliest = await deps.db.getEarliestAuditStartedAt();
  if (earliest === null) {
    throw new NoAuditHistoryError(
      "audit_log is empty, so the bot's go-live date can't be inferred — pass --since YYYY-MM-DD explicitly.",
    );
  }
  // Same UTC-ymd convention daily-check uses for `regime_state.date` (D3).
  return earliest.slice(0, 10);
}

// Cap on the per-date lines printed in the summary so a multi-month backfill
// doesn't dump hundreds of lines to the terminal.
const SUMMARY_ROW_LIMIT = 20;

function formatRows(rows: { date: string; equity_usd: number }[]): string[] {
  const shown = rows.slice(0, SUMMARY_ROW_LIMIT).map((r) => `  ${r.date}: ${r.equity_usd}`);
  if (rows.length > SUMMARY_ROW_LIMIT) {
    shown.push(`  ... and ${rows.length - SUMMARY_ROW_LIMIT} more`);
  }
  return shown;
}

function logSummary(log: (line: string) => void, summary: BackfillSummary): void {
  log(`mode: ${summary.mode}`);
  log(`window: ${summary.since} .. ${summary.until} (exclusive of ${summary.until})`);
  log(`alpaca days fetched: ${summary.alpacaDays}`);
  log(`zero/invalid equity dropped: ${summary.zeroEquityDropped}`);
  log(`already present: ${summary.alreadyPresent}`);
  if (summary.mode === "dry-run") {
    log(`to insert: ${summary.candidateRows.length}`);
    for (const line of formatRows(summary.candidateRows)) log(line);
    if (summary.candidateRows.length > 0) {
      log("re-run with --execute to write");
    }
  } else {
    log(`inserted: ${summary.insertedRows.length}`);
    for (const line of formatRows(summary.insertedRows)) log(line);
    const racedAway = summary.candidateRows.length - summary.insertedRows.length;
    if (racedAway > 0) {
      log(
        `note: ${racedAway} candidate date(s) were written by another process between read ` +
          `and write — safely skipped, not an error`,
      );
    }
  }
}

export async function runBackfill(
  deps: BackfillDeps,
  opts: BackfillOpts,
): Promise<BackfillSummary> {
  const since = await resolveSince(deps, opts.since);
  const todayEt = etDateOf(deps.now());

  let existing: string[];
  try {
    existing = await deps.db.getExistingSnapshotDates(since);
  } catch (e) {
    if (e instanceof EquitySnapshotsTableMissingError) {
      throw new Error(
        "equity_snapshots table not found — apply migration 0009 (supabase db push) first.",
      );
    }
    throw e;
  }
  const existingSet = new Set(existing);

  const history = await deps.fetchPortfolioHistory(since);
  const mapped = mapHistoryToDailyRows(history, todayEt);

  const candidateRows = mapped.rows.filter((r) => !existingSet.has(r.date));
  const alreadyPresent = mapped.rows.length - candidateRows.length;

  let insertedRows: { date: string; equity_usd: number }[] = [];
  if (opts.execute && candidateRows.length > 0) {
    const insertedDates = new Set(await deps.db.insertSnapshotsIgnoreDuplicates(candidateRows));
    insertedRows = candidateRows.filter((r) => insertedDates.has(r.date));
  }

  const summary: BackfillSummary = {
    mode: opts.execute ? "execute" : "dry-run",
    since,
    until: todayEt,
    alpacaDays: mapped.alpacaDays,
    zeroEquityDropped: mapped.zeroEquityDropped,
    alreadyPresent,
    candidateRows,
    insertedRows,
  };

  logSummary(deps.log, summary);
  return summary;
}
