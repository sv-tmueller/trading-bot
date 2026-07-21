// HTTP layer for the daily-check Edge Function. Split out of index.ts so the
// auth + pipeline flow is unit-testable without Deno.serve; the pipeline
// runner is injectable for the same reason (defaults to the real deps).
import { type DailyCheckDeps, runDailyCheck } from "./logic.ts";
import { requireServiceRole } from "../_shared/auth.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getDailyCloses, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  claimTradeDate,
  getConfig,
  getLatestRegimeState,
  insertAuditLog,
  insertTrade,
  updateAuditLog,
  upsertEquitySnapshot,
  upsertRegimeState,
} from "../_shared/db.ts";
import { createOutbox } from "../_shared/outbox.ts";

function buildDeps(): DailyCheckDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  const outbox = createOutbox(sb);
  const deps: DailyCheckDeps = {
    config: getStrategyConfig(),
    now: () => new Date(),
    marketdata: { getDailyCloses, getLatestTradePrice },
    alpaca: {
      getClock: () => alpaca.getClock(),
      getCalendar: (s, e) => alpaca.getCalendar(s, e),
      getPosition: (s) => alpaca.getPosition(s),
      getAccountValue: () => alpaca.getAccountValue(),
      placeMarketOrder: (a) => alpaca.placeMarketOrder(a),
      liquidate: (s) => alpaca.liquidate(s),
    },
    db: {
      getConfig: (k) => getConfig(sb, k),
      getLatestRegimeState: () => getLatestRegimeState(sb),
      claimTradeDate: (scriptName, tradeDate) => claimTradeDate(sb, scriptName, tradeDate),
      upsertRegimeState: (p) => upsertRegimeState(sb, p),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
      upsertEquitySnapshot: (p) => upsertEquitySnapshot(sb, p),
    },
    notifications: outbox.notifications,
  };
  return deps;
}

function runWithRealDeps(): Promise<string> {
  return runDailyCheck(buildDeps());
}

// #397 T5: flush is called after run() completes, never inside logic.ts --
// trading never waits behind a webhook-outage backlog. It writes no
// audit_log row (same principle as status's read-only path) and is retried
// every 5 minutes for free by the kill-switch cadence. Wrapped in its own
// try/catch as belt-and-braces even though flushOutbox itself never throws.
function flushWithRealDeps(): Promise<void> {
  return createOutbox(getServiceClient()).flush();
}

export async function handleDailyCheck(
  req: Request,
  run: () => Promise<string> = runWithRealDeps,
  flush: () => Promise<void> = flushWithRealDeps,
): Promise<Response> {
  const authError = requireServiceRole(req);
  if (authError !== null) return authError;

  const outcome = await run();
  try {
    await flush();
  } catch (e) {
    console.warn(`daily-check: outbox flush threw unexpectedly: ${String(e).slice(0, 200)}`);
  }
  return new Response(JSON.stringify({ outcome }), {
    headers: { "content-type": "application/json" },
  });
}
