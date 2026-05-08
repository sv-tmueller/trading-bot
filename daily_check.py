"""Daily regime-filter check + IBKR position flip.

Scheduled by cron `30 22 * * 1-5` UTC (>=1.5h after US close, gives yfinance
time to publish the daily bar).

Flow:
    1. Fetch SPY history.
    2. Compute 200-day SMA and today's regime decision.
    3. Reconcile bot DB state with IBKR broker truth (auto-reconcile on desync).
    4. If target != current, place market order on BOT_TICKER via IBKR.
    5. Update DB rows (regime_state, trades, audit_log).
    6. Notify Discord.

Designed to be idempotent: a second run on the same trading day computes the
same target_state, sees current_state already matches, and writes a no-op
regime_state row.

Dry-run mode (``DAILY_CHECK_DRY_RUN=true`` env var or ``--dry-run`` CLI flag,
the latter wins on conflict): skips the broker order and the trades INSERT,
keeps current_state pinned at its pre-run value, marks audit_log.outcome with
the ``dry_run:`` prefix, and asks notify_regime_flip to flag the payload as
hypothetical. Used for the post-pivot soak window when we want the cron
running end-to-end without committing real capital.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import traceback
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from config import settings
from strategy.regime import compute_target_state
from tools.ibkr_broker import (
    IBKRConnectionError,
    connect_ibkr,
    get_account_value,
    get_position,
    liquidate,
    place_market_order,
)
from tools.notifications import (
    notify_regime_flip,
    notify_state_desync,
    notify_trade_failed,
    notify_tws_disconnected,
)
from tools.database import (
    get_latest_regime_state,
    insert_audit_log,
    insert_trade,
    update_audit_log,
    upsert_regime_state,
)

DB_PATH = "trading_bot.db"


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_dry_run(argv: list[str] | None) -> bool:
    """CLI ``--dry-run`` wins over ``settings.DAILY_CHECK_DRY_RUN``; either truthy enables dry-run."""
    parser = argparse.ArgumentParser(prog="daily_check", add_help=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("-h", "--help", action="store_true", default=False)
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    if args.help:
        print("Usage: python daily_check.py [--dry-run]")
        sys.exit(0)
    return args.dry_run or settings.DAILY_CHECK_DRY_RUN


def _fetch_vehicle_close(ticker: str) -> float:
    """Return the most recent close for ``ticker``. Used for sizing the
    hypothetical buy in dry-run, the live buy in the live path, and the
    fill_price field on the dry-run bearish CASH-flip alert (so the operator
    sees a meaningful price rather than 0.0). Kept as a standalone helper so
    test patches on ``daily_check.yf.download`` cover all call sites.
    """
    df = yf.download(ticker, period="5d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return float(df["Close"].dropna().iloc[-1])


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 on error.

    ``argv`` lets tests inject CLI args without touching ``sys.argv``. When
    ``None`` the real ``sys.argv[1:]`` is parsed.
    """
    dry_run = _resolve_dry_run(argv)
    if dry_run:
        print("[daily_check] DRY-RUN mode active — no broker orders will be placed.")

    started = _now_iso()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    audit_id = insert_audit_log(conn, script_name="daily_check", started_at=started)

    # Operational kill switch — same semantics as `main.py scan` (#197 review):
    # when TRADING_PAUSED is truthy the script must exit cleanly without touching
    # yfinance, IBKR, or the trades table. Honouring this here preserves the
    # `panic --pause` workflow once #200 decommissions `main.py scan`.
    if settings.TRADING_PAUSED:
        update_audit_log(
            conn,
            rowid=audit_id,
            finished_at=_now_iso(),
            outcome="skipped:trading_paused",
            notes="TRADING_PAUSED env var is set",
        )
        conn.close()
        return 0

    try:
        # 1. Fetch SPY data
        spy_df = yf.download(
            settings.BOT_BENCHMARK,
            period="2y",
            auto_adjust=True,
            progress=False,
        )
        if isinstance(spy_df.columns, pd.MultiIndex):
            spy_df.columns = spy_df.columns.get_level_values(0)
        spy_df = spy_df.dropna()

        # Stale-data check: is the last bar from today (UTC)?
        last_bar_date = spy_df.index[-1].date()
        today_utc = datetime.now(timezone.utc).date()
        if last_bar_date < today_utc:
            update_audit_log(
                conn,
                rowid=audit_id,
                finished_at=_now_iso(),
                outcome="skipped:stale_data",
                notes=f"last bar={last_bar_date}, today={today_utc}",
            )
            return 0

        spy_close = float(spy_df["Close"].iloc[-1])
        spy_sma = float(
            spy_df["Close"].rolling(settings.REGIME_SMA_DAYS).mean().iloc[-1]
        )

        # 2. Compute regime decision (against the pre-reconcile DB state).
        latest = get_latest_regime_state(conn)
        current_state = latest["current_state"] if latest else "CASH"
        kill_switch_active = bool(latest["kill_switch_active"]) if latest else False

        target_state, new_ks = compute_target_state(
            spy_close=spy_close,
            spy_sma200=spy_sma,
            current_state=current_state,
            kill_switch_active=kill_switch_active,
        )

        # 3. Connect to IBKR + reconcile against broker truth.
        try:
            ib = connect_ibkr(
                host=settings.IBKR_HOST,
                port=settings.IBKR_PORT,
                client_id=settings.IBKR_CLIENT_ID,
            )
        except IBKRConnectionError as e:
            notify_tws_disconnected(
                host=settings.IBKR_HOST,
                port=settings.IBKR_PORT,
                attempts=3,
                error_msg=str(e),
            )
            update_audit_log(
                conn,
                rowid=audit_id,
                finished_at=_now_iso(),
                outcome="error:tws_disconnect",
                notes=str(e),
            )
            return 1

        try:
            qty = get_position(ib, settings.BOT_TICKER)
            broker_state = "LONG" if qty > 0 else "CASH"

            if broker_state != current_state:
                notify_state_desync(
                    db_state=current_state,
                    broker_state=broker_state,
                    symbol=settings.BOT_TICKER,
                    action_taken=f"DB updated to {broker_state}",
                )
                current_state = broker_state
                # Re-compute target with the reconciled current_state so
                # downstream flip logic uses broker truth, not the stale DB row.
                target_state, new_ks = compute_target_state(
                    spy_close=spy_close,
                    spy_sma200=spy_sma,
                    current_state=current_state,
                    kill_switch_active=kill_switch_active,
                )

            # 4. Flip position if needed.
            position_dd_pct = None
            new_current_state = current_state  # what we'll persist below
            outcome = "success"

            if target_state != current_state:
                if target_state == "LONG":
                    if dry_run:
                        # Hypothetical buy: don't touch the broker, don't write
                        # a trades row, don't advance current_state. Still
                        # surface a dry-run alert so the operator can see the
                        # decision the live cron WOULD make.
                        account_value = get_account_value(ib, currency="EUR")
                        vehicle_close = _fetch_vehicle_close(settings.BOT_TICKER)
                        target_qty = int((account_value * 0.99) / vehicle_close)
                        notify_regime_flip(
                            target_state="LONG",
                            spy_close=spy_close,
                            spy_sma200=spy_sma,
                            ticker=settings.BOT_TICKER,
                            fill_price=vehicle_close,
                            qty=max(target_qty, 0),
                            account_value=account_value,
                            dry_run=True,
                        )
                        outcome = "dry_run:would_flip_long"
                    else:
                        account_value = get_account_value(ib, currency="EUR")
                        vehicle_close = _fetch_vehicle_close(settings.BOT_TICKER)
                        target_qty = int((account_value * 0.99) / vehicle_close)
                        if target_qty <= 0:
                            notify_trade_failed(
                                symbol=settings.BOT_TICKER,
                                side="BUY",
                                qty=0,
                                reason="insufficient_buying_power",
                            )
                            update_audit_log(
                                conn,
                                rowid=audit_id,
                                finished_at=_now_iso(),
                                outcome="error:insufficient_funds",
                            )
                            return 1
                        fill = place_market_order(
                            ib,
                            symbol=settings.BOT_TICKER,
                            side="BUY",
                            qty=target_qty,
                        )
                        insert_trade(
                            conn,
                            symbol=settings.BOT_TICKER,
                            side="BUY",
                            qty=fill["qty"],
                            fill_price=fill["fill_price"],
                            fill_time=fill["fill_time"],
                            ibkr_order_id=fill["order_id"],
                            reason="regime_flip_long",
                        )
                        notify_regime_flip(
                            target_state="LONG",
                            spy_close=spy_close,
                            spy_sma200=spy_sma,
                            ticker=settings.BOT_TICKER,
                            fill_price=fill["fill_price"],
                            qty=fill["qty"],
                            account_value=account_value,
                        )
                        new_current_state = "LONG"
                else:  # CASH — sell all
                    if dry_run:
                        # Hypothetical sell: skip liquidate + insert_trade.
                        # Use last-known position qty from broker for the alert
                        # so the operator sees the sized impact, plus the most
                        # recent close as fill_price (review minor #2 — 0.0 is
                        # not informative for the operator).
                        vehicle_close = _fetch_vehicle_close(settings.BOT_TICKER)
                        notify_regime_flip(
                            target_state="CASH",
                            spy_close=spy_close,
                            spy_sma200=spy_sma,
                            ticker=settings.BOT_TICKER,
                            fill_price=vehicle_close,
                            qty=qty,
                            account_value=get_account_value(ib, currency="EUR"),
                            dry_run=True,
                        )
                        outcome = "dry_run:would_flip_cash"
                    else:
                        fill = liquidate(ib, symbol=settings.BOT_TICKER)
                        if fill:
                            insert_trade(
                                conn,
                                symbol=settings.BOT_TICKER,
                                side="SELL",
                                qty=fill["qty"],
                                fill_price=fill["fill_price"],
                                fill_time=fill["fill_time"],
                                ibkr_order_id=fill["order_id"],
                                reason="regime_flip_cash",
                            )
                            notify_regime_flip(
                                target_state="CASH",
                                spy_close=spy_close,
                                spy_sma200=spy_sma,
                                ticker=settings.BOT_TICKER,
                                fill_price=fill["fill_price"],
                                qty=fill["qty"],
                                account_value=get_account_value(ib, currency="EUR"),
                            )
                            # Only advance current_state when the broker
                            # confirmed the liquidation. If `liquidate()`
                            # returned None (review important #2), drop into
                            # the error branch below — silently flipping to
                            # CASH would lie to tomorrow's idempotency check
                            # about the broker position.
                            new_current_state = "CASH"
                        else:
                            notify_trade_failed(
                                symbol=settings.BOT_TICKER,
                                side="SELL",
                                qty=qty,
                                reason="liquidate_returned_none",
                            )
                            update_audit_log(
                                conn,
                                rowid=audit_id,
                                finished_at=_now_iso(),
                                outcome="error:liquidate_failed",
                                notes=f"liquidate({settings.BOT_TICKER}) returned None; current_state pinned at {current_state}",
                            )
                            return 1
            else:
                # No flip required.
                if dry_run:
                    outcome = "dry_run:no_change"

            # 5. Persist regime_state. In dry-run, current_state stays at the
            # pre-flip value so tomorrow's run computes the same flip again.
            upsert_regime_state(
                conn,
                date=_today_iso(),
                spy_close=spy_close,
                spy_sma200=spy_sma,
                target_state=target_state,
                current_state=new_current_state,
                position_drawdown_pct=position_dd_pct,
                kill_switch_active=new_ks,
                kill_switch_fired_at=(
                    latest["kill_switch_fired_at"] if latest and new_ks else None
                ),
            )
            update_audit_log(
                conn,
                rowid=audit_id,
                finished_at=_now_iso(),
                outcome=outcome,
                notes=f"target={target_state} current={new_current_state}",
            )
            return 0
        finally:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        update_audit_log(
            conn,
            rowid=audit_id,
            finished_at=_now_iso(),
            outcome=f"error:{type(e).__name__}",
            notes=tb[:500],
        )
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
