// HTTP-layer auth tests for kill-switch (#291): service-role JWT → passes
// through to the (mocked) pipeline; anon JWT / malformed / absent → 401.
// The pipeline runner is injected (like panic/index.test.ts) — no Alpaca calls.
import { assertEquals } from "@std/assert";
import { handleKillSwitch } from "./handler.ts";

const BASE = "https://example.test/kill-switch";

// ---------------------------------------------------------------------------
// JWT helpers (same as auth.test.ts — real base64url encoding)
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

// Stub run function: returns a fixed outcome; records whether it was called.
function makeRun(outcome = "success") {
  let called = false;
  const run = () => {
    called = true;
    return Promise.resolve(outcome);
  };
  return { run, wasCalled: () => called };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

Deno.test("service_role JWT -> 200 with outcome, pipeline called", async () => {
  const { run, wasCalled } = makeRun("success");
  const res = await handleKillSwitch(req({ auth: `Bearer ${SERVICE_ROLE_JWT}` }), run);
  assertEquals(res.status, 200);
  assertEquals(await res.json(), { outcome: "success" });
  assertEquals(wasCalled(), true);
});

Deno.test("anon JWT -> 401, pipeline never called", async () => {
  const { run, wasCalled } = makeRun();
  const res = await handleKillSwitch(req({ auth: `Bearer ${ANON_JWT}` }), run);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});

Deno.test("absent Authorization header -> 401, pipeline never called", async () => {
  const { run, wasCalled } = makeRun();
  const res = await handleKillSwitch(req(), run);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});

Deno.test("malformed bearer -> 401, pipeline never called", async () => {
  const { run, wasCalled } = makeRun();
  const res = await handleKillSwitch(req({ auth: "Bearer notajwt" }), run);
  assertEquals(res.status, 401);
  assertEquals(wasCalled(), false);
  await res.body?.cancel();
});
