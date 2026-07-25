"""Daily candlestick-PATTERN study runner — frozen 28-cell grid (refs #422, #431).

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker *trading*
calls, no order endpoint. The only network is a read-only historical-bars pull, and the
``--data`` path needs no network at all.

What this answers
-----------------
Does any classic candlestick pattern, traded on **daily** bars with a bracket exit anchored
to the pattern's own extreme, clear the frozen SPY buy-and-hold bar?

Mirrors ``run_turtle_breakout.py``'s daily arm deliberately — same vehicle, same after-tax
Calmar metric, same SPY bar, same random-entry and always-in baselines, same #398 gate — so
the candlestick numbers are directly comparable to the Turtle numbers already on record
(`docs/research/2026-07-24-turtle-breakout-verdict.md`).

Why daily and not intraday
--------------------------
#422's short-horizon NO-GO rests on a cost wall (72-128%/yr drag at 1-minute) and on free
intraday history not reaching n_w=13. Neither wall cares which signal fires, so an intraday
candlestick grid re-runs into both. Daily bars clear both: a pattern fires on the order of
10-30 bars a year, and daily SPY reaches 1993 (~33 non-overlapping 12-month windows).

Frozen geometry (pre-registered — see the verdict doc, do not tune)
------------------------------------------------------------------
Stops are anchored to the **pattern's own extreme**, which is what distinguishes candlestick
trading from an indicator with an ATR stop:

  - long arm:  ``stop = min(Low over the pattern's span) * (1 - BUFFER)``
  - short arm: ``stop = max(High over the pattern's span) * (1 + BUFFER)``
  - ``risk = |entry_ref - stop|`` where ``entry_ref = Open * (1 ± slip)`` at the entry bar
  - ``target = entry_ref ± R * risk`` for ``R`` in the frozen grid

The span is the pattern's own bar count (1, 2 or 3). Levels are computed at the SIGNAL bar
and shifted onto the ENTRY bar, so nothing reads a price the decision could not have seen.
A non-positive ``risk`` yields a NaN stop, which the engine treats as "suppress this entry".

Disclosed deviation — the inside-bar arms
----------------------------------------
Classic inside-bar trading enters on an intrabar BREAK of the mother bar's extreme. The
bracket engine's entry is "at the next bar's open", which cannot express an intrabar
breakout trigger. So ``inside_bar_long`` / ``inside_bar_short`` are a **directional bet at
the next open after an inside bar**, not a breakout. This is a real deviation from the
textbook rule and is labelled as such here, in the registry, and in the verdict doc.
``doji`` is registered as a pattern but is **excluded from the trading grid**: it is a pure
indecision bar with no directional implication, and assigning it one would be an unfrozen
free parameter.

Run: ``python3 -m backtest.run_candlestick_study [--data FILE] [--vehicle SPY] [--end ...]``
Exit codes: ``0`` the grid ran; ``2`` data unavailable or underpowered (no table printed).
All numbers come from a live read-only pull or a local file; no price is ever fabricated.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from backtest import candlestick as cs
from backtest import intraday_data as idata
from backtest.bracket import LONG, SHORT, simulate_bracket
from backtest.regime import (
    COMMISSION_BPS,
    SLIPPAGE_BPS,
    STARTING_CASH,
)
from backtest.run_candidate_survey import _after_tax_metrics

# --- Frozen grid ---------------------------------------------------------------------
#: Each arm is ``(arm_name, pattern_name, direction)``. Twelve directional patterns plus
#: the two disclosed inside-bar arms. ``doji`` is deliberately absent (see module docstring).
ARMS: Tuple[Tuple[str, str, str], ...] = (
    ("bullish_engulfing", "bullish_engulfing", LONG),
    ("bearish_engulfing", "bearish_engulfing", SHORT),
    ("hammer", "hammer", LONG),
    ("shooting_star", "shooting_star", SHORT),
    ("bullish_pin_bar", "bullish_pin_bar", LONG),
    ("bearish_pin_bar", "bearish_pin_bar", SHORT),
    ("bullish_marubozu", "bullish_marubozu", LONG),
    ("bearish_marubozu", "bearish_marubozu", SHORT),
    ("bullish_harami", "bullish_harami", LONG),
    ("bearish_harami", "bearish_harami", SHORT),
    ("morning_star", "morning_star", LONG),
    ("evening_star", "evening_star", SHORT),
    ("inside_bar_long", "inside_bar", LONG),
    ("inside_bar_short", "inside_bar", SHORT),
)

R_GRID: Tuple[float, ...] = (2.0, 3.0)
N_CELLS = len(ARMS) * len(R_GRID)          # 28 — the DSR multiplicity count

#: Bars each pattern spans, for the stop anchor. Must cover every arm above.
PATTERN_SPAN = {
    "hammer": 1, "shooting_star": 1,
    "bullish_pin_bar": 1, "bearish_pin_bar": 1,
    "bullish_marubozu": 1, "bearish_marubozu": 1,
    "bullish_engulfing": 2, "bearish_engulfing": 2,
    "bullish_harami": 2, "bearish_harami": 2,
    "inside_bar": 2,
    "morning_star": 3, "evening_star": 3,
    "doji": 1,
}

STOP_BUFFER = 0.001   # 10 bp beyond the pattern extreme, so an exact touch is not a stop
SPY_BAR = 1.3085475049604838  # SPY B&H median-window after-tax Calmar (n_w=13, 2013-25)
RANDOM_SEED = 42


def _pattern_extreme(df: pd.DataFrame, span: int) -> Tuple[pd.Series, pd.Series]:
    """Rolling ``(min Low, max High)`` over the pattern's ``span`` bars, ending at bar t."""
    return (
        df["Low"].rolling(span).min(),
        df["High"].rolling(span).max(),
    )


def bracket_levels(
    df: pd.DataFrame,
    entry_trigger: pd.Series,
    direction: str,
    span: int,
    r: float,
    *,
    slippage_bps: int = SLIPPAGE_BPS,
) -> Tuple[pd.Series, pd.Series]:
    """Absolute stop/target levels anchored to the pattern extreme and the executed entry.

    The extreme is measured at the SIGNAL bar (``t``) and shifted onto the ENTRY bar
    (``t+1``), which is the bar ``simulate_bracket`` reads the levels on. This function is
    the only place the candlestick stop geometry lives — the engine consumes absolute prices.
    """
    slip = slippage_bps / 10_000.0
    low_min, high_max = _pattern_extreme(df, span)

    if direction == LONG:
        entry_ref = df["Open"] * (1 + slip)
        stop = low_min.shift(1) * (1 - STOP_BUFFER)
        risk = entry_ref - stop
        target = entry_ref + r * risk
    else:
        entry_ref = df["Open"] * (1 - slip)
        stop = high_max.shift(1) * (1 + STOP_BUFFER)
        risk = stop - entry_ref
        target = entry_ref - r * risk

    # A non-positive risk is not a tradeable setup (the entry gapped past its own stop):
    # NaN the stop so the engine suppresses that entry rather than sizing off garbage.
    bad = ~(risk > 0)
    stop = stop.mask(bad)
    target = target.mask(bad)

    return stop.where(entry_trigger), target.where(entry_trigger)


def build_cell(df: pd.DataFrame, arm: Tuple[str, str, str], r: float) -> dict:
    """One candlestick cell: detect the pattern, shift to next-open, simulate the bracket."""
    _, pattern, direction = arm
    span = PATTERN_SPAN[pattern]
    signal = cs.detect(pattern, df)
    entry_trigger = signal.shift(1, fill_value=False)
    stop, target = bracket_levels(df, entry_trigger, direction, span, r)
    return simulate_bracket(
        df, entry_trigger, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=False, session_close_out=False,
        direction=direction,
    )


def build_random_cell(
    df: pd.DataFrame, arm: Tuple[str, str, str], r: float, seed: int = RANDOM_SEED
) -> dict:
    """Random-entry twin: identical geometry and entry COUNT, entry dates shuffled.

    The control that separates "this pattern has edge" from "any bracket with this geometry
    on this vehicle would have done that". Same trade count, same stop/target construction,
    entries placed at random eligible bars.
    """
    _, pattern, direction = arm
    span = PATTERN_SPAN[pattern]
    signal = cs.detect(pattern, df)
    n_signals = int(signal.sum())

    rng = np.random.default_rng(seed)
    eligible = np.arange(span, len(df) - 1)
    shuffled = pd.Series(False, index=df.index)
    if n_signals > 0 and len(eligible) > 0:
        picks = rng.choice(eligible, size=min(n_signals, len(eligible)), replace=False)
        shuffled.iloc[picks] = True

    entry_trigger = shuffled.shift(1, fill_value=False)
    stop, target = bracket_levels(df, entry_trigger, direction, span, r)
    return simulate_bracket(
        df, entry_trigger, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=False, session_close_out=False,
        direction=direction,
    )


def always_in(df: pd.DataFrame) -> dict:
    """Buy-and-hold the vehicle over the same index — the beta the cells must beat."""
    trigger = pd.Series(False, index=df.index)
    trigger.iloc[0] = True
    stop = pd.Series(np.nan, index=df.index)
    stop.iloc[0] = 0.0                      # an unreachable stop: never exits early
    return simulate_bracket(
        df, trigger, stop, None,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=False, session_close_out=False,
        direction=LONG,
    )


def run_grid(df: pd.DataFrame) -> list:
    """Every frozen cell over ``df``. Returns one row dict per cell."""
    rows = []
    for arm in ARMS:
        for r in R_GRID:
            sim = build_cell(df, arm, r)
            rand = build_random_cell(df, arm, r)
            rows.append({
                "arm": arm[0],
                "direction": arm[2],
                "r": r,
                "metrics": _after_tax_metrics(sim, df.index),
                "random_calmar_us": _after_tax_metrics(rand, df.index)["calmar_us"],
                "trade_count": sim["trade_count"],
                "max_drawdown": sim["max_drawdown"],
            })
    return rows


def cell_status(row: dict) -> str:
    """Classify a cell so a NaN Calmar is never printed as a bare number.

    A NaN after-tax Calmar means two completely different things and they must not be
    conflated in a table someone will quote:

      - ``no-trades``  — the pattern never fired, so there is nothing to judge.
      - ``RUINED``     — it traded and the after-tax curve was destroyed (the no-loss-credit
                         US tax on gross winners drives after-tax equity to a NaN Calmar,
                         the same failure mode the #430 random-entry cells hit). This is a
                         *worse* outcome than a negative Calmar, not a missing one.
      - ``ok``         — a finite Calmar to compare against the bar.
    """
    calmar = row["metrics"]["calmar_us"]
    if row["trade_count"] == 0:
        return "no-trades"
    if not np.isfinite(calmar):
        return "RUINED"
    return "ok"


def _sort_key(row: dict) -> tuple:
    """Best finite Calmar first; then RUINED, then no-trades (NaN never sorts silently)."""
    rank = {"ok": 0, "RUINED": 1, "no-trades": 2}[cell_status(row)]
    calmar = row["metrics"]["calmar_us"]
    return (rank, -calmar if np.isfinite(calmar) else 0.0)


def format_report(rows: list, bench: dict, power: "idata.PowerReport", source: str) -> str:
    """Render the per-cell table. Callers MUST NOT call this on an underpowered frame."""
    out = [
        "Daily candlestick-pattern study — frozen 28-cell grid",
        f"source: {source}",
        f"power: {power.verdict} — {power.reason}",
        f"bars: {power.n_bars}  span: {power.first} -> {power.last}",
        f"frozen SPY bar (median-window after-tax Calmar): {SPY_BAR:.4f}",
        f"always-in after-tax CalmarUS: {bench['calmar_us']:+.4f}",
        "",
        f"{'arm':<20} {'dir':<6} {'R':>4} {'CalmarUS':>10} {'>bar?':>6} "
        f"{'CAGR':>8} {'maxDD':>8} {'#tr':>5} {'random':>9} {'status':>10}",
    ]
    for row in sorted(rows, key=_sort_key):
        m = row["metrics"]
        status = cell_status(row)
        calmar_txt = f"{m['calmar_us']:>+10.4f}" if status == "ok" else f"{'—':>10}"
        rand = row["random_calmar_us"]
        rand_txt = f"{rand:>+9.4f}" if np.isfinite(rand) else f"{'—':>9}"
        clears = "YES" if (status == "ok" and m["calmar_us"] > SPY_BAR) else "no"
        out.append(
            f"{row['arm']:<20} {row['direction']:<6} {row['r']:>4.0f} "
            f"{calmar_txt} {clears:>6} "
            f"{m['cagr_pretax']:>+7.2%} {row['max_drawdown']:>+7.2%} "
            f"{row['trade_count']:>5} {rand_txt} {status:>10}"
        )

    cleared = [
        r for r in rows
        if cell_status(r) == "ok" and r["metrics"]["calmar_us"] > SPY_BAR
    ]
    ruined = [r for r in rows if cell_status(r) == "RUINED"]
    untraded = [r for r in rows if cell_status(r) == "no-trades"]
    out += [
        "",
        f"cells clearing the {SPY_BAR:.4f} bar: {len(cleared)} / {len(rows)}",
        f"cells with a RUINED after-tax curve: {len(ruined)} / {len(rows)}",
        f"cells that never traded: {len(untraded)} / {len(rows)}",
        f"DSR multiplicity (trial count): N = {N_CELLS}",
    ]
    if cleared:
        out.append("clearing cells: " + ", ".join(
            f"{r['arm']}/R{r['r']:.0f}" for r in cleared
        ))
    if untraded:
        out.append(
            "NOTE: a never-traded cell is not evidence about the pattern — it means the "
            "frozen rule found no setup on this frame. Report it, never omit it."
        )
    return "\n".join(out)


def _fetch_daily(ticker: str, end: Optional[date]) -> pd.DataFrame:
    """Read-only daily bars via yfinance. Returns an empty frame when unreachable."""
    import yfinance as yf

    raw = yf.download(
        ticker, start="1993-01-01",
        end=None if end is None else end.isoformat(),
        interval="1d", auto_adjust=False, progress=False,
    )
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return idata.validate_ohlc(raw)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None,
                    help="local CSV/Parquet of daily bars (no network)")
    ap.add_argument("--vehicle", default="SPY", help="ticker for the network path")
    ap.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    args = ap.parse_args(argv)

    end = date.fromisoformat(args.end) if args.end else None

    if args.data:
        source = f"local:{args.data}"
        try:
            df = idata.load_local(args.data)
        except Exception as exc:                       # noqa: BLE001 - report, never crash
            print(f"DATA-BLOCKED: could not load {args.data}: {exc}", file=sys.stderr)
            return 2
    else:
        source = f"yfinance:{args.vehicle}:1d"
        try:
            df = _fetch_daily(args.vehicle, end)
        except Exception as exc:                       # noqa: BLE001
            print(f"DATA-BLOCKED: fetch failed: {exc}", file=sys.stderr)
            return 2

    if df is None or len(df) == 0:
        print(
            "DATA-BLOCKED: no bars available. Every market-data host is 403-denied by "
            "this environment's egress policy — supply bars with --data instead "
            "(see docs/runbooks/orb-data-drop.md).",
            file=sys.stderr,
        )
        return 2

    power = idata.describe_power(df)

    # Mechanical honesty gate: on an underpowered frame print NO per-cell table at all.
    # A table gets quoted out of context; a refusal cannot be. Same gate as the ORB runner.
    if power.verdict == "UNDERPOWERED":
        print(
            f"UNDERPOWERED: {power.reason}\n"
            f"bars={power.n_bars} span={power.first} -> {power.last}\n"
            "No per-cell results are printed: numbers from this frame would be plumbing "
            "smoke, not a read.",
            file=sys.stderr,
        )
        return 2

    rows = run_grid(df)
    bench = _after_tax_metrics(always_in(df), df.index)
    print(format_report(rows, bench, power, source))
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
