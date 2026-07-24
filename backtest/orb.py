"""Opening-Range Breakout (ORB) signal geometry — long AND short (#434).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls, no network — this module is **pure geometry**: given an intraday
OHLC frame it returns the entry trigger plus the ABSOLUTE stop/target levels that
``bracket.simulate_bracket`` consumes. Simulation, costs and data access live elsewhere
(``bracket.py`` and the runner respectively).

Why this module exists. ``run_orb_probe.py`` (#431) inlined a *long-only, 1-bar-OR,
OR-low-stop* variant with no way to vary any of it. Zarattini & Aziz (2023) — the one
intraday candidate with a published positive result — trade **long and short**, and the
opening-range length is the obvious first robustness axis. Generalising the geometry here
(and shorts in ``bracket.py``) is what lets that setup actually be replicated instead of
approximated. The #431 defaults are preserved exactly, so the frozen probe is reproducible:
``or_bars=1``, ``direction="long"``, ``stop_mode="or_opposite"``.

Frozen rules (mirrored per direction, no look-ahead anywhere):
  - **Opening range (OR)** = the first ``or_bars`` bars of each session; its High is the
    running max and its Low the running min over exactly those bars. On 5-minute bars
    ``or_bars=1`` is the paper's 5-minute OR; 3 is a 15-minute OR; 6 a 30-minute OR.
  - **Entry (long)** = the first later bar of the SAME session whose **Close breaks above
    the OR high**; enter at the **next bar's open** (close-t -> open-t+1 shift).
    **Short** mirrors it: the first Close **below the OR low**.
  - **One entry per session per direction**, never on an OR bar, never across a session
    boundary. The two directions are independent arms (the engine is single-lot per call).
  - **Stop** = the opposite side of the OR (long: OR low; short: OR high), or ``k*ATR``
    from the entry reference when ``stop_mode="atr"``.
  - **Target** = ``R`` multiples of the per-share risk, or ``None`` for exit-at-close.
    Long: ``entry + R*(entry - stop)``. Short: ``entry - R*(stop - entry)``.

The entry reference used for the geometry is the entry bar's own Open adjusted for
slippage — the price the engine will actually fill at. Reading it at the entry bar is not
look-ahead: the trigger was already decided by the PREVIOUS bar's close.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from backtest.bracket import LONG, SHORT, DIRECTIONS
from backtest.regime import SLIPPAGE_BPS

# #431's frozen defaults, preserved so that probe stays reproducible.
DEFAULT_OR_BARS = 1
STOP_OR_OPPOSITE = "or_opposite"
STOP_ATR = "atr"
STOP_MODES = (STOP_OR_OPPOSITE, STOP_ATR)


def session_ids(index: pd.DatetimeIndex) -> pd.Series:
    """Session label per bar: the normalized calendar date.

    A US regular session lives inside one UTC date (open 13:30/14:30 -> close 20:00/21:00
    UTC), so the normalized timestamp IS the session key — the same convention
    ``bracket._session_end_flags`` uses for its EOD close-out.
    """
    return pd.Series(index.normalize(), index=index)


def opening_range(
    df: pd.DataFrame, or_bars: int = DEFAULT_OR_BARS
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Per-session opening range, broadcast to every bar of its session.

    Returns ``(or_high, or_low, is_or_bar, sess)``. ``or_high``/``or_low`` are the max
    High / min Low over the session's first ``or_bars`` bars. ``is_or_bar`` marks those
    bars — entries are forbidden on them, which is also what makes the broadcast safe:
    a bar that may trade is always strictly after the whole OR window, so no future
    information reaches a tradeable decision.
    """
    if or_bars < 1:
        raise ValueError(f"or_bars must be >= 1, got {or_bars}")
    sess = session_ids(df.index)
    is_or_bar = df.groupby(sess).cumcount() < or_bars
    or_high = df["High"].where(is_or_bar).groupby(sess).transform("max")
    or_low = df["Low"].where(is_or_bar).groupby(sess).transform("min")
    return or_high, or_low, is_or_bar, sess


def entry_trigger(
    df: pd.DataFrame,
    or_bars: int = DEFAULT_OR_BARS,
    direction: str = LONG,
) -> pd.Series:
    """ORB entry trigger aligned to ``df.index`` (True = enter at THIS bar's open).

    The break is detected on a bar's CLOSE and filled at the NEXT bar's open, so the
    signal is shifted by one bar. Only the session's FIRST break trades; a trigger that
    would land on an OR bar (i.e. the break was the session's last bar) is dropped, which
    also prevents an entry leaking across a session boundary.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    or_high, or_low, is_or_bar, sess = opening_range(df, or_bars)
    if direction == SHORT:
        breaks = (df["Close"] < or_low) & (~is_or_bar)
    else:
        breaks = (df["Close"] > or_high) & (~is_or_bar)
    first_break = breaks & (breaks.groupby(sess).cumsum() == 1)
    return first_break.shift(1, fill_value=False) & (~is_or_bar)


def orb_levels(
    df: pd.DataFrame,
    trigger: pd.Series,
    or_high: pd.Series,
    or_low: pd.Series,
    r: Optional[float],
    *,
    direction: str = LONG,
    stop_mode: str = STOP_OR_OPPOSITE,
    atr: Optional[pd.Series] = None,
    atr_k: float = 1.0,
    slippage_bps: int = SLIPPAGE_BPS,
) -> Tuple[pd.Series, Optional[pd.Series]]:
    """Absolute stop and target levels for each ORB entry, per direction.

    ``entry_ref`` is the entry bar's Open moved by slippage in the direction the engine
    will actually fill (a long pays up, a short receives less), so the R-multiple geometry
    is measured against the realistic fill rather than the raw Open. The OR levels read at
    the entry bar belong to that bar's own session (guaranteed by ``entry_trigger``).
    Levels are meaningful only where ``trigger`` is True; elsewhere they are NaN, which the
    engine treats as "no entry".
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    if stop_mode not in STOP_MODES:
        raise ValueError(f"stop_mode must be one of {STOP_MODES}, got {stop_mode!r}")
    if stop_mode == STOP_ATR and atr is None:
        raise ValueError('stop_mode="atr" requires an atr Series')

    slip = slippage_bps / 10_000.0
    is_short = direction == SHORT
    entry_ref = df["Open"] * (1 - slip) if is_short else df["Open"] * (1 + slip)

    if stop_mode == STOP_ATR:
        offset = atr_k * atr
        raw_stop = entry_ref + offset if is_short else entry_ref - offset
    else:
        raw_stop = or_high if is_short else or_low

    stop = raw_stop.where(trigger)
    if r is None:
        return stop, None

    # Per-share risk is always a positive distance from the entry to the stop.
    risk = (raw_stop - entry_ref) if is_short else (entry_ref - raw_stop)
    raw_target = entry_ref - r * risk if is_short else entry_ref + r * risk
    return stop, raw_target.where(trigger)


def build_orb(
    df: pd.DataFrame,
    *,
    or_bars: int = DEFAULT_OR_BARS,
    direction: str = LONG,
    r: Optional[float] = None,
    stop_mode: str = STOP_OR_OPPOSITE,
    atr: Optional[pd.Series] = None,
    atr_k: float = 1.0,
    slippage_bps: int = SLIPPAGE_BPS,
) -> Tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """One-call convenience: ``(trigger, stop_prices, target_prices)`` for ``simulate_bracket``.

    The returned triple is exactly ``simulate_bracket``'s positional contract, so a cell is::

        trig, stop, target = build_orb(df, or_bars=1, direction="short", r=10.0)
        res = simulate_bracket(df, trig, stop, target,
                               session_close_out=True, eow_close_out=False,
                               direction="short")
    """
    or_high, or_low, _is_or_bar, _sess = opening_range(df, or_bars)
    trig = entry_trigger(df, or_bars, direction)
    stop, target = orb_levels(
        df, trig, or_high, or_low, r,
        direction=direction, stop_mode=stop_mode, atr=atr, atr_k=atr_k,
        slippage_bps=slippage_bps,
    )
    return trig, stop, target
