import { assertEquals, assertThrows } from "@std/assert";
import { DataError, requireNumber } from "./num.ts";

Deno.test("requireNumber parses valid numbers", () => {
  assertEquals(requireNumber("12345.67", "equity"), 12345.67);
  assertEquals(requireNumber(70.5, "price"), 70.5);
  assertEquals(requireNumber("0", "qty"), 0);
});

Deno.test("requireNumber rejects null/undefined/empty", () => {
  assertThrows(() => requireNumber(null, "f"), DataError, "f");
  assertThrows(() => requireNumber(undefined, "f"), DataError, "f");
  assertThrows(() => requireNumber("", "f"), DataError, "f");
});

Deno.test("requireNumber rejects whitespace-only strings (finding 14)", () => {
  // Number(" ") === 0 — a blank price/qty must fail loud, not become 0.
  assertThrows(() => requireNumber(" ", "f"), DataError, "f");
  assertThrows(() => requireNumber("\t\n", "f"), DataError, "f");
});

Deno.test("requireNumber rejects non-numeric strings", () => {
  assertThrows(() => requireNumber("abc", "f"), DataError, "f");
});
