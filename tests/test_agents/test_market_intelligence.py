from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from agents.market_intelligence import MarketIntelligenceAgent


def make_mock_claude_response(text: str):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=text)]
    mock_response.usage.input_tokens = 800
    mock_response.usage.output_tokens = 300
    mock_response.stop_reason = "end_turn"
    return mock_response


def test_market_intelligence_returns_briefing(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        '{"watchlist_summary": "AMD trending up", "flagged_positions": [], "market_context": "bullish"}'
    )

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = MarketIntelligenceAgent()
        result = agent.run("Scan the watchlist", conn=db_conn)

    assert "watchlist_summary" in result
    assert "flagged_positions" in result
    assert "market_context" in result


def test_market_intelligence_name():
    with patch("agents.base.anthropic.Anthropic"):
        agent = MarketIntelligenceAgent()
    assert agent.name == "market_intelligence"
