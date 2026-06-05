// Supabase persistence. Mirrors tools/database.py. Each function takes the
// Supabase client so callers (Edge Functions) inject the service-role client.
import type { SupabaseClient } from "@supabase/supabase-js";

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
  return (data as RegimeStateRow) ?? null;
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
