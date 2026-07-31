import { assertEquals, assertThrows } from "@std/assert";
import { DataError, requireNumber, roundToCents } from "./num.ts";

Deno.test("requireNumber accepts finite numbers and numeric strings", () => {
  assertEquals(requireNumber(42, "x"), 42);
  assertEquals(requireNumber("3.14", "x"), 3.14);
  assertEquals(requireNumber("12345.67", "equity"), 12345.67);
  assertEquals(requireNumber(0, "x"), 0);
  assertEquals(requireNumber(-5, "x"), -5);
  assertEquals(requireNumber("0", "qty"), 0);
});

Deno.test("requireNumber rejects null / undefined / empty", () => {
  assertThrows(() => requireNumber(null, "x"), DataError, "x");
  assertThrows(() => requireNumber(undefined, "x"), DataError, "x");
  assertThrows(() => requireNumber("", "x"), DataError, "x");
});

Deno.test("requireNumber rejects whitespace-only strings (finding 14)", () => {
  // Number(" ") === 0 — a blank price/qty must fail loud, not become 0.
  assertThrows(() => requireNumber(" ", "x"), DataError, "x");
  assertThrows(() => requireNumber("\t\n", "x"), DataError, "x");
});

Deno.test("requireNumber rejects NaN and non-finite values", () => {
  assertThrows(() => requireNumber("abc", "x"), DataError, "x");
  assertThrows(() => requireNumber(Infinity, "x"), DataError, "finite");
  assertThrows(() => requireNumber(-Infinity, "x"), DataError, "finite");
  assertThrows(() => requireNumber("1e999", "x"), DataError, "finite"); // overflows to Infinity
});

// ---------------------------------------------------------------------------
// #494 group A: roundToCents -- the outbound half of the numeric boundary.
//
// Alpaca rejects any equity price above $1 that is not a $0.01 multiple with
// a 422 (code 42210000). The contract is stated in SERIALIZATION terms
// because the defect is a serialization defect: String(output) must render at
// most two decimals with no float artifact. A numeric-only contract would
// admit 745.05000000000007, which still 422s.
// ---------------------------------------------------------------------------

Deno.test("A1 roundToCents: the 2026-07-30 rejection 745.0495000000001 -> 745.05", () => {
  // Live literal from the 16:07Z take_profit.limit_price rejection: float
  // noise AND sub-penny at the same time.
  assertEquals(roundToCents(745.0495000000001), 745.05);
  assertEquals(String(roundToCents(745.0495000000001)), "745.05");
});

Deno.test("A2 roundToCents: the 2026-07-30 rejection 746.173 -> 746.17", () => {
  // KEEP THIS CASE. It is not redundant with A1. 746.173 (the 17:07Z
  // rejection) has no float representation artifact at all: it is a clean
  // three-decimal number, i.e. genuinely a tenth of a cent. A fix that only
  // de-noises the float representation passes A1 and still gets a 422 here.
  // This case is what pins the requirement to quantization rather than
  // de-noising.
  assertEquals(roundToCents(746.173), 746.17);
  assertEquals(String(roundToCents(746.173)), "746.17");
});

Deno.test("A3 roundToCents: penny-exact inputs pass through and stay penny-exact", () => {
  for (const v of [744.21, 746.64, 547.75, 554.5, 550, 0.05, 0]) {
    assertEquals(roundToCents(v), v);
    assertEquals(String(roundToCents(v)), String(v));
  }
});

Deno.test("A4 roundToCents: output always serializes to at most two decimals", () => {
  const CENT_CLEAN = /^-?\d+(\.\d{1,2})?$/;
  for (let i = 0; i < 2000; i++) {
    // Geometry-shaped values: a 4-decimal stop times an R multiple is exactly
    // the arithmetic that produced the rejected prices.
    const raw = 744 + i * 0.0007 + 2 * (i * 0.00013);
    const out = roundToCents(raw, "sweep");
    assertEquals(CENT_CLEAN.test(String(out)), true, `${raw} -> ${String(out)}`);
  }
});

Deno.test("A5 roundToCents: half-cent tie direction is pinned by test, not promised", () => {
  // Implementation-defined (Math.round(v * 100) / 100). Pinned so a future
  // change of helper is a deliberate, visible decision.
  assertEquals(roundToCents(745.005), 745.01); // exact tie -> away from zero
  assertEquals(roundToCents(1.005), 1); // the decimal literal is below the tie in binary
  assertEquals(roundToCents(2.675), 2.68);
});

Deno.test("A6 roundToCents: NaN, non-finite and non-number input throw DataError", () => {
  // Never degrade to 0, and never quietly parse a string the way requireNumber
  // does -- this helper is the outbound direction, so its input has already
  // crossed the boundary and must already be a finite number.
  assertThrows(() => roundToCents(NaN, "stop_price"), DataError, "stop_price");
  assertThrows(() => roundToCents(Infinity, "target_price"), DataError, "target_price");
  assertThrows(() => roundToCents(-Infinity, "target_price"), DataError, "target_price");
  assertThrows(() => roundToCents("745.05" as unknown as number, "stop_price"), DataError);
  assertThrows(() => roundToCents(null as unknown as number, "stop_price"), DataError);
  assertThrows(() => roundToCents(undefined as unknown as number, "stop_price"), DataError);
});
