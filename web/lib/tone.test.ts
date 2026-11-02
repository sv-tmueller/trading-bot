import { test } from "node:test";
import assert from "node:assert/strict";
import {
  decisionTone,
  directionLabel,
  headroomTone,
  HEADROOM_WARN_PCT,
  outcomeTone,
  qtyLabel,
  signTone,
} from "./tone.ts";

test("signTone: positive is pos, negative is neg", () => {
  assert.equal(signTone(0.0123), "pos");
  assert.equal(signTone(-0.0123), "neg");
});

test("signTone: zero, null, undefined and non-finite are muted", () => {
  for (const v of [0, -0, null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(signTone(v), "muted", String(v));
  }
});

test("outcomeTone: success and success:* are pos", () => {
  assert.equal(outcomeTone("success"), "pos");
  assert.equal(outcomeTone("success:no_action"), "pos");
  assert.equal(outcomeTone("success:legs_replaced"), "pos");
});

test("outcomeTone: success:auto_paused is neg (lead decision, batch #738)", () => {
  assert.equal(outcomeTone("success:auto_paused"), "neg");
});

test("outcomeTone: success:journal_degraded is warn (lead decision, batch #738)", () => {
  assert.equal(outcomeTone("success:journal_degraded"), "warn");
});

test("outcomeTone: error:* is neg", () => {
  assert.equal(outcomeTone("error:DataError"), "neg");
  assert.equal(outcomeTone("error:naked_position_flattened"), "neg");
});

test("outcomeTone: skipped:*, null and empty are muted", () => {
  assert.equal(outcomeTone("skipped:trading_paused"), "muted");
  assert.equal(outcomeTone("skipped:duplicate_run"), "muted");
  assert.equal(outcomeTone(null), "muted");
  assert.equal(outcomeTone(undefined), "muted");
  assert.equal(outcomeTone(""), "muted");
});

test("outcomeTone: unknown strings get no tone, never a guess", () => {
  assert.equal(outcomeTone("successful"), null);
  assert.equal(outcomeTone("errors:x"), null);
  assert.equal(outcomeTone("unknown"), null);
});

test("headroomTone: exactly the warn threshold is default text (null)", () => {
  assert.equal(HEADROOM_WARN_PCT, 5);
  assert.equal(headroomTone(5, false), null);
});

test("headroomTone: inside the 0-5% band is warn", () => {
  for (const v of [4.99, 2.5, 0.01]) {
    assert.equal(headroomTone(v, false), "warn", String(v));
  }
});

test("headroomTone: at or below the floor is neg", () => {
  assert.equal(headroomTone(0, false), "neg");
  assert.equal(headroomTone(-3, false), "neg");
  assert.equal(headroomTone(null, true), "neg");
  assert.equal(headroomTone(40, true), "neg");
});

test("headroomTone: unknown headroom is muted", () => {
  assert.equal(headroomTone(null, false), "muted");
  assert.equal(headroomTone(NaN, false), "muted");
});

test("headroomTone: never pos", () => {
  for (const v of [-10, 0, 1, 4.99, 5, 40, 100]) {
    assert.notEqual(headroomTone(v, false), "pos", String(v));
  }
});

test("decisionTone: SKIP and missing are muted, direction is untoned", () => {
  assert.equal(decisionTone("SKIP"), "muted");
  assert.equal(decisionTone(null), "muted");
  assert.equal(decisionTone(undefined), "muted");
  assert.equal(decisionTone("LONG"), null);
  assert.equal(decisionTone("SHORT"), null);
});

test("directionLabel: long side gets an up marker, short side a down marker", () => {
  assert.equal(directionLabel("LONG"), "▲ LONG");
  assert.equal(directionLabel("SHORT"), "▼ SHORT");
  assert.equal(directionLabel("BUY"), "▲ BUY");
  assert.equal(directionLabel("SELL"), "▼ SELL");
  assert.equal(directionLabel("buy"), "▲ buy");
});

test("directionLabel: other text is unchanged", () => {
  assert.equal(directionLabel("SKIP"), "SKIP");
});

test("qtyLabel: sign becomes a marker and the minus is kept", () => {
  assert.equal(qtyLabel(10), "▲ 10");
  assert.equal(qtyLabel(-10), "▼ -10");
  assert.equal(qtyLabel(0), "0");
});
