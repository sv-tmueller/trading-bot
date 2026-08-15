import type { Fill, OpenPosition } from "../_shared/alpaca.ts";
import { AlpacaError } from "../_shared/alpaca.ts";
import type { DailyBar } from "../_shared/marketdata.ts";
import type { RegimeStateRow } from "../_shared/db.ts";
import type { StrategyConfig } from "../_shared/config.ts";
import { DataError } from "../_shared/num.ts";

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
    // #474 D1: the safety stack is broker-position-driven -- getOpenPositions
    // discovers every open position instead of being keyed to config.botTicker.
    getOpenPositions: () => Promise<OpenPosition[]>;
    // #474 D1: side-aware close (SELL a long, BUY to cover a short).
    closePosition: (symbol: string) => Promise<Fill | null>;
    // #474 D4/§7 (Task 7): cancel resting bracket/OCO legs before closing a
    // position outside its own bracket, so a stale leg can't fire after the
    // position is already flat and open an unintended reverse position.
    cancelAllOrders: () => Promise<number>;
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
    // #474 D2: the hourly bot's post-fire flag, bot_config keys this package
    // only WRITES (never reads or clears -- the feature package, #475, owns
    // reading/gating/clearing).
    setConfig: (key: string, value: string) => Promise<void>;
    insertTrade: (p: {
      symbol: string;
      side: "BUY" | "SELL";
      qty: number;
      fillPrice: number;
      fillTime: string;
      brokerOrderId: string;
      reason:
        | "regime_flip_long"
        | "regime_flip_cash"
        | "kill_switch"
        | "hourly_kill_switch"
        | "panic_cli";
    }) => Promise<number>;
    insertAuditLog: (p: { scriptName: string; startedAt: string }) => Promise<number>;
    updateAuditLog: (
      p: { id: number; finishedAt: string; outcome: string; notes?: string | null },
    ) => Promise<void>;
  };
  notifications: {
    notifyKillSwitchFired: (p: {
      ticker: string;
      side: "LONG" | "SHORT";
      drawdownPct: number;
      refPrice: number;
      lastPrice: number;
      qty: number;
      fillPrice: number;
    }) => Promise<void>;
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
  // Only meaningful for the legacy botTicker branch -- regime_state has
  // nothing to say about any other position.
  let desyncNote = "";
  // qtyNote (#342) carries the broker-reported position qty on every subsequent
  // finish() call, so a forensic audit_log query always knows how many shares
  // were at risk. Set once a position is under evaluation.
  let qtyNote = "";
  const finish = (outcome: string, notes?: string) =>
    db.updateAuditLog({
      id: auditId,
      finishedAt: iso(deps.now()),
      outcome,
      notes: desyncNote === "" && qtyNote === ""
        ? notes
        : `${desyncNote}${notes ?? ""}${qtyNote}`.trimStart(),
    });

  try {
    // Broker is the source of truth for which position(s) exist (#237,
    // extended by D1 from "is there a position" to "which position(s)").
    const positions = await alpaca.getOpenPositions();
    if (positions.length === 0) {
      await finish("success:no_position");
      return "success:no_position";
    }

    // Intraday-stop design (spec §4/§8.1). isLegacy gates the regime_state/
    // desync persistence only (D2); the reference/implausibility/dual-breach
    // math is identical for a LONG position whether or not it's the legacy
    // botTicker.
    const checkLong = async (
      position: OpenPosition,
      latest: RegimeStateRow | null,
      barsArr: DailyBar[],
      lastPrice: number,
      isLegacy: boolean,
    ): Promise<string> => {
      const recentHighs = barsArr.slice(-config.killSwitchLookbackDays).map((b) => b.high);
      const refHigh = Math.max(...recentHighs, lastPrice);

      // Plausibility guard (#265): a >50% drop from the lookback high is
      // impossible without a corporate action or a bad print.
      if (refHigh / lastPrice > 2) {
        const msg = `kill-switch: implausible drawdown for ${position.symbol}: ` +
          `refHigh=${refHigh} lastPrice=${lastPrice} (ratio ${
            (refHigh / lastPrice).toFixed(2)
          } > 2); ` +
          `suspected corporate action or bad data — NOT liquidating`;
        await notifications.notifyError(msg);
        await finish("error:implausible_drawdown", msg);
        return "error:implausible_drawdown";
      }

      const drawdown = lastPrice / refHigh - 1;

      // Legacy-only: persist the running drawdown while still LONG. Skipped
      // when no regime_state row exists at all (#266 desync path) or this
      // isn't the legacy branch (D2: no running-drawdown persistence
      // anywhere for a non-legacy position; drawdown goes to audit notes).
      if (isLegacy && latest) {
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

      // B1b dual-breach confirmation (#269 finding 8, #352): confirm against
      // the quote bid (the realizable sale price for a down-breach). The
      // fetch is wrapped LOCALLY so a quote OUTAGE fails toward protection
      // and never falls through to the outer catch (which would disarm the
      // switch). Placed BEFORE the #293 claim so an unconfirmed breach
      // consumes no claim.
      let confirmation: "confirmed" | "unverified_quote_outage" = "unverified_quote_outage";
      let fireBid: number | null = null;
      try {
        const quote = await marketdata.getLatestQuote(position.symbol);
        const bidRatio = Math.max(quote.bid, lastPrice) / Math.min(quote.bid, lastPrice);
        if (bidRatio > 2) {
          throw new DataError(
            `implausible quote bid for ${position.symbol}: bid=${quote.bid} lastPrice=${lastPrice} (ratio ${
              bidRatio.toFixed(2)
            } > 2)`,
          );
        }
        const bidDrawdown = quote.bid / refHigh - 1;
        if (bidDrawdown > -config.killSwitchDrawdownPct) {
          const msg = `breach unconfirmed: trade dd=${drawdown.toFixed(4)} (px=${lastPrice}) ` +
            `but quote-bid dd=${
              bidDrawdown.toFixed(4)
            } (bid=${quote.bid}) within threshold — NOT liquidating`;
          await notifications.notifyError(`kill-switch: ${msg}`);
          await finish("skipped:breach_unconfirmed", msg);
          return "skipped:breach_unconfirmed";
        }
        confirmation = "confirmed";
        fireBid = quote.bid;
      } catch (e) {
        await notifications.notifyError(
          `kill-switch: quote fetch failed for ${position.symbol} ` +
            `(${
              String((e as Error)?.message ?? e).slice(0, 200)
            }) — liquidating on trade price alone (fail-toward-protection)`,
        );
      }

      // Concurrency guard (#293/D3): at most one close per trading day, still
      // date-keyed and shared across every position this run checks -- the
      // first breach to consume the claim wins; a later same-day breach on a
      // different position is skipped:duplicate_run (the disclosed residual).
      const claimed = await db.claimTradeDate("kill-switch", ymd(deps.now()));
      if (!claimed) {
        await finish(
          "skipped:duplicate_run",
          "trade_claims conflict: another invocation already closed a position today",
        );
        return "skipped:duplicate_run";
      }

      // Orphan-leg hazard (#474 D4, spec §7): closing a bracketed position
      // outside its own bracket can leave resting stop/target legs live at
      // the broker, which can fire after the position is already flat and
      // open an unintended reverse position. Cancel first and verify --
      // wrapped LOCALLY (fail-toward-protection: a running breach on a 3x or
      // short position outranks stale-leg risk, so a cancel failure must not
      // abort the close or route to the outer error:* catch).
      let cancelNote = "cancel=verified";
      try {
        await alpaca.cancelAllOrders();
      } catch (e) {
        cancelNote = `cancel=UNVERIFIED (${String((e as Error)?.message ?? e).slice(0, 100)})`;
        await notifications.notifyError(
          `kill-switch: cancelAllOrders failed before closing ${position.symbol} (${cancelNote}) — proceeding with the close anyway (fail-toward-protection)`,
        );
      }

      const fill = await alpaca.closePosition(position.symbol);

      // Persist the flip FIRST, before insertTrade or the notification, so a
      // later DB/notify failure cannot erase the fact that the kill-switch
      // fired (#238).
      if (isLegacy && latest) {
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
      } else if (!isLegacy) {
        await db.setConfig("hourly_kill_switch_active", "true");
        await db.setConfig("hourly_kill_switch_side", "LONG");
        await db.setConfig("hourly_kill_switch_fired_at", iso(deps.now()));
      }

      if (fill === null) {
        await finish("success:no_position_to_liquidate");
        return "success:no_position_to_liquidate";
      }

      await db.insertTrade({
        symbol: position.symbol,
        side: "SELL",
        qty: fill.qty,
        fillPrice: fill.fillPrice,
        fillTime: fill.fillTime,
        brokerOrderId: fill.orderId,
        // #543: the hourly (non-legacy) LONG fire attributes its trade as
        // "hourly_kill_switch" so the weekly journal and dashboard hourly_*
        // filters match it; the legacy botTicker fire keeps "kill_switch" so
        // retired-daily-bot trades do NOT leak into hourly-only views.
        reason: isLegacy ? "kill_switch" : "hourly_kill_switch",
      });
      await notifications.notifyKillSwitchFired({
        ticker: position.symbol,
        side: "LONG",
        drawdownPct: drawdown,
        refPrice: refHigh,
        lastPrice,
        qty: fill.qty,
        fillPrice: fill.fillPrice,
      });
      const bidNote = fireBid !== null ? ` bid=${fireBid}` : "";
      await finish(
        "success:kill_switch_fired",
        `dd=${drawdown.toFixed(4)}${bidNote} confirmation=${confirmation} ${cancelNote}`,
      );
      return "success:kill_switch_fired";
    };

    // Short mirror (spec §8.1): adverse excursion for a short is a RISE in
    // price, so the reference extreme is the rolling LOW (not high) plus
    // today's last trade -- refLow includes lastPrice so a fresh low yields
    // adverse 0 (can't fire), the mirror of the long path's "can't be in
    // drawdown at a new high."
    const checkShort = async (
      position: OpenPosition,
      barsArr: DailyBar[],
      lastPrice: number,
    ): Promise<string> => {
      const recentLows = barsArr.slice(-config.killSwitchLookbackDays).map((b) => {
        if (b.low === undefined) {
          throw new DataError(`missing bar low for ${position.symbol}`);
        }
        return b.low;
      });
      const refLow = Math.min(...recentLows, lastPrice);

      // Reciprocal implausibility guard (mirror of refHigh/lastPrice > 2):
      // a >2x rise from the lookback low is implausible without a corporate
      // action or a bad print.
      if (lastPrice / refLow > 2) {
        const msg = `kill-switch: implausible drawdown for ${position.symbol} (SHORT): ` +
          `refLow=${refLow} lastPrice=${lastPrice} (ratio ${
            (lastPrice / refLow).toFixed(2)
          } > 2); ` +
          `suspected corporate action or bad data — NOT covering`;
        await notifications.notifyError(msg);
        await finish("error:implausible_drawdown", msg);
        return "error:implausible_drawdown";
      }

      const adverse = lastPrice / refLow - 1;

      // D2: no running-drawdown persistence anywhere for a short -- there is
      // no regime_state analog for it; the value goes to audit notes only.
      if (adverse < config.killSwitchDrawdownPct) {
        await finish("success:within_threshold", `dd=${adverse.toFixed(4)}`);
        return "success:within_threshold";
      }

      // Dual-breach confirmation flips to the ASK (covering a short executes
      // at the ask, the mirror of the long path's bid rationale). Fail-toward-
      // protection on a quote outage or implausible ask is preserved.
      let confirmation: "confirmed" | "unverified_quote_outage" = "unverified_quote_outage";
      let fireAsk: number | null = null;
      try {
        const quote = await marketdata.getLatestQuote(position.symbol);
        const askRatio = Math.max(quote.ask, lastPrice) / Math.min(quote.ask, lastPrice);
        if (askRatio > 2) {
          throw new DataError(
            `implausible quote ask for ${position.symbol}: ask=${quote.ask} lastPrice=${lastPrice} (ratio ${
              askRatio.toFixed(2)
            } > 2)`,
          );
        }
        const askAdverse = quote.ask / refLow - 1;
        if (askAdverse < config.killSwitchDrawdownPct) {
          const msg = `breach unconfirmed: trade dd=${adverse.toFixed(4)} (px=${lastPrice}) ` +
            `but quote-ask dd=${
              askAdverse.toFixed(4)
            } (ask=${quote.ask}) within threshold — NOT covering`;
          await notifications.notifyError(`kill-switch: ${msg}`);
          await finish("skipped:breach_unconfirmed", msg);
          return "skipped:breach_unconfirmed";
        }
        confirmation = "confirmed";
        fireAsk = quote.ask;
      } catch (e) {
        await notifications.notifyError(
          `kill-switch: quote fetch failed for ${position.symbol} ` +
            `(${
              String((e as Error)?.message ?? e).slice(0, 200)
            }) — covering on trade price alone (fail-toward-protection)`,
        );
      }

      const claimed = await db.claimTradeDate("kill-switch", ymd(deps.now()));
      if (!claimed) {
        await finish(
          "skipped:duplicate_run",
          "trade_claims conflict: another invocation already closed a position today",
        );
        return "skipped:duplicate_run";
      }

      // Orphan-leg hazard (#474 D4, spec §7): same cancel-before-close as the
      // long path, wrapped LOCALLY so a cancel failure never aborts the close
      // or routes to the outer error:* catch.
      let cancelNote = "cancel=verified";
      try {
        await alpaca.cancelAllOrders();
      } catch (e) {
        cancelNote = `cancel=UNVERIFIED (${String((e as Error)?.message ?? e).slice(0, 100)})`;
        await notifications.notifyError(
          `kill-switch: cancelAllOrders failed before closing ${position.symbol} (${cancelNote}) — proceeding with the close anyway (fail-toward-protection)`,
        );
      }

      const fill = await alpaca.closePosition(position.symbol);

      // D2: a short is never the legacy branch -- always write the hourly keys.
      await db.setConfig("hourly_kill_switch_active", "true");
      await db.setConfig("hourly_kill_switch_side", "SHORT");
      await db.setConfig("hourly_kill_switch_fired_at", iso(deps.now()));

      if (fill === null) {
        await finish("success:no_position_to_liquidate");
        return "success:no_position_to_liquidate";
      }

      await db.insertTrade({
        symbol: position.symbol,
        side: "BUY",
        qty: fill.qty,
        fillPrice: fill.fillPrice,
        fillTime: fill.fillTime,
        brokerOrderId: fill.orderId,
        // #543: a short is never the legacy branch (always hourly), so its
        // trade attributes as "hourly_kill_switch".
        reason: "hourly_kill_switch",
      });
      await notifications.notifyKillSwitchFired({
        ticker: position.symbol,
        side: "SHORT",
        drawdownPct: adverse,
        refPrice: refLow,
        lastPrice,
        qty: fill.qty,
        fillPrice: fill.fillPrice,
      });
      const askNote = fireAsk !== null ? ` ask=${fireAsk}` : "";
      await finish(
        "success:kill_switch_fired",
        `dd=${adverse.toFixed(4)}${askNote} confirmation=${confirmation} ${cancelNote}`,
      );
      return "success:kill_switch_fired";
    };

    // checkOnePosition runs the full drawdown check for a single open
    // position and returns the run's outcome for it, calling finish() itself
    // (matching the original single-position control flow exactly).
    const checkOnePosition = async (position: OpenPosition): Promise<string> => {
      qtyNote = ` qty=${position.qty}`;
      const side: "LONG" | "SHORT" = position.qty > 0 ? "LONG" : "SHORT";
      // D2: the legacy persistence path (desync check, regime_state upserts)
      // applies iff this is a LONG position in config.botTicker -- the
      // incumbent bot's own position. Every other fire writes the
      // hourly_kill_switch_* keys instead.
      const isLegacy = side === "LONG" && position.symbol === config.botTicker;

      let latest: RegimeStateRow | null = null;
      if (isLegacy) {
        latest = await db.getLatestRegimeState();
        const dbState: "LONG" | "CASH" = latest?.current_state === "LONG" ? "LONG" : "CASH";
        if (dbState !== "LONG") {
          desyncNote = `state_desync db=${latest?.current_state ?? "none"} broker=LONG; `;
          await notifications.notifyStateDesync({
            dbState,
            brokerState: "LONG",
            symbol: position.symbol,
            actionTaken: "kill-switch continuing drawdown check on the live position",
          });
        }
      }

      if (!(await alpaca.getClock()).isOpen) {
        await finish("skipped:market_closed");
        return "skipped:market_closed";
      }

      const barsArr = await marketdata.getDailyCloses(
        position.symbol,
        config.killSwitchLookbackDays + 10,
      );
      if (barsArr.length < config.killSwitchLookbackDays) {
        await finish(
          "skipped:insufficient_data",
          `only ${barsArr.length} bars, need ${config.killSwitchLookbackDays}`,
        );
        return "skipped:insufficient_data";
      }

      const lastPrice = await marketdata.getLatestTradePrice(position.symbol);
      if (side === "LONG") {
        return await checkLong(position, latest, barsArr, lastPrice, isLegacy);
      }
      return await checkShort(position, barsArr, lastPrice);
    };

    // Defensively iterate every open position (in practice, at most one --
    // the account holds one bot's position at a time,
    // docs/decisions/2026-07-27-deprecate-upro-regime-bot.md).
    let finalOutcome = "success:within_threshold";
    for (const position of positions) {
      finalOutcome = await checkOnePosition(position);
      if (finalOutcome !== "success:within_threshold") return finalOutcome;
    }
    return finalOutcome;
  } catch (e) {
    const err = e as Error;
    if (err instanceof AlpacaError) {
      await notifications.notifyBrokerError({ context: "kill-switch", errorMsg: err.message });
    }
    await finish(`error:${err.name}`, String(err.message).slice(0, 500));
    return `error:${err.name}`;
  }
}
