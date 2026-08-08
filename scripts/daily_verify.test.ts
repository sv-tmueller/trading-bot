// Unit tests for the daily-verification evaluator (#547, batch #545 Package
// B). Pure core only -- see daily_verify.ts's own header comment for the
// CLI/permission split. Structured like deadman_check.test.ts: explicit
// `now`/input construction, no network, no DB, no env.
import { assertEquals, assertThrows } from "@std/assert";
import type { HourlyScanRow, TradeRow } from "../supabase/functions/_shared/db.ts";
import {
  buildLedgerRow,
  buildSummary,
  checkGeometry,
  checkJournal,
  checkKillSwitch,
  checkLatency,
  checkScans,
  checkSlots,
  checkState,
  deriveMissingKillSwitchSlots,
  evaluateVerification,
  formatMissingSlots,
  HOURLY_SLOTS_PER_WEEKDAY,
  isWeekendYmd,
  KILL_SWITCH_SLOTS_PER_WEEKDAY,
  type LedgerRow,
  MalformedVerificationError,
  NON_SCANNING_OUTCOMES,
  parseVerificationBlock,
  renderMarkdownDigest,
  resolveTargetDate,
  selectPreviousRow,
  upsertLedgerJsonl,
  type VerificationBlock,
  type VerifyHourlyCheckRun,
} from "./daily_verify.ts";

// The full 108-slot grid of kill-switch started_at timestamps for a clean
// weekday, 13:00 through 21:55 UTC every 5 minutes -- shared by the
// deriveMissingKillSwitchSlots and fixture tests below.
function fullKillSwitchGrid(dateYmd = "2026-08-07"): string[] {
  return Array.from({ length: KILL_SWITCH_SLOTS_PER_WEEKDAY }, (_, i) => {
    const totalMinutes = 13 * 60 + i * 5;
    const h = String(Math.floor(totalMinutes / 60)).padStart(2, "0");
    const m = String(totalMinutes % 60).padStart(2, "0");
    return `${dateYmd}T${h}:${m}:00.000Z`;
  });
}

// ---------------------------------------------------------------------------
// Fixture builders -- minimal, complete rows so every test only spells out
// the field(s) it actually varies.
// ---------------------------------------------------------------------------

function scanRow(overrides: Partial<HourlyScanRow> = {}): HourlyScanRow {
  return {
    symbol: "SPY",
    bar_ts: "2026-08-05T13:00:00.000Z",
    decision: "SKIP",
    skip_reason: "no_detectors_fired",
    detectors_fired: [],
    context_mode: "sma",
    entry_ref_price: null,
    stop_price: null,
    target_price: null,
    risk_per_share: null,
    equity_usd: 1_000_000,
    qty: 0,
    entry_order_id: null,
    ...overrides,
  };
}

function tradeRow(overrides: Partial<TradeRow> = {}): TradeRow {
  return {
    symbol: "SPY",
    side: "BUY",
    qty: 100,
    fill_price: 500,
    fill_time: "2026-08-05T14:07:00.000Z",
    reason: "hourly_long_entry",
    broker_order_id: "order-1",
    ...overrides,
  };
}

function hourlyRun(overrides: Partial<VerifyHourlyCheckRun> = {}): VerifyHourlyCheckRun {
  return {
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:01.000Z",
    outcome: "success:no_action",
    notes: null,
    ...overrides,
  };
}

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

// ---------------------------------------------------------------------------
// NON_SCANNING_OUTCOMES (spec §5.3): pinned against the five gates in
// supabase/functions/hourly-check/logic.ts that return before any
// hourly_scans journal write for the run's own candidate bar, per the #545
// architect's traced derivation (issue #547 SUB_PLAN):
//   1. skipped:trading_paused   -- gate 1, operational pause (~line 677-681):
//      returns before reconcile() and before the bar fetch.
//   2. skipped:market_closed    -- gate 3, market-open gate (~line 687-691):
//      same, precedes reconcile() entirely.
//   3. error:naked_position_flattened -- reconcile()'s terminal branch
//      (~line 576-627): returned via recon.terminalOutcome, short-circuits
//      before the bar fetch.
//   4. success:auto_paused      -- gate 6, equity floor fires (~line
//      754-803): calls finish() directly, deliberately bypassing done(),
//      before the gate-7 bar fetch.
//   5. skipped:duplicate_run    -- gate 19, bar-claim loser (~line
//      1136-1141): the file's own comment says the loser writes audit only
//      and must not upsert.
// Confirmed NOT in the set (all journal before returning): skipped:partial_bar
// and skipped:stale_data (both via preDecisionSkip -> journalSkip, ~line
// 922-950), every gateSkip() outcome, the SKIP-decision outcomes
// (skipped:signal_conflict, success:no_action), skipped:geometry_invalid,
// skipped:size_too_small, and success / success:journal_degraded (preceded by
// the pre-order journal at ~line 1147). error:* outcomes are excluded
// generally -- they are dynamic (err.name), not enumerable, and the `slots`
// check already FAILs any error:* regardless of how `scans` classifies it.
Deno.test("NON_SCANNING_OUTCOMES: exactly the five outcomes derived from hourly-check/logic.ts's gate order", () => {
  assertEquals(
    NON_SCANNING_OUTCOMES,
    new Set([
      "skipped:trading_paused",
      "skipped:market_closed",
      "error:naked_position_flattened",
      "success:auto_paused",
      "skipped:duplicate_run",
    ]),
  );
});

Deno.test("NON_SCANNING_OUTCOMES: does not contain skipped:partial_bar or skipped:stale_data (both journal via preDecisionSkip)", () => {
  assertEquals(NON_SCANNING_OUTCOMES.has("skipped:partial_bar"), false);
  assertEquals(NON_SCANNING_OUTCOMES.has("skipped:stale_data"), false);
});

Deno.test("NON_SCANNING_OUTCOMES: does not contain any gateSkip()/SKIP-decision/success outcome", () => {
  for (
    const outcome of [
      "skipped:session_close_flatten_only",
      "skipped:kill_switch_active",
      "skipped:position_open",
      "skipped:cooldown",
      "skipped:max_entries_reached",
      "skipped:shorts_disabled",
      "skipped:not_shortable",
      "skipped:signal_conflict",
      "skipped:geometry_invalid",
      "skipped:size_too_small",
      "success:no_action",
      "success",
      "success:journal_degraded",
    ]
  ) {
    assertEquals(NON_SCANNING_OUTCOMES.has(outcome), false, outcome);
  }
});

// ---------------------------------------------------------------------------
// checkSlots (§5.3 check 1)
// ---------------------------------------------------------------------------

Deno.test("checkSlots: 9 finished runs, no error outcomes -> PASS", () => {
  const runs = Array.from({ length: 9 }, () => hourlyRun());
  assertEquals(checkSlots(runs), { status: "PASS", findings: [] });
});

Deno.test("checkSlots: fewer than 9 runs -> FAIL", () => {
  const runs = Array.from({ length: 8 }, () => hourlyRun());
  const result = checkSlots(runs);
  assertEquals(result.status, "FAIL");
  assertEquals(result.findings.length > 0, true);
});

Deno.test("checkSlots: a run with finished_at null -> FAIL", () => {
  const runs = [
    ...Array.from({ length: 8 }, () => hourlyRun()),
    hourlyRun({ finished_at: null, outcome: null }),
  ];
  assertEquals(checkSlots(runs).status, "FAIL");
});

Deno.test("checkSlots: a run with outcome starting error: -> FAIL", () => {
  const runs = [
    ...Array.from({ length: 8 }, () => hourlyRun()),
    hourlyRun({ outcome: "error:AlpacaError" }),
  ];
  assertEquals(checkSlots(runs).status, "FAIL");
});

// ---------------------------------------------------------------------------
// checkLatency (§5.3 check 5)
// ---------------------------------------------------------------------------

Deno.test("checkLatency: every run well under the warn threshold -> PASS", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:02.000Z",
  })];
  assertEquals(checkLatency(runs), { status: "PASS", findings: [] });
});

Deno.test("checkLatency: just over the 10s warn threshold -> WARN", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:10.001Z",
  })];
  const result = checkLatency(runs);
  assertEquals(result.status, "WARN");
  assertEquals(result.findings.length, 1);
});

Deno.test("checkLatency: exactly at the 10s warn threshold -> PASS (boundary is exclusive)", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:10.000Z",
  })];
  assertEquals(checkLatency(runs), { status: "PASS", findings: [] });
});

Deno.test("checkLatency: just over the 120s fail threshold -> FAIL", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:09:00.001Z",
  })];
  assertEquals(checkLatency(runs).status, "FAIL");
});

Deno.test("checkLatency: a FAIL run alongside a WARN run -> overall FAIL (highest severity wins)", () => {
  const runs = [
    hourlyRun({
      started_at: "2026-08-05T13:07:00.000Z",
      finished_at: "2026-08-05T13:07:10.001Z",
    }),
    hourlyRun({
      started_at: "2026-08-05T14:07:00.000Z",
      finished_at: "2026-08-05T14:09:00.001Z",
    }),
  ];
  assertEquals(checkLatency(runs).status, "FAIL");
});

Deno.test("checkLatency: unfinished run (finished_at null) is skipped, not a latency finding", () => {
  const runs = [hourlyRun({ finished_at: null, outcome: null })];
  assertEquals(checkLatency(runs), { status: "PASS", findings: [] });
});

// ---------------------------------------------------------------------------
// checkScans (§5.3 check 2)
// ---------------------------------------------------------------------------

function verificationForScans(overrides: {
  hourly_check_runs?: VerifyHourlyCheckRun[];
  scans?: HourlyScanRow[];
  shorts_enabled?: boolean;
}) {
  return {
    shorts_enabled: overrides.shorts_enabled ?? true,
    hourly_check_runs: overrides.hourly_check_runs ?? [],
    scans: overrides.scans ?? [],
  };
}

Deno.test("checkScans: scan count matches the number of scanning runs -> PASS", () => {
  const v = verificationForScans({
    hourly_check_runs: [
      hourlyRun({ outcome: "skipped:market_closed" }),
      hourlyRun({ outcome: "success:no_action" }),
    ],
    scans: [scanRow()],
  });
  assertEquals(checkScans(v), { status: "PASS", findings: [] });
});

Deno.test("checkScans: holiday -- 9 skipped:market_closed runs, zero scans -> PASS", () => {
  const v = verificationForScans({
    hourly_check_runs: Array.from(
      { length: 9 },
      () => hourlyRun({ outcome: "skipped:market_closed" }),
    ),
    scans: [],
  });
  assertEquals(checkScans(v), { status: "PASS", findings: [] });
});

Deno.test("checkScans: mismatch between scan count and scanning-run count -> FAIL", () => {
  const v = verificationForScans({
    hourly_check_runs: [hourlyRun({ outcome: "success:no_action" })],
    scans: [],
  });
  assertEquals(checkScans(v).status, "FAIL");
});

Deno.test("checkScans: SHORT decision while shorts_enabled is false -> FAIL", () => {
  const v = verificationForScans({
    hourly_check_runs: [hourlyRun({ outcome: "success" })],
    scans: [scanRow({ decision: "SHORT" })],
    shorts_enabled: false,
  });
  assertEquals(checkScans(v).status, "FAIL");
});

Deno.test("checkScans: LONG decision with a null entry_order_id -> WARN, not FAIL", () => {
  const v = verificationForScans({
    hourly_check_runs: [hourlyRun({ outcome: "success:journal_degraded" })],
    scans: [scanRow({ decision: "LONG", entry_order_id: null })],
  });
  assertEquals(checkScans(v).status, "WARN");
});

Deno.test("checkScans: neutral-only detectors_fired alongside no_detectors_fired skip_reason is never a finding", () => {
  const v = verificationForScans({
    hourly_check_runs: [hourlyRun({ outcome: "success:no_action" })],
    scans: [
      scanRow({
        decision: "SKIP",
        skip_reason: "no_detectors_fired",
        detectors_fired: ["neutral"],
      }),
    ],
  });
  assertEquals(checkScans(v), { status: "PASS", findings: [] });
});

// ---------------------------------------------------------------------------
// checkGeometry (§5.3 check 3)
// ---------------------------------------------------------------------------

Deno.test("checkGeometry: whole-cent stop/target prices -> PASS", () => {
  const scans = [scanRow({ stop_price: 499.5, target_price: 501.25 })];
  assertEquals(checkGeometry(scans), { status: "PASS", findings: [] });
});

Deno.test("checkGeometry: null stop/target prices (no entry attempted) -> PASS", () => {
  assertEquals(checkGeometry([scanRow()]), { status: "PASS", findings: [] });
});

Deno.test("checkGeometry: sub-cent stop_price -> FAIL", () => {
  const scans = [scanRow({ stop_price: 499.505 })];
  assertEquals(checkGeometry(scans).status, "FAIL");
});

Deno.test("checkGeometry: a value within the 1e-6 float-noise tolerance of a whole cent -> PASS", () => {
  // 123.45 * 100 === 12344.999999999998 in IEEE 754 -- must not FAIL on that noise.
  const scans = [scanRow({ stop_price: 123.45 })];
  assertEquals(checkGeometry(scans), { status: "PASS", findings: [] });
});

// ---------------------------------------------------------------------------
// checkJournal (§5.3 check 4)
// ---------------------------------------------------------------------------

Deno.test("checkJournal: every entry trade matched by a scan's entry_order_id -> PASS", () => {
  const scans = [scanRow({ decision: "LONG", entry_order_id: "order-1" })];
  const trades = [tradeRow({ reason: "hourly_long_entry", broker_order_id: "order-1" })];
  assertEquals(checkJournal(trades, scans), { status: "PASS", findings: [] });
});

Deno.test("checkJournal: an entry trade with no matching scan -> FAIL", () => {
  const trades = [tradeRow({ reason: "hourly_long_entry", broker_order_id: "order-1" })];
  const result = checkJournal(trades, []);
  assertEquals(result.status, "FAIL");
  assertEquals(result.findings.length, 1);
});

Deno.test("checkJournal: a non-hourly trade is ignored entirely", () => {
  const trades = [tradeRow({ reason: "panic_cli", broker_order_id: "order-9" })];
  assertEquals(checkJournal(trades, []), { status: "PASS", findings: [] });
});

// ---------------------------------------------------------------------------
// checkState (§5.3 check 6)
// ---------------------------------------------------------------------------

Deno.test("checkState: paused=false, verified matches baseline, no previous row -> PASS", () => {
  const config = {
    paused: "false",
    hourly_experiment_start_equity: "1000000.00",
    hourly_experiment_baseline_verified: "1000000.00",
  };
  assertEquals(checkState(config, null), { status: "PASS", findings: [] });
});

Deno.test("checkState: paused=true -> FAIL", () => {
  const config = {
    paused: "true",
    hourly_experiment_start_equity: "1000000.00",
    hourly_experiment_baseline_verified: "1000000.00",
  };
  assertEquals(checkState(config, null).status, "FAIL");
});

Deno.test("checkState: unset baseline -> WARN (day-zero), not FAIL", () => {
  const config = {
    paused: "false",
    hourly_experiment_start_equity: null,
    hourly_experiment_baseline_verified: null,
  };
  assertEquals(checkState(config, null).status, "WARN");
});

Deno.test("checkState: baseline_verified diverges from the raw baseline -> FAIL", () => {
  const config = {
    paused: "false",
    hourly_experiment_start_equity: "1000000.00",
    hourly_experiment_baseline_verified: "999999.99",
  };
  assertEquals(checkState(config, null).status, "FAIL");
});

Deno.test("checkState: baseline moved since the previous ledger row -> FAIL", () => {
  const config = {
    paused: "false",
    hourly_experiment_start_equity: "1000000.00",
    hourly_experiment_baseline_verified: "1000000.00",
  };
  assertEquals(
    checkState(config, { floor_baseline_raw: "999000.00" }).status,
    "FAIL",
  );
});

Deno.test("checkState: baseline byte-identical to the previous ledger row -> PASS", () => {
  const config = {
    paused: "false",
    hourly_experiment_start_equity: "1000000.00",
    hourly_experiment_baseline_verified: "1000000.00",
  };
  assertEquals(
    checkState(config, { floor_baseline_raw: "1000000.00" }),
    { status: "PASS", findings: [] },
  );
});

// ---------------------------------------------------------------------------
// deriveMissingKillSwitchSlots (#562: name the missing kill-switch slots)
// ---------------------------------------------------------------------------

Deno.test("deriveMissingKillSwitchSlots: a full 108-slot day -> no gaps", () => {
  assertEquals(deriveMissingKillSwitchSlots(fullKillSwitchGrid()), []);
});

Deno.test("deriveMissingKillSwitchSlots: one missing slot", () => {
  const grid = fullKillSwitchGrid().filter((ts) => !ts.includes("T19:05:00"));
  assertEquals(deriveMissingKillSwitchSlots(grid), ["19:05Z"]);
});

Deno.test("deriveMissingKillSwitchSlots: scattered gaps returned ascending", () => {
  const grid = fullKillSwitchGrid().filter(
    (ts) => !ts.includes("T20:15:00") && !ts.includes("T13:00:00"),
  );
  assertEquals(deriveMissingKillSwitchSlots(grid), ["13:00Z", "20:15Z"]);
});

Deno.test("deriveMissingKillSwitchSlots: jittered timestamp maps to its slot via flooring", () => {
  const grid = fullKillSwitchGrid().map((ts) =>
    ts.includes("T19:00:00") ? "2026-08-07T19:00:00.531Z" : ts
  );
  assertEquals(deriveMissingKillSwitchSlots(grid), []);
});

Deno.test("deriveMissingKillSwitchSlots: an out-of-grid timestamp occupies nothing", () => {
  const grid = fullKillSwitchGrid().filter((ts) => !ts.includes("T19:05:00"));
  grid.push("2026-08-07T22:30:00.000Z");
  assertEquals(deriveMissingKillSwitchSlots(grid), ["19:05Z"]);
});

Deno.test("deriveMissingKillSwitchSlots: boundary slots 13:00Z and 21:55Z are recognized", () => {
  const grid = fullKillSwitchGrid().filter(
    (ts) => !ts.includes("T13:00:00") && !ts.includes("T21:55:00"),
  );
  assertEquals(deriveMissingKillSwitchSlots(grid), ["13:00Z", "21:55Z"]);
});

// ---------------------------------------------------------------------------
// formatMissingSlots (#562)
// ---------------------------------------------------------------------------

Deno.test("formatMissingSlots: empty -> empty string", () => {
  assertEquals(formatMissingSlots([]), "");
});

Deno.test("formatMissingSlots: a single slot", () => {
  assertEquals(formatMissingSlots(["19:05Z"]), "19:05Z");
});

Deno.test("formatMissingSlots: two non-adjacent slots", () => {
  assertEquals(formatMissingSlots(["19:05Z", "20:15Z"]), "19:05Z, 20:15Z");
});

Deno.test("formatMissingSlots: a consecutive run collapses into a range", () => {
  assertEquals(
    formatMissingSlots(["19:05Z", "19:10Z", "19:15Z", "19:20Z"]),
    "19:05Z-19:20Z",
  );
});

Deno.test("formatMissingSlots: a mix of a singleton and a range", () => {
  assertEquals(
    formatMissingSlots([
      "19:05Z",
      "20:15Z",
      "20:20Z",
      "20:25Z",
      "20:30Z",
      "20:35Z",
      "20:40Z",
      "20:45Z",
      "20:50Z",
      "20:55Z",
      "21:00Z",
    ]),
    "19:05Z, 20:15Z-21:00Z",
  );
});

Deno.test("formatMissingSlots: a full dead day collapses to one range", () => {
  const allLabels = fullKillSwitchGrid().map((ts) => ts.slice(11, 16) + "Z");
  assertEquals(formatMissingSlots(allLabels), "13:00Z-21:55Z");
});

// ---------------------------------------------------------------------------
// checkKillSwitch (§5.3 check 7)
// ---------------------------------------------------------------------------

Deno.test("checkKillSwitch: 108 runs, all success:no_position, no LONG scans -> PASS", () => {
  const result = checkKillSwitch(
    { count: 108, outcome_counts: { "success:no_position": 108 } },
    [],
  );
  assertEquals(result, { status: "PASS", findings: [] });
});

Deno.test("checkKillSwitch: count !== 108 -> FAIL", () => {
  const result = checkKillSwitch(
    { count: 107, outcome_counts: { "success:no_position": 107 } },
    [],
  );
  assertEquals(result.status, "FAIL");
});

Deno.test("checkKillSwitch: an outcome not starting success:/skipped: -> FAIL", () => {
  const result = checkKillSwitch(
    { count: 108, outcome_counts: { "success:no_position": 107, "error:AlpacaError": 1 } },
    [],
  );
  assertEquals(result.status, "FAIL");
});

Deno.test("checkKillSwitch: uniform success:no_position alongside a LONG scan -> FAIL (contradiction)", () => {
  const result = checkKillSwitch(
    { count: 108, outcome_counts: { "success:no_position": 108 } },
    [scanRow({ decision: "LONG" })],
  );
  assertEquals(result.status, "FAIL");
});

Deno.test("checkKillSwitch: non-uniform outcome_counts alongside a LONG scan is not the contradiction -> PASS", () => {
  const result = checkKillSwitch(
    { count: 108, outcome_counts: { "success:no_position": 100, "success:in_position": 8 } },
    [scanRow({ decision: "LONG" })],
  );
  assertEquals(result, { status: "PASS", findings: [] });
});

// #562: naming the missing slots in the count-mismatch finding.

Deno.test("checkKillSwitch: 107 runs with started_at -> finding names the missing slot", () => {
  const startedAt = fullKillSwitchGrid().filter((ts) => !ts.includes("T19:05:00"));
  const result = checkKillSwitch(
    { count: 107, outcome_counts: { "success:no_position": 107 }, started_at: startedAt },
    [],
  );
  assertEquals(result.status, "FAIL");
  assertEquals(result.findings, [
    "kill_switch: expected 108 runs, found 107 (missing: 19:05Z)",
  ]);
});

Deno.test("checkKillSwitch: multiple missing slots with started_at -> finding names all of them", () => {
  const startedAt = fullKillSwitchGrid().filter(
    (ts) => !ts.includes("T19:05:00") && !ts.includes("T20:15:00"),
  );
  const result = checkKillSwitch(
    { count: 106, outcome_counts: { "success:no_position": 106 }, started_at: startedAt },
    [],
  );
  assertEquals(result.findings, [
    "kill_switch: expected 108 runs, found 106 (missing: 19:05Z, 20:15Z)",
  ]);
});

Deno.test("checkKillSwitch: 108 runs with a full started_at grid -> PASS, exactly as today", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 108 },
      started_at: fullKillSwitchGrid(),
    },
    [],
  );
  assertEquals(result, { status: "PASS", findings: [] });
});

Deno.test("checkKillSwitch: count mismatch, started_at absent -> today's plain finding, unchanged", () => {
  const result = checkKillSwitch(
    { count: 107, outcome_counts: { "success:no_position": 107 } },
    [],
  );
  assertEquals(result.findings, ["kill_switch: expected 108 runs, found 107"]);
});

Deno.test("checkKillSwitch: 109 runs (a duplicated slot) with started_at but no grid slot missing -> today's plain finding", () => {
  const startedAt = [...fullKillSwitchGrid(), "2026-08-07T19:05:00.900Z"];
  const result = checkKillSwitch(
    { count: 109, outcome_counts: { "success:no_position": 109 }, started_at: startedAt },
    [],
  );
  assertEquals(result.findings, ["kill_switch: expected 108 runs, found 109"]);
});

// ---------------------------------------------------------------------------
// evaluateVerification -- composes the seven checks + metrics (§5.3/§6.1).
// ---------------------------------------------------------------------------

function cleanDayVerification(): VerificationBlock {
  return {
    date: "2026-08-05",
    window: { since: "2026-08-05T00:00:00.000Z", until: "2026-08-05T23:59:59.999Z" },
    shorts_enabled: false,
    hourly_check_runs: Array.from({ length: 9 }, (_, i) =>
      hourlyRun({
        started_at: `2026-08-05T${13 + i}:07:00.000Z`,
        finished_at: `2026-08-05T${13 + i}:07:01.500Z`,
        outcome: "success:no_action",
      })),
    kill_switch_runs: { count: 108, outcome_counts: { "success:no_position": 108 } },
    scans: Array.from(
      { length: 9 },
      (_, i) => scanRow({ bar_ts: `2026-08-05T${13 + i}:00:00.000Z` }),
    ),
    trades: [],
    config: {
      paused: "false",
      hourly_experiment_start_equity: "1000000.00",
      hourly_experiment_baseline_verified: "1000000.00",
    },
  };
}

Deno.test("evaluateVerification: a clean day -> PASS with every check PASS", () => {
  const result = evaluateVerification(cleanDayVerification(), null);
  assertEquals(result.verdict, "PASS");
  assertEquals(result.checks, {
    slots: "PASS",
    latency: "PASS",
    scans: "PASS",
    geometry: "PASS",
    journal: "PASS",
    state: "PASS",
    kill_switch: "PASS",
  });
  assertEquals(result.findings, []);
});

Deno.test("evaluateVerification: a holiday (9x skipped:market_closed, zero scans) -> PASS", () => {
  const v = cleanDayVerification();
  v.hourly_check_runs = v.hourly_check_runs.map((r) => ({
    ...r,
    outcome: "skipped:market_closed",
  }));
  v.scans = [];
  const result = evaluateVerification(v, null);
  assertEquals(result.verdict, "PASS");
  assertEquals(result.metrics.scan_rows, 0);
});

Deno.test("evaluateVerification: metrics.hourly_runs and metrics.scan_rows count the clean day correctly", () => {
  const result = evaluateVerification(cleanDayVerification(), null);
  assertEquals(result.metrics.hourly_runs, 9);
  assertEquals(result.metrics.scan_rows, 9);
  assertEquals(result.metrics.kill_switch_runs, 108);
  assertEquals(result.metrics.decision_counts, { LONG: 0, SHORT: 0, SKIP: 9 });
});

Deno.test("evaluateVerification: metrics.latency_ms.max/median over finished runs", () => {
  const result = evaluateVerification(cleanDayVerification(), null);
  // Every clean-day run takes 1500ms.
  assertEquals(result.metrics.latency_ms, { max: 1500, median: 1500 });
});

Deno.test("evaluateVerification: metrics.evaluated_bars excludes partial_bar/stale_data skips", () => {
  const v = cleanDayVerification();
  v.scans = [
    scanRow({ bar_ts: "2026-08-05T13:00:00.000Z", skip_reason: "partial_bar" }),
    scanRow({ bar_ts: "2026-08-05T14:00:00.000Z", skip_reason: "no_detectors_fired" }),
  ];
  const result = evaluateVerification(v, null);
  assertEquals(result.metrics.scan_rows, 2);
  assertEquals(result.metrics.evaluated_bars, 1);
});

Deno.test("evaluateVerification: metrics.equity_usd is the latest (by bar_ts) scan's equity, or null with no scans", () => {
  const v = cleanDayVerification();
  v.scans = [
    scanRow({ bar_ts: "2026-08-05T13:00:00.000Z", equity_usd: 1_000_000 }),
    scanRow({ bar_ts: "2026-08-05T14:00:00.000Z", equity_usd: 1_010_000 }),
  ];
  assertEquals(evaluateVerification(v, null).metrics.equity_usd, 1_010_000);

  v.scans = [];
  assertEquals(evaluateVerification(v, null).metrics.equity_usd, null);
});

Deno.test("evaluateVerification: metrics.floor_price_usd and headroom_pct match the published formula", () => {
  const v = cleanDayVerification();
  v.config.hourly_experiment_start_equity = "1017330.61";
  v.config.hourly_experiment_baseline_verified = "1017330.61";
  v.scans = [scanRow({ bar_ts: "2026-08-05T13:00:00.000Z", equity_usd: 1017330.61 })];
  const result = evaluateVerification(v, null);
  assertEquals(result.metrics.floor_price_usd, 1017330.61 * 0.85);
  assertEquals(Math.round((result.metrics.headroom_pct ?? 0) * 10) / 10, 15.0);
});

Deno.test("evaluateVerification: metrics.entries/fills/closed_trades/r_multiples come from pairHourlyTrades", () => {
  const v = cleanDayVerification();
  v.scans = [
    scanRow({
      bar_ts: "2026-08-05T13:00:00.000Z",
      decision: "LONG",
      entry_order_id: "order-1",
      risk_per_share: 1,
    }),
  ];
  v.trades = [
    tradeRow({
      reason: "hourly_long_entry",
      broker_order_id: "order-1",
      fill_price: 500,
      fill_time: "2026-08-05T14:07:00.000Z",
    }),
    tradeRow({
      reason: "hourly_bracket_exit",
      broker_order_id: "order-2",
      fill_price: 502,
      fill_time: "2026-08-05T15:07:00.000Z",
    }),
  ];
  const result = evaluateVerification(v, null);
  assertEquals(result.metrics.entries, 1);
  assertEquals(result.metrics.fills, 2);
  assertEquals(result.metrics.closed_trades, 1);
  assertEquals(result.metrics.r_multiples, [2]);
});

// ---------------------------------------------------------------------------
// buildLedgerRow / upsertLedgerJsonl / selectPreviousRow (§5.5/§6.1, D6)
// ---------------------------------------------------------------------------

Deno.test("buildLedgerRow: carries date/verdict/checks/metrics/findings straight from the evaluation", () => {
  const evaluation = evaluateVerification(cleanDayVerification(), null);
  const row = buildLedgerRow("2026-08-05", evaluation);
  assertEquals(row.date, "2026-08-05");
  assertEquals(row.verdict, "PASS");
  assertEquals(row.checks, evaluation.checks);
  assertEquals(row.findings, evaluation.findings);
});

function ledgerRow(date: string, overrides: Partial<LedgerRow> = {}): LedgerRow {
  const evaluation = evaluateVerification(cleanDayVerification(), null);
  return { ...buildLedgerRow(date, evaluation), ...overrides };
}

Deno.test("upsertLedgerJsonl: inserts into an empty ledger", () => {
  const row = ledgerRow("2026-08-05");
  const text = upsertLedgerJsonl("", row);
  assertEquals(text, JSON.stringify(row) + "\n");
});

Deno.test("upsertLedgerJsonl: replaces an existing row for the same date rather than duplicating it", () => {
  const first = ledgerRow("2026-08-05", { verdict: "PASS" });
  const replaced = ledgerRow("2026-08-05", { verdict: "FAIL" });
  const afterFirst = upsertLedgerJsonl("", first);
  const afterReplace = upsertLedgerJsonl(afterFirst, replaced);
  const lines = afterReplace.trim().split("\n");
  assertEquals(lines.length, 1);
  assertEquals(JSON.parse(lines[0]).verdict, "FAIL");
});

Deno.test("upsertLedgerJsonl: keeps rows in ascending date order regardless of insertion order", () => {
  const day1 = ledgerRow("2026-08-03");
  const day3 = ledgerRow("2026-08-05");
  const day2 = ledgerRow("2026-08-04");
  let text = upsertLedgerJsonl("", day3);
  text = upsertLedgerJsonl(text, day1);
  text = upsertLedgerJsonl(text, day2);
  const dates = text.trim().split("\n").map((l: string) => JSON.parse(l).date);
  assertEquals(dates, ["2026-08-03", "2026-08-04", "2026-08-05"]);
});

Deno.test("upsertLedgerJsonl: re-running the same date with the same row is byte-identical (idempotent)", () => {
  const row = ledgerRow("2026-08-05");
  const once = upsertLedgerJsonl("", row);
  const twice = upsertLedgerJsonl(once, row);
  assertEquals(twice, once);
});

Deno.test("selectPreviousRow: the newest row strictly before the target date", () => {
  const rows = [ledgerRow("2026-08-03"), ledgerRow("2026-08-04"), ledgerRow("2026-08-05")];
  assertEquals(selectPreviousRow(rows, "2026-08-05")?.date, "2026-08-04");
});

Deno.test("selectPreviousRow: skips a gap day correctly (no row exactly one day back)", () => {
  const rows = [ledgerRow("2026-08-01"), ledgerRow("2026-08-05")];
  assertEquals(selectPreviousRow(rows, "2026-08-06")?.date, "2026-08-05");
});

Deno.test("selectPreviousRow: a backfilled out-of-order write is still found by date, not insertion order", () => {
  const rows = [ledgerRow("2026-08-05"), ledgerRow("2026-08-01")];
  assertEquals(selectPreviousRow(rows, "2026-08-05")?.date, "2026-08-01");
});

Deno.test("selectPreviousRow: no row strictly before the target -> null (day zero)", () => {
  const rows = [ledgerRow("2026-08-05")];
  assertEquals(selectPreviousRow(rows, "2026-08-05"), null);
  assertEquals(selectPreviousRow([], "2026-08-05"), null);
});

// ---------------------------------------------------------------------------
// renderMarkdownDigest (§6.2, D6 determinism)
// ---------------------------------------------------------------------------

Deno.test("renderMarkdownDigest: two renders of the same evaluation are byte-identical", () => {
  const evaluation = evaluateVerification(cleanDayVerification(), null);
  const first = renderMarkdownDigest("2026-08-05", evaluation, null);
  const second = renderMarkdownDigest("2026-08-05", evaluation, null);
  assertEquals(first, second);
});

Deno.test("renderMarkdownDigest: mentions the verdict, the date, and every one of the seven checks", () => {
  const evaluation = evaluateVerification(cleanDayVerification(), null);
  const md = renderMarkdownDigest("2026-08-05", evaluation, null);
  assertEquals(md.includes("PASS"), true);
  assertEquals(md.includes("2026-08-05"), true);
  for (
    const title of [
      "Slots",
      "Scans",
      "Geometry",
      "Journal",
      "Latency",
      "State",
      "Kill-switch",
    ]
  ) {
    assertEquals(md.includes(title), true, title);
  }
});

Deno.test("renderMarkdownDigest: lists every finding on a FAIL day", () => {
  const v = cleanDayVerification();
  v.config.paused = "true";
  const evaluation = evaluateVerification(v, null);
  const md = renderMarkdownDigest("2026-08-05", evaluation, null);
  for (const finding of evaluation.findings) {
    assertEquals(md.includes(finding), true);
  }
});

Deno.test("renderMarkdownDigest: never contains a generated-at timestamp or run URL (D6)", () => {
  const evaluation = evaluateVerification(cleanDayVerification(), null);
  const md = renderMarkdownDigest("2026-08-05", evaluation, null);
  assertEquals(md.includes("generated"), false);
  assertEquals(md.includes("http://") || md.includes("https://"), false);
});

// #562: a full 108-entry started_at grid alongside cleanDayVerification's
// existing count: 108 -- the digest/ledger render is byte-identical to
// before this change (acceptance criterion: "a full 108-run day behaves
// exactly as today").
Deno.test("renderMarkdownDigest: a clean day with a full started_at grid renders identically to one without it", () => {
  const withoutTimestamps = evaluateVerification(cleanDayVerification(), null);
  const withTimestamps = evaluateVerification(
    {
      ...cleanDayVerification(),
      kill_switch_runs: {
        count: 108,
        outcome_counts: { "success:no_position": 108 },
        started_at: fullKillSwitchGrid("2026-08-05"),
      },
    },
    null,
  );
  assertEquals(
    renderMarkdownDigest("2026-08-05", withTimestamps, null),
    renderMarkdownDigest("2026-08-05", withoutTimestamps, null),
  );
});

// ---------------------------------------------------------------------------
// Fixture-driven case matrix (§9), one file per case class under
// scripts/testdata/. Each fixture is a verification-block-shaped object built
// by hand against §4.3 (never against Package A's branch, per §10's file
// ownership split).
// ---------------------------------------------------------------------------

function loadFixture(name: string): VerificationBlock {
  const text = Deno.readTextFileSync(
    new URL(`./testdata/daily-verify-${name}.json`, import.meta.url),
  );
  return JSON.parse(text) as VerificationBlock;
}

Deno.test("fixture clean-day: PASS", () => {
  const result = evaluateVerification(loadFixture("clean-day"), null);
  assertEquals(result.verdict, "PASS");
});

Deno.test("fixture holiday: nine gate-exits, zero scans, still PASS (no calendar needed)", () => {
  const v = loadFixture("holiday");
  const result = evaluateVerification(v, null);
  assertEquals(result.verdict, "PASS");
  assertEquals(v.scans.length, 0);
  assertEquals(v.hourly_check_runs.length, HOURLY_SLOTS_PER_WEEKDAY);
});

Deno.test("fixture missing-slot: FAIL via the slots check", () => {
  const result = evaluateVerification(loadFixture("missing-slot"), null);
  assertEquals(result.verdict, "FAIL");
  assertEquals(result.checks.slots, "FAIL");
});

Deno.test("fixture unfinished-row: FAIL via the slots check (finished_at: null)", () => {
  const result = evaluateVerification(loadFixture("unfinished-row"), null);
  assertEquals(result.verdict, "FAIL");
  assertEquals(result.checks.slots, "FAIL");
});

Deno.test("fixture error-outcome: FAIL via the slots check regardless of the scans check", () => {
  const result = evaluateVerification(loadFixture("error-outcome"), null);
  assertEquals(result.verdict, "FAIL");
  assertEquals(result.checks.slots, "FAIL");
});

Deno.test("fixture latency-warn: WARN via the latency check, not FAIL", () => {
  const result = evaluateVerification(loadFixture("latency-warn"), null);
  assertEquals(result.checks.latency, "WARN");
  assertEquals(result.verdict, "WARN");
});

Deno.test("fixture latency-fail: FAIL via the latency check", () => {
  const result = evaluateVerification(loadFixture("latency-fail"), null);
  assertEquals(result.checks.latency, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

Deno.test("fixture sub-cent-geometry: FAIL via the geometry check", () => {
  const result = evaluateVerification(loadFixture("sub-cent-geometry"), null);
  assertEquals(result.checks.geometry, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

Deno.test("fixture unmatched-fill: FAIL via the journal check", () => {
  const result = evaluateVerification(loadFixture("unmatched-fill"), null);
  assertEquals(result.checks.journal, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

Deno.test("fixture paused-true: FAIL via the state check", () => {
  const result = evaluateVerification(loadFixture("paused-true"), null);
  assertEquals(result.checks.state, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

Deno.test("fixture baseline-moved: FAIL via the state check, against a previous ledger row with a different baseline", () => {
  const result = evaluateVerification(loadFixture("baseline-moved"), {
    floor_baseline_raw: "999000.00",
  });
  assertEquals(result.checks.state, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

Deno.test("fixture baseline-unset: WARN via the state check (day-zero), not FAIL", () => {
  const result = evaluateVerification(loadFixture("baseline-unset"), null);
  assertEquals(result.checks.state, "WARN");
  assertEquals(result.verdict, "WARN");
});

Deno.test("fixture short-while-disabled: FAIL via the scans check", () => {
  const result = evaluateVerification(loadFixture("short-while-disabled"), null);
  assertEquals(result.checks.scans, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

Deno.test("fixture pending-long: WARN via the scans check, not FAIL", () => {
  const result = evaluateVerification(loadFixture("pending-long"), null);
  assertEquals(result.checks.scans, "WARN");
  assertEquals(result.verdict, "WARN");
});

Deno.test("fixture no-position-contradiction: FAIL via the kill_switch check", () => {
  const result = evaluateVerification(loadFixture("no-position-contradiction"), null);
  assertEquals(result.checks.kill_switch, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

// #562: reproduces the 2026-08-07 incident (#559) -- 107 kill-switch runs,
// missing the 19:05 UTC slot. The finding, ledger row, and rendered digest
// all carry the enriched string.
Deno.test("fixture kill-switch-missing-slot: FAIL via the kill_switch check, finding names the missing 19:05Z slot", () => {
  const v = loadFixture("kill-switch-missing-slot");
  const result = evaluateVerification(v, null);
  assertEquals(result.checks.kill_switch, "FAIL");
  assertEquals(result.verdict, "FAIL");
  assertEquals(
    result.findings.includes("kill_switch: expected 108 runs, found 107 (missing: 19:05Z)"),
    true,
  );

  const ledgerRow = buildLedgerRow(v.date, result);
  assertEquals(
    ledgerRow.findings.includes("kill_switch: expected 108 runs, found 107 (missing: 19:05Z)"),
    true,
  );

  const digest = renderMarkdownDigest(v.date, result, null);
  assertEquals(digest.includes("kill_switch: expected 108 runs, found 107 (missing: 19:05Z)"), true);
});

// Disclosed residual (§5.3/NON_SCANNING_OUTCOMES's own comment): the
// completed.length === 0 branch returns via done() before any journal call
// and can surface as skipped:stale_data without a matching scan row. It is
// deliberately NOT folded into NON_SCANNING_OUTCOMES either way, so this
// fixture pins that it surfaces as an ordinary scans-check FAIL (a visible,
// investigable mismatch) rather than crashing or being silently swallowed.
Deno.test("fixture zero-completed-bars-residual: surfaces as a scans-check FAIL, not a crash or a silent pass", () => {
  const result = evaluateVerification(loadFixture("zero-completed-bars-residual"), null);
  assertEquals(result.checks.scans, "FAIL");
  assertEquals(result.verdict, "FAIL");
});

// ---------------------------------------------------------------------------
// buildSummary (§5.5 stdout envelope's `summary` field)
// ---------------------------------------------------------------------------

Deno.test("buildSummary: matches §5.5's worked example format", () => {
  const evaluation = evaluateVerification(loadFixture("clean-day"), null);
  const summary = buildSummary(evaluation.metrics);
  assertEquals(summary, "9/9 slots, 9 scans, 0 entries, 108/108 kill-switch, headroom 15.0%");
});

Deno.test("buildSummary: headroom n/a when there is no baseline to compute it from", () => {
  const evaluation = evaluateVerification(loadFixture("baseline-unset"), null);
  const summary = buildSummary(evaluation.metrics);
  assertEquals(summary.includes("headroom n/a"), true);
});

// ---------------------------------------------------------------------------
// parseVerificationBlock (§5.1: malformed input -> exit 1)
// ---------------------------------------------------------------------------

Deno.test("parseVerificationBlock: a well-formed block round-trips unchanged", () => {
  const raw = loadFixture("clean-day");
  assertEquals(parseVerificationBlock(raw), raw);
});

Deno.test("parseVerificationBlock: null -> throws MalformedVerificationError", () => {
  assertThrows(() => parseVerificationBlock(null), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: missing hourly_check_runs -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  delete (raw as { hourly_check_runs?: unknown }).hourly_check_runs;
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: an unparseable started_at timestamp -> throws", () => {
  const raw = loadFixture("clean-day");
  raw.hourly_check_runs[0].started_at = "not-a-timestamp";
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: an unparseable finished_at timestamp -> throws", () => {
  const raw = loadFixture("clean-day");
  raw.hourly_check_runs[0].finished_at = "not-a-timestamp";
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: missing config -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  delete (raw as { config?: unknown }).config;
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

// #562: kill_switch_runs.started_at is optional -- absent is valid (backward
// compat with an older deployed `status`); when present it must be an array
// of parsable timestamps.

Deno.test("parseVerificationBlock: kill_switch_runs.started_at absent -> parses fine (old digest)", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  const killSwitchRuns = raw.kill_switch_runs as Record<string, unknown>;
  assertEquals("started_at" in killSwitchRuns, false);
  const parsed = parseVerificationBlock(raw);
  assertEquals(parsed.kill_switch_runs.started_at, undefined);
});

Deno.test("parseVerificationBlock: kill_switch_runs.started_at present and valid -> parses through", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).started_at = [
    "2026-08-05T13:00:00.000Z",
    "2026-08-05T13:05:00.000Z",
  ];
  const parsed = parseVerificationBlock(raw);
  assertEquals(parsed.kill_switch_runs.started_at, [
    "2026-08-05T13:00:00.000Z",
    "2026-08-05T13:05:00.000Z",
  ]);
});

Deno.test("parseVerificationBlock: kill_switch_runs.started_at not an array -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).started_at = "not-an-array";
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: kill_switch_runs.started_at with an unparseable entry -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).started_at = ["not-a-timestamp"];
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});
