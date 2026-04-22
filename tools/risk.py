from __future__ import annotations

import math


def calculate_position(
    portfolio_value: float,
    risk_pct: float,
    entry_price: float,
    atr: float,
    atr_stop_multiplier: float = 1.5,
    rr_ratio_min: float = 2.0,
) -> dict:
    risk_dollars = portfolio_value * risk_pct
    stop_distance = atr * atr_stop_multiplier
    shares = math.floor(risk_dollars / stop_distance)
    stop_loss = round(entry_price - stop_distance, 4)
    take_profit = round(entry_price + stop_distance * rr_ratio_min, 4)
    return {
        "shares": shares,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_dollars": round(risk_dollars, 2),
        "stop_distance": round(stop_distance, 4),
    }


def check_portfolio_guardrails(
    open_positions: int,
    max_positions: int,
    deployed_pct: float,
    max_exposure: float,
    daily_pnl_pct: float,
    drawdown_limit: float,
) -> dict:
    if open_positions >= max_positions:
        return {
            "can_trade": False,
            "reason": f"max_positions reached ({open_positions}/{max_positions})",
        }
    if deployed_pct >= max_exposure:
        return {
            "can_trade": False,
            "reason": f"exposure limit reached ({deployed_pct:.1%}/{max_exposure:.1%})",
        }
    if daily_pnl_pct <= -drawdown_limit:
        return {
            "can_trade": False,
            "reason": f"drawdown limit breached ({daily_pnl_pct:.1%})",
        }
    return {"can_trade": True, "reason": ""}
