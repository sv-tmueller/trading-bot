"""Giveback study runner — #420. Research-only; no Alpaca import, no orders.

Compares the 200-DMA-on-3x incumbent (giveback-OFF) against the same strategy
with the profit-protecting giveback (ON), on synthetic-3x (SPY 1993+) and real
UPRO (2009+). Pre-registered bar (see docs/research/2026-07-24-giveback-backtest-
verdict.md): enable live only if the full-window after-tax US Calmar improves ON
vs OFF, computed identically for both arms.

The giveback is injected as a pure transform of the 200-DMA signal fed to the
shared engine via ``simulate_from_signal(vehicle_df=…, is_bullish_close_t=…)`` —
the same hook the incumbent leveraged-regime study uses. The engine applies the
single close-T -> open-T+1 shift; the transform must NOT pre-shift.

Both arms share one execution model (close-based giveback detection, next-open
fill), so the ON-vs-OFF comparison is fair. See the verdict doc's modeling caveat.

Usage: python3 -m backtest.run_giveback_study [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from backtest.giveback import apply_giveback, worst_giveback
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, simulate_from_signal
from backtest.regime_signals import sma_signal
from backtest.run_candidate_survey import STARTING_CASH, _after_tax_metrics
from backtest.synthetic import (
    UPRO_EXPENSE,
    build_synthetic_leverage,
    daily_risk_free,
    fetch_ohlc,
)

LEVERAGE = 3.0
SMA_DAYS = 200
ARM_PCT = 0.20
PROTECT_FRACTION = 0.50


def _sim(vehicle_df: pd.DataFrame, signal_bool: pd.Series) -> dict:
    return simulate_from_signal(
        vehicle_df=vehicle_df,
        is_bullish_close_t=signal_bool,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS,
        commission_bps=COMMISSION_BPS,
    )


def _bool_to_str(sig_bool: pd.Series) -> pd.Series:
    """bool/NaN is_bullish_close_t -> LONG/CASH (NaN and False both -> CASH)."""
    # ``== True`` is NaN-safe (NaN == True -> False), avoiding an object-dtype
    # fillna downcast warning.
    return pd.Series(
        np.where(sig_bool == True, "LONG", "CASH"),  # noqa: E712
        index=sig_bool.index,
    )


def _run_arms(spy_close: pd.Series, vehicle_df: pd.DataFrame,
              common: pd.DatetimeIndex) -> dict:
    """OFF (raw 200-DMA) vs ON (giveback-adjusted) on one vehicle over ``common``.

    The 200-DMA is computed on the FULL SPY history, then sliced to ``common``, so
    the signal is warm from the first day of the vehicle window (matters for real
    UPRO, whose window starts well after the 200-day warm-up).
    """
    sig_off = sma_signal(spy_close, SMA_DAYS).loc[common]  # bool / NaN
    vehicle = vehicle_df.loc[common]
    vclose = vehicle["Close"]

    # OFF arm: raw signal straight to the engine (NaN warm-up -> flat).
    off_sim = _sim(vehicle, sig_off)
    off_pos_str = _bool_to_str(sig_off)

    # ON arm: bool -> string -> giveback transform -> bool -> engine (no pre-shift).
    on_pos_str = apply_giveback(
        _bool_to_str(sig_off), vclose,
        arm_pct=ARM_PCT, protect_fraction=PROTECT_FRACTION,
    )
    on_sim = _sim(vehicle, on_pos_str == "LONG")

    return {
        "off": {
            "metrics": _after_tax_metrics(off_sim, common),
            "worst_giveback": worst_giveback(off_pos_str, vclose),
        },
        "on": {
            "metrics": _after_tax_metrics(on_sim, common),
            "worst_giveback": worst_giveback(on_pos_str, vclose),
        },
    }


def run_study(end: Optional[date] = None) -> dict:
    end = end or date.today()
    print(f"Fetching SPY, ^IRX, UPRO (1990 -> {end}) ...", flush=True)
    spy = fetch_ohlc("SPY", date(1990, 1, 1), end)
    rf = daily_risk_free(date(1990, 1, 1), end)
    syn3x = build_synthetic_leverage(
        spy["Close"], leverage=LEVERAGE, annual_expense=UPRO_EXPENSE, rf_daily=rf
    )
    upro = fetch_ohlc("UPRO", date(2009, 6, 25), end)

    vehicles = {
        "Synthetic-3x SPY (1993+)": (spy["Close"], syn3x,
                                     spy.index.intersection(syn3x.index)),
        "Real UPRO (2009+)": (spy["Close"], upro,
                              spy.index.intersection(upro.index)),
    }
    out: dict = {}
    for name, (spy_close, vdf, common) in vehicles.items():
        print(f"  {name}: {common[0].date()} -> {common[-1].date()} "
              f"({len(common)} rows)", flush=True)
        out[name] = {
            "arms": _run_arms(spy_close, vdf, common),
            "window": (common[0].date(), common[-1].date()),
            "n_days": len(common),
        }
    return out


def _fmt(x, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x*100:+.1f}%" if pct else f"{x:.3f}"


def _print_report(res: dict) -> None:
    print("\n" + "=" * 92)
    print("GIVEBACK STUDY (#420) — 200-DMA giveback-OFF vs giveback-ON")
    print(f"Params: arm_pct={ARM_PCT}, protect_fraction={PROTECT_FRACTION}; "
          f"gate = full-window after-tax US Calmar, ON > OFF")
    print("=" * 92)
    header = (f"{'vehicle / arm':<28} {'CalmarUS':>9} {'CalmarDE':>9} {'CAGR':>7} "
              f"{'maxDD':>8} {'worstGB':>8}")
    for name, r in res.items():
        w0, w1 = r["window"]
        print(f"\n{name}  [{w0} -> {w1}, {r['n_days']}d]")
        print(header)
        print("-" * len(header))
        for arm in ("off", "on"):
            a = r["arms"][arm]
            m = a["metrics"]
            label = "  giveback-OFF" if arm == "off" else "  giveback-ON"
            print(f"{label:<28} {_fmt(m['calmar_us']):>9} {_fmt(m['calmar_de']):>9} "
                  f"{_fmt(m['cagr_pretax'], pct=True):>7} "
                  f"{_fmt(m['max_dd'], pct=True):>8} "
                  f"{_fmt(a['worst_giveback'], pct=True):>8}")
        off_c = r["arms"]["off"]["metrics"]["calmar_us"]
        on_c = r["arms"]["on"]["metrics"]["calmar_us"]
        verdict = "GO (ON > OFF)" if on_c > off_c else "NO-GO (ON <= OFF)"
        print(f"  GATE (Calmar US ON > OFF): {verdict}  "
              f"[OFF {_fmt(off_c)} vs ON {_fmt(on_c)}]")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_giveback_study")
    parser.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else date.today()
    _print_report(run_study(end=end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
