import { assertEquals, assertThrows } from "@std/assert";
import { computeTargetState } from "./regime.ts";

// --- Bullish regime (SPY > SMA200) ---
Deno.test("bullish, no ks, from cash -> long", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: 380,
    currentState: "CASH",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "LONG");
  assertEquals(r.killSwitchActive, false);
});

Deno.test("bullish, no ks, already long -> long", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: 380,
    currentState: "LONG",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "LONG");
  assertEquals(r.killSwitchActive, false);
});

Deno.test("bullish with ks clears flag and re-enters", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: 380,
    currentState: "CASH",
    killSwitchActive: true,
  });
  assertEquals(r.targetState, "LONG");
  assertEquals(r.killSwitchActive, false);
});

// --- Bearish regime (SPY <= SMA200) ---
Deno.test("bearish, no ks, from long -> cash", () => {
  const r = computeTargetState({
    spyClose: 380,
    spySma200: 400,
    currentState: "LONG",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, false);
});

Deno.test("bearish, no ks, already cash -> cash", () => {
  const r = computeTargetState({
    spyClose: 380,
    spySma200: 400,
    currentState: "CASH",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, false);
});

Deno.test("bearish with ks keeps flag set", () => {
  const r = computeTargetState({
    spyClose: 380,
    spySma200: 400,
    currentState: "CASH",
    killSwitchActive: true,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, true);
});

// --- Boundary: SPY == SMA200 (strictly greater required for LONG) ---
Deno.test("boundary equal sma -> cash", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: 400,
    currentState: "CASH",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, false);
});

Deno.test("boundary equal sma from long -> cash", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: 400,
    currentState: "LONG",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, false);
});

// --- Defensive: NaN SMA (insufficient history) ---
Deno.test("nan sma -> cash defensively", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: NaN,
    currentState: "CASH",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, false);
});

Deno.test("nan sma with existing long exits to cash", () => {
  const r = computeTargetState({
    spyClose: 400,
    spySma200: NaN,
    currentState: "LONG",
    killSwitchActive: false,
  });
  assertEquals(r.targetState, "CASH");
  assertEquals(r.killSwitchActive, false);
});

// --- Validation ---
Deno.test("invalid current_state raises", () => {
  assertThrows(
    () =>
      computeTargetState({
        spyClose: 400,
        spySma200: 380,
        // deno-lint-ignore no-explicit-any
        currentState: "HOLDING" as any,
        killSwitchActive: false,
      }),
    Error,
    "currentState",
  );
});

Deno.test("negative spy_close raises", () => {
  assertThrows(
    () =>
      computeTargetState({
        spyClose: -1,
        spySma200: 380,
        currentState: "CASH",
        killSwitchActive: false,
      }),
    Error,
    "spyClose",
  );
});

Deno.test("negative sma raises", () => {
  assertThrows(
    () =>
      computeTargetState({
        spyClose: 400,
        spySma200: -380,
        currentState: "CASH",
        killSwitchActive: false,
      }),
    Error,
    "spySma200",
  );
});

// --- Truth table (all 8 combos: regime × current × ks) ---
const truthTable: Array<[number, number, "LONG" | "CASH", boolean, "LONG" | "CASH", boolean]> = [
  [400, 380, "CASH", false, "LONG", false],
  [400, 380, "CASH", true, "LONG", false],
  [400, 380, "LONG", false, "LONG", false],
  [400, 380, "LONG", true, "LONG", false],
  [380, 400, "CASH", false, "CASH", false],
  [380, 400, "CASH", true, "CASH", true],
  [380, 400, "LONG", false, "CASH", false],
  [380, 400, "LONG", true, "CASH", true],
];

Deno.test("truth table", () => {
  for (const [spy, sma, cur, ksIn, expTarget, expKs] of truthTable) {
    const r = computeTargetState({
      spyClose: spy,
      spySma200: sma,
      currentState: cur,
      killSwitchActive: ksIn,
    });
    assertEquals(r.targetState, expTarget, `target for ${spy}/${sma}/${cur}/${ksIn}`);
    assertEquals(r.killSwitchActive, expKs, `ks for ${spy}/${sma}/${cur}/${ksIn}`);
  }
});
