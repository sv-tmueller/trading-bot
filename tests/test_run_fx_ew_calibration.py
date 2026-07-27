"""Tests for backtest/run_fx_ew_calibration.py — the firing-rate calibration runner.

Offline / synthetic OHLC (no network) via ``--data``. Live-FXCM-fetch behavior is not
exercised here (that path is ``@pytest.mark.slow`` territory elsewhere in this repo's
convention; this runner's FXCM-specific loading reuses ``run_fx_plumbing_check``'s
already-tested ``build_history``, so nothing new needs re-testing there).

Locks the runner's two frozen discipline rules (SUB_PLAN §4, do-not-de-scope):
  - exempt from the power gate (a shallow frame still gets a firing-rate table);
  - no performance number of any kind, ever, in stdout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import backtest.run_fx_ew_calibration as rfc


def _synth_hourly(n: int = 2000, seed: int = 4) -> pd.DataFrame:
    """Synthetic H1 OHLC random walk -- enough structure to fire some pivots/waves."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    steps = rng.normal(0, 0.004, n)
    close = 100.0 * np.cumprod(1.0 + steps)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.0005
    low = np.minimum(open_, close) * 0.9995
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close}, index=idx
    )


def _write_csv(tmp_path, df: pd.DataFrame, name: str = "bars.csv"):
    path = tmp_path / name
    df.reset_index(names="timestamp").to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Exempt from the power gate.
# ---------------------------------------------------------------------------

def test_calibration_runs_on_a_shallow_underpowered_frame(tmp_path, capsys):
    """A shallow frame (far below the 500-session floor) still gets a firing-rate
    read -- the power gate does not apply to a rate diagnostic (candlestick precedent:
    "firing rates are a property of the detectors, not a performance claim")."""
    df = _synth_hourly(n=200)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "firing-rate calibration" in out.lower()


def test_calibration_prints_power_verdict_without_gating_on_it(tmp_path, capsys):
    df = _synth_hourly(n=200)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UNDERPOWERED" in out  # printed, not gated


# ---------------------------------------------------------------------------
# No performance number of any kind, ever.
# ---------------------------------------------------------------------------

def test_calibration_stdout_never_contains_a_performance_number(tmp_path, capsys):
    df = _synth_hourly(n=3000)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    for forbidden in ("Calmar", "Sharpe", "equity", "PnL", "return", "win rate", "profit"):
        assert forbidden not in out, f"found forbidden term {forbidden!r} in calibration stdout"


def test_calibration_on_promotable_sized_frame_still_prints_no_performance_number(tmp_path, capsys):
    """Even a deep, PROMOTABLE-power-shaped frame prints no performance number --
    the rule holds regardless of power, it is not a power-gated behavior."""
    df = _synth_hourly(n=90000, seed=11)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    for forbidden in ("Calmar", "Sharpe", "equity", "PnL", "return", "win rate", "profit"):
        assert forbidden not in out, f"found forbidden term {forbidden!r} in calibration stdout"


# ---------------------------------------------------------------------------
# Data-missing / basic structure of the report.
# ---------------------------------------------------------------------------

def test_calibration_exits_2_when_data_file_is_missing(tmp_path, capsys):
    rc = rfc.main(["--data", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


def test_calibration_reports_pivots_per_theta_grid_point(tmp_path, capsys):
    df = _synth_hourly(n=3000)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    for theta in rfc.ew.THETA_GRID:
        assert f"{theta:.2%}" in out


def test_calibration_reports_structure_counts_by_kind_and_direction(tmp_path, capsys):
    df = _synth_hourly(n=3000)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "impulse" in out
    assert "zigzag" in out


def test_calibration_prints_reproducibility_hash_line(tmp_path, capsys):
    df = _synth_hourly(n=3000)
    path = _write_csv(tmp_path, df)

    rc = rfc.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "sha256(input)" in out
    assert "sha256(label" in out


def test_calibration_two_runs_produce_identical_reproducibility_hashes(tmp_path, capsys):
    df = _synth_hourly(n=3000)
    path = _write_csv(tmp_path, df)

    rfc.main(["--data", str(path)])
    first = capsys.readouterr().out
    rfc.main(["--data", str(path)])
    second = capsys.readouterr().out

    def _hash_line(out):
        return next(line for line in out.splitlines() if "sha256(input)" in line)

    assert _hash_line(first) == _hash_line(second)
