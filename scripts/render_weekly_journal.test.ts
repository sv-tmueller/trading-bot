// Unit tests for the weekly-review aggregator (#481, batch #478 Package C).
// Every dep is a plain injected mock -- no network, no real Supabase client
// construction, no filesystem writes outside deps.writeFile mocks.
// CLAUDE_AGENT_NO_BROKER is set by the `test` deno.json task; this script
// never imports _shared/alpaca.ts, so the guard is inert here (defense in
// depth only, per the repo's Architectural invariants).
import { assertEquals, assertThrows } from "@std/assert";
import type { AuditLogRow, HourlyScanRow, TradeRow } from "../supabase/functions/_shared/db.ts";
import {
  type ClosedTradeResult,
  computeCumulativeStats,
  computeWeeklyAggregates,
  type CumulativeStats,
  DEFAULT_PROPOSAL_CANDIDATES,
  pairHourlyTrades,
  parseArgs,
  parseWeekLabel,
  previousCompletedWeek,
  PROPOSAL_MIN_CLOSED_TRADES,
  proposeParamChange,
  weekWindowUtc,
} from "./render_weekly_journal.ts";

// ---------------------------------------------------------------------------
// T3 fixtures
// ---------------------------------------------------------------------------

function trade(over: Partial<TradeRow>): TradeRow {
  return {
    symbol: "SPY",
    side: "BUY",
    qty: 10,
    fill_price: 550,
    fill_time: "2026-07-27T14:05:00Z",
    reason: "hourly_long_entry",
    broker_order_id: "o1",
    ...over,
  };
}

function scan(over: Partial<HourlyScanRow>): HourlyScanRow {
  return {
    symbol: "SPY",
    bar_ts: "2026-07-27T14:00:00Z",
    decision: "LONG",
    skip_reason: null,
    detectors_fired: ["bullish_marubozu"],
    context_mode: "none",
    entry_ref_price: 550,
    stop_price: 547.75,
    target_price: 554.5,
    risk_per_share: 2.25,
    equity_usd: 100000,
    qty: 10,
    entry_order_id: "o1",
    ...over,
  };
}

// ---------------------------------------------------------------------------
// T1 -- week-window math
// ---------------------------------------------------------------------------

Deno.test("parseWeekLabel: a well-formed label round-trips", () => {
  assertEquals(parseWeekLabel("2026-W31"), { isoYear: 2026, isoWeek: 31 });
});

Deno.test("parseWeekLabel: rejects a malformed label", () => {
  assertThrows(() => parseWeekLabel("2026-31"), Error, "week label");
  assertThrows(() => parseWeekLabel("2026-W5"), Error, "week label");
  assertThrows(() => parseWeekLabel("bogus"), Error, "week label");
});

Deno.test("parseWeekLabel: rejects a week number out of range", () => {
  assertThrows(() => parseWeekLabel("2026-W00"), Error, "week label");
  assertThrows(() => parseWeekLabel("2026-W54"), Error, "week label");
});

Deno.test("weekWindowUtc: a known mid-year EDT week", () => {
  // 2026-W31: Mon 27 Jul -- Fri 31 Jul 2026, matching docs/trading-journal/2026-W31.md's
  // own title. EDT (UTC-4): Monday 00:00 ET == 04:00 UTC.
  const win = weekWindowUtc(2026, 31);
  assertEquals(win.startIso, "2026-07-27T04:00:00.000Z");
  // Saturday 00:00 ET == 04:00 UTC.
  assertEquals(win.endIsoExclusive, "2026-08-01T04:00:00.000Z");
  assertEquals(win.title, "Week 2026-W31 (Mon 27 Jul -- Fri 31 Jul 2026)");
});

Deno.test("weekWindowUtc: an EST week (winter, UTC-5)", () => {
  // 2026-W03: Mon 12 Jan -- Fri 16 Jan 2026. EST: Monday 00:00 ET == 05:00 UTC.
  const win = weekWindowUtc(2026, 3);
  assertEquals(win.startIso, "2026-01-12T05:00:00.000Z");
  assertEquals(win.endIsoExclusive, "2026-01-17T05:00:00.000Z");
});

Deno.test("weekWindowUtc: ISO-year boundary -- 2026-W01's Monday falls in Dec 2025", () => {
  const win = weekWindowUtc(2026, 1);
  // Monday 29 Dec 2025, EST (UTC-5).
  assertEquals(win.startIso, "2025-12-29T05:00:00.000Z");
  assertEquals(win.title, "Week 2026-W01 (Mon 29 Dec -- Fri 2 Jan 2026)");
});

Deno.test("weekWindowUtc: the DST spring-forward boundary week stays EST throughout", () => {
  // 2026-03-08 (Sun) is the US spring-forward transition. The week *before*
  // it (2026-W10: Mon 2 Mar -- Fri 6 Mar) is entirely EST -- the Mon-Sat
  // window never straddles the Sunday 02:00 transition instant itself.
  const win = weekWindowUtc(2026, 10);
  assertEquals(win.startIso, "2026-03-02T05:00:00.000Z");
  assertEquals(win.endIsoExclusive, "2026-03-07T05:00:00.000Z");
});

Deno.test("weekWindowUtc: the week after spring-forward is EDT throughout", () => {
  // 2026-W11: Mon 9 Mar -- Fri 13 Mar, entirely after the transition.
  const win = weekWindowUtc(2026, 11);
  assertEquals(win.startIso, "2026-03-09T04:00:00.000Z");
  assertEquals(win.endIsoExclusive, "2026-03-14T04:00:00.000Z");
});

Deno.test("previousCompletedWeek: resolves to the ISO week 7 days before `now`", () => {
  // now = Tue 28 Jul 2026 (in 2026-W31) -> previous completed week is 2026-W30.
  const result = previousCompletedWeek(new Date("2026-07-28T15:00:00Z"));
  assertEquals(result, { isoYear: 2026, isoWeek: 30 });
});

Deno.test("previousCompletedWeek: crosses an ISO-year boundary correctly", () => {
  // now = Wed 7 Jan 2026 (2026-W02) -> previous completed week is 2026-W01
  // (Mon 29 Dec 2025 -- Fri 2 Jan 2026).
  const result = previousCompletedWeek(new Date("2026-01-07T12:00:00Z"));
  assertEquals(result, { isoYear: 2026, isoWeek: 1 });
});

// ---------------------------------------------------------------------------
// T2 -- arg parsing
// ---------------------------------------------------------------------------

Deno.test("parseArgs: defaults (no flags) -> render mode, no week/out, no force", () => {
  const parsed = parseArgs([]);
  assertEquals(parsed, {
    mode: "render",
    help: false,
    week: undefined,
    out: undefined,
    force: false,
  });
});

Deno.test("parseArgs: --week is accepted in render mode", () => {
  const parsed = parseArgs(["--week", "2026-W30"]);
  assertEquals(parsed.mode, "render");
  assertEquals((parsed as { week?: string }).week, "2026-W30");
});

Deno.test("parseArgs: --out and --force are accepted in render mode", () => {
  const parsed = parseArgs(["--out", "/tmp/x.md", "--force"]);
  assertEquals((parsed as { out?: string }).out, "/tmp/x.md");
  assertEquals((parsed as { force: boolean }).force, true);
});

Deno.test("parseArgs: -h / --help sets help in either mode", () => {
  assertEquals(parseArgs(["-h"]).help, true);
  assertEquals(parseArgs(["--help"]).help, true);
  assertEquals(parseArgs(["--record-accepted-bump", "--ref", "#481", "-h"]).help, true);
});

Deno.test("parseArgs: --record-accepted-bump with --ref -> bump mode", () => {
  const parsed = parseArgs(["--record-accepted-bump", "--ref", "docs/decisions/2026-08-01-bump.md"]);
  assertEquals(parsed.mode, "bump");
  assertEquals((parsed as { ref: string }).ref, "docs/decisions/2026-08-01-bump.md");
});

Deno.test("parseArgs: --record-accepted-bump without --ref throws", () => {
  assertThrows(() => parseArgs(["--record-accepted-bump"]), Error, "--ref");
});

Deno.test("parseArgs: --ref without --record-accepted-bump throws", () => {
  assertThrows(() => parseArgs(["--ref", "#481"]), Error, "--record-accepted-bump");
});

Deno.test("parseArgs: --record-accepted-bump combined with a render flag throws (mutually exclusive)", () => {
  assertThrows(
    () => parseArgs(["--record-accepted-bump", "--ref", "#481", "--week", "2026-W30"]),
    Error,
    "mutually exclusive",
  );
  assertThrows(
    () => parseArgs(["--record-accepted-bump", "--ref", "#481", "--force"]),
    Error,
    "mutually exclusive",
  );
});

Deno.test("parseArgs: unknown argument throws an UnknownArgError", () => {
  assertThrows(() => parseArgs(["--bogus"]), Error, "unknown argument");
});

Deno.test("parseArgs: --week with no value throws", () => {
  assertThrows(() => parseArgs(["--week"]), Error, "--week");
});

// ---------------------------------------------------------------------------
// T3 -- pairHourlyTrades / R-multiples
// ---------------------------------------------------------------------------

Deno.test("pairHourlyTrades: a winning LONG pairs entry->exit with a positive R", () => {
  const entry = trade({
    reason: "hourly_long_entry",
    side: "BUY",
    fill_price: 550,
    fill_time: "2026-07-27T14:05:00Z",
    broker_order_id: "o1",
  });
  const exit = trade({
    reason: "hourly_bracket_exit",
    side: "SELL",
    fill_price: 554.5,
    fill_time: "2026-07-27T16:05:00Z",
    broker_order_id: "o2",
  });
  const s = scan({ entry_order_id: "o1", risk_per_share: 2.25 });
  const result = pairHourlyTrades([entry, exit], [s]);
  assertEquals(result.closedTrades.length, 1);
  const [ct] = result.closedTrades;
  assertEquals(ct.side, "LONG");
  assertEquals(ct.rMultiple, 2); // (554.5 - 550) / 2.25 == 2
  assertEquals(ct.rMultipleNaReason, undefined);
  assertEquals(result.openEntries.length, 0);
  assertEquals(result.orphanExits.length, 0);
  assertEquals(result.manualInterventions.length, 0);
});

Deno.test("pairHourlyTrades: a losing SHORT flips the sign correctly", () => {
  const entry = trade({
    reason: "hourly_short_entry",
    side: "SELL",
    fill_price: 550,
    fill_time: "2026-07-27T14:05:00Z",
    broker_order_id: "o1",
  });
  const exit = trade({
    reason: "hourly_bracket_exit",
    side: "BUY",
    fill_price: 552.25, // moved against the short by one stop-distance
    fill_time: "2026-07-27T15:05:00Z",
    broker_order_id: "o2",
  });
  const s = scan({ entry_order_id: "o1", risk_per_share: 2.25, decision: "SHORT" });
  const result = pairHourlyTrades([entry, exit], [s]);
  const [ct] = result.closedTrades;
  assertEquals(ct.side, "SHORT");
  // R = -1 * (552.25 - 550) / 2.25 == -1
  assertEquals(ct.rMultiple, -1);
});

Deno.test("pairHourlyTrades: an unpaired entry (still open at week end) is reported separately", () => {
  const entry = trade({ reason: "hourly_long_entry", broker_order_id: "o1" });
  const result = pairHourlyTrades([entry], [scan({ entry_order_id: "o1" })]);
  assertEquals(result.closedTrades.length, 0);
  assertEquals(result.openEntries.length, 1);
  assertEquals(result.openEntries[0].broker_order_id, "o1");
});

Deno.test("pairHourlyTrades: an orphan exit (no matching queued entry) is reported separately", () => {
  const exit = trade({ reason: "hourly_bracket_exit", broker_order_id: "o2" });
  const result = pairHourlyTrades([exit], []);
  assertEquals(result.closedTrades.length, 0);
  assertEquals(result.orphanExits.length, 1);
  assertEquals(result.orphanExits[0].broker_order_id, "o2");
});

Deno.test("pairHourlyTrades: a missing scan row degrades R to n/a with a stated reason", () => {
  const entry = trade({ reason: "hourly_long_entry", broker_order_id: "o1", fill_price: 550 });
  const exit = trade({
    reason: "hourly_bracket_exit",
    broker_order_id: "o2",
    fill_price: 554.5,
    fill_time: "2026-07-27T16:05:00Z",
  });
  // No scan row at all -- entry_order_id "o1" is never found.
  const result = pairHourlyTrades([entry, exit], []);
  const [ct] = result.closedTrades;
  assertEquals(ct.rMultiple, null);
  assertEquals(ct.rMultipleNaReason, "missing scan row for entry o1");
});

Deno.test("pairHourlyTrades: a zero/absent risk_per_share degrades R to n/a with a stated reason", () => {
  const entry = trade({ reason: "hourly_long_entry", broker_order_id: "o1", fill_price: 550 });
  const exit = trade({
    reason: "hourly_bracket_exit",
    broker_order_id: "o2",
    fill_price: 554.5,
    fill_time: "2026-07-27T16:05:00Z",
  });
  const s = scan({ entry_order_id: "o1", risk_per_share: null });
  const result = pairHourlyTrades([entry, exit], [s]);
  const [ct] = result.closedTrades;
  assertEquals(ct.rMultiple, null);
  assertEquals(ct.rMultipleNaReason, "risk_per_share unavailable");
});

Deno.test("pairHourlyTrades: an in-window panic_cli fill is a manual intervention, not paired", () => {
  const entry = trade({ reason: "hourly_long_entry", broker_order_id: "o1" });
  const panic = trade({
    reason: "panic_cli",
    broker_order_id: "o3",
    fill_time: "2026-07-27T17:00:00Z",
  });
  const result = pairHourlyTrades([entry, panic], [scan({ entry_order_id: "o1" })]);
  assertEquals(result.manualInterventions.length, 1);
  assertEquals(result.manualInterventions[0].broker_order_id, "o3");
  // The entry is untouched by the panic fill -- still open, per D-note in the sub-plan.
  assertEquals(result.openEntries.length, 1);
});

Deno.test("pairHourlyTrades: sequential FIFO pairing across multiple entries for the same symbol", () => {
  const e1 = trade({ reason: "hourly_long_entry", broker_order_id: "e1", fill_time: "2026-07-27T14:00:00Z" });
  const e2 = trade({ reason: "hourly_long_entry", broker_order_id: "e2", fill_time: "2026-07-27T15:00:00Z" });
  const x1 = trade({
    reason: "hourly_bracket_exit",
    broker_order_id: "x1",
    fill_time: "2026-07-27T16:00:00Z",
    fill_price: 560,
  });
  const scans = [scan({ entry_order_id: "e1" }), scan({ entry_order_id: "e2" })];
  const result = pairHourlyTrades([e1, e2, x1], scans);
  assertEquals(result.closedTrades.length, 1);
  assertEquals(result.openEntries.length, 1);
  // FIFO: e1 (earliest) pairs with the only exit; e2 stays open.
  assertEquals(result.openEntries[0].broker_order_id, "e2");
});

// ---------------------------------------------------------------------------
// T4 -- aggregation
// ---------------------------------------------------------------------------

function auditRow(over: Partial<AuditLogRow>): AuditLogRow {
  return {
    script_name: "hourly-check",
    started_at: "2026-07-27T14:00:00Z",
    finished_at: "2026-07-27T14:00:05Z",
    outcome: "success",
    notes: null,
    ...over,
  };
}

Deno.test("computeWeeklyAggregates: detector rates, decisions, skips, audit outcomes, equity vs floor", () => {
  const scanA = scan({
    bar_ts: "2026-07-27T14:00:00Z",
    decision: "LONG",
    skip_reason: null,
    detectors_fired: ["bullish_marubozu"],
    equity_usd: 100000,
  });
  const scanB = scan({
    bar_ts: "2026-07-27T15:00:00Z",
    decision: "SKIP",
    skip_reason: "signal_conflict",
    detectors_fired: ["bullish_marubozu", "hammer"],
    equity_usd: 95000,
  });
  const scanC = scan({
    bar_ts: "2026-07-27T16:00:00Z",
    decision: "SKIP",
    skip_reason: "size_too_small",
    detectors_fired: [],
    equity_usd: 84000,
  });
  const auditRows = [
    auditRow({ started_at: "2026-07-27T14:00:00Z", outcome: "success" }),
    auditRow({ started_at: "2026-07-27T16:00:00Z", outcome: "success:auto_paused" }),
  ];

  // Passed out of order to prove the aggregator sorts by bar_ts itself.
  const agg = computeWeeklyAggregates([scanC, scanA, scanB], auditRows, 100000);

  assertEquals(agg.scansInWeek, 3);
  assertEquals(agg.detectorRates, [
    { name: "bullish_marubozu", fired: 2, scanned: 3, rate: 2 / 3 },
    { name: "hammer", fired: 1, scanned: 3, rate: 1 / 3 },
  ]);
  assertEquals(agg.decisionCounts, { LONG: 1, SHORT: 0, SKIP: 2 });
  assertEquals(agg.skipReasonCounts, { signal_conflict: 1, size_too_small: 1 });
  assertEquals(agg.auditOutcomeCounts, { success: 1, "success:auto_paused": 1 });
  assertEquals(agg.autoPausedTimestamps, ["2026-07-27T16:00:00Z"]);
  assertEquals(agg.equity.first, 100000);
  assertEquals(agg.equity.last, 84000);
  assertEquals(agg.equity.min, 84000);
  assertEquals(agg.equity.floorBaseline, 100000);
  assertEquals(agg.equity.floorPrice, 85000);
  assertEquals(agg.equity.breached, true);
});

Deno.test("computeWeeklyAggregates: an all-quiet week (no scans, no audit rows) still returns zeros", () => {
  const agg = computeWeeklyAggregates([], [], 100000);
  assertEquals(agg.scansInWeek, 0);
  assertEquals(agg.detectorRates, []);
  assertEquals(agg.decisionCounts, { LONG: 0, SHORT: 0, SKIP: 0 });
  assertEquals(agg.equity.first, null);
  assertEquals(agg.equity.min, null);
  assertEquals(agg.equity.last, null);
  assertEquals(agg.equity.breached, false);
});

function closedTrade(over: Partial<ClosedTradeResult>): ClosedTradeResult {
  return {
    symbol: "SPY",
    side: "LONG",
    entryFillPrice: 550,
    entryFillTime: "2026-07-27T14:05:00Z",
    entryOrderId: "e",
    exitFillPrice: 554.5,
    exitFillTime: "2026-07-27T16:05:00Z",
    exitOrderId: "x",
    exitReason: "hourly_bracket_exit",
    qty: 10,
    holdingBars: 2,
    rMultiple: 2,
    ...over,
  };
}

Deno.test("computeCumulativeStats: win rate, target-hit rate, mean/sum R over a mixed sample", () => {
  const trades: ClosedTradeResult[] = [
    closedTrade({ rMultiple: 2, exitReason: "hourly_bracket_exit" }), // win + target hit
    closedTrade({ rMultiple: -1, exitReason: "hourly_bracket_exit" }), // loss
    closedTrade({ rMultiple: null, rMultipleNaReason: "missing scan row for entry e3" }), // n/a
    closedTrade({ rMultiple: 0.5, exitReason: "hourly_session_close_exit" }), // win, not a target hit
  ];
  const stats = computeCumulativeStats(trades);
  assertEquals(stats.closedTradeCount, 4);
  assertEquals(stats.winRate, 0.5); // 2 winners / 4 total
  assertEquals(stats.targetHitRate, 0.25); // 1 bracket-exit win / 4 total
  assertEquals(stats.sumR, 1.5);
  assertEquals(stats.meanR, 0.5); // 1.5 / 3 trades with a known R
});

Deno.test("computeCumulativeStats: zero closed trades -> all rates null, not NaN", () => {
  const stats = computeCumulativeStats([]);
  assertEquals(stats, {
    closedTradeCount: 0,
    winRate: null,
    targetHitRate: null,
    meanR: null,
    sumR: null,
  });
});

// ---------------------------------------------------------------------------
// T5 -- proposal rule (spec §11's two constraints, mechanically enforced)
// ---------------------------------------------------------------------------

function stats(over: Partial<CumulativeStats>): CumulativeStats {
  return {
    closedTradeCount: 40,
    winRate: 0.3,
    targetHitRate: 0.08,
    meanR: -0.1,
    sumR: -4,
    ...over,
  };
}

Deno.test("proposeParamChange: below the minimum sample -> gated, even if the statistic breaches", () => {
  const result = proposeParamChange(stats({ closedTradeCount: 10, targetHitRate: 0.05 }));
  assertEquals(result, {
    gated: true,
    reason: `no proposal permitted (N=10 < ${PROPOSAL_MIN_CLOSED_TRADES})`,
  });
});

Deno.test("proposeParamChange: at N=30 with hit rate 0.24 -> exactly one proposal naming the parameter", () => {
  const result = proposeParamChange(stats({ closedTradeCount: 30, targetHitRate: 0.24 }));
  assertEquals(result.gated, false);
  if (result.gated) throw new Error("unreachable");
  assertEquals(result.proposal !== null, true);
  assertEquals(result.proposal!.includes("HOURLY_BRACKET_R_MULTIPLE"), true);
  assertEquals(result.proposal!.includes("N=30"), true);
  assertEquals(result.proposal!.includes("24"), true);
});

Deno.test("proposeParamChange: hit rate 0.30 (above the floor) -> no proposal", () => {
  const result = proposeParamChange(stats({ closedTradeCount: 30, targetHitRate: 0.30 }));
  assertEquals(result, { gated: false, proposal: null });
});

Deno.test("proposeParamChange: at most one proposal -- first-hit-wins over a two-candidate list", () => {
  const candidates = [
    {
      name: "always_fires",
      check: () => true,
      render: () => "candidate A fired",
    },
    {
      name: "also_would_fire",
      check: () => true,
      render: () => "candidate B fired",
    },
  ];
  const result = proposeParamChange(stats({ closedTradeCount: 40 }), candidates);
  assertEquals(result, { gated: false, proposal: "candidate A fired" });
});

Deno.test("DEFAULT_PROPOSAL_CANDIDATES: exactly one default candidate (D5, size:M trim point)", () => {
  assertEquals(DEFAULT_PROPOSAL_CANDIDATES.length, 1);
});
