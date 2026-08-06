// HTTP layer for the status Edge Function. Split out of index.ts so the
// method/auth mapping is unit-testable without Deno.serve; the digest runner
// is injectable for the same reason (defaults to the real deps).
import { runStatus, type StatusDeps } from "./logic.ts";
import type { StatusDigest } from "./logic.ts";
import { getStatusToken, getStrategyConfig } from "../_shared/config.ts";
import { timingSafeEqual } from "../_shared/auth.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  getAuditLogSince,
  getConfig,
  getEarliestEquitySnapshot,
  getEquitySnapshotsSince,
  getHourlyScansSince,
  getLastTrade,
  getLatestAuditForScript,
  getLatestEquitySnapshot,
  getLatestHourlyScan,
  getLatestRegimeState,
  getRegimeStatesSince,
  getTradesSince,
} from "../_shared/db.ts";

function buildDeps(): StatusDeps {
  const sb = getServiceClient();
  // #508: explicit opt-out -- status is read-only (no mutating helper is
  // wired below), stated explicitly here for the scan's benefit rather than
  // relying on a default.
  const alpaca = createAlpacaClient({ paperOnly: false });
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
      getTradesSince: (sinceIso) => getTradesSince(sb, sinceIso),
      getRegimeStatesSince: (sinceDate) => getRegimeStatesSince(sb, sinceDate),
      getEarliestEquitySnapshot: () => getEarliestEquitySnapshot(sb),
      getLatestEquitySnapshot: () => getLatestEquitySnapshot(sb),
      getEquitySnapshotsSince: (sinceDate) => getEquitySnapshotsSince(sb, sinceDate),
      getLatestAuditForScript: (scriptName) => getLatestAuditForScript(sb, scriptName),
      getLatestHourlyScan: () => getLatestHourlyScan(sb),
      getHourlyScansSince: (sinceIso) => getHourlyScansSince(sb, sinceIso),
    },
  };
}

function runWithRealDeps(days?: number): Promise<StatusDigest> {
  return runStatus(buildDeps(), days);
}

// #358 D5: `?days=N` — presence (not value) toggles the digest's extended
// mode (see runStatus). Accepted syntax: trimmed `/^[0-9]+$/`, integer 1-60
// inclusive. Anything else (missing digits, decimals, out-of-range) is
// rejected so a malformed param never silently falls back to the default.
const MIN_DAYS = 1;
const MAX_DAYS = 60;

type DaysParseResult = { ok: true; value: number | undefined } | { ok: false };

function parseDays(url: URL): DaysParseResult {
  const raw = url.searchParams.get("days");
  if (raw === null) return { ok: true, value: undefined };
  const trimmed = raw.trim();
  if (!/^[0-9]+$/.test(trimmed)) return { ok: false };
  const value = Number(trimmed);
  if (value < MIN_DAYS || value > MAX_DAYS) return { ok: false };
  return { ok: true, value };
}

export async function handleStatus(
  req: Request,
  run: (days?: number) => Promise<StatusDigest> = runWithRealDeps,
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

  // #358 D5: 400 (bad `days`) comes after auth (401 stays the unauthenticated
  // surface) but before any dependency call (no buildDeps()/runStatus()).
  const daysResult = parseDays(new URL(req.url));
  if (!daysResult.ok) {
    return json({ error: "days must be an integer between 1 and 60" }, 400);
  }

  try {
    const digest = await run(daysResult.value);
    return json(digest, 200);
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }
}
