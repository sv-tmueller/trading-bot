// HTTP-layer tests for the status function (#354 T5): method gating (GET
// only — read-only endpoint, token in a header), token auth (fail-closed,
// constant-time via the shared timingSafeEqual), and the digest/error mapping.
// The digest runner is stubbed — no broker, no DB.
import { assertEquals } from "@std/assert";
import { handleStatus } from "./handler.ts";
import type { StatusDigest } from "./logic.ts";

const BASE = "https://example.test/status";

const DIGEST: StatusDigest = {
  generated_at: "2026-07-09T15:00:00.000Z",
  market_open: true,
  paused: false,
  regime: null,
  audit_7d: { since: "2026-07-02T15:00:00.000Z", outcome_counts: {}, errors: [] },
  last_trade: null,
  alpaca: { equity_usd: 100_000, position: { symbol: "UPRO", qty: 0 } },
};

function req(opts: { method?: string; token?: string }): Request {
  const headers = new Headers();
  if (opts.token !== undefined) headers.set("x-status-token", opts.token);
  return new Request(BASE, { method: opts.method ?? "GET", headers });
}

async function withStatusToken<T>(value: string | null, fn: () => Promise<T>): Promise<T> {
  const orig = Deno.env.get("STATUS_TOKEN");
  if (value === null) Deno.env.delete("STATUS_TOKEN");
  else Deno.env.set("STATUS_TOKEN", value);
  try {
    return await fn();
  } finally {
    if (orig === undefined) Deno.env.delete("STATUS_TOKEN");
    else Deno.env.set("STATUS_TOKEN", orig);
  }
}

Deno.test("non-GET -> 405, before auth, runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    for (const method of ["POST", "PUT", "DELETE"]) {
      const res = await handleStatus(req({ method, token: "secret" }), run);
      assertEquals(res.status, 405);
      await res.body?.cancel();
    }
    assertEquals(ran, false);
  });
});

Deno.test("missing token -> 401, runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(req({}), run);
    assertEquals(res.status, 401);
    assertEquals(ran, false);
    await res.body?.cancel();
  });
});

Deno.test("wrong token -> 401, runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(req({ token: "wrong" }), run);
    assertEquals(res.status, 401);
    assertEquals(ran, false);
    await res.body?.cancel();
  });
});

Deno.test("unset STATUS_TOKEN fails closed (even with an empty token header)", async () => {
  await withStatusToken(null, async () => {
    const res = await handleStatus(
      req({ token: "" }),
      () => Promise.resolve(DIGEST),
    );
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("valid GET + correct token -> 200 with the digest body", async () => {
  await withStatusToken("secret", async () => {
    const res = await handleStatus(req({ token: "secret" }), () => Promise.resolve(DIGEST));
    assertEquals(res.status, 200);
    assertEquals(await res.json(), DIGEST);
  });
});

Deno.test("runner throws -> JSON 500", async () => {
  await withStatusToken("secret", async () => {
    const res = await handleStatus(
      req({ token: "secret" }),
      () => Promise.reject(new Error("db down")),
    );
    assertEquals(res.status, 500);
    const body = await res.json();
    assertEquals(typeof body.error, "string");
  });
});
