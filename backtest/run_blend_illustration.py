"""Illustrative candidate-plus-benchmark blend, for the #758 diversifier-bar decision.

Research-only. Lives in ``backtest/``, is never imported by ``supabase/functions/``,
makes no network or broker call, uses no LLM, and touches no trial store.

Why this exists
---------------
Roadmap C.2b asked whether a diversifier candidate should be judged stand-alone
or as a pre-registered blend with SPY under one risk budget. Issue #758 settles
that question. This script produces the *illustrative* arithmetic behind the
decision note (``docs/research/2026-11-07-diversifier-bar-decision.md``): what
the blend criterion would have done to the two etf-daily-r2 candidates that came
closest to the stand-alone bar.

It is **post-hoc and illustrative**. It reads two already-committed development
returns files from a finished round, re-uses each candidate's selected trial, and
re-scores nothing. It is not a verdict, not a retest, and it never re-opens a
round: no holdout is read, no trial id is minted, no gate is re-run.

What it reads
-------------
Exactly two frozen results artifacts, one column set each:

- ``docs/research/2026-11-06-etf-daily-r2-study/etf-daily-r2-donchian-trend-breakout-development-returns.csv``
- ``docs/research/2026-11-06-etf-daily-r2-study/etf-daily-r2-vol-regime-gating-development-returns.csv``

Both are read only (the study directory is a frozen results artifact). Paths are
repo-root-anchored by default and overridable on the command line.

Why no DSR, PBO or bootstrap on the blend
-----------------------------------------
Constraint (b) of #758: the blend re-uses the *selected* trial's returns from a
round that has already been evaluated and whose 18 configurations are already in
the programme store (37 trials). A blend is a linear re-weighting of one existing
trial against the benchmark, not a new configuration, so it adds nothing to the
round budget or the DSR vector -- and computing a fresh DSR/PBO on it would be a
second grid on the same data, which is exactly what the constraint forbids. This
module therefore deliberately imports nothing from ``backtest.overfitting_gate``
and re-implements none of its thresholds.

Run: ``venv/bin/python -m backtest.run_blend_illustration``
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

STUDY_DIR = REPO_ROOT / "docs" / "research" / "2026-11-06-etf-daily-r2-study"

_TRADING_DAYS = 252

# Candidate id -> (returns file, selected trial column, human label). Both files
# live in the same frozen study directory; the selected trial ids are the ones
# the r2 verdict records for each candidate.
CANDIDATES: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "etf-daily-r2-donchian-trend-breakout",
        "etf-daily-r2-donchian-trend-breakout-development-returns.csv",
        "etf-daily-r2-donchian-trend-breakout-05",
        "#764 Donchian trend breakout",
    ),
    (
        "etf-daily-r2-vol-regime-gating",
        "etf-daily-r2-vol-regime-gating-development-returns.csv",
        "etf-daily-r2-vol-regime-gating-06",
        "#763 vol-regime gating",
    ),
)

# The two stated blend weights: 50/50 and a benchmark-heavy 30/70. The 30/70 leg
# is included because the illustration shows the verdict flipping on the weight
# alone, which is itself part of the argument for keeping the stand-alone bar.
WEIGHTS: Tuple[float, ...] = (0.5, 0.3)


# ---------------------------------------------------------------------------
# Metric primitives (definitions follow backtest/scorecard.py)
# ---------------------------------------------------------------------------

def _years_between(idx: pd.DatetimeIndex) -> float:
    return (idx[-1] - idx[0]).days / 365.25


def _curve_metrics(curve: pd.Series) -> Dict[str, Optional[float]]:
    """CAGR, max drawdown (non-negative magnitude) and Calmar on an equity curve.

    Mirrors ``backtest.scorecard._curve_metrics`` for a curve that stays strictly
    positive: CAGR from the first to the last point, drawdown as the deepest
    peak-to-trough magnitude, Calmar as their ratio. A zero drawdown gives a
    ``None`` Calmar rather than an infinity.
    """
    start = float(curve.iloc[0])
    end = float(curve.iloc[-1])
    span_years = _years_between(curve.index)
    drawdown = (curve - curve.cummax()) / curve.cummax()
    max_dd = max(0.0, float(-drawdown.min()))
    cagr = float((end / start) ** (1.0 / span_years) - 1.0) if span_years > 0 else None
    calmar = float(cagr / max_dd) if (cagr is not None and max_dd > 0.0) else None
    return {"cagr": cagr, "max_drawdown": max_dd, "calmar": calmar}


def scored_years(idx: pd.DatetimeIndex) -> List[int]:
    """Full calendar years only, the repo's n_w convention (``scorecard._scored_years``).

    A year Y counts when the index starts on or before Y-01-07 and ends on or
    after Y-12-25, so a leading or trailing partial year is never scored.
    """
    years = sorted(set(int(y) for y in idx.year))
    return [
        y for y in years
        if idx[0] <= pd.Timestamp(y, 1, 7) and idx[-1] >= pd.Timestamp(y, 12, 25)
    ]


def yearly_calmars(returns: pd.Series) -> Dict[str, float]:
    """Per-scored-year Calmar, pre-tax (no trade ledger is available here).

    The gallery of r2 CSVs carries daily returns only -- no trade ledger -- so
    this is the pre-tax per-year Calmar, which is the same pre-tax convention the
    gate's ``beats_benchmark`` reads through ``window_calmars``. Years with an
    undefined Calmar (zero drawdown) are dropped, matching the scorecard.
    """
    eq = (1.0 + returns.astype(float)).cumprod()
    out: Dict[str, float] = {}
    for year in scored_years(eq.index):
        calmar = _curve_metrics(eq[eq.index.year == year])["calmar"]
        if calmar is not None:
            out[str(year)] = calmar
    return out


def series_metrics(returns: pd.Series) -> Dict[str, Optional[float]]:
    """The metric block published for one return stream.

    CAGR / max drawdown / Calmar on the full development span, the median of the
    per-scored-year Calmars (the ``beats_benchmark`` statistic), the annualised
    unrealised vol and Sharpe (mean/std(ddof=1), annualised at 252 days).
    """
    returns = returns.astype(float)
    metrics = dict(_curve_metrics((1.0 + returns).cumprod()))
    calmars = yearly_calmars(returns)
    metrics["median_year_calmar"] = float(np.median(list(calmars.values()))) if calmars else None
    metrics["n_scored_years"] = len(calmars)
    std = float(returns.std(ddof=1))
    metrics["mean_daily"] = float(returns.mean())
    metrics["realized_vol"] = float(std * np.sqrt(_TRADING_DAYS))
    metrics["sharpe_annual"] = float(returns.mean() / std * np.sqrt(_TRADING_DAYS)) if std > 0.0 else 0.0
    metrics["n_periods"] = int(len(returns))
    metrics["n_years"] = float(_years_between(returns.index))
    return metrics


# ---------------------------------------------------------------------------
# Blend
# ---------------------------------------------------------------------------

def validate_weight(weight: float) -> float:
    """A blend weight is the candidate's share of the one risk budget, in [0, 1]."""
    weight = float(weight)
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"weight must be in [0, 1], got {weight}")
    return weight


def blend_returns(candidate: pd.Series, benchmark: pd.Series, weight: float) -> pd.Series:
    """``weight * candidate + (1 - weight) * benchmark``, on the shared daily index.

    Both legs are already vol-targeted return streams under the same 10% target,
    so the blend is a capital split of one risk budget, not a re-leverage. The
    weighted mean is the mean of this blend exactly (Pitfall 1), which is why a
    positive stand-alone mean has to remain a hard precondition.
    """
    weight = validate_weight(weight)
    return weight * candidate.astype(float) + (1.0 - weight) * benchmark.astype(float)


def _correlation(a: pd.Series, b: pd.Series) -> float:
    """Pearson correlation of two daily-return streams, NaN on a flat leg.

    Computed explicitly rather than via ``Series.corr`` so a zero-variance leg
    returns NaN quietly instead of raising numpy's divide warning inside pandas.
    """
    a = a.astype(float).to_numpy()
    b = b.astype(float).to_numpy()
    a_dev, b_dev = a - a.mean(), b - b.mean()
    denom = float(np.sqrt((a_dev * a_dev).sum() * (b_dev * b_dev).sum()))
    if denom == 0.0:
        return float("nan")
    return float((a_dev * b_dev).sum() / denom)


def blend_metrics(candidate: pd.Series, benchmark: pd.Series, weight: float) -> Dict[str, Optional[float]]:
    """Every published metric for the blend, plus the legs' daily correlation."""
    blended = blend_returns(candidate, benchmark, weight)
    metrics = series_metrics(blended)
    metrics["weight"] = validate_weight(weight)
    metrics["correlation"] = _correlation(candidate, benchmark)
    return metrics


# ---------------------------------------------------------------------------
# I/O (read-only)
# ---------------------------------------------------------------------------

def load_returns_csv(path: Path) -> pd.DataFrame:
    """Read a frozen r2 development returns file, indexed by date.

    Read-only by contract: the study directory is a results artifact and is never
    written to.
    """
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index.name = "date"
    return frame


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{float(x):.6f}"


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{float(x) * 100.0:.2f}%"


def _metric_line(nm: str, m: Dict[str, Optional[float]]) -> str:
    return (
        f"{nm:<22s} mean {_fmt(m['mean_daily'])}  CAGR {_pct(m['cagr'])}  "
        f"maxDD {_pct(m['max_drawdown'])}  Calmar {_fmt(m['calmar'])}  "
        f"median-year Calmar {_fmt(m['median_year_calmar'])} (n_w={m['n_scored_years']})  "
        f"vol {_pct(m['realized_vol'])}  Sharpe {_fmt(m['sharpe_annual'])}"
    )


def report(frame: pd.DataFrame, trial: str, label: str, weights=WEIGHTS) -> str:
    """The published block for one candidate: both legs, then each blend weight."""
    leg, bench = frame[trial], frame["benchmark"]
    leg_metrics = series_metrics(leg)
    bench_metrics = series_metrics(bench)
    lines = [f"== {label}: trial {trial} (development, post-hoc / illustrative)"]
    lines.append(_metric_line("stand-alone candidate", leg_metrics))
    lines.append(_metric_line("benchmark (vol-tgt SPY)", bench_metrics))
    for w in weights:
        m = blend_metrics(leg, bench, w)
        lines.append(_metric_line(f"blend {w:.2f}/{1.0 - w:.2f}", m) + f"  corr {_fmt(m['correlation'])}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_blend_illustration", description=__doc__.splitlines()[0])
    parser.add_argument("--study-dir", type=Path, default=STUDY_DIR,
                        help="frozen r2 study directory (default: %(default)s)")
    parser.add_argument("--weights", type=float, nargs="+", default=list(WEIGHTS),
                        help="candidate share(s) of the one risk budget (default: %(default)s)")
    args = parser.parse_args(argv)

    print("Blend illustration -- POST-HOC / ILLUSTRATIVE, not a verdict, not a retest.")
    print("Reads only the committed r2 development returns files; no DSR, no PBO, no holdout.")
    print("")
    for candidate_id, filename, trial, label in CANDIDATES:
        path = args.study_dir / filename
        if not path.is_file():
            print(f"missing returns file for {candidate_id}: {path}")
            return 1
        frame = load_returns_csv(path)
        print(report(frame, trial, label, weights=args.weights))
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
