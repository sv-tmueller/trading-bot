"""Synthetic leveraged-ETF series + long-horizon research helpers.

This module is RESEARCH ONLY. It builds a synthetic daily-leveraged index from a
total-return index plus a financing cost, so the 200-DMA regime backtest can be
run back to ~1990 (before UPRO/SSO existed). It reuses ``backtest.regime``'s
simulation engine via the ``vehicle_px`` / ``benchmark_px`` injection hooks.

Synthetic-leverage model (per trading day):

    r_lev = L * r_index - (annual_expense / 252) - (L - 1) * r_f_daily

where:
- ``r_index``      = the index's daily total return (close-to-close).
- ``L``            = leverage multiple (3 for UPRO, 2 for SSO).
- ``annual_expense`` = the ETF expense ratio (0.0091 for UPRO, 0.0089 for SSO).
- ``r_f_daily``    = the daily risk-free rate, from the 13-week T-bill (``^IRX``,
                     an annualized % yield) converted to a daily decimal rate.

This is a standard daily-rebalanced leverage model: a (L)x fund holds L dollars
of exposure per $1 of equity, borrows (L-1) at the short rate, and bleeds the
expense ratio. It captures the dominant real-world drivers (financing drag +
volatility/compounding decay) but ignores swap spreads, tracking error, and the
fund's actual borrowing rate vs the T-bill — see the validation step.

Costs (slippage + commission) and execution rules are inherited unchanged from
``backtest.regime``. A synthetic vehicle has no intraday open, so we set
``Open == Close`` for each synthetic day; execution therefore happens at the
synthetic daily level (one tick later than the signal, same as the real engine).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from backtest.regime import run_regime_backtest

UPRO_EXPENSE = 0.0091
SSO_EXPENSE = 0.0089
TRADING_DAYS = 252


def fetch_close(ticker: str, start: date, end: date) -> pd.Series:
    """Download a single ``Close`` series (auto-adjusted), date-indexed."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()


def fetch_ohlc(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Download an ``Open``/``Close`` frame (auto-adjusted), date-indexed."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def daily_risk_free(start: date, end: date, irx: Optional[pd.Series] = None) -> pd.Series:
    """Daily risk-free rate (decimal) from ``^IRX`` (13-week T-bill % yield).

    ``^IRX`` quotes an annualized yield in percent (e.g. 1.495 == 1.495%/yr). We
    convert to a simple daily rate (annual / 252). Missing days are forward-filled
    then back-filled; if ``^IRX`` is unavailable the caller passes ``irx=...``.
    """
    if irx is None:
        irx = fetch_close("^IRX", start, end)
    rf_annual = irx / 100.0
    return (rf_annual / TRADING_DAYS).rename("rf_daily")


def build_synthetic_leverage(
    index_close: pd.Series,
    *,
    leverage: float,
    annual_expense: float,
    rf_daily: pd.Series,
    base: float = 1.0,
) -> pd.DataFrame:
    """Build a synthetic Lx daily-leveraged price frame from an index TR series.

    Returns an OHLC-style frame with ``Open == Close`` (synthetic series has no
    meaningful intraday open) indexed by the index's trading days. The first row
    is the ``base`` price (no return applied on day 0).
    """
    r_index = index_close.pct_change()
    rf = rf_daily.reindex(index_close.index).ffill().bfill()
    expense_daily = annual_expense / TRADING_DAYS

    r_lev = leverage * r_index - expense_daily - (leverage - 1.0) * rf
    r_lev.iloc[0] = 0.0  # no return on the first day

    price = base * (1.0 + r_lev).cumprod()
    return pd.DataFrame({"Open": price, "Close": price})


def buy_and_hold(
    px: pd.DataFrame,
    *,
    starting_cash: float = 100_000.0,
    slippage_bps: float = 5,
    commission_bps: float = 5,
) -> dict:
    """Buy at first Open, hold to last Close, with the same per-side costs.

    Works on either a real OHLC frame or a synthetic ``Open == Close`` frame.
    Returns total_return, cagr, max_drawdown, ending_equity, equity_curve.
    """
    px = px.dropna()
    o0 = float(px["Open"].iloc[0])
    buy = o0 * (1 + slippage_bps / 10_000)
    qty = int(starting_cash / buy / (1 + commission_bps / 10_000))
    cost = qty * buy * (1 + commission_bps / 10_000)
    cash = starting_cash - cost

    # Mark-to-market equity curve on close, net of the eventual exit costs so the
    # drawdown reflects what an investor could actually realise.
    net_close = px["Close"] * (1 - slippage_bps / 10_000) * (1 - commission_bps / 10_000)
    eq = cash + qty * net_close
    eq.iloc[-1] = cash + qty * float(px["Close"].iloc[-1]) * (1 - slippage_bps / 10_000) * (1 - commission_bps / 10_000)

    ending = float(eq.iloc[-1])
    total_return = ending / starting_cash - 1
    n_years = (px.index[-1] - px.index[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
    max_dd = float(((eq - eq.cummax()) / eq.cummax()).min())
    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "ending_equity": ending,
        "equity_curve": eq,
    }


def validate_synthetic(
    synth_close: pd.Series,
    real_close: pd.Series,
    label: str,
) -> dict:
    """Compare a synthetic leveraged series to the real ETF over their overlap.

    Returns daily-return correlation + total-return/CAGR for each, computed on the
    common trading days (both reindexed to the same dates, normalized to the first
    common day so the two start at the same base).
    """
    common = synth_close.index.intersection(real_close.index)
    s = synth_close.loc[common]
    r = real_close.loc[common]
    s = s / s.iloc[0]
    r = r / r.iloc[0]

    s_ret = s.pct_change().dropna()
    r_ret = r.pct_change().dropna()
    corr = float(np.corrcoef(s_ret.values, r_ret.values)[0, 1])

    n_years = (common[-1] - common[0]).days / 365.25
    s_tot = float(s.iloc[-1] / s.iloc[0] - 1)
    r_tot = float(r.iloc[-1] / r.iloc[0] - 1)
    s_cagr = (1 + s_tot) ** (1 / n_years) - 1
    r_cagr = (1 + r_tot) ** (1 / n_years) - 1
    return {
        "label": label,
        "overlap_start": common[0].date(),
        "overlap_end": common[-1].date(),
        "n_days": len(common),
        "daily_return_corr": corr,
        "synth_total_return": s_tot,
        "real_total_return": r_tot,
        "synth_cagr": s_cagr,
        "real_cagr": r_cagr,
        "total_return_gap_pp": (s_tot - r_tot) * 100,
        "cagr_gap_pp": (s_cagr - r_cagr) * 100,
    }


def run_synthetic_regime(
    benchmark_close: pd.Series,
    synth_vehicle: pd.DataFrame,
    *,
    start: date,
    end: date,
    sma_days: int = 200,
    alloc_frac: float = 1.0,
) -> dict:
    """Run the 200-DMA regime backtest on a synthetic vehicle.

    ``benchmark_close`` is the signal series (index Close, e.g. ^GSPC) — wrapped
    as an OHLC frame so the engine can use it. ``synth_vehicle`` is the synthetic
    leveraged OHLC frame from ``build_synthetic_leverage``.
    """
    benchmark_px = pd.DataFrame({"Open": benchmark_close, "Close": benchmark_close})
    return run_regime_backtest(
        start=start,
        end=end,
        sma_days=sma_days,
        alloc_frac=alloc_frac,
        benchmark_px=benchmark_px,
        vehicle_px=synth_vehicle,
    )


def drawdown_in_window(eq: pd.Series, start: str, end: str) -> float:
    """Peak-to-trough drawdown of an equity/price series within [start, end].

    Peak is anchored at the running max *up to* ``start`` (so a crash that begins
    before the window's left edge still measures from the true pre-crash peak),
    then extended through the window.
    """
    s = eq.loc[:end]
    if len(s) == 0:
        return float("nan")
    window = s.loc[start:end]
    if len(window) == 0:
        return float("nan")
    # running peak from the very beginning through each point in the window
    running_peak = s.cummax().loc[window.index]
    dd = (window - running_peak) / running_peak
    return float(dd.min())
