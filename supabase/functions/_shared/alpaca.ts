// Alpaca Trading REST v2 client. Mirrors tools/ibkr_broker.py: mutating methods
// call the guard first so a forgotten mock fails fast instead of placing a live
// order (spec §5, ported #168). Read-only methods are unguarded but cannot place
// an order.
import { type AlpacaConfig, getAlpacaConfig, isClaudeAgentNoBroker } from "./config.ts";
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
// #475 T5 (spec §8.3): thrown by the paper-only guard's Layers A/B. .name is
// "PaperGuardFailed" (not the class name) so the audit outcome is exactly
// §9's error:PaperGuardFailed.
export class PaperGuardFailedError extends Error {
  override name = "PaperGuardFailed";
}
// #494: an order leg price Alpaca cannot accept (rationale: roundToCents in
// num.ts). Extends AlpacaError, like OrderTimeoutError above and unlike
// PaperGuardFailedError, because it replaces a broker 422 that DID reach
// Discord via the callers' `instanceof AlpacaError -> notifyBrokerError`
// catch, and that alert is how #494 was found at all. A silent audit row
// would make the next recurrence invisible.
export class SubPennyPriceError extends AlpacaError {
  override name = "SubPennyPriceError";
}
// #511 D1: per-request deadline for every Alpaca REST call (trading and
// market-data, one shared value -- see the 0015 migration's #511 addendum
// for the arithmetic). ~20x #498's 500ms stressed-broker allowance, so no
// legitimate call gets cut; deliberately generous rather than tight because
// a falsely-aborted order POST can leave a broker-side order the client
// never learns about.
export const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;
// Extends AlpacaError (like OrderTimeoutError/SubPennyPriceError above) so
// both cron callers' existing `instanceof AlpacaError -> notifyBrokerError`
// catches surface a stalled broker connection with zero caller changes.
export class BrokerRequestTimeoutError extends AlpacaError {
  override name = "BrokerRequestTimeoutError";
}

// Races `promise` against the SAME AbortSignal-driven deadline used for the
// setTimeout above, rejecting with BrokerRequestTimeoutError the instant the
// deadline fires -- independent of whether `promise` itself ever inspects or
// honors the signal. `onAbortExtra` runs first (e.g. cancelling a response
// body stream) so callers can attach cleanup before the shared rejection.
// The timer can fire (and dispatch "abort") between `promise` being created
// and this listener being attached -- a past "abort" event is never
// redelivered, so `controller.signal.aborted` is checked directly rather than
// relying solely on the event, to avoid a hang in that race window.
function raceAgainstDeadline<T>(
  promise: Promise<T>,
  controller: AbortController,
  method: string,
  url: string,
  timeoutMs: number,
  onAbortExtra?: () => void,
): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_resolve, reject) => {
      const onAbort = () => {
        onAbortExtra?.();
        reject(
          new BrokerRequestTimeoutError(
            `${method} ${url} did not complete within ${timeoutMs}ms`,
          ),
        );
      };
      if (controller.signal.aborted) onAbort();
      else controller.signal.addEventListener("abort", onAbort, { once: true });
    }),
  ]);
}

// #511 D4: bounds the WHOLE round trip (headers + body), not just headers --
// a headers-only bound leaves the classic blackhole (headers arrive, body
// trickles forever) unbounded. AbortController + setTimeout, cleared in
// `finally` -- deliberately NOT AbortSignal.timeout(): an explicit, cleared
// timer is deterministic under Deno's test sanitizers, which otherwise flag
// a leaked timer. Reads the body here and returns a reconstructed Response so
// every existing call site (res.ok, res.status, res.json(), res.text(), the
// 204 checks in cancelOrder/cancelAllOrders) works byte-for-byte unchanged;
// "" -> null keeps null-body statuses (204) constructible. Both the initial
// fetch() and the body read are raced against the SAME deadline (rather than
// relying on fetch internals to cancel the stream), so the bound is
// self-contained defense-in-depth: it holds even against a fetch
// implementation that never inspects the AbortSignal at all, not just for
// real fetches and stubFetch-constructed Responses in tests that do.
export async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const method = init.method ?? "GET";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const fetchPromise = fetch(url, { ...init, signal: controller.signal });
    // A losing (non-cooperative) fetch promise may still settle later --
    // swallow that so it never surfaces as an unhandled rejection.
    fetchPromise.catch(() => {});
    const res = await raceAgainstDeadline(fetchPromise, controller, method, url, timeoutMs);
    const text = await raceAgainstDeadline(
      res.text(),
      controller,
      method,
      url,
      timeoutMs,
      () => {
        res.body?.cancel().catch(() => {});
      },
    );
    return new Response(text === "" ? null : text, { status: res.status });
  } catch (e) {
    if (e instanceof BrokerRequestTimeoutError) throw e;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new BrokerRequestTimeoutError(
        `${method} ${url} did not complete within ${timeoutMs}ms`,
      );
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// Matched against String(price), because that is what the order bodies below
// put on the wire: this rejects sub-penny values AND magnitudes that serialize
// in exponent notation. Deliberately independent of roundToCents, so a
// quantizer regression cannot propagate silently into the check guarding it.
const WHOLE_CENT_PRICE = /^-?\d+(\.\d{1,2})?$/;

function requireWholeCentPrice(value: number, field: string): void {
  if (!Number.isFinite(value)) {
    throw new SubPennyPriceError(`${field} must be a finite price, got ${String(value)}`);
  }
  if (!WHOLE_CENT_PRICE.test(String(value))) {
    throw new SubPennyPriceError(
      `${field} must be a whole-cent price, got ${String(value)}`,
    );
  }
}

export interface Fill {
  orderId: string;
  fillPrice: number;
  qty: number;
  fillTime: string;
}

// #475 T11: a fill discovered via listFilledOrdersSince, which (unlike
// placeMarketOrder's Fill) does not already know its own side from the
// caller's request -- the reconciliation consumer needs it to write a
// trades row.
export interface ClosedOrderFill extends Fill {
  side: "BUY" | "SELL";
}

export interface PollOpts {
  timeoutMs?: number;
  intervalMs?: number;
}

export interface OpenPosition {
  symbol: string;
  qty: number;
}

export interface AlpacaClient {
  // nextClose is epoch ms (spec §7): additive field, existing callers
  // (daily-check, kill-switch) destructure only isOpen and are unaffected.
  getClock(): Promise<{ isOpen: boolean; nextClose: number }>;
  /** US trading-session dates (YYYY-MM-DD) in [start, end], oldest-first. */
  getCalendar(start: string, end: string): Promise<string[]>;
  getAccountValue(): Promise<number>;
  getPosition(symbol: string): Promise<number>;
  /** Every open position, signed qty (negative = short). [] when flat. */
  getOpenPositions(): Promise<OpenPosition[]>;
  placeMarketOrder(
    args: { symbol: string; side: "BUY" | "SELL"; qty: number },
    opts?: PollOpts,
  ): Promise<Fill>;
  liquidate(symbol: string, opts?: PollOpts): Promise<Fill | null>;
  /** Side-aware close: SELL for a long, BUY (to cover) for a short. null when flat. */
  closePosition(symbol: string, opts?: PollOpts): Promise<Fill | null>;
  cancelAllOrders(): Promise<number>;
  // #475 T5 (spec §8.3 Layer B): one /v2/account read at pipeline start,
  // asserting a confirmed paper-account marker. Piggybacks the equity read
  // so the caller needs only one account read per run.
  assertPaperAccount(): Promise<{ equity: number }>;
  // #475 T6 (spec §7): bracket entry (both legs placed atomically with the
  // entry order); the entry leg reuses the market-order poll/timeout/reject
  // contract, the exit legs are broker-resident.
  placeBracketOrder(
    args: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      takeProfitPrice: number;
      stopLossPrice: number;
    },
    opts?: PollOpts,
  ): Promise<Fill>;
  // #475 T6: OCO exit pair (stop + limit) against an EXISTING position --
  // the §7 fallback path (plain entry, then legs once the fill confirms) and
  // the position-without-legs re-leg rule (§7 finding 3) both need this
  // regardless of whether bracket-on-short is confirmed. `side` is the
  // CLOSING side (SELL to exit a long, BUY to cover a short). No polling --
  // this places a resting order and returns its broker id immediately.
  placeOcoExitPair(args: {
    symbol: string;
    side: "BUY" | "SELL";
    qty: number;
    takeProfitPrice: number;
    stopLossPrice: number;
  }): Promise<{ orderId: string }>;
  // #475 T6: targeted cancel (verified) -- cancelAllOrders would also kill
  // the incumbent daily-check bot's orders during the decommission window,
  // so leg cancels must be surgical (spec §7 orphan-leg hazard).
  cancelOrder(orderId: string, opts?: PollOpts): Promise<void>;
  // #475 T6: read-only GET /v2/assets/{symbol}. Field names (shortable/
  // easy_to_borrow) are [to verify] -- see the PR disclosure; unguarded like
  // every other read-only helper (cannot place an order).
  getAssetShortability(symbol: string): Promise<{ shortable: boolean; easyToBorrow: boolean }>;
  // #475 T11 (spec §7 reconciliation contract): implied-by-spec additions not
  // separately named in T6's helper list -- the reconciliation contract
  // ("list closed orders for the symbol since the last journaled exit") and
  // the position-without-legs rule ("an open position with no resting
  // stop/target legs at all") cannot be implemented without a broker order
  // list read. Disclosed as a delta in the PR; both are read-only (unguarded)
  // and use Alpaca's documented GET /v2/orders list endpoint, [to verify]
  // like every other API-shape assertion in this file.
  listFilledOrdersSince(symbol: string, sinceIso: string): Promise<ClosedOrderFill[]>;
  listOpenOrderIds(symbol: string): Promise<string[]>;
}

function checkGuard(op: string): void {
  if (isClaudeAgentNoBroker()) {
    throw new BrokerCallBlockedError(
      `CLAUDE_AGENT_NO_BROKER is set; refusing to perform '${op}'. Mock the broker in tests.`,
    );
  }
}

// #475 T5 (spec §8.3 Layer A): per-call, no network. Asserts BOTH cfg.paper
// and the trading base URL match the paper host -- the URL check is
// load-bearing (it is literally the host about to be called), so a mis-set
// boolean alone cannot defeat this guard. Exported standalone (not just
// exercised through createAlpacaClient) so the URL-vs-boolean independence is
// directly unit-testable.
export function checkPaperOnly(
  op: string,
  cfg: Pick<AlpacaConfig, "paper" | "tradingBaseUrl">,
): void {
  if (cfg.paper !== true || cfg.tradingBaseUrl !== "https://paper-api.alpaca.markets") {
    throw new PaperGuardFailedError(
      `paper-only guard failed for '${op}': paper=${cfg.paper} tradingBaseUrl=${cfg.tradingBaseUrl}`,
    );
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createAlpacaClient(
  opts: { paperOnly: boolean; requestTimeoutMs?: number },
): AlpacaClient {
  const cfg = getAlpacaConfig();
  const paperOnly = opts.paperOnly;
  // #511 D1: requestTimeoutMs is a test-only override -- every production call
  // site (daily-check, kill-switch, panic, status, hourly-check) passes only
  // paperOnly, so the 10s default applies everywhere in production.
  const requestTimeoutMs = opts.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
  const headers = {
    "APCA-API-KEY-ID": cfg.apiKeyId,
    "APCA-API-SECRET-KEY": cfg.apiSecretKey,
  };

  // #475 T5: called by every mutating helper immediately after checkGuard()
  // when this client opted into paperOnly. #508: paperOnly is now a required
  // param, so every call site states its stance explicitly -- hourly-check
  // passes true; daily-check/kill-switch/panic/status pass false (each with
  // its own audited why-comment at the call site) -- so their runtime
  // behavior stays byte-for-byte unchanged from before this param was
  // required.
  function guardMutation(op: string): void {
    checkGuard(op);
    if (paperOnly) checkPaperOnly(op, cfg);
  }

  async function trade(path: string, init?: RequestInit): Promise<Response> {
    return await fetchWithTimeout(
      `${cfg.tradingBaseUrl}${path}`,
      { ...init, headers: { ...headers, ...(init?.headers ?? {}) } },
      requestTimeoutMs,
    );
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
    // #475 T4 (spec §7 must-fix round 2 finding 1): next_close is asserted,
    // not verified against a live response in this agent session (no paper
    // credentials present -- disclosed in the PR). Missing/unparseable is a
    // hard error, routed through the same requireNumber boundary as every
    // other JSON->number Alpaca field: a permanently-false
    // `nextClose - now <= 1h` comparison would silently hold positions
    // overnight with no visible signal that anything is wrong.
    const raw = j.next_close;
    const nextClose = requireNumber(
      typeof raw === "string" ? Date.parse(raw) : raw,
      "next_close",
    );
    return { isOpen: Boolean(j.is_open), nextClose };
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

  // Extracts a Fill from an order body when any shares actually filled (full
  // or partial); null otherwise. Partial fills must reach the caller so the
  // trades table records the shares really owned (#267). Shared by every
  // entry-leg poller (placeMarketOrder, placeBracketOrder's entry leg).
  function partialOrFullFill(orderId: string, o: Record<string, unknown>): Fill | null {
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
  }

  const TERMINAL_NON_FILL = ["rejected", "canceled", "expired"];

  // Poll-until-filled / timeout / reject contract (#267/#262/#342), factored
  // out of placeMarketOrder (#475 T6) so placeBracketOrder's entry leg reuses
  // it verbatim rather than duplicating the timeout/verified-cancel logic.
  // `label` carries the human-readable order description into every thrown
  // message (e.g. "BUY 100 UPRO" for a plain market order).
  async function pollOrderUntilFilled(
    orderId: string,
    label: string,
    opts?: PollOpts,
  ): Promise<Fill> {
    const timeoutMs = opts?.timeoutMs ?? 30_000;
    const intervalMs = opts?.intervalMs ?? 500;

    // #511 D5: a true wall-clock deadline, not accumulated sleep -- the old
    // `waited += intervalMs` counter never counted the awaited HTTP round
    // trip inside each iteration, so `timeoutMs` didn't bound real elapsed
    // time. Total loop elapsed is now bounded by timeoutMs plus at most one
    // in-flight request (itself bounded by D1's per-request deadline).
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
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
        const partial = partialOrFullFill(orderId, o);
        if (partial) return partial;
        const reason = o.reject_reason ? `: ${o.reject_reason}` : "";
        throw new OrderRejectedError(
          `${label} order ${orderId} terminal status '${o.status}'${reason}`,
          String(o.status),
        );
      }
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      await sleep(Math.min(intervalMs, remaining)); // clamp: never sleep past the deadline
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
      const fill = partialOrFullFill(orderId, final);
      if (fill) return fill;
      if (TERMINAL_NON_FILL.includes(String(final.status))) {
        // Cancel verified: the order is confirmed dead. `rejected` counts as
        // verified too — the order cannot be live, which is the property
        // being verified.
        throw new OrderTimeoutError(
          `${label} did not fill within ${timeoutMs}ms; ` +
            `cancelled (verified: status '${final.status}')`,
        );
      }
      // Still live (e.g. pending_cancel) — an immediate re-poll can legitimately
      // race the broker's own cancel processing, so this is classified
      // UNVERIFIED rather than assumed cancelled.
      throw new OrderTimeoutError(
        `${label} did not fill within ${timeoutMs}ms; ` +
          `cancel UNVERIFIED — order ${orderId} may still be live (status '${final.status}')`,
      );
    } catch (e) {
      if (e instanceof OrderTimeoutError) throw e;
      throw new OrderTimeoutError(
        `${label} did not fill within ${timeoutMs}ms; ` +
          `cancel UNVERIFIED — order ${orderId} may still be live ` +
          `(post-cancel status check failed: ${(e as Error).message})`,
      );
    }
  }

  async function placeMarketOrder(
    args: { symbol: string; side: "BUY" | "SELL"; qty: number },
    opts?: PollOpts,
  ): Promise<Fill> {
    guardMutation("placeMarketOrder");
    if (args.side !== "BUY" && args.side !== "SELL") {
      throw new Error(`side must be BUY or SELL, got ${args.side}`);
    }
    if (args.qty <= 0) throw new Error(`qty must be > 0, got ${args.qty}`);

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
    return await pollOrderUntilFilled(orderId, `${args.side} ${args.qty} ${args.symbol}`, opts);
  }

  // #475 T6 (spec §7): bracket entry. Body field names confirmed against
  // Alpaca's documented bracket-order shape (nested take_profit.limit_price /
  // stop_loss.stop_price objects) -- the PR discloses the evidence cited for
  // this shape. time_in_force defaults to "day" (fallback per the spec's
  // [to verify] note: every existing order in this repo uses "day", and no
  // live capture was possible in this agent session to confirm "gtc" is also
  // accepted on a bracket entry).
  async function placeBracketOrder(
    args: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      takeProfitPrice: number;
      stopLossPrice: number;
    },
    opts?: PollOpts,
  ): Promise<Fill> {
    guardMutation("placeBracketOrder");
    if (args.side !== "BUY" && args.side !== "SELL") {
      throw new Error(`side must be BUY or SELL, got ${args.side}`);
    }
    if (args.qty <= 0) throw new Error(`qty must be > 0, got ${args.qty}`);
    requireWholeCentPrice(args.takeProfitPrice, "takeProfitPrice");
    requireWholeCentPrice(args.stopLossPrice, "stopLossPrice");

    const created = await tradeJson("/v2/orders", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        symbol: args.symbol,
        qty: String(args.qty),
        side: args.side.toLowerCase(),
        type: "market",
        time_in_force: "day",
        order_class: "bracket",
        take_profit: { limit_price: String(args.takeProfitPrice) },
        stop_loss: { stop_price: String(args.stopLossPrice) },
      }),
    });
    const orderId = String(created.id);
    return await pollOrderUntilFilled(
      orderId,
      `${args.side} ${args.qty} ${args.symbol} bracket entry`,
      opts,
    );
  }

  // #475 T6 (spec §7): OCO exit pair against an existing position. No
  // polling -- these legs are broker-resident and fill (or don't) on their
  // own; the reconciliation contract (hourly-check/logic.ts, T11) discovers
  // fills on a later scan.
  async function placeOcoExitPair(args: {
    symbol: string;
    side: "BUY" | "SELL";
    qty: number;
    takeProfitPrice: number;
    stopLossPrice: number;
  }): Promise<{ orderId: string }> {
    guardMutation("placeOcoExitPair");
    if (args.side !== "BUY" && args.side !== "SELL") {
      throw new Error(`side must be BUY or SELL, got ${args.side}`);
    }
    if (args.qty <= 0) throw new Error(`qty must be > 0, got ${args.qty}`);
    requireWholeCentPrice(args.takeProfitPrice, "takeProfitPrice");
    requireWholeCentPrice(args.stopLossPrice, "stopLossPrice");

    const created = await tradeJson("/v2/orders", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        symbol: args.symbol,
        qty: String(args.qty),
        side: args.side.toLowerCase(),
        // An OCO exit is a single order: type="limit" carries the take-profit
        // price at the top level, paired with a stop_loss sub-order -- unlike
        // a bracket entry, there is no separate take_profit object here.
        type: "limit",
        limit_price: String(args.takeProfitPrice),
        time_in_force: "day",
        order_class: "oco",
        stop_loss: { stop_price: String(args.stopLossPrice) },
      }),
    });
    return { orderId: String(created.id) };
  }

  // #475 T6 (spec §7 orphan-leg hazard): targeted, verified cancel. Confirms
  // the order reaches a terminal state (canceled/filled/rejected/expired)
  // before returning -- an unverified cancel must not be treated as "the
  // leg is gone" (the same discipline as cancelAllOrders/placeMarketOrder's
  // post-timeout cancel verification). Short bounded poll (fix round 1
  // finding 6): Alpaca's cancel is asynchronous, so a healthy cancel
  // routinely reads back `pending_cancel` on the very next GET -- a single
  // immediate read would misclassify that as UNVERIFIED. Mirrors
  // pollOrderUntilFilled's poll/timeout shape, just against the narrower
  // terminal-status set already used here.
  async function cancelOrder(orderId: string, opts?: PollOpts): Promise<void> {
    guardMutation("cancelOrder");
    const res = await trade(`/v2/orders/${encodeURIComponent(orderId)}`, { method: "DELETE" });
    if (res.status !== 204 && !res.ok) {
      throw new AlpacaError(`DELETE order ${orderId} -> ${res.status}: ${await res.text()}`);
    }
    const TERMINAL_ANY = ["canceled", "filled", "rejected", "expired"];
    const timeoutMs = opts?.timeoutMs ?? 3_000;
    const intervalMs = opts?.intervalMs ?? 250;

    // #511 D5: same wall-clock deadline as pollOrderUntilFilled above (the
    // initial DELETE just issued is itself bounded by D1's per-request
    // deadline).
    const deadline = Date.now() + timeoutMs;
    let lastStatus = "";
    while (Date.now() < deadline) {
      const final = await tradeJson(`/v2/orders/${orderId}`);
      lastStatus = String(final.status);
      if (TERMINAL_ANY.includes(lastStatus)) return;
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      await sleep(Math.min(intervalMs, remaining)); // clamp: never sleep past the deadline
    }
    throw new AlpacaError(
      `cancelOrder(${orderId}) UNVERIFIED — order status still '${lastStatus}' after DELETE`,
    );
  }

  // #475 T6 (spec §7 shortability [to verify]): read-only, unguarded (cannot
  // place an order). Field names asserted here (shortable/easy_to_borrow) are
  // per the spec's documented claim, not confirmed against a live response in
  // this agent session (no paper credentials present) -- disclosed in the PR.
  async function getAssetShortability(
    symbol: string,
  ): Promise<{ shortable: boolean; easyToBorrow: boolean }> {
    const res = await trade(`/v2/assets/${encodeURIComponent(symbol)}`);
    if (!res.ok) {
      throw new AlpacaError(`GET asset ${symbol} -> ${res.status}: ${await res.text()}`);
    }
    const j = await res.json();
    return { shortable: Boolean(j.shortable), easyToBorrow: Boolean(j.easy_to_borrow) };
  }

  // #475 T11: read-only, unguarded. Lists CLOSED orders for `symbol` filled
  // strictly after `sinceIso`, so the reconciliation contract (spec §7) can
  // discover bracket/OCO exit-leg fills the caller did not itself poll for.
  async function listFilledOrdersSince(
    symbol: string,
    sinceIso: string,
  ): Promise<ClosedOrderFill[]> {
    const res = await trade(
      `/v2/orders?status=closed&symbols=${encodeURIComponent(symbol)}` +
        `&after=${encodeURIComponent(sinceIso)}&direction=asc&limit=500`,
    );
    if (!res.ok) {
      throw new AlpacaError(`GET orders (closed) ${symbol} -> ${res.status}: ${await res.text()}`);
    }
    const arr = await res.json();
    if (!Array.isArray(arr)) {
      throw new AlpacaError("GET orders (closed) -> unexpected non-array body");
    }
    return (arr as Record<string, unknown>[])
      .filter((o) => o.status === "filled")
      .map((o) => ({
        orderId: String(o.id),
        side: String(o.side).toLowerCase() === "buy" ? "BUY" : "SELL",
        fillPrice: requireNumber(o.filled_avg_price, "filled_avg_price"),
        qty: Math.trunc(requireNumber(o.filled_qty, "filled_qty")),
        fillTime: String(o.filled_at),
      }));
  }

  // #475 T11: read-only, unguarded. Broker order ids still resting (open)
  // for `symbol` -- used by the position-without-legs rule (spec §7 finding
  // 3) to detect an open position with no resting stop/target legs at all.
  async function listOpenOrderIds(symbol: string): Promise<string[]> {
    const res = await trade(
      `/v2/orders?status=open&symbols=${encodeURIComponent(symbol)}&limit=500`,
    );
    if (!res.ok) {
      throw new AlpacaError(`GET orders (open) ${symbol} -> ${res.status}: ${await res.text()}`);
    }
    const arr = await res.json();
    if (!Array.isArray(arr)) {
      throw new AlpacaError("GET orders (open) -> unexpected non-array body");
    }
    return (arr as Record<string, unknown>[]).map((o) => String(o.id));
  }

  async function liquidate(symbol: string, opts?: PollOpts): Promise<Fill | null> {
    guardMutation("liquidate");
    const qty = await getPosition(symbol);
    if (qty <= 0) return null;
    return await placeMarketOrder({ symbol, side: "SELL", qty }, opts);
  }

  // Read-only: distinguishes "no position" from a short (getPosition already
  // returns signed qty via Math.trunc; this just lists every symbol at once).
  // [to verify] the exact GET /v2/positions response shape is asserted from
  // the single-position endpoint's own field names, not captured live.
  async function getOpenPositions(): Promise<OpenPosition[]> {
    const res = await trade("/v2/positions");
    if (!res.ok) {
      throw new AlpacaError(`GET positions -> ${res.status}: ${await res.text()}`);
    }
    const arr = await res.json();
    if (!Array.isArray(arr)) return [];
    return arr.map((p) => ({
      symbol: String((p as { symbol: unknown }).symbol),
      qty: Math.trunc(requireNumber((p as { qty: unknown }).qty, "position qty")),
    }));
  }

  // Side-aware close (#474, D1/§8.1): the retrofit's BUY-to-cover helper.
  // Routes through placeMarketOrder, so checkGuard/CLAUDE_AGENT_NO_BROKER
  // covers it twice (directly and transitively) and it inherits the same
  // poll/timeout/partial-fill/verified-cancel contract as liquidate.
  async function closePosition(symbol: string, opts?: PollOpts): Promise<Fill | null> {
    checkGuard("closePosition");
    const qty = await getPosition(symbol);
    if (qty === 0) return null;
    if (qty > 0) return await placeMarketOrder({ symbol, side: "SELL", qty }, opts);
    return await placeMarketOrder({ symbol, side: "BUY", qty: Math.abs(qty) }, opts);
  }

  async function cancelAllOrders(): Promise<number> {
    guardMutation("cancelAllOrders");
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

  // #475 T5 / #479 T3 (spec §8.3 Layer B): guarded like a mutating call (no
  // live network from an agent test session), then asserts the paper-only
  // Layer A checks, then reads /v2/account once. The pinned marker -- a
  // string account_number starting with "PA" -- is confirmed against a real
  // paper-account response captured by the operator (see the "Capture
  // evidence — four read-only paper GETs (T1), operator-run 2026-07-29"
  // comment on #479: account_number came back "PA****", sanitized to its
  // 2-char prefix). Fail-closed is retained: missing, non-string, or
  // non-"PA"-prefixed account_number still throws PaperGuardFailedError.
  async function assertPaperAccount(): Promise<{ equity: number }> {
    guardMutation("assertPaperAccount");
    const j = await tradeJson("/v2/account");
    const equity = requireNumber(j.equity, "account equity");
    // Nit 11 (fix round 1): mask the raw account_number in this error
    // message -- only the marker prefix (e.g. the "PA" paper-account marker)
    // is diagnostically useful here, and this message can end up in
    // notifications/logs that shouldn't carry the full account identifier.
    const rawAccountNumber = typeof j.account_number === "string" ? j.account_number : null;
    const maskedAccountNumber = rawAccountNumber === null
      ? null
      : rawAccountNumber.slice(0, 2) + "*".repeat(Math.max(rawAccountNumber.length - 2, 0));
    if (rawAccountNumber === null || !rawAccountNumber.startsWith("PA")) {
      throw new PaperGuardFailedError(
        `Layer B paper-account marker check failed (spec §8.3, pinned from the #479 T1 capture: ` +
          `account_number must be a string starting with "PA") -- refusing to trade (fail-closed); ` +
          `account_number=${JSON.stringify(maskedAccountNumber)}, equity=${equity}`,
      );
    }
    return { equity };
  }

  return {
    getClock,
    getCalendar,
    getAccountValue,
    getPosition,
    getOpenPositions,
    placeMarketOrder,
    liquidate,
    closePosition,
    cancelAllOrders,
    assertPaperAccount,
    placeBracketOrder,
    placeOcoExitPair,
    cancelOrder,
    getAssetShortability,
    listFilledOrdersSince,
    listOpenOrderIds,
  };
}
