"""Daily candlestick study, v2: TREND-CONTEXT grid (56 cells) — refs #422, #431.

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker *trading* calls.
The only network is a read-only historical-bars pull; ``--data`` needs no network at all.

What this adds over v1
----------------------
v1 (``run_candlestick_study.py``, 28 cells) tests every pattern **context-free**. Classic
candlestick doctrine is explicit that these patterns are context-dependent — a hammer means
something at the end of a downtrend and nothing mid-range — so v1 tests them in their
weakest possible form. v2 adds the trend context as a frozen 2-level factor.

Both canonical readings are frozen, because neither may be preferred after seeing results:

- ``reversal`` — the textbook reading. Bullish patterns are reversal signals, so they count
  only in a DOWNtrend (close < SMA200); bearish only in an UPtrend.
- ``continuation`` — the with-trend reading. Bullish patterns count only in an UPtrend.

The trend definition **reuses** ``regime_signals.sma_signal`` (the incumbent 200-DMA filter)
rather than introducing a second, drifting definition of "trend".

Multiplicity — read this before quoting any cell
------------------------------------------------
This is the second round of a widening search, and widening must not launder multiplicity by
resetting the trial count each round. Two numbers are therefore always reported:

- **this grid**: N = 56 (14 arms × 2 R × 2 contexts)
- **cumulative family**: N = 84 (v1's 28 + this grid's 56)

The deflated-Sharpe bar must be computed against the **cumulative** N. The honest consequence,
stated up front: **every added round raises the bar**, so a survivor found late needs a larger
effect to be credible than one found in round 1.

Run: ``python3 -m backtest.run_candlestick_context_study [--data FILE] [--vehicle SPY]``
Exit codes: ``0`` the grid ran; ``2`` data unavailable or underpowered (no table printed).
All numbers come from a live read-only pull or a local file; no price is ever fabricated.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional, Tuple

import numpy as np

from backtest import candlestick as cs
from backtest import intraday_data as idata
from backtest.run_candidate_survey import _after_tax_metrics
from backtest.run_candlestick_study import (
    ARMS,
    N_CELLS as V1_N_CELLS,
    R_GRID,
    SPY_BAR,
    _fetch_daily,
    always_in,
    build_cell,
    build_random_cell,
    cell_status,
)

#: The frozen context factor for v2. ``CONTEXT_NONE`` is deliberately absent — that is v1's
#: grid and is not re-run here (re-running it would double-count those 28 trials).
CONTEXT_GRID: Tuple[str, ...] = (cs.CONTEXT_REVERSAL, cs.CONTEXT_CONTINUATION)

N_CELLS = len(ARMS) * len(R_GRID) * len(CONTEXT_GRID)      # 56
CUMULATIVE_N = V1_N_CELLS + N_CELLS                        # 84 — the DSR trial count


def run_grid(df) -> list:
    """Every frozen v2 cell over ``df``. One row dict per cell."""
    rows = []
    for arm in ARMS:
        for r in R_GRID:
            for context in CONTEXT_GRID:
                sim = build_cell(df, arm, r, context=context)
                rand = build_random_cell(df, arm, r, context=context)
                rows.append({
                    "arm": arm[0],
                    "direction": arm[2],
                    "r": r,
                    "context": context,
                    "metrics": _after_tax_metrics(sim, df.index),
                    "random_calmar_us": _after_tax_metrics(rand, df.index)["calmar_us"],
                    "trade_count": sim["trade_count"],
                    "max_drawdown": sim["max_drawdown"],
                })
    return rows


def _sort_key(row: dict) -> tuple:
    """Best finite Calmar first; then RUINED, then no-trades. NaN never sorts silently."""
    rank = {"ok": 0, "RUINED": 1, "no-trades": 2}[cell_status(row)]
    calmar = row["metrics"]["calmar_us"]
    return (rank, -calmar if np.isfinite(calmar) else 0.0)


def format_report(rows: list, bench: dict, power, source: str) -> str:
    """Render the per-cell table. Callers MUST NOT call this on an underpowered frame."""
    out = [
        "Daily candlestick study v2 — TREND-CONTEXT grid (56 cells)",
        f"source: {source}",
        f"power: {power.verdict} — {power.reason}",
        f"bars: {power.n_bars}  span: {power.first} -> {power.last}",
        f"frozen SPY bar (median-window after-tax Calmar): {SPY_BAR:.4f}",
        f"always-in after-tax CalmarUS: {bench['calmar_us']:+.4f}",
        "",
        f"{'arm':<20} {'dir':<6} {'ctx':<13} {'R':>3} {'CalmarUS':>10} {'>bar?':>6} "
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
            f"{row['arm']:<20} {row['direction']:<6} {row['context']:<13} "
            f"{row['r']:>3.0f} {calmar_txt} {clears:>6} "
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
        "",
        f"DSR multiplicity — THIS grid: N = {N_CELLS}",
        f"DSR multiplicity — CUMULATIVE family (v1 {V1_N_CELLS} + v2 {N_CELLS}): "
        f"N = {CUMULATIVE_N}",
        "The cumulative N is the one the deflated-Sharpe bar must use. Widening the search "
        "raises that bar; it never lowers it.",
    ]
    if cleared:
        out.append("clearing cells: " + ", ".join(
            f"{r['arm']}/{r['context']}/R{r['r']:.0f}" for r in cleared
        ))
    if untraded:
        out.append(
            "NOTE: a never-traded cell is not evidence about the pattern — the context "
            "filter admitted no setup. Report it, never omit it."
        )
    return "\n".join(out)


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

    # Same mechanical honesty gate as v1: no per-cell table on an underpowered frame.
    # A table gets quoted out of context; a refusal cannot be.
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
