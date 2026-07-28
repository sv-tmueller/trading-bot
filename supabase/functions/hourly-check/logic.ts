// hourly-check: the hourly-candlestick long/short bot's pipeline (#475,
// spec docs/superpowers/specs/2026-07-27-hourly-bot-design.md). Follows the
// daily-check/kill-switch shape: `runHourlyCheck(deps)` opens the audit row
// first, closes every path via a single `finish(outcome, notes)`, and a
// top-level catch maps any thrown error to `error:${err.name}`.
//
// Gate ladder (spec §4-§9, sub-plan T9): a fixed pipeline order, one
// deterministic outcome per run. See the sub-plan's 20-row table for the
// full spec; this file implements it in that exact order.
import { AlpacaError, type ClosedOrderFill, type Fill } from "../_shared/alpaca.ts";
import { CONTEXT_SMA_WINDOW } from "../_shared/candlestick.ts";
import type { HourlyConfig } from "../_shared/config.ts";
import type { HourlyScanRow, TradeRow } from "../_shared/db.ts";
import { decideHourly, type HourlyAction } from "../_shared/hourly_signal.ts";
import type { CalendarSession, HourlyBar } from "../_shared/marketdata.ts";
import { DataError, requireNumber } from "../_shared/num.ts";

const HOUR_MS = 60 * 60 * 1000;

// §11's hard floor: -15% account equity from the paper experiment's start.
// Not a config setting (not in §10's table) -- a fixed default the operator
// owns via the spec's own merge, same as the 4-week/30-trade checkpoint.
const EQUITY_FLOOR_PCT = 0.15;

// Every reason this package's trades rows can carry. hourly_kill_switch is
// read (as an exit event, for cooldown/day-cap bookkeeping) but never
// written here -- the retrofit package (#474) owns writing it.
const ENTRY_REASONS: string[] = ["hourly_long_entry", "hourly_short_entry"];
const EXIT_REASONS: string[] = [
  "hourly_bracket_exit",
  "hourly_session_close_exit",
  "hourly_kill_switch",
];

export interface HourlyCheckDeps {
  config: HourlyConfig;
  now: () => Date;
  marketdata: {
    getHourlyBars: (symbol: string, opts: { count: number }) => Promise<HourlyBar[]>;
    getCalendarSessions: (start: string, end: string) => Promise<CalendarSession[]>;
    getLatestTradePrice: (symbol: string) => Promise<number>;
  };
  alpaca: {
    getClock: () => Promise<{ isOpen: boolean; nextClose: number }>;
    getPosition: (symbol: string) => Promise<number>;
    assertPaperAccount: () => Promise<{ equity: number }>;
    placeBracketOrder: (args: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      takeProfitPrice: number;
      stopLossPrice: number;
    }) => Promise<Fill>;
    placeOcoExitPair: (args: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      takeProfitPrice: number;
      stopLossPrice: number;
    }) => Promise<{ orderId: string }>;
    placeMarketOrder: (
      args: { symbol: string; side: "BUY" | "SELL"; qty: number },
    ) => Promise<Fill>;
    cancelOrder: (orderId: string) => Promise<void>;
    getAssetShortability: (
      symbol: string,
    ) => Promise<{ shortable: boolean; easyToBorrow: boolean }>;
    listFilledOrdersSince: (symbol: string, sinceIso: string) => Promise<ClosedOrderFill[]>;
    listOpenOrderIds: (symbol: string) => Promise<string[]>;
  };
  db: {
    getConfig: (key: string) => Promise<string | null>;
    setConfig: (key: string, value: string) => Promise<void>;
    getTradesSince: (sinceIso: string) => Promise<TradeRow[]>;
    upsertHourlyScan: (p: {
      symbol: string;
      barTs: string;
      decision: "LONG" | "SHORT" | "SKIP";
      skipReason: string | null;
      detectorsFired: string[];
      contextMode: string;
      entryRefPrice: number | null;
      stopPrice: number | null;
      targetPrice: number | null;
      riskPerShare: number | null;
      equityUsd: number;
      qty: number;
      entryOrderId: string | null;
    }) => Promise<void>;
    getHourlyScanByEntryOrderId: (symbol: string, orderId: string) => Promise<HourlyScanRow | null>;
    claimBar: (scriptName: string, barTs: string) => Promise<boolean>;
    insertTrade: (p: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      fillPrice: number;
      fillTime: string;
      brokerOrderId: string;
      reason:
        | "hourly_long_entry"
        | "hourly_short_entry"
        | "hourly_bracket_exit"
        | "hourly_session_close_exit";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (
      p: { id: number; finishedAt: string; outcome: string; notes?: string | null },
    ) => Promise<void>;
  };
  notifications: {
    notifyBrokerError: (p: { context: string; errorMsg: string }) => Promise<void>;
  };
}

// ---------------------------------------------------------------------------
// Pure helpers (sub-plan T9/T10): partial-bar predicate, ET<->UTC conversion,
// bracket geometry, sizing. No I/O, directly unit-testable.
// ---------------------------------------------------------------------------

/**
 * UTC-minutes-past-midnight offset of America/New_York on `dateStr`
 * (YYYY-MM-DD), computed via Intl's built-in tz database rather than a
 * hand-rolled DST table. Positive (e.g. 240 for EDT, 300 for EST) = ET is
 * behind UTC by that many minutes.
 */
export function etOffsetMinutes(dateStr: string): number {
  const probe = new Date(`${dateStr}T12:00:00Z`);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    hour12: false,
  }).formatToParts(probe);
  const hourPart = parts.find((p) => p.type === "hour")?.value ?? "12";
  // Intl can render midnight as "24" under hour12:false; normalize to 0-23.
  const localHour = Number(hourPart) % 24;
  return (12 - localHour) * 60;
}

/** Converts an exchange-local HH:MM on `dateStr` (ET) to a UTC epoch-ms instant. */
export function etHHMMToUtcMs(dateStr: string, hhmm: string): number {
  const offsetMin = etOffsetMinutes(dateStr);
  const [hh, mm] = hhmm.split(":").map(Number);
  const base = new Date(`${dateStr}T00:00:00Z`).getTime();
  return base + (hh * 60 + mm + offsetMin) * 60 * 1000;
}

/**
 * Partial session-edge bar predicate (spec §4): a bar is partial if its
 * start is not a clean top-of-hour boundary, OR its [start, start+1h) span
 * is not fully inside the session's [open, close) bounds. Over-exclusion is
 * the fail-safe direction.
 */
export function isBarPartial(
  bar: { timestamp: string },
  session: { date: string; open: string; close: string },
): boolean {
  const startMs = new Date(bar.timestamp).getTime();
  const endMs = startMs + HOUR_MS;
  const isTopOfHour = startMs % HOUR_MS === 0;
  const sessionOpenMs = etHHMMToUtcMs(session.date, session.open);
  const sessionCloseMs = etHHMMToUtcMs(session.date, session.close);
  const fullyInside = startMs >= sessionOpenMs && endMs <= sessionCloseMs;
  return !isTopOfHour || !fullyInside;
}

export interface BracketGeometry {
  stopPrice: number;
  targetPrice: number;
}

/**
 * Bracket geometry (spec §7): stop is the signal bar's own extreme plus a
 * buffer (long: low - buffer; short: high + buffer); target is
 * entry +/- R * stopDistance, R frozen at HOURLY_BRACKET_R_MULTIPLE.
 */
export function computeBracketGeometry(
  action: "LONG" | "SHORT",
  bar: { high: number; low: number },
  entryRef: number,
  cfg: { hourlyStopBufferPct: number; hourlyBracketRMultiple: number },
): BracketGeometry {
  const barRange = bar.high - bar.low;
  const buffer = cfg.hourlyStopBufferPct * barRange;
  const stopPrice = action === "LONG" ? bar.low - buffer : bar.high + buffer;
  const stopDistance = Math.abs(entryRef - stopPrice);
  const targetPrice = action === "LONG"
    ? entryRef + cfg.hourlyBracketRMultiple * stopDistance
    : entryRef - cfg.hourlyBracketRMultiple * stopDistance;
  return { stopPrice, targetPrice };
}

export interface SizingResult {
  /** false = entryRef is on the wrong side of stopPrice, or too close (spec §6 finding 12). */
  valid: boolean;
  stopDistance: number;
  qtyRisk: number;
  qtyCap: number;
  qty: number;
}

/** Sizing (spec §6): stop first, then quantity. Whole shares only. */
export function computeSizing(
  action: "LONG" | "SHORT",
  entryRef: number,
  stopPrice: number,
  equity: number,
  cfg: {
    sizingRiskPct: number;
    sizingNotionalCapPct: number;
    hourlyMinStopDistance: number;
  },
): SizingResult {
  const stopDistance = Math.abs(entryRef - stopPrice);
  // Signed distance on the *correct* side: long wants entryRef > stopPrice,
  // short wants entryRef < stopPrice. A negative value here means inverted
  // geometry; either failure mode (inverted or too-close) is "not usable".
  const signedDistance = action === "LONG" ? entryRef - stopPrice : stopPrice - entryRef;
  if (signedDistance < cfg.hourlyMinStopDistance) {
    return { valid: false, stopDistance, qtyRisk: 0, qtyCap: 0, qty: 0 };
  }
  const riskBudget = cfg.sizingRiskPct * equity;
  const qtyRisk = Math.floor(riskBudget / stopDistance);
  const qtyCap = Math.floor((cfg.sizingNotionalCapPct * equity) / entryRef);
  const qty = Math.min(qtyRisk, qtyCap);
  return { valid: true, stopDistance, qtyRisk, qtyCap, qty };
}

// ---------------------------------------------------------------------------
// Reconciliation contract (spec §7, sub-plan T11)
// ---------------------------------------------------------------------------

interface ReconcileResult {
  /** Set -> the caller returns this outcome immediately (terminal). */
  terminalOutcome?: string;
  /** Set -> supersedes whatever outcome the rest of the run would report. */
  supersede?: string;
  notes?: string;
}

async function reconcile(
  deps: HourlyCheckDeps,
  symbol: string,
  isFlattenScan: boolean,
): Promise<ReconcileResult> {
  const { alpaca, db, notifications } = deps;

  // Bounded lookback: a position can never span more than a few sessions
  // given the flatten-scan rule closes everything by session end.
  const lookbackIso = new Date(deps.now().getTime() - 5 * 24 * HOUR_MS).toISOString();
  const hourlyTrades = (await db.getTradesSince(lookbackIso)).filter(
    (t) =>
      t.symbol === symbol && (ENTRY_REASONS.includes(t.reason) || EXIT_REASONS.includes(t.reason)),
  );
  const byTimeDesc = [...hourlyTrades].sort((a, b) => b.fill_time.localeCompare(a.fill_time));
  const lastEntry = byTimeDesc.find((t) => ENTRY_REASONS.includes(t.reason)) ?? null;
  const lastExit = byTimeDesc.find((t) => EXIT_REASONS.includes(t.reason)) ?? null;
  const entryConsideredOpen = lastEntry !== null &&
    (lastExit === null || lastExit.fill_time < lastEntry.fill_time);

  // 1. Discover newly-filled exit legs since the last journaled exit, so the
  // position check below sees post-fill broker truth.
  if (entryConsideredOpen && lastEntry) {
    const discovered = await alpaca.listFilledOrdersSince(symbol, lastEntry.fill_time);
    for (const f of discovered) {
      if (f.orderId === lastEntry.broker_order_id) continue; // the entry itself
      if (hourlyTrades.some((t) => t.broker_order_id === f.orderId)) continue; // already recorded
      await db.insertTrade({
        symbol,
        side: f.side,
        qty: f.qty,
        fillPrice: f.fillPrice,
        fillTime: f.fillTime,
        brokerOrderId: f.orderId,
        reason: "hourly_bracket_exit",
      });
    }
  }

  // 2. Position-without-legs rule (finding 3) -- runs off broker truth
  // regardless of our own bookkeeping.
  let positionQty = await alpaca.getPosition(symbol);
  if (positionQty !== 0) {
    const openIds = await alpaca.listOpenOrderIds(symbol);
    if (openIds.length === 0) {
      const provenance = lastEntry
        ? await db.getHourlyScanByEntryOrderId(symbol, lastEntry.broker_order_id)
        : null;
      let relegged = false;
      if (provenance?.stop_price != null && provenance?.target_price != null) {
        try {
          await alpaca.placeOcoExitPair({
            symbol,
            side: positionQty > 0 ? "SELL" : "BUY",
            qty: Math.abs(positionQty),
            takeProfitPrice: provenance.target_price,
            stopLossPrice: provenance.stop_price,
          });
          relegged = true;
        } catch (_e) {
          // fall through to the fail-toward-protection flatten below
        }
      }
      if (relegged) {
        return { supersede: "success:legs_replaced", notes: `re-legged qty=${positionQty}` };
      }
      // Fail toward protection: cancel any remnants (verified), then market-close.
      for (const id of await alpaca.listOpenOrderIds(symbol)) {
        await alpaca.cancelOrder(id);
      }
      const closeSide = positionQty > 0 ? "SELL" : "BUY";
      const fill = await alpaca.placeMarketOrder({
        symbol,
        side: closeSide,
        qty: Math.abs(positionQty),
      });
      await db.insertTrade({
        symbol,
        side: closeSide,
        qty: fill.qty,
        fillPrice: fill.fillPrice,
        fillTime: fill.fillTime,
        brokerOrderId: fill.orderId,
        reason: "hourly_bracket_exit",
      });
      await notifications.notifyBrokerError({
        context: "hourly-check:naked_position_flattened",
        errorMsg:
          `position qty=${positionQty} had no resting legs and no re-leggable provenance; flattened`,
      });
      return { terminalOutcome: "error:naked_position_flattened" };
    }
  }

  // 3. Flatten scan: cancel resting legs (verified) then market-close,
  // whether or not the naked-position branch already acted above.
  if (isFlattenScan) {
    positionQty = await alpaca.getPosition(symbol);
    if (positionQty !== 0) {
      for (const id of await alpaca.listOpenOrderIds(symbol)) {
        await alpaca.cancelOrder(id);
      }
      const closeSide = positionQty > 0 ? "SELL" : "BUY";
      const fill = await alpaca.placeMarketOrder({
        symbol,
        side: closeSide,
        qty: Math.abs(positionQty),
      });
      await db.insertTrade({
        symbol,
        side: closeSide,
        qty: fill.qty,
        fillPrice: fill.fillPrice,
        fillTime: fill.fillTime,
        brokerOrderId: fill.orderId,
        reason: "hourly_session_close_exit",
      });
    }
  }

  return {};
}

// ---------------------------------------------------------------------------
// Main pipeline
// ---------------------------------------------------------------------------

export async function runHourlyCheck(deps: HourlyCheckDeps): Promise<string> {
  const { config, db, alpaca, marketdata, notifications } = deps;
  const symbol = config.hourlyBotTicker;
  const iso = (d: Date) => d.toISOString();
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const startedAt = iso(deps.now());
  const auditId = await db.insertAuditLog({ scriptName: "hourly-check", startedAt });

  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });

  try {
    // 1. Operational pause (daily-check precedent).
    const paused = (await db.getConfig("paused"))?.toLowerCase() === "true";
    if (paused) {
      await finish("skipped:trading_paused");
      return "skipped:trading_paused";
    }

    // 2. Layer-B paper assert, pipeline start; equity read piggybacks.
    const { equity: equityAtStart } = await alpaca.assertPaperAccount();

    // 3. Market-open gate + flatten-scan detection.
    const clock = await alpaca.getClock();
    if (!clock.isOpen) {
      await finish("skipped:market_closed");
      return "skipped:market_closed";
    }
    const nowMs = deps.now().getTime();
    const isFlattenScan = clock.nextClose - nowMs <= HOUR_MS;

    // 4-5. Reconciliation contract + flatten-scan close-out (T11).
    const recon = await reconcile(deps, symbol, isFlattenScan);
    if (recon.terminalOutcome) {
      await finish(recon.terminalOutcome, recon.notes);
      return recon.terminalOutcome;
    }
    const supersede = recon.supersede ?? null;

    // Every outcome from here on is routed through `done()` so a
    // superseding reconciliation outcome (success:legs_replaced) always
    // wins over the run's ordinary outcome, per spec §7 finding 3.
    const done = async (outcome: string, notes?: string): Promise<string> => {
      const actual = supersede ?? outcome;
      await finish(actual, notes);
      return actual;
    };

    // 6. -15% equity floor (placed after 4-5 so protection duties always
    // run first). Missing baseline is a hard error (derived decision C2) --
    // never a silently inert floor.
    const baselineRaw = await db.getConfig("hourly_experiment_start_equity");
    if (baselineRaw === null || baselineRaw.trim() === "") {
      throw new DataError(
        "bot_config.hourly_experiment_start_equity is not set -- required before any scan " +
          "can evaluate the -15% equity floor (spec §11)",
      );
    }
    const baseline = requireNumber(baselineRaw, "hourly_experiment_start_equity");
    if (equityAtStart <= baseline * (1 - EQUITY_FLOOR_PCT)) {
      await db.setConfig("paused", "true");
      return await done("success:auto_paused", `equity=${equityAtStart} baseline=${baseline}`);
    }

    // 7. Bars: completed-only filter, partial-bar exclusion (before
    // staleness), then the staleness guard -- fixed precedence (spec §4).
    const fetchCount = config.hourlyContextMode !== "none" ? CONTEXT_SMA_WINDOW + 30 : 10;
    const barsRaw = await marketdata.getHourlyBars(symbol, { count: fetchCount });
    const completed = barsRaw.filter((b) => new Date(b.timestamp).getTime() + HOUR_MS <= nowMs);
    if (completed.length === 0) {
      return await done("skipped:stale_data", "no completed bars returned");
    }
    const candidate = completed[completed.length - 1];
    const today = ymd(deps.now());
    const sessions = await marketdata.getCalendarSessions(today, today);
    const session = sessions.find((s) => s.date === today);
    if (!session) {
      throw new DataError(`no calendar session found for ${today} (market reported open)`);
    }
    if (isBarPartial(candidate, session)) {
      return await done("skipped:partial_bar", `candidate bar ${candidate.timestamp}`);
    }
    const barEndMs = new Date(candidate.timestamp).getTime() + HOUR_MS;
    const staleMinutes = (nowMs - barEndMs) / 60000;
    if (staleMinutes > config.hourlyStalenessToleranceMin) {
      return await done(
        "skipped:stale_data",
        `bar end=${new Date(barEndMs).toISOString()} stale by ${staleMinutes.toFixed(1)}min`,
      );
    }
    const barTs = candidate.timestamp;

    // 8. decideHourly.
    const decision = decideHourly(completed, { contextMode: config.hourlyContextMode });

    // hourly_scans row policy (disclosed): `decision`/`skipReason` reflect
    // the FINAL post-gating result (a gated LONG/SHORT is journaled as
    // SKIP + the gate's reason); `detectorsFired` always preserves the raw
    // signal regardless of gating, per §4's firing-rate requirement.
    const journal = (p: {
      finalDecision: "LONG" | "SHORT" | "SKIP";
      finalSkipReason: string | null;
      qty: number;
      entryRefPrice: number | null;
      stopPrice: number | null;
      targetPrice: number | null;
      riskPerShare: number | null;
      entryOrderId: string | null;
    }) =>
      db.upsertHourlyScan({
        symbol,
        barTs,
        decision: p.finalDecision,
        skipReason: p.finalSkipReason,
        detectorsFired: decision.detectorsFired,
        contextMode: config.hourlyContextMode,
        entryRefPrice: p.entryRefPrice,
        stopPrice: p.stopPrice,
        targetPrice: p.targetPrice,
        riskPerShare: p.riskPerShare,
        equityUsd: equityAtStart,
        qty: p.qty,
        entryOrderId: p.entryOrderId,
      });

    // A gate that skips with no geometry ever computed (steps 9-16).
    const gateSkip = async (reason: string): Promise<string> => {
      await journal({
        finalDecision: "SKIP",
        finalSkipReason: reason,
        qty: 0,
        entryRefPrice: null,
        stopPrice: null,
        targetPrice: null,
        riskPerShare: null,
        entryOrderId: null,
      });
      return await done(`skipped:${reason}`);
    };

    const action: HourlyAction = decision.action;

    // 9. Flatten-scan entry downgrade -- before the kill-switch gate (§5's
    // atomic clear+enter must never fire on a scan that cannot enter).
    if (isFlattenScan && action !== "SKIP") {
      return await gateSkip("session_close_flatten_only");
    }

    // 10. Kill-switch flag gate -- runs for every decision (including SKIP)
    // once the flag is active; only a decision on the opposite side from
    // hourly_kill_switch_side clears the flag and is allowed through.
    const flagActive = (await db.getConfig("hourly_kill_switch_active"))?.toLowerCase() === "true";
    if (flagActive) {
      const side = await db.getConfig("hourly_kill_switch_side");
      if (action === "SKIP" || action === side) {
        return await gateSkip("kill_switch_active");
      }
      await db.setConfig("hourly_kill_switch_active", "false");
      await db.setConfig("hourly_kill_switch_side", "");
      await db.setConfig("hourly_kill_switch_fired_at", "");
    }

    // 11. SKIP decisions (flag not active, or the flag gate above didn't apply).
    if (action === "SKIP") {
      await journal({
        finalDecision: "SKIP",
        finalSkipReason: decision.reason,
        qty: 0,
        entryRefPrice: null,
        stopPrice: null,
        targetPrice: null,
        riskPerShare: null,
        entryOrderId: null,
      });
      if (decision.reason === "signal_conflict") {
        return await done("skipped:signal_conflict");
      }
      return await done("success:no_action");
    }

    // 12. Position-open check, broker-sourced (any nonzero qty blocks).
    const positionQty = await alpaca.getPosition(symbol);
    if (positionQty !== 0) {
      return await gateSkip("position_open");
    }

    // 13. Cooldown: signal bar start must be strictly after the last
    // hourly_* exit's fill_time (stateless recompute from trades).
    const lookbackIso = new Date(deps.now().getTime() - 5 * 24 * HOUR_MS).toISOString();
    const recentTrades = (await db.getTradesSince(lookbackIso)).filter((t) => t.symbol === symbol);
    const lastExitRow = recentTrades
      .filter((t) => EXIT_REASONS.includes(t.reason))
      .sort((a, b) => b.fill_time.localeCompare(a.fill_time))[0];
    const barStartMs = new Date(barTs).getTime();
    if (lastExitRow && barStartMs <= new Date(lastExitRow.fill_time).getTime()) {
      return await gateSkip("cooldown");
    }

    // 14. Day cap: today's entry count for the symbol.
    const entriesToday = recentTrades.filter(
      (t) => ENTRY_REASONS.includes(t.reason) && t.fill_time.slice(0, 10) === today,
    ).length;
    if (entriesToday >= config.hourlyMaxEntriesPerDay) {
      return await gateSkip("max_entries_reached");
    }

    // 15-16. SHORT-only gates.
    if (action === "SHORT") {
      if (!config.hourlyShortsEnabled) {
        return await gateSkip("shorts_disabled");
      }
      const { shortable } = await alpaca.getAssetShortability(symbol);
      if (!shortable) {
        return await gateSkip("not_shortable");
      }
    }

    // 17. Geometry guard, then 18. sizing.
    const entryRef = await marketdata.getLatestTradePrice(symbol);
    const { stopPrice, targetPrice } = computeBracketGeometry(action, candidate, entryRef, config);
    const sizing = computeSizing(action, entryRef, stopPrice, equityAtStart, config);

    if (!sizing.valid) {
      await journal({
        finalDecision: "SKIP",
        finalSkipReason: "geometry_invalid",
        qty: 0,
        entryRefPrice: entryRef,
        stopPrice,
        targetPrice,
        riskPerShare: sizing.stopDistance,
        entryOrderId: null,
      });
      return await done("skipped:geometry_invalid");
    }
    if (sizing.qty <= 0) {
      await journal({
        finalDecision: "SKIP",
        finalSkipReason: "size_too_small",
        qty: 0,
        entryRefPrice: entryRef,
        stopPrice,
        targetPrice,
        riskPerShare: sizing.stopDistance,
        entryOrderId: null,
      });
      return await done("skipped:size_too_small");
    }

    // 19. Bar-level claim -- taken immediately before order placement
    // (daily-check #293 precedent). The loser writes audit only and must
    // not upsert hourly_scans (it would clobber the winner's row).
    const claimed = await db.claimBar("hourly-check", barTs);
    if (!claimed) {
      return await done("skipped:duplicate_run");
    }

    // 20. Journal pre-order (provenance-first, so the naked-position rule
    // always has geometry to re-leg against), place the order, insertTrade,
    // then update entry_order_id.
    await journal({
      finalDecision: action,
      finalSkipReason: null,
      qty: sizing.qty,
      entryRefPrice: entryRef,
      stopPrice,
      targetPrice,
      riskPerShare: sizing.stopDistance,
      entryOrderId: null,
    });

    let fill: Fill;
    let reason: "hourly_long_entry" | "hourly_short_entry";
    if (action === "LONG") {
      fill = await alpaca.placeBracketOrder({
        symbol,
        side: "BUY",
        qty: sizing.qty,
        takeProfitPrice: targetPrice,
        stopLossPrice: stopPrice,
      });
      reason = "hourly_long_entry";
    } else {
      // Bracket-on-short is unconfirmed (spec §7 [to verify]) -- documented
      // fallback: plain entry, then an OCO exit pair once the fill confirms.
      fill = await alpaca.placeMarketOrder({ symbol, side: "SELL", qty: sizing.qty });
      await alpaca.placeOcoExitPair({
        symbol,
        side: "BUY",
        qty: fill.qty,
        takeProfitPrice: targetPrice,
        stopLossPrice: stopPrice,
      });
      reason = "hourly_short_entry";
    }

    await db.insertTrade({
      symbol,
      side: action === "LONG" ? "BUY" : "SELL",
      qty: fill.qty,
      fillPrice: fill.fillPrice,
      fillTime: fill.fillTime,
      brokerOrderId: fill.orderId,
      reason,
    });

    await journal({
      finalDecision: action,
      finalSkipReason: null,
      qty: sizing.qty,
      entryRefPrice: entryRef,
      stopPrice,
      targetPrice,
      riskPerShare: sizing.stopDistance,
      entryOrderId: fill.orderId,
    });

    return await done("success");
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await notifications.notifyBrokerError({ context: "hourly-check", errorMsg: err.message });
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
