import { assertEquals, assertRejects } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import {
  AlpacaError,
  BrokerCallBlockedError,
  createAlpacaClient,
  OrderRejectedError,
  OrderTimeoutError,
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
  liftBrokerGuard();
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
