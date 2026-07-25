"""Classic candlestick PATTERN detectors — the untested signal shape (refs #422, #431).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls. Every function takes an already-fetched OHLC frame, so the
network lives in the runner and these unit tests stay offline.

Why this module exists
----------------------
Every entry family this repo has surveyed and killed was an **indicator** computed from
candles — MA-cross, Donchian breakout, ROC/TSMOM momentum, RSI, Bollinger
(`docs/research/2026-07-13-forex-4h-strategy-preregistration.md` §3) — plus the
opening-range breakout (#431). The classic candlestick *patterns* themselves appear in
this repo only as a keyword list (`docs/research/swing-trading/keywords.md` §"Candlestick
Patterns"): never implemented, never backtested.

They are a different functional form from the killed families: **fixed 1-to-3-bar OHLC
geometry** (body/wick proportions and bar-to-bar containment) rather than a rolling-window
aggregate. That is what makes them untested rather than a re-run.

Cadence is load-bearing — read before using this on intraday bars
-----------------------------------------------------------------
#422's NO-GO (`docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md`) closed
the **short-horizon** entry class on two walls that do not care which signal fires:
a cost wall (re-derived 72-128%/yr drag at 1-minute) and data scarcity (no free intraday
history reaches the n_w=13 power bar). A candlestick pattern evaluated every minute hits
both walls exactly as an RSI would.

On **daily** bars neither wall binds: a pattern fires on the order of 10-30 bars a year
rather than 250+, and daily SPY history reaches 1993 (34 non-overlapping 12-month windows
in the #430 Turtle daily arm), which is the one basis #422 §3 says "only *daily* clears."
So the intended use of this module is the **daily** arm. Nothing here prevents an intraday
call, and the detectors are cadence-agnostic by construction, but an intraday grid must
carry #422's cost and power caveats explicitly and is not gate-eligible on free data.

No-look-ahead contract
----------------------
A detector's value at bar ``t`` is a function of bars ``t``, ``t-1``, ``t-2`` **only** —
never ``t+1``. Detection happens on bar ``t``'s close; the caller applies the
close-t -> open-t+1 shift (``signal.shift(1)``) before handing the trigger to
``backtest.bracket.simulate_bracket``, exactly as ``orb.py`` and the Donchian signal do.
Warm-up rows (no ``t-1`` / ``t-2``) are False, never NaN.

Degenerate bars
---------------
A zero-range bar (``high == low``, a limit/halt print) makes every ratio undefined. Such
bars return False for every pattern rather than raising or silently comparing against a
NaN — a halted bar is not a setup.
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

import numpy as np
import pandas as pd

# --- Direction labels (mirror backtest.bracket's, imported there for the engine) -------
BULLISH = "long"
BEARISH = "short"
NEUTRAL = "neutral"   # direction comes from a breakout, not the pattern itself

# --- Frozen default thresholds -------------------------------------------------------
# Published/conventional values, chosen BEFORE any result was seen and recorded here so
# the pre-registration can freeze them by reference. No in-sample tuning.
DOJI_BODY_MAX = 0.10        # body <= 10% of range -> indecision bar
HAMMER_WICK_MIN = 2.0       # lower wick >= 2x body (the conventional hammer proportion)
HAMMER_OPP_WICK_MAX = 0.10  # opposing wick <= 10% of range (body sits at the far end)
PIN_WICK_MIN = 0.66         # dominant wick >= 2/3 of the whole range
MARUBOZU_BODY_MIN = 0.90    # body >= 90% of range -> effectively wickless
STAR_BODY_MAX = 0.30        # middle bar of a star: body <= 30% of its range


def _parts(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Decompose an OHLC frame into the body/wick primitives every detector uses.

    Returns Series aligned to ``df.index``: ``body`` (absolute), ``upper``/``lower`` wick,
    ``rng`` (high-low), ``bull``/``bear`` (strict), and ``valid`` (``rng > 0``).
    """
    o = df["Open"].astype(float)
    h = df["High"].astype(float)
    low = df["Low"].astype(float)
    c = df["Close"].astype(float)
    top = pd.concat([o, c], axis=1).max(axis=1)
    bottom = pd.concat([o, c], axis=1).min(axis=1)
    return {
        "open": o, "high": h, "low": low, "close": c,
        "body": (c - o).abs(),
        "upper": h - top,
        "lower": bottom - low,
        "rng": h - low,
        "bull": c > o,
        "bear": c < o,
        "valid": (h - low) > 0,
    }


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    """``num/den`` with zero-denominator rows returning NaN instead of raising/inf."""
    den_safe = den.where(den > 0, np.nan)
    return num / den_safe


def _clean(mask: pd.Series, index: pd.Index) -> pd.Series:
    """Normalize a detector mask: NaN -> False, dtype bool, reindexed to ``index``."""
    return mask.reindex(index).fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# One-bar patterns
# ---------------------------------------------------------------------------

def doji(df: pd.DataFrame, body_max: float = DOJI_BODY_MAX) -> pd.Series:
    """Indecision bar: body is at most ``body_max`` of the bar's range. NEUTRAL."""
    p = _parts(df)
    return _clean(_safe_ratio(p["body"], p["rng"]) <= body_max, df.index)


def hammer(
    df: pd.DataFrame,
    wick_min: float = HAMMER_WICK_MIN,
    opp_wick_max: float = HAMMER_OPP_WICK_MAX,
) -> pd.Series:
    """Bullish single-bar reversal: long LOWER wick, small body parked at the top.

    ``lower >= wick_min * body`` and ``upper <= opp_wick_max * range``. A zero-body bar
    with a long lower wick qualifies (the ratio test is written as a product so a zero
    body does not divide).
    """
    p = _parts(df)
    long_lower = p["lower"] >= wick_min * p["body"]
    small_upper = _safe_ratio(p["upper"], p["rng"]) <= opp_wick_max
    return _clean(p["valid"] & long_lower & small_upper & (p["lower"] > 0), df.index)


def shooting_star(
    df: pd.DataFrame,
    wick_min: float = HAMMER_WICK_MIN,
    opp_wick_max: float = HAMMER_OPP_WICK_MAX,
) -> pd.Series:
    """Bearish single-bar reversal: the exact mirror of ``hammer`` (long UPPER wick)."""
    p = _parts(df)
    long_upper = p["upper"] >= wick_min * p["body"]
    small_lower = _safe_ratio(p["lower"], p["rng"]) <= opp_wick_max
    return _clean(p["valid"] & long_upper & small_lower & (p["upper"] > 0), df.index)


def bullish_pin_bar(df: pd.DataFrame, wick_min: float = PIN_WICK_MIN) -> pd.Series:
    """Lower wick alone is at least ``wick_min`` of the whole range (rejection of lows)."""
    p = _parts(df)
    return _clean(p["valid"] & (_safe_ratio(p["lower"], p["rng"]) >= wick_min), df.index)


def bearish_pin_bar(df: pd.DataFrame, wick_min: float = PIN_WICK_MIN) -> pd.Series:
    """Upper wick alone is at least ``wick_min`` of the whole range (rejection of highs)."""
    p = _parts(df)
    return _clean(p["valid"] & (_safe_ratio(p["upper"], p["rng"]) >= wick_min), df.index)


def bullish_marubozu(
    df: pd.DataFrame, body_min: float = MARUBOZU_BODY_MIN
) -> pd.Series:
    """Effectively wickless up bar: bullish and ``body >= body_min * range``."""
    p = _parts(df)
    big = _safe_ratio(p["body"], p["rng"]) >= body_min
    return _clean(p["valid"] & p["bull"] & big, df.index)


def bearish_marubozu(
    df: pd.DataFrame, body_min: float = MARUBOZU_BODY_MIN
) -> pd.Series:
    """Effectively wickless down bar: bearish and ``body >= body_min * range``."""
    p = _parts(df)
    big = _safe_ratio(p["body"], p["rng"]) >= body_min
    return _clean(p["valid"] & p["bear"] & big, df.index)


# ---------------------------------------------------------------------------
# Two-bar patterns
# ---------------------------------------------------------------------------

def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Prior bar bearish, current bar bullish and its body strictly engulfs the prior's.

    ``open_t < close_{t-1}`` and ``close_t > open_{t-1}``.
    """
    p = _parts(df)
    prev_bear = p["bear"].shift(1)
    engulf = (p["open"] < p["close"].shift(1)) & (p["close"] > p["open"].shift(1))
    return _clean(prev_bear.astype("boolean") & p["bull"] & engulf, df.index)


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Prior bar bullish, current bar bearish and its body strictly engulfs the prior's."""
    p = _parts(df)
    prev_bull = p["bull"].shift(1)
    engulf = (p["open"] > p["close"].shift(1)) & (p["close"] < p["open"].shift(1))
    return _clean(prev_bull.astype("boolean") & p["bear"] & engulf, df.index)


def bullish_harami(df: pd.DataFrame) -> pd.Series:
    """Inverse of engulfing: prior bar bearish, current bullish body INSIDE the prior's."""
    p = _parts(df)
    prev_bear = p["bear"].shift(1)
    inside = (p["open"] > p["close"].shift(1)) & (p["close"] < p["open"].shift(1))
    return _clean(prev_bear.astype("boolean") & p["bull"] & inside, df.index)


def bearish_harami(df: pd.DataFrame) -> pd.Series:
    """Prior bar bullish, current bearish body INSIDE the prior's."""
    p = _parts(df)
    prev_bull = p["bull"].shift(1)
    inside = (p["open"] < p["close"].shift(1)) & (p["close"] > p["open"].shift(1))
    return _clean(prev_bull.astype("boolean") & p["bear"] & inside, df.index)


def inside_bar(df: pd.DataFrame) -> pd.Series:
    """Current bar's whole RANGE is contained by the prior bar's. NEUTRAL (compression).

    ``high_t <= high_{t-1}`` and ``low_t >= low_{t-1}``. Direction is not implied by the
    pattern — the caller supplies it (a long arm buys the break of the mother bar's high,
    a short arm sells the break of its low), which is why this is registered NEUTRAL.

    Unlike the ratio-based detectors, containment is well-defined on a zero-range bar — a
    halted print is trivially "inside" anything. The ``valid`` guard is applied anyway so
    the module-wide contract ("a degenerate bar is never a setup") holds without exception:
    a zero-range bar is an absence of trading, not a compression setup, and admitting it
    would manufacture entries out of a data artifact.
    """
    p = _parts(df)
    contained = (p["high"] <= p["high"].shift(1)) & (p["low"] >= p["low"].shift(1))
    return _clean(p["valid"] & contained, df.index)


# ---------------------------------------------------------------------------
# Three-bar patterns
# ---------------------------------------------------------------------------

def morning_star(df: pd.DataFrame, star_body_max: float = STAR_BODY_MAX) -> pd.Series:
    """Bullish 3-bar reversal: big down bar, small-bodied star, big up bar recovering.

    Bar ``t-2`` bearish; bar ``t-1`` a small body (``<= star_body_max`` of its own range)
    whose body sits BELOW bar ``t-2``'s body midpoint; bar ``t`` bullish and closing above
    bar ``t-2``'s body midpoint. Gaps are not required (index futures/ETFs rarely gap the
    way the pattern's stock-era description assumes) — the midpoint tests carry it.
    """
    p = _parts(df)
    mid2 = (p["open"].shift(2) + p["close"].shift(2)) / 2.0
    star_top = pd.concat([p["open"].shift(1), p["close"].shift(1)], axis=1).max(axis=1)
    small_star = _safe_ratio(p["body"].shift(1), p["rng"].shift(1)) <= star_body_max
    cond = (
        p["bear"].shift(2).astype("boolean")
        & small_star
        & (star_top < mid2)
        & p["bull"]
        & (p["close"] > mid2)
    )
    return _clean(cond, df.index)


def evening_star(df: pd.DataFrame, star_body_max: float = STAR_BODY_MAX) -> pd.Series:
    """Bearish 3-bar reversal: the exact mirror of ``morning_star``."""
    p = _parts(df)
    mid2 = (p["open"].shift(2) + p["close"].shift(2)) / 2.0
    star_bottom = pd.concat([p["open"].shift(1), p["close"].shift(1)], axis=1).min(axis=1)
    small_star = _safe_ratio(p["body"].shift(1), p["rng"].shift(1)) <= star_body_max
    cond = (
        p["bull"].shift(2).astype("boolean")
        & small_star
        & (star_bottom > mid2)
        & p["bear"]
        & (p["close"] < mid2)
    )
    return _clean(cond, df.index)


# ---------------------------------------------------------------------------
# Registry — the frozen candidate set the pre-registration counts for multiplicity
# ---------------------------------------------------------------------------

#: name -> (detector, direction). NEUTRAL entries need a breakout side from the caller.
#: The runner iterates this dict, so its length IS the pattern-arm trial count that the
#: #398 deflated-Sharpe multiplicity correction consumes. Adding a pattern changes that
#: count — do not extend this registry after a grid is frozen.
PATTERNS: Dict[str, Tuple[Callable[[pd.DataFrame], pd.Series], str]] = {
    "bullish_engulfing": (bullish_engulfing, BULLISH),
    "bearish_engulfing": (bearish_engulfing, BEARISH),
    "hammer": (hammer, BULLISH),
    "shooting_star": (shooting_star, BEARISH),
    "bullish_pin_bar": (bullish_pin_bar, BULLISH),
    "bearish_pin_bar": (bearish_pin_bar, BEARISH),
    "bullish_marubozu": (bullish_marubozu, BULLISH),
    "bearish_marubozu": (bearish_marubozu, BEARISH),
    "bullish_harami": (bullish_harami, BULLISH),
    "bearish_harami": (bearish_harami, BEARISH),
    "morning_star": (morning_star, BULLISH),
    "evening_star": (evening_star, BEARISH),
    "doji": (doji, NEUTRAL),
    "inside_bar": (inside_bar, NEUTRAL),
}


def detect(name: str, df: pd.DataFrame, **kwargs) -> pd.Series:
    """Run one registered detector by name. Raises ``KeyError`` on an unknown name."""
    if name not in PATTERNS:
        raise KeyError(
            f"unknown pattern {name!r}; registered: {sorted(PATTERNS)}"
        )
    return PATTERNS[name][0](df, **kwargs)


def direction_of(name: str) -> str:
    """Direction a registered pattern trades (``BULLISH``/``BEARISH``/``NEUTRAL``)."""
    if name not in PATTERNS:
        raise KeyError(
            f"unknown pattern {name!r}; registered: {sorted(PATTERNS)}"
        )
    return PATTERNS[name][1]
