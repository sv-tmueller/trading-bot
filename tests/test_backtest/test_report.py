from __future__ import annotations

import pytest

from backtest.report import format_terminal, notify_backtest


def _make_result() -> dict:
    return {
        "params": {
            "years": 1,
            "ema_fast": 20,
            "ema_slow": 50,
            "rsi_lower": 40.0,
            "rsi_upper": 60.0,
            "max_hold_days": 5,
        },
        "period": "2024-04-23 → 2025-04-23",
        "tickers": {
            "AMD": {"trades": 3, "win_rate": 0.667, "total_return": 0.05, "max_drawdown": -0.02},
            "NVDA": {"trades": 2, "win_rate": 0.5, "total_return": 0.03, "max_drawdown": -0.01},
        },
        "aggregate": {
            "trades": 5,
            "win_rate": 0.60,
            "total_return": 0.04,
            "max_drawdown": -0.02,
        },
    }


def test_format_terminal_contains_tickers():
    output = format_terminal(_make_result())
    assert "AMD" in output
    assert "NVDA" in output


def test_format_terminal_contains_aggregate():
    output = format_terminal(_make_result())
    assert "TOTAL" in output


def test_format_terminal_contains_param_header():
    output = format_terminal(_make_result())
    assert "EMA 20/50" in output
    assert "RSI 40-60" in output


def test_format_terminal_shows_single_year_warning():
    output = format_terminal(_make_result())
    assert "Single-year" in output


def test_format_terminal_no_warning_for_multi_year():
    result = _make_result()
    result["params"]["years"] = 3
    output = format_terminal(result)
    assert "Single-year" not in output


def test_notify_backtest_calls_post(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    notify_backtest(_make_result())
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "Backtest" in msg
    assert "5 trades" in msg
    assert "60.0%" in msg
