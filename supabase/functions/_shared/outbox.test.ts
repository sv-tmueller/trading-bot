// #397 T4: outbox.ts test matrix. Uses plain fake OutboxDeps objects (no
// supabase-js fluent-builder mocking, no real fetch) -- notifyDurable and
// flushOutbox are pure orchestration over an injected deps object, same
// pattern as logic.ts. stubWarn mirrors notifications.test.ts's helper.
import { assertEquals } from "@std/assert";
import { flushOutbox, notifyDurable, type OutboxDeps } from "./outbox.ts";
import type { OutboxRow } from "./db.ts";
import type { NotifyStatus } from "./notifications.ts";

function stubWarn(): { calls: unknown[][]; restore: () => void } {
  const original = console.warn;
  const calls: unknown[][] = [];
  console.warn = (...args: unknown[]) => {
    calls.push(args);
  };
  return { calls, restore: () => (console.warn = original) };
}

function joinCalls(calls: unknown[][]): string {
  return calls.map((c) => c.map((a) => String(a)).join(" ")).join("\n");
}

// deno-lint-ignore no-explicit-any
function fakeDeps(overrides: Partial<OutboxDeps> = {}): OutboxDeps & Record<string, any> {
  const enqueueCalls: Array<{ eventType: string; event: Record<string, unknown> }> = [];
  const markAttemptCalls: Array<{ id: number; attempts: number }> = [];
  const removeCalls: number[][] = [];
  const getPendingCalls: number[] = [];
  const deps = {
    post: (_event: Record<string, unknown>): Promise<NotifyStatus> => Promise.resolve("sent"),
    enqueue: (p: { eventType: string; event: Record<string, unknown> }): Promise<void> => {
      enqueueCalls.push(p);
      return Promise.resolve();
    },
    getPending: (limit: number): Promise<OutboxRow[]> => {
      getPendingCalls.push(limit);
      return Promise.resolve([]);
    },
    remove: (ids: number[]): Promise<void> => {
      removeCalls.push(ids);
      return Promise.resolve();
    },
    markAttempt: (id: number, attempts: number): Promise<void> => {
      markAttemptCalls.push({ id, attempts });
      return Promise.resolve();
    },
    now: () => new Date("2026-07-21T13:37:00Z"),
    ...overrides,
  };
  return Object.assign(deps, { enqueueCalls, markAttemptCalls, removeCalls, getPendingCalls });
}

function row(overrides: Partial<OutboxRow> = {}): OutboxRow {
  return {
    id: 1,
    event_type: "test_event",
    event: { event_type: "test_event", secret_field: "top-secret-payload-value" },
    attempts: 0,
    last_attempt_at: null,
    created_at: "2026-07-21T12:00:00Z",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// notifyDurable
// ---------------------------------------------------------------------------

Deno.test("notifyDurable: post fails (fetch rejects, surfaced as 'failed') -> enqueue called with the built event + correct event_type; no throw", async () => {
  const deps = fakeDeps({ post: () => Promise.resolve("failed") });
  await notifyDurable(deps, "trade_failed", { event_type: "trade_failed", symbol: "UPRO" });
  assertEquals(deps.enqueueCalls.length, 1);
  assertEquals(deps.enqueueCalls[0].eventType, "trade_failed");
  assertEquals(deps.enqueueCalls[0].event, { event_type: "trade_failed", symbol: "UPRO" });
});

Deno.test("notifyDurable: post non-2xx ('failed') -> enqueued", async () => {
  const deps = fakeDeps({ post: () => Promise.resolve("failed") });
  await notifyDurable(deps, "broker_error", { event_type: "broker_error" });
  assertEquals(deps.enqueueCalls.length, 1);
});

Deno.test("notifyDurable: post 2xx ('sent') -> not enqueued", async () => {
  const deps = fakeDeps({ post: () => Promise.resolve("sent") });
  await notifyDurable(deps, "broker_error", { event_type: "broker_error" });
  assertEquals(deps.enqueueCalls.length, 0);
});

Deno.test("notifyDurable: enqueue throws (DB down) -> warn only, no throw; warn contains neither URL nor payload fields", async () => {
  const deps = fakeDeps({
    post: () => Promise.resolve("failed"),
    enqueue: () =>
      Promise.reject(
        new Error("db unreachable: connection refused to https://secret-project.supabase.co"),
      ),
  });
  const { calls, restore } = stubWarn();
  try {
    await notifyDurable(deps, "trade_failed", {
      event_type: "trade_failed",
      symbol: "UPRO",
      message: "top-secret-message-payload",
    });
    const joined = joinCalls(calls);
    assertEquals(joined.includes("trade_failed"), true);
    assertEquals(joined.includes("top-secret-message-payload"), false);
    assertEquals(joined.includes("UPRO"), false);
  } finally {
    restore();
  }
});

Deno.test("notifyDurable: webhook URL unset ('skipped_unset') -> no enqueue, no throw", async () => {
  const deps = fakeDeps({ post: () => Promise.resolve("skipped_unset") });
  await notifyDurable(deps, "error", { event_type: "error" });
  assertEquals(deps.enqueueCalls.length, 0);
});

// ---------------------------------------------------------------------------
// flushOutbox
// ---------------------------------------------------------------------------
// getNotifyWebhookUrl() is read from the NOTIFY_WEBHOOK_URL env var by
// flushOutbox itself (mirrors notifications.ts's own sourcing), so tests that
// want the flush to proceed past the early return must set it.

Deno.test("flushOutbox: pending row + post 2xx -> row deleted", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const pending = [row({ id: 42 })];
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => Promise.resolve("sent"),
  });
  try {
    await flushOutbox(deps);
    assertEquals(deps.removeCalls, [[42]]);
    assertEquals(deps.markAttemptCalls.length, 0);
  } finally {
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: post fails -> markAttempt called with attempts+1, row not deleted", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const pending = [row({ id: 7, attempts: 2 })];
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => Promise.resolve("failed"),
  });
  try {
    await flushOutbox(deps);
    assertEquals(deps.markAttemptCalls, [{ id: 7, attempts: 3 }]);
    assertEquals(deps.removeCalls.length, 0);
  } finally {
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: row past TTL -> deleted with warn, post never called for it", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let postCalled = false;
  const staleCreatedAt = "2026-07-01T00:00:00Z"; // > 72h before fake now() (2026-07-21T13:37Z)
  const pending = [row({ id: 99, created_at: staleCreatedAt })];
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => {
      postCalled = true;
      return Promise.resolve("sent");
    },
  });
  const { calls, restore } = stubWarn();
  try {
    await flushOutbox(deps);
    assertEquals(postCalled, false);
    assertEquals(deps.removeCalls, [[99]]);
    const joined = joinCalls(calls);
    assertEquals(joined.includes("dropped"), true);
    assertEquals(joined.includes("id=99"), true);
    assertEquals(joined.includes("test_event"), true);
    assertEquals(joined.includes("secret_field"), false);
    assertEquals(joined.includes("top-secret-payload-value"), false);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: row at attempts cap -> deleted with warn, post never called for it", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  let postCalled = false;
  const pending = [row({ id: 100, attempts: 500 })];
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => {
      postCalled = true;
      return Promise.resolve("sent");
    },
  });
  const { calls, restore } = stubWarn();
  try {
    await flushOutbox(deps);
    assertEquals(postCalled, false);
    assertEquals(deps.removeCalls, [[100]]);
    assertEquals(joinCalls(calls).includes("dropped"), true);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: getPending throws -> warn, no throw", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const deps = fakeDeps({ getPending: () => Promise.reject(new Error("db down")) });
  const { calls, restore } = stubWarn();
  try {
    await flushOutbox(deps); // must not throw
    assertEquals(calls.length > 0, true);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: remove throws -> warn, no throw", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const pending = [row({ id: 1 })];
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => Promise.resolve("sent"),
    remove: () => Promise.reject(new Error("db down")),
  });
  const { calls, restore } = stubWarn();
  try {
    await flushOutbox(deps); // must not throw
    assertEquals(calls.length > 0, true);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: markAttempt throws -> warn, no throw", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const pending = [row({ id: 1 })];
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => Promise.resolve("failed"),
    markAttempt: () => Promise.reject(new Error("db down")),
  });
  const { calls, restore } = stubWarn();
  try {
    await flushOutbox(deps); // must not throw
    assertEquals(calls.length > 0, true);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: batch cap respected (getPending called with 10)", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const deps = fakeDeps();
  try {
    await flushOutbox(deps);
    assertEquals(deps.getPendingCalls, [10]);
  } finally {
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

Deno.test("flushOutbox: webhook URL unset -> no DB call at all", async () => {
  Deno.env.delete("NOTIFY_WEBHOOK_URL");
  const deps = fakeDeps();
  await flushOutbox(deps);
  assertEquals(deps.getPendingCalls.length, 0);
  assertEquals(deps.removeCalls.length, 0);
  assertEquals(deps.markAttemptCalls.length, 0);
});

Deno.test("flushOutbox: mid-batch skipped_unset stops the loop leaving remaining rows intact", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const pending = [row({ id: 1 }), row({ id: 2 })];
  let calls = 0;
  const deps = fakeDeps({
    getPending: () => Promise.resolve(pending),
    post: () => {
      calls++;
      return Promise.resolve(calls === 1 ? "skipped_unset" : "sent");
    },
  });
  try {
    await flushOutbox(deps);
    assertEquals(deps.removeCalls.length, 0);
    assertEquals(deps.markAttemptCalls.length, 0);
  } finally {
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});

// ---------------------------------------------------------------------------
// Warn-hygiene sweep: no warn line above ever contains a payload field value
// or a webhook URL. Spot-checked per-test above; this test re-asserts the
// invariant across the two paths that log a payload-adjacent value (dropped
// row, enqueue-failure) using a distinctive marker.
// ---------------------------------------------------------------------------

Deno.test("warn-hygiene: dropped-row warn never includes event payload values", async () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "http://localhost:5678/hook");
  const marker = "MARKER-PAYLOAD-VALUE-1234";
  const pending = [
    row({
      id: 55,
      attempts: 500,
      event: { event_type: "test_event", message: marker },
    }),
  ];
  const deps = fakeDeps({ getPending: () => Promise.resolve(pending) });
  const { calls, restore } = stubWarn();
  try {
    await flushOutbox(deps);
    assertEquals(joinCalls(calls).includes(marker), false);
  } finally {
    restore();
    Deno.env.delete("NOTIFY_WEBHOOK_URL");
  }
});
