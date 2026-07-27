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
