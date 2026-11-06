"""Candidate #763 ``etf-daily-r2-vol-regime-gating``: vol-regime-gated basket allocation.

Research-only: no broker, no Supabase, no LLM, no production code. The only
network contact is the market-data fetch inside ``backtest.etf_data.load_daily_bars``.
Never imported by ``supabase/functions/``. Every definition applied here is
frozen in ``docs/research/2026-11-06-etf-daily-r2-preregistration.md`` (section
numbers in comments refer to it); nothing outside its section 6 grid is
evaluated and nothing in it is tuned.

Rule (sections 3.1 and 3.1.1): the underlying allocation is passive (all 14
ETFs, all-ones signal frame); the only decision is the exposure fraction
``f(T)`` driven by SPY's realised volatility. ``realised_vol(T)`` = annualised
std (ddof=1, x sqrt(252)) of SPY's daily close-to-close returns over the prior
``L_vol`` master-index rows inclusive of T (forward-filled signal closes); the
gate is on when ``realised_vol(T) < V``, off otherwise (warm-up off). The
all-ones frame goes through ``inverse_vol_weights`` then ``vol_target_weights``
exactly as r1, and the resulting target weights are multiplied row-wise by
``f(T)`` (1.0 on, ``f_off`` off) BEFORE the simulator (section 3.1.1 step 2).

Usage (always from the worktree root)::

    export CLAUDE_AGENT_NO_BROKER=1
    venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/run_vol_regime_gating.py \
        --phase development

The holdout path (``--phase holdout``) is implemented but run ONLY by the
orchestrating session, once, after the development result is recorded; the
analyst never executes it.

The development path appends the 12 trials to the programme ledger in one
``append_trials`` call (no ``round_budget=``; the round's 18 of 50 is inside
the budget), writes ``<candidate_id>-development-returns.csv`` and
``<candidate_id>-development-payload.json`` into this directory and never
calls ``record_result``.

Usage (holdout; orchestrating session only, once, after the development
result is recorded)::

    venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/run_vol_regime_gating.py \
        --phase holdout --i-am-the-orchestrator

The holdout path reads ``selected_trial_id`` and ``config`` from the committed
``docs/research/pipeline/etf-daily-r2-vol-regime-gating/development_result.json``,
loads the full series from the data start with ``phase="holdout"`` (so gate
state, positions and volatility estimates carry in naturally through
2021-12-31), runs only the selected configuration plus the benchmark and the
double-cost and 1.5x re-runs, cuts everything to rows on or after
2022-01-01 (section 8 holdout method), builds the holdout scorecard and calls
``record_result`` in the same process. It appends no trial. The analyst
implements it but never runs it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import etf_daily_r2_common as common  # noqa: E402
from backtest.etf_data import HOLDOUT_START  # noqa: E402
from backtest.portfolio import PortfolioResult, round_trips_per_year  # noqa: E402
from backtest.trial_store import DAILY_ALLOCATION, TrialRecord, append_trials  # noqa: E402

CANDIDATE_ID = "etf-daily-r2-vol-regime-gating"
RUN_DATE = "2026-11-06"

_TRADING_DAYS = 252

# Section 6 grid, N = 12, in trial-id order: (L_vol, V, f_off).
GRID: List[Tuple[int, float, float]] = [
    (21, 0.15, 0.25),
    (21, 0.15, 0.0),
    (21, 0.20, 0.25),
    (21, 0.20, 0.0),
    (21, 0.25, 0.25),
    (21, 0.25, 0.0),
    (63, 0.15, 0.25),
    (63, 0.15, 0.0),
    (63, 0.20, 0.25),
    (63, 0.20, 0.0),
    (63, 0.25, 0.25),
    (63, 0.25, 0.0),
]


def trial_id(n: int) -> str:
    return f"{CANDIDATE_ID}-{n:02d}"


def trial_config(L_vol: int, V: float, f_off: float) -> dict:
    cfg = {"L_vol": int(L_vol), "V": float(V), "f_off": float(f_off)}
    cfg.update(common.SIZING_CONFIG)
    return cfg


# ---------------------------------------------------------------------------
# Section 3.1: the gate, and section 3.1.1: the two-step mechanism
# ---------------------------------------------------------------------------

def exposure_fraction(data: common.BasketData, L_vol: int, V: float, f_off: float) -> pd.Series:
    """``f(T)`` on the master index: 1.0 when the gate is on, ``f_off`` otherwise.

    ``realised_vol(T)`` = annualised std (ddof=1, x sqrt(252)) of SPY's daily
    close-to-close returns over the prior ``L_vol`` rows inclusive of T, from
    the forward-filled SPY signal closes. A not-computable vol (warm-up: the
    window must hold ``L_vol`` finite returns) leaves the gate off. The gate is
    on when ``realised_vol(T) < V`` (strictly), off otherwise.
    """
    if L_vol < 1:
        raise ValueError(f"L_vol must be >= 1, got {L_vol}")
    spy = data.signal_closes[common.BENCHMARK_SYMBOL]
    rets = spy.pct_change()                      # close-to-close, row 0 NaN
    vol = rets.rolling(window=L_vol, min_periods=L_vol).std(ddof=1) * np.sqrt(_TRADING_DAYS)
    gate_on = vol < V                            # NaN compares False -> off
    return pd.Series(
        np.where(gate_on.to_numpy(dtype=bool), 1.0, float(f_off)),
        index=data.index,
    )


def run_config(
    data: common.BasketData,
    L_vol: int,
    V: float,
    f_off: float,
    *,
    costs,
    gross_cap: float,
) -> PortfolioResult:
    """Section 3.1.1: all-ones signals -> sizing chain -> row-wise f(T) -> simulator."""
    signals = pd.DataFrame(
        1.0, index=data.index, columns=common.ETF_BASKET_XA14
    )
    target = common.size_signals(signals, data, gross_cap=gross_cap)
    f = exposure_fraction(data, L_vol, V, f_off)
    gated = target.mul(f, axis=0)                # after vol targeting, before simulator
    return common.simulate_from_target(gated, data, costs=costs, gross_cap=gross_cap)


# ---------------------------------------------------------------------------
# Development path
# ---------------------------------------------------------------------------

def run_development() -> None:
    bars = common.load_basket("development")
    data = common.build_basket(bars)
    n_rows = len(data.index)
    print(f"data start (first date all 15 tickers have a bar): {data.data_start.date()}")
    print(f"development rows on the master index: {n_rows} "
          f"({data.index[0].date()} to {data.index[-1].date()})")
    print(f"missing close rows per ticker on the master index: {data.missing_rows}")

    benchmark = common.simulate_benchmark(data)

    trial_ids = [trial_id(n) for n in range(1, len(GRID) + 1)]
    results: Dict[str, PortfolioResult] = {}
    cards: Dict[str, dict] = {}
    for tid, (L_vol, V, f_off) in zip(trial_ids, GRID):
        res = run_config(data, L_vol, V, f_off,
                         costs=common.VERDICT_COSTS, gross_cap=common.GROSS_CAP)
        results[tid] = res
        cards[tid] = common.scorecard_for(res, benchmark)
        # The ledger value is the scorecard's sharpe_daily; cross-check the definition.
        own = common.sharpe_daily(res.daily_returns)
        if abs(own - cards[tid]["sharpe_daily"]) > 1e-12:
            raise RuntimeError(f"{tid}: sharpe_daily mismatch {own} vs {cards[tid]['sharpe_daily']}")
        if common.n_finite(res.daily_returns) != cards[tid]["n_periods"]:
            raise RuntimeError(f"{tid}: n_periods mismatch")
        f = exposure_fraction(data, L_vol, V, f_off)
        print(f"{tid}: gate on {float((f == 1.0).mean()):.4f} of development rows "
              f"(L_vol={L_vol}, V={V}, f_off={f_off})")

    # Section 6: every trial (losers included) in one append_trials call.
    records = [
        TrialRecord(
            trial_id=tid,
            round_id=common.ROUND_ID,
            candidate_id=CANDIDATE_ID,
            space=DAILY_ALLOCATION,
            config=trial_config(L_vol, V, f_off),
            sharpe_daily=float(cards[tid]["sharpe_daily"]),
            n_periods=int(cards[tid]["n_periods"]),
            source=common.PREREG_SOURCE,
            date=RUN_DATE,
        )
        for tid, (L_vol, V, f_off) in zip(trial_ids, GRID)
    ]
    append_trials(records)  # default store path; always run from the worktree root
    print(f"appended {len(records)} trials to {common.TRIALS_PATH}")

    # Section 7 returns file.
    returns_path = common.STUDY_DIR / f"{CANDIDATE_ID}-development-returns.csv"
    columns = {tid: results[tid].daily_returns for tid in trial_ids}
    columns["benchmark"] = benchmark.daily_returns
    common.write_returns_csv(returns_path, columns, data.index)
    print(f"wrote {returns_path}")

    # Section 6 selection: highest sharpe_daily, tie to the lowest trial_id.
    selected = trial_ids[0]
    for tid in trial_ids[1:]:
        if cards[tid]["sharpe_daily"] > cards[selected]["sharpe_daily"]:
            selected = tid
    L_sel, V_sel, f_sel = GRID[trial_ids.index(selected)]
    config = trial_config(L_sel, V_sel, f_sel)

    double = run_config(data, L_sel, V_sel, f_sel,
                        costs=common.DOUBLE_COSTS, gross_cap=common.GROSS_CAP)
    leverage = run_config(data, L_sel, V_sel, f_sel,
                         costs=common.VERDICT_COSTS, gross_cap=common.LEVERAGE_GROSS_CAP)
    scorecard = common.scorecard_for(
        results[selected], benchmark, double_cost=double, leverage_info=leverage
    )

    payload = {
        "round_id": common.ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "trial_ids": trial_ids,
        "selected_trial_id": selected,
        "config": config,
        "scorecard": scorecard,
        "commit": common.git_commit(),
    }
    payload_path = common.STUDY_DIR / f"{CANDIDATE_ID}-development-payload.json"
    payload_path.write_text(common.strict_json(payload))
    print(f"wrote {payload_path}")

    # Compact table.
    print()
    print(common.summary_header())
    for tid, (L_vol, V, f_off) in zip(trial_ids, GRID):
        print(common.summary_row(f"{tid} (L={L_vol},V={V},f_off={f_off})", cards[tid]))
    bench_block = dict(scorecard["benchmark"])
    bench_block["round_trips_per_year"] = round_trips_per_year(benchmark)
    bench_block["max_time_share_one_etf"] = float(
        (benchmark.held_weights != 0.0).mean().max()
    )
    print(common.summary_row("benchmark (vol-targeted SPY)", bench_block))
    print()
    print(f"selected: {selected} config={config}")
    print(f"scored years (len(window_calmars)): {len(scorecard['window_calmars'])} "
          f"-> {list(scorecard['window_calmars'].keys())}")
    print(f"benchmark scored years: {len(scorecard['benchmark']['window_calmars'])}")
    dc = scorecard["double_cost"]
    li = scorecard["leverage_info"]
    print(f"double_cost: {dc}")
    print(f"leverage_info (1.5x): {li}")
    print(f"costs (selected, currency): {results[selected].costs}")
    print(f"commit: {payload['commit']}")


# ---------------------------------------------------------------------------
# Holdout path (orchestrating session only; written by the analyst, never run here)
# ---------------------------------------------------------------------------

def run_holdout(i_am_the_orchestrator: bool) -> None:
    if not i_am_the_orchestrator:
        raise SystemExit(
            "the holdout path is run once by the orchestrating session; "
            "pass --i-am-the-orchestrator to confirm"
        )
    import json

    from backtest.etf_data import record_result

    dev_path = common.PIPELINE_DIR / CANDIDATE_ID / "development_result.json"
    dev = json.loads(dev_path.read_text())
    selected = dev["selected_trial_id"]
    config = dev["config"]
    n = int(selected.rsplit("-", 1)[1])
    if trial_id(n) != selected or not (1 <= n <= len(GRID)):
        raise ValueError(f"selected_trial_id {selected!r} is not in the section 6 grid")
    L_vol, V, f_off = GRID[n - 1]
    if trial_config(L_vol, V, f_off) != config:
        raise ValueError(
            f"development_result config {config} does not match grid entry {n} "
            f"{trial_config(L_vol, V, f_off)}"
        )

    # Lock-checked load; the loader raises HoldoutLockedError if not released.
    bars = common.load_basket("holdout", candidate_id=CANDIDATE_ID)
    full = common.build_basket(bars)
    dev_only = common.build_basket(common.cut_bars_before(bars, HOLDOUT_START))
    print(f"data start: {full.data_start.date()}; full rows {len(full.index)} "
          f"({full.index[0].date()} to {full.index[-1].date()}); "
          f"development rows {len(dev_only.index)}")

    def both(costs, gross_cap: float) -> PortfolioResult:
        return common.slice_to_holdout(
            run_config(full, L_vol, V, f_off, costs=costs, gross_cap=gross_cap),
            run_config(dev_only, L_vol, V, f_off, costs=costs, gross_cap=gross_cap),
        )

    result = both(common.VERDICT_COSTS, common.GROSS_CAP)
    benchmark = common.slice_to_holdout(
        common.simulate_benchmark(full), common.simulate_benchmark(dev_only)
    )
    double = both(common.DOUBLE_COSTS, common.GROSS_CAP)
    leverage = both(common.VERDICT_COSTS, common.LEVERAGE_GROSS_CAP)
    scorecard = common.scorecard_for(
        result, benchmark, double_cost=double, leverage_info=leverage
    )

    payload = {
        "round_id": common.ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "selected_trial_id": selected,
        "config": config,
        "scorecard": scorecard,
        "commit": common.git_commit(),
    }
    common.strict_json(payload)  # raises on NaN/inf before anything is recorded
    path = record_result(CANDIDATE_ID, "holdout", payload)  # default pipeline_dir (skill Phase 4 e)
    print(f"recorded holdout result at {path}")
    print(common.summary_header())
    print(common.summary_row(f"{selected} holdout", scorecard))
    print(f"holdout rows: {len(result.equity)} ({result.equity.index[0].date()} to "
          f"{result.equity.index[-1].date()}); scored years "
          f"{list(scorecard['window_calmars'].keys())}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", choices=("development", "holdout"), required=True)
    parser.add_argument(
        "--i-am-the-orchestrator", action="store_true",
        help="required with --phase holdout; the analyst never passes it",
    )
    args = parser.parse_args(argv)
    if args.phase == "development":
        if args.i_am_the_orchestrator:
            raise SystemExit("--i-am-the-orchestrator applies to --phase holdout only")
        run_development()
    else:
        run_holdout(args.i_am_the_orchestrator)


if __name__ == "__main__":
    main()
