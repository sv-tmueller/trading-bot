from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backtest import synthetic
from backtest.giveback import apply_giveback


def _mk(signal_vals, prices):
    idx = pd.date_range("2020-01-01", periods=len(prices), freq="D")
    return (
        pd.Series(signal_vals, index=idx),
        pd.Series(prices, index=idx, dtype=float),
    )


def test_dormant_below_arm_threshold():
    # Peak gain never reaches +20% -> giveback never fires; series == signal.
    sig, px = _mk(["LONG"] * 6, [100, 105, 110, 108, 112, 109])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    assert list(out) == ["LONG"] * 6


def test_fires_when_gain_falls_to_half_of_armed_peak():
    # Peak +20% at 120 (day 2); floor = +10% = 110. Day 3 close 109 -> exit.
    sig, px = _mk(["LONG"] * 5, [100, 115, 120, 109, 108])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    assert list(out) == ["LONG", "LONG", "LONG", "CASH", "CASH"]


def test_reentry_locked_until_regime_resets():
    # After a giveback exit, a still-LONG signal must NOT re-enter until a CASH day.
    sig, px = _mk(
        ["LONG", "LONG", "LONG", "LONG", "CASH", "LONG"],
        [100, 120, 109, 130, 90, 95],
    )
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    # day2 exit; day3 stays CASH (locked despite LONG signal); day4 CASH clears
    # the lock; day5 LONG signal re-enters.
    assert list(out) == ["LONG", "LONG", "CASH", "CASH", "CASH", "LONG"]


def test_floor_ratchets_up_with_a_higher_peak():
    # New peak +40% at 140 -> floor rises to +20% = 120; a dip to 121 does not fire.
    sig, px = _mk(["LONG"] * 5, [100, 120, 140, 121, 119])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    assert list(out) == ["LONG", "LONG", "LONG", "LONG", "CASH"]


@pytest.mark.slow
def test_synthetic_3x_tracks_real_upro():
    """Gate check (spec §7): the simulated 3x SPY must track real UPRO.

    Builds the synthetic-3x vehicle from SPY auto-adjusted (total-return) closes
    — NOT ^GSPC, whose dropped dividends (~1.8-2%/yr) would spuriously blow up
    the CAGR gap ×3 — and compares daily returns + CAGR to real UPRO over the
    2009+ overlap. If this fails, the §7 basis is void: stop and report.
    """
    start, end = date(2009, 6, 25), date(2025, 12, 31)
    spy = synthetic.fetch_close("SPY", start, end)
    upro = synthetic.fetch_close("UPRO", start, end)
    rf = synthetic.daily_risk_free(start, end)
    synth = synthetic.build_synthetic_leverage(
        spy, leverage=3.0, annual_expense=synthetic.UPRO_EXPENSE, rf_daily=rf
    )
    res = synthetic.validate_synthetic(synth["Close"], upro, "UPRO 3x")
    assert res["daily_return_corr"] > 0.99, res
    assert abs(res["cagr_gap_pp"]) < 5.0, res  # within 5 pp/yr over ~16y
