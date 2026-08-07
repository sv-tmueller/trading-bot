// HTTP layer for the status Edge Function. Split out of index.ts so the
// method/auth mapping is unit-testable without Deno.serve; the digest runner
// is injectable for the same reason (defaults to the real deps).
import { runStatus, type StatusDeps } from "./logic.ts";
import type { StatusDigest } from "./logic.ts";
import { getHourlyShortsEnabled, getStatusToken, getStrategyConfig } from "../_shared/config.ts";
import { timingSafeEqual } from "../_shared/auth.ts";
import { createAlpacaClient } from "../_shared/alpaca.ts";
import { getServiceClient } from "../_shared/supabase_client.ts";
import {
  getAuditLogSince,
  getConfig,
  getEarliestEquitySnapshot,
  getEquitySnapshotsSince,
  getHourlyScansInWindow,
  getHourlyScansSince,
  getLastTrade,
  getLatestAuditForScript,
  getLatestEquitySnapshot,
  getLatestHourlyScan,
  getLatestRegimeState,
  getRegimeStatesSince,
  getTradesInWindow,
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
    // #546: the narrow reader, NOT getHourlyConfig() -- see StatusDeps's
    // doc comment in logic.ts for why (lead decision on #545).
    shortsEnabled: getHourlyShortsEnabled(),
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
      getHourlyScansInWindow: (sinceIso, untilIso) =>
        getHourlyScansInWindow(sb, sinceIso, untilIso),
      getTradesInWindow: (sinceIso, untilIso) => getTradesInWindow(sb, sinceIso, untilIso),
    },
  };
}

function runWithRealDeps(days?: number, verifyDate?: string): Promise<StatusDigest> {
  return runStatus(buildDeps(), days, verifyDate);
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

// #546: `?verify=YYYY-MM-DD` — presence (not value) toggles the digest's
// `verification` block (see runStatus). A malformed/out-of-range value is a
// 400, never a silent fallback, mirroring parseDays above.
const MAX_VERIFY_DAYS_BACK = 90;
const DAY_MS = 24 * 60 * 60 * 1000;

type VerifyParseResult = { ok: true; value: string | undefined } | { ok: false };

function parseVerify(url: URL, now: () => Date): VerifyParseResult {
  const raw = url.searchParams.get("verify");
  if (raw === null) return { ok: true, value: undefined };
  const trimmed = raw.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return { ok: false };

  const parsed = new Date(`${trimmed}T00:00:00Z`);
  // `new Date("2026-13-01T00:00:00Z")` -> NaN getTime(). Guard first: the
  // round-trip check below would otherwise call toISOString() on an invalid
  // Date and throw.
  if (Number.isNaN(parsed.getTime())) return { ok: false };
  // `new Date("2026-02-30T00:00:00Z")` silently rolls over to 2026-03-02
  // instead of producing NaN — caught by round-tripping through
  // toISOString() and comparing the date part back to the trimmed input.
  // Neither this check nor the NaN check alone is sufficient.
  if (parsed.toISOString().slice(0, 10) !== trimmed) return { ok: false };

  // Anchor both sides at UTC midnight before diffing (mirroring logic.ts's
  // shiftDate style), so time-of-day never drifts the not-future/90-day
  // bounds.
  const todayMidnight = new Date(`${now().toISOString().slice(0, 10)}T00:00:00Z`);
  if (parsed.getTime() > todayMidnight.getTime()) return { ok: false }; // future
  const daysBack = (todayMidnight.getTime() - parsed.getTime()) / DAY_MS;
  if (daysBack > MAX_VERIFY_DAYS_BACK) return { ok: false };

  return { ok: true, value: trimmed };
}

export async function handleStatus(
  req: Request,
  run: (days?: number, verifyDate?: string) => Promise<StatusDigest> = runWithRealDeps,
  now: () => Date = () => new Date(),
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
  const url = new URL(req.url);
  const daysResult = parseDays(url);
  if (!daysResult.ok) {
    return json({ error: "days must be an integer between 1 and 60" }, 400);
  }

  // #546: validation order is days before verify, matching this file's
  // existing precedence (method before days, auth before days).
  const verifyResult = parseVerify(url, now);
  if (!verifyResult.ok) {
    return json({
      error:
        "verify must be a real calendar date (YYYY-MM-DD), not in the future, and within 90 days",
    }, 400);
  }

  try {
    const digest = await run(daysResult.value, verifyResult.value);
    return json(digest, 200);
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }
}
