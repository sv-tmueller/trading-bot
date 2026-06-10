import { runDailyCheck, type DailyCheckDeps } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getDailyCloses, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  getConfig, getLatestRegimeState, insertAuditLog, insertTrade, updateAuditLog, upsertRegimeState,
} from "../_shared/db.ts";
import {
  notifyBrokerError, notifyRegimeFlip, notifyStateDesync, notifyTradeFailed,
} from "../_shared/notifications.ts";

function buildDeps(): DailyCheckDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return {
    config: getStrategyConfig(),
    now: () => new Date(),
    marketdata: { getDailyCloses, getLatestTradePrice },
    alpaca: {
      getClock: () => alpaca.getClock(),
      getPosition: (s) => alpaca.getPosition(s),
      getAccountValue: () => alpaca.getAccountValue(),
      placeMarketOrder: (a) => alpaca.placeMarketOrder(a),
      liquidate: (s) => alpaca.liquidate(s),
    },
    db: {
      getConfig: (k) => getConfig(sb, k),
      getLatestRegimeState: () => getLatestRegimeState(sb),
      upsertRegimeState: (p) => upsertRegimeState(sb, p),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: { notifyRegimeFlip, notifyStateDesync, notifyTradeFailed, notifyBrokerError },
  };
}

Deno.serve(async () => {
  const outcome = await runDailyCheck(buildDeps());
  return new Response(JSON.stringify({ outcome }), {
    headers: { "content-type": "application/json" },
  });
});
