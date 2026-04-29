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
    candidate_pct: float = 0.0,
) -> dict:
    if open_positions >= max_positions:
        return {
            "can_trade": False,
            "reason": f"max_positions reached ({open_positions}/{max_positions})",
        }
    # candidate_pct lets the caller test whether the candidate would push the
    # post-trade exposure over the cap. Defaulting to 0.0 preserves the
    # original "current state only" behaviour for callers that don't supply it.
    post_trade_pct = deployed_pct + candidate_pct
    if post_trade_pct >= max_exposure:
        return {
            "can_trade": False,
            "reason": f"exposure limit reached ({post_trade_pct:.1%}/{max_exposure:.1%})",
        }
    if daily_pnl_pct <= -drawdown_limit:
        return {
            "can_trade": False,
            "reason": f"drawdown limit breached ({daily_pnl_pct:.1%})",
        }
    return {"can_trade": True, "reason": ""}


def check_exposure_for_new_order(
    current_notional: float,
    candidate_notional: float,
    portfolio_value: float,
    max_exposure: float,
) -> dict:
    """Deterministic gate: can a new order be placed without breaching the
    post-trade portfolio exposure cap?

    Returns ``{"can_trade": bool, "reason": str}``. The live order path in
    ``agents/team_leader.place_order`` calls this before submitting any buy.
    Computing on broker truth (live positions + live prices) — not DB state —
    is the whole point: the LLM cannot bypass it by hallucinating a smaller
    portfolio.
    """
    if portfolio_value <= 0:
        return {
            "can_trade": False,
            "reason": f"invalid portfolio_value ({portfolio_value})",
        }
    post_trade_notional = current_notional + candidate_notional
    post_trade_pct = post_trade_notional / portfolio_value
    if post_trade_pct > max_exposure:
        return {
            "can_trade": False,
            "reason": (
                f"exposure cap breached "
                f"(current=${current_notional:,.0f} + candidate=${candidate_notional:,.0f} "
                f"= {post_trade_pct:.1%} > {max_exposure:.1%})"
            ),
        }
    return {"can_trade": True, "reason": ""}
