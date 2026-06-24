"""Offline smoke + invariant tests for the leveraged-regime study runner (#321).

The fetch seams (yfinance) are monkeypatched with a hand-built SPY series, so the
real synthetic-3x model + the real simulator + the real after-tax layer run
without network.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

import backtest.run_leveraged_regime_study as R


def _synthetic_spy() -> pd.DataFrame:
    # ~900 business days: rise -> drawdown -> recovery, so the trend signals flip.
    idx = pd.bdate_range("2015-01-01", periods=900)
    up1 = np.linspace(100, 150, 400)
    down = np.linspace(150, 95, 120)
    up2 = np.linspace(95, 165, 380)
    close = np.concatenate([up1, down, up2])
    return pd.DataFrame({"Open": close, "Close": close}, index=idx)


@pytest.fixture
def patched(monkeypatch):
    spy = _synthetic_spy()
    monkeypatch.setattr(R, "fetch_ohlc", lambda t, s, e: spy)
    monkeypatch.setattr(
        R, "daily_risk_free", lambda s, e: pd.Series(0.0001, index=spy.index)
    )
    # UPRO cross-check: return too-short overlap -> graceful "insufficient" path
    monkeypatch.setattr(R, "fetch_close", lambda t, s, e: spy["Close"].iloc[:10])
    return spy


def test_run_study_structure_and_strategies(patched):
    res = R.run_study(end=date(2018, 12, 31))
    assert set(res["rows"]) == {label for label, _, _ in R.STRATEGIES}
    assert res["n_days"] > 300
    # every row carries metrics + stability + bear, and the right vehicle
    for label, _, veh in R.STRATEGIES:
        r = res["rows"][label]
        assert {"metrics", "stability", "bear", "vehicle"} <= set(r)
        assert r["vehicle"] == veh  # regime rows trade syn3x; the 1x row trades spy


def test_after_tax_not_above_pretax(patched):
    res = R.run_study(end=date(2018, 12, 31))
    for label, r in res["rows"].items():
        m = r["metrics"]
        # after-tax CAGR (US) must not exceed pre-tax CAGR (tax is a drag, never a credit)
        if not (isinstance(m["cagr_us"], float) and np.isnan(m["cagr_us"])):
            assert m["cagr_us"] <= m["cagr_pretax"] + 1e-9, label


def test_leveraged_beats_1x_on_return(patched):
    # On a mostly-rising path, the 3x incumbent must out-CAGR 1x SPY (pre-tax).
    res = R.run_study(end=date(2018, 12, 31))
    inc = res["rows"]["200-DMA on 3x (INCUMBENT)"]["metrics"]["cagr_pretax"]
    spy = res["rows"]["1x SPY (buy & hold)"]["metrics"]["cagr_pretax"]
    assert inc > spy
