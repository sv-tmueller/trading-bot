"""Tests for backtest/vol_target.py -- vol-target sizing and the SPY benchmark.

Research-only. All data is synthetic and seeded; no network, no broker, no LLM.
The tests pin the no-lookahead window, the warm-up rule, the exact gross cap
(no tolerance, because the weighted simulator rejects any sum|w| > cap) and
the benchmark's "same mechanism as a candidate" property (spec 5.2 criterion 2).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest.vol_target import (
    benchmark_weights,
    inverse_vol_weights,
    vol_target_weights,
)

ANN = math.sqrt(252)


def _rets(n=400, cols=("SPY", "AGG"), vols=(0.20, 0.05), seed=0) -> pd.DataFrame:
    """iid normal daily returns with the given annualised vols."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n)
    data = {c: rng.normal(0.0, v / ANN, n) for c, v in zip(cols, vols)}
    return pd.DataFrame(data, index=idx)


def _ones_on(rets: pd.DataFrame, col: str) -> pd.DataFrame:
    sig = pd.DataFrame(0.0, index=rets.index, columns=rets.columns)
    sig[col] = 1.0
    return sig


def _perturb_after(rets: pd.DataFrame, t: int, seed=99) -> pd.DataFrame:
    """Copy of rets with every row strictly after position t replaced."""
    out = rets.copy()
    rng = np.random.default_rng(seed)
    out.iloc[t + 1:] = rng.normal(0.0, 0.05, out.iloc[t + 1:].shape)
    return out


# --- cap ------------------------------------------------------------------


def test_gross_never_exceeds_cap_with_shorts():
    n_assets = 12
    cols = [f"A{i}" for i in range(n_assets)]
    rets = _rets(n=300, cols=cols, vols=[0.02] * n_assets, seed=1)
    rng = np.random.default_rng(2)
    raw = pd.DataFrame(
        rng.choice([-1.0, -0.5, 0.5, 1.0], size=rets.shape),
        index=rets.index,
        columns=rets.columns,
    )
    w = vol_target_weights(raw, rets, target_vol=0.10, gross_cap=1.0)
    gross = w.abs().sum(axis=1)

    # Exact cap, no tolerance: the simulator raises on sum|w| > cap.
    assert (gross <= 1.0).all()
    # The cap must actually bind after warm-up, else the test proves nothing.
    assert (gross.iloc[60:] >= 1.0 - 1e-9).all()
    # Signs and proportions are kept: w / raw is constant within a row.
    ratio = (w / raw).iloc[60:]
    assert np.allclose(ratio.max(axis=1), ratio.min(axis=1), rtol=1e-9, atol=0)
    assert (ratio > 0).all().all()


def test_gross_cap_above_one_is_respected_exactly():
    rets = _rets(n=300, cols=("A", "B", "C"), vols=(0.02, 0.03, 0.02), seed=3)
    raw = pd.DataFrame(
        [[1.0, -1.0, 0.5]] * len(rets), index=rets.index, columns=rets.columns
    )
    w = vol_target_weights(raw, rets, target_vol=0.10, gross_cap=1.5)
    gross = w.abs().sum(axis=1)
    assert (gross <= 1.5).all()
    assert (gross.iloc[60:] >= 1.5 - 1e-9).all()


# --- scaling --------------------------------------------------------------


def test_scaling_hits_target_when_cap_not_binding():
    # iid returns at 30% annual vol, one asset, target 10% -> weight ~ 1/3.
    rets = _rets(n=3000, cols=("SPY",), vols=(0.30,), seed=7)
    raw = _ones_on(rets, "SPY")
    w = vol_target_weights(raw, rets, target_vol=0.10, gross_cap=1.0)["SPY"]
    after = w.iloc[60:]
    # Per-row estimates are noisy at lookback 60; the median is the stable check.
    assert abs(after.median() - 1 / 3) / (1 / 3) < 0.15
    assert (after > 0).all()


def test_uses_full_covariance():
    # Two identical columns at raw [0.5, 0.5]: the portfolio is the single
    # asset, so each weight is 0.5x the single-asset weight. Ignoring the
    # cross-covariance would give 1/sqrt(2) instead. S is rank 1 here.
    r = _rets(n=300, cols=("X",), vols=(0.20,), seed=4)["X"]
    rets = pd.DataFrame({"X": r, "Y": r})
    single = vol_target_weights(
        pd.DataFrame({"X": 1.0}, index=r.index),
        pd.DataFrame({"X": r}),
        target_vol=0.10,
        gross_cap=5.0,
    )["X"]
    raw = pd.DataFrame({"X": 0.5, "Y": 0.5}, index=r.index)
    w = vol_target_weights(raw, rets, target_vol=0.10, gross_cap=5.0)
    assert np.allclose(w["X"].iloc[60:], 0.5 * single.iloc[60:], rtol=1e-9)
    assert np.allclose(w["Y"].iloc[60:], 0.5 * single.iloc[60:], rtol=1e-9)


# --- time semantics -------------------------------------------------------


@pytest.mark.parametrize("which", ["inverse", "target", "benchmark"])
def test_no_lookahead(which):
    rets = _rets(n=300, cols=("SPY", "AGG", "GLD"), vols=(0.2, 0.05, 0.15), seed=5)
    rng = np.random.default_rng(6)
    sig = pd.DataFrame(
        rng.choice([-1.0, 0.0, 1.0], size=rets.shape),
        index=rets.index,
        columns=rets.columns,
    )

    def run(r):
        if which == "inverse":
            return inverse_vol_weights(sig, r)
        if which == "target":
            return vol_target_weights(sig * 0.3, r)
        return benchmark_weights(r)

    t = 200
    base = run(rets)
    changed = run(_perturb_after(rets, t))
    # Bit-identical up to and including T, even though every later row differs.
    pd.testing.assert_frame_equal(
        base.iloc[: t + 1], changed.iloc[: t + 1], check_exact=True
    )
    assert not base.iloc[t + 1:].equals(changed.iloc[t + 1:])


@pytest.mark.parametrize("which", ["inverse", "target"])
def test_window_includes_T(which):
    # The window ends at T (no pre-shift): changing the return at T changes
    # the weight at T.
    rets = _rets(n=200, cols=("SPY", "AGG"), vols=(0.2, 0.05), seed=8)
    sig = pd.DataFrame(1.0, index=rets.index, columns=rets.columns)
    t = 150
    bumped = rets.copy()
    bumped.iloc[t, 0] += 0.05

    def run(r):
        if which == "inverse":
            return inverse_vol_weights(sig, r)
        return vol_target_weights(sig * 0.5, r)

    assert not np.allclose(run(rets).iloc[t], run(bumped).iloc[t])


@pytest.mark.parametrize("which", ["inverse", "target", "benchmark"])
def test_warmup_rows_are_zero(which):
    lookback = 30
    rets = _rets(n=120, seed=9)
    sig = pd.DataFrame(1.0, index=rets.index, columns=rets.columns)

    def run(r):
        if which == "inverse":
            return inverse_vol_weights(sig, r, lookback=lookback)
        if which == "target":
            return vol_target_weights(sig * 0.5, r, lookback=lookback)
        return benchmark_weights(r, lookback=lookback)

    w = run(rets)
    # All-finite returns: rows 0..lookback-2 are zero, row lookback-1 is not.
    assert (w.iloc[: lookback - 1] == 0).all().all()
    assert (w.iloc[lookback - 1].abs() > 0).any()

    # With a leading pct_change NaN the first `lookback` rows are zero.
    nan_first = rets.copy()
    nan_first.iloc[0] = np.nan
    w2 = run(nan_first)
    assert (w2.iloc[:lookback] == 0).all().all()
    assert (w2.iloc[lookback].abs() > 0).any()


# --- benchmark ------------------------------------------------------------


def test_benchmark_is_spy_only_and_capped():
    rets = _rets(n=400, cols=("SPY", "AGG", "EFA"), vols=(0.20, 0.05, 0.18), seed=10)
    # EFA lists late: NaN for its first 100 rows.
    rets.iloc[:100, rets.columns.get_loc("EFA")] = np.nan
    b = benchmark_weights(rets)
    assert list(b.columns) == list(rets.columns)
    assert (b.drop(columns="SPY") == 0).all().all()
    assert (b["SPY"] <= 1.0).all()
    assert (b["SPY"] >= 0).all()
    assert (b["SPY"].iloc[60:] > 0).all()
    # A late-listing column does not zero SPY after SPY's own warm-up.
    assert (b["SPY"].iloc[60:100] > 0).all()


def test_benchmark_matches_candidate_mechanism():
    rets = _rets(n=400, cols=("SPY", "AGG"), vols=(0.20, 0.05), seed=11)
    sig = _ones_on(rets, "SPY")
    cand = vol_target_weights(inverse_vol_weights(sig, rets), rets)
    bench = benchmark_weights(rets)
    assert np.allclose(bench.values, cand.values, rtol=0, atol=1e-12)


# --- edge cases -----------------------------------------------------------


def test_all_zero_signal_rows_are_zero():
    rets = _rets(n=200, seed=12)
    sig = pd.DataFrame(1.0, index=rets.index, columns=rets.columns)
    sig.iloc[100:120] = 0.0
    sig.iloc[130:140] = np.nan  # NaN counts as 0
    inv = inverse_vol_weights(sig, rets)
    assert (inv.iloc[100:120] == 0).all().all()
    assert (inv.iloc[130:140] == 0).all().all()
    assert (inv.iloc[150:].abs().sum(axis=1) > 0).all()
    tgt = vol_target_weights(inv, rets)
    assert (tgt.iloc[100:120] == 0).all().all()
    assert np.isfinite(tgt.values).all()


def test_zero_vol_asset_gets_zero_weight():
    rets = _rets(n=200, cols=("SPY",), vols=(0.20,), seed=13)
    rets["FLAT"] = 0.0
    sig = pd.DataFrame(1.0, index=rets.index, columns=rets.columns)
    w = inverse_vol_weights(sig, rets)
    assert (w["FLAT"] == 0).all()
    assert np.allclose(w["SPY"].iloc[60:].abs(), 1.0)
    assert np.isfinite(w.values).all()


def test_zero_portfolio_vol_row_is_zero():
    # Columns r and -r at raw [0.5, 0.5]: portfolio return is exactly 0.
    r = _rets(n=200, cols=("X",), vols=(0.20,), seed=14)["X"]
    rets = pd.DataFrame({"X": r, "Y": -r})
    raw = pd.DataFrame({"X": 0.5, "Y": 0.5}, index=r.index)
    w = vol_target_weights(raw, rets)
    assert (w == 0).all().all()
    assert np.isfinite(w.values).all()


def test_nan_preinception_column_zero_until_sizable():
    lookback = 60
    rets = _rets(n=300, cols=("A", "B"), vols=(0.20, 0.10), seed=15)
    rets.iloc[:100, rets.columns.get_loc("B")] = np.nan
    sig = pd.DataFrame(1.0, index=rets.index, columns=rets.columns)

    inv = inverse_vol_weights(sig, rets, lookback=lookback)
    first_b = 100 + lookback - 1  # B's first full window ends here
    assert (inv["B"].iloc[:first_b] == 0).all()
    assert (inv["B"].iloc[first_b:].abs() > 0).all()
    # While B is unsizable, A takes the whole unit of gross.
    assert np.allclose(inv["A"].iloc[lookback - 1 : first_b].abs(), 1.0)

    raw = pd.DataFrame({"A": 0.5, "B": 0.5}, index=rets.index)
    tgt = vol_target_weights(raw, rets, lookback=lookback)
    assert np.isfinite(tgt.values).all()
    assert (tgt["B"].iloc[:first_b] == 0).all()
    # Before B is sizable, A is sized exactly as if B had raw weight 0.
    a_only = vol_target_weights(
        pd.DataFrame({"A": 0.5, "B": 0.0}, index=rets.index), rets, lookback=lookback
    )
    assert (tgt["A"].iloc[lookback - 1 : first_b] > 0).all()
    pd.testing.assert_series_equal(
        tgt["A"].iloc[:first_b], a_only["A"].iloc[:first_b], check_exact=True
    )


def test_output_finite():
    rng = np.random.default_rng(16)
    rets = _rets(n=300, cols=("A", "B", "C"), vols=(0.2, 0.0001, 0.1), seed=16)
    rets.iloc[::17, 0] = np.nan
    rets["C"] = rets["C"].where(rets.index > rets.index[50])  # late listing
    raw = pd.DataFrame(
        rng.choice([-1.0, 0.0, 1.0, np.nan], size=rets.shape),
        index=rets.index,
        columns=rets.columns,
    )
    for out in (
        inverse_vol_weights(raw, rets),
        vol_target_weights(raw, rets),
        benchmark_weights(rets, symbol="A"),
    ):
        assert np.isfinite(out.values).all()
        assert out.shape == rets.shape


def test_invalid_inputs_raise():
    rets = _rets(n=100, seed=17)
    sig = pd.DataFrame(1.0, index=rets.index, columns=rets.columns)

    bad_signal = sig.copy()
    bad_signal.iloc[10, 0] = 2.0
    with pytest.raises(ValueError):
        inverse_vol_weights(bad_signal, rets)

    with pytest.raises(ValueError):
        inverse_vol_weights(sig.iloc[1:], rets)
    with pytest.raises(ValueError):
        vol_target_weights(sig.iloc[1:], rets)

    rev = rets.iloc[::-1]
    with pytest.raises(ValueError):
        vol_target_weights(sig.iloc[::-1], rev)
    with pytest.raises(ValueError):
        benchmark_weights(rev)

    dup_idx = rets.index.tolist()
    dup_idx[5] = dup_idx[4]
    dup = rets.copy()
    dup.index = pd.DatetimeIndex(dup_idx)
    with pytest.raises(ValueError):
        benchmark_weights(dup)

    with pytest.raises(ValueError):
        vol_target_weights(sig.assign(ZZZ=1.0), rets)
    with pytest.raises(ValueError):
        benchmark_weights(rets, symbol="QQQ")
    with pytest.raises(ValueError):
        vol_target_weights(sig, rets, lookback=1)
    with pytest.raises(ValueError):
        inverse_vol_weights(sig, rets, lookback=1)
    with pytest.raises(ValueError):
        vol_target_weights(sig, rets, target_vol=0.0)
    with pytest.raises(ValueError):
        vol_target_weights(sig, rets, target_vol=float("nan"))
    with pytest.raises(ValueError):
        vol_target_weights(sig, rets, gross_cap=0.0)
    with pytest.raises(ValueError):
        benchmark_weights(rets, gross_cap=-1.0)
