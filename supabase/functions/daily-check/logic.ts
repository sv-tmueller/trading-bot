import { computeTargetState, type State } from "../_shared/regime.ts";
import type { Fill } from "../_shared/alpaca.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";
import type { RegimeStateRow } from "../_shared/db.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export interface DailyCheckDeps {
  config: StrategyConfig;
  now: () => Date;
  marketdata: {
    getDailyCloses: (symbol: string, count: number) => Promise<DailyBar[]>;
    getLatestTradePrice: (symbol: string) => Promise<number>;
  };
  alpaca: {
    getClock: () => Promise<{ isOpen: boolean }>;
    getCalendar: (start: string, end: string) => Promise<string[]>;
    getPosition: (symbol: string) => Promise<number>;
    getAccountValue: () => Promise<number>;
    placeMarketOrder: (a: { symbol: string; side: "BUY" | "SELL"; qty: number }) => Promise<Fill>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    getConfig: (key: string) => Promise<string | null>;
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
    claimTradeDate: (scriptName: string, tradeDate: string) => Promise<boolean>;
    upsertRegimeState: (p: {
      date: string;
      spyClose: number;
      spySma200: number;
      targetState: State;
      currentState: State;
      positionDrawdownPct: number | null;
      killSwitchActive: boolean;
      killSwitchFiredAt: string | null;
    }) => Promise<void>;
    insertTrade: (p: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      fillPrice: number;
      fillTime: string;
      brokerOrderId: string;
      reason: "regime_flip_long" | "regime_flip_cash" | "kill_switch" | "panic_cli";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (
      p: { id: number; finishedAt: string; outcome: string; notes?: string | null },
    ) => Promise<void>;
    // #383 T3: one equity_snapshots row per trading day, written after
    // upsertRegimeState so a snapshot-write failure can never block the
    // trading-critical state write (D2).
    upsertEquitySnapshot: (p: { date: string; equityUsd: number }) => Promise<void>;
  };
  notifications: {
    notifyRegimeFlip: (p: {
      targetState: State;
      spyClose: number;
      spySma200: number;
      ticker: string;
      fillPrice: number;
      qty: number;
      accountValue: number;
      dryRun?: boolean;
    }) => Promise<void>;
    notifyStateDesync: (
      p: { dbState: State; brokerState: State; symbol: string; actionTaken: string },
    ) => Promise<void>;
    notifyTradeFailed: (
      p: { symbol: string; side: "BUY" | "SELL"; qty: number; reason: string },
    ) => Promise<void>;
    notifyBrokerError: (p: { context: string; errorMsg: string }) => Promise<void>;
  };
}

function sma(closes: number[], n: number): number {
  if (closes.length < n) return NaN;
  const slice = closes.slice(-n);
  return slice.reduce((a, b) => a + b, 0) / n;
}

export async function runDailyCheck(deps: DailyCheckDeps): Promise<string> {
  const { config, db, alpaca, marketdata, notifications } = deps;
  const iso = (d: Date) => d.toISOString();
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const startedAt = iso(deps.now());
  const auditId = await db.insertAuditLog({ scriptName: "daily-check", startedAt });

  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });

  try {
    // Operational pause. Read inside the try so a DB failure here yields an
    // error:* audit outcome instead of an unhandled throw that escapes with no
    // outcome written (the index.ts handler has no top-level catch).
    const paused = (await db.getConfig("paused"))?.toLowerCase() === "true";
    if (paused) {
      await finish("skipped:trading_paused", "bot_config.paused is true");
      return "skipped:trading_paused";
    }

    // Post-open execution (#256): the cron fires at 13:37 and 14:37 UTC
    // year-round; the off-season slot, weekends-after-holiday edge cases, and
    // market holidays all exit here. Same gate pattern as kill-switch.
    if (!(await alpaca.getClock()).isOpen) {
      await finish("skipped:market_closed");
      return "skipped:market_closed";
    }

    const barsRaw = await marketdata.getDailyCloses(config.botBenchmark, config.regimeSmaDays + 10);
    // The daily-bars feed can include today's in-progress bar during market
    // hours; the signal must only ever see completed sessions (#256).
    const today = ymd(deps.now());
    const barsArr = barsRaw.filter((b) => b.date < today);
    if (barsArr.length === 0) {
      await finish("skipped:stale_data", "no completed bars returned");
      return "skipped:stale_data";
    }
    const lastBar = barsArr[barsArr.length - 1];
    // Staleness: the last completed bar must be the most recent trading day
    // strictly before today (calendar-aware: holidays, long weekends). At
    // 13:37/14:37 UTC the UTC date equals the US-Eastern session date, so
    // `today` bounds both the filter above and the calendar query.
    const calStart = new Date(deps.now().getTime() - 10 * 86400000).toISOString().slice(0, 10);
    const sessions = await alpaca.getCalendar(calStart, today);
    const prevTradingDay = sessions.filter((d) => d < today).pop();
    if (!prevTradingDay || lastBar.date !== prevTradingDay) {
      await finish(
        "skipped:stale_data",
        `last bar=${lastBar.date}, prev trading day=${prevTradingDay ?? "none"}`,
      );
      return "skipped:stale_data";
    }

    const closes = barsArr.map((b) => b.close);
    const spyClose = lastBar.close;
    const spySma200 = sma(closes, config.regimeSmaDays);

    // Not enough history to compute the SMA → skip cleanly rather than act on a
    // NaN-driven signal. (Also avoids writing NaN, which JSON-serializes to null
    // and would violate the spy_sma200 NOT NULL column.) regime.ts's NaN→CASH
    // branch remains as defense in depth for any caller that skips this check.
    if (Number.isNaN(spySma200)) {
      await finish(
        "skipped:insufficient_history",
        `only ${closes.length} bars for SMA${config.regimeSmaDays}`,
      );
      return "skipped:insufficient_history";
    }

    const latest = await db.getLatestRegimeState();
    let currentState: State = (latest?.current_state as State) ?? "CASH";
    const killSwitchActive = latest?.kill_switch_active ?? false;

    let { targetState, killSwitchActive: newKs } = computeTargetState({
      spyClose,
      spySma200,
      currentState,
      killSwitchActive,
    });

    // Reconcile against broker truth.
    const qty = await alpaca.getPosition(config.botTicker);
    const brokerState: State = qty > 0 ? "LONG" : "CASH";
    if (brokerState !== currentState) {
      await notifications.notifyStateDesync({
        dbState: currentState,
        brokerState,
        symbol: config.botTicker,
        actionTaken: `DB updated to ${brokerState}`,
      });
      currentState = brokerState;
      ({ targetState, killSwitchActive: newKs } = computeTargetState({
        spyClose,
        spySma200,
        currentState,
        killSwitchActive,
      }));
    }

    let newCurrentState: State = currentState;
    const outcome = "success";
    // #383 T3/D1: hoisted so it can be filled in by the flip branch below (a
    // read already needed for sizing/notification) or, on a no-flip day,
    // reused-or-fetched once more just before the equity snapshot write —
    // either way alpaca.getAccountValue() is called exactly once per run.
    let accountValue: number | undefined;

    if (targetState !== currentState) {
      // Concurrency guard (#293): at most one order per trading day. The first
      // invocation to INSERT into trade_claims wins; a concurrent invocation
      // racing on the same (script_name, trade_date) PK gets a unique-violation
      // and must back off, not place a duplicate order.
      const claimed = await db.claimTradeDate("daily-check", ymd(deps.now()));
      if (!claimed) {
        await finish(
          "skipped:duplicate_run",
          "trade_claims conflict: another invocation claimed this date",
        );
        return "skipped:duplicate_run";
      }

      // Read account value once, before any order, so a transient read failure
      // errors cleanly pre-trade rather than after a fill — a post-fill read
      // failure would skip the state write and mislabel a completed trade as
      // error. Reused by both the LONG (sizing) and CASH (notification) paths,
      // and by the end-of-run equity snapshot (D1) so it is fetched only once.
      accountValue = await alpaca.getAccountValue();
      if (targetState === "LONG") {
        const vehiclePrice = await marketdata.getLatestTradePrice(config.botTicker);
        const targetQty = Math.floor((accountValue * 0.99) / vehiclePrice);
        if (targetQty <= 0) {
          await notifications.notifyTradeFailed({
            symbol: config.botTicker,
            side: "BUY",
            qty: 0,
            reason: "insufficient_buying_power",
          });
          await finish("error:insufficient_funds");
          return "error:insufficient_funds";
        }
        const fill = await alpaca.placeMarketOrder({
          symbol: config.botTicker,
          side: "BUY",
          qty: targetQty,
        });
        await db.insertTrade({
          symbol: config.botTicker,
          side: "BUY",
          qty: fill.qty,
          fillPrice: fill.fillPrice,
          fillTime: fill.fillTime,
          brokerOrderId: fill.orderId,
          reason: "regime_flip_long",
        });
        await notifications.notifyRegimeFlip({
          targetState: "LONG",
          spyClose,
          spySma200,
          ticker: config.botTicker,
          fillPrice: fill.fillPrice,
          qty: fill.qty,
          accountValue,
        });
        newCurrentState = "LONG";
      } else {
        const fill = await alpaca.liquidate(config.botTicker);
        if (fill) {
          await db.insertTrade({
            symbol: config.botTicker,
            side: "SELL",
            qty: fill.qty,
            fillPrice: fill.fillPrice,
            fillTime: fill.fillTime,
            brokerOrderId: fill.orderId,
            reason: "regime_flip_cash",
          });
          await notifications.notifyRegimeFlip({
            targetState: "CASH",
            spyClose,
            spySma200,
            ticker: config.botTicker,
            fillPrice: fill.fillPrice,
            qty: fill.qty,
            accountValue,
          });
          newCurrentState = "CASH";
        } else {
          await notifications.notifyTradeFailed({
            symbol: config.botTicker,
            side: "SELL",
            qty,
            reason: "liquidate_returned_null",
          });
          await finish(
            "error:liquidate_failed",
            `liquidate(${config.botTicker}) returned null; current pinned at ${currentState}`,
          );
          return "error:liquidate_failed";
        }
      }
    }

    await db.upsertRegimeState({
      date: ymd(deps.now()),
      spyClose,
      spySma200,
      targetState,
      currentState: newCurrentState,
      positionDrawdownPct: null,
      killSwitchActive: newKs,
      // Forensic timestamp of the last kill-switch fire (finding 10): carry it
      // through even when the flag clears (e.g. same-day bullish re-entry) —
      // never overwrite it with null once it exists.
      killSwitchFiredAt: latest?.kill_switch_fired_at ?? null,
    });

    // #383 T3/D1/D2: one equity_snapshots row per trading day, including
    // no-flip days — required for the trailing-return windows to have data
    // most days rather than only on the few-times-a-year regime flips.
    // Ordered after upsertRegimeState (D2) so a snapshot-write failure can
    // never block the trading-critical state write.
    if (accountValue === undefined) accountValue = await alpaca.getAccountValue();
    try {
      await db.upsertEquitySnapshot({ date: ymd(deps.now()), equityUsd: accountValue });
    } catch (snapshotErr) {
      // #383 D4: the snapshot is a non-critical reporting side-effect. By this
      // point the trade (if any) has filled and upsertRegimeState has already
      // succeeded, so a write failure here must never propagate to the outer
      // catch and mislabel a completed, state-persisted trade day as
      // `error:*`. Warn (no secrets/PII, matching the notifications.ts
      // console.warn style) and continue to the normal outcome; it self-heals
      // on the next run (target==current -> no re-trade -> snapshot retried).
      console.warn(
        `daily-check: equity snapshot write failed: ${(snapshotErr as Error).message}`,
      );
    }

    await finish(outcome, `target=${targetState} current=${newCurrentState}`);
    return outcome;
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await deps.notifications.notifyBrokerError({ context: "daily-check", errorMsg: err.message });
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
