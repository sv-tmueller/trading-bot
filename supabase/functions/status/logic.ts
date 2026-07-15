// Pure aggregation for the read-only status digest (#354 T4). No decision
// logic, no writes: StatusDeps exposes only read methods (getClock,
// getAccountValue, getPosition off Alpaca; four SELECT-only db.ts helpers),
// so there is nothing here that could reach a mutating broker call or write
// to the DB even by mistake — that is enforced at the type level, not just
// by convention. In particular, unlike runPanic, this never opens/closes an
// audit_log row: status is deliberately invisible to that table so it stays
// a clean record of trading actions.
import type { StrategyConfig } from "../_shared/config.ts";
import type { AuditLogRow, RegimeStateRow, TradeRow } from "../_shared/db.ts";

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
  // #358: only present when `runStatus` is called with a `windowDays`
  // (i.e. `?days=N` was supplied). Never set to `undefined` — the keys are
  // conditionally spread so they are entirely absent from the JSON in
  // default mode (D3), keeping the no-param response byte-identical.
  trades?: TradeRow[];
  regime_history?: RegimeStateRow[];
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
  ]);

  const outcome_counts: Record<string, number> = {};
  for (const row of auditRows) {
    const key = row.outcome ?? UNFINISHED_LABEL;
    outcome_counts[key] = (outcome_counts[key] ?? 0) + 1;
  }
  const errors = auditRows.filter((r) => r.outcome?.startsWith("error:"));

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
    ...(extended
      ? { trades: trades as TradeRow[], regime_history: regimeHistory as RegimeStateRow[] }
      : {}),
  };
}
