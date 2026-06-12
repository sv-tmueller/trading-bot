import { assertEquals, assertThrows } from "@std/assert";
import { DataError, requireNumber } from "./num.ts";

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
