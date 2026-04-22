from __future__ import annotations

import pandas as pd
import pytest
from tools.market_data import compute_signals, is_entry_signal


@pytest.fixture
def bullish_bars():
    """60 daily bars with a clear uptrend — EMA20 crosses above EMA50 at the end, moderate RSI, above-avg volume."""
    prices = [100 + i * 0.5 for i in range(60)]
    volumes = [1_000_000] * 60
    volumes[-1] = 1_800_000  # spike on last bar for volume confirmation
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    return pd.DataFrame({
        "close": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "volume": volumes,
    }, index=index)


@pytest.fixture
def ranging_bars():
    """60 bars oscillating — EMA20 near EMA50, no crossover."""
    prices = [100 + 2 * (i % 2) for i in range(60)]
    volumes = [1_000_000] * 60
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    return pd.DataFrame({
        "close": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "volume": volumes,
    }, index=index)


def test_compute_signals_returns_required_keys(bullish_bars):
    signals = compute_signals(bullish_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    for key in ("ema_fast", "ema_slow", "rsi", "volume_ratio", "atr", "ema_crossover"):
        assert key in signals, f"Missing key: {key}"


def test_volume_ratio_computed(bullish_bars):
    signals = compute_signals(bullish_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    # last bar volume is 1.8M, 20-day avg is 1.0M → ratio ≈ 1.8
    assert signals["volume_ratio"] == pytest.approx(1.8, rel=0.05)


def test_is_entry_signal_true_when_all_conditions_met():
    signals = {
        "ema_crossover": True,
        "rsi": 50.0,
        "volume_ratio": 1.8,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is True


def test_is_entry_signal_false_when_rsi_overbought():
    signals = {
        "ema_crossover": True,
        "rsi": 72.0,
        "volume_ratio": 2.0,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is False


def test_is_entry_signal_false_when_no_crossover():
    signals = {
        "ema_crossover": False,
        "rsi": 50.0,
        "volume_ratio": 2.0,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is False


def test_is_entry_signal_false_when_volume_low():
    signals = {
        "ema_crossover": True,
        "rsi": 50.0,
        "volume_ratio": 1.2,
    }
    assert is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5) is False


def test_compute_signals_ema_crossover_is_native_bool(bullish_bars):
    signals = compute_signals(bullish_bars, ema_fast=20, ema_slow=50, rsi_period=14, atr_period=14)
    assert isinstance(signals["ema_crossover"], bool)
    result = is_entry_signal(signals, rsi_lower=40, rsi_upper=60, volume_multiplier=1.5)
    assert isinstance(result, bool)
