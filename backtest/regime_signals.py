"""Daily moving-average regime signals for the leveraged-regime study (#321).

Each function takes a daily close Series and returns a daily ``is_bullish_close_t``
Series (True / False / NaN), the same contract as ``backtest.baselines``: the raw
signal at close-T, before the T+1 execution shift that ``simulate_from_signal``
applies. Do NOT shift inside these functions.

These complement the two existing baseline trend signals reused by the study
(``baselines.tsmom_signal`` = 12-month TSMOM, ``baselines.faber_sma_signal`` =
10-month SMA). The two NEW signals here are:

- ``sma_signal``           : close > N-day daily SMA. With ``window=200`` this is
                             the live bot's incumbent 200-DMA regime filter.
- ``confirmed_sma_signal`` : the same N-day SMA rule with a symmetric debounce —
                             the state flips only after ``confirm`` consecutive
                             closes on the new side, to cut single-day whipsaws.

Research-only. Lives in backtest/ and is never imported by supabase/functions/.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma_signal(closes: pd.Series, window: int = 200) -> pd.Series:
    """Bullish when close > the ``window``-day simple moving average (daily).

    With ``window=200`` this is the incumbent 200-DMA regime filter. NaN during
    the ``window``-day warm-up (no SMA yet). No shift (the caller applies it).
    """
    sma = closes.rolling(window).mean()
    return (closes > sma).where(sma.notna(), other=float("nan"))


def confirmed_sma_signal(
    closes: pd.Series, window: int = 200, confirm: int = 2
) -> pd.Series:
    """``window``-day SMA rule with a symmetric ``confirm``-day debounce.

    The raw rule is ``close > SMA``. The confirmed state flips to bullish only
    after ``confirm`` consecutive closes above the SMA, and to bearish only after
    ``confirm`` consecutive closes below it; a single-day breach does not flip it.
    NaN until the first confirmed run establishes a state (and during SMA warm-up).
    ``confirm=1`` reduces to ``sma_signal``. No shift (the caller applies it).
    """
    if confirm < 1:
        raise ValueError("confirm must be >= 1")
    sma = closes.rolling(window).mean()
    raw = (closes > sma).to_numpy()
    valid = sma.notna().to_numpy()

    out: list = []
    state = None       # confirmed regime: True / False / None (not yet established)
    run_val = None     # value of the current raw run
    run_len = 0        # length of the current raw run
    for i in range(len(closes)):
        if not valid[i]:
            out.append(float("nan"))
            continue
        v = bool(raw[i])
        if v == run_val:
            run_len += 1
        else:
            run_val = v
            run_len = 1
        if run_len >= confirm:
            state = v
        out.append(state if state is not None else float("nan"))
    return pd.Series(out, index=closes.index)
