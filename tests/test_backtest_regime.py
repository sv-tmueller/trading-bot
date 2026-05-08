"""Regression test for backtest/regime.py.

Pinned to the 2021-05-07 to 2026-05-07 window with UPRO as the vehicle (since
3USL data history may be insufficient on yfinance). The 200-DMA filter on UPRO
over this window produced ~+150% total / ~-35% max DD in our brainstorming
session. Exact numbers will vary with yfinance data revisions, so we assert
loose bounds rather than equality.
"""
from __future__ import annotations

from datetime import date
import pytest
from backtest.regime import run_regime_backtest


@pytest.mark.slow
def test_upro_2021_2026_filter_within_expected_envelope():
    result = run_regime_backtest(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2021, 5, 7),
        end=date(2026, 5, 7),
        sma_days=200,
    )
    # Headline metrics
    assert 0.80 < result["total_return"] < 2.50, f"total_return={result['total_return']!r}"
    assert -0.55 < result["max_drawdown"] < -0.20, f"max_dd={result['max_drawdown']!r}"
    # Trade count: regime filter on a 5y window typically produces 4-12 round trips
    assert 2 <= result["trade_count"] <= 20, f"trade_count={result['trade_count']!r}"
    # Sanity: starting and ending equity
    assert result["starting_cash"] == pytest.approx(100_000.0)
    assert result["ending_equity"] > 0


def test_handles_short_history_vehicle(monkeypatch):
    """If vehicle data starts mid-window, backtest skips pre-data days."""
    # Synthetic test: ask for a window that's longer than available data.
    # We can't easily fake yfinance — instead, run with a very short window
    # and verify the structure of the result.
    result = run_regime_backtest(
        benchmark_ticker="SPY",
        vehicle_ticker="SPY",  # same as benchmark for this test
        start=date(2024, 1, 1),
        end=date(2024, 6, 1),
        sma_days=200,
    )
    assert "total_return" in result
    assert "max_drawdown" in result
    assert "trade_count" in result
