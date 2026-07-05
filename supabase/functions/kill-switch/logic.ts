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
    getLatestQuote: (symbol: string) => Promise<{ bid: number; ask: number; mid: number }>;
  };
  alpaca: {
    getClock: () => Promise<{ isOpen: boolean }>;
    getPosition: (symbol: string) => Promise<number>;
    liquidate: (symbol: string) => Promise<Fill | null>;
  };
  db: {
    getLatestRegimeState: () => Promise<RegimeStateRow | null>;
    claimTradeDate: (scriptName: string, tradeDate: string) => Promise<boolean>;
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
    updateAuditLog: (
      p: { id: number; finishedAt: string; outcome: string; notes?: string | null },
    ) => Promise<void>;
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
    notifyTradeFailed: (
      p: { symbol: string; side: "BUY" | "SELL"; qty: number; reason: string },
    ) => Promise<void>;
    notifyBrokerError: (p: { context: string; errorMsg: string }) => Promise<void>;
    notifyStateDesync: (p: {
      dbState: "LONG" | "CASH";
      brokerState: "LONG" | "CASH";
      symbol: string;
      actionTaken: string;
    }) => Promise<void>;
    notifyError: (message: string) => Promise<void>;
  };
}

export async function runKillSwitch(deps: KillSwitchDeps): Promise<string> {
  const { config, db, alpaca, marketdata, notifications } = deps;
  const iso = (d: Date) => d.toISOString();
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const auditId = await db.insertAuditLog({
    scriptName: "kill-switch",
    startedAt: iso(deps.now()),
  });
  // desyncNote (#266) is prepended to every audit-notes write once a DB/broker
  // state desync is detected, so the forensic trail survives in audit_log.
  let desyncNote = "";
  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({
      id: auditId,
      finishedAt: iso(deps.now()),
      outcome,
      notes: desyncNote === "" ? notes : `${desyncNote}${notes ?? ""}`,
    });

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
      desyncNote = `state_desync db=${latest?.current_state ?? "none"} broker=LONG qty=${qty}; `;
      await notifications.notifyStateDesync({
        dbState,
        brokerState: "LONG",
        symbol: config.botTicker,
        actionTaken: "kill-switch continuing drawdown check on the live position",
      });
    }

    // With no regime_state row at all (anomalous — daily-check writes a row
    // every weekday) the drawdown check still continues so the live position
    // stays protected (#266): the regime_state upserts below are skipped (no
    // SPY data here to satisfy the NOT NULL spy_close/spy_sma200 columns) and
    // daily-check resyncs the DB on its next run.

    if (!(await alpaca.getClock()).isOpen) {
      await finish("skipped:market_closed");
      return "skipped:market_closed";
    }

    const barsArr = await marketdata.getDailyCloses(
      config.botTicker,
      config.killSwitchLookbackDays + 10,
    );
    if (barsArr.length < config.killSwitchLookbackDays) {
      await finish(
        "skipped:insufficient_data",
        `only ${barsArr.length} bars, need ${config.killSwitchLookbackDays}`,
      );
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

    // Plausibility guard (#265): a >50% drop from the lookback high is impossible
    // for a 3x ETF inside a ~30-day window without a corporate action (e.g. an
    // unadjusted forward split) or a bad print. Do NOT liquidate on such data —
    // alert the operator and exit non-fatally instead.
    if (refHigh / lastPrice > 2) {
      const msg = `kill-switch: implausible drawdown for ${config.botTicker}: ` +
        `refHigh=${refHigh} lastPrice=${lastPrice} (ratio ${
          (refHigh / lastPrice).toFixed(2)
        } > 2); ` +
        `suspected corporate action or bad data — NOT liquidating`;
      await notifications.notifyError(msg);
      await finish("error:implausible_drawdown", msg);
      return "error:implausible_drawdown";
    }

    const drawdown = lastPrice / refHigh - 1;

    // Persist drawdown update (still LONG at this point). Skipped only when no
    // regime_state row exists at all (#266 desync path) — there is no SPY data
    // in this function to seed one, and daily-check resyncs on its next run.
    if (latest) {
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
    }

    if (drawdown > -config.killSwitchDrawdownPct) {
      await finish("success:within_threshold", `dd=${drawdown.toFixed(4)}`);
      return "success:within_threshold";
    }

    // B1b dual-breach confirmation (#269 finding 8): a single thin-feed (IEX)
    // trade print must not liquidate the 3x position alone. Confirm against the
    // quote midpoint; fire only if BOTH breach. The fetch is wrapped LOCALLY so a
    // quote OUTAGE fails toward protection (fire on trade alone) and never falls
    // through to the outer catch (which returns error:* and would disarm the
    // switch). Placed BEFORE the #293 claim so an unconfirmed breach consumes no
    // claim and a later real breach the same day can still fire.
    let confirmation: "confirmed" | "unverified_quote_outage" = "unverified_quote_outage";
    let fireMid: number | null = null;
    try {
      const quote = await marketdata.getLatestQuote(config.botTicker);
      const midDrawdown = quote.mid / refHigh - 1;
      if (midDrawdown > -config.killSwitchDrawdownPct) {
        const msg = `breach unconfirmed: trade dd=${drawdown.toFixed(4)} (px=${lastPrice}) ` +
          `but quote-mid dd=${midDrawdown.toFixed(4)} (mid=${quote.mid}) within threshold — NOT liquidating`;
        await notifications.notifyError(`kill-switch: ${msg}`);
        await finish("skipped:breach_unconfirmed", msg);
        return "skipped:breach_unconfirmed";
      }
      // both breach -> fall through to claim + liquidate
      confirmation = "confirmed";
      fireMid = quote.mid;
    } catch (e) {
      await notifications.notifyError(
        `kill-switch: quote fetch failed for ${config.botTicker} ` +
          `(${String((e as Error)?.message ?? e).slice(0, 200)}) — liquidating on trade price alone (fail-toward-protection)`,
      );
      // confirmation stays "unverified_quote_outage"; fall through to claim + liquidate
    }

    // Concurrency guard (#293): at most one liquidation per trading day. Place
    // the claim as the last gate before liquidate so a non-breaching tick
    // consumes no claim and a later-that-day real breach can still fire.
    // NOTE: fail-toward-no-protection — after the kill-switch fires (claim
    // taken), a same-day manual/desync re-entry cannot be re-protected that day,
    // and a claim-then-crash suppresses that position's liquidation until the
    // next daily-check resyncs. This is in-spec given "at most one order per
    // trading day" but is a real behavior change (stated in PR description).
    const claimed = await db.claimTradeDate("kill-switch", ymd(deps.now()));
    if (!claimed) {
      await finish("skipped:duplicate_run", "trade_claims conflict: another invocation already liquidated today");
      return "skipped:duplicate_run";
    }

    // Threshold breached — liquidate.
    const fill = await alpaca.liquidate(config.botTicker);

    // Persist the flip to CASH + kill_switch_active FIRST, before insertTrade or
    // the notification, so a later DB/notify failure cannot erase the fact that
    // the kill-switch fired (#238). Runs whether or not there was a position to
    // sell, but is skipped when no regime_state row exists (#266 desync path).
    if (latest) {
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
    }

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
    const midNote = fireMid !== null ? ` mid=${fireMid}` : "";
    await finish(
      "success:kill_switch_fired",
      `dd=${drawdown.toFixed(4)}${midNote} confirmation=${confirmation}`,
    );
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
