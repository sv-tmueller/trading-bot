"""The 11 pre-registered signal shapes + frozen 33-cell registry (#376).

Research-only. Lives in ``backtest/`` and is never imported by
``supabase/functions/``. No LLM, no broker calls, no orders.

Every shape here is a 1:1 implementation of
``docs/research/2026-07-13-forex-4h-strategy-preregistration.md`` §3 (frozen
at SHA e409bf8) — that document is the single authoritative source for every
threshold, window length, and tie rule; nothing here re-derives a number
from EUR/USD price history.

Signal interface (spec §2, SUB_PLAN §2)
----------------------------------------
Every shape function is a **position-unaware pure function** of a
pre-rolled bar-history slice: value at bar t = what the family would say at
t's close, computed vectorized over the whole slice. This is exactly
equivalent to "not called while a position is open" (§2) because
``fx_execution.simulate_fx``/``simulate_fx_state`` only ever CONSULT the
signal at bar i-1 when flat and never read it mid-trade — the simulator
does the T -> T+1 fill shift itself. Do NOT pre-shift the input here.

Contract, every shape:
  - dtype int, values in {-1, 0, 1}; index identical to the input.
  - warm-up / NaN bars -> 0, emitted EXPLICITLY (not left as NaN relying on
    a downstream ``.fillna(0)``) — comparisons against NaN in pandas/numpy
    already evaluate False, so a warm-up bar naturally lands on the `0`
    branch of every threshold test below; this module additionally
    constructs every returned Series starting from an explicit all-zero
    base so there is never a NaN in the output.
  - Ties (any exact-equality condition) -> 0 (theta=0, spec §2, restated per
    family below).

Per-window pre-roll note (SUB_PLAN §2): signals are computed per pre-rolled
window slice (the walkforward convention). This matters for the Wilder RSI
recursion in particular: the seed anchors at each window's pre-roll start;
with a 300-bar pre-roll (spec §5), the RMA memory term is (13/14)**300 ~=
1e-10 for R1 (n=14), so values at test-window start are fully converged.
This is stated here so it is not "fixed" later as if it were a bug.
"""
from __future__ import annotations

from typing import Callable, Dict, List

import numpy as np
import pandas as pd

# §4: symmetric TP=SL=R grid, in fractional units (20bp, 30bp, 50bp).
R_GRID = (0.0020, 0.0030, 0.0050)


def _zero_int_series(index: pd.Index) -> pd.Series:
    return pd.Series(0, index=index, dtype="int64")


def _apply_long_short(index: pd.Index, long_cond: pd.Series, short_cond: pd.Series) -> pd.Series:
    """Combine two boolean masks into the {-1,0,1} contract. NaN in either
    mask (shouldn't normally occur -- comparisons against NaN are already
    False -- but guarded explicitly) is treated as False -> decline."""
    sig = _zero_int_series(index)
    sig[long_cond.fillna(False)] = 1
    sig[short_cond.fillna(False)] = -1
    return sig


# ---------------------------------------------------------------------------
# Family T -- trend-following (§3 T1, T2)
# ---------------------------------------------------------------------------

def sma_cross_signal(mid_close: pd.Series, fast: int, slow: int) -> pd.Series:
    """T1: fast/slow SMA cross-as-EVENT (§3 T1).

    SMA = unweighted arithmetic mean over the trailing window INCLUDING the
    current completed bar (``rolling(n).mean()``). "Crosses on the
    just-completed bar": fast was <= slow at the prior bar AND fast > slow
    at this bar -> long; the mirror image -> short. fast==slow at the
    current bar, or the prior-bar relationship already being on the "right"
    side (not a fresh cross), or either SMA NaN at t or t-1 -> decline
    (comparisons against NaN evaluate False in pandas, so this falls out of
    the boolean masks below without special-casing).
    """
    fast_sma = mid_close.rolling(fast).mean()
    slow_sma = mid_close.rolling(slow).mean()
    fast_prev = fast_sma.shift(1)
    slow_prev = slow_sma.shift(1)

    cross_up = (fast_prev <= slow_prev) & (fast_sma > slow_sma)
    cross_down = (fast_prev >= slow_prev) & (fast_sma < slow_sma)
    return _apply_long_short(mid_close.index, cross_up, cross_down)


def donchian_signal(
    mid_close: pd.Series, mid_high: pd.Series, mid_low: pd.Series, n: int,
) -> pd.Series:
    """T2: Donchian breakout, channel EXCLUDING the current bar (§3 T2, the
    pinned off-by-one). Channel = the N bars strictly before the bar being
    evaluated: ``mid_high.shift(1).rolling(n).max()`` / the mirror for
    mid_low. Mid close strictly ABOVE the prior-N mid-high -> long; strictly
    BELOW the prior-N mid-low -> short; exactly-equal or NaN (insufficient
    history) -> decline.
    """
    channel_high = mid_high.shift(1).rolling(n).max()
    channel_low = mid_low.shift(1).rolling(n).min()

    long_cond = mid_close > channel_high
    short_cond = mid_close < channel_low
    return _apply_long_short(mid_close.index, long_cond, short_cond)


# ---------------------------------------------------------------------------
# Family M -- momentum (§3 M1)
# ---------------------------------------------------------------------------

def roc_signal(mid_close: pd.Series, n: int) -> pd.Series:
    """M1: ROC(N) = close/close[N bars ago] - 1. theta fixed at 0: > 0 ->
    long, < 0 -> short, ==0 or NaN (warm-up) -> decline."""
    roc = mid_close / mid_close.shift(n) - 1.0
    long_cond = roc > 0
    short_cond = roc < 0
    return _apply_long_short(mid_close.index, long_cond, short_cond)


# ---------------------------------------------------------------------------
# Family R -- mean-reversion (§3 R1, R2, R3)
# ---------------------------------------------------------------------------

def wilder_rsi(mid_close: pd.Series, n: int) -> pd.Series:
    """Wilder's RMA-smoothed RSI (§3 R1/R2), explicit recursion:

        avg[t] = ((n-1) * avg[t-1] + x[t]) / n

    seeded by the SIMPLE arithmetic mean of the first n gains and first n
    losses (bars 1..n, 0-indexed prices p0..). The first n bars (0-indexed
    0..n-1) NEVER receive an RSI value -- RSI is defined from bar n onward
    (0-indexed). Wilder's degenerate conventions: avgLoss==0 -> RSI=100;
    avgGain==0 -> RSI=0 (avgLoss checked first, so a simultaneous
    avgGain==avgLoss==0 -- a perfectly flat window -- resolves to RSI=100).

    Deliberately NOT ``ewm(alpha=1/n, adjust=False)`` -- that does not
    reproduce this pinned simple-mean seed (SUB_PLAN §3 warning). A plain
    Python loop is used for the recursion (research code; a loop is fine).
    """
    prices = mid_close.to_numpy(dtype=float)
    T = len(prices)
    rsi = np.full(T, np.nan)
    if T <= n:
        return pd.Series(rsi, index=mid_close.index)

    diffs = np.diff(prices)  # diffs[i] = prices[i+1] - prices[i]; "gain/loss at bar i+1"
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)

    avg_gain = float(gains[:n].mean())
    avg_loss = float(losses[:n].mean())

    def _rsi_from_avgs(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        if ag == 0:
            return 0.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    rsi[n] = _rsi_from_avgs(avg_gain, avg_loss)
    for t in range(n + 1, T):
        g = gains[t - 1]
        l = losses[t - 1]
        avg_gain = ((n - 1) * avg_gain + g) / n
        avg_loss = ((n - 1) * avg_loss + l) / n
        rsi[t] = _rsi_from_avgs(avg_gain, avg_loss)

    return pd.Series(rsi, index=mid_close.index)


def rsi_signal(mid_close: pd.Series, n: int, low: float, high: float) -> pd.Series:
    """R1/R2: RSI < low -> long, RSI > high -> short, else (incl. exactly
    low/high, or NaN warm-up) -> decline."""
    rsi = wilder_rsi(mid_close, n)
    long_cond = rsi < low
    short_cond = rsi > high
    return _apply_long_short(mid_close.index, long_cond, short_cond)


def bollinger_signal(mid_close: pd.Series, n: int = 20, num_std: float = 2.0) -> pd.Series:
    """R3: Bollinger(20, 2). SMA(20) of mid close (same SMA definition as
    T1) +/- num_std standard deviations over the SAME trailing 20-bar
    window, with **ddof=0** (population std -- Bollinger's own published
    definition; pandas' ``.std()`` defaults to ddof=1, which would silently
    diverge -- pinned explicitly, spec §3 R3). Strictly below the lower band
    -> long; strictly above the upper band -> short; exactly-on-band or
    NaN (warm-up) -> decline.
    """
    sma = mid_close.rolling(n).mean()
    std = mid_close.rolling(n).std(ddof=0)
    upper = sma + num_std * std
    lower = sma - num_std * std

    long_cond = mid_close < lower
    short_cond = mid_close > upper
    return _apply_long_short(mid_close.index, long_cond, short_cond)


# ---------------------------------------------------------------------------
# Registry (§4) -- 11 shapes x 3 R values = 33 cells
# ---------------------------------------------------------------------------

def _mid_close(df: pd.DataFrame) -> pd.Series:
    return df["MidClose"]


SHAPES: "Dict[str, Callable[[pd.DataFrame], pd.Series]]" = {
    "T1_sma_5_20": lambda df: sma_cross_signal(df["MidClose"], 5, 20),
    "T1_sma_20_50": lambda df: sma_cross_signal(df["MidClose"], 20, 50),
    "T1_sma_50_200": lambda df: sma_cross_signal(df["MidClose"], 50, 200),
    "T2_donchian_20": lambda df: donchian_signal(df["MidClose"], df["MidHigh"], df["MidLow"], 20),
    "T2_donchian_55": lambda df: donchian_signal(df["MidClose"], df["MidHigh"], df["MidLow"], 55),
    "M1_roc_12": lambda df: roc_signal(df["MidClose"], 12),
    "M1_roc_24": lambda df: roc_signal(df["MidClose"], 24),
    "M1_roc_48": lambda df: roc_signal(df["MidClose"], 48),
    "R1_rsi_14": lambda df: rsi_signal(df["MidClose"], 14, 30, 70),
    "R2_rsi_2": lambda df: rsi_signal(df["MidClose"], 2, 10, 90),
    "R3_boll_20_2": lambda df: bollinger_signal(df["MidClose"], 20, 2.0),
}


def _r_label(r: float) -> str:
    """R value (fraction) -> stable label, e.g. 0.0020 -> 'R20' (bp)."""
    return f"R{int(round(r * 10_000))}"


CELLS: "List[str]" = [
    f"{shape_id}_{_r_label(r)}" for shape_id in SHAPES for r in R_GRID
]


def build_cells() -> "List[dict]":
    """Every (shape, R) combo as ``{cell_id, shape_id, r, fn}`` -- the
    survivor-evaluated unit (spec §4/§6). 33 entries, always."""
    cells: "List[dict]" = []
    for shape_id, fn in SHAPES.items():
        for r in R_GRID:
            cells.append({
                "cell_id": f"{shape_id}_{_r_label(r)}",
                "shape_id": shape_id,
                "r": r,
                "fn": fn,
            })
    return cells
