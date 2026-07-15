import { assertEquals } from "@std/assert";
import { stubFetch } from "./test_helpers.ts";
import {
  notify,
  notifyBrokerError,
  notifyError,
  notifyKillSwitchFired,
  notifyPanic,
  notifyRegimeFlip,
  notifyStateDesync,
  notifyTradeFailed,
} from "./notifications.ts";

function stubWarn(): { calls: unknown[][]; restore: () => void } {
  const original = console.warn;
  const calls: unknown[][] = [];
  console.warn = (...args: unknown[]) => {
    calls.push(args);
  };
  return { calls, restore: () => (console.warn = original) };
}

Deno.test("notify posts JSON to the webhook", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let capturedUrl = "";
  let capturedBody: unknown = null;
  const restore = stubFetch(async (input, init) => {
    capturedUrl = typeof input === "string" ? input : input.toString();
    capturedBody = JSON.parse(String(init?.body));
    return new Response("ok", { status: 200 });
  });
  try {
    await notify({ event_type: "test", foo: 1, message: "hi" });
    assertEquals(capturedUrl, "http://localhost:5678/hook");
    assertEquals(capturedBody, { event_type: "test", foo: 1, message: "hi", content: "hi" });
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify is a no-op when URL unset", async () => {
  Deno.env.delete("NOTIFY_WEBHOOK_URL");
  let called = false;
  const restore = stubFetch(async () => {
    called = true;
    return new Response("ok");
  });
  const { restore: restoreWarn } = stubWarn(); // side-effect warn (#366); clean test output only
  try {
    await notify({ event_type: "test" });
    assertEquals(called, false);
  } finally {
    restoreWarn();
    restore();
  }
});

Deno.test("notify swallows fetch errors (never throws)", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const restore = stubFetch(() => Promise.reject(new Error("network down")));
  const { restore: restoreWarn } = stubWarn(); // side-effect warn (#366); clean test output only
  try {
    await notify({ event_type: "test" }); // must not throw
  } finally {
    restoreWarn();
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notifyRegimeFlip builds the structured payload", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
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
    // Human-readable field Discord renders directly as `content`; structured
    // fields are kept for any future JSON-consuming forwarder.
    assertEquals(typeof body.message, "string");
    assertEquals((body.message as string).includes("Regime flip -> LONG"), true);
    assertEquals(body.title, "regime_flip LONG");
    assertEquals(body.content, body.message);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

// ---------------------------------------------------------------------------
// Discord-native `content` field (#362): notify() derives it centrally from
// `event.message`, so every helper gets it for free.
// ---------------------------------------------------------------------------

Deno.test("notify: no message -> body has no content field, and is otherwise unchanged", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_i, init) => {
    body = JSON.parse(String(init?.body));
    return new Response("ok");
  });
  try {
    await notify({ event_type: "test", foo: 1 });
    assertEquals(body, { event_type: "test", foo: 1 });
    assertEquals("content" in body, false);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: content truncation boundary at exactly 2000 chars (untruncated)", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_i, init) => {
    body = JSON.parse(String(init?.body));
    return new Response("ok");
  });
  try {
    const message = "a".repeat(2000);
    await notify({ event_type: "test", message });
    assertEquals(body.content, message);
    assertEquals((body.content as string).length, 2000);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: content truncation boundary at 2001 chars (truncated to first 2000, message untouched)", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_i, init) => {
    body = JSON.parse(String(init?.body));
    return new Response("ok");
  });
  try {
    const message = "b".repeat(2001);
    await notify({ event_type: "test", message });
    assertEquals(body.content, "b".repeat(2000));
    assertEquals((body.content as string).length, 2000);
    // Structured `message` field carries the full text for forensics/forwarders.
    assertEquals(body.message, message);
    assertEquals((body.message as string).length, 2001);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: content truncation is codepoint-safe across an astral-character boundary", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_i, init) => {
    body = JSON.parse(String(init?.body));
    return new Response("ok");
  });
  try {
    // 1999 ascii chars + one astral codepoint (🛑, a surrogate pair in UTF-16)
    // straddling the 2000-codepoint cut, then more filler.
    const message = "c".repeat(1999) + "🛑" + "d".repeat(50);
    await notify({ event_type: "test", message });
    const content = body.content as string;
    const codepoints = [...content];
    assertEquals(codepoints.length, 2000);
    assertEquals(codepoints[1999], "🛑");
    // No lone surrogate: re-encoding the codepoints back to a string round-trips
    // without a replacement character, and the string length matches (2 UTF-16
    // units for the astral char + 1999 ascii = 2001).
    assertEquals(content, "c".repeat(1999) + "🛑");
    assertEquals(content.length, 2001);
    assertEquals(content.includes("�"), false);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: empty-string message produces no content field", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_i, init) => {
    body = JSON.parse(String(init?.body));
    return new Response("ok");
  });
  try {
    await notify({ event_type: "test", message: "" });
    assertEquals("content" in body, false);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

// ---------------------------------------------------------------------------
// #366: notify() failures must be visible via console.warn — unset-secret
// skip, fetch rejection (redacted), and non-2xx webhook responses.
// ---------------------------------------------------------------------------

Deno.test("notify: unset secret warns once with event_type and makes zero fetch calls", async () => {
  Deno.env.delete("NOTIFY_WEBHOOK_URL");
  let fetchCalls = 0;
  const restoreFetch = stubFetch(async () => {
    fetchCalls++;
    return new Response("ok");
  });
  const { calls, restore: restoreWarn } = stubWarn();
  try {
    await notify({ event_type: "test_event" }); // must not throw
    assertEquals(fetchCalls, 0);
    assertEquals(calls.length, 1);
    const joined = calls[0].map((a) => String(a)).join(" ");
    assertEquals(joined.includes("NOTIFY_WEBHOOK_URL unset"), true);
    assertEquals(joined.includes("test_event"), true);
  } finally {
    restoreWarn();
    restoreFetch();
  }
});

Deno.test("notify: fetch rejection warns once and redacts the webhook URL", async () => {
  const stubUrl = "http://localhost:5678/hook";
  Deno.env.set("NOTIFY_WEBHOOK_URL", stubUrl);
  const restoreFetch = stubFetch(() =>
    Promise.reject(new TypeError(`error sending request for url (${stubUrl})`))
  );
  const { calls, restore: restoreWarn } = stubWarn();
  try {
    await notify({ event_type: "test_event" }); // must not throw
    assertEquals(calls.length, 1);
    const joined = calls[0].map((a) => String(a)).join(" ");
    assertEquals(joined.includes(stubUrl), false);
    assertEquals(joined.includes("test_event"), true);
  } finally {
    restoreWarn();
    restoreFetch();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: non-2xx response warns with status and truncated body snippet", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const restoreFetch = stubFetch(async () => new Response("x".repeat(300), { status: 400 }));
  const { calls, restore: restoreWarn } = stubWarn();
  try {
    await notify({ event_type: "test_event" }); // must not throw
    assertEquals(calls.length, 1);
    const joined = calls[0].map((a) => String(a)).join(" ");
    assertEquals(joined.includes("400"), true);
    assertEquals(joined.includes("test_event"), true);
    assertEquals(joined.includes("x".repeat(200)), true);
    assertEquals(joined.includes("x".repeat(201)), false);
    assertEquals(joined.includes("http://localhost:5678/hook"), false);
  } finally {
    restoreWarn();
    restoreFetch();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: non-2xx body containing the webhook URL straddling the snippet boundary never leaks a URL fragment", async () => {
  const stubUrl = "http://localhost:5678/hook/tok_9f8e7d6c5b4a3210SECRET";
  Deno.env.set("NOTIFY_WEBHOOK_URL", stubUrl);
  // Position the full URL so it straddles the 200-codepoint snippet cutoff.
  // Redacting AFTER truncating (the bug) leaves an un-redacted prefix of the
  // URL -- including part of the secret token -- inside the logged snippet.
  const prefixLen = 200 - Math.floor(stubUrl.length / 2);
  const body = "z".repeat(prefixLen) + stubUrl;
  const restoreFetch = stubFetch(async () => new Response(body, { status: 400 }));
  const { calls, restore: restoreWarn } = stubWarn();
  try {
    await notify({ event_type: "probe_token" }); // must not throw
    assertEquals(calls.length, 1);
    const joined = calls[0].map((a) => String(a)).join(" ");
    assertEquals(joined.includes(stubUrl), false);
    assertEquals(joined.includes("tok_"), false);
    assertEquals(joined.includes("localhost"), false);
    assertEquals(joined.includes("probe_token"), true);
  } finally {
    restoreWarn();
    restoreFetch();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: non-2xx body snippet truncation is codepoint-safe across an astral-character boundary", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  // 199 ascii chars + one astral codepoint (🛑, a surrogate pair in UTF-16)
  // straddling the 200-codepoint snippet cut, then more filler.
  const body = "e".repeat(199) + "🛑" + "f".repeat(50);
  const restoreFetch = stubFetch(async () => new Response(body, { status: 400 }));
  const { calls, restore: restoreWarn } = stubWarn();
  try {
    await notify({ event_type: "test_event" });
    assertEquals(calls.length, 1);
    const joined = calls[0].map((a) => String(a)).join(" ");
    // No lone surrogate leaks into the log line, and the snippet is cut at
    // exactly the astral codepoint (not mid-surrogate-pair).
    assertEquals(joined.includes("�"), false);
    assertEquals(joined.includes("e".repeat(199) + "🛑"), true);
    assertEquals(joined.includes("f".repeat(50)), false);
  } finally {
    restoreWarn();
    restoreFetch();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("notify: 2xx response emits no warn", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const restoreFetch = stubFetch(async () => new Response("ok", { status: 200 }));
  const { calls, restore: restoreWarn } = stubWarn();
  try {
    await notify({ event_type: "test_event" });
    assertEquals(calls.length, 0);
  } finally {
    restoreWarn();
    restoreFetch();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("all seven notify helpers carry content === message", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const bodies: Record<string, unknown>[] = [];
  const restore = stubFetch(async (_i, init) => {
    bodies.push(JSON.parse(String(init?.body)));
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
    });
    await notifyKillSwitchFired({
      ticker: "UPRO",
      drawdownPct: 0.3,
      refHigh: 100,
      lastPrice: 70,
      qty: 100,
      fillPrice: 70,
    });
    await notifyTradeFailed({ symbol: "UPRO", side: "BUY", qty: 10, reason: "insufficient funds" });
    await notifyStateDesync({
      dbState: "CASH",
      brokerState: "LONG",
      symbol: "UPRO",
      actionTaken: "protected",
    });
    await notifyBrokerError({ context: "getClock", errorMsg: "timeout" });
    await notifyError("something went wrong");
    await notifyPanic({ action: "pause", result: "ok" });

    assertEquals(bodies.length, 7);
    for (const body of bodies) {
      assertEquals(typeof body.message, "string");
      assertEquals(body.content, body.message);
    }
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});
