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
import {
  notifyBrokerError,
  notifyError,
  notifyKillSwitchFired,
  notifyStateDesync,
} from "../_shared/notifications.ts";

function buildDeps(): KillSwitchDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return {
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
    notifications: {
      notifyKillSwitchFired,
      notifyBrokerError,
      notifyStateDesync,
      notifyError,
    },
  };
}

function runWithRealDeps(): Promise<string> {
  return runKillSwitch(buildDeps());
}

export async function handleKillSwitch(
  req: Request,
  run: () => Promise<string> = runWithRealDeps,
): Promise<Response> {
  const authError = requireServiceRole(req);
  if (authError !== null) return authError;

  const outcome = await run();
  return new Response(JSON.stringify({ outcome }), {
    headers: { "content-type": "application/json" },
  });
}
