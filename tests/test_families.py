"""Tests for backtest/families.py — the GEM and Faber target-weight builders.

Hand-built monthly price series with known 12-month momenta / 10-month SMA
crossings pin which asset each rule selects. All offline / synthetic — no
network.
"""
from __future__ import annotations

import pandas as pd
import pytest

import math

from backtest.families import (
    faber_gtaa_weights,
    faber_single_weights,
    gem_weights,
    vol_target_weights,
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


# ---------------------------------------------------------------------------
# Vol-targeting: continuous SPY weight scaled to target annualised vol
# ---------------------------------------------------------------------------

def _build_spy_close(daily_returns: list[float], start: str = "2020-01-02") -> pd.Series:
    """Build a SPY close series from a list of daily simple returns.

    Starts at 100.0; each successive price is prev * (1 + ret).
    Index is a business-day range starting at start.
    """
    prices = [100.0]
    for r in daily_returns:
        prices.append(prices[-1] * (1.0 + r))
    idx = pd.bdate_range(start, periods=len(prices))
    return pd.Series(prices, index=idx)


def test_vol_target_higher_vol_lower_weight():
    """Higher realized vol on segment B produces a lower weight than segment A.

    Segment A: 30 days of small returns (~1% daily = 16% annualised).
    Segment B: 30 days of large returns (~4% daily = 63% annualised).
    After the 20-day warm-up, segment A should have a higher weight than B.
    """
    low_vol_ret = 0.01    # ~16% ann
    high_vol_ret = 0.04   # ~63% ann

    # Alternate-sign returns so the price doesn't drift to zero/infinity.
    low_rets = [low_vol_ret * (1 if i % 2 == 0 else -1) for i in range(30)]
    high_rets = [high_vol_ret * (1 if i % 2 == 0 else -1) for i in range(30)]

    spy = _build_spy_close(low_rets + high_rets)
    idx = spy.index
    w = vol_target_weights(spy, idx, target_vol=0.10, vol_window=20)

    assert list(w.columns) == ["SPY"]
    # Last day of segment A (index 30, the 31st price after 30 returns applied)
    # vs last day of segment B (index 60).
    w_low = w["SPY"].iloc[30]
    w_high = w["SPY"].iloc[-1]
    assert w_low > w_high, (
        f"low-vol period should have higher weight: w_low={w_low:.4f}, w_high={w_high:.4f}"
    )


def test_vol_target_weight_capped_at_one():
    """When realized vol < target vol, weight is capped at 1.0 (no leverage).

    Use target_vol=0.50 (50%) with very small daily returns (~0.1% -> ~1.6% ann).
    target/realized >> 1, so without the cap the weight would exceed 1.
    """
    tiny_rets = [0.001 * (1 if i % 2 == 0 else -1) for i in range(40)]
    spy = _build_spy_close(tiny_rets)
    idx = spy.index
    w = vol_target_weights(spy, idx, target_vol=0.50, vol_window=20, cap=1.0)

    post_warmup = w["SPY"].iloc[20:]  # first 20 rows are warm-up -> 0.0
    assert (post_warmup <= 1.0 + 1e-9).all(), "weight must never exceed cap=1.0"
    # At least one post-warmup value should be at the cap (would exceed without it).
    assert (post_warmup >= 1.0 - 1e-9).any(), "expected some rows pinned at cap"


def test_vol_target_warmup_is_cash():
    """First vol_window rows (where rolling std is NaN) must be 0.0 (cash).

    With vol_window=20 and a 30-return series, rows 0-19 are warm-up (fewer than
    20 complete returns in the window -> NaN std -> weight = 0.0).
    """
    rets = [0.01 * (1 if i % 2 == 0 else -1) for i in range(30)]
    spy = _build_spy_close(rets)
    idx = spy.index
    w = vol_target_weights(spy, idx, target_vol=0.10, vol_window=20)

    # The price series has 31 points (price[0] + 30 returns).
    # pct_change() produces NaN at position 0, then 30 returns.
    # rolling(20).std() first non-NaN is at position 20 (index 20 of the series).
    warmup = w["SPY"].iloc[:20]
    assert (warmup == 0.0).all(), f"warm-up rows must be 0.0 (cash), got:\n{warmup}"


def test_vol_target_no_pre_shift():
    """The returned weight is the close-T value — not shifted forward by one day.

    Build a price series where the last return is large (high vol on the final
    window). The weight on the LAST row of the output must reflect that last
    window's realized vol, not a stale prior day's value. If the builder had
    pre-shifted (shift(1)), the last row would carry the second-to-last window's
    weight instead of the final one.

    Strategy: 25 calm days then 5 high-vol days. The last 20-day window spans
    both. Compute realized_vol manually on the raw series and compare.
    """
    calm = [0.001 * (1 if i % 2 == 0 else -1) for i in range(25)]
    volatile = [0.05 * (1 if i % 2 == 0 else -1) for i in range(5)]
    rets = calm + volatile
    spy = _build_spy_close(rets)
    idx = spy.index

    w = vol_target_weights(spy, idx, target_vol=0.10, vol_window=20)

    # Manually compute the expected weight at the last date.
    ret_series = spy.pct_change()
    rv = ret_series.rolling(20).std(ddof=1) * math.sqrt(252)
    expected_w = min(0.10 / rv.iloc[-1], 1.0)

    got_w = w["SPY"].iloc[-1]
    assert got_w == pytest.approx(expected_w, rel=1e-6), (
        f"last-row weight {got_w:.6f} != expected close-T weight {expected_w:.6f}; "
        "builder must NOT pre-shift"
    )
