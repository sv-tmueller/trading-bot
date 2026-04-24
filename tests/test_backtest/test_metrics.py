from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.runner import (
    _compute_aggregate_metrics,
    _compute_trade_metrics,
    _safe_float,
)


def _trades(returns_pct: list, pnls: list) -> pd.DataFrame:
    # ReturnPct expressed as fraction (0.05 = +5%), matching backtesting.py convention
    return pd.DataFrame({"ReturnPct": returns_pct, "PnL": pnls})


# ---------- _safe_float ----------

def test_safe_float_handles_nan():
    assert _safe_float(float("nan")) is None


def test_safe_float_handles_none():
    assert _safe_float(None) is None


def test_safe_float_converts_numeric():
    assert _safe_float(3.14) == 3.14
    assert _safe_float("2.5") == 2.5


# ---------- _compute_trade_metrics (per-ticker) ----------

def test_trade_metrics_mix_of_winners_and_losers():
    trades = _trades([0.05, 0.03, -0.02, -0.04], [500, 300, -200, -400])
    m = _compute_trade_metrics(trades)
    assert m["avg_winner_pct"] == pytest.approx(4.0)
    assert m["avg_loser_pct"] == pytest.approx(-3.0)
    assert m["winner_loser_ratio"] == pytest.approx(4.0 / 3.0)


def test_trade_metrics_all_winners():
    trades = _trades([0.05, 0.03], [500, 300])
    m = _compute_trade_metrics(trades)
    assert m["avg_winner_pct"] == pytest.approx(4.0)
    assert m["avg_loser_pct"] is None
    assert m["winner_loser_ratio"] is None  # no losers — ratio undefined


def test_trade_metrics_all_losers():
    trades = _trades([-0.05, -0.03], [-500, -300])
    m = _compute_trade_metrics(trades)
    assert m["avg_winner_pct"] is None
    assert m["avg_loser_pct"] == pytest.approx(-4.0)
    assert m["winner_loser_ratio"] is None  # no winners


def test_trade_metrics_empty():
    m = _compute_trade_metrics(pd.DataFrame(columns=["ReturnPct", "PnL"]))
    assert m["avg_winner_pct"] is None
    assert m["avg_loser_pct"] is None
    assert m["winner_loser_ratio"] is None


def test_trade_metrics_none_input():
    m = _compute_trade_metrics(None)
    assert m["avg_winner_pct"] is None
    assert m["avg_loser_pct"] is None
    assert m["winner_loser_ratio"] is None


# ---------- _compute_aggregate_metrics (pooled) ----------

def test_aggregate_metrics_pooled_profit_factor():
    trades = _trades(
        [0.05, 0.03, -0.02, -0.04],
        [500, 300, -200, -400],
    )
    agg = _compute_aggregate_metrics(trades)
    # gross wins 800, gross losses 600 → PF = 800/600 ≈ 1.333
    assert agg["profit_factor"] == pytest.approx(800 / 600)
    # Expectancy = mean ReturnPct × 100 = (0.05+0.03-0.02-0.04)/4 × 100 = 0.5
    assert agg["expectancy_pct"] == pytest.approx(0.5)
    assert agg["avg_winner_pct"] == pytest.approx(4.0)
    assert agg["avg_loser_pct"] == pytest.approx(-3.0)


def test_aggregate_metrics_all_winners_profit_factor_inf():
    trades = _trades([0.05, 0.03], [500, 300])
    agg = _compute_aggregate_metrics(trades)
    assert agg["profit_factor"] == float("inf")
    assert agg["avg_loser_pct"] is None


def test_aggregate_metrics_all_losers_profit_factor_none():
    trades = _trades([-0.05, -0.03], [-500, -300])
    agg = _compute_aggregate_metrics(trades)
    assert agg["profit_factor"] is None  # no wins — undefined, not infinite
    assert agg["avg_winner_pct"] is None


def test_aggregate_metrics_empty_returns_all_none():
    agg = _compute_aggregate_metrics(pd.DataFrame(columns=["ReturnPct", "PnL"]))
    assert agg["profit_factor"] is None
    assert agg["expectancy_pct"] is None
    assert agg["avg_winner_pct"] is None
    assert agg["avg_loser_pct"] is None
    assert agg["winner_loser_ratio"] is None
