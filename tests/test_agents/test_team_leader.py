from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from agents.team_leader import TeamLeaderAgent


def make_mock_claude_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 1200
    mock.usage.output_tokens = 500
    mock.stop_reason = "end_turn"
    return mock


def test_team_leader_executes_trades(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 222, "reasoning": "all signals aligned"}], "summary": "1 trade placed"}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        with patch("tools.broker.place_market_order", return_value="order-123"):
            agent = TeamLeaderAgent()
            result = agent.run("Approved: AMD 222 shares", conn=db_conn)

    assert "decisions" in result
    assert "summary" in result
    assert result["decisions"][0]["ticker"] == "AMD"
    assert result["summary"] == "1 trade placed"


def test_team_leader_name():
    with patch("agents.base.anthropic.Anthropic"):
        agent = TeamLeaderAgent()
    assert agent.name == "team_leader"


def test_team_leader_parse_fallback():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        "No trades today, conditions unfavorable"
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = TeamLeaderAgent()
        result = agent.run("Approved: AMD 222 shares")

    assert result["decisions"] == []
    assert "No trades today" in result["summary"]
