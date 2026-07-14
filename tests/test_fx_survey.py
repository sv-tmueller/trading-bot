"""Tests for backtest/fx_survey.py -- composition library for the pre-
registered FX signal survey (#376). All offline: no network, no cache
access -- ``fx_data.get_week_bytes``/``read_cache`` are never touched by any
test in this file except via explicit monkeypatch of the network seam.
"""
from __future__ import annotations

import gzip

import numpy as np
import pandas as pd
import pytest

from backtest import fx_survey


# ---------------------------------------------------------------------------
# prepare_history -- load -> validate/BLOCKED gate -> Saturday carve-out ->
# resample -> drop in-progress bar (SUB_PLAN §4)
# ---------------------------------------------------------------------------

_HEADER = "DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose"


def _make_csv_gzip(rows: list) -> bytes:
    text = _HEADER + "\n" + "\n".join(rows) + "\n"
    return gzip.compress(text.encode("utf-8"))


def _row(dt: str, bo, bh, bl, bc, ao, ah, al, ac) -> str:
    return f"{dt},{bo},{bh},{bl},{bc},{ao},{ah},{al},{ac}"


def _week_of_hourly_rows(start: str, n: int = 24) -> list:
    """n contiguous hourly rows starting at `start` (MM/DD/YYYY HH:MM:SS.000)."""
    idx = pd.date_range(start, periods=n, freq="1h")
    rows = []
    for ts in idx:
        dt = ts.strftime("%m/%d/%Y %H:%M:%S.000")
        rows.append(_row(dt, 1.10, 1.11, 1.09, 1.105, 1.101, 1.111, 1.091, 1.106))
    return rows


def test_prepare_history_offline_pipeline_order(monkeypatch):
    """Cache-hit path only (no network): one cached week of clean data, one
    Saturday-stamped row injected to prove the carve-out actually runs."""
    from backtest import fx_data

    # Week starting Sunday 2023-01-29 22:00 UTC (a normal FX week open) plus
    # one deliberately Saturday-stamped extra row (2023-02-04 is a Saturday).
    rows = _week_of_hourly_rows("2023-01-29 22:00", n=20)
    rows.append(_row("02/04/2023 12:00:00.000", 1.10, 1.11, 1.09, 1.105, 1.101, 1.111, 1.091, 1.106))
    raw = _make_csv_gzip(rows)

    def fake_read_cache(year, week, *, root=fx_data.CACHE_ROOT):
        if year == 2023 and week == 5:
            return raw
        return None

    def fake_get_week_bytes(year, week, *, fetch=False, root=fx_data.CACHE_ROOT):
        cached = fake_read_cache(year, week, root=root)
        if cached is not None:
            return cached
        raise FileNotFoundError("no cached data (offline test)")

    monkeypatch.setattr(fx_data, "read_cache", fake_read_cache)
    monkeypatch.setattr(fx_data, "get_week_bytes", fake_get_week_bytes)

    result = fx_survey.prepare_history(fetch=False, start_year=2023, end_year=2023)

    assert result["n_saturday_dropped"] == 1
    bars_4h = result["bars_4h"]
    assert len(bars_4h) > 0
    # No Saturday-UTC bars survive resampling.
    assert (bars_4h.index.dayofweek == 5).sum() == 0
    # The in-progress final bar was dropped (bars_4h shorter than the raw resample).
    assert result["resample_report"]["n_bars"] > len(bars_4h)


def test_prepare_history_blocked_on_no_cached_data(monkeypatch):
    from backtest import fx_data

    monkeypatch.setattr(fx_data, "read_cache", lambda year, week, **kw: None)

    def fake_get_week_bytes(year, week, *, fetch=False, root=fx_data.CACHE_ROOT):
        raise FileNotFoundError("no cached data (offline test)")

    monkeypatch.setattr(fx_data, "get_week_bytes", fake_get_week_bytes)

    with pytest.raises(SystemExit, match="BLOCKED"):
        fx_survey.prepare_history(fetch=False, start_year=2023, end_year=2023)


# ---------------------------------------------------------------------------
# slice_calendar_year_windows (spec §5)
# ---------------------------------------------------------------------------

def _make_4h_index(start: str, end: str) -> pd.DatetimeIndex:
    idx = pd.date_range(start, end, freq="4h", tz="UTC")
    idx.name = "datetime_utc"
    return idx


def test_slice_calendar_year_windows_jan1_utc_boundaries():
    idx = _make_4h_index("2012-06-01", "2014-06-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    w2013 = next(w for w in windows if w["year"] == 2013)
    assert w2013["test_start"] == pd.Timestamp("2013-01-01", tz="UTC")
    assert w2013["test_end"] == pd.Timestamp("2014-01-01", tz="UTC")


def test_slice_calendar_year_windows_exactly_300_bar_positional_pre_roll():
    idx = _make_4h_index("2012-01-01", "2014-06-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    w2013 = next(w for w in windows if w["year"] == 2013)
    ts_pos = idx.searchsorted(w2013["test_start"], side="left")
    expected_pre_roll_start = idx[max(0, ts_pos - 300)]
    assert w2013["pre_roll_start"] == expected_pre_roll_start


def test_slice_calendar_year_windows_2012_never_appears_as_a_window():
    idx = _make_4h_index("2012-01-01", "2014-06-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    years = [w["year"] for w in windows]
    assert 2012 not in years
    assert 2013 in years


def test_slice_calendar_year_windows_2026_excluded_from_scoring():
    idx = _make_4h_index("2012-01-01", "2026-05-01")
    windows = fx_survey.slice_calendar_year_windows(
        idx, first_test_year=2013, pre_roll_bars=300, excluded_years=(2026,)
    )
    scored_years = [w["year"] for w in windows if w["scored"]]
    unscored_years = [w["year"] for w in windows if not w["scored"]]
    assert 2026 in unscored_years
    assert 2026 not in scored_years
    assert scored_years == list(range(2013, 2026))
    assert len(scored_years) == 13


def test_slice_calendar_year_windows_stops_when_data_runs_out():
    idx = _make_4h_index("2012-01-01", "2015-01-01")
    windows = fx_survey.slice_calendar_year_windows(idx, first_test_year=2013, pre_roll_bars=300)
    years = [w["year"] for w in windows]
    assert max(years) <= 2015
    assert all(y >= 2013 for y in years)


# ---------------------------------------------------------------------------
# compute_window_metrics -- √260 Sharpe, CAGR, Calmar NaN-on-no-drawdown,
# win rate, trade count (spec §5; SUB_PLAN §6)
# ---------------------------------------------------------------------------

def _daily_eq(values: list) -> pd.Series:
    idx = pd.date_range("2013-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_compute_window_metrics_hand_computed():
    """eq = [100000, 110000, 99000] over 2 calendar days -- every figure
    independently computed via the pinned formulas (not the implementation
    under test): total_return, maxDD, CAGR (calendar-span/365.25), Calmar =
    CAGR/|maxDD|, Sharpe/vol on daily pct_change with ddof=1, √260."""
    eq = _daily_eq([100000.0, 110000.0, 99000.0])
    trades = [{"pnl": 100.0}, {"pnl": -50.0}, {"pnl": 200.0}]
    m = fx_survey.compute_window_metrics(eq, trades)

    assert m["total_return"] == pytest.approx(-0.01)
    assert m["max_drawdown"] == pytest.approx(-0.1)
    assert m["cagr"] == pytest.approx(-0.8404571251824035)
    assert m["calmar"] == pytest.approx(-8.404571251824034)
    assert m["sharpe"] == pytest.approx(0.0, abs=1e-10)
    assert m["annualized_vol"] == pytest.approx(2.2803508501982765)
    assert m["trade_count"] == 3
    assert m["win_rate"] == pytest.approx(2 / 3)


def test_compute_window_metrics_calmar_nan_when_no_drawdown():
    eq = _daily_eq([100000.0, 110000.0, 120000.0])  # monotonic up -> maxDD == 0
    m = fx_survey.compute_window_metrics(eq, [])
    assert m["max_drawdown"] == 0.0
    assert pd.isna(m["calmar"])


def test_compute_window_metrics_win_rate_nan_when_zero_trades():
    eq = _daily_eq([100000.0, 100500.0])
    m = fx_survey.compute_window_metrics(eq, [])
    assert m["trade_count"] == 0
    assert pd.isna(m["win_rate"])


def test_compute_window_metrics_sharpe_uses_sqrt_260_not_252_or_365():
    """Discriminating check: sqrt(260) != sqrt(252) != sqrt(365) by enough
    margin that a wrong annualization constant would fail this assertion."""
    import numpy as np
    eq = _daily_eq([100000.0, 101000.0, 99500.0, 102000.0, 100500.0])
    m = fx_survey.compute_window_metrics(eq, [])
    daily_rets = eq.pct_change().dropna()
    mean_r, std_r = daily_rets.mean(), daily_rets.std(ddof=1)
    expected_sharpe_260 = mean_r / std_r * (260 ** 0.5)
    expected_sharpe_252 = mean_r / std_r * (252 ** 0.5)
    assert m["sharpe"] == pytest.approx(expected_sharpe_260)
    assert m["sharpe"] != pytest.approx(expected_sharpe_252)


# ---------------------------------------------------------------------------
# Both tax modes wired (spec §5: German annual-netting PRIMARY,
# no-loss-credit ledger model sensitivity-only)
# ---------------------------------------------------------------------------

def test_compute_after_tax_metrics_annual_netting_mode():
    eq = _daily_eq([100000.0, 100000.0, 130000.0])
    trades = [{
        "entry_date": eq.index[0], "exit_date": eq.index[2], "pnl": 30000.0,
    }]
    m = fx_survey.compute_after_tax_metrics(eq, trades, mode="annual_netting")
    # 30000 * 26.375% = 7912.5 tax deducted at the exit date -> after-tax
    # equity at that point = 130000 - 7912.5 = 122087.5
    assert m["total_return"] == pytest.approx(122087.5 / 100000.0 - 1.0)


def test_compute_after_tax_metrics_de_sensitivity_mode():
    eq = _daily_eq([100000.0, 100000.0, 130000.0])
    trades = [{
        "entry_date": eq.index[0], "exit_date": eq.index[2], "pnl": 30000.0,
    }]
    m = fx_survey.compute_after_tax_metrics(eq, trades, mode="de_sensitivity")
    assert m["total_return"] == pytest.approx(122087.5 / 100000.0 - 1.0)


def test_compute_after_tax_metrics_unknown_mode_raises():
    eq = _daily_eq([100000.0, 100500.0])
    with pytest.raises(ValueError):
        fx_survey.compute_after_tax_metrics(eq, [], mode="bogus")


# ---------------------------------------------------------------------------
# Cost matrix + FXCM-spread reconciliation row (spec §5; SUB_PLAN §3 pin f)
# ---------------------------------------------------------------------------

def test_cost_rows_has_nine_rows_four_venues_times_two_plus_reconciliation():
    rows = fx_survey.cost_rows(measured_spread_pips=0.6)
    assert len(rows) == 9
    reconciliation = [r for r in rows if r["cost_mode"] == "reconciliation"]
    assert len(reconciliation) == 1


def test_cost_rows_co_primary_flags_xtb_base_and_6e_base_only():
    rows = fx_survey.cost_rows(measured_spread_pips=0.6)
    co_primary = {(r["venue_key"], r["cost_mode"]) for r in rows if r["is_co_primary"]}
    assert co_primary == {("xtb", "base"), ("6e", "base")}


def test_cost_rows_without_reconciliation_arg_has_eight_rows():
    rows = fx_survey.cost_rows()
    assert len(rows) == 8


def test_reconciliation_cost_rt_formula():
    # 0.6 pip spread on EURUSD (1 pip = 0.0001), ref price 1.10:
    # cost_rt = 0.6 * 0.0001 / 1.10
    expected = 0.6 * 0.0001 / 1.10
    assert fx_survey.reconciliation_cost_rt(0.6, ref_price=1.10) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# aggregate_metric_across_windows -- median/worst + NaN-Calmar handling
# ---------------------------------------------------------------------------

def test_aggregate_median_and_worst_window():
    window_metrics = [
        {"year": 2013, "total_return": 0.10, "calmar": 2.0},
        {"year": 2014, "total_return": -0.05, "calmar": 1.0},
        {"year": 2015, "total_return": 0.20, "calmar": 3.0},
    ]
    agg = fx_survey.aggregate_metric_across_windows(window_metrics)
    assert agg["median_calmar"] == pytest.approx(2.0)
    assert agg["median_total_return"] == pytest.approx(0.10)
    assert agg["worst_window_total_return"] == pytest.approx(-0.05)
    assert agg["worst_window_label"] == 2014
    assert agg["n_windows"] == 3
    assert agg["n_nan_calmar_windows"] == 0


def test_aggregate_skips_nan_calmar_from_median_but_counts_it():
    window_metrics = [
        {"year": 2013, "total_return": 0.10, "calmar": float("nan")},
        {"year": 2014, "total_return": 0.05, "calmar": 1.0},
        {"year": 2015, "total_return": 0.20, "calmar": 3.0},
    ]
    agg = fx_survey.aggregate_metric_across_windows(window_metrics)
    assert agg["n_nan_calmar_windows"] == 1
    assert agg["median_calmar"] == pytest.approx(2.0)  # median of [1.0, 3.0]
    assert agg["n_windows"] == 3


def test_aggregate_all_nan_calmar_median_is_nan():
    window_metrics = [
        {"year": 2013, "total_return": 0.10, "calmar": float("nan")},
        {"year": 2014, "total_return": 0.05, "calmar": float("nan")},
    ]
    agg = fx_survey.aggregate_metric_across_windows(window_metrics)
    assert agg["n_nan_calmar_windows"] == 2
    assert pd.isna(agg["median_calmar"])


# ---------------------------------------------------------------------------
# Baseline-4 degenerate-window convention (spec §6)
# ---------------------------------------------------------------------------

def test_baseline4_degenerate_window_return_and_calmar_set_to_zero():
    window_metrics = [
        {"year": 2013, "total_return": 0.10, "calmar": 2.0, "trade_count": 3},
        {"year": 2014, "total_return": 0.0, "calmar": float("nan"), "trade_count": 0},  # flat all window
    ]
    adjusted = fx_survey.apply_baseline4_degenerate_convention(window_metrics)
    assert adjusted[0]["total_return"] == pytest.approx(0.10)
    assert adjusted[0]["calmar"] == pytest.approx(2.0)
    assert adjusted[1]["total_return"] == pytest.approx(0.0)
    assert adjusted[1]["calmar"] == pytest.approx(0.0)  # NOT NaN -- the pinned convention


def test_baseline4_degenerate_convention_does_not_mutate_input():
    window_metrics = [{"year": 2013, "total_return": 0.0, "calmar": float("nan"), "trade_count": 0}]
    fx_survey.apply_baseline4_degenerate_convention(window_metrics)
    assert pd.isna(window_metrics[0]["calmar"])  # original untouched


# ---------------------------------------------------------------------------
# SPY bar -- SPY buy-and-hold after-tax Calmar on the same calendar windows
# (spec §5 "the bar", inherited from #255 §2/§5). Smoke-only execution
# (lead decision ND2); truth-table/offline-tested here via a patched _fetch.
# ---------------------------------------------------------------------------

def _synthetic_spy_frame(start: str, n: int, daily_return: float = 0.0005) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="B")
    closes = 400.0 * (1.0 + daily_return) ** np.arange(n)
    return pd.DataFrame({"Open": closes * 0.999, "Close": closes}, index=idx)


def test_compute_spy_windows_uses_patched_fetch_and_returns_per_window_metrics(monkeypatch):
    calendar_windows = [
        {
            "year": 2013, "scored": True,
            "pre_roll_start": pd.Timestamp("2012-11-01"),
            "test_start": pd.Timestamp("2013-01-01"),
            "test_end": pd.Timestamp("2014-01-01"),
        },
        {
            "year": 2014, "scored": True,
            "pre_roll_start": pd.Timestamp("2013-11-01"),
            "test_start": pd.Timestamp("2014-01-01"),
            "test_end": pd.Timestamp("2015-01-01"),
        },
    ]
    full_frame = _synthetic_spy_frame("2012-11-01", n=600)

    calls = []

    def fake_fetch(ticker, start, end):
        calls.append((ticker, start, end))
        return full_frame

    rows = fx_survey.compute_spy_windows(calendar_windows=calendar_windows, fetch=fake_fetch)

    assert len(calls) == 1  # fetched ONCE for the whole span, not per-window
    assert calls[0][0] == "SPY"
    assert len(rows) == 2
    assert {r["year"] for r in rows} == {2013, 2014}
    for r in rows:
        assert "total_return" in r
        assert "calmar" in r


def test_compute_spy_windows_empty_input_returns_empty_list():
    assert fx_survey.compute_spy_windows(calendar_windows=[], fetch=lambda *a: None) == []


# ---------------------------------------------------------------------------
# §6 survivor evaluator -- truth table (spec §6)
# ---------------------------------------------------------------------------

_CO_PRIMARY = ("xtb_base", "6e_base")


def _agg(median_calmar, median_total_return, worst_window_total_return):
    return {
        "median_calmar": median_calmar,
        "median_total_return": median_total_return,
        "worst_window_total_return": worst_window_total_return,
    }


def _passing_cell_and_baselines():
    cell_agg = {v: _agg(2.0, 0.05, 0.02) for v in _CO_PRIMARY}
    baseline_aggs = {
        "buy_and_hold": {v: _agg(0.5, 0.01, -0.05) for v in _CO_PRIMARY},
        "persistence": {v: _agg(0.3, -0.01, -0.10) for v in _CO_PRIMARY},
        "sma200_regime": {v: _agg(0.8, 0.02, -0.03) for v in _CO_PRIMARY},
    }
    spy_median_calmar = 1.0
    return cell_agg, baseline_aggs, spy_median_calmar


def test_survivor_all_conditions_pass():
    cell_agg, baseline_aggs, spy_calmar = _passing_cell_and_baselines()
    result = fx_survey.evaluate_survivor(
        cell_agg=cell_agg, baseline_aggs=baseline_aggs, spy_median_calmar=spy_calmar,
    )
    assert result["condition_1"] is True
    assert result["condition_2"] is True
    assert result["condition_3"] is True
    assert result["is_survivor"] is True


def test_survivor_fails_condition_1_when_not_beating_spy_at_one_venue():
    cell_agg, baseline_aggs, spy_calmar = _passing_cell_and_baselines()
    cell_agg["6e_base"]["median_calmar"] = 0.5  # below SPY's 1.0
    result = fx_survey.evaluate_survivor(
        cell_agg=cell_agg, baseline_aggs=baseline_aggs, spy_median_calmar=spy_calmar,
    )
    assert result["condition_1"] is False
    assert result["is_survivor"] is False


def test_survivor_fails_condition_2_always_flat_median_return_not_positive():
    cell_agg, baseline_aggs, spy_calmar = _passing_cell_and_baselines()
    cell_agg["xtb_base"]["median_total_return"] = -0.01
    result = fx_survey.evaluate_survivor(
        cell_agg=cell_agg, baseline_aggs=baseline_aggs, spy_median_calmar=spy_calmar,
    )
    assert result["condition_2"] is False
    assert result["is_survivor"] is False


def test_survivor_fails_condition_2_does_not_beat_a_baseline():
    cell_agg, baseline_aggs, spy_calmar = _passing_cell_and_baselines()
    baseline_aggs["persistence"]["6e_base"]["median_calmar"] = 5.0  # now beats the cell
    result = fx_survey.evaluate_survivor(
        cell_agg=cell_agg, baseline_aggs=baseline_aggs, spy_median_calmar=spy_calmar,
    )
    assert result["condition_2"] is False
    assert result["is_survivor"] is False


def test_survivor_fails_condition_3_negative_worst_window():
    cell_agg, baseline_aggs, spy_calmar = _passing_cell_and_baselines()
    cell_agg["xtb_base"]["worst_window_total_return"] = -0.001
    result = fx_survey.evaluate_survivor(
        cell_agg=cell_agg, baseline_aggs=baseline_aggs, spy_median_calmar=spy_calmar,
    )
    assert result["condition_3"] is False
    assert result["is_survivor"] is False


def test_survivor_nan_median_calmar_fails_condition_1_deterministically():
    cell_agg, baseline_aggs, spy_calmar = _passing_cell_and_baselines()
    cell_agg["xtb_base"]["median_calmar"] = float("nan")
    result = fx_survey.evaluate_survivor(
        cell_agg=cell_agg, baseline_aggs=baseline_aggs, spy_median_calmar=spy_calmar,
    )
    assert result["condition_1"] is False
    assert result["is_survivor"] is False


def test_family_kill_true_when_no_cell_in_family_survives():
    results = {
        "T1_sma_5_20_R20": {"is_survivor": False},
        "T1_sma_5_20_R30": {"is_survivor": False},
    }
    assert fx_survey.family_kill(results, list(results.keys())) is True


def test_family_kill_false_when_one_cell_survives():
    results = {
        "T1_sma_5_20_R20": {"is_survivor": False},
        "T1_sma_5_20_R30": {"is_survivor": True},
    }
    assert fx_survey.family_kill(results, list(results.keys())) is False


def test_class_kill_false_when_any_survivor_exists():
    results = {"cell_a": {"is_survivor": True, "condition_1": True, "condition_2": True, "condition_3": True}}
    out = fx_survey.class_kill(results)
    assert out["class_dead"] is False
    assert out["reason"] is None


def test_class_kill_pattern_a_no_cell_clears_median():
    results = {
        "cell_a": {"is_survivor": False, "condition_1": False, "condition_2": True, "condition_3": True},
        "cell_b": {"is_survivor": False, "condition_1": True, "condition_2": False, "condition_3": True},
    }
    out = fx_survey.class_kill(results)
    assert out["class_dead"] is True
    assert out["reason"] == "a_no_cell_clears_median"


def test_class_kill_pattern_b_clears_median_but_never_survives_worst_window():
    results = {
        "cell_a": {"is_survivor": False, "condition_1": True, "condition_2": True, "condition_3": False},
        "cell_b": {"is_survivor": False, "condition_1": True, "condition_2": True, "condition_3": False},
    }
    out = fx_survey.class_kill(results)
    assert out["class_dead"] is True
    assert out["reason"] == "b_never_survives_worst_window"
