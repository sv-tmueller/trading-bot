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
      symbol: string; side: "BUY" | "SELL"; qty: number; fillPrice: number; fillTime: string;
      brokerOrderId: string; reason: "regime_flip_long" | "regime_flip_cash" | "kill_switch" | "panic_cli";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (p: { id: number; finishedAt: string; outcome: string; notes?: string | null }) => Promise<void>;
  };
  notifications: { notifyPanic: (p: { action: string; result: string }) => Promise<void> };
}

export interface PanicResult {
  ok: boolean;
  result: string;
}

export async function runPanic(deps: PanicDeps, action: PanicAction): Promise<PanicResult> {
  const { db, alpaca, config } = deps;
  const iso = (d: Date) => d.toISOString();
  // Audit row is written BEFORE any broker call (recoverable on partial run).
  const auditId = await db.insertAuditLog({ scriptName: "panic", startedAt: iso(deps.now()) });
  let ok = false;
  let result = "";
  let err: Error | null = null;
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
            symbol: config.botTicker, side: "SELL", qty: fill.qty, fillPrice: fill.fillPrice,
            fillTime: fill.fillTime, brokerOrderId: fill.orderId, reason: "panic_cli",
          });
          result = `liquidated ${fill.qty} ${config.botTicker} @ ${fill.fillPrice}`;
        } else {
          result = "no position to liquidate";
        }
        break;
      }
      default:
        throw new Error(`unknown action: ${action}`);
    }
    ok = true;
    // Notify fire-and-forget — a notification failure must not flip a
    // successful action's outcome to error.
    try {
      await deps.notifications.notifyPanic({ action, result });
    } catch (_e) { /* fire-and-forget */ }
  } catch (e) {
    err = e as Error;
    result = `${err.name}: ${err.message}`;
  } finally {
    // Single point that closes the audit row — matches the documented
    // "updated in a finally" contract and avoids a double-update.
    const outcome = ok ? "success:panic" : `error:${err?.name}`;
    const notes = ok ? `${action}: ${result}` : `${action}: ${err?.message}`.slice(0, 500);
    await db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });
  }
  return { ok, result };
}
