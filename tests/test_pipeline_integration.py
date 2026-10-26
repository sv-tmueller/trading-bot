"""Integration test: compute_scorecard output feeds evaluate_candidate (#708).

Research only: no network, no broker, nothing under supabase/functions/.
Each phase is built as its own PortfolioResult (spec 5.3 runs the holdout as a
separate run after development), scored by the real compute_scorecard, and the
resulting dicts go unchanged into the real evaluate_candidate. No scorecard
dict is written by hand, so a renamed or dropped key on either side of the
contract fails here. Helpers are copied, not imported from other test modules.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

import backtest.overfitting_gate as og
from backtest import pipeline_gate as pg
from backtest.portfolio import PortfolioResult
from backtest.scorecard import compute_scorecard

GATE_KWARGS = {"pbo_n_splits": 8, "bootstrap_n_boot": 500}
CRITERIA = ["drawdown", "beats_benchmark", "luck", "holdout", "activity"]
ZERO_COSTS = {"trading": 0.0, "borrow": 0.0, "financing": 0.0, "cash_interest": 0.0}
TARGET_VOL = 0.15

DEV_INDEX = pd.bdate_range("2019-01-01", "2021-12-31")
HOLDOUT_INDEX = pd.bdate_range("2022-01-03", "2022-12-30")

# Every scorecard path evaluate_candidate reads (backtest/pipeline_gate.py).
DEV_READS = (
    ("max_drawdown",),
    ("window_calmars",),
    ("benchmark", "window_calmars"),
    ("round_trips_per_year",),
    ("max_time_share_one_etf",),
)
HOLDOUT_READS = (("cagr",), ("max_drawdown",))


# --- luck battery, copied verbatim from tests/test_pipeline_gate.py ----------

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


LUCK = _luck_inputs()


# --- phase builders ---------------------------------------------------------

def _result(values, index, weights=None, trades=None) -> PortfolioResult:
    equity = pd.Series(np.asarray(values, dtype=float), index=index)
    hw = weights if weights is not None else pd.DataFrame(index=index)
    gross = hw.abs().sum(axis=1) if len(hw.columns) else pd.Series(0.0, index=index)
    return PortfolioResult(
        equity=equity,
        daily_returns=equity.pct_change().fillna(0.0),
        gross_exposure=gross.astype(float),
        held_weights=hw,
        trades=list(trades or []),
        costs=dict(ZERO_COSTS),
    )


def _candidate_curve(index, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.004, len(index)))


def _benchmark_curve(index, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.010, len(index)))


def _round_trips(index) -> list:
    """One round trip per 10th business day, exiting 5 business days later (pnl 0)."""
    trips = []
    for i in range(0, len(index) - 5, 10):
        trips.append({
            "symbol": "SPY",
            "side": "long",
            "kind": "round_trip",
            "entry_date": index[i],
            "exit_date": index[i + 5],
            "entry_price": 100.0,
            "exit_price": 100.0,
            "qty": 1.0,
            "pnl": 0.0,
            "exit_reason": "close",
        })
    return trips


def _alternating_weights(index) -> pd.DataFrame:
    """SPY and TLT held in alternating 10-day blocks (max time share about 0.5)."""
    on_spy = (np.arange(len(index)) // 10) % 2 == 0
    return pd.DataFrame(
        {"SPY": np.where(on_spy, 1.0, 0.0), "TLT": np.where(on_spy, 0.0, 1.0)},
        index=index,
    )


def _phase_card(index, cand_seed: int, bench_seed: int, stress: bool = False) -> dict:
    values = _candidate_curve(index, cand_seed)
    if stress:
        k = int(np.argmax(index >= pd.Timestamp("2020-06-01")))
        values[k:] *= 0.70
    candidate = _result(
        values, index, weights=_alternating_weights(index), trades=_round_trips(index)
    )
    benchmark = _result(_benchmark_curve(index, bench_seed), index)
    return compute_scorecard(candidate, benchmark, target_vol=TARGET_VOL)


def _evaluate(development: dict, holdout) -> dict:
    return pg.evaluate_candidate(
        development, holdout, gate_kwargs=dict(GATE_KWARGS), **LUCK
    )


def _median_calmar(windows: dict) -> float:
    return float(np.median(list(windows.values())))


@pytest.fixture(scope="module")
def cards() -> dict:
    return {
        "dev": _phase_card(DEV_INDEX, cand_seed=11, bench_seed=12),
        "holdout": _phase_card(HOLDOUT_INDEX, cand_seed=21, bench_seed=22),
        "stressed": _phase_card(DEV_INDEX, cand_seed=11, bench_seed=12, stress=True),
    }


def _resolve(card: dict, path: tuple):
    node = card
    for key in path:
        node = node[key]
    return node


# 1
def test_scorecards_feed_gate_end_to_end_and_values_tie_through(cards):
    dev, holdout = cards["dev"], cards["holdout"]
    # preconditions: the fixture really is a calm, passing candidate
    assert dev["max_drawdown"] < 0.20
    assert holdout["max_drawdown"] < 0.20
    assert holdout["cagr"] > 0
    assert _median_calmar(dev["window_calmars"]) > _median_calmar(
        dev["benchmark"]["window_calmars"]
    )
    assert dev["round_trips_per_year"] >= pg.MIN_ROUND_TRIPS_PER_YEAR
    assert 0.0 < dev["max_time_share_one_etf"] <= pg.MAX_TIME_SHARE_ONE_ETF

    result = _evaluate(dev, holdout)

    assert result["passed"] is True
    assert list(result["criteria"]) == CRITERIA
    for entry in result["criteria"].values():
        assert type(entry["passed"]) is bool
    assert json.loads(json.dumps(result, allow_nan=False)) == result

    assert set(dev["window_calmars"]) == {"2019", "2020", "2021"}
    assert set(dev["benchmark"]["window_calmars"]) == {"2019", "2020", "2021"}

    details = {k: v["detail"] for k, v in result["criteria"].items()}
    assert f"development {dev['max_drawdown']:.4f}" in details["drawdown"]
    assert f"holdout {holdout['max_drawdown']:.4f}" in details["drawdown"]
    cand_med = _median_calmar(dev["window_calmars"])
    bench_med = _median_calmar(dev["benchmark"]["window_calmars"])
    assert f"candidate {cand_med:.4f}" in details["beats_benchmark"]
    assert f"benchmark {bench_med:.4f}" in details["beats_benchmark"]
    assert details["beats_benchmark"].count("n_w=3") == 2
    assert f"{dev['round_trips_per_year']:.4f}" in details["activity"]
    assert f"{dev['max_time_share_one_etf']:.4f}" in details["activity"]


# 2
def test_drawdown_criterion_follows_the_scorecard_data(cards):
    calm, stressed = cards["dev"], cards["stressed"]
    assert calm["max_drawdown"] < 0.20
    assert stressed["max_drawdown"] > pg.MAX_DRAWDOWN

    assert _evaluate(calm, cards["holdout"])["criteria"]["drawdown"]["passed"] is True

    result = _evaluate(stressed, cards["holdout"])
    assert result["criteria"]["drawdown"]["passed"] is False
    assert result["passed"] is False
    assert f"development {stressed['max_drawdown']:.4f}" in result["criteria"]["drawdown"]["detail"]


# 3
def test_holdout_not_run_fails_only_the_holdout_criterion(cards):
    result = _evaluate(cards["dev"], None)

    assert result["criteria"]["holdout"] == {"passed": False, "detail": "holdout not yet run"}
    assert "holdout not yet run" in result["criteria"]["drawdown"]["detail"]
    failed = {k for k, v in result["criteria"].items() if not v["passed"]}
    assert failed == {"holdout"}
    assert result["passed"] is False


# 4a
@pytest.mark.parametrize("phase,paths", [("dev", DEV_READS), ("holdout", HOLDOUT_READS)])
def test_every_pinned_read_path_exists_in_the_produced_card(cards, phase, paths):
    for path in paths:
        try:
            _resolve(cards[phase], path)
        except KeyError as exc:
            pytest.fail(f"{phase} scorecard lacks pinned path {'/'.join(path)}: {exc!r}")


# 4b
@pytest.mark.parametrize(
    "phase,path",
    [("dev", p) for p in DEV_READS] + [("holdout", p) for p in HOLDOUT_READS],
    ids=lambda v: v if isinstance(v, str) else "/".join(v),
)
def test_removing_a_read_key_raises_keyerror_not_a_failed_verdict(cards, phase, path):
    dev, holdout = copy.deepcopy(cards["dev"]), copy.deepcopy(cards["holdout"])
    parent = _resolve({"dev": dev, "holdout": holdout}[phase], path[:-1])
    del parent[path[-1]]

    with pytest.raises(KeyError) as exc:
        _evaluate(dev, holdout)
    assert exc.value.args[0] == path[-1]
