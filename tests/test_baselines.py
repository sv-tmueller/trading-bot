"""Tests for backtest/baselines.py.

All offline — no network calls. Verifies:
- buy_and_hold_signal: always True (flip_count=0)
- persistence_signal: lag-1 sign (transitions at price reversals)
- faber_sma_signal: monthly transitions only (Trap B)
- tsmom_signal: monthly transitions only, flat during 12-mo warm-up (Trap B)
- NaN→flat during warm-up for all monthly rules
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.baselines import (
    buy_and_hold_signal,
    faber_sma_signal,
    persistence_signal,
    tsmom_signal,
)


def _daily_index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=periods)


# ---------------------------------------------------------------------------
# buy_and_hold_signal
# ---------------------------------------------------------------------------

def test_bah_always_true():
    """B&H signal is always True, flip count is 0."""
    idx = _daily_index("2020-01-02", 100)
    closes = pd.Series(np.random.rand(100) * 100 + 50, index=idx)
    sig = buy_and_hold_signal(closes)
    assert sig.all(), "B&H should be True on every day"
    # Flip count: number of True→False or False→True transitions
    flips = (sig != sig.shift(1)).sum() - 1  # subtract first NaN comparison
    assert flips == 0, f"B&H should have 0 flips, got {flips}"


def test_bah_length_matches_input():
    idx = _daily_index("2020-01-02", 50)
    closes = pd.Series([100.0] * 50, index=idx)
    sig = buy_and_hold_signal(closes)
    assert len(sig) == 50


# ---------------------------------------------------------------------------
# persistence_signal
# ---------------------------------------------------------------------------

def test_persistence_lag1_sign():
    """Persistence = lag-1 sign: True when yesterday's return > 0."""
    idx = _daily_index("2023-01-02", 6)
    # Day-over-day: up, up, down, up, down
    closes = pd.Series([100.0, 102.0, 104.0, 101.0, 103.0, 100.0], index=idx)
    sig = persistence_signal(closes)
    # Day 0: NaN (no prior day)
    assert pd.isna(sig.iloc[0]), "first day should be NaN (no prior)"
    # Day 1: close[1] > close[0] → True
    assert sig.iloc[1] is True or bool(sig.iloc[1]) is True
    # Day 2: close[2] > close[1] → True
    assert bool(sig.iloc[2]) is True
    # Day 3: close[3] < close[2] → False
    assert bool(sig.iloc[3]) is False
    # Day 4: close[4] > close[3] → True
    assert bool(sig.iloc[4]) is True
    # Day 5: close[5] < close[4] → False
    assert bool(sig.iloc[5]) is False


def test_persistence_flat_close_is_false():
    """Flat close (return == 0) → persistence is False (not bullish)."""
    idx = _daily_index("2023-01-02", 4)
    closes = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    sig = persistence_signal(closes)
    # Day 1 onward: flat → return 0 → NOT strictly positive → False
    assert bool(sig.iloc[1]) is False


# ---------------------------------------------------------------------------
# faber_sma_signal
# ---------------------------------------------------------------------------

def _make_monthly_close_above_sma(n_months: int = 20) -> pd.Series:
    """Construct a series where monthly close stays above 10-mo SMA after warm-up."""
    # Generate daily data for n_months months, starting 2010-01-04
    idx = pd.bdate_range("2010-01-04", periods=n_months * 21)  # ~21 bdays/month
    # Gradually rising prices so close > 10-mo SMA after first 10 months
    prices = [float(100 + i * 0.5) for i in range(len(idx))]
    return pd.Series(prices, index=idx)


def test_faber_transitions_only_at_month_end():
    """Faber SMA signal must only change value at month-end boundaries (Trap B).

    'Month boundary' means: the first business day on or after a calendar
    month-end. This occurs when the 'ME' resample date (calendar month-end,
    which may be a weekend) is forward-filled to the daily business-day index —
    the signal first appears on the next business day.
    """
    closes = _make_monthly_close_above_sma(n_months=24)
    sig = faber_sma_signal(closes)

    # Find all days where signal transitions (ignoring NaN)
    valid = sig.dropna()
    transitions = valid[valid != valid.shift(1)].dropna()

    for ts in transitions.index:
        # Check: is this date the first business day on or after a calendar month-end?
        # Calendar month-end for the prior month: e.g. for Nov 1 transition → Oct 31
        # The month-end resample date is the last day of the prior month.
        prior_month_end = (ts - pd.offsets.MonthEnd(1))
        next_bday_after_month_end = prior_month_end + pd.offsets.BDay(0)
        # BDay(0) snaps to current day if already a business day, else next bday
        is_at_month_boundary = (ts == next_bday_after_month_end)
        assert is_at_month_boundary, (
            f"Faber signal changed on {ts} ({ts.day_name()}), which is not the first "
            f"business day after a month-end. Prior month-end: {prior_month_end.date()}. "
            f"Expected first bday on/after that: {next_bday_after_month_end.date()}. "
            f"Transitions must only occur at month boundaries."
        )


def test_faber_nan_during_warmup():
    """Faber should return NaN for the first 10 months (insufficient data for SMA-10)."""
    # Only 8 months of data — not enough for 10-mo SMA → all NaN
    idx = pd.bdate_range("2010-01-04", periods=8 * 21)
    prices = pd.Series([float(100 + i) for i in range(len(idx))], index=idx)
    sig = faber_sma_signal(prices)
    # All should be NaN since we can't complete 10-month SMA
    assert sig.isna().all() or sig.dropna().empty, "Should be NaN during warm-up"


def test_faber_consistent_within_month():
    """Within a calendar month, Faber signal must not change value (Trap B verification)."""
    closes = _make_monthly_close_above_sma(n_months=24)
    sig = faber_sma_signal(closes)
    valid = sig.dropna()

    # Group by month; signal should be constant within each month
    months = valid.groupby([valid.index.year, valid.index.month])
    for (yr, mo), group in months:
        unique_vals = group.dropna().unique()
        assert len(unique_vals) <= 1, (
            f"Faber signal changed within month {yr}-{mo:02d}: {unique_vals}"
        )


# ---------------------------------------------------------------------------
# tsmom_signal
# ---------------------------------------------------------------------------

def _make_tsmom_series(n_months: int = 20) -> pd.Series:
    """Ascending daily close series to give positive 12-mo momentum after warm-up."""
    idx = pd.bdate_range("2010-01-04", periods=n_months * 21)
    prices = [float(100 + i * 0.3) for i in range(len(idx))]
    return pd.Series(prices, index=idx)


def test_tsmom_nan_during_warmup():
    """TSMOM should be NaN for the first 12 months (insufficient lookback)."""
    # Only 10 months of data
    idx = pd.bdate_range("2010-01-04", periods=10 * 21)
    prices = pd.Series([float(100 + i) for i in range(len(idx))], index=idx)
    sig = tsmom_signal(prices)
    # All NaN since we can't compute 12-mo trailing return
    assert sig.isna().all() or sig.dropna().empty, "Should be NaN during 12-mo warm-up"


def test_tsmom_transitions_only_at_month_end():
    """TSMOM signal must only change value at month-end boundaries (Trap B)."""
    closes = _make_tsmom_series(n_months=30)
    sig = tsmom_signal(closes)

    valid = sig.dropna()
    transitions = valid[valid != valid.shift(1)].dropna()

    for ts in transitions.index:
        assert ts == ts + pd.offsets.BMonthEnd(0), (
            f"TSMOM signal changed on {ts}, not a month-end. "
            f"Transitions must only occur at month boundaries."
        )


def test_tsmom_positive_return_is_bullish():
    """If 12-mo trailing return is positive, signal should be True."""
    # Create a series that's risen over 12+ months (ascending price)
    idx = pd.bdate_range("2010-01-04", periods=15 * 21)
    prices = pd.Series([float(100 + i) for i in range(len(idx))], index=idx)
    sig = tsmom_signal(prices)

    # After warm-up (12 months), signal should be True (rising prices → pos 12-mo return)
    valid = sig.dropna()
    if len(valid) > 0:
        assert valid.iloc[-1] is True or bool(valid.iloc[-1]) is True, (
            "Rising series should produce bullish TSMOM signal after warm-up"
        )


def test_tsmom_consistent_within_month():
    """Within a calendar month, TSMOM signal must not change value (Trap B)."""
    closes = _make_tsmom_series(n_months=30)
    sig = tsmom_signal(closes)
    valid = sig.dropna()

    months = valid.groupby([valid.index.year, valid.index.month])
    for (yr, mo), group in months:
        unique_vals = group.dropna().unique()
        assert len(unique_vals) <= 1, (
            f"TSMOM signal changed within month {yr}-{mo:02d}: {unique_vals}"
        )
