"""Hourly drawdown kill-switch.

Scheduled by cron `5 14-21 * * 1-5` UTC (8 fires across US market hours).

Flow:
    1. Read latest regime_state from DB.
    2. If current_state != LONG: exit (nothing to protect).
    3. Fetch vehicle's last KILL_SWITCH_LOOKBACK_DAYS bars; compute rolling high.
    4. drawdown = (last_price / high) - 1
    5. If drawdown <= -KILL_SWITCH_DRAWDOWN_PCT: liquidate, notify, update DB.
"""
from __future__ import annotations

import sqlite3
import sys
import traceback
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from config import settings
from tools.ibkr_broker import (
    IBKRConnectionError, OrderTimeoutError,
    connect_ibkr, get_position, liquidate,
)
from tools.notifications import (
    notify_kill_switch_fired,
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    started = _now_iso()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    audit_id = insert_audit_log(conn, script_name="kill_switch", started_at=started)

    try:
        latest = get_latest_regime_state(conn)
        if not latest or latest["current_state"] != "LONG":
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success:no_position")
            return 0

        # Fetch vehicle history
        df = yf.download(settings.BOT_TICKER, period="60d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df["Close"].dropna()
        if len(df) < settings.KILL_SWITCH_LOOKBACK_DAYS:
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="skipped:insufficient_data",
                             notes=f"only {len(df)} bars, need {settings.KILL_SWITCH_LOOKBACK_DAYS}")
            return 0

        last_price = float(df.iloc[-1])
        ref_high = float(df.iloc[-settings.KILL_SWITCH_LOOKBACK_DAYS:].max())
        drawdown = last_price / ref_high - 1

        # Update position_drawdown_pct in regime_state for visibility
        upsert_regime_state(
            conn,
            date=_today_iso(),
            spy_close=latest["spy_close"], spy_sma200=latest["spy_sma200"],
            target_state=latest["target_state"], current_state="LONG",
            position_drawdown_pct=drawdown,
            kill_switch_active=bool(latest["kill_switch_active"]),
            kill_switch_fired_at=latest["kill_switch_fired_at"],
        )

        if drawdown > -settings.KILL_SWITCH_DRAWDOWN_PCT:
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success:within_threshold",
                             notes=f"dd={drawdown:.4f}")
            return 0

        # Threshold breached — connect, liquidate
        try:
            ib = connect_ibkr(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                              client_id=settings.IBKR_CLIENT_ID)
        except IBKRConnectionError as e:
            notify_tws_disconnected(host=settings.IBKR_HOST, port=settings.IBKR_PORT,
                                    attempts=3, error_msg=str(e))
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="error:tws_disconnect_during_kill_switch",
                             notes=str(e))
            return 1

        try:
            qty = get_position(ib, settings.BOT_TICKER)
            try:
                fill = liquidate(ib, symbol=settings.BOT_TICKER)
            except OrderTimeoutError as e:
                notify_trade_failed(symbol=settings.BOT_TICKER, side="SELL",
                                    qty=qty, reason=f"kill_switch_timeout:{e}")
                update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                                 outcome="error:kill_switch_liquidate_failed",
                                 notes=str(e))
                return 1

            if fill is None:
                # Position vanished between our position read and liquidate — auto-reconcile
                upsert_regime_state(
                    conn,
                    date=_today_iso(),
                    spy_close=latest["spy_close"], spy_sma200=latest["spy_sma200"],
                    target_state="CASH", current_state="CASH",
                    position_drawdown_pct=drawdown,
                    kill_switch_active=True, kill_switch_fired_at=_now_iso(),
                )
                update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                                 outcome="success:no_position_to_liquidate")
                return 0

            insert_trade(
                conn,
                symbol=settings.BOT_TICKER, side="SELL",
                qty=fill["qty"], fill_price=fill["fill_price"],
                fill_time=fill["fill_time"], ibkr_order_id=fill["order_id"],
                reason="kill_switch",
            )
            upsert_regime_state(
                conn,
                date=_today_iso(),
                spy_close=latest["spy_close"], spy_sma200=latest["spy_sma200"],
                target_state="CASH", current_state="CASH",
                position_drawdown_pct=drawdown,
                kill_switch_active=True, kill_switch_fired_at=_now_iso(),
            )
            notify_kill_switch_fired(
                ticker=settings.BOT_TICKER,
                drawdown_pct=drawdown,
                ref_high=ref_high,
                last_price=last_price,
                qty=fill["qty"],
                fill_price=fill["fill_price"],
            )
            update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                             outcome="success:kill_switch_fired",
                             notes=f"dd={drawdown:.4f}")
            return 0
        finally:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        update_audit_log(conn, rowid=audit_id, finished_at=_now_iso(),
                         outcome=f"error:{type(e).__name__}", notes=tb[:500])
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
