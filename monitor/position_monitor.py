from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime
from config import settings
from tools.database import get_open_trades, close_trade
from tools.broker import get_current_price, close_position as broker_close, get_alpaca_positions


@dataclass
class MonitorAction:
    trade_id: int
    ticker: str
    action: str   # "hold" | "close" | "reconciled"
    reason: str   # "" | "stop_loss" | "take_profit" | "max_hold" | "broker_closed"
    current_price: float


def evaluate_position(
    position: dict,
    current_price: float,
    today: str,
    max_hold_days: int = None,
) -> MonitorAction:
    max_hold_days = max_hold_days if max_hold_days is not None else settings.MAX_HOLD_DAYS
    entry_date = datetime.strptime(position["entry_date"], "%Y-%m-%d").date()
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    hold_days = (today_date - entry_date).days

    if current_price <= position["stop_loss"]:
        return MonitorAction(position["id"], position["ticker"], "close", "stop_loss", current_price)
    if current_price >= position["take_profit"]:
        return MonitorAction(position["id"], position["ticker"], "close", "take_profit", current_price)
    if hold_days >= max_hold_days:
        return MonitorAction(position["id"], position["ticker"], "close", "max_hold", current_price)
    return MonitorAction(position["id"], position["ticker"], "hold", "", current_price)


def _reconcile_phantom_closes(conn, open_trades: list, today: str) -> tuple[list, list]:
    """Detect trades the broker already closed (bracket child fired) and update DB.

    Bracket stops/targets execute server-side at Alpaca, so the broker may
    close a position between monitor runs. The DB still shows it open until we
    reconcile here. Returns (still_open_trades, reconciled_actions).
    """
    try:
        live_positions = get_alpaca_positions()
    except Exception:
        # Fail-open on reconciliation: better to run soft-stop on stale data
        # than skip the entire monitor cycle when Alpaca is unreachable.
        return open_trades, []

    live_tickers = {p["ticker"] for p in live_positions}
    still_open: list = []
    reconciled: list = []
    for trade in open_trades:
        if trade["ticker"] not in live_tickers:
            try:
                price = get_current_price(trade["ticker"])
            except Exception:
                price = trade["entry_price"]   # best-effort accounting
            entry_price = trade["entry_price"]
            stop_distance = entry_price - trade["stop_loss"]
            pnl_dollars = (price - entry_price) * trade["shares"]
            r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
            entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            today_date = datetime.strptime(today, "%Y-%m-%d").date()
            hold_days = (today_date - entry_date).days
            # Infer which bracket leg fired by comparing price to stop/target (0.5% slippage tolerance).
            if price <= trade["stop_loss"] * 1.005:
                exit_reason = "stop_loss"
            elif price >= trade["take_profit"] * 0.995:
                exit_reason = "take_profit"
            else:
                exit_reason = "manual"
            close_trade(conn, trade["id"], {
                "exit_date": today,
                "exit_price": price,
                "exit_reason": exit_reason,
                "pnl_dollars": round(pnl_dollars, 2),
                "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                "hold_days": hold_days,
                "r_multiple": round(r_multiple, 3),
            })
            reconciled.append(MonitorAction(trade["id"], trade["ticker"], "reconciled", "broker_closed", price))
        else:
            still_open.append(trade)
    return still_open, reconciled


def run_monitor(conn, today: str = None) -> list:
    """Hourly check on open positions.

    Stops and targets now execute server-side at Alpaca via bracket orders.
    This monitor's primary jobs are:
      1. Reconcile broker-truth: if Alpaca already closed a position
         (bracket child fired), close it in the DB.
      2. Trigger max_hold exits — bracket orders can't enforce time limits.
      3. Soft stop/target check kept as defense-in-depth: if Alpaca's bracket
         leg fails to fill (broker outage, halted symbol), this is the backup.
         Keep redundant — costs nothing on the happy path.
    """
    today = today or date_cls.today().isoformat()
    trades = get_open_trades(conn)

    # Step 1: reconcile broker-side closures so we don't act on phantom rows.
    trades, reconciled = _reconcile_phantom_closes(conn, trades, today)
    actions: list = list(reconciled)

    # Step 2 & 3: evaluate stop/target/max-hold for everything still open.
    for trade in trades:
        price = get_current_price(trade["ticker"])
        action = evaluate_position(trade, price, today)

        if action.action == "close":
            broker_close(trade["ticker"])
            entry_price = trade["entry_price"]
            stop_distance = entry_price - trade["stop_loss"]
            r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
            pnl_dollars = (price - entry_price) * trade["shares"]
            entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            today_date = datetime.strptime(today, "%Y-%m-%d").date()
            hold_days = (today_date - entry_date).days
            close_trade(conn, trade["id"], {
                "exit_date": today,
                "exit_price": price,
                "exit_reason": action.reason,
                "pnl_dollars": round(pnl_dollars, 2),
                "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                "hold_days": hold_days,
                "r_multiple": round(r_multiple, 3),
            })

        actions.append(action)

    return actions
