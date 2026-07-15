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
    # Duplicate-timestamp count is reported, not silently computed and discarded.
    assert result["n_duplicates"] == 0


def test_prepare_history_blocked_on_no_cached_data(monkeypatch):
    from backtest import fx_data

    monkeypatch.setattr(fx_data, "read_cache", lambda year, week, **kw: None)

    def fake_get_week_bytes(year, week, *, fetch=False, root=fx_data.CACHE_ROOT):
        raise FileNotFoundError("no cached data (offline test)")

    monkeypatch.setattr(fx_data, "get_week_bytes", fake_get_week_bytes)

    with pytest.raises(SystemExit, match="BLOCKED"):
        fx_survey.prepare_history(fetch=False, start_year=2023, end_year=2023)


def _patch_clean_offline_cache(monkeypatch):
    """One cached week of clean H1 data (no Saturday rows, no threshold
    crossings) -- lets prepare_history run its real pipeline up to the
    BLOCKED gate, whose decision (``evaluate_blocked_reasons``'s return
    value) individual tests then monkeypatch to exercise the ND-A
    adjudicated-reasons whitelist in isolation."""
    from backtest import fx_data

    raw = _make_csv_gzip(_week_of_hourly_rows("2023-01-29 22:00", n=20))

    def fake_read_cache(year, week, *, root=fx_data.CACHE_ROOT):
        return raw if (year, week) == (2023, 5) else None

    def fake_get_week_bytes(year, week, *, fetch=False, root=fx_data.CACHE_ROOT):
        cached = fake_read_cache(year, week, root=root)
        if cached is not None:
            return cached
        raise FileNotFoundError("no cached data (offline test)")

    monkeypatch.setattr(fx_data, "read_cache", fake_read_cache)
    monkeypatch.setattr(fx_data, "get_week_bytes", fake_get_week_bytes)


# ---------------------------------------------------------------------------
# ND-A (lead decision, batch #378): prepare_history's strictly-additive,
# keyword-only adjudicated_reasons whitelist. Exact (label, reason) matches
# against the #374-adjudicated crossings are collected into the returned
# dict's "adjudicated_crossings" instead of raising; any unmatched reason
# still BLOCKs. Default () = behavior byte-identical.
# ---------------------------------------------------------------------------

def test_prepare_history_default_adjudicated_reasons_still_blocks(monkeypatch):
    from backtest import run_fx_plumbing_check

    _patch_clean_offline_cache(monkeypatch)
    monkeypatch.setattr(
        run_fx_plumbing_check, "evaluate_blocked_reasons",
        lambda *a, **kw: [(2024, "missing weeks 7.55% > 2.00%")],
    )
    with pytest.raises(SystemExit, match="BLOCKED"):
        fx_survey.prepare_history(fetch=False, start_year=2023, end_year=2023)


def test_prepare_history_adjudicated_reasons_matched_are_collected_not_raised(monkeypatch):
    from backtest import run_fx_plumbing_check

    _patch_clean_offline_cache(monkeypatch)
    crossings = (
        (2024, "missing weeks 7.55% > 2.00%"),
        (2025, "missing weeks 7.55% > 2.00%"),
        ("all", "crossed-quotes rate 2.3791% > 0.100%"),
    )
    monkeypatch.setattr(
        run_fx_plumbing_check, "evaluate_blocked_reasons",
        lambda *a, **kw: list(crossings),
    )
    result = fx_survey.prepare_history(
        fetch=False, start_year=2023, end_year=2023, adjudicated_reasons=crossings,
    )
    assert result["adjudicated_crossings"] == list(crossings)
    assert len(result["bars_4h"]) > 0  # the pipeline actually ran to completion


def test_prepare_history_one_unmatched_reason_still_blocks_even_when_others_match(monkeypatch):
    from backtest import run_fx_plumbing_check

    _patch_clean_offline_cache(monkeypatch)
    adjudicated = (
        (2024, "missing weeks 7.55% > 2.00%"),
        (2025, "missing weeks 7.55% > 2.00%"),
        ("all", "crossed-quotes rate 2.3791% > 0.100%"),
    )
    monkeypatch.setattr(
        run_fx_plumbing_check, "evaluate_blocked_reasons",
        lambda *a, **kw: list(adjudicated) + [(2023, "missing weeks 99.00% > 2.00%")],
    )
    with pytest.raises(SystemExit, match="BLOCKED"):
        fx_survey.prepare_history(
            fetch=False, start_year=2023, end_year=2023, adjudicated_reasons=adjudicated,
        )


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


def test_aggregate_computes_median_for_every_pinned_metric():
    """The reviewer's must-fix: the summary must carry a median for EVERY
    pinned metric (total return, maxDD, CAGR, after-tax Calmar, Sharpe,
    trade count, win rate) -- not just calmar/total_return."""
    window_metrics = [
        {
            "year": 2013, "total_return": 0.10, "max_drawdown": -0.05, "cagr": 0.10,
            "calmar": 2.0, "sharpe": 1.0, "annualized_vol": 0.1, "trade_count": 4, "win_rate": 0.5,
        },
        {
            "year": 2014, "total_return": 0.20, "max_drawdown": -0.10, "cagr": 0.20,
            "calmar": 2.0, "sharpe": 1.5, "annualized_vol": 0.2, "trade_count": 6, "win_rate": 0.75,
        },
    ]
    agg = fx_survey.aggregate_metric_across_windows(window_metrics)
    assert agg["median_total_return"] == pytest.approx(0.15)
    assert agg["median_max_drawdown"] == pytest.approx(-0.075)
    assert agg["median_cagr"] == pytest.approx(0.15)
    assert agg["median_calmar"] == pytest.approx(2.0)
    assert agg["median_sharpe"] == pytest.approx(1.25)
    assert agg["median_trade_count"] == pytest.approx(5.0)
    assert agg["median_win_rate"] == pytest.approx(0.625)


def test_aggregate_median_skips_nan_win_rate_windows():
    """win_rate is NaN on a zero-trade window (SUB_PLAN pin (c)) -- the
    median must skip it, the same NaN-tolerant treatment as Calmar."""
    window_metrics = [
        {"year": 2013, "total_return": 0.0, "calmar": float("nan"), "win_rate": float("nan"), "trade_count": 0},
        {"year": 2014, "total_return": 0.10, "calmar": 1.0, "win_rate": 0.6, "trade_count": 5},
    ]
    agg = fx_survey.aggregate_metric_across_windows(window_metrics)
    assert agg["median_win_rate"] == pytest.approx(0.6)


def test_aggregate_missing_metric_keys_default_to_nan():
    """Backward/forward compatible: a window dict missing a metric key
    (e.g. a minimal test fixture) contributes NaN for that metric's
    median rather than raising KeyError."""
    window_metrics = [{"year": 2013, "total_return": 0.10, "calmar": 1.0}]
    agg = fx_survey.aggregate_metric_across_windows(window_metrics)
    assert pd.isna(agg["median_sharpe"])
    assert pd.isna(agg["median_trade_count"])


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


def test_compute_spy_windows_records_skip_reason_for_insufficient_window_bars():
    """Skip-row parity with the FX runners (Nit 1, PR #377 final review): a
    window whose [pre_roll_start, test_end] span has fewer than 2 SPY rows
    is reported as a skip row (same shape as run_cell_across_windows'/
    run_baseline_across_windows' skip rows), not silently ``continue``d."""
    full_frame = _synthetic_spy_frame("2019-11-01", n=300)
    calendar_windows = [{
        "year": 2013, "scored": True,
        "pre_roll_start": pd.Timestamp("2013-01-01"),
        "test_start": pd.Timestamp("2013-01-01"),
        "test_end": pd.Timestamp("2013-01-01"),  # entirely outside the fetched frame
    }]
    rows = fx_survey.compute_spy_windows(
        calendar_windows=calendar_windows, fetch=lambda *a: full_frame,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == 2013
    assert row["scored"] is True
    assert row["skipped"] is True
    assert row["skip_reason"] == "insufficient_window_bars"
    assert row["n_window_bars"] < 2
    assert row["n_test_bars"] is None


def test_compute_spy_windows_records_skip_reason_for_insufficient_test_bars():
    full_frame = _synthetic_spy_frame("2019-11-01", n=300)
    calendar_windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": full_frame.index[0],
        "test_start": full_frame.index[-2],
        "test_end": full_frame.index[-1],  # exclusive -- only 1 bar in [test_start, test_end)
    }]
    rows = fx_survey.compute_spy_windows(
        calendar_windows=calendar_windows, fetch=lambda *a: full_frame,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["skipped"] is True
    assert row["skip_reason"] == "insufficient_test_bars"
    assert row["n_window_bars"] >= 2
    assert row["n_test_bars"] < 2


def test_compute_spy_windows_non_skipped_rows_carry_skipped_false_and_none_reason():
    calendar_windows = [
        {
            "year": 2013, "scored": True,
            "pre_roll_start": pd.Timestamp("2012-11-01"),
            "test_start": pd.Timestamp("2013-01-01"),
            "test_end": pd.Timestamp("2014-01-01"),
        },
    ]
    full_frame = _synthetic_spy_frame("2012-11-01", n=600)
    rows = fx_survey.compute_spy_windows(
        calendar_windows=calendar_windows, fetch=lambda *a: full_frame,
    )
    assert len(rows) == 1
    assert rows[0]["skipped"] is False
    assert rows[0]["skip_reason"] is None


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


# ---------------------------------------------------------------------------
# Synthetic smoke fixture (spec §7) -- code-generated, deterministic, NEVER
# real cache data. Includes deliberate Saturday-UTC rows to exercise the
# carve-out.
# ---------------------------------------------------------------------------

def test_make_smoke_fixture_is_deterministic_for_a_fixed_seed():
    a = fx_survey.make_smoke_fixture(seed=42)
    b = fx_survey.make_smoke_fixture(seed=42)
    pd.testing.assert_frame_equal(a, b)


def test_make_smoke_fixture_differs_for_a_different_seed():
    a = fx_survey.make_smoke_fixture(seed=42)
    c = fx_survey.make_smoke_fixture(seed=43)
    assert not a["MidClose"].equals(c["MidClose"])


def test_make_smoke_fixture_has_saturday_rows_and_is_ohlc_coherent():
    from backtest import fx_data

    fixture = fx_survey.make_smoke_fixture(seed=42)
    weekend = fx_data.check_weekend_bars(fixture)
    assert weekend["n_saturday_bars"] > 0  # deliberately present -- exercises the carve-out

    coherence = fx_data.check_ohlc_coherence(fixture)
    assert coherence["n_coherence_violations"] == 0
    assert coherence["n_crossed_quotes"] == 0
    assert coherence["n_non_positive_prices"] == 0


def test_make_smoke_fixture_covers_roughly_1_5_years():
    fixture = fx_survey.make_smoke_fixture(seed=42)
    span_days = (fixture.index[-1] - fixture.index[0]).days
    assert 400 <= span_days <= 600  # ~1.1-1.6 years


def test_make_smoke_spy_fixture_has_open_close_columns_and_is_deterministic():
    a = fx_survey.make_smoke_spy_fixture(seed=7)
    b = fx_survey.make_smoke_spy_fixture(seed=7)
    assert list(a.columns) == ["Open", "Close"]
    pd.testing.assert_frame_equal(a, b)
    assert (a["Close"] > 0).all()


# ---------------------------------------------------------------------------
# Per-cell / per-baseline window runners
# ---------------------------------------------------------------------------

def _tiny_bars_4h(n=40, start="2020-06-01"):
    idx = pd.date_range(start, periods=n, freq="4h", tz="UTC")
    idx.name = "datetime_utc"
    rng = np.random.default_rng(1)
    mid_close = 1.10 + np.cumsum(rng.normal(0, 0.0002, n))
    df = pd.DataFrame({
        "MidOpen": mid_close, "MidHigh": mid_close + 0.0003,
        "MidLow": mid_close - 0.0003, "MidClose": mid_close,
    }, index=idx)
    return df


def test_run_cell_across_windows_returns_windows_and_summary_shape():
    bars = _tiny_bars_4h(n=60)
    windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": bars.index[0], "test_start": bars.index[20], "test_end": bars.index[-1],
    }]
    from backtest import fx_signals

    fn = fx_signals.SHAPES["M1_roc_12"]
    result = fx_survey.run_cell_across_windows(
        bars, fn, 0.0030, windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    assert set(result.keys()) == {"windows", "summary"}
    assert len(result["windows"]) == 1
    row = result["windows"][0]
    assert row["year"] == 2020
    assert row["scored"] is True
    assert row["skipped"] is False
    assert row["skip_reason"] is None
    assert row["n_pre_roll_bars"] > 0
    assert row["n_test_bars"] > 0
    for key in fx_survey.METRIC_KEYS:
        assert key in row

    summary = result["summary"]
    for key in ("median_calmar", "n_nan_calmar_windows", "median_total_return",
                "median_max_drawdown", "median_cagr", "median_sharpe",
                "median_trade_count", "median_win_rate",
                "worst_window_total_return", "worst_window_label", "n_windows"):
        assert key in summary


def test_run_cell_across_windows_includes_unscored_window_but_excludes_it_from_summary():
    """ND1-style partial-year window (scored=False): the row is still
    reported in "windows" (unscored coverage, per spec §7's "results are
    reported, not discarded"), but never feeds the summary's n_windows."""
    bars = _tiny_bars_4h(n=60)
    windows = [
        {
            "year": 2020, "scored": True,
            "pre_roll_start": bars.index[0], "test_start": bars.index[20], "test_end": bars.index[40],
        },
        {
            "year": 2021, "scored": False,  # e.g. ND1's excluded partial trailing year
            "pre_roll_start": bars.index[10], "test_start": bars.index[40], "test_end": bars.index[-1],
        },
    ]
    from backtest import fx_signals

    fn = fx_signals.SHAPES["M1_roc_12"]
    result = fx_survey.run_cell_across_windows(
        bars, fn, 0.0030, windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    assert len(result["windows"]) == 2
    assert [row["year"] for row in result["windows"]] == [2020, 2021]
    assert result["windows"][1]["scored"] is False
    assert result["summary"]["n_windows"] == 1  # only the scored window


def test_run_cell_across_windows_records_skip_reason_for_insufficient_pre_roll_bars():
    bars = _tiny_bars_4h(n=60)
    windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": bars.index[-1],
        "test_start": bars.index[-1],
        "test_end": bars.index[-1] + pd.Timedelta("4h"),
    }]
    from backtest import fx_signals

    fn = fx_signals.SHAPES["M1_roc_12"]
    result = fx_survey.run_cell_across_windows(
        bars, fn, 0.0030, windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    row = result["windows"][0]
    assert row["skipped"] is True
    assert row["skip_reason"] == "insufficient_pre_roll_bars"
    assert row["n_test_bars"] is None
    assert result["summary"]["n_windows"] == 0


def test_run_cell_across_windows_records_skip_reason_for_insufficient_test_bars():
    bars = _tiny_bars_4h(n=60)
    windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": bars.index[0],
        "test_start": bars.index[-2],
        "test_end": bars.index[-1],  # exclusive -- only 1 bar in [test_start, test_end)
    }]
    from backtest import fx_signals

    fn = fx_signals.SHAPES["M1_roc_12"]
    result = fx_survey.run_cell_across_windows(
        bars, fn, 0.0030, windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    row = result["windows"][0]
    assert row["skipped"] is True
    assert row["skip_reason"] == "insufficient_test_bars"
    assert row["n_pre_roll_bars"] > 0
    assert result["summary"]["n_windows"] == 0


def test_run_baseline_across_windows_returns_windows_and_summary_shape():
    bars = _tiny_bars_4h(n=60)
    windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": bars.index[0], "test_start": bars.index[20], "test_end": bars.index[-1],
    }]
    result = fx_survey.run_baseline_across_windows(
        bars, "persistence", windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    assert set(result.keys()) == {"windows", "summary"}
    assert len(result["windows"]) == 1
    row = result["windows"][0]
    assert row["n_pre_roll_bars"] > 0
    assert row["n_test_bars"] > 0
    for key in ("median_calmar", "n_windows"):
        assert key in result["summary"]


def test_run_baseline_across_windows_records_skip_reason():
    bars = _tiny_bars_4h(n=60)
    windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": bars.index[-1],
        "test_start": bars.index[-1],
        "test_end": bars.index[-1] + pd.Timedelta("4h"),
    }]
    result = fx_survey.run_baseline_across_windows(
        bars, "persistence", windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    row = result["windows"][0]
    assert row["skipped"] is True
    assert row["skip_reason"] == "insufficient_pre_roll_bars"


def test_run_baseline_across_windows_sma200_applies_degenerate_convention():
    """A window entirely too short for SMA(200) to ever turn on (all-flat,
    zero trades) must aggregate to calmar=0, not NaN (spec §6) -- in the
    SUMMARY; the raw per-window row still shows the true (NaN) calmar and
    zero trade_count, undisguised."""
    bars = _tiny_bars_4h(n=60)
    windows = [{
        "year": 2020, "scored": True,
        "pre_roll_start": bars.index[0], "test_start": bars.index[20], "test_end": bars.index[-1],
    }]
    result = fx_survey.run_baseline_across_windows(
        bars, "sma200_regime", windows, cost_rt=0.0001, overnight=None, tax_mode="annual_netting",
    )
    assert result["summary"]["n_nan_calmar_windows"] == 0
    assert result["summary"]["median_calmar"] == pytest.approx(0.0)
    # The raw row is NOT rewritten by the convention -- it shows the truth.
    row = result["windows"][0]
    assert row["trade_count"] == 0
    assert pd.isna(row["calmar"])


# ---------------------------------------------------------------------------
# run_survey -- the extracted, parameterized combinatorial loop (SUB_PLAN
# should-fix #3). Takes ALREADY-PREPARED bars_4h + windows; does no data
# loading of its own, so it is import-callable for stage 2c against real
# data with zero changes -- and, in this package, is exercised only against
# synthetic/tiny fixtures, never real cache data.
# ---------------------------------------------------------------------------

def _survey_ready_bars(n=400, start="2020-01-01"):
    idx = pd.date_range(start, periods=n, freq="4h", tz="UTC")
    idx.name = "datetime_utc"
    rng = np.random.default_rng(3)
    mid_close = 1.10 + np.cumsum(rng.normal(0, 0.0002, n))
    return pd.DataFrame({
        "MidOpen": mid_close, "MidHigh": mid_close + 0.0003,
        "MidLow": mid_close - 0.0003, "MidClose": mid_close,
    }, index=idx)


def test_run_survey_returns_full_digest_with_full_structure_in_cell_matrix():
    bars = _survey_ready_bars(n=400)
    windows = fx_survey.slice_calendar_year_windows(
        bars.index, first_test_year=bars.index[0].year, pre_roll_bars=50, excluded_years=(),
    )
    spy_frame = _synthetic_spy_frame("2019-11-01", n=300)

    result = fx_survey.run_survey(
        bars, windows, measured_spread_pips=0.6,
        spy_fetch=lambda ticker, start, end: spy_frame,
    )

    assert len(result["survivor_results"]) == 33
    assert set(result["family_kills"].keys()) == {"T", "M", "R"}
    assert "class_dead" in result["class_kill"]
    assert "spy_median_calmar" in result

    # Must-fix: cell_full_matrix carries the FULL {"windows","summary"}
    # structure, not just a flattened summary -- through every cell x
    # venue/cost-mode x tax-mode cell.
    one_cell = next(iter(result["cell_full_matrix"].values()))
    one_row = one_cell["xtb_base"]["annual_netting"]
    assert set(one_row.keys()) == {"windows", "summary"}
    assert isinstance(one_row["windows"], list)


def test_run_survey_is_import_callable_and_never_touches_cache(monkeypatch):
    from backtest import fx_data

    def _raise(*a, **kw):
        raise AssertionError("run_survey must never touch the FXCM cache -- it takes prepared bars_4h")

    monkeypatch.setattr(fx_data, "read_cache", _raise)
    monkeypatch.setattr(fx_data, "get_week_bytes", _raise)

    bars = _survey_ready_bars(n=400)
    windows = fx_survey.slice_calendar_year_windows(
        bars.index, first_test_year=bars.index[0].year, pre_roll_bars=50, excluded_years=(),
    )
    spy_frame = _synthetic_spy_frame("2019-11-01", n=300)

    result = fx_survey.run_survey(
        bars, windows, measured_spread_pips=0.6,
        spy_fetch=lambda ticker, start, end: spy_frame,
    )
    assert len(result["survivor_results"]) == 33


def test_run_survey_spy_skip_row_does_not_break_aggregation():
    """Mandatory companion to the Nit 1 SPY skip-row fix: a skip row has no
    ``total_return``/``calmar`` keys, so run_survey's own scored-window
    filter must exclude ``skipped=True`` rows before they reach
    ``aggregate_metric_across_windows`` (which indexes ``m["total_return"]``
    directly) -- otherwise this KeyErrors instead of computing a real
    spy_median_calmar over the windows that DID have enough SPY data."""
    bars = _survey_ready_bars(n=400)
    windows = fx_survey.slice_calendar_year_windows(
        bars.index, first_test_year=bars.index[0].year, pre_roll_bars=50, excluded_years=(),
    )
    # A short SPY frame: covers the later windows fully but leaves the
    # earliest window(s) with fewer than 2 SPY rows -- a real skip row.
    spy_frame = _synthetic_spy_frame("2021-06-01", n=250)

    result = fx_survey.run_survey(
        bars, windows, measured_spread_pips=0.6,
        spy_fetch=lambda ticker, start, end: spy_frame,
    )
    # Must not raise KeyError; a finite/NaN median_calmar is fine either way.
    assert "spy_median_calmar" in result


# ---------------------------------------------------------------------------
# Full smoke composition (spec §7) -- offline, synthetic-only, zero cache
# access. This is the SAME composition run_fx_survey.py --smoke executes
# (run_smoke_survey is now a THIN wrapper around run_survey: generates the
# synthetic fixture + windows, then delegates the entire combinatorial loop
# to run_survey).
# ---------------------------------------------------------------------------

def test_run_smoke_survey_never_touches_cache(monkeypatch):
    from backtest import fx_data

    def _raise(*a, **kw):
        raise AssertionError("smoke survey must never touch the FXCM cache")

    monkeypatch.setattr(fx_data, "read_cache", _raise)
    monkeypatch.setattr(fx_data, "get_week_bytes", _raise)

    result = fx_survey.run_smoke_survey(seed=42)

    assert result["n_saturday_dropped"] > 0
    assert result["bars_4h_len"] > 0
    assert len(result["survivor_results"]) == 33
    assert set(result["family_kills"].keys()) == {"T", "M", "R"}
    assert "class_dead" in result["class_kill"]
    assert "spy_median_calmar" in result  # always present (value itself may legitimately be NaN)

    # Full structure carried through cell_full_matrix (must-fix #1), end to end.
    one_cell = next(iter(result["cell_full_matrix"].values()))
    one_row = one_cell["xtb_base"]["annual_netting"]
    assert set(one_row.keys()) == {"windows", "summary"}


def test_run_smoke_survey_is_deterministic():
    r1 = fx_survey.run_smoke_survey(seed=42)
    r2 = fx_survey.run_smoke_survey(seed=42)
    assert r1["n_saturday_dropped"] == r2["n_saturday_dropped"]
    assert r1["bars_4h_len"] == r2["bars_4h_len"]
    assert r1["survivor_results"].keys() == r2["survivor_results"].keys()
