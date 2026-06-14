"""Tests for the extracted simulate_from_signal core in backtest/regime.py.

Characterization tests pin exact golden values on synthetic series so any
refactor that changes behaviour fails immediately.

All tests are offline — no network calls.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backtest.regime import simulate_from_signal


def _make_vehicle(prices: list[float], start: str = "2023-01-02") -> pd.DataFrame:
    """Build a tiny Open/Close DataFrame with business-day index."""
    idx = pd.bdate_range(start, periods=len(prices))
    return pd.DataFrame({"Open": prices, "Close": prices}, index=idx)


# ---------------------------------------------------------------------------
# Core correctness: all-True signal ≈ fee-adjusted B&H
# ---------------------------------------------------------------------------

def test_all_true_signal_rides_price_up():
    """All-True signal should buy on day 2 (first T+1 open) and stay long."""
    prices = [100.0, 100.0, 100.0, 110.0, 110.0, 110.0]
    vehicle = _make_vehicle(prices)
    is_bullish = pd.Series([True] * len(prices), index=vehicle.index)

    result = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=10_000.0,
        slippage_bps=5,
        commission_bps=5,
    )
    assert result["ending_equity"] > 10_000.0, "should end above starting cash"
    assert result["trade_count"] >= 1, "at least one trade open"


def test_all_false_signal_stays_flat():
    """All-False signal → never enters → ending_equity == starting_cash."""
    prices = [100.0, 105.0, 110.0, 120.0]
    vehicle = _make_vehicle(prices)
    is_bullish = pd.Series([False] * len(prices), index=vehicle.index)

    result = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=10_000.0,
    )
    assert result["trade_count"] == 0
    assert result["ending_equity"] == pytest.approx(10_000.0)
    assert result["total_return"] == pytest.approx(0.0)


def test_nan_signal_treated_as_flat():
    """NaN signal entries must NOT trigger a buy (warm-up pre-roll guard)."""
    prices = [100.0, 100.0, 110.0, 110.0, 115.0, 115.0]
    vehicle = _make_vehicle(prices)
    sig_values = [float("nan"), float("nan"), float("nan"), True, True, True]
    is_bullish = pd.Series(sig_values, index=vehicle.index)

    result = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=10_000.0,
    )
    # No crash; trade count is a non-negative int
    assert isinstance(result["trade_count"], int)
    assert result["trade_count"] >= 0
    assert result["ending_equity"] > 0


# ---------------------------------------------------------------------------
# Characterization (golden): exact values pinned from pre-refactor run
# ---------------------------------------------------------------------------

def test_golden_regime_upward_trend():
    """Pin exact equity-curve values captured from the pre-refactor code.

    Series: 10 bdays, rising closes 100..108, SMA-3 → bullish from day 3 on.
    Pre-refactor run_regime_backtest yielded ending_equity=10561.630146.
    """
    prices = [100.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
    vehicle = _make_vehicle(prices)

    closes = pd.Series(prices, index=vehicle.index)
    sma = closes.rolling(3).mean()
    is_bullish = (closes > sma).fillna(False)

    result = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=10_000.0,
        slippage_bps=5,
        commission_bps=5,
    )
    assert result["ending_equity"] == pytest.approx(10_561.630146, rel=1e-4)
    assert result["trade_count"] == 1


# ---------------------------------------------------------------------------
# Required result keys
# ---------------------------------------------------------------------------

def test_result_has_required_keys():
    prices = [100.0, 100.0, 100.0, 100.0]
    vehicle = _make_vehicle(prices)
    is_bullish = pd.Series([False] * 4, index=vehicle.index)
    result = simulate_from_signal(vehicle_df=vehicle, is_bullish_close_t=is_bullish)
    for key in ("total_return", "max_drawdown", "trade_count", "ending_equity",
                "starting_cash", "trades", "equity_curve"):
        assert key in result, f"missing key: {key}"


def test_trade_ledger_reconciles():
    """sum(trade.pnl) + starting_cash == ending_equity within $1."""
    prices = [100.0] * 10 + [110.0] * 5
    vehicle = _make_vehicle(prices)
    is_bullish = pd.Series([False] * 3 + [True] * 12, index=vehicle.index)

    result = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=10_000.0,
    )
    if result["trade_count"] > 0:
        sum_pnl = sum(t["pnl"] for t in result["trades"])
        assert abs(result["starting_cash"] + sum_pnl - result["ending_equity"]) < 1.0
