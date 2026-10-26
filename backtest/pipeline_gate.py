"""Five-criterion candidate gate for the research pipeline (plan Task 8, #696).

Pure function over plain scorecard dicts (the shape pinned by #695) plus the
luck-gate inputs. No I/O, no trial-store access, no scorecard import: the
caller supplies everything. Research only; never touches the trading path.

Criteria, in fixed order (the scorecard renderer iterates in this order):

1. ``drawdown``        max drawdown, a non-negative magnitude (the #695
                       convention) of at most MAX_DRAWDOWN, on the development
                       card and, when the holdout has been run, on the holdout
                       card. A signed negative value fails.
2. ``beats_benchmark`` median development window Calmar strictly above the
                       benchmark's median window Calmar.
3. ``luck``            ``evaluate_gate`` (DSR / PBO / bootstrap) passes on
                       development data; this module re-implements no threshold.
4. ``holdout``         holdout CAGR (pre-tax, after costs) > 0 and holdout max
                       drawdown a non-negative magnitude of at most
                       MAX_DRAWDOWN. ``holdout=None`` fails with the detail
                       ``holdout not yet run``.
5. ``activity``        development round trips per year >=
                       MIN_ROUND_TRIPS_PER_YEAR and development max time share
                       in one ETF <= MAX_TIME_SHARE_ONE_ETF.

All five are always evaluated (no short-circuit) so every criterion reports.
A present value that is None or non-finite fails the criterion that reads it.

Pinned readings: a holdout drawdown above the cap fails both ``drawdown`` and
``holdout``; ``activity`` reads the development card only.

Call-site note (Task 11): append this round's trials to the trial store before
calling ``programme_sharpes()``, so the best trial is in ``all_trial_sharpes``.
``ValueError`` from ``evaluate_gate`` (too few trials, T < n_splits) and
``KeyError`` for a missing scorecard key propagate: they are operator input
errors, not failed verdicts.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from backtest.overfitting_gate import evaluate_gate

MAX_DRAWDOWN = 0.20
MIN_ROUND_TRIPS_PER_YEAR = 20
MAX_TIME_SHARE_ONE_ETF = 0.90


def _finite(x) -> bool:
    return x is not None and math.isfinite(float(x))


def _fmt(x) -> str:
    return f"{float(x):.4f}" if _finite(x) else "n/a"


def _entry(passed: bool, detail: str) -> dict:
    return {"passed": bool(passed), "detail": detail}


def _median(windows: dict) -> float:
    # Callers guarantee a non-empty dict. A None or non-finite entry becomes NaN,
    # which propagates to a NaN median (and so fails the criterion).
    return float(np.median([float(v) if _finite(v) else math.nan for v in windows.values()]))


def _drawdown(development: dict, holdout: Optional[dict]) -> dict:
    dev = development["max_drawdown"]
    ok = _finite(dev) and 0.0 <= float(dev) <= MAX_DRAWDOWN
    detail = f"development {_fmt(dev)}"
    if holdout is None:
        detail += "; holdout not yet run"
    else:
        hold = holdout["max_drawdown"]
        ok = ok and _finite(hold) and 0.0 <= float(hold) <= MAX_DRAWDOWN
        detail += f"; holdout {_fmt(hold)}"
    return _entry(ok, f"{detail}; cap {MAX_DRAWDOWN:.4f}")


def _beats_benchmark(development: dict) -> dict:
    cand = development["window_calmars"]
    bench = development["benchmark"]["window_calmars"]
    n_c, n_b = len(cand), len(bench)
    if n_c == 0 or n_b == 0:
        return _entry(False, f"no scored windows (candidate n_w={n_c}, benchmark n_w={n_b})")
    med_c, med_b = _median(cand), _median(bench)
    ok = _finite(med_c) and _finite(med_b) and med_c > med_b
    return _entry(
        ok,
        f"median window Calmar candidate {_fmt(med_c)} (n_w={n_c}) "
        f"vs benchmark {_fmt(med_b)} (n_w={n_b})",
    )


def _luck(res: dict) -> dict:
    boot = res["bootstrap_result"]
    detail = (
        f"DSR {_fmt(res['dsr'])} over N={res['dsr_result']['n_trials']} trials; "
        f"PBO {_fmt(res['pbo'])}; "
        f"uplift CI [{_fmt(boot['ci_low'])}, {_fmt(boot['ci_high'])}]"
    )
    if res["reasons"]:
        detail += "; " + "; ".join(res["reasons"])
    return _entry(bool(res["passed"]), detail)


def _holdout(holdout: Optional[dict]) -> dict:
    if holdout is None:
        return _entry(False, "holdout not yet run")
    cagr, dd = holdout["cagr"], holdout["max_drawdown"]
    ok = _finite(cagr) and float(cagr) > 0.0 and _finite(dd) and 0.0 <= float(dd) <= MAX_DRAWDOWN
    return _entry(ok, f"holdout CAGR {_fmt(cagr)} (need > 0); max drawdown {_fmt(dd)}")


def _activity(development: dict) -> dict:
    trips = development["round_trips_per_year"]
    share = development["max_time_share_one_etf"]
    ok = (
        _finite(trips)
        and float(trips) >= MIN_ROUND_TRIPS_PER_YEAR
        and _finite(share)
        and float(share) <= MAX_TIME_SHARE_ONE_ETF
    )
    return _entry(
        ok,
        f"round trips per year {_fmt(trips)} (min {MIN_ROUND_TRIPS_PER_YEAR}); "
        f"max time share in one ETF {_fmt(share)} (max {MAX_TIME_SHARE_ONE_ETF:.4f})",
    )


def evaluate_candidate(
    development: dict,
    holdout: Optional[dict],
    *,
    returns_best: np.ndarray,
    all_trial_sharpes: np.ndarray,
    perf_matrix: np.ndarray,
    uplifts: np.ndarray,
    gate_kwargs: Optional[dict] = None,
) -> dict:
    """Return ``{"passed": bool, "criteria": {name: {"passed", "detail"}}}``.

    ``development`` and ``holdout`` are #695 scorecard dicts; ``all_trial_sharpes``
    is ``programme_sharpes()``; ``gate_kwargs`` is forwarded to ``evaluate_gate``
    unchanged.
    """
    res = evaluate_gate(
        returns_best=returns_best,
        all_trial_sharpes=all_trial_sharpes,
        perf_matrix=perf_matrix,
        uplifts=uplifts,
        **(gate_kwargs or {}),
    )
    criteria = {
        "drawdown": _drawdown(development, holdout),
        "beats_benchmark": _beats_benchmark(development),
        "luck": _luck(res),
        "holdout": _holdout(holdout),
        "activity": _activity(development),
    }
    return {
        "passed": all(c["passed"] for c in criteria.values()),
        "criteria": criteria,
    }
