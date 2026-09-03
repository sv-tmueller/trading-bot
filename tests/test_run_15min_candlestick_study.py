"""Tests for backtest/run_15min_candlestick_study.py — the 15-min candlestick study.

Offline / synthetic OHLC (no network). Validates:
  - synthetic-frame pipeline smoke;
  - firing-rate table shape (all 14 detectors, both cadences);
  - win-rate / profit-factor computation correctness;
  - power-gate refusal (UNDERPOWERED withholds the performance table);
  - hourly baseline comparison structure;
  - cost-wall diagnostic output.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import candlestick as cs
from backtest.bracket import LONG, SHORT
import backtest.run_15min_candlestick_study as r15


def _synth_intraday(
    n: int = 5000, seed: int = 7, freq: str = "15min", drift: float = 0.0
) -> pd.DataFrame:
    """Synthetic intraday OHLC random walk at 15-min cadence, RTH-only.

    Generates properly sorted 15-minute bars during 13:30-21:00 UTC (26 bars/session).
    """
    rng = np.random.default_rng(seed)
    # Generate enough business-day sessions to cover n bars (26 bars per RTH session)
    days_needed = max(n // 26 + 10, 550)  # guarantee > 500 sessions for power gate
    starts = pd.bdate_range("2016-01-04", periods=days_needed)

    times = []
    for ts in starts:
        for hh in range(13, 21):
            for mm in (0, 15, 30, 45):
                if hh == 13 and mm < 30:
                    continue
                if hh == 21 and mm > 0:
                    continue
                times.append(pd.Timestamp(f"{ts.date()} {hh}:{mm:02d}", tz="UTC"))

    n_actual = min(len(times), n)
    times = times[:n_actual]
    idx = pd.DatetimeIndex(times, tz="UTC")

    close_prev = 100.0
    o_arr = np.empty(n_actual)
    h_arr = np.empty(n_actual)
    l_arr = np.empty(n_actual)
    c_arr = np.empty(n_actual)
    for i in range(n_actual):
        o = close_prev * (1 + rng.normal(0, 0.001))
        c = o * (1 + rng.normal(drift, 0.003))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.001)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.001)))
        o_arr[i] = o
        h_arr[i] = h
        l_arr[i] = lo
        c_arr[i] = c
        close_prev = c

    return pd.DataFrame(
        {"Open": o_arr, "High": h_arr, "Low": l_arr, "Close": c_arr}, index=idx
    )


def _save_csv(df: pd.DataFrame, path) -> None:
    df.reset_index(names="timestamp").to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Pipeline smoke
# ---------------------------------------------------------------------------

def test_imports_shared_primitives_from_daily_runner():
    """The 15m runner must reuse the frozen geometry, not redefine it."""
    assert r15.ARMS is not None
    assert r15.PATTERN_SPAN is not None
    assert r15.bracket_levels is not None
    assert r15.build_cell is not None
    assert r15.build_random_cell is not None
    # Same 14 arms
    assert len(r15.ARMS) == 14
    assert r15.N_CELLS == 28


def test_win_rate_pf_computation_correctness():
    """Win rate and profit factor are computed from the trade ledger."""
    fake_sim = {
        "trades": [
            {"pnl": 100.0, "return_pct": 0.01},
            {"pnl": -50.0, "return_pct": -0.005},
            {"pnl": 200.0, "return_pct": 0.02},
            {"pnl": -75.0, "return_pct": -0.0075},
        ],
    }
    wr, pf = r15._win_rate_pf(fake_sim)
    assert wr == pytest.approx(0.5)
    assert pf == pytest.approx(300.0 / 125.0)


def test_win_rate_pf_empty_ledger():
    wr, pf = r15._win_rate_pf({"trades": []})
    assert wr == 0.0
    assert pf == 0.0


def test_win_rate_pf_all_winners():
    fake_sim = {"trades": [{"pnl": 100.0, "return_pct": 0.01}]}
    wr, pf = r15._win_rate_pf(fake_sim)
    assert wr == 1.0
    assert pf == float("inf")


def test_build_cell_eod_produces_a_ledger():
    """The EOD-flat cell builder must return a valid simulation dict."""
    df = _synth_intraday(2000)
    arm = ("hammer", "hammer", LONG)
    sim = r15._build_cell_eod(df, arm, 2.0)
    assert "trades" in sim
    assert "equity_curve" in sim
    assert "trade_count" in sim


def test_run_perf_grid_returns_expected_rows():
    """The performance grid must produce one row per (arm, R) pair."""
    df = _synth_intraday(3000)
    rows = r15.run_perf_grid(df)
    assert len(rows) == r15.N_CELLS
    for row in rows:
        assert "win_rate" in row
        assert "profit_factor" in row
        assert "metrics" in row
        assert "random_calmar_us" in row
        assert "trade_count" in row


# ---------------------------------------------------------------------------
# Firing-rate table
# ---------------------------------------------------------------------------

def test_firing_rate_table_has_all_14_detectors(tmp_path, capsys):
    df = _synth_intraday(3000)
    p15 = tmp_path / "15m.csv"
    p60 = tmp_path / "60m.csv"
    _save_csv(df, p15)
    _save_csv(df, p60)

    rc = r15.main(["--data-15m", str(p15), "--data-60m", str(p60), "--firing-rates"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Firing-rate calibration" in out
    for name in cs.PATTERNS:
        assert name in out
    # No performance numbers in calibration mode
    assert "CalmarUS" not in out
    assert "win rate" not in out.lower()


# ---------------------------------------------------------------------------
# Power-gate refusal
# ---------------------------------------------------------------------------

def test_power_gate_withholds_performance_table(tmp_path, capsys):
    """An UNDERPOWERED frame must print firing rates but NO performance table."""
    # Very short frame: ~5 sessions, far below the 500-session floor
    df_shallow = _synth_intraday(130)
    p15 = tmp_path / "shallow15.csv"
    p60 = tmp_path / "shallow60.csv"
    _save_csv(df_shallow, p15)
    _save_csv(df_shallow, p60)

    rc = r15.main(["--data-15m", str(p15), "--data-60m", str(p60)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UNDERPOWERED" in captured.err
    # Firing rates ARE printed (exempt from gate)
    assert "Firing-rate calibration" in captured.out
    # Performance table is NOT printed — check the perf-table header is absent
    assert "per-arm performance" not in captured.out
    assert "Cost-wall assessment" not in captured.out


def test_power_gate_does_not_fire_on_firing_rates_mode(tmp_path, capsys):
    """Even a shallow frame prints firing rates (exempt from the power gate)."""
    df_shallow = _synth_intraday(130)
    p15 = tmp_path / "shallow15.csv"
    p60 = tmp_path / "shallow60.csv"
    _save_csv(df_shallow, p15)
    _save_csv(df_shallow, p60)

    rc = r15.main(["--data-15m", str(p15), "--data-60m", str(p60), "--firing-rates"])
    out = capsys.readouterr().out
    assert rc == 0  # NOT 2
    assert "Firing-rate calibration" in out


def test_data_blocked_when_no_paths_supplied(capsys):
    rc = r15.main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "DATA-BLOCKED" in err


# ---------------------------------------------------------------------------
# Hourly baseline comparison
# ---------------------------------------------------------------------------

def test_perf_table_compares_15m_vs_60m(tmp_path, capsys):
    """The performance table must include both 15m and 60m columns."""
    # 18000 bars = 600 sessions -> DIRECTIONAL (passes the 500-session floor)
    df = _synth_intraday(18000)
    p15 = tmp_path / "15m.csv"
    p60 = tmp_path / "60m.csv"
    _save_csv(df, p15)
    _save_csv(df, p60)

    rc = r15.main(["--data-15m", str(p15), "--data-60m", str(p60)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "15m WR" in out
    assert "60m WR" in out
    assert "15m PF" in out
    assert "60m PF" in out


# ---------------------------------------------------------------------------
# Cost-wall diagnostics
# ---------------------------------------------------------------------------

def test_cost_wall_diag_structure():
    """cost_wall_diag returns a dict with the expected keys for both cadences."""
    df = _synth_intraday(18000)
    diag = r15.cost_wall_diag(df, df)
    assert "15m" in diag
    assert "60m" in diag
    for label in ("15m", "60m"):
        d = diag[label]
        assert "total_trades" in d
        assert "sessions" in d
        assert "trades_per_day" in d
        assert "ann_drag_pct" in d
        assert "median_stop_dist" in d
        assert "median_slip_over_stop" in d
        assert "pct_slip_ge_stop" in d


def test_cost_wall_appears_in_output(tmp_path, capsys):
    # 18000 bars = 600 sessions -> DIRECTIONAL (passes the 500-session floor)
    df = _synth_intraday(18000)
    p15 = tmp_path / "15m.csv"
    p60 = tmp_path / "60m.csv"
    _save_csv(df, p15)
    _save_csv(df, p60)

    rc = r15.main(["--data-15m", str(p15), "--data-60m", str(p60)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cost-wall assessment" in out
    assert "#422" in out
    assert "#571" in out
    assert "annualized drag" in out.lower()


def test_median_stop_distance_returns_float():
    df = _synth_intraday(2000)
    arm = ("hammer", "hammer", LONG)
    val = r15._median_stop_distance(df, arm, 2.0)
    assert isinstance(val, float)
    # Should be positive on a reasonable frame
    if np.isfinite(val):
        assert val > 0
