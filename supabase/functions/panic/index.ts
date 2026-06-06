import { runPanic, type PanicAction } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { insertAuditLog, insertTrade, setConfig, updateAuditLog } from "../_shared/db.ts";
import { notifyPanic } from "../_shared/notifications.ts";

const VALID: PanicAction[] = ["pause", "resume", "cancel-orders", "liquidate"];

Deno.serve(async (req) => {
  const token = req.headers.get("x-panic-token") ?? "";
  const expected = Deno.env.get("PANIC_TOKEN") ?? "";
  if (expected === "" || token !== expected) {
    return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
  }
  const url = new URL(req.url);
  const action = (url.searchParams.get("action") ?? "") as PanicAction;
  if (!VALID.includes(action)) {
    return new Response(JSON.stringify({ error: `action must be one of ${VALID.join("|")}` }), { status: 400 });
  }

  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  const result = await runPanic({
    config: getStrategyConfig(),
    now: () => new Date(),
    alpaca: { cancelAllOrders: () => alpaca.cancelAllOrders(), liquidate: (s) => alpaca.liquidate(s) },
    db: {
      setConfig: (k, v) => setConfig(sb, k, v),
      insertTrade: (p) => insertTrade(sb, p),
      insertAuditLog: (p) => insertAuditLog(sb, p),
      updateAuditLog: (p) => updateAuditLog(sb, p),
    },
    notifications: { notifyPanic },
  }, action);

  // Surface a failed action (e.g. liquidate timeout) as 500 so the operator
  // can't mistake an error result for success.
  const status = result.ok ? 200 : 500;
  return new Response(JSON.stringify({ result: result.result }), {
    status,
    headers: { "content-type": "application/json" },
  });
});
