"""Tests for backtest/run_blend_illustration.py (#758).

Two layers, both offline (no network, no broker, no trial store):

1. Synthetic-fixture math tests on in-memory ``pd.Series`` -- the metric
   definitions (CAGR, max drawdown, Calmar, the n_w full-calendar-year
   convention, annualised Sharpe and vol, correlation) and the Pitfall 1
   arithmetic pin: a stream with an exactly zero mean, blended 50/50 with
   another stream, shows the blend's *mean* stay at the weighted mean (here
   zero) while its Calmar lifts on variance reduction alone.

2. Pinned-value tests against the two committed r2 returns CSVs under
   ``docs/research/2026-11-06-etf-daily-r2-study/``. These pin the numbers the
   decision note publishes, so a silent drift in the CSVs or in the metric
   definitions fails loudly. They are deterministic and well under a second (no
   ``slow`` marker). Read-only: the CSVs are frozen results artifacts.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import backtest.run_blend_illustration as rbi

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = REPO_ROOT / "docs" / "research" / "2026-11-06-etf-daily-r2-study"
DONCHIAN_CSV = STUDY_DIR / "etf-daily-r2-donchian-trend-breakout-development-returns.csv"
VOL_REGIME_CSV = STUDY_DIR / "etf-daily-r2-vol-regime-gating-development-returns.csv"

# Selected trials (r2 verdict sections 3 and 4).
DONCHIAN_TRIAL = "etf-daily-r2-donchian-trend-breakout-05"
VOL_REGIME_TRIAL = "etf-daily-r2-vol-regime-gating-06"

# 14 scored development years (2008-2021), the r2 n_w convention.
N_SCORED_YEARS = 14


def _series(values, start="2008-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def _periodic(pattern, scale, start="2008-01-01", end="2021-12-31"):
    """A busy-day series repeating ``pattern * scale`` across the whole span."""
    idx = pd.bdate_range(start, end)
    data = np.resize(np.asarray(pattern, dtype=float) * scale, len(idx))
    return pd.Series(data, index=idx)


# ---------------------------------------------------------------------------
# Synthetic-fixture math tests
# ---------------------------------------------------------------------------

def test_blend_daily_returns_is_the_weighted_sum():
    a = _series([0.01, -0.02, 0.03])
    b = _series([0.00, 0.04, -0.01])
    blended = rbi.blend_returns(a, b, 0.3)
    assert list(blended.index) == list(a.index)
    assert blended.iloc[1] == pytest.approx(0.3 * -0.02 + 0.7 * 0.04)


def test_blend_mean_is_exactly_the_weighted_mean_of_the_components():
    a = _series([0.01, -0.02, 0.03, 0.05])
    b = _series([0.00, 0.04, -0.01, 0.02])
    for w in (0.5, 0.3, 1.0, 0.0):
        blended = rbi.blend_returns(a, b, w)
        assert blended.mean() == pytest.approx(w * a.mean() + (1.0 - w) * b.mean(), abs=1e-15)


def test_weight_one_is_the_standalone_leg_and_weight_zero_the_benchmark():
    a = _series([0.01, -0.02, 0.03])
    b = _series([0.00, 0.04, -0.01])
    assert rbi.blend_metrics(a, b, 1.0)["mean_daily"] == pytest.approx(a.mean())
    assert rbi.blend_metrics(a, b, 0.0)["mean_daily"] == pytest.approx(b.mean())


def test_max_drawdown_is_a_non_negative_magnitude_on_the_equity_curve():
    # Equity 1.0 -> 1.2 -> 0.9 -> 0.9: the peak-to-trough drawdown is 25%.
    returns = _series([0.2, -0.25, 0.0])
    metrics = rbi.series_metrics(returns)
    assert metrics["max_drawdown"] == pytest.approx(0.25)
    assert metrics["max_drawdown"] >= 0.0


def test_calmar_is_cagr_over_max_drawdown():
    returns = _series([0.2, -0.25, 0.0])
    metrics = rbi.series_metrics(returns)
    assert metrics["calmar"] == pytest.approx(metrics["cagr"] / metrics["max_drawdown"])


def test_zero_drawdown_yields_a_none_calmar_and_a_none_median_year():
    returns = _series([0.01] * 260)  # monotonically up: no drawdown anywhere
    metrics = rbi.series_metrics(returns)
    assert metrics["max_drawdown"] == 0.0
    assert metrics["calmar"] is None
    assert metrics["median_year_calmar"] is None
    assert metrics["n_scored_years"] == 0


def test_scored_years_counts_only_full_calendar_years():
    # A span starting mid-January and ending mid-December scores no year at all.
    idx = pd.date_range("2010-01-15", "2011-12-15", freq="B")
    assert rbi.scored_years(idx) == []


def test_realized_vol_and_sharpe_are_annualised_at_252_days():
    rng = np.random.default_rng(0)
    returns = _series(rng.normal(0.0004, 0.01, 3000))
    metrics = rbi.series_metrics(returns)
    assert metrics["realized_vol"] == pytest.approx(returns.std(ddof=1) * np.sqrt(252))
    assert metrics["sharpe_annual"] == pytest.approx(
        returns.mean() / returns.std(ddof=1) * np.sqrt(252)
    )


def test_correlation_is_the_daily_return_correlation_of_the_two_legs():
    a = _series([0.01, -0.02, 0.03, -0.01, 0.02])
    b = _series([0.02, -0.04, 0.06, -0.02, 0.04])  # exactly 2x a
    assert rbi.blend_metrics(a, b, 0.5)["correlation"] == pytest.approx(1.0)


def test_zero_variance_leg_gives_a_nan_correlation_not_an_exception():
    a = _series([0.01] * 260)
    b = _series(np.linspace(-0.01, 0.01, 260))
    assert np.isnan(rbi.blend_metrics(a, b, 0.5)["correlation"])


def test_pitfall1_zero_mean_stream_lifts_calmar_on_variance_reduction_alone():
    """The note's core arithmetic, pinned mechanically.

    Two exactly zero-mean streams are blended 50/50. The blend's mean stays the
    weighted mean (here exactly 0.0), yet its drawdown is smaller than either
    component's and its Calmar sits *above* both components'. A Calmar-only bar
    would therefore pass a blend with no edge at all, which is precisely why the
    note makes a positive stand-alone mean a hard sub-condition.
    """
    a = _periodic([1, -1], 0.010)                       # +-1% alternating
    b = _periodic([1, 1, -1, 1, -1, -1], 0.012)         # a busier zero-mean stream
    assert a.mean() == 0.0
    assert b.mean() == 0.0

    blended = rbi.blend_returns(a, b, 0.5)
    ma, mb, mbl = rbi.series_metrics(a), rbi.series_metrics(b), rbi.series_metrics(blended)

    # Variance reduction is real: a shallower drawdown than either component.
    assert mbl["max_drawdown"] < ma["max_drawdown"]
    assert mbl["max_drawdown"] < mb["max_drawdown"]
    # The mean is unchanged by construction -- the weighted mean of zeros.
    assert mbl["mean_daily"] == 0.0
    # And the Calmar-only bar would nonetheless be *cleared*.
    assert mbl["calmar"] > ma["calmar"]
    assert mbl["calmar"] > mb["calmar"]


# ---------------------------------------------------------------------------
# Pinned-value tests against the committed r2 CSVs
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def donchian_frame() -> pd.DataFrame:
    return rbi.load_returns_csv(DONCHIAN_CSV)


@pytest.fixture(scope="module")
def vol_regime_frame() -> pd.DataFrame:
    return rbi.load_returns_csv(VOL_REGIME_CSV)


def test_load_returns_csv_reads_the_frozen_r2_returns_file(donchian_frame):
    assert list(donchian_frame.index[:1]) == [pd.Timestamp("2007-05-30")]
    assert donchian_frame.index[-1] == pd.Timestamp("2021-12-31")
    assert len(donchian_frame) == 3676
    assert DONCHIAN_TRIAL in donchian_frame.columns
    assert "benchmark" in donchian_frame.columns


def test_pinned_standalone_legs_and_benchmark_for_764(donchian_frame):
    leg = rbi.series_metrics(donchian_frame[DONCHIAN_TRIAL])
    bench = rbi.series_metrics(donchian_frame["benchmark"])
    assert leg["mean_daily"] == pytest.approx(0.00019153036961735975)
    assert leg["cagr"] == pytest.approx(0.04693684653961494)
    assert leg["max_drawdown"] == pytest.approx(0.18963260991728526)
    assert leg["calmar"] == pytest.approx(0.2475146366444466)
    assert leg["median_year_calmar"] == pytest.approx(1.4452890691853058)
    assert leg["n_scored_years"] == N_SCORED_YEARS
    assert bench["cagr"] == pytest.approx(0.07338948009380086)
    assert bench["max_drawdown"] == pytest.approx(0.22349304367600176)
    assert bench["median_year_calmar"] == pytest.approx(1.1077896932936104)


def test_pinned_blend_metrics_for_764_at_both_stated_weights(donchian_frame):
    leg, bench = donchian_frame[DONCHIAN_TRIAL], donchian_frame["benchmark"]

    half = rbi.blend_metrics(leg, bench, 0.5)
    assert half["cagr"] == pytest.approx(0.06124383033144021)
    assert half["max_drawdown"] == pytest.approx(0.14174141998039136)
    assert half["calmar"] == pytest.approx(0.4320813939913452)
    assert half["median_year_calmar"] == pytest.approx(1.2772940049497472)
    assert half["realized_vol"] == pytest.approx(0.07460198204638464)
    assert half["correlation"] == pytest.approx(0.47191923880234554)
    assert half["n_scored_years"] == N_SCORED_YEARS

    thirty = rbi.blend_metrics(leg, bench, 0.3)
    assert thirty["cagr"] == pytest.approx(0.06636646074947472)
    assert thirty["max_drawdown"] == pytest.approx(0.15897795129379277)
    assert thirty["calmar"] == pytest.approx(0.417457013437221)
    assert thirty["median_year_calmar"] == pytest.approx(1.0738631378648469)


def test_pinned_blend_metrics_for_763_at_both_stated_weights(vol_regime_frame):
    leg, bench = vol_regime_frame[VOL_REGIME_TRIAL], vol_regime_frame["benchmark"]

    half = rbi.blend_metrics(leg, bench, 0.5)
    assert half["cagr"] == pytest.approx(0.06400932073556231)
    assert half["max_drawdown"] == pytest.approx(0.12856700213577066)
    assert half["calmar"] == pytest.approx(0.49786741288380143)
    assert half["median_year_calmar"] == pytest.approx(1.818704851556446)
    assert half["realized_vol"] == pytest.approx(0.06788781681308541)
    assert half["correlation"] == pytest.approx(0.6469769243393635)
    assert half["n_scored_years"] == N_SCORED_YEARS

    thirty = rbi.blend_metrics(leg, bench, 0.3)
    assert thirty["cagr"] == pytest.approx(0.06797110753062752)
    assert thirty["max_drawdown"] == pytest.approx(0.1660442062624201)
    assert thirty["median_year_calmar"] == pytest.approx(1.5191520018295033)


def test_pinned_blend_mean_is_the_weighted_mean_on_the_real_data(donchian_frame):
    leg, bench = donchian_frame[DONCHIAN_TRIAL], donchian_frame["benchmark"]
    for w in rbi.WEIGHTS:
        blended = rbi.blend_returns(leg, bench, w)
        assert blended.mean() == pytest.approx(
            w * leg.mean() + (1.0 - w) * bench.mean(), abs=1e-15
        )


def test_the_blend_bar_is_weight_sensitive_on_764(donchian_frame):
    """The published illustration's point: 764's median-year Calmar clears the
    benchmark at 50/50 and falls below it at 30/70, so a blend bar would flip a
    verdict on the choice of weight alone."""
    leg, bench = donchian_frame[DONCHIAN_TRIAL], donchian_frame["benchmark"]
    bench_median = rbi.series_metrics(bench)["median_year_calmar"]
    assert rbi.blend_metrics(leg, bench, 0.5)["median_year_calmar"] > bench_median
    assert rbi.blend_metrics(leg, bench, 0.3)["median_year_calmar"] < bench_median


def test_illustration_covers_both_candidates_and_both_weights(capsys):
    assert rbi.main([]) == 0
    out = capsys.readouterr().out
    for token in (DONCHIAN_TRIAL, VOL_REGIME_TRIAL, "0.50", "0.30", "post-hoc", "illustrative"):
        assert token in out


def test_illustration_computes_no_dsr_or_pbo():
    """Constraint (b): the blend re-uses one selected trial's returns, so it adds
    no configuration to the DSR vector and must not re-run the luck gate."""
    source = (REPO_ROOT / "backtest" / "run_blend_illustration.py").read_text(encoding="utf-8")
    for forbidden in ("evaluate_gate", "programme_sharpes", "deflated_sharpe", "pbo"):
        assert forbidden not in source, forbidden
