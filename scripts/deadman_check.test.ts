// Unit tests for the dead-man watchdog's pure evaluation logic (#396 T2).
// Pure function, no network/DB/env — every case constructs `now` and
// `lastRuns` explicitly. See the #396 SUB_PLAN (issue comment) for the
// design decisions this test matrix encodes (boundary times, arm windows).
import { assertEquals, assertThrows } from "@std/assert";
import { type DeadmanLastRuns, evaluateDeadman } from "./deadman_check.ts";

// 2026-07-20 is a Monday (weekday); 2026-07-18/19 are Sat/Sun.
const MON = "2026-07-20";
const SUN = "2026-07-19";
const SAT = "2026-07-18";

function utc(date: string, hhmm: string): Date {
  return new Date(`${date}T${hhmm}:00Z`);
}

function healthyLastRuns(dailyCheckIso: string, killSwitchIso: string): DeadmanLastRuns {
  return {
    daily_check: { started_at: dailyCheckIso, outcome: "success" },
    kill_switch: { started_at: killSwitchIso, outcome: "success" },
  };
}

Deno.test("weekend (Saturday) -> no findings, even with everything stale/absent", () => {
  const lastRuns: DeadmanLastRuns = { daily_check: null, kill_switch: null };
  assertEquals(evaluateDeadman(lastRuns, utc(SAT, "15:05")), []);
});

Deno.test("weekend (Sunday) -> no findings, even with everything stale/absent", () => {
  const lastRuns: DeadmanLastRuns = { daily_check: null, kill_switch: null };
  assertEquals(evaluateDeadman(lastRuns, utc(SUN, "15:05")), []);
});

// ---------------------------------------------------------------------------
// daily-check: armed only once both pg_cron slots (13:37 + 14:37 UTC) have
// had a chance to run — 15:00 UTC per the SUB_PLAN's grace window.
// ---------------------------------------------------------------------------

Deno.test("weekday 14:00 UTC, no row today -> no daily-check finding (not armed yet — before 15:00)", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: null,
    kill_switch: { started_at: utc(MON, "13:55").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "14:00")), []);
});

Deno.test("weekday 15:05 UTC, daily-check row at 13:38 today -> healthy", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "13:38").toISOString(),
    utc(MON, "14:55").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("weekday 15:05 UTC, daily-check row from yesterday -> finding", () => {
  const lastRuns = healthyLastRuns(
    utc(SUN, "13:38").toISOString(),
    utc(MON, "14:55").toISOString(),
  );
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("daily-check"), true);
});

Deno.test("weekday 15:05 UTC, last_runs.daily_check === null -> finding", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: null,
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "success" },
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("daily-check"), true);
});

Deno.test("weekday 15:05 UTC, today's daily-check row has outcome skipped:market_closed -> healthy (outcome content ignored)", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: { started_at: utc(MON, "13:37").toISOString(), outcome: "skipped:market_closed" },
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "skipped:market_closed" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

// ---------------------------------------------------------------------------
// kill-switch: armed in [13:20, 22:10] UTC; stale past 20 minutes (4 missed
// 5-minute slots) or absent inside the window.
// ---------------------------------------------------------------------------

Deno.test("kill-switch: 15:05 UTC, row 10 minutes old -> healthy", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "13:37").toISOString(),
    utc(MON, "14:55").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("kill-switch: 15:05 UTC, row 25 minutes old -> finding", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "13:37").toISOString(),
    utc(MON, "14:40").toISOString(),
  );
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("kill-switch"), true);
});

Deno.test("kill-switch: 15:05 UTC, last_runs.kill_switch === null (inside window) -> finding", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: { started_at: utc(MON, "13:37").toISOString(), outcome: "success" },
    kill_switch: null,
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("kill-switch"), true);
});

Deno.test("kill-switch: 12:00 UTC with a stale row -> no finding (window not yet armed)", () => {
  const lastRuns = healthyLastRuns(
    utc(SUN, "13:37").toISOString(), // daily-check not armed at 12:00 either
    utc(MON, "09:00").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "12:00")), []);
});

Deno.test("kill-switch: 22:30 UTC with a stale row -> no finding (window no longer armed)", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "13:37").toISOString(),
    utc(MON, "20:00").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "22:30")), []);
});

Deno.test("kill-switch: 13:10 UTC -> no finding (window not yet armed)", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: null, // 13:10 also < daily-check's 15:00 arm time
    kill_switch: null,
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "13:10")), []);
});

Deno.test("kill-switch: 22:05 UTC with a row at 21:55 -> healthy (10 min old, window still armed through 22:10)", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "13:37").toISOString(),
    utc(MON, "21:55").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "22:05")), []);
});

// ---------------------------------------------------------------------------
// Timestamp parsing + malformed-input error paths (CLI exit 1).
// ---------------------------------------------------------------------------

Deno.test("timestamp with +00:00 offset (PostgREST timestamptz format) parses identically to Z", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: { started_at: "2026-07-20T13:37:00+00:00", outcome: "success" },
    kill_switch: { started_at: "2026-07-20T14:55:00+00:00", outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("malformed started_at timestamp -> throws", () => {
  const lastRuns: DeadmanLastRuns = {
    daily_check: { started_at: "not-a-timestamp", outcome: "success" },
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "success" },
  };
  assertThrows(() => evaluateDeadman(lastRuns, utc(MON, "15:05")));
});

Deno.test("missing last_runs (undefined) -> throws", () => {
  assertThrows(() => evaluateDeadman(undefined as unknown as DeadmanLastRuns, utc(MON, "15:05")));
});

Deno.test("missing last_runs (null) -> throws", () => {
  assertThrows(() => evaluateDeadman(null as unknown as DeadmanLastRuns, utc(MON, "15:05")));
});
