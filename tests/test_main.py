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


def test_run_morning_scan_calls_notify_error_on_exception(db_conn):
    """If any agent raises, notify_error must be called and the exception must not propagate."""
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error") as mock_notify_error:
        MockMI.return_value.run.side_effect = RuntimeError("API timeout")
        from main import run_morning_scan
        run_morning_scan()  # must NOT raise

    mock_notify_error.assert_called_once()
    context, error_text = mock_notify_error.call_args[0]
    assert context == "morning_scan"
    assert "API timeout" in error_text


def test_run_position_monitor_calls_notify_error_on_exception(db_conn):
    """If run_monitor raises, notify_error must be called."""
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.run_monitor", side_effect=RuntimeError("connection refused")), \
         patch("main.notify_error") as mock_notify_error:
        from main import run_position_monitor
        run_position_monitor()  # must NOT raise

    mock_notify_error.assert_called_once()
    context, error_text = mock_notify_error.call_args[0]
    assert context == "position_monitor"
    assert "connection refused" in error_text


def test_run_morning_scan_closes_conn_on_exception(db_conn):
    """DB connection must be closed even when an agent raises."""
    mock_conn = MagicMock()
    mock_conn.row_factory = None

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=mock_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error"):
        MockMI.return_value.run.side_effect = RuntimeError("boom")
        from main import run_morning_scan
        run_morning_scan()

    mock_conn.close.assert_called_once()


def test_run_position_monitor_closes_conn_on_exception(db_conn):
    """DB connection must be closed even when run_monitor raises."""
    mock_conn = MagicMock()

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=mock_conn), \
         patch("main.run_monitor", side_effect=RuntimeError("boom")), \
         patch("main.notify_error"):
        from main import run_position_monitor
        run_position_monitor()

    mock_conn.close.assert_called_once()
