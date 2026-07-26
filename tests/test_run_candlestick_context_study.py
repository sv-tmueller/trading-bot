"""Tests for backtest/run_candlestick_context_study.py — the v2 trend-context grid.

Offline / synthetic OHLC (no network). Live-data tests are @pytest.mark.slow.

Beyond grid shape, these lock the multiplicity-honesty properties that make a *widening*
search defensible:
  - v1's 28 cells are NOT re-run here (that would double-count those trials);
  - both the per-grid N and the CUMULATIVE family N are reported;
  - a NaN Calmar is classified, never printed bare;
  - an UNDERPOWERED frame prints no per-cell table and exits 2;
  - pure noise clears no cell.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import candlestick as cs
from backtest.bracket import LONG
import backtest.run_candlestick_context_study as rccs
import backtest.run_candlestick_study as rcs


def _synth_daily(n: int = 1200, seed: int = 3, drift: float = 0.0) -> pd.DataFrame:
    """Synthetic daily OHLC random walk. Opens are NOT pinned to the prior close."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.011, n)))
    o = np.empty(n)
    h = np.empty(n)
    lo = np.empty(n)
    for i in range(n):
        base = close[i - 1] if i else 100.0
        o[i] = base * (1 + rng.normal(0, 0.002))
        h[i] = max(o[i], close[i]) * (1 + abs(rng.normal(0, 0.004)))
        lo[i] = min(o[i], close[i]) * (1 - abs(rng.normal(0, 0.004)))
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": close}, index=idx)


# ---------------------------------------------------------------------------
# Grid shape and multiplicity honesty
# ---------------------------------------------------------------------------

def test_grid_shape_and_cumulative_multiplicity():
    assert rccs.CONTEXT_GRID == (cs.CONTEXT_REVERSAL, cs.CONTEXT_CONTINUATION)
    assert rccs.N_CELLS == len(rcs.ARMS) * len(rcs.R_GRID) * 2 == 56
    assert rccs.CUMULATIVE_N == rcs.N_CELLS + rccs.N_CELLS == 84


def test_v1_context_none_is_not_re_run_in_v2():
    """Re-running v1's unfiltered cells here would double-count 28 trials."""
    assert cs.CONTEXT_NONE not in rccs.CONTEXT_GRID


def test_run_grid_returns_one_row_per_frozen_cell():
    df = _synth_daily(900)
    rows = rccs.run_grid(df)
    assert len(rows) == rccs.N_CELLS
    assert {(r["arm"], r["r"], r["context"]) for r in rows} == {
        (a[0], r, c) for a in rcs.ARMS for r in rcs.R_GRID for c in rccs.CONTEXT_GRID
    }


def test_report_states_both_the_grid_and_cumulative_n():
    """The cumulative figure must be present, or widening silently launders multiplicity."""
    df = _synth_daily(900)
    power = rccs.idata.describe_power(df)
    rows = rccs.run_grid(df)
    bench = {"calmar_us": 0.3}
    text = rccs.format_report(rows, bench, power, "test")
    assert f"THIS grid: N = {rccs.N_CELLS}" in text
    assert f"N = {rccs.CUMULATIVE_N}" in text
    assert "raises that bar" in text


def test_report_never_prints_a_bare_nan():
    df = _synth_daily(700)
    power = rccs.idata.describe_power(df)
    rows = [{
        "arm": "x", "direction": LONG, "r": 2.0, "context": cs.CONTEXT_REVERSAL,
        "metrics": {"calmar_us": float("nan"), "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"), "trade_count": 0, "max_drawdown": -0.1,
    }, {
        "arm": "y", "direction": LONG, "r": 3.0, "context": cs.CONTEXT_CONTINUATION,
        "metrics": {"calmar_us": float("nan"), "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"), "trade_count": 9, "max_drawdown": -0.2,
    }]
    text = rccs.format_report(rows, {"calmar_us": 0.3}, power, "test")
    assert "nan" not in text.lower()
    assert "RUINED" in text
    assert "no-trades" in text


def test_sort_key_orders_finite_then_ruined_then_untraded():
    def row(calmar, trades):
        return {
            "arm": "a", "direction": LONG, "r": 2.0, "context": cs.CONTEXT_REVERSAL,
            "metrics": {"calmar_us": calmar, "cagr_pretax": 0.0},
            "random_calmar_us": float("nan"),
            "trade_count": trades, "max_drawdown": -0.1,
        }
    rows = [row(float("nan"), 0), row(float("nan"), 5), row(-1.0, 5), row(2.0, 5)]
    ordered = sorted(rows, key=rccs._sort_key)
    assert [rccs.cell_status(r) for r in ordered] == ["ok", "ok", "RUINED", "no-trades"]
    assert ordered[0]["metrics"]["calmar_us"] == 2.0


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

def test_main_exits_2_when_the_data_file_is_missing(tmp_path, capsys):
    rc = rccs.main(["--data", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


def test_main_exits_2_and_prints_no_table_on_an_underpowered_frame(tmp_path, capsys):
    df = _synth_daily(120)
    path = tmp_path / "shallow.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rccs.main(["--data", str(path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UNDERPOWERED" in captured.err
    assert captured.out == ""


def test_main_runs_the_full_grid_on_a_powered_frame(tmp_path, capsys):
    df = _synth_daily(3600)
    path = tmp_path / "deep.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rccs.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"N = {rccs.CUMULATIVE_N}" in out
    for context in rccs.CONTEXT_GRID:
        assert context in out


# ---------------------------------------------------------------------------
# Negative control
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pure_noise_clears_no_cell():
    """Driftless random-walk bars must clear no cell in the v2 grid either.

    A new grid without its own negative control is not finished: without it, an all-negative
    real result is ambiguous between "the context filter does not help" and "the filter is
    wired up wrong".
    """
    df = _synth_daily(3600, seed=2026, drift=0.0)
    rows = rccs.run_grid(df)
    cleared = [
        r for r in rows
        if rccs.cell_status(r) == "ok" and r["metrics"]["calmar_us"] > rccs.SPY_BAR
    ]
    assert cleared == [], f"noise cleared {len(cleared)} cells"
