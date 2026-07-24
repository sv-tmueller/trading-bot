"""Tests for backtest/orb.py — ORB signal geometry, long and short (#434).

Offline / synthetic intraday OHLC (no network). Locks:
  - the opening range spans exactly the first `or_bars` bars of each session;
  - entries never fire on an OR bar and never cross a session boundary;
  - only the session's FIRST break trades, and it fills at the NEXT bar's open;
  - short mirrors long (break BELOW the OR low, stop at the OR high, target below);
  - R-multiple geometry is measured against the slippage-adjusted entry reference;
  - #431's frozen defaults (or_bars=1, long, or_opposite stop) are preserved.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.orb as orb
from backtest.bracket import simulate_bracket


def _session(day, n, o, h, l, c, start="14:30", freq="5min"):
    """One synthetic intraday session of n bars."""
    idx = pd.date_range(f"{day} {start}", periods=n, freq=freq)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c}, index=idx)


def _two_sessions(a, b):
    return pd.concat([a, b])


# ---------------------------------------------------------------------------
# opening_range
# ---------------------------------------------------------------------------

def test_opening_range_single_bar_is_that_bars_high_low():
    df = _session("2020-01-06", 4,
                  o=[100, 101, 102, 103],
                  h=[105, 106, 107, 108],
                  l=[95,  96,  97,  98],
                  c=[100, 101, 102, 103])
    or_high, or_low, is_or, _sess = orb.opening_range(df, or_bars=1)
    assert list(or_high) == [105.0] * 4          # broadcast to the whole session
    assert list(or_low) == [95.0] * 4
    assert list(is_or) == [True, False, False, False]


def test_opening_range_multi_bar_spans_exactly_or_bars():
    df = _session("2020-01-06", 5,
                  o=[100, 100, 100, 100, 100],
                  h=[105, 110, 200, 200, 200],   # bar2 high 110 inside a 3-bar OR
                  l=[95,  90,  1,   1,   1],     # bar2 low 90 inside; later lows ignored
                  c=[100, 100, 100, 100, 100])
    or_high, or_low, is_or, _sess = orb.opening_range(df, or_bars=3)
    assert or_high.iloc[0] == 200.0              # max of bars 0..2
    assert or_low.iloc[0] == 1.0                 # min of bars 0..2
    assert list(is_or) == [True, True, True, False, False]


def test_opening_range_is_per_session_not_global():
    a = _session("2020-01-06", 3, o=[100]*3, h=[105]*3, l=[95]*3, c=[100]*3)
    b = _session("2020-01-07", 3, o=[200]*3, h=[205]*3, l=[195]*3, c=[200]*3)
    df = _two_sessions(a, b)
    or_high, or_low, _is_or, _sess = orb.opening_range(df, or_bars=1)
    assert or_high.iloc[0] == 105.0 and or_high.iloc[3] == 205.0
    assert or_low.iloc[0] == 95.0 and or_low.iloc[3] == 195.0


def test_opening_range_rejects_zero_bars():
    df = _session("2020-01-06", 2, o=[100]*2, h=[105]*2, l=[95]*2, c=[100]*2)
    with pytest.raises(ValueError, match="or_bars must be >= 1"):
        orb.opening_range(df, or_bars=0)


# ---------------------------------------------------------------------------
# entry_trigger — long
# ---------------------------------------------------------------------------

def test_long_entry_fires_bar_after_the_break():
    df = _session("2020-01-06", 4,
                  o=[100, 100, 100, 100],
                  h=[105, 105, 105, 105],
                  l=[95,  95,  95,  95],
                  c=[100, 106, 100, 100])     # bar1 closes above the 105 OR high
    trig = orb.entry_trigger(df, or_bars=1, direction="long")
    assert list(trig) == [False, False, True, False]   # fills on bar2's open


def test_long_entry_never_on_an_or_bar():
    """A break on the OR bar itself is not a break, and cannot trigger."""
    df = _session("2020-01-06", 3,
                  o=[100, 100, 100],
                  h=[105, 105, 105],
                  l=[95,  95,  95],
                  c=[200, 100, 100])         # OR bar closes 'above' its own high
    trig = orb.entry_trigger(df, or_bars=1, direction="long")
    assert not trig.any()


def test_only_first_break_per_session_triggers():
    df = _session("2020-01-06", 5,
                  o=[100]*5,
                  h=[105]*5,
                  l=[95]*5,
                  c=[100, 106, 107, 108, 100])   # three breaks, only the first counts
    trig = orb.entry_trigger(df, or_bars=1, direction="long")
    assert list(trig) == [False, False, True, False, False]


def test_entry_does_not_leak_across_a_session_boundary():
    """A break on a session's LAST bar would fill on the next session's OR bar — dropped."""
    a = _session("2020-01-06", 2, o=[100]*2, h=[105]*2, l=[95]*2, c=[100, 106])
    b = _session("2020-01-07", 2, o=[100]*2, h=[105]*2, l=[95]*2, c=[100, 100])
    df = _two_sessions(a, b)
    trig = orb.entry_trigger(df, or_bars=1, direction="long")
    assert not trig.iloc[2]          # would be day 2's OR bar
    assert not trig.any()


def test_each_session_gets_its_own_entry():
    a = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4, c=[100, 106, 100, 100])
    b = _session("2020-01-07", 4, o=[100]*4, h=[105]*4, l=[95]*4, c=[100, 106, 100, 100])
    df = _two_sessions(a, b)
    trig = orb.entry_trigger(df, or_bars=1, direction="long")
    assert list(trig) == [False, False, True, False, False, False, True, False]


# ---------------------------------------------------------------------------
# entry_trigger — short (mirrored)
# ---------------------------------------------------------------------------

def test_short_entry_fires_on_break_below_the_or_low():
    df = _session("2020-01-06", 4,
                  o=[100]*4,
                  h=[105]*4,
                  l=[95]*4,
                  c=[100, 94, 100, 100])      # bar1 closes below the 95 OR low
    trig = orb.entry_trigger(df, or_bars=1, direction="short")
    assert list(trig) == [False, False, True, False]


def test_short_ignores_an_upside_break():
    df = _session("2020-01-06", 4,
                  o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])     # breaks UP: nothing for the short arm
    assert not orb.entry_trigger(df, or_bars=1, direction="short").any()


def test_long_ignores_a_downside_break():
    df = _session("2020-01-06", 4,
                  o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 94, 100, 100])
    assert not orb.entry_trigger(df, or_bars=1, direction="long").any()


def test_entry_trigger_rejects_bad_direction():
    df = _session("2020-01-06", 3, o=[100]*3, h=[105]*3, l=[95]*3, c=[100]*3)
    with pytest.raises(ValueError, match="direction must be one of"):
        orb.entry_trigger(df, direction="sideways")


# ---------------------------------------------------------------------------
# orb_levels — stop / target geometry
# ---------------------------------------------------------------------------

def test_long_levels_stop_at_or_low_and_target_is_r_multiple_of_risk():
    df = _session("2020-01-06", 4,
                  o=[100, 100, 100, 100],
                  h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    trig, stop, target = orb.build_orb(df, or_bars=1, direction="long", r=2.0,
                                       slippage_bps=0)
    i = 2                                        # the entry bar
    assert stop.iloc[i] == pytest.approx(95.0)   # OR low
    # entry_ref = Open = 100; risk = 100-95 = 5; target = 100 + 2*5 = 110
    assert target.iloc[i] == pytest.approx(110.0)


def test_short_levels_stop_at_or_high_and_target_below_entry():
    df = _session("2020-01-06", 4,
                  o=[100, 100, 100, 100],
                  h=[105]*4, l=[95]*4,
                  c=[100, 94, 100, 100])
    trig, stop, target = orb.build_orb(df, or_bars=1, direction="short", r=2.0,
                                       slippage_bps=0)
    i = 2
    assert stop.iloc[i] == pytest.approx(105.0)  # OR high — ABOVE the entry
    # risk = 105-100 = 5; target = 100 - 2*5 = 90 — BELOW the entry
    assert target.iloc[i] == pytest.approx(90.0)
    assert target.iloc[i] < 100.0 < stop.iloc[i]


def test_target_none_means_exit_at_close():
    df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    _trig, stop, target = orb.build_orb(df, or_bars=1, direction="long", r=None)
    assert target is None
    assert not np.isnan(stop.iloc[2])


def test_levels_are_nan_where_no_entry_triggers():
    df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    _trig, stop, target = orb.build_orb(df, or_bars=1, direction="long", r=2.0)
    assert np.isnan(stop.iloc[0]) and np.isnan(stop.iloc[1]) and np.isnan(stop.iloc[3])
    assert np.isnan(target.iloc[0])


def test_slippage_moves_the_entry_reference_per_direction():
    """A long's reference is marked UP, a short's DOWN — the fill each will actually get."""
    long_df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                       c=[100, 106, 100, 100])
    short_df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                        c=[100, 94, 100, 100])
    _t, _s, tgt_long = orb.build_orb(long_df, direction="long", r=1.0, slippage_bps=100)
    _t2, _s2, tgt_short = orb.build_orb(short_df, direction="short", r=1.0,
                                        slippage_bps=100)
    # long entry_ref = 101 -> risk 6 -> target 107 (above the zero-slip 105)
    assert tgt_long.iloc[2] == pytest.approx(107.0)
    # short entry_ref = 99 -> risk 6 -> target 93 (below the zero-slip 95)
    assert tgt_short.iloc[2] == pytest.approx(93.0)


def test_atr_stop_mode_uses_k_times_atr_from_the_entry_reference():
    df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    atr = pd.Series(4.0, index=df.index)
    _trig, stop, target = orb.build_orb(df, direction="long", r=2.0, stop_mode="atr",
                                        atr=atr, atr_k=1.5, slippage_bps=0)
    assert stop.iloc[2] == pytest.approx(100.0 - 1.5 * 4.0)   # 94
    assert target.iloc[2] == pytest.approx(100.0 + 2.0 * 6.0)  # risk 6 -> 112


def test_atr_stop_mode_requires_an_atr_series():
    df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    with pytest.raises(ValueError, match="requires an atr Series"):
        orb.build_orb(df, stop_mode="atr", atr=None)


def test_orb_levels_rejects_bad_stop_mode():
    df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    with pytest.raises(ValueError, match="stop_mode must be one of"):
        orb.build_orb(df, stop_mode="magic")


# ---------------------------------------------------------------------------
# End-to-end through the bracket engine (geometry + engine agree).
# ---------------------------------------------------------------------------

def test_long_orb_round_trip_hits_target_through_the_engine():
    df = _session("2020-01-06", 5,
                  o=[100, 100, 100, 100, 100],
                  h=[105, 105, 105, 111, 105],   # bar3 reaches the 110 target
                  l=[95,  95,  95,  99,  95],
                  c=[100, 106, 100, 110, 100])
    trig, stop, target = orb.build_orb(df, or_bars=1, direction="long", r=2.0,
                                       slippage_bps=0)
    res = simulate_bracket(df, trig, stop, target, slippage_bps=0, commission_bps=0,
                           eow_close_out=False, session_close_out=True,
                           direction="long")
    assert res["trade_count"] == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "target"
    assert t["exit_price"] == pytest.approx(110.0)
    assert t["pnl"] > 0


def test_short_orb_round_trip_hits_target_through_the_engine():
    df = _session("2020-01-06", 5,
                  o=[100, 100, 100, 100, 100],
                  h=[105, 105, 105, 101, 105],
                  l=[95,  95,  95,  89,  95],    # bar3 reaches the 90 target
                  c=[100, 94, 100, 90, 100])
    trig, stop, target = orb.build_orb(df, or_bars=1, direction="short", r=2.0,
                                       slippage_bps=0)
    res = simulate_bracket(df, trig, stop, target, slippage_bps=0, commission_bps=0,
                           eow_close_out=False, session_close_out=True,
                           direction="short")
    assert res["trade_count"] == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "target"
    assert t["exit_price"] == pytest.approx(90.0)
    assert t["pnl"] > 0          # a short that falls to its target MAKES money


def test_orb_position_is_flat_overnight():
    """session_close_out means an ORB lot never survives into the next session."""
    # After the entry the lows stay ABOVE the 95 OR-low stop and the highs below the
    # 10R target, so the ONLY thing that can close the lot is the session boundary.
    a = _session("2020-01-06", 4, o=[100]*4, h=[105, 105, 105, 105],
                 l=[95, 95, 99, 99], c=[100, 106, 100, 100])
    b = _session("2020-01-07", 4, o=[100]*4, h=[105]*4, l=[99]*4,
                 c=[100, 100, 100, 100])
    df = _two_sessions(a, b)
    trig, stop, target = orb.build_orb(df, or_bars=1, direction="long", r=10.0,
                                       slippage_bps=0)
    res = simulate_bracket(df, trig, stop, target, slippage_bps=0, commission_bps=0,
                           eow_close_out=False, session_close_out=True,
                           direction="long")
    t = res["trades"][0]
    assert t["exit_reason"] == "session"
    assert t["exit_date"] == a.index[-1]      # flattened on day 1's last bar


def test_431_frozen_defaults_are_preserved():
    """or_bars=1 + long + or_opposite is #431's frozen rule — the default call."""
    df = _session("2020-01-06", 4, o=[100]*4, h=[105]*4, l=[95]*4,
                  c=[100, 106, 100, 100])
    d_trig, d_stop, _d_tgt = orb.build_orb(df, r=None)
    e_trig, e_stop, _e_tgt = orb.build_orb(df, or_bars=1, direction="long",
                                           stop_mode="or_opposite", r=None)
    assert list(d_trig) == list(e_trig)
    assert d_stop.iloc[2] == pytest.approx(e_stop.iloc[2]) == pytest.approx(95.0)
