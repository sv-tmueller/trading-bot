"""Backfill the programme trial store with the prior daily-allocation trials.

Research only. Lives in ``backtest/``; never imported by ``supabase/functions/``. No LLM, no
broker calls. The only network use is the read-only yfinance daily-bar fetch inside
``etf_data.load_daily_bars``, and it is skipped when nothing is missing.

Why this exists
---------------
``overfitting_gate.deflated_sharpe_ratio`` needs the Sharpe ratio of every configuration the
programme has tried (design spec section 5.4), so each prior trial must be in
``docs/research/pipeline/trials.json`` before round 1 scores a candidate. This script re-runs
five prior daily-allocation trials over the development window (bars before 2022-01-01) and
appends one record per trial under ``round_id == "backfill"``.

The five trials each match one record in ``backtest/tested_cells.py`` (the #681 block) and cite
that record's ``source`` and study date. Excluded on purpose (batch decision on #715): the four
leveraged UPRO cells of #694 (the pipeline hypothesis space is 1x gross) and the incumbent
200-DMA, persistence and buy-and-hold rules (live rule and null baselines, not trials).

Method
------
Bars come from ``load_daily_bars(..., phase="development")`` (the holdout cannot be read). Each
trial runs through ``run_candidate_survey._simulate_strategy_on_index`` (the survey's own
``simulate_from_signal`` path: published default signal, next-day-open execution, costs), on the
common index of the trial's window tickers. The Sharpe is ``mean / std(ddof=1)`` of the finite
daily equity-curve returns, 0.0 when ``std <= 1e-12``: not annualised, not excess, the same as
the scorecard's ``_performance_block`` and the gate's ``sr_hat``. Warm-up days stay in.

Caveats
-------
1. The original runs went to 2026-06-23. This re-run stops at 2021-12-31, so no verdict doc
   prints the stored Sharpe and there is no published number to check it against.
2. It keeps the original survey's cost and cash settings (5 + 5 bps per side, 0% on idle
   cash). The pipeline uses 5 + 0 bps and a T-bill rate on cash. The DSR threshold (``sr_star``)
   depends only on the spread of the trial Sharpes and on N, not on their level, so the
   difference is minor.
3. GTAA weights drift between signal flips (first-cut caveat); the re-run inherits this.
4. The binary simulator force-closes the position on the last day (about 0.1% on that day);
   the original curves carry the same cost.

Rerun safety
------------
A missing store is a hard error (the file is never created). Trial ids already in the store are
skipped, never recomputed: yfinance back-adjusts history when dividends post, so the first
committed values stay frozen. All missing records are computed first, then appended with one
``append_trials`` call; any error prints to stderr, returns 1, and writes nothing.

Usage (from the repo root, because ``DEFAULT_PATH`` is relative)::

    python -m backtest.run_trial_backfill --dry-run
    python -m backtest.run_trial_backfill
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

import backtest.run_candidate_survey as rcs
from backtest.etf_data import load_daily_bars
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS
from backtest.trial_store import (
    BACKFILL_ROUND,
    DAILY_ALLOCATION,
    DEFAULT_PATH,
    TrialRecord,
    append_trials,
    load_trials,
)

TRIAL_DATE = "2026-06-24"
_ZERO_VARIANCE_ATOL = 1e-12
_FIRST_CUT = "docs/research/2026-06-24-candidate-strategy-survey-first-cut.md"
_SECOND_CUT = "docs/research/2026-06-24-candidate-strategy-survey-second-cut.md"
_SIMULATOR = "backtest.regime.simulate_from_signal"


@dataclass(frozen=True)
class TrialSpec:
    trial_id: str
    ledger_family: str
    ledger_vehicle: str
    survey_strategy: str
    held: List[str]
    window_tickers: List[str]
    source: str


def _family(key: str) -> dict:
    return next(f for f in rcs.FAMILIES if f["key"] == key)


def _family_spec(trial_id: str, ledger_family: str, ledger_vehicle: str, key: str,
                 source: str) -> TrialSpec:
    fam = _family(key)
    return TrialSpec(
        trial_id=trial_id,
        ledger_family=ledger_family,
        ledger_vehicle=ledger_vehicle,
        survey_strategy=key,
        held=list(fam["held"]),
        window_tickers=list(fam["binding"]),
        source=source,
    )


TRIALS: List[TrialSpec] = [
    # TSMOM is a survey baseline, not a FAMILIES entry.
    TrialSpec("backfill-tsmom-12m-spy", "tsmom_timeseries", "SPY", "tsmom",
              ["SPY"], ["SPY"], _FIRST_CUT),
    _family_spec("backfill-faber-10m-spy", "faber_ma_timing", "SPY", "faber_single", _FIRST_CUT),
    _family_spec("backfill-faber-gtaa5", "faber_ma_timing", "ETF_BASKET_GTAA5", "gtaa",
                 _FIRST_CUT),
    _family_spec("backfill-gem-dual-momentum", "dual_momentum_gem", "ETF_BASKET_GEM", "gem",
                 _FIRST_CUT),
    _family_spec("backfill-vol-target-10-spy", "vol_target", "SPY", "vol_target", _SECOND_CUT),
]


def _sharpe_daily(returns: np.ndarray) -> float:
    """Non-annualised, non-excess Sharpe: mean / std(ddof=1); 0.0 if std <= 1e-12."""
    r = np.asarray(returns, dtype=float)
    std = float(r.std(ddof=1)) if len(r) >= 2 else 0.0
    return 0.0 if std <= _ZERO_VARIANCE_ATOL else float(r.mean() / std)


def _compute_record(spec: TrialSpec, bars: dict) -> TrialRecord:
    window = rcs._common_index([bars[t] for t in spec.window_tickers])
    sim = rcs._simulate_strategy_on_index(spec.survey_strategy, bars, spec.held, window)
    rets = sim["equity_curve"].pct_change().iloc[1:].to_numpy(dtype=float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        raise ValueError(f"{spec.trial_id}: fewer than 2 finite returns")
    config = {
        "ledger_family": spec.ledger_family,
        "ledger_vehicle": spec.ledger_vehicle,
        "survey_strategy": spec.survey_strategy,
        "held": list(spec.held),
        "window_tickers": list(spec.window_tickers),
        "dev_window": [window[0].date().isoformat(), window[-1].date().isoformat()],
        "simulator": _SIMULATOR,
        "slippage_bps": SLIPPAGE_BPS,
        "commission_bps": COMMISSION_BPS,
        "cash_yield": 0.0,
    }
    return TrialRecord(
        trial_id=spec.trial_id,
        round_id=BACKFILL_ROUND,
        candidate_id=spec.ledger_family,
        space=DAILY_ALLOCATION,
        config=config,
        sharpe_daily=_sharpe_daily(rets),
        n_periods=int(len(rets)),
        source=spec.source,
        date=TRIAL_DATE,
    )


def main(
    argv: Optional[List[str]] = None,
    *,
    fetch: Optional[Callable[[str], pd.DataFrame]] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="list which trials are present or missing; no fetch, no write")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH,
                        help="trial store (default: %(default)s)")
    args = parser.parse_args(argv)

    try:
        stored = {r.trial_id for r in load_trials(args.path)}
    except (OSError, ValueError) as exc:
        print(f"error: cannot read trial store {args.path}: {exc}", file=sys.stderr)
        return 1

    missing = [t for t in TRIALS if t.trial_id not in stored]

    if args.dry_run:
        for spec in TRIALS:
            state = "missing" if spec in missing else "present"
            print(f"{spec.trial_id}\t{state}\t{spec.source}")
        return 0

    if not missing:
        print("nothing to append")
        return 0

    try:
        tickers: List[str] = []
        for spec in missing:
            tickers += [t for t in spec.window_tickers if t not in tickers]
        bars = load_daily_bars(tickers, phase="development", fetch=fetch)
        records = [_compute_record(spec, bars) for spec in missing]
        append_trials(records, path=args.path)
    except Exception as exc:  # noqa: BLE001 -- any failure must leave the store untouched
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for rec in records:
        print(
            f"{rec.trial_id}\tdev_window={rec.config['dev_window']}\tn_periods={rec.n_periods}"
            f"\tsharpe_daily={rec.sharpe_daily:.6f}"
            f"\tsharpe_annualised={rec.sharpe_daily * math.sqrt(252):.3f}\tappended"
        )
    for spec in TRIALS:
        if spec not in missing:
            print(f"{spec.trial_id}\tskipped (already stored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
