import { assertEquals, assertRejects } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import {
  AlpacaError,
  BrokerCallBlockedError,
  createAlpacaClient,
  OrderTimeoutError,
} from "./alpaca.ts";
import { DataError } from "./num.ts";

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
  try {
    const fill = await createAlpacaClient().liquidate("UPRO", { timeoutMs: 1000, intervalMs: 1 });
    assertEquals(placedSide, "sell");
    assertEquals(placedQty, "100");
    assertEquals(fill, { orderId: "o9", fillPrice: 69.5, qty: 100, fillTime: "2026-06-05T15:00:00Z" });
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
    await assertRejects(() => c.placeMarketOrder({ symbol: "UPRO", side: "BUY", qty: 1 }), BrokerCallBlockedError);
    await assertRejects(() => c.liquidate("UPRO"), BrokerCallBlockedError);
    await assertRejects(() => c.cancelAllOrders(), BrokerCallBlockedError);
    assertEquals(networkHit, false);
  } finally {
    restore();
    clearKeys();
  }
});
