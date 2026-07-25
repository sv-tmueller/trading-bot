"""Tests for backtest/run_orb_study.py — the long/short ORB grid runner (#434).

Offline (synthetic frames + tmp files, no network). Locks the properties that keep the
runner honest:
  - the frozen grid is 18 cells and every one is reported (multiplicity disclosed);
  - UNDERPOWERED data produces NO cell table and a non-zero exit — the mechanical
    version of #431's hand-written "plumbing smoke" caveat;
  - missing data exits DATA-BLOCKED rather than inventing bars;
  - the random-entry baseline actually places trades (a masking bug here would silently
    hand every cell a free win against a do-nothing baseline).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest.run_orb_study as study


def _sessions(n_days, bars=14, seed=7, start="2020-01-06"):
    """A synthetic multi-session 5-min frame with genuine intraday movement."""
    rng = np.random.default_rng(seed)
    frames = []
    for day in pd.bdate_range(start, periods=n_days):
        idx = pd.date_range(f"{day:%Y-%m-%d} 14:30", periods=bars, freq="5min",
                            tz="UTC")
        steps = rng.normal(0, 0.4, bars).cumsum()
        close = 100.0 + steps
        open_ = np.concatenate([[100.0], close[:-1]])
        high = np.maximum(open_, close) + rng.uniform(0.05, 0.5, bars)
        low = np.minimum(open_, close) - rng.uniform(0.05, 0.5, bars)
        frames.append(pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close}, index=idx))
    return pd.concat(frames)


# ---------------------------------------------------------------------------
# Frozen grid
# ---------------------------------------------------------------------------

def test_grid_is_eighteen_cells():
    assert study.N_CELLS == 18
    assert len(study.DIRECTIONS) == 2
    assert study.OR_BARS_GRID == (1, 3, 6)
    assert len(study.TARGET_GRID) == 3


def test_run_grid_reports_every_cell():
    rows = study.run_grid(_sessions(40))
    assert len(rows) == study.N_CELLS
    combos = {(r["direction"], r["or_bars"], r["target"]) for r in rows}
    assert len(combos) == study.N_CELLS       # no cell silently dropped or duplicated


def test_both_directions_are_present():
    rows = study.run_grid(_sessions(40))
    assert {r["direction"] for r in rows} == {"long", "short"}


def test_spy_bar_is_the_standing_frozen_value():
    """Comparability with #425/#430 depends on this constant not drifting."""
    assert study.SPY_BAR == pytest.approx(1.3085475049604838)


# ---------------------------------------------------------------------------
# Cells and baselines actually trade
# ---------------------------------------------------------------------------

def test_long_cell_places_trades():
    res = study.build_cell(_sessions(40), "long", 1, 5.0)
    assert res["trade_count"] > 0


def test_short_cell_places_trades():
    res = study.build_cell(_sessions(40), "short", 1, 5.0)
    assert res["trade_count"] > 0


def test_random_baseline_places_trades():
    """Guards the masking bug: a NaN-ed random baseline would trade zero times and
    hand every real cell an unearned win."""
    df = _sessions(40)
    real = study.build_cell(df, "long", 1, 5.0)
    rand = study.build_random_cell(df, "long", 1, 5.0)
    assert real["trade_count"] > 0
    assert rand["trade_count"] > 0


def test_random_baseline_is_seeded_and_reproducible():
    df = _sessions(40)
    a = study.build_random_cell(df, "long", 1, 5.0)
    b = study.build_random_cell(df, "long", 1, 5.0)
    assert a["ending_equity"] == pytest.approx(b["ending_equity"])
    assert a["trade_count"] == b["trade_count"]


def test_cells_never_hold_overnight():
    """session_close_out: no trade may span two calendar dates."""
    df = _sessions(30)
    for direction in ("long", "short"):
        res = study.build_cell(df, direction, 1, None)
        for t in res["trades"]:
            assert t["entry_date"].date() == t["exit_date"].date()


def test_wider_opening_range_gives_fewer_or_equal_entries():
    """A 30-min OR is harder to break out of than a 5-min one."""
    df = _sessions(60)
    narrow = study.build_cell(df, "long", 1, None)["trade_count"]
    wide = study.build_cell(df, "long", 6, None)["trade_count"]
    assert wide <= narrow


# ---------------------------------------------------------------------------
# The mechanical power refusal
# ---------------------------------------------------------------------------

def test_missing_data_exits_data_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = study.main([])
    assert rc == 2
    out = capsys.readouterr().out
    assert "DATA-BLOCKED" in out
    assert "|" not in out          # no cell table on missing data


def test_underpowered_data_prints_no_cell_table(tmp_path, monkeypatch, capsys):
    """The #431 shape: a real file, but far too shallow to read."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "shallow.csv"
    _sessions(30).to_csv(p, index_label="timestamp")
    rc = study.main(["--data", str(p)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "DATA-BLOCKED" in out
    assert "plumbing" in out
    assert "| long |" not in out   # crucially: NO per-cell numbers are shown


def test_report_states_multiplicity_and_the_bar():
    rows = study.run_grid(_sessions(40))
    bench = {"calmar_us": 0.5}
    text = study.format_report(rows, bench, "DIRECTIONAL: ...", "local:test.csv")
    assert "18 cells" in text
    assert "multiplicity" in text
    assert "1.3085" in text
    assert text.count("| long |") + text.count("| short |") == study.N_CELLS


def test_local_csv_round_trip_loads_and_runs(tmp_path):
    """The operator's file-drop path end to end: CSV on disk -> cells computed."""
    from backtest.intraday_data import load_local

    p = tmp_path / "SPY_5min.csv"
    _sessions(40).to_csv(p, index_label="timestamp")
    df = load_local(p)
    rows = study.run_grid(df)
    assert len(rows) == study.N_CELLS
    assert any(r["trades"] > 0 for r in rows)


# ---------------------------------------------------------------------------
# Negative control — the pure-noise-must-fail property (#398's convention).
# ---------------------------------------------------------------------------

def _noise_sessions(n_days, bars=78, seed=11, start="2014-01-02"):
    """Driftless random-walk intraday bars: NO edge exists by construction."""
    rng = np.random.default_rng(seed)
    frames = []
    for day in pd.bdate_range(start, periods=n_days):
        idx = pd.date_range(f"{day:%Y-%m-%d} 14:30", periods=bars, freq="5min",
                            tz="UTC")
        close = 100.0 + rng.normal(0, 0.08, bars).cumsum()
        op = np.concatenate([[close[0]], close[:-1]])
        hi = np.maximum(op, close) + rng.uniform(0.01, 0.09, bars)
        lo = np.minimum(op, close) - rng.uniform(0.01, 0.09, bars)
        frames.append(pd.DataFrame(
            {"Open": op, "High": hi, "Low": lo, "Close": close}, index=idx))
    return pd.concat(frames)


@pytest.mark.slow
def test_pure_noise_clears_no_cell_and_matches_its_random_twin():
    """On data with no edge BY CONSTRUCTION, the harness must find none.

    Two properties, both load-bearing for trusting a real run:
      1. no cell clears the SPY bar — the harness cannot manufacture edge from noise;
      2. every cell sits close to its own seeded random-entry twin — the ORB's *timing*
         adds nothing when there is nothing to time, which is exactly the tell that
         killed #430's Turtle breakout.

    Mirrors the pure-noise-must-fail self-test in tests/test_overfitting_gate.py.
    Marked slow: 760 sessions x 18 cells is a real grid run, not a unit test.
    """
    rows = study.run_grid(_noise_sessions(760))
    assert len(rows) == study.N_CELLS
    assert not any(r["beats_bar"] for r in rows), "noise cleared the bar"
    for r in rows:
        assert r["calmar_us"] < 0, f"noise cell {r} produced a positive Calmar"
        # The real cell must not look meaningfully better than shuffled entries.
        assert r["calmar_us"] - r["random_calmar_us"] < 0.25, (
            f"cell {r} beat its random twin by an implausible margin on pure noise"
        )
