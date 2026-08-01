import { assertEquals, assertRejects, assertThrows } from "@std/assert";
import {
  assertLocalSupabaseUrl,
  createLocalDbClient,
  isLocalSupabaseHost,
  RemoteSupabaseHostError,
  withConfigRestored,
} from "./db_test_guard.ts";
import { getConfig, setConfig } from "./db.ts";

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

// ---------------------------------------------------------------------------
// withConfigRestored: the gated bot_config roundtrip must leave the flag it
// found. Exercised here against an in-memory bot_config table (no network),
// because the roundtrip itself only runs behind RUN_DB_TESTS.
// ---------------------------------------------------------------------------

function fakeConfigClient(initial: Record<string, string>, opts: { writesFail?: boolean } = {}) {
  const rows = new Map(Object.entries(initial));
  const writeError = opts.writesFail ? { message: "bot_config is read-only in this fake" } : null;
  const reader = (key?: string) => ({
    select: () => reader(key),
    eq: (_col: string, val: string) => reader(val),
    maybeSingle: () =>
      Promise.resolve({
        data: key !== undefined && rows.has(key) ? { value: rows.get(key) } : null,
        error: null,
      }),
  });
  const sb = {
    from: (table: string) => {
      if (table !== "bot_config") throw new Error(`unexpected table ${table}`);
      return {
        ...reader(),
        upsert: (row: { key: string; value: string }) => {
          if (writeError) return Promise.resolve({ error: writeError });
          rows.set(row.key, row.value);
          return Promise.resolve({ error: null });
        },
        delete: () => ({
          eq: (_col: string, val: string) => {
            if (writeError) return Promise.resolve({ error: writeError });
            rows.delete(val);
            return Promise.resolve({ error: null });
          },
        }),
      };
    },
  };
  // deno-lint-ignore no-explicit-any
  return { sb: sb as any, rows };
}

Deno.test("withConfigRestored: restores the value the body found", async () => {
  const { sb, rows } = fakeConfigClient({ paused: "true" });
  await withConfigRestored(sb, "paused", async () => {
    await setConfig(sb, "paused", "false");
    assertEquals(await getConfig(sb, "paused"), "false");
  });
  assertEquals(rows.get("paused"), "true");
});

Deno.test("withConfigRestored: restores on a failing body and rethrows", async () => {
  const { sb, rows } = fakeConfigClient({ paused: "true" });
  await assertRejects(
    () =>
      withConfigRestored(sb, "paused", async () => {
        await setConfig(sb, "paused", "false");
        throw new Error("assertion blew up mid-test");
      }),
    Error,
    "assertion blew up mid-test",
  );
  assertEquals(rows.get("paused"), "true");
});

Deno.test("withConfigRestored: no prior row -> the key is deleted again, not left behind", async () => {
  const { sb, rows } = fakeConfigClient({});
  await withConfigRestored(sb, "paused", async () => {
    await setConfig(sb, "paused", "true");
  });
  assertEquals(rows.has("paused"), false);
});

Deno.test("withConfigRestored: returns the body's value", async () => {
  const { sb } = fakeConfigClient({ paused: "false" });
  const result = await withConfigRestored(sb, "paused", () => Promise.resolve(42));
  assertEquals(result, 42);
});

Deno.test("withConfigRestored: a failing restore does not mask the body's failure", async () => {
  const { sb } = fakeConfigClient({ paused: "true" }, { writesFail: true });
  const originalError = console.error;
  const logged: unknown[][] = [];
  console.error = (...args: unknown[]) => void logged.push(args);
  try {
    await assertRejects(
      () => withConfigRestored(sb, "paused", () => Promise.reject(new Error("the real failure"))),
      Error,
      "the real failure",
    );
  } finally {
    console.error = originalError;
  }
  assertEquals(logged.length, 1);
  assertEquals(String(logged[0][0]).includes("failed to restore paused"), true);
});

Deno.test("withConfigRestored: a failing restore surfaces when the body succeeded", async () => {
  const { sb } = fakeConfigClient({ paused: "true" }, { writesFail: true });
  await assertRejects(
    () => withConfigRestored(sb, "paused", () => Promise.resolve("ok")),
    Error,
    "setConfig",
  );
});
