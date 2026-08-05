// Unit tests for the dead-man watchdog's pure evaluation logic (#396 T2,
// repointed at hourly-check by #537). Pure function, no network/DB/env --
// every case constructs `now` and `lastRuns` explicitly. See the #537
// SUB_PLAN (issue comment) for the design decisions this test matrix
// encodes (boundary times, arm windows, undefined-vs-null).
import { assertEquals, assertThrows } from "@std/assert";
import { type DeadmanLastRuns, evaluateDeadman } from "./deadman_check.ts";

// 2026-07-20 is a Monday (weekday); 2026-07-18/19 are Sat/Sun.
const MON = "2026-07-20";
const SUN = "2026-07-19";
const SAT = "2026-07-18";

function utc(date: string, hhmm: string): Date {
  return new Date(`${date}T${hhmm}:00Z`);
}

function healthyLastRuns(killSwitchIso: string, hourlyCheckIso: string): DeadmanLastRuns {
  return {
    kill_switch: { started_at: killSwitchIso, outcome: "success" },
    hourly_check: { started_at: hourlyCheckIso, outcome: "success" },
  };
}

// ---------------------------------------------------------------------------
// Weekend: everything inert regardless of staleness/absence/nullness.
// ---------------------------------------------------------------------------

Deno.test("weekend (Saturday) -> no findings, even with everything stale/absent", () => {
  const lastRuns: DeadmanLastRuns = { kill_switch: null, hourly_check: null };
  assertEquals(evaluateDeadman(lastRuns, utc(SAT, "15:05")), []);
});

Deno.test("weekend (Sunday) -> no findings, even with everything stale/absent", () => {
  const lastRuns: DeadmanLastRuns = { kill_switch: null, hourly_check: null };
  assertEquals(evaluateDeadman(lastRuns, utc(SUN, "15:05")), []);
});

Deno.test("weekend (Saturday), hourly_check key omitted entirely -> no findings", () => {
  const lastRuns: DeadmanLastRuns = { kill_switch: null };
  assertEquals(evaluateDeadman(lastRuns, utc(SAT, "15:05")), []);
});

Deno.test("weekend (Saturday), hourly_check present but stale -> no findings", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: null,
    hourly_check: { started_at: utc(SUN, "10:00").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(SAT, "15:05")), []);
});

// ---------------------------------------------------------------------------
// hourly-check: armed in [14:22, 22:10] UTC (derived from the "7 13-21 * *
// 1-5" UTC pg_cron -- 9 daily slots, first 13:07, last 21:07 -- as
// armStart = firstSlot + staleThreshold and armEnd <= lastSlot +
// staleThreshold); stale past 75 minutes (60-minute cadence + ~15 minutes'
// grace) or absent/null inside the window.
// ---------------------------------------------------------------------------

Deno.test("weekday before hourly-check arm-start (14:00 UTC), hourly_check absent -> no finding", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "13:55").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "14:00")), []);
});

Deno.test("weekday before hourly-check arm-start (14:00 UTC), hourly_check null -> no finding", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "13:55").toISOString(), outcome: "success" },
    hourly_check: null,
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "14:00")), []);
});

Deno.test("weekday before hourly-check arm-start (14:00 UTC), hourly_check stale -> no finding", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "13:55").toISOString(), outcome: "success" },
    hourly_check: { started_at: utc(SUN, "13:07").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "14:00")), []);
});

Deno.test("hourly-check: 15:05 UTC, row 15 minutes old -> healthy", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "14:55").toISOString(),
    utc(MON, "14:50").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("hourly-check: 16:00 UTC, row 90 minutes old -> finding mentions hourly-check and stale", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "15:55").toISOString(),
    utc(MON, "14:30").toISOString(),
  );
  const findings = evaluateDeadman(lastRuns, utc(MON, "16:00"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("hourly-check"), true);
  assertEquals(findings[0].includes("stale"), true);
});

Deno.test("hourly-check: 15:05 UTC, last_runs.hourly_check === null -> finding names 'no audit_log row'", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "success" },
    hourly_check: null,
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("hourly-check"), true);
  assertEquals(findings[0].includes("no audit_log row"), true);
});

Deno.test("hourly-check: 15:05 UTC, hourly_check key omitted entirely -> finding names predates-hourly-coverage/redeploy", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "success" },
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("predates hourly-bot coverage"), true);
  assertEquals(findings[0].includes("redeploy"), true);
});

Deno.test("hourly-check: 15:05 UTC, today's row outcome skipped:market_closed -> healthy (outcome content ignored)", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "skipped:market_closed" },
    hourly_check: {
      started_at: utc(MON, "14:50").toISOString(),
      outcome: "skipped:market_closed",
    },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("hourly-check: 15:05 UTC, today's row outcome skipped:trading_paused -> healthy (outcome content ignored)", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "skipped:trading_paused" },
    hourly_check: {
      started_at: utc(MON, "14:50").toISOString(),
      outcome: "skipped:trading_paused",
    },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

// ---------------------------------------------------------------------------
// Boundary cases: arm-start/arm-end derivation (armStart = firstSlot +
// threshold, armEnd <= lastSlot + threshold) and the exact staleness
// threshold.
// ---------------------------------------------------------------------------

Deno.test("hourly-check: at arm-start (14:22 UTC), a row from the first slot (13:07 UTC, exactly 75 min old) -> healthy, no false alarm at window open", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:15").toISOString(), outcome: "success" },
    hourly_check: { started_at: utc(MON, "13:07").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "14:22")), []);
});

Deno.test("hourly-check: at arm-start (14:22 UTC), a row older than the first slot's grace (76 min) -> finding", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:15").toISOString(), outcome: "success" },
    hourly_check: { started_at: utc(MON, "13:06").toISOString(), outcome: "success" },
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "14:22"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("hourly-check"), true);
});

Deno.test("hourly-check: exactly at the 75-minute stale threshold -> healthy", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "15:55").toISOString(), outcome: "success" },
    hourly_check: { started_at: utc(MON, "14:45").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "16:00")), []);
});

Deno.test("hourly-check: one minute past the 75-minute stale threshold -> finding", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "15:55").toISOString(), outcome: "success" },
    hourly_check: { started_at: utc(MON, "14:44").toISOString(), outcome: "success" },
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "16:00"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("hourly-check"), true);
});

Deno.test("hourly-check: 22:05 UTC with a row at 21:55 -> healthy (10 min old, window still armed through 22:10)", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "21:55").toISOString(),
    utc(MON, "21:55").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "22:05")), []);
});

Deno.test("hourly-check: 23:00 UTC (past arm-end), hourly_check absent -> no finding (window no longer armed)", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: null,
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "23:00")), []);
});

Deno.test("hourly-check: 22:30 UTC (past arm-end) with a very stale row -> no finding (window no longer armed)", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "20:00").toISOString(), outcome: "success" },
    hourly_check: { started_at: utc(MON, "13:07").toISOString(), outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "22:30")), []);
});

// ---------------------------------------------------------------------------
// kill-switch: armed in [13:20, 22:10] UTC; stale past 20 minutes (4 missed
// 5-minute slots) or absent inside the window. Logic unchanged from #396 --
// only the literals below gained an hourly_check field (kept fresh relative
// to each test's own `now` so it never leaks an unrelated finding).
// ---------------------------------------------------------------------------

Deno.test("kill-switch: 15:05 UTC, row 10 minutes old -> healthy", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "14:55").toISOString(),
    utc(MON, "14:50").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("kill-switch: 15:05 UTC, row 25 minutes old -> finding", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "14:40").toISOString(),
    utc(MON, "14:50").toISOString(),
  );
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("kill-switch"), true);
});

Deno.test("kill-switch: 15:05 UTC, last_runs.kill_switch === null (inside window) -> finding", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: null,
    hourly_check: { started_at: utc(MON, "14:50").toISOString(), outcome: "success" },
  };
  const findings = evaluateDeadman(lastRuns, utc(MON, "15:05"));
  assertEquals(findings.length, 1);
  assertEquals(findings[0].includes("kill-switch"), true);
});

Deno.test("kill-switch: 12:00 UTC with a stale row -> no finding (window not yet armed)", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "09:00").toISOString(), outcome: "success" },
    hourly_check: null, // hourly-check not armed at 12:00 either (arms 14:22)
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "12:00")), []);
});

Deno.test("kill-switch: 22:30 UTC with a stale row -> no finding (window no longer armed)", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "20:00").toISOString(),
    utc(MON, "20:00").toISOString(), // also stale, but hourly-check window is closed by 22:30 too
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "22:30")), []);
});

Deno.test("kill-switch: 13:10 UTC -> no finding (window not yet armed)", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: null,
    hourly_check: null, // 13:10 also < hourly-check's 14:22 arm time
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "13:10")), []);
});

Deno.test("kill-switch: 22:05 UTC with a row at 21:55 -> healthy (10 min old, window still armed through 22:10)", () => {
  const lastRuns = healthyLastRuns(
    utc(MON, "21:55").toISOString(),
    utc(MON, "21:55").toISOString(),
  );
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "22:05")), []);
});

// ---------------------------------------------------------------------------
// Timestamp parsing + malformed-input error paths (CLI exit 1).
// ---------------------------------------------------------------------------

Deno.test("timestamp with +00:00 offset (PostgREST timestamptz format) parses identically to Z", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: "2026-07-20T14:55:00+00:00", outcome: "success" },
    hourly_check: { started_at: "2026-07-20T14:50:00+00:00", outcome: "success" },
  };
  assertEquals(evaluateDeadman(lastRuns, utc(MON, "15:05")), []);
});

Deno.test("malformed kill_switch.started_at timestamp -> throws", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: "not-a-timestamp", outcome: "success" },
    hourly_check: { started_at: utc(MON, "14:50").toISOString(), outcome: "success" },
  };
  assertThrows(() => evaluateDeadman(lastRuns, utc(MON, "15:05")));
});

Deno.test("malformed hourly_check.started_at timestamp -> throws", () => {
  const lastRuns: DeadmanLastRuns = {
    kill_switch: { started_at: utc(MON, "14:55").toISOString(), outcome: "success" },
    hourly_check: { started_at: "not-a-timestamp", outcome: "success" },
  };
  assertThrows(() => evaluateDeadman(lastRuns, utc(MON, "15:05")));
});

Deno.test("missing last_runs (undefined) -> throws", () => {
  assertThrows(() => evaluateDeadman(undefined as unknown as DeadmanLastRuns, utc(MON, "15:05")));
});

Deno.test("missing last_runs (null) -> throws", () => {
  assertThrows(() => evaluateDeadman(null as unknown as DeadmanLastRuns, utc(MON, "15:05")));
});
