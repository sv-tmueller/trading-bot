"""Tests for backtest/run_candidate_survey.py wiring.

Offline / synthetic universe (no network). Verifies the survey's load-bearing
properties: the after-tax curve never sits above pre-tax, DE (flat) is never
cheaper than US-long-term on a single held lot, and a Faber single-asset family
row reproduces the faber10 baseline (the one-column-frame == binary dispatch).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.run_candidate_survey as rcs


def _synthetic_universe(seed: int = 0) -> dict:
    idx = pd.bdate_range("2016-01-04", periods=1300)  # ~5y
    rng = np.random.default_rng(seed)
    out = {}
    drifts = {"SPY": 0.0004, "EFA": 0.0002, "AGG": 0.0001,
              "BIL": 0.00004, "DBC": 0.0001, "VNQ": 0.0003}
    for i, (t, d) in enumerate(drifts.items()):
        r = np.random.default_rng(seed + i).normal(d, 0.011, len(idx))
        px = 100.0 * np.exp(np.cumsum(r))
        out[t] = pd.DataFrame({"Open": px, "Close": px}, index=idx)
    return out


def test_faber_single_family_matches_faber10_baseline():
    """The Faber single-asset family row == the faber10 baseline exactly.

    Both are the published 10-month SMA on SPY; the family path runs it as a
    one-column {0,1} weight frame, which must dispatch to the binary loop and
    reproduce the baseline equity curve to the cent.
    """
    u = _synthetic_universe()
    idx = u["SPY"].index
    fam = rcs._simulate_strategy_on_index("faber_single", u, ["SPY"], idx)
    base = rcs._simulate_strategy_on_index("faber10", u, ["SPY"], idx)
    assert fam["ending_equity"] == pytest.approx(base["ending_equity"], rel=1e-9)
    assert fam["trade_count"] == base["trade_count"]
    pd.testing.assert_series_equal(
        fam["equity_curve"], base["equity_curve"], rtol=1e-9, check_names=False
    )


def test_after_tax_never_above_pretax_for_every_strategy():
    """For every strategy, the US and DE after-tax curves sit at/below pre-tax."""
    u = _synthetic_universe(seed=3)
    idx = u["SPY"].index
    cases = [("gem", ["SPY", "EFA", "AGG"]), ("gtaa", ["SPY", "EFA", "AGG", "DBC", "VNQ"]),
             ("faber_single", ["SPY"]), ("vol_target", ["SPY"]),
             ("1x_spy", ["SPY"]), ("tsmom", ["SPY"])]
    from backtest.tax import apply_tax_to_ledger
    for strat, held in cases:
        sim = rcs._simulate_strategy_on_index(strat, u, held, idx)
        eq = sim["equity_curve"]
        for j in ("US", "DE"):
            after = apply_tax_to_ledger(sim["trades"], eq, jurisdiction=j)
            assert (after <= eq + 1e-6).all(), f"{strat}/{j}: after-tax above pre-tax"


def test_buy_and_hold_de_not_cheaper_than_us_long_term():
    """A single long-held lot: US taxes it long-term (18.8%) < DE flat (26.375%).

    So 1x SPY buy-and-hold's after-tax ending equity must be HIGHER under US than
    under DE (less tax) whenever the single lot is held > 1 year and gains.
    """
    u = _synthetic_universe(seed=7)
    idx = u["SPY"].index
    sim = rcs._simulate_strategy_on_index("1x_spy", u, ["SPY"], idx)
    # Single buy-and-hold lot held the full ~5y window
    assert sim["trade_count"] == 1
    m = rcs._after_tax_metrics(sim, idx)
    from backtest.tax import apply_tax_to_ledger
    end_us = apply_tax_to_ledger(sim["trades"], sim["equity_curve"], jurisdiction="US").iloc[-1]
    end_de = apply_tax_to_ledger(sim["trades"], sim["equity_curve"], jurisdiction="DE").iloc[-1]
    # only meaningful if the lot is a gain
    if sim["trades"][0]["pnl"] > 0:
        assert end_us > end_de, "LT-qualified US lot should keep more than DE flat"


def test_turnover_reported_per_year():
    """Turnover = trade_count / years; 1x SPY (1 trade over ~5y) ~ 0.2/yr."""
    u = _synthetic_universe()
    idx = u["SPY"].index
    sim = rcs._simulate_strategy_on_index("1x_spy", u, ["SPY"], idx)
    m = rcs._after_tax_metrics(sim, idx)
    yrs = (idx[-1] - idx[0]).days / 365.25
    assert m["turnover_yr"] == pytest.approx(sim["trade_count"] / yrs, rel=1e-9)
    assert m["turnover_yr"] < 1.0  # buy-and-hold barely trades


def test_curve_metrics_ruin_safe_on_negative_after_tax_curve():
    """A capital-wiped after-tax curve reports NaN CAGR/Calmar, not a crash.

    The no-loss-credit US tax model taxes gross winners even when gross losers
    dominate, so a high-churn after-tax curve can go non-positive. CAGR on a
    negative base is complex (undefined); the runner must report NaN with maxDD
    clamped at <= -100%, recording the ruin honestly.
    """
    idx = pd.date_range("2007-01-01", "2026-01-01", freq="D")
    curve = pd.Series(np.linspace(100_000.0, -38_000.0, len(idx)), index=idx)
    m = rcs._curve_metrics(curve)
    assert np.isnan(m["cagr"])
    assert np.isnan(m["calmar"])
    assert m["max_drawdown"] <= -1.0


def test_curve_metrics_matches_foundation_on_a_healthy_curve():
    """On a positive curve, _curve_metrics agrees with the foundation's CAGR/Calmar."""
    import backtest.walkforward as wf
    idx = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    n = len(idx)
    vals = np.empty(n)
    t = n // 3
    vals[: t + 1] = np.linspace(100.0, 80.0, t + 1)
    vals[t:] = np.linspace(80.0, 144.0, n - t)
    curve = pd.Series(vals, index=idx)
    mine = rcs._curve_metrics(curve)
    theirs = wf._compute_window_metrics(curve, [], 100.0)
    assert mine["cagr"] == pytest.approx(theirs["cagr"], rel=1e-9)
    assert mine["calmar"] == pytest.approx(theirs["calmar"], rel=1e-9)
    assert mine["max_drawdown"] == pytest.approx(theirs["max_drawdown"], rel=1e-9)


def test_no_look_ahead_weighted_family_fills_next_open():
    """A GEM-style weight change fills at the NEXT open, not the signal close.

    Build a 2-asset weighted frame by hand where the weight flips on a known
    day; the first trade's entry price must equal the following day's open.
    """
    from backtest.regime import simulate_from_signal
    opens = [100.0, 120.0, 150.0, 200.0, 210.0, 220.0]
    closes = [110.0, 130.0, 160.0, 205.0, 215.0, 225.0]
    idx = pd.bdate_range("2020-01-02", periods=6)
    df = pd.DataFrame({"Open": opens, "Close": closes}, index=idx)
    w = pd.DataFrame({"X": [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]}, index=idx)
    res = simulate_from_signal(target_weights=w, asset_px={"X": df},
                               starting_cash=10_000.0, slippage_bps=0, commission_bps=0)
    assert res["trades"][0]["entry_price"] == pytest.approx(200.0, abs=1e-9)


def test_no_look_ahead_vol_target_fills_next_open():
    """Vol-target weight builder returns close-T weight; fill lands at NEXT open.

    Use vol_window=3 so warm-up ends quickly. Build a price series where the
    weight goes positive at a known row; the first trade must fill at the
    following day's open.
    """
    from backtest.families import vol_target_weights
    from backtest.regime import simulate_from_signal
    # 8 days; enough for vol_window=3 (needs 4 rows of returns = 5 price points)
    opens  = [100.0, 102.0, 101.0, 103.0, 104.0, 105.0, 106.0, 107.0]
    closes = [101.0, 103.0, 100.0, 104.0, 106.0, 107.0, 108.0, 109.0]
    idx = pd.bdate_range("2020-01-02", periods=8)
    spy_df = pd.DataFrame({"Open": opens, "Close": closes}, index=idx)
    spy_close = spy_df["Close"]

    w = vol_target_weights(spy_close, idx, vol_window=3)
    wcol = w["SPY"].to_numpy()

    # At least one positive weight must exist
    pos_rows = np.flatnonzero(wcol > 0)
    assert len(pos_rows) > 0, "no positive weight — price series needs more variance"

    first_pos = int(pos_rows[0])
    # There must be a day after the first positive weight to fill at
    assert first_pos + 1 < len(idx), "no next open available after first positive weight"

    res = simulate_from_signal(
        target_weights=w, asset_px={"SPY": spy_df},
        starting_cash=10_000.0, slippage_bps=0, commission_bps=0,
    )
    assert len(res["trades"]) >= 1
    assert res["trades"][0]["entry_price"] == pytest.approx(opens[first_pos + 1], abs=1e-9)
