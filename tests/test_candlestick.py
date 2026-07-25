"""Tests for backtest/candlestick.py — the classic candlestick PATTERN detectors.

Offline / synthetic OHLC (no network). Every fixture is hand-constructed so the
expected classification is arithmetic, not eyeballed.

Locks the module's three structural contracts:
  - **No look-ahead.** A detector's value at bar t depends only on bars t, t-1, t-2;
    truncating the frame after t must not change it (property test).
  - **Warm-up is False, never NaN.** Rows without the required history are False and the
    returned dtype is bool.
  - **Degenerate bars are not setups.** A zero-range bar (high == low) is False for every
    registered pattern rather than raising or comparing against NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.candlestick as cs


def _frame(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Build an OHLC frame from ``(open, high, low, close)`` tuples on daily dates."""
    idx = pd.date_range("2020-01-01", periods=len(bars), freq="D")
    return pd.DataFrame(
        {
            "Open": [b[0] for b in bars],
            "High": [b[1] for b in bars],
            "Low": [b[2] for b in bars],
            "Close": [b[3] for b in bars],
        },
        index=idx,
    )


# A neutral filler bar: small body, symmetric, matches no directional pattern.
FILLER = (100.0, 100.5, 99.5, 100.0)


# ---------------------------------------------------------------------------
# One-bar patterns
# ---------------------------------------------------------------------------

def test_hammer_positive():
    # body=1, lower wick=3 (>=2x body), upper wick=0.2 (4.8% of range 4.2)
    df = _frame([FILLER, (100.0, 101.2, 97.0, 101.0)])
    assert bool(cs.hammer(df).iloc[1])


def test_hammer_rejects_long_upper_wick():
    # same body but the wick is on the WRONG side -> not a hammer
    df = _frame([FILLER, (100.0, 104.0, 99.8, 101.0)])
    assert not bool(cs.hammer(df).iloc[1])


def test_hammer_rejects_body_too_large_for_wick():
    # lower wick 1.0 is less than 2x the body 3.0
    df = _frame([FILLER, (100.0, 103.1, 99.0, 103.0)])
    assert not bool(cs.hammer(df).iloc[1])


def test_shooting_star_is_the_hammer_mirror():
    # mirror of test_hammer_positive about the horizontal: upper wick dominates
    df = _frame([FILLER, (101.0, 104.0, 100.8, 100.0)])
    assert bool(cs.shooting_star(df).iloc[1])
    assert not bool(cs.hammer(df).iloc[1])


def test_pin_bars_need_two_thirds_of_range_in_one_wick():
    # range 3.0, lower wick 2.4 = 80% -> bullish pin
    df = _frame([FILLER, (100.0, 100.6, 97.6, 100.2)])
    assert bool(cs.bullish_pin_bar(df).iloc[1])
    assert not bool(cs.bearish_pin_bar(df).iloc[1])


def test_marubozu_requires_body_to_dominate_range():
    # body 9.5 of range 10.0 = 95% -> bullish marubozu
    df = _frame([FILLER, (100.0, 110.0, 100.0, 109.5)])
    assert bool(cs.bullish_marubozu(df).iloc[1])
    assert not bool(cs.bearish_marubozu(df).iloc[1])
    # a bar with big wicks at the same body is not a marubozu
    df2 = _frame([FILLER, (100.0, 115.0, 95.0, 109.5)])
    assert not bool(cs.bullish_marubozu(df2).iloc[1])


def test_doji_is_a_small_body_relative_to_range():
    # body 0.05 of range 4.0 = 1.25% <= 10%
    df = _frame([FILLER, (100.0, 102.0, 98.0, 100.05)])
    assert bool(cs.doji(df).iloc[1])
    # a full-bodied bar is not a doji
    assert not bool(cs.doji(_frame([FILLER, (100.0, 110.0, 100.0, 110.0)])).iloc[1])


# ---------------------------------------------------------------------------
# Two-bar patterns
# ---------------------------------------------------------------------------

def test_bullish_engulfing_positive():
    # prev bearish 105->100; current bullish 99->106 strictly engulfs that body
    df = _frame([FILLER, (105.0, 105.5, 99.5, 100.0), (99.0, 106.5, 98.5, 106.0)])
    assert bool(cs.bullish_engulfing(df).iloc[2])


def test_bullish_engulfing_rejects_non_engulfing_body():
    # current bullish but opens ABOVE prev close -> no engulf
    df = _frame([FILLER, (105.0, 105.5, 99.5, 100.0), (101.0, 106.5, 100.5, 106.0)])
    assert not bool(cs.bullish_engulfing(df).iloc[2])


def test_engulfing_fires_when_open_equals_prior_close_no_gap():
    """Regression: containment is INCLUSIVE, so a gapless open still engulfs.

    On SPY/ES the open frequently sits exactly at the prior close. Under a strict ``<``
    test these patterns could only fire on gap days, making the gap — not the engulfing
    geometry — the actual signal. Caught on a synthetic no-gap frame where every
    engulfing arm produced structurally zero trades.
    """
    # prev bearish 105->100; current opens EXACTLY at 100 and closes above the prior open
    df = _frame([FILLER, (105.0, 105.5, 99.5, 100.0), (100.0, 106.5, 99.5, 106.0)])
    assert bool(cs.bullish_engulfing(df).iloc[2])
    # and the bearish mirror at an exactly-equal open
    df2 = _frame([FILLER, (100.0, 105.5, 99.5, 105.0), (105.0, 105.5, 98.5, 99.0)])
    assert bool(cs.bearish_engulfing(df2).iloc[2])


def test_harami_and_engulfing_are_separated_by_the_prior_bar_direction():
    """The two carry identical body inequalities; only the prior bar's direction differs."""
    # bearish prior + body between prior open/close -> harami, never engulfing
    bear_prior = _frame([FILLER, (110.0, 110.5, 99.5, 100.0), (102.0, 108.5, 101.5, 108.0)])
    assert bool(cs.bullish_harami(bear_prior).iloc[2])
    assert not bool(cs.bearish_engulfing(bear_prior).iloc[2])
    # bullish prior + body outside prior open/close -> engulfing, never harami
    bull_prior = _frame([FILLER, (100.0, 110.5, 99.5, 110.0), (111.0, 111.5, 98.5, 99.0)])
    assert bool(cs.bearish_engulfing(bull_prior).iloc[2])
    assert not bool(cs.bullish_harami(bull_prior).iloc[2])


def test_bullish_engulfing_requires_prior_bar_bearish():
    # prior bar is bullish -> not the pattern even though bodies engulf
    df = _frame([FILLER, (100.0, 105.5, 99.5, 105.0), (99.0, 106.5, 98.5, 106.0)])
    assert not bool(cs.bullish_engulfing(df).iloc[2])


def test_bearish_engulfing_is_the_mirror():
    df = _frame([FILLER, (100.0, 105.5, 99.5, 105.0), (106.0, 106.5, 98.5, 99.0)])
    assert bool(cs.bearish_engulfing(df).iloc[2])
    assert not bool(cs.bullish_engulfing(df).iloc[2])


def test_harami_is_the_inverse_of_engulfing():
    # prev bearish 110->100; current bullish 102->108 sits INSIDE that body
    df = _frame([FILLER, (110.0, 110.5, 99.5, 100.0), (102.0, 108.5, 101.5, 108.0)])
    assert bool(cs.bullish_harami(df).iloc[2])
    assert not bool(cs.bullish_engulfing(df).iloc[2])


def test_bearish_harami_positive():
    df = _frame([FILLER, (100.0, 110.5, 99.5, 110.0), (108.0, 108.5, 101.5, 102.0)])
    assert bool(cs.bearish_harami(df).iloc[2])


def test_inside_bar_requires_full_range_containment():
    df = _frame([FILLER, (100.0, 110.0, 90.0, 105.0), (101.0, 108.0, 92.0, 103.0)])
    assert bool(cs.inside_bar(df).iloc[2])
    # a bar poking above the mother bar's high is not inside
    df2 = _frame([FILLER, (100.0, 110.0, 90.0, 105.0), (101.0, 111.0, 92.0, 103.0)])
    assert not bool(cs.inside_bar(df2).iloc[2])


def test_inside_bar_is_direction_neutral_in_the_registry():
    assert cs.direction_of("inside_bar") == cs.NEUTRAL
    assert cs.direction_of("doji") == cs.NEUTRAL


# ---------------------------------------------------------------------------
# Three-bar patterns
# ---------------------------------------------------------------------------

def test_morning_star_positive():
    # t-2 bearish 110->100 (mid 105); t-1 small body (0.5 of range 2 = 25%) below 105;
    # t bullish closing 107 > 105
    df = _frame([
        FILLER,
        (110.0, 110.5, 99.5, 100.0),
        (98.0, 99.0, 97.0, 97.5),
        (99.0, 107.5, 98.5, 107.0),
    ])
    assert bool(cs.morning_star(df).iloc[3])


def test_morning_star_rejects_close_below_prior_midpoint():
    # identical except the final close (104) fails to clear the 105 midpoint
    df = _frame([
        FILLER,
        (110.0, 110.5, 99.5, 100.0),
        (98.0, 99.0, 97.0, 97.5),
        (99.0, 104.5, 98.5, 104.0),
    ])
    assert not bool(cs.morning_star(df).iloc[3])


def test_morning_star_rejects_large_middle_body():
    # middle bar body 4.0 of range 4.5 = 89% -> not a star
    df = _frame([
        FILLER,
        (110.0, 110.5, 99.5, 100.0),
        (98.0, 98.5, 94.0, 94.5),
        (99.0, 107.5, 98.5, 107.0),
    ])
    assert not bool(cs.morning_star(df).iloc[3])


def test_evening_star_positive():
    # t-2 bullish 100->110 (mid 105); t-1 small body above 105; t bearish closing 103
    df = _frame([
        FILLER,
        (100.0, 110.5, 99.5, 110.0),
        (112.0, 114.0, 111.0, 112.5),
        (111.0, 111.5, 102.5, 103.0),
    ])
    assert bool(cs.evening_star(df).iloc[3])


# ---------------------------------------------------------------------------
# Structural contracts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(cs.PATTERNS))
def test_warmup_rows_are_false_and_dtype_is_bool(name):
    df = _frame([FILLER, FILLER, FILLER])
    out = cs.detect(name, df)
    assert out.dtype == bool, f"{name} returned {out.dtype}, expected bool"
    assert not out.isna().any()
    # the first row can never satisfy a 2- or 3-bar pattern
    if name not in ("doji", "hammer", "shooting_star", "bullish_pin_bar",
                    "bearish_pin_bar", "bullish_marubozu", "bearish_marubozu"):
        assert not bool(out.iloc[0]), f"{name} fired on the first bar with no history"


@pytest.mark.parametrize("name", sorted(cs.PATTERNS))
def test_zero_range_bar_is_never_a_setup(name):
    # a halted/limit print: high == low == open == close
    df = _frame([FILLER, (100.0, 100.0, 100.0, 100.0), FILLER])
    assert not bool(cs.detect(name, df).iloc[1]), f"{name} fired on a zero-range bar"


@pytest.mark.parametrize("name", sorted(cs.PATTERNS))
def test_no_look_ahead_truncation_invariance(name):
    """Truncating the frame after bar t must not change the detector's value at t.

    This is the property that actually rules out look-ahead: if any detector consulted a
    future bar, removing that bar would flip the earlier value.
    """
    rng = np.random.default_rng(7)
    n = 60
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    bars = []
    for i in range(n):
        o = float(close[i - 1]) if i else 100.0
        c = float(close[i])
        hi = max(o, c) + abs(float(rng.normal(0, 0.6)))
        lo = min(o, c) - abs(float(rng.normal(0, 0.6)))
        bars.append((o, hi, lo, c))
    df = _frame(bars)
    full = cs.detect(name, df)
    for cut in (20, 35, 50):
        truncated = cs.detect(name, df.iloc[:cut])
        pd.testing.assert_series_equal(
            truncated, full.iloc[:cut], check_names=False,
            obj=f"{name} truncated at {cut}",
        )


def test_registry_is_complete_and_directions_are_valid():
    assert len(cs.PATTERNS) == 14, "registry size is the frozen multiplicity count"
    for name, (fn, direction) in cs.PATTERNS.items():
        assert callable(fn), name
        assert direction in (cs.BULLISH, cs.BEARISH, cs.NEUTRAL), (name, direction)
    # every bullish pattern has a bearish counterpart and vice versa
    bulls = {n for n, (_, d) in cs.PATTERNS.items() if d == cs.BULLISH}
    bears = {n for n, (_, d) in cs.PATTERNS.items() if d == cs.BEARISH}
    assert len(bulls) == len(bears) == 6


def test_detect_and_direction_of_reject_unknown_names():
    df = _frame([FILLER, FILLER])
    with pytest.raises(KeyError, match="unknown pattern"):
        cs.detect("not_a_pattern", df)
    with pytest.raises(KeyError, match="unknown pattern"):
        cs.direction_of("not_a_pattern")


def test_bullish_and_bearish_arms_are_mutually_exclusive_on_a_directional_bar():
    """A strongly bullish bar must not simultaneously fire a bearish directional pattern."""
    df = _frame([FILLER, (105.0, 105.5, 99.5, 100.0), (99.0, 106.5, 98.5, 106.0)])
    assert bool(cs.bullish_engulfing(df).iloc[2])
    for name, (fn, direction) in cs.PATTERNS.items():
        if direction == cs.BEARISH:
            assert not bool(fn(df).iloc[2]), f"{name} fired on a bullish engulfing bar"
