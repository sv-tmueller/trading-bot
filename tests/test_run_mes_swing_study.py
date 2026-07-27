"""Tests for backtest/run_mes_swing_study.py — the frozen 24-cell MES swing grid (#457 PR A).

Offline / synthetic OHLC only (no network) — the graded criterion for this PR: no real SPY
data is fetched or referenced anywhere in these tests. Live-data reads are PR B's job.

Mirrors the house conventions already established by run_turtle_breakout.py (ATR-bracket
geometry, random-entry twin) and run_candlestick_study.py/run_candlestick_timestop_study.py
(frozen-grid shape, per-cell report, NaN classification, pure-noise negative control).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest.bracket import LONG, SHORT
import backtest.run_candlestick_study as rcs
import backtest.run_mes_swing_study as rms


def _synth_daily(n: int = 900, seed: int = 3, drift: float = 0.0,
                  start: str = "2010-01-01") -> pd.DataFrame:
    """Synthetic daily OHLC random walk (construction copied from the candlestick tests
    so the pure-noise control is directly comparable)."""
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
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": close}, index=idx)


def _trending_daily(n: int, drift: float, start: str = "2010-01-01") -> pd.DataFrame:
    """A steady-drift synthetic series — cheap way to force real signal crossings."""
    return _synth_daily(n, seed=11, drift=drift, start=start)


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

def test_arms_registry_has_12_edge_trigger_arms():
    assert len(rms.ARMS) == 12
    names = {a[0] for a in rms.ARMS}
    assert names == {
        "T1L", "T1S", "T2L", "T2S", "M1L", "M1S",
        "M2L", "M2S", "V1L", "V1S", "V2L", "V2S",
    }


def test_arms_are_mirrored_long_short_pairs():
    directions = {a[0]: a[1] for a in rms.ARMS}
    for base in ("T1", "T2", "M1", "M2", "V1", "V2"):
        assert directions[f"{base}L"] == LONG
        assert directions[f"{base}S"] == SHORT


def test_grid_is_24_cells():
    assert rms.R_GRID == (2.0, 3.0)
    assert rms.N_CELLS == len(rms.ARMS) * len(rms.R_GRID) == 24
    assert rms.CUMULATIVE_N == rms.N_CELLS  # fresh family, round 1: no prior trials


# ---------------------------------------------------------------------------
# Edge-trigger derivation: no re-trigger while the underlying state persists
# ---------------------------------------------------------------------------

def test_edge_trigger_fires_only_on_first_bar_of_a_run():
    cond = pd.Series([False, True, True, True, False, True, False], dtype=bool)
    edge = rms._edge_trigger(cond)
    assert list(edge) == [False, True, False, False, False, True, False]


def test_momentum_arm_does_not_retrigger_while_roc_stays_positive():
    """A long, steady up-drift keeps ROC(63) positive for hundreds of bars in a row —
    the M1L arm must fire once at the crossing, not on every subsequent bar."""
    df = _trending_daily(400, drift=0.004)
    signal = dict((a[0], a[2]) for a in rms.ARMS)["M1L"](df)
    # Once triggered, no two consecutive True bars (a real re-trigger would violate this).
    trues = np.flatnonzero(signal.to_numpy())
    if len(trues) > 1:
        assert np.all(np.diff(trues) > 1)


def test_mean_reversion_arm_does_not_retrigger_while_rsi_stays_extreme():
    """RSI(2) can sit under 10 for several consecutive bars in a sharp selloff — V1L must
    fire only once per excursion below the threshold."""
    df = _synth_daily(500, seed=7, drift=-0.01)  # sharp sustained decline
    signal = dict((a[0], a[2]) for a in rms.ARMS)["V1L"](df)
    trues = np.flatnonzero(signal.to_numpy())
    if len(trues) > 1:
        assert np.all(np.diff(trues) > 1)


def test_trend_arms_are_already_edge_native_no_double_derivation():
    """T1/T2 reuse fx_signals.sma_cross_signal directly — it is already 0 except at the
    exact crossing bar, so no separate edge-trigger derivation runs on top of it."""
    df = _trending_daily(400, drift=0.002)
    signal = dict((a[0], a[2]) for a in rms.ARMS)["T1L"](df)
    trues = np.flatnonzero(signal.to_numpy())
    if len(trues) > 1:
        assert np.all(np.diff(trues) > 1)


# ---------------------------------------------------------------------------
# No look-ahead: build_cell shifts the signal by exactly one bar
# ---------------------------------------------------------------------------

def test_build_cell_enters_the_bar_after_the_signal_bar():
    df = _trending_daily(400, drift=0.003)
    arm = next(a for a in rms.ARMS if a[0] == "T1L")
    signal = arm[2](df)
    sim = rms.build_cell(df, arm, 2.0, commission_bps=0.35)
    signal_bars = set(np.flatnonzero(signal.to_numpy()))
    date_to_pos = {d: i for i, d in enumerate(df.index)}
    for t in sim["trades"]:
        entry_pos = date_to_pos[t["entry_date"]]
        assert (entry_pos - 1) in signal_bars


# ---------------------------------------------------------------------------
# ATR-bracket geometry: turtle convention, mirrored for shorts
# ---------------------------------------------------------------------------

def test_bracket_levels_match_turtle_convention_for_longs():
    df = _trending_daily(300, drift=0.002)
    trigger = pd.Series(False, index=df.index)
    trigger.iloc[150] = True
    stop, target = rms._bracket_levels(df, trigger, r=2.0, direction=LONG, slippage_bps=0.0)

    n_signal = rms._atr(df).shift(1)
    entry_ref = df["Open"]
    expected_stop = (entry_ref - 2.0 * n_signal).iloc[150]
    expected_target = (entry_ref + 2.0 * n_signal).iloc[150]
    assert stop.iloc[150] == pytest.approx(expected_stop)
    assert target.iloc[150] == pytest.approx(expected_target)
    assert np.isnan(stop.iloc[100])  # not the trigger bar -> suppressed


def test_bracket_levels_mirror_for_shorts():
    df = _trending_daily(300, drift=-0.002)
    trigger = pd.Series(False, index=df.index)
    trigger.iloc[150] = True
    stop, target = rms._bracket_levels(df, trigger, r=3.0, direction=SHORT, slippage_bps=0.0)

    n_signal = rms._atr(df).shift(1)
    entry_ref = df["Open"]
    expected_stop = (entry_ref + 2.0 * n_signal).iloc[150]
    expected_target = (entry_ref - 3.0 * n_signal).iloc[150]
    assert stop.iloc[150] == pytest.approx(expected_stop)
    assert target.iloc[150] == pytest.approx(expected_target)


# ---------------------------------------------------------------------------
# Cost model: co-primary presets wire commission_bps = RT/2, slippage 0
# ---------------------------------------------------------------------------

def test_cost_presets_are_the_two_frozen_round_trips():
    labels = dict(rms.COST_PRESETS)
    assert labels["base"] == pytest.approx(0.35)
    assert labels["pessimistic"] == pytest.approx(0.53)
    assert rms.SLIPPAGE_BPS == 0.0


def test_round_trip_haircut_matches_the_frozen_bp_figure():
    """A single flat-price trade's total cost, in bp of notional, must equal the frozen
    round-trip figure (commission-only, since slippage is pinned to 0)."""
    idx = pd.bdate_range("2020-01-01", periods=5)
    price = 100.0
    df = pd.DataFrame(
        {"Open": price, "High": price + 0.01, "Low": price - 0.01, "Close": price},
        index=idx,
    )
    trigger = pd.Series([True, False, False, False, False], index=idx)
    stop = pd.Series([price - 50.0] * 5, index=idx)   # never hit
    target = pd.Series([price + 50.0] * 5, index=idx)  # never hit -> ends at end_of_window

    for label, commission_bps in rms.COST_PRESETS:
        from backtest.bracket import simulate_bracket
        sim = simulate_bracket(
            df, trigger, stop, target,
            starting_cash=100_000.0, slippage_bps=0.0, commission_bps=commission_bps,
            eow_close_out=False, session_close_out=False, direction=LONG,
        )
        assert sim["trade_count"] == 1
        t = sim["trades"][0]
        realized_bp = -(t["pnl"] / (t["qty"] * t["entry_price"])) * 10_000.0
        expected_rt_bp = commission_bps * 2.0
        assert realized_bp == pytest.approx(expected_rt_bp, rel=0.01)


# ---------------------------------------------------------------------------
# Close-outs and time stop are confirmed off
# ---------------------------------------------------------------------------

def test_no_eow_session_or_time_stop_exits():
    df = _trending_daily(700, drift=0.002)
    arm = next(a for a in rms.ARMS if a[0] == "T2L")
    sim = rms.build_cell(df, arm, 3.0, commission_bps=0.35)
    reasons = {t["exit_reason"] for t in sim["trades"]}
    assert reasons <= {"stop", "target", "end_of_window"}


def test_short_arm_actually_runs_the_engine_short_side():
    df = _trending_daily(700, drift=-0.003)
    arm = next(a for a in rms.ARMS if a[0] == "T1S")
    assert arm[1] == SHORT
    sim = rms.build_cell(df, arm, 2.0, commission_bps=0.35)
    # A short profits when price falls; on a down-trend most closed trades should be wins.
    if sim["trade_count"] > 0:
        wins = sum(1 for t in sim["trades"] if t["pnl"] > 0)
        assert wins >= sim["trade_count"] / 2


# ---------------------------------------------------------------------------
# MES_SURVEY_BAR drift-proofing
# ---------------------------------------------------------------------------

def test_mes_survey_bar_equals_the_candlestick_spy_bar():
    assert rms.MES_SURVEY_BAR == rcs.SPY_BAR


# ---------------------------------------------------------------------------
# Random-entry twin: _build_random_cell convention (seed 42, matched count)
# ---------------------------------------------------------------------------

def test_random_cell_matches_entry_count_and_is_seed_reproducible():
    df = _trending_daily(700, drift=0.003)
    arm = next(a for a in rms.ARMS if a[0] == "T2L")
    real = rms.build_cell(df, arm, 2.0, commission_bps=0.35)
    rand_a = rms.build_random_cell(df, arm, 2.0, commission_bps=0.35, seed=42)
    rand_b = rms.build_random_cell(df, arm, 2.0, commission_bps=0.35, seed=42)
    assert rand_a["trade_count"] == rand_b["trade_count"]
    assert rand_a["ending_equity"] == pytest.approx(rand_b["ending_equity"])
    if real["trade_count"] > 0:
        assert rand_a["trade_count"] <= real["trade_count"]


def test_random_seed_default_is_42():
    assert rms.RANDOM_SEED == 42


# ---------------------------------------------------------------------------
# Per-window annual-netting scoring (D3)
# ---------------------------------------------------------------------------

def test_per_window_scores_drops_nan_windows_and_reports_counts():
    """A monotone-declining series never triggers a long arm -> every window is zero-trade
    (NaN Calmar dropped), mirroring run_turtle_breakout._per_window_calmar's own test."""
    idx = pd.bdate_range("2010-01-01", periods=700)
    close = np.linspace(100.0, 50.0, 700)
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) + 0.1
    low = np.minimum(open_, close) - 0.1
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)
    arm = next(a for a in rms.ARMS if a[0] == "T1L")  # long-only trend arm

    def cell_fn(d):
        return rms.build_cell(d, arm, 2.0, commission_bps=0.35)

    scores = rms._per_window_scores(df, cell_fn, rms.PRIMARY_WINDOW_START)
    assert scores["n_windows"] == 0
    assert np.isnan(scores["median_calmar"])
    assert np.isnan(scores["worst_calmar"])


def test_annual_netting_and_deduct_at_exit_diverge_on_a_netting_ledger():
    """Constructed ledger: a loss and a gain closing in the SAME calendar year. Annual
    netting nets them into one taxable event (net_gain = 400 -> tax on 400); deduct-at-exit
    taxes the gain trade alone, with the loss clamped to zero and no netting (tax on the
    full 1000). The two models must produce genuinely different after-tax curves -- pins
    that D3's tax-mode deviation from the candlestick precedent (`apply_tax_to_ledger`) is
    not a no-op."""
    from backtest import tax as tax_mod

    idx = pd.bdate_range("2020-01-01", "2020-03-31")
    equity = pd.Series(100_000.0, index=idx)
    trades = [
        {"entry_date": idx[0], "exit_date": idx[10], "pnl": 1000.0},
        {"entry_date": idx[15], "exit_date": idx[25], "pnl": -600.0},
    ]

    annual = tax_mod.apply_annual_netting_tax(trades, equity)
    deduct = tax_mod.apply_tax_to_ledger(trades, equity, jurisdiction="DE")

    expected_annual_tax = max(1000.0 - 600.0, 0.0) * tax_mod.DE_FLAT_RATE
    expected_deduct_tax = 1000.0 * tax_mod.DE_FLAT_RATE
    assert annual.iloc[-1] == pytest.approx(100_000.0 - expected_annual_tax)
    assert deduct.iloc[-1] == pytest.approx(100_000.0 - expected_deduct_tax)
    assert not annual.equals(deduct)


def test_run_grid_calls_annual_netting_tax(monkeypatch):
    calls = []
    from backtest import tax as tax_mod
    original = tax_mod.apply_annual_netting_tax

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(rms.tax, "apply_annual_netting_tax", spy)
    df = _trending_daily(900, drift=0.003)
    rms.run_grid(df)
    assert len(calls) > 0


# ---------------------------------------------------------------------------
# Primary window set is capped at PRIMARY_WINDOW_END (2025-12-31) -- a trailing partial
# year must never enter the verdict-bearing median/worst (round-1 review finding 2)
# ---------------------------------------------------------------------------

def test_primary_window_end_is_frozen_at_2025_12_31():
    assert rms.PRIMARY_WINDOW_END == date(2025, 12, 31)


def test_primary_window_set_excludes_a_trailing_partial_year():
    """A frame spanning ~2011 through mid-2026 must yield exactly the 13 full calendar-year
    windows (2013-2025) in the primary set, none with te past PRIMARY_WINDOW_END -- the
    partial 2026 window belongs only to the uncapped era read."""
    idx = pd.bdate_range("2011-01-01", "2026-06-30")
    df = _synth_daily(n=len(idx), seed=21, start="2011-01-01")

    windows = rms._primary_windows(df, rms.PRIMARY_WINDOW_START, rms.PRIMARY_WINDOW_END)
    assert len(windows) == 13
    cutoff = pd.Timestamp(rms.PRIMARY_WINDOW_END)
    assert all(te <= cutoff for _, _, te in windows)

    def cell_fn(d):
        return rms.always_in(d, commission_bps=0.35)

    primary = rms._per_window_scores(df, cell_fn, rms.PRIMARY_WINDOW_START, rms.PRIMARY_WINDOW_END)
    assert primary["n_windows"] == 13

    era = rms._per_window_scores(df, cell_fn, rms.PRIMARY_WINDOW_START)
    assert era["n_windows"] > primary["n_windows"]


def test_run_grid_primary_scoring_is_capped_on_a_frame_reaching_into_2026():
    """run_grid's own primary column must reflect the capped window set, not the raw
    (uncapped) one, on a frame that extends past PRIMARY_WINDOW_END."""
    idx = pd.bdate_range("2011-01-01", "2026-06-30")
    df = _synth_daily(n=len(idx), seed=23, drift=0.0003, start="2011-01-01")
    rows = rms.run_grid(df)
    for row in rows:
        for label, _ in rms.COST_PRESETS:
            p = row["presets"][label]
            assert p["n_windows"] <= 13


# ---------------------------------------------------------------------------
# Grid runner shape + report
# ---------------------------------------------------------------------------

def test_run_grid_returns_one_row_per_frozen_cell():
    df = _synth_daily(900, seed=5)
    rows = rms.run_grid(df)
    assert len(rows) == rms.N_CELLS
    assert {(r["arm"], r["r"]) for r in rows} == {
        (a[0], r) for a in rms.ARMS for r in rms.R_GRID
    }


def test_every_row_carries_both_cost_presets():
    df = _synth_daily(900, seed=5)
    rows = rms.run_grid(df)
    for row in rows:
        assert set(row["presets"].keys()) == {"base", "pessimistic"}
        assert "clears_both" in row


def _stub_preset(**overrides) -> dict:
    base = {
        "median_calmar": float("nan"), "worst_calmar": float("nan"),
        "n_windows": 0, "n_positive": 0, "clears": False,
        "era_median_calmar": float("nan"), "era_worst_calmar": float("nan"),
        "era_n_windows": 0, "full_calmar_us": float("nan"),
        "full_calmar_de": float("nan"), "random_median_calmar": float("nan"),
        "trade_count": 0,
    }
    base.update(overrides)
    return base


def _stub_benchmark() -> dict:
    return {
        "base": {
            "median_calmar": float("nan"), "worst_calmar": float("nan"),
            "n_windows": 0, "n_positive": 0,
            "era_median_calmar": float("nan"), "era_worst_calmar": float("nan"),
            "era_n_windows": 0, "full_calmar_us": float("nan"),
            "full_calmar_de": float("nan"), "trade_count": 0,
        },
        "pessimistic": {
            "median_calmar": float("nan"), "worst_calmar": float("nan"),
            "n_windows": 0, "n_positive": 0,
            "era_median_calmar": float("nan"), "era_worst_calmar": float("nan"),
            "era_n_windows": 0, "full_calmar_us": float("nan"),
            "full_calmar_de": float("nan"), "trade_count": 0,
        },
    }


def test_report_prints_both_this_grid_and_cumulative_N_lines():
    df = _synth_daily(900, seed=5)
    power = rms.idata.describe_power(df)
    rows = rms.run_grid(df)
    benchmark = rms.compute_benchmark(df)
    text = rms.format_report(rows, power, "test", benchmark)
    assert f"this grid N = {rms.N_CELLS}" in text
    assert f"cumulative family N = {rms.CUMULATIVE_N}" in text


def test_report_prints_all_24_cells_at_both_presets_with_no_truncation():
    df = _synth_daily(900, seed=5)
    power = rms.idata.describe_power(df)
    rows = rms.run_grid(df)
    benchmark = rms.compute_benchmark(df)
    text = rms.format_report(rows, power, "test", benchmark)
    for arm in rms.ARMS:
        assert text.count(arm[0]) >= 2  # appears in at least both preset tables
    assert "base" in text and "pessimistic" in text
    assert text.count("cells clearing at") == 3  # base, pessimistic, BOTH


def test_report_prints_the_bar_at_full_precision():
    df = _synth_daily(900, seed=5)
    power = rms.idata.describe_power(df)
    rows = rms.run_grid(df)
    benchmark = rms.compute_benchmark(df)
    text = rms.format_report(rows, power, "test", benchmark)
    assert "1.3085475049604838" in text


def test_report_never_prints_a_bare_nan():
    power_stub = rms.idata.describe_power(_synth_daily(600))
    rows = [{
        "arm": "T1L", "direction": LONG, "r": 2.0,
        "presets": {
            "base": _stub_preset(),
            "pessimistic": _stub_preset(),
        },
        "clears_both": False,
    }]
    text = rms.format_report(rows, power_stub, "test", _stub_benchmark())
    assert "nan" not in text.lower()


def test_report_never_prints_a_bare_nan_for_the_no_scored_windows_case():
    """A cell that traded but had every window dropped (n_windows == 0, trade_count > 0)
    must be labeled distinctly from a genuine ruin and never print a bare NaN."""
    power_stub = rms.idata.describe_power(_synth_daily(600))
    rows = [{
        "arm": "T1L", "direction": LONG, "r": 2.0,
        "presets": {
            "base": _stub_preset(trade_count=3),
            "pessimistic": _stub_preset(trade_count=3),
        },
        "clears_both": False,
    }]
    text = rms.format_report(rows, power_stub, "test", _stub_benchmark())
    assert "nan" not in text.lower()
    assert "no-scored-windows" in text


# ---------------------------------------------------------------------------
# always_in benchmark row (round-1 review finding 3): scored through the same D3 pipeline
# on the primary window set, at both presets, printed so stopping-rule condition 3 is
# adjudicable from the report alone.
# ---------------------------------------------------------------------------

def test_compute_benchmark_scores_always_in_on_the_primary_window_set():
    df = _synth_daily(900, seed=5, drift=0.0002)
    benchmark = rms.compute_benchmark(df)
    assert set(benchmark.keys()) == {"base", "pessimistic"}
    for label in ("base", "pessimistic"):
        b = benchmark[label]
        assert b["trade_count"] > 0  # always_in always has exactly one open trade
        for key in (
            "median_calmar", "worst_calmar", "n_windows", "n_positive",
            "era_median_calmar", "era_worst_calmar", "era_n_windows",
            "full_calmar_us", "full_calmar_de",
        ):
            assert key in b


def test_report_prints_the_always_in_benchmark_row_at_both_presets():
    df = _synth_daily(900, seed=5, drift=0.0002)
    power = rms.idata.describe_power(df)
    rows = rms.run_grid(df)
    benchmark = rms.compute_benchmark(df)
    text = rms.format_report(rows, power, "test", benchmark)
    assert text.count("ALWAYS_IN") >= 2  # at least one appearance per preset table


# ---------------------------------------------------------------------------
# D3 secondary columns (round-1 review finding 4): era_median_calmar, era_worst_calmar,
# era_n_windows, full_calmar_us, full_calmar_de, n_positive must be printed for every cell
# (and the benchmark), never as a bare NaN.
# ---------------------------------------------------------------------------

def test_report_prints_the_d3_secondary_columns_for_every_cell():
    df = _synth_daily(900, seed=5, drift=0.0002)
    power = rms.idata.describe_power(df)
    rows = rms.run_grid(df)
    benchmark = rms.compute_benchmark(df)
    text = rms.format_report(rows, power, "test", benchmark)
    assert "era_med" in text or "era_median" in text
    assert "full_us" in text or "full_calmar_us" in text
    assert "full_de" in text or "full_calmar_de" in text
    for arm in rms.ARMS:
        assert text.count(arm[0]) >= 3  # both primary tables + the secondary table(s)


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

def test_main_exits_2_when_the_data_file_is_missing(tmp_path, capsys):
    rc = rms.main(["--data", str(tmp_path / "nope.csv")])
    assert rc == 2
    assert "DATA-BLOCKED" in capsys.readouterr().err


def test_main_exits_2_and_prints_no_table_on_an_underpowered_frame(tmp_path, capsys):
    df = _synth_daily(120)
    path = tmp_path / "shallow.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rms.main(["--data", str(path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UNDERPOWERED" in captured.err
    assert captured.out == ""
    for arm in rms.ARMS:
        assert arm[0] not in captured.err


def test_main_runs_the_full_grid_on_a_powered_frame(tmp_path, capsys):
    df = _synth_daily(3600, seed=13, drift=0.0004)
    path = tmp_path / "deep.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)

    rc = rms.main(["--data", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"cumulative family N = {rms.CUMULATIVE_N}" in out


# ---------------------------------------------------------------------------
# Negative control (pure-noise grid, both presets)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pure_noise_clears_no_cell_at_either_preset():
    """Driftless random-walk daily OHLC must clear no cell at either cost preset.

    Construction copied unchanged from the candlestick/turtle precedent
    (``_synth_daily(3600, seed=2026, drift=0.0)``) so the control is directly comparable.
    """
    df = _synth_daily(3600, seed=2026, drift=0.0)
    rows = rms.run_grid(df)
    assert len(rows) == rms.N_CELLS
    for row in rows:
        for label, _ in rms.COST_PRESETS:
            assert not row["presets"][label]["clears"], (
                f"{row['arm']}/R{row['r']}/{label} cleared on pure noise"
            )
    assert not any(row["clears_both"] for row in rows)
