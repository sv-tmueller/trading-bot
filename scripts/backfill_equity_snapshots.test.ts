// Unit tests for the equity_snapshots backfill script (#389). Every dep is a
// plain injected mock — no network, no real Supabase client construction.
// CLAUDE_AGENT_NO_BROKER is set by the `test` deno.json task; this script
// adds no mutating broker helper, so the guard is inert here (defense in
// depth only).
import { assertEquals, assertThrows } from "@std/assert";
import { mapHistoryToDailyRows, parseArgs } from "./backfill_equity_snapshots.ts";

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
