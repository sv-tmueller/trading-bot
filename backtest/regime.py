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

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


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


def simulate_from_signal(
    *,
    vehicle_df: pd.DataFrame,
    is_bullish_close_t: pd.Series,
    starting_cash: float = STARTING_CASH,
    slippage_bps: int = SLIPPAGE_BPS,
    commission_bps: int = COMMISSION_BPS,
) -> dict:
    """Core signal→equity simulation loop shared by all strategies.

    Parameters
    ----------
    vehicle_df:
        DataFrame with columns Open and Close, indexed by trading date.
        Must share the same index as ``is_bullish_close_t``.
    is_bullish_close_t:
        Boolean (or NaN) Series at close-T. NaN → treated as flat (no entry).
        The T+1 execution shift is applied INSIDE this function via shift(1).
    starting_cash:
        Initial cash.
    slippage_bps:
        One-way slippage in basis points.
    commission_bps:
        One-way commission in basis points.

    Returns
    -------
    dict with keys: total_return, max_drawdown, trade_count, ending_equity,
    starting_cash, trades (list of dicts), equity_curve (pd.Series).
    Note: cagr is NOT returned — it requires calendar dates known to the caller.
    """
    index = vehicle_df.index

    # Shift signal by 1: close-T signal → execute at open T+1.
    # NaN entries in is_bullish_close_t propagate to the shifted series;
    # we treat NaN → False (no entry) using pd.isna check in the loop.
    signal = is_bullish_close_t.shift(1)

    equity_curve: list[tuple] = []
    cash = starting_cash
    qty = 0
    entry_price = 0.0
    entry_date: Optional[pd.Timestamp] = None
    trades: list[Trade] = []

    for i, ts in enumerate(index):
        open_px = float(vehicle_df["Open"].iloc[i])
        close_px = float(vehicle_df["Close"].iloc[i])

        raw_sig = signal.iloc[i]
        # NaN → flat; bool(np.nan) would be True which is wrong
        want_long = bool(raw_sig) if not pd.isna(raw_sig) else False

        # Open-of-day execution
        if want_long and qty == 0:
            # Buy at open, with slippage + commission
            execution_px = open_px * (1 + slippage_bps / 10_000)
            qty = int(cash / execution_px / (1 + commission_bps / 10_000))
            cost = qty * execution_px * (1 + commission_bps / 10_000)
            cash -= cost
            entry_price = execution_px
            entry_date = ts
        elif not want_long and qty > 0:
            # Sell at open
            execution_px = open_px * (1 - slippage_bps / 10_000)
            proceeds = qty * execution_px * (1 - commission_bps / 10_000)
            cash += proceeds
            pnl = proceeds - (qty * entry_price * (1 + commission_bps / 10_000))
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
        last_ts = index[-1]
        last_close = float(vehicle_df["Close"].iloc[-1])
        execution_px = last_close * (1 - slippage_bps / 10_000)
        proceeds = qty * execution_px * (1 - commission_bps / 10_000)
        cash += proceeds
        pnl = proceeds - (qty * entry_price * (1 + commission_bps / 10_000))
        trades.append(Trade(
            entry_date=entry_date, exit_date=last_ts,
            entry_price=entry_price, exit_price=execution_px,
            qty=qty, pnl=pnl,
            return_pct=(execution_px / entry_price - 1),
            exit_reason="end_of_window",
        ))
        # Reconcile last equity-curve point with the closed-out cash so
        # ending_equity (derived from eq_series.iloc[-1]) reflects the same
        # slippage/commission haircut as the trade ledger.
        if len(equity_curve) > 0:
            last_curve_ts = equity_curve[-1][0]
            equity_curve[-1] = (last_curve_ts, cash)

    eq_series = pd.Series(dict(equity_curve))
    total_return = float(eq_series.iloc[-1] / starting_cash - 1)
    rolling_max = eq_series.cummax()
    max_dd = float(((eq_series - rolling_max) / rolling_max).min())

    return {
        "total_return": total_return,
        "max_drawdown": max_dd,
        "trade_count": len(trades),
        "ending_equity": float(eq_series.iloc[-1]),
        "starting_cash": starting_cash,
        "trades": [t.__dict__ for t in trades],
        "equity_curve": eq_series,
    }


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

    Thin wrapper: fetches data, computes the 200-DMA signal, delegates the
    simulation to ``simulate_from_signal``, then adds ``cagr`` (which requires
    the calendar ``start``/``end`` params, not available inside the core).

    Result keys: total_return, cagr, max_drawdown, trade_count, ending_equity,
                 starting_cash, trades (list of dicts), equity_curve (pd.Series).
    """
    benchmark = _fetch(benchmark_ticker, start, end)
    vehicle = _fetch(vehicle_ticker, start, end)

    # Align on common dates BEFORE computing the SMA (order matters)
    common = benchmark.index.intersection(vehicle.index)
    benchmark = benchmark.loc[common]
    vehicle = vehicle.loc[common]

    # SMA on benchmark close
    sma = benchmark["Close"].rolling(sma_days).mean()
    is_bullish = (benchmark["Close"] > sma).fillna(False)

    result = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=starting_cash,
        slippage_bps=SLIPPAGE_BPS,
        commission_bps=COMMISSION_BPS,
    )

    # cagr lives in the wrapper — it requires the calendar window, not the index
    total_return = result["total_return"]
    n_years = (end - start).days / 365.25
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
    result["cagr"] = cagr

    return result


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
