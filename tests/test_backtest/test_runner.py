from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.runner import run_backtest


def _make_fixture(n: int = 90) -> pd.DataFrame:
    """Flat price — no crossover, so 0 trades. Safe to run 8× in tests."""
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    prices = np.full(n, 100.0)
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices * 1.005,
            "Low": prices * 0.995,
            "Close": prices.copy(),
            "Volume": np.full(n, 500_000.0),
        },
        index=dates,
    )


def test_run_backtest_returns_required_keys(mocker):
    mocker.patch("backtest.runner.fetch_data", return_value=_make_fixture())
    mocker.patch("backtest.runner.notify_backtest")

    result = run_backtest(years=1)

    assert "aggregate" in result
    assert "tickers" in result
    assert "params" in result
    assert "period" in result


def test_run_backtest_aggregate_has_required_fields(mocker):
    mocker.patch("backtest.runner.fetch_data", return_value=_make_fixture())
    mocker.patch("backtest.runner.notify_backtest")

    result = run_backtest(years=1)

    agg = result["aggregate"]
    assert set(agg.keys()) == {"trades", "win_rate", "total_return", "max_drawdown"}


def test_run_backtest_stores_param_overrides(mocker):
    mocker.patch("backtest.runner.fetch_data", return_value=_make_fixture())
    mocker.patch("backtest.runner.notify_backtest")

    result = run_backtest(ema_fast=10, ema_slow=30, years=2)

    assert result["params"]["ema_fast"] == 10
    assert result["params"]["ema_slow"] == 30
    assert result["params"]["years"] == 2


def test_run_backtest_covers_all_watchlist_tickers(mocker):
    from config.watchlist import WATCHLIST

    mock_fetch = mocker.patch("backtest.runner.fetch_data", return_value=_make_fixture())
    mocker.patch("backtest.runner.notify_backtest")

    result = run_backtest(years=1)

    assert mock_fetch.call_count == len(WATCHLIST)
    assert set(result["tickers"].keys()) == set(WATCHLIST)


def test_run_backtest_calls_notify(mocker):
    mocker.patch("backtest.runner.fetch_data", return_value=_make_fixture())
    mock_notify = mocker.patch("backtest.runner.notify_backtest")

    run_backtest(years=1)

    mock_notify.assert_called_once()


def test_run_backtest_default_years_is_3(mocker):
    mocker.patch("backtest.runner.fetch_data", return_value=_make_fixture())
    mocker.patch("backtest.runner.notify_backtest")

    result = run_backtest()

    assert result["params"]["years"] == 3
