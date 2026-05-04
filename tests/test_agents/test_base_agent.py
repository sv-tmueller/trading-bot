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


def test_agent_tool_use_loop_executes(db_conn):
    """Tool-use loop must call the tool, append results, and return the end_turn response."""

    class ToolAgent(BaseAgent):
        name = "tool_agent"
        system_prompt = "You use tools."

        def get_tools(self) -> list:
            return [{"name": "get_price", "description": "Get price", "input_schema": {"type": "object", "properties": {}}}]

        def _get_tool_functions(self) -> list:
            def get_price():
                return {"price": 42.0}
            return [get_price]

        def parse_output(self, response) -> dict:
            return {"result": response.content[0].text}

    # First response: tool_use
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "get_price"
    tool_block.id = "tool_123"
    tool_block.input = {}

    first_response = MagicMock()
    first_response.content = [tool_block]
    first_response.stop_reason = "tool_use"
    first_response.usage.input_tokens = 100
    first_response.usage.output_tokens = 50

    # Second response: end_turn
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "price is 42"

    second_response = MagicMock()
    second_response.content = [text_block]
    second_response.stop_reason = "end_turn"
    second_response.usage.input_tokens = 200
    second_response.usage.output_tokens = 80

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ToolAgent()
        result = agent.run("get the price", conn=db_conn)

    assert result["result"] == "price is 42"
    assert mock_client.messages.create.call_count == 2


def test_handle_tool_calls_isolates_tool_exception():
    """A tool that raises must not abort the loop — error is reported back to the LLM."""

    class FailingToolAgent(BaseAgent):
        name = "failing_tool_agent"
        system_prompt = "."

        def get_tools(self) -> list:
            return [{"name": "boom", "description": "fails", "input_schema": {"type": "object", "properties": {}}}]

        def _get_tool_functions(self) -> list:
            def boom():
                raise ValueError("atr must be > 0 (got 0)")
            return [boom]

        def parse_output(self, response) -> dict:
            return {}

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "boom"
    tool_block.id = "tool_boom_1"
    tool_block.input = {}

    response = MagicMock()
    response.content = [tool_block]

    with patch("agents.base.anthropic.Anthropic", return_value=MagicMock()):
        agent = FailingToolAgent()
        results = agent._handle_tool_calls(response)

    assert len(results) == 1
    assert results[0]["tool_use_id"] == "tool_boom_1"
    assert results[0]["is_error"] is True
    assert "ValueError" in results[0]["content"]
    assert "atr must be > 0" in results[0]["content"]


def test_handle_tool_calls_unknown_tool_returns_is_error():
    """Unknown tool names must be reported back as is_error=True, not crash."""

    class NoToolsAgent(BaseAgent):
        name = "no_tools_agent"
        system_prompt = "."

        def get_tools(self) -> list:
            return []

        def _get_tool_functions(self) -> list:
            return []

        def parse_output(self, response) -> dict:
            return {}

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "ghost_tool"
    tool_block.id = "tool_ghost_1"
    tool_block.input = {}

    response = MagicMock()
    response.content = [tool_block]

    with patch("agents.base.anthropic.Anthropic", return_value=MagicMock()):
        agent = NoToolsAgent()
        results = agent._handle_tool_calls(response)

    assert len(results) == 1
    assert results[0]["tool_use_id"] == "tool_ghost_1"
    assert results[0]["is_error"] is True
    assert "ghost_tool" in results[0]["content"]


def test_agent_tool_use_loop_continues_after_tool_exception(db_conn):
    """End-to-end: a failing tool yields an error tool_result and the LLM produces final text."""

    class FailingToolAgent(BaseAgent):
        name = "failing_tool_agent_e2e"
        system_prompt = "."

        def get_tools(self) -> list:
            return [{"name": "boom", "description": "fails", "input_schema": {"type": "object", "properties": {}}}]

        def _get_tool_functions(self) -> list:
            def boom():
                raise RuntimeError("tool exploded")
            return [boom]

        def parse_output(self, response) -> dict:
            return {"result": response.content[0].text}

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "boom"
    tool_block.id = "tool_e2e_1"
    tool_block.input = {}

    first_response = MagicMock()
    first_response.content = [tool_block]
    first_response.stop_reason = "tool_use"
    first_response.usage.input_tokens = 50
    first_response.usage.output_tokens = 20

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "skipping due to error"

    second_response = MagicMock()
    second_response.content = [text_block]
    second_response.stop_reason = "end_turn"
    second_response.usage.input_tokens = 30
    second_response.usage.output_tokens = 10

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = FailingToolAgent()
        result = agent.run("try the tool", conn=db_conn)

    assert result["result"] == "skipping due to error"
    assert mock_client.messages.create.call_count == 2
    second_call_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
    follow_up_user_msg = second_call_messages[-1]
    assert follow_up_user_msg["role"] == "user"
    tool_result = follow_up_user_msg["content"][0]
    assert tool_result["is_error"] is True
    assert "RuntimeError" in tool_result["content"]
    assert "tool exploded" in tool_result["content"]


def test_agent_tool_use_loop_accumulates_tokens(db_conn):
    """Tokens from both turns must be summed and logged."""

    class ToolAgent(BaseAgent):
        name = "tool_agent"
        system_prompt = "You use tools."

        def get_tools(self) -> list:
            return [{"name": "ping", "description": "ping", "input_schema": {"type": "object", "properties": {}}}]

        def _get_tool_functions(self) -> list:
            def ping():
                return "pong"
            return [ping]

        def parse_output(self, response) -> dict:
            return {"result": response.content[0].text}

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "ping"
    tool_block.id = "tool_456"
    tool_block.input = {}

    first_response = MagicMock()
    first_response.content = [tool_block]
    first_response.stop_reason = "tool_use"
    first_response.usage.input_tokens = 100
    first_response.usage.output_tokens = 50

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "done"

    second_response = MagicMock()
    second_response.content = [text_block]
    second_response.stop_reason = "end_turn"
    second_response.usage.input_tokens = 200
    second_response.usage.output_tokens = 80

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ToolAgent()
        agent.run("ping", conn=db_conn)

    row = db_conn.execute("SELECT * FROM agent_logs WHERE agent_name = 'tool_agent'").fetchone()
    assert row["input_tokens"] == 300   # 100 + 200
    assert row["output_tokens"] == 130  # 50 + 80
    assert row["tokens_used"] == 430    # total
