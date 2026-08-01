import { assertEquals, assertThrows } from "@std/assert";
import {
  assertLocalSupabaseUrl,
  createLocalDbClient,
  isLocalSupabaseHost,
  RemoteSupabaseHostError,
} from "./db_test_guard.ts";

Deno.test("isLocalSupabaseHost: loopback names and addresses are local", () => {
  assertEquals(isLocalSupabaseHost("127.0.0.1"), true);
  assertEquals(isLocalSupabaseHost("127.0.0.2"), true);
  assertEquals(isLocalSupabaseHost("localhost"), true);
  assertEquals(isLocalSupabaseHost("LOCALHOST"), true);
  assertEquals(isLocalSupabaseHost("::1"), true);
  assertEquals(isLocalSupabaseHost("host.docker.internal"), true);
});

Deno.test("isLocalSupabaseHost: hosted Supabase projects and other remotes are not local", () => {
  assertEquals(isLocalSupabaseHost("qdaxxsuicyiscdvsdowc.supabase.co"), false);
  assertEquals(isLocalSupabaseHost("db.qdaxxsuicyiscdvsdowc.supabase.co"), false);
  assertEquals(isLocalSupabaseHost("10.0.0.5"), false);
  assertEquals(isLocalSupabaseHost("192.168.1.20"), false);
  assertEquals(isLocalSupabaseHost(""), false);
});

Deno.test("isLocalSupabaseHost: near-miss hostnames that merely contain a local token are not local", () => {
  assertEquals(isLocalSupabaseHost("localhost.evil.example"), false);
  assertEquals(isLocalSupabaseHost("127.0.0.1.nip.io"), false);
  assertEquals(isLocalSupabaseHost("not-localhost"), false);
  assertEquals(isLocalSupabaseHost("1270.0.0.1"), false);
});

Deno.test("assertLocalSupabaseUrl: a local stack URL on any port passes", () => {
  assertLocalSupabaseUrl("http://127.0.0.1:54321");
  assertLocalSupabaseUrl("http://localhost:64321");
  assertLocalSupabaseUrl("http://[::1]:54321");
});

Deno.test("assertLocalSupabaseUrl: a remote URL throws and the message names the host", () => {
  const err = assertThrows(
    () => assertLocalSupabaseUrl("https://qdaxxsuicyiscdvsdowc.supabase.co"),
    RemoteSupabaseHostError,
  );
  assertEquals(err.host, "qdaxxsuicyiscdvsdowc.supabase.co");
  assertEquals(err.message.includes("qdaxxsuicyiscdvsdowc.supabase.co"), true);
  assertEquals(err.message.includes("SUPABASE_URL"), true);
});

Deno.test("assertLocalSupabaseUrl: an unparseable URL throws and quotes the offending value", () => {
  const err = assertThrows(() => assertLocalSupabaseUrl("not-a-url"), RemoteSupabaseHostError);
  assertEquals(err.message.includes("not-a-url"), true);
});

Deno.test("createLocalDbClient: refuses a remote SUPABASE_URL before building a client", () => {
  const prevUrl = Deno.env.get("SUPABASE_URL");
  Deno.env.set("SUPABASE_URL", "https://qdaxxsuicyiscdvsdowc.supabase.co");
  try {
    const err = assertThrows(() => createLocalDbClient(), RemoteSupabaseHostError);
    assertEquals(err.host, "qdaxxsuicyiscdvsdowc.supabase.co");
  } finally {
    if (prevUrl === undefined) Deno.env.delete("SUPABASE_URL");
    else Deno.env.set("SUPABASE_URL", prevUrl);
  }
});

Deno.test("createLocalDbClient: builds a client for the local stack (no query is issued)", () => {
  const prevUrl = Deno.env.get("SUPABASE_URL");
  const prevKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  Deno.env.set("SUPABASE_URL", "http://127.0.0.1:54321");
  Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", "local-stack-anon-placeholder");
  try {
    const sb = createLocalDbClient();
    assertEquals(typeof sb.from, "function");
  } finally {
    if (prevUrl === undefined) Deno.env.delete("SUPABASE_URL");
    else Deno.env.set("SUPABASE_URL", prevUrl);
    if (prevKey === undefined) Deno.env.delete("SUPABASE_SERVICE_ROLE_KEY");
    else Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", prevKey);
  }
});
