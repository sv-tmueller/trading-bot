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
        '{"watchlist_summary": "AMD trending up", "flagged_positions": [], "market_context": "bullish", "top_movers": ["AMD"]}'
    )

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = MarketIntelligenceAgent()
        result = agent.run("Scan the watchlist", conn=db_conn)

    assert result["watchlist_summary"] == "AMD trending up"
    assert result["flagged_positions"] == []
    assert result["market_context"] == "bullish"
    assert "top_movers" in result


def test_market_intelligence_name():
    with patch("agents.base.anthropic.Anthropic"):
        agent = MarketIntelligenceAgent()
    assert agent.name == "market_intelligence"


def test_market_intelligence_parse_fallback():
    with patch("agents.base.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Markets look volatile today")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        agent = MarketIntelligenceAgent()
        result = agent.run("Scan the watchlist")

    assert result["watchlist_summary"] == "Markets look volatile today"
    assert result["flagged_positions"] == []
    assert result["market_context"] == "unknown"
    assert result["top_movers"] == []


def test_market_intelligence_get_portfolio_state_tool(db_conn):
    """get_portfolio_state must fetch prices only for open-position tickers."""
    from unittest.mock import call

    # First response: tool_use requesting get_portfolio_state
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "get_portfolio_state"
    tool_block.id = "tool_abc"
    tool_block.input = {}

    first_response = MagicMock()
    first_response.content = [tool_block]
    first_response.stop_reason = "tool_use"
    first_response.usage.input_tokens = 200
    first_response.usage.output_tokens = 50

    # Second response: end_turn with final briefing
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = '{"watchlist_summary": "AMD open", "flagged_positions": [], "market_context": "neutral", "top_movers": []}'

    second_response = MagicMock()
    second_response.content = [text_block]
    second_response.stop_reason = "end_turn"
    second_response.usage.input_tokens = 300
    second_response.usage.output_tokens = 100

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    # One open position: AMD
    mock_open_trades = [{"ticker": "AMD", "entry_price": 150.0, "shares": 10, "stop_loss": 140.0, "take_profit": 170.0}]
    mock_portfolio = [{"ticker": "AMD", "current_price": 155.0, "unrealized_pnl": 50.0, "pct_to_stop": 0.06, "pct_to_target": 0.097}]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.database.get_open_trades", return_value=mock_open_trades), \
         patch("tools.portfolio.get_open_positions_with_prices", return_value=mock_portfolio), \
         patch("tools.broker.get_current_price", return_value=155.0) as mock_price:
        agent = MarketIntelligenceAgent()
        result = agent.run("Scan the watchlist", conn=db_conn)

    # get_current_price called only for AMD, not all WATCHLIST tickers
    mock_price.assert_called_once_with("AMD")
    assert result["market_context"] == "neutral"
