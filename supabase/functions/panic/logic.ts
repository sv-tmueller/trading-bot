import type { Fill } from "../_shared/alpaca.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export type PanicAction = "pause" | "resume" | "cancel-orders" | "liquidate";

export interface PanicDeps {
  config: StrategyConfig;
  now: () => Date;
  alpaca: {
    cancelAllOrders: () => Promise<number>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    setConfig: (key: string, value: string) => Promise<void>;
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
  };
  notifications: { notifyPanic: (p: { action: string; result: string }) => Promise<void> };
}

export async function runPanic(deps: PanicDeps, action: PanicAction): Promise<string> {
  const { db, alpaca, config } = deps;
  const iso = (d: Date) => d.toISOString();
  // Audit row is written BEFORE any broker call (recoverable on partial run).
  const auditId = await db.insertAuditLog({ scriptName: "panic", startedAt: iso(deps.now()) });
  let result = "";
  try {
    switch (action) {
      case "pause":
        await db.setConfig("paused", "true");
        result = "paused";
        break;
      case "resume":
        await db.setConfig("paused", "false");
        result = "resumed";
        break;
      case "cancel-orders": {
        const n = await alpaca.cancelAllOrders();
        result = `cancelled ${n} orders`;
        break;
      }
      case "liquidate": {
        const fill = await alpaca.liquidate(config.botTicker);
        if (fill) {
          await db.insertTrade({
            symbol: config.botTicker,
            side: "SELL",
            qty: fill.qty,
            fillPrice: fill.fillPrice,
            fillTime: fill.fillTime,
            brokerOrderId: fill.orderId,
            reason: "panic_cli",
          });
          result = `liquidated ${fill.qty} ${config.botTicker} @ ${fill.fillPrice}`;
        } else {
          result = "no position to liquidate";
        }
        // Finding 13: a successful liquidate also pauses, otherwise a still-
        // bullish SPY would make the next daily-check re-buy the position the
        // operator just dumped. Clear with action=resume.
        await db.setConfig("paused", "true");
        result += "; trading paused";
        break;
      }
      default:
        throw new Error(`unknown action: ${action}`);
    }
    // Close the audit row FIRST, then notify fire-and-forget — a notification
    // failure must not flip a successful action's outcome to error.
    await db.updateAuditLog({
      id: auditId,
      finishedAt: iso(deps.now()),
      outcome: "success:panic",
      notes: `${action}: ${result}`,
    });
    try {
      await deps.notifications.notifyPanic({ action, result });
    } catch (_e) { /* fire-and-forget */ }
    return result;
  } catch (e) {
    const err = e as Error;
    const outcome = `error:${err.name}`;
    await db.updateAuditLog({
      id: auditId,
      finishedAt: iso(deps.now()),
      outcome,
      notes: `${action}: ${err.message}`.slice(0, 500),
    });
    return `${outcome}: ${err.message}`;
  }
}
