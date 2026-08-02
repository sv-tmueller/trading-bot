// Behavioral pin (#508): exercises the REAL production wiring in
// buildDeps() -- today's only coverage of buildDeps was indirect (through
// invariants.test.ts's source-text scan). With a live-shaped Alpaca config
// (ALPACA_PAPER=false), every mutating dep buildDeps() wires up must reject
// with PaperGuardFailedError before touching the network, proving the
// { paperOnly: true } opt-in at the hourly-check call site actually gates
// the client this function hands to the pipeline -- not just its source text.
import { assertEquals, assertRejects } from "@std/assert";
import { stubFetch } from "../_shared/test_helpers.ts";
import { PaperGuardFailedError } from "../_shared/alpaca.ts";
import { buildDeps } from "./handler.ts";

// Save/restore-in-finally precedent: alpaca.test.ts's setKeys/clearKeys.
const ORIGINAL_NO_BROKER = Deno.env.get("CLAUDE_AGENT_NO_BROKER");

function stageEnv() {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_PAPER", "false"); // live-shaped config -- the guard must still fire
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("SUPABASE_URL", "http://stub.invalid");
  Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", "stub-service-role-key");
  // Lifted deliberately (restored in finally): this test exercises the
  // paper-only guard itself, not the CLAUDE_AGENT_NO_BROKER backstop -- the
  // fetch stub below still asserts zero network calls either way.
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
}

function restoreEnv() {
  for (
    const k of [
      "ALPACA_API_KEY",
      "ALPACA_SECRET_KEY",
      "ALPACA_PAPER",
      "HOURLY_BOT_PAPER_ONLY",
      "SUPABASE_URL",
      "SUPABASE_SERVICE_ROLE_KEY",
    ]
  ) {
    Deno.env.delete(k);
  }
  if (ORIGINAL_NO_BROKER === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
  else Deno.env.set("CLAUDE_AGENT_NO_BROKER", ORIGINAL_NO_BROKER);
}

async function assertGuardedBeforeFetch(
  call: () => Promise<unknown>,
  fetchCalls: () => number,
) {
  await assertRejects(call, PaperGuardFailedError);
  assertEquals(fetchCalls(), 0);
}

Deno.test("buildDeps(): placeMarketOrder rejects with PaperGuardFailedError before any fetch", async () => {
  stageEnv();
  let fetchCalls = 0;
  const restore = stubFetch(() => {
    fetchCalls++;
    return Promise.resolve(new Response("{}"));
  });
  try {
    const deps = buildDeps();
    await assertGuardedBeforeFetch(
      () => deps.alpaca.placeMarketOrder({ symbol: "SPY", side: "BUY", qty: 1 }),
      () => fetchCalls,
    );
  } finally {
    restore();
    restoreEnv();
  }
});

Deno.test("buildDeps(): placeBracketOrder rejects with PaperGuardFailedError before any fetch", async () => {
  stageEnv();
  let fetchCalls = 0;
  const restore = stubFetch(() => {
    fetchCalls++;
    return Promise.resolve(new Response("{}"));
  });
  try {
    const deps = buildDeps();
    await assertGuardedBeforeFetch(
      () =>
        deps.alpaca.placeBracketOrder({
          symbol: "SPY",
          side: "BUY",
          qty: 1,
          takeProfitPrice: 110,
          stopLossPrice: 90,
        }),
      () => fetchCalls,
    );
  } finally {
    restore();
    restoreEnv();
  }
});

Deno.test("buildDeps(): placeOcoExitPair rejects with PaperGuardFailedError before any fetch", async () => {
  stageEnv();
  let fetchCalls = 0;
  const restore = stubFetch(() => {
    fetchCalls++;
    return Promise.resolve(new Response("{}"));
  });
  try {
    const deps = buildDeps();
    await assertGuardedBeforeFetch(
      () =>
        deps.alpaca.placeOcoExitPair({
          symbol: "SPY",
          side: "SELL",
          qty: 1,
          takeProfitPrice: 110,
          stopLossPrice: 90,
        }),
      () => fetchCalls,
    );
  } finally {
    restore();
    restoreEnv();
  }
});

Deno.test("buildDeps(): cancelOrder rejects with PaperGuardFailedError before any fetch", async () => {
  stageEnv();
  let fetchCalls = 0;
  const restore = stubFetch(() => {
    fetchCalls++;
    return Promise.resolve(new Response("{}"));
  });
  try {
    const deps = buildDeps();
    await assertGuardedBeforeFetch(
      () => deps.alpaca.cancelOrder("order-1"),
      () => fetchCalls,
    );
  } finally {
    restore();
    restoreEnv();
  }
});

Deno.test("buildDeps(): assertPaperAccount rejects with PaperGuardFailedError before any fetch", async () => {
  stageEnv();
  let fetchCalls = 0;
  const restore = stubFetch(() => {
    fetchCalls++;
    return Promise.resolve(new Response("{}"));
  });
  try {
    const deps = buildDeps();
    await assertGuardedBeforeFetch(
      () => deps.alpaca.assertPaperAccount(),
      () => fetchCalls,
    );
  } finally {
    restore();
    restoreEnv();
  }
});
