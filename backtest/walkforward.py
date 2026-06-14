"""Walk-forward OOS stability analysis for the 200-DMA regime rule.

Splits the full history into non-overlapping test windows. Each window has a
pre-roll (warm-up) period prepended so signals are valid from test_start. All
five strategies run through the identical simulate_from_signal execution model.
Metrics are computed on the test sub-window only (Trap A).

Usage
-----
    venv/bin/python -m backtest.walkforward --vehicle UPRO --start 2015-01-01

This script is research-only. It lives in backtest/ and must never be imported
by supabase/functions/. No LLM, no broker calls.
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from backtest.baselines import (
    buy_and_hold_signal,
    faber_sma_signal,
    persistence_signal,
    tsmom_signal,
)
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, simulate_from_signal

# Maximum lookback in trading days across all five strategies.
# TSMOM needs 12 monthly closes ≈ 13–14 calendar months ≈ 275 trading days.
# 200-DMA needs 200 trading days.
_MAX_LOOKBACK_DAYS = 300


def _fetch(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch Open/Close from yfinance. Patchable seam for offline tests."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def _slice_windows(
    all_dates: pd.DatetimeIndex,
    test_start: date,
    window_months: int,
    max_lookback_days: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Generate non-overlapping (pre_roll_start, test_start, test_end) tuples.

    Each window's pre-roll extends ``max_lookback_days`` before test_start so
    all signals are valid at the first test day. Windows are calendar-aligned
    (test boundaries at approximately month boundaries).

    Parameters
    ----------
    all_dates:
        Full sorted business-day index of available data.
    test_start:
        Date of the first test window's start (inclusive).
    window_months:
        Length of each test sub-window in calendar months.
    max_lookback_days:
        Pre-roll length in trading days.

    Returns
    -------
    List of (pre_roll_start, ts, te) Timestamps.
    """
    windows: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    ts = pd.Timestamp(test_start)

    while True:
        te = ts + pd.DateOffset(months=window_months) - pd.offsets.BDay(1)
        # Snap te to the last available date if we overshoot
        if te > all_dates[-1]:
            te = all_dates[-1]
        if ts > all_dates[-1]:
            break
        if ts > te:
            break

        # Pre-roll start: max_lookback_days before ts in the business-day index
        ts_pos = all_dates.searchsorted(ts, side="left")
        pr_pos = max(0, ts_pos - max_lookback_days)
        pr_start = all_dates[pr_pos]

        windows.append((pr_start, ts, te))

        # Next window: advance by window_months from ts
        next_ts = ts + pd.DateOffset(months=window_months)
        if next_ts > all_dates[-1]:
            break
        ts = next_ts

    return windows


def _compute_window_metrics(
    equity_slice: pd.Series,
    trades: list[dict],
    starting_cash: float,
) -> dict:
    """Compute return, vol, maxDD, Sharpe on the equity_slice.

    Sharpe convention (matches backtest/run_pcs_riv.py::_buy_and_hold):
        daily_returns = equity.pct_change().dropna()
        sharpe = mean(rets) / std(rets, ddof=1) * sqrt(252)
        rf = 0
    """
    total_return = float(equity_slice.iloc[-1] / equity_slice.iloc[0] - 1)
    rolling_max = equity_slice.cummax()
    max_dd = float(((equity_slice - rolling_max) / rolling_max).min())

    daily_rets = equity_slice.pct_change().dropna()
    n = len(daily_rets)
    if n >= 2:
        mean_r = float(daily_rets.mean())
        std_r = float(daily_rets.std(ddof=1))
        sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0.0
        annualized_vol = std_r * (252 ** 0.5)
    else:
        sharpe = 0.0
        annualized_vol = 0.0

    # Flip count: number of regime-flip exits (excludes end-of-window close)
    flip_count = sum(1 for t in trades if t.get("exit_reason") == "regime_flip")

    return {
        "total_return": total_return,
        "annualized_vol": annualized_vol,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "flip_count": flip_count,
    }


def run_walkforward(
    *,
    benchmark_ticker: str = "SPY",
    vehicle_ticker: str = "UPRO",
    start: date,
    end: date,
    window_months: int = 12,
    starting_cash: float = 100_000.0,
) -> list[dict]:
    """Run five strategies over non-overlapping OOS windows.

    Parameters
    ----------
    benchmark_ticker:
        Ticker for the regime signal computation (typically SPY).
    vehicle_ticker:
        Ticker for execution (typically UPRO).
    start:
        First test window start date.
    end:
        Last date to include in analysis.
    window_months:
        Length of each test window in calendar months.
    starting_cash:
        Initial capital per window.

    Returns
    -------
    List of per-window per-strategy result dicts with keys:
    ``window``, ``strategy``, ``total_return``, ``annualized_vol``,
    ``max_drawdown``, ``sharpe``, ``flip_count``.
    """
    # Fetch full series once — from max_lookback before start through end
    full_start = pd.Timestamp(start) - pd.DateOffset(days=_MAX_LOOKBACK_DAYS * 2)
    benchmark_full = _fetch(benchmark_ticker, full_start.date(), end)
    vehicle_full = _fetch(vehicle_ticker, full_start.date(), end)

    # Align on common business days
    common = benchmark_full.index.intersection(vehicle_full.index)
    benchmark_full = benchmark_full.loc[common]
    vehicle_full = vehicle_full.loc[common]

    windows = _slice_windows(
        all_dates=common,
        test_start=start,
        window_months=window_months,
        max_lookback_days=_MAX_LOOKBACK_DAYS,
    )

    rows: list[dict] = []

    for pr_start, ts, te in windows:
        window_label = f"{ts.date()} / {te.date()}"

        # Slice the full data to the pre-rolled window [pr_start, te]
        mask = (common >= pr_start) & (common <= te)
        bench_w = benchmark_full.loc[mask]
        veh_w = vehicle_full.loc[mask]

        bench_close = bench_w["Close"]

        # Build all five signals on the pre-rolled window
        # 1. 200-DMA regime
        sma200 = bench_close.rolling(200).mean()
        sig_200dma = (bench_close > sma200).fillna(False)

        # 2-5. Baselines (signal on benchmark close, execute on vehicle)
        sig_bah = buy_and_hold_signal(bench_close)
        sig_pers = persistence_signal(bench_close)
        sig_faber = faber_sma_signal(bench_close)
        sig_tsmom = tsmom_signal(bench_close)

        strategies = [
            ("200dma", sig_200dma),
            ("buy_and_hold", sig_bah),
            ("persistence", sig_pers),
            ("faber", sig_faber),
            ("tsmom", sig_tsmom),
        ]

        for strat_name, is_bullish in strategies:
            sim = simulate_from_signal(
                vehicle_df=veh_w,
                is_bullish_close_t=is_bullish,
                starting_cash=starting_cash,
                slippage_bps=SLIPPAGE_BPS,
                commission_bps=COMMISSION_BPS,
            )

            # Trap A: compute metrics on the test sub-window [ts, te] only.
            # The pre-roll is used only for signal warm-up.
            eq_full = sim["equity_curve"]
            test_mask = (eq_full.index >= ts) & (eq_full.index <= te)
            eq_test = eq_full.loc[test_mask]

            if len(eq_test) < 2:
                continue  # insufficient test data for this window/strategy

            # Trades that closed within [ts, te]
            test_trades = [
                t for t in sim["trades"]
                if t["exit_date"] >= ts and t["exit_date"] <= te
            ]

            metrics = _compute_window_metrics(
                equity_slice=eq_test,
                trades=test_trades,
                starting_cash=starting_cash,
            )

            rows.append({
                "window": window_label,
                "strategy": strat_name,
                **metrics,
            })

    return rows


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Print a per-window OOS table."""
    parser = argparse.ArgumentParser(prog="backtest.walkforward")
    parser.add_argument("--vehicle", default="UPRO", help="vehicle ticker (default UPRO)")
    parser.add_argument("--benchmark", default="SPY", help="benchmark ticker (default SPY)")
    parser.add_argument(
        "--window-months", type=int, default=12,
        help="OOS window length in months (default 12)",
    )
    parser.add_argument("--start", default="2010-01-01", help="first test window start (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="last date (default today)")
    args = parser.parse_args(argv)

    start_dt = date.fromisoformat(args.start)
    end_dt = date.fromisoformat(args.end) if args.end else date.today()

    print(f"Walk-forward OOS  vehicle={args.vehicle}  benchmark={args.benchmark}")
    print(f"Window: {args.window_months} months  |  {start_dt} -> {end_dt}")
    print()

    results = run_walkforward(
        benchmark_ticker=args.benchmark,
        vehicle_ticker=args.vehicle,
        start=start_dt,
        end=end_dt,
        window_months=args.window_months,
    )

    if not results:
        print("No windows generated — try a wider date range.")
        return 1

    # Print table
    header = (
        f"{'window':<28} {'strategy':<15} {'return':>8} {'vol':>7} "
        f"{'maxDD':>8} {'sharpe':>7} {'flips':>6}"
    )
    print(header)
    print("-" * len(header))

    current_window = None
    for row in results:
        if row["window"] != current_window:
            if current_window is not None:
                print()
            current_window = row["window"]
        print(
            f"{row['window']:<28} {row['strategy']:<15} "
            f"{row['total_return']*100:>7.1f}% {row['annualized_vol']*100:>6.1f}% "
            f"{row['max_drawdown']*100:>7.1f}% {row['sharpe']:>7.2f} "
            f"{row['flip_count']:>6}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
