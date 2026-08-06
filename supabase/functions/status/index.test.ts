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
  regime_margin_pct: null,
  audit_7d: { since: "2026-07-02T15:00:00.000Z", outcome_counts: {}, errors: [] },
  last_trade: null,
  alpaca: { equity_usd: 100_000, position: { symbol: "UPRO", qty: 0 } },
  returns: { since_inception_pct: null, trailing_7d_pct: null, trailing_30d_pct: null },
  last_runs: { daily_check: null, kill_switch: null, hourly_check: null },
  hourly: {
    latest_scan: null,
    equity: {
      equity_usd: null,
      floor_baseline_usd: null,
      floor_price_usd: null,
      headroom_pct: null,
    },
    skip_reason_counts: {},
    audit_outcome_counts: {},
  },
};

function req(
  opts: { method?: string; token?: string; days?: string; verify?: string },
): Request {
  const url = new URL(BASE);
  if (opts.days !== undefined) url.searchParams.set("days", opts.days);
  if (opts.verify !== undefined) url.searchParams.set("verify", opts.verify);
  const headers = new Headers();
  if (opts.token !== undefined) headers.set("x-status-token", opts.token);
  return new Request(url.toString(), { method: opts.method ?? "GET", headers });
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

// ---------------------------------------------------------------------------
// #358 T6: `?days=N` param parsing (D5 order: 405 -> 401 -> 400 -> run).
// ---------------------------------------------------------------------------

Deno.test("no days param -> runner called with undefined", async () => {
  await withStatusToken("secret", async () => {
    let received: number | undefined = -1 as unknown as number;
    let called = false;
    const run = (days?: number) => {
      called = true;
      received = days;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(req({ token: "secret" }), run);
    assertEquals(res.status, 200);
    assertEquals(called, true);
    assertEquals(received, undefined);
  });
});

for (const daysStr of ["1", "7", "60"]) {
  Deno.test(`days=${daysStr} -> runner receives the parsed number`, async () => {
    await withStatusToken("secret", async () => {
      let received: number | undefined;
      const run = (days?: number) => {
        received = days;
        return Promise.resolve(DIGEST);
      };
      const res = await handleStatus(req({ token: "secret", days: daysStr }), run);
      assertEquals(res.status, 200);
      assertEquals(received, Number(daysStr));
    });
  });
}

for (const bad of ["0", "61", "abc", "7.5", ""]) {
  Deno.test(`days=${bad === "" ? "(empty)" : bad} -> 400, runner never called`, async () => {
    await withStatusToken("secret", async () => {
      let ran = false;
      const run = () => {
        ran = true;
        return Promise.resolve(DIGEST);
      };
      const res = await handleStatus(req({ token: "secret", days: bad }), run);
      assertEquals(res.status, 400);
      assertEquals(ran, false);
      const body = await res.json();
      assertEquals(body.error, "days must be an integer between 1 and 60");
    });
  });
}

Deno.test("wrong token + bad days -> 401 (auth precedes days validation)", async () => {
  await withStatusToken("secret", async () => {
    const res = await handleStatus(
      req({ token: "wrong", days: "999" }),
      () => Promise.resolve(DIGEST),
    );
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("non-GET + bad days -> 405 (method check precedes days validation)", async () => {
  await withStatusToken("secret", async () => {
    const res = await handleStatus(
      req({ method: "POST", token: "secret", days: "999" }),
      () => Promise.resolve(DIGEST),
    );
    assertEquals(res.status, 405);
    await res.body?.cancel();
  });
});

// ---------------------------------------------------------------------------
// #546: `?verify=YYYY-MM-DD` param parsing. `now` is injectable so the
// not-future and 90-day bounds are deterministic (default leaves index.ts
// unchanged -- it never passes a third argument).
// ---------------------------------------------------------------------------

const FIXED_NOW = () => new Date("2026-08-05T12:00:00.000Z");

for (const bad of ["2026-8-5", "2026/08/05", "not-a-date", "", "2026-08-05T00:00:00Z"]) {
  Deno.test(`verify=${bad === "" ? "(empty)" : bad} -> 400 (malformed format), runner never called`, async () => {
    await withStatusToken("secret", async () => {
      let ran = false;
      const run = () => {
        ran = true;
        return Promise.resolve(DIGEST);
      };
      const res = await handleStatus(req({ token: "secret", verify: bad }), run, FIXED_NOW);
      assertEquals(res.status, 400);
      assertEquals(ran, false);
    });
  });
}

Deno.test("verify=2026-02-30 -> 400 (rolls over to March, caught by the round-trip check), runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-02-30" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 400);
    assertEquals(ran, false);
  });
});

Deno.test("verify=2026-13-01 -> 400 (Date.getTime() is NaN), runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-13-01" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 400);
    assertEquals(ran, false);
  });
});

Deno.test("verify=2026-08-06 (tomorrow relative to now()) -> 400, runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-08-06" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 400);
    assertEquals(ran, false);
  });
});

Deno.test("verify=2026-05-06 (91 days before now()) -> 400 (older than 90 days), runner never called", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-05-06" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 400);
    assertEquals(ran, false);
  });
});

Deno.test("verify=2026-08-05 (exactly today, same-day allowed) -> 200, runner called with the date", async () => {
  await withStatusToken("secret", async () => {
    let received: string | undefined;
    const run = (_days?: number, verifyDate?: string) => {
      received = verifyDate;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-08-05" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 200);
    assertEquals(received, "2026-08-05");
  });
});

Deno.test("verify=2026-05-07 (exactly 90 days before now()) -> 200, runner called with the date", async () => {
  await withStatusToken("secret", async () => {
    let received: string | undefined;
    const run = (_days?: number, verifyDate?: string) => {
      received = verifyDate;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-05-07" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 200);
    assertEquals(received, "2026-05-07");
  });
});

Deno.test("no verify param -> runner called with undefined verifyDate", async () => {
  await withStatusToken("secret", async () => {
    let received: string | undefined = "sentinel";
    const run = (_days?: number, verifyDate?: string) => {
      received = verifyDate;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(req({ token: "secret" }), run, FIXED_NOW);
    assertEquals(res.status, 200);
    assertEquals(received, undefined);
  });
});

Deno.test("verify= alone (no days) reaches the runner correctly", async () => {
  await withStatusToken("secret", async () => {
    let receivedDays: number | undefined = -1 as unknown as number;
    let receivedVerify: string | undefined;
    const run = (days?: number, verifyDate?: string) => {
      receivedDays = days;
      receivedVerify = verifyDate;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-08-05" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 200);
    assertEquals(receivedDays, undefined);
    assertEquals(receivedVerify, "2026-08-05");
  });
});

Deno.test("verify= together with days=N reaches the runner with both, correctly", async () => {
  await withStatusToken("secret", async () => {
    let receivedDays: number | undefined;
    let receivedVerify: string | undefined;
    const run = (days?: number, verifyDate?: string) => {
      receivedDays = days;
      receivedVerify = verifyDate;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", verify: "2026-08-05", days: "30" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 200);
    assertEquals(receivedDays, 30);
    assertEquals(receivedVerify, "2026-08-05");
  });
});

Deno.test("bad days + bad verify -> 400 for days (validation order: days before verify)", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(
      req({ token: "secret", days: "999", verify: "not-a-date" }),
      run,
      FIXED_NOW,
    );
    assertEquals(res.status, 400);
    const body = await res.json();
    assertEquals(body.error, "days must be an integer between 1 and 60");
    assertEquals(ran, false);
  });
});

Deno.test("405 precedes verify validation", async () => {
  await withStatusToken("secret", async () => {
    const res = await handleStatus(
      req({ method: "POST", token: "secret", verify: "not-a-date" }),
      () => Promise.resolve(DIGEST),
      FIXED_NOW,
    );
    assertEquals(res.status, 405);
    await res.body?.cancel();
  });
});

Deno.test("401 precedes verify validation", async () => {
  await withStatusToken("secret", async () => {
    const res = await handleStatus(
      req({ token: "wrong", verify: "not-a-date" }),
      () => Promise.resolve(DIGEST),
      FIXED_NOW,
    );
    assertEquals(res.status, 401);
    await res.body?.cancel();
  });
});

Deno.test("default `now` (no third argument) is real wall-clock time -- a far-future verify date is rejected", async () => {
  await withStatusToken("secret", async () => {
    let ran = false;
    const run = () => {
      ran = true;
      return Promise.resolve(DIGEST);
    };
    const res = await handleStatus(req({ token: "secret", verify: "2099-01-01" }), run);
    assertEquals(res.status, 400);
    assertEquals(ran, false);
  });
});
