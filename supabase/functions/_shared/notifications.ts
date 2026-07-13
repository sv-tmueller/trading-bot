// Direct-to-Discord webhook poster (#362 — no n8n middleman). Every event
// carries structured `event_type` + event-specific fields (kept for any
// future JSON-consuming forwarder), plus a human-readable `message`. When
// `message` is present, notify() also derives a Discord-native `content`
// field (Discord's incoming-webhook API renders `content` directly, and
// ignores unrecognised extra fields), codepoint-safe-truncated to 2,000
// characters — Discord's hard content limit — so a long message still posts
// instead of 400ing the whole webhook call. The full untruncated text always
// survives in `message`. NEVER throws — a notification outage must not crash
// the bot.
import { getNotifyWebhookUrl } from "./config.ts";

const DISCORD_CONTENT_MAX_CODEPOINTS = 2000;

export async function notify(event: Record<string, unknown>): Promise<void> {
  const url = getNotifyWebhookUrl();
  if (url === "") return;
  const message = event.message;
  const body = typeof message === "string" && message !== ""
    ? { ...event, content: [...message].slice(0, DISCORD_CONTENT_MAX_CODEPOINTS).join("") }
    : event;
  try {
    await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
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
  const titlePrefix = p.dryRun ? "[DRY-RUN] " : "";
  const message = `${titlePrefix}Regime flip -> ${p.targetState}: ${p.ticker} qty=${p.qty} ` +
    `@ $${p.fillPrice.toFixed(2)} (SPY $${p.spyClose.toFixed(2)} vs 200-DMA $${
      p.spySma200.toFixed(2)
    })`;
  return notify({
    event_type: "regime_flip",
    title: `${titlePrefix}regime_flip ${p.targetState}`,
    message,
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
  const message =
    `Kill switch fired on ${p.ticker}: drawdown ${(p.drawdownPct * 100).toFixed(1)}% ` +
    `(ref high $${p.refHigh.toFixed(2)}, last $${p.lastPrice.toFixed(2)}), ` +
    `liquidated qty=${p.qty} @ $${p.fillPrice.toFixed(2)}`;
  return notify({
    event_type: "kill_switch_fired",
    message,
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
  const message = `Trade failed: ${p.side} ${p.qty} ${p.symbol} -- ${p.reason}`;
  return notify({
    event_type: "trade_failed",
    message,
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
  const message =
    `State desync on ${p.symbol}: DB=${p.dbState}, broker=${p.brokerState}. ${p.actionTaken}`;
  return notify({
    event_type: "state_desync",
    message,
    db_state: p.dbState,
    broker_state: p.brokerState,
    symbol: p.symbol,
    action_taken: p.actionTaken,
  });
}

// Replaces notify_tws_disconnected — Alpaca is stateless REST, so this covers
// any broker/API error (connection, 5xx, auth).
export function notifyBrokerError(p: { context: string; errorMsg: string }): Promise<void> {
  const message = `Broker API error (${p.context}): ${p.errorMsg}`;
  return notify({
    event_type: "broker_error",
    message,
    context: p.context,
    error_msg: p.errorMsg,
  });
}

export function notifyError(message: string): Promise<void> {
  return notify({ event_type: "error", message });
}

export function notifyPanic(p: { action: string; result: string }): Promise<void> {
  const message = `🛑 PANIC — ${p.action}: ${p.result}`;
  return notify({ event_type: "panic", message, action: p.action, result: p.result });
}
