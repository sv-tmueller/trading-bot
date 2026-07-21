// Pure aggregation for the read-only status digest (#354 T4). No decision
// logic, no writes: StatusDeps exposes only read methods (getClock,
// getAccountValue, getPosition off Alpaca; four SELECT-only db.ts helpers),
// so there is nothing here that could reach a mutating broker call or write
// to the DB even by mistake — that is enforced at the type level, not just
// by convention. In particular, unlike runPanic, this never opens/closes an
// audit_log row: status is deliberately invisible to that table so it stays
// a clean record of trading actions.
import type { StrategyConfig } from "../_shared/config.ts";
import type { AuditLogRow, EquitySnapshotRow, RegimeStateRow, TradeRow } from "../_shared/db.ts";

const DAY_MS = 24 * 60 * 60 * 1000;

export interface StatusDeps {
  config: StrategyConfig;
  now: () => Date;
  alpaca: {
    getClock: () => Promise<{ isOpen: boolean }>;
    getAccountValue: () => Promise<number>;
    getPosition: (symbol: string) => Promise<number>;
  };
  db: {
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
    getAuditLogSince: (sinceIso: string, untilIso: string) => Promise<AuditLogRow[]>;
    getLastTrade: () => Promise<TradeRow | null>;
    getConfig: (key: string) => Promise<string | null>;
    // #358 T4/T5: windowed reads for the `?days=N` extended digest mode.
    // Only called when a windowDays is passed to runStatus.
    getTradesSince: (sinceIso: string) => Promise<TradeRow[]>;
    getRegimeStatesSince: (sinceDate: string) => Promise<RegimeStateRow[]>;
    // #383 T4: equity_snapshots reads for the `returns` block. Always called
    // (both default and extended mode) — independent of windowDays/`?days=N`,
    // and independent of the live alpaca.getAccountValue() read used for
    // `alpaca.equity_usd`.
    getEarliestEquitySnapshot: () => Promise<EquitySnapshotRow | null>;
    getLatestEquitySnapshot: () => Promise<EquitySnapshotRow | null>;
    getEquitySnapshotsSince: (sinceDate: string) => Promise<EquitySnapshotRow[]>;
    // #396 T1: latest audit_log row for a single script, used to build
    // `last_runs` for the dead-man watchdog (scripts/deadman_check.ts).
    getLatestAuditForScript: (scriptName: string) => Promise<AuditLogRow | null>;
  };
}

export interface StatusDigest {
  generated_at: string;
  market_open: boolean;
  paused: boolean;
  regime: RegimeStateRow | null;
  // #384: SPY's raw (unrounded) % distance from its 200-DMA, derived from
  // `regime.spy_close`/`regime.spy_sma200` — positive above the line (LONG
  // side), negative below (CASH side), matching computeTargetState's sense.
  // Required (always present, both digest modes) and nullable — null when
  // regime is null (no regime_state row yet).
  regime_margin_pct: number | null;
  // Legacy key name kept in both modes (#358 D4) so the response shape never
  // forks between default and extended mode; `since` is self-describing and
  // reflects the widened window when `windowDays` is set.
  audit_7d: {
    since: string;
    outcome_counts: Record<string, number>;
    errors: AuditLogRow[];
  };
  last_trade: TradeRow | null;
  alpaca: {
    equity_usd: number;
    position: { symbol: string; qty: number };
  };
  // #383 T4: trailing portfolio returns computed from equity_snapshots.
  // Top-level, always present in both default and extended (`?days=N`) mode
  // — unlike `trades`/`regime_history` below, presence does not depend on
  // `windowDays`. Sourced only from equity_snapshots; never cross-wired to
  // the live `alpaca.getAccountValue()` read used for `alpaca.equity_usd` —
  // the two numbers may legitimately differ intraday. No manual rounding
  // (raw float, like `position_drawdown_pct`).
  returns: {
    since_inception_pct: number | null;
    trailing_7d_pct: number | null;
    trailing_30d_pct: number | null;
  };
  // #358: only present when `runStatus` is called with a `windowDays`
  // (i.e. `?days=N` was supplied). Never set to `undefined` — the keys are
  // conditionally spread so they are entirely absent from the JSON in
  // default mode (D3), keeping the no-param response byte-identical.
  trades?: TradeRow[];
  regime_history?: RegimeStateRow[];
  // #396 T1: latest audit_log row per monitored script, so an external
  // dead-man watchdog can detect a stalled pg_cron pipeline (a stack that
  // has stopped invoking daily-check/kill-switch entirely can't be caught by
  // audit_7d's outcome counts alone — a widened `?days=N` window can still
  // miss a stall shorter than the window, and audit_7d.errors only carries
  // `error:*` rows, not the latest row overall). Required (always present,
  // both digest modes), snake_case JSON keys so `jq` paths need no quoting.
  // `null` per script when that script has never written an audit_log row.
  last_runs: {
    daily_check: { started_at: string; outcome: string | null } | null;
    kill_switch: { started_at: string; outcome: string | null } | null;
  };
}

// A crashed/still-open run leaves outcome NULL in the DB (documented in
// CLAUDE.md: "outcome is written before exit so a crashed run leaves a row
// with no finished_at") — group those under this label instead of "null".
const UNFINISHED_LABEL = "(unfinished)";

// #384: pure helper — SPY's % distance from its 200-DMA. Stored/returned
// unrounded (raw float); rounding to 1 decimal happens in the shell renderers.
// Guards spySma200 <= 0 and non-finite inputs -> null (never Infinity/NaN).
export function computeRegimeMarginPct(spyClose: number, spySma200: number): number | null {
  if (!Number.isFinite(spyClose) || !Number.isFinite(spySma200) || spySma200 <= 0) {
    return null;
  }
  return ((spyClose - spySma200) / spySma200) * 100;
}

// #383 T4: `returns` helpers — pure, calendar-date arithmetic on
// EquitySnapshotRow, anchored on the latest snapshot's date (not deps.now()),
// so a stale digest (e.g. daily-check hasn't run in a couple of days) still
// reports trailing windows relative to the data it actually has.

// EQUITY_WINDOW_LOOKBACK_DAYS: how far back of the latest snapshot's date to
// fetch candidate rows for the trailing_30d_pct search. 60 gives 30 days of
// buffer beyond the widest trailing window (30d) to tolerate gaps (an
// error:*/skipped:* day writes no snapshot), while staying within
// getEquitySnapshotsSince's .limit(60) row cap: daily-check only writes a
// snapshot on trading days, so 60 calendar days yields ~44 rows at most —
// comfortably under the cap even before accounting for gap days.
const EQUITY_WINDOW_LOOKBACK_DAYS = 60;

function shiftDate(dateStr: string, days: number): string {
  const d = new Date(`${dateStr}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function pctChange(from: number, to: number): number {
  return (to - from) / from * 100;
}

// Closest snapshot with date <= thresholdDate, out of an ascending-by-date
// array. Returns null if every row postdates the threshold (not old enough).
function closestOnOrBefore(
  ascendingRows: EquitySnapshotRow[],
  thresholdDate: string,
): EquitySnapshotRow | null {
  let result: EquitySnapshotRow | null = null;
  for (const row of ascendingRows) {
    if (row.date <= thresholdDate) {
      result = row;
    } else {
      break;
    }
  }
  return result;
}

function computeReturns(
  earliest: EquitySnapshotRow | null,
  latest: EquitySnapshotRow | null,
  window: EquitySnapshotRow[],
): StatusDigest["returns"] {
  if (!earliest || !latest) {
    return { since_inception_pct: null, trailing_7d_pct: null, trailing_30d_pct: null };
  }
  const sorted = [...window].sort((a, b) => a.date.localeCompare(b.date));
  const sevenBase = closestOnOrBefore(sorted, shiftDate(latest.date, 7));
  const thirtyBase = closestOnOrBefore(sorted, shiftDate(latest.date, 30));
  return {
    since_inception_pct: pctChange(earliest.equity_usd, latest.equity_usd),
    trailing_7d_pct: sevenBase ? pctChange(sevenBase.equity_usd, latest.equity_usd) : null,
    trailing_30d_pct: thirtyBase ? pctChange(thirtyBase.equity_usd, latest.equity_usd) : null,
  };
}

// windowDays: presence (not value) toggles extended mode (#358 D3). Absent ->
// the legacy 7-day-window, 7-key response (byte-identical to the current
// deployment); present -> same base shape plus `trades`/`regime_history`.
export async function runStatus(deps: StatusDeps, windowDays?: number): Promise<StatusDigest> {
  const { db, alpaca, config } = deps;
  const now = deps.now();
  const until = now.toISOString();
  const since = new Date(now.getTime() - (windowDays ?? 7) * DAY_MS).toISOString();
  const extended = windowDays !== undefined;

  const [
    regime,
    auditRows,
    lastTrade,
    pausedRaw,
    clock,
    equity,
    positionQty,
    trades,
    regimeHistory,
    earliestSnapshot,
    latestSnapshot,
    latestDailyCheckAudit,
    latestKillSwitchAudit,
  ] = await Promise.all([
    db.getLatestRegimeState(),
    db.getAuditLogSince(since, until),
    db.getLastTrade(),
    db.getConfig("paused"),
    alpaca.getClock(),
    alpaca.getAccountValue(),
    alpaca.getPosition(config.botTicker),
    extended ? db.getTradesSince(since) : Promise.resolve(undefined),
    // date part of `since` (already UTC via toISOString) is the boundary for
    // the once-a-day regime_state table.
    extended ? db.getRegimeStatesSince(since.slice(0, 10)) : Promise.resolve(undefined),
    db.getEarliestEquitySnapshot(),
    db.getLatestEquitySnapshot(),
    // #396 T1: script names match audit_log.script_name exactly, as written
    // by daily-check/kill-switch's insertAuditLog calls.
    db.getLatestAuditForScript("daily-check"),
    db.getLatestAuditForScript("kill-switch"),
  ]);

  const outcome_counts: Record<string, number> = {};
  for (const row of auditRows) {
    const key = row.outcome ?? UNFINISHED_LABEL;
    outcome_counts[key] = (outcome_counts[key] ?? 0) + 1;
  }
  const errors = auditRows.filter((r) => r.outcome?.startsWith("error:"));

  // #383 T4: the window query needs latestSnapshot's date, so it can't join
  // the Promise.all above; always computed (both modes), independent of
  // windowDays.
  const equityWindow = latestSnapshot
    ? await db.getEquitySnapshotsSince(shiftDate(latestSnapshot.date, EQUITY_WINDOW_LOOKBACK_DAYS))
    : [];
  const returns = computeReturns(earliestSnapshot, latestSnapshot, equityWindow);

  return {
    generated_at: now.toISOString(),
    market_open: clock.isOpen,
    paused: pausedRaw === "true",
    regime,
    regime_margin_pct: regime ? computeRegimeMarginPct(regime.spy_close, regime.spy_sma200) : null,
    audit_7d: { since, outcome_counts, errors },
    last_trade: lastTrade,
    alpaca: {
      equity_usd: equity,
      position: { symbol: config.botTicker, qty: positionQty },
    },
    returns,
    last_runs: {
      daily_check: latestDailyCheckAudit
        ? { started_at: latestDailyCheckAudit.started_at, outcome: latestDailyCheckAudit.outcome }
        : null,
      kill_switch: latestKillSwitchAudit
        ? { started_at: latestKillSwitchAudit.started_at, outcome: latestKillSwitchAudit.outcome }
        : null,
    },
    ...(extended
      ? { trades: trades as TradeRow[], regime_history: regimeHistory as RegimeStateRow[] }
      : {}),
  };
}
