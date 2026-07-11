// HTTP layer for the status Edge Function. Split out of index.ts so the
// method/auth mapping is unit-testable without Deno.serve; the digest runner
// is injectable for the same reason (defaults to the real deps).
import { runStatus, type StatusDeps } from "./logic.ts";
import type { StatusDigest } from "./logic.ts";
import { getStatusToken, getStrategyConfig } from "../_shared/config.ts";
import { timingSafeEqual } from "../_shared/auth.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import { getAuditLogSince, getConfig, getLastTrade, getLatestRegimeState } from "../_shared/db.ts";

function buildDeps(): StatusDeps {
  const sb = getServiceClient();
  const alpaca = createAlpacaClient();
  return {
    config: getStrategyConfig(),
    now: () => new Date(),
    // Only the read-only Alpaca helpers are wired in — no mutating helper
    // (placeMarketOrder / liquidate / cancelAllOrders) is reachable from here.
    alpaca: {
      getClock: () => alpaca.getClock(),
      getAccountValue: () => alpaca.getAccountValue(),
      getPosition: (s) => alpaca.getPosition(s),
    },
    db: {
      getLatestRegimeState: () => getLatestRegimeState(sb),
      getAuditLogSince: (sinceIso, untilIso) => getAuditLogSince(sb, sinceIso, untilIso),
      getLastTrade: () => getLastTrade(sb),
      getConfig: (k) => getConfig(sb, k),
    },
  };
}

function runWithRealDeps(): Promise<StatusDigest> {
  return runStatus(buildDeps());
}

export async function handleStatus(
  req: Request,
  run: () => Promise<StatusDigest> = runWithRealDeps,
): Promise<Response> {
  const json = (body: unknown, status: number) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });

  // Status is read-only: GET only, checked before auth.
  if (req.method !== "GET") {
    return json({ error: "method not allowed" }, 405);
  }

  // Unset/empty STATUS_TOKEN fails closed. getStatusToken() throws on
  // unset/blank (config.ts validation) — treat that the same as a wrong
  // token so the observable behavior doesn't leak "misconfigured" vs "wrong".
  let expected: string;
  try {
    expected = getStatusToken();
  } catch {
    expected = "";
  }
  const token = req.headers.get("x-status-token") ?? "";
  if (expected === "" || !(await timingSafeEqual(token, expected))) {
    return json({ error: "unauthorized" }, 401);
  }

  try {
    const digest = await run();
    return json(digest, 200);
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }
}
