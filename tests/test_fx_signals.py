"""Tests for backtest/fx_signals.py — the 11 pre-registered signal shapes
(#376, spec `docs/research/2026-07-13-forex-4h-strategy-preregistration.md`
frozen at SHA e409bf8, §3) plus the frozen registry (§4).

Every family's -1/0/+1 sequence is hand-derived from the spec text alone in
a tiny synthetic fixture — no real EUR/USD data, no cache access. All offline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import fx_signals as fs


def _series(values: list) -> pd.Series:
    idx = pd.date_range("2024-01-08", periods=len(values), freq="4h", tz="UTC")
    idx.name = "datetime_utc"
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# T1 — SMA cross (§3 T1)
# ---------------------------------------------------------------------------

def test_t1_sma_cross_warmup_tie_and_cross_events():
    """fast=2, slow=3 on a hand-picked price path:
    - i=0,1: warm-up (slow undefined at i<2, or prior bar undefined) -> 0
    - i=3: fast==slow (tie AT the current bar) -> 0 (theta=0 tie rule)
    - i=4: genuine cross-down (fast[3]>=slow[3] via the tie, fast[4]<slow[4]) -> -1
    - i=5: genuine cross-up (fast[4]<=slow[4], fast[5]>slow[5]) -> +1
    - i=6: still above, no new cross -> 0
    - i=7: genuine cross-down (fast[6]>=slow[6], fast[7]<slow[7]) -> -1
    Hand computation (SMA = trailing mean INCLUDING current bar):
      prices: [10,10,10,10,5,20,2,1]
      fast[i]=mean(p[i-1],p[i]); slow[i]=mean(p[i-2],p[i-1],p[i])
      fast: [NaN,10,10,10,7.5,12.5,11,1.5]
      slow: [NaN,NaN,10,10,8.333,11.667,9,7.667]
    A prior-bar TIE counts as "on that side already" for both the <= and >=
    mirror conditions (spec §3 T1's cross clause is stated with <=/>=, not
    strict < / >), so a tie immediately followed by a strict move is a
    genuine cross event -- this is exercised at i=4 (tie at i=3 -> strictly
    below at i=4).
    """
    close = _series([10, 10, 10, 10, 5, 20, 2, 1])
    sig = fs.sma_cross_signal(close, fast=2, slow=3)

    assert sig.dtype == np.int64 or sig.dtype == int
    assert set(sig.unique()).issubset({-1, 0, 1})
    assert list(sig.index) == list(close.index)

    assert sig.iloc[0] == 0  # both NaN
    assert sig.iloc[1] == 0  # slow NaN (i-1 also NaN via warmup)
    assert sig.iloc[2] == 0  # slow first defined but prior (i=1) slow is NaN -> decline
    assert sig.iloc[3] == 0  # fast==slow==10 tie at the current bar
    assert sig.iloc[4] == -1  # cross-down: fast[3]>=slow[3] (tie) and fast[4]<slow[4]
    assert sig.iloc[5] == 1  # cross-up: fast[4]<=slow[4] and fast[5]>slow[5]
    assert sig.iloc[6] == 0  # still above, no new cross
    assert sig.iloc[7] == -1  # cross-down: fast[6]>=slow[6] and fast[7]<slow[7]


def test_t1_sma_cross_no_pre_shift():
    """The signal at bar t reflects information available AT bar t's close —
    the function itself does not shift; simulate_fx applies T->T+1."""
    close = _series([10, 10, 10, 10, 5, 20, 2, 1])
    sig = fs.sma_cross_signal(close, fast=2, slow=3)
    # The cross-up is detectable exactly at i=5, not i=6 (would be true if
    # the function itself had pre-shifted the signal by one bar).
    assert sig.iloc[5] == 1
    assert sig.iloc[6] != 1


# ---------------------------------------------------------------------------
# T2 — Donchian breakout (§3 T2)
# ---------------------------------------------------------------------------

def test_t2_donchian_excludes_current_bar_off_by_one():
    """A spike in the CURRENT bar's own high must NOT raise its own channel
    (the pinned off-by-one). N=2.
    bar0: high=10 low=5 close=7
    bar1: high=9  low=4 close=8
    bar2: high=20 low=6 close=11   <- current bar's own high=20 must be excluded
    Correct channel_high at i=2 = max(bar0.high, bar1.high) = 10 (excludes bar2's own 20).
    close(11) > 10 -> long (+1). A buggy off-by-one (including bar2 in its
    own window) would compute max(9,20)=20 and close(11) would NOT breach ->
    would wrongly emit 0.
    """
    close = _series([7, 8, 11])
    high = _series([10, 9, 20])
    low = _series([5, 4, 6])
    sig = fs.donchian_signal(close, high, low, n=2)
    assert sig.iloc[2] == 1


def test_t2_donchian_long_short_tie_and_warmup():
    """N=2.
    bar0: high=10 low=5 close=7
    bar1: high=11 low=4 close=8
    bar2: high=9  low=6 close=12  -> channel_high(bar0,bar1)=11; close=12>11 -> +1
    bar3: high=9  low=3 close=9   -> channel_high(bar1,bar2)=11; channel_low(bar1,bar2)=4;
                                     close=9 in-band -> 0
    bar4: high=8  low=2 close=3   -> channel_low(bar2,bar3)=3; close=3==3 tie -> 0
    bar5: high=7  low=1 close=1   -> channel_low(bar3,bar4)=2; close=1<2 -> -1
    """
    close = _series([7, 8, 12, 9, 3, 1])
    high = _series([10, 11, 9, 9, 8, 7])
    low = _series([5, 4, 6, 3, 2, 1])
    sig = fs.donchian_signal(close, high, low, n=2)

    assert sig.iloc[0] == 0  # warm-up: no prior bars
    assert sig.iloc[1] == 0  # warm-up: only 1 prior bar (need 2)
    assert sig.iloc[2] == 1  # breakout long
    assert sig.iloc[3] == 0  # in-band
    assert sig.iloc[4] == 0  # exactly-equal-to-boundary -> decline
    assert sig.iloc[5] == -1  # breakout short


# ---------------------------------------------------------------------------
# M1 — ROC (§3 M1)
# ---------------------------------------------------------------------------

def test_m1_roc_long_short_zero_tie_and_warmup():
    """N=2.
    close: [100,110,90,100,100,100]
    roc[i]=close[i]/close[i-2]-1
    i=0,1: NaN -> 0
    i=2: 90/100-1=-0.1 -> -1
    i=3: 100/110-1=-0.0909 -> -1
    i=4: 100/90-1=0.111 -> +1
    i=5: 100/100-1=0 -> 0 (theta=0 tie rule)
    """
    close = _series([100, 110, 90, 100, 100, 100])
    sig = fs.roc_signal(close, n=2)
    assert sig.iloc[0] == 0
    assert sig.iloc[1] == 0
    assert sig.iloc[2] == -1
    assert sig.iloc[3] == -1
    assert sig.iloc[4] == 1
    assert sig.iloc[5] == 0


# ---------------------------------------------------------------------------
# R1/R2 — Wilder RSI recursion (§3 R1-R2)
# ---------------------------------------------------------------------------

def test_wilder_rsi_n2_hand_computed_recursion():
    """n=2, fully hand-computed (see SUB_PLAN §8).
    prices: [10, 11, 10, 13, 9, 9, 12]
    diffs:   d1=+1 d2=-1 d3=+3 d4=-4 d5=0 d6=+3
    gains:      1    0    3    0   0    3
    losses:     0    1    0    4   0    0

    Seed (mean of first n=2 gains/losses): avgGain=0.5, avgLoss=0.5
    RSI lands at bar index n=2 (0-indexed) -> RSI[2] = 50 (RS=1)
    Recursion avg[t] = ((n-1)*avg[t-1] + x[t])/n:
      t=3: avgGain=(0.5+3)/2=1.75  avgLoss=(0.5+0)/2=0.25  RS=7      RSI=87.5
      t=4: avgGain=(1.75+0)/2=0.875 avgLoss=(0.25+4)/2=2.125 RS=0.411765 RSI=29.166667
      t=5: avgGain=(0.875+0)/2=0.4375 avgLoss=(2.125+0)/2=1.0625 RS=0.411765 RSI=29.166667
      t=6: avgGain=(0.4375+3)/2=1.71875 avgLoss=(1.0625+0)/2=0.53125 RS=3.235294 RSI=76.388889
    """
    close = _series([10, 11, 10, 13, 9, 9, 12])
    rsi = fs.wilder_rsi(close, n=2)

    assert pd.isna(rsi.iloc[0])
    assert pd.isna(rsi.iloc[1])
    assert rsi.iloc[2] == pytest.approx(50.0)
    assert rsi.iloc[3] == pytest.approx(87.5)
    assert rsi.iloc[4] == pytest.approx(29.166667, abs=1e-4)
    assert rsi.iloc[5] == pytest.approx(29.166667, abs=1e-4)
    assert rsi.iloc[6] == pytest.approx(76.388889, abs=1e-4)


def test_wilder_rsi_first_value_lands_at_bar_n_not_before():
    """The first n bars (0-indexed 0..n-1) never receive an RSI value —
    RSI is defined from bar n onward (pinned index, §3 R1)."""
    close = _series([10, 11, 10, 13, 9, 9, 12])
    rsi = fs.wilder_rsi(close, n=2)
    assert rsi.iloc[:2].isna().all()
    assert not pd.isna(rsi.iloc[2])


def test_wilder_rsi_avg_loss_zero_is_rsi_100_degenerate(n=14):
    """All-gains 14-bar seed window (avgLoss==0) -> RSI=100 (Wilder's
    degenerate convention). Crafted series (§3 R1/R2 pin, SUB_PLAN §8):
    prices p0..p14 = 100..114 (14 diffs of +1 each) -> seed avgGain=1.0,
    avgLoss=0.0 -> RSI[14]=100. Next bar drops by 2 (loss=2, gain=0):
      avgGain=(13*1.0+0)/14=0.928571  avgLoss=(13*0+2)/14=0.142857
      RS=6.5  RSI=100-100/7.5=86.666667
    """
    prices = list(range(100, 115)) + [112]  # p0..p14 then p15=112 (114-2)
    close = _series(prices)
    rsi = fs.wilder_rsi(close, n=14)
    assert rsi.iloc[:14].isna().all()
    assert rsi.iloc[14] == pytest.approx(100.0)
    assert rsi.iloc[15] == pytest.approx(86.666667, abs=1e-4)


def test_wilder_rsi_avg_gain_zero_is_rsi_0_degenerate():
    """All-losses seed window (avgGain==0) -> RSI=0. n=2: prices [10,9,8]."""
    close = _series([10, 9, 8])
    rsi = fs.wilder_rsi(close, n=2)
    assert rsi.iloc[2] == pytest.approx(0.0)


def test_r1_rsi_signal_thresholds_and_ties(monkeypatch):
    """R1: n=14, RSI<30 -> +1, RSI>70 -> -1, ==30/==70 -> 0, NaN(warmup) -> 0.
    Thresholding is tested in isolation from the recursion (already hand-
    verified above) by monkeypatching wilder_rsi with controlled values."""
    close = _series([0, 0, 0, 0, 0])
    fake_rsi = pd.Series([float("nan"), 29.9, 30.0, 70.0, 70.1], index=close.index)
    monkeypatch.setattr(fs, "wilder_rsi", lambda mc, n: fake_rsi)
    sig = fs.rsi_signal(close, n=14, low=30, high=70)
    assert sig.iloc[0] == 0    # NaN warmup -> decline
    assert sig.iloc[1] == 1    # 29.9 < 30 -> long
    assert sig.iloc[2] == 0    # exactly 30 -> decline (tie)
    assert sig.iloc[3] == 0    # exactly 70 -> decline (tie)
    assert sig.iloc[4] == -1   # 70.1 > 70 -> short


def test_r2_rsi_signal_thresholds(monkeypatch):
    """R2: n=2, RSI<10 -> +1, RSI>90 -> -1."""
    close = _series([0, 0, 0])
    fake_rsi = pd.Series([9.9, 10.0, 90.1], index=close.index)
    monkeypatch.setattr(fs, "wilder_rsi", lambda mc, n: fake_rsi)
    sig = fs.rsi_signal(close, n=2, low=10, high=90)
    assert sig.iloc[0] == 1
    assert sig.iloc[1] == 0
    assert sig.iloc[2] == -1


# ---------------------------------------------------------------------------
# R3 — Bollinger(20, 2), ddof=0 (§3 R3)
# ---------------------------------------------------------------------------

def test_r3_bollinger_ddof0_vs_ddof1_discriminating_fixture():
    """20-bar window where the ddof=0 (population) lower band is breached by
    the current close, but the ddof=1 (sample) lower band is NOT — pandas'
    .std() defaults to ddof=1, which would silently produce a different
    (wrong, per Bollinger's own published definition) signal if unpinned.
    Independently verified with pandas' own rolling/std primitives (not the
    production function under test)."""
    vals = [
        100.3047, 98.96, 100.7505, 100.9406, 98.049, 98.6978, 100.1278, 99.6838,
        99.9832, 99.147, 100.8794, 100.7778, 100.066, 101.1272, 100.4675,
        99.1407, 100.3688, 99.0411, 100.8785, 97.9086,
    ]
    close = _series(vals)

    # Independent verification (pandas primitives, not fx_signals):
    sma = close.rolling(20).mean().iloc[-1]
    std0 = close.rolling(20).std(ddof=0).iloc[-1]
    std1 = close.rolling(20).std(ddof=1).iloc[-1]
    lower0 = sma - 2 * std0
    lower1 = sma - 2 * std1
    assert vals[-1] < lower0  # breaches under ddof=0
    assert vals[-1] >= lower1  # does NOT breach under ddof=1

    sig = fs.bollinger_signal(close, n=20, num_std=2.0)
    assert sig.iloc[-1] == 1  # long -- pinned ddof=0 answer


def test_r3_bollinger_long_short_tie_and_warmup():
    """20 identical values (std=0) plus one exact-tie evaluation: SMA==close
    and bands collapse to the mean -> exactly-on-band -> decline. Warm-up
    (< 20 bars) -> decline."""
    close = _series([100.0] * 20)
    sig = fs.bollinger_signal(close, n=20, num_std=2.0)
    assert (sig.iloc[:19] == 0).all()  # warm-up
    assert sig.iloc[19] == 0  # std=0 -> upper==lower==mean==close -> tie -> decline

    # A clear breakout: 19 identical bars, then a big spike up on bar 20.
    vals = [100.0] * 19 + [200.0]
    close2 = _series(vals)
    sig2 = fs.bollinger_signal(close2, n=20, num_std=2.0)
    assert sig2.iloc[-1] == -1  # far above upper band -> short (mean reversion)

    vals_down = [100.0] * 19 + [0.0]
    close3 = _series(vals_down)
    sig3 = fs.bollinger_signal(close3, n=20, num_std=2.0)
    assert sig3.iloc[-1] == 1  # far below lower band -> long


# ---------------------------------------------------------------------------
# Registry (§4) — 11 shapes, 33 cells, stable IDs, R grid
# ---------------------------------------------------------------------------

def test_registry_has_exactly_11_shapes():
    assert len(fs.SHAPES) == 11


def test_r_grid_values():
    assert fs.R_GRID == (0.0020, 0.0030, 0.0050)


def test_registry_has_exactly_33_cells():
    assert len(fs.CELLS) == 33


def test_registry_cell_ids_are_stable_and_match_sub_plan_examples():
    assert "T1_sma_5_20_R20" in fs.CELLS
    assert "R3_boll_20_2_R50" in fs.CELLS


def test_registry_shape_names_cover_all_families():
    names = set(fs.SHAPES.keys())
    expected = {
        "T1_sma_5_20", "T1_sma_20_50", "T1_sma_50_200",
        "T2_donchian_20", "T2_donchian_55",
        "M1_roc_12", "M1_roc_24", "M1_roc_48",
        "R1_rsi_14", "R2_rsi_2", "R3_boll_20_2",
    }
    assert names == expected


def test_registry_shapes_are_callable_on_a_bars_frame():
    """Every registered shape fn takes a DataFrame with MidClose/MidHigh/MidLow
    columns and returns an int series in {-1,0,1} aligned to the index."""
    idx = pd.date_range("2024-01-08", periods=250, freq="4h", tz="UTC")
    idx.name = "datetime_utc"
    rng = np.random.default_rng(7)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 0.1, len(idx))), index=idx)
    df = pd.DataFrame({
        "MidClose": close,
        "MidHigh": close + 0.05,
        "MidLow": close - 0.05,
    })
    for shape_id, fn in fs.SHAPES.items():
        sig = fn(df)
        assert list(sig.index) == list(df.index), shape_id
        assert set(sig.unique()).issubset({-1, 0, 1}), shape_id


def test_build_cells_returns_33_entries_with_fn_and_r():
    cells = fs.build_cells()
    assert len(cells) == 33
    ids = {c["cell_id"] for c in cells}
    assert ids == set(fs.CELLS)
    for c in cells:
        assert c["r"] in fs.R_GRID
        assert callable(c["fn"])
