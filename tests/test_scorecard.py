"""Tests for backtest/scorecard.py -- research pipeline scorecard metrics (Task 7).

Research-only. Every ``PortfolioResult`` is built directly by a local helper
(never through ``simulate_portfolio``), all data is synthetic and seeded, and
nothing reads ``costs["cash_interest"]``. No network, no broker, no LLM.
"""
from __future__ import annotations

import json
import math
import re

import numpy as np
import pandas as pd
import pytest

from backtest.overfitting_gate import deflated_sharpe_ratio
from backtest.portfolio import PortfolioResult, round_trips_per_year
from backtest.scorecard import ROW_LABELS, compute_scorecard, render_scorecard_markdown

TARGET_VOL = 0.10

SPEC_LABELS = [
    "CAGR (pre-tax, after costs)",
    "CAGR after German tax",
    "Max drawdown, and its dates",
    "Calmar (return / max drawdown)",
    "Sharpe; target and realised annualised volatility",
    "Worst calendar year; 2008 and 2020 (development), 2022 (holdout)",
    "Round trips per year, average holding days, max share of time in one ETF",
    "Cost drag per year, incl. short-borrow cost; result at double cost",
    "vs vol-targeted SPY benchmark (Calmar, CAGR, max DD)",
    "DSR (with programme trial count), PBO, bootstrap CI on uplift",
    "Same rule at 1.5x gross exposure, incl. financing (information only)",
]

ZERO_COSTS = {"trading": 0.0, "borrow": 0.0, "financing": 0.0, "cash_interest": 0.0}


def _result(values, index, weights=None, trades=None, costs=None) -> PortfolioResult:
    equity = pd.Series(np.asarray(values, dtype=float), index=index)
    daily = equity.pct_change().fillna(0.0)
    hw = weights if weights is not None else pd.DataFrame(index=index)
    gross = hw.abs().sum(axis=1) if len(hw.columns) else pd.Series(0.0, index=index)
    return PortfolioResult(
        equity=equity,
        daily_returns=daily,
        gross_exposure=gross.astype(float),
        held_weights=hw,
        trades=list(trades or []),
        costs=dict(costs or ZERO_COSTS),
    )


def _trade(entry, exit_, pnl, kind="round_trip", symbol="SPY") -> dict:
    return {
        "symbol": symbol,
        "side": "long",
        "kind": kind,
        "entry_date": pd.Timestamp(entry),
        "exit_date": pd.Timestamp(exit_),
        "entry_price": 100.0,
        "exit_price": 100.0,
        "qty": 1.0,
        "pnl": float(pnl),
        "exit_reason": "close" if kind == "round_trip" else "resize",
    }


def _random_curve(index, seed=0, drift=0.0008, vol=0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.cumprod(1.0 + rng.normal(drift, vol, len(index)))


def _calendar_index() -> pd.DatetimeIndex:
    # 2018 and 2022 are partial; 2019, 2020, 2021 are full calendar years.
    return pd.bdate_range("2018-06-01", "2022-01-31")


def _cells(markdown: str, label: str):
    for line in markdown.splitlines():
        if line.startswith("| " + label + " |"):
            return [c.strip() for c in line.strip().strip("|").split(" | ")]
    raise AssertionError(f"row {label!r} not found")


def _card(result=None, benchmark=None, **kw):
    idx = pd.bdate_range("2020-01-01", periods=10)
    result = result or _result(np.linspace(100, 110, 10), idx)
    benchmark = benchmark or _result(np.linspace(100, 105, 10), idx)
    return compute_scorecard(result, benchmark, target_vol=TARGET_VOL, **kw)


# 1
def test_max_drawdown_is_a_positive_magnitude_with_exact_dates():
    idx = pd.bdate_range("2020-01-01", periods=7)
    res = _result([100, 110, 121, 108.9, 115, 121, 130], idx)
    card = _card(res, _result(np.linspace(100, 130, 7), idx))
    assert card["max_drawdown"] == pytest.approx(0.10)
    assert card["max_drawdown"] > 0
    assert card["max_drawdown_start"] == idx[2].strftime("%Y-%m-%d")
    assert card["max_drawdown_end"] == idx[3].strftime("%Y-%m-%d")


# 2
def test_flat_then_minus_ten_percent_then_recovery_gives_calmar_cagr_over_ten_percent():
    idx = pd.bdate_range("2020-01-01", periods=13)
    res = _result([100] * 5 + [90] * 3 + [105] * 4 + [110], idx)
    card = _card(res, _result(np.linspace(100, 110, 13), idx))
    years = (idx[-1] - idx[0]).days / 365.25
    expected_cagr = (110 / 100) ** (1 / years) - 1
    assert card["cagr"] == pytest.approx(expected_cagr)
    assert card["max_drawdown"] == pytest.approx(0.10)
    assert card["calmar"] == pytest.approx(expected_cagr / 0.10)


# 3
def test_max_time_share_one_etf_is_one_for_a_single_always_held_asset():
    idx = pd.bdate_range("2020-01-01", periods=10)
    hw = pd.DataFrame({"SPY": 1.0, "AGG": 0.0}, index=idx)
    card = _card(_result(np.linspace(100, 110, 10), idx, weights=hw))
    assert card["max_time_share_one_etf"] == 1.0


def test_max_time_share_one_etf_is_the_largest_fraction_of_all_rows_held():
    idx = pd.bdate_range("2020-01-01", periods=10)
    hw = pd.DataFrame(
        {"SPY": [1.0] * 3 + [0.0] * 7, "AGG": [0.0] * 3 + [-0.5] * 4 + [0.0] * 3},
        index=idx,
    )
    card = _card(_result(np.linspace(100, 110, 10), idx, weights=hw))
    assert card["max_time_share_one_etf"] == pytest.approx(0.4)


# 4
def test_rendered_markdown_contains_the_header_and_every_spec_row_label():
    assert list(ROW_LABELS) == SPEC_LABELS
    md = render_scorecard_markdown(_card(), None, None)
    assert "| Figure | Development (to 2021) | Holdout (2022+) |" in md
    for label in SPEC_LABELS:
        assert label in md


# 5
def test_sharpe_daily_matches_the_gate_and_annual_scales_by_sqrt_252():
    idx = pd.bdate_range("2020-01-01", periods=300)
    res = _result(_random_curve(idx, seed=1), idx)
    card = _card(res, _result(_random_curve(idx, seed=2), idx))
    r = res.daily_returns.to_numpy()
    assert card["sharpe_daily"] == pytest.approx(r.mean() / r.std(ddof=1))
    gate = deflated_sharpe_ratio(r, [0.0, 0.1])
    assert card["sharpe_daily"] == pytest.approx(gate["sr_hat"])
    assert card["sharpe_annual"] == pytest.approx(card["sharpe_daily"] * math.sqrt(252))
    assert card["n_periods"] == 300
    assert card["realized_vol"] == pytest.approx(r.std(ddof=1) * math.sqrt(252))


def test_constant_returns_give_zero_sharpe():
    idx = pd.bdate_range("2020-01-01", periods=50)
    res = _result(100.0 * 1.001 ** np.arange(50), idx)
    res.daily_returns[:] = 0.001
    assert _card(res, _result(np.linspace(100, 105, 50), idx))["sharpe_daily"] == 0.0


# 6
def test_repeated_peak_value_starts_the_drawdown_at_the_last_flat_day():
    idx = pd.bdate_range("2020-01-01", periods=7)
    res = _result([100, 110, 110, 110, 99, 105, 111], idx)
    card = _card(res, _result(np.linspace(100, 111, 7), idx))
    assert card["max_drawdown"] == pytest.approx(0.10)
    assert card["max_drawdown_start"] == idx[3].strftime("%Y-%m-%d")
    assert card["max_drawdown_end"] == idx[4].strftime("%Y-%m-%d")


# 7
def test_window_calmars_score_only_full_calendar_years_with_string_keys():
    idx = _calendar_index()
    card = _card(_result(_random_curve(idx, seed=3), idx), _result(_random_curve(idx, seed=4), idx))
    assert sorted(card["window_calmars"]) == ["2019", "2020", "2021"]
    assert sorted(card["year_returns"]) == ["2019", "2020", "2021"]
    assert card["worst_year"]["year"] in card["year_returns"]
    assert card["worst_year"]["return"] == min(card["year_returns"].values())


@pytest.mark.parametrize(
    "start, end, expected",
    [
        ("2019-01-07", "2019-12-25", ["2019"]),  # both bounds exactly on the edge
        ("2019-01-08", "2019-12-31", []),  # starts one day too late
        ("2019-01-02", "2019-12-24", []),  # ends one day too early
        ("2022-01-03", "2022-12-30", ["2022"]),  # a holdout year starting at the first session
    ],
)
def test_full_year_bounds_are_jan_7_and_dec_25_inclusive(start, end, expected):
    idx = pd.bdate_range(start, end)
    assert idx[0] == pd.Timestamp(start) and idx[-1] == pd.Timestamp(end)
    card = _card(
        _result(_random_curve(idx, seed=3), idx), _result(_random_curve(idx, seed=4), idx)
    )
    assert sorted(card["year_returns"]) == expected


def test_trade_exiting_in_a_year_lowers_that_years_calmar_but_not_other_years():
    idx = _calendar_index()
    eq = _random_curve(idx, seed=3, drift=0.002)
    bench = _result(_random_curve(idx, seed=4), idx)
    base = _card(_result(eq, idx), bench)
    assert base["window_calmars"]["2020"] > 0 and base["window_calmars"]["2021"] > 0
    in_2020 = _card(_result(eq, idx, trades=[_trade("2020-02-03", "2020-06-01", 10.0)]), bench)
    assert in_2020["window_calmars"]["2020"] < base["window_calmars"]["2020"]
    assert in_2020["window_calmars"]["2021"] == pytest.approx(base["window_calmars"]["2021"])
    assert in_2020["window_calmars"]["2019"] == pytest.approx(base["window_calmars"]["2019"])
    in_2019 = _card(_result(eq, idx, trades=[_trade("2019-02-03", "2019-06-01", 10.0)]), bench)
    assert in_2019["window_calmars"]["2020"] == pytest.approx(base["window_calmars"]["2020"])
    assert in_2019["window_calmars"]["2019"] < base["window_calmars"]["2019"]


# 8
def test_partial_trade_gain_lowers_after_tax_cagr_but_not_activity_figures():
    idx = pd.bdate_range("2020-01-01", periods=300)
    eq = _random_curve(idx, seed=5)
    bench = _result(_random_curve(idx, seed=6), idx)
    loss = _trade("2020-02-03", "2020-02-13", -5.0)
    partial = _trade("2020-03-02", "2020-03-04", 20.0, kind="partial")
    without = _card(_result(eq, idx, trades=[loss]), bench)
    with_partial = _card(_result(eq, idx, trades=[loss, partial]), bench)
    assert with_partial["cagr_after_tax"] < without["cagr_after_tax"]
    assert with_partial["cagr"] == without["cagr"]
    assert with_partial["round_trips_per_year"] == without["round_trips_per_year"]
    assert with_partial["round_trips_per_year"] == round_trips_per_year(_result(eq, idx, trades=[loss]))
    assert with_partial["avg_holding_days"] == without["avg_holding_days"] == 10.0


def test_avg_holding_days_is_none_without_round_trips():
    assert _card()["avg_holding_days"] is None


# 9
def test_scorecard_round_trips_through_strict_json_including_zero_drawdown():
    idx = pd.bdate_range("2020-01-01", periods=10)
    res = _result(np.linspace(100, 110, 10), idx, trades=[_trade("2020-01-02", "2020-01-10", 3.0)])
    dbl = _result(np.linspace(100, 108, 10), idx)
    card = _card(res, _result(np.linspace(100, 105, 10), idx), double_cost=dbl, leverage_info=dbl)
    assert card["max_drawdown"] == 0.0
    assert math.copysign(1.0, card["max_drawdown"]) == 1.0  # never -0.0
    assert card["calmar"] is None
    assert card["max_drawdown_start"] is None and card["max_drawdown_end"] is None
    assert json.loads(json.dumps(card, allow_nan=False)) == card
    assert set(card["double_cost"]) == {"cagr", "max_drawdown", "calmar"}
    assert set(card["leverage_info"]) == {"cagr", "max_drawdown", "calmar"}
    assert _card()["double_cost"] is None and _card()["leverage_info"] is None


def test_scorecard_with_dates_and_years_round_trips_through_strict_json():
    idx = _calendar_index()
    card = _card(
        _result(_random_curve(idx, seed=3), idx, trades=[_trade("2020-02-03", "2020-06-01", 7.0)]),
        _result(_random_curve(idx, seed=4), idx),
    )
    assert json.loads(json.dumps(card, allow_nan=False)) == card


def _raw_result(values, index) -> PortfolioResult:
    """Like ``_result`` but with a raw ``equity.pct_change()`` (row 0 NaN).

    ``backtest/portfolio.py`` sets row 0 finite but applies no fillna, so a
    ruined (exactly zero) equity curve carries NaN (0/0) or inf (x/0) in later
    rows; this fixture reproduces those rows.
    """
    equity = pd.Series(np.asarray(values, dtype=float), index=index)
    return PortfolioResult(
        equity=equity,
        daily_returns=equity.pct_change(),
        gross_exposure=pd.Series(0.0, index=index),
        held_weights=pd.DataFrame(index=index),
        trades=[],
        costs=dict(ZERO_COSTS),
    )


def test_raw_pct_change_returns_with_row_zero_nan_round_trip_through_strict_json():
    idx = _calendar_index()
    res = _raw_result(_random_curve(idx, seed=5), idx)
    assert math.isnan(res.daily_returns.iloc[0])
    card = _card(res, _raw_result(_random_curve(idx, seed=6), idx))
    assert json.loads(json.dumps(card, allow_nan=False)) == card
    r = res.daily_returns.to_numpy()[1:]
    assert card["n_periods"] == len(idx) - 1
    assert card["sharpe_daily"] == pytest.approx(deflated_sharpe_ratio(r, [0.0, 0.1])["sr_hat"])
    assert card["realized_vol"] == pytest.approx(r.std(ddof=1) * math.sqrt(252))
    assert set(card["year_returns"]) == {"2019", "2020", "2021"}


def test_ruin_to_exactly_zero_equity_round_trips_through_strict_json():
    idx = _calendar_index()
    values = _random_curve(idx, seed=7)
    values[300:] = 0.0  # ruin inside 2019 and flat at zero for years afterwards
    res = _raw_result(values, idx)
    assert res.daily_returns.isna().any()
    card = _card(res, _raw_result(_random_curve(idx, seed=8), idx))
    assert json.loads(json.dumps(card, allow_nan=False)) == card
    assert all(math.isfinite(v) for v in card["year_returns"].values())
    assert card["sharpe_daily"] is not None and math.isfinite(card["sharpe_daily"])
    # The ruin day (2019-07-26, -100%) is finite and stays; later dropped days count as 0%.
    assert card["year_returns"]["2019"] == -1.0
    assert card["year_returns"]["2020"] == 0.0
    assert card["n_periods"] == 300


def test_short_ruin_curve_and_zero_start_curve_round_trip_through_strict_json():
    idx = pd.bdate_range("2020-01-01", periods=8)
    curves = ([100, 50, 0, 0, 0, 0, 0, 0], [0, 100, 110, 120, 130, 140, 150, 160], [0.0] * 8)
    for values in curves:
        card = _card(_raw_result(values, idx), _result(np.linspace(100, 105, 8), idx))
        assert json.loads(json.dumps(card, allow_nan=False)) == card
        for key in ("sharpe_daily", "sharpe_annual", "realized_vol"):
            assert math.isfinite(card[key])


# 10
def test_mismatched_benchmark_double_cost_or_leverage_index_raises():
    idx = pd.bdate_range("2020-01-01", periods=10)
    other = pd.bdate_range("2020-01-02", periods=10)
    res = _result(np.linspace(100, 110, 10), idx)
    ok = _result(np.linspace(100, 105, 10), idx)
    bad = _result(np.linspace(100, 105, 10), other)
    with pytest.raises(ValueError):
        compute_scorecard(res, bad, target_vol=TARGET_VOL)
    with pytest.raises(ValueError):
        compute_scorecard(res, ok, target_vol=TARGET_VOL, double_cost=bad)
    with pytest.raises(ValueError):
        compute_scorecard(res, ok, target_vol=TARGET_VOL, leverage_info=bad)


@pytest.mark.parametrize("target_vol", [0.0, -0.1, float("nan"), float("inf")])
def test_invalid_target_vol_raises(target_vol):
    idx = pd.bdate_range("2020-01-01", periods=10)
    res = _result(np.linspace(100, 110, 10), idx)
    with pytest.raises(ValueError):
        compute_scorecard(res, res, target_vol=target_vol)


def test_result_with_fewer_than_two_rows_raises():
    idx = pd.bdate_range("2020-01-01", periods=1)
    res = _result([100.0], idx)
    with pytest.raises(ValueError):
        compute_scorecard(res, res, target_vol=TARGET_VOL)


# 11
def test_cost_drag_and_borrow_cost_per_year_match_known_costs():
    idx = pd.bdate_range("2020-01-01", periods=300)
    eq = _random_curve(idx, seed=7)
    costs = {"trading": 100.0, "borrow": 40.0, "financing": 10.0, "cash_interest": 999.0}
    card = _card(_result(eq, idx, costs=costs), _result(_random_curve(idx, seed=8), idx))
    years = (idx[-1] - idx[0]).days / 365.25
    mean_eq = float(np.mean(eq))
    assert card["cost_drag_per_year"] == pytest.approx(150.0 / mean_eq / years)
    assert card["borrow_cost_per_year"] == pytest.approx(40.0 / mean_eq / years)
    assert card["target_vol"] == TARGET_VOL


def test_benchmark_block_has_the_thirteen_performance_keys():
    card = _card()
    keys = {
        "cagr", "cagr_after_tax", "max_drawdown", "max_drawdown_start", "max_drawdown_end",
        "calmar", "sharpe_daily", "sharpe_annual", "n_periods", "realized_vol",
        "year_returns", "worst_year", "window_calmars",
    }
    assert set(card["benchmark"]) == keys
    assert keys <= set(card)


# 12
def test_render_without_holdout_has_n_a_in_every_holdout_cell():
    md = render_scorecard_markdown(_card(), None, None)
    for label in SPEC_LABELS:
        cells = _cells(md, label)
        assert len(cells) == 3
        assert cells[2] == "n/a"


def test_render_with_holdout_keeps_the_dsr_holdout_cell_n_a():
    verdict = {
        "passed": False,
        "criteria": {
            "drawdown": {"passed": True, "detail": "dd ok"},
            "beats_benchmark": {"passed": True, "detail": "beats"},
            "luck": {"passed": False, "detail": "DSR 0.41 | N=40"},
            "holdout": {"passed": True, "detail": "holdout ok"},
            "activity": {"passed": True, "detail": "active"},
        },
    }
    md = render_scorecard_markdown(_card(), _card(), verdict)
    dsr = _cells(md, SPEC_LABELS[9])
    assert dsr[2] == "n/a"
    assert dsr[1] == "DSR 0.41 \\| N=40"
    assert _cells(md, SPEC_LABELS[0])[2] != "n/a"
    assert md.index("drawdown:") < md.index("beats_benchmark:") < md.index("luck:") \
        < md.index("holdout:") < md.index("activity:")
    assert "FAIL" in md


def test_render_without_verdict_has_n_a_dsr_and_none_values_render_n_a():
    md = render_scorecard_markdown(_card(), None, None)
    assert _cells(md, SPEC_LABELS[9])[1] == "n/a"
    # zero-drawdown curve: calmar is None; no "None" or "nan" leaks into the table
    assert _cells(md, SPEC_LABELS[3])[1] == "n/a"
    assert "None" not in md and re.search(r"\bnan\b", md) is None


def test_rendered_markdown_contains_no_em_dash():
    verdict = {"passed": True, "criteria": {"luck": {"passed": True, "detail": "ok"}}}
    for md in (
        render_scorecard_markdown(_card(), None, None),
        render_scorecard_markdown(_card(), _card(), verdict),
    ):
        assert chr(0x2014) not in md
