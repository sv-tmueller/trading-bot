"""Tests for backtest/families.py — the GEM and Faber target-weight builders.

Hand-built monthly price series with known 12-month momenta / 10-month SMA
crossings pin which asset each rule selects. All offline / synthetic — no
network.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest.families import (
    faber_gtaa_weights,
    faber_single_weights,
    gem_weights,
)


def _daily_from_monthly(monthly_vals: list[float], start: str = "2000-01-31") -> pd.Series:
    """Build a daily close series whose month-end values equal monthly_vals.

    Each month is filled with a constant equal to that month's target value, on a
    business-day index, so resample('ME').last() reproduces monthly_vals exactly.
    """
    month_ends = pd.date_range(start, periods=len(monthly_vals), freq="ME")
    pieces = []
    prev_end = month_ends[0] - pd.offsets.MonthBegin(1)
    for val, me in zip(monthly_vals, month_ends):
        days = pd.bdate_range(prev_end, me)
        pieces.append(pd.Series(val, index=days))
        prev_end = me + pd.offsets.Day(1)
    s = pd.concat(pieces)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


# ---------------------------------------------------------------------------
# GEM: absolute + relative momentum selection
# ---------------------------------------------------------------------------

def test_gem_risk_off_picks_agg_when_spy_below_bill():
    """SPY 12m return below the BIL hurdle -> risk-off -> hold AGG.

    Construct 13 months. SPY falls over the trailing 12 months (month 0 -> 12 is
    down), while BIL inches up. At month 12 SPY's 12m return < BIL's 12m return,
    so absolute momentum fails and GEM must select AGG regardless of EFA.
    """
    spy = _daily_from_monthly([100.0] * 1 + [100 - i for i in range(1, 13)])  # 100 -> 88
    efa = _daily_from_monthly([100.0] + [100 + i for i in range(1, 13)])       # EFA strongly up
    agg = _daily_from_monthly([100.0] * 13)
    bil = _daily_from_monthly([100.0] + [100 + 0.1 * i for i in range(1, 13)]) # BIL up ~1.2%

    idx = spy.index.intersection(efa.index).intersection(agg.index)
    w = gem_weights({"SPY": spy, "EFA": efa, "AGG": agg, "BIL": bil}, idx)

    last = w.iloc[-1]
    assert last["AGG"] == pytest.approx(1.0), f"risk-off should hold AGG, got {last.to_dict()}"
    assert last["SPY"] == pytest.approx(0.0)
    assert last["EFA"] == pytest.approx(0.0)


def test_gem_risk_on_picks_higher_momentum_of_spy_efa():
    """Risk-on (SPY 12m > BIL) -> hold the higher 12m return of SPY vs EFA.

    SPY rises +20% over 12 months and EFA +50%; BIL ~flat. Absolute momentum
    passes (SPY up), and relative momentum favours EFA (50% > 20%) -> hold EFA.
    """
    spy = _daily_from_monthly([100.0] + [100 + (20.0 * i / 12) for i in range(1, 13)])  # ->120
    efa = _daily_from_monthly([100.0] + [100 + (50.0 * i / 12) for i in range(1, 13)])  # ->150
    agg = _daily_from_monthly([100.0] * 13)
    bil = _daily_from_monthly([100.0] * 13)

    idx = spy.index.intersection(efa.index).intersection(agg.index)
    w = gem_weights({"SPY": spy, "EFA": efa, "AGG": agg, "BIL": bil}, idx)

    last = w.iloc[-1]
    assert last["EFA"] == pytest.approx(1.0), f"EFA has higher momentum, got {last.to_dict()}"
    assert last["SPY"] == pytest.approx(0.0)
    assert last["AGG"] == pytest.approx(0.0)


def test_gem_risk_on_picks_spy_when_spy_beats_efa():
    """Risk-on and SPY's 12m return beats EFA's -> hold SPY."""
    spy = _daily_from_monthly([100.0] + [100 + (50.0 * i / 12) for i in range(1, 13)])  # ->150
    efa = _daily_from_monthly([100.0] + [100 + (20.0 * i / 12) for i in range(1, 13)])  # ->120
    agg = _daily_from_monthly([100.0] * 13)
    bil = _daily_from_monthly([100.0] * 13)

    idx = spy.index.intersection(efa.index).intersection(agg.index)
    w = gem_weights({"SPY": spy, "EFA": efa, "AGG": agg, "BIL": bil}, idx)

    last = w.iloc[-1]
    assert last["SPY"] == pytest.approx(1.0), f"SPY has higher momentum, got {last.to_dict()}"


def test_gem_warmup_is_cash():
    """Before 12 monthly returns exist, every row is all-zero (cash)."""
    spy = _daily_from_monthly([100.0 + i for i in range(6)])  # only 6 months
    efa = _daily_from_monthly([100.0 + i for i in range(6)])
    agg = _daily_from_monthly([100.0] * 6)
    bil = _daily_from_monthly([100.0] * 6)
    idx = spy.index.intersection(efa.index).intersection(agg.index)
    w = gem_weights({"SPY": spy, "EFA": efa, "AGG": agg, "BIL": bil}, idx)
    assert (w.sum(axis=1) == 0.0).all(), "no 12m momentum yet -> all cash"


def test_gem_rows_are_one_hot_or_cash():
    """Every GEM row holds at most one asset at 100% (or all cash).

    Warm-up rows before the first month-end decision are NaN (the simulator
    reads NaN as cash); ``.sum(axis=1)`` skips NaN so they sum to 0.0. Post
    warm-up, every row is one-hot (sum 1.0) or all-cash (sum 0.0); none exceeds
    1.0 (no leverage).
    """
    spy = _daily_from_monthly([100.0 + i for i in range(15)])
    efa = _daily_from_monthly([100.0 + 0.5 * i for i in range(15)])
    agg = _daily_from_monthly([100.0] * 15)
    bil = _daily_from_monthly([100.0] * 15)
    idx = spy.index.intersection(efa.index).intersection(agg.index)
    w = gem_weights({"SPY": spy, "EFA": efa, "AGG": agg, "BIL": bil}, idx)
    row_sums = w.fillna(0.0).sum(axis=1)
    is_cash = row_sums.abs() < 1e-9
    is_full = (row_sums - 1.0).abs() < 1e-9
    assert (is_cash | is_full).all()
    # no row exceeds 1.0 (no leverage)
    assert (row_sums <= 1.0 + 1e-9).all()


# ---------------------------------------------------------------------------
# Faber single-asset: 10-month SMA crossing
# ---------------------------------------------------------------------------

def test_faber_single_flips_on_known_sma_crossing():
    """Price above its 10-month SMA -> long SPY (1.0); below -> cash (0.0).

    Build 14 months: a flat run at 100 (months 0-9), month 10 jumps to 130
    (above the 10-mo SMA), month 11 drops to 70 (below), then two trailing flat
    months at 70 so both the up-cross (month 10) and the down-cross (month 11)
    month-ends are strictly interior to the daily index (a ffilled monthly
    signal only becomes visible the trading day AFTER its month-end close).

    SMA(10) at month 10 = mean(months 1..10) = mean(100*9, 130) = 103 -> 130>103
    -> long.  SMA(10) at month 11 = mean(months 2..11) = mean(100*8, 130, 70) =
    100 -> 70<100 -> cash.
    """
    spy = _daily_from_monthly([100.0] * 10 + [130.0, 70.0, 70.0, 70.0])
    idx = spy.index
    w = faber_single_weights(spy, idx)

    me10 = pd.date_range("2000-01-31", periods=11, freq="ME")[-1]  # up-cross month-end
    me11 = pd.date_range("2000-01-31", periods=12, freq="ME")[-1]  # down-cross month-end
    me12 = pd.date_range("2000-01-31", periods=13, freq="ME")[-1]
    # Month 11 (the trading days strictly after month-10 close, value 130 carried
    # forward) is long: the up-cross decision is visible there.
    in_m11 = w.loc[(w.index > me10) & (w.index <= me11)]
    assert in_m11["SPY"].iloc[-1] == pytest.approx(1.0), "above 10mo SMA -> long"
    # Month 12 (trading days after month-11 close, value 70) is cash: the
    # down-cross decision is now visible.
    in_m12 = w.loc[(w.index > me11) & (w.index <= me12)]
    assert in_m12["SPY"].iloc[-1] == pytest.approx(0.0), "below 10mo SMA -> cash"


def test_faber_single_is_one_column_zero_one_frame():
    """Output is a single SPY column of only 0.0/1.0 (dispatchable to binary)."""
    spy = _daily_from_monthly([100.0 + i for i in range(14)])
    w = faber_single_weights(spy, spy.index)
    assert list(w.columns) == ["SPY"]
    vals = set(w["SPY"].unique())
    assert vals.issubset({0.0, 1.0}), f"expected only 0/1, got {vals}"


# ---------------------------------------------------------------------------
# Faber 5-asset GTAA-lite: per-sleeve 1/N
# ---------------------------------------------------------------------------

def test_gtaa_all_above_sma_is_fully_invested_equal_weight():
    """All five sleeves above their 10-mo SMA -> each 0.2, row sum 1.0."""
    assets = ("SPY", "EFA", "AGG", "DBC", "VNQ")
    closes = {a: _daily_from_monthly([100.0] * 10 + [120.0, 121.0, 122.0]) for a in assets}
    idx = None
    for a in assets:
        idx = closes[a].index if idx is None else idx.intersection(closes[a].index)
    w = faber_gtaa_weights(closes, idx)
    last = w.iloc[-1]
    for a in assets:
        assert last[a] == pytest.approx(0.2), f"{a} above SMA should be 0.2, got {last[a]}"
    assert last.sum() == pytest.approx(1.0)


def test_gtaa_mixed_signals_partial_allocation():
    """Some sleeves below their SMA sit in cash; row sum = 0.2 * (#above).

    SPY/EFA/AGG sit above their SMA at month 11; DBC/VNQ crash below it. A
    trailing flat month makes the month-11 decision interior to the daily index
    so the ffilled monthly weights are visible on the last day.
    """
    assets = ("SPY", "EFA", "AGG", "DBC", "VNQ")
    up = _daily_from_monthly([100.0] * 10 + [120.0, 125.0, 125.0])
    down = _daily_from_monthly([100.0] * 10 + [120.0, 60.0, 60.0])
    closes = {"SPY": up, "EFA": up, "AGG": up, "DBC": down, "VNQ": down}
    idx = None
    for a in assets:
        idx = closes[a].index if idx is None else idx.intersection(closes[a].index)
    w = faber_gtaa_weights(closes, idx)
    last = w.iloc[-1]
    assert last["SPY"] == pytest.approx(0.2)
    assert last["EFA"] == pytest.approx(0.2)
    assert last["AGG"] == pytest.approx(0.2)
    assert last["DBC"] == pytest.approx(0.0), "DBC below SMA -> cash"
    assert last["VNQ"] == pytest.approx(0.0), "VNQ below SMA -> cash"
    assert last.sum() == pytest.approx(0.6)


def test_gtaa_rows_never_exceed_one():
    """No-leverage guarantee: every GTAA row sums to <= 1."""
    assets = ("SPY", "EFA", "AGG", "DBC", "VNQ")
    closes = {a: _daily_from_monthly([100.0 + i + hash(a) % 5 for i in range(14)]) for a in assets}
    idx = None
    for a in assets:
        idx = closes[a].index if idx is None else idx.intersection(closes[a].index)
    w = faber_gtaa_weights(closes, idx)
    assert (w.sum(axis=1) <= 1.0 + 1e-9).all()
