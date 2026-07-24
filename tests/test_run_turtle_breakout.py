"""Tests for backtest/run_turtle_breakout.py wiring (#430).

Offline / synthetic OHLC (no network): ``_fetch`` is monkeypatched. Verifies the grid
wiring, the daily-only gate (D1 N=6, D2 per-day returns), the hourly-depth probe, the
random/always-in baselines, and that the per-window pass survives a zero-trade window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.run_turtle_breakout as rt


def _synth_ohlc(n: int, seed: int, drift: float, start: str, freq: str) -> pd.DataFrame:
    """Deterministic OHLC with an up-drift so Donchian-55 breakouts occur."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.012, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    span = rng.uniform(0.002, 0.02, n) * close
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)


def _declining_ohlc(n: int, start: str) -> pd.DataFrame:
    """Monotone-declining series: never a new 55-bar high -> zero breakouts."""
    close = np.linspace(100.0, 50.0, n)
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) + 0.1
    low = np.minimum(open_, close) - 0.1
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)


def _fake_fetch(ticker: str, start, end, interval: str = "1d") -> pd.DataFrame:
    seed = (hash(ticker) & 0xFFFF) + (0 if interval == "1d" else 7)
    if interval == "1d":
        return _synth_ohlc(1300, seed, drift=0.0006, start="2016-01-04", freq="B")
    return _synth_ohlc(2000, seed, drift=0.0004, start="2024-01-02", freq="h")


@pytest.fixture(autouse=True)
def _patch_fetch(monkeypatch):
    monkeypatch.setattr(rt, "_fetch", _fake_fetch)


def test_build_cell_makes_trades_on_a_breakout_series():
    df = _synth_ohlc(600, seed=1, drift=0.001, start="2016-01-04", freq="B")
    sim = rt._build_cell(df, r=3)
    assert sim["trade_count"] >= 1
    for t in sim["trades"]:
        assert t["exit_date"] > t["entry_date"]
        assert t["exit_reason"] in {"stop", "target", "eow", "end_of_window"}


def test_build_cell_zero_trades_on_declining_series():
    df = _declining_ohlc(400, start="2016-01-04")
    sim = rt._build_cell(df, r=2)
    assert sim["trade_count"] == 0
    assert sim["ending_equity"] == pytest.approx(sim["starting_cash"])


def test_random_cell_is_seed_reproducible():
    df = _synth_ohlc(500, seed=2, drift=0.0008, start="2016-01-04", freq="B")
    a = rt._build_random_cell(df, r=3, seed=99)
    b = rt._build_random_cell(df, r=3, seed=99)
    assert a["trade_count"] == b["trade_count"]
    assert a["ending_equity"] == pytest.approx(b["ending_equity"])


def test_per_window_pass_survives_a_zero_trade_window():
    """A declining window yields 0 trades (NaN Calmar dropped) without crashing."""
    df = _declining_ohlc(700, start="2016-01-04")
    st = rt._per_window_calmar(df, lambda d: rt._build_cell(d, 2))
    assert st["n_windows"] == 0  # every window is zero-trade -> all dropped
    assert np.isnan(st["median_calmar"])


def test_run_turtle_full_grid_and_hourly_probe():
    res = rt.run_turtle(end=pd.Timestamp("2026-06-30").date())
    # 12 cells: R{2,3,4} x {SPY, ES=F} x {daily, hourly}
    assert len(res["cells"]) == 12
    for vehicle in rt.VEHICLES:
        for bar in rt.BARS:
            for r in rt.R_VALUES:
                assert (vehicle, bar, r) in res["cells"]
    # hourly depth probe reports a bar count per vehicle
    for vehicle in rt.VEHICLES:
        assert res["hourly_depth"][vehicle]["n_bars"] > 0
    assert res["spy_bar"] == rt.SPY_BAR


def test_daily_gate_uses_six_trials_and_never_crashes():
    res = rt.run_turtle(end=pd.Timestamp("2026-06-30").date())
    g = res["gate"]
    assert g is not None
    assert g["n_trials"] == 6                      # D1: 6 daily cells only
    # gate either computed a verdict or recorded an error string — never crashed
    assert (g["gate"] is not None) or (g["error"] is not None)
    if g["gate"] is not None:
        assert set(g["gate"].keys()) >= {"passed", "dsr", "pbo", "ci_low"}


def test_cells_carry_baselines_and_beats_flag_inputs():
    res = rt.run_turtle(end=pd.Timestamp("2026-06-30").date())
    cell = res["cells"][("SPY", "daily", 3)]
    assert "random_calmar_us" in cell
    assert "always_in_calmar_us" in cell
    assert "stability" in cell                     # daily arm gets per-window stability
    assert "metrics" in cell and "calmar_us" in cell["metrics"]
    # hourly cells are directional: no per-window stability attached
    assert "stability" not in res["cells"][("SPY", "hourly", 3)]
