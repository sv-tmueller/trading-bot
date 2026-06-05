import { runKillSwitch, type KillSwitchDeps } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getDailyCloses, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { getLatestRegimeState, insertAuditLog, insertTrade, updateAuditLog, upsertRegimeState } from "../_shared/db.ts";
import { notifyBrokerError, notifyKillSwitchFired, notifyTradeFailed } from "../_shared/notifications.ts";

function buildDeps(): KillSwitchDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return {
    config: getStrategyConfig(),
    now: () => new Date(),
    marketdata: { getDailyCloses, getLatestTradePrice },
    alpaca: { getClock: () => alpaca.getClock(), liquidate: (s) => alpaca.liquidate(s) },
    db: {
      getLatestRegimeState: () => getLatestRegimeState(sb),
      upsertRegimeState: (p) => upsertRegimeState(sb, p),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: { notifyKillSwitchFired, notifyTradeFailed, notifyBrokerError },
  };
}

Deno.serve(async () => {
  const outcome = await runKillSwitch(buildDeps());
  return new Response(JSON.stringify({ outcome }), { headers: { "content-type": "application/json" } });
});
