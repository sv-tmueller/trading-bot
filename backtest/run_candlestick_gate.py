"""Pooled #398 overfitting gate over the cumulative candlestick family (#443/#448, N=168).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls — the only network is the read-only historical-bars pull already
wired into ``run_candlestick_study._fetch_daily``; this module's ``--data`` path uses none.

None of the three frozen runners — ``run_candlestick_study.py`` (28 cells),
``run_candlestick_context_study.py`` (56 cells), ``run_candlestick_timestop_study.py``
(84 cells) — invokes the #398 gate itself; each only screens its own cells' after-tax
Calmar against the frozen SPY bar. This module applies the gate **across the pooled
cumulative family** (v1's 28 + v2's 56 + v3's 84 = 168), mirroring
``run_turtle_breakout.evaluate_daily_gate`` in its conventions verbatim: non-annualized
per-day trial Sharpes (required by ``overfitting_gate``'s units contract — see its module
docstring), best-cell selection by ``argmax`` Sharpe, a ``(T, 168)`` per-day performance
matrix for PBO/CSCV, and best-cell-minus-SPY-buy-and-hold per-day uplifts for the block
bootstrap, seeded with the same ``RANDOM_SEED`` (42) the frozen runners already use.

It introduces **no new free parameter**: every cell definition, R, context, time-stop
level and seed is imported unchanged from the three frozen runners (``ARMS``, ``R_GRID``,
``build_cell``, ``always_in``, ``RANDOM_SEED`` from ``run_candlestick_study``;
``CONTEXT_GRID`` from ``run_candlestick_context_study``; ``TIME_STOP_GRID`` from
``run_candlestick_timestop_study``). This module never modifies any of the three.

The v3 extension (#448) was committed BEFORE any real SPY number was seen for it — the
cell-selection rule inside the gate stays frozen before results exist, so pooling the new
84 cells in is not a post-hoc choice, exactly as v1/v2's own pooling (#443 step 1) was not.
The v1+v2 subset of 84 cells is untouched by this extension: same keys, same sims,
pinned by ``tests/test_run_candlestick_gate.py::test_the_v1_v2_subset_is_unchanged_by_the_v3_extension``
— the recorded N=84 read has to stay reproducible.

The gate is only defined at full statistical power: ``main`` refuses to run below
``PROMOTABLE`` (``intraday_data.describe_power``), the same floor the frozen runners
already enforce for their own per-cell tables.

Run: ``python3 -m backtest.run_candlestick_gate --data FILE``
Exit codes: ``0`` the gate ran (pass or fail is reported in the body); ``2`` data
unavailable or the frame does not clear ``PROMOTABLE`` power.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from backtest import intraday_data as idata
from backtest.overfitting_gate import DSR_THRESHOLD, PBO_THRESHOLD, evaluate_gate
from backtest.run_candlestick_context_study import CONTEXT_GRID
from backtest.run_candlestick_study import (
    ARMS,
    R_GRID,
    RANDOM_SEED,
    always_in,
    build_cell,
)
from backtest.run_candlestick_timestop_study import TIME_STOP_GRID
from backtest.candlestick import CONTEXT_NONE

#: Cell key: (arm_name, R, "context" for v1/v2 or "timestopN" for v3). Mirrors the frozen
#: runners' own cell identity; the third element's string space is disjoint between the
#: context labels ("none"/"reversal"/"continuation") and the "timestopN" labels, so keys
#: never collide across grids.
CellKey = Tuple[str, float, str]

N_V1_CELLS = len(ARMS) * len(R_GRID)                       # 28
N_V2_CELLS = len(ARMS) * len(R_GRID) * len(CONTEXT_GRID)   # 56
N_V3_CELLS = len(ARMS) * len(R_GRID) * len(TIME_STOP_GRID)  # 84
N_CELLS = N_V1_CELLS + N_V2_CELLS + N_V3_CELLS              # 168 — the pooled trial count


def build_all_cells(df: pd.DataFrame) -> "dict[CellKey, dict]":
    """Every frozen cell of the cumulative family (v1's 28 + v2's 56 + v3's 84) over ``df``.

    Rebuilds only the REAL cell for each arm/R/context/time-stop — the gate needs each
    cell's own equity curve, not its random-entry twin (the twin comparison is each
    runner's own primary read, already reported there). The v1+v2 subset (the first 84
    keys built here) is byte-identical to the pre-#448 gate — this function only ADDS the
    84 v3 keys, it never perturbs the earlier ones.
    """
    cells: "dict[CellKey, dict]" = {}
    for arm in ARMS:
        for r in R_GRID:
            cells[(arm[0], r, CONTEXT_NONE)] = build_cell(df, arm, r)
    for arm in ARMS:
        for r in R_GRID:
            for context in CONTEXT_GRID:
                cells[(arm[0], r, context)] = build_cell(df, arm, r, context=context)
    for arm in ARMS:
        for r in R_GRID:
            for time_stop in TIME_STOP_GRID:
                cells[(arm[0], r, f"timestop{time_stop}")] = build_cell(
                    df, arm, r, max_bars=time_stop
                )
    return cells


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


def evaluate_candlestick_gate(cells: "dict[CellKey, dict]", spy_daily_eq: pd.Series) -> dict:
    """The #398 gate over the pooled cumulative family (N=84).

    ``cells`` maps cell key -> cell sim (as returned by ``build_all_cells``). All cells'
    per-day returns are put on their common index (zero-filled — a bracket is flat most
    days); the best-Sharpe cell feeds DSR, all cells feed the PBO matrix, and best-minus-
    SPY-buy-and-hold per-day returns feed the block bootstrap.
    """
    keys = list(cells.keys())
    common = None
    for _k, sim in cells.items():
        idx = sim["equity_curve"].index
        common = idx if common is None else common.intersection(idx)
    common = common.intersection(spy_daily_eq.index)

    cols = [_daily_returns_on(common, cells[k]["equity_curve"]) for k in keys]
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


def _print_report(power: "idata.PowerReport", source: str, result: dict) -> None:
    print(f"Pooled #398 overfitting gate — candlestick family, cumulative N={N_CELLS}")
    print(f"source: {source}")
    print(f"power: {power.summary()}")
    print(f"n_trials: {result['n_trials']}")
    print(f"best cell: {result['best_cell']} over {result['n_common_days']} common days")

    if result["error"]:
        print(f"gate uncomputable: {result['error']}")
        return

    gate = result["gate"]
    dsr_pass = gate["dsr"] >= DSR_THRESHOLD
    pbo_pass = gate["pbo"] < PBO_THRESHOLD
    bootstrap_pass = gate["ci_low"] > 0.0

    print(f"DSR {gate['dsr']:.4f} (threshold >= {DSR_THRESHOLD}) "
          f"-> {'PASS' if dsr_pass else 'FAIL'}")
    print(f"PBO {gate['pbo']:.4f} (threshold < {PBO_THRESHOLD}) "
          f"-> {'PASS' if pbo_pass else 'FAIL'}")
    print(f"bootstrap ci_low {gate['ci_low']:.6f} (threshold > 0) "
          f"-> {'PASS' if bootstrap_pass else 'FAIL'}")
    print(f"combined verdict -> {'PASS' if gate['passed'] else 'FAIL'}")
    if gate["reasons"]:
        print(f"reasons: {'; '.join(gate['reasons'])}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True,
                    help="local CSV/Parquet of daily bars (no network)")
    args = ap.parse_args(argv)

    try:
        df = idata.load_local(args.data)
    except Exception as exc:                       # noqa: BLE001 - report, never crash
        print(f"DATA-BLOCKED: could not load {args.data}: {exc}", file=sys.stderr)
        return 2

    power = idata.describe_power(df)
    if power.verdict != "PROMOTABLE":
        print(
            f"REFUSED: this gate is only defined at PROMOTABLE power, got {power.verdict}.\n"
            f"{power.summary()}",
            file=sys.stderr,
        )
        return 2

    cells = build_all_cells(df)
    spy_eq = always_in(df)["equity_curve"]
    result = evaluate_candlestick_gate(cells, spy_eq)
    _print_report(power, f"local:{args.data}", result)
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
