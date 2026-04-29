from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from agents.strategy import StrategyAgent


def make_mock_claude_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 1000
    mock.usage.output_tokens = 400
    mock.stop_reason = "end_turn"
    return mock


def test_strategy_agent_returns_candidates(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
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


def test_strategy_tool_blocks_entry_when_in_earnings_blackout():
    """When EARNINGS_BLACKOUT_DAYS > 0 and ticker is in window, entry_signal must flip to False."""
    fake_signals = {
        "ema_fast": 100.0,
        "ema_slow": 90.0,
        "ema_fast_prev": 89.0,
        "ema_slow_prev": 90.5,
        "rsi": 55.0,
        "atr": 2.0,
        "volume_ratio": 2.0,
        "current_price": 100.0,
    }

    with patch("agents.base.anthropic.Anthropic"), \
         patch("tools.market_data.fetch_bars", return_value=[]), \
         patch("tools.market_data.compute_signals", return_value=dict(fake_signals)), \
         patch("tools.market_data.is_entry_signal", return_value=True), \
         patch("tools.earnings.is_in_blackout_window", return_value=True), \
         patch("tools.earnings.get_next_earnings_date", return_value=__import__("datetime").date(2026, 5, 1)), \
         patch("tools.earnings.get_last_earnings_date", return_value=None), \
         patch("config.settings.EARNINGS_BLACKOUT_DAYS", 5):
        agent = StrategyAgent()
        fns = agent._get_tool_functions()
        compute = next(f for f in fns if f.__name__ == "compute_ticker_signals")
        out = compute("AMD")
    assert out["entry_signal"] is False
    assert "earnings_blackout_reason" in out


def test_strategy_tool_unchanged_when_blackout_disabled():
    fake_signals = {
        "ema_fast": 100.0,
        "ema_slow": 90.0,
        "rsi": 55.0,
        "atr": 2.0,
        "volume_ratio": 2.0,
        "current_price": 100.0,
    }

    blackout_called = {"hit": False}

    def _spy(*a, **kw):
        blackout_called["hit"] = True
        return True

    with patch("agents.base.anthropic.Anthropic"), \
         patch("tools.market_data.fetch_bars", return_value=[]), \
         patch("tools.market_data.compute_signals", return_value=dict(fake_signals)), \
         patch("tools.market_data.is_entry_signal", return_value=True), \
         patch("tools.earnings.is_in_blackout_window", side_effect=_spy), \
         patch("config.settings.EARNINGS_BLACKOUT_DAYS", 0):
        agent = StrategyAgent()
        fns = agent._get_tool_functions()
        compute = next(f for f in fns if f.__name__ == "compute_ticker_signals")
        out = compute("AMD")
    assert out["entry_signal"] is True
    assert "earnings_blackout_reason" not in out
    assert blackout_called["hit"] is False
