from __future__ import annotations

import json
from datetime import date
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
                    "properties": {"ticker": {"type": "string"}},
                    "required": ["ticker"],
                },
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.broker import place_market_order, close_position as broker_close_position
        from tools.broker import get_current_price
        from tools.database import insert_trade
        conn = self._conn
        pending_stops = self._pending_stops
        pending_targets = self._pending_targets

        def place_order(ticker: str, shares: int, side: str) -> dict:
            order_id = place_market_order(ticker, shares, side)
            if side == "buy":
                price = get_current_price(ticker)
                insert_trade(conn, {
                    "ticker": ticker,
                    "entry_date": date.today().isoformat(),
                    "entry_price": price,
                    "shares": shares,
                    "stop_loss": pending_stops.get(ticker, price * 0.97),
                    "take_profit": pending_targets.get(ticker, price * 1.06),
                })
            return {"order_id": order_id, "status": "submitted"}

        def close_position(ticker: str) -> dict:
            order_id = broker_close_position(ticker)
            return {"order_id": order_id, "status": "closed"}

        return [place_order, close_position]

    def run(self, prompt: str, conn=None, pending_stops: dict = None, pending_targets: dict = None) -> dict:
        self._conn = conn
        self._pending_stops = pending_stops or {}
        self._pending_targets = pending_targets or {}
        return super().run(prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = response.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"decisions": [], "summary": text}
