from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backtest import synthetic


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
