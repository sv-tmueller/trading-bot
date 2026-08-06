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
// ---------------------------------------------------------------------------
// Local structural types for the digest's `verification` block (§4.3). A
// minimal local type, not an import of supabase/functions/status/logic.ts --
// same rationale as deadman_check.ts's own DeadmanLastRuns: this script stays
// coupled to the JSON shape only, not to the Edge Function module (which
// pulls in Alpaca/Supabase client types this script has no business
// depending on). The shapes below are structurally compatible with
// _shared/db.ts's HourlyScanRow/TradeRow, which is what lets them flow
// straight into the imported pairHourlyTrades/findUnmatchedEntryTrades (D9)
// without a second, parallel type.
// ---------------------------------------------------------------------------

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

export interface VerifyScanRow {
  symbol: string;
  bar_ts: string;
  decision: "LONG" | "SHORT" | "SKIP";
  skip_reason: string | null;
  detectors_fired: string[];
  entry_ref_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  risk_per_share: number | null;
  equity_usd: number;
  qty: number;
  entry_order_id: string | null;
}

export interface VerifyTradeRow {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  fill_price: number;
  fill_time: string;
  reason: string;
  broker_order_id: string;
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
  scans: VerifyScanRow[];
  trades: VerifyTradeRow[];
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
