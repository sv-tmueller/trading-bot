// Unit tests for the daily-verification evaluator (#547, batch #545 Package
// B). Pure core only -- see daily_verify.ts's own header comment for the
// CLI/permission split. Structured like deadman_check.test.ts: explicit
// `now`/input construction, no network, no DB, no env.
import { assertEquals } from "@std/assert";
import { isWeekendYmd, resolveTargetDate } from "./daily_verify.ts";

function utc(iso: string): Date {
  return new Date(iso);
}

// ---------------------------------------------------------------------------
// resolveTargetDate (spec §5.4)
// ---------------------------------------------------------------------------

Deno.test("resolveTargetDate: explicit date wins verbatim regardless of now", () => {
  assertEquals(resolveTargetDate(utc("2026-08-06T00:00:00Z"), "2026-08-01"), "2026-08-01");
});

Deno.test("resolveTargetDate: no explicit date, UTC hour >= 12 -> today", () => {
  assertEquals(resolveTargetDate(utc("2026-08-06T12:00:00Z")), "2026-08-06");
  assertEquals(resolveTargetDate(utc("2026-08-06T23:59:00Z")), "2026-08-06");
});

Deno.test("resolveTargetDate: no explicit date, UTC hour < 12 -> previous UTC day", () => {
  assertEquals(resolveTargetDate(utc("2026-08-06T00:00:00Z")), "2026-08-05");
  assertEquals(resolveTargetDate(utc("2026-08-06T11:59:00Z")), "2026-08-05");
});

Deno.test("resolveTargetDate: past-midnight jitter just after 00:00 still resolves to the previous day", () => {
  assertEquals(resolveTargetDate(utc("2026-08-06T00:03:00Z")), "2026-08-05");
});

Deno.test("resolveTargetDate: exactly at the 12:00 UTC boundary resolves to today", () => {
  assertEquals(resolveTargetDate(utc("2026-08-06T12:00:00.000Z")), "2026-08-06");
});

Deno.test("resolveTargetDate: month rollover on the previous-day branch", () => {
  assertEquals(resolveTargetDate(utc("2026-09-01T00:00:00Z")), "2026-08-31");
});

// ---------------------------------------------------------------------------
// isWeekendYmd (spec §5.4 / D12)
// ---------------------------------------------------------------------------

Deno.test("isWeekendYmd: Saturday -> true", () => {
  assertEquals(isWeekendYmd("2026-08-08"), true);
});

Deno.test("isWeekendYmd: Sunday -> true", () => {
  assertEquals(isWeekendYmd("2026-08-09"), true);
});

Deno.test("isWeekendYmd: Monday -> false", () => {
  assertEquals(isWeekendYmd("2026-08-10"), false);
});

Deno.test("isWeekendYmd: Friday -> false", () => {
  assertEquals(isWeekendYmd("2026-08-07"), false);
});
