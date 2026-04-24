from __future__ import annotations

import json
from agents.base import BaseAgent
from config.watchlist import WATCHLIST


class MarketIntelligenceAgent(BaseAgent):
    name = "market_intelligence"
    system_prompt = """You are the Market Intelligence Agent for a swing trading bot.

Your job each trading day:
1. Review the watchlist of tickers
2. Assess current open positions — how are they tracking vs stop-loss and take-profit targets?
3. Summarise broader market context (trending up/down/sideways, notable volatility)
4. Flag any positions that need urgent attention (within 5% of stop-loss)

You have access to tools to fetch live market data and portfolio state.

Always respond with a JSON object containing:
- watchlist_summary: string describing overall watchlist conditions
- flagged_positions: list of position IDs needing attention
- market_context: string (bullish/bearish/neutral + brief reason)
- top_movers: list of tickers showing strongest signals today
"""

    def __init__(self) -> None:
        super().__init__()
        self._conn = None

    def get_tools(self) -> list:
        return [
            {
                "name": "get_portfolio_state",
                "description": "Returns open positions with current prices and distance to stop/target",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_watchlist",
                "description": "Returns the curated watchlist of tickers to scan",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.portfolio import get_open_positions_with_prices
        from tools.database import get_open_trades
        from tools.broker import get_current_price
        conn = self._conn  # capture locally so closures don't hold mutable self reference

        def get_portfolio_state():
            open_trades = get_open_trades(conn)
            open_tickers = [t["ticker"] for t in open_trades]
            prices = {t: get_current_price(t) for t in open_tickers}
            return get_open_positions_with_prices(conn, prices)

        def get_watchlist():
            return WATCHLIST

        return [get_portfolio_state, get_watchlist]

    def run(self, prompt: str, conn=None) -> dict:
        self._conn = conn
        return super().run(prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = self._extract_json_text(response.content[0].text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "watchlist_summary": text,
                "flagged_positions": [],
                "market_context": "unknown",
                "top_movers": [],
            }
