// Unit tests for scripts/apply_reflection.ts (#583, wiring the frozen
// nightly-reflection engine (backtest/reflection.py) into
// .github/workflows/daily-verification.yml). Pure core only -- see that
// file's own header comment for the CLI/permission split. Fixtures under
// scripts/testdata/reflection/ were generated once by running the
// deterministic engine (backtest/reflection.py::compute_reflection) against
// tests/fixtures/reflection/'s own committed inputs. The committed copies are
// content-identical to the engine's stdout, pretty-printed for readability --
// no network, no subprocess, no Python in this test file itself.
import { assertEquals, assertMatch, assertThrows } from "@std/assert";
import { parseLedgerJsonl } from "./daily_verify.ts";
import {
  applyReflectionSection,
  DuplicateLedgerRowError,
  fallbackReflectionMarkdown,
  mergeReflectionIntoLedger,
  MissingLedgerRowError,
  planApply,
  selectPriorLedgerRows,
} from "./apply_reflection.ts";

const FIXTURES_DIR = "scripts/testdata/reflection";

function readFixture(name: string): string {
  return Deno.readTextFileSync(`${FIXTURES_DIR}/${name}`);
}

interface Envelope {
  date: string;
  markdown: string;
  reflection: unknown;
}

function readEnvelope(name: string): Envelope {
  return JSON.parse(readFixture(name)) as Envelope;
}

const BASE_DOC = readFixture("base-daily-doc.md");
const LEDGER_3_ROWS = readFixture("ledger-3-rows.jsonl");
const TRADES_ENVELOPE = readEnvelope("envelope-trades.json");
const NO_TRADES_ENVELOPE = readEnvelope("envelope-no-trades.json");
const ERROR_ENVELOPE = readEnvelope("envelope-error.json");

// ---------------------------------------------------------------------------
// applyReflectionSection: append/replace the ## Reflection section at the
// end of a daily digest doc.
// ---------------------------------------------------------------------------

Deno.test("applyReflectionSection appends a section to a doc that has none (exact bytes)", () => {
  const result = applyReflectionSection(BASE_DOC, TRADES_ENVELOPE.markdown);
  const expected = `${BASE_DOC.replace(/\n+$/, "")}\n\n---\n\n${TRADES_ENVELOPE.markdown}\n`;
  assertEquals(result, expected);
});

Deno.test("applyReflectionSection replaces an existing section rather than duplicating it", () => {
  const once = applyReflectionSection(BASE_DOC, TRADES_ENVELOPE.markdown);
  const twice = applyReflectionSection(once, NO_TRADES_ENVELOPE.markdown);
  // Only one "## Reflection" heading anywhere in the doc.
  const occurrences = twice.split("## Reflection").length - 1;
  assertEquals(occurrences, 1);
  assertMatch(twice, /No closed trades; no reflection\.\n$/);
});

Deno.test("applyReflectionSection re-run with an identical envelope is byte-identical", () => {
  const once = applyReflectionSection(BASE_DOC, TRADES_ENVELOPE.markdown);
  const rerun = applyReflectionSection(once, TRADES_ENVELOPE.markdown);
  assertEquals(rerun, once);
});

Deno.test("applyReflectionSection wraps a bare error-day line under the ## Reflection heading", () => {
  const result = applyReflectionSection(BASE_DOC, ERROR_ENVELOPE.markdown);
  assertMatch(result, /## Reflection\n\nReflection: error -- /);
  // The engine's own error markdown never starts with the heading itself.
  assertEquals(ERROR_ENVELOPE.markdown.startsWith("## Reflection"), false);
});

Deno.test("applyReflectionSection renders a no-trades envelope's markdown verbatim", () => {
  const result = applyReflectionSection(BASE_DOC, NO_TRADES_ENVELOPE.markdown);
  assertMatch(result, /## Reflection\n\nNo closed trades; no reflection\.\n$/);
});

// ---------------------------------------------------------------------------
// selectPriorLedgerRows: strict-before filter feeding the engine's
// trailing-20 window.
// ---------------------------------------------------------------------------

Deno.test("selectPriorLedgerRows keeps only rows strictly before the target date", () => {
  const priorText = selectPriorLedgerRows(LEDGER_3_ROWS, "2026-08-06");
  const rows = parseLedgerJsonl(priorText);
  assertEquals(rows.map((r) => r.date), ["2026-08-04", "2026-08-05"]);
});

Deno.test("selectPriorLedgerRows excludes the target date's own row", () => {
  const priorText = selectPriorLedgerRows(LEDGER_3_ROWS, "2026-08-04");
  assertEquals(parseLedgerJsonl(priorText).length, 0);
});

Deno.test("selectPriorLedgerRows on an empty ledger returns no rows", () => {
  const priorText = selectPriorLedgerRows("", "2026-08-06");
  assertEquals(parseLedgerJsonl(priorText).length, 0);
});

// ---------------------------------------------------------------------------
// mergeReflectionIntoLedger: read-modify-write of the matching row only.
// ---------------------------------------------------------------------------

Deno.test("mergeReflectionIntoLedger adds reflection as the target row's trailing key", () => {
  const merged = mergeReflectionIntoLedger(LEDGER_3_ROWS, "2026-08-06", TRADES_ENVELOPE.reflection);
  const lines = merged.trimEnd().split("\n");
  const targetLine = lines.find((l: string) => JSON.parse(l).date === "2026-08-06")!;
  const keys = Object.keys(JSON.parse(targetLine));
  assertEquals(keys[keys.length - 1], "reflection");
  assertEquals(JSON.parse(targetLine).reflection, TRADES_ENVELOPE.reflection);
});

Deno.test("mergeReflectionIntoLedger leaves the other rows byte-untouched", () => {
  const merged = mergeReflectionIntoLedger(LEDGER_3_ROWS, "2026-08-06", TRADES_ENVELOPE.reflection);
  const originalLines = LEDGER_3_ROWS.trimEnd().split("\n");
  const mergedLines = merged.trimEnd().split("\n");
  const untouched = originalLines.filter((l: string) => JSON.parse(l).date !== "2026-08-06");
  for (const line of untouched) {
    assertEquals(mergedLines.includes(line), true);
  }
});

Deno.test("mergeReflectionIntoLedger preserves ascending date order", () => {
  const merged = mergeReflectionIntoLedger(
    LEDGER_3_ROWS,
    "2026-08-05",
    NO_TRADES_ENVELOPE.reflection,
  );
  const dates = merged.trimEnd().split("\n").map((l: string) => JSON.parse(l).date);
  assertEquals(dates, ["2026-08-04", "2026-08-05", "2026-08-06"]);
});

Deno.test("mergeReflectionIntoLedger is idempotent on re-merge with the same reflection", () => {
  const once = mergeReflectionIntoLedger(LEDGER_3_ROWS, "2026-08-06", TRADES_ENVELOPE.reflection);
  const twice = mergeReflectionIntoLedger(once, "2026-08-06", TRADES_ENVELOPE.reflection);
  assertEquals(twice, once);
});

Deno.test("mergeReflectionIntoLedger throws when the target date has no ledger row", () => {
  assertThrows(
    () => mergeReflectionIntoLedger(LEDGER_3_ROWS, "2026-08-09", TRADES_ENVELOPE.reflection),
    MissingLedgerRowError,
  );
});

Deno.test("mergeReflectionIntoLedger throws when more than one ledger row matches the target date", () => {
  const duplicateDateLedger = [
    JSON.stringify({ date: "2026-08-06", equity: 1000 }),
    JSON.stringify({ date: "2026-08-06", equity: 1001 }),
  ].join("\n") + "\n";
  assertThrows(
    () => mergeReflectionIntoLedger(duplicateDateLedger, "2026-08-06", TRADES_ENVELOPE.reflection),
    DuplicateLedgerRowError,
  );
});

// ---------------------------------------------------------------------------
// fallbackReflectionMarkdown: glue-authored vocabulary for the "envelope
// never landed" case -- never the frozen engine's own contract.
// ---------------------------------------------------------------------------

Deno.test("fallbackReflectionMarkdown names the failure under a ## Reflection heading", () => {
  const md = fallbackReflectionMarkdown("engine did not produce an output envelope");
  assertMatch(md, /^## Reflection\n\n/);
  assertMatch(md, /engine did not produce an output envelope/);
});

// ---------------------------------------------------------------------------
// planApply: the orchestration the CLI's apply mode delegates to -- decides
// doc/ledger outcomes from raw inputs without touching disk itself.
// ---------------------------------------------------------------------------

Deno.test("planApply merges the doc and ledger when the envelope parses cleanly", () => {
  const raw = JSON.stringify(TRADES_ENVELOPE);
  const plan = planApply("2026-08-06", raw, BASE_DOC, LEDGER_3_ROWS);
  assertMatch(plan.docText, /## Reflection\n\nCounterfactuals are diagnostic/);
  assertEquals(
    JSON.parse(plan.ledgerText.trimEnd().split("\n")[2]).reflection,
    TRADES_ENVELOPE.reflection,
  );
});

Deno.test("planApply writes a fallback section and leaves the ledger untouched when the envelope is absent", () => {
  const plan = planApply("2026-08-06", null, BASE_DOC, LEDGER_3_ROWS);
  assertMatch(plan.docText, /## Reflection\n\nReflection unavailable: /);
  assertEquals(plan.ledgerText, LEDGER_3_ROWS);
});

Deno.test("planApply degrades gracefully when the envelope file is present but not valid JSON", () => {
  const plan = planApply("2026-08-06", "{not json", BASE_DOC, LEDGER_3_ROWS);
  assertMatch(plan.docText, /## Reflection\n\nReflection unavailable: /);
  assertEquals(plan.ledgerText, LEDGER_3_ROWS);
});

Deno.test("planApply throws when the envelope's own date does not match --date", () => {
  const raw = JSON.stringify(TRADES_ENVELOPE);
  assertThrows(() => planApply("2026-08-07", raw, BASE_DOC, LEDGER_3_ROWS));
});
