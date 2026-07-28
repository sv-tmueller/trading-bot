import type { Fill, OpenPosition } from "../_shared/alpaca.ts";
import type { StrategyConfig } from "../_shared/config.ts";

export type PanicAction = "pause" | "resume" | "cancel-orders" | "liquidate";

export interface PanicDeps {
  config: StrategyConfig;
  now: () => Date;
  alpaca: {
    cancelAllOrders: () => Promise<number>;
    // #474 D1/§8.2: side-aware + symbol-aware -- panic must be able to flatten
    // whatever position is actually held (short or long, any symbol), not
    // just a hardcoded long-only config.botTicker liquidate.
    getOpenPositions: () => Promise<OpenPosition[]>;
    closePosition: (symbol: string) => Promise<Fill | null>;
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

export interface PanicResult {
  ok: boolean;
  result: string;
}

export interface PanicOpts {
  // Finding 13 (2026-06-11 review) / issue #185 option 1: a successful
  // liquidate ALSO pauses trading by default, so the next daily-check cannot
  // re-buy the position the operator just dumped while SPY is still bullish.
  // Explicit opt-out (?pause=false) supports the brief-flatten-then-auto-resume
  // workflow. A failed liquidation never pauses.
  pauseOnLiquidate?: boolean;
}

export async function runPanic(
  deps: PanicDeps,
  action: PanicAction,
  opts: PanicOpts = {},
): Promise<PanicResult> {
  const { db, alpaca } = deps;
  const pauseOnLiquidate = opts.pauseOnLiquidate ?? true;
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
        // #474 D1/§8.2: flatten whatever is actually held, side-aware and
        // symbol-aware -- not a hardcoded long-only config.botTicker
        // liquidate. This is NOT a kill-switch fire, so it never writes the
        // hourly_kill_switch_* keys (paused=true is its own gate instead).
        const positions = await alpaca.getOpenPositions();
        const parts: string[] = [];
        for (const position of positions) {
          const fill = await alpaca.closePosition(position.symbol);
          if (fill === null) continue;
          const side: "BUY" | "SELL" = position.qty > 0 ? "SELL" : "BUY";
          await db.insertTrade({
            symbol: position.symbol,
            side,
            qty: fill.qty,
            fillPrice: fill.fillPrice,
            fillTime: fill.fillTime,
            brokerOrderId: fill.orderId,
            reason: "panic_cli",
          });
          const verb = position.qty > 0 ? "liquidated" : "covered";
          parts.push(`${verb} ${fill.qty} ${position.symbol} @ ${fill.fillPrice}`);
        }
        result = parts.length > 0 ? parts.join("; ") : "no position to liquidate";
        // Finding 13 / #185 option 1: pause AFTER a successful liquidation (a
        // throw above skips this), unless explicitly opted out via pause=false.
        // The result string always says which happened.
        if (pauseOnLiquidate) {
          await db.setConfig("paused", "true");
          result += "; trading paused";
        } else {
          result += "; trading NOT paused (pause=false)";
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
    try {
      await db.updateAuditLog({ id: auditId, finishedAt: iso(deps.now()), outcome, notes });
    } catch (_e) {
      /* audit-close failed: leave the row open (documented recoverable state); never mask the action result */
    }
  }
  return { ok, result };
}
