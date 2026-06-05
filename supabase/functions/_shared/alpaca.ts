// Alpaca Trading REST v2 client. Mirrors tools/ibkr_broker.py: mutating methods
// call the guard first so a forgotten mock fails fast instead of placing a live
// order (spec §5, ported #168). Read-only methods are unguarded but cannot place
// an order.
import { getAlpacaConfig, isClaudeAgentNoBroker } from "./config.ts";
import { requireNumber } from "./num.ts";

export class BrokerCallBlockedError extends Error {}
export class AlpacaError extends Error {}
export class OrderTimeoutError extends Error {}

export interface Fill {
  orderId: string;
  fillPrice: number;
  qty: number;
  fillTime: string;
}

export interface PollOpts {
  timeoutMs?: number;
  intervalMs?: number;
}

export interface AlpacaClient {
  getClock(): Promise<{ isOpen: boolean }>;
  getAccountValue(): Promise<number>;
  getPosition(symbol: string): Promise<number>;
  placeMarketOrder(
    args: { symbol: string; side: "BUY" | "SELL"; qty: number },
    opts?: PollOpts,
  ): Promise<Fill>;
  liquidate(symbol: string, opts?: PollOpts): Promise<Fill | null>;
  cancelAllOrders(): Promise<number>;
}

function checkGuard(op: string): void {
  if (isClaudeAgentNoBroker()) {
    throw new BrokerCallBlockedError(
      `CLAUDE_AGENT_NO_BROKER is set; refusing to perform '${op}'. Mock the broker in tests.`,
    );
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createAlpacaClient(): AlpacaClient {
  const cfg = getAlpacaConfig();
  const headers = {
    "APCA-API-KEY-ID": cfg.apiKeyId,
    "APCA-API-SECRET-KEY": cfg.apiSecretKey,
  };

  async function trade(path: string, init?: RequestInit): Promise<Response> {
    return await fetch(`${cfg.tradingBaseUrl}${path}`, {
      ...init,
      headers: { ...headers, ...(init?.headers ?? {}) },
    });
  }

  async function tradeJson(path: string, init?: RequestInit): Promise<Record<string, unknown>> {
    const res = await trade(path, init);
    if (!res.ok) {
      throw new AlpacaError(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`);
    }
    return await res.json();
  }

  async function getClock() {
    const j = await tradeJson("/v2/clock");
    return { isOpen: Boolean(j.is_open) };
  }

  async function getAccountValue() {
    const j = await tradeJson("/v2/account");
    return requireNumber(j.equity, "account equity");
  }

  async function getPosition(symbol: string): Promise<number> {
    const res = await trade(`/v2/positions/${encodeURIComponent(symbol)}`);
    if (res.status === 404) return 0;
    if (!res.ok) throw new AlpacaError(`GET position ${symbol} -> ${res.status}: ${await res.text()}`);
    const j = await res.json();
    return Math.trunc(requireNumber(j.qty, "position qty"));
  }

  async function placeMarketOrder(
    args: { symbol: string; side: "BUY" | "SELL"; qty: number },
    opts?: PollOpts,
  ): Promise<Fill> {
    checkGuard("placeMarketOrder");
    if (args.side !== "BUY" && args.side !== "SELL") {
      throw new Error(`side must be BUY or SELL, got ${args.side}`);
    }
    if (args.qty <= 0) throw new Error(`qty must be > 0, got ${args.qty}`);

    const timeoutMs = opts?.timeoutMs ?? 30_000;
    const intervalMs = opts?.intervalMs ?? 500;

    const created = await tradeJson("/v2/orders", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        symbol: args.symbol,
        qty: String(args.qty),
        side: args.side.toLowerCase(),
        type: "market",
        time_in_force: "day",
      }),
    });
    const orderId = String(created.id);

    let waited = 0;
    while (waited < timeoutMs) {
      const o = await tradeJson(`/v2/orders/${orderId}`);
      if (o.status === "filled") {
        return {
          orderId,
          fillPrice: requireNumber(o.filled_avg_price, "filled_avg_price"),
          qty: Math.trunc(requireNumber(o.filled_qty, "filled_qty")),
          fillTime: String(o.filled_at),
        };
      }
      await sleep(intervalMs);
      waited += intervalMs;
    }
    // Timed out — best-effort cancel, then raise.
    try {
      await trade(`/v2/orders/${orderId}`, { method: "DELETE" });
    } catch (_e) { /* best effort */ }
    throw new OrderTimeoutError(
      `${args.side} ${args.qty} ${args.symbol} did not fill within ${timeoutMs}ms; cancelled`,
    );
  }

  async function liquidate(symbol: string, opts?: PollOpts): Promise<Fill | null> {
    checkGuard("liquidate");
    const qty = await getPosition(symbol);
    if (qty <= 0) return null;
    return await placeMarketOrder({ symbol, side: "SELL", qty }, opts);
  }

  async function cancelAllOrders(): Promise<number> {
    checkGuard("cancelAllOrders");
    const res = await trade("/v2/orders", { method: "DELETE" });
    if (res.status === 204) return 0;
    if (!res.ok) throw new AlpacaError(`DELETE orders -> ${res.status}: ${await res.text()}`);
    const arr = await res.json();
    if (!Array.isArray(arr)) return 0;
    return arr.filter((e) => Number((e as { status?: number }).status) === 200).length;
  }

  return { getClock, getAccountValue, getPosition, placeMarketOrder, liquidate, cancelAllOrders };
}
