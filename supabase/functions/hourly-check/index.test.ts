// HTTP-layer auth tests for hourly-check (#475 T12), mirroring
// daily-check/index.test.ts exactly. The pipeline runner is injected -- no
// Alpaca calls.
import { assertEquals } from "@std/assert";
import { handleHourlyCheck } from "./handler.ts";

const BASE = "https://example.test/hourly-check";

// ---------------------------------------------------------------------------
// JWT helpers (same as auth.test.ts -- real base64url encoding)
// ---------------------------------------------------------------------------
function base64url(obj: Record<string, unknown>): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function makeJwt(payload: Record<string, unknown>): string {
  const header = base64url({ alg: "HS256", typ: "JWT" });
  const body = base64url(payload);
  return `${header}.${body}.fake-sig`;
}

const SERVICE_ROLE_JWT = makeJwt({ role: "service_role", iss: "supabase" });
const ANON_JWT = makeJwt({ role: "anon", iss: "supabase" });

function req(opts: { auth?: string } = {}): Request {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (opts.auth !== undefined) headers.set("Authorization", opts.auth);
  return new Request(BASE, { method: "POST", headers });
}

function makeRun(outcome = "success") {
  let called = false;
  const run = () => {
    called = true;
    return Promise.resolve(outcome);
  };
  return { run, wasCalled: () => called };
}

function makeFlush(order: string[], opts: { reject?: boolean } = {}) {
  let called = false;
  const flush = () => {
    called = true;
    order.push("flush");
    return opts.reject ? Promise.reject(new Error("flush failed")) : Promise.resolve();
  };
  return { flush, wasCalled: () => called };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

Deno.test("service_role JWT -> 200 with outcome, pipeline called", async () => {
  const { run, wasCalled } = makeRun("success");
  const noopFlush = () => Promise.resolve();
  const res = await handleHourlyCheck(req({ auth: `Bearer ${SERVICE_ROLE_JWT}` }), run, noopFlush);
  assertEquals(res.status, 200);
  assertEquals(await res.json(), { outcome: "success" });
  assertEquals(wasCalled(), true);
});

Deno.test("anon JWT -> 401, pipeline never called", async () => {
  const { run, wasCalled } = makeRun();
  const res = await handleHourlyCheck(req({ auth: `Bearer ${ANON_JWT}` }), run);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});

Deno.test("absent Authorization header -> 401, pipeline never called", async () => {
  const { run, wasCalled } = makeRun();
  const res = await handleHourlyCheck(req(), run);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});

Deno.test("malformed bearer -> 401, pipeline never called", async () => {
  const { run, wasCalled } = makeRun();
  const res = await handleHourlyCheck(req({ auth: "Bearer notajwt" }), run);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});

// ---------------------------------------------------------------------------
// Outbox flush hook: injected as a third parameter, called after run()
// completes and before the Response is built -- never inside logic.ts.
// ---------------------------------------------------------------------------

Deno.test("authorized request -> flush called exactly once, after run", async () => {
  const order: string[] = [];
  const run = () => {
    order.push("run");
    return Promise.resolve("success");
  };
  const { flush, wasCalled } = makeFlush(order);
  const res = await handleHourlyCheck(req({ auth: `Bearer ${SERVICE_ROLE_JWT}` }), run, flush);
  assertEquals(res.status, 200);
  assertEquals(await res.json(), { outcome: "success" });
  assertEquals(wasCalled(), true);
  assertEquals(order, ["run", "flush"]);
});

Deno.test("401 -> flush never called", async () => {
  const { run } = makeRun();
  const order: string[] = [];
  const { flush, wasCalled } = makeFlush(order);
  const res = await handleHourlyCheck(req({ auth: `Bearer ${ANON_JWT}` }), run, flush);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});

Deno.test("flush rejecting -> response still 200 with outcome (outbox failure never blocks the response)", async () => {
  const { run } = makeRun("success");
  const order: string[] = [];
  const { flush, wasCalled } = makeFlush(order, { reject: true });
  const res = await handleHourlyCheck(req({ auth: `Bearer ${SERVICE_ROLE_JWT}` }), run, flush);
  assertEquals(res.status, 200);
  assertEquals(await res.json(), { outcome: "success" });
  assertEquals(wasCalled(), true);
});
