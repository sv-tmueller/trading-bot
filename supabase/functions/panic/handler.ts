// HTTP layer for the panic Edge Function. Split out of index.ts so the
// method/auth/status mapping is unit-testable without Deno.serve; the action
// runner is injectable for the same reason (defaults to the real deps).
import { runPanic, type PanicAction } from "./logic.ts";
import { getStrategyConfig } from "../_shared/config.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { insertAuditLog, insertTrade, setConfig, updateAuditLog } from "../_shared/db.ts";
import { notifyPanic } from "../_shared/notifications.ts";

const VALID: PanicAction[] = ["pause", "resume", "cancel-orders", "liquidate"];

// Constant-time string comparison (finding 5, 2026-06-11 review): hash both
// sides with SHA-256 and compare the fixed-length digests byte-wise with no
// early exit, so neither the token's length nor its bytes leak via timing.
export async function timingSafeEqual(a: string, b: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [da, db] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const ua = new Uint8Array(da);
  const ub = new Uint8Array(db);
  let diff = 0;
  for (let i = 0; i < ua.length; i++) diff |= ua[i] ^ ub[i];
  return diff === 0;
}

function runWithRealDeps(action: PanicAction): Promise<string> {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return runPanic({
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
}

export async function handlePanic(
  req: Request,
  run: (action: PanicAction) => Promise<string> = runWithRealDeps,
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

  const result = await run(action);
  // Surface a failed action (e.g. liquidate timeout) as 500 so the operator
  // can't mistake an error result for success.
  return json({ result }, result.startsWith("error:") ? 500 : 200);
}
