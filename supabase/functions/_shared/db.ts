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

// #475 T7: widened to include the five hourly-check reasons (0012 migration's
// trades.reason check extension). Existing callers (daily-check, kill-switch)
// pass their own narrower literal unions, which remain assignable here.
export async function insertTrade(sb: SupabaseClient, p: {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  fillPrice: number;
  fillTime: string;
  brokerOrderId: string;
  reason:
    | "regime_flip_long"
    | "regime_flip_cash"
    | "kill_switch"
    | "panic_cli"
    | "hourly_long_entry"
    | "hourly_short_entry"
    | "hourly_bracket_exit"
    | "hourly_session_close_exit"
    | "hourly_kill_switch";
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

// #546: day-scoped [sinceIso, untilIso] read for the status digest's
// `verification.trades` block, unfiltered by reason. Ascending by fill_time
// (lead decision on #545 -- the other two arrays in the block are ascending;
// a mixed convention inside one block is a trap for the consumer). Same
// defensive .limit(1000) cap as getTradesSince: a single trading day cannot
// plausibly produce anywhere near that many fills.
export async function getTradesInWindow(
  sb: SupabaseClient,
  sinceIso: string,
  untilIso: string,
): Promise<TradeRow[]> {
  const { data, error } = await sb
    .from("trades")
    .select("symbol, side, qty, fill_price, fill_time, reason, broker_order_id")
    .gte("fill_time", sinceIso)
    .lte("fill_time", untilIso)
    .order("fill_time", { ascending: true })
    .limit(1000);
  if (error) throw new Error(`getTradesInWindow: ${error.message}`);
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

// #396 T1: latest audit_log row for a single script, used by the status
// digest's `last_runs` field (consumed by the dead-man watchdog,
// scripts/deadman_check.ts). SELECT-only, same shape as getLatestRegimeState.
export async function getLatestAuditForScript(
  sb: SupabaseClient,
  scriptName: string,
): Promise<AuditLogRow | null> {
  const { data, error } = await sb
    .from("audit_log")
    .select("script_name, started_at, finished_at, outcome, notes")
    .eq("script_name", scriptName)
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getLatestAuditForScript: ${error.message}`);
  return data as AuditLogRow | null;
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

// ---------------------------------------------------------------------------
// #475 T7: hourly_scans (0012 migration) -- one row per scan, including skips.
// ---------------------------------------------------------------------------

export interface HourlyScanRow {
  symbol: string;
  bar_ts: string;
  decision: "LONG" | "SHORT" | "SKIP";
  skip_reason: string | null;
  detectors_fired: string[];
  context_mode: string;
  entry_ref_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  risk_per_share: number | null;
  equity_usd: number;
  qty: number;
  entry_order_id: string | null;
  created_at?: string;
}

// PostgREST returns `numeric` columns as JSON strings to preserve precision
// (same reason as coerceRegimeRow/coerceTradeRow/coerceEquitySnapshotRow).
export function coerceHourlyScanRow(raw: Record<string, unknown>): HourlyScanRow {
  const num = (v: unknown, field: string): number | null =>
    v == null ? null : requireNumber(v, field);
  return {
    symbol: raw.symbol as string,
    bar_ts: raw.bar_ts as string,
    decision: raw.decision as "LONG" | "SHORT" | "SKIP",
    skip_reason: (raw.skip_reason as string | null) ?? null,
    detectors_fired: (raw.detectors_fired as string[] | null) ?? [],
    context_mode: raw.context_mode as string,
    entry_ref_price: num(raw.entry_ref_price, "entry_ref_price"),
    stop_price: num(raw.stop_price, "stop_price"),
    target_price: num(raw.target_price, "target_price"),
    risk_per_share: num(raw.risk_per_share, "risk_per_share"),
    equity_usd: requireNumber(raw.equity_usd, "equity_usd"),
    qty: requireNumber(raw.qty, "qty"),
    entry_order_id: (raw.entry_order_id as string | null) ?? null,
    created_at: raw.created_at as string | undefined,
  };
}

export interface HourlyScanUpsert {
  symbol: string;
  barTs: string;
  decision: "LONG" | "SHORT" | "SKIP";
  skipReason: string | null;
  detectorsFired: string[];
  contextMode: string;
  entryRefPrice: number | null;
  stopPrice: number | null;
  targetPrice: number | null;
  riskPerShare: number | null;
  equityUsd: number;
  qty: number;
  entryOrderId: string | null;
}

/**
 * #487 review finding 2: the SKIP-journal payload, narrowed so the
 * "SKIP only" contract of upsertHourlyScanUnlessEntered is enforced by the
 * type system rather than by a comment. A LONG/SHORT payload would invert
 * that helper's semantics (see its doc comment), and nothing but this type
 * stops a future third caller from passing one.
 */
export type HourlyScanSkipUpsert = Omit<HourlyScanUpsert, "decision"> & { decision: "SKIP" };

function hourlyScanColumns(p: HourlyScanUpsert): Record<string, unknown> {
  return {
    symbol: p.symbol,
    bar_ts: p.barTs,
    decision: p.decision,
    skip_reason: p.skipReason,
    detectors_fired: p.detectorsFired,
    context_mode: p.contextMode,
    entry_ref_price: p.entryRefPrice,
    stop_price: p.stopPrice,
    target_price: p.targetPrice,
    risk_per_share: p.riskPerShare,
    equity_usd: p.equityUsd,
    qty: p.qty,
    entry_order_id: p.entryOrderId,
  };
}

// Upsert on (symbol, bar_ts): a re-run on the same bar replaces the row
// idempotently, same regime_state date-PK + onConflict pattern.
export async function upsertHourlyScan(sb: SupabaseClient, p: HourlyScanUpsert): Promise<void> {
  const { error } = await sb.from("hourly_scans").upsert(hourlyScanColumns(p), {
    onConflict: "symbol,bar_ts",
  });
  if (error) throw new Error(`upsertHourlyScan: ${error.message}`);
}

/**
 * #487: the same upsert, but it refuses to downgrade a row that already
 * records a LONG/SHORT decision. Every SKIP journal in hourly-check's
 * pipeline lands BEFORE claimBar, so the bar-level claim cannot protect the
 * row: a re-scan whose candidate is the same bar (a lagging feed at the next
 * cron slot, or a duplicate invocation stopped at the position-open gate)
 * would otherwise overwrite decision + entry_order_id and destroy the
 * provenance the #480 recovery step searches for. The clobbered row does not
 * even look orphaned afterwards, so #486's report cannot recover it either.
 *
 * Two statements, each atomic on its own, so this is race-free without a
 * migration (a read-then-write in logic.ts would still lose the window where
 * a concurrent invocation journals its pre-order LONG in between):
 *
 *   1. ON CONFLICT DO NOTHING insert (`ignoreDuplicates`), which returns the
 *      row only when it actually inserted;
 *   2. only if step 1 inserted nothing, an UPDATE filtered on
 *      `decision = 'SKIP'` -- the guard. A LONG/SHORT row matches nothing.
 *
 * Returns true when the SKIP row was written (either statement), false when
 * an entered row was preserved. The payload is SKIP-only by type
 * (HourlyScanSkipUpsert): `decision` is what the caller wants STORED, while
 * the guard reads the row's CURRENT decision, so a LONG payload here would
 * preserve a stored LONG instead of stamping it. Entry rows go through
 * upsertHourlyScan.
 */
export async function upsertHourlyScanUnlessEntered(
  sb: SupabaseClient,
  p: HourlyScanSkipUpsert,
): Promise<boolean> {
  const row = hourlyScanColumns(p);
  const inserted = await sb
    .from("hourly_scans")
    .upsert(row, { onConflict: "symbol,bar_ts", ignoreDuplicates: true })
    .select("bar_ts");
  if (inserted.error) {
    throw new Error(`upsertHourlyScanUnlessEntered: ${inserted.error.message}`);
  }
  if ((inserted.data ?? []).length > 0) return true;

  const updated = await sb
    .from("hourly_scans")
    .update(row)
    .eq("symbol", p.symbol)
    .eq("bar_ts", p.barTs)
    .eq("decision", "SKIP")
    .select("bar_ts");
  if (updated.error) {
    throw new Error(`upsertHourlyScanUnlessEntered: ${updated.error.message}`);
  }
  // Zero rows updated conflates two causes: the stored decision is LONG/SHORT
  // (the case this exists for), or the row vanished between the two statements
  // (nothing deletes hourly_scans, so unreachable in production). The caller's
  // warn text names only the first. Row integrity does not depend on telling
  // them apart -- neither statement can overwrite a LONG/SHORT -- so this
  // affects the return value's precision only.
  return (updated.data ?? []).length > 0;
}

// #475 T11: the `trades` table has no bar_ts column (§9 keeps bar_ts scoped
// to hourly_scans), so the naked-position provenance lookup (spec §7 finding
// 3, "keyed on the entry's bar_ts") is instead keyed on the entry's broker
// order id -- entry_order_id and (symbol, bar_ts) both uniquely identify the
// scan row that produced an open position's entry once the order is placed.
export async function getHourlyScanByEntryOrderId(
  sb: SupabaseClient,
  symbol: string,
  entryOrderId: string,
): Promise<HourlyScanRow | null> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("*")
    .eq("symbol", symbol)
    .eq("entry_order_id", entryOrderId)
    .order("bar_ts", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getHourlyScanByEntryOrderId: ${error.message}`);
  return data ? coerceHourlyScanRow(data as Record<string, unknown>) : null;
}

// #536 T1: getLatestHourlyScan / getHourlyScansSince -- read-only helpers for
// the status digest's `hourly` block (status/logic.ts). SELECT-only, no
// symbol filter -- same one-bot-one-symbol assumption already documented in
// scripts/render_weekly_journal.ts.
export async function getLatestHourlyScan(sb: SupabaseClient): Promise<HourlyScanRow | null> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("*")
    .order("bar_ts", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(`getLatestHourlyScan: ${error.message}`);
  return data ? coerceHourlyScanRow(data as Record<string, unknown>) : null;
}

// Windowed read for the status digest's bar-level skip-reason distribution,
// mirroring getTradesSince's shape and defensive cap: an hourly-cadence bot
// scanning only during market hours cannot plausibly produce more than 1000
// rows even across the widest 60-day window this digest supports.
export async function getHourlyScansSince(
  sb: SupabaseClient,
  sinceIso: string,
): Promise<HourlyScanRow[]> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("*")
    .gte("bar_ts", sinceIso)
    .order("bar_ts", { ascending: false })
    .limit(1000);
  if (error) throw new Error(`getHourlyScansSince: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceHourlyScanRow);
}

// #546: day-scoped [sinceIso, untilIso] read for the status digest's
// `verification.scans` block. **Ascending** by bar_ts, unlike the descending
// getHourlyScansSince above -- the evaluator reads a day's scans in
// chronological order. Same defensive .limit(1000) cap: a single trading
// day's scan volume cannot plausibly approach it.
export async function getHourlyScansInWindow(
  sb: SupabaseClient,
  sinceIso: string,
  untilIso: string,
): Promise<HourlyScanRow[]> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("*")
    .gte("bar_ts", sinceIso)
    .lte("bar_ts", untilIso)
    .order("bar_ts", { ascending: true })
    .limit(1000);
  if (error) throw new Error(`getHourlyScansInWindow: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceHourlyScanRow);
}

// #480 T2: pending-entry scan lookup, consumed by logic.ts reconcile()'s
// recovery step. `decision IN ('LONG','SHORT') AND entry_order_id IS NULL` is
// the exact signature the pre-order journal (logic.ts step 20) leaves behind
// when every post-fill write group then exhausts its retries (T1) -- the
// #480 failure window. Round-1 finding 9 (PR #477) removed the dead
// getHourlyScanByBar helper (a bar-oriented read with no consumer); this one
// deliberately reintroduces a bar-oriented read because it has a wired
// consumer. .limit(50) is a defensive cap: the 5-day reconcile lookback at
// hourly cadence cannot plausibly produce anywhere near that many pending
// rows without the recovery step itself having long since caught up.
export async function getHourlyScansPendingEntry(
  sb: SupabaseClient,
  symbol: string,
  sinceIso: string,
): Promise<HourlyScanRow[]> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("*")
    .eq("symbol", symbol)
    .in("decision", ["LONG", "SHORT"])
    .is("entry_order_id", null)
    .gte("bar_ts", sinceIso)
    .order("bar_ts", { ascending: true })
    .limit(50);
  if (error) throw new Error(`getHourlyScansPendingEntry: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(coerceHourlyScanRow);
}

// #513: returns every non-null entry_order_id for `symbol` so the recovery
// step can exclude fills already claimed by another scan row. This keys
// adoption to the entry_order_id / broker_order_id relationship rather than
// a time window -- a fill is adoptable only by the scan row that produced
// it, independent of when it lands. SELECT-only, no joins: the table is small
// (one row per scan, 5-day lookback at hourly cadence << 1000 rows), so a
// single-column scan with a defensive .limit(5000) cap suffices without an
// index on entry_order_id.
export async function getHourlyScanClaimedOrderIds(
  sb: SupabaseClient,
  symbol: string,
): Promise<Set<string>> {
  const { data, error } = await sb
    .from("hourly_scans")
    .select("entry_order_id")
    .eq("symbol", symbol)
    .not("entry_order_id", "is", null);
  if (error) throw new Error(`getHourlyScanClaimedOrderIds: ${error.message}`);
  return new Set(
    ((data ?? []) as { entry_order_id: string }[])
      .map((r) => r.entry_order_id),
  );
}

// Bar-level concurrency guard (spec §8.4), mirroring claimTradeDate exactly
// but keyed on (script_name, bar_ts) instead of (script_name, trade_date) --
// an hourly bot placing multiple entries/day cannot be expressed at date
// granularity. `bar_claims` is owned by the sibling #474 package
// (short-side safety-stack retrofit, migration 0011); this function consumes
// the table without owning its schema. Returns:
//   true  — claim succeeded; this invocation may proceed to place an order
//   false — unique-violation (Postgres 23505); another invocation already
//            claimed this bar
// Any other error is re-thrown so the caller surfaces it as error:* rather
// than silently swallowing a DB failure as a false skipped:duplicate_run.
export async function claimBar(
  sb: SupabaseClient,
  scriptName: string,
  barTs: string,
): Promise<boolean> {
  const { error } = await sb.from("bar_claims").insert({
    script_name: scriptName,
    bar_ts: barTs,
  });
  if (!error) return true;
  if (error.code === "23505") return false;
  throw new Error(`claimBar: ${error.message}`);
}
