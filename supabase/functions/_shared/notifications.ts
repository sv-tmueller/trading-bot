// Direct-to-Discord webhook poster (#362 — no n8n middleman). Every event
// carries structured `event_type` + event-specific fields (kept for any
// future JSON-consuming forwarder), plus a human-readable `message`. When
// `message` is present, postEvent() also derives a Discord-native `content`
// field (Discord's incoming-webhook API renders `content` directly, and
// ignores unrecognised extra fields), codepoint-safe-truncated to 2,000
// characters — Discord's hard content limit — so a long message still posts
// instead of 400ing the whole webhook call. The full untruncated text always
// survives in `message`. NEVER throws — a notification outage must not crash
// the bot. An unset secret, a fetch rejection, or a non-2xx response are all
// logged via console.warn (visible in Supabase function logs, #366) — never
// the webhook URL or the full payload — so an outage is silent to the caller
// but visible in ops.
//
// #397: postEvent() is notify()'s former body, now returning a NotifyStatus
// instead of discarding it, so outbox.ts's notifyDurable can enqueue a
// "failed" post for retry. notify() stays a thin `Promise<void>` wrapper —
// its signature and observable behavior are UNCHANGED (see notifications.test.ts,
// every pre-#397 case still passes unmodified) because widening notify()'s own
// return type would force edits to the DailyCheckDeps/KillSwitchDeps
// notifications interfaces in both logic.ts files, which must stay untouched.
import { getNotifyWebhookUrl } from "./config.ts";

const DISCORD_CONTENT_MAX_CODEPOINTS = 2000;
const WARN_BODY_SNIPPET_MAX_CODEPOINTS = 200;

function truncateCodepoints(s: string, max: number): string {
  return [...s].slice(0, max).join("");
}

export type NotifyStatus = "sent" | "failed" | "skipped_unset";

export async function postEvent(event: Record<string, unknown>): Promise<NotifyStatus> {
  const url = getNotifyWebhookUrl();
  const eventType = String(event.event_type ?? "unknown");
  if (url === "") {
    console.warn(`notify: skipped (NOTIFY_WEBHOOK_URL unset), event_type=${eventType}`);
    return "skipped_unset";
  }
  const message = event.message;
  const body = typeof message === "string" && message !== ""
    ? { ...event, content: truncateCodepoints(message, DISCORD_CONTENT_MAX_CODEPOINTS) }
    : event;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      // Redact the FULL untruncated text first, then truncate — the reverse
      // order would leave an un-redacted prefix of the URL (including part of
      // any secret token) in the snippet whenever the URL straddles the cut.
      const snippet = truncateCodepoints(
        text.replaceAll(url, "[webhook-url]"),
        WARN_BODY_SNIPPET_MAX_CODEPOINTS,
      );
      console.warn(
        `notify: webhook responded ${res.status}: ${snippet}, event_type=${eventType}`,
      );
      return "failed";
    }
    return "sent";
  } catch (e) {
    const name = e instanceof Error ? e.name : "Error";
    const msg = String(e instanceof Error ? e.message : e).replaceAll(url, "[webhook-url]");
    console.warn(`notify: webhook POST failed: ${name}: ${msg}, event_type=${eventType}`);
    return "failed";
  }
}

export async function notify(event: Record<string, unknown>): Promise<void> {
  await postEvent(event);
}

export function regimeFlipEvent(p: {
  targetState: "LONG" | "CASH";
  spyClose: number;
  spySma200: number;
  ticker: string;
  fillPrice: number;
  qty: number;
  accountValue: number;
  dryRun?: boolean;
}): Record<string, unknown> {
  const titlePrefix = p.dryRun ? "[DRY-RUN] " : "";
  const message = `${titlePrefix}Regime flip -> ${p.targetState}: ${p.ticker} qty=${p.qty} ` +
    `@ $${p.fillPrice.toFixed(2)} (SPY $${p.spyClose.toFixed(2)} vs 200-DMA $${
      p.spySma200.toFixed(2)
    })`;
  return {
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
  };
}

export function notifyRegimeFlip(p: Parameters<typeof regimeFlipEvent>[0]): Promise<void> {
  return notify(regimeFlipEvent(p));
}

// #474 T4 (spec §8.1): side-aware -- refPrice is side-neutral (the rolling
// high for a LONG fire, the rolling low for a SHORT fire) so the same event
// shape covers the kill-switch's short mirror. side names which close verb
// fired (SELL closes a long, BUY covers a short).
export function killSwitchFiredEvent(p: {
  ticker: string;
  side: "LONG" | "SHORT";
  drawdownPct: number;
  refPrice: number;
  lastPrice: number;
  qty: number;
  fillPrice: number;
}): Record<string, unknown> {
  const closeVerb = p.side === "LONG" ? "SELL" : "BUY";
  const refLabel = p.side === "LONG" ? "ref high" : "ref low";
  const message =
    `Kill switch fired on ${p.ticker} (${p.side}): drawdown ${(p.drawdownPct * 100).toFixed(1)}% ` +
    `(${refLabel} $${p.refPrice.toFixed(2)}, last $${p.lastPrice.toFixed(2)}), ` +
    `${closeVerb} qty=${p.qty} @ $${p.fillPrice.toFixed(2)}`;
  return {
    event_type: "kill_switch_fired",
    message,
    ticker: p.ticker,
    side: p.side,
    drawdown_pct: p.drawdownPct,
    ref_price: p.refPrice,
    last_price: p.lastPrice,
    qty: p.qty,
    fill_price: p.fillPrice,
  };
}

export function notifyKillSwitchFired(
  p: Parameters<typeof killSwitchFiredEvent>[0],
): Promise<void> {
  return notify(killSwitchFiredEvent(p));
}

export function tradeFailedEvent(p: {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  reason: string;
}): Record<string, unknown> {
  const message = `Trade failed: ${p.side} ${p.qty} ${p.symbol} -- ${p.reason}`;
  return {
    event_type: "trade_failed",
    message,
    symbol: p.symbol,
    side: p.side,
    qty: p.qty,
    reason: p.reason,
  };
}

export function notifyTradeFailed(p: Parameters<typeof tradeFailedEvent>[0]): Promise<void> {
  return notify(tradeFailedEvent(p));
}

export function stateDesyncEvent(p: {
  dbState: "LONG" | "CASH";
  brokerState: "LONG" | "CASH";
  symbol: string;
  actionTaken: string;
}): Record<string, unknown> {
  const message =
    `State desync on ${p.symbol}: DB=${p.dbState}, broker=${p.brokerState}. ${p.actionTaken}`;
  return {
    event_type: "state_desync",
    message,
    db_state: p.dbState,
    broker_state: p.brokerState,
    symbol: p.symbol,
    action_taken: p.actionTaken,
  };
}

export function notifyStateDesync(p: Parameters<typeof stateDesyncEvent>[0]): Promise<void> {
  return notify(stateDesyncEvent(p));
}

// Replaces notify_tws_disconnected — Alpaca is stateless REST, so this covers
// any broker/API error (connection, 5xx, auth).
export function brokerErrorEvent(
  p: { context: string; errorMsg: string },
): Record<string, unknown> {
  const message = `Broker API error (${p.context}): ${p.errorMsg}`;
  return {
    event_type: "broker_error",
    message,
    context: p.context,
    error_msg: p.errorMsg,
  };
}

export function notifyBrokerError(p: Parameters<typeof brokerErrorEvent>[0]): Promise<void> {
  return notify(brokerErrorEvent(p));
}

export function errorEvent(message: string): Record<string, unknown> {
  return { event_type: "error", message };
}

export function notifyError(message: string): Promise<void> {
  return notify(errorEvent(message));
}

export function notifyPanic(p: { action: string; result: string }): Promise<void> {
  const message = `🛑 PANIC — ${p.action}: ${p.result}`;
  return notify({ event_type: "panic", message, action: p.action, result: p.result });
}
