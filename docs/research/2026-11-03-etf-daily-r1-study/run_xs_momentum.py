"""Candidate #751 ``etf-daily-r1-xs-momentum``: cross-sectional momentum on ETF_BASKET_XA14.

Research-only: no broker, no Supabase, no LLM, no production code. The only
network contact is the market-data fetch inside ``backtest.etf_data.load_daily_bars``.
Never imported by ``supabase/functions/``. Every definition applied here is
frozen in ``docs/research/2026-11-03-etf-daily-r1-preregistration.md`` (section
numbers in comments refer to it); nothing outside its section 6 grid is
evaluated and nothing in it is tuned. Loading, sizing, simulation, costs,
benchmark, holdout slicing and the output helpers are reused unchanged from
``etf_daily_r1_common.py``; this script adds only the section 3.2 rule and the
section 6 grid of this candidate.

Usage (always from the worktree root)::

    export CLAUDE_AGENT_NO_BROKER=1
    venv/bin/python3 docs/research/2026-11-03-etf-daily-r1-study/run_xs_momentum.py \
        --phase development

    # Orchestrating session only, once, after development_result.json is recorded:
    venv/bin/python3 docs/research/2026-11-03-etf-daily-r1-study/run_xs_momentum.py \
        --phase holdout --i-am-the-orchestrator

The development path appends the 6 trials to the programme ledger in one call,
writes ``<candidate_id>-development-returns.csv`` and
``<candidate_id>-development-payload.json`` into this directory and never calls
``record_result``. The holdout path appends no trial, loads holdout bars (the
loader's lock releases them once per candidate) and calls ``record_result`` in
the same process.
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

import etf_daily_r1_common as common  # noqa: E402
from backtest.etf_data import HOLDOUT_START  # noqa: E402
from backtest.portfolio import PortfolioResult, round_trips_per_year  # noqa: E402
from backtest.trial_store import DAILY_ALLOCATION, TrialRecord, append_trials  # noqa: E402

CANDIDATE_ID = "etf-daily-r1-xs-momentum"
RUN_DATE = "2026-11-03"

# Section 3.2 fixed parameters (not gridded).
SKIP = 21     # S: rows skipped between the score window and the ranking day
TOP_K = 4     # size of the top (long) and bottom (short) groups

# Section 6 grid, N = 6, in trial-id order.
GRID: List[Tuple[int, str]] = [
    (63, "long_only"),
    (63, "long_short"),
    (126, "long_only"),
    (126, "long_short"),
    (252, "long_only"),
    (252, "long_short"),
]
VARIANTS = ("long_only", "long_short")


def trial_id(n: int) -> str:
    return f"{CANDIDATE_ID}-{n:02d}"


def trial_config(L: int, variant: str) -> dict:
    cfg = {"L": int(L), "variant": str(variant), "skip": SKIP, "k": TOP_K}
    cfg.update(common.SIZING_CONFIG)
    return cfg


# ---------------------------------------------------------------------------
# Section 3.2: the rule
# ---------------------------------------------------------------------------

def ranking_day_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """True on the last trading day of each calendar week (Monday to Sunday).

    A row is a ranking day when the next row on the master index falls in a
    different Monday-to-Sunday week, or when it is the last row. A holiday at
    the end of a week (a Friday off) therefore makes the preceding trading day
    (usually the Thursday) that week's ranking day; a week with no trading day
    has no ranking day and the previous ranking's signals carry on.
    """
    weeks = index.to_period("W-SUN")  # weekly periods ending Sunday
    if len(weeks) == 0:
        return np.zeros(0, dtype=bool)
    mask = np.empty(len(weeks), dtype=bool)
    mask[:-1] = np.asarray(weeks[1:] != weeks[:-1])
    mask[-1] = True
    return mask


def xs_scores(data: common.BasketData, L: int) -> pd.DataFrame:
    """score_i(T) = Close_i(T-S) / Close_i(T-S-L) - 1, row offsets on the master
    index, forward-filled closes (signal use only). NaN where not computable."""
    if L < 1:
        raise ValueError(f"L must be >= 1, got {L}")
    etf = data.signal_closes[common.ETF_BASKET_XA14]
    return etf.shift(SKIP) / etf.shift(SKIP + L) - 1.0


def xs_signals(data: common.BasketData, L: int, variant: str) -> pd.DataFrame:
    """The section 3.2 signal frame in {-1, 0, +1} on the master index.

    On each ranking day the 14 scores are ranked descending, ties broken by
    ticker in alphabetical order (the alphabetically earlier ticker takes the
    better rank). ``long_only``: top 4 get +1, the rest 0. ``long_short``: top 4
    get +1, bottom 4 get -1, the middle 6 get 0. If any score is not computable
    on a ranking day every signal is 0 for that week. Signals set on a ranking
    day are held unchanged (including on the ranking day itself) until the next
    ranking day; rows before the first ranking day are 0.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    tickers = list(common.ETF_BASKET_XA14)
    n_assets = len(tickers)
    if n_assets < 2 * TOP_K:
        raise ValueError("basket too small for top/bottom groups")
    # Alphabetical rank of each basket column (0 = alphabetically first).
    alpha_rank = np.argsort(np.argsort(np.array(tickers)))

    scores = xs_scores(data, L).to_numpy(dtype=float)
    mask = ranking_day_mask(data.index)
    sig = np.zeros_like(scores)
    current = np.zeros(n_assets)
    for row in range(len(data.index)):
        if mask[row]:
            s = scores[row]
            if np.isfinite(s).all():
                # Primary key: score descending; secondary: ticker alphabetical.
                order = np.lexsort((alpha_rank, -s))
                current = np.zeros(n_assets)
                current[order[:TOP_K]] = 1.0
                if variant == "long_short":
                    current[order[-TOP_K:]] = -1.0
            else:
                current = np.zeros(n_assets)
        sig[row] = current
    return pd.DataFrame(sig, index=data.index, columns=tickers)


def run_config(
    data: common.BasketData, L: int, variant: str, *, costs, gross_cap: float
) -> PortfolioResult:
    return common.size_and_simulate(
        xs_signals(data, L, variant), data, costs=costs, gross_cap=gross_cap
    )


def signal_plausibility(data: common.BasketData, signals: pd.DataFrame, L: int) -> dict:
    """Facts about the signal frame for the report (no decision depends on them)."""
    mask = ranking_day_mask(data.index)
    rank_days = data.index[mask]
    n_long = (signals == 1.0).sum(axis=1)
    n_short = (signals == -1.0).sum(axis=1)
    scores = xs_scores(data, L)
    computable = scores.notna().all(axis=1).to_numpy() & mask
    first_rank = data.index[computable][0].date() if computable.any() else None
    per_year = pd.Series(1, index=rank_days).groupby(rank_days.year).sum()
    return {
        "ranking_days": int(mask.sum()),
        "ranking_days_per_year": {int(y): int(c) for y, c in per_year.items()},
        "non_friday_ranking_days": int((rank_days.dayofweek != 4).sum()),
        "first_computable_ranking_day": str(first_rank),
        "rows_exactly_4_long": int((n_long == 4).sum()),
        "rows_zero_long": int((n_long == 0).sum()),
        "rows_exactly_4_short": int((n_short == 4).sum()),
        "share_rows_exactly_4_long": float((n_long == 4).mean()),
        "signal_changes_on_non_ranking_rows": int(
            (signals.diff().abs().sum(axis=1).to_numpy()[1:] > 0)[~mask[1:]].sum()
        ),
    }


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
    plaus: Dict[str, dict] = {}
    for tid, (L, variant) in zip(trial_ids, GRID):
        signals = xs_signals(data, L, variant)
        plaus[tid] = signal_plausibility(data, signals, L)
        res = common.size_and_simulate(
            signals, data, costs=common.VERDICT_COSTS, gross_cap=common.GROSS_CAP
        )
        results[tid] = res
        cards[tid] = common.scorecard_for(res, benchmark)
        # The ledger value is the scorecard's sharpe_daily; cross-check the definition.
        own = common.sharpe_daily(res.daily_returns)
        if abs(own - cards[tid]["sharpe_daily"]) > 1e-12:
            raise RuntimeError(f"{tid}: sharpe_daily mismatch {own} vs {cards[tid]['sharpe_daily']}")
        if common.n_finite(res.daily_returns) != cards[tid]["n_periods"]:
            raise RuntimeError(f"{tid}: n_periods mismatch")

    # Section 6: every trial (losers included) in one append_trials call.
    records = [
        TrialRecord(
            trial_id=tid,
            round_id=common.ROUND_ID,
            candidate_id=CANDIDATE_ID,
            space=DAILY_ALLOCATION,
            config=trial_config(L, variant),
            sharpe_daily=float(cards[tid]["sharpe_daily"]),
            n_periods=int(cards[tid]["n_periods"]),
            source=common.PREREG_SOURCE,
            date=RUN_DATE,
        )
        for tid, (L, variant) in zip(trial_ids, GRID)
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
    L_sel, v_sel = GRID[trial_ids.index(selected)]
    config = trial_config(L_sel, v_sel)

    double = run_config(data, L_sel, v_sel, costs=common.DOUBLE_COSTS,
                        gross_cap=common.GROSS_CAP)
    leverage = run_config(data, L_sel, v_sel, costs=common.VERDICT_COSTS,
                          gross_cap=common.LEVERAGE_GROSS_CAP)
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
    for tid, (L, variant) in zip(trial_ids, GRID):
        print(common.summary_row(f"{tid} (L={L},{variant})", cards[tid]))
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
    print()
    print("signal plausibility (section 3.2 ranking-day logic):")
    for tid, (L, variant) in zip(trial_ids, GRID):
        print(f"  {tid} (L={L},{variant}): {plaus[tid]}")


# ---------------------------------------------------------------------------
# Holdout path (orchestrating session only; never run by the analyst)
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
    L, variant = GRID[n - 1]
    if trial_config(L, variant) != config:
        raise ValueError(
            f"development_result config {config} does not match grid entry {n} "
            f"{trial_config(L, variant)}"
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
            run_config(full, L, variant, costs=costs, gross_cap=gross_cap),
            run_config(dev_only, L, variant, costs=costs, gross_cap=gross_cap),
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
