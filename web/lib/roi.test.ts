import { test } from "node:test";
import assert from "node:assert/strict";
import {
  computeDashboardRoi,
  computeRoi,
  countWeekdays,
  DAYS_PER_YEAR,
  formatSignedPct,
  HOURLY_BOT_START_DATE,
  ROLLING_WINDOW_DAYS,
  SHORT_WINDOW_TRADING_DAYS,
  type RoiInput,
} from "./roi.ts";

const EPS = 1e-12;

function close(actual: number | null, expected: number, eps = EPS): void {
  assert.notEqual(actual, null);
  assert.ok(
    Math.abs((actual as number) - expected) <= eps,
    `expected ${actual} to be within ${eps} of ${expected}`,
  );
}

function input(over: Partial<RoiInput> = {}): RoiInput {
  return {
    startEquity: 100,
    endEquity: 110,
    startDate: "2026-01-01",
    endDate: "2027-01-01",
    tradingDays: 261,
    ...over,
  };
}

test("computeRoi: +10% over 365 days annualizes to 10%", () => {
  const r = computeRoi(input());
  assert.ok(r);
  assert.equal(r.calendarDays, 365);
  close(r.rawRoi, 0.1);
  close(r.annualizedRoi, 0.1);
});

test("computeRoi: +21% over 730 days compounds to 10%, not 10.5%", () => {
  const r = computeRoi(input({ endEquity: 121, endDate: "2028-01-01" }));
  assert.ok(r);
  assert.equal(r.calendarDays, 730);
  close(r.rawRoi, 0.21);
  close(r.annualizedRoi, 0.1);
});

test("computeRoi: losses annualize negative", () => {
  const a = computeRoi(input({ endEquity: 90 }));
  assert.ok(a);
  close(a.rawRoi, -0.1);
  close(a.annualizedRoi, -0.1);
  const b = computeRoi(input({ endEquity: 99, endDate: "2026-01-31" }));
  assert.ok(b);
  assert.equal(b.calendarDays, 30);
  assert.equal(DAYS_PER_YEAR, 365);
  close(b.annualizedRoi, Math.pow(0.99, DAYS_PER_YEAR / 30) - 1);
  close(b.annualizedRoi, -0.1151, 1e-4);
});

test("computeRoi: equal dates keep raw ROI, null annualized, short window", () => {
  const r = computeRoi(input({ endDate: "2026-01-01", tradingDays: 0 }));
  assert.ok(r);
  assert.equal(r.calendarDays, 0);
  close(r.rawRoi, 0.1);
  assert.equal(r.annualizedRoi, null);
  assert.equal(r.shortWindow, true);
});

test("computeRoi: a single data point (same equity, same date) is raw 0, not annualized", () => {
  const r = computeRoi(input({ endEquity: 100, endDate: "2026-01-01", tradingDays: 0 }));
  assert.ok(r);
  assert.equal(r.rawRoi, 0);
  assert.equal(r.annualizedRoi, null);
  assert.equal(r.shortWindow, true);
});

test("computeRoi: end before start is null", () => {
  assert.equal(computeRoi(input({ startDate: "2026-02-01", endDate: "2026-01-01" })), null);
});

test("computeRoi: non-positive equity is null", () => {
  assert.equal(computeRoi(input({ startEquity: 0 })), null);
  assert.equal(computeRoi(input({ startEquity: -1 })), null);
  assert.equal(computeRoi(input({ endEquity: 0 })), null);
});

test("computeRoi: non-finite equity is null", () => {
  assert.equal(computeRoi(input({ startEquity: Number.NaN })), null);
  assert.equal(computeRoi(input({ endEquity: Number.POSITIVE_INFINITY })), null);
});

test("computeRoi: malformed or impossible dates are null", () => {
  assert.equal(computeRoi(input({ startDate: "2026-7-30" })), null);
  assert.equal(computeRoi(input({ endDate: "" })), null);
  assert.equal(computeRoi(input({ endDate: "2026-02-30" })), null);
});

test("computeRoi: tradingDays must be a non-negative integer", () => {
  assert.equal(computeRoi(input({ tradingDays: -1 })), null);
  assert.equal(computeRoi(input({ tradingDays: 1.5 })), null);
  assert.equal(computeRoi(input({ tradingDays: Number.NaN })), null);
});

test("computeRoi: short window is under 60 trading days, boundary exclusive", () => {
  assert.equal(SHORT_WINDOW_TRADING_DAYS, 60);
  assert.equal(computeRoi(input({ tradingDays: 59 }))?.shortWindow, true);
  assert.equal(computeRoi(input({ tradingDays: 60 }))?.shortWindow, false);
});

test("computeRoi: annualized overflow becomes null while raw stays finite", () => {
  const r = computeRoi(input({
    startEquity: 1,
    endEquity: 1e6,
    startDate: "2026-01-01",
    endDate: "2026-01-02",
    tradingDays: 1,
  }));
  assert.ok(r);
  assert.equal(r.annualizedRoi, null);
  assert.ok(Number.isFinite(r.rawRoi));
});

test("computeRoi: periodLabel has the exact shape", () => {
  const r = computeRoi({
    startEquity: 1017330.61,
    endEquity: 1019040.28,
    startDate: "2026-07-30",
    endDate: "2026-10-27",
    tradingDays: 63,
  });
  assert.ok(r);
  assert.equal(r.periodLabel, "2026-07-30 to 2026-10-27 (89 calendar days, ~63 trading days)");
});

test("countWeekdays: counts Mon-Fri days in (start, end]; same, reversed or invalid dates are 0", () => {
  assert.equal(countWeekdays("2026-07-30", "2026-07-30"), 0);
  assert.equal(countWeekdays("2026-08-03", "2026-07-30"), 0);
  assert.equal(countWeekdays("nope", "2026-08-10"), 0);
  assert.equal(countWeekdays("2026-08-03", "2026-02-30"), 0);
  assert.equal(countWeekdays("2026-07-31", "2026-08-03"), 1); // Fri -> Mon
  assert.equal(countWeekdays("2026-08-01", "2026-08-02"), 0); // Sat -> Sun
  assert.equal(countWeekdays("2026-08-03", "2026-08-10"), 5); // Mon -> Mon
});

test("countWeekdays: dev experiment span (Labor Day 2026-09-07 is counted)", () => {
  assert.equal(countWeekdays("2026-07-30", "2026-10-27"), 63);
  assert.equal(countWeekdays("2026-07-30", "2026-10-22"), 60);
});

const BASELINE = 1017330.61;
const START = HOURLY_BOT_START_DATE;

test("computeDashboardRoi: dev fixture since start (2026-10-26)", () => {
  const out = computeDashboardRoi({
    baselineEquity: BASELINE,
    latest: { date: "2026-10-26", equity: 1019040.28 },
    history: [],
    startDate: START,
    rollingDays: 90,
  });
  assert.equal(START, "2026-07-30");
  assert.equal(ROLLING_WINDOW_DAYS, 90);
  assert.ok(out.sinceStart);
  close(out.sinceStart.rawRoi, 0.0016805, 1e-6);
  close(out.sinceStart.annualizedRoi, 0.0069889, 1e-6);
  assert.equal(out.sinceStart.calendarDays, 88);
  assert.equal(out.sinceStart.tradingDays, 62);
  assert.equal(out.sinceStart.shortWindow, false);
  assert.equal(out.rolling, null);
});

test("computeDashboardRoi: null baseline nulls sinceStart, rolling uses history; null latest nulls both", () => {
  const history = [
    { date: "2026-07-01", equity: 900 },
    { date: "2026-08-03", equity: 1000 },
  ];
  const latest = { date: "2026-11-01", equity: 1100 };
  const a = computeDashboardRoi({ baselineEquity: null, latest, history, startDate: START, rollingDays: 90 });
  assert.equal(a.sinceStart, null);
  assert.ok(a.rolling);
  assert.match(a.rolling.periodLabel, /^2026-08-03 to 2026-11-01 /);
  const b = computeDashboardRoi({
    baselineEquity: BASELINE,
    latest: null,
    history,
    startDate: START,
    rollingDays: 90,
  });
  assert.equal(b.sinceStart, null);
  assert.equal(b.rolling, null);
});

test("computeDashboardRoi: rolling is null with under 90 days of history", () => {
  const out = computeDashboardRoi({
    baselineEquity: BASELINE,
    latest: { date: "2026-10-27", equity: 1019000 },
    history: [{ date: "2026-08-03", equity: 1018000 }],
    startDate: START,
    rollingDays: 90,
  });
  assert.ok(out.sinceStart);
  assert.equal(out.rolling, null);
});

test("computeDashboardRoi: on 2026-10-28 the rolling start is the baseline point", () => {
  const out = computeDashboardRoi({
    baselineEquity: BASELINE,
    latest: { date: "2026-10-28", equity: 1019000 },
    history: [{ date: "2026-08-03", equity: 1018000 }],
    startDate: START,
    rollingDays: 90,
  });
  assert.ok(out.rolling);
  assert.equal(out.rolling.calendarDays, 90);
  assert.match(out.rolling.periodLabel, /^2026-07-30 to 2026-10-28 /);
  close(out.rolling.rawRoi, 1019000 / BASELINE - 1);
});

test("computeDashboardRoi: rolling picks the latest point on or before the target from unsorted history", () => {
  const out = computeDashboardRoi({
    baselineEquity: BASELINE,
    latest: { date: "2026-11-10", equity: 1100 },
    history: [
      { date: "2026-08-14", equity: 1030 }, // after target (2026-08-12)
      { date: "2026-08-12", equity: 1020 }, // exactly on target
      { date: "2026-08-05", equity: 1010 },
      { date: "2026-08-11", equity: 1015 },
    ],
    startDate: START,
    rollingDays: 90,
  });
  assert.ok(out.rolling);
  assert.match(out.rolling.periodLabel, /^2026-08-12 to 2026-11-10 /);
  close(out.rolling.rawRoi, 1100 / 1020 - 1);
});

test("computeDashboardRoi: null or zero equity points are skipped for the previous valid point", () => {
  for (const bad of [null, 0]) {
    const out = computeDashboardRoi({
      baselineEquity: BASELINE,
      latest: { date: "2026-12-06", equity: 1100 },
      history: [
        { date: "2026-09-04", equity: 1010 },
        { date: "2026-09-07", equity: bad },
      ],
      startDate: START,
      rollingDays: 90,
    });
    assert.ok(out.rolling);
    // target = 2026-09-07; the bad point is dropped, so 2026-09-04 is used.
    assert.match(out.rolling.periodLabel, /^2026-09-04 to 2026-12-06 /);
  }
});

test("computeDashboardRoi: points dated before startDate are never a start", () => {
  const out = computeDashboardRoi({
    baselineEquity: null,
    latest: { date: "2026-11-30", equity: 1100 },
    history: [{ date: "2026-07-01", equity: 500 }, { date: "2026-07-30", equity: 600 }],
    startDate: START,
    rollingDays: 90,
  });
  assert.equal(out.rolling, null);
});

test("computeDashboardRoi: a target inside a gap uses the point before the gap and says so", () => {
  const out = computeDashboardRoi({
    baselineEquity: BASELINE,
    latest: { date: "2026-12-01", equity: 1100 }, // target 2026-09-02
    history: [
      { date: "2026-08-14", equity: 1010 },
      { date: "2026-09-10", equity: 1020 },
    ],
    startDate: START,
    rollingDays: 90,
  });
  assert.ok(out.rolling);
  assert.match(out.rolling.periodLabel, /^2026-08-14 to 2026-12-01 /);
  assert.ok(out.rolling.calendarDays > 90);
});

test("formatSignedPct: positive, negative and zero", () => {
  assert.equal(formatSignedPct(0.00168), "+0.17%");
  assert.equal(formatSignedPct(-0.1), "-10.00%");
  assert.equal(formatSignedPct(0), "+0.00%");
});
