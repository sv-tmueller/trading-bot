# MVP 2.0 Infra Migration — Plan 2: I/O Modules

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four side-effecting modules the Edge Functions compose — Alpaca broker client (with the `CLAUDE_AGENT_NO_BROKER` guard), Alpaca market-data, the Supabase DB layer, and n8n notifications — each unit-tested in isolation.

**Architecture:** Pure-ish adapter modules over `fetch` (Alpaca, n8n) and the Supabase JS client (DB). Broker mutations are guarded so any unmocked call in a test fails fast instead of placing a live order. Network modules are tested by stubbing `globalThis.fetch`; the DB module is tested against the **local** Supabase Postgres (no broker risk) behind a `RUN_DB_TESTS` flag.

**Tech Stack:** Deno, TypeScript, `@std/assert`, `@supabase/supabase-js` (JSR), Alpaca Trading + Market Data REST v2.

**Spec:** `docs/superpowers/specs/2026-06-05-mvp2-infra-migration-design.md`
**Issue:** [#220](https://github.com/sv-tmueller/trading-bot/issues/220)
**Plan 2 of 3** — depends on Plan 1 (scaffold, schema, `config.ts`, `regime.ts`). Plan 3 wires these into the three Edge Functions + `pg_cron` + rollout.

---

## File Structure

- Modify: `supabase/functions/_shared/config.ts` — add `getAlpacaConfig()`, `getN8nWebhookUrl()`, `isClaudeAgentNoBroker()`.
- Modify: `supabase/functions/_shared/config.test.ts` — tests for the new accessors.
- Create: `supabase/functions/_shared/test_helpers.ts` — `stubFetch()`, `jsonResponse()`.
- Create: `supabase/functions/_shared/notifications.ts` + `.test.ts` — n8n webhook poster + typed event builders.
- Create: `supabase/functions/_shared/alpaca.ts` + `.test.ts` — broker client + guard.
- Create: `supabase/functions/_shared/marketdata.ts` + `.test.ts` — daily bars + latest trade.
- Create: `supabase/functions/_shared/db.ts` + `.test.ts` — Supabase persistence (integration tests vs local Postgres).
- Modify: `deno.json` — add `@supabase/supabase-js` import + `test:db` task.

**Safety:** The `alpaca.ts` mutating methods (`placeMarketOrder`, `liquidate`, `cancelAllOrders`) MUST call the guard first (spec §5). Read-only methods (`getClock`, `getAccountValue`, `getPosition`) are not guarded — they cannot place an order — but tests still stub `fetch` so no live call leaks. Dev/test use Alpaca **paper** keys (defense in depth).

---

## Task 1: Extend `config.ts` (Alpaca + n8n accessors + guard)

**Files:**
- Modify: `supabase/functions/_shared/config.ts`
- Modify: `supabase/functions/_shared/config.test.ts`
- Modify: `deno.json`

- [ ] **Step 1: Add the import + task to `deno.json`**

Replace `deno.json` with:

```json
{
  "imports": {
    "@std/assert": "jsr:@std/assert@^1.0.8",
    "@supabase/supabase-js": "jsr:@supabase/supabase-js@^2.45.0"
  },
  "tasks": {
    "test": "deno test --allow-env --allow-net supabase/functions/_shared/",
    "test:db": "RUN_DB_TESTS=1 deno test --allow-env --allow-net supabase/functions/_shared/db.test.ts",
    "fmt": "deno fmt supabase/functions/",
    "lint": "deno lint supabase/functions/"
  },
  "fmt": { "lineWidth": 100 }
}
```

- [ ] **Step 2: Write the failing tests**

Append to `supabase/functions/_shared/config.test.ts`:

```ts
import { getAlpacaConfig, getN8nWebhookUrl, isClaudeAgentNoBroker } from "./config.ts";

Deno.test("getAlpacaConfig throws when keys missing", () => {
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  assertThrows(() => getAlpacaConfig(), Error, "ALPACA_API_KEY");
});

Deno.test("getAlpacaConfig defaults to paper base URL", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.delete("ALPACA_PAPER");
  const c = getAlpacaConfig();
  assertEquals(c.paper, true);
  assertEquals(c.tradingBaseUrl, "https://paper-api.alpaca.markets");
  assertEquals(c.dataBaseUrl, "https://data.alpaca.markets");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
});

Deno.test("getAlpacaConfig honours ALPACA_PAPER=false", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_PAPER", "false");
  assertEquals(getAlpacaConfig().tradingBaseUrl, "https://api.alpaca.markets");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  Deno.env.delete("ALPACA_PAPER");
});

Deno.test("getN8nWebhookUrl empty when unset", () => {
  Deno.env.delete("N8N_WEBHOOK_URL");
  assertEquals(getN8nWebhookUrl(), "");
});

Deno.test("isClaudeAgentNoBroker reads env fresh", () => {
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
  assertEquals(isClaudeAgentNoBroker(), false);
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  assertEquals(isClaudeAgentNoBroker(), true);
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `getAlpacaConfig`/`getN8nWebhookUrl`/`isClaudeAgentNoBroker` not exported.

- [ ] **Step 4: Implement**

Append to `supabase/functions/_shared/config.ts`:

```ts
export interface AlpacaConfig {
  apiKeyId: string;
  apiSecretKey: string;
  paper: boolean;
  tradingBaseUrl: string;
  dataBaseUrl: string;
}

export function getAlpacaConfig(): AlpacaConfig {
  const apiKeyId = Deno.env.get("ALPACA_API_KEY")?.trim() ?? "";
  const apiSecretKey = Deno.env.get("ALPACA_SECRET_KEY")?.trim() ?? "";
  if (apiKeyId === "" || apiSecretKey === "") {
    throw new Error("ALPACA_API_KEY and ALPACA_SECRET_KEY must both be set");
  }
  // Default to PAPER. Only an explicit ALPACA_PAPER=false selects live.
  const paper = (Deno.env.get("ALPACA_PAPER") ?? "true").toLowerCase() !== "false";
  return {
    apiKeyId,
    apiSecretKey,
    paper,
    tradingBaseUrl: paper
      ? "https://paper-api.alpaca.markets"
      : "https://api.alpaca.markets",
    dataBaseUrl: "https://data.alpaca.markets",
  };
}

export function getN8nWebhookUrl(): string {
  return Deno.env.get("N8N_WEBHOOK_URL")?.trim() ?? "";
}

// Ported #168 guard. Read fresh every call so tests can flip it mid-test.
export function isClaudeAgentNoBroker(): boolean {
  const v = Deno.env.get("CLAUDE_AGENT_NO_BROKER")?.toLowerCase() ?? "";
  return v === "1" || v === "true" || v === "yes";
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `deno task test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add deno.json supabase/functions/_shared/config.ts supabase/functions/_shared/config.test.ts
git commit -m "feat(mvp2): config accessors for Alpaca, n8n, broker guard (#220)"
```

---

## Task 2: `test_helpers.ts` + `notifications.ts`

> **Post-review amendment (2026-06-05):** the implemented `notifications.ts` additionally
> includes a human-readable `message` field in every typed wrapper (and a `title` field in
> `notifyRegimeFlip`), matching the prose in `tools/notifications.py`, because the existing
> n8n→Discord flow likely renders `body.message`. The code blocks below show the original
> structured-only version; the committed module (see `git show` of the Task 2 commit) is the
> source of truth.

**Files:**
- Create: `supabase/functions/_shared/test_helpers.ts`
- Create: `supabase/functions/_shared/notifications.test.ts`
- Create: `supabase/functions/_shared/notifications.ts`

- [ ] **Step 1: Create the shared test helper**

Create `supabase/functions/_shared/test_helpers.ts`:

```ts
// Test-only helpers. Stub globalThis.fetch and restore it.
export type FetchHandler = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export function stubFetch(handler: FetchHandler): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function urlOf(input: string | URL | Request): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}
```

- [ ] **Step 2: Write the failing tests**

Create `supabase/functions/_shared/notifications.test.ts`:

```ts
import { assertEquals } from "@std/assert";
import { stubFetch } from "./test_helpers.ts";
import { notify, notifyRegimeFlip } from "./notifications.ts";

Deno.test("notify posts JSON to the webhook", async () => {
  Deno.env.set("N8N_WEBHOOK_URL", "http://localhost:5678/hook");
  let capturedUrl = "";
  let capturedBody: unknown = null;
  const restore = stubFetch(async (input, init) => {
    capturedUrl = typeof input === "string" ? input : input.toString();
    capturedBody = JSON.parse(String(init?.body));
    return new Response("ok", { status: 200 });
  });
  try {
    await notify({ event_type: "test", foo: 1 });
    assertEquals(capturedUrl, "http://localhost:5678/hook");
    assertEquals(capturedBody, { event_type: "test", foo: 1 });
  } finally {
    restore();
    Deno.env.delete("N8N_WEBHOOK_URL");
  }
});

Deno.test("notify is a no-op when URL unset", async () => {
  Deno.env.delete("N8N_WEBHOOK_URL");
  let called = false;
  const restore = stubFetch(async () => {
    called = true;
    return new Response("ok");
  });
  try {
    await notify({ event_type: "test" });
    assertEquals(called, false);
  } finally {
    restore();
  }
});

Deno.test("notify swallows fetch errors (never throws)", async () => {
  Deno.env.set("N8N_WEBHOOK_URL", "http://localhost:5678/hook");
  const restore = stubFetch(() => Promise.reject(new Error("network down")));
  try {
    await notify({ event_type: "test" }); // must not throw
  } finally {
    restore();
    Deno.env.delete("N8N_WEBHOOK_URL");
  }
});

Deno.test("notifyRegimeFlip builds the structured payload", async () => {
  Deno.env.set("N8N_WEBHOOK_URL", "http://localhost:5678/hook");
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_i, init) => {
    body = JSON.parse(String(init?.body));
    return new Response("ok");
  });
  try {
    await notifyRegimeFlip({
      targetState: "LONG",
      spyClose: 400,
      spySma200: 380,
      ticker: "UPRO",
      fillPrice: 70,
      qty: 100,
      accountValue: 7000,
      dryRun: false,
    });
    assertEquals(body.event_type, "regime_flip");
    assertEquals(body.target_state, "LONG");
    assertEquals(body.ticker, "UPRO");
    assertEquals(body.dry_run, false);
  } finally {
    restore();
    Deno.env.delete("N8N_WEBHOOK_URL");
  }
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `./notifications.ts` not found.

- [ ] **Step 4: Implement**

Create `supabase/functions/_shared/notifications.ts`:

```ts
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
```

- [ ] **Step 5: Run to verify they pass**

Run: `deno task test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add supabase/functions/_shared/test_helpers.ts supabase/functions/_shared/notifications.ts supabase/functions/_shared/notifications.test.ts
git commit -m "feat(mvp2): n8n notifications module + test helpers (#220)"
```

---

## Task 3: `alpaca.ts` — broker client + guard

**Files:**
- Create: `supabase/functions/_shared/alpaca.test.ts`
- Create: `supabase/functions/_shared/alpaca.ts`

- [ ] **Step 1: Write the failing tests**

Create `supabase/functions/_shared/alpaca.test.ts`:

```ts
import { assertEquals, assertRejects } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import {
  BrokerCallBlockedError,
  createAlpacaClient,
  OrderTimeoutError,
} from "./alpaca.ts";

function setKeys() {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_PAPER", "true");
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
}
function clearKeys() {
  for (const k of ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_PAPER", "CLAUDE_AGENT_NO_BROKER"]) {
    Deno.env.delete(k);
  }
}

Deno.test("getClock maps is_open", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).endsWith("/v2/clock"), true);
    return Promise.resolve(jsonResponse({ is_open: true, timestamp: "t" }));
  });
  try {
    const client = createAlpacaClient();
    assertEquals((await client.getClock()).isOpen, true);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getAccountValue parses equity", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ equity: "12345.67" })));
  try {
    assertEquals(await createAlpacaClient().getAccountValue(), 12345.67);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getPosition returns qty, 0 on 404", async () => {
  setKeys();
  let restore = stubFetch(() => Promise.resolve(jsonResponse({ qty: "100" })));
  try {
    assertEquals(await createAlpacaClient().getPosition("UPRO"), 100);
  } finally {
    restore();
  }
  restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "position does not exist" }, 404)));
  try {
    assertEquals(await createAlpacaClient().getPosition("UPRO"), 0);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder polls to fill", async () => {
  setKeys();
  let polls = 0;
  const restore = stubFetch((i, init) => {
    const url = urlOf(i);
    if (init?.method === "POST" && url.endsWith("/v2/orders")) {
      return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
    }
    // GET /v2/orders/o1
    polls += 1;
    if (polls < 2) return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
    return Promise.resolve(jsonResponse({
      id: "o1",
      status: "filled",
      filled_avg_price: "70.5",
      filled_qty: "100",
      filled_at: "2026-06-05T14:00:00Z",
    }));
  });
  try {
    const fill = await createAlpacaClient().placeMarketOrder(
      { symbol: "UPRO", side: "BUY", qty: 100 },
      { timeoutMs: 1000, intervalMs: 1 },
    );
    assertEquals(fill, { orderId: "o1", fillPrice: 70.5, qty: 100, fillTime: "2026-06-05T14:00:00Z" });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder times out and cancels", async () => {
  setKeys();
  let cancelled = false;
  const restore = stubFetch((i, init) => {
    const url = urlOf(i);
    if (init?.method === "POST" && url.endsWith("/v2/orders")) {
      return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
    }
    if (init?.method === "DELETE") {
      cancelled = true;
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" })); // never fills
  });
  try {
    await assertRejects(
      () =>
        createAlpacaClient().placeMarketOrder(
          { symbol: "UPRO", side: "BUY", qty: 100 },
          { timeoutMs: 5, intervalMs: 1 },
        ),
      OrderTimeoutError,
    );
    assertEquals(cancelled, true);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder validates side and qty", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({})));
  try {
    const c = createAlpacaClient();
    // deno-lint-ignore no-explicit-any
    await assertRejects(() => c.placeMarketOrder({ symbol: "UPRO", side: "HOLD" as any, qty: 1 }), Error, "side");
    await assertRejects(() => c.placeMarketOrder({ symbol: "UPRO", side: "BUY", qty: 0 }), Error, "qty");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("liquidate returns null with no position", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "no position" }, 404)));
  try {
    assertEquals(await createAlpacaClient().liquidate("UPRO"), null);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("guard blocks mutating calls without touching the network", async () => {
  setKeys();
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  let networkHit = false;
  const restore = stubFetch(() => {
    networkHit = true;
    return Promise.resolve(jsonResponse({}));
  });
  try {
    const c = createAlpacaClient();
    await assertRejects(() => c.placeMarketOrder({ symbol: "UPRO", side: "BUY", qty: 1 }), BrokerCallBlockedError);
    await assertRejects(() => c.liquidate("UPRO"), BrokerCallBlockedError);
    await assertRejects(() => c.cancelAllOrders(), BrokerCallBlockedError);
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `./alpaca.ts` not found.

- [ ] **Step 3: Implement**

Create `supabase/functions/_shared/alpaca.ts`:

```ts
// Alpaca Trading REST v2 client. Mirrors tools/ibkr_broker.py: mutating methods
// call the guard first so a forgotten mock fails fast instead of placing a live
// order (spec §5, ported #168). Read-only methods are unguarded but cannot place
// an order.
import { getAlpacaConfig, isClaudeAgentNoBroker } from "./config.ts";

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
    return Number(j.equity);
  }

  async function getPosition(symbol: string): Promise<number> {
    const res = await trade(`/v2/positions/${encodeURIComponent(symbol)}`);
    if (res.status === 404) return 0;
    if (!res.ok) throw new AlpacaError(`GET position ${symbol} -> ${res.status}: ${await res.text()}`);
    const j = await res.json();
    return Math.trunc(Number(j.qty));
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
          fillPrice: Number(o.filled_avg_price),
          qty: Math.trunc(Number(o.filled_qty)),
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `deno task test`
Expected: PASS — all `alpaca.test.ts` tests green, incl. the guard test (no network hit).

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/_shared/alpaca.ts supabase/functions/_shared/alpaca.test.ts
git commit -m "feat(mvp2): Alpaca broker client with CLAUDE_AGENT_NO_BROKER guard (#220)"
```

---

## Task 4: `marketdata.ts` — daily bars + latest trade

**Files:**
- Create: `supabase/functions/_shared/marketdata.test.ts`
- Create: `supabase/functions/_shared/marketdata.ts`

- [ ] **Step 1: Write the failing tests**

Create `supabase/functions/_shared/marketdata.test.ts`:

```ts
import { assertEquals } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import { getDailyCloses, getLatestTradePrice } from "./marketdata.ts";

function setKeys() {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
}
function clearKeys() {
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
}

Deno.test("getDailyCloses returns ordered {date, close, high}", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/stocks/SPY/bars"), true);
    return Promise.resolve(jsonResponse({
      bars: [
        { t: "2026-06-03T04:00:00Z", o: 1, h: 401, l: 1, c: 400, v: 1 },
        { t: "2026-06-04T04:00:00Z", o: 1, h: 412, l: 1, c: 410, v: 1 },
      ],
      next_page_token: null,
    }));
  });
  try {
    const bars = await getDailyCloses("SPY", 250);
    assertEquals(bars.length, 2);
    assertEquals(bars[1], { date: "2026-06-04", close: 410, high: 412 });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestTradePrice parses trade.p", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/stocks/UPRO/trades/latest"), true);
    return Promise.resolve(jsonResponse({ trade: { p: 71.25, s: 10, t: "x" } }));
  });
  try {
    assertEquals(await getLatestTradePrice("UPRO"), 71.25);
  } finally {
    restore();
    clearKeys();
  }
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `deno task test`
Expected: FAIL — `./marketdata.ts` not found.

- [ ] **Step 3: Implement**

Create `supabase/functions/_shared/marketdata.ts`:

```ts
// Alpaca Market Data REST v2. Replaces yfinance. Uses the IEX feed (free).
import { getAlpacaConfig } from "./config.ts";

export interface DailyBar {
  date: string; // YYYY-MM-DD (UTC)
  close: number;
  high: number;
}

function headers() {
  const cfg = getAlpacaConfig();
  return {
    "APCA-API-KEY-ID": cfg.apiKeyId,
    "APCA-API-SECRET-KEY": cfg.apiSecretKey,
  };
}

// Fetch the most recent `count` daily bars, oldest-first. `count` should exceed
// the SMA window (e.g. 250 for a 200-DMA) to guarantee enough history.
export async function getDailyCloses(symbol: string, count: number): Promise<DailyBar[]> {
  const cfg = getAlpacaConfig();
  // Look back generously in calendar days to cover `count` trading days.
  const startMs = Date.now() - Math.ceil(count * 1.6) * 24 * 60 * 60 * 1000;
  const start = new Date(startMs).toISOString().slice(0, 10);
  const url =
    `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/bars` +
    `?timeframe=1Day&start=${start}&limit=10000&adjustment=raw&feed=iex`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET bars ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  const bars = Array.isArray(j.bars) ? j.bars : [];
  return bars.map((b: { t: string; c: number; h: number }) => ({
    date: String(b.t).slice(0, 10),
    close: Number(b.c),
    high: Number(b.h),
  }));
}

export async function getLatestTradePrice(symbol: string): Promise<number> {
  const cfg = getAlpacaConfig();
  const url =
    `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/trades/latest?feed=iex`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET latest trade ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  return Number(j.trade.p);
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `deno task test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/_shared/marketdata.ts supabase/functions/_shared/marketdata.test.ts
git commit -m "feat(mvp2): Alpaca market-data module (daily bars + latest trade) (#220)"
```

---

## Task 5: `db.ts` — Supabase persistence (integration-tested vs local Postgres)

**Files:**
- Create: `supabase/functions/_shared/db.test.ts`
- Create: `supabase/functions/_shared/db.ts`

The Supabase fluent client is awkward to mock meaningfully, and there is no
broker risk in DB code, so `db.ts` is tested against the **local** Supabase
Postgres (started in Plan 1). These tests are gated behind `RUN_DB_TESTS=1` and
run via `deno task test:db`; the default `deno task test` skips them.

- [ ] **Step 1: Write the failing tests**

Create `supabase/functions/_shared/db.test.ts`:

```ts
import { assertEquals } from "@std/assert";
import { createClient } from "@supabase/supabase-js";
import {
  getConfig,
  getLatestRegimeState,
  insertAuditLog,
  insertTrade,
  setConfig,
  updateAuditLog,
  upsertRegimeState,
} from "./db.ts";

const RUN = Deno.env.get("RUN_DB_TESTS") === "1";

function localClient() {
  // From `supabase status`: API URL + service_role key. Defaults below match a
  // standard local stack; override via env if your local ports differ.
  const url = Deno.env.get("SUPABASE_URL") ?? "http://127.0.0.1:54321";
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  return createClient(url, key, { auth: { persistSession: false } });
}

Deno.test({
  name: "regime_state upsert + getLatest (ON CONFLICT replaces same date)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await sb.from("regime_state").delete().eq("date", "2030-01-02");
    await upsertRegimeState(sb, {
      date: "2030-01-02",
      spyClose: 400,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: null,
      killSwitchActive: false,
      killSwitchFiredAt: null,
    });
    await upsertRegimeState(sb, {
      date: "2030-01-02",
      spyClose: 401,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: -0.1,
      killSwitchActive: true,
      killSwitchFiredAt: "2030-01-02T15:00:00Z",
    });
    const latest = await getLatestRegimeState(sb);
    assertEquals(latest?.current_state, "LONG");
    assertEquals(latest?.kill_switch_active, true);
    assertEquals(Number(latest?.spy_close), 401);
    await sb.from("regime_state").delete().eq("date", "2030-01-02");
  },
});

Deno.test({
  name: "insertTrade returns id; row persists",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const id = await insertTrade(sb, {
      symbol: "UPRO",
      side: "BUY",
      qty: 100,
      fillPrice: 70.5,
      fillTime: "2030-01-02T15:00:00Z",
      brokerOrderId: "o-test",
      reason: "regime_flip_long",
    });
    assertEquals(typeof id, "number");
    await sb.from("trades").delete().eq("id", id);
  },
});

Deno.test({
  name: "audit_log insert then update",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const id = await insertAuditLog(sb, {
      scriptName: "db-test",
      startedAt: "2030-01-02T15:00:00Z",
    });
    await updateAuditLog(sb, {
      id,
      finishedAt: "2030-01-02T15:00:01Z",
      outcome: "success",
      notes: "ok",
    });
    const { data } = await sb.from("audit_log").select("outcome").eq("id", id).single();
    assertEquals(data?.outcome, "success");
    await sb.from("audit_log").delete().eq("id", id);
  },
});

Deno.test({
  name: "bot_config get/set",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await setConfig(sb, "paused", "true");
    assertEquals(await getConfig(sb, "paused"), "true");
    await setConfig(sb, "paused", "false");
    assertEquals(await getConfig(sb, "paused"), "false");
  },
});
```

- [ ] **Step 2: Run to verify they fail**

Ensure local Supabase is up: `supabase start`, then export the creds it prints:
`export SUPABASE_URL=http://127.0.0.1:54321` and
`export SUPABASE_SERVICE_ROLE_KEY=<service_role key from 'supabase status'>`.
Run: `deno task test:db`
Expected: FAIL — `./db.ts` not found.

- [ ] **Step 3: Implement**

Create `supabase/functions/_shared/db.ts`:

```ts
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `deno task test:db`
Expected: PASS (all four DB tests). Also run `deno task test` and confirm the DB tests are skipped (ignored) there and everything else stays green.

- [ ] **Step 5: Commit**

```bash
git add supabase/functions/_shared/db.ts supabase/functions/_shared/db.test.ts
git commit -m "feat(mvp2): Supabase DB persistence layer (#220)"
```

---

## Plan 2 Self-Review (completed during authoring)

- **Spec coverage:** `alpaca.ts` → spec §3 broker client + §5 guard; `marketdata.ts` → §3/§4 (drop yfinance); `db.ts` → §3/§6 (incl. `bot_config`, `broker_order_id`); `notifications.ts` → §3 (with `notifyBrokerError` replacing `notify_tws_disconnected`); config accessors → §7.
- **Placeholder scan:** none — every step has complete code + a runnable command with expected output.
- **Type consistency:** `Fill`, `AlpacaClient`, `DailyBar`, `RegimeStateRow`, and the camelCase param objects (`upsertRegimeState`, `insertTrade`, …) are defined once and consumed consistently by the tests and (in Plan 3) the Edge Functions. The DB row reads use snake_case column names exactly as the schema defines them.
- **Guard check:** the dedicated guard test asserts mutating calls throw `BrokerCallBlockedError` with zero network hits — the invariant holds end-to-end.

## Definition of done (Plan 2)

- `deno task test` green (config, notifications, alpaca, marketdata; db tests skipped).
- `deno task test:db` green against local Supabase.
- Five commits landed.
- Ready for Plan 3 (Edge Functions + scheduling + rollout).
