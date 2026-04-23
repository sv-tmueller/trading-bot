from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch


def _make_agent_mock(return_value: dict):
    mock = MagicMock()
    mock.run.return_value = return_value
    return mock


def test_inter_agent_handoff_is_valid_json(db_conn):
    """Strategy, risk, and leader agents must receive valid JSON, not Python repr."""
    market_briefing = {
        "market_context": "bullish",
        "watchlist_summary": "AMD up 2%",
        "flagged_positions": [],
        "top_movers": ["AMD"],
    }
    candidates = {
        "candidates": [{"ticker": "AMD", "score": 0.8}],
        "tldr": "AMD crossover",
        "tickers_to_watch": [],
    }
    reviewed = {
        "approved": [{"ticker": "AMD", "shares": 100, "stop_loss": 140.0, "take_profit": 160.0}],
        "rejected": [],
    }
    decisions = {"decisions": [], "summary": "done"}

    mi_mock = _make_agent_mock(market_briefing)
    strategy_mock = _make_agent_mock(candidates)
    risk_mock = _make_agent_mock(reviewed)
    leader_mock = _make_agent_mock(decisions)

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent", return_value=mi_mock), \
         patch("main.StrategyAgent", return_value=strategy_mock), \
         patch("main.RiskReviewAgent", return_value=risk_mock), \
         patch("main.TeamLeaderAgent", return_value=leader_mock), \
         patch("main.get_daily_token_costs", return_value={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}), \
         patch("main.notify_scan_complete"), \
         patch("main.notify_error"):
        from main import run_morning_scan
        run_morning_scan()

    # Each handoff must be valid JSON
    strategy_arg = strategy_mock.run.call_args[0][0]
    parsed = json.loads(strategy_arg)
    assert parsed["market_context"] == "bullish"

    risk_arg = risk_mock.run.call_args[0][0]
    parsed = json.loads(risk_arg)
    assert "candidates" in parsed

    leader_arg = leader_mock.run.call_args[0][0]
    parsed = json.loads(leader_arg)
    assert "approved" in parsed
