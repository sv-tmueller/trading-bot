// HTTP-layer tests for the panic function (finding 5 + finding 15, 2026-06-11
// review): method gating, token auth (fail-closed, constant-time), and the
// error->500 mapping. The action runner is stubbed — no broker, no DB.
import { assertEquals } from "@std/assert";
import { handlePanic, timingSafeEqual } from "./handler.ts";

const BASE = "https://example.test/panic";

function req(opts: { method?: string; action?: string; token?: string }): Request {
  const url = opts.action === undefined ? BASE : `${BASE}?action=${opts.action}`;
  const headers = new Headers();
  if (opts.token !== undefined) headers.set("x-panic-token", opts.token);
  return new Request(url, { method: opts.method ?? "POST", headers });
}

async function withPanicToken<T>(value: string | null, fn: () => Promise<T>): Promise<T> {
  const orig = Deno.env.get("PANIC_TOKEN");
  if (value === null) Deno.env.delete("PANIC_TOKEN");
  else Deno.env.set("PANIC_TOKEN", value);
  try {
    return await fn();
  } finally {
    if (orig === undefined) Deno.env.delete("PANIC_TOKEN");
    else Deno.env.set("PANIC_TOKEN", orig);
  }
}

Deno.test("non-POST -> 405, before auth, runner never called", async () => {
  await withPanicToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve("paused");
    };
    for (const method of ["GET", "PUT", "DELETE"]) {
      const res = await handlePanic(req({ method, action: "pause", token: "secret" }), run);
      assertEquals(res.status, 405);
      await res.body?.cancel();
    }
    assertEquals(ran, false);
  });
});

Deno.test("missing token -> 401", async () => {
  await withPanicToken("secret", async () => {
    const res = await handlePanic(req({ action: "pause" }), () => Promise.resolve("paused"));
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("wrong token -> 401", async () => {
  await withPanicToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve("paused");
    };
    const res = await handlePanic(req({ action: "pause", token: "wrong" }), run);
    assertEquals(res.status, 401);
    assertEquals(ran, false);
    await res.body?.cancel();
  });
});

Deno.test("unset PANIC_TOKEN fails closed (even with an empty token header)", async () => {
  await withPanicToken(null, async () => {
    const res = await handlePanic(req({ action: "pause", token: "" }), () => Promise.resolve("paused"));
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("invalid action -> 400, runner never called", async () => {
  await withPanicToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve("x");
    };
    const res = await handlePanic(req({ action: "explode", token: "secret" }), run);
    assertEquals(res.status, 400);
    assertEquals(ran, false);
    await res.body?.cancel();
  });
});

Deno.test("valid POST + correct token -> 200 with the action result", async () => {
  await withPanicToken("secret", async () => {
    const res = await handlePanic(
      req({ action: "pause", token: "secret" }),
      (action) => Promise.resolve(`ran:${action}`),
    );
    assertEquals(res.status, 200);
    assertEquals(await res.json(), { result: "ran:pause" });
  });
});

Deno.test("failed action (error: result) -> 500", async () => {
  await withPanicToken("secret", async () => {
    const res = await handlePanic(
      req({ action: "liquidate", token: "secret" }),
      () => Promise.resolve("error:OrderTimeoutError: did not fill"),
    );
    assertEquals(res.status, 500);
    assertEquals((await res.json()).result.startsWith("error:"), true);
  });
});

Deno.test("timingSafeEqual compares correctly", async () => {
  assertEquals(await timingSafeEqual("abc", "abc"), true);
  assertEquals(await timingSafeEqual("abc", "abd"), false);
  assertEquals(await timingSafeEqual("abc", "abcd"), false);
  assertEquals(await timingSafeEqual("", ""), true);
});
