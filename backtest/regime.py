"""Backtest the 200-DMA regime filter on a single vehicle.

Simulation rules (matching the live bot's behaviour as closely as possible):
- Daily decision: at end of day, compute SMA(sma_days) on benchmark closes.
- Trade execution: next day's open. Slippage modeled via `slippage_bps`.
- Commission: bps of notional, applied per round trip.
- Binary in/out: on LONG, deploy 100% of available cash into the vehicle.
- Cash earns 0% (conservative).
- Kill-switch: NOT modelled here. Backtest is for the regime rule alone;
  kill-switch is a separate operational protection. Modelling it would
  require intraday data we don't have in the daily-bar yfinance feed.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    exit_reason: str  # "regime_flip"


STARTING_CASH = 100_000.0
SLIPPAGE_BPS = 5  # 0.05% per side
COMMISSION_BPS = 5  # 0.05% per side


def _fetch(ticker: str, start: date, end: date) -> pd.Series:
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def run_regime_backtest(
    *,
    benchmark_ticker: str = "SPY",
    vehicle_ticker: str = "UPRO",
    start: date,
    end: date,
    sma_days: int = 200,
    starting_cash: float = STARTING_CASH,
) -> dict:
    """Run the regime-filter backtest. Returns headline metrics + trade list.

    Result keys: total_return, cagr, max_drawdown, trade_count, ending_equity,
                 starting_cash, trades (list of dicts), equity_curve (pd.Series).
    """
    benchmark = _fetch(benchmark_ticker, start, end)
    vehicle = _fetch(vehicle_ticker, start, end)

    # Align on common dates
    common = benchmark.index.intersection(vehicle.index)
    benchmark = benchmark.loc[common]
    vehicle = vehicle.loc[common]

    # SMA on benchmark close
    sma = benchmark["Close"].rolling(sma_days).mean()
    is_bullish = (benchmark["Close"] > sma).fillna(False)

    # Trade at next open after the signal day
    signal = is_bullish.shift(1).fillna(False)

    # Simulation
    equity_curve = []
    cash = starting_cash
    qty = 0
    entry_price = 0.0
    entry_date: Optional[pd.Timestamp] = None
    trades: list[Trade] = []

    for i, ts in enumerate(common):
        open_px = float(vehicle["Open"].iloc[i])
        close_px = float(vehicle["Close"].iloc[i])
        want_long = bool(signal.iloc[i])

        # Open-of-day execution
        if want_long and qty == 0 and not np.isnan(sma.iloc[i - 1] if i > 0 else np.nan):
            # Buy at open, with slippage + commission
            execution_px = open_px * (1 + SLIPPAGE_BPS / 10_000)
            qty = int(cash / execution_px / (1 + COMMISSION_BPS / 10_000))
            cost = qty * execution_px * (1 + COMMISSION_BPS / 10_000)
            cash -= cost
            entry_price = execution_px
            entry_date = ts
        elif not want_long and qty > 0:
            # Sell at open
            execution_px = open_px * (1 - SLIPPAGE_BPS / 10_000)
            proceeds = qty * execution_px * (1 - COMMISSION_BPS / 10_000)
            cash += proceeds
            pnl = proceeds - (qty * entry_price * (1 + COMMISSION_BPS / 10_000))
            trades.append(Trade(
                entry_date=entry_date, exit_date=ts,
                entry_price=entry_price, exit_price=execution_px,
                qty=qty, pnl=pnl,
                return_pct=(execution_px / entry_price - 1),
                exit_reason="regime_flip",
            ))
            qty = 0
            entry_price = 0.0
            entry_date = None

        # Mark equity to close
        eq = cash + qty * close_px
        equity_curve.append((ts, eq))

    # Close any open position at last close
    if qty > 0:
        last_ts = common[-1]
        last_close = float(vehicle["Close"].iloc[-1])
        execution_px = last_close * (1 - SLIPPAGE_BPS / 10_000)
        proceeds = qty * execution_px * (1 - COMMISSION_BPS / 10_000)
        cash += proceeds
        pnl = proceeds - (qty * entry_price * (1 + COMMISSION_BPS / 10_000))
        trades.append(Trade(
            entry_date=entry_date, exit_date=last_ts,
            entry_price=entry_price, exit_price=execution_px,
            qty=qty, pnl=pnl,
            return_pct=(execution_px / entry_price - 1),
            exit_reason="end_of_window",
        ))

    eq_series = pd.Series(dict(equity_curve))
    total_return = float(eq_series.iloc[-1] / starting_cash - 1)
    n_years = (end - start).days / 365.25
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
    rolling_max = eq_series.cummax()
    max_dd = float(((eq_series - rolling_max) / rolling_max).min())

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
        "ending_equity": float(eq_series.iloc[-1]),
        "starting_cash": starting_cash,
        "trades": [t.__dict__ for t in trades],
        "equity_curve": eq_series,
    }


def main_cli() -> None:
    """Command-line wrapper for ad-hoc runs (called by main.py backtest)."""
    import argparse
    from datetime import date as _date

    parser = argparse.ArgumentParser(prog="backtest.regime")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--vehicle", default="UPRO")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--sma", type=int, default=200)
    args = parser.parse_args()

    end = _date.today()
    try:
        start = _date(end.year - args.years, end.month, end.day)
    except ValueError:
        start = _date(end.year - args.years, end.month, 28)

    result = run_regime_backtest(
        benchmark_ticker=args.benchmark,
        vehicle_ticker=args.vehicle,
        start=start, end=end,
        sma_days=args.sma,
    )
    print(f"Period: {start} -> {end}  ({args.years}y)")
    print(f"Vehicle: {args.vehicle}  Benchmark: {args.benchmark}  SMA: {args.sma}")
    print(f"Total return:    {result['total_return']*100:+.2f}%")
    print(f"CAGR:            {result['cagr']*100:+.2f}%")
    print(f"Max drawdown:    {result['max_drawdown']*100:+.2f}%")
    print(f"Trade count:     {result['trade_count']}")
    print(f"Ending equity:   ${result['ending_equity']:,.2f}")


if __name__ == "__main__":
    main_cli()
