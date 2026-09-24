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
  excerptNote,
  formatMessageSuffix,
  formatMissingSlots,
  HOURLY_SLOTS_PER_WEEKDAY,
  isWeekendYmd,
  KILL_SWITCH_SLOTS_PER_WEEKDAY,
  type LedgerRow,
  MalformedVerificationError,
  NON_SCANNING_OUTCOMES,
  NOTE_EXCERPT_MAX_CHARS,
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
// excerptNote / formatMessageSuffix (#659). Interpretation A (lead decision
// on #659): `status` ships raw `error:*` notes; this evaluator does all
// redaction, truncation and grouping before any text becomes public (a
// public repo, issues, the committed digest and ledger, Discord).
// ---------------------------------------------------------------------------

Deno.test("excerptNote: null -> null", () => {
  assertEquals(excerptNote(null), null);
});

Deno.test("excerptNote: undefined -> null", () => {
  assertEquals(excerptNote(undefined), null);
});

Deno.test("excerptNote: a number -> null", () => {
  assertEquals(excerptNote(42), null);
});

Deno.test("excerptNote: empty string -> null", () => {
  assertEquals(excerptNote(""), null);
});

Deno.test("excerptNote: whitespace-only string -> null", () => {
  assertEquals(excerptNote("   \n\t  "), null);
});

Deno.test("excerptNote: a short message comes back unchanged", () => {
  assertEquals(
    excerptNote("GET bars SPY -> 503: upstream connect error"),
    "GET bars SPY -> 503: upstream connect error",
  );
});

Deno.test("excerptNote: newlines and tabs collapse to single spaces", () => {
  assertEquals(excerptNote("line one\nline\ttwo\r\nline three"), "line one line two line three");
});

Deno.test("excerptNote: a URL is redacted to [url]", () => {
  assertEquals(
    excerptNote("GET https://api.example.com/v2/clock -> timeout"),
    "GET [url] -> timeout",
  );
});

Deno.test("excerptNote: the Deno 'error sending request for url (...)' shape redacts the parenthesized URL", () => {
  assertEquals(
    excerptNote(
      "error sending request for url (https://abcproj.supabase.co/rest/v1/audit_log): error trying to connect: tcp connect error",
    ),
    "error sending request for url ([url]): error trying to connect: tcp connect error",
  );
});

Deno.test("excerptNote: an uppercase HTTPS:// scheme is redacted to [url] (case-insensitive)", () => {
  assertEquals(
    excerptNote("GET HTTPS://api.example.com/v2/clock -> timeout"),
    "GET [url] -> timeout",
  );
});

Deno.test("excerptNote: a postgres:// URL with embedded credentials is redacted to [url]", () => {
  assertEquals(
    excerptNote("could not connect: postgres://user:pass@host/db"),
    "could not connect: [url]",
  );
});

Deno.test("excerptNote: a bare supabase host with no protocol is redacted to [host]", () => {
  assertEquals(
    excerptNote("could not reach abcproj.supabase.co right now"),
    "could not reach [host] right now",
  );
});

Deno.test("excerptNote: a JWT is redacted", () => {
  const jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGVzdHNpZ25hdHVyZXZhbHVl";
  // Deliberately not adjacent to a "token="-shaped prefix -- that's covered
  // by the key=value test below, and the two redaction classes may
  // legitimately compose (accepted over-redaction) when a note has both.
  assertEquals(excerptNote(`session ${jwt} expired`), "session [redacted] expired");
});

Deno.test("excerptNote: a Bearer token is redacted", () => {
  assertEquals(
    excerptNote("Authorization: Bearer abcDEF123token456value"),
    "Authorization: [redacted]",
  );
});

Deno.test("excerptNote: a key=value secret-shaped field is redacted", () => {
  assertEquals(excerptNote("api_key=SUPERSECRETVALUE123 invalid"), "[redacted] invalid");
});

Deno.test("excerptNote: an sb_secret_ token is redacted", () => {
  assertEquals(
    excerptNote("using sb_secret_abcdefghijklmnopqrstuvwxyz0123456789 failed"),
    "using [redacted] failed",
  );
});

Deno.test("excerptNote: a bare 40-char run (e.g. a hex digest) is redacted", () => {
  // Space-separated, not "sha=...": a "=" joined onto the run would itself be
  // consumed by the generic 32+ [A-Za-z0-9+/=_-] class (accepted
  // over-redaction), which is exercised separately by the key=value test.
  assertEquals(
    excerptNote("digest a94a8fe5ccb19ba61c4c0873d391e987982fbbd3 mismatch"),
    "digest [redacted] mismatch",
  );
});

Deno.test("excerptNote: an Alpaca PK-prefixed key id is redacted", () => {
  assertEquals(
    excerptNote("key PK1234567890ABCDEF rejected"),
    "key [redacted] rejected",
  );
});

Deno.test("excerptNote: an HTML 502 page is stripped but the visible text survives", () => {
  assertEquals(
    excerptNote("<html><body><h1>502 Bad Gateway</h1></body></html>"),
    "502 Bad Gateway",
  );
});

Deno.test("excerptNote: quotes, backticks and @everyone are neutralized", () => {
  assertEquals(
    excerptNote('say "hi" `code` @everyone'),
    "say 'hi' 'code' (at)everyone",
  );
});

// A run of 10 letters followed by a space, cycled -- never a 32+-char run
// from GENERIC_SECRET_RE's charset (space breaks it every 10 chars), so
// these fixtures exercise ONLY the length/truncation behavior, not
// redaction.
function safeText(length: number): string {
  let out = "";
  let i = 0;
  while (out.length < length) {
    out += String.fromCharCode(97 + (i % 26));
    i++;
    if (i % 10 === 0) out += " ";
  }
  return out.slice(0, length);
}

Deno.test("excerptNote: over 200 chars truncates to exactly 200 codepoints, ending in ...", () => {
  const long = safeText(500);
  const result = excerptNote(long)!;
  assertEquals([...result].length, NOTE_EXCERPT_MAX_CHARS);
  assertEquals(result.endsWith("..."), true);
  assertEquals(result.slice(0, 197), long.slice(0, 197));
});

Deno.test("excerptNote: exactly 200 codepoints is not cut", () => {
  const exact = safeText(200);
  assertEquals(excerptNote(exact), exact);
});

Deno.test("excerptNote: astral characters (surrogate pairs) are not split by truncation", () => {
  const long = "\u{1F600}".repeat(250); // 250 codepoints, 500 UTF-16 code units
  const result = excerptNote(long)!;
  // Every character in the result (other than the trailing "...") must be a
  // full astral codepoint -- Array.from never produces a lone surrogate.
  const chars = [...result];
  assertEquals(chars.length, NOTE_EXCERPT_MAX_CHARS);
  for (const c of chars.slice(0, chars.length - 3)) {
    assertEquals(c, "\u{1F600}");
  }
});

Deno.test("excerptNote: a secret straddling the 200-char cut does not partially appear", () => {
  const secret = "abcdefghij0123456789ABCDEFGHIJ0123456789"; // 40 chars, 32+ run
  // Padding alternates "x" with a space so it never merges with the secret
  // into one contiguous GENERIC_SECRET_RE run (a space isn't in that class'
  // character set) -- the secret genuinely starts at its own codepoint 185,
  // straddling the 200-char cut, instead of being absorbed into one giant
  // redacted run together with the padding.
  const padding = "x ".repeat(92) + "x"; // 185 codepoints
  const result = excerptNote(padding + secret + " tail")!;
  assertEquals(result.includes(secret), false);
  // No fragment of the raw secret (a run of 8+ of its own characters) survives.
  assertEquals(result.includes(secret.slice(0, 8)), false);
});

Deno.test("formatMessageSuffix: empty array -> empty string", () => {
  assertEquals(formatMessageSuffix([]), "");
});

Deno.test("formatMessageSuffix: all-null notes -> empty string (today's text, unchanged)", () => {
  assertEquals(formatMessageSuffix([null, null]), "");
});

Deno.test("formatMessageSuffix: one message across count=2 has no +N", () => {
  assertEquals(
    formatMessageSuffix(["same message", "same message"]),
    ' -- message: "same message"',
  );
});

Deno.test("formatMessageSuffix: two distinct messages -> singular +1 other distinct message", () => {
  assertEquals(
    formatMessageSuffix(["first", "second"]),
    ' -- message: "first" (+1 other distinct message)',
  );
});

Deno.test("formatMessageSuffix: three distinct messages -> plural +2 other distinct messages", () => {
  assertEquals(
    formatMessageSuffix(["first", "second", "third"]),
    ' -- message: "first" (+2 other distinct messages)',
  );
});

Deno.test("formatMessageSuffix: notes differing only in a URL count as one distinct message", () => {
  assertEquals(
    formatMessageSuffix([
      "GET https://a.example.com/x -> timeout",
      "GET https://b.example.com/y -> timeout",
    ]),
    ' -- message: "GET [url] -> timeout"',
  );
});

Deno.test("formatMessageSuffix: mixed null and non-null -- first non-null is used, nulls not counted", () => {
  assertEquals(
    formatMessageSuffix([null, "abc", null, "xyz"]),
    ' -- message: "abc" (+1 other distinct message)',
  );
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

// #659: message excerpts on the per-run error: finding.

Deno.test("checkSlots: an error run with notes gets the message excerpt suffix", () => {
  const runs = [
    ...Array.from({ length: 8 }, () => hourlyRun()),
    hourlyRun({
      started_at: "2026-08-05T21:07:00.000Z",
      outcome: "error:AlpacaError",
      notes: "GET bars SPY -> 503: upstream connect error",
    }),
  ];
  const result = checkSlots(runs);
  assertEquals(result.findings, [
    'slots: run started_at=2026-08-05T21:07:00.000Z outcome=error:AlpacaError -- message: "GET bars SPY -> 503: upstream connect error"',
  ]);
});

Deno.test("checkSlots: an error run with null notes -> byte-identical finding to today's text", () => {
  const runs = [
    ...Array.from({ length: 8 }, () => hourlyRun()),
    hourlyRun({
      started_at: "2026-08-05T21:07:00.000Z",
      outcome: "error:AlpacaError",
      notes: null,
    }),
  ];
  const result = checkSlots(runs);
  assertEquals(result.findings, [
    "slots: run started_at=2026-08-05T21:07:00.000Z outcome=error:AlpacaError",
  ]);
});

Deno.test("checkSlots: a non-error run's notes (e.g. the journal-degraded order id) never surface", () => {
  const runs = [
    ...Array.from({ length: 8 }, () => hourlyRun()),
    hourlyRun({ outcome: "success:journal_degraded", notes: "journal_degraded order o-1" }),
  ];
  assertEquals(checkSlots(runs), { status: "PASS", findings: [] });
});

// ---------------------------------------------------------------------------
// checkLatency (§5.3 check 5)
// ---------------------------------------------------------------------------

Deno.test("checkLatency: every run well under the scan warn threshold -> PASS", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:02.000Z",
  })];
  assertEquals(checkLatency(runs, 0), { status: "PASS", findings: [] });
});

Deno.test("checkLatency: just over the 5s scan warn threshold -> WARN (scan-only day)", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:05.001Z",
  })];
  const result = checkLatency(runs, 0);
  assertEquals(result.status, "WARN");
  assertEquals(result.findings.length, 1);
});

Deno.test("checkLatency: exactly at the 5s scan warn threshold -> PASS (boundary is exclusive)", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:05.000Z",
  })];
  assertEquals(checkLatency(runs, 0), { status: "PASS", findings: [] });
});

Deno.test("checkLatency: scan-only day at 6s -> WARN (over 5000ms scan threshold)", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:06.000Z",
  })];
  const result = checkLatency(runs, 0);
  assertEquals(result.status, "WARN");
  assertEquals(result.findings.length, 1);
});

Deno.test("checkLatency: entry day at 11s -> PASS (under 12000ms entry threshold)", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:11.000Z",
  })];
  assertEquals(checkLatency(runs, 1), { status: "PASS", findings: [] });
});

Deno.test("checkLatency: entry day at 13s -> WARN (over 12000ms entry threshold)", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:07:13.000Z",
  })];
  const result = checkLatency(runs, 1);
  assertEquals(result.status, "WARN");
  assertEquals(result.findings.length, 1);
});

Deno.test("checkLatency: just over the 120s fail threshold -> FAIL", () => {
  const runs = [hourlyRun({
    started_at: "2026-08-05T13:07:00.000Z",
    finished_at: "2026-08-05T13:09:00.001Z",
  })];
  assertEquals(checkLatency(runs, 0).status, "FAIL");
});

Deno.test("checkLatency: a FAIL run alongside a WARN run -> overall FAIL (highest severity wins)", () => {
  const runs = [
    hourlyRun({
      started_at: "2026-08-05T13:07:00.000Z",
      finished_at: "2026-08-05T13:07:06.001Z",
    }),
    hourlyRun({
      started_at: "2026-08-05T14:07:00.000Z",
      finished_at: "2026-08-05T14:09:00.001Z",
    }),
  ];
  assertEquals(checkLatency(runs, 0).status, "FAIL");
});

Deno.test("checkLatency: unfinished run (finished_at null) is skipped, not a latency finding", () => {
  const runs = [hourlyRun({ finished_at: null, outcome: null })];
  assertEquals(checkLatency(runs, 0), { status: "PASS", findings: [] });
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

// #659: message excerpts on the odd-outcome finding.

Deno.test("checkKillSwitch: one message across count=2 has no +N", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 106, "error:Error": 2 },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: "boom" },
        { started_at: "2026-08-05T19:05:00.000Z", outcome: "error:Error", notes: "boom" },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    'kill_switch: outcome=error:Error (count=2) is neither success:* nor skipped:* -- message: "boom"',
  ]);
});

Deno.test("checkKillSwitch: two distinct messages -> singular +1 other distinct message", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 105, "error:Error": 3 },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: "first" },
        { started_at: "2026-08-05T19:05:00.000Z", outcome: "error:Error", notes: "second" },
        { started_at: "2026-08-05T19:10:00.000Z", outcome: "error:Error", notes: "first" },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    'kill_switch: outcome=error:Error (count=3) is neither success:* nor skipped:* -- message: "first" (+1 other distinct message)',
  ]);
});

Deno.test("checkKillSwitch: three distinct messages -> plural +2 other distinct messages", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 105, "error:Error": 3 },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: "first" },
        { started_at: "2026-08-05T19:05:00.000Z", outcome: "error:Error", notes: "second" },
        { started_at: "2026-08-05T19:10:00.000Z", outcome: "error:Error", notes: "third" },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    'kill_switch: outcome=error:Error (count=3) is neither success:* nor skipped:* -- message: "first" (+2 other distinct messages)',
  ]);
});

Deno.test("checkKillSwitch: notes differing only in a URL count as one distinct message", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 106, "error:Error": 2 },
      error_runs: [
        {
          started_at: "2026-08-05T19:00:00.000Z",
          outcome: "error:Error",
          notes: "GET https://a.example.com/x -> timeout",
        },
        {
          started_at: "2026-08-05T19:05:00.000Z",
          outcome: "error:Error",
          notes: "GET https://b.example.com/y -> timeout",
        },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    'kill_switch: outcome=error:Error (count=2) is neither success:* nor skipped:* -- message: "GET [url] -> timeout"',
  ]);
});

Deno.test("checkKillSwitch: an all-null error_runs group gives today's text (no suffix)", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 106, "error:Error": 2 },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: null },
        { started_at: "2026-08-05T19:05:00.000Z", outcome: "error:Error", notes: null },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    "kill_switch: outcome=error:Error (count=2) is neither success:* nor skipped:*",
  ]);
});

Deno.test("checkKillSwitch: mixed null and non-null notes -- first non-null used, nulls not counted", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 105, "error:Error": 3 },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: null },
        { started_at: "2026-08-05T19:05:00.000Z", outcome: "error:Error", notes: "abc" },
        { started_at: "2026-08-05T19:10:00.000Z", outcome: "error:Error", notes: "xyz" },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    'kill_switch: outcome=error:Error (count=3) is neither success:* nor skipped:* -- message: "abc" (+1 other distinct message)',
  ]);
});

Deno.test("checkKillSwitch: two error outcomes each get only their own group's messages", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: {
        "success:no_position": 104,
        "error:Error": 2,
        "error:AlpacaError": 2,
      },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: "aaa" },
        { started_at: "2026-08-05T19:05:00.000Z", outcome: "error:Error", notes: "aaa" },
        { started_at: "2026-08-05T20:00:00.000Z", outcome: "error:AlpacaError", notes: "bbb" },
        { started_at: "2026-08-05T20:05:00.000Z", outcome: "error:AlpacaError", notes: "bbb" },
      ],
    },
    [],
  );
  assertEquals(
    result.findings.sort(),
    [
      'kill_switch: outcome=error:AlpacaError (count=2) is neither success:* nor skipped:* -- message: "bbb"',
      'kill_switch: outcome=error:Error (count=2) is neither success:* nor skipped:* -- message: "aaa"',
    ].sort(),
  );
});

Deno.test("checkKillSwitch: error_runs absent gives today's text byte-for-byte", () => {
  const result = checkKillSwitch(
    { count: 108, outcome_counts: { "success:no_position": 107, "error:Error": 1 } },
    [],
  );
  assertEquals(result.findings, [
    "kill_switch: outcome=error:Error (count=1) is neither success:* nor skipped:*",
  ]);
});

Deno.test("checkKillSwitch: a non-error odd outcome gets no suffix (no matching error_runs entries)", () => {
  const result = checkKillSwitch(
    {
      count: 108,
      outcome_counts: { "success:no_position": 107, "weird:outcome": 1 },
      error_runs: [
        { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Unrelated", notes: "n/a" },
      ],
    },
    [],
  );
  assertEquals(result.findings, [
    "kill_switch: outcome=weird:outcome (count=1) is neither success:* nor skipped:*",
  ]);
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
    pg_net_timeouts: "PASS",
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

// #659: end-to-end -- a 108-run kill-switch block with two `error:Error`
// rows carrying notes gives FAIL, the message excerpt appears in the
// finding, and the finding COUNT stays stable versus the no-notes variant
// (the suffix is appended to the existing finding, never a new one) so a
// FAIL issue title's `N finding(s)` doesn't shift just because notes showed
// up.
Deno.test("evaluateVerification: a 108-run kill-switch block with 2x error:Error+notes -> FAIL, excerpt appears, findings.length unchanged vs. the no-notes variant", () => {
  const withNotes = cleanDayVerification();
  withNotes.kill_switch_runs = {
    count: 108,
    outcome_counts: { "success:no_position": 106, "error:Error": 2 },
    error_runs: [
      {
        started_at: "2026-08-05T19:00:00.000Z",
        outcome: "error:Error",
        notes: "GET bars SPY -> 503: upstream connect error",
      },
      {
        started_at: "2026-08-05T19:05:00.000Z",
        outcome: "error:Error",
        notes: "GET bars SPY -> 503: upstream connect error",
      },
    ],
  };
  const withNotesResult = evaluateVerification(withNotes, null);
  assertEquals(withNotesResult.verdict, "FAIL");
  assertEquals(
    withNotesResult.findings.some((f) =>
      f === "kill_switch: outcome=error:Error (count=2) is neither success:* nor skipped:* -- " +
          'message: "GET bars SPY -> 503: upstream connect error"'
    ),
    true,
  );

  const noNotes = cleanDayVerification();
  noNotes.kill_switch_runs = {
    count: 108,
    outcome_counts: { "success:no_position": 106, "error:Error": 2 },
  };
  const noNotesResult = evaluateVerification(noNotes, null);
  assertEquals(noNotesResult.verdict, "FAIL");
  assertEquals(withNotesResult.findings.length, noNotesResult.findings.length);
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
  const row = buildLedgerRow("2026-08-05", "dev", evaluation);
  assertEquals(row.date, "2026-08-05");
  assertEquals(row.verdict, "PASS");
  assertEquals(row.checks, evaluation.checks);
  assertEquals(row.findings, evaluation.findings);
});

function ledgerRow(date: string, overrides: Partial<LedgerRow> = {}): LedgerRow {
  const evaluation = evaluateVerification(cleanDayVerification(), null);
  return { ...buildLedgerRow(date, "dev", evaluation), ...overrides };
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
  assertEquals(selectPreviousRow(rows, "2026-08-05", "dev")?.date, "2026-08-04");
});

Deno.test("selectPreviousRow: skips a gap day correctly (no row exactly one day back)", () => {
  const rows = [ledgerRow("2026-08-01"), ledgerRow("2026-08-05")];
  assertEquals(selectPreviousRow(rows, "2026-08-06", "dev")?.date, "2026-08-05");
});

Deno.test("selectPreviousRow: a backfilled out-of-order write is still found by date, not insertion order", () => {
  const rows = [ledgerRow("2026-08-05"), ledgerRow("2026-08-01")];
  assertEquals(selectPreviousRow(rows, "2026-08-05", "dev")?.date, "2026-08-01");
});

Deno.test("selectPreviousRow: no row strictly before the target -> null (day zero)", () => {
  const rows = [ledgerRow("2026-08-05")];
  assertEquals(selectPreviousRow(rows, "2026-08-05", "dev"), null);
  assertEquals(selectPreviousRow([], "2026-08-05", "dev"), null);
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

  const ledgerRow = buildLedgerRow(v.date, "dev", result);
  assertEquals(
    ledgerRow.findings.includes("kill_switch: expected 108 runs, found 107 (missing: 19:05Z)"),
    true,
  );

  const digest = renderMarkdownDigest(v.date, result, null);
  assertEquals(
    digest.includes("kill_switch: expected 108 runs, found 107 (missing: 19:05Z)"),
    true,
  );
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

// #659: kill_switch_runs.error_runs is optional -- absent is valid (backward
// compat, same #562 pattern as started_at above); when present, each entry
// needs a parsable started_at and a string outcome. notes is not validated.

Deno.test("parseVerificationBlock: kill_switch_runs.error_runs absent -> parses fine (old digest)", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  const killSwitchRuns = raw.kill_switch_runs as Record<string, unknown>;
  assertEquals("error_runs" in killSwitchRuns, false);
  const parsed = parseVerificationBlock(raw);
  assertEquals(parsed.kill_switch_runs.error_runs, undefined);
});

Deno.test("parseVerificationBlock: kill_switch_runs.error_runs valid -> parses through", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).error_runs = [
    { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: "boom" },
  ];
  const parsed = parseVerificationBlock(raw);
  assertEquals(parsed.kill_switch_runs.error_runs, [
    { started_at: "2026-08-05T19:00:00.000Z", outcome: "error:Error", notes: "boom" },
  ]);
});

Deno.test("parseVerificationBlock: kill_switch_runs.error_runs not an array -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).error_runs = "not-an-array";
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: kill_switch_runs.error_runs entry not an object -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).error_runs = ["not-an-object"];
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: kill_switch_runs.error_runs entry with an unparseable started_at -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).error_runs = [
    { started_at: "not-a-timestamp", outcome: "error:Error", notes: null },
  ];
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});

Deno.test("parseVerificationBlock: kill_switch_runs.error_runs entry with a non-string outcome -> throws", () => {
  const raw = loadFixture("clean-day") as unknown as Record<string, unknown>;
  (raw.kill_switch_runs as Record<string, unknown>).error_runs = [
    { started_at: "2026-08-05T19:00:00.000Z", outcome: 42, notes: null },
  ];
  assertThrows(() => parseVerificationBlock(raw), MalformedVerificationError);
});
