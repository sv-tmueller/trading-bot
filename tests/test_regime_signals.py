"""Tests for backtest/regime_signals.py (#321) — the two new MA regime signals."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.regime_signals import confirmed_sma_signal, sma_signal


def _series(vals: list[float]) -> pd.Series:
    idx = pd.bdate_range("2020-01-01", periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


def test_sma_signal_basic_and_warmup():
    # 3-day SMA on [10,10,10,11,9,9,9]
    s = _series([10, 10, 10, 11, 9, 9, 9])
    sig = sma_signal(s, window=3)
    # warm-up: first window-1 rows have no SMA -> NaN
    assert pd.isna(sig.iloc[0]) and pd.isna(sig.iloc[1])
    assert sig.iloc[2] == False  # close 10 vs SMA 10 -> not strictly above
    assert sig.iloc[3] == True   # close 11 vs SMA (10+10+11)/3=10.33 -> above
    assert sig.iloc[4] == False  # close 9 vs SMA (10+11+9)/3=10 -> below
    assert sig.iloc[6] == False


def test_sma_signal_no_shift():
    # The signal at T reflects close[T] vs SMA[T], NOT a shifted value.
    s = _series([1, 2, 3, 4, 5, 6])  # strictly rising -> close always > trailing SMA
    sig = sma_signal(s, window=2)
    # first valid row is idx1 (SMA of [1,2]=1.5 < close 2) -> True, and stays True
    assert pd.isna(sig.iloc[0])
    assert all(sig.iloc[1:] == True)


def test_confirmed_debounces_single_day_whipsaw():
    # window=2, confirm=2: a single-day breach must NOT flip the confirmed state.
    s = _series([10, 12, 8, 12, 8, 8, 12, 12])
    raw = sma_signal(s, window=2)
    con = confirmed_sma_signal(s, window=2, confirm=2)
    # raw flips to True at idx6 (single up-day after a down run)...
    assert raw.iloc[6] == True
    # ...but the confirmed signal, having established bearish at idx5 (two
    # consecutive closes below the SMA), stays bearish through the 1-day whipsaw.
    assert con.iloc[5] == False
    assert con.iloc[6] == False  # debounced: single-day breach ignored
    # not-yet-established before the first confirmed run -> NaN
    assert pd.isna(con.iloc[4])


def test_confirm_one_equals_sma_signal():
    s = _series([10, 11, 9, 12, 8, 13, 7, 14])
    raw = sma_signal(s, window=3)
    con = confirmed_sma_signal(s, window=3, confirm=1)
    # confirm=1 -> flips immediately -> identical to the raw SMA signal
    for a, b in zip(raw.tolist(), con.tolist()):
        assert (pd.isna(a) and pd.isna(b)) or a == b


def test_confirmed_no_shift():
    # The confirmed signal at T reflects close[T] vs SMA[T], NOT a shifted value.
    # On a strictly rising series, once warm-up + confirmation pass the state is
    # True and tracks the current close (no lag beyond the documented debounce).
    s = _series([1, 2, 3, 4, 5, 6, 7, 8])
    con = confirmed_sma_signal(s, window=2, confirm=2)
    assert con.iloc[-1] == True  # current close above SMA -> confirmed bullish now
    assert pd.isna(con.iloc[0])  # SMA warm-up


def test_confirm_must_be_positive():
    s = _series([1, 2, 3])
    with pytest.raises(ValueError):
        confirmed_sma_signal(s, window=2, confirm=0)
