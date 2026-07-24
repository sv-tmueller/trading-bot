"""Turtle / Donchian-55 breakout bracket — Candidate A runner (#430, P1 of #429).

Research-only. Lives in backtest/ and is never imported by supabase/functions/.
No LLM, no broker calls, no broker-client import. Mirror pattern: run_giveback_study.py.

Screens the FROZEN 12-cell grid (see docs/research/2026-07-24-turtle-breakout-verdict.md):
``R ∈ {2,3,4} × vehicle ∈ {SPY, ES=F} × bar ∈ {daily, hourly}``. The daily arm (6 cells)
is gate-eligible; the hourly arm (6 cells) is a directional, non-promotable read
(yfinance 60m is depth-capped and cannot reach n_w=13 — depth is probed at runtime).

Entry: Donchian-55 breakout, no look-ahead (``close > high.shift(1).rolling(55).max()``).
N = ATR(20) Wilder at the signal bar (t−1). Stop = entry − 2N; target = entry + R·N,
computed here and passed to ``simulate_bracket`` as ABSOLUTE levels (the engine never
hardcodes the geometry, so #431's ORB reuses it unchanged).

Primary verdict: per-cell full-window after-tax US Calmar vs the frozen SPY bar
(1.3085475049604838). Secondary robustness (daily arm only, D1/D2): the #398
DSR/PBO/bootstrap gate on per-day equity returns, with N=6 trial Sharpes. Each cell is
also reported vs a seeded random-entry bracket and an always-in baseline (beta catch).

Run: python3 -m backtest.run_turtle_breakout [--end YYYY-MM-DD]
All numbers come from a live yfinance pull at run time; no price is ever fabricated.
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from ta.volatility import AverageTrueRange

from backtest.bracket import donchian_breakout_signal, simulate_bracket
from backtest.overfitting_gate import evaluate_gate
from backtest.regime import (
    COMMISSION_BPS,
    SLIPPAGE_BPS,
    STARTING_CASH,
    simulate_from_signal,
)
from backtest.run_candidate_survey import _after_tax_metrics, _curve_metrics
from backtest.tax import apply_tax_to_ledger
from backtest.walkforward import _slice_windows

# --- Frozen grid + rule parameters (pre-registered) ---------------------------------
R_VALUES = (2, 3, 4)
VEHICLES = ("SPY", "ES=F")
BARS = ("daily", "hourly")
DONCHIAN_WINDOW = 55
ATR_WINDOW = 20
STOP_N = 2.0
SPY_BAR = 1.3085475049604838  # SPY B&H median-window after-tax Calmar (n_w=13, 2013-25)

# Data windows.
DAILY_START = date(1990, 1, 1)   # true inception bounds each vehicle (SPY 1993, ES 2000)
HOURLY_LOOKBACK_DAYS = 700       # yfinance 60m is capped ~730d FROM NOW; stay inside
RANDOM_SEED = 42                 # seeded random-entry baseline (reproducible)

_MAX_LOOKBACK_DAYS = 120         # Donchian-55 + ATR-20 warm-up pre-roll for per-window
_MIN_WINDOW_BARS = 80            # need > 75 bars for the warm-up to produce any signal


def _fetch(ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
    """Fetch auto-adjusted OHLC from yfinance (patchable seam for offline tests)."""
    df = yf.download(
        ticker, start=start, end=end, interval=interval,
        auto_adjust=True, progress=False,
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close"]].dropna()


def _atr(df: pd.DataFrame, window: int = ATR_WINDOW) -> pd.Series:
    """ATR (Wilder) via ``ta`` — matches the survey + scalping precedent."""
    return AverageTrueRange(
        df["High"], df["Low"], df["Close"], window=window
    ).average_true_range()


def _bracket_levels(
    df: pd.DataFrame, entry_trigger: pd.Series, r: float,
    *, slippage_bps: int = SLIPPAGE_BPS,
) -> tuple:
    """Absolute stop/target levels for a Turtle entry, anchored to the executed entry.

    N = ATR at the signal bar (t−1) = ``atr.shift(1)``; entry ≈ ``Open·(1+slip)`` at the
    entry bar. Stop = entry − 2N, target = entry + R·N. Levels are aligned to the entry
    bar (the bar ``simulate_bracket`` reads them on). This is the ONLY place the ATR
    geometry lives — the engine consumes absolute prices.
    """
    n_signal = _atr(df).shift(1)
    slip = slippage_bps / 10_000.0
    entry_ref = df["Open"] * (1 + slip)
    stop = entry_ref - STOP_N * n_signal
    target = entry_ref + r * n_signal
    # only meaningful where an entry actually triggers
    stop = stop.where(entry_trigger)
    target = target.where(entry_trigger)
    return stop, target


def _build_cell(df: pd.DataFrame, r: float) -> dict:
    """One Turtle/Donchian breakout cell over ``df`` (its own full index)."""
    sig = donchian_breakout_signal(df["High"], df["Close"], window=DONCHIAN_WINDOW)
    entry_trigger = sig.shift(1, fill_value=False)
    stop, target = _bracket_levels(df, entry_trigger, r)
    return simulate_bracket(
        df, entry_trigger, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )


def _build_random_cell(df: pd.DataFrame, r: float, seed: int = RANDOM_SEED) -> dict:
    """Random-entry bracket: same 2N-stop / R·N-target geometry, entries SHUFFLED.

    Places the same NUMBER of entries as the real signal at random valid bars (seeded).
    A real edge must beat this — otherwise the bracket is just capturing beta/vol.
    """
    sig = donchian_breakout_signal(df["High"], df["Close"], window=DONCHIAN_WINDOW)
    real_trigger = sig.shift(1, fill_value=False)
    k = int(real_trigger.sum())
    n_signal = _atr(df).shift(1)
    valid = np.flatnonzero((~n_signal.isna()).to_numpy())
    rng = np.random.default_rng(seed)
    trig = pd.Series(False, index=df.index)
    if k > 0 and len(valid) > 0:
        chosen = rng.choice(valid, size=min(k, len(valid)), replace=False)
        trig.iloc[np.sort(chosen)] = True
    stop, target = _bracket_levels(df, trig, r)
    return simulate_bracket(
        df, trig, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )


def _always_in(df: pd.DataFrame) -> dict:
    """Always-long the vehicle (buy & hold) — the beta baseline for this window."""
    oc = df[["Open", "Close"]]
    sig = pd.Series(True, index=df.index)
    return simulate_from_signal(
        vehicle_df=oc, is_bullish_close_t=sig,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )


def _per_window_calmar(df: pd.DataFrame, cell_fn: Callable[[pd.DataFrame], dict]) -> dict:
    """Median per-window after-tax (US) Calmar over non-overlapping 12-mo OOS windows.

    Each window rebuilds the cell on a pre-rolled sub-frame (warm-up in the pre-roll),
    then measures the test sub-window only. NaN-Calmar windows (0-1 trades — the sparse-
    series caveat) are dropped, as in run_candidate_survey.
    """
    idx = df.index
    windows = _slice_windows(
        all_dates=idx, test_start=idx[0].date(),
        window_months=12, max_lookback_days=_MAX_LOOKBACK_DAYS,
    )
    calmars: list[float] = []
    for pr_start, ts, te in windows:
        mask = (idx >= pr_start) & (idx <= te)
        widx = idx[mask]
        if len(widx) < _MIN_WINDOW_BARS:
            continue
        sim = cell_fn(df.loc[widx])
        eq = sim["equity_curve"]
        eq_test = eq.loc[(eq.index >= ts) & (eq.index <= te)]
        if len(eq_test) < 2:
            continue
        test_trades = [t for t in sim["trades"] if ts <= t["exit_date"] <= te]
        after = apply_tax_to_ledger(test_trades, eq_test, jurisdiction="US")
        c = _curve_metrics(after)["calmar"]
        if not (isinstance(c, float) and np.isnan(c)):
            calmars.append(c)
    if not calmars:
        return {"median_calmar": float("nan"), "n_windows": 0, "n_positive": 0}
    arr = np.array(calmars, dtype=float)
    return {
        "median_calmar": float(np.median(arr)),
        "n_windows": len(arr),
        "n_positive": int((arr > 0).sum()),
    }


def _daily_returns_on(index: pd.DatetimeIndex, eq: pd.Series) -> np.ndarray:
    """Per-day equity returns reindexed to a common index, zero-filled (D2 basis)."""
    r = eq.pct_change().dropna()
    return r.reindex(index).fillna(0.0).to_numpy(dtype=float)


def _sharpe(r: np.ndarray) -> float:
    """Non-annualized per-observation Sharpe (0.0 for a flat series)."""
    if len(r) < 2:
        return 0.0
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else 0.0


def evaluate_daily_gate(daily_cells: dict, spy_daily_eq: pd.Series) -> dict:
    """The #398 gate on the DAILY arm only (D1: N=6 trial Sharpes; D2: per-day returns).

    ``daily_cells`` maps ``(vehicle, R) -> cell sim``. All 6 cells' per-day returns are
    put on their common index (zero-filled — a bracket is flat most days anyway); the
    best-Sharpe cell feeds DSR, all six feed the PBO matrix, and best-minus-SPY-B&H
    per-day returns feed the block-bootstrap. Returned with the sparse-series caveat.
    """
    keys = list(daily_cells.keys())
    common = None
    for _k, sim in daily_cells.items():
        idx = sim["equity_curve"].index
        common = idx if common is None else common.intersection(idx)
    common = common.intersection(spy_daily_eq.index)

    cols = [_daily_returns_on(common, daily_cells[k]["equity_curve"]) for k in keys]
    perf_matrix = np.column_stack(cols)
    trial_sharpes = [_sharpe(c) for c in cols]
    best = int(np.argmax(trial_sharpes))
    returns_best = cols[best]
    spy_bh = _daily_returns_on(common, spy_daily_eq)
    uplifts = returns_best - spy_bh

    try:
        gate = evaluate_gate(
            returns_best=returns_best,
            all_trial_sharpes=trial_sharpes,
            perf_matrix=perf_matrix,
            uplifts=uplifts,
            bootstrap_seed=RANDOM_SEED,
        )
        error = None
    except Exception as exc:  # noqa: BLE001 — record, never crash the run
        gate = None
        error = f"{type(exc).__name__}: {exc}"

    return {
        "best_cell": keys[best],
        "n_trials": len(keys),
        "n_common_days": len(common),
        "trial_sharpes": dict(zip((str(k) for k in keys), trial_sharpes)),
        "gate": gate,
        "error": error,
    }


def run_turtle(end: Optional[date] = None) -> dict:
    """Fetch data and run the full 12-cell grid + baselines + daily gate.

    Returns a nested dict: per-cell metrics, per-window stability (daily), the hourly
    depth probe, and the daily-arm gate result.
    """
    end = end or date.today()
    cells: dict = {}
    hourly_depth: dict = {}
    daily_sims: dict = {}          # (vehicle, R) -> daily cell sim, for the gate
    spy_daily_eq: Optional[pd.Series] = None

    # yfinance 60m only serves roughly the last 730 days FROM NOW (not from ``end``),
    # so the hourly window is anchored to today's date regardless of ``end``; the
    # actual returned span is probed and reported below.
    today = date.today()
    hourly_end = min(pd.Timestamp(end), pd.Timestamp(today))
    hourly_start = pd.Timestamp(today) - pd.Timedelta(days=HOURLY_LOOKBACK_DAYS)

    for vehicle in VEHICLES:
        daily = _fetch(vehicle, DAILY_START, end, "1d")
        hourly = _fetch(vehicle, hourly_start.date(), hourly_end.date(), "60m")
        hourly_depth[vehicle] = {
            "n_bars": len(hourly),
            "span": (hourly.index[0], hourly.index[-1]) if len(hourly) else None,
        }
        if vehicle == "SPY":
            spy_daily_eq = _always_in(daily)["equity_curve"]

        for bar, df in (("daily", daily), ("hourly", hourly)):
            if len(df) < _MIN_WINDOW_BARS:
                continue
            for r in R_VALUES:
                sim = _build_cell(df, r)
                if bar == "daily":
                    daily_sims[(vehicle, r)] = sim
                rand = _build_random_cell(df, r)
                cell = {
                    "vehicle": vehicle, "bar": bar, "R": r,
                    "window": (df.index[0], df.index[-1]),
                    "n_bars": len(df),
                    "metrics": _after_tax_metrics(sim, df.index),
                    "random_calmar_us": _after_tax_metrics(rand, df.index)["calmar_us"],
                    "always_in_calmar_us": _after_tax_metrics(_always_in(df), df.index)["calmar_us"],
                }
                if bar == "daily":
                    cell["stability"] = _per_window_calmar(df, lambda d, _r=r: _build_cell(d, _r))
                cells[(vehicle, bar, r)] = cell

    gate = None
    if len(daily_sims) >= 2 and spy_daily_eq is not None:
        gate = evaluate_daily_gate(daily_sims, spy_daily_eq)

    return {
        "cells": cells,
        "hourly_depth": hourly_depth,
        "gate": gate,
        "spy_bar": SPY_BAR,
        "end": end,
    }


def _fmt(x, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x*100:+.1f}%" if pct else f"{x:.3f}"


def _print_report(res: dict) -> None:
    print("\n" + "=" * 100)
    print("TURTLE / DONCHIAN-55 BREAKOUT BRACKET (#430) — after-tax Calmar vs SPY bar")
    print(f"SPY bar (median-window after-tax Calmar, n_w=13, 2013-25): {res['spy_bar']:.4f}")
    print("Daily arm = gate-eligible; hourly arm = directional, NON-promotable.")
    print("=" * 100)

    print("\nHourly depth probe (yfinance 60m is capped ~730d — cannot reach n_w=13):")
    for v, d in res["hourly_depth"].items():
        span = f"{d['span'][0]} -> {d['span'][1]}" if d["span"] else "no data"
        print(f"  {v:6s}: {d['n_bars']} bars  [{span}]")

    header = (f"{'cell':<22} {'CalmarUS':>9} {'>SPYbar?':>9} {'CAGR':>7} {'maxDD':>8} "
              f"{'#trd':>5} {'rand':>7} {'always':>7}")
    for bar in BARS:
        print(f"\n--- {bar.upper()} arm ---")
        print(header)
        print("-" * len(header))
        for vehicle in VEHICLES:
            for r in R_VALUES:
                cell = res["cells"].get((vehicle, bar, r))
                if cell is None:
                    print(f"{vehicle} R{r} {bar:<8}: insufficient data")
                    continue
                m = cell["metrics"]
                c = m["calmar_us"]
                beats = ""
                if bar == "daily" and not (isinstance(c, float) and np.isnan(c)):
                    beats = "YES" if c > res["spy_bar"] else "no"
                elif bar == "hourly":
                    beats = "(dir)"
                label = f"{vehicle} R{r}"
                print(f"{label:<22} {_fmt(c):>9} {beats:>9} "
                      f"{_fmt(m['cagr_pretax'], pct=True):>7} {_fmt(m['max_dd'], pct=True):>8} "
                      f"{m['trade_count']:>5} {_fmt(cell['random_calmar_us']):>7} "
                      f"{_fmt(cell['always_in_calmar_us']):>7}")

    # daily per-window stability
    print("\nDaily per-window after-tax (US) Calmar stability (12mo OOS windows; sparse):")
    for vehicle in VEHICLES:
        for r in R_VALUES:
            cell = res["cells"].get((vehicle, "daily", r))
            if cell is None or "stability" not in cell:
                continue
            st = cell["stability"]
            print(f"  {vehicle} R{r}: median Calmar {_fmt(st['median_calmar'])} "
                  f"({st['n_positive']}/{st['n_windows']} windows positive)")

    # daily gate
    g = res["gate"]
    print("\nDaily-arm #398 gate (D1 N=6 trial Sharpes; D2 per-day returns; SECONDARY):")
    if g is None:
        print("  not computed (insufficient daily cells)")
    elif g["error"]:
        print(f"  gate uncomputable: {g['error']}")
    elif g["gate"] is not None:
        gg = g["gate"]
        print(f"  best cell {g['best_cell']} over {g['n_common_days']} common days")
        print(f"  DSR {gg['dsr']:.4f}  PBO {gg['pbo']:.4f}  bootstrap ci_low {gg['ci_low']:.6f}"
              f"  -> {'PASS' if gg['passed'] else 'FAIL'}")
        if gg["reasons"]:
            print(f"  reasons: {'; '.join(gg['reasons'])}")
    print("  Caveat: bracket daily returns are mostly zeros; the gate is a robustness")
    print("  check reported WITH this caveat, not the primary verdict.")
    print("\nLeverage caveat: v1 tests 1x. Replacing the 3x UPRO bot must eventually clear")
    print("the bar vs the 3x incumbent (run_leveraged_regime_study.py), not just 1x SPY.")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_turtle_breakout")
    parser.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else date.today()
    _print_report(run_turtle(end=end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
