from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from agents.risk_review import RiskReviewAgent


def make_mock_claude_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 600
    mock.usage.output_tokens = 250
    mock.stop_reason = "end_turn"
    return mock


def test_risk_review_approves_valid_candidates(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        '{"approved": [{"ticker": "AMD", "shares": 222, "stop_loss": 145.5, "take_profit": 159.0, "risk_dollars": 1000.0}], "rejected": []}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = RiskReviewAgent()
        result = agent.run("Review these candidates: AMD score 0.85", conn=db_conn)

    assert "approved" in result
    assert "rejected" in result
    assert result["approved"][0]["ticker"] == "AMD"
    assert result["approved"][0]["shares"] == 222
    assert result["rejected"] == []


def test_risk_review_name():
    with patch("agents.base.anthropic.Anthropic"):
        agent = RiskReviewAgent()
    assert agent.name == "risk_review"


def test_risk_review_parse_fallback():
    with patch("agents.base.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Guardrails breached, no trades today")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        agent = RiskReviewAgent()
        result = agent.run("Review candidates")

    assert result["approved"] == []
    assert len(result["rejected"]) == 1
    assert "Guardrails breached" in result["rejected"][0]["reason"]
