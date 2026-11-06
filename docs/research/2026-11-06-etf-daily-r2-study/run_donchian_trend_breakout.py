"""Candidate #764 ``etf-daily-r2-donchian-trend-breakout``: Turtle-style Donchian
channel breakout with a separate (shorter) exit channel and an optional short
side, on the frozen 14-ETF basket.

Research-only: no broker, no Supabase, no LLM, no production code. The only
network contact is the market-data fetch inside ``backtest.etf_data.load_daily_bars``
(adjusted daily OHLC; the loader enforces the holdout lock). Never
imported by ``supabase/functions/``. Every definition applied here is frozen in
``docs/research/2026-11-06-etf-daily-r2-preregistration.md`` (section numbers in
comments refer to it); nothing outside its section 6 grid is evaluated and
nothing in it is tuned.

Rule (section 3.2, per-ETF state machine): each ETF's signal is a state in
{+1, 0, -1}, evaluated at every close in master-index order on the
forward-filled signal closes, with the channels excluding the current row:

- Entry long:  close at T > highest close of the prior ``L_e`` rows.
- Exit long:   close at T < lowest close of the prior ``L_x`` rows,
  ``L_x = ceil(L_e / 2)`` (28, 63, 126 for 55, 126, 252).
- ``long_flat``: {+1 on entry, 0 after exit}.
- ``long_short``: additionally short on the lower ``L_e``-channel breakdown
  (close at T < lowest close of the prior ``L_e`` rows), covered on the upper
  exit channel (close at T > highest close of the prior ``L_x`` rows).
- A not-computable channel (warm-up) leaves the state unchanged. No separate
  stop, target or time stop. Evaluated from the data start.

Sizing (section 4, the r1 chain via ``etf_daily_r2_common``): the signal frame
goes through ``inverse_vol_weights`` then ``vol_target_weights`` directly; there
is NO per-candidate post-multiplication for this candidate -- the signals carry
the rule.

Usage (always from the worktree root)::

    export CLAUDE_AGENT_NO_BROKER=1
    venv/bin/python docs/research/2026-11-06-etf-daily-r2-study/run_donchian_trend_breakout.py \
        --phase development

The holdout path (``--phase holdout``) is NOT implemented in this script: per
the dispatch, the analyst implements the development path only; the
orchestrating session runs the holdout separately.

The development path appends the 6 trials to the programme ledger in one
``append_trials`` call (no ``round_budget=``; the round's 18 of 50 is inside
the budget), writes ``<candidate_id>-development-returns.csv`` and
``<candidate_id>-development-payload.json`` into this directory and never
calls ``record_result``.
"""
from __future__ import annotations

import argparse
import math
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
from backtest.portfolio import PortfolioResult, round_trips_per_year  # noqa: E402
from backtest.trial_store import DAILY_ALLOCATION, TrialRecord, append_trials  # noqa: E402

CANDIDATE_ID = "etf-daily-r2-donchian-trend-breakout"
RUN_DATE = "2026-11-06"

# Section 6 grid, N = 6, in trial-id order: (L_e, L_x, variant).
# L_x is derived (ceil(L_e/2)); it is asserted against the frozen table below.
GRID: List[Tuple[int, int, str]] = [
    (55, 28, "long_flat"),
    (55, 28, "long_short"),
    (126, 63, "long_flat"),
    (126, 63, "long_short"),
    (252, 126, "long_flat"),
    (252, 126, "long_short"),
]


def trial_id(n: int) -> str:
    return f"{CANDIDATE_ID}-{n:02d}"


def trial_config(L_e: int, L_x: int, variant: str) -> dict:
    cfg = {"L_e": int(L_e), "L_x": int(L_x), "variant": str(variant)}
    cfg.update(common.SIZING_CONFIG)
    return cfg


# ---------------------------------------------------------------------------
# Section 3.2: the per-ETF Donchian state machine
# ---------------------------------------------------------------------------

def _channel_prior(series: pd.Series, window: int, kind: str) -> np.ndarray:
    """Highest (``max``) or lowest (``min``) close of the prior ``window`` rows.

    Row T holds the extremum of rows T-``window`` .. T-1 (the channel excludes
    the current row); NaN during warm-up (fewer than ``window`` prior rows).
    """
    rolled = series.rolling(window=window, min_periods=window)
    ext = rolled.max() if kind == "max" else rolled.min()
    return ext.shift(1).to_numpy(dtype=float)


def donchian_state(
    close: pd.Series,
    L_e: int,
    variant: str,
) -> np.ndarray:
    """One ETF's signal state {+1, 0, -1} row by row (section 3.2).

    Triggers, with channels excluding the current row (NaN -> trigger False,
    i.e. warm-up leaves the state unchanged):

    - ``entry_long``  : close > max of prior ``L_e`` rows  -> state +1 (from any
      state; from -1 it covers the short and goes long the same row).
    - ``entry_short`` : close < min of prior ``L_e`` rows (``long_short`` only)
      -> state -1 (from any state; from +1 the long exits and the short opens
      the same row).
    - ``exit_long``   : close < min of prior ``L_x`` rows  -> a +1 state goes to
      0 (flat; the short side needs the wider ``L_e`` breakdown).
    - ``exit_short``  : close > max of prior ``L_x`` rows  -> a -1 state goes to
      0 (flat; the long side needs the wider ``L_e`` breakout).

    Because the ``L_e`` channel strictly contains the ``L_x`` channel, an
    entry trigger implies the opposite exit trigger on the same row; the entry
    is evaluated first so the state flips directly (+1 -> -1 or -1 -> +1)
    rather than passing through 0.
    """
    if L_e < 1:
        raise ValueError(f"L_e must be >= 1, got {L_e}")
    L_x = int(math.ceil(L_e / 2))
    if L_x < 1:
        raise ValueError(f"L_x must be >= 1, got {L_x}")
    if variant not in ("long_flat", "long_short"):
        raise ValueError(f"unknown variant: {variant!r}")

    c = close.to_numpy(dtype=float)
    upper_e = _channel_prior(close, L_e, "max")
    lower_e = _channel_prior(close, L_e, "min")
    upper_x = _channel_prior(close, L_x, "max")
    lower_x = _channel_prior(close, L_x, "min")

    with np.errstate(invalid="ignore"):
        entry_long = c > upper_e      # NaN channel -> False (warm-up)
        entry_short = c < lower_e
        exit_long = c < lower_x
        exit_short = c > upper_x
    if variant == "long_flat":
        entry_short = np.zeros_like(entry_short)

    state = 0
    out = np.empty(len(c), dtype=int)
    for t in range(len(c)):
        if entry_long[t]:
            state = 1
        elif entry_short[t]:
            state = -1
        elif state == 1 and exit_long[t]:
            state = 0
        elif state == -1 and exit_short[t]:
            state = 0
        out[t] = state
    return out


def donchian_signals(
    data: common.BasketData,
    L_e: int,
    variant: str,
) -> pd.DataFrame:
    """The signal frame (14 ETF columns, master index) for one configuration."""
    cols = {
        t: donchian_state(data.signal_closes[t], L_e, variant)
        for t in common.ETF_BASKET_XA14
    }
    return pd.DataFrame(cols, index=data.index, columns=common.ETF_BASKET_XA14)


def run_config(
    data: common.BasketData,
    L_e: int,
    variant: str,
    *,
    costs,
    gross_cap: float,
) -> PortfolioResult:
    """Section 3.2 + section 4: signals -> sizing chain -> simulator, no gate."""
    signals = donchian_signals(data, L_e, variant)
    return common.size_and_simulate(signals, data, costs=costs, gross_cap=gross_cap)


# ---------------------------------------------------------------------------
# Development path
# ---------------------------------------------------------------------------

def run_development() -> None:
    # Frozen-grid self-check: L_x is derived, the table's value must match.
    for L_e, L_x, _variant in GRID:
        if L_x != int(math.ceil(L_e / 2)):
            raise RuntimeError(f"grid L_x {L_x} != ceil(L_e/2) for L_e={L_e}")

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
    for tid, (L_e, L_x, variant) in zip(trial_ids, GRID):
        signals = donchian_signals(data, L_e, variant)
        res = common.size_and_simulate(
            signals, data, costs=common.VERDICT_COSTS, gross_cap=common.GROSS_CAP,
        )
        results[tid] = res
        cards[tid] = common.scorecard_for(res, benchmark)
        # The ledger value is the scorecard's sharpe_daily; cross-check the definition.
        own = common.sharpe_daily(res.daily_returns)
        if abs(own - cards[tid]["sharpe_daily"]) > 1e-12:
            raise RuntimeError(f"{tid}: sharpe_daily mismatch {own} vs {cards[tid]['sharpe_daily']}")
        if common.n_finite(res.daily_returns) != cards[tid]["n_periods"]:
            raise RuntimeError(f"{tid}: n_periods mismatch")
        sig = signals.to_numpy(dtype=float)
        print(f"{tid}: signal rows +1 {float((sig == 1.0).mean()):.4f} / "
              f"-1 {float((sig == -1.0).mean()):.4f} of ETF-days "
              f"(L_e={L_e}, L_x={L_x}, {variant})")

    # Section 6: every trial (losers included) in one append_trials call.
    records = [
        TrialRecord(
            trial_id=tid,
            round_id=common.ROUND_ID,
            candidate_id=CANDIDATE_ID,
            space=DAILY_ALLOCATION,
            config=trial_config(L_e, L_x, variant),
            sharpe_daily=float(cards[tid]["sharpe_daily"]),
            n_periods=int(cards[tid]["n_periods"]),
            source=common.PREREG_SOURCE,
            date=RUN_DATE,
        )
        for tid, (L_e, L_x, variant) in zip(trial_ids, GRID)
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
    L_sel, Lx_sel, variant_sel = GRID[trial_ids.index(selected)]
    config = trial_config(L_sel, Lx_sel, variant_sel)

    # Section 5 double-cost re-run; section 4/7 leverage_info re-run at gross cap 1.5.
    double = run_config(data, L_sel, variant_sel,
                        costs=common.DOUBLE_COSTS, gross_cap=common.GROSS_CAP)
    leverage = run_config(data, L_sel, variant_sel,
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
    for tid, (L_e, L_x, variant) in zip(trial_ids, GRID):
        print(common.summary_row(f"{tid} (L_e={L_e},L_x={L_x},{variant})", cards[tid]))
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", choices=("development",), required=True)
    args = parser.parse_args(argv)
    run_development()


if __name__ == "__main__":
    main()
