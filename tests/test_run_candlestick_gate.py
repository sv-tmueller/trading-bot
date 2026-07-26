"""Tests for backtest/run_candlestick_gate.py — pooled #398 gate over the cumulative
candlestick family (28 v1 context-free + 56 v2 trend-context + 84 v3 time-stop cells =
168), #443 / #448.

Offline / synthetic OHLC only (no network). Mirrors the pure-noise-must-fail convention at
tests/test_run_orb_study.py:193 and the daily-gate wiring in tests/test_run_turtle_breakout.py.
This module applies the gate; it introduces no new grid, no new threshold, and does not
modify any of the three frozen runners (run_candlestick_study.py,
run_candlestick_context_study.py, run_candlestick_timestop_study.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.run_candlestick_gate as gate


def _synth_daily(n: int = 3600, seed: int = 3, drift: float = 0.0) -> pd.DataFrame:
    """Synthetic daily OHLC random walk (mirrors run_candlestick_study.py's test helper)."""
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
    return pd.DataFrame(
        {"Open": o, "High": h, "Low": lo, "Close": close}, index=idx
    )


# ---------------------------------------------------------------------------
# (a) N-accounting is exactly 168 (28 v1 + 56 v2 + 84 v3)
# ---------------------------------------------------------------------------

def test_build_all_cells_has_exactly_168_trials():
    """28 v1 context-free + 56 v2 context + 84 v3 time-stop cells = the cumulative N."""
    df = _synth_daily(3600, seed=1)
    cells = gate.build_all_cells(df)
    assert len(cells) == 168
    assert gate.N_CELLS == 168


def test_build_all_cells_keys_are_unique_and_cover_all_three_grids():
    df = _synth_daily(1200, seed=1)
    cells = gate.build_all_cells(df)
    assert len(set(cells.keys())) == 168


def test_the_v1_v2_subset_is_unchanged_by_the_v3_extension():
    """All 84 prior (v1+v2) keys are still present, unchanged (pinned on trade_count and
    ending equity).

    The recorded N=84 read must stay reproducible — the v3 extension pools additional
    cells, it must never perturb the ones the earlier reads already reported.
    """
    df = _synth_daily(1800, seed=5)
    before_keys = set()
    for arm in gate.ARMS:
        for r in gate.R_GRID:
            before_keys.add((arm[0], r, gate.CONTEXT_NONE))
    for arm in gate.ARMS:
        for r in gate.R_GRID:
            for context in gate.CONTEXT_GRID:
                before_keys.add((arm[0], r, context))
    assert len(before_keys) == 84

    cells = gate.build_all_cells(df)
    assert before_keys <= set(cells.keys())

    for key in before_keys:
        arm_name, r, context = key
        arm = next(a for a in gate.ARMS if a[0] == arm_name)
        expected = (
            gate.build_cell(df, arm, r) if context == gate.CONTEXT_NONE
            else gate.build_cell(df, arm, r, context=context)
        )
        assert cells[key]["trade_count"] == expected["trade_count"]
        assert cells[key]["ending_equity"] == pytest.approx(expected["ending_equity"])


# ---------------------------------------------------------------------------
# (b) pure-noise frame must not pass the gate
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pure_noise_frame_does_not_pass_the_gate():
    """Mirrors tests/test_run_orb_study.py:193's noise-must-fail convention.

    On data with no edge by construction, the pooled N=168 gate must reject it: DSR stays
    below threshold once deflated for 168 trials.
    """
    df = _synth_daily(3600, seed=2026, drift=0.0)
    cells = gate.build_all_cells(df)
    spy_eq = gate.always_in(df)["equity_curve"]
    result = gate.evaluate_candlestick_gate(cells, spy_eq)
    assert result["n_trials"] == 168
    assert result["error"] is None
    assert result["gate"]["passed"] is False


# ---------------------------------------------------------------------------
# (c) same seed -> same output (bit-reproducible)
# ---------------------------------------------------------------------------

def test_same_seed_gives_the_same_gate_output():
    df = _synth_daily(2600, seed=7, drift=0.0003)
    cells_a = gate.build_all_cells(df)
    cells_b = gate.build_all_cells(df)
    spy_eq = gate.always_in(df)["equity_curve"]

    result_a = gate.evaluate_candlestick_gate(cells_a, spy_eq)
    result_b = gate.evaluate_candlestick_gate(cells_b, spy_eq)

    assert result_a["gate"]["dsr"] == result_b["gate"]["dsr"]
    assert result_a["gate"]["pbo"] == result_b["gate"]["pbo"]
    assert result_a["gate"]["ci_low"] == result_b["gate"]["ci_low"]
    assert result_a["best_cell"] == result_b["best_cell"]


# ---------------------------------------------------------------------------
# (d) refuses a non-PROMOTABLE frame
# ---------------------------------------------------------------------------

def test_main_refuses_a_non_promotable_frame(tmp_path, capsys):
    """The gate is only defined at full power (finding 1) — it must not run below it."""
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

def test_main_runs_and_prints_168_trials_on_a_powered_frame(tmp_path, capsys):
    df = _synth_daily(3600, seed=11, drift=0.0004)     # ~14 years -> PROMOTABLE
    path = tmp_path / "deep.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = gate.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "n_trials: 168" in out
    assert "DSR" in out and "PBO" in out
    assert ("PASS" in out) or ("FAIL" in out)
