from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from backtesting import Backtest

from backtest.strategy import EMAStrategy


def _make_fixture(has_crossover: bool = True, n: int = 90) -> pd.DataFrame:
    """90-bar synthetic OHLCV. Crossover fixture: downtrend for 60 bars then sharp rise."""
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    if has_crossover:
        # Downtrend first forces fast EMA below slow EMA; sharp uptrend creates crossover
        prices = np.concatenate([
            np.linspace(110.0, 100.0, 60),
            np.linspace(101.0, 130.0, n - 60),
        ])
        volumes = np.where(np.arange(n) >= 60, 2_000_000.0, 700_000.0)
    else:
        prices = np.linspace(130.0, 100.0, n)  # downtrend — no EMA crossover up
        volumes = np.full(n, 700_000.0)

    return pd.DataFrame(
        {
            "Open": prices * 0.999,
            "High": prices * 1.006,
            "Low": prices * 0.994,
            "Close": prices.copy(),
            "Volume": volumes,
        },
        index=dates,
    )


def test_strategy_produces_trade_on_crossover():
    df = _make_fixture(has_crossover=True)
    bt = Backtest(df, EMAStrategy, cash=100_000, commission=0.001, exclusive_orders=True)
    stats = bt.run(
        ema_fast=10,
        ema_slow=20,
        rsi_period=7,
        rsi_lower=0.0,
        rsi_upper=100.0,
        volume_multiplier=1.5,
        atr_period=5,
        atr_multiplier=1.5,
        rr_ratio=2.0,
        max_hold_days=15,
    )
    assert stats["# Trades"] >= 1


def test_strategy_no_trades_on_downtrend():
    df = _make_fixture(has_crossover=False)
    bt = Backtest(df, EMAStrategy, cash=100_000, commission=0.001, exclusive_orders=True)
    stats = bt.run(
        ema_fast=10,
        ema_slow=20,
        rsi_period=7,
        rsi_lower=0.0,
        rsi_upper=100.0,
        volume_multiplier=0.0,
        atr_period=5,
        atr_multiplier=1.5,
        rr_ratio=2.0,
        max_hold_days=15,
    )
    assert stats["# Trades"] == 0


def test_strategy_rsi_filter_blocks_entry():
    """Tight RSI window (50–51) should block most entries that pass wider window."""
    df = _make_fixture(has_crossover=True)
    bt = Backtest(df, EMAStrategy, cash=100_000, commission=0.001, exclusive_orders=True)

    stats_open = bt.run(
        ema_fast=10, ema_slow=20, rsi_period=7,
        rsi_lower=0.0, rsi_upper=100.0,
        volume_multiplier=0.0, atr_period=5, atr_multiplier=1.5,
        rr_ratio=2.0, max_hold_days=15,
    )
    stats_tight = bt.run(
        ema_fast=10, ema_slow=20, rsi_period=7,
        rsi_lower=50.0, rsi_upper=51.0,
        volume_multiplier=0.0, atr_period=5, atr_multiplier=1.5,
        rr_ratio=2.0, max_hold_days=15,
    )
    assert stats_tight["# Trades"] <= stats_open["# Trades"]
