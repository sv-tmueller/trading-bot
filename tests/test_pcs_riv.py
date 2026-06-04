"""Tests for backtest/pcs_riv.py — the Put-Credit-Spread-on-Regime+IV harness.

Deterministic synthetic worlds (ModeledSource + injected SPY/VIX series), one per
entry/exit branch. `sma_days=3` keeps the regime window tiny.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backtest.options_data import ModeledSource
from backtest.pcs_riv import run_pcs_riv_backtest

START = date(2024, 6, 3)


def _dates(n: int) -> list:
    return [START + timedelta(days=i) for i in range(n)]


def _world(path, *, iv="up", spread_frac=0.0):
    """Build (source, spy_closes, trading_dates, iv_series) from a price path."""
    dates = _dates(len(path))
    prices = {d: p for d, p in zip(dates, path)}
    ivs = {d: 0.20 for d in dates}  # flat pricing vol for the options
    source = ModeledSource(prices, ivs, spread_frac=spread_frac)
    if iv == "up":  # current is always the max -> IV-rank ~100
        iv_series = {d: 10.0 + i for i, d in enumerate(dates)}
    else:  # current is always the min -> IV-rank ~0
        iv_series = {d: 100.0 - i for i, d in enumerate(dates)}
    return source, prices, dates, iv_series


def _run(source, spy_closes, dates, iv_series, **kw):
    return run_pcs_riv_backtest(
        source=source,
        underlyings=["SPY"],
        spy_closes=spy_closes,
        iv_series=iv_series,
        trading_dates=dates,
        sma_days=3,
        iv_rank_threshold=30.0,
        **kw,
    )


def test_no_entry_when_bearish():
    # Strictly declining -> close < SMA(3) -> never bullish. IV is high (isolates regime).
    source, prices, dates, iv_series = _world([110 - i for i in range(10)], iv="up")
    res = _run(source, prices, dates, iv_series)
    assert res["trade_count"] == 0
    assert res["ending_equity"] == pytest.approx(res["starting_cash"])


def test_no_entry_when_iv_rank_below_threshold():
    # Rising -> bullish, but IV-rank ~0 -> gate blocks entry.
    source, prices, dates, iv_series = _world([100 + i for i in range(10)], iv="down")
    res = _run(source, prices, dates, iv_series)
    assert res["trade_count"] == 0


def test_profit_target_exit_on_up_gap():
    # Rising-bullish entry, then a gap up collapses the puts -> captured >= 50% of credit.
    path = [100, 101, 102, 130, 130, 130, 130, 130, 130, 130, 130, 130]
    source, prices, dates, iv_series = _world(path, iv="up")
    res = _run(source, prices, dates, iv_series)
    assert res["trade_count"] >= 1
    first = res["trades"][0]
    assert first["exit_reason"] == "profit_target"
    assert first["pnl"] > 0


def test_regime_flip_exit_on_crash():
    # Rising-bullish entry, then an immediate crash flips the regime bearish -> close.
    path = [100, 101, 102, 80, 80, 80, 80, 80]
    source, prices, dates, iv_series = _world(path, iv="up")
    res = _run(source, prices, dates, iv_series)
    assert res["trade_count"] >= 1
    assert res["trades"][0]["exit_reason"] == "regime_flip"


def test_mid_fills_beat_spread_fills():
    # Same profitable world; conservative bid/ask fills must underperform mid fills.
    path = [100, 101, 102, 130, 130, 130, 130, 130, 130, 130, 130, 130]
    mid = _run(*_world(path, iv="up", spread_frac=0.0))
    spread = _run(*_world(path, iv="up", spread_frac=0.10))
    assert mid["ending_equity"] > spread["ending_equity"]


def test_result_has_expected_metric_keys():
    source, prices, dates, iv_series = _world([100, 101, 102, 130, 130, 130, 130, 130], iv="up")
    res = _run(source, prices, dates, iv_series)
    for k in ("starting_cash", "ending_equity", "total_return", "cagr",
              "max_drawdown", "sharpe", "trade_count", "win_rate", "profit_factor",
              "trades", "equity_curve"):
        assert k in res
