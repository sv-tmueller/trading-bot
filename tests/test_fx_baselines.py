"""Tests for backtest/fx_baselines.py -- the 4 dumb baselines (#376, spec
§5), each a STATE function consumed by ``fx_execution.simulate_fx_state``
(no TP/SL execution layer -- see that module's docstring).
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest import fx_baselines as fb


def _idx(n: int, start: str = "2024-01-08", freq: str = "4h") -> pd.DatetimeIndex:
    i = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    i.name = "datetime_utc"
    return i


def _close(values: list, start: str = "2024-01-08", freq: str = "4h") -> pd.Series:
    idx = _idx(len(values), start=start, freq=freq)
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# Baseline 1: always-flat
# ---------------------------------------------------------------------------

def test_always_flat_state_is_all_zero():
    idx = _idx(5)
    sig = fb.always_flat_state(idx)
    assert (sig == 0).all()
    assert list(sig.index) == list(idx)


# ---------------------------------------------------------------------------
# Baseline 2: EUR/USD buy-and-hold -- state +1 from the last pre-roll bar
# ---------------------------------------------------------------------------

def test_buy_and_hold_state_fills_on_first_test_bar():
    """State is 0 before ``from_ts`` and 1 from ``from_ts`` onward, so that
    when ``simulate_fx_state`` reads state[i-1] to decide bar i's fill, the
    fill lands EXACTLY on the test window's first bar's open (from_ts =
    the last pre-roll bar)."""
    idx = _idx(5)
    from_ts = idx[2]  # "last pre-roll bar" -- test window starts at idx[3]
    sig = fb.buy_and_hold_state(idx, from_ts)
    assert list(sig.iloc[:2]) == [0, 0]
    assert list(sig.iloc[2:]) == [1, 1, 1]


def test_buy_and_hold_state_end_to_end_fill_via_simulate_fx_state():
    from backtest import fx_execution as fx

    entry = 1.1000
    idx = _idx(4)
    bars = pd.DataFrame(
        {
            "Open": [entry, entry, entry + 0.001, entry + 0.002],
            "High": [entry + 0.001] * 4,
            "Low": [entry - 0.001] * 4,
            "Close": [entry, entry, entry + 0.0015, entry + 0.0025],
        },
        index=idx,
    )
    from_ts = idx[1]  # last pre-roll bar
    state = fb.buy_and_hold_state(idx, from_ts)
    result = fx.simulate_fx_state(bars, state, cost_rt=0.0, overnight=None)
    assert result["trade_count"] == 1
    t = result["trades"][0]
    # Fill lands on idx[2]'s open -- the first TEST bar (idx[1] was pre-roll).
    assert t["entry_date"] == idx[2]
    assert t["entry_price"] == pytest.approx(entry + 0.001)


# ---------------------------------------------------------------------------
# Baseline 3: persistence
# ---------------------------------------------------------------------------

def test_persistence_state_sign_of_last_completed_return():
    close = _close([100, 105, 105, 102])
    sig = fb.persistence_state(close)
    assert sig.iloc[0] == 0   # no prior bar -> flat
    assert sig.iloc[1] == 1   # 105 > 100 -> up
    assert sig.iloc[2] == 0   # 105 == 105 -> zero-return -> flat (theta=0 tie rule)
    assert sig.iloc[3] == -1  # 102 < 105 -> down


# ---------------------------------------------------------------------------
# Baseline 4: 200-SMA regime, native 4h bars
# ---------------------------------------------------------------------------

def test_sma200_regime_state_long_above_flat_below_and_warmup():
    # indices 0..199: 100.0 (200 values); index 200: 101.0; index 201: 99.0
    values = [100.0] * 200 + [101.0, 99.0]  # 202 bars total
    close = _close(values)
    sig = fb.sma200_regime_state(close, n=200)

    assert (sig.iloc[:199] == 0).all()  # warm-up (< 200 bars)
    # bar index 199 (200th bar, first defined SMA): window is all 100.0 ->
    # SMA=100.0, close=100.0 -> exactly equal -> flat (theta=0 tie rule)
    assert sig.iloc[199] == 0
    # bar index 200: window [1..200] mean=100.005, close=101.0 > SMA -> long
    assert sig.iloc[200] == 1
    # bar index 201: window [2..201] mean=100.0, close=99.0 < SMA -> flat (not short -- long/flat only)
    assert sig.iloc[201] == 0


def test_sma200_regime_state_values_in_expected_set():
    values = list(range(250))
    close = _close(values)
    sig = fb.sma200_regime_state(close, n=200)
    assert set(sig.unique()).issubset({0, 1})  # long/flat only, never -1
