from __future__ import annotations

import sqlite3
from tools.database import get_open_trades


def get_open_positions_with_prices(
    conn: sqlite3.Connection,
    current_prices: dict,
) -> list:
    trades = get_open_trades(conn)
    result = []
    for t in trades:
        ticker = t["ticker"]
        price = current_prices.get(ticker, t["entry_price"])
        unrealized_pnl = (price - t["entry_price"]) * t["shares"]
        pct_to_stop = (price - t["stop_loss"]) / price if price > 0 else 0.0
        pct_to_target = (t["take_profit"] - price) / price if price > 0 else 0.0
        result.append({
            **t,
            "current_price": price,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pct_to_stop": round(pct_to_stop, 4),
            "pct_to_target": round(pct_to_target, 4),
        })
    return result


def get_portfolio_stats(
    conn: sqlite3.Connection,
    portfolio_value: float,
    current_prices: dict = None,
) -> dict:
    current_prices = current_prices or {}
    positions = get_open_positions_with_prices(conn, current_prices)
    deployed = sum(t["entry_price"] * t["shares"] for t in positions)
    unrealized_pnl = sum(t["unrealized_pnl"] for t in positions)
    return {
        "open_count": len(positions),
        "deployed_dollars": round(deployed, 2),
        "deployed_pct": round(deployed / portfolio_value, 4) if portfolio_value else 0.0,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "daily_pnl_pct": round(unrealized_pnl / portfolio_value, 4) if portfolio_value else 0.0,
        "positions": positions,
    }
