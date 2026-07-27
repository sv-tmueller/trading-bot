"""Pooled #398 overfitting gate over the mes_swing family (#457 PR A, n_trials=24).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls — no network anywhere in this module; the ``--data`` path uses none.

``run_mes_swing_study.py`` (the 24-cell frozen grid) never invokes the #398 gate itself —
it only screens each cell's own per-window after-tax Calmar against the frozen bar. This
module applies the gate **across the family's cumulative N (24, D2 — a fresh family with no
prior trials to pool in)**, mirroring ``run_turtle_breakout.evaluate_daily_gate`` /
``run_candlestick_gate.py`` in its conventions verbatim: non-annualized per-day trial
Sharpes, best-cell selection by ``argmax``, a ``(T, 24)`` per-day performance matrix for
PBO/CSCV, and best-cell-minus-SPY-buy-and-hold per-day uplifts for the block bootstrap,
seeded with the study module's own ``RANDOM_SEED`` (42).

It introduces **no new free parameter**: ``ARMS``, ``R_GRID``, ``RANDOM_SEED``,
``build_cell``, ``always_in`` are all imported unchanged from ``run_mes_swing_study``. This
module never modifies that study.

Gate cells use the BASE co-primary cost preset's pre-tax equity curve — the same convention
``run_turtle_breakout``/``run_candlestick_gate`` already use (neither layers the after-tax
model into the #398 gate; only the primary Calmar verdict in the study module does that).
This is a disclosed choice, not a silent one: the study module's own verdict still screens
BOTH cost presets; only this gate's per-day robustness read uses one.

The gate is only defined at full statistical power: ``main`` refuses to run below
``PROMOTABLE`` (``intraday_data.describe_power``), the same floor the study module enforces
for its own per-cell table.

Run: ``python3 -m backtest.run_mes_swing_gate --data FILE``
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
from backtest.run_mes_swing_study import (
    ARMS,
    COST_PRESETS,
    N_CELLS,
    R_GRID,
    RANDOM_SEED,
    always_in,
    build_cell,
)

#: Cell key: (arm_id, R). Mirrors the frozen study's own cell identity exactly.
CellKey = Tuple[str, float]

#: Base co-primary preset's per-side commission (disclosed above — the gate's own choice).
_GATE_COMMISSION_BPS = COST_PRESETS[0][1]


def build_all_cells(df: pd.DataFrame) -> "dict[CellKey, dict]":
    """Every frozen (arm, R) cell over ``df``, at the base cost preset. 24 entries."""
    return {
        (arm[0], r): build_cell(df, arm, r, _GATE_COMMISSION_BPS)
        for arm in ARMS
        for r in R_GRID
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


def evaluate_mes_gate(cells: "dict[CellKey, dict]", spy_daily_eq: pd.Series) -> dict:
    """The #398 gate over the pooled family (N=24).

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
    print(f"Pooled #398 overfitting gate — mes_swing family, cumulative N={N_CELLS}")
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
    spy_eq = always_in(df, _GATE_COMMISSION_BPS)["equity_curve"]
    result = evaluate_mes_gate(cells, spy_eq)
    _print_report(power, f"local:{args.data}", result)
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
