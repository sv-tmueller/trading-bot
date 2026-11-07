"""Shared loading, sizing, simulation, slicing and payload helpers for round ``etf-daily-r2``.

Research-only: no broker, no Supabase, no LLM. The only network contact is the
market-data fetch inside ``backtest.etf_data.load_daily_bars`` (the only loader
this study may use; it enforces the holdout lock). Never imported by
``supabase/functions/``. Every definition here is frozen in
``docs/research/2026-11-06-etf-daily-r2-preregistration.md`` (section numbers in
comments refer to it). Rule-specific code (the #763 gate's exposure fraction,
the #764 Donchian state machine) lives in the per-candidate runner scripts;
this module holds only what both candidates, the benchmark and the two
information re-runs share (sections 2, 4, 5, 7 and 8).

Sizing-chain note (section 3.1.1): the chain here is generic -- it takes a
signal frame in {-1, 0, +1}. The #763 gate's row-wise ``f(T)`` multiplication
happens AFTER ``vol_target_weights`` and is applied in that candidate's runner
(``run_vol_regime_gating.py``), never here.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backtest.etf_data import HOLDOUT_START, load_daily_bars  # noqa: E402
from backtest.portfolio import CostModel, PortfolioResult, simulate_portfolio  # noqa: E402
from backtest.scorecard import compute_scorecard  # noqa: E402
from backtest.vol_target import (  # noqa: E402
    benchmark_weights,
    inverse_vol_weights,
    vol_target_weights,
)

# --- Section 1: identifiers -------------------------------------------------
ROUND_ID = "etf-daily-r2"
PREREG_SOURCE = "docs/research/2026-11-06-etf-daily-r2-preregistration.md"
STUDY_DIR = HERE
PIPELINE_DIR = REPO / "docs" / "research" / "pipeline"
TRIALS_PATH = PIPELINE_DIR / "trials.json"

# --- Section 2: universe and data -------------------------------------------
ETF_BASKET_XA14: List[str] = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "TLT",
    "IEF", "LQD", "HYG", "TIP", "GLD", "DBC", "UUP",
]
CASH_SYMBOL = "BIL"          # never traded; cash_returns of the simulator
BENCHMARK_SYMBOL = "SPY"     # section 7
ALL_TICKERS: List[str] = ETF_BASKET_XA14 + [CASH_SYMBOL]

# --- Section 4: sizing and simulation ---------------------------------------
VOL_LOOKBACK = 60
TARGET_VOL = 0.10
GROSS_CAP = 1.0              # every verdict run
LEVERAGE_GROSS_CAP = 1.5     # leverage_info line only
REBALANCE_BAND = 0.02
STARTING_EQUITY = 100_000.0

# --- Section 5: costs -------------------------------------------------------
VERDICT_COSTS = CostModel(
    slippage_bps=5.0, commission_bps=0.0,
    borrow_bps_annual=50.0, financing_spread_bps_annual=100.0,
)
DOUBLE_COSTS = CostModel(
    slippage_bps=10.0, commission_bps=0.0,
    borrow_bps_annual=100.0, financing_spread_bps_annual=200.0,
)

SIZING_CONFIG = {
    "vol_lookback": VOL_LOOKBACK,
    "target_vol": TARGET_VOL,
    "gross_cap": GROSS_CAP,
    "rebalance_band": REBALANCE_BAND,
}


@dataclass
class BasketData:
    """The basket on the master index (section 2).

    ``opens`` / ``closes``: the 14 ETFs, un-filled (trading: the simulator skips
    an asset on a day with a missing open or close). ``signal_closes``: the 14
    ETFs plus BIL, forward-filled across a ticker's missing days (signal
    computation only). ``asset_returns = closes.pct_change()`` (row 0 NaN) and
    ``cash_returns = Close_BIL.pct_change()``, both on the master index.
    """

    data_start: pd.Timestamp
    index: pd.DatetimeIndex
    opens: pd.DataFrame
    closes: pd.DataFrame
    signal_closes: pd.DataFrame
    asset_returns: pd.DataFrame
    cash_returns: pd.Series
    missing_rows: Dict[str, int]


def build_basket(bars: Dict[str, pd.DataFrame]) -> BasketData:
    """Master index and frames from the loader's per-ticker OHLC frames."""
    missing = [t for t in ALL_TICKERS if t not in bars]
    if missing:
        raise ValueError(f"loader returned no frame for {missing}")
    common = None
    for t in ALL_TICKERS:
        idx = bars[t].index
        common = idx if common is None else common.intersection(idx)
    if common is None or len(common) == 0:
        raise ValueError("no date on which all 15 tickers have a bar")
    data_start = pd.Timestamp(common.min())      # first date all 15 have a bar

    spy_idx = bars[BENCHMARK_SYMBOL].index
    index = pd.DatetimeIndex(spy_idx[spy_idx >= data_start])  # SPY's trading days
    if not (index.is_unique and index.is_monotonic_increasing):
        raise ValueError("master index must be unique and increasing")

    opens = pd.DataFrame(
        {t: bars[t]["Open"].reindex(index).astype(float) for t in ETF_BASKET_XA14},
        index=index,
    )
    closes = pd.DataFrame(
        {t: bars[t]["Close"].reindex(index).astype(float) for t in ETF_BASKET_XA14},
        index=index,
    )
    signal_closes = pd.DataFrame(
        {t: bars[t]["Close"].reindex(index).astype(float) for t in ALL_TICKERS},
        index=index,
    ).ffill()
    cash_close = bars[CASH_SYMBOL]["Close"].reindex(index).astype(float)

    asset_returns = closes.pct_change()
    cash_returns = cash_close.pct_change()

    missing_rows = {
        t: int(bars[t]["Close"].reindex(index).isna().sum()) for t in ALL_TICKERS
    }
    return BasketData(
        data_start=data_start,
        index=index,
        opens=opens,
        closes=closes,
        signal_closes=signal_closes,
        asset_returns=asset_returns,
        cash_returns=cash_returns,
        missing_rows=missing_rows,
    )


def load_basket(phase: str, candidate_id: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """The raw per-ticker frames through the one permitted loader."""
    # Default pipeline_dir on purpose (skill Phase 4 e); always run from the worktree root.
    return load_daily_bars(ALL_TICKERS, phase=phase, candidate_id=candidate_id)


def cut_bars_before(bars: Dict[str, pd.DataFrame], cutoff) -> Dict[str, pd.DataFrame]:
    """Rows strictly before ``cutoff`` (what the development loader returns)."""
    ts = pd.Timestamp(cutoff)
    return {t: df[df.index < ts] for t, df in bars.items()}


def check_signals(signals: pd.DataFrame, data: BasketData) -> None:
    """The signal frame must share the master index and the 14 ETF columns."""
    if not signals.index.equals(data.asset_returns.index):
        raise ValueError("signals index must equal the master index")
    if list(signals.columns) != list(data.asset_returns.columns):
        raise ValueError("signals columns must be the 14 ETFs in basket order")
    vals = signals.to_numpy(dtype=float)
    if not np.isin(vals, (-1.0, 0.0, 1.0)).all():
        raise ValueError("signals must be in {-1, 0, 1}")


# --- Section 4: the sizing chain, in the two steps the runners compose -------
# ``size_signals`` and ``simulate_from_target`` exist so a candidate can apply a
# per-candidate step between vol targeting and the simulator (the #763 gate's
# row-wise f(T) multiplication, section 3.1.1 step 2). ``size_and_simulate`` is
# the straight-through chain for candidates (and re-runs) that need no such step.


def size_signals(
    signals: pd.DataFrame,
    data: BasketData,
    *,
    gross_cap: float,
) -> pd.DataFrame:
    """inverse-vol -> vol target (section 4), no gate, no simulation."""
    check_signals(signals, data)
    raw = inverse_vol_weights(signals, data.asset_returns, lookback=VOL_LOOKBACK)
    return vol_target_weights(
        raw, data.asset_returns,
        target_vol=TARGET_VOL, lookback=VOL_LOOKBACK, gross_cap=gross_cap,
    )


def simulate_from_target(
    target_weights: pd.DataFrame,
    data: BasketData,
    *,
    costs: CostModel,
    gross_cap: float,
) -> PortfolioResult:
    """The simulator call of section 4 on an already-final weight frame."""
    return simulate_portfolio(
        target_weights, data.opens, data.closes, data.cash_returns,
        starting_equity=STARTING_EQUITY, costs=costs,
        gross_cap=gross_cap, rebalance_band=REBALANCE_BAND,
    )


def size_and_simulate(
    signals: pd.DataFrame,
    data: BasketData,
    *,
    costs: CostModel,
    gross_cap: float,
) -> PortfolioResult:
    """Section 4: inverse-vol -> vol target -> simulator, one configuration."""
    return simulate_from_target(
        size_signals(signals, data, gross_cap=gross_cap), data,
        costs=costs, gross_cap=gross_cap,
    )


def simulate_benchmark(data: BasketData) -> PortfolioResult:
    """Section 7: vol-targeted SPY through the same simulator call."""
    target = benchmark_weights(
        data.asset_returns, symbol=BENCHMARK_SYMBOL,
        target_vol=TARGET_VOL, lookback=VOL_LOOKBACK, gross_cap=GROSS_CAP,
    )
    return simulate_portfolio(
        target, data.opens, data.closes, data.cash_returns,
        starting_equity=STARTING_EQUITY, costs=VERDICT_COSTS,
        gross_cap=GROSS_CAP, rebalance_band=REBALANCE_BAND,
    )


def sharpe_daily(returns: pd.Series) -> float:
    """mean / std(ddof=1) of the finite daily returns; 0.0 if std <= 1e-12."""
    r = returns.to_numpy(dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    std = float(r.std(ddof=1))
    if std <= 1e-12:
        return 0.0
    return float(r.mean() / std)


def n_finite(returns: pd.Series) -> int:
    r = returns.to_numpy(dtype=float)
    return int(np.isfinite(r).sum())


def slice_to_holdout(full: PortfolioResult, dev_only: PortfolioResult) -> PortfolioResult:
    """Section 8 holdout method: cut a full-series result to rows >= HOLDOUT_START.

    ``equity``, ``daily_returns``, ``gross_exposure`` and ``held_weights`` are
    sliced; ``trades`` keeps those with ``exit_date >= HOLDOUT_START``; ``costs``
    per key = full-series costs minus the development-only run's costs (the two
    runs are identical through DEV_END).
    """
    start = pd.Timestamp(HOLDOUT_START)
    mask = full.equity.index >= start
    if not mask.any():
        raise ValueError("no rows on or after HOLDOUT_START in the full-series result")
    dev_idx = full.equity.index[~mask]
    if not dev_idx.equals(dev_only.equity.index):
        raise ValueError("development-only run does not cover exactly the pre-holdout rows")
    if not np.allclose(full.equity[~mask].to_numpy(), dev_only.equity.to_numpy()):
        raise ValueError("full-series and development-only equity differ before HOLDOUT_START")
    costs = {k: float(full.costs[k]) - float(dev_only.costs[k]) for k in full.costs}
    trades = [t for t in full.trades if pd.Timestamp(t["exit_date"]) >= start]
    return PortfolioResult(
        equity=full.equity[mask],
        daily_returns=full.daily_returns[mask],
        gross_exposure=full.gross_exposure[mask],
        held_weights=full.held_weights[mask],
        trades=trades,
        costs=costs,
    )


def git_commit() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def write_returns_csv(path: Path, columns: Dict[str, pd.Series], index: pd.DatetimeIndex) -> None:
    """Section 7 returns file: index ``date`` (ISO), one column per trial plus benchmark."""
    frame = pd.DataFrame({k: v.reindex(index) for k, v in columns.items()}, index=index)
    frame.index = pd.Index([d.strftime("%Y-%m-%d") for d in index], name="date")
    frame.to_csv(path, float_format="%.17g")


def strict_json(payload: dict) -> str:
    """``json.dumps`` with ``allow_nan=False``: raises on NaN/inf, never writes them."""
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def scorecard_for(
    result: PortfolioResult,
    benchmark: PortfolioResult,
    *,
    double_cost: Optional[PortfolioResult] = None,
    leverage_info: Optional[PortfolioResult] = None,
) -> dict:
    return compute_scorecard(
        result, benchmark, target_vol=TARGET_VOL,
        double_cost=double_cost, leverage_info=leverage_info,
    )


def _fmt(x: Optional[float], digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def summary_row(label: str, card: dict) -> str:
    """One compact table row from a scorecard (or its benchmark block)."""
    return (
        f"{label:<40} {_fmt(card.get('sharpe_daily'), 5):>9} "
        f"{_fmt(card.get('sharpe_annual')):>8} {_fmt(card.get('cagr'), 4):>8} "
        f"{_fmt(card.get('max_drawdown'), 4):>8} "
        f"{_fmt(card.get('round_trips_per_year'), 2):>8} "
        f"{_fmt(card.get('max_time_share_one_etf'), 4):>9}"
    )


def summary_header() -> str:
    return (
        f"{'trial':<40} {'sharpe_d':>9} {'sharpe_a':>8} {'cagr':>8} "
        f"{'max_dd':>8} {'rt/yr':>8} {'max_tshr':>9}"
    )
