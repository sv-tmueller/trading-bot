// hourly-check: the hourly-candlestick long/short bot's pipeline (#475,
// spec docs/superpowers/specs/2026-07-27-hourly-bot-design.md). Follows the
// daily-check/kill-switch shape: `runHourlyCheck(deps)` opens the audit row
// first, closes every path via a single `finish(outcome, notes)`, and a
// top-level catch maps any thrown error to `error:${err.name}`.
//
// Gate ladder (spec §4-§9, sub-plan T9): a fixed pipeline order, one
// deterministic outcome per run. See the sub-plan's 20-row table for the
// full spec; this file implements it in that exact order.
//
// #514 D6: outcome-to-alert policy (the recorded decision). Rule: an outcome
// raises a real-time Discord alert iff (a) it halts trading in a way that
// persists without operator action, or (b) it indicates broker state that is
// or was unprotected. Every `error:*` alerts. Routine gates, idempotent
// no-ops, and downstream consequences of an already-alerted event stay
// silent. Any PR adding a new outcome string should update this table.
//
// | Outcome                                    | Alerts? | Reason                                                                    |
// |---------------------------------------------|---------|----------------------------------------------------------------------------|
// | success:auto_paused                          | YES (notifyEquityFloorFired) | halting, machine-initiated, never self-clears; possibly unmanaged open position (runbook §11) |
// | error:naked_position_flattened               | YES (notifyBrokerError)      | position was unprotected and got closed unexpectedly |
// | error:DataError via gate-6 alertAndFail      | YES (notifyError)            | halting: blocks every scan until fixed (#488) |
// | error:AlpacaError incl. subclasses           | YES (notifyBrokerError)      | broker faults block entries (2026-07-30 precedent) |
// | any other error:* (calendar-session          | YES (notifyError, D5)        | verified gap; a repeating silent error is a halted bot |
// |   DataError, marketdata parse faults, generic throws) | | |
// | success                                      | no      | routine paper entry; visible in `trades` and weekly review |
// | success:no_action                            | no      | the modal outcome |
// | success:legs_replaced                        | no (real-time) | auto-repaired, protected at run end; runbook §10 marks it investigate-only |
// | success:journal_degraded                     | no (here)      | surfacing owned by #486 in a later batch |
// | skipped:trading_paused                       | no      | the pause event itself alerted; re-alerting is 9/day spam |
// | skipped:kill_switch_active                    | no      | the fire already alerted via notifyKillSwitchFired at flag-set |
// | all other skipped:*                          | no      | routine gates working as designed; anomalies surface in `hourly_scans` and weekly review |
//
// Residual, disclosed: a crash before insertAuditLog produces no outcome and
// no alert; runbook §10's no-audit-row triage covers it, out of scope.
import { AlpacaError, type ClosedOrderFill, type Fill } from "../_shared/alpaca.ts";
import { CONTEXT_SMA_WINDOW } from "../_shared/candlestick.ts";
import type { HourlyConfig } from "../_shared/config.ts";
import type {
  HourlyScanRow,
  HourlyScanSkipUpsert,
  HourlyScanUpsert,
  TradeRow,
} from "../_shared/db.ts";
import { decideHourly, type HourlyAction } from "../_shared/hourly_signal.ts";
import type { CalendarSession, HourlyBar } from "../_shared/marketdata.ts";
import { DataError, requireNumber, roundToCents } from "../_shared/num.ts";

const HOUR_MS = 60 * 60 * 1000;

// §11's hard floor: -15% account equity from the paper experiment's start.
// Not a config setting (not in §10's table) -- a fixed default the operator
// owns via the spec's own merge, same as the 4-week/30-trade checkpoint.
const EQUITY_FLOOR_PCT = 0.15;

// #488: how far BELOW account equity the stored experiment baseline may sit at
// the moment it is first checked. A wrong baseline (as opposed to a missing
// one) parses fine and silently relocates the floor -- the 2026-07-29 ops
// window left a stale 100000.00 baseline against 1017330.61 of equity, putting
// the floor at a 91.6% loss.
//
// Both bounds on this number are real. It must stay WIDE enough to absorb the
// drift between the operator's /v2/account read and the first scan, which is
// hours to a few days and can carry a residual leveraged position. It must
// stay well BELOW the smallest dangerous error class, a 2x stale value
// (100% off). 20% sits between them with margin either way.
//
// Duplicated as the 0.20 in the runbook §5 verification query, which gives the
// operator the same verdict before deploy. Change both together.
const BASELINE_TOLERANCE_PCT = 0.20;

// Companion bot_config key holding the baseline string that has already been
// checked against this account's equity. It is what makes the check one-shot
// rather than continuous -- see isBaselinePlausible and its call site.
const BASELINE_VERIFIED_KEY = "hourly_experiment_baseline_verified";

// Every reason this package's trades rows can carry. hourly_kill_switch is
// read (as an exit event, for cooldown/day-cap bookkeeping) but never
// written here -- the retrofit package (#474) owns writing it.
const ENTRY_REASONS: string[] = ["hourly_long_entry", "hourly_short_entry"];
const EXIT_REASONS: string[] = [
  "hourly_bracket_exit",
  "hourly_session_close_exit",
  "hourly_kill_switch",
];

// #480 T1: step 20's post-fill writes (kill-switch clears -> insertTrade ->
// provenance journal) used to abort on the first throw, leaving a filled
// entry with no trades row and no entry_order_id (PR #477 round-2 review
// finding 2 + corollary). POST_FILL_WRITE_ATTEMPTS bounds an immediate
// (no-sleep) retry per write group; a group's exhaustion degrades the run's
// outcome instead of throwing, so the remaining groups still get their own
// attempt. Not a config setting -- fixed, like EQUITY_FLOOR_PCT above.
const POST_FILL_WRITE_ATTEMPTS = 3;

/**
 * Retries `fn` up to POST_FILL_WRITE_ATTEMPTS times (no backoff -- these are
 * fast, independent DB writes, not broker calls). Returns true once `fn`
 * resolves; false (after a `console.warn`) once every attempt has thrown.
 *
 * Accepted residual (should-fix round 1 finding 4): the `insert_trade`
 * group is the one non-idempotent retried write -- `trades` has no unique
 * index on broker_order_id -- so a response failure after a commit (or two
 * concurrent runs racing, since recovery runs ahead of claimBar) can retry
 * into a duplicate row for the same fill. This is fail-closed for gate 14's
 * day cap (an extra counted entry only makes the cap stricter) and inert
 * for gate 13's cooldown (keyed off the latest fill_time, unaffected by a
 * duplicate), but it does duplicate a row in the ledger #481 renders. No
 * schema change ships in this package; a unique index on broker_order_id is
 * the follow-up fix.
 */
async function tryPostFillWrite(label: string, fn: () => Promise<unknown>): Promise<boolean> {
  let lastErr: unknown;
  for (let attempt = 1; attempt <= POST_FILL_WRITE_ATTEMPTS; attempt++) {
    try {
      await fn();
      return true;
    } catch (e) {
      lastErr = e;
    }
  }
  console.warn(
    `hourly-check: post-fill write '${label}' failed after ${POST_FILL_WRITE_ATTEMPTS} ` +
      `attempts: ${String((lastErr as Error)?.message ?? lastErr)}`,
  );
  return false;
}

/**
 * #488 round-2 finding 5: raises a Discord alert and returns the DataError to
 * throw. Gate 6's failures all mean "the -15% floor cannot be trusted", and
 * the top-level catch notifies on AlpacaError only, so without this they are
 * visible in audit_log alone -- detection would rest on someone reading it.
 *
 * Returns rather than throws so the call site keeps `throw` on the same line
 * and stays obviously terminal. DataError is deliberate: these are config
 * faults, not broker faults, so reparenting them to AlpacaError to inherit its
 * notification would misreport the source (#494 set AlpacaError's scope).
 */
async function alertAndFail(
  notifications: HourlyCheckDeps["notifications"],
  message: string,
): Promise<DataError> {
  // The outbox's notifyError swallows its own failures, so alerting cannot
  // mask the fault it is reporting.
  await notifications.notifyError(`hourly-check equity floor: ${message}`);
  const err = new DataError(message);
  // #514 D5: a property flag, not a subclass -- the outcome string this
  // error produces (`error:DataError`) must stay exactly that. The top-level
  // catch's fallback alert (below) checks this flag so an already-alerted
  // gate-6 fault never alerts twice.
  (err as DataError & { alerted?: boolean }).alerted = true;
  return err;
}

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
    upsertHourlyScan: (p: HourlyScanUpsert) => Promise<void>;
    // #487: the SKIP-journal write. Refuses to downgrade a row that already
    // records a LONG/SHORT decision; returns false when it preserved one.
    upsertHourlyScanUnlessEntered: (p: HourlyScanSkipUpsert) => Promise<boolean>;
    getHourlyScanByEntryOrderId: (symbol: string, orderId: string) => Promise<HourlyScanRow | null>;
    // #513: all non-null entry_order_ids for a symbol, so the recovery step
    // can exclude fills already claimed by another scan row.
    getHourlyScanClaimedOrderIds: (symbol: string) => Promise<Set<string>>;
    // #480 T2: pending-entry scans (decision LONG/SHORT, entry_order_id NULL)
    // consumed by reconcile()'s recovery step.
    getHourlyScansPendingEntry: (symbol: string, sinceIso: string) => Promise<HourlyScanRow[]>;
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
    // #488: gate 6's failures are config faults, not broker faults, so the
    // AlpacaError-only notify in the top-level catch never sees them. The
    // outbox's notifyError is durable and never throws, so alerting cannot
    // itself break the gate.
    notifyError: (message: string) => Promise<void>;
    // #514: the -15% equity floor's halt event. positionQty is null when the
    // fire site's own guarded getPosition() read failed or was never
    // attempted -- rendered as unknown/treat-as-open (fail-safe, runbook §11).
    notifyEquityFloorFired: (p: {
      ticker: string;
      equity: number;
      baseline: number;
      drawdownPct: number;
      positionQty: number | null;
      positionError?: string;
    }) => Promise<void>;
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

/**
 * #488: is `baseline` close enough to `equity` to have plausibly been derived
 * from this account? Only ever asked at the one moment the answer is knowable
 * -- the first scan after a baseline is written, when the two are supposed to
 * be the same number -- and only when equity exceeds the baseline, since the
 * floor owns the other direction. See BASELINE_TOLERANCE_PCT for both bounds.
 *
 * Equity is the denominator, so a zero or negative equity admits no baseline
 * at all, which is the right answer: a floor cannot be validated against an
 * account that has none.
 */
export function isBaselinePlausible(baseline: number, equity: number): boolean {
  return Math.abs(baseline - equity) <= equity * BASELINE_TOLERANCE_PCT;
}

export interface BracketGeometry {
  stopPrice: number;
  targetPrice: number;
}

/**
 * Bracket geometry (spec §7): stop is the signal bar's own extreme plus a
 * buffer (long: low - buffer; short: high + buffer); target is
 * entry +/- R * stopDistance, R frozen at HOURLY_BRACKET_R_MULTIPLE.
 *
 * Both prices are quantized to whole cents (roundToCents, #494). Quantizing
 * here rather than at the send site keeps the journaled hourly_scans geometry
 * identical to what the broker holds, which the re-leg path and the weekly
 * review's R denominator both read back.
 *
 * The ORDERING is load-bearing: the stop is rounded first and stopDistance is
 * recomputed from the ROUNDED stop, so the target derives from the number that
 * actually goes on the wire. buffer = 0.05 * barRange on a 2-decimal range
 * yields a 4-decimal stop, and the target's x2 then lands on an exact
 * half-cent whenever the range ends in x.x5; deriving the target from the
 * rounded stop removes that tie class instead of forcing a tie-break
 * convention, and keeps wire R exactly R against wire risk.
 */
export function computeBracketGeometry(
  action: "LONG" | "SHORT",
  bar: { high: number; low: number },
  entryRef: number,
  cfg: { hourlyStopBufferPct: number; hourlyBracketRMultiple: number },
): BracketGeometry {
  const barRange = bar.high - bar.low;
  const buffer = cfg.hourlyStopBufferPct * barRange;
  const rawStop = action === "LONG" ? bar.low - buffer : bar.high + buffer;
  const stopPrice = roundToCents(rawStop, "stop_price");
  const stopDistance = Math.abs(entryRef - stopPrice);
  const rawTarget = action === "LONG"
    ? entryRef + cfg.hourlyBracketRMultiple * stopDistance
    : entryRef - cfg.hourlyBracketRMultiple * stopDistance;
  return { stopPrice, targetPrice: roundToCents(rawTarget, "target_price") };
}

export interface SizingResult {
  /** false = entryRef is on the wrong side of stopPrice, or too close (spec §6 finding 12). */
  valid: boolean;
  stopDistance: number;
  qtyRisk: number;
  qtyCap: number;
  qty: number;
}

/**
 * Sizing (spec §6): stop first, then quantity. Whole shares only.
 *
 * The two legs (`qtyRisk`, `qtyCap`) cross at
 * `stopDistance > (SIZING_RISK_PCT / SIZING_NOTIONAL_CAP_PCT) x entryRef` -- 10% of price at the
 * 0.01/0.10 defaults. SPY hourly stops never clear that, so `qtyCap` always binds and realised
 * risk per trade is ~0.03% of equity, not the configured `SIZING_RISK_PCT` (#499).
 */
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

  // Trades snapshot fetched once; recovery (step 0 below) augments this array
  // in-memory on adoption instead of triggering a second DB read (#480 T3).
  const allSymbolTrades = (await db.getTradesSince(lookbackIso)).filter((t) => t.symbol === symbol);

  // Memoized broker read (nit 7): both the recovery step below and the
  // exit-fill discovery step further down query the SAME window
  // (`lookbackIso`); when recovery's adoption makes entryConsideredOpen true
  // in this same run, exit-fill discovery would otherwise issue an
  // identical second broker read.
  let discoveredFillsPromise: Promise<ClosedOrderFill[]> | null = null;
  const getDiscoveredFills = (): Promise<ClosedOrderFill[]> => {
    if (!discoveredFillsPromise) {
      discoveredFillsPromise = alpaca.listFilledOrdersSince(symbol, lookbackIso);
    }
    return discoveredFillsPromise;
  };

  // 0. Recovery (#480 T3): closes the residual window T1's bounded retry
  // cannot fully eliminate. A pre-order journal (logic.ts step 20) commits
  // decision IN ('LONG','SHORT') with entry_order_id NULL; if every post-fill
  // write group then exhausted its retries, that row is the exact signature
  // left behind. Match each such pending row against a broker fill that is
  // (a) on the matching side, (b) NOT already claimed as entry_order_id by
  // another scan row (#513 -- replaces the former [bar_ts+1h, bar_ts+2h) time
  // window, which could adopt a neighbouring bar's fill on an off-cadence or
  // manual invocation; a fill is now adoptable only by the scan row that
  // produced it, independent of when it lands), and (c) either unjournaled OR
  // already journaled under THIS row's own entry reason (must-fix round 1
  // finding 2 -- a fill journaled under an EXIT reason must never be adopted
  // as entry provenance; the "journaled under its own reason" half keeps a
  // partial-fault replay working, where the insert_trade group already landed
  // the row before the journal group failed). Adopt the earliest eligible
  // match at most once, and restore entry_order_id. Idempotent/convergent: a
  // DB failure during recovery itself just retries next scan (should-fix
  // finding 3 -- the whole step is additionally wrapped below so a
  // bookkeeping-only throw here can never abort the scan ahead of this
  // function's protection duties).
  //
  // #513 residual (was nit 6, narrowed): a same-side fill on the symbol not
  // placed by any hourly-check entry path (manual, another tool) can still be
  // adopted if no scan row has claimed its orderId -- but it can no longer be
  // adopted by the WRONG row, which was the bug. This is the same class of
  // residual as the pre-fix code, just without the cross-bar confusion.
  //
  // Deliberately NEVER clears hourly_kill_switch_* here. §5's atomic
  // clear+enter is a decision-scoped act (this bar's own decision clearing
  // the flag it just satisfied), not a fill-scoped one a later recovery pass
  // can safely infer after #474's writer may have re-armed the flag on the
  // recovered position itself in between; PR #477's round-2 review already
  // ratified "stale until a later fully-successful opposite-side entry" as
  // fail-closed, and this recovery step pins that instead of silently
  // changing it (#480 T5). The clear itself still only ever happens at step
  // 20, immediately after THAT scan's own successful entry.
  try {
    const pending = await db.getHourlyScansPendingEntry(symbol, lookbackIso);
    if (pending.length > 0) {
      const discovered = await getDiscoveredFills();
      // #513: fills already claimed as entry_order_id by another scan row
      // are not adoptable. This keys adoption to the entry_order_id /
      // broker_order_id relationship rather than a time window.
      const claimedOrderIds = await db.getHourlyScanClaimedOrderIds(symbol);
      const adoptedOrderIds = new Set<string>();
      for (const row of pending) {
        const wantSide = row.decision === "LONG" ? "BUY" : "SELL";
        const reason = row.decision === "LONG" ? "hourly_long_entry" : "hourly_short_entry";
        const match = discovered
          .filter((f) => f.side === wantSide)
          .filter((f) => !adoptedOrderIds.has(f.orderId))
          .filter((f) => !claimedOrderIds.has(f.orderId))
          .filter((f) => {
            const existing = allSymbolTrades.find((t) => t.broker_order_id === f.orderId);
            return existing === undefined || existing.reason === reason;
          })
          .sort((a, b) => a.fillTime.localeCompare(b.fillTime))[0];
        if (!match) continue;
        adoptedOrderIds.add(match.orderId);
        const alreadyJournaled = allSymbolTrades.some((t) => t.broker_order_id === match.orderId);
        if (!alreadyJournaled) {
          await db.insertTrade({
            symbol,
            side: match.side,
            qty: match.qty,
            fillPrice: match.fillPrice,
            fillTime: match.fillTime,
            brokerOrderId: match.orderId,
            reason,
          });
          allSymbolTrades.push({
            symbol,
            side: match.side,
            qty: match.qty,
            fill_price: match.fillPrice,
            fill_time: match.fillTime,
            reason,
            broker_order_id: match.orderId,
          });
        }
        await db.upsertHourlyScan({
          symbol: row.symbol,
          barTs: row.bar_ts,
          decision: row.decision,
          skipReason: row.skip_reason,
          detectorsFired: row.detectors_fired,
          contextMode: row.context_mode,
          entryRefPrice: row.entry_ref_price,
          stopPrice: row.stop_price,
          targetPrice: row.target_price,
          riskPerShare: row.risk_per_share,
          equityUsd: row.equity_usd,
          qty: row.qty,
          entryOrderId: match.orderId,
        });
      }
    }
  } catch (e) {
    // Should-fix round 1 finding 3: recovery is a bookkeeping convenience,
    // not a protection duty -- it must never abort the scan ahead of the
    // naked-position rule and the flatten close-out below. Recovery is
    // convergent, so swallowing here just means the next scan retries.
    console.warn(
      `hourly-check: recovery step failed, skipping this scan (will retry next scan): ${
        String((e as Error)?.message ?? e)
      }`,
    );
  }

  const hourlyTrades = allSymbolTrades.filter(
    (t) => ENTRY_REASONS.includes(t.reason) || EXIT_REASONS.includes(t.reason),
  );
  const byTimeDesc = [...hourlyTrades].sort((a, b) => b.fill_time.localeCompare(a.fill_time));
  const lastEntry = byTimeDesc.find((t) => ENTRY_REASONS.includes(t.reason)) ?? null;
  const lastExit = byTimeDesc.find((t) => EXIT_REASONS.includes(t.reason)) ?? null;
  const entryConsideredOpen = lastEntry !== null &&
    (lastExit === null || lastExit.fill_time < lastEntry.fill_time);

  // 1. Discover newly-filled exit legs since the last journaled exit, so the
  // position check below sees post-fill broker truth. Bounded by the same
  // 5-day reconcile lookback rather than the last entry's fill_time (must-fix
  // round 1 finding 3): Alpaca's `after` filters on SUBMISSION time, and
  // bracket children are submitted alongside the parent -- before the entry
  // fill -- so `after=lastEntry.fill_time` would silently never find them.
  // The wider window is safe because every discovered fill is deduped below
  // against ALL journaled trades for the symbol (should-fix finding 5:
  // regardless of reason, so a panic_cli fill is never re-journaled here).
  if (entryConsideredOpen && lastEntry) {
    const discovered = await getDiscoveredFills();
    for (const f of discovered) {
      if (f.orderId === lastEntry.broker_order_id) continue; // the entry itself
      if (allSymbolTrades.some((t) => t.broker_order_id === f.orderId)) continue; // already recorded
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
      // #497: capture the re-leg failure's message so the flatten alert
      // below can distinguish "provenance absent" (lookup found nothing)
      // from "provenance present but rejected" (e.g. a pre-#494
      // hourly_scans row whose numeric(14,4) stop_price/target_price
      // round-trips sub-penny and is now refused by requireWholeCentPrice).
      // The catch stays bare in the control-flow sense: no re-raise, no
      // gating -- protecting the position outranks naming the cause.
      let relegFailureMsg: string | null = null;
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
        } catch (e) {
          // fall through to the fail-toward-protection flatten below
          relegFailureMsg = String((e as Error)?.message ?? e);
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
      // #497: the alert message distinguishes the two causes that converge
      // on this flatten. When provenance was found but the re-leg threw
      // (SubPennyPriceError, broker reject, etc.), the operator needs to
      // see WHY it was refused -- not the misleading "no re-leggable
      // provenance" which implies the lookup found nothing.
      const flattenReason = relegFailureMsg !== null
        ? `provenance rejected (${relegFailureMsg})`
        : "no re-leggable provenance";
      await notifications.notifyBrokerError({
        context: "hourly-check:naked_position_flattened",
        errorMsg: `position qty=${positionQty} had no resting legs and ${flattenReason}; flattened`,
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
    const currentUtcHour = deps.now().getUTCHours();
    const isFlattenScan =
      (clock.nextClose - nowMs <= HOUR_MS) ||
      (currentUtcHour >= config.hourlyScanEndHour);

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
    //
    // Nit 8 (determinism on the failure path): if `supersede` were ever set
    // AND step 20 below degraded, `actual` would become the supersede
    // outcome while `notes` still carries the degraded-group enumeration --
    // outcome and notes could then disagree. Practically unreachable today:
    // a supersede requires reconcile() to find a naked, re-leggable position
    // at the TOP of this same run, which means gate 12 (position_open) skips
    // this run out before step 20 ever executes. Pre-existing mechanism, not
    // touched by this package -- noted because determinism on the failure
    // path is an acceptance criterion.
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
      throw await alertAndFail(
        notifications,
        "bot_config.hourly_experiment_start_equity is not set -- required before any scan " +
          "can evaluate the -15% equity floor (spec §11)",
      );
    }
    // Third way the floor becomes untrustworthy: present but unparseable
    // ('1,017,330.61', '$1017330.61' -- the fat-fingered paste an account UI
    // produces). requireNumber throws its own DataError, which would sail past
    // alertAndFail and leave this path the only silent one of the three.
    let baseline: number;
    try {
      baseline = requireNumber(baselineRaw, "hourly_experiment_start_equity");
    } catch (e) {
      throw await alertAndFail(notifications, String((e as Error)?.message ?? e));
    }

    // The floor owns everything strictly below the baseline, and it runs FIRST
    // (round-2 finding 1). Below the baseline a drawdown and a wrong-high
    // baseline are indistinguishable on a first scan, and the plausibility
    // check must not pre-empt the floor there: doing so would downgrade the
    // persistent bot_config.paused kill switch to a per-scan error (status
    // would report paused=false while the bot sits erroring), and the
    // diagnostic would tell the operator to move the baseline DOWN onto the
    // drawn-down equity, erasing the breach. A wrong-high baseline only makes
    // the floor fire EARLY, which is conservative, so it needs no second
    // opinion.
    if (equityAtStart <= baseline * (1 - EQUITY_FLOOR_PCT)) {
      // #514 D2: bot_config.paused=true is written FIRST, unconditionally --
      // the alert and the position read below are reporting duties, not
      // gates, and must never delay or block the pause itself.
      await db.setConfig("paused", "true");

      // Fresh, guarded read of the position "at pause time": reconcile()'s
      // own read (steps 4-5, above) can be stale by now -- its own step-3
      // flatten can change it, or time simply passes -- so this is a second,
      // deliberate broker call. A failed read renders as UNKNOWN in the
      // alert, which the message treats as open (fail-safe).
      let positionQty: number | null = null;
      let positionError: string | undefined;
      try {
        positionQty = await alpaca.getPosition(symbol);
      } catch (e) {
        positionError = String((e as Error)?.message ?? e);
      }

      // #514 D3: guarded even though the outbox's own notify helpers never
      // throw -- this path is a protection duty, so a misbehaving injected
      // dep (a test double, a future regression) must never cost this audit
      // row after paused=true is already written.
      try {
        await notifications.notifyEquityFloorFired({
          ticker: symbol,
          equity: equityAtStart,
          baseline,
          drawdownPct: (baseline - equityAtStart) / baseline,
          positionQty,
          positionError,
        });
      } catch (e) {
        console.warn(
          `hourly-check: equity-floor alert failed: ${String((e as Error)?.message ?? e)}`,
        );
      }

      // #514 D4: bypasses `done()` deliberately. Gate 6 runs AFTER
      // reconcile() (steps 4-5), so a same-run naked-position re-leg can have
      // already set `supersede = "success:legs_replaced"` -- `done()` would
      // let that supersede win and silently swallow the auto-pause outcome
      // (see the outcome-to-alert policy table above the gate ladder). The
      // re-leg is still recorded, in notes, just never as the outcome string.
      const notes = supersede
        ? `equity=${equityAtStart} baseline=${baseline} supersede=${supersede}`
        : `equity=${equityAtStart} baseline=${baseline}`;
      await finish("success:auto_paused", notes);
      return "success:auto_paused";
    }

    // #488: a WRONG baseline parses fine here and silently relocates the
    // floor, unlike a missing one. The dangerous direction is a baseline too
    // LOW relative to equity -- the 2026-07-29 case, 100000 against 1017330.61
    // -- because that is where the floor goes inert. So the check runs only
    // when equity is AT OR ABOVE the baseline; below it, the floor above has
    // already had its say.
    //
    // The check is one-shot, keyed to the baseline VALUE: BASELINE_VERIFIED_KEY
    // holds the baseline string already checked against this account's equity.
    // That keying is what distinguishes "this baseline was never derived from
    // this account" from "the account has since drifted". Baseline and equity
    // are only ever expected to agree at one instant -- the first scan after a
    // baseline is written. After that, divergence is the whole point of a
    // baseline and carries no expected bound, so a continuous magnitude check
    // would false-positive on exactly the outcome the experiment is measuring.
    // Once the marker matches, this block never runs again.
    //
    // Residual, deliberately accepted (runbook §5 documents it): the marker is
    // keyed to the baseline value, not to the account, so pointing the bot at a
    // different paper account whose baseline happens to be byte-identical skips
    // the check. Account identity is not in bot_config today, and the check is
    // one line of defence among several.
    //
    // The guard is `>=`, not `>`: equality is the IDEAL case, a baseline set
    // from the equity this scan just read, and it can only ever pass (the
    // deviation is zero). Excluding it would leave the ideal case unrecorded
    // and the check armed until equity happened to tick up. Everything
    // strictly below the baseline still belongs to the floor alone.
    const alreadyVerified = baselineRaw === await db.getConfig(BASELINE_VERIFIED_KEY);
    if (!alreadyVerified && equityAtStart >= baseline) {
      if (!isBaselinePlausible(baseline, equityAtStart)) {
        throw await alertAndFail(
          notifications,
          `bot_config.hourly_experiment_start_equity=${baseline} is implausible against ` +
            `account equity ${equityAtStart} -- more than ${BASELINE_TOLERANCE_PCT * 100}% ` +
            `below it, leaving the -15% floor at ` +
            `${roundToCents(baseline * (1 - EQUITY_FLOOR_PCT), "floor_from_baseline")} when ` +
            `the account holds ${roundToCents(equityAtStart, "equity_at_start")}. Correct the ` +
            `baseline UP to the equity at experiment start with an explicit UPDATE (runbook ` +
            `§5); to accept it as intentional, set bot_config.${BASELINE_VERIFIED_KEY} to the ` +
            `same value.`,
        );
      }
      // Recording the marker IS the one-shot guarantee, not bookkeeping
      // (round-2 finding 2). If it cannot land, the check stays armed and will
      // fire later on the legitimate upside divergence the baseline exists to
      // measure -- so fail the run rather than warn into a function log that
      // audit_log never sees. Nothing has been placed yet; the cost is one
      // skipped scan.
      try {
        await db.setConfig(BASELINE_VERIFIED_KEY, baselineRaw);
      } catch (e) {
        throw await alertAndFail(
          notifications,
          `baseline ${baselineRaw} passed the plausibility check but ` +
            `bot_config.${BASELINE_VERIFIED_KEY} could not be recorded ` +
            `(${String((e as Error)?.message ?? e)}) -- refusing to continue with the check ` +
            `left armed against legitimate divergence.`,
        );
      }
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

    // Session lookup spans every date the completed series touches, not just
    // today's candidate -- must-fix round 1 finding 1. The per-bar partial
    // filter below needs each bar's OWN session (a t-1 stub can fall on a
    // different session day than the candidate); a bar with no matching
    // session is excluded from the signal -- over-exclusion is the specced
    // fail-safe direction.
    const barDates = [
      ...new Set(completed.map((b) => new Date(b.timestamp).toISOString().slice(0, 10))),
    ].sort();
    const sessions = await marketdata.getCalendarSessions(
      barDates[0],
      barDates[barDates.length - 1],
    );
    const sessionsByDate = new Map(sessions.map((s) => [s.date, s]));

    const todaySession = sessionsByDate.get(today);
    if (!todaySession) {
      throw new DataError(`no calendar session found for ${today} (market reported open)`);
    }

    // #487: every SKIP journal this pipeline writes lands BEFORE claimBar, so
    // the bar-level claim cannot protect the row -- route them all through the
    // guarded upsert (why, in full, at upsertHourlyScanUnlessEntered in
    // _shared/db.ts). Step 20's entry journal and reconcile()'s recovery
    // upsert deliberately keep the unconditional write: those must be able to
    // write LONG/SHORT and stamp entry_order_id.
    //
    // A preserved row does NOT change the run's outcome -- the gate ladder
    // reports exactly what it reports today.
    const journalSkip = async (p: HourlyScanSkipUpsert): Promise<void> => {
      const written = await db.upsertHourlyScanUnlessEntered(p);
      if (!written) {
        console.warn(
          `hourly-check: SKIP journal (${p.skipReason}) for ${p.symbol} bar_ts=${p.barTs} ` +
            `preserved an existing entry decision`,
        );
      }
    };

    // A gate that skips before decideHourly runs, keyed to the candidate bar
    // (must-fix round 1 finding 2): journal a SKIP row so a partial/stale
    // scan is visible in hourly_scans, not audit_log-only. Detectors are
    // never computed for a scan that skips here, so detectorsFired is empty
    // and the sizing columns stay null ("null unless computed").
    const preDecisionSkip = async (reason: string, notes?: string): Promise<string> => {
      await journalSkip({
        symbol,
        barTs: candidate.timestamp,
        decision: "SKIP",
        skipReason: reason,
        detectorsFired: [],
        contextMode: config.hourlyContextMode,
        entryRefPrice: null,
        stopPrice: null,
        targetPrice: null,
        riskPerShare: null,
        equityUsd: equityAtStart,
        qty: 0,
        entryOrderId: null,
      });
      return await done(`skipped:${reason}`, notes);
    };

    if (isBarPartial(candidate, todaySession)) {
      return await preDecisionSkip("partial_bar", `candidate bar ${candidate.timestamp}`);
    }
    // #628: explicit UTC hour-range gate. With defaults (13/21) this is a
    // no-op for the cron's 13-21 envelope; it lets operators narrow the
    // entry window without a migration. isBarPartial stays unchanged --
    // it handles session-edge data quality independently.
    const candidateHour = new Date(candidate.timestamp).getUTCHours();
    if (
      candidateHour < config.hourlyScanStartHour ||
      candidateHour >= config.hourlyScanEndHour
    ) {
      return await preDecisionSkip(
        "outside_scan_window",
        `bar hour ${candidateHour} outside [${config.hourlyScanStartHour}, ${config.hourlyScanEndHour})`,
      );
    }
    const barEndMs = new Date(candidate.timestamp).getTime() + HOUR_MS;
    const staleMinutes = (nowMs - barEndMs) / 60000;
    if (staleMinutes > config.hourlyStalenessToleranceMin) {
      return await preDecisionSkip(
        "stale_data",
        `bar end=${new Date(barEndMs).toISOString()} stale by ${staleMinutes.toFixed(1)}min`,
      );
    }
    const barTs = candidate.timestamp;

    // The series passed to decideHourly excludes every partial bar against
    // ITS OWN session, not just the candidate (must-fix round 1 finding 1):
    // every session has a session-open stub at its first wall-clock hour
    // (spec §4), and leaving that stub in the series corrupts the
    // proportional body/wick detectors that look at the prior bar. A bar
    // with no matching session is excluded (over-exclusion is the fail-safe
    // direction, same as the candidate's own partial check above).
    const series = completed.filter((b) => {
      const bDate = new Date(b.timestamp).toISOString().slice(0, 10);
      const bSession = sessionsByDate.get(bDate);
      return bSession ? !isBarPartial(b, bSession) : false;
    });

    // 8. decideHourly.
    const decision = decideHourly(series, { contextMode: config.hourlyContextMode });

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
    }) => {
      const row: HourlyScanUpsert = {
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
      };
      // #487: SKIP rows go through the guard (see journalSkip above); the
      // entry journal at step 20 is the one write that must overwrite. The
      // re-stated `decision` is what narrows the row to the guard's
      // SKIP-only payload type -- TS cannot infer it from p.finalDecision.
      return p.finalDecision === "SKIP"
        ? journalSkip({ ...row, decision: "SKIP" })
        : db.upsertHourlyScan(row);
    };

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
    // hourly_kill_switch_side is allowed through. The clear itself is
    // deferred to step 20, after the entry order is successfully placed
    // (lead ruling, fix round 1 finding 4): clearing here and only then
    // failing a later gate (shorts disabled, position open, geometry
    // invalid, ...) would clear the flag on a scan that never entered,
    // defeating §5's atomic clear+enter intent.
    const flagActive = (await db.getConfig("hourly_kill_switch_active"))?.toLowerCase() === "true";
    let shouldClearKillSwitch = false;
    if (flagActive) {
      const side = await db.getConfig("hourly_kill_switch_side");
      if (action === "SKIP" || action === side) {
        return await gateSkip("kill_switch_active");
      }
      shouldClearKillSwitch = true;
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

    // 20b. Post-fill writes (#480 T1): three independent groups, each bounded-
    // retried via tryPostFillWrite -- a group's exhaustion no longer aborts
    // the remaining groups (PR #477 round-2 review finding 2 + corollary).
    // Fixed order for both execution and the degraded-outcome notes below:
    // kill_switch_clear, insert_trade, journal. A reconciliation-side
    // recovery step (T3) closes the residual window this can't fully cover
    // on its own (a group that exhausts all attempts still leaves the DB
    // write undone until the next scan's recovery pass).
    const failedGroups: string[] = [];

    // Atomic clear+enter (spec §5; lead ruling, fix round 1 finding 4): the
    // three hourly_kill_switch_* keys clear only now that the entry order has
    // actually been placed and filled -- never earlier, so a scan that later
    // failed a gate (or, before this point, the entry itself) would have left
    // the flag untouched. "" matches bot_config.value's NOT NULL column (the
    // only representable "cleared" string; #474's writer never clears these
    // keys itself, so there is no other precedent to diverge from -- nit 12).
    // All three writes are one retried unit, key order active -> side ->
    // fired_at, so a partial clear (if the group is abandoned mid-retry by a
    // crash rather than a caught error) leaves the flag fully inert.
    if (shouldClearKillSwitch) {
      const clearOk = await tryPostFillWrite("kill_switch_clear", async () => {
        await db.setConfig("hourly_kill_switch_active", "false");
        await db.setConfig("hourly_kill_switch_side", "");
        await db.setConfig("hourly_kill_switch_fired_at", "");
      });
      if (!clearOk) failedGroups.push("kill_switch_clear");
    }

    const insertOk = await tryPostFillWrite("insert_trade", () =>
      db.insertTrade({
        symbol,
        side: action === "LONG" ? "BUY" : "SELL",
        qty: fill.qty,
        fillPrice: fill.fillPrice,
        fillTime: fill.fillTime,
        brokerOrderId: fill.orderId,
        reason,
      }));
    if (!insertOk) failedGroups.push("insert_trade");

    // Must-fix round 1 finding 1: the journal group stamps entry_order_id on
    // the hourly_scans row -- only run it once the trades row has actually
    // landed. Stamping entry_order_id on a row with no trades row would
    // destroy the exact signature recovery (T3) depends on
    // (decision IN ('LONG','SHORT') AND entry_order_id IS NULL), leaving the
    // scan permanently unrecoverable: entryConsideredOpen would read false
    // (no lastEntry), so exit-leg discovery never runs, the day cap
    // undercounts, cooldown never fires, and a later leg loss flattens at
    // market instead of re-legging (no lastEntry to read provenance from).
    // Skipping the stamp costs nothing -- entry_order_id's only reader is
    // reached via lastEntry, which does not exist in that state. Still
    // recorded in failedGroups (without being attempted) so the notes
    // enumeration stays deterministic regardless of whether insert_trade
    // failed on its own or journal would also have failed independently.
    if (insertOk) {
      const journalOk = await tryPostFillWrite("journal", () =>
        journal({
          finalDecision: action,
          finalSkipReason: null,
          qty: sizing.qty,
          entryRefPrice: entryRef,
          stopPrice,
          targetPrice,
          riskPerShare: sizing.stopDistance,
          entryOrderId: fill.orderId,
        }));
      if (!journalOk) failedGroups.push("journal");
    } else {
      failedGroups.push("journal");
    }

    if (failedGroups.length === 0) {
      return await done("success");
    }
    // The broker_order_id is the forensic breadcrumb: it lets a human (or the
    // T3 recovery step) locate the fill that a degraded write left dangling.
    return await done(
      "success:journal_degraded",
      `failed=[${failedGroups.join(",")}] order=${fill.orderId}`,
    );
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await notifications.notifyBrokerError({ context: "hourly-check", errorMsg: err.message });
    } else if (!(err as DataError & { alerted?: boolean }).alerted) {
      // #514 D5: closes the verified gap -- gate-6 DataErrors already alert
      // via alertAndFail (skipped here via the `alerted` flag), but a thrown
      // calendar-session DataError, a marketdata parse fault, or any other
      // generic throw produced a silent `error:*` audit row. An erroring
      // scan blocks every entry until fixed and can repeat up to 9x/day, so
      // it must alert exactly like a broker fault does.
      await notifications.notifyError(`hourly-check: ${err.name}: ${err.message}`);
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
