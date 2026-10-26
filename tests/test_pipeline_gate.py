"""Tests for backtest.pipeline_gate (research pipeline, plan Task 8, issue #696).

Fixtures follow the scorecard shape pinned by #695 (plain dicts); nothing here
imports backtest.scorecard. The luck inputs are built with the same synthetic
battery helpers as tests/test_overfitting_gate.py (copied, not imported).
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

import backtest.overfitting_gate as og
from backtest import pipeline_gate as pg

GATE_KWARGS = {"pbo_n_splits": 8, "bootstrap_n_boot": 500}
CRITERIA = ["drawdown", "beats_benchmark", "luck", "holdout", "activity"]


def _noise_battery(seed: int, n_strats: int, n_periods: int, sigma: float = 0.01) -> np.ndarray:
    out = np.empty((n_periods, n_strats), dtype=float)
    for i in range(n_strats):
        rng = np.random.default_rng(seed * 10_000 + i)
        out[:, i] = rng.normal(0.0, sigma, n_periods)
    return out


def _edge_battery(
    seed: int,
    n_strats: int,
    n_periods: int,
    sigma: float = 0.01,
    edge_annualized_sharpe: float = 6.0,
    edge_col: int = 0,
) -> np.ndarray:
    out = _noise_battery(seed, n_strats, n_periods, sigma=sigma)
    edge_mu = edge_annualized_sharpe * sigma / np.sqrt(252.0)
    rng = np.random.default_rng(seed * 10_000 + edge_col + 999_999)
    out[:, edge_col] = rng.normal(edge_mu, sigma, n_periods)
    return out


def _per_window_uplift(cand: np.ndarray, base: np.ndarray, n_windows: int) -> np.ndarray:
    window_len = len(cand) // n_windows
    trimmed = window_len * n_windows
    c = cand[:trimmed].reshape(n_windows, window_len).mean(axis=1)
    b = base[:trimmed].reshape(n_windows, window_len).mean(axis=1)
    return c - b


def _luck_inputs() -> dict:
    perf = _edge_battery(seed=42, n_strats=50, n_periods=750, edge_annualized_sharpe=6.0, edge_col=0)
    sharpes = og._column_sharpes(perf)
    best = int(np.argmax(sharpes))
    return {
        "returns_best": perf[:, best],
        "all_trial_sharpes": sharpes,
        "perf_matrix": perf,
        "uplifts": _per_window_uplift(perf[:, best], perf[:, 1], 30),
    }


def _scorecard(**overrides) -> dict:
    card = {
        "max_drawdown": 0.15,
        "cagr": 0.12,
        "sharpe_daily": 1.1,
        "n_periods": 3000,
        "window_calmars": {"2012": 1.6, "2013": 1.9, "2014": 1.4},
        "round_trips_per_year": 26.0,
        "max_time_share_one_etf": 0.62,
        "benchmark": {"window_calmars": {"2012": 1.0, "2013": 1.1, "2014": 0.9}},
    }
    card.update(overrides)
    return card


def _holdout(**overrides) -> dict:
    card = {"cagr": 0.06, "max_drawdown": 0.12}
    card.update(overrides)
    return card


_DEFAULT = object()


def _run(development=None, holdout=_DEFAULT, luck=None, gate_kwargs=_DEFAULT) -> dict:
    inputs = luck if luck is not None else _luck_inputs()
    return pg.evaluate_candidate(
        _scorecard() if development is None else development,
        _holdout() if holdout is _DEFAULT else holdout,
        gate_kwargs=dict(GATE_KWARGS) if gate_kwargs is _DEFAULT else gate_kwargs,
        **inputs,
    )


def _failed(result: dict) -> set:
    return {k for k, v in result["criteria"].items() if not v["passed"]}


def _assert_only_fails(result: dict, failing: set) -> None:
    details = {k: v["detail"] for k, v in result["criteria"].items()}
    assert _failed(result) == failing, details
    assert result["passed"] is False


# 1
def test_all_pass_fixture_passes_with_five_ordered_criteria_and_is_json_safe():
    result = _run()
    assert result["passed"] is True
    assert list(result["criteria"]) == CRITERIA
    for entry in result["criteria"].values():
        assert set(entry) == {"passed", "detail"}
        assert isinstance(entry["passed"], bool)
        assert isinstance(entry["detail"], str)
        assert "\n" not in entry["detail"]
        assert "|" not in entry["detail"]
        assert "—" not in entry["detail"]
    json.dumps(result, allow_nan=False)


# 2
def test_holdout_none_fails_only_holdout_with_exact_detail():
    result = _run(holdout=None)
    _assert_only_fails(result, {"holdout"})
    assert result["criteria"]["holdout"]["detail"] == "holdout not yet run"
    assert "holdout not yet run" in result["criteria"]["drawdown"]["detail"]


# 3
def _swapped_uplifts() -> dict:
    inputs = _luck_inputs()
    inputs["uplifts"] = -np.abs(inputs["uplifts"]) - 0.0005
    return inputs


@pytest.mark.parametrize(
    "failing,kwargs",
    [
        ("drawdown", {"development": _scorecard(max_drawdown=0.25)}),
        (
            "beats_benchmark",
            {"development": _scorecard(window_calmars={"2012": 0.5, "2013": 0.6, "2014": 0.4})},
        ),
        ("luck", {"luck": _swapped_uplifts()}),
        ("holdout", {"holdout": _holdout(cagr=-0.02)}),
        ("activity", {"development": _scorecard(round_trips_per_year=12)}),
        ("activity", {"development": _scorecard(max_time_share_one_etf=0.95)}),
    ],
)
def test_each_criterion_alone_can_fail(failing, kwargs):
    _assert_only_fails(_run(**kwargs), {failing})


# 4
def test_constants_exact():
    assert pg.MAX_DRAWDOWN == 0.20
    assert pg.MIN_ROUND_TRIPS_PER_YEAR == 20
    assert pg.MAX_TIME_SHARE_ONE_ETF == 0.90


# 5
@pytest.mark.parametrize(
    "kwargs,failing",
    [
        ({"development": _scorecard(max_drawdown=0.20)}, set()),
        ({"development": _scorecard(max_drawdown=0.2001)}, {"drawdown"}),
        ({"holdout": _holdout(max_drawdown=0.20)}, set()),
        ({"holdout": _holdout(max_drawdown=0.2001)}, {"drawdown", "holdout"}),
        ({"development": _scorecard(round_trips_per_year=20)}, set()),
        ({"development": _scorecard(round_trips_per_year=19.99)}, {"activity"}),
        ({"development": _scorecard(max_time_share_one_etf=0.90)}, set()),
        ({"development": _scorecard(max_time_share_one_etf=0.9001)}, {"activity"}),
        ({"holdout": _holdout(cagr=0.0)}, {"holdout"}),
        ({"holdout": _holdout(cagr=None)}, {"holdout"}),
    ],
)
def test_boundaries(kwargs, failing):
    result = _run(**kwargs)
    assert _failed(result) == failing
    assert result["passed"] is (not failing)


def test_holdout_cagr_none_renders_n_a():
    result = _run(holdout=_holdout(cagr=None))
    assert "n/a" in result["criteria"]["holdout"]["detail"]
    json.dumps(result, allow_nan=False)


def test_nan_drawdown_fails_closed_and_renders_n_a():
    result = _run(development=_scorecard(max_drawdown=float("nan")))
    assert result["criteria"]["drawdown"]["passed"] is False
    assert "n/a" in result["criteria"]["drawdown"]["detail"]
    json.dumps(result, allow_nan=False)


# 6
def test_beats_benchmark_equal_medians_fail():
    dev = _scorecard(window_calmars={"2012": 1.0, "2013": 1.1, "2014": 0.9})
    assert _run(development=dev)["criteria"]["beats_benchmark"]["passed"] is False


def test_beats_benchmark_empty_candidate_fails_with_window_counts():
    result = _run(development=_scorecard(window_calmars={}))
    entry = result["criteria"]["beats_benchmark"]
    assert entry["passed"] is False
    assert "n_w=0" in entry["detail"]


def test_beats_benchmark_empty_benchmark_fails():
    result = _run(development=_scorecard(benchmark={"window_calmars": {}}))
    entry = result["criteria"]["beats_benchmark"]
    assert entry["passed"] is False
    assert "n_w=0" in entry["detail"]


def test_beats_benchmark_even_count_median_averages_middle_values():
    # candidate median = (1.0 + 3.0) / 2 = 2.0 ; benchmark median 1.99 -> passes.
    dev = _scorecard(
        window_calmars={"2010": 0.1, "2011": 1.0, "2012": 3.0, "2013": 9.0},
        benchmark={"window_calmars": {"2010": 1.99, "2011": 1.99, "2012": 1.99, "2013": 1.99}},
    )
    entry = _run(development=dev)["criteria"]["beats_benchmark"]
    assert entry["passed"] is True
    assert "2.0000" in entry["detail"]
    # benchmark median 2.01 -> fails.
    dev["benchmark"] = {"window_calmars": {"2010": 2.01, "2011": 2.01}}
    assert _run(development=dev)["criteria"]["beats_benchmark"]["passed"] is False


def test_beats_benchmark_differing_window_counts_allowed_and_reported():
    dev = _scorecard(
        window_calmars={"2012": 2.0, "2013": 2.0},
        benchmark={"window_calmars": {"2012": 1.0, "2013": 1.0, "2014": 1.0}},
    )
    entry = _run(development=dev)["criteria"]["beats_benchmark"]
    assert entry["passed"] is True
    assert "n_w=2" in entry["detail"]
    assert "n_w=3" in entry["detail"]


# 7
def test_holdout_drawdown_overlap_fails_drawdown_and_holdout():
    result = _run(holdout=_holdout(max_drawdown=0.25, cagr=0.05))
    _assert_only_fails(result, {"drawdown", "holdout"})


# 8
def test_luck_consistent_with_evaluate_gate_and_detail_has_figures():
    inputs = _luck_inputs()
    result = _run(luck=inputs)
    expected = og.evaluate_gate(**inputs, **GATE_KWARGS)
    entry = result["criteria"]["luck"]
    assert entry["passed"] is bool(expected["passed"])
    detail = entry["detail"]
    for token in ("DSR", "N=50", "PBO", "CI"):
        assert token in detail
    assert "\n" not in detail and "|" not in detail and "—" not in detail
    assert f"{expected['dsr']:.4f}" in detail
    assert f"{expected['pbo']:.4f}" in detail


def test_luck_failure_detail_includes_reasons():
    result = _run(luck=_swapped_uplifts())
    detail = result["criteria"]["luck"]["detail"]
    assert "bootstrap ci_low" in detail
    assert "\n" not in detail and "|" not in detail


# 9
def test_gate_kwargs_pass_through_and_caller_dict_unchanged():
    kwargs = {**GATE_KWARGS, "dsr_threshold": 1.01}
    snapshot = copy.deepcopy(kwargs)
    result = _run(gate_kwargs=kwargs)
    _assert_only_fails(result, {"luck"})
    assert kwargs == snapshot


def test_gate_kwargs_none_is_accepted():
    # evaluate_gate defaults (16 splits, 1000 boots) on the same battery.
    result = _run(gate_kwargs=None)
    assert list(result["criteria"]) == CRITERIA


# 10
def test_single_trial_sharpe_raises_value_error():
    inputs = _luck_inputs()
    inputs["all_trial_sharpes"] = np.array([1.0])
    with pytest.raises(ValueError):
        _run(luck=inputs)


# 11
def test_inputs_are_not_mutated():
    dev, hold = _scorecard(), _holdout()
    dev_copy, hold_copy = copy.deepcopy(dev), copy.deepcopy(hold)
    inputs = _luck_inputs()
    arrays = {k: v.copy() for k, v in inputs.items()}
    _run(development=dev, holdout=hold, luck=inputs)
    assert dev == dev_copy and hold == hold_copy
    for k, v in arrays.items():
        assert np.array_equal(inputs[k], v)


def test_missing_scorecard_key_raises_key_error():
    dev = _scorecard()
    del dev["round_trips_per_year"]
    with pytest.raises(KeyError):
        _run(development=dev)
