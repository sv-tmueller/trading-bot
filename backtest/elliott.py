"""Deterministic Elliott Wave labeler (#468) — no LLM anywhere in this module.

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls, no network, no I/O. Pure ``pandas``/``numpy`` arithmetic only
(no ``scipy`` — ``argrelextrema`` and friends are both unavailable in this repo's
research venv and lookahead-prone by construction: they scan the whole array).

This module reverses a recorded ``skip`` verdict against a specific, cited object:
``docs/research/swing-trading/roadmap.md:585`` and ``strategies.md:415`` record Elliott
Wave as ``skip`` because wave-counting is "non-deterministic by construction" — but that
verdict was against an **LLM-authored** count. ``strategies.md:378`` itself asks for the
deterministic envelope this module builds ("codify pivot detection deterministically …
treat the LLM only as a confirmation layer, not the count author"). This module builds
that envelope with **no LLM at all**: a causal ZigZag pivot state machine (§1), a wave
grammar with hard rules and frozen Fibonacci bands (§2), a total-order no-backtracking
matcher (§3), and a signal mapping (§4). Full reasoning:
``docs/research/2026-07-27-forex-1h-data-feasibility.md`` §1.

This module does **not** claim the algorithm has any economic edge — only that it is
deterministic, falsifiable, and now testable. No performance number is computed anywhere
in this module or its calibration runner (``backtest/run_fx_ew_calibration.py``).

Explicit v1 non-goals (state loudly — omitting these is what makes v1 mechanizable):
nested / fractal counting (a wave subdividing into its own 5-wave set) — the largest
doctrinal simplification; diagonals (leading/ending, which permit W1/W4 overlap); flats
and triangles (only the zigzag correction is mechanized); the alternation guideline (W2
sharp => W4 sideways); multi-timeframe confluence; wave-2 entry ("start of wave 3", which
requires signalling on an *incomplete* structure).

§1 Causal ZigZag pivots — the hardest correctness point
---------------------------------------------------------
A classic ZigZag repaints: a pivot at bar t is only knowable at bar t+k, once price has
reversed by theta from it. Scanning the full array for local extrema is look-ahead and
would silently produce a beautiful, worthless backtest. ``find_pivots`` is instead a
streaming state machine over ``Close`` only (frozen price basis — removes intrabar-path
ambiguity entirely; matches ``fx_signals.py``'s ``mid_close``-throughout convention; H/L
touch logic already lives in ``bracket.py``/``fx_execution.py`` for exits, kept separate
from the *signal*). State: ``(direction, running_extreme_price, running_extreme_idx)``.

Bar 0 seeds a provisional extreme with ``direction = UNKNOWN`` (tracked internally as
``None``). While UNKNOWN, both a running high and a running low are tracked from the
seed; direction resolves at the first bar crossing theta away from whichever extreme has
moved past the seed (HIGH-breach is checked before LOW-breach when both extremes have
moved on the same bar — an internal tie-break, frozen and documented here, distinct from
the wave-matching tie-break in §3). Once resolved: in an UP leg, ``close > running_extreme``
extends the extreme; ``close <= running_extreme * (1 - theta)`` **confirms** a HIGH pivot
at the extreme's bar and flips to DOWN (symmetric for DOWN legs, mirrored inequalities).

**The final, unconfirmed leg is never emitted** — that is the whole no-lookahead guarantee.
Invariant, property-tested in ``tests/test_elliott.py``: ``confirmed_idx > pivot_idx`` for
every row, always (structural: a bar is either a new-extreme bar or a confirming bar,
never both, by the if/elif branching below).

Frozen conventions (each a decision, stated here):
  - **Price basis: Close only** (see above).
  - **theta (reversal threshold): 0.30% default**, kwarg-overridable. Inherited from an
    already-frozen repo constant, not tuned on wave counts — ``fx_signals.R_GRID =
    (0.0020, 0.0030, 0.0050)`` and ``run_fx_plumbing_check.R_PCT = 0.0030``. Grid axis:
    ``THETA_GRID = {0.20%, 0.30%, 0.50%}``, mirroring ``R_GRID`` exactly.
  - **Threshold comparison: inclusive** (``<=``/``>=``) — pinned by a boundary test.
  - **Scale: percentage, not ATR-multiple** — an ATR-adaptive theta would couple the
    labeler to a rolling-window aggregate, precisely the functional form of every killed
    family. ATR-theta is a declared future grid axis, not built here.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# --- §1 pivot kinds -------------------------------------------------------
HIGH = "H"
LOW = "L"

# theta grid, mirroring fx_signals.R_GRID / run_fx_plumbing_check.R_PCT exactly (#468 §3.1).
DEFAULT_THETA = 0.0030
THETA_GRID = (0.0020, 0.0030, 0.0050)

_PIVOT_COLUMNS = ["pivot_idx", "pivot_ts", "pivot_price", "kind", "confirmed_idx", "confirmed_ts"]


def _empty_pivots() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pivot_idx": pd.Series(dtype="int64"),
            "pivot_ts": pd.Series(dtype="datetime64[ns, UTC]"),
            "pivot_price": pd.Series(dtype="float64"),
            "kind": pd.Series(dtype="object"),
            "confirmed_idx": pd.Series(dtype="int64"),
            "confirmed_ts": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )


def find_pivots(df: pd.DataFrame, theta: float = DEFAULT_THETA) -> pd.DataFrame:
    """Causal ZigZag pivot extraction over ``df["Close"]`` (see module docstring §1).

    Returns one row per **confirmed** pivot: ``pivot_idx``/``pivot_ts``/``pivot_price``
    (the extreme itself), ``kind`` (``"H"``/``"L"``), ``confirmed_idx``/``confirmed_ts``
    (the bar at which the reversal past ``theta`` made the extreme knowable). Empty input
    (0 or 1 rows) returns an empty frame. Raises ``ValueError`` on any NaN in ``Close``.
    """
    close = df["Close"]
    if close.isna().any():
        raise ValueError("Close contains NaN values")
    n = len(close)
    if n < 2:
        return _empty_pivots()

    prices = close.to_numpy(dtype=float)
    idx = close.index

    rows = []
    seed_price = prices[0]
    running_high = seed_price
    running_high_idx = 0
    running_low = seed_price
    running_low_idx = 0
    direction: Optional[str] = None  # None == UNKNOWN
    running_extreme = seed_price
    running_extreme_idx = 0

    def _emit(kind: str, extreme_price: float, extreme_idx: int, confirmed_i: int) -> None:
        rows.append(
            {
                "pivot_idx": extreme_idx,
                "pivot_ts": idx[extreme_idx],
                "pivot_price": extreme_price,
                "kind": kind,
                "confirmed_idx": confirmed_i,
                "confirmed_ts": idx[confirmed_i],
            }
        )

    for i in range(1, n):
        price = prices[i]
        if direction is None:
            if price > running_high:
                running_high, running_high_idx = price, i
            if price < running_low:
                running_low, running_low_idx = price, i
            if running_high > seed_price and price <= running_high * (1 - theta):
                _emit(HIGH, running_high, running_high_idx, i)
                direction, running_extreme, running_extreme_idx = "DOWN", price, i
            elif running_low < seed_price and price >= running_low * (1 + theta):
                _emit(LOW, running_low, running_low_idx, i)
                direction, running_extreme, running_extreme_idx = "UP", price, i
        elif direction == "UP":
            if price > running_extreme:
                running_extreme, running_extreme_idx = price, i
            elif price <= running_extreme * (1 - theta):
                _emit(HIGH, running_extreme, running_extreme_idx, i)
                direction, running_extreme, running_extreme_idx = "DOWN", price, i
        else:  # DOWN
            if price < running_extreme:
                running_extreme, running_extreme_idx = price, i
            elif price >= running_extreme * (1 + theta):
                _emit(LOW, running_extreme, running_extreme_idx, i)
                direction, running_extreme, running_extreme_idx = "UP", price, i

    if not rows:
        return _empty_pivots()
    out = pd.DataFrame(rows, columns=_PIVOT_COLUMNS)
    out["pivot_idx"] = out["pivot_idx"].astype("int64")
    out["confirmed_idx"] = out["confirmed_idx"].astype("int64")
    return out
