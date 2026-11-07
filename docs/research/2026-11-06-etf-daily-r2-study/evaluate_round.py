"""Phase 5 verdict tool for research round etf-daily-r2 (orchestrator-run, research only).

Reads the committed development returns CSV and the two result files of one
candidate, builds the gate inputs exactly as the frozen pre-registration
(section 7) defines them, calls ``evaluate_candidate`` with the frozen
``gate_kwargs``, renders the scorecard, and writes
``<out>/<candidate_id>-verdict.json`` and ``<out>/<candidate_id>-scorecard.md``.
No network, no broker, no LLM. ``trials.json`` is read only
(``programme_sharpes``); the gate inputs are built from the returns CSV and
never recomputed after the holdout.

The r1 verdict tool (``docs/research/2026-11-03-etf-daily-r1-study/evaluate_round.py``)
is the template; the shape is unchanged, only the study dir and round scope.

Usage (from the worktree root):
  venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/evaluate_round.py \
      --candidate etf-daily-r2-vol-regime-gating --out /tmp/r2-verdicts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from backtest.pipeline_gate import evaluate_candidate  # noqa: E402
from backtest.scorecard import _scored_years, render_scorecard_markdown  # noqa: E402
from backtest.trial_store import programme_sharpes  # noqa: E402

STUDY_DIR = ROOT / "docs/research/2026-11-06-etf-daily-r2-study"
PIPELINE_DIR = ROOT / "docs/research/pipeline"

# Frozen gate_kwargs (r2 pre-registration section 7; inherited from r1).
GATE_KWARGS = {
    "pbo_n_splits": 16,
    "bootstrap_block_length": 2,
    "bootstrap_n_boot": 1000,
    "bootstrap_seed": 0,
    "bootstrap_alpha": 0.05,
    "dsr_sr_benchmark": 0.0,
}


def year_calmar(returns: pd.Series) -> float | None:
    """Pre-tax Calmar of one calendar year of daily returns, equity rebased to 1.0 (section 7)."""
    eq = (1.0 + returns.astype(float)).cumprod()
    running_max = np.maximum.accumulate(np.concatenate([[1.0], eq.to_numpy()]))[1:]
    dd = float(np.max(1.0 - eq.to_numpy() / running_max))
    if dd <= 0.0:
        return None
    return float((eq.iloc[-1] - 1.0) / dd)


def uplift_vector(selected: pd.Series, benchmark: pd.Series) -> Tuple[np.ndarray, list]:
    """One uplift per scored development calendar year: Calmar_Y(selected) - Calmar_Y(benchmark)."""
    years = _scored_years(selected.index)
    out, used = [], []
    for y in years:
        mask = selected.index.year == y
        c = year_calmar(selected[mask])
        b = year_calmar(benchmark[mask])
        if c is None or b is None:
            drop = "selected" if c is None else "benchmark"
            print(f"uplift: year {y} dropped (zero drawdown on {drop} side)")
        else:
            out.append(c - b)
            used.append((y, c, b))
    return np.array(out, dtype=float), used


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-holdout", action="store_true", help="retest without holdout (Phase 4 h)")
    args = ap.parse_args()
    cid = args.candidate
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    dev = json.loads((PIPELINE_DIR / cid / "development_result.json").read_text())
    hold = None
    if not args.no_holdout:
        hold = json.loads((PIPELINE_DIR / cid / "holdout_result.json").read_text())
    csv = pd.read_csv(STUDY_DIR / f"{cid}-development-returns.csv", index_col=0, parse_dates=True)

    trial_ids = dev["trial_ids"]
    selected = dev["selected_trial_id"]
    missing = [t for t in trial_ids if t not in csv.columns]
    if missing or "benchmark" not in csv.columns:
        raise KeyError(f"returns csv missing columns: {missing or 'benchmark'}")
    perf = csv[trial_ids].to_numpy(dtype=float)
    finite_rows = np.isfinite(perf).all(axis=1)
    perf_matrix = perf[finite_rows]
    returns_best = csv[selected].to_numpy(dtype=float)
    returns_best = returns_best[np.isfinite(returns_best)]
    uplifts, used = uplift_vector(csv[selected], csv["benchmark"])

    all_sharpes = programme_sharpes()
    verdict = evaluate_candidate(
        dev["scorecard"],
        None if hold is None else hold["scorecard"],
        returns_best=returns_best,
        all_trial_sharpes=all_sharpes,
        perf_matrix=perf_matrix,
        uplifts=uplifts,
        gate_kwargs=GATE_KWARGS,
    )
    md = render_scorecard_markdown(dev["scorecard"], None if hold is None else hold["scorecard"], verdict)

    record = {
        "candidate_id": cid,
        "selected_trial_id": selected,
        "n_trials_candidate": len(trial_ids),
        "programme_trial_count": int(all_sharpes.size),
        "perf_matrix_shape": list(perf_matrix.shape),
        "n_returns_best": int(returns_best.size),
        "uplift_years": [{"year": y, "calmar_selected": c, "calmar_benchmark": b} for y, c, b in used],
        "uplifts": uplifts.tolist(),
        "gate_kwargs": GATE_KWARGS,
        "verdict": verdict,
        "n_w_development": len(dev["scorecard"]["window_calmars"]),
    }
    (out / f"{cid}-verdict.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (out / f"{cid}-scorecard.md").write_text(md)
    print(md)
    print(json.dumps({k: v for k, v in record.items() if k != "verdict"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
