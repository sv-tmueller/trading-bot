"""Tests for backtest/run_candlestick_timestop_study.py — the v3 time-stop grid (#448).

Offline / synthetic OHLC (no network). Live-data tests are @pytest.mark.slow.

Beyond grid shape, these lock the multiplicity-honesty properties that make a *widening*
search defensible (same conventions as tests/test_run_candlestick_context_study.py):
  - ARMS/R_GRID are IMPORTED, never redefined, so the registry cannot drift;
  - v3 runs CONTEXT_NONE only — no context x time-stop cross (D-B, the sub-plan);
  - v1's cells are not re-run here (``None`` is not a TIME_STOP_GRID level);
  - both the per-grid N (84) and the CUMULATIVE family N (168 = v1 28 + v2 56 + v3 84)
    are reported, plus the disclosure that this round's own N (84) coincidentally equals
    the PREVIOUS cumulative N (84) — a coincidence, not a re-use;
  - every trade in the grid respects its cell's own time stop;
  - a NaN Calmar is classified, never printed bare;
  - an UNDERPOWERED frame prints no per-cell table and exits 2;
  - pure noise clears no cell.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import candlestick as cs
import backtest.run_candlestick_context_study as rccs
import backtest.run_candlestick_study as rcs
import backtest.run_candlestick_timestop_study as rcts


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
    assert rcts.TIME_STOP_GRID == (3, 5, 10)
    assert rcts.N_CELLS == len(rcs.ARMS) * len(rcs.R_GRID) * 3 == 84
    assert rcts.CUMULATIVE_N == rccs.CUMULATIVE_N + rcts.N_CELLS == 168


def test_arms_and_r_grid_are_imported_not_redefined():
    """Identity against run_candlestick_study — the registry cannot drift between studies."""
    assert rcts.ARMS is rcs.ARMS
    assert rcts.R_GRID is rcs.R_GRID


def test_v3_runs_context_none_only():
    """No context x time-stop cross (D-B): every row is CONTEXT_NONE, never re-running v2."""
    df = _synth_daily(900)
    rows = rcts.run_grid(df)
    assert rows
    assert all(r["context"] == cs.CONTEXT_NONE for r in rows)


def test_no_time_stop_level_reproduces_v1():
    """None is not a level in TIME_STOP_GRID — v1's own (unbounded) cells are not re-run here."""
    assert None not in rcts.TIME_STOP_GRID


def test_run_grid_returns_one_row_per_frozen_cell():
    df = _synth_daily(900)
    rows = rcts.run_grid(df)
    assert len(rows) == rcts.N_CELLS
    assert {(r["arm"], r["r"], r["time_stop"]) for r in rows} == {
        (a[0], r, t) for a in rcs.ARMS for r in rcs.R_GRID for t in rcts.TIME_STOP_GRID
    }


def test_every_trade_respects_its_cells_time_stop():
    """Across the whole grid, no trade's bar-count exceeds its cell's own time stop."""
    df = _synth_daily(700)
    date_to_pos = {d: i for i, d in enumerate(df.index)}
    for arm in rcs.ARMS:
        for r in rcs.R_GRID:
            for time_stop in rcts.TIME_STOP_GRID:
                sim = rcs.build_cell(df, arm, r, max_bars=time_stop)
                for t in sim["trades"]:
                    held = date_to_pos[t["exit_date"]] - date_to_pos[t["entry_date"]]
                    assert held <= time_stop, (
                        f"{arm[0]}/R{r}/timestop{time_stop} held {held} bars"
                    )


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def test_report_prints_both_this_grid_N_and_cumulative_N():
    """The cumulative figure and the 84/84 coincidence disclosure must both be present."""
    df = _synth_daily(900)
    power = rcts.idata.describe_power(df)
    rows = rcts.run_grid(df)
    bench = {"calmar_us": 0.3}
    text = rcts.format_report(rows, bench, power, "test")
    assert f"THIS grid: N = {rcts.N_CELLS}" in text
    assert f"N = {rcts.CUMULATIVE_N}" in text
    assert "raises that bar" in text
    assert "coincidence" in text.lower()


def test_report_never_prints_a_bare_nan():
    df = _synth_daily(700)
    power = rcts.idata.describe_power(df)
    rows = [{
        "arm": "x", "direction": rcs.LONG, "r": 2.0, "time_stop": 3,
        "context": cs.CONTEXT_NONE,
        "metrics": {"calmar_us": float("nan"), "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"), "trade_count": 0, "max_drawdown": -0.1,
    }, {
        "arm": "y", "direction": rcs.LONG, "r": 3.0, "time_stop": 5,
        "context": cs.CONTEXT_NONE,
        "metrics": {"calmar_us": float("nan"), "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"), "trade_count": 9, "max_drawdown": -0.2,
    }]
    text = rcts.format_report(rows, {"calmar_us": 0.3}, power, "test")
    assert "nan" not in text.lower()
    assert "RUINED" in text
    assert "no-trades" in text


def test_report_counts_ruined_and_untraded_cells_explicitly():
    df = _synth_daily(700)
    power = rcts.idata.describe_power(df)
    rows = [{
        "arm": "x", "direction": rcs.LONG, "r": 2.0, "time_stop": 3,
        "context": cs.CONTEXT_NONE,
        "metrics": {"calmar_us": float("nan"), "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"), "trade_count": 0, "max_drawdown": -0.1,
    }, {
        "arm": "y", "direction": rcs.LONG, "r": 3.0, "time_stop": 10,
        "context": cs.CONTEXT_NONE,
        "metrics": {"calmar_us": float("nan"), "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"), "trade_count": 9, "max_drawdown": -0.2,
    }]
    text = rcts.format_report(rows, {"calmar_us": 0.3}, power, "test")
    assert "cells with a RUINED after-tax curve: 1 / 2" in text
    assert "cells that never traded: 1 / 2" in text


def test_sort_key_orders_finite_then_ruined_then_untraded():
    def row(calmar, trades):
        return {
            "arm": "a", "direction": rcs.LONG, "r": 2.0, "time_stop": 3,
            "context": cs.CONTEXT_NONE,
            "metrics": {"calmar_us": calmar, "cagr_pretax": 0.0},
            "random_calmar_us": float("nan"),
            "trade_count": trades, "max_drawdown": -0.1,
        }
    rows = [row(float("nan"), 0), row(float("nan"), 5), row(-1.0, 5), row(2.0, 5)]
    ordered = sorted(rows, key=rcts._sort_key)
    assert [rcts.cell_status(r) for r in ordered] == ["ok", "ok", "RUINED", "no-trades"]
    assert ordered[0]["metrics"]["calmar_us"] == 2.0


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

def test_main_exits_2_when_the_data_file_is_missing(tmp_path, capsys):
    rc = rcts.main(["--data", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


def test_main_exits_2_and_prints_no_table_on_an_underpowered_frame(tmp_path, capsys):
    df = _synth_daily(120)
    path = tmp_path / "shallow.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rcts.main(["--data", str(path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UNDERPOWERED" in captured.err
    assert captured.out == ""
    for arm in rcs.ARMS:
        assert arm[0] not in captured.err


def test_main_runs_the_full_grid_on_a_powered_frame(tmp_path, capsys):
    df = _synth_daily(3600)
    path = tmp_path / "deep.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rcts.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"N = {rcts.CUMULATIVE_N}" in out
    for time_stop in rcts.TIME_STOP_GRID:
        assert str(time_stop) in out


# ---------------------------------------------------------------------------
# Negative control
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pure_noise_clears_no_cell():
    """Driftless random-walk bars must clear no cell in the v3 grid either.

    Construction copied unchanged from v1/v2's own controls, so the three are
    comparable. Without this, an all-negative real result would be ambiguous between
    "time stops do not rescue the class" and "the new exit is wired up wrong".
    """
    df = _synth_daily(3600, seed=2026, drift=0.0)
    rows = rcts.run_grid(df)
    assert len(rows) == rcts.N_CELLS
    cleared = [
        r for r in rows
        if rcts.cell_status(r) == "ok" and r["metrics"]["calmar_us"] > rcts.SPY_BAR
    ]
    assert cleared == [], f"noise cleared {len(cleared)} cells"
