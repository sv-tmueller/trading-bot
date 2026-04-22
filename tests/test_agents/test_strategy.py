from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from agents.strategy import StrategyAgent


def make_mock_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 1000
    mock.usage.output_tokens = 400
    mock.stop_reason = "end_turn"
    return mock


def test_strategy_agent_returns_candidates(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_response(
        '{"candidates": [{"ticker": "AMD", "score": 0.85, "reasoning": "strong trend"}], "no_trade_reason": ""}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = StrategyAgent()
        result = agent.run("Analyse watchlist for entries", conn=db_conn)

    assert "candidates" in result
    assert isinstance(result["candidates"], list)
    assert result["candidates"][0]["ticker"] == "AMD"
    assert "no_trade_reason" in result


def test_strategy_agent_name():
    with patch("agents.base.anthropic.Anthropic"):
        agent = StrategyAgent()
    assert agent.name == "strategy"


def test_strategy_agent_parse_fallback():
    with patch("agents.base.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="No clear setups today")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        agent = StrategyAgent()
        result = agent.run("Analyse watchlist for entries")

    assert result["candidates"] == []
    assert "No clear setups today" in result["no_trade_reason"]
