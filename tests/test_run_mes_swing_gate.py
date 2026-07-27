"""Tests for backtest/run_mes_swing_gate.py — pooled #398 gate at n_trials=24 (#457 PR A).

Offline / synthetic OHLC only (no network). Mirrors the pure-noise-must-fail convention at
tests/test_run_candlestick_gate.py and the daily-gate wiring in tests/test_run_turtle_breakout.py.
This module applies the gate; it introduces no new grid, no new threshold, and does not
modify backtest/run_mes_swing_study.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.run_mes_swing_gate as gate


def _synth_daily(n: int = 3600, seed: int = 3, drift: float = 0.0,
                  start: str = "2010-01-01") -> pd.DataFrame:
    """Synthetic daily OHLC random walk (mirrors run_mes_swing_study.py's test helper)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.011, n)))
    o = np.empty(n)
    h = np.empty(n)
    lo = np.empty(n)
    for i in range(n):
        base = close[i - 1] if i else 100.0
        o[i] = base * (1 + rng.normal(0, 0.002))
        h[i] = max(o[i], close[i]) * (1 + abs(rng.normal(0, 0.004)))
        lo[i] = min(o[i], close[i]) * (1 - abs(rng.normal(0, 0.004)))
    return pd.DataFrame(
        {"Open": o, "High": h, "Low": lo, "Close": close}, index=idx
    )


# ---------------------------------------------------------------------------
# (a) N-accounting is exactly 24, imported not redefined
# ---------------------------------------------------------------------------

def test_n_cells_is_imported_from_the_study_module():
    import backtest.run_mes_swing_study as study
    assert gate.N_CELLS is study.N_CELLS
    assert gate.N_CELLS == 24


def test_build_all_cells_has_exactly_24_trials():
    df = _synth_daily(3600, seed=1)
    cells = gate.build_all_cells(df)
    assert len(cells) == 24


def test_build_all_cells_keys_are_unique_and_cover_every_arm_and_r():
    import backtest.run_mes_swing_study as study
    df = _synth_daily(1200, seed=1)
    cells = gate.build_all_cells(df)
    assert set(cells.keys()) == {(a[0], r) for a in study.ARMS for r in study.R_GRID}


def test_gate_introduces_no_new_free_parameter():
    """ARMS, R_GRID, RANDOM_SEED are imported, never redefined."""
    import backtest.run_mes_swing_study as study
    assert gate.ARMS is study.ARMS
    assert gate.R_GRID is study.R_GRID
    assert gate.RANDOM_SEED is study.RANDOM_SEED


def test_cumulative_n_is_imported_from_the_study_module():
    import backtest.run_mes_swing_study as study
    assert gate.CUMULATIVE_N is study.CUMULATIVE_N


# ---------------------------------------------------------------------------
# The printed "cumulative N=" line reports CUMULATIVE_N, not N_CELLS (round-1 review
# finding 9) -- equal today by D2, but the round-2 inheritance argument rests on the
# distinction, so the report must read the right name.
# ---------------------------------------------------------------------------

def test_report_prints_cumulative_n_not_n_cells(monkeypatch, capsys):
    monkeypatch.setattr(gate, "CUMULATIVE_N", 999)
    power = gate.idata.describe_power(_synth_daily(3600, seed=1))
    result = {
        "best_cell": ("T1L", 2.0), "n_trials": 24, "n_common_days": 100,
        "trial_sharpes": {}, "gate": None, "error": "boom",
    }
    gate._print_report(power, "test", result)
    out = capsys.readouterr().out
    assert "cumulative N=999" in out
    assert "cumulative N=24" not in out


# ---------------------------------------------------------------------------
# (b) pure-noise frame must not pass the gate
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pure_noise_frame_does_not_pass_the_gate():
    df = _synth_daily(3600, seed=2026, drift=0.0)
    cells = gate.build_all_cells(df)
    spy_eq = gate.always_in(df, gate._GATE_COMMISSION_BPS)["equity_curve"]
    result = gate.evaluate_mes_gate(cells, spy_eq)
    assert result["n_trials"] == 24
    assert result["error"] is None
    assert result["gate"]["passed"] is False


# ---------------------------------------------------------------------------
# (c) same seed -> same output (bit-reproducible)
# ---------------------------------------------------------------------------

def test_same_seed_gives_the_same_gate_output():
    df = _synth_daily(2600, seed=7, drift=0.0003)
    cells_a = gate.build_all_cells(df)
    cells_b = gate.build_all_cells(df)
    spy_eq = gate.always_in(df, gate._GATE_COMMISSION_BPS)["equity_curve"]

    result_a = gate.evaluate_mes_gate(cells_a, spy_eq)
    result_b = gate.evaluate_mes_gate(cells_b, spy_eq)

    assert result_a["gate"]["dsr"] == result_b["gate"]["dsr"]
    assert result_a["gate"]["pbo"] == result_b["gate"]["pbo"]
    assert result_a["gate"]["ci_low"] == result_b["gate"]["ci_low"]
    assert result_a["best_cell"] == result_b["best_cell"]


# ---------------------------------------------------------------------------
# (d) refuses a non-PROMOTABLE frame
# ---------------------------------------------------------------------------

def test_main_refuses_a_non_promotable_frame(tmp_path, capsys):
    df = _synth_daily(120)          # far below the 500-session floor -> UNDERPOWERED
    path = tmp_path / "shallow.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = gate.main(["--data", str(path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "PROMOTABLE" in captured.err
    assert captured.out == ""


def test_main_exits_2_when_the_data_file_is_missing(tmp_path, capsys):
    rc = gate.main(["--data", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CLI wiring on a powered frame
# ---------------------------------------------------------------------------

def test_main_runs_and_prints_24_trials_on_a_powered_frame(tmp_path, capsys):
    df = _synth_daily(3600, seed=11, drift=0.0004)     # ~14 years -> PROMOTABLE
    path = tmp_path / "deep.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = gate.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "n_trials: 24" in out
    assert "DSR" in out and "PBO" in out
    assert ("PASS" in out) or ("FAIL" in out)
