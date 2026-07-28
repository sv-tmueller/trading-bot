// Weekly-review aggregator (#481, batch #478 Package C, spec
// docs/superpowers/specs/2026-07-27-hourly-bot-design.md §11/§14 finding
// 10). A standalone, read-only, operator-run script over `hourly_scans` +
// `trades` rendering `docs/trading-journal/YYYY-Www.md` -- per-detector
// firing rates, entries/exits with R-multiples, gate-skip distribution,
// equity trajectory vs the -15% floor, and the PROPOSAL_RULE trigger
// statistics. Not a cron, not an Edge Function.
//
// D1: TypeScript under scripts/, run via `deno run`, following
// scripts/backfill_equity_snapshots.ts's shape. D2: PostgREST via
// getServiceClient() + a gitignored .env.weekly. D3: DB-only equity
// sourcing -- this file MUST NOT import _shared/alpaca.ts or read any
// ALPACA_* env var. Allowed _shared imports: db.ts, supabase_client.ts,
// num.ts only (no Edge Function modules, no backtest/strategy imports).
import type { SupabaseClient } from "@supabase/supabase-js";
import { getServiceClient } from "../supabase/functions/_shared/supabase_client.ts";
import {
  type AuditLogRow,
  coerceHourlyScanRow,
  coerceTradeRow,
  type HourlyScanRow,
  type TradeRow,
} from "../supabase/functions/_shared/db.ts";
import { requireNumber } from "../supabase/functions/_shared/num.ts";

// ---------------------------------------------------------------------------
// T1 -- week-window math (pure, D4: every render-layer read is upper-bounded
// by the week window's end; the clock is only ever read in main()).
// ---------------------------------------------------------------------------

const WEEK_LABEL_RE = /^(\d{4})-W(\d{2})$/;

export interface WeekId {
  isoYear: number;
  isoWeek: number;
}

export class WeekLabelError extends Error {
  override name = "WeekLabelError";
}

/** Parses a `YYYY-Www` label. Throws WeekLabelError on any malformed input. */
export function parseWeekLabel(label: string): WeekId {
  const m = WEEK_LABEL_RE.exec(label);
  if (!m) {
    throw new WeekLabelError(`malformed week label, expected YYYY-Www: ${JSON.stringify(label)}`);
  }
  const isoYear = Number(m[1]);
  const isoWeek = Number(m[2]);
  if (isoWeek < 1 || isoWeek > 53) {
    throw new WeekLabelError(`malformed week label, week out of range 01-53: ${JSON.stringify(label)}`);
  }
  return { isoYear, isoWeek };
}

function formatWeekLabel(week: WeekId): string {
  return `${week.isoYear}-W${String(week.isoWeek).padStart(2, "0")}`;
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** ISO week 1's Monday is the Monday of the week containing 4 Jan (ISO 8601 rule). */
function isoWeekMondayYmd(week: WeekId): string {
  const jan4 = new Date(Date.UTC(week.isoYear, 0, 4));
  const jan4Dow = (jan4.getUTCDay() + 6) % 7; // Mon=0 .. Sun=6
  const week1Monday = jan4.getTime() - jan4Dow * MS_PER_DAY;
  const monday = new Date(week1Monday + (week.isoWeek - 1) * 7 * MS_PER_DAY);
  return monday.toISOString().slice(0, 10);
}

function addDaysYmd(ymd: string, days: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

const SHORT_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function formatDayMonth(ymd: string): string {
  const [, m, d] = ymd.split("-").map(Number);
  return `${d} ${SHORT_MONTHS[m - 1]}`;
}

// America/New_York's UTC offset (in minutes, positive = ET behind UTC) for a
// given calendar date. Probed at noon UTC (same technique
// supabase/functions/hourly-check/logic.ts's etOffsetMinutes uses) --
// reimplemented locally rather than imported, since hourly-check is an Edge
// Function module and this script's allowed _shared surface is db.ts /
// supabase_client.ts / num.ts only.
function etOffsetMinutes(dateYmd: string): number {
  const probe = new Date(`${dateYmd}T12:00:00Z`);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    hour12: false,
  }).formatToParts(probe);
  const hourPart = parts.find((p) => p.type === "hour")?.value ?? "12";
  const localHour = Number(hourPart) % 24;
  return (12 - localHour) * 60;
}

/** Converts an exchange-local HH:MM on `dateYmd` (ET) to a UTC ISO instant. */
function etHHMMToUtcIso(dateYmd: string, hhmm: string): string {
  const offsetMin = etOffsetMinutes(dateYmd);
  const [hh, mm] = hhmm.split(":").map(Number);
  const base = new Date(`${dateYmd}T00:00:00Z`).getTime();
  return new Date(base + (hh * 60 + mm + offsetMin) * 60 * 1000).toISOString();
}

export interface WeekWindow {
  /** Inclusive lower bound, UTC ISO instant for Monday 00:00 ET. */
  startIso: string;
  /** Exclusive upper bound, UTC ISO instant for Saturday 00:00 ET. */
  endIsoExclusive: string;
  /** Human title, e.g. "Week 2026-W31 (Mon 27 Jul -- Fri 31 Jul 2026)". */
  title: string;
}

/**
 * The ISO week's [Monday 00:00 ET, Saturday 00:00 ET) window, converted to
 * UTC (D4). The Saturday exclusive bound covers the full Friday ET calendar
 * day regardless of DST, without ever admitting the following week's data.
 */
export function weekWindowUtc(isoYear: number, isoWeek: number): WeekWindow {
  const week: WeekId = { isoYear, isoWeek };
  const mondayYmd = isoWeekMondayYmd(week);
  const fridayYmd = addDaysYmd(mondayYmd, 4);
  const saturdayYmd = addDaysYmd(mondayYmd, 5);
  const startIso = etHHMMToUtcIso(mondayYmd, "00:00");
  const endIsoExclusive = etHHMMToUtcIso(saturdayYmd, "00:00");
  const fridayYear = Number(fridayYmd.slice(0, 4));
  const title = `Week ${formatWeekLabel(week)} (Mon ${formatDayMonth(mondayYmd)} -- ` +
    `Fri ${formatDayMonth(fridayYmd)} ${fridayYear})`;
  return { startIso, endIsoExclusive, title };
}

/** The ISO week of a plain UTC-calendar date (used only to derive `previousCompletedWeek`). */
function isoWeekOfUtcDate(d: Date): WeekId {
  const date = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const isoWeek = Math.ceil(((date.getTime() - yearStart.getTime()) / MS_PER_DAY + 1) / 7);
  return { isoYear: date.getUTCFullYear(), isoWeek };
}

/**
 * The default `--week` target: the ISO week immediately before the one
 * containing `now`, resolved here (main()'s only clock read) so the render
 * layer below never sees a clock (D4). Subtracting a flat 7 calendar days
 * from `now`'s UTC date and taking *that* date's ISO week is exact because
 * ISO weeks are 7-day-aligned -- it also handles ISO-year rollovers for free.
 */
export function previousCompletedWeek(now: Date): WeekId {
  const sevenDaysAgo = new Date(now.getTime() - 7 * MS_PER_DAY);
  return isoWeekOfUtcDate(sevenDaysAgo);
}
