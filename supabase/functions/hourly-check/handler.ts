// HTTP layer for the hourly-check Edge Function. Mirrors daily-check/handler.ts
// exactly: auth + pipeline flow is unit-testable without Deno.serve, and the
// pipeline runner is injectable for the same reason (defaults to the real
// deps). The only opted-in Alpaca client in the repo -- createAlpacaClient
// is called with { paperOnly: true } here, and nowhere else (#475 T5/T12).
import { type HourlyCheckDeps, runHourlyCheck } from "./logic.ts";
import { requireServiceRole } from "../_shared/auth.ts";
import { getHourlyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getCalendarSessions, getHourlyBars, getLatestTradePrice } from "../_shared/marketdata.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  claimBar,
  getConfig,
  getHourlyScanByEntryOrderId,
  getTradesSince,
  insertAuditLog,
  insertTrade,
  setConfig,
  updateAuditLog,
  upsertHourlyScan,
} from "../_shared/db.ts";
import { createOutbox } from "../_shared/outbox.ts";

function buildDeps(): HourlyCheckDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient({ paperOnly: true });
  const outbox = createOutbox(sb);
  const deps: HourlyCheckDeps = {
    config: getHourlyConfig(),
    now: () => new Date(),
    marketdata: {
      getHourlyBars: (symbol, opts) => getHourlyBars(symbol, opts),
      getCalendarSessions: (start, end) => getCalendarSessions(start, end),
      getLatestTradePrice: (symbol) => getLatestTradePrice(symbol),
    },
    alpaca: {
      getClock: () => alpaca.getClock(),
      getPosition: (symbol) => alpaca.getPosition(symbol),
      assertPaperAccount: () => alpaca.assertPaperAccount(),
      placeBracketOrder: (args) => alpaca.placeBracketOrder(args),
      placeOcoExitPair: (args) => alpaca.placeOcoExitPair(args),
      placeMarketOrder: (args) => alpaca.placeMarketOrder(args),
      cancelOrder: (orderId) => alpaca.cancelOrder(orderId),
      getAssetShortability: (symbol) => alpaca.getAssetShortability(symbol),
      listFilledOrdersSince: (symbol, sinceIso) => alpaca.listFilledOrdersSince(symbol, sinceIso),
      listOpenOrderIds: (symbol) => alpaca.listOpenOrderIds(symbol),
    },
    db: {
      getConfig: (key) => getConfig(sb, key),
      setConfig: (key, value) => setConfig(sb, key, value),
      getTradesSince: (sinceIso) => getTradesSince(sb, sinceIso),
      upsertHourlyScan: (p) => upsertHourlyScan(sb, p),
      getHourlyScanByEntryOrderId: (symbol, orderId) =>
        getHourlyScanByEntryOrderId(sb, symbol, orderId),
      claimBar: (scriptName, barTs) => claimBar(sb, scriptName, barTs),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: outbox.notifications,
  };
  return deps;
}

function runWithRealDeps(): Promise<string> {
  return runHourlyCheck(buildDeps());
}

// #397 T5 precedent: flush is called after run() completes, never inside
// logic.ts -- trading never waits behind a webhook-outage backlog.
function flushWithRealDeps(): Promise<void> {
  return createOutbox(getServiceClient()).flush();
}

export async function handleHourlyCheck(
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
    console.warn(`hourly-check: outbox flush threw unexpectedly: ${String(e).slice(0, 200)}`);
  }
  return new Response(JSON.stringify({ outcome }), {
    headers: { "content-type": "application/json" },
  });
}
