"""Daily candlestick study, v3: TIME-STOP grid (84 cells) — #448.

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker *trading* calls.
The only network is a read-only historical-bars pull; ``--data`` needs no network at all.

What this adds over v1/v2
--------------------------
v1 (``run_candlestick_study.py``, 28 cells) tests every pattern context-free with no exit
other than its R-target bracket. v2 (``run_candlestick_context_study.py``, 56 cells) adds a
trend-context filter and found it did not rescue the class (NO_GO). v3 adds a **third,
orthogonal** axis: a maximum holding period (time stop), via the ``max_bars`` keyword the
bracket engine gained in #448 PR A. Per decision D-A of the #448 sub-plan, this is an ADDED
factor, not a replacement one — the frozen v1 pattern-extreme stop and R-target geometry are
kept verbatim, and only the holding period is capped. A v3 cell therefore differs from its v1
twin in exactly ONE respect (the time stop), which is what lets any difference between them be
attributed to the time stop rather than to a confound.

Per decision D-B, v3 runs **CONTEXT_NONE only** — there is no context x time-stop cross. v2
already answered the context question (NO_GO); crossing it here would put the grid at 252
cells and the cumulative family at 336 for no new question. Every row this module produces
carries ``context: CONTEXT_NONE`` explicitly, so that is auditable rather than assumed.

Multiplicity — read this before quoting any cell
--------------------------------------------------
This is round 3 of a widening search, and widening must not launder multiplicity by resetting
the trial count each round. Two numbers are therefore always reported:

- **this grid**: N = 84 (14 arms x R{2,3} x time-stop{3,5,10})
- **cumulative family**: N = 168 (v1's 28 + v2's 56 + this grid's 84)

**This round's own N (84) is numerically equal to the PREVIOUS round's cumulative N (84,
v1+v2). That equality is a coincidence of the grid sizes chosen, not a re-use of the same 84
trials** — the 84 cells counted here are the NEW v3 grid (time-stop x arm x R), disjoint from
the 84 already-run v1+v2 cells. The deflated-Sharpe bar for this round uses the cumulative
N = 168, not 84.

Time-stop levels ``{3, 5, 10}`` bars are fixed from doctrine before any number is seen: 3 and
5 bars are the swing-trading horizon over which candlestick doctrine claims a pattern "plays
out"; 10 days is Bulkowski's standard measurement horizon for pattern statistics — the same
justification style v1's own detector thresholds use.

Run: ``python3 -m backtest.run_candlestick_timestop_study [--data FILE] [--vehicle SPY]``
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
from backtest.run_candlestick_context_study import CUMULATIVE_N as V2_CUMULATIVE_N
from backtest.run_candlestick_study import (
    ARMS,
    N_CELLS as V1_N_CELLS,
    R_GRID,
    RANDOM_SEED,
    SPY_BAR,
    _fetch_daily,
    always_in,
    build_cell,
    build_random_cell,
    cell_status,
)

#: The frozen time-stop factor for v3 (bars held). ``None`` is deliberately absent — that
#: reproduces v1's own (unbounded) cells and re-running them here would double-count 28
#: trials. CONTEXT_NONE only (D-B): no context x time-stop cross.
TIME_STOP_GRID: Tuple[int, ...] = (3, 5, 10)

N_CELLS = len(ARMS) * len(R_GRID) * len(TIME_STOP_GRID)    # 84
CUMULATIVE_N = V2_CUMULATIVE_N + N_CELLS                    # 168 -- the DSR trial count


def run_grid(df) -> list:
    """Every frozen v3 cell over ``df``. One row dict per cell."""
    rows = []
    for arm in ARMS:
        for r in R_GRID:
            for time_stop in TIME_STOP_GRID:
                sim = build_cell(df, arm, r, max_bars=time_stop)
                rand = build_random_cell(df, arm, r, max_bars=time_stop)
                rows.append({
                    "arm": arm[0],
                    "direction": arm[2],
                    "r": r,
                    "time_stop": time_stop,
                    "context": cs.CONTEXT_NONE,
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
        "Daily candlestick study v3 — TIME-STOP grid (84 cells)",
        f"source: {source}",
        f"power: {power.verdict} — {power.reason}",
        f"bars: {power.n_bars}  span: {power.first} -> {power.last}",
        f"frozen SPY bar (median-window after-tax Calmar): {SPY_BAR:.4f}",
        f"always-in after-tax CalmarUS: {bench['calmar_us']:+.4f}",
        "",
        f"{'arm':<20} {'dir':<6} {'R':>3} {'stop':>5} {'CalmarUS':>10} {'>bar?':>6} "
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
            f"{row['arm']:<20} {row['direction']:<6} "
            f"{row['r']:>3.0f} {row['time_stop']:>5} {calmar_txt} {clears:>6} "
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
        f"DSR multiplicity — CUMULATIVE family "
        f"(v1 {V1_N_CELLS} + v2 {V2_CUMULATIVE_N - V1_N_CELLS} + v3 {N_CELLS}): "
        f"N = {CUMULATIVE_N}",
        "The cumulative N is the one the deflated-Sharpe bar must use. Widening the search "
        "raises that bar; it never lowers it.",
        f"NOTE: this round's own N ({N_CELLS}) numerically equals the PREVIOUS round's "
        f"cumulative N ({V2_CUMULATIVE_N}) — a coincidence of grid sizes, not a re-run of "
        "those same trials.",
    ]
    if cleared:
        out.append("clearing cells: " + ", ".join(
            f"{r['arm']}/R{r['r']:.0f}/stop{r['time_stop']}" for r in cleared
        ))
    if untraded:
        out.append(
            "NOTE: a never-traded cell is not evidence about the pattern — the frozen "
            "rule found no setup on this frame. Report it, never omit it."
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

    # Same mechanical honesty gate as v1/v2: no per-cell table on an underpowered frame.
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
