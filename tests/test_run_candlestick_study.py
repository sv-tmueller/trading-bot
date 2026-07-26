"""Tests for backtest/run_candlestick_study.py — the daily candlestick grid runner.

Offline / synthetic OHLC (no network). Live-data tests are @pytest.mark.slow.

Locks the runner's honesty machinery as well as its geometry:
  - the frozen grid's shape and multiplicity count;
  - stop/target geometry is anchored to the pattern extreme, on the correct side per
    direction, and a non-positive risk suppresses the entry rather than sizing off garbage;
  - a NaN Calmar is classified (no-trades vs RUINED) and never printed as a bare number;
  - an UNDERPOWERED frame prints NO per-cell table and exits 2;
  - a pure-noise negative control clears no cell (slow).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import candlestick as cs
from backtest.bracket import LONG, SHORT
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
    return pd.DataFrame(
        {"Open": o, "High": h, "Low": lo, "Close": close}, index=idx
    )


# ---------------------------------------------------------------------------
# Frozen grid integrity
# ---------------------------------------------------------------------------

def test_grid_shape_matches_the_declared_multiplicity():
    assert len(rcs.ARMS) == 14
    assert rcs.R_GRID == (2.0, 3.0)
    assert rcs.N_CELLS == len(rcs.ARMS) * len(rcs.R_GRID) == 28


def test_every_arm_names_a_registered_pattern_with_a_known_span():
    for arm_name, pattern, direction in rcs.ARMS:
        assert pattern in cs.PATTERNS, arm_name
        assert pattern in rcs.PATTERN_SPAN, pattern
        assert direction in (LONG, SHORT), arm_name


def test_doji_is_excluded_from_the_trading_grid():
    """doji is registered as a pattern but has no directional rule — it must not trade."""
    assert "doji" in cs.PATTERNS
    assert "doji" not in {pattern for _, pattern, _ in rcs.ARMS}


def test_arm_names_are_unique():
    names = [a[0] for a in rcs.ARMS]
    assert len(names) == len(set(names))


def test_directional_arms_match_the_registry_direction():
    """An arm's traded side must agree with the pattern's registered direction.

    The inside-bar arms are the deliberate exception: the pattern is NEUTRAL and the
    runner supplies both sides.
    """
    for arm_name, pattern, direction in rcs.ARMS:
        registered = cs.direction_of(pattern)
        if registered == cs.NEUTRAL:
            assert pattern == "inside_bar", arm_name
        else:
            assert registered == direction, arm_name


# ---------------------------------------------------------------------------
# Bracket geometry
# ---------------------------------------------------------------------------

def test_long_stop_sits_below_entry_and_target_above():
    df = _synth_daily(300)
    trigger = pd.Series(True, index=df.index)
    stop, target = rcs.bracket_levels(df, trigger, LONG, span=1, r=2.0)
    entry_ref = df["Open"] * (1 + rcs.SLIPPAGE_BPS / 10_000.0)
    live = stop.notna()
    assert live.any()
    assert (stop[live] < entry_ref[live]).all()
    assert (target[live] > entry_ref[live]).all()


def test_short_stop_sits_above_entry_and_target_below():
    df = _synth_daily(300)
    trigger = pd.Series(True, index=df.index)
    stop, target = rcs.bracket_levels(df, trigger, SHORT, span=1, r=2.0)
    entry_ref = df["Open"] * (1 - rcs.SLIPPAGE_BPS / 10_000.0)
    live = stop.notna()
    assert live.any()
    assert (stop[live] > entry_ref[live]).all()
    assert (target[live] < entry_ref[live]).all()


def test_target_distance_is_r_times_the_risk():
    df = _synth_daily(200)
    trigger = pd.Series(True, index=df.index)
    for r in (2.0, 3.0):
        stop, target = rcs.bracket_levels(df, trigger, LONG, span=1, r=r)
        entry_ref = df["Open"] * (1 + rcs.SLIPPAGE_BPS / 10_000.0)
        live = stop.notna()
        risk = entry_ref[live] - stop[live]
        reward = target[live] - entry_ref[live]
        np.testing.assert_allclose(reward.to_numpy(), (r * risk).to_numpy(), rtol=1e-9)


def test_stop_is_anchored_to_the_pattern_extreme_at_the_signal_bar():
    """The stop must come from the SIGNAL bar's extreme, shifted onto the entry bar."""
    df = _synth_daily(120)
    trigger = pd.Series(True, index=df.index)
    span = 3
    stop, _ = rcs.bracket_levels(df, trigger, LONG, span=span, r=2.0)
    expected = df["Low"].rolling(span).min().shift(1) * (1 - rcs.STOP_BUFFER)
    live = stop.notna() & expected.notna()
    np.testing.assert_allclose(stop[live].to_numpy(), expected[live].to_numpy(), rtol=1e-12)


def test_non_positive_risk_suppresses_the_entry():
    """An entry gapping past its own stop yields NaN levels, not a garbage position."""
    # Open gaps far BELOW the prior bar's low, so a long's stop sits above the entry.
    df = pd.DataFrame(
        {
            "Open": [100.0, 50.0],
            "High": [101.0, 51.0],
            "Low": [99.0, 49.0],
            "Close": [100.5, 50.5],
        },
        index=pd.bdate_range("2020-01-01", periods=2),
    )
    trigger = pd.Series([False, True], index=df.index)
    stop, target = rcs.bracket_levels(df, trigger, LONG, span=1, r=2.0)
    assert pd.isna(stop.iloc[1])
    assert pd.isna(target.iloc[1])


def test_levels_are_nan_where_no_entry_triggers():
    df = _synth_daily(60)
    trigger = pd.Series(False, index=df.index)
    stop, target = rcs.bracket_levels(df, trigger, LONG, span=1, r=2.0)
    assert stop.isna().all()
    assert target.isna().all()


# ---------------------------------------------------------------------------
# Cell construction
# ---------------------------------------------------------------------------

def test_build_cell_returns_a_ledger_and_respects_direction():
    df = _synth_daily(600)
    arm = ("hammer", "hammer", LONG)
    sim = rcs.build_cell(df, arm, 2.0)
    assert set(["trades", "equity_curve", "trade_count"]).issubset(sim)
    for t in sim["trades"]:
        assert t["exit_date"] > t["entry_date"]


def test_v1_grid_is_unchanged_by_the_context_parameter_default():
    """The frozen v1 grid must be byte-identical with the default context.

    v1's 28-cell result is on record in the pre-registration. Adding the context factor
    must not perturb it, or the published v1 numbers would silently stop reproducing.
    """
    df = _synth_daily(900)
    for arm in (("hammer", "hammer", LONG), ("shooting_star", "shooting_star", SHORT)):
        for r in rcs.R_GRID:
            default = rcs.build_cell(df, arm, r)
            explicit = rcs.build_cell(df, arm, r, context=cs.CONTEXT_NONE)
            assert default["trade_count"] == explicit["trade_count"]
            assert default["ending_equity"] == pytest.approx(explicit["ending_equity"])
            assert default["max_drawdown"] == pytest.approx(explicit["max_drawdown"])


def test_v1_grid_is_unchanged_by_the_max_bars_parameter_default():
    """The frozen v1 grid must be byte-identical with the default max_bars (#448 A2).

    v1's 28-cell result is on record in the pre-registration. Adding the time-stop
    passthrough must not perturb it, or the published v1 numbers would silently stop
    reproducing.
    """
    df = _synth_daily(900)
    for arm in (("hammer", "hammer", LONG), ("shooting_star", "shooting_star", SHORT)):
        for r in rcs.R_GRID:
            default = rcs.build_cell(df, arm, r)
            explicit = rcs.build_cell(df, arm, r, max_bars=None)
            assert default["trade_count"] == explicit["trade_count"]
            assert default["ending_equity"] == pytest.approx(explicit["ending_equity"])
            assert default["max_drawdown"] == pytest.approx(explicit["max_drawdown"])


def test_build_cell_honours_max_bars():
    """A tight max_bars must not increase the holding period of any trade."""
    df = _synth_daily(1200)
    arm = ("hammer", "hammer", LONG)
    r = 2.0
    unbounded = rcs.build_cell(df, arm, r)
    bounded = rcs.build_cell(df, arm, r, max_bars=3)
    assert bounded["trade_count"] > 0
    date_to_pos = {d: i for i, d in enumerate(df.index)}
    for t in bounded["trades"]:
        held = date_to_pos[t["exit_date"]] - date_to_pos[t["entry_date"]]
        assert held <= 3, f"trade held {held} bars, max_bars=3"
    # bounding the hold must never fabricate trades relative to the unbounded run
    assert bounded["trade_count"] >= unbounded["trade_count"]


def test_random_twin_honours_max_bars():
    """The random-entry control shares the geometry, including the time stop."""
    df = _synth_daily(1200)
    arm = ("hammer", "hammer", LONG)
    rand = rcs.build_random_cell(df, arm, 2.0, max_bars=3)
    assert rand["trade_count"] > 0
    date_to_pos = {d: i for i, d in enumerate(df.index)}
    for t in rand["trades"]:
        held = date_to_pos[t["exit_date"]] - date_to_pos[t["entry_date"]]
        assert held <= 3, f"twin trade held {held} bars, max_bars=3"


def test_context_filter_reduces_or_equals_the_unfiltered_trade_count():
    """A filter can only remove entries, never add them."""
    df = _synth_daily(1200)
    arm = ("hammer", "hammer", LONG)
    base = rcs.build_cell(df, arm, 2.0)["trade_count"]
    for mode in (cs.CONTEXT_REVERSAL, cs.CONTEXT_CONTINUATION):
        filtered = rcs.build_cell(df, arm, 2.0, context=mode)["trade_count"]
        assert filtered <= base, f"{mode} produced MORE trades than unfiltered"


def test_random_twin_draws_only_from_context_admitted_bars():
    """The control must differ from the real cell in entry timing ONLY, not in regime too."""
    df = _synth_daily(1200)
    arm = ("hammer", "hammer", LONG)
    mode = cs.CONTEXT_REVERSAL
    mask = cs.context_mask(df, LONG, mode)
    rand = rcs.build_random_cell(df, arm, 2.0, context=mode)
    # every entry date the twin used must sit on a context-admitted bar
    for t in rand["trades"]:
        # entry executes the bar AFTER the (masked) signal bar
        signal_pos = df.index.get_loc(t["entry_date"]) - 1
        assert bool(mask.iloc[signal_pos]), (
            f"twin entered off a bar the {mode} context excludes"
        )


def test_random_cell_matches_the_real_cell_trade_count_closely():
    """The control must trade a comparable amount or it is not a control."""
    df = _synth_daily(800)
    arm = ("hammer", "hammer", LONG)
    real = rcs.build_cell(df, arm, 2.0)
    rand = rcs.build_random_cell(df, arm, 2.0)
    assert real["trade_count"] > 0
    assert rand["trade_count"] > 0
    # same entry-signal count feeds both; realised trades can differ slightly because
    # overlapping entries are skipped while a lot is open
    assert abs(real["trade_count"] - rand["trade_count"]) <= real["trade_count"]


def test_random_cell_is_deterministic_for_a_given_seed():
    df = _synth_daily(400)
    arm = ("hammer", "hammer", LONG)
    a = rcs.build_random_cell(df, arm, 2.0, seed=99)
    b = rcs.build_random_cell(df, arm, 2.0, seed=99)
    assert a["trade_count"] == b["trade_count"]
    assert a["ending_equity"] == pytest.approx(b["ending_equity"])


def test_run_grid_returns_one_row_per_frozen_cell():
    df = _synth_daily(700)
    rows = rcs.run_grid(df)
    assert len(rows) == rcs.N_CELLS
    assert {(r["arm"], r["r"]) for r in rows} == {
        (a[0], r) for a in rcs.ARMS for r in rcs.R_GRID
    }


# ---------------------------------------------------------------------------
# Honesty machinery
# ---------------------------------------------------------------------------

def _row(calmar: float, trades: int) -> dict:
    return {
        "arm": "x", "direction": LONG, "r": 2.0,
        "metrics": {"calmar_us": calmar, "cagr_pretax": 0.0},
        "random_calmar_us": float("nan"),
        "trade_count": trades, "max_drawdown": -0.1,
    }


def test_cell_status_separates_no_trades_from_ruined():
    assert rcs.cell_status(_row(float("nan"), 0)) == "no-trades"
    assert rcs.cell_status(_row(float("nan"), 40)) == "RUINED"
    assert rcs.cell_status(_row(0.5, 40)) == "ok"


def test_report_never_prints_a_bare_nan():
    df = _synth_daily(600)
    power = rcs.idata.describe_power(df)
    rows = [_row(float("nan"), 0), _row(float("nan"), 12), _row(0.42, 30)]
    bench = {"calmar_us": 0.3}
    text = rcs.format_report(rows, bench, power, "test")
    assert "nan" not in text.lower()
    assert "RUINED" in text
    assert "no-trades" in text


def test_report_counts_ruined_and_untraded_cells_explicitly():
    df = _synth_daily(600)
    power = rcs.idata.describe_power(df)
    rows = [_row(float("nan"), 0), _row(float("nan"), 12), _row(0.42, 30)]
    text = rcs.format_report(rows, {"calmar_us": 0.3}, power, "test")
    assert "RUINED after-tax curve: 1 / 3" in text
    assert "never traded: 1 / 3" in text


def test_sort_key_puts_finite_calmars_first_then_ruined_then_untraded():
    rows = [_row(float("nan"), 0), _row(float("nan"), 5), _row(-1.0, 5), _row(2.0, 5)]
    ordered = sorted(rows, key=rcs._sort_key)
    assert [rcs.cell_status(r) for r in ordered] == [
        "ok", "ok", "RUINED", "no-trades"
    ]
    assert ordered[0]["metrics"]["calmar_us"] == 2.0


def test_main_exits_2_when_the_data_file_is_missing(tmp_path, capsys):
    rc = rcs.main(["--data", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


def test_main_exits_2_and_prints_no_table_on_an_underpowered_frame(tmp_path, capsys):
    """The load-bearing gate: a shallow frame must yield NO per-cell numbers at all."""
    df = _synth_daily(120)          # far below the 500-session floor
    path = tmp_path / "shallow.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rcs.main(["--data", str(path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UNDERPOWERED" in captured.err
    assert captured.out == ""
    for arm_name, _, _ in rcs.ARMS:
        assert arm_name not in captured.out


def test_main_runs_the_full_grid_on_a_powered_frame(tmp_path, capsys):
    df = _synth_daily(3600)         # ~14 years -> PROMOTABLE
    path = tmp_path / "deep.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rcs.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"N = {rcs.N_CELLS}" in out
    for arm_name, _, _ in rcs.ARMS:
        assert arm_name in out


# ---------------------------------------------------------------------------
# Firing-rate calibration mode
# ---------------------------------------------------------------------------

def test_firing_rates_mode_prints_a_table_and_no_performance_numbers(tmp_path, capsys):
    """The calibration table must carry no Calmar/equity number that could read as a result."""
    df = _synth_daily(900)
    path = tmp_path / "bars.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rcs.main(["--data", str(path), "--firing-rates"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "firing-rate calibration" in out
    for name in cs.PATTERNS:
        assert name in out
    # a calibration run is not a performance run
    assert "CalmarUS" not in out
    assert "clearing the" not in out


def test_firing_rates_mode_is_exempt_from_the_power_gate(tmp_path, capsys):
    """A shallow frame still answers the calibration question — it makes no perf claim.

    The power gate exists to stop underpowered PERFORMANCE numbers escaping. Firing rates
    are a property of the detectors, so gating them would withhold a safe diagnostic.
    """
    df = _synth_daily(120)              # far below the 500-session floor
    path = tmp_path / "shallow.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rcs.main(["--data", str(path), "--firing-rates"])
    out = capsys.readouterr().out
    assert rc == 0                       # NOT 2 — the perf gate does not apply
    assert "firing-rate calibration" in out
    assert "CalmarUS" not in out


def test_firing_rates_mode_still_exits_2_when_data_is_missing(tmp_path, capsys):
    rc = rcs.main(["--data", str(tmp_path / "nope.csv"), "--firing-rates"])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Negative control
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pure_noise_clears_no_cell():
    """Driftless random-walk bars must clear no cell in the frozen grid.

    Without this, a real run returning all-negative numbers is ambiguous between "no edge
    in candlestick patterns" and "the harness is broken". A harness that manufactured edge
    would show it here, where by construction there is none to find.
    """
    df = _synth_daily(3600, seed=2026, drift=0.0)
    rows = rcs.run_grid(df)
    cleared = [
        r for r in rows
        if rcs.cell_status(r) == "ok" and r["metrics"]["calmar_us"] > rcs.SPY_BAR
    ]
    assert cleared == [], f"noise cleared {len(cleared)} cells: {[c['arm'] for c in cleared]}"
