// HTTP layer for the kill-switch Edge Function. Split out of index.ts so the
// auth + pipeline flow is unit-testable without Deno.serve; the pipeline
// runner is injectable for the same reason (defaults to the real deps).
import { type KillSwitchDeps, runKillSwitch } from "./logic.ts";
import { requireServiceRole } from "../_shared/auth.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getDailyCloses, getLatestQuote, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  claimTradeDate,
  getLatestRegimeState,
  insertAuditLog,
  insertTrade,
  updateAuditLog,
  upsertRegimeState,
} from "../_shared/db.ts";
import { createOutbox } from "../_shared/outbox.ts";

function buildDeps(): KillSwitchDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  const outbox = createOutbox(sb);
  const deps: KillSwitchDeps = {
    config: getStrategyConfig(),
    now: () => new Date(),
    marketdata: { getDailyCloses, getLatestTradePrice, getLatestQuote },
    alpaca: {
      getClock: () => alpaca.getClock(),
      getPosition: (s) => alpaca.getPosition(s),
      liquidate: (s) => alpaca.liquidate(s),
    },
    db: {
      getLatestRegimeState: () => getLatestRegimeState(sb),
      claimTradeDate: (scriptName, tradeDate) => claimTradeDate(sb, scriptName, tradeDate),
      upsertRegimeState: (p) => upsertRegimeState(sb, p),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: outbox.notifications,
  };
  return deps;
}

function runWithRealDeps(): Promise<string> {
  return runKillSwitch(buildDeps());
}

// #397 T5: flush is called after run() completes, never inside logic.ts --
// trading never waits behind a webhook-outage backlog. It writes no
// audit_log row (same principle as status's read-only path) and, on this
// function's own 5-minute cadence during market hours, gets essentially-free
// retries of anything the daily-check flush couldn't clear. Wrapped in its
// own try/catch as belt-and-braces even though flushOutbox itself never
// throws.
function flushWithRealDeps(): Promise<void> {
  return createOutbox(getServiceClient()).flush();
}

export async function handleKillSwitch(
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
    console.warn(`kill-switch: outbox flush threw unexpectedly: ${String(e).slice(0, 200)}`);
  }
  return new Response(JSON.stringify({ outcome }), {
    headers: { "content-type": "application/json" },
  });
}
