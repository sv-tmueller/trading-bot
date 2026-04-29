from __future__ import annotations

import json
from datetime import date, datetime
from agents.base import BaseAgent


class TeamLeaderAgent(BaseAgent):
    name = "team_leader"
    system_prompt = """You are the Team Leader Agent — the final decision-maker for a swing trading bot.

You receive consolidated reports from three specialist agents:
- Market Intelligence: current market conditions and flagged positions
- Strategy: scored trade candidates with technical reasoning
- Risk Review: approved candidates with exact position sizes and risk parameters

Your job:
1. Review all agent reports holistically
2. Make final go/no-go decision on each approved candidate
3. Place orders for approved trades using the place_order tool
4. Handle any flagged positions from Market Intelligence (close if needed)
5. Write a clear decision log explaining every action taken

You are the only agent authorised to place or close orders.

Respond with JSON:
{
  "decisions": [
    {"ticker": "AMD", "action": "buy", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "reasoning": "..."}
  ],
  "summary": "brief summary of the session"
}
"""

    def __init__(self) -> None:
        super().__init__()
        self._conn = None
        self._pending_stops: dict = {}
        self._pending_targets: dict = {}
        self._dry_run: bool = False

    def get_tools(self) -> list:
        return [
            {
                "name": "place_order",
                "description": "Place a market order to buy or sell shares",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "shares": {"type": "integer"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                    },
                    "required": ["ticker", "shares", "side"],
                },
            },
            {
                "name": "close_position",
                "description": "Close an open position entirely",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "enum": ["stop_loss", "take_profit", "trend_reversal", "max_hold", "manual"],
                            "description": "Why this position is being closed",
                        },
                    },
                    "required": ["ticker"],
                },
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.broker import place_market_order, close_position as broker_close_position
        from tools.broker import get_current_price, get_alpaca_positions, get_portfolio_value
        from tools.database import insert_trade, get_open_trades, close_trade
        from tools.risk import check_exposure_for_new_order
        from tools.notifications import notify_order_rejected
        from config import settings
        conn = self._conn
        pending_stops = self._pending_stops
        pending_targets = self._pending_targets
        dry_run = self._dry_run

        def place_order(ticker: str, shares: int, side: str) -> dict:
            if dry_run:
                print(f"[DRY RUN] would {side} {shares} shares of {ticker}")
                return {"order_id": "dry-run", "status": "dry-run"}
            price = get_current_price(ticker)   # fetch BEFORE broker — no ghost risk

            # Deterministic exposure gate — runs on every buy. The LLM cannot
            # bypass this; even if Team Leader hallucinates a clean portfolio
            # we recompute current notional from broker truth here. Sells skip
            # the gate because they reduce, not add, exposure.
            if side == "buy":
                try:
                    portfolio_value = get_portfolio_value()
                    open_positions = get_alpaca_positions()
                    current_notional = sum(
                        p["qty"] * p["avg_entry_price"] for p in open_positions
                    )
                except Exception as e:
                    # Fail-closed: if we can't verify exposure, reject. Better
                    # to skip a trade than over-deploy.
                    reason = f"exposure check failed: {e}"
                    print(f"[place_order] REJECTED {ticker} {shares}sh — {reason}")
                    notify_order_rejected(ticker, shares, reason)
                    return {"order_id": None, "status": "rejected", "reason": reason}

                candidate_notional = shares * price
                gate = check_exposure_for_new_order(
                    current_notional=current_notional,
                    candidate_notional=candidate_notional,
                    portfolio_value=portfolio_value,
                    max_exposure=settings.MAX_PORTFOLIO_EXPOSURE,
                )
                if not gate["can_trade"]:
                    reason = gate["reason"]
                    print(f"[place_order] REJECTED {ticker} {shares}sh — {reason}")
                    notify_order_rejected(ticker, shares, reason)
                    return {"order_id": None, "status": "rejected", "reason": reason}

            order_result = place_market_order(ticker, shares, side)
            order_id = order_result["order_id"]
            if side == "buy":
                entry_price = order_result["fill_price"] if order_result["fill_price"] is not None else price  # Alpaca fills async; fill_price may be None on paper — pre-order quote is the fallback
                insert_trade(conn, {
                    "ticker": ticker,
                    "entry_date": date.today().isoformat(),
                    "entry_price": entry_price,
                    "shares": shares,
                    "stop_loss": pending_stops.get(ticker, entry_price * 0.97),
                    "take_profit": pending_targets.get(ticker, entry_price * 1.06),
                })
            return {"order_id": order_id, "status": "submitted"}

        def close_position(ticker: str, reason: str = "manual") -> dict:
            if dry_run:
                print(f"[DRY RUN] would close {ticker} ({reason})")
                return {"order_id": "dry-run", "status": "dry-run"}
            price = get_current_price(ticker)   # fetch BEFORE broker — no ghost risk
            order_id = broker_close_position(ticker)
            today = date.today().isoformat()
            open_trades = get_open_trades(conn)
            trade = next((t for t in open_trades if t["ticker"] == ticker), None)
            if trade is not None:
                entry_price = trade["entry_price"]
                stop_distance = entry_price - trade["stop_loss"]
                pnl_dollars = (price - entry_price) * trade["shares"]
                r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
                entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
                today_date = datetime.strptime(today, "%Y-%m-%d").date()
                hold_days = (today_date - entry_date).days
                close_trade(conn, trade["id"], {
                    "exit_date": today,
                    "exit_price": price,
                    "exit_reason": reason,
                    "pnl_dollars": round(pnl_dollars, 2),
                    "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                    "hold_days": hold_days,
                    "r_multiple": round(r_multiple, 3),
                })
            return {"order_id": order_id, "status": "closed"}

        return [place_order, close_position]

    def run(self, prompt: str, conn=None, pending_stops: dict = None, pending_targets: dict = None, dry_run: bool = False) -> dict:
        self._conn = conn
        self._pending_stops = pending_stops or {}
        self._pending_targets = pending_targets or {}
        self._dry_run = dry_run
        return super().run(prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = self._extract_json_text(response.content[0].text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"decisions": [], "summary": text}
