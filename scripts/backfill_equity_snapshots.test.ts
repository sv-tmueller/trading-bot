// Unit tests for the equity_snapshots backfill script (#389). Every dep is a
// plain injected mock — no network, no real Supabase client construction.
// CLAUDE_AGENT_NO_BROKER is set by the `test` deno.json task; this script
// adds no mutating broker helper, so the guard is inert here (defense in
// depth only).
import { assertEquals, assertRejects, assertThrows } from "@std/assert";
import {
  type BackfillDeps,
  EquitySnapshotsTableMissingError,
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
  const { rows } = mapHistoryToDailyRows(history, "2026-07-15");
  assertEquals(rows, [{ date: "2026-01-05", equity_usd: 100234.56 }]);
});

Deno.test("mapHistoryToDailyRows: excludes today (ET) and later", () => {
  const history = {
    timestamp: [
      sec("2026-07-14T20:00:00Z"), // 2026-07-14 ET (EDT, UTC-4 in July)
      sec("2026-07-15T20:00:00Z"), // 2026-07-15 ET == todayEt, excluded
    ],
    equity: [100, 200],
  };
  const { rows, alpacaDays } = mapHistoryToDailyRows(history, "2026-07-15");
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
  const { rows, zeroEquityDropped } = mapHistoryToDailyRows(history, "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-13", equity_usd: 42 }]);
  assertEquals(zeroEquityDropped, 3);
});

Deno.test("mapHistoryToDailyRows: requireNumber accepts numeric strings", () => {
  const history = {
    timestamp: [sec("2026-07-10T20:00:00Z")],
    equity: ["1234.5"],
  };
  const { rows } = mapHistoryToDailyRows(history, "2026-07-15");
  assertEquals(rows, [{ date: "2026-07-10", equity_usd: 1234.5 }]);
});

Deno.test("mapHistoryToDailyRows: parallel-array length mismatch throws a clear error", () => {
  const history = { timestamp: [sec("2026-07-10T20:00:00Z"), sec("2026-07-11T20:00:00Z")], equity: [1] };
  assertThrows(
    () => mapHistoryToDailyRows(history, "2026-07-15"),
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
        throw new EquitySnapshotsTableMissingError("relation \"equity_snapshots\" does not exist");
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
});

Deno.test("runBackfill: execute-mode summary carries window + all four counts", async () => {
  const { deps, logs } = makeDeps();
  await runBackfill(deps, { execute: true });
  const joined = logs.join("\n");
  assertEquals(joined.includes("execute"), true);
  assertEquals(joined.includes("inserted"), true);
});
