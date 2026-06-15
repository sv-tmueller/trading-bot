// HTTP-layer tests for the panic function (finding 5 + finding 15, 2026-06-11
// review): method gating, token auth (fail-closed, constant-time), the
// ok->status mapping of the typed {ok,result} contract (#240/#250), and the
// pause=false opt-out plumbing (finding 13 / #185 option 1). The action runner
// is stubbed — no broker, no DB.
import { assertEquals } from "@std/assert";
import { handlePanic, timingSafeEqual } from "./handler.ts";
import type { PanicResult } from "./logic.ts";

const BASE = "https://example.test/panic";

const ok = (result: string): Promise<PanicResult> => Promise.resolve({ ok: true, result });

function req(
  opts: { method?: string; action?: string; token?: string; pause?: string },
): Request {
  const url = new URL(BASE);
  if (opts.action !== undefined) url.searchParams.set("action", opts.action);
  if (opts.pause !== undefined) url.searchParams.set("pause", opts.pause);
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
      return ok("paused");
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
    const res = await handlePanic(req({ action: "pause" }), () => ok("paused"));
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("wrong token -> 401", async () => {
  await withPanicToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return ok("paused");
    };
    const res = await handlePanic(req({ action: "pause", token: "wrong" }), run);
    assertEquals(res.status, 401);
    assertEquals(ran, false);
    await res.body?.cancel();
  });
});

Deno.test("unset PANIC_TOKEN fails closed (even with an empty token header)", async () => {
  await withPanicToken(null, async () => {
    const res = await handlePanic(
      req({ action: "pause", token: "" }),
      () => ok("paused"),
    );
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("invalid action -> 400, runner never called", async () => {
  await withPanicToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return ok("x");
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
      (action) => ok(`ran:${action}`),
    );
    assertEquals(res.status, 200);
    assertEquals(await res.json(), { result: "ran:pause" });
  });
});

Deno.test("failed action (ok:false) -> 500", async () => {
  await withPanicToken("secret", async () => {
    const res = await handlePanic(
      req({ action: "liquidate", token: "secret" }),
      () => Promise.resolve({ ok: false, result: "OrderTimeoutError: did not fill" }),
    );
    assertEquals(res.status, 500);
    assertEquals((await res.json()).result, "OrderTimeoutError: did not fill");
  });
});

Deno.test("pause query param: default true, ?pause=false opts out (finding 13)", async () => {
  await withPanicToken("secret", async () => {
    let seen: boolean | undefined;
    const run = (_action: unknown, opts: { pauseOnLiquidate?: boolean }) => {
      seen = opts.pauseOnLiquidate;
      return ok("liquidated");
    };
    let res = await handlePanic(req({ action: "liquidate", token: "secret" }), run);
    assertEquals(seen, true);
    await res.body?.cancel();

    res = await handlePanic(
      req({ action: "liquidate", token: "secret", pause: "false" }),
      run,
    );
    assertEquals(seen, false);
    await res.body?.cancel();
  });
});

Deno.test("timingSafeEqual compares correctly", async () => {
  assertEquals(await timingSafeEqual("abc", "abc"), true);
  assertEquals(await timingSafeEqual("abc", "abd"), false);
  assertEquals(await timingSafeEqual("abc", "abcd"), false);
  assertEquals(await timingSafeEqual("", ""), true);
});
