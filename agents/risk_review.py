from __future__ import annotations

import json
from agents.base import BaseAgent
from config import settings


class RiskReviewAgent(BaseAgent):
    name = "risk_review"
    system_prompt = """You are the Risk Review Agent for a swing trading bot.

Your job:
1. Receive trade candidates from the Strategy Agent
2. For each candidate, calculate exact position size, stop-loss, and take-profit using the risk tool
3. Check portfolio guardrails before approving each trade
4. Reject candidates that violate risk rules — always explain why

Rules you enforce:
- Never risk more than RISK_PCT of portfolio per trade
- Never exceed MAX_POSITIONS open simultaneously
- Never exceed MAX_EXPOSURE of portfolio deployed
- Reject if daily drawdown limit is breached

Respond with JSON. Include the ATR you used for each approved trade so Team Leader can recompute the bracket against the latest quote at submission time:
{
  "approved": [
    {"ticker": "AMD", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "risk_dollars": 1000.0, "atr": 3.0}
  ],
  "rejected": [
    {"ticker": "NVDA", "reason": "max positions reached"}
  ]
}
"""

    def __init__(self) -> None:
        super().__init__()
        self._conn = None

    def get_tools(self) -> list:
        return [
            {
                "name": "calculate_position",
                "description": "Calculate position size, stop-loss and take-profit for a ticker",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "entry_price": {"type": "number"},
                        "atr": {"type": "number"},
                    },
                    "required": ["ticker", "entry_price", "atr"],
                },
            },
            {
                "name": "check_guardrails",
                "description": "Check if portfolio guardrails allow a new trade",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    def _get_tool_functions(self) -> list:
        from tools.risk import calculate_position as _calc_position, check_portfolio_guardrails
        from tools.portfolio import get_portfolio_stats
        from tools.broker import get_portfolio_value
        conn = self._conn  # capture locally

        def calculate_position(ticker: str, entry_price: float, atr: float) -> dict:
            portfolio_value = get_portfolio_value()
            return _calc_position(
                portfolio_value=portfolio_value,
                risk_pct=settings.RISK_PER_TRADE,
                entry_price=entry_price,
                atr=atr,
                atr_stop_multiplier=settings.ATR_STOP_MULTIPLIER,
                rr_ratio_min=settings.RR_RATIO_MIN,
            )

        def check_guardrails() -> dict:
            portfolio_value = get_portfolio_value()
            stats = get_portfolio_stats(conn, portfolio_value)
            return check_portfolio_guardrails(
                open_positions=stats["open_count"],
                max_positions=settings.MAX_POSITIONS,
                deployed_pct=stats["deployed_pct"],
                max_exposure=settings.MAX_PORTFOLIO_EXPOSURE,
                daily_pnl_pct=stats["daily_pnl_pct"],
                drawdown_limit=settings.DAILY_DRAWDOWN_LIMIT,
            )

        return [calculate_position, check_guardrails]

    def run(self, prompt: str, conn=None) -> dict:
        self._conn = conn
        risk_prompt = (
            f"Risk parameters:\n"
            f"- Risk per trade: {settings.RISK_PER_TRADE:.1%}\n"
            f"- Max positions: {settings.MAX_POSITIONS}\n"
            f"- Max exposure: {settings.MAX_PORTFOLIO_EXPOSURE:.0%}\n"
            f"- ATR stop multiplier: {settings.ATR_STOP_MULTIPLIER}x\n"
            f"- Minimum R:R ratio: {settings.RR_RATIO_MIN}:1\n\n"
            f"Candidates to review: {prompt}\n\n"
            f"Calculate position details for each and approve or reject."
        )
        return super().run(risk_prompt, conn=conn)

    def parse_output(self, response) -> dict:
        text = self._extract_json_text(response.content[0].text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"approved": [], "rejected": [{"reason": text}]}
