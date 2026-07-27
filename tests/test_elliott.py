"""Tests for backtest/elliott.py — the deterministic Elliott Wave labeler (#468).

Offline / synthetic OHLC (no network). Every fixture is a hand-constructed knot path so
every ratio is exact arithmetic, never eyeballed (same standard as tests/test_candlestick.py).

Locks the module's structural contracts:
  - **No look-ahead** at both the pivot level (``confirmed_idx > pivot_idx``, always) and
    the structure level (truncation invariance property test).
  - **Determinism**: two calls on the same input produce byte-identical labels.
  - **Scale invariance**: multiplying the whole path by a constant does not change the
    labels (every ratio in the grammar is scale-free).
  - **Anti-oracle**: a pure sawtooth with all legs equal must NOT produce an impulse label
    (guards against a labeler that fires on any alternating sequence).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.elliott as ew


# ---------------------------------------------------------------------------
# Fixture helper — linear interpolation between (bar_index, price) knots.
# ---------------------------------------------------------------------------

def _path(knots: list) -> pd.DataFrame:
    """Build an OHLC frame whose Close follows the given knots exactly (linear
    interpolation between them), with Open/High/Low derived so a validator would pass.
    ``knots`` is a list of ``(bar_index, price)`` pairs, strictly increasing bar_index.
    """
    xs = [k[0] for k in knots]
    ys = [k[1] for k in knots]
    n = xs[-1] + 1
    close = np.interp(np.arange(n), xs, ys)
    idx = pd.date_range("2020-01-01", periods=n, freq="h")
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close)
    low = np.minimum(open_, close)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close}, index=idx
    )


def _flat(n: int, price: float = 100.0) -> pd.DataFrame:
    return _path([(0, price), (n - 1, price)])


# ---------------------------------------------------------------------------
# Pivots (8 tests) — the causal ZigZag state machine.
# ---------------------------------------------------------------------------

def test_find_pivots_below_theta_noise_yields_zero_pivots():
    # Oscillates +/-1% around 100, theta=10% -> never breaches.
    df = _path([(0, 100.0), (1, 101.0), (2, 99.5), (3, 100.5), (4, 99.8)])
    pivots = ew.find_pivots(df, theta=0.10)
    assert len(pivots) == 0


def test_find_pivots_exactly_at_theta_pins_inclusive_convention():
    theta = 0.10
    peak = 110.0
    threshold = peak * (1 - theta)  # computed identically to the implementation
    df = _path([(0, 100.0), (1, peak), (2, threshold)])
    pivots = ew.find_pivots(df, theta=theta)
    assert len(pivots) == 1
    row = pivots.iloc[0]
    assert row["kind"] == "H"
    assert row["pivot_idx"] == 1
    assert row["pivot_price"] == pytest.approx(peak)
    assert row["confirmed_idx"] == 2


def test_find_pivots_one_clean_leg_then_reversal_confirms_exactly_one_high():
    theta = 0.10
    peak = 110.0
    threshold = peak * (1 - theta)
    df = _path([(0, 100.0), (1, 105.0), (2, peak), (3, 108.0), (4, threshold - 0.5)])
    pivots = ew.find_pivots(df, theta=theta)
    assert len(pivots) == 1
    row = pivots.iloc[0]
    assert row["kind"] == "H"
    assert row["pivot_idx"] == 2  # the actual peak bar, not bar 1 or bar 3
    assert row["confirmed_idx"] == 4


def test_find_pivots_final_unconfirmed_leg_is_never_emitted():
    theta = 0.10
    peak = 110.0
    threshold = peak * (1 - theta)
    # Confirm one HIGH pivot, then start a second (DOWN) leg that never reverses back.
    df = _path([(0, 100.0), (1, peak), (2, threshold), (3, threshold - 2.0)])
    pivots = ew.find_pivots(df, theta=theta)
    assert len(pivots) == 1  # the pending low at bar 3 is NOT emitted
    assert pivots.iloc[0]["kind"] == "H"


def test_find_pivots_confirmed_idx_after_pivot_idx_property():
    rng = np.random.default_rng(11)
    n = 300
    steps = rng.normal(0, 0.004, n)
    close = 100.0 * np.cumprod(1.0 + steps)
    idx = pd.date_range("2020-01-01", periods=n, freq="h")
    open_ = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame(
        {"Open": open_, "High": np.maximum(open_, close), "Low": np.minimum(open_, close),
         "Close": close},
        index=idx,
    )
    pivots = ew.find_pivots(df, theta=0.003)
    assert len(pivots) > 5  # sanity: the random walk actually produced pivots
    assert (pivots["confirmed_idx"] > pivots["pivot_idx"]).all()


def test_find_pivots_flat_series_yields_zero_pivots_no_exception():
    df = _flat(10)
    pivots = ew.find_pivots(df, theta=0.003)
    assert len(pivots) == 0


def test_find_pivots_empty_and_one_bar_frames_yield_empty_result():
    empty = _flat(10).iloc[0:0]
    assert len(ew.find_pivots(empty)) == 0
    one_bar = _flat(10).iloc[0:1]
    assert len(ew.find_pivots(one_bar)) == 0


def test_find_pivots_nan_input_raises():
    df = _flat(5).copy()
    df.loc[df.index[2], "Close"] = np.nan
    with pytest.raises(ValueError):
        ew.find_pivots(df)
