"""Tests for the CAGR + Calmar additions to _compute_window_metrics.

All offline / synthetic — no network. The existing return/vol/maxDD/Sharpe
keys must remain unchanged; this only adds `cagr` and `calmar`.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import backtest.walkforward as wf


def test_cagr_and_calmar_on_synthetic_curve():
    """Hand-checkable CAGR and Calmar on a curve with a known max drawdown.

    Construct a 2-year (731 calendar days) equity slice that:
    - starts at 100, dips to 80 (a -20% drawdown from the running peak of 100),
    - recovers and ends at 144.

    total_return = 144/100 - 1 = 0.44
    span_years   = (idx[-1]-idx[0]).days / 365.25 = 731 / 365.25 = 2.00137...
    CAGR         = 1.44 ** (1/span_years) - 1
    maxDD        = (80 - 100)/100 = -0.20
    Calmar       = CAGR / |maxDD|
    """
    # Daily index spanning exactly 731 calendar days (2 years inclusive of both ends)
    idx = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    span_days = (idx[-1] - idx[0]).days
    assert span_days == 730  # 2020-01-01 -> 2021-12-31 is 730 days

    n = len(idx)
    # Build a curve: 100 -> 80 (trough at 1/3) -> 144 (end).
    # Piecewise-linear is fine; only the running-peak trough and the endpoints
    # drive the metrics under test.
    trough_i = n // 3
    values = np.empty(n)
    values[: trough_i + 1] = np.linspace(100.0, 80.0, trough_i + 1)
    values[trough_i:] = np.linspace(80.0, 144.0, n - trough_i)
    equity = pd.Series(values, index=idx)

    metrics = wf._compute_window_metrics(
        equity_slice=equity,
        trades=[],
        starting_cash=100.0,
    )

    # max drawdown: peak is the start (100), trough is 80 -> -0.20
    assert metrics["max_drawdown"] == pytest.approx(-0.20, abs=1e-9)

    total_return = 144.0 / 100.0 - 1.0
    span_years = span_days / 365.25
    expected_cagr = (1.0 + total_return) ** (1.0 / span_years) - 1.0
    assert metrics["cagr"] == pytest.approx(expected_cagr, rel=1e-9)

    expected_calmar = expected_cagr / abs(-0.20)
    assert metrics["calmar"] == pytest.approx(expected_calmar, rel=1e-9)


def test_calmar_is_nan_when_no_drawdown():
    """A strictly monotonic-up curve has maxDD == 0 -> Calmar is NaN (documented)."""
    idx = pd.date_range("2020-01-01", "2021-01-01", freq="D")
    equity = pd.Series(np.linspace(100.0, 130.0, len(idx)), index=idx)

    metrics = wf._compute_window_metrics(
        equity_slice=equity,
        trades=[],
        starting_cash=100.0,
    )
    assert metrics["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
    assert math.isnan(metrics["calmar"])


def test_existing_metric_keys_preserved():
    """Adding cagr/calmar must not drop the original metric keys."""
    idx = pd.date_range("2020-01-01", "2020-06-30", freq="D")
    equity = pd.Series(np.linspace(100.0, 110.0, len(idx)), index=idx)
    metrics = wf._compute_window_metrics(equity_slice=equity, trades=[], starting_cash=100.0)
    for key in ("total_return", "annualized_vol", "max_drawdown", "sharpe", "flip_count"):
        assert key in metrics
    assert "cagr" in metrics
    assert "calmar" in metrics
