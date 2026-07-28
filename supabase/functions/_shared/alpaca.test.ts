import { assertEquals, assertRejects } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import {
  AlpacaError,
  BrokerCallBlockedError,
  checkPaperOnly,
  createAlpacaClient,
  OrderRejectedError,
  OrderTimeoutError,
  PaperGuardFailedError,
} from "./alpaca.ts";
import { DataError } from "./num.ts";

// The test harness runs with CLAUDE_AGENT_NO_BROKER=1 (deno task test, #268).
// Capture the ambient value so clearKeys() can restore it after the few tests
// that must lift it.
const ORIGINAL_NO_BROKER = Deno.env.get("CLAUDE_AGENT_NO_BROKER");

function setKeys() {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_PAPER", "true");
}
// ONLY for tests that deliberately exercise the guarded mutating helpers'
// (stub-fetched) HTTP path. Everything else runs with the guard env var as-is,
// so a forgotten fetch stub fails fast instead of reaching the network (#268).
function liftBrokerGuard() {
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
}
function clearKeys() {
  for (const k of ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_PAPER"]) {
    Deno.env.delete(k);
  }
  if (ORIGINAL_NO_BROKER === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
  else Deno.env.set("CLAUDE_AGENT_NO_BROKER", ORIGINAL_NO_BROKER);
}

Deno.test("getClock maps is_open", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).endsWith("/v2/clock"), true);
    return Promise.resolve(
      jsonResponse({ is_open: true, timestamp: "t", next_close: "2026-07-27T20:00:00-04:00" }),
    );
  });
  try {
    const client = createAlpacaClient();
    assertEquals((await client.getClock()).isOpen, true);
  } finally {
    restore();
    clearKeys();
  }
});

// #475 T4 (spec §7 must-fix round 2 finding 1): getClock() additively gains
// nextClose, parsed via requireNumber/Date.parse. Existing callers
// (daily-check, kill-switch) destructure only isOpen and are unaffected.
Deno.test("getClock: parses next_close as epoch ms via Date.parse", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({
      is_open: true,
      timestamp: "2026-07-27T15:07:00-04:00",
      next_close: "2026-07-27T16:00:00-04:00",
    }))
  );
  try {
    const client = createAlpacaClient();
    const clock = await client.getClock();
    assertEquals(clock.nextClose, Date.parse("2026-07-27T16:00:00-04:00"));
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getClock: missing next_close is a hard error (DataError), never silently false", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({ is_open: true, timestamp: "t", next_close: null }))
  );
  try {
    await assertRejects(() => createAlpacaClient().getClock(), DataError, "next_close");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getClock: unparseable next_close is a hard error", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({ is_open: true, timestamp: "t", next_close: "not-a-date" }))
  );
  try {
    await assertRejects(() => createAlpacaClient().getClock(), DataError, "next_close");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getCalendar returns session dates in range", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/calendar?start=2026-06-01&end=2026-06-05"), true);
    return Promise.resolve(jsonResponse([
      { date: "2026-06-01", open: "09:30", close: "16:00" },
      { date: "2026-06-02", open: "09:30", close: "16:00" },
      { date: "2026-06-04", open: "09:30", close: "16:00" },
      { date: "2026-06-05", open: "09:30", close: "16:00" },
    ]));
  });
  try {
    assertEquals(await createAlpacaClient().getCalendar("2026-06-01", "2026-06-05"), [
      "2026-06-01",
      "2026-06-02",
      "2026-06-04",
      "2026-06-05",
    ]);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getCalendar throws AlpacaError on non-ok response", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "boom" }, 500)));
  try {
    await assertRejects(
      () => createAlpacaClient().getCalendar("2026-06-01", "2026-06-05"),
      AlpacaError,
    );
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
  restore = stubFetch(() =>
    Promise.resolve(jsonResponse({ message: "position does not exist" }, 404))
  );
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
  liftBrokerGuard();
  try {
    const fill = await createAlpacaClient().placeMarketOrder(
      { symbol: "UPRO", side: "BUY", qty: 100 },
      { timeoutMs: 1000, intervalMs: 1 },
    );
    assertEquals(fill, {
      orderId: "o1",
      fillPrice: 70.5,
      qty: 100,
      fillTime: "2026-06-05T14:00:00Z",
    });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder times out, post-cancel status still live -> cancel UNVERIFIED", async () => {
  // The post-DELETE re-poll shows the order still "accepted" (a live status) —
  // an immediate re-poll can legitimately race the broker's own cancel
  // processing (e.g. pending_cancel), so this is classified UNVERIFIED per
  // #262/#342 rather than assumed cancelled.
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
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" })); // still live
  });
  liftBrokerGuard();
  try {
    const err = await assertRejects(
      () =>
        createAlpacaClient().placeMarketOrder(
          { symbol: "UPRO", side: "BUY", qty: 100 },
          { timeoutMs: 5, intervalMs: 1 },
        ),
      OrderTimeoutError,
    );
    assertEquals(cancelled, true);
    assertEquals(err.message.includes("cancel UNVERIFIED"), true);
    assertEquals(err.message.includes("may still be live"), true);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder times out, post-cancel status canceled -> verified-dead, no UNVERIFIED", async () => {
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
    if (cancelled) {
      return Promise.resolve(jsonResponse({ id: "o1", status: "canceled", filled_qty: "0" }));
    }
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
  });
  liftBrokerGuard();
  try {
    const err = await assertRejects(
      () =>
        createAlpacaClient().placeMarketOrder(
          { symbol: "UPRO", side: "BUY", qty: 100 },
          { timeoutMs: 5, intervalMs: 1 },
        ),
      OrderTimeoutError,
    );
    assertEquals(cancelled, true);
    assertEquals(err.message.includes("cancelled"), true);
    assertEquals(err.message.includes("UNVERIFIED"), false);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder times out, post-cancel status rejected (no fill) -> verified-dead, no UNVERIFIED", async () => {
  // rejected counts as verified: the order cannot be live, which is the
  // property being verified.
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
    if (cancelled) {
      return Promise.resolve(jsonResponse({ id: "o1", status: "rejected", filled_qty: "0" }));
    }
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
  });
  liftBrokerGuard();
  try {
    const err = await assertRejects(
      () =>
        createAlpacaClient().placeMarketOrder(
          { symbol: "UPRO", side: "BUY", qty: 100 },
          { timeoutMs: 5, intervalMs: 1 },
        ),
      OrderTimeoutError,
    );
    assertEquals(cancelled, true);
    assertEquals(err.message.includes("UNVERIFIED"), false);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder times out, post-cancel status GET throws -> cancel UNVERIFIED", async () => {
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
    if (cancelled) {
      return Promise.resolve(jsonResponse({ message: "boom" }, 500));
    }
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
  });
  liftBrokerGuard();
  try {
    const err = await assertRejects(
      () =>
        createAlpacaClient().placeMarketOrder(
          { symbol: "UPRO", side: "BUY", qty: 100 },
          { timeoutMs: 5, intervalMs: 1 },
        ),
      OrderTimeoutError,
    );
    assertEquals(cancelled, true);
    assertEquals(err.message.includes("cancel UNVERIFIED"), true);
    assertEquals(err.message.includes("may still be live"), true);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder throws OrderRejectedError promptly on a rejected order", async () => {
  setKeys();
  let polls = 0;
  const restore = stubFetch((i, init) => {
    const url = urlOf(i);
    if (init?.method === "POST" && url.endsWith("/v2/orders")) {
      return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
    }
    polls += 1;
    return Promise.resolve(jsonResponse({
      id: "o1",
      status: "rejected",
      reject_reason: "insufficient buying power",
      filled_qty: "0",
    }));
  });
  liftBrokerGuard();
  try {
    // timeoutMs 30s + intervalMs 1s: if the loop did not break on the terminal
    // status this test would spin for the full 30s.
    await assertRejects(
      () =>
        createAlpacaClient().placeMarketOrder(
          { symbol: "UPRO", side: "BUY", qty: 100 },
          { timeoutMs: 30_000, intervalMs: 1000 },
        ),
      OrderRejectedError,
      "rejected",
    );
    assertEquals(polls, 1); // broke on the first poll, no spin
  } finally {
    restore();
    clearKeys();
  }
});

for (const terminalStatus of ["canceled", "expired"]) {
  Deno.test(
    `placeMarketOrder throws OrderRejectedError promptly on a broker-initiated '${terminalStatus}' with zero fill (#269 finding 15b)`,
    async () => {
      setKeys();
      let polls = 0;
      const restore = stubFetch((i, init) => {
        const url = urlOf(i);
        if (init?.method === "POST" && url.endsWith("/v2/orders")) {
          return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
        }
        polls += 1;
        return Promise.resolve(jsonResponse({
          id: "o1",
          status: terminalStatus,
          filled_qty: "0",
        }));
      });
      liftBrokerGuard();
      try {
        // timeoutMs 30s + intervalMs 1s: if the loop did not break on the
        // terminal status this test would spin for the full 30s.
        await assertRejects(
          () =>
            createAlpacaClient().placeMarketOrder(
              { symbol: "UPRO", side: "BUY", qty: 100 },
              { timeoutMs: 30_000, intervalMs: 1000 },
            ),
          OrderRejectedError,
          terminalStatus,
        );
        assertEquals(polls, 1); // broke on the first poll, no spin
      } finally {
        restore();
        clearKeys();
      }
    },
  );
}

Deno.test("placeMarketOrder timeout race: order filled after cancel -> returns the fill", async () => {
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
    if (cancelled) {
      // The order (partially) filled in the race window before the cancel took
      // effect: 40 of 100 shares are owned and must be reported to the caller.
      return Promise.resolve(jsonResponse({
        id: "o1",
        status: "canceled",
        filled_qty: "40",
        filled_avg_price: "70.1",
        filled_at: null,
        updated_at: "2026-06-05T14:00:01Z",
      }));
    }
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" })); // never fills in time
  });
  liftBrokerGuard();
  try {
    const fill = await createAlpacaClient().placeMarketOrder(
      { symbol: "UPRO", side: "BUY", qty: 100 },
      { timeoutMs: 5, intervalMs: 1 },
    );
    assertEquals(cancelled, true);
    assertEquals(fill, {
      orderId: "o1",
      fillPrice: 70.1,
      qty: 40,
      fillTime: "2026-06-05T14:00:01Z",
    });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeMarketOrder validates side and qty", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({})));
  liftBrokerGuard();
  try {
    const c = createAlpacaClient();
    await assertRejects(
      // deno-lint-ignore no-explicit-any
      () => c.placeMarketOrder({ symbol: "UPRO", side: "HOLD" as any, qty: 1 }),
      Error,
      "side",
    );
    await assertRejects(
      () => c.placeMarketOrder({ symbol: "UPRO", side: "BUY", qty: 0 }),
      Error,
      "qty",
    );
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("liquidate returns null with no position", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "no position" }, 404)));
  liftBrokerGuard();
  try {
    assertEquals(await createAlpacaClient().liquidate("UPRO"), null);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("liquidate sells the full position and returns the fill", async () => {
  setKeys();
  let placedSide = "";
  let placedQty = "";
  const restore = stubFetch((i, init) => {
    const url = urlOf(i);
    if (url.includes("/v2/positions/")) {
      return Promise.resolve(jsonResponse({ qty: "100" }));
    }
    if (init?.method === "POST" && url.endsWith("/v2/orders")) {
      const body = JSON.parse(String(init?.body));
      placedSide = body.side;
      placedQty = body.qty;
      return Promise.resolve(jsonResponse({ id: "o9", status: "accepted" }));
    }
    return Promise.resolve(jsonResponse({
      id: "o9",
      status: "filled",
      filled_avg_price: "69.5",
      filled_qty: "100",
      filled_at: "2026-06-05T15:00:00Z",
    }));
  });
  liftBrokerGuard();
  try {
    const fill = await createAlpacaClient().liquidate("UPRO", { timeoutMs: 1000, intervalMs: 1 });
    assertEquals(placedSide, "sell");
    assertEquals(placedQty, "100");
    assertEquals(fill, {
      orderId: "o9",
      fillPrice: 69.5,
      qty: 100,
      fillTime: "2026-06-05T15:00:00Z",
    });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("cancelAllOrders returns count when all cancels succeed", async () => {
  setKeys();
  const restore = stubFetch((i, init) => {
    assertEquals(init?.method, "DELETE");
    assertEquals(urlOf(i).endsWith("/v2/orders"), true);
    return Promise.resolve(jsonResponse(
      [{ id: "a", status: 200 }, { id: "b", status: 200 }],
      207,
    ));
  });
  liftBrokerGuard();
  try {
    assertEquals(await createAlpacaClient().cancelAllOrders(), 2);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("cancelAllOrders throws when any order fails to cancel", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse(
      [{ id: "a", status: 200 }, { id: "b", status: 500 }],
      207,
    ))
  );
  liftBrokerGuard();
  try {
    // A partial cancel must not be reported as success.
    await assertRejects(() => createAlpacaClient().cancelAllOrders(), AlpacaError, "failed");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getAccountValue throws on non-numeric equity", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ equity: null })));
  try {
    await assertRejects(() => createAlpacaClient().getAccountValue(), DataError, "equity");
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
    await assertRejects(
      () => c.placeMarketOrder({ symbol: "UPRO", side: "BUY", qty: 1 }),
      BrokerCallBlockedError,
    );
    await assertRejects(() => c.liquidate("UPRO"), BrokerCallBlockedError);
    await assertRejects(() => c.cancelAllOrders(), BrokerCallBlockedError);
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});

// ---------------------------------------------------------------------------
// #475 T5: paper-only guard, Layers A and B (spec §8.3)
// ---------------------------------------------------------------------------

Deno.test("checkPaperOnly: passes when paper=true and tradingBaseUrl is the paper host", () => {
  checkPaperOnly("test-op", {
    paper: true,
    tradingBaseUrl: "https://paper-api.alpaca.markets",
  });
});

Deno.test("checkPaperOnly: throws PaperGuardFailedError when paper=false", () => {
  try {
    checkPaperOnly("test-op", { paper: false, tradingBaseUrl: "https://api.alpaca.markets" });
    throw new Error("expected checkPaperOnly to throw");
  } catch (e) {
    assertEquals(e instanceof PaperGuardFailedError, true);
  }
});

// The URL check is load-bearing (spec §8.3): even if `paper` were somehow
// true, a non-paper trading host must still fail closed -- a mis-set boolean
// alone cannot defeat this guard.
Deno.test("checkPaperOnly: throws PaperGuardFailedError on a non-paper URL even with paper=true", () => {
  try {
    checkPaperOnly("test-op", { paper: true, tradingBaseUrl: "https://api.alpaca.markets" });
    throw new Error("expected checkPaperOnly to throw");
  } catch (e) {
    assertEquals(e instanceof PaperGuardFailedError, true);
  }
});

Deno.test("createAlpacaClient(): default client has no paper check (existing callers untouched)", async () => {
  setKeys();
  Deno.env.set("ALPACA_PAPER", "false"); // live config -- daily-check/kill-switch/panic shape
  liftBrokerGuard();
  const restore = stubFetch((_i, init) => {
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(jsonResponse({}));
  });
  try {
    const c = createAlpacaClient();
    // cancelAllOrders reaches the network (no PaperGuardFailedError) -- the
    // default client (no opts) never opts into the paper-only layer.
    assertEquals(await c.cancelAllOrders(), 0);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("createAlpacaClient({paperOnly:true}): throws PaperGuardFailedError when ALPACA_PAPER=false", async () => {
  setKeys();
  Deno.env.set("ALPACA_PAPER", "false");
  liftBrokerGuard();
  let networkHit = false;
  const restore = stubFetch(() => {
    networkHit = true;
    return Promise.resolve(jsonResponse({}));
  });
  try {
    const c = createAlpacaClient({ paperOnly: true });
    await assertRejects(() => c.cancelAllOrders(), PaperGuardFailedError);
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("createAlpacaClient({paperOnly:true}): checkGuard still fires first (precedence preserved)", async () => {
  setKeys();
  Deno.env.set("ALPACA_PAPER", "false"); // would also fail the paper check
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  const restore = stubFetch(() => Promise.resolve(jsonResponse({})));
  try {
    const c = createAlpacaClient({ paperOnly: true });
    // BrokerCallBlockedError must win over PaperGuardFailedError.
    await assertRejects(() => c.cancelAllOrders(), BrokerCallBlockedError);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("createAlpacaClient({paperOnly:true}): placeMarketOrder honors the paper-only guard too", async () => {
  setKeys();
  Deno.env.set("ALPACA_PAPER", "false");
  liftBrokerGuard();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({})));
  try {
    const c = createAlpacaClient({ paperOnly: true });
    await assertRejects(
      () => c.placeMarketOrder({ symbol: "SPY", side: "BUY", qty: 1 }),
      PaperGuardFailedError,
    );
  } finally {
    restore();
    clearKeys();
  }
});

// Layer B: the paper-account marker [to verify] could not be confirmed
// against a live /v2/account response in this agent session (no paper
// credentials present) -- ships fail-closed per the spec's own fallback.
Deno.test("assertPaperAccount: fails closed (marker unconfirmed) even on a paper-configured client", async () => {
  setKeys();
  liftBrokerGuard();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({ account_number: "PA000", equity: "100000" }))
  );
  try {
    const c = createAlpacaClient({ paperOnly: true });
    await assertRejects(() => c.assertPaperAccount(), PaperGuardFailedError);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("assertPaperAccount: checkGuard fires first under CLAUDE_AGENT_NO_BROKER", async () => {
  setKeys();
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ account_number: "PA000" })));
  try {
    const c = createAlpacaClient({ paperOnly: true });
    await assertRejects(() => c.assertPaperAccount(), BrokerCallBlockedError);
  } finally {
    restore();
    clearKeys();
  }
});

// ---------------------------------------------------------------------------
// #475 T6: order helpers (spec §7) -- placeBracketOrder, placeOcoExitPair,
// cancelOrder, getAssetShortability.
// ---------------------------------------------------------------------------

Deno.test("placeBracketOrder: posts order_class=bracket with take_profit/stop_loss legs, polls to fill", async () => {
  setKeys();
  let postedBody: Record<string, unknown> = {};
  let polls = 0;
  const restore = stubFetch((i, init) => {
    const url = urlOf(i);
    if (init?.method === "POST" && url.endsWith("/v2/orders")) {
      postedBody = JSON.parse(String(init.body));
      return Promise.resolve(jsonResponse({ id: "b1", status: "accepted" }));
    }
    polls += 1;
    if (polls < 2) return Promise.resolve(jsonResponse({ id: "b1", status: "accepted" }));
    return Promise.resolve(jsonResponse({
      id: "b1",
      status: "filled",
      filled_avg_price: "550.10",
      filled_qty: "18",
      filled_at: "2026-07-27T15:00:00Z",
    }));
  });
  liftBrokerGuard();
  try {
    const fill = await createAlpacaClient().placeBracketOrder(
      { symbol: "SPY", side: "BUY", qty: 18, takeProfitPrice: 554.5, stopLossPrice: 547.75 },
      { timeoutMs: 1000, intervalMs: 1 },
    );
    assertEquals(fill.qty, 18);
    assertEquals(postedBody.order_class, "bracket");
    assertEquals(postedBody.type, "market");
    assertEquals(postedBody.time_in_force, "day");
    assertEquals(postedBody.side, "buy");
    assertEquals((postedBody.take_profit as { limit_price: string }).limit_price, "554.5");
    assertEquals((postedBody.stop_loss as { stop_price: string }).stop_price, "547.75");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeBracketOrder: guarded (BrokerCallBlockedError before any fetch)", async () => {
  setKeys();
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  let networkHit = false;
  const restore = stubFetch(() => {
    networkHit = true;
    return Promise.resolve(jsonResponse({}));
  });
  try {
    await assertRejects(
      () =>
        createAlpacaClient().placeBracketOrder({
          symbol: "SPY",
          side: "BUY",
          qty: 1,
          takeProfitPrice: 100,
          stopLossPrice: 90,
        }),
      BrokerCallBlockedError,
    );
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeBracketOrder: paper-only guard fires on an opted-in client", async () => {
  setKeys();
  Deno.env.set("ALPACA_PAPER", "false");
  liftBrokerGuard();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({})));
  try {
    await assertRejects(
      () =>
        createAlpacaClient({ paperOnly: true }).placeBracketOrder({
          symbol: "SPY",
          side: "BUY",
          qty: 1,
          takeProfitPrice: 100,
          stopLossPrice: 90,
        }),
      PaperGuardFailedError,
    );
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeBracketOrder: propagates OrderTimeoutError via the shared poller", async () => {
  setKeys();
  const restore = stubFetch((i, init) => {
    const url = urlOf(i);
    if (init?.method === "POST" && url.endsWith("/v2/orders")) {
      return Promise.resolve(jsonResponse({ id: "b1", status: "accepted" }));
    }
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(jsonResponse({ id: "b1", status: "accepted" }));
  });
  liftBrokerGuard();
  try {
    await assertRejects(
      () =>
        createAlpacaClient().placeBracketOrder(
          { symbol: "SPY", side: "SELL", qty: 5, takeProfitPrice: 90, stopLossPrice: 110 },
          { timeoutMs: 5, intervalMs: 1 },
        ),
      OrderTimeoutError,
    );
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeOcoExitPair: posts order_class=oco with the closing side and both legs, no polling", async () => {
  setKeys();
  let postedBody: Record<string, unknown> = {};
  const restore = stubFetch((_i, init) => {
    postedBody = JSON.parse(String(init?.body));
    return Promise.resolve(jsonResponse({ id: "oco1", status: "accepted" }));
  });
  liftBrokerGuard();
  try {
    const result = await createAlpacaClient().placeOcoExitPair({
      symbol: "SPY",
      side: "SELL",
      qty: 18,
      takeProfitPrice: 554.5,
      stopLossPrice: 547.75,
    });
    assertEquals(result.orderId, "oco1");
    assertEquals(postedBody.order_class, "oco");
    assertEquals(postedBody.side, "sell");
    assertEquals(postedBody.limit_price, "554.5");
    assertEquals((postedBody.stop_loss as { stop_price: string }).stop_price, "547.75");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("placeOcoExitPair: guarded (BrokerCallBlockedError before any fetch)", async () => {
  setKeys();
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  let networkHit = false;
  const restore = stubFetch(() => {
    networkHit = true;
    return Promise.resolve(jsonResponse({}));
  });
  try {
    await assertRejects(
      () =>
        createAlpacaClient().placeOcoExitPair({
          symbol: "SPY",
          side: "SELL",
          qty: 1,
          takeProfitPrice: 100,
          stopLossPrice: 90,
        }),
      BrokerCallBlockedError,
    );
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("cancelOrder: DELETE then verifies terminal status", async () => {
  setKeys();
  let deleted = false;
  const restore = stubFetch((_i, init) => {
    if (init?.method === "DELETE") {
      deleted = true;
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(jsonResponse({ id: "o1", status: "canceled" }));
  });
  liftBrokerGuard();
  try {
    await createAlpacaClient().cancelOrder("o1");
    assertEquals(deleted, true);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("cancelOrder: throws when the post-cancel status is still live (unverified)", async () => {
  setKeys();
  const restore = stubFetch((_i, init) => {
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(jsonResponse({ id: "o1", status: "accepted" }));
  });
  liftBrokerGuard();
  try {
    await assertRejects(() => createAlpacaClient().cancelOrder("o1"), AlpacaError);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("cancelOrder: guarded (BrokerCallBlockedError before any fetch)", async () => {
  setKeys();
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  let networkHit = false;
  const restore = stubFetch(() => {
    networkHit = true;
    return Promise.resolve(jsonResponse({}));
  });
  try {
    await assertRejects(() => createAlpacaClient().cancelOrder("o1"), BrokerCallBlockedError);
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getAssetShortability: parses shortable/easy_to_borrow, unguarded read", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/assets/SPY"), true);
    return Promise.resolve(jsonResponse({ shortable: true, easy_to_borrow: false }));
  });
  try {
    const result = await createAlpacaClient().getAssetShortability("SPY");
    assertEquals(result, { shortable: true, easyToBorrow: false });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getAssetShortability: throws AlpacaError on non-ok response", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "not found" }, 404)));
  try {
    await assertRejects(() => createAlpacaClient().getAssetShortability("SPY"), AlpacaError);
  } finally {
    restore();
    clearKeys();
  }
});

// ---------------------------------------------------------------------------
// #475 T11: listFilledOrdersSince / listOpenOrderIds (reconciliation contract)
// ---------------------------------------------------------------------------

Deno.test("listFilledOrdersSince: filters to status=filled, maps to Fill[]", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/orders?status=closed&symbols=SPY"), true);
    assertEquals(urlOf(i).includes("after="), true);
    return Promise.resolve(jsonResponse([
      {
        id: "leg1",
        side: "sell",
        status: "filled",
        filled_avg_price: "554.50",
        filled_qty: "18",
        filled_at: "2026-07-27T15:00:00Z",
      },
      { id: "leg2", side: "sell", status: "canceled", filled_qty: "0" },
    ]));
  });
  try {
    const fills = await createAlpacaClient().listFilledOrdersSince(
      "SPY",
      "2026-07-27T14:00:00Z",
    );
    assertEquals(fills, [{
      orderId: "leg1",
      side: "SELL",
      fillPrice: 554.5,
      qty: 18,
      fillTime: "2026-07-27T15:00:00Z",
    }]);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("listFilledOrdersSince: throws AlpacaError on non-ok response", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "boom" }, 500)));
  try {
    await assertRejects(
      () => createAlpacaClient().listFilledOrdersSince("SPY", "2026-07-27T14:00:00Z"),
      AlpacaError,
    );
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("listOpenOrderIds: returns broker order ids still resting", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/orders?status=open&symbols=SPY"), true);
    return Promise.resolve(jsonResponse([{ id: "leg1" }, { id: "leg2" }]));
  });
  try {
    assertEquals(await createAlpacaClient().listOpenOrderIds("SPY"), ["leg1", "leg2"]);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("listOpenOrderIds: empty when no resting orders", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse([])));
  try {
    assertEquals(await createAlpacaClient().listOpenOrderIds("SPY"), []);
  } finally {
    restore();
    clearKeys();
  }
});
