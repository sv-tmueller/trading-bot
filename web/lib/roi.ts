// Pure ROI / annualized-ROI math for the dashboard (#674). No imports on
// purpose: no `server-only` (it throws under plain Node, which runs
// roi.test.ts via `npm test`), no fs, no network. Only TypeScript syntax Node
// can strip (no enums or namespaces). The caller (web/app/page.tsx) supplies
// every equity figure it already read; nothing here reads or writes anything.

// Dev paper experiment start. The baseline (bot_config
// hourly_experiment_start_equity) was taken on 2026-07-29 before the first
// hourly session, i.e. it is the equity at the start of 2026-07-30. A prod
// dashboard needs its own start date once prod exists.
export const HOURLY_BOT_START_DATE = "2026-07-30";
export const ROLLING_WINDOW_DAYS = 90; // calendar days
export const SHORT_WINDOW_TRADING_DAYS = 60;
export const DAYS_PER_YEAR = 365;

export interface EquityPoint {
  date: string; // YYYY-MM-DD (UTC)
  equity: number | null;
}

export interface RoiInput {
  startEquity: number;
  endEquity: number;
  startDate: string;
  endDate: string;
  tradingDays: number;
}

export interface RoiResult {
  rawRoi: number; // end / start - 1
  annualizedRoi: number | null; // (end / start) ^ (365 / calendarDays) - 1
  calendarDays: number;
  tradingDays: number;
  periodLabel: string; // "2026-07-30 to 2026-10-27 (89 calendar days, ~63 trading days)"
  shortWindow: boolean; // tradingDays < SHORT_WINDOW_TRADING_DAYS
}

const MS_PER_DAY = 86_400_000;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

// YYYY-MM-DD -> UTC midnight in ms, or null. Checked by round-trip so
// impossible dates such as 2026-02-30 are rejected rather than rolled over.
function parseUtcDate(date: string): number | null {
  if (typeof date !== "string" || !DATE_RE.test(date)) return null;
  const ms = Date.parse(`${date}T00:00:00Z`);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms).toISOString().slice(0, 10) === date ? ms : null;
}

function isValidEquity(v: number | null): v is number {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

export function computeRoi(input: RoiInput): RoiResult | null {
  const { startEquity, endEquity, startDate, endDate, tradingDays } = input;
  if (!isValidEquity(startEquity) || !isValidEquity(endEquity)) return null;
  const startMs = parseUtcDate(startDate);
  const endMs = parseUtcDate(endDate);
  if (startMs === null || endMs === null || endMs < startMs) return null;
  if (!Number.isInteger(tradingDays) || tradingDays < 0) return null;

  const calendarDays = Math.round((endMs - startMs) / MS_PER_DAY);
  const ratio = endEquity / startEquity;
  let annualizedRoi: number | null = null;
  if (calendarDays > 0) {
    const a = Math.pow(ratio, DAYS_PER_YEAR / calendarDays) - 1;
    annualizedRoi = Number.isFinite(a) ? a : null;
  }
  return {
    rawRoi: ratio - 1,
    annualizedRoi,
    calendarDays,
    tradingDays,
    periodLabel:
      `${startDate} to ${endDate} (${calendarDays} calendar days, ~${tradingDays} trading days)`,
    shortWindow: tradingDays < SHORT_WINDOW_TRADING_DAYS,
  };
}

// Mon-Fri days d with start < d <= end. Exchange holidays are not excluded,
// hence the "~" in the label. 0 when end <= start or a date is invalid.
export function countWeekdays(startDate: string, endDate: string): number {
  const startMs = parseUtcDate(startDate);
  const endMs = parseUtcDate(endDate);
  if (startMs === null || endMs === null || endMs <= startMs) return 0;
  let count = 0;
  for (let ms = startMs + MS_PER_DAY; ms <= endMs; ms += MS_PER_DAY) {
    const dow = new Date(ms).getUTCDay();
    if (dow !== 0 && dow !== 6) count++;
  }
  return count;
}

function roiBetween(
  start: { date: string; equity: number },
  end: { date: string; equity: number },
): RoiResult | null {
  return computeRoi({
    startEquity: start.equity,
    endEquity: end.equity,
    startDate: start.date,
    endDate: end.date,
    tradingDays: countWeekdays(start.date, end.date),
  });
}

export function computeDashboardRoi(input: {
  baselineEquity: number | null;
  latest: EquityPoint | null;
  history: EquityPoint[];
  startDate: string;
  rollingDays: number;
}): { sinceStart: RoiResult | null; rolling: RoiResult | null } {
  const { baselineEquity, latest, history, startDate, rollingDays } = input;
  if (latest === null || !isValidEquity(latest.equity)) {
    return { sinceStart: null, rolling: null };
  }
  const end = { date: latest.date, equity: latest.equity };

  const sinceStart = isValidEquity(baselineEquity)
    ? roiBetween({ date: startDate, equity: baselineEquity }, end)
    : null;

  // Rolling start: the latest candidate on or before (latest date - rollingDays),
  // the same rule as closestOnOrBefore in supabase/functions/status/logic.ts.
  // Candidates are the baseline point (dated startDate) plus ledger points
  // dated after startDate, so nothing earlier than the experiment is used.
  // A gap in the ledger therefore yields a longer, correctly labelled window,
  // never a wrong number.
  const endMs = parseUtcDate(end.date);
  if (endMs === null) return { sinceStart, rolling: null };
  const target = new Date(endMs - rollingDays * MS_PER_DAY).toISOString().slice(0, 10);

  const candidates: { date: string; equity: number }[] = [];
  if (isValidEquity(baselineEquity)) candidates.push({ date: startDate, equity: baselineEquity });
  for (const p of history) {
    if (p.date > startDate && parseUtcDate(p.date) !== null && isValidEquity(p.equity)) {
      candidates.push({ date: p.date, equity: p.equity });
    }
  }
  candidates.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  let start: { date: string; equity: number } | null = null;
  for (const c of candidates) {
    if (c.date <= target) start = c;
  }
  const rolling = start === null ? null : roiBetween(start, end);
  return { sinceStart, rolling };
}

// "+0.17%", "-10.00%", "+0.00%". Input is a fraction (0.0017 -> "+0.17%").
export function formatSignedPct(fraction: number): string {
  const text = (fraction * 100).toFixed(2);
  return fraction >= 0 ? `+${text}%` : `${text}%`;
}
