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

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

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
    getAuditLogSince: (sinceIso: string) => Promise<AuditLogRow[]>;
    getLastTrade: () => Promise<TradeRow | null>;
    getConfig: (key: string) => Promise<string | null>;
  };
}

export interface StatusDigest {
  generated_at: string;
  market_open: boolean;
  paused: boolean;
  regime: RegimeStateRow | null;
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
}

// A crashed/still-open run leaves outcome NULL in the DB (documented in
// CLAUDE.md: "outcome is written before exit so a crashed run leaves a row
// with no finished_at") — group those under this label instead of "null".
const UNFINISHED_LABEL = "(unfinished)";

export async function runStatus(deps: StatusDeps): Promise<StatusDigest> {
  const { db, alpaca, config } = deps;
  const now = deps.now();
  const since = new Date(now.getTime() - SEVEN_DAYS_MS).toISOString();

  const [regime, auditRows, lastTrade, pausedRaw, clock, equity, positionQty] = await Promise.all([
    db.getLatestRegimeState(),
    db.getAuditLogSince(since),
    db.getLastTrade(),
    db.getConfig("paused"),
    alpaca.getClock(),
    alpaca.getAccountValue(),
    alpaca.getPosition(config.botTicker),
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
    audit_7d: { since, outcome_counts, errors },
    last_trade: lastTrade,
    alpaca: {
      equity_usd: equity,
      position: { symbol: config.botTicker, qty: positionQty },
    },
  };
}
