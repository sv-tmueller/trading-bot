// Pure aggregation for the read-only status digest (#354 T4). No decision
// logic, no writes: StatusDeps exposes only read methods (getClock,
// getAccountValue, getPosition off Alpaca; four SELECT-only db.ts helpers),
// so there is nothing here that could reach a mutating broker call or write
// to the DB even by mistake — that is enforced at the type level, not just
// by convention. In particular, unlike runPanic, this never opens/closes an
// audit_log row: status is deliberately invisible to that table so it stays
// a clean record of trading actions.
import type { StrategyConfig } from "../_shared/config.ts";
import type {
  AuditLogRow,
  EquitySnapshotRow,
  HourlyScanRow,
  RegimeStateRow,
  TradeRow,
} from "../_shared/db.ts";
import { requireNumber } from "../_shared/num.ts";

const DAY_MS = 24 * 60 * 60 * 1000;

export interface StatusDeps {
  config: StrategyConfig;
  now: () => Date;
  // #546: the narrow HOURLY_SHORTS_ENABLED reader's result (getHourlyShortsEnabled()
  // in _shared/config.ts), passed in by handler.ts's buildDeps() rather than
  // read here via getHourlyConfig() -- that function throws unless
  // HOURLY_BOT_PAPER_ONLY is explicitly "true", which would take this
  // read-only, availability-critical endpoint down over one unrelated secret
  // (lead decision on #545). Feeds `verification.shorts_enabled` only.
  shortsEnabled: boolean;
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
    // #536 T3: read-only reads for the `hourly` digest block, sourced from
    // hourly_scans + bot_config. No symbol filter -- one bot instance, one
    // symbol, same assumption already documented in
    // scripts/render_weekly_journal.ts.
    getLatestHourlyScan: () => Promise<HourlyScanRow | null>;
    getHourlyScansSince: (sinceIso: string) => Promise<HourlyScanRow[]>;
    // #546: day-scoped [since, until] reads for the `verification` block.
    // Only called when `verifyDate` is passed to runStatus. No mutating
    // helper is added alongside these -- the read-only-by-type guarantee
    // documented at the top of this file still holds.
    getHourlyScansInWindow: (sinceIso: string, untilIso: string) => Promise<HourlyScanRow[]>;
    getTradesInWindow: (sinceIso: string, untilIso: string) => Promise<TradeRow[]>;
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
    // #536 T3: alongside daily_check/kill_switch above, for the same
    // dead-man-watchdog purpose.
    hourly_check: { started_at: string; outcome: string | null } | null;
  };
  // #536 T3: the live hourly bot's digest, sourced from hourly_scans +
  // bot_config -- strictly additive, no existing key touched. Required
  // (always present, both digest modes), unlike `trades`/`regime_history`.
  hourly: {
    // Direct pass-through of the newest hourly_scans row, same style as
    // `regime`/`last_trade` above -- carries bracket geometry (entry
    // reference price, stop, target, qty) when that scan entered.
    latest_scan: HourlyScanRow | null;
    equity: {
      // Sourced from latest_scan.equity_usd -- never a live
      // alpaca.getAccountValue() read, matching render_weekly_journal.ts's
      // documented equity source for the hourly bot.
      equity_usd: number | null;
      // bot_config.hourly_experiment_start_equity; null when unset.
      floor_baseline_usd: number | null;
      floor_price_usd: number | null;
      headroom_pct: number | null;
    };
    // Bar-level distribution over the same [since, until] window as
    // audit_7d, grouped exactly like computeWeeklyAggregates in
    // scripts/render_weekly_journal.ts (skip_reason ?? "unspecified";
    // LONG/SHORT rows excluded).
    skip_reason_counts: Record<string, number>;
    // Run-level outcome counts for script_name === "hourly-check" only,
    // filtered from the same auditRows already fetched for audit_7d -- no
    // second DB round trip.
    audit_outcome_counts: Record<string, number>;
  };
  // #546: only present when `runStatus` is called with a `verifyDate`
  // (i.e. `?verify=YYYY-MM-DD` was supplied). Never set to `undefined` --
  // the key is conditionally spread so it is entirely absent from the JSON
  // when no verifyDate is given, matching the `trades`/`regime_history`
  // precedent (#358 D3). Frozen shape: spec §4.3
  // (docs/superpowers/specs/2026-08-06-daily-verification-design.md) --
  // #547's evaluator implements against this shape from its own fixtures,
  // with no file shared between the two packages, so a silent deviation here
  // breaks #547 without either package's tests catching it.
  verification?: {
    date: string;
    window: { since: string; until: string };
    shorts_enabled: boolean;
    // Filtered to script_name === "hourly-check", ascending by started_at.
    // `notes` carries the journal-degraded order id (rollout runbook §10).
    hourly_check_runs: Array<
      {
        started_at: string;
        finished_at: string | null;
        outcome: string | null;
        notes: string | null;
      }
    >;
    // Counts only, never rows -- 108 identical-outcome rows carry no
    // information the counts lack.
    kill_switch_runs: { count: number; outcome_counts: Record<string, number> };
    // Full HourlyScanRow values, ascending by bar_ts.
    scans: HourlyScanRow[];
    // Full TradeRow values, unfiltered by reason, ascending by fill_time --
    // the evaluator applies the `hourly%` filter, so a future reason string
    // needs no redeploy here.
    trades: TradeRow[];
    // Raw `bot_config` strings, null when unset. `hourly_experiment_start_equity`
    // and `hourly_experiment_baseline_verified` MUST NOT be coerced to number
    // -- check 6 (#547) is a byte-identity string comparison, which coercion
    // would destroy.
    config: {
      paused: string | null;
      hourly_experiment_start_equity: string | null;
      hourly_experiment_baseline_verified: string | null;
    };
  };
}

// #536: mirrors supabase/functions/hourly-check/logic.ts's own
// EQUITY_FLOOR_PCT (and scripts/render_weekly_journal.ts's copy of it).
// Duplicated rather than imported/extracted to `_shared/`: this package's
// batch slicing keeps status/logic.ts single-owner, and hourly-check/logic.ts
// is a file this package deliberately does not touch. Kept in sync manually
// -- a mismatch here would only affect this digest's rendered headroom, never
// the live floor enforcement in hourly-check itself.
const EQUITY_FLOOR_PCT = 0.15;

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

// #536: pure helper — the hourly bot's equity headroom above its -15% floor,
// as a % of current equity (how much further equity could drop before
// hitting floorPriceUsd). Guarded like computeRegimeMarginPct: non-finite
// inputs and equityUsd <= 0 (division by zero / nonsensical domain) -> null,
// never Infinity/NaN.
export function computeEquityHeadroomPct(
  equityUsd: number,
  floorPriceUsd: number,
): number | null {
  if (!Number.isFinite(equityUsd) || !Number.isFinite(floorPriceUsd) || equityUsd <= 0) {
    return null;
  }
  return ((equityUsd - floorPriceUsd) / equityUsd) * 100;
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
// verifyDate: presence (not value) toggles the `verification` block (#546),
// independently of windowDays -- the two params compose freely.
export async function runStatus(
  deps: StatusDeps,
  windowDays?: number,
  verifyDate?: string,
): Promise<StatusDigest> {
  const { db, alpaca, config } = deps;
  const now = deps.now();
  const until = now.toISOString();
  const since = new Date(now.getTime() - (windowDays ?? 7) * DAY_MS).toISOString();
  const extended = windowDays !== undefined;
  const verifying = verifyDate !== undefined;
  // #546: fixed string templates, not date arithmetic -- avoids any
  // month/year-boundary bug (sub-plan). Deliberately a distinct window from
  // `since`/`until` above (the 7-day/`?days=N` window): the two are never
  // conflated.
  const verifySince = verifying ? `${verifyDate}T00:00:00.000Z` : undefined;
  const verifyUntil = verifying ? `${verifyDate}T23:59:59.999Z` : undefined;

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
    latestHourlyCheckAudit,
    latestHourlyScan,
    hourlyScansWindow,
    hourlyFloorBaselineRaw,
    verifyAuditRows,
    verifyScans,
    verifyTrades,
    hourlyBaselineVerifiedRaw,
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
    // #536 T3: hourly digest reads.
    db.getLatestAuditForScript("hourly-check"),
    db.getLatestHourlyScan(),
    db.getHourlyScansSince(since),
    db.getConfig("hourly_experiment_start_equity"),
    // #546: `verification` block reads -- a second, day-scoped
    // getAuditLogSince call, distinct from the 7-day/`?days=N` call above.
    verifying ? db.getAuditLogSince(verifySince!, verifyUntil!) : Promise.resolve(undefined),
    verifying ? db.getHourlyScansInWindow(verifySince!, verifyUntil!) : Promise.resolve(undefined),
    verifying ? db.getTradesInWindow(verifySince!, verifyUntil!) : Promise.resolve(undefined),
    verifying ? db.getConfig("hourly_experiment_baseline_verified") : Promise.resolve(undefined),
  ]);

  const outcome_counts: Record<string, number> = {};
  const hourlyAuditOutcomeCounts: Record<string, number> = {};
  for (const row of auditRows) {
    const key = row.outcome ?? UNFINISHED_LABEL;
    outcome_counts[key] = (outcome_counts[key] ?? 0) + 1;
    // #536: same already-fetched auditRows, scoped to hourly-check -- no
    // second DB round trip.
    if (row.script_name === "hourly-check") {
      hourlyAuditOutcomeCounts[key] = (hourlyAuditOutcomeCounts[key] ?? 0) + 1;
    }
  }
  const errors = auditRows.filter((r) => r.outcome?.startsWith("error:"));

  // #536: skip-reason grouping matches computeWeeklyAggregates in
  // scripts/render_weekly_journal.ts exactly -- only SKIP rows are counted.
  const hourlySkipReasonCounts: Record<string, number> = {};
  for (const scan of hourlyScansWindow) {
    if (scan.decision === "SKIP") {
      const reason = scan.skip_reason ?? "unspecified";
      hourlySkipReasonCounts[reason] = (hourlySkipReasonCounts[reason] ?? 0) + 1;
    }
  }

  // #536: bot_config.hourly_experiment_start_equity is a runtime config
  // value, not an env secret -- null if never set (day-zero digest). A set
  // but non-numeric value throws (fail loud, not a silently corrupted
  // headroom), same contract as render_weekly_journal.ts's own read of it.
  const hourlyFloorBaselineUsd = hourlyFloorBaselineRaw == null
    ? null
    : requireNumber(hourlyFloorBaselineRaw, "hourly_experiment_start_equity");
  const hourlyFloorPriceUsd = hourlyFloorBaselineUsd == null
    ? null
    : hourlyFloorBaselineUsd * (1 - EQUITY_FLOOR_PCT);
  const hourlyEquityUsd = latestHourlyScan?.equity_usd ?? null;
  const hourlyHeadroomPct = hourlyEquityUsd != null && hourlyFloorPriceUsd != null
    ? computeEquityHeadroomPct(hourlyEquityUsd, hourlyFloorPriceUsd)
    : null;

  // #383 T4: the window query needs latestSnapshot's date, so it can't join
  // the Promise.all above; always computed (both modes), independent of
  // windowDays.
  const equityWindow = latestSnapshot
    ? await db.getEquitySnapshotsSince(shiftDate(latestSnapshot.date, EQUITY_WINDOW_LOOKBACK_DAYS))
    : [];
  const returns = computeReturns(earliestSnapshot, latestSnapshot, equityWindow);

  // #546: `verification` block -- split the day's audit rows into
  // hourly_check_runs (rows, ascending by started_at) and kill_switch_runs
  // (counts only), per spec §4.3.
  let verification: StatusDigest["verification"];
  if (verifying) {
    const dayRows = verifyAuditRows ?? [];
    const hourlyCheckRuns = dayRows
      .filter((r) => r.script_name === "hourly-check")
      .map((r) => ({
        started_at: r.started_at,
        finished_at: r.finished_at,
        outcome: r.outcome,
        notes: r.notes,
      }))
      .sort((a, b) => a.started_at.localeCompare(b.started_at));
    const killSwitchOutcomeCounts: Record<string, number> = {};
    let killSwitchCount = 0;
    for (const row of dayRows) {
      if (row.script_name !== "kill-switch") continue;
      killSwitchCount++;
      const key = row.outcome ?? UNFINISHED_LABEL;
      killSwitchOutcomeCounts[key] = (killSwitchOutcomeCounts[key] ?? 0) + 1;
    }
    verification = {
      date: verifyDate!,
      window: { since: verifySince!, until: verifyUntil! },
      shorts_enabled: deps.shortsEnabled,
      hourly_check_runs: hourlyCheckRuns,
      kill_switch_runs: { count: killSwitchCount, outcome_counts: killSwitchOutcomeCounts },
      scans: verifyScans ?? [],
      trades: verifyTrades ?? [],
      // Raw strings, no coercion (byte-identity-sensitive -- see check 6 in
      // spec §5.3). pausedRaw/hourlyFloorBaselineRaw are the same already-
      // fetched values used elsewhere in this digest, reused here verbatim.
      config: {
        paused: pausedRaw,
        hourly_experiment_start_equity: hourlyFloorBaselineRaw,
        hourly_experiment_baseline_verified: hourlyBaselineVerifiedRaw ?? null,
      },
    };
  }

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
      hourly_check: latestHourlyCheckAudit
        ? { started_at: latestHourlyCheckAudit.started_at, outcome: latestHourlyCheckAudit.outcome }
        : null,
    },
    hourly: {
      latest_scan: latestHourlyScan,
      equity: {
        equity_usd: hourlyEquityUsd,
        floor_baseline_usd: hourlyFloorBaselineUsd,
        floor_price_usd: hourlyFloorPriceUsd,
        headroom_pct: hourlyHeadroomPct,
      },
      skip_reason_counts: hourlySkipReasonCounts,
      audit_outcome_counts: hourlyAuditOutcomeCounts,
    },
    ...(extended
      ? { trades: trades as TradeRow[], regime_history: regimeHistory as RegimeStateRow[] }
      : {}),
    ...(verifying ? { verification } : {}),
  };
}
