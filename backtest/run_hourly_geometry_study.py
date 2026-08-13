"""CLI: run the hourly bracket-geometry/cadence/sizing study grid (#571 step D/E).

Research-only, GET-only-free (no network at all -- every input is a local CSV). Consumes
two decisions CSVs already emitted by ``scripts/emit_hourly_decisions.ts`` (one per cadence)
plus the staged 5Min bars CSV, and prints the full 6-cell grid (per-arm exit distribution +
expectancy), the no-flatten counterfactual, and the sizing-cap equity replay -- the exact
tables ``docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md`` quotes verbatim.

Usage::

    python3 -m backtest.run_hourly_geometry_study \\
        --decisions-60m <path/to/decisions_60m.csv> \\
        --decisions-30m <path/to/decisions_30m.csv> \\
        --bars5 data/intraday/SPY_5min.csv

The two decisions CSVs are produced by (never committed, regenerate locally) -- ``--bars5``
on the emitter is load-bearing: it is what lets entryRef key off the fill-instant price
rather than the candidate bar's own (up to ~1h07m-stale) close::

    CLAUDE_AGENT_NO_BROKER=1 deno run --allow-env --allow-read=data,scripts,supabase/functions \\
        --allow-write=<out-dir> scripts/emit_hourly_decisions.ts \\
        --bars data/intraday/SPY_60min.csv --bars5 data/intraday/SPY_5min.csv \\
        --out <out-dir>/decisions_60m.csv --period-minutes 60
    CLAUDE_AGENT_NO_BROKER=1 deno run --allow-env --allow-read=data,scripts,supabase/functions \\
        --allow-write=<out-dir> scripts/emit_hourly_decisions.ts \\
        --bars data/intraday/SPY_30min.csv --bars5 data/intraday/SPY_5min.csv \\
        --out <out-dir>/decisions_30m.csv --period-minutes 30
"""
from __future__ import annotations

import argparse
from typing import List, Sequence

from backtest.hourly_geometry import (
    Trade,
    cost_drag_diagnostic,
    exit_distribution,
    expectancy_r,
    load_decisions_csv,
    no_flatten_counterfactual,
    replay_equity,
    simulate_hourly_geometry,
)
from backtest.intraday_data import load_local

R_MULTIPLES: Sequence[float] = (1.0, 1.5, 2.0)
SIZING_CAPS: Sequence[float] = (0.10, 0.25, 0.50, 1.00)
CADENCES = (("60m", 60), ("30m", 30))


def run_cell(decisions_path: str, r_multiple: float, period_minutes: int, bars5) -> dict:
    decisions = load_decisions_csv(decisions_path, r_multiple)
    result = simulate_hourly_geometry(decisions, bars5, period_minutes=period_minutes)
    trades: List[Trade] = result["trades"]
    flattened = [t for t in trades if t.exit_reason == "flatten"]
    counterfactual = no_flatten_counterfactual(flattened, bars5) if flattened else []
    replays = {cap: replay_equity(trades, cap) for cap in SIZING_CAPS}
    return {
        "trades": trades,
        "exit_distribution": exit_distribution(trades),
        "expectancy_r": expectancy_r(trades),
        "n_flattened": len(flattened),
        "counterfactual_expectancy_r": expectancy_r(counterfactual) if counterfactual else float("nan"),
        "replays": replays,
        "cost_drag": cost_drag_diagnostic(trades),
    }


def render_cell(cadence_label: str, r_multiple: float, cell: dict) -> str:
    cd = cell["cost_drag"]
    lines = [
        f"--- cadence={cadence_label} R={r_multiple:.1f} ---",
        f"trades: {len(cell['trades'])}  expectancy(R): {cell['expectancy_r']:.4f}",
        f"exit distribution: {cell['exit_distribution']}",
        f"no-flatten counterfactual: {cell['n_flattened']} flattened trades, "
        f"counterfactual expectancy(R): {cell['counterfactual_expectancy_r']:.4f}",
        f"cost drag: median stop_distance=${cd['median_stop_distance']:.4f} "
        f"median entry-slippage cost=${cd['median_entry_slippage_cost']:.4f} "
        f"(median cost/stop_distance={cd['median_cost_over_stop_distance']:.3f}); "
        f"{cd['pct_entry_slippage_exceeds_stop_distance']:.1f}% of trades have entry "
        f"slippage alone >= the whole stop distance",
    ]
    for cap in SIZING_CAPS:
        r = cell["replays"][cap]
        lines.append(
            f"  cap={cap:.2f}: ending_equity=${r['ending_equity']:,.2f} "
            f"total_return={r['total_return']:+.4%} max_dd={r['max_drawdown']:.4%} "
            f"breached_15pct_floor={r['breached_15pct_floor']}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decisions-60m", required=True)
    ap.add_argument("--decisions-30m", required=True)
    ap.add_argument("--bars5", default="data/intraday/SPY_5min.csv")
    args = ap.parse_args(argv)

    bars5 = load_local(args.bars5)
    decisions_paths = {"60m": args.decisions_60m, "30m": args.decisions_30m}

    print("Hourly bracket-geometry/cadence/sizing study -- frozen 6-cell grid (#571)")
    print(f"bars5 source: {args.bars5} ({len(bars5)} rows, {bars5.index[0]} -> {bars5.index[-1]})")
    print()

    for cadence_label, period_minutes in CADENCES:
        for r_multiple in R_MULTIPLES:
            cell = run_cell(decisions_paths[cadence_label], r_multiple, period_minutes, bars5)
            print(render_cell(cadence_label, r_multiple, cell))
            print()

    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
