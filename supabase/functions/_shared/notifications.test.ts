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
    // Human-readable fields the n8n Discord node renders (parity with the
    // Python tools/notifications.py payloads).
    assertEquals(typeof body.message, "string");
    assertEquals((body.message as string).includes("Regime flip -> LONG"), true);
    assertEquals(body.title, "regime_flip LONG");
  } finally {
    restore();
    Deno.env.delete("N8N_WEBHOOK_URL");
  }
});
