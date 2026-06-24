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
    vehicle_df: Optional[pd.DataFrame] = None,
    is_bullish_close_t: Optional[pd.Series] = None,
    target_weights: Optional[pd.DataFrame] = None,
    asset_px: Optional[dict] = None,
    starting_cash: float = STARTING_CASH,
    slippage_bps: int = SLIPPAGE_BPS,
    commission_bps: int = COMMISSION_BPS,
    alloc_frac: float = 1.0,
) -> dict:
    """Signal/weight → equity simulation shared by all strategies.

    Two calling conventions:

    Binary single-asset (legacy, unchanged):
        simulate_from_signal(vehicle_df=..., is_bullish_close_t=...)
        A boolean (or NaN) signal at close-T deploys ``alloc_frac`` of cash into
        the single vehicle on LONG, 0% cash on the remainder. The T+1 execution
        shift is applied inside via ``shift(1)``.

    Weighted multi-asset (new — for the #314 candidate survey):
        simulate_from_signal(target_weights=<dates×assets frame>, asset_px=<dict
        of asset → Open/Close frame>)
        Each column is a daily target weight in [0,1]; the row sum must be ≤ 1
        (remainder is cash, 0% yield — no leverage). The weight vector is shifted
        one day (close-T target → T+1 open fill) and the portfolio trades **only
        when the (shifted) target weights change** — a constant weight is bought
        once and held. A one-column {0,1} frame is the binary special case and is
        dispatched to the legacy loop so its equity curve is identical.

    Parameters
    ----------
    vehicle_df, is_bullish_close_t:
        Binary path inputs (see above). Must share the same index.
    target_weights:
        Weighted path input: a DataFrame indexed by trading date, one column per
        asset, values in [0,1] with row sum ≤ 1.
    asset_px:
        Weighted path input: ``{asset_name: Open/Close DataFrame}``. Keys must
        cover every column of ``target_weights`` and share its index.
    starting_cash, slippage_bps, commission_bps:
        As before. One-way slippage / commission in basis points.
    alloc_frac:
        Binary path only: fraction of cash deployed on LONG (default 1.0).

    Returns
    -------
    dict with keys: total_return, max_drawdown, trade_count, ending_equity,
    starting_cash, trades (list of dicts), equity_curve (pd.Series).
    Note: cagr is NOT returned — it requires calendar dates known to the caller.
    """
    if target_weights is not None:
        # One-column {0,1} frame == the binary special case: dispatch to the
        # legacy loop so the equity curve is identical, not approximately equal.
        col_values = target_weights.values
        is_binary_single = (
            target_weights.shape[1] == 1
            and np.isin(col_values[~np.isnan(col_values)], (0.0, 1.0)).all()
        )
        if is_binary_single:
            if asset_px is None:
                raise ValueError("asset_px is required with target_weights")
            asset = target_weights.columns[0]
            sig = target_weights[asset].astype(bool)
            return simulate_from_signal(
                vehicle_df=asset_px[asset],
                is_bullish_close_t=sig,
                starting_cash=starting_cash,
                slippage_bps=slippage_bps,
                commission_bps=commission_bps,
                alloc_frac=1.0,
            )
        if asset_px is None:
            raise ValueError("asset_px is required with target_weights")
        return _simulate_weighted(
            target_weights=target_weights,
            asset_px=asset_px,
            starting_cash=starting_cash,
            slippage_bps=slippage_bps,
            commission_bps=commission_bps,
        )

    if vehicle_df is None or is_bullish_close_t is None:
        raise ValueError(
            "provide either (vehicle_df, is_bullish_close_t) or "
            "(target_weights, asset_px)"
        )

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
            # Buy at open, with slippage + commission. ``alloc_frac`` of cash is
            # deployed; the remainder stays in cash (0% yield).
            execution_px = open_px * (1 + slippage_bps / 10_000)
            investable = cash * alloc_frac
            qty = int(investable / execution_px / (1 + commission_bps / 10_000))
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


def _simulate_weighted(
    *,
    target_weights: pd.DataFrame,
    asset_px: dict,
    starting_cash: float,
    slippage_bps: int,
    commission_bps: int,
) -> dict:
    """Multi-asset target-weight simulation (transition-only rebalancing).

    Each column of ``target_weights`` is a daily target weight in [0,1]; the row
    sum must be ≤ 1 (remainder = cash, 0% yield). The weight vector is shifted
    one day (close-T target → T+1 open fill), and the portfolio rebalances **only
    on days the shifted target vector changes** (a constant weight is bought once
    and held). Each asset is held as a single lot: a weight transition closes the
    open lot (a ``Trade``) and opens a new one, so the ledger classifies cleanly
    by holding period for the tax layer.

    Cost model matches the binary loop: per traded leg, buys execute at
    ``open*(1+slip)`` with an extra ``(1+comm)`` haircut, sells at
    ``open*(1-slip)`` with ``(1-comm)``.
    """
    index = target_weights.index
    assets = list(target_weights.columns)

    if (target_weights.fillna(0.0).sum(axis=1) > 1.0 + 1e-9).any():
        raise ValueError("target weights must sum to ≤ 1 per row (no leverage)")

    # close-T target → execute at T+1 open
    shifted = target_weights.shift(1)

    cash = starting_cash
    shares: dict = {a: 0.0 for a in assets}
    # open lot bookkeeping per asset (for the trade ledger / tax classification)
    lot_entry_date: dict = {a: None for a in assets}
    lot_entry_px: dict = {a: 0.0 for a in assets}
    prev_target: dict = {a: 0.0 for a in assets}

    trades: list[Trade] = []
    equity_curve: list[tuple] = []

    slip = slippage_bps / 10_000
    comm = commission_bps / 10_000

    def _open_price(a: str, i: int) -> float:
        return float(asset_px[a]["Open"].iloc[i])

    def _close_price(a: str, i: int) -> float:
        return float(asset_px[a]["Close"].iloc[i])

    for i, ts in enumerate(index):
        # Today's effective target (NaN row → all flat)
        row = shifted.iloc[i]
        target = {a: (0.0 if pd.isna(row[a]) else float(row[a])) for a in assets}

        changed = any(abs(target[a] - prev_target[a]) > 1e-12 for a in assets)

        if changed:
            # Portfolio value marked at today's opens
            port_val = cash + sum(shares[a] * _open_price(a, i) for a in assets)

            # First sells (free up cash), then buys
            for a in assets:
                tgt_val = port_val * target[a]
                cur_val = shares[a] * _open_price(a, i)
                if tgt_val < cur_val - 1e-9:
                    # reduce / close this leg
                    open_px = _open_price(a, i)
                    exec_px = open_px * (1 - slip)
                    # shares to sell
                    sell_shares = shares[a] - (tgt_val / open_px if open_px > 0 else 0.0)
                    proceeds = sell_shares * exec_px * (1 - comm)
                    cash += proceeds
                    shares[a] -= sell_shares
                    # record the closed lot (entire prior lot if going flat)
                    if lot_entry_date[a] is not None:
                        entry_px = lot_entry_px[a]
                        trades.append(Trade(
                            entry_date=lot_entry_date[a], exit_date=ts,
                            entry_price=entry_px, exit_price=exec_px,
                            qty=int(round(sell_shares)),
                            pnl=sell_shares * (exec_px * (1 - comm)
                                               - entry_px * (1 + comm)),
                            return_pct=(exec_px / entry_px - 1) if entry_px > 0 else 0.0,
                            exit_reason="rebalance",
                        ))
                    if shares[a] <= 1e-9:
                        shares[a] = 0.0
                        lot_entry_date[a] = None
                        lot_entry_px[a] = 0.0

            for a in assets:
                tgt_val = port_val * target[a]
                cur_val = shares[a] * _open_price(a, i)
                if tgt_val > cur_val + 1e-9:
                    open_px = _open_price(a, i)
                    exec_px = open_px * (1 + slip)
                    buy_dollars = tgt_val - cur_val
                    buy_shares = buy_dollars / exec_px / (1 + comm)
                    cost = buy_shares * exec_px * (1 + comm)
                    cash -= cost
                    if shares[a] <= 1e-9:
                        lot_entry_date[a] = ts
                        lot_entry_px[a] = exec_px
                    shares[a] += buy_shares

            prev_target = dict(target)

        # Mark equity to close
        eq = cash + sum(shares[a] * _close_price(a, i) for a in assets)
        equity_curve.append((ts, eq))

    # Close any open lots at the last close
    last_i = len(index) - 1
    last_ts = index[-1]
    for a in assets:
        if shares[a] > 1e-9:
            close_px = _close_price(a, last_i)
            exec_px = close_px * (1 - slip)
            proceeds = shares[a] * exec_px * (1 - comm)
            cash += proceeds
            entry_px = lot_entry_px[a]
            trades.append(Trade(
                entry_date=lot_entry_date[a], exit_date=last_ts,
                entry_price=entry_px, exit_price=exec_px,
                qty=int(round(shares[a])),
                pnl=shares[a] * (exec_px * (1 - comm) - entry_px * (1 + comm)),
                return_pct=(exec_px / entry_px - 1) if entry_px > 0 else 0.0,
                exit_reason="end_of_window",
            ))
            shares[a] = 0.0
    # Reconcile the last equity point with closed-out cash
    if len(equity_curve) > 0 and len(trades) > 0:
        equity_curve[-1] = (last_ts, cash)

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
    alloc_frac: float = 1.0,
    benchmark_px: Optional[pd.DataFrame] = None,
    vehicle_px: Optional[pd.DataFrame] = None,
) -> dict:
    """Run the regime-filter backtest. Returns headline metrics + trade list.

    Thin wrapper: fetches data, computes the 200-DMA signal, delegates the
    simulation to ``simulate_from_signal``, then adds ``cagr`` (which requires
    the calendar ``start``/``end`` params, not available inside the core).

    Result keys: total_return, cagr, max_drawdown, trade_count, ending_equity,
                 starting_cash, trades (list of dicts), equity_curve (pd.Series).

    ``alloc_frac`` is the fraction of available cash deployed into the vehicle
    on LONG (default 1.0 = 100%, the live bot's behaviour). The remainder stays
    in cash earning 0%. ``benchmark_px`` / ``vehicle_px`` let callers inject an
    already-built OHLC frame (used by the synthetic-leverage research code) in
    place of a yfinance download; each must have ``Open`` and ``Close`` columns
    indexed by date.
    """
    benchmark = _fetch(benchmark_ticker, start, end) if benchmark_px is None else benchmark_px
    vehicle = _fetch(vehicle_ticker, start, end) if vehicle_px is None else vehicle_px

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
        alloc_frac=alloc_frac,
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
