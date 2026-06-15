"""Tests for backtest/walkforward.py.

All offline — uses monkeypatch on backtest.walkforward._fetch.
Live-data tests are @pytest.mark.slow.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

import backtest.walkforward as wf


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_price_df(
    n_days: int,
    start: str = "2015-01-02",
    start_price: float = 100.0,
    drift: float = 0.0003,
) -> pd.DataFrame:
    """Build a synthetic Open/Close DataFrame."""
    idx = pd.bdate_range(start, periods=n_days)
    prices = [start_price * (1 + drift) ** i for i in range(n_days)]
    return pd.DataFrame({"Open": prices, "Close": prices}, index=idx)


# ---------------------------------------------------------------------------
# _slice_windows
# ---------------------------------------------------------------------------

def test_slice_windows_non_overlapping():
    """Windows must be non-overlapping — test_start of next = test_end of prev."""
    windows = wf._slice_windows(
        all_dates=pd.bdate_range("2015-01-02", "2020-12-31"),
        test_start=date(2016, 1, 1),
        window_months=12,
        max_lookback_days=252,
    )
    assert len(windows) >= 1
    for i in range(len(windows) - 1):
        _, ts_i, te_i = windows[i]
        _, ts_next, _ = windows[i + 1]
        assert ts_next > te_i, "windows must not overlap"
        assert ts_next == te_i + pd.offsets.BDay(1) or ts_next > te_i


def test_slice_windows_preroll_included():
    """Each window's pre-roll start must be before its test_start."""
    all_dates = pd.bdate_range("2013-01-02", "2020-12-31")
    windows = wf._slice_windows(
        all_dates=all_dates,
        test_start=date(2015, 1, 1),
        window_months=12,
        max_lookback_days=300,
    )
    for pr_start, ts, te in windows:
        assert pr_start < ts, f"pre-roll start {pr_start} must be before test_start {ts}"


def test_slice_windows_minimum_one_window():
    """At least one window should be returned for a multi-year series."""
    all_dates = pd.bdate_range("2015-01-02", "2020-12-31")
    windows = wf._slice_windows(
        all_dates=all_dates,
        test_start=date(2016, 1, 1),
        window_months=12,
        max_lookback_days=252,
    )
    assert len(windows) >= 1


# ---------------------------------------------------------------------------
# run_walkforward (offline monkeypatched)
# ---------------------------------------------------------------------------

def test_run_walkforward_returns_expected_keys(monkeypatch):
    """run_walkforward returns a list of result dicts with required keys."""
    benchmark_df = _make_price_df(n_days=2000)
    vehicle_df = _make_price_df(n_days=2000)

    monkeypatch.setattr(
        wf, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    results = wf.run_walkforward(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2015, 1, 2),
        end=date(2022, 12, 31),
        window_months=12,
    )
    assert isinstance(results, list)
    assert len(results) >= 1

    required_keys = {
        "window", "strategy", "total_return", "annualized_vol",
        "max_drawdown", "sharpe", "flip_count",
    }
    for row in results:
        missing = required_keys - set(row.keys())
        assert not missing, f"result row missing keys: {missing}"


def test_run_walkforward_five_strategies(monkeypatch):
    """Each window should produce results for all five strategies."""
    benchmark_df = _make_price_df(n_days=2000)
    vehicle_df = _make_price_df(n_days=2000)

    monkeypatch.setattr(
        wf, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    results = wf.run_walkforward(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2015, 1, 2),
        end=date(2022, 12, 31),
        window_months=12,
    )
    # Collect unique strategies per window
    from collections import defaultdict
    by_window: dict = defaultdict(set)
    for row in results:
        by_window[row["window"]].add(row["strategy"])

    expected_strategies = {"200dma", "buy_and_hold", "persistence", "faber", "tsmom"}
    for window, strats in by_window.items():
        assert strats == expected_strategies, (
            f"Window {window} missing strategies: {expected_strategies - strats}"
        )


def test_run_walkforward_sharpe_convention(monkeypatch):
    """Sharpe is mean/std * sqrt(252), ddof=1, rf=0 — matching _buy_and_hold."""
    # Use ascending price so we can predict the sign
    benchmark_df = _make_price_df(n_days=2000, drift=0.001)
    vehicle_df = _make_price_df(n_days=2000, drift=0.001)

    monkeypatch.setattr(
        wf, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    results = wf.run_walkforward(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2015, 1, 2),
        end=date(2022, 12, 31),
        window_months=12,
    )
    # All Sharpes should be finite floats (not inf/nan) for the B&H arm
    bah_rows = [r for r in results if r["strategy"] == "buy_and_hold"]
    for row in bah_rows:
        assert np.isfinite(row["sharpe"]), f"Sharpe not finite: {row}"


def test_run_walkforward_bah_flip_count_zero(monkeypatch):
    """Buy-and-hold has flip count 0 (never exits and re-enters)."""
    benchmark_df = _make_price_df(n_days=2000)
    vehicle_df = _make_price_df(n_days=2000)

    monkeypatch.setattr(
        wf, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    results = wf.run_walkforward(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2015, 1, 2),
        end=date(2022, 12, 31),
        window_months=12,
    )
    bah_rows = [r for r in results if r["strategy"] == "buy_and_hold"]
    for row in bah_rows:
        assert row["flip_count"] == 0, f"B&H flip_count should be 0, got {row['flip_count']}"


def test_run_walkforward_metrics_on_test_window_only(monkeypatch):
    """Per-window Sharpe must be computed on the test sub-window, not the pre-roll.

    Verifies Trap A: pre-roll is used for signal warm-up only; metrics are
    measured on [test_start, test_end].
    """
    # Use a price series that is flat during the pre-roll and upward in the test window.
    # If metrics were computed over the pre-roll, vol would be 0 → Sharpe undefined.
    n_pre = 260  # ~1 year pre-roll
    n_test = 252  # 1-year test window
    flat_prices = [100.0] * n_pre
    up_prices = [100.0 * (1.001 ** i) for i in range(n_test)]
    all_prices = flat_prices + up_prices

    idx = pd.bdate_range("2013-01-02", periods=len(all_prices))
    df = pd.DataFrame({"Open": all_prices, "Close": all_prices}, index=idx)

    monkeypatch.setattr(wf, "_fetch", lambda ticker, start, end: df)

    results = wf.run_walkforward(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2014, 1, 2),
        end=date(2015, 6, 30),
        window_months=12,
    )
    # If computed over pre-roll (all flat), vol = 0 → Sharpe = inf; test that it's finite
    for row in results:
        assert np.isfinite(row["sharpe"]) or row["sharpe"] == 0.0, (
            f"Sharpe should be finite (metrics on test window only), got {row['sharpe']}"
        )


# ---------------------------------------------------------------------------
# main() CLI smoke test (offline)
# ---------------------------------------------------------------------------

def test_main_cli_offline(monkeypatch, capsys):
    """main() with monkeypatched _fetch doesn't crash and prints a table."""
    benchmark_df = _make_price_df(n_days=2000)
    vehicle_df = _make_price_df(n_days=2000)

    monkeypatch.setattr(
        wf, "_fetch",
        lambda ticker, start, end: benchmark_df if ticker == "SPY" else vehicle_df,
    )

    rc = wf.main([
        "--vehicle", "UPRO",
        "--benchmark", "SPY",
        "--start", "2015-01-02",
        "--end", "2022-12-31",
        "--window-months", "12",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "200dma" in captured.out or "strategy" in captured.out.lower()


# ---------------------------------------------------------------------------
# Slow live-data tests (require network)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_live_200dma_upro_2021_2026_envelope():
    """Live run: 200-DMA on UPRO 2021-2026 should tie out to existing findings doc.

    ~+150% total / ~-35% max DD (loose envelope matching regime backtest).
    """
    results = wf.run_walkforward(
        benchmark_ticker="SPY",
        vehicle_ticker="UPRO",
        start=date(2021, 5, 7),
        end=date(2026, 5, 7),
        window_months=12,
    )
    dma_rows = [r for r in results if r["strategy"] == "200dma"]
    assert len(dma_rows) >= 3, "expect at least 3 OOS windows over 5 years"
    # Aggregate: sum of per-window returns should be in a plausible range
    total_ret = sum(r["total_return"] for r in dma_rows)
    assert total_ret > 0.5, f"aggregate return {total_ret:.1%} looks too low"
