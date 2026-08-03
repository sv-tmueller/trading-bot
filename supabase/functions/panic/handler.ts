// HTTP layer for the panic Edge Function. Split out of index.ts so the
// method/auth/status mapping is unit-testable without Deno.serve; the action
// runner is injectable for the same reason (defaults to the real deps).
import { type PanicAction, type PanicOpts, type PanicResult, runPanic } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { insertAuditLog, insertTrade, setConfig, updateAuditLog } from "../_shared/db.ts";
import { notifyPanic } from "../_shared/notifications.ts";
// timingSafeEqual moved to _shared/auth.ts (T1 of #354) so the new status
// Edge Function's token check can reuse it too.
import { timingSafeEqual } from "../_shared/auth.ts";

const VALID: PanicAction[] = ["pause", "resume", "cancel-orders", "liquidate"];

function runWithRealDeps(action: PanicAction, opts: PanicOpts): Promise<PanicResult> {
  const sb = getServiceClient();
  // #508: explicit opt-out -- panic is the deterministic kill button, a
  // protective-exit path that must keep functioning on a live account at
  // #230 go-live; this literal is that decision's marker for a future
  // reviewer.
  const alpaca = createAlpacaClient({ paperOnly: false });
  return runPanic(
    {
      config: getStrategyConfig(),
      now: () => new Date(),
      alpaca: {
        cancelAllOrders: () => alpaca.cancelAllOrders(),
        // #474 D1/§8.2: position-driven, side-aware flatten.
        getOpenPositions: () => alpaca.getOpenPositions(),
        closePosition: (s) => alpaca.closePosition(s),
      },
      db: {
        setConfig: (k, v) => setConfig(sb, k, v),
        insertTrade: (p) => insertTrade(sb, p),
        insertAuditLog: (p) => insertAuditLog(sb, p),
        updateAuditLog: (p) => updateAuditLog(sb, p),
      },
      notifications: { notifyPanic },
    },
    action,
    opts,
  );
}

export async function handlePanic(
  req: Request,
  run: (action: PanicAction, opts: PanicOpts) => Promise<PanicResult> = runWithRealDeps,
): Promise<Response> {
  const json = (body: unknown, status: number) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });

  // Panic actions are state-changing: POST only, checked before auth.
  if (req.method !== "POST") {
    return json({ error: "method not allowed" }, 405);
  }

  // Unset/empty PANIC_TOKEN fails closed.
  const expected = Deno.env.get("PANIC_TOKEN") ?? "";
  const token = req.headers.get("x-panic-token") ?? "";
  if (expected === "" || !(await timingSafeEqual(token, expected))) {
    return json({ error: "unauthorized" }, 401);
  }

  const url = new URL(req.url);
  const action = (url.searchParams.get("action") ?? "") as PanicAction;
  if (!VALID.includes(action)) {
    return json({ error: `action must be one of ${VALID.join("|")}` }, 400);
  }

  // Finding 13 / #185 option 1: liquidate auto-pauses unless ?pause=false.
  const pauseOnLiquidate = url.searchParams.get("pause") !== "false";

  let result: PanicResult;
  try {
    result = await run(action, { pauseOnLiquidate });
  } catch (e) {
    return json({ result: "internal: " + (e as Error).message }, 500);
  }
  // Surface a failed action (e.g. liquidate timeout) as 500 so the operator
  // can't mistake an error result for success.
  return json({ result: result.result }, result.ok ? 200 : 500);
}
