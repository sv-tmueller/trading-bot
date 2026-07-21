// Supabase persistence. Mirrors tools/database.py. Each function takes the
// Supabase client so callers (Edge Functions) inject the service-role client.
// `supabase functions deploy`'s bundler does not resolve the repo-root deno.json import map, so
// this inline jsr: specifier is load-bearing for deployment.
// deno-lint-ignore no-import-prefix
import type { SupabaseClient } from "jsr:@supabase/supabase-js@^2.45.0";
import { requireNumber } from "./num.ts";

export interface RegimeStateRow {
  date: string;
  spy_close: number;
  spy_sma200: number;
  target_state: "LONG" | "CASH";
  current_state: "LONG" | "CASH";
  position_drawdown_pct: number | null;
  kill_switch_active: boolean;
  kill_switch_fired_at: string | null;
  created_at?: string;
}

// PostgREST returns `numeric` columns as JSON strings to preserve precision.
// Coerce the price/money fields back to number so RegimeStateRow stays
// number-typed for the bot. Accepts numbers too (pre-migration double rows).
export function coerceRegimeRow(raw: Record<string, unknown>): RegimeStateRow {
  return {
    date: raw.date as string,
    spy_close: requireNumber(raw.spy_close, "spy_close"),
    spy_sma200: requireNumber(raw.spy_sma200, "spy_sma200"),
    target_state: raw.target_state as "LONG" | "CASH",
    current_state: raw.current_state as "LONG" | "CASH",
    position_drawdown_pct: raw.position_drawdown_pct == null
      ? null
      : requireNumber(raw.position_drawdown_pct, "position_drawdown_pct"),
    kill_switch_active: raw.kill_switch_active as boolean,
    kill_switch_fired_at: (raw.kill_switch_fired_at as string | null) ?? null,
    created_at: raw.created_at as string | undefined,
  };
}

export async function upsertRegimeState(sb: SupabaseClient, p: {
  date: string;
  spyClose: number;
  spySma200: number;
  targetState: "LONG" | "CASH";
  currentState: "LONG" | "CASH";
  positionDrawdownPct: number | null;
  killSwitchActive: boolean;
  killSwitchFiredAt: string | null;
}): Promise<void> {
  const { error } = await sb.from("regime_state").upsert({
    date: p.date,
    spy_close: p.spyClose,
    spy_sma200: p.spySma200,
    target_state: p.targetState,
    current_state: p.currentState,
    position_drawdown_pct: p.positionDrawdownPct,
    kill_switch_active: p.killSwitchActive,
    kill_switch_fired_at: p.killSwitchFiredAt,
  }, { onConflict: "date" });
  if (error) throw new Error(`upsertRegimeState: ${error.message}`);
}

export async function getLatestRegimeState(
  sb: SupabaseClient,
): Promise<RegimeStateRow | null> {
  const { data, error } = await sb
    .from("regime_state")
    .select("*")
    .order("date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getLatestRegimeState: ${error.message}`);
  return data ? coerceRegimeRow(data as Record<string, unknown>) : null;
}

export async function insertTrade(sb: SupabaseClient, p: {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  fillPrice: number;
  fillTime: string;
  brokerOrderId: string;
  reason: "regime_flip_long" | "regime_flip_cash" | "kill_switch" | "panic_cli";
}): Promise<number> {
  const { data, error } = await sb.from("trades").insert({
    symbol: p.symbol,
    side: p.side,
    qty: p.qty,
    fill_price: p.fillPrice,
    fill_time: p.fillTime,
    broker_order_id: p.brokerOrderId,
    reason: p.reason,
  }).select("id").single();
  if (error) throw new Error(`insertTrade: ${error.message}`);
  return (data as { id: number }).id;
}

export async function insertAuditLog(sb: SupabaseClient, p: {
  scriptName: string;
  startedAt: string;
}): Promise<number> {
  const { data, error } = await sb.from("audit_log").insert({
    script_name: p.scriptName,
    started_at: p.startedAt,
  }).select("id").single();
  if (error) throw new Error(`insertAuditLog: ${error.message}`);
  return (data as { id: number }).id;
}

export async function updateAuditLog(sb: SupabaseClient, p: {
  id: number;
  finishedAt: string;
  outcome: string;
  notes?: string | null;
}): Promise<void> {
  const { error } = await sb.from("audit_log").update({
    finished_at: p.finishedAt,
    outcome: p.outcome,
    notes: p.notes ?? null,
  }).eq("id", p.id);
  if (error) throw new Error(`updateAuditLog: ${error.message}`);
}

// ---------------------------------------------------------------------------
// Read-only helpers for the status Edge Function (#354 T3). Both SELECT-only —
// no insert/update/upsert — mirroring getLatestRegimeState's shape.
// ---------------------------------------------------------------------------

export interface TradeRow {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  fill_price: number;
  fill_time: string;
  reason: string;
  broker_order_id: string;
}

// PostgREST returns `numeric` columns as JSON strings to preserve precision
// (same reason as coerceRegimeRow above). Shared by getLastTrade and the
// #358 T4 getTradesSince window helper so both map rows identically.
export function coerceTradeRow(raw: Record<string, unknown>): TradeRow {
  return {
    symbol: raw.symbol as string,
    side: raw.side as "BUY" | "SELL",
    qty: requireNumber(raw.qty, "qty"),
    fill_price: requireNumber(raw.fill_price, "fill_price"),
    fill_time: raw.fill_time as string,
    reason: raw.reason as string,
    broker_order_id: raw.broker_order_id as string,
  };
}

export async function getLastTrade(sb: SupabaseClient): Promise<TradeRow | null> {
  const { data, error } = await sb
    .from("trades")
    .select("symbol, side, qty, fill_price, fill_time, reason, broker_order_id")
    .order("fill_time", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getLastTrade: ${error.message}`);
  return data ? coerceTradeRow(data as Record<string, unknown>) : null;
}

// #358 T4: windowed read for the status digest's `?days=N` extended mode.
// SELECT-only, same shape as getLastTrade. .limit(1000) is a defensive cap,
// not a pagination need: a <=1-trade/day bot cannot plausibly produce more
// than 1000 fills in a 60-day window (the widest allowed `days`).
export async function getTradesSince(sb: SupabaseClient, sinceIso: string): Promise<TradeRow[]> {
  const { data, error } = await sb
    .from("trades")
    .select("symbol, side, qty, fill_price, fill_time, reason, broker_order_id")
    .gte("fill_time", sinceIso)
    .order("fill_time", { ascending: false })
    .limit(1000);
  if (error) throw new Error(`getTradesSince: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceTradeRow);
}

// #358 T4: windowed read for the status digest's `?days=N` extended mode.
// SELECT-only. .limit(1000) is a defensive cap: one row per trading day
// means a 60-day window cannot plausibly exceed it.
export async function getRegimeStatesSince(
  sb: SupabaseClient,
  sinceDate: string,
): Promise<RegimeStateRow[]> {
  const { data, error } = await sb
    .from("regime_state")
    .select("*")
    .gte("date", sinceDate)
    .order("date", { ascending: false })
    .limit(1000);
  if (error) throw new Error(`getRegimeStatesSince: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceRegimeRow);
}

export interface AuditLogRow {
  script_name: string;
  started_at: string;
  finished_at: string | null;
  outcome: string | null;
  notes: string | null;
}

// PostgREST's default max_rows is 1000 per request, so a window that holds
// more than 1000 audit rows (#358: any `?days=N` window past ~2 days at
// current volume) silently truncates on a single `.limit()` call. This loop
// pages through with `.range()` instead, taking a **closed window**
// [sinceIso, untilIso] (D2): `untilIso` is snapshotted by the caller from
// deps.now() before the loop starts, and audit rows are append-only, so a row
// inserted mid-pagination has started_at > untilIso and can never shift an
// offset between pages — pagination is stable without a stronger DB-side
// snapshot mechanism. Order stays `started_at desc`; page size 1000; the loop
// ends on a short (< page size) page. Hard cap of 10 pages (10,000 rows): the
// worst realistic window (days=60, ~4,700 rows at current volume) is ~5
// pages, so the cap has 2x headroom and exists only to bound a runaway loop —
// breaching it throws (surfaced as the existing JSON 500 path) rather than
// silently returning a truncated count.
const AUDIT_PAGE_SIZE = 1000;
const AUDIT_MAX_PAGES = 10;

export async function getAuditLogSince(
  sb: SupabaseClient,
  sinceIso: string,
  untilIso: string,
): Promise<AuditLogRow[]> {
  const rows: AuditLogRow[] = [];
  for (let page = 0; page < AUDIT_MAX_PAGES; page++) {
    const from = page * AUDIT_PAGE_SIZE;
    const to = from + AUDIT_PAGE_SIZE - 1;
    const { data, error } = await sb
      .from("audit_log")
      .select("script_name, started_at, finished_at, outcome, notes")
      .gte("started_at", sinceIso)
      .lte("started_at", untilIso)
      .order("started_at", { ascending: false })
      .range(from, to);
    if (error) throw new Error(`getAuditLogSince: ${error.message}`);
    const pageRows = (data ?? []) as AuditLogRow[];
    rows.push(...pageRows);
    if (pageRows.length < AUDIT_PAGE_SIZE) {
      return rows;
    }
  }
  throw new Error(
    `getAuditLogSince: exceeded ${AUDIT_MAX_PAGES * AUDIT_PAGE_SIZE}-row page cap ` +
      `(${sinceIso} .. ${untilIso})`,
  );
}

export async function getConfig(sb: SupabaseClient, key: string): Promise<string | null> {
  const { data, error } = await sb.from("bot_config").select("value").eq("key", key).maybeSingle();
  if (error) throw new Error(`getConfig: ${error.message}`);
  return (data as { value: string } | null)?.value ?? null;
}

export async function setConfig(sb: SupabaseClient, key: string, value: string): Promise<void> {
  const { error } = await sb.from("bot_config").upsert(
    { key, value, updated_at: new Date().toISOString() },
    { onConflict: "key" },
  );
  if (error) throw new Error(`setConfig: ${error.message}`);
}

// ---------------------------------------------------------------------------
// #383 T2: equity_snapshots — one row per trading day, written by daily-check
// from the existing alpaca.getAccountValue() read-only helper (D1), read by
// status to compute trailing returns. Same coerce/upsert shape as
// coerceRegimeRow/upsertRegimeState.
// ---------------------------------------------------------------------------

export interface EquitySnapshotRow {
  date: string;
  equity_usd: number;
  created_at?: string;
}

// PostgREST returns `numeric` columns as JSON strings to preserve precision
// (same reason as coerceRegimeRow/coerceTradeRow above).
export function coerceEquitySnapshotRow(raw: Record<string, unknown>): EquitySnapshotRow {
  return {
    date: raw.date as string,
    equity_usd: requireNumber(raw.equity_usd, "equity_usd"),
    created_at: raw.created_at as string | undefined,
  };
}

export async function upsertEquitySnapshot(sb: SupabaseClient, p: {
  date: string;
  equityUsd: number;
}): Promise<void> {
  const { error } = await sb.from("equity_snapshots").upsert({
    date: p.date,
    equity_usd: p.equityUsd,
  }, { onConflict: "date" });
  if (error) throw new Error(`upsertEquitySnapshot: ${error.message}`);
}

export async function getEarliestEquitySnapshot(
  sb: SupabaseClient,
): Promise<EquitySnapshotRow | null> {
  const { data, error } = await sb
    .from("equity_snapshots")
    .select("*")
    .order("date", { ascending: true })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getEarliestEquitySnapshot: ${error.message}`);
  return data ? coerceEquitySnapshotRow(data as Record<string, unknown>) : null;
}

export async function getLatestEquitySnapshot(
  sb: SupabaseClient,
): Promise<EquitySnapshotRow | null> {
  const { data, error } = await sb
    .from("equity_snapshots")
    .select("*")
    .order("date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getLatestEquitySnapshot: ${error.message}`);
  return data ? coerceEquitySnapshotRow(data as Record<string, unknown>) : null;
}

// Windowed read for status's trailing-return computation. .limit(60) is a
// defensive cap: one row per trading day means even the widest allowed
// `?days=60` window cannot plausibly exceed it.
export async function getEquitySnapshotsSince(
  sb: SupabaseClient,
  sinceDate: string,
): Promise<EquitySnapshotRow[]> {
  const { data, error } = await sb
    .from("equity_snapshots")
    .select("*")
    .gte("date", sinceDate)
    .order("date", { ascending: true })
    .limit(60);
  if (error) throw new Error(`getEquitySnapshotsSince: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceEquitySnapshotRow);
}

// ---------------------------------------------------------------------------
// #397 T2: notification_outbox — durable retry queue for notifications.ts
// posts that come back "failed" (see outbox.ts's notifyDurable/flushOutbox).
// Throw-on-error, same convention as every other helper in this file; the
// never-throw guarantee for the notification path lives one layer up in
// outbox.ts, not here.
// ---------------------------------------------------------------------------

export interface OutboxRow {
  id: number;
  event_type: string;
  event: Record<string, unknown>;
  attempts: number;
  last_attempt_at: string | null;
  created_at: string;
}

export async function enqueueNotification(sb: SupabaseClient, p: {
  eventType: string;
  event: Record<string, unknown>;
}): Promise<void> {
  const { error } = await sb.from("notification_outbox").insert({
    event_type: p.eventType,
    event: p.event,
  });
  if (error) throw new Error(`enqueueNotification: ${error.message}`);
}

// Oldest first, so TTL-expired rows are naturally processed (and dropped)
// before fresher ones within a batch.
export async function getPendingNotifications(
  sb: SupabaseClient,
  limit: number,
): Promise<OutboxRow[]> {
  const { data, error } = await sb
    .from("notification_outbox")
    .select("*")
    .order("created_at", { ascending: true })
    .limit(limit);
  if (error) throw new Error(`getPendingNotifications: ${error.message}`);
  return (data ?? []) as OutboxRow[];
}

export async function deleteNotifications(sb: SupabaseClient, ids: number[]): Promise<void> {
  const { error } = await sb.from("notification_outbox").delete().in("id", ids);
  if (error) throw new Error(`deleteNotifications: ${error.message}`);
}

// Caller passes attempts = row.attempts + 1. Two concurrent flushers can lose
// an increment or double-send a row — benign for alerts (at-least-once is the
// documented delivery semantic), and deliberately unlocked: notifications are
// not orders, so there is no trade_claims analog here.
export async function markNotificationAttempt(
  sb: SupabaseClient,
  id: number,
  attempts: number,
): Promise<void> {
  const { error } = await sb.from("notification_outbox").update({
    attempts,
    last_attempt_at: new Date().toISOString(),
  }).eq("id", id);
  if (error) throw new Error(`markNotificationAttempt: ${error.message}`);
}

// Per-trading-day concurrency guard (#293). Attempts to INSERT a claim row
// for (scriptName, tradeDate). Returns:
//   true  — claim succeeded; this invocation may proceed to place an order
//   false — unique-violation (Postgres 23505); another invocation already
//            claimed this date; caller must skip the order
// Any other error is re-thrown so the caller can surface it as error:*
// rather than silently swallowing a DB failure as a false skipped:duplicate.
export async function claimTradeDate(
  sb: SupabaseClient,
  scriptName: string,
  tradeDate: string,
): Promise<boolean> {
  const { error } = await sb.from("trade_claims").insert({
    script_name: scriptName,
    trade_date: tradeDate,
  });
  if (!error) return true;
  if (error.code === "23505") return false;
  throw new Error(`claimTradeDate: ${error.message}`);
}
