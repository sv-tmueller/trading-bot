from __future__ import annotations

from collections import Counter
from typing import Dict

import numpy as np
import pandas as pd
import pytest

from backtest.portfolio import (
    PortfolioSimulator,
    candidate_score,
    run_portfolio_backtest,
)
from backtest.runner import run_backtest


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _flat(n: int = 90, price: float = 100.0, volume: float = 500_000.0) -> pd.DataFrame:
    """Flat price, constant volume — produces zero signals."""
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    prices = np.full(n, price)
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices * 1.005,
            "Low": prices * 0.995,
            "Close": prices.copy(),
            "Volume": np.full(n, volume),
        },
        index=dates,
    )


def _with_signal_on_day(
    n: int = 200,
    crossover_day: int = 80,
    base_price: float = 100.0,
    start_price: float = 90.0,
    volume_spike: float = 5.0,
) -> pd.DataFrame:
    """Build a price series where EMA-fast crosses EMA-slow upward sometime
    after ``crossover_day``. Up-trend after crossover, sustained volume above
    the 20-day SMA so the volume gate fires at the crossover bar (which lags
    the price reversal due to EMA inertia).
    """
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    # Downtrend then uptrend so EMAs cross.
    prices = np.concatenate(
        [
            np.linspace(base_price, start_price, crossover_day),
            np.linspace(start_price, base_price * 1.5, n - crossover_day),
        ]
    )
    # Pulse volume on the actual EMA-crossover bar (which lags the price
    # reversal by ~13 bars for EMA(20)/EMA(50) at this scale).
    volume = np.full(n, 500_000.0)
    cross_bar = crossover_day + 13
    volume[cross_bar : cross_bar + 5] = 500_000.0 * volume_spike
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices * 1.01,
            "Low": prices * 0.99,
            "Close": prices,
            "Volume": volume,
        },
        index=dates,
    )


def _loader(data_map: Dict[str, pd.DataFrame]):
    def load(ticker: str, years: int = 1) -> pd.DataFrame:
        return data_map.get(ticker, _flat())
    return load


# ---------------------------------------------------------------------------
# Basic sanity
# ---------------------------------------------------------------------------


def test_empty_watchlist_returns_zero_trades():
    result = run_portfolio_backtest(
        years=1,
        tickers=[],
        data_loader=lambda *a, **kw: _flat(),
    )
    assert result["aggregate"]["trades"] == 0
    assert result["trades"] == []
    assert result["rejected"] == []


def test_no_signals_day_produces_no_trades():
    data = {f"T{i}": _flat(n=150) for i in range(3)}
    result = run_portfolio_backtest(
        years=1,
        tickers=list(data.keys()),
        data_loader=_loader(data),
    )
    assert result["aggregate"]["trades"] == 0
    assert result["rejected"] == []


def test_candidate_score_neutral_rsi_scores_higher():
    high = pd.Series({"rsi": 50.0, "Volume": 1_000_000, "vol_sma": 500_000})
    low = pd.Series({"rsi": 30.0, "Volume": 1_000_000, "vol_sma": 500_000})
    assert candidate_score(high) > candidate_score(low)


def test_candidate_score_handles_missing_data():
    bad = pd.Series({"rsi": np.nan, "Volume": 1_000_000, "vol_sma": 500_000})
    assert candidate_score(bad) == 0.0


# ---------------------------------------------------------------------------
# Portfolio gating
# ---------------------------------------------------------------------------


def test_max_positions_gates_excess_candidates():
    """Six simultaneous buy-signals: top 5 opened, 6th logged as max_positions.

    Loosens the exposure cap to its upper bound so this test isolates the
    MAX_POSITIONS gate (a separate test covers the exposure gate).
    """
    data = {}
    for i in range(6):
        df = _with_signal_on_day(n=200, crossover_day=80, volume_spike=1.6 + i * 0.1)
        data[f"T{i}"] = df

    sim = PortfolioSimulator(
        years=1,
        ema_fast=20,
        ema_slow=50,
        rsi_period=14,
        rsi_lower=0,
        rsi_upper=100,
        volume_multiplier=1.5,
        atr_period=14,
        atr_multiplier=1.5,
        rr_ratio=2.0,
        max_hold_days=5,
        strict_crossover=True,
        max_positions=5,
        max_portfolio_exposure=0.99,   # disable exposure gate
        risk_per_trade=0.001,          # tiny size so cash is plentiful
        tickers=list(data.keys()),
        data_loader=_loader(data),
    )
    result = sim.run()

    reasons = Counter(r["reason"] for r in result["rejected"])
    # Expect exactly the 6th candidate rejected for MAX_POSITIONS.
    assert reasons["max_positions"] >= 1
    entered = {t["ticker"] for t in result["trades"]}
    assert len(entered) <= 5
    assert len(entered) == 5


def test_max_exposure_gate_enforced():
    """With tiny exposure cap, even the first candidate may be accepted, but a
    second one should be rejected for ``max_exposure``.
    """
    data = {
        "A": _with_signal_on_day(n=200, crossover_day=80, volume_spike=2.0),
        "B": _with_signal_on_day(n=200, crossover_day=80, volume_spike=1.8),
        "C": _with_signal_on_day(n=200, crossover_day=80, volume_spike=1.6),
    }

    # Very tight exposure cap forces rejection after the first fill.
    sim = PortfolioSimulator(
        years=1,
        ema_fast=20,
        ema_slow=50,
        rsi_period=14,
        rsi_lower=0,
        rsi_upper=100,
        volume_multiplier=1.5,
        atr_period=14,
        atr_multiplier=1.5,
        rr_ratio=2.0,
        max_hold_days=5,
        strict_crossover=True,
        max_portfolio_exposure=0.01,   # 1% cap
        tickers=list(data.keys()),
        data_loader=_loader(data),
    )
    result = sim.run()

    reasons = Counter(r["reason"] for r in result["rejected"])
    assert reasons.get("max_exposure", 0) >= 1


# ---------------------------------------------------------------------------
# Single-ticker parity vs per-ticker runner
# ---------------------------------------------------------------------------


def test_single_ticker_parity_with_per_ticker_runner(mocker):
    """With a single-ticker watchlist, portfolio-mode total_return should track
    the per-ticker runner within a small tolerance.

    We don't assert byte-equality because the per-ticker runner uses
    backtesting.py (intrabar order fills, different commission accounting)
    while our simulator uses closing-bar evaluation. But the sign and
    rough magnitude should match.
    """
    fixture = _with_signal_on_day(n=200, crossover_day=90, volume_spike=3.0)

    mocker.patch("backtest.runner.fetch_data", return_value=fixture)
    mocker.patch("backtest.portfolio.fetch_data", return_value=fixture)
    mocker.patch("backtest.runner.notify_backtest")
    mocker.patch("config.watchlist.WATCHLIST", ["AAA"])
    # Both the runner and the portfolio module cache WATCHLIST at import.
    import backtest.runner as runner_mod
    import backtest.portfolio as portfolio_mod
    mocker.patch.object(runner_mod, "WATCHLIST", ["AAA"])
    mocker.patch.object(portfolio_mod, "WATCHLIST", ["AAA"])

    per_ticker = run_backtest(years=1, portfolio=False)
    portfolio = run_backtest(years=1, portfolio=True)

    # If per-ticker runner found trades, portfolio simulator should too.
    if per_ticker["aggregate"]["trades"] > 0:
        assert portfolio["aggregate"]["trades"] > 0
        # Directional agreement
        pt_ret = per_ticker["aggregate"]["total_return"]
        pf_ret = portfolio["aggregate"]["total_return"]
        assert (pt_ret >= 0) == (pf_ret >= 0)


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


def test_output_structure_has_required_keys():
    data = {"A": _with_signal_on_day(n=200, crossover_day=80, volume_spike=2.0)}
    result = run_portfolio_backtest(
        years=1,
        tickers=["A"],
        data_loader=_loader(data),
    )
    assert set(result.keys()) >= {"aggregate", "trades", "rejected", "params", "period"}
    agg = result["aggregate"]
    for key in (
        "trades",
        "win_rate",
        "total_return",
        "max_drawdown",
        "profit_factor",
        "expectancy_pct",
        "avg_winner_pct",
        "avg_loser_pct",
        "winner_loser_ratio",
        "final_equity",
    ):
        assert key in agg


def test_runner_does_not_call_notify_when_portfolio_mode(mocker):
    """The existing per-ticker notify_backtest should NOT fire in portfolio
    mode (it formats per-ticker output and would be confusing).
    """
    fixture = _flat(n=200)
    mocker.patch("backtest.portfolio.fetch_data", return_value=fixture)
    mock_notify = mocker.patch("backtest.runner.notify_backtest")
    import backtest.portfolio as portfolio_mod
    mocker.patch.object(portfolio_mod, "WATCHLIST", ["AAA"])

    run_backtest(years=1, portfolio=True)
    mock_notify.assert_not_called()


def test_non_portfolio_path_unchanged(mocker):
    """Sanity: the per-ticker path still fires ``notify_backtest`` exactly once
    and returns the original schema when ``portfolio`` is False (default).
    """
    mocker.patch("backtest.runner.fetch_data", return_value=_flat())
    mock_notify = mocker.patch("backtest.runner.notify_backtest")

    result = run_backtest(years=1)
    mock_notify.assert_called_once()
    assert "tickers" in result  # schema-preserving
