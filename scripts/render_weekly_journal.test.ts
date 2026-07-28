// Unit tests for the weekly-review aggregator (#481, batch #478 Package C).
// Every dep is a plain injected mock -- no network, no real Supabase client
// construction, no filesystem writes outside deps.writeFile mocks.
// CLAUDE_AGENT_NO_BROKER is set by the `test` deno.json task; this script
// never imports _shared/alpaca.ts, so the guard is inert here (defense in
// depth only, per the repo's Architectural invariants).
import { assertEquals, assertThrows } from "@std/assert";
import {
  parseWeekLabel,
  previousCompletedWeek,
  weekWindowUtc,
} from "./render_weekly_journal.ts";

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
