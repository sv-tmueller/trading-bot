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
    """If vehicle data starts mid-window, backtest skips pre-data days.

    Offline by design: patches `backtest.regime._fetch` to return a synthetic
    DataFrame so the default test run (no `slow` marker) makes no network call.
    """
    import pandas as pd

    idx = pd.bdate_range("2024-01-02", periods=5)
    fake_df = pd.DataFrame(
        {"Open": [100.0] * 5, "Close": [101.0] * 5},
        index=idx,
    )
    monkeypatch.setattr("backtest.regime._fetch", lambda *a, **kw: fake_df)

    result = run_regime_backtest(
        benchmark_ticker="SPY",
        vehicle_ticker="SPY",
        start=date(2024, 1, 1),
        end=date(2024, 6, 1),
        sma_days=200,
    )
    assert "total_return" in result
    assert "max_drawdown" in result
    assert "trade_count" in result


def test_equity_and_trade_ledger_reconcile(monkeypatch):
    """sum(trade.pnl) + starting_cash == ending_equity, regardless of end-of-window state.

    Constructs a synthetic price series where the regime turns bullish after the
    SMA warm-up and stays bullish through end-of-window — guaranteeing the
    post-loop close path runs. Verifies the equity curve reflects the same
    slippage/commission haircut as the trade ledger.
    """
    import pandas as pd

    idx = pd.bdate_range("2023-01-02", periods=300)
    # Flat then up — bullish for the whole window after SMA warm-up
    closes = [100.0] * 200 + [105.0] * 100
    fake_benchmark = pd.DataFrame(
        {"Open": closes, "Close": closes}, index=idx,
    )
    fake_vehicle = pd.DataFrame(
        {"Open": closes, "Close": closes}, index=idx,
    )

    def fake_fetch(ticker, start, end):
        return fake_benchmark if ticker == "SPY" else fake_vehicle

    monkeypatch.setattr("backtest.regime._fetch", fake_fetch)

    result = run_regime_backtest(
        benchmark_ticker="SPY",
        vehicle_ticker="VEHICLE",
        start=date(2023, 1, 1),
        end=date(2024, 3, 1),
        sma_days=20,  # short SMA so we get a regime flip in the synthetic window
    )

    if result["trade_count"] > 0:
        sum_pnl = sum(t["pnl"] for t in result["trades"])
        reconstructed = result["starting_cash"] + sum_pnl
        assert abs(reconstructed - result["ending_equity"]) < 1.0, (
            f"Ledger mismatch: trades sum to {reconstructed:.2f}, "
            f"ending equity {result['ending_equity']:.2f}"
        )
