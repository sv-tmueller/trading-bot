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


# ---------------------------------------------------------------------------
# Confirmed-pivot path builder — visits `pivot_prices` in order, with a small
# leading/trailing reversal so the FIRST and LAST prices are themselves
# CONFIRMED pivots (find_pivots() only emits confirmed extremes; the raw
# series start/end is never auto-confirmed -- see module docstring §1).
# ---------------------------------------------------------------------------

def _confirmed_path(pivot_prices: list, *, bar_spacing: int = 10, pad: int = 2) -> pd.DataFrame:
    """Build a path visiting `pivot_prices` as CONFIRMED pivots (see module docstring:
    ``label_waves`` only resolves a starting position once its 6-pivot impulse window is
    itself fully confirmed). ``pad`` appends this many extra small, alternating,
    confirmed pivots after the intended sequence so the matcher can definitively rule
    out an impulse at the tail position and safely emit whatever structure ends there --
    without ``pad``, a bare 4-pivot zigzag fixture would never resolve at all (the scan
    halts rather than guess). The pad legs are tiny relative to any real leg used in
    these fixtures, so they trivially fail every Fibonacci band if ever considered part
    of an extended impulse window.
    """
    prices = list(pivot_prices)
    pad_leg = 1.0
    # The first pad step must REVERSE the direction of the leg leading into the last
    # intended pivot (otherwise it just extends that leg instead of confirming it).
    sign = -np.sign(prices[-1] - prices[-2])
    for _ in range(pad):
        prices.append(prices[-1] + sign * pad_leg)
        sign = -sign

    first_leg = prices[1] - prices[0]
    last_leg = prices[-1] - prices[-2]
    lead = prices[0] + np.sign(first_leg) * abs(first_leg) * 0.05
    # The trail bump must itself comfortably exceed theta (else it never gets confirmed
    # and dangles unconfirmed forever) -- 0.05x of a full-size real leg is plenty, but
    # 0.05x of a *pad* leg (tiny by design) is not, so use a much larger fraction here.
    trail = prices[-1] - np.sign(last_leg) * abs(last_leg) * 0.5
    knots = [(0, lead)]
    for k, price in enumerate(prices):
        knots.append(((k + 1) * bar_spacing, price))
    knots.append((knots[-1][0] + bar_spacing, trail))
    return _path(knots)


_THETA = 0.0005  # tiny relative to every leg used below (all several % moves)


# ---------------------------------------------------------------------------
# Impulse grammar
# ---------------------------------------------------------------------------

def test_label_waves_textbook_bullish_impulse():
    # W2/W1=0.618, W3/W1=1.618, W4/W3=0.382, W5/W1=1.000 -- canonical ratios.
    prices = [100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924]
    df = _confirmed_path(prices)
    pivots = ew.find_pivots(df, theta=_THETA)
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 1
    row = labels.iloc[0]
    assert row["kind"] == "impulse"
    assert row["direction"] == "up"
    assert row["w2_w1"] == pytest.approx(0.618)
    assert row["w3_w1"] == pytest.approx(1.618)
    assert row["w4_w3"] == pytest.approx(0.382)
    assert row["w5_w1"] == pytest.approx(1.000)
    # signal_ts is the LAST pivot's confirmed_ts, never its own pivot_ts.
    last_pivot = pivots[np.isclose(pivots["pivot_price"], prices[-1])].iloc[0]
    assert row["signal_ts"] == last_pivot["confirmed_ts"]
    assert row["signal_ts"] != last_pivot["pivot_ts"]


def test_label_waves_bearish_impulse_mirror():
    prices = [100.0, 90.0, 96.18, 80.0, 86.18076, 76.18076]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 1
    row = labels.iloc[0]
    assert row["kind"] == "impulse"
    assert row["direction"] == "down"
    assert row["w2_w1"] == pytest.approx(0.618)
    assert row["w3_w1"] == pytest.approx(1.618)
    assert row["w4_w3"] == pytest.approx(0.382)
    assert row["w5_w1"] == pytest.approx(1.000)


def test_label_waves_r1_violation_wave2_retraces_101pct_rejects_impulse_entirely():
    """W2 retraces past P0 (101% of W1) -- R1 fails. This fixture is also engineered
    so no fallback zigzag matches either: nothing at all is emitted."""
    prices = [100.0, 110.0, 99.9, 116.08, 96.08, 111.08]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert "impulse" not in set(labels["kind"])
    assert len(labels) == 0


def test_label_waves_r2_violation_wave3_shortest_rejects_impulse_falls_through_to_zigzag():
    """W3 (8) is shorter than both W1 (10) and W5 (12) -- R2 fails, so no impulse.
    The SAME starting pivot's first four legs (P0..P3) independently satisfy the
    zigzag grammar, so the total-order scan correctly falls through to a zigzag --
    this is "precisely what else is emitted" for this rejection."""
    prices = [100.0, 110.0, 103.82, 111.82, 110.32, 122.32]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert "impulse" not in set(labels["kind"])
    assert len(labels) == 1
    row = labels.iloc[0]
    assert row["kind"] == "zigzag"
    assert row["direction"] == "up"
    assert row["wb_wa"] == pytest.approx(0.618)
    assert row["wc_wa"] == pytest.approx(0.8)


def test_label_waves_r3_violation_wave4_overlaps_wave1_rejects_impulse_falls_through_to_zigzag():
    """P4 (108.82) enters wave 1's territory (P1=110) -- R3 fails, so no impulse. As
    with the R2 fixture, P0..P3 independently satisfy the zigzag grammar."""
    prices = [100.0, 110.0, 103.82, 118.82, 108.82, 118.82]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert "impulse" not in set(labels["kind"])
    assert len(labels) == 1
    row = labels.iloc[0]
    assert row["kind"] == "zigzag"
    assert row["direction"] == "up"
    assert row["wb_wa"] == pytest.approx(0.618)
    assert row["wc_wa"] == pytest.approx(1.5)


@pytest.mark.parametrize("band,accept_ratio,reject_ratio", [
    ("F1", ew.F1_LOW, ew.F1_LOW * 0.999),
    ("F1", ew.F1_HIGH, ew.F1_HIGH * 1.001),
    ("F2", ew.F2_LOW, ew.F2_LOW * 0.999),
    ("F2", ew.F2_HIGH, ew.F2_HIGH * 1.001),
    ("F3", ew.F3_LOW, ew.F3_LOW * 0.999),
    ("F3", ew.F3_HIGH, ew.F3_HIGH * 1.001),
    ("F4", ew.F4_LOW, ew.F4_LOW * 0.999),
    ("F4", ew.F4_HIGH, ew.F4_HIGH * 1.001),
])
def test_label_waves_impulse_fib_boundary_pairs(band, accept_ratio, reject_ratio):
    """Exactly at each F-band endpoint -> accept; one epsilon outside -> reject."""
    w1 = 10.0

    def _build(w2_w1, w3_w1, w4_w3, w5_w1):
        p0 = 100.0
        p1 = p0 + w1
        p2 = p1 - w2_w1 * w1
        w3 = w3_w1 * w1
        p3 = p2 + w3
        p4 = p3 - w4_w3 * w3
        p5 = p4 + w5_w1 * w1
        return [p0, p1, p2, p3, p4, p5]

    # A safe interior baseline for every OTHER ratio, so only `band` is being probed
    # (chosen so R1-R3 hold comfortably across the full tested range of every axis --
    # 0.618/1.618/0.382/1.000 look "canonical" but 1-0.382 == 0.618 exactly, which
    # collides with R3's own boundary right at F2's low endpoint).
    base = dict(w2_w1=0.4, w3_w1=2.0, w4_w3=0.2, w5_w1=1.000)
    key = {"F1": "w2_w1", "F2": "w3_w1", "F3": "w4_w3", "F4": "w5_w1"}[band]

    accept_kwargs = dict(base, **{key: accept_ratio})
    reject_kwargs = dict(base, **{key: reject_ratio})

    accept_df = _confirmed_path(_build(**accept_kwargs))
    accept_labels = ew.label_waves(accept_df, theta=_THETA)
    assert len(accept_labels) == 1 and accept_labels.iloc[0]["kind"] == "impulse", (
        f"{band} at its boundary must be accepted"
    )

    reject_df = _confirmed_path(_build(**reject_kwargs))
    reject_labels = ew.label_waves(reject_df, theta=_THETA)
    assert "impulse" not in set(reject_labels["kind"]), (
        f"{band} one epsilon outside its boundary must reject the impulse"
    )


# ---------------------------------------------------------------------------
# Correction grammar (zigzag, 5-3-5)
# ---------------------------------------------------------------------------

def test_label_waves_textbook_bearish_zigzag():
    # WA=10, WB=6.18 (ratio 0.618), WC=10 (ratio 1.000) -- one zigzag/down.
    prices = [100.0, 90.0, 96.18, 86.18]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 1
    row = labels.iloc[0]
    assert row["kind"] == "zigzag"
    assert row["direction"] == "down"
    assert row["wb_wa"] == pytest.approx(0.618)
    assert row["wc_wa"] == pytest.approx(1.000)


def test_label_waves_bullish_zigzag_mirror():
    prices = [100.0, 110.0, 103.82, 113.82]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 1
    row = labels.iloc[0]
    assert row["kind"] == "zigzag"
    assert row["direction"] == "up"
    assert row["wb_wa"] == pytest.approx(0.618)
    assert row["wc_wa"] == pytest.approx(1.000)


def test_label_waves_c1_violation_b_retraces_past_a_rejects_zigzag():
    """Q2 (101.0) exceeds Q0 (100.0) -- C1 fails for a bearish zigzag (H,L,H,L):
    the B-leg retraces more than 100% of the A-leg."""
    prices = [100.0, 90.0, 101.0, 95.0]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 0


@pytest.mark.parametrize("band,accept_ratio,reject_ratio", [
    ("C2", ew.C2_LOW, ew.C2_LOW * 0.999),
    ("C2", ew.C2_HIGH, ew.C2_HIGH * 1.001),
    ("C3", ew.C3_LOW, ew.C3_LOW * 0.999),
    ("C3", ew.C3_HIGH, ew.C3_HIGH * 1.001),
])
def test_label_waves_zigzag_fib_boundary_pairs(band, accept_ratio, reject_ratio):
    wa = 10.0

    def _build(wb_wa, wc_wa):
        q0 = 100.0
        q1 = q0 - wa
        q2 = q1 + wb_wa * wa
        q3 = q2 - wc_wa * wa
        return [q0, q1, q2, q3]

    base = dict(wb_wa=0.618, wc_wa=1.000)
    key = {"C2": "wb_wa", "C3": "wc_wa"}[band]

    accept_df = _confirmed_path(_build(**dict(base, **{key: accept_ratio})))
    accept_labels = ew.label_waves(accept_df, theta=_THETA)
    assert len(accept_labels) == 1 and accept_labels.iloc[0]["kind"] == "zigzag"

    reject_df = _confirmed_path(_build(**dict(base, **{key: reject_ratio})))
    reject_labels = ew.label_waves(reject_df, theta=_THETA)
    assert "zigzag" not in set(reject_labels["kind"])


# ---------------------------------------------------------------------------
# Sequencing / tie-break
# ---------------------------------------------------------------------------

def test_label_waves_impulse_then_correction_origin_is_impulse_terminal_pivot():
    impulse = [100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924]
    # A fresh bearish zigzag correction beginning exactly at the impulse's P5.
    q0 = impulse[-1]
    q1 = q0 - 10.0
    q2 = q1 + 6.18
    q3 = q2 - 10.0
    full = impulse + [q1, q2, q3]
    df = _confirmed_path(full)
    labels = ew.label_waves(df, theta=_THETA)
    assert list(labels["kind"]) == ["impulse", "zigzag"]
    assert labels.iloc[1]["direction"] == "down"
    # The correction's origin IS the impulse's terminal pivot (P5 == Q0).
    assert labels.iloc[0]["end_idx"] == labels.iloc[1]["start_idx"]


def test_label_waves_impulse_priority_over_overlapping_zigzag():
    """A window where the first 4 pivots ALSO satisfy the zigzag grammar and the full
    6 satisfy the impulse grammar -- impulse wins (the frozen priority)."""
    prices = [100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 1
    assert labels.iloc[0]["kind"] == "impulse"


def test_label_waves_overlapping_candidates_never_both_emit():
    """The impulse's own interior pivots (P1..P4) are never independently re-examined
    as a fresh structure's start once the impulse has claimed them."""
    prices = [100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924]
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    starts = list(labels["start_idx"])
    assert len(starts) == len(set(starts))  # no pivot claimed as a start twice


# ---------------------------------------------------------------------------
# Structural guarantees — do not de-scope any of these.
# ---------------------------------------------------------------------------

def _random_walk_frame(n: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.004, n)
    close = 100.0 * np.cumprod(1.0 + steps)
    idx = pd.date_range("2020-01-01", periods=n, freq="h")
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"Open": open_, "High": np.maximum(open_, close), "Low": np.minimum(open_, close),
         "Close": close},
        index=idx,
    )


def test_label_waves_no_lookahead_truncation_invariance():
    """Truncating the frame after bar k must not change any already-emitted label:
    label_waves(series[:k]) == label_waves(series) filtered to signal_ts <= series[k-1]."""
    df = _random_walk_frame(n=500, seed=5)
    full = ew.label_waves(df, theta=0.003)
    for cut in (150, 300, 450):
        truncated = ew.label_waves(df.iloc[:cut], theta=0.003)
        cutoff_ts = df.index[cut - 1]
        expected = full[full["signal_ts"] <= cutoff_ts].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            truncated.reset_index(drop=True), expected, obj=f"truncated at {cut}",
        )


def test_label_waves_determinism_two_calls_identical():
    df = _random_walk_frame(n=300, seed=9)
    first = ew.label_waves(df, theta=0.003)
    second = ew.label_waves(df, theta=0.003)
    pd.testing.assert_frame_equal(first, second)


def test_label_waves_determinism_different_index_name_and_float_backing():
    """A different index name and a differently-constructed (but numerically identical)
    float array must not change the labels. This is deliberately NOT a lossy dtype
    round-trip (e.g. float32 truncation) -- that would genuinely perturb the input
    values, which is a different question (numerical sensitivity) from determinism."""
    df = _random_walk_frame(n=300, seed=9)
    first = ew.label_waves(df, theta=0.003)

    df2 = df.copy()
    df2.index = df2.index.rename("some_other_name")
    # A different concrete array construction path, same values bit-for-bit.
    df2["Close"] = np.array(df["Close"].tolist(), dtype=np.float64)
    second = ew.label_waves(df2, theta=0.003)
    pd.testing.assert_frame_equal(
        first, second, check_names=False,
    )


def test_label_waves_scale_invariance():
    df = _random_walk_frame(n=300, seed=13)
    scaled = df.copy()
    for col in ("Open", "High", "Low", "Close"):
        scaled[col] = scaled[col] * 7.5

    original = ew.label_waves(df, theta=0.003)
    scaled_labels = ew.label_waves(scaled, theta=0.003)

    pd.testing.assert_series_equal(original["kind"], scaled_labels["kind"])
    pd.testing.assert_series_equal(original["direction"], scaled_labels["direction"])
    pd.testing.assert_series_equal(original["signal_ts"], scaled_labels["signal_ts"])
    for col in ("w2_w1", "w3_w1", "w4_w3", "w5_w1", "wb_wa", "wc_wa"):
        pd.testing.assert_series_equal(original[col], scaled_labels[col], check_names=False)


def test_label_waves_anti_oracle_sawtooth_never_produces_an_impulse():
    """A pure sawtooth with ALL legs equal: W2/W1 = 1.0, which fails F1 ([0.382, 0.886])
    -- no impulse. Guards against a labeler that fires on any alternating sequence."""
    leg = 10.0
    prices = [100.0]
    price = 100.0
    up = True
    for _ in range(8):
        price = price + leg if up else price - leg
        prices.append(price)
        up = not up
    df = _confirmed_path(prices)
    labels = ew.label_waves(df, theta=_THETA)
    assert "impulse" not in set(labels["kind"])


# ---------------------------------------------------------------------------
# Mapping (FADE / FOLLOW) -- the fx_signals contract.
# ---------------------------------------------------------------------------

def test_structure_signal_fade_and_follow_are_exact_opposites():
    df = _confirmed_path([100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924])
    labels = ew.label_waves(df, theta=_THETA)
    assert len(labels) == 1

    fade = ew.structure_signal(labels, df.index, ew.FADE)
    follow = ew.structure_signal(labels, df.index, ew.FOLLOW)

    nonzero_fade = fade[fade != 0]
    nonzero_follow = follow[follow != 0]
    assert len(nonzero_fade) == 1
    assert len(nonzero_follow) == 1
    assert nonzero_fade.index.equals(nonzero_follow.index)
    assert (nonzero_fade == -nonzero_follow).all()


def test_structure_signal_warmup_rows_are_explicit_zero_never_nan():
    df = _confirmed_path([100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924])
    labels = ew.label_waves(df, theta=_THETA)
    sig = ew.structure_signal(labels, df.index, ew.FADE)
    assert not sig.isna().any()
    assert (sig.iloc[:5] == 0).all()  # long before any structure can complete


def test_structure_signal_contract_dtype_and_index_identity():
    df = _confirmed_path([100.0, 110.0, 103.82, 120.0, 113.81924, 123.81924])
    labels = ew.label_waves(df, theta=_THETA)
    sig = ew.structure_signal(labels, df.index, ew.FOLLOW)
    assert sig.dtype == np.int64
    pd.testing.assert_index_equal(sig.index, df.index)
    assert set(sig.unique()).issubset({-1, 0, 1})
