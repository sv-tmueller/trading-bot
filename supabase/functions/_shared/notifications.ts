// n8n webhook poster. Mirrors tools/notifications.py: structured event_type
// payloads, and NEVER throws — a notification outage must not crash the bot.
import { getN8nWebhookUrl } from "./config.ts";

export async function notify(event: Record<string, unknown>): Promise<void> {
  const url = getN8nWebhookUrl();
  if (url === "") return;
  try {
    await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(event),
    });
  } catch (_e) {
    // swallow — outage must not crash the bot
  }
}

export function notifyRegimeFlip(p: {
  targetState: "LONG" | "CASH";
  spyClose: number;
  spySma200: number;
  ticker: string;
  fillPrice: number;
  qty: number;
  accountValue: number;
  dryRun?: boolean;
}): Promise<void> {
  return notify({
    event_type: "regime_flip",
    target_state: p.targetState,
    spy_close: p.spyClose,
    spy_sma200: p.spySma200,
    ticker: p.ticker,
    fill_price: p.fillPrice,
    qty: p.qty,
    account_value: p.accountValue,
    dry_run: p.dryRun ?? false,
  });
}

export function notifyKillSwitchFired(p: {
  ticker: string;
  drawdownPct: number;
  refHigh: number;
  lastPrice: number;
  qty: number;
  fillPrice: number;
}): Promise<void> {
  return notify({
    event_type: "kill_switch_fired",
    ticker: p.ticker,
    drawdown_pct: p.drawdownPct,
    ref_high: p.refHigh,
    last_price: p.lastPrice,
    qty: p.qty,
    fill_price: p.fillPrice,
  });
}

export function notifyTradeFailed(p: {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  reason: string;
}): Promise<void> {
  return notify({
    event_type: "trade_failed",
    symbol: p.symbol,
    side: p.side,
    qty: p.qty,
    reason: p.reason,
  });
}

export function notifyStateDesync(p: {
  dbState: "LONG" | "CASH";
  brokerState: "LONG" | "CASH";
  symbol: string;
  actionTaken: string;
}): Promise<void> {
  return notify({
    event_type: "state_desync",
    db_state: p.dbState,
    broker_state: p.brokerState,
    symbol: p.symbol,
    action_taken: p.actionTaken,
  });
}

// Replaces notify_tws_disconnected — Alpaca is stateless REST, so this covers
// any broker/API error (connection, 5xx, auth).
export function notifyBrokerError(p: { context: string; errorMsg: string }): Promise<void> {
  return notify({
    event_type: "broker_error",
    context: p.context,
    error_msg: p.errorMsg,
  });
}

export function notifyError(message: string): Promise<void> {
  return notify({ event_type: "error", message });
}

export function notifyPanic(p: { action: string; result: string }): Promise<void> {
  return notify({ event_type: "panic", action: p.action, result: p.result });
}
