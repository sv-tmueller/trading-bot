from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from agents.base import BaseAgent


class ConcreteAgent(BaseAgent):
    name = "test_agent"
    system_prompt = "You are a test agent."

    def get_tools(self) -> list:
        return []

    def _get_tool_functions(self) -> list:
        return []

    def parse_output(self, response) -> dict:
        return {"result": response.content[0].text}


def test_agent_name():
    agent = ConcreteAgent()
    assert agent.name == "test_agent"


def test_agent_run_calls_claude(db_conn):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="analysis complete")]
    mock_response.usage.input_tokens = 500
    mock_response.usage.output_tokens = 200
    mock_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ConcreteAgent()
        result = agent.run("analyse the market", conn=db_conn)

    assert result["result"] == "analysis complete"
    mock_client.messages.create.assert_called_once()


def test_agent_run_logs_to_db(db_conn):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="done")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    mock_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ConcreteAgent()
        agent.run("test prompt", conn=db_conn)

    rows = db_conn.execute("SELECT * FROM agent_logs").fetchall()
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "test_agent"
    assert rows[0]["tokens_used"] == 150


def test_agent_run_without_conn_does_not_crash():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="ok")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ConcreteAgent()
        result = agent.run("test")  # no conn — should not crash

    assert result["result"] == "ok"
