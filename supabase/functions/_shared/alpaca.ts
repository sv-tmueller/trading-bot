// Alpaca Trading REST v2 client. Mirrors tools/ibkr_broker.py: mutating methods
// call the guard first so a forgotten mock fails fast instead of placing a live
// order (spec §5, ported #168). Read-only methods are unguarded but cannot place
// an order.
import { getAlpacaConfig, isClaudeAgentNoBroker } from "./config.ts";
import { requireNumber } from "./num.ts";

// Set .name so the deterministic `error:${err.name}` audit outcomes distinguish
// broker errors (e.g. error:AlpacaError) instead of collapsing to error:Error.
export class BrokerCallBlockedError extends Error {
  override name = "BrokerCallBlockedError";
}
export class AlpacaError extends Error {
  override name = "AlpacaError";
}
// Extends AlpacaError (#342) so both cron callers' existing
// `instanceof AlpacaError -> notifyBrokerError` catches surface a timed-out
// order (including an UNVERIFIED cancel, #262) with zero caller changes.
export class OrderTimeoutError extends AlpacaError {
  override name = "OrderTimeoutError";
}
// Terminal non-fill (rejected/canceled/expired) detected while polling (#267).
// Carries Alpaca's order status, plus its reason in the message when present.
export class OrderRejectedError extends Error {
  override name = "OrderRejectedError";
  readonly status: string;
  constructor(message: string, status: string) {
    super(message);
    this.status = status;
  }
}

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
  /** US trading-session dates (YYYY-MM-DD) in [start, end], oldest-first. */
  getCalendar(start: string, end: string): Promise<string[]>;
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
      throw new AlpacaError(
        `${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`,
      );
    }
    return await res.json();
  }

  async function getClock() {
    const j = await tradeJson("/v2/clock");
    return { isOpen: Boolean(j.is_open) };
  }

  async function getCalendar(start: string, end: string): Promise<string[]> {
    const res = await trade(`/v2/calendar?start=${start}&end=${end}`);
    if (!res.ok) {
      throw new AlpacaError(`GET calendar -> ${res.status}: ${await res.text()}`);
    }
    const arr = await res.json();
    if (!Array.isArray(arr)) {
      throw new AlpacaError("GET calendar -> unexpected non-array body");
    }
    return arr.map((e) => String((e as { date: unknown }).date));
  }

  async function getAccountValue() {
    const j = await tradeJson("/v2/account");
    return requireNumber(j.equity, "account equity");
  }

  async function getPosition(symbol: string): Promise<number> {
    const res = await trade(`/v2/positions/${encodeURIComponent(symbol)}`);
    if (res.status === 404) return 0;
    if (!res.ok) {
      throw new AlpacaError(`GET position ${symbol} -> ${res.status}: ${await res.text()}`);
    }
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

    // Extracts a Fill from an order body when any shares actually filled
    // (full or partial); null otherwise. Partial fills must reach the caller
    // so the trades table records the shares really owned (#267).
    const partialOrFullFill = (o: Record<string, unknown>): Fill | null => {
      const raw = o.filled_qty;
      const qty = raw === null || raw === undefined || raw === "" ? 0 : Math.trunc(Number(raw));
      if (!Number.isFinite(qty) || qty <= 0) return null;
      return {
        orderId,
        fillPrice: requireNumber(o.filled_avg_price, "filled_avg_price"),
        qty,
        // filled_at is only set on a full fill; fall back for partials.
        fillTime: String(o.filled_at ?? o.updated_at ?? new Date().toISOString()),
      };
    };

    const TERMINAL_NON_FILL = ["rejected", "canceled", "expired"];

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
      if (TERMINAL_NON_FILL.includes(String(o.status))) {
        // Terminal without a full fill: break immediately (#267) — no point
        // spinning out the timeout. A partial fill (e.g. canceled after a
        // partial execution) is still returned so the caller records it.
        const partial = partialOrFullFill(o);
        if (partial) return partial;
        const reason = o.reject_reason ? `: ${o.reject_reason}` : "";
        throw new OrderRejectedError(
          `${args.side} ${args.qty} ${args.symbol} order ${orderId} ` +
            `terminal status '${o.status}'${reason}`,
          String(o.status),
        );
      }
      await sleep(intervalMs);
      waited += intervalMs;
    }
    // Timed out — best-effort cancel, then re-check once: the order can fill
    // (fully or partially) in the race window between the last poll and the
    // cancel, and those shares must be reported, not swallowed (#267). The
    // post-cancel status also VERIFIES the cancel actually landed (#262/#342):
    // a terminal non-fill status confirms the order is dead, but anything
    // still live — or a failed status check — must alert the operator that
    // the order may still be resting at the broker.
    try {
      await trade(`/v2/orders/${orderId}`, { method: "DELETE" });
    } catch (_e) { /* best effort — fetch-level failure only */ }
    try {
      const final = await tradeJson(`/v2/orders/${orderId}`);
      const fill = partialOrFullFill(final);
      if (fill) return fill;
      if (TERMINAL_NON_FILL.includes(String(final.status))) {
        // Cancel verified: the order is confirmed dead. `rejected` counts as
        // verified too — the order cannot be live, which is the property
        // being verified.
        throw new OrderTimeoutError(
          `${args.side} ${args.qty} ${args.symbol} did not fill within ${timeoutMs}ms; ` +
            `cancelled (verified: status '${final.status}')`,
        );
      }
      // Still live (e.g. pending_cancel) — an immediate re-poll can legitimately
      // race the broker's own cancel processing, so this is classified
      // UNVERIFIED rather than assumed cancelled.
      throw new OrderTimeoutError(
        `${args.side} ${args.qty} ${args.symbol} did not fill within ${timeoutMs}ms; ` +
          `cancel UNVERIFIED — order ${orderId} may still be live (status '${final.status}')`,
      );
    } catch (e) {
      if (e instanceof OrderTimeoutError) throw e;
      throw new OrderTimeoutError(
        `${args.side} ${args.qty} ${args.symbol} did not fill within ${timeoutMs}ms; ` +
          `cancel UNVERIFIED — order ${orderId} may still be live ` +
          `(post-cancel status check failed: ${(e as Error).message})`,
      );
    }
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
    const cancelled = arr.filter((e) => Number((e as { status?: number }).status) === 200).length;
    const failed = arr.length - cancelled;
    if (failed > 0) {
      // Don't report a partial cancel as success — surface it so the panic
      // operator sees a 500 instead of "cancelled N orders".
      throw new AlpacaError(
        `cancel-all: ${cancelled} cancelled, ${failed} failed of ${arr.length}`,
      );
    }
    return cancelled;
  }

  return {
    getClock,
    getCalendar,
    getAccountValue,
    getPosition,
    placeMarketOrder,
    liquidate,
    cancelAllOrders,
  };
}
