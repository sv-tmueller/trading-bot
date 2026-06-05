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
    getPosition: (symbol: string) => Promise<number>;
    getAccountValue: () => Promise<number>;
    placeMarketOrder: (a: { symbol: string; side: "BUY" | "SELL"; qty: number }) => Promise<Fill>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    getConfig: (key: string) => Promise<string | null>;
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
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
    updateAuditLog: (p: { id: number; finishedAt: string; outcome: string; notes?: string | null }) => Promise<void>;
  };
  notifications: {
    notifyRegimeFlip: (p: {
      targetState: State; spyClose: number; spySma200: number; ticker: string;
      fillPrice: number; qty: number; accountValue: number; dryRun?: boolean;
    }) => Promise<void>;
    notifyStateDesync: (p: { dbState: State; brokerState: State; symbol: string; actionTaken: string }) => Promise<void>;
    notifyTradeFailed: (p: { symbol: string; side: "BUY" | "SELL"; qty: number; reason: string }) => Promise<void>;
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

  // Operational pause.
  const paused = (await db.getConfig("paused"))?.toLowerCase() === "true";
  if (paused) {
    await finish("skipped:trading_paused", "bot_config.paused is true");
    return "skipped:trading_paused";
  }

  try {
    const barsArr = await marketdata.getDailyCloses(config.botBenchmark, config.regimeSmaDays + 10);
    if (barsArr.length === 0) {
      await finish("skipped:stale_data", "no bars returned");
      return "skipped:stale_data";
    }
    const lastBar = barsArr[barsArr.length - 1];
    if (lastBar.date < ymd(deps.now())) {
      await finish("skipped:stale_data", `last bar=${lastBar.date}, today=${ymd(deps.now())}`);
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
      await finish("skipped:insufficient_history", `only ${closes.length} bars for SMA${config.regimeSmaDays}`);
      return "skipped:insufficient_history";
    }

    const latest = await db.getLatestRegimeState();
    let currentState: State = (latest?.current_state as State) ?? "CASH";
    const killSwitchActive = latest?.kill_switch_active ?? false;

    let { targetState, killSwitchActive: newKs } = computeTargetState({
      spyClose, spySma200, currentState, killSwitchActive,
    });

    // Reconcile against broker truth.
    const qty = await alpaca.getPosition(config.botTicker);
    const brokerState: State = qty > 0 ? "LONG" : "CASH";
    if (brokerState !== currentState) {
      await notifications.notifyStateDesync({
        dbState: currentState, brokerState, symbol: config.botTicker,
        actionTaken: `DB updated to ${brokerState}`,
      });
      currentState = brokerState;
      ({ targetState, killSwitchActive: newKs } = computeTargetState({
        spyClose, spySma200, currentState, killSwitchActive,
      }));
    }

    let newCurrentState: State = currentState;
    let outcome = "success";

    if (targetState !== currentState) {
      if (targetState === "LONG") {
        const accountValue = await alpaca.getAccountValue();
        const vehiclePrice = await marketdata.getLatestTradePrice(config.botTicker);
        const targetQty = Math.floor((accountValue * 0.99) / vehiclePrice);
        if (targetQty <= 0) {
          await notifications.notifyTradeFailed({ symbol: config.botTicker, side: "BUY", qty: 0, reason: "insufficient_buying_power" });
          await finish("error:insufficient_funds");
          return "error:insufficient_funds";
        }
        const fill = await alpaca.placeMarketOrder({ symbol: config.botTicker, side: "BUY", qty: targetQty });
        await db.insertTrade({
          symbol: config.botTicker, side: "BUY", qty: fill.qty, fillPrice: fill.fillPrice,
          fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "regime_flip_long",
        });
        await notifications.notifyRegimeFlip({
          targetState: "LONG", spyClose, spySma200, ticker: config.botTicker,
          fillPrice: fill.fillPrice, qty: fill.qty, accountValue,
        });
        newCurrentState = "LONG";
      } else {
        const fill = await alpaca.liquidate(config.botTicker);
        if (fill) {
          await db.insertTrade({
            symbol: config.botTicker, side: "SELL", qty: fill.qty, fillPrice: fill.fillPrice,
            fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "regime_flip_cash",
          });
          await notifications.notifyRegimeFlip({
            targetState: "CASH", spyClose, spySma200, ticker: config.botTicker,
            fillPrice: fill.fillPrice, qty: fill.qty, accountValue: await alpaca.getAccountValue(),
          });
          newCurrentState = "CASH";
        } else {
          await notifications.notifyTradeFailed({ symbol: config.botTicker, side: "SELL", qty, reason: "liquidate_returned_null" });
          await finish("error:liquidate_failed", `liquidate(${config.botTicker}) returned null; current pinned at ${currentState}`);
          return "error:liquidate_failed";
        }
      }
    }

    await db.upsertRegimeState({
      date: ymd(deps.now()), spyClose, spySma200, targetState, currentState: newCurrentState,
      positionDrawdownPct: null, killSwitchActive: newKs,
      killSwitchFiredAt: latest && newKs ? latest.kill_switch_fired_at : null,
    });
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
