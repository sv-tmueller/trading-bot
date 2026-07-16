// Unit tests for the equity_snapshots backfill script (#389). Every dep is a
// plain injected mock — no network, no real Supabase client construction.
// CLAUDE_AGENT_NO_BROKER is set by the `test` deno.json task; this script
// adds no mutating broker helper, so the guard is inert here (defense in
// depth only).
import { assertEquals, assertRejects, assertThrows } from "@std/assert";
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  type BackfillDeps,
  EquitySnapshotsTableMissingError,
  fetchPortfolioHistoryAdapter,
  getEarliestAuditStartedAtAdapter,
  getExistingSnapshotDatesAdapter,
  insertSnapshotsIgnoreDuplicatesAdapter,
  mapHistoryToDailyRows,
  parseArgs,
  runBackfill,
} from "./backfill_equity_snapshots.ts";

const sec = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);

Deno.test("parseArgs: defaults (no flags) -> dry-run, no since, no help", () => {
  const parsed = parseArgs([]);
  assertEquals(parsed, { help: false, since: undefined, execute: false });
});

Deno.test("parseArgs: --since with a valid YYYY-MM-DD is accepted", () => {
  const parsed = parseArgs(["--since", "2026-01-05"]);
  assertEquals(parsed, { help: false, since: "2026-01-05", execute: false });
});

Deno.test("parseArgs: --execute flips execute to true", () => {
  const parsed = parseArgs(["--execute"]);
  assertEquals(parsed.execute, true);
});

Deno.test("parseArgs: --since and --execute together", () => {
  const parsed = parseArgs(["--since", "2026-01-05", "--execute"]);
  assertEquals(parsed, { help: false, since: "2026-01-05", execute: true });
});

Deno.test("parseArgs: -h sets help", () => {
  assertEquals(parseArgs(["-h"]).help, true);
});

Deno.test("parseArgs: --help sets help", () => {
  assertEquals(parseArgs(["--help"]).help, true);
});

Deno.test("parseArgs: --since with a malformed date throws a one-line ArgError", () => {
  assertThrows(
    () => parseArgs(["--since", "not-a-date"]),
    Error,
    "--since",
  );
});

Deno.test("parseArgs: --since with an out-of-range calendar date throws", () => {
  // 2026-02-30 doesn't exist; JS Date silently rolls it over to March 2 unless
  // we round-trip-validate.
  assertThrows(
    () => parseArgs(["--since", "2026-02-30"]),
    Error,
    "--since",
  );
});

Deno.test("parseArgs: --since with no value throws", () => {
  assertThrows(() => parseArgs(["--since"]), Error, "--since");
});

Deno.test("parseArgs: unknown argument throws an UnknownArgError", () => {
  assertThrows(
    () => parseArgs(["--bogus"]),
    Error,
    "unknown argument",
  );
});

// ---------------------------------------------------------------------------
// T2 — mapHistoryToDailyRows
// ---------------------------------------------------------------------------

Deno.test("mapHistoryToDailyRows: maps epoch seconds to America/New_York calendar date", () => {
  // 2026-01-06T04:30:00Z is 2026-01-05 23:30 ET (EST, UTC-5 in January) — UTC
  // date != ET date, per the D3 fixture in the SUB_PLAN.
  const history = {
    timestamp: [sec("2026-01-06T04:30:00Z")],
    equity: [100234.56],
  };
  const { rows } = mapHistoryToDailyRows(history, "2026-01-01", "2026-07-15");
  assertEquals(rows, [{ date: "2026-01-05", equity_usd: 100234.56 }]);
});

Deno.test("mapHistoryToDailyRows: excludes dates before `since` (lower bound)", () => {
  // Mirrors the todayEt upper-bound exclusion: the fetch adapter requests
  // start=<since>T00:00:00Z, which Alpaca rounds *backward* into the prior ET
  // day (see the doc-comment on fetchPortfolioHistoryAdapter) — so a
  // pre-`since` row can come back from Alpaca and must be dropped client-side.
  const history = {
    timestamp: [
      sec("2026-07-09T20:00:00Z"), // 2026-07-09 ET — before since, excluded
      sec("2026-07-10T20:00:00Z"), // 2026-07-10 ET == since, included
    ],
    equity: [100, 200],
  };
  const { rows } = mapHistoryToDailyRows(history, "2026-07-10", "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-10", equity_usd: 200 }]);
});

Deno.test("mapHistoryToDailyRows: excludes today (ET) and later", () => {
  const history = {
    timestamp: [
      sec("2026-07-14T20:00:00Z"), // 2026-07-14 ET (EDT, UTC-4 in July)
      sec("2026-07-15T20:00:00Z"), // 2026-07-15 ET == todayEt, excluded
    ],
    equity: [100, 200],
  };
  const { rows, alpacaDays } = mapHistoryToDailyRows(history, "2026-07-01", "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-14", equity_usd: 100 }]);
  assertEquals(alpacaDays, 2);
});

Deno.test("mapHistoryToDailyRows: drops zero/negative/non-finite equity, counted separately", () => {
  const history = {
    timestamp: [
      sec("2026-07-10T20:00:00Z"),
      sec("2026-07-11T20:00:00Z"),
      sec("2026-07-12T20:00:00Z"),
      sec("2026-07-13T20:00:00Z"),
    ],
    equity: [0, -5, NaN, 42],
  };
  const { rows, zeroEquityDropped } = mapHistoryToDailyRows(history, "2026-07-01", "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-13", equity_usd: 42 }]);
  assertEquals(zeroEquityDropped, 3);
});

Deno.test("mapHistoryToDailyRows: requireNumber accepts numeric strings", () => {
  const history = {
    timestamp: [sec("2026-07-10T20:00:00Z")],
    equity: ["1234.5"],
  };
  const { rows } = mapHistoryToDailyRows(history, "2026-07-01", "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-10", equity_usd: 1234.5 }]);
});

Deno.test("mapHistoryToDailyRows: dedupes two timestamps mapping to the same ET date, keeping the last", () => {
  const history = {
    timestamp: [
      sec("2026-07-10T14:00:00Z"), // 2026-07-10 10:00 ET (EDT)
      sec("2026-07-10T20:00:00Z"), // 2026-07-10 16:00 ET (EDT) — same ET date
    ],
    equity: [100, 200],
  };
  const { rows } = mapHistoryToDailyRows(history, "2026-07-01", "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-10", equity_usd: 200 }]);
});

Deno.test("mapHistoryToDailyRows: parallel-array length mismatch throws a clear error", () => {
  const history = {
    timestamp: [sec("2026-07-10T20:00:00Z"), sec("2026-07-11T20:00:00Z")],
    equity: [1],
  };
  assertThrows(
    () => mapHistoryToDailyRows(history, "2026-07-01", "2026-07-15"),
    Error,
    "length mismatch",
  );
});

// ---------------------------------------------------------------------------
// T3 — runBackfill orchestration
// ---------------------------------------------------------------------------

function makeDeps(over: Partial<BackfillDeps> = {}): {
  deps: BackfillDeps;
  logs: string[];
  inserted: { date: string; equity_usd: number }[][];
} {
  const logs: string[] = [];
  const inserted: { date: string; equity_usd: number }[][] = [];

  const defaultDb: BackfillDeps["db"] = {
    getEarliestAuditStartedAt: () => Promise.resolve("2026-01-01T13:37:00Z"),
    getExistingSnapshotDates: () => Promise.resolve([]),
    insertSnapshotsIgnoreDuplicates: (rows) => {
      inserted.push(rows);
      return Promise.resolve(rows.map((r) => r.date));
    },
  };

  const deps: BackfillDeps = {
    now: () => new Date("2026-07-15T18:00:00Z"),
    fetchPortfolioHistory: (_startYmd: string) =>
      Promise.resolve({
        timestamp: [
          sec("2026-07-13T20:00:00Z"),
          sec("2026-07-14T20:00:00Z"),
        ],
        equity: [100000, 100500],
      }),
    db: defaultDb,
    log: (line: string) => logs.push(line),
    ...over,
  };
  return { deps, logs, inserted };
}

Deno.test("runBackfill: --since overrides the audit_log default", async () => {
  const { deps } = makeDeps({
    db: {
      getEarliestAuditStartedAt: () => {
        throw new Error("should not be called when --since is given");
      },
      getExistingSnapshotDates: () => Promise.resolve([]),
      insertSnapshotsIgnoreDuplicates: (rows) => Promise.resolve(rows.map((r) => r.date)),
    },
  });
  const summary = await runBackfill(deps, { since: "2026-06-01", execute: false });
  assertEquals(summary.since, "2026-06-01");
});

Deno.test("runBackfill: since defaults to earliest audit_log row (UTC ymd)", async () => {
  const { deps } = makeDeps();
  const summary = await runBackfill(deps, { execute: false });
  assertEquals(summary.since, "2026-01-01");
});

Deno.test("runBackfill: empty audit_log + no --since throws a clean error", async () => {
  const { deps } = makeDeps({
    db: {
      getEarliestAuditStartedAt: () => Promise.resolve(null),
      getExistingSnapshotDates: () => Promise.resolve([]),
      insertSnapshotsIgnoreDuplicates: (rows) => Promise.resolve(rows.map((r) => r.date)),
    },
  });
  await assertRejects(
    () => runBackfill(deps, { execute: false }),
    Error,
    "--since",
  );
});

Deno.test("runBackfill: dry-run never calls insertSnapshotsIgnoreDuplicates", async () => {
  const { deps, inserted } = makeDeps();
  await runBackfill(deps, { execute: false });
  assertEquals(inserted.length, 0);
});

Deno.test("runBackfill: --execute writes exactly the missing dates", async () => {
  const { deps, inserted } = makeDeps();
  const summary = await runBackfill(deps, { execute: true });
  assertEquals(inserted, [[
    { date: "2026-07-13", equity_usd: 100000 },
    { date: "2026-07-14", equity_usd: 100500 },
  ]]);
  assertEquals(summary.insertedRows.map((r) => r.date), ["2026-07-13", "2026-07-14"]);
});

Deno.test("runBackfill: an existing date is never re-sent, even with a differing Alpaca equity value", async () => {
  // The seeded existing date ("2026-07-13") has equity 100000 at Alpaca in
  // makeDeps' default fetchPortfolioHistory, but that must never surface in
  // the write payload — the DB row is canonical (D2b).
  const sentPayloads: { date: string; equity_usd: number }[][] = [];
  const { deps } = makeDeps({
    db: {
      getEarliestAuditStartedAt: () => Promise.resolve("2026-01-01T13:37:00Z"),
      getExistingSnapshotDates: () => Promise.resolve(["2026-07-13"]),
      insertSnapshotsIgnoreDuplicates: (rows) => {
        sentPayloads.push(rows);
        return Promise.resolve(rows.map((r) => r.date));
      },
    },
  });
  const summary = await runBackfill(deps, { execute: true });
  assertEquals(sentPayloads, [[{ date: "2026-07-14", equity_usd: 100500 }]]);
  assertEquals(summary.alreadyPresent, 1);
});

Deno.test("runBackfill: PostgREST 42P01 surfaces a migration-0009 message, not a raw error", async () => {
  const { deps } = makeDeps({
    db: {
      getEarliestAuditStartedAt: () => Promise.resolve("2026-01-01T13:37:00Z"),
      getExistingSnapshotDates: () => {
        throw new EquitySnapshotsTableMissingError('relation "equity_snapshots" does not exist');
      },
      insertSnapshotsIgnoreDuplicates: (rows) => Promise.resolve(rows.map((r) => r.date)),
    },
  });
  await assertRejects(
    () => runBackfill(deps, { execute: false }),
    Error,
    "migration 0009",
  );
});

Deno.test("runBackfill: dry-run summary carries window + all four counts", async () => {
  const { deps, logs } = makeDeps();
  await runBackfill(deps, { execute: false });
  const joined = logs.join("\n");
  assertEquals(joined.includes("dry-run"), true);
  assertEquals(joined.includes("2026-01-01"), true);
  assertEquals(joined.includes("2026-07-15"), true);
  assertEquals(joined.includes("re-run with --execute"), true);
  // The four summary counts (D5) — makeDeps' default fixture fetches 2 days,
  // drops none, has nothing already present, so both are missing.
  assertEquals(joined.includes("alpaca days fetched: 2"), true);
  assertEquals(joined.includes("zero/invalid equity dropped: 0"), true);
  assertEquals(joined.includes("already present: 0"), true);
  assertEquals(joined.includes("to insert: 2"), true);
});

Deno.test("runBackfill: execute-mode summary carries window + all four counts", async () => {
  const { deps, logs } = makeDeps();
  await runBackfill(deps, { execute: true });
  const joined = logs.join("\n");
  assertEquals(joined.includes("execute"), true);
  assertEquals(joined.includes("inserted"), true);
  assertEquals(joined.includes("alpaca days fetched: 2"), true);
  assertEquals(joined.includes("zero/invalid equity dropped: 0"), true);
  assertEquals(joined.includes("already present: 0"), true);
  assertEquals(joined.includes("inserted: 2"), true);
});

// ---------------------------------------------------------------------------
// T4 — real-deps adapters. No test constructs real network traffic: DB
// adapters get a hand-rolled chainable stub (every method records the call
// and returns itself; the chain resolves via `.then`, matching how the real
// PostgREST query builder is awaited); the fetch adapter stubs
// `globalThis.fetch` for the duration of each test.
// ---------------------------------------------------------------------------

interface StubCall {
  method: string;
  args: unknown[];
}

function makeChainable(result: { data: unknown; error: unknown }): {
  sb: unknown;
  calls: StubCall[];
} {
  const calls: StubCall[] = [];
  // deno-lint-ignore no-explicit-any
  const proxy: any = new Proxy(function () {}, {
    get(_t, prop) {
      if (prop === "then") {
        return (onFulfilled: (v: unknown) => unknown, onRejected?: (e: unknown) => unknown) =>
          Promise.resolve(result).then(onFulfilled, onRejected);
      }
      return (...args: unknown[]) => {
        calls.push({ method: String(prop), args });
        return proxy;
      };
    },
  });
  return { sb: proxy, calls };
}

Deno.test("getEarliestAuditStartedAtAdapter: audit_log ordered ascending, limit 1, maybeSingle", async () => {
  const { sb, calls } = makeChainable({
    data: { started_at: "2026-01-01T00:00:00Z" },
    error: null,
  });
  const result = await getEarliestAuditStartedAtAdapter(sb as unknown as SupabaseClient);
  assertEquals(result, "2026-01-01T00:00:00Z");
  assertEquals(calls[0], { method: "from", args: ["audit_log"] });
  assertEquals(
    calls.some((c) =>
      c.method === "order" && c.args[0] === "started_at" &&
      (c.args[1] as { ascending: boolean }).ascending === true
    ),
    true,
  );
  assertEquals(calls.some((c) => c.method === "limit" && c.args[0] === 1), true);
});

Deno.test("getEarliestAuditStartedAtAdapter: empty audit_log (null data) -> null", async () => {
  const { sb } = makeChainable({ data: null, error: null });
  const result = await getEarliestAuditStartedAtAdapter(sb as unknown as SupabaseClient);
  assertEquals(result, null);
});

Deno.test("getExistingSnapshotDatesAdapter: selects date, .gte('date', since), .limit(1000), maps rows", async () => {
  const { sb, calls } = makeChainable({
    data: [{ date: "2026-01-01" }, { date: "2026-01-02" }],
    error: null,
  });
  const result = await getExistingSnapshotDatesAdapter(
    sb as unknown as SupabaseClient,
    "2026-01-01",
  );
  assertEquals(result, ["2026-01-01", "2026-01-02"]);
  assertEquals(calls[0], { method: "from", args: ["equity_snapshots"] });
  assertEquals(
    calls.some((c) => c.method === "gte" && c.args[0] === "date" && c.args[1] === "2026-01-01"),
    true,
  );
  assertEquals(calls.some((c) => c.method === "limit" && c.args[0] === 1000), true);
});

Deno.test("getExistingSnapshotDatesAdapter: PostgREST 42P01 throws EquitySnapshotsTableMissingError", async () => {
  const { sb } = makeChainable({
    data: null,
    error: { code: "42P01", message: 'relation "equity_snapshots" does not exist' },
  });
  await assertRejects(
    () => getExistingSnapshotDatesAdapter(sb as unknown as SupabaseClient, "2026-01-01"),
    EquitySnapshotsTableMissingError,
  );
});

Deno.test("insertSnapshotsIgnoreDuplicatesAdapter: pins onConflict:'date' + ignoreDuplicates:true, selects date", async () => {
  const rows = [{ date: "2026-01-01", equity_usd: 100 }];
  const { sb, calls } = makeChainable({ data: [{ date: "2026-01-01" }], error: null });
  const result = await insertSnapshotsIgnoreDuplicatesAdapter(
    sb as unknown as SupabaseClient,
    rows,
  );
  assertEquals(result, ["2026-01-01"]);
  const upsertCall = calls.find((c) => c.method === "upsert");
  assertEquals(upsertCall?.args[0], rows);
  assertEquals(upsertCall?.args[1], { onConflict: "date", ignoreDuplicates: true });
  assertEquals(calls.some((c) => c.method === "select" && c.args[0] === "date"), true);
});

Deno.test("insertSnapshotsIgnoreDuplicatesAdapter: empty rows -> no DB call, returns []", async () => {
  const { sb, calls } = makeChainable({ data: [], error: null });
  const result = await insertSnapshotsIgnoreDuplicatesAdapter(sb as unknown as SupabaseClient, []);
  assertEquals(result, []);
  assertEquals(calls.length, 0);
});

function withStubbedFetch<T>(
  impl: (url: string, init?: RequestInit) => Promise<Response>,
  fn: () => Promise<T>,
): Promise<T> {
  const original = globalThis.fetch;
  // deno-lint-ignore no-explicit-any
  globalThis.fetch = ((url: any, init?: RequestInit) => impl(String(url), init)) as typeof fetch;
  return fn().finally(() => {
    globalThis.fetch = original;
  });
}

const ALPACA_CFG = {
  tradingBaseUrl: "https://paper-api.alpaca.markets",
  apiKeyId: "key123",
  apiSecretKey: "secret456",
};

Deno.test("fetchPortfolioHistoryAdapter: builds timeframe=1D + start URL, sends Alpaca auth headers", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const result = await withStubbedFetch(
    (url, init) => {
      calls.push({ url, init });
      return Promise.resolve(
        new Response(JSON.stringify({ timestamp: [1], equity: [100] }), { status: 200 }),
      );
    },
    () => fetchPortfolioHistoryAdapter(ALPACA_CFG, "2026-01-01"),
  );
  assertEquals(result, { timestamp: [1], equity: [100] });
  assertEquals(calls.length, 1);
  assertEquals(calls[0].url.includes("timeframe=1D"), true);
  assertEquals(calls[0].url.includes("2026-01-01"), true);
  const headers = new Headers(calls[0].init?.headers);
  assertEquals(headers.get("APCA-API-KEY-ID"), "key123");
  assertEquals(headers.get("APCA-API-SECRET-KEY"), "secret456");
});

Deno.test("fetchPortfolioHistoryAdapter: non-2xx throws with status, no secret in message", async () => {
  const err = await withStubbedFetch(
    () => Promise.resolve(new Response("unauthorized", { status: 401 })),
    () =>
      assertRejects(
        () => fetchPortfolioHistoryAdapter(ALPACA_CFG, "2026-01-01"),
        Error,
      ),
  );
  assertEquals(err.message.includes("401"), true);
  assertEquals(err.message.includes("secret456"), false);
});

Deno.test("fetchPortfolioHistoryAdapter: a fetch rejection is wrapped, not swallowed", async () => {
  const err = await withStubbedFetch(
    () => Promise.reject(new Error("network down")),
    () =>
      assertRejects(
        () => fetchPortfolioHistoryAdapter(ALPACA_CFG, "2026-01-01"),
        Error,
      ),
  );
  assertEquals(err.message.includes("network down"), true);
});

Deno.test("fetchPortfolioHistoryAdapter: missing timestamp/equity arrays throws a clear error", async () => {
  const err = await withStubbedFetch(
    () => Promise.resolve(new Response(JSON.stringify({ foo: "bar" }), { status: 200 })),
    () =>
      assertRejects(
        () => fetchPortfolioHistoryAdapter(ALPACA_CFG, "2026-01-01"),
        Error,
      ),
  );
  assertEquals(err.message.includes("unexpected response shape"), true);
});
