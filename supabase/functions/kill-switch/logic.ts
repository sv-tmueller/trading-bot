import type { Fill } from "../_shared/alpaca.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";
import type { RegimeStateRow } from "../_shared/db.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export interface KillSwitchDeps {
  config: StrategyConfig;
  now: () => Date;
  marketdata: {
    getDailyCloses: (symbol: string, count: number) => Promise<DailyBar[]>;
    getLatestTradePrice: (symbol: string) => Promise<number>;
  };
  alpaca: {
    getClock: () => Promise<{ isOpen: boolean }>;
    getPosition: (symbol: string) => Promise<number>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
    upsertRegimeState: (p: {
      date: string;
      spyClose: number;
      spySma200: number;
      targetState: "LONG" | "CASH";
      currentState: "LONG" | "CASH";
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
    updateAuditLog: (p: { id: number; finishedAt: string; outcome: string; notes?: string | null }) => Promise<void>;
  };
  notifications: {
    notifyKillSwitchFired: (p: {
      ticker: string;
      drawdownPct: number;
      refHigh: number;
      lastPrice: number;
      qty: number;
      fillPrice: number;
    }) => Promise<void>;
    notifyTradeFailed: (p: { symbol: string; side: "BUY" | "SELL"; qty: number; reason: string }) => Promise<void>;
    notifyBrokerError: (p: { context: string; errorMsg: string }) => Promise<void>;
    notifyStateDesync: (
      p: { dbState: "LONG" | "CASH"; brokerState: "LONG" | "CASH"; symbol: string; actionTaken: string },
    ) => Promise<void>;
  };
}

export async function runKillSwitch(deps: KillSwitchDeps): Promise<string> {
  const { config, db, alpaca, marketdata, notifications } = deps;
  const iso = (d: Date) => d.toISOString();
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const auditId = await db.insertAuditLog({ scriptName: "kill-switch", startedAt: iso(deps.now()) });
  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });

  try {
    const latest = await db.getLatestRegimeState();

    // Reconcile against broker truth: the kill-switch protects the ACTUAL
    // position, not the DB's belief, so a DB/broker desync can't leave a real
    // position unprotected (#237). The broker is the source of truth for
    // "is there a position".
    const qty = await alpaca.getPosition(config.botTicker);
    if (qty <= 0) {
      await finish("success:no_position");
      return "success:no_position";
    }

    // Broker holds a position. If the DB didn't know, surface the desync.
    const dbState: "LONG" | "CASH" = latest?.current_state === "LONG" ? "LONG" : "CASH";
    if (dbState !== "LONG") {
      await notifications.notifyStateDesync({
        dbState,
        brokerState: "LONG",
        symbol: config.botTicker,
        actionTaken: "kill-switch protecting live broker position",
      });
    }

    if (!latest) {
      // Position exists but there is no regime_state row to carry forward
      // (spy_close/spy_sma200 are NOT NULL). Anomalous — daily-check writes a row
      // every weekday — so surface it (desync already notified) and skip rather
      // than fabricate regime values for the audit row.
      await finish("skipped:no_regime_state", `broker qty=${qty} but no regime_state row`);
      return "skipped:no_regime_state";
    }

    if (!(await alpaca.getClock()).isOpen) {
      await finish("skipped:market_closed");
      return "skipped:market_closed";
    }

    const barsArr = await marketdata.getDailyCloses(config.botTicker, config.killSwitchLookbackDays + 10);
    if (barsArr.length < config.killSwitchLookbackDays) {
      await finish("skipped:insufficient_data", `only ${barsArr.length} bars, need ${config.killSwitchLookbackDays}`);
      return "skipped:insufficient_data";
    }

    // Intraday-stop design (spec §4), NOT the old daily-close hourly logic in
    // monitor/kill_switch.py: reference high = max of recent daily *highs* plus
    // today's last trade, so we measure drawdown from the actual recent peak.
    // Including lastPrice means a fresh high yields drawdown 0 (can't fire) —
    // intended: you can't be in drawdown while at a new high.
    const lastPrice = await marketdata.getLatestTradePrice(config.botTicker);
    const recentHighs = barsArr.slice(-config.killSwitchLookbackDays).map((b) => b.high);
    const refHigh = Math.max(...recentHighs, lastPrice);
    const drawdown = lastPrice / refHigh - 1;

    // Persist drawdown update (still LONG at this point).
    await db.upsertRegimeState({
      date: ymd(deps.now()),
      spyClose: latest.spy_close,
      spySma200: latest.spy_sma200,
      targetState: latest.target_state,
      currentState: "LONG",
      positionDrawdownPct: drawdown,
      killSwitchActive: latest.kill_switch_active,
      killSwitchFiredAt: latest.kill_switch_fired_at,
    });

    if (drawdown > -config.killSwitchDrawdownPct) {
      await finish("success:within_threshold", `dd=${drawdown.toFixed(4)}`);
      return "success:within_threshold";
    }

    // Threshold breached — liquidate.
    const fill = await alpaca.liquidate(config.botTicker);

    // Persist the flip to CASH + kill_switch_active FIRST, before insertTrade or
    // the notification, so a later DB/notify failure cannot erase the fact that
    // the kill-switch fired. Runs whether or not there was a position to sell.
    await db.upsertRegimeState({
      date: ymd(deps.now()),
      spyClose: latest.spy_close,
      spySma200: latest.spy_sma200,
      targetState: "CASH",
      currentState: "CASH",
      positionDrawdownPct: drawdown,
      killSwitchActive: true,
      killSwitchFiredAt: iso(deps.now()),
    });

    if (fill === null) {
      // Position already gone — state is flipped above; no fill to record.
      await finish("success:no_position_to_liquidate");
      return "success:no_position_to_liquidate";
    }

    await db.insertTrade({
      symbol: config.botTicker,
      side: "SELL",
      qty: fill.qty,
      fillPrice: fill.fillPrice,
      fillTime: fill.fillTime,
      brokerOrderId: fill.orderId,
      reason: "kill_switch",
    });
    await notifications.notifyKillSwitchFired({
      ticker: config.botTicker,
      drawdownPct: drawdown,
      refHigh,
      lastPrice,
      qty: fill.qty,
      fillPrice: fill.fillPrice,
    });
    await finish("success:kill_switch_fired", `dd=${drawdown.toFixed(4)}`);
    return "success:kill_switch_fired";
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await notifications.notifyBrokerError({ context: "kill-switch", errorMsg: err.message });
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
