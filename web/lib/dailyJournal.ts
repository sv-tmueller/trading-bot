import "server-only";
import fs from "node:fs";
import path from "node:path";

// Sole owner of filesystem access for the daily-verification artifacts (#548,
// design spec §6.1/§6.2/§8). Every read here happens at Next.js build time
// (generateStaticParams / a plain static-page render), never at request time
// for the two /daily routes; see web/app/daily/**. The dashboard tile
// (web/app/page.tsx) is the one deliberate exception: it calls
// getLatestVerifiedDay() from a force-dynamic route at request time, which
// the design spec's lead decision accepts (identical Vercel
// outside-root-directory exposure either way).

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export type Verdict = "PASS" | "WARN" | "FAIL";

export interface LedgerMetrics {
  hourly_runs: number;
  hourly_outcome_counts: Record<string, number>;
  latency_ms: { max: number; median: number };
  scan_rows: number;
  evaluated_bars: number;
  decision_counts: { LONG: number; SHORT: number; SKIP: number };
  skip_reason_counts: Record<string, number>;
  detector_fire_counts: Record<string, number>;
  entries: number;
  fills: number;
  closed_trades: number;
  r_multiples: number[];
  equity_usd: number;
  floor_baseline_raw: string | null;
  floor_price_usd: number | null;
  headroom_pct: number | null;
  kill_switch_runs: number;
  kill_switch_outcome_counts: Record<string, number>;
}

export interface LedgerRow {
  date: string;
  environment: string;
  verdict: Verdict;
  checks: Record<string, Verdict>;
  metrics: LedgerMetrics;
  findings: string[];
}

function isVerdict(value: unknown): value is Verdict {
  return value === "PASS" || value === "WARN" || value === "FAIL";
}

// Tolerant per-line validation: only the envelope (date, verdict, checks,
// metrics, findings) is checked. A line that fails this check is skipped with
// a console.warn rather than failing the whole build; #547 (the producer)
// may still be stabilizing its output.
//
// #555: the `environment` field is optional in the tolerant reader -- rows
// without it (pre-migration history) are treated as "dev", matching the
// one-time migration that added `"environment": "dev"` to all existing rows.
// The dashboard currently shows dev-only history; when a prod leg is
// activated, the reader can be extended to filter by a query param.
function asLedgerRow(value: unknown): LedgerRow | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.date !== "string" || !DATE_RE.test(v.date)) return null;
  if (!isVerdict(v.verdict)) return null;
  if (typeof v.checks !== "object" || v.checks === null) return null;
  if (typeof v.metrics !== "object" || v.metrics === null) return null;
  if (!Array.isArray(v.findings)) return null;
  return {
    date: v.date,
    environment: typeof v.environment === "string" ? v.environment : "dev",
    verdict: v.verdict,
    checks: v.checks as Record<string, Verdict>,
    metrics: v.metrics as LedgerMetrics,
    findings: v.findings as string[],
  };
}

function isEnoent(err: unknown): boolean {
  return (err as NodeJS.ErrnoException | null)?.code === "ENOENT";
}

// Prefers web/content/** (populated by the documented, currently-unwired
// scripts/copy-daily-artifacts.mjs prebuild fallback) and falls through to
// the repo's docs/trading-journal/** on ENOENT, the layout a full CI
// checkout and a correctly configured Vercel "include source files outside
// the Root Directory" setting both have. Any non-ENOENT error propagates and
// fails the build loudly, matching this repo's no-silent-fallback
// convention: only "artifact legitimately absent" is swallowed.
function resolveExisting(preferred: string, fallback: string): string {
  try {
    fs.accessSync(preferred);
    return preferred;
  } catch (err) {
    if (!isEnoent(err)) throw err;
    return fallback;
  }
}

function ledgerPath(): string {
  return resolveExisting(
    path.join(process.cwd(), "content", "daily-verification.jsonl"),
    path.join(process.cwd(), "..", "docs", "trading-journal", "daily-verification.jsonl"),
  );
}

// #555: digests are namespaced per environment under daily/{env}/. The
// dashboard currently serves the dev environment only (the only one with
// committed history). When a prod leg is activated, this function can be
// parameterized by environment.
const DASHBOARD_ENV = "dev";

function dailyDigestDir(): string {
  return resolveExisting(
    path.join(process.cwd(), "content", "daily", DASHBOARD_ENV),
    path.join(process.cwd(), "..", "docs", "trading-journal", "daily", DASHBOARD_ENV),
  );
}

// Reads the full ledger (docs/trading-journal/daily-verification.jsonl),
// ascending by date per D6. #555: filters to the dashboard's environment
// (dev) -- the ledger is a single file shared across environments, so the
// reader partitions by the `environment` field. Returns [] when the file
// does not exist yet (#547 has not landed, or no day has been verified yet)
// rather than throwing: the empty state is a first-class case, not a fallback.
export function readLedger(): LedgerRow[] {
  let raw: string;
  try {
    raw = fs.readFileSync(ledgerPath(), "utf-8");
  } catch (err) {
    if (isEnoent(err)) return [];
    throw err;
  }
  const rows: LedgerRow[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      console.warn(`dailyJournal: skipping malformed ledger line: ${trimmed.slice(0, 80)}`);
      continue;
    }
    const row = asLedgerRow(parsed);
    if (row === null) {
      console.warn(`dailyJournal: skipping ledger line with unexpected shape: ${trimmed.slice(0, 80)}`);
      continue;
    }
    if (row.environment !== DASHBOARD_ENV) continue;
    rows.push(row);
  }
  return rows;
}

// The dashboard tile's data source (called at request time from the
// force-dynamic `/` route). The ledger is kept in ascending date order, so
// the latest verified day is the last row.
export function getLatestVerifiedDay(): LedgerRow | null {
  const rows = readLedger();
  return rows.length === 0 ? null : rows[rows.length - 1];
}

// Dates with a rendered markdown digest, sorted ascending. Backs
// generateStaticParams for /daily/[date]. Returns [] when the directory does
// not exist yet, which is what makes the empty state (zero generated pages,
// every /daily/* URL 404ing) the correct behavior rather than an error.
export function listDigestDates(): string[] {
  let entries: string[];
  try {
    entries = fs.readdirSync(dailyDigestDir());
  } catch (err) {
    if (isEnoent(err)) return [];
    throw err;
  }
  return entries
    .filter((name) => name.endsWith(".md"))
    .map((name) => name.slice(0, -3))
    .filter((date) => DATE_RE.test(date))
    .sort();
}

// Raw markdown for one verified day, or null if the date is malformed or the
// file does not exist. Validating `date` against DATE_RE before building the
// path is cheap traversal hygiene even though in practice `date` only ever
// comes from generateStaticParams's own listDigestDates() output.
export function readDigestMarkdown(date: string): string | null {
  if (!DATE_RE.test(date)) return null;
  try {
    return fs.readFileSync(path.join(dailyDigestDir(), `${date}.md`), "utf-8");
  } catch (err) {
    if (isEnoent(err)) return null;
    throw err;
  }
}
