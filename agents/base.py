from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import date

import anthropic

from config import settings
from tools.database import log_agent_output


class BaseAgent(ABC):
    name: str = "base"
    system_prompt: str = ""

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.CLAUDE_MODEL

    @abstractmethod
    def get_tools(self) -> list:
        """Return Anthropic tool definitions for this agent."""
        ...

    @abstractmethod
    def _get_tool_functions(self) -> list:
        """Return callable functions corresponding to get_tools()."""
        ...

    @abstractmethod
    def parse_output(self, response) -> dict:
        """Extract structured result from the raw Claude response."""
        ...

    def run(self, prompt: str, conn: sqlite3.Connection = None) -> dict:
        messages = [{"role": "user", "content": prompt}]
        tools = self.get_tools()

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        # Tool-use loop
        while response.stop_reason == "tool_use":
            tool_results = self._handle_tool_calls(response)
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
            kwargs["messages"] = messages
            response = self.client.messages.create(**kwargs)

        result = self.parse_output(response)
        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        if conn is not None:
            log_agent_output(conn, {
                "cycle_date": date.today().isoformat(),
                "agent_name": self.name,
                "input_summary": prompt[:200],
                "output_summary": str(result)[:200],
                "full_reasoning": str(result),
                "tokens_used": tokens_used,
            })

        return result

    def _handle_tool_calls(self, response) -> list:
        tool_map = {fn.__name__: fn for fn in self._get_tool_functions()}
        results = []
        for block in response.content:
            if block.type == "tool_use":
                fn = tool_map.get(block.name)
                if fn is not None:
                    output = fn(**block.input)
                else:
                    output = {"error": f"unknown tool: {block.name}"}
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
        return results
