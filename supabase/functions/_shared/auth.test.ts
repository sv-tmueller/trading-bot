// Unit tests for requireServiceRole (#291: service-role authorization gate).
// Does NOT verify JWT signatures — that is handled by Supabase's verify_jwt=ON.
// Tests confirm: service_role JWT → null (pass); anon JWT → 401; malformed/absent → 401.
import { assertEquals } from "@std/assert";
import { requireServiceRole, timingSafeEqual } from "./auth.ts";

const BASE = "https://example.test/daily-check";

// ---------------------------------------------------------------------------
// JWT helpers — build real base64url-encoded payloads (unsigned; sig doesn't
// matter here since verify_jwt already validated them before our handler runs).
// A real Supabase JWT header is {"alg":"HS256","typ":"JWT"} — we use the same.
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

// A payload that forces a base64url-specific char: the `+` from standard
// base64 would break plain atob — any payload whose b64 encoding contains `+`
// or `/` exercises the replace. We include a long enough string to reliably hit
// one (the role value alone can trigger it with the right JSON length).
const SERVICE_ROLE_JWT = makeJwt({ role: "service_role", iss: "supabase" });
const ANON_JWT = makeJwt({ role: "anon", iss: "supabase" });

function req(authHeader?: string): Request {
  const headers = new Headers();
  if (authHeader !== undefined) headers.set("Authorization", authHeader);
  return new Request(BASE, { method: "POST", headers });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

Deno.test("service_role JWT -> null (authorized)", async () => {
  const result = await requireServiceRole(req(`Bearer ${SERVICE_ROLE_JWT}`));
  assertEquals(result, null);
});

Deno.test("anon JWT -> 401 Response", async () => {
  const result = await requireServiceRole(req(`Bearer ${ANON_JWT}`));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  const body = await (result as Response).json();
  assertEquals(body.error, "unauthorized");
});

Deno.test("absent Authorization header -> 401", async () => {
  const result = await requireServiceRole(req());
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

Deno.test("non-Bearer Authorization -> 401", async () => {
  const result = await requireServiceRole(req("Basic dXNlcjpwYXNz"));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

Deno.test("Bearer with only one JWT segment -> 401", async () => {
  const result = await requireServiceRole(req("Bearer notajwt"));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

Deno.test("Bearer with two segments (no signature) -> 401", async () => {
  const result = await requireServiceRole(req("Bearer header.payload"));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

Deno.test("Bearer with malformed base64url payload -> 401", async () => {
  const result = await requireServiceRole(req("Bearer header.!!!.sig"));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

Deno.test("Bearer with valid structure but non-object payload -> 401", async () => {
  const badPayload = btoa('"just a string"')
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  const result = await requireServiceRole(req(`Bearer header.${badPayload}.sig`));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

Deno.test("empty Authorization header value -> 401", async () => {
  const result = await requireServiceRole(req(""));
  assertEquals(result instanceof Response, true);
  assertEquals((result as Response).status, 401);
  await (result as Response).body?.cancel();
});

// ---------------------------------------------------------------------------
// timingSafeEqual (moved from panic/handler.ts, T1 of #354: shared so the new
// status Edge Function's token check can reuse it without duplicating the
// constant-time comparison).
// ---------------------------------------------------------------------------

Deno.test("timingSafeEqual compares correctly", async () => {
  assertEquals(await timingSafeEqual("abc", "abc"), true);
  assertEquals(await timingSafeEqual("abc", "abd"), false);
  assertEquals(await timingSafeEqual("abc", "abcd"), false);
  assertEquals(await timingSafeEqual("", ""), true);
});
