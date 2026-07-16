// Unit tests for the equity_snapshots backfill script (#389). Every dep is a
// plain injected mock — no network, no real Supabase client construction.
// CLAUDE_AGENT_NO_BROKER is set by the `test` deno.json task; this script
// adds no mutating broker helper, so the guard is inert here (defense in
// depth only).
import { assertEquals, assertThrows } from "@std/assert";
import { parseArgs } from "./backfill_equity_snapshots.ts";

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
