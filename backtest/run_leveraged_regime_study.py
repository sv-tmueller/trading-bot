"""Leveraged-regime-signal study runner — #321 (refs #255).

Tests whether a better regime signal than the incumbent 200-DMA makes a 3x SPY
position (synthetic UPRO) clear 1x SPY's after-tax Calmar, by cutting drawdown
while keeping the leveraged return. Research-only; the live bot is untouched.

Each regime signal is a binary is_bullish_close_t computed on the UNDERLYING SPY
close and applied to the synthetic-3x vehicle (LONG synthetic-3x / CASH). The 1x
SPY buy-and-hold row is the bar. The 200-DMA-on-3x row is the live incumbent.

Reuses the survey foundation (no reimplementation): the weighted/binary simulator
(`simulate_from_signal`), the US/DE after-tax layer, `_after_tax_metrics` /
`_curve_metrics`, the walk-forward window slicer, and `synthetic.py`'s 3x model.

Run:
    python3 -m backtest.run_leveraged_regime_study
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Callable, Optional

import numpy as np
import pandas as pd

from backtest.baselines import buy_and_hold_signal, faber_sma_signal, tsmom_signal
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, simulate_from_signal
from backtest.regime_signals import confirmed_sma_signal, sma_signal
from backtest.run_candidate_survey import (
    STARTING_CASH,
    _MAX_LOOKBACK_DAYS,
    _after_tax_metrics,
    _curve_metrics,
    _BEAR_WINDOWS,
)
from backtest.synthetic import (
    UPRO_EXPENSE,
    build_synthetic_leverage,
    daily_risk_free,
    fetch_close,
    fetch_ohlc,
)
from backtest.tax import apply_tax_to_ledger
from backtest.walkforward import _slice_windows

LEVERAGE = 3.0

# (label, signal_fn(spy_close) -> is_bullish_close_t, vehicle key)
STRATEGIES = [
    ("200-DMA on 3x (INCUMBENT)", lambda c: sma_signal(c, 200), "syn3x"),
    ("100-DMA on 3x (faster)", lambda c: sma_signal(c, 100), "syn3x"),
    ("tsmom-12mo on 3x", tsmom_signal, "syn3x"),
    ("Faber 10mo SMA on 3x", faber_sma_signal, "syn3x"),
    ("200-DMA + 2d confirm on 3x", lambda c: confirmed_sma_signal(c, 200, 2), "syn3x"),
    ("1x SPY (buy & hold)", buy_and_hold_signal, "spy"),
]


def _sim(vehicle_df: pd.DataFrame, signal: pd.Series) -> dict:
    return simulate_from_signal(
        vehicle_df=vehicle_df,
        is_bullish_close_t=signal,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS,
        commission_bps=COMMISSION_BPS,
    )


def _sim_strategy_on_index(
    signal_fn: Callable[[pd.Series], pd.Series],
    vehicle_key: str,
    spy: pd.DataFrame,
    syn3x: pd.DataFrame,
    idx: pd.DatetimeIndex,
) -> dict:
    """Compute the signal on SPY closes over ``idx`` and trade the chosen vehicle."""
    sig = signal_fn(spy["Close"].loc[idx])
    vehicle = (syn3x if vehicle_key == "syn3x" else spy).loc[idx]
    return _sim(vehicle, sig)


def _per_window_after_tax_calmar(
    signal_fn: Callable[[pd.Series], pd.Series],
    vehicle_key: str,
    spy: pd.DataFrame,
    syn3x: pd.DataFrame,
    common_idx: pd.DatetimeIndex,
    window_months: int = 12,
) -> dict:
    """Median per-window after-tax (US) Calmar + positive-window count (stability gate)."""
    windows = _slice_windows(
        all_dates=common_idx,
        test_start=common_idx[0].date(),
        window_months=window_months,
        max_lookback_days=_MAX_LOOKBACK_DAYS,
    )
    calmars: list[float] = []
    for pr_start, ts, te in windows:
        mask = (common_idx >= pr_start) & (common_idx <= te)
        widx = common_idx[mask]
        if len(widx) < 30:
            continue
        sim = _sim_strategy_on_index(signal_fn, vehicle_key, spy, syn3x, widx)
        eq = sim["equity_curve"]
        eq_test = eq.loc[(eq.index >= ts) & (eq.index <= te)]
        if len(eq_test) < 2:
            continue
        test_trades = [t for t in sim["trades"] if ts <= t["exit_date"] <= te]
        m = _curve_metrics(apply_tax_to_ledger(test_trades, eq_test, jurisdiction="US"))
        c = m["calmar"]
        if not (isinstance(c, float) and np.isnan(c)):
            calmars.append(c)
    if not calmars:
        return {"median_calmar": float("nan"), "n_windows": 0, "n_positive": 0}
    arr = np.array(calmars, dtype=float)
    return {"median_calmar": float(np.median(arr)),
            "n_windows": len(arr), "n_positive": int((arr > 0).sum())}


def _bear_stress(
    signal_fn: Callable[[pd.Series], pd.Series],
    vehicle_key: str,
    spy: pd.DataFrame,
    syn3x: pd.DataFrame,
    common_idx: pd.DatetimeIndex,
) -> dict:
    """Max drawdown / window return of the strategy in each bear sub-window."""
    out: dict = {}
    for label, (b0, b1) in _BEAR_WINDOWS.items():
        pr0 = pd.Timestamp(b0) - pd.DateOffset(days=_MAX_LOOKBACK_DAYS * 2)
        widx = common_idx[(common_idx >= pr0) & (common_idx <= pd.Timestamp(b1))]
        in_bear = (widx >= pd.Timestamp(b0)) & (widx <= pd.Timestamp(b1))
        if in_bear.sum() < 20:
            out[label] = None
            continue
        sim = _sim_strategy_on_index(signal_fn, vehicle_key, spy, syn3x, widx)
        eq = sim["equity_curve"]
        eq_bear = eq.loc[(eq.index >= pd.Timestamp(b0)) & (eq.index <= pd.Timestamp(b1))]
        if len(eq_bear) < 2:
            out[label] = None
            continue
        roll = eq_bear.cummax()
        out[label] = {"max_dd": float(((eq_bear - roll) / roll).min()),
                      "window_return": float(eq_bear.iloc[-1] / eq_bear.iloc[0] - 1)}
    return out


def _upro_crosscheck(spy_close: pd.Series, syn3x: pd.DataFrame, end: date) -> dict:
    """Compare the synthetic-3x series to real UPRO over the overlapping window."""
    try:
        upro = fetch_close("UPRO", date(2009, 6, 1), end)
    except Exception as exc:  # network / data issue — report, don't crash the study
        return {"error": f"UPRO fetch failed: {exc}"}
    common = syn3x.index.intersection(upro.index)
    if len(common) < 60:
        return {"error": "insufficient UPRO overlap"}
    syn = syn3x["Close"].loc[common]
    real = upro.loc[common]
    syn_r = syn.pct_change().dropna()
    real_r = real.reindex(syn_r.index).pct_change().dropna()
    j = syn_r.index.intersection(real_r.index)
    syn_cagr = (syn.iloc[-1] / syn.iloc[0]) ** (365.25 / (common[-1] - common[0]).days) - 1
    real_cagr = (real.iloc[-1] / real.iloc[0]) ** (365.25 / (common[-1] - common[0]).days) - 1
    return {
        "overlap": (common[0].date(), common[-1].date()),
        "daily_return_corr": float(syn_r.loc[j].corr(real_r.loc[j])),
        "synthetic_cagr": float(syn_cagr),
        "real_upro_cagr": float(real_cagr),
    }


def run_study(end: Optional[date] = None) -> dict:
    end = end or date.today()
    print(f"Fetching SPY, ^IRX, UPRO (1990 -> {end}) ...", flush=True)
    spy = fetch_ohlc("SPY", date(1990, 1, 1), end)
    rf = daily_risk_free(date(1990, 1, 1), end)
    syn3x = build_synthetic_leverage(
        spy["Close"], leverage=LEVERAGE, annual_expense=UPRO_EXPENSE, rf_daily=rf
    )
    common = spy.index.intersection(syn3x.index)
    spy = spy.loc[common]
    syn3x = syn3x.loc[common]
    print(f"  SPY/syn3x common: {common[0].date()} -> {common[-1].date()} "
          f"({len(common)} rows)", flush=True)

    rows: dict = {}
    for label, fn, veh in STRATEGIES:
        sim = _sim_strategy_on_index(fn, veh, spy, syn3x, common)
        rows[label] = {
            "metrics": _after_tax_metrics(sim, common),
            "stability": _per_window_after_tax_calmar(fn, veh, spy, syn3x, common),
            "bear": _bear_stress(fn, veh, spy, syn3x, common),
            "vehicle": veh,
        }
    return {
        "window": (common[0].date(), common[-1].date()),
        "n_days": len(common),
        "rows": rows,
        "crosscheck": _upro_crosscheck(spy["Close"], syn3x, end),
    }


def _fmt(x, pct: bool = False, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x*100:+.1f}%" if pct else f"{x:.{nd}f}"


def _print_report(res: dict) -> None:
    w0, w1 = res["window"]
    print("\n" + "=" * 100)
    print("LEVERAGED-REGIME-SIGNAL STUDY (#321) — 3x SPY (synthetic UPRO) by regime signal")
    print(f"Window: {w0} -> {w1}  ({res['n_days']} trading days, ~{(w1 - w0).days/365.25:.1f}y)")
    print("Bar: clear = beat 1x SPY after-tax Calmar AND the 200-DMA incumbent.")
    print("=" * 100)
    spy_row = res["rows"]["1x SPY (buy & hold)"]["metrics"]
    spy_cal = spy_row["calmar_us"]
    header = (f"{'strategy':<30} {'Calmar US':>9} {'Calmar DE':>9} {'CAGR':>7} "
              f"{'maxDD':>8} {'trd/yr':>7} {'>1xSPY?':>8}")
    print(header)
    print("-" * len(header))
    for label, r in res["rows"].items():
        m = r["metrics"]
        beats = ""
        if not label.startswith("1x SPY"):
            bc = m["calmar_us"]
            if (isinstance(bc, float) and np.isnan(bc)) or (isinstance(spy_cal, float) and np.isnan(spy_cal)):
                beats = "n/a"
            else:
                beats = "YES" if bc > spy_cal else "no"
        print(f"{label:<30} {_fmt(m['calmar_us']):>9} {_fmt(m['calmar_de']):>9} "
              f"{_fmt(m['cagr_pretax'], pct=True):>7} {_fmt(m['max_dd'], pct=True):>8} "
              f"{_fmt(m['turnover_yr']):>7} {beats:>8}")
    print("\nPer-window after-tax (US) stability (12mo OOS windows):")
    for label, r in res["rows"].items():
        st = r["stability"]
        print(f"  {label:<30} median Calmar {_fmt(st['median_calmar'])}  "
              f"({st['n_positive']}/{st['n_windows']} positive)")
    print("\nBear stress (max DD / window return):")
    for label, r in res["rows"].items():
        parts = []
        for bl in _BEAR_WINDOWS:
            b = r["bear"].get(bl)
            parts.append(f"{bl} {_fmt(b['max_dd'], pct=True)}/{_fmt(b['window_return'], pct=True)}"
                         if b else f"{bl} n/a")
        print(f"  {label:<30} " + "  |  ".join(parts))
    cc = res["crosscheck"]
    print("\nSynthetic-3x vs real UPRO cross-check:")
    if "error" in cc:
        print(f"  {cc['error']}")
    else:
        o0, o1 = cc["overlap"]
        print(f"  overlap {o0} -> {o1}: daily-return corr {cc['daily_return_corr']:.3f}; "
              f"CAGR synthetic {_fmt(cc['synthetic_cagr'], pct=True)} vs real UPRO "
              f"{_fmt(cc['real_upro_cagr'], pct=True)}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_leveraged_regime_study")
    parser.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else date.today()
    _print_report(run_study(end=end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
