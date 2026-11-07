"""#772 cost-model slippage recalibration study -- research-only, offline.

The research pipeline's frozen ``CostModel`` charges 5.0bps per side
(``backtest/portfolio.py::CostModel.slippage_bps``, re-exported as ``SLIPPAGE_BPS`` from
``backtest/regime.py``). The nightly reflection engine's trigger 3 ("cost divergence") has
fired every trading day since 2026-09-23 against that model. This CLI quantifies the realized
paper-account per-side |slippage| distribution and applies the pre-registered stopping rule
(``docs/research/2026-11-07-cost-model-slippage-preregistration.md``) to decide whether a
recalibrated per-side value should be proposed to the operator.

Data contact is deliberately minimal, per the frozen pre-registration: this module reads
exactly one committed file, ``docs/trading-journal/daily-verification.jsonl``, sliced to
``date <= 2026-11-06``. No network, no Supabase, no broker import, no production code touched.
It never edits the ledger, ``backtest/portfolio.py``, ``backtest/regime.py`` or
``backtest/reflection.py``; it only re-derives the reflection engine's own trailing-window
statistic to prove the re-derivation is faithful before trusting any new number.

The reproduction gate (pre-registration section 7) is the study's sanity check: every stored
``reflection.cost_check`` for all 52 reflection-bearing records must be reproduced exactly.
A mismatch is reported, never coded around.

Usage:
    python3 -m backtest.run_cost_model_slippage_study \
        --out docs/research/2026-11-07-cost-model-slippage-study
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

import backtest.reflection as rfl

# --------------------------------------------------------------------------- frozen constants

# Pre-registration freeze (docs/research/2026-11-07-cost-model-slippage-preregistration.md).
FREEZE_END = "2026-11-06"
CALIBRATION_START = "2026-08-13"
CALIBRATION_END = "2026-09-30"
VALIDATION_START = "2026-10-01"

MODEL_BPS = 5.0
CANDIDATES_BPS: Tuple[float, ...] = (1.0, 2.0, 3.0, 5.0)
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 0
BOOTSTRAP_PERCENTILE = 95.0
ROLLING_WINDOW = 40

DEFAULT_LEDGER = os.path.join("docs", "trading-journal", "daily-verification.jsonl")
SIDES: Tuple[str, ...] = ("entry", "exit")


@dataclass
class Fill:
    """One pooled per-side fill, tagged with its record date for window assignment."""

    value: float
    is_entry: bool
    date: str
    exit_fill_time: str


# --------------------------------------------------------------------------- loading


def load_records(path: str, end: str = FREEZE_END) -> List[Dict[str, Any]]:
    """Read the ledger and keep records whose own ``date`` field is on or before ``end``.

    The slice is load-bearing: the ledger keeps growing while the PR is open, and every frozen
    number in the study must stay pinned to the pre-registration freeze date.
    """
    records: List[Dict[str, Any]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if str(record.get("date", "")) <= end:
                records.append(record)
    return records


def all_trades(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every ``reflection.trades`` record, in ledger order.

    A row with no ``reflection`` key (pre-ship) contributes nothing -- the same no-backfill
    semantics ``build_trailing_window`` uses.
    """
    trades: List[Dict[str, Any]] = []
    for record in records:
        reflection = record.get("reflection") or {}
        trades.extend(reflection.get("trades") or [])
    return trades


def pooled_abs_fills(trades: Sequence[Dict[str, Any]]) -> List[float]:
    """Pool both sides' absolute slippage, dropping nulls (the per-side model unit)."""
    fills: List[float] = []
    for trade in trades:
        for key in ("entry_slippage_bps", "exit_slippage_bps"):
            value = trade.get(key)
            if value is not None:
                fills.append(abs(float(value)))
    return fills


def side_fills(trades: Sequence[Dict[str, Any]], side: str) -> List[float]:
    """Absolute slippage for one side only (``entry`` or ``exit``), nulls dropped."""
    key = "entry_slippage_bps" if side == "entry" else "exit_slippage_bps"
    out: List[float] = []
    for trade in trades:
        value = trade.get(key)
        if value is not None:
            out.append(abs(float(value)))
    return out


def trades_in_window(records: Sequence[Dict[str, Any]], start: str, end: str) -> List[Dict[str, Any]]:
    """All trades from records whose own ``date`` falls in ``[start, end]``."""
    trades: List[Dict[str, Any]] = []
    for record in records:
        date = str(record.get("date", ""))
        if start <= date <= end:
            trades.extend((record.get("reflection") or {}).get("trades") or [])
    return trades


def fills_in_window(records: Sequence[Dict[str, Any]], start: str, end: str) -> List[float]:
    return pooled_abs_fills(trades_in_window(records, start, end))


# --------------------------------------------------------------------------- reproduction gate


def trailing_window_trades(records: Sequence[Dict[str, Any]], index: int) -> List[Dict[str, Any]]:
    """Re-derivation of ``reflection.build_trailing_window`` for the record at ``index``.

    Prior records' own ``reflection.trades`` plus this record's, ordered by ``exit_fill_time``,
    window ``min(n, 20)`` trades. A record with no ``reflection`` key contributes nothing.
    """
    all_records: List[Dict[str, Any]] = []
    for record in records[:index]:
        reflection = record.get("reflection") or {}
        all_records.extend(reflection.get("trades") or [])
    all_records.extend((records[index].get("reflection") or {}).get("trades") or [])
    all_records.sort(key=lambda trade: trade["exit_fill_time"])
    return all_records[-rfl.TRAILING_WINDOW :]


def cost_check(window_trades: Sequence[Dict[str, Any]], model_bps: float = MODEL_BPS) -> Dict[str, Any]:
    """The reflection engine's own trailing-window statistic, re-derived.

    ``model_bps`` defaults to the frozen 5.0bps so the reproduction gate compares like with
    like; the grid passes each candidate instead.
    """
    fills = pooled_abs_fills(window_trades)
    if not fills:
        return {"n": 0, "median_abs_slippage_bps": None, "model_bps": model_bps, "ratio": None}
    median = float(np.median(fills))
    return {
        "n": len(fills),
        "median_abs_slippage_bps": median,
        "model_bps": model_bps,
        "ratio": median / model_bps,
    }


def reproduce_cost_checks(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reproduce every stored ``reflection.cost_check`` and report match/mismatch.

    Returns one entry per reflection-bearing record, in ledger order. ``match`` is bit-for-bit
    on the re-derived median and integer equality on ``n``.
    """
    out: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        reflection = record.get("reflection")
        if not reflection:
            continue
        stored = reflection.get("cost_check") or {}
        reproduced = cost_check(trailing_window_trades(records, index))
        match = (
            reproduced["median_abs_slippage_bps"] == stored.get("median_abs_slippage_bps")
            and reproduced["n"] == stored.get("n")
            and reproduced["ratio"] == stored.get("ratio")
        )
        out.append(
            {
                "date": record.get("date"),
                "n": reproduced["n"],
                "median_abs_slippage_bps": reproduced["median_abs_slippage_bps"],
                "ratio": reproduced["ratio"],
                "stored_median_abs_slippage_bps": stored.get("median_abs_slippage_bps"),
                "stored_ratio": stored.get("ratio"),
                "match": match,
            }
        )
    return out


# --------------------------------------------------------------------------- fill series


def ordered_fills(records: Sequence[Dict[str, Any]]) -> List[Fill]:
    """All pooled fills ordered by the trade's ``exit_fill_time``, entry emitted before exit.

    The tie-break rank (entry 0, exit 1) keeps the within-trade order deterministic, matching
    the pre-registration's section 5.2 operationalization.
    """
    items: List[Tuple[str, int, Fill]] = []
    for record in records:
        date = str(record.get("date", ""))
        for trade in (record.get("reflection") or {}).get("trades") or []:
            exit_time = str(trade.get("exit_fill_time", ""))
            entry = trade.get("entry_slippage_bps")
            if entry is not None:
                items.append((exit_time, 0, Fill(abs(float(entry)), True, date, exit_time)))
            exit_value = trade.get("exit_slippage_bps")
            if exit_value is not None:
                items.append((exit_time, 1, Fill(abs(float(exit_value)), False, date, exit_time)))
    items.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in items]


def rolling_window_medians(fills: Sequence[Fill], window: int = ROLLING_WINDOW) -> List[Dict[str, Any]]:
    """Every contiguous ``window``-fill block's median, with its end index, date and n."""
    blocks: List[Dict[str, Any]] = []
    values = [fill.value for fill in fills]
    for start in range(0, len(values) - window + 1):
        end = start + window - 1
        chunk = values[start : start + window]
        blocks.append(
            {
                "start_index": start,
                "end_index": end,
                "end_date": fills[end].date,
                "n": window,
                "median": float(np.median(chunk)),
            }
        )
    return blocks


def validation_rolling_medians(
    fills: Sequence[Fill], window: int = ROLLING_WINDOW, validation_start: str = VALIDATION_START
) -> List[Dict[str, Any]]:
    """Rolling blocks whose final fill is validation-dated (clause b's denominator)."""
    return [
        block
        for block in rolling_window_medians(fills, window=window)
        if block["end_date"] >= validation_start
    ]


# --------------------------------------------------------------------------- statistics


def percentile_fill_stats(fills: Sequence[float]) -> Dict[str, Any]:
    """Median, IQR, tail quantiles and count for one fill series (descriptive)."""
    if not fills:
        return {"n": 0, "median": None, "iqr": None, "p90": None, "p95": None, "max": None}
    array = np.asarray(fills, dtype=float)
    q25, q75 = np.percentile(array, [25.0, 75.0])
    return {
        "n": len(fills),
        "median": float(np.median(array)),
        "q25": float(q25),
        "q75": float(q75),
        "iqr": float(q75 - q25),
        "p90": float(np.percentile(array, 90.0)),
        "p95": float(np.percentile(array, 95.0)),
        "max": float(array.max()),
    }


def fraction_exceeding(fills: Sequence[float], threshold: float) -> Optional[float]:
    if not fills:
        return None
    return float(sum(1 for value in fills if value > threshold) / len(fills))


def bootstrap_ci_upper(
    fills: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[float]:
    """One-sided 95% percentile-bootstrap upper bound of the sample median.

    Frozen verbatim in the pre-registration: 10,000 resamples, ``numpy.random.default_rng(0)``
    drawn once in resample order, ``numpy.percentile`` at the 95th with default interpolation.
    """
    if not fills:
        return None
    array = np.asarray(fills, dtype=float)
    rng = np.random.default_rng(seed)
    medians = np.empty(resamples, dtype=float)
    for i in range(resamples):
        sample = rng.choice(array, size=array.size, replace=True)
        medians[i] = np.median(sample)
    return float(np.percentile(medians, BOOTSTRAP_PERCENTILE))


def evaluate_stopping_rule(
    ci_upper: Optional[float],
    rolling_medians: Sequence[float],
    model_bps: float = MODEL_BPS,
    candidates: Sequence[float] = CANDIDATES_BPS,
) -> Dict[str, Any]:
    """Apply the frozen stopping rule.

    Fires iff (a) the validation-window bootstrap CI upper bound is strictly below ``model_bps``
    and (b) at least one validation rolling window exists and every one is strictly below
    ``model_bps``. The proposed value is the smallest candidate >= the CI upper bound.
    """
    medians = [float(m) for m in rolling_medians]
    clause_a_below = ci_upper is not None and ci_upper < model_bps
    clause_b_all = len(medians) > 0 and all(m < model_bps for m in medians)
    fired = bool(clause_a_below and clause_b_all)
    proposed: Optional[float] = None
    if fired and ci_upper is not None:
        eligible = [c for c in candidates if c >= ci_upper]
        proposed = min(eligible) if eligible else float(max(candidates))
    return {
        "fired": fired,
        "proposed_bps": proposed,
        "model_bps": model_bps,
        "candidates_bps": list(candidates),
        "clause_a": {"ci_upper": ci_upper, "model_bps": model_bps, "below_model": bool(clause_a_below)},
        "clause_b": {
            "n_windows": len(medians),
            "worst_median": max(medians) if medians else None,
            "model_bps": model_bps,
            "all_below_model": bool(clause_b_all),
        },
    }


# --------------------------------------------------------------------------- the run


def _window_report(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    pooled = pooled_abs_fills(trades)
    report: Dict[str, Any] = {
        "n_fills": len(pooled),
        "pooled": percentile_fill_stats(pooled),
        "sides": {side: percentile_fill_stats(side_fills(trades, side)) for side in SIDES},
    }
    report["grid"] = {}
    for candidate in CANDIDATES_BPS:
        check = cost_check(trades, model_bps=candidate)
        report["grid"]["{:g}bps".format(candidate)] = {
            "model_bps": candidate,
            "median_abs_slippage_bps": check["median_abs_slippage_bps"],
            "ratio": check["ratio"],
            "fraction_exceeding": fraction_exceeding(pooled, candidate),
        }
    return report


def run_study(ledger_path: str, end: str = FREEZE_END) -> Dict[str, Any]:
    """Run the frozen study over the frozen slice and return the results payload."""
    records = load_records(ledger_path, end=end)
    checks = reproduce_cost_checks(records)

    calibration_trades = trades_in_window(records, CALIBRATION_START, CALIBRATION_END)
    validation_trades = trades_in_window(records, VALIDATION_START, end)
    validation_fills = pooled_abs_fills(validation_trades)

    ci_upper = bootstrap_ci_upper(validation_fills)
    fills = ordered_fills(records)
    rolling = validation_rolling_medians(fills)
    stopping = evaluate_stopping_rule(ci_upper, [block["median"] for block in rolling])

    return {
        "study": "2026-11-07-cost-model-slippage",
        "issue": 772,
        "freeze_end": end,
        "windows": {
            "calibration": {"start": CALIBRATION_START, "end": CALIBRATION_END},
            "validation": {"start": VALIDATION_START, "end": end},
        },
        "reproduction_gate": {
            "n_records": len(checks),
            "n_mismatched": sum(1 for entry in checks if not entry["match"]),
            "checks": checks,
        },
        "windows_report": {
            "calibration": _window_report(calibration_trades),
            "validation": _window_report(validation_trades),
        },
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "percentile": BOOTSTRAP_PERCENTILE,
            "validation_median": float(np.median(validation_fills)) if validation_fills else None,
            "ci_upper": ci_upper,
        },
        "rolling": {
            "window": ROLLING_WINDOW,
            "n_blocks_total": len(rolling_window_medians(fills)),
            "n_blocks_validation": len(rolling),
            "worst_median": max((b["median"] for b in rolling), default=None),
            "blocks": rolling,
        },
        "stopping_rule": stopping,
    }


# --------------------------------------------------------------------------- artifacts


def write_artifacts(result: Dict[str, Any], out_dir: str) -> Dict[str, str]:
    """Write the results JSON and the per-date rolling CSV; return their paths."""
    os.makedirs(out_dir, exist_ok=True)
    results_path = os.path.join(out_dir, "cost-model-slippage-results.json")
    rolling_path = os.path.join(out_dir, "cost-model-slippage-rolling.csv")

    with open(results_path, "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=False)
        fh.write("\n")

    with open(rolling_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "n", "median_abs_slippage_bps", "ratio", "match"])
        for entry in result["reproduction_gate"]["checks"]:
            writer.writerow(
                [
                    entry["date"],
                    entry["n"],
                    "{:.12g}".format(entry["median_abs_slippage_bps"]),
                    "{:.12g}".format(entry["ratio"]),
                    "PASS" if entry["match"] else "MISMATCH",
                ]
            )
    return {"results_json": results_path, "rolling_csv": rolling_path}


# --------------------------------------------------------------------------- CLI


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", default=DEFAULT_LEDGER, help="committed verification ledger")
    parser.add_argument("--end", default=FREEZE_END, help="freeze end date (inclusive)")
    parser.add_argument("--out", default=None, help="artifact directory (omit to print only)")
    args = parser.parse_args(argv)

    result = run_study(args.ledger, end=args.end)
    if args.out:
        write_artifacts(result, args.out)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
