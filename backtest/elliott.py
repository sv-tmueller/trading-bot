"""Deterministic Elliott Wave labeler (#468) — no LLM anywhere in this module.

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no trading/order-placement calls, no network, no I/O. Pure ``pandas``/``numpy`` arithmetic only
(no ``scipy`` — ``argrelextrema`` and friends are both unavailable in this repo's
research venv and lookahead-prone by construction: they scan the whole array).

This module reverses a recorded ``skip`` verdict against a specific, cited object:
``docs/research/swing-trading/roadmap.md:585`` and ``strategies.md:415`` record Elliott
Wave as ``skip`` because wave-counting is "non-deterministic by construction" — but that
verdict was against an **LLM-authored** count. ``strategies.md:378`` (on §15 Voigt-
Markttechnik, a related mechanizable pattern, not Elliott Wave itself) itself asks for the
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

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

# --- §1 pivot kinds -------------------------------------------------------
HIGH = "H"
LOW = "L"

# theta grid, mirroring fx_signals.R_GRID / run_fx_plumbing_check.R_PCT exactly (#468 §3.1).
DEFAULT_THETA = 0.0030
THETA_GRID = (0.0020, 0.0030, 0.0050)

# --- §2 Fibonacci constant table -------------------------------------------------------
# Anti-tuning device (SUB_PLAN §3.2): every band endpoint below is a FIB[...] lookup, so
# a reviewer can see at a glance that no endpoint is a hand-fitted number.
FIB: Dict[str, float] = {
    "0.146": 0.146, "0.236": 0.236, "0.382": 0.382, "0.500": 0.500,
    "0.618": 0.618, "0.786": 0.786, "0.886": 0.886, "1.000": 1.000,
    "1.272": 1.272, "1.618": 1.618, "2.618": 2.618, "4.236": 4.236,
}

# Soft Fibonacci windows (frozen, inclusive) -- impulse.
F1_LOW, F1_HIGH = FIB["0.382"], FIB["0.886"]   # W2/W1
F2_LOW, F2_HIGH = FIB["1.000"], FIB["4.236"]   # W3/W1
F3_LOW, F3_HIGH = FIB["0.146"], FIB["0.618"]   # W4/W3
F4_LOW, F4_HIGH = FIB["0.382"], FIB["2.618"]   # W5/W1

# Soft Fibonacci windows (frozen, inclusive) -- zigzag correction.
C2_LOW, C2_HIGH = FIB["0.382"], FIB["0.886"]   # WB/WA
C3_LOW, C3_HIGH = FIB["0.618"], FIB["1.618"]   # WC/WA

# Numerical tolerance for the (inclusive) band checks below. A ratio built by
# reconstructing prices from a target ratio (leg = ratio * other_leg, price = base +/-
# leg) accumulates a few ULPs of floating-point rounding by the time it is divided back
# out -- "exactly at the boundary" would otherwise flip to "one ULP outside" depending on
# the arithmetic path, which is not the frozen-band inclusive semantics the spec asks
# for. Tiny relative to any real rejection margin (the boundary tests below probe 0.1%
# outside the band, ~1e6x larger than this).
_BAND_EPS = 1e-9

# --- §4 signal mapping -----------------------------------------------------------------
FADE = "FADE"
FOLLOW = "FOLLOW"

_BULLISH_IMPULSE = ("L", "H", "L", "H", "L", "H")
_BEARISH_IMPULSE = ("H", "L", "H", "L", "H", "L")
_BULLISH_ZIGZAG = ("L", "H", "L", "H")
_BEARISH_ZIGZAG = ("H", "L", "H", "L")

_LABEL_COLUMNS = [
    "kind", "direction", "start_idx", "end_idx", "signal_ts",
    "w2_w1", "w3_w1", "w4_w3", "w5_w1", "wb_wa", "wc_wa",
]

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


# ---------------------------------------------------------------------------
# §2 Wave grammar — hard rules (binary, non-negotiable) + frozen Fibonacci bands.
#
# Cite in comments: R. N. Elliott, *The Wave Principle* (1938); Frost & Prechter,
# *Elliott Wave Principle* (1978) -- the canonical statement of the three impulse rules.
# ---------------------------------------------------------------------------

def _check_impulse(prices: Tuple[float, ...], bullish: bool) -> Tuple[bool, Optional[dict]]:
    """Impulse P0..P5 (6 pivots), hard rules R1-R3 then soft Fibonacci bands F1-F4.
    Returns ``(ok, ratios_or_None)``. ``ratios`` is always returned when ``ok`` is True."""
    p0, p1, p2, p3, p4, p5 = prices
    w1 = abs(p1 - p0)
    w2 = abs(p2 - p1)
    w3 = abs(p3 - p2)
    w4 = abs(p4 - p3)
    w5 = abs(p5 - p4)
    if w1 == 0 or w3 == 0:
        return False, None

    # R1: wave 2 never retraces more than 100% of wave 1 (strict; tie rejects).
    if bullish:
        if not (p2 > p0):
            return False, None
    else:
        if not (p2 < p0):
            return False, None

    # R2: wave 3 is never the shortest of {1, 3, 5}.
    if not (w3 >= w1 or w3 >= w5):
        return False, None

    # R3: wave 4 never enters wave 1's price territory (non-diagonal only; strict).
    if bullish:
        if not (p4 > p1):
            return False, None
    else:
        if not (p4 < p1):
            return False, None

    # Soft Fibonacci windows (frozen tolerance bands, inclusive).
    r_w2w1 = w2 / w1
    r_w3w1 = w3 / w1
    r_w4w3 = w4 / w3
    r_w5w1 = w5 / w1
    if not (F1_LOW - _BAND_EPS <= r_w2w1 <= F1_HIGH + _BAND_EPS):
        return False, None
    if not (F2_LOW - _BAND_EPS <= r_w3w1 <= F2_HIGH + _BAND_EPS):
        return False, None
    if not (F3_LOW - _BAND_EPS <= r_w4w3 <= F3_HIGH + _BAND_EPS):
        return False, None
    if not (F4_LOW - _BAND_EPS <= r_w5w1 <= F4_HIGH + _BAND_EPS):
        return False, None

    return True, {"w2_w1": r_w2w1, "w3_w1": r_w3w1, "w4_w3": r_w4w3, "w5_w1": r_w5w1}


def _check_zigzag(prices: Tuple[float, ...], bullish: bool) -> Tuple[bool, Optional[dict]]:
    """Zigzag correction Q0..Q3 (4 pivots), hard rule C1 then soft bands C2-C3."""
    q0, q1, q2, q3 = prices
    wa = abs(q1 - q0)
    wb = abs(q2 - q1)
    wc = abs(q3 - q2)
    if wa == 0:
        return False, None

    # C1: B never retraces more than 100% of A (strict).
    if bullish:
        if not (q2 > q0):
            return False, None
    else:
        if not (q2 < q0):
            return False, None

    r_wbwa = wb / wa
    r_wcwa = wc / wa
    if not (C2_LOW - _BAND_EPS <= r_wbwa <= C2_HIGH + _BAND_EPS):
        return False, None
    if not (C3_LOW - _BAND_EPS <= r_wcwa <= C3_HIGH + _BAND_EPS):
        return False, None

    return True, {"wb_wa": r_wbwa, "wc_wa": r_wcwa}


def _empty_labels() -> pd.DataFrame:
    cols = {c: pd.Series(dtype="float64") for c in _LABEL_COLUMNS}
    cols["kind"] = pd.Series(dtype="object")
    cols["direction"] = pd.Series(dtype="object")
    cols["start_idx"] = pd.Series(dtype="int64")
    cols["end_idx"] = pd.Series(dtype="int64")
    cols["signal_ts"] = pd.Series(dtype="datetime64[ns, UTC]")
    return pd.DataFrame(cols, columns=_LABEL_COLUMNS)


def label_waves(df: pd.DataFrame, theta: float = DEFAULT_THETA) -> pd.DataFrame:
    """Deterministic wave labeler (§2-§3): pivots -> grammar -> total-order matcher.

    Scans confirmed pivots (``find_pivots``) left to right with NO backtracking and NO
    scoring: at each starting position ``i``, an impulse (``i..i+5``) is attempted before
    a zigzag correction (``i..i+3``) -- a frozen tie-break (a 6-pivot impulse window
    contains 4-pivot correction sub-windows, so without a priority the count would be
    ambiguous). The first match wins, is emitted, and the scan resumes at the structure's
    **last pivot** (doctrinally correct -- a correction begins where an impulse ended). No
    match advances ``i`` by 1. No scoring, no "best count", no re-labelling of an
    already-emitted structure. Ever.

    **Halting rule -- the load-bearing no-lookahead guarantee at the structure level.**
    A position ``i`` is only ever resolved (impulse-vs-zigzag decided, or "no structure
    here, advance by 1") once its full 6-pivot impulse window is ITSELF fully confirmed
    (``i + 6 <= n``). If only the 4-pivot zigzag window is available (``i + 4 <= n <
    i + 6``), the scan **halts without emitting anything further** rather than committing
    to a zigzag that a not-yet-confirmed 5th/6th pivot could later turn into a
    higher-priority impulse claiming the SAME starting pivot -- exactly the repaint this
    module exists to rule out. (A verdict reached once ``i + 6 <= n`` is permanent: it is
    a pure function of 6 already-confirmed, immutable pivots, so more data arriving later
    can never change it -- only extend the scan further along.) This is what makes
    ``label_waves(series[:k])`` agree with ``label_waves(series)`` filtered to
    ``signal_ts <= series.index[k-1]`` for every ``k`` (the no-lookahead truncation
    property, pinned by a dedicated test) -- a stronger, structure-level version of the
    pivot-level ``confirmed_idx > pivot_idx`` guarantee.

    ``signal_ts`` (the emission time) is **decision-knowable stamping**: the timestamp
    at which the emitted verdict was actually knowable, given every hypothesis this
    matcher inspected to reach it -- not merely the emitted structure's own last pivot.
    This matters for a **fall-through** structure specifically:

      - **Impulse accepted** -- the verdict is a pure function of the same 6 pivots
        whose confirmation was required to reach it; ``signal_ts = confirmed_ts[i+5]``
        already reflects the latest of those.
      - **Impulse rejected (pattern mismatch, a hard rule R1-R3, or a soft Fibonacci band
        F1-F4) then a zigzag matches** -- rejecting the impulse required inspecting
        ``kinds[i:i+6]`` / the 6-pivot price tuple, i.e. pivot ``i+5`` was ALREADY
        confirmed by the time that rejection became knowable, even though the emitted
        zigzag itself only spans pivots ``i..i+3``. Stamping ``confirmed_ts[i+3]`` alone
        would **backdate** the label to before the higher-priority hypothesis was
        actually resolved -- exactly the round-1 regression fixed here. The correct
        stamp is ``max(confirmed_ts[i+3], confirmed_ts[i+5])`` (the pivot indices are
        monotonically increasing in confirmation time, so this is always
        ``confirmed_ts[i+5]`` in practice, but the ``max`` is kept explicit as the
        general rule: "own last pivot" vs "the pivot that resolved the higher-priority
        hypothesis").
      - **Nothing matches at position i** -- no label is emitted, so no stamping
        question arises; ``i`` simply advances by 1.

    Explicit v1 non-goals (see module docstring): no nested/fractal counting, no
    diagonals, no flats/triangles, no alternation guideline, no multi-timeframe
    confluence, no wave-2 ("start of wave 3") entry signalling.
    """
    pivots = find_pivots(df, theta=theta)
    n = len(pivots)
    if n == 0:
        return _empty_labels()

    kinds = pivots["kind"].to_numpy()
    prices = pivots["pivot_price"].to_numpy(dtype=float)
    pivot_idx_arr = pivots["pivot_idx"].to_numpy()
    confirmed_ts_arr = pivots["confirmed_ts"].to_numpy()

    rows = []
    i = 0
    while i < n:
        if i + 6 > n:
            # Not yet knowable whether an impulse starting at i exists -- halt rather
            # than risk a zigzag a future pivot could invalidate (see docstring).
            break

        matched = False

        # Priority 1: impulse (6-pivot window) -- fully knowable at this point.
        window_kinds = tuple(kinds[i:i + 6])
        if window_kinds in (_BULLISH_IMPULSE, _BEARISH_IMPULSE):
            bullish = window_kinds == _BULLISH_IMPULSE
            ok, ratios = _check_impulse(tuple(prices[i:i + 6]), bullish)
            if ok:
                rows.append({
                    "kind": "impulse",
                    "direction": "up" if bullish else "down",
                    "start_idx": int(pivot_idx_arr[i]),
                    "end_idx": int(pivot_idx_arr[i + 5]),
                    "signal_ts": confirmed_ts_arr[i + 5],
                    "w2_w1": ratios["w2_w1"], "w3_w1": ratios["w3_w1"],
                    "w4_w3": ratios["w4_w3"], "w5_w1": ratios["w5_w1"],
                    "wb_wa": np.nan, "wc_wa": np.nan,
                })
                i += 5
                matched = True

        # Priority 2: zigzag correction (4-pivot window) -- the impulse window's own
        # first 4 pivots are already known NOT to complete an impulse at this point
        # (checked immediately above, over the same immutable 6 pivots), so this
        # decision is equally permanent. IMPORTANT: reaching this fall-through branch
        # at all required inspecting ``kinds[i:i+6]`` above (a 6-element window, whether
        # the impulse pattern mismatched, or a hard rule (R1-R3), or a soft Fibonacci
        # band (F1-F4) rejected it) -- i.e. pivot i+5 was ALREADY confirmed by the time
        # this rejection became knowable. A zigzag emitted here is therefore only
        # genuinely knowable at ``max(confirmed_ts[i+3], confirmed_ts[i+5])`` -- never at
        # its own last pivot's confirmed_ts alone, which would backdate the label to
        # before the higher-priority impulse hypothesis was actually resolved (round-1
        # regression: ``test_label_waves_r2_fallthrough_zigzag_signal_ts_backdated_regression``).
        if not matched:
            window_kinds4 = tuple(kinds[i:i + 4])
            if window_kinds4 in (_BULLISH_ZIGZAG, _BEARISH_ZIGZAG):
                bullish = window_kinds4 == _BULLISH_ZIGZAG
                ok, ratios = _check_zigzag(tuple(prices[i:i + 4]), bullish)
                if ok:
                    signal_ts = max(confirmed_ts_arr[i + 3], confirmed_ts_arr[i + 5])
                    rows.append({
                        "kind": "zigzag",
                        "direction": "up" if bullish else "down",
                        "start_idx": int(pivot_idx_arr[i]),
                        "end_idx": int(pivot_idx_arr[i + 3]),
                        "signal_ts": signal_ts,
                        "w2_w1": np.nan, "w3_w1": np.nan, "w4_w3": np.nan, "w5_w1": np.nan,
                        "wb_wa": ratios["wb_wa"], "wc_wa": ratios["wc_wa"],
                    })
                    i += 3
                    matched = True

        if not matched:
            i += 1

    if not rows:
        return _empty_labels()
    out = pd.DataFrame(rows, columns=_LABEL_COLUMNS)
    out["start_idx"] = out["start_idx"].astype("int64")
    out["end_idx"] = out["end_idx"].astype("int64")
    return out


# ---------------------------------------------------------------------------
# §4 Signal derivation — emit labels, let the study choose the mapping.
# ---------------------------------------------------------------------------

def structure_signal(labels: pd.DataFrame, index: pd.Index, mapping: str) -> pd.Series:
    """Map completed structures to a trade side under ``mapping in {FADE, FOLLOW}``.

    Doctrine (mirrored in the module docstring / feasibility note): take the position
    OPPOSITE the direction of the just-completed structure (``FADE``); ``FOLLOW`` is the
    contested reading, frozen as the second registered arm rather than argued away (the
    candlestick v2 precedent -- both arms frozen, not just the winning one).

    Contract, matching ``fx_signals.py`` exactly: ``int64`` dtype, values in
    ``{-1, 0, 1}``, index identical to ``index``, warm-up rows explicitly ``0`` (never
    NaN), ties -> ``0``. NOT pre-shifted -- ``fx_execution.simulate_fx`` does the T -> T+1
    fill shift itself.
    """
    if mapping not in (FADE, FOLLOW):
        raise ValueError(f"mapping must be {FADE!r} or {FOLLOW!r}, got {mapping!r}")

    sig = pd.Series(0, index=index, dtype="int64")
    if len(labels) == 0:
        return sig

    def _value(direction: str) -> int:
        base = 1 if direction == "up" else -1
        return -base if mapping == FADE else base

    counts: Dict[pd.Timestamp, int] = {}
    values: Dict[pd.Timestamp, int] = {}
    for _, row in labels.iterrows():
        ts = row["signal_ts"]
        v = _value(row["direction"])
        counts[ts] = counts.get(ts, 0) + 1
        values[ts] = v if ts not in values else (values[ts] if values[ts] == v else 0)

    for ts, v in values.items():
        if ts in index:
            sig.loc[ts] = v if counts[ts] == 1 else 0
    return sig
