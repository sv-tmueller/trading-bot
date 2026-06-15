"""Four baseline strategies for walk-forward OOS comparison.

Each function takes a daily close Series (benchmark closes, same as the
regime rule's input) and returns a daily is_bullish_close_t Series — the
raw signal at close-T, before the T+1 execution shift.

The caller (walkforward.py) passes this signal to simulate_from_signal,
which applies the shift internally. Do NOT shift inside these functions.

Strategies
----------
- buy_and_hold_signal:    Always True. Fee-adjusted B&H; flip count 0.
- persistence_signal:     Lag-1 sign of daily return (close[T] > close[T-1]).
                          Source: "time-series momentum in individual stocks",
                          see Moskowitz, Ooi & Pedersen (2012) for the genre.
                          Here simplified to sign of yesterday's 1-day return.
- faber_sma_signal:       10-month SMA on monthly close (Faber, 2007).
                          Monthly signal → forward-filled to daily so the
                          signal only transitions at month-end boundaries.
- tsmom_signal:           12-month trailing return > 0 (TSMOM, Moskowitz et al.).
                          Computed on monthly close, forward-filled to daily.
                          NaN during the 12-month warm-up → flat.

All four are parameter-free — the SMA length and lookback are fixed by the
published rules (10-mo Faber, 12-mo TSMOM). This is a stability analysis of
fixed rules, NOT an optimisation.
"""
from __future__ import annotations

import pandas as pd


def buy_and_hold_signal(closes: pd.Series) -> pd.Series:
    """Always-True signal. Equivalent to fee-adjusted buy-and-hold when passed
    to simulate_from_signal (shift inside core means day 0 is flat, then long
    from day 1 through end-of-window).

    Parameters
    ----------
    closes:
        Daily close price Series (any index).

    Returns
    -------
    Boolean Series, same index as closes, all True.
    """
    return pd.Series(True, index=closes.index)


def persistence_signal(closes: pd.Series) -> pd.Series:
    """Lag-1 sign signal: bullish if today's close is higher than yesterday's
    (i.e. today's 1-day return > 0).

    This is the is_bullish_close_t signal — the T+1 execution shift is applied
    by the caller (simulate_from_signal). The first day is NaN (no prior close).

    Parameters
    ----------
    closes:
        Daily close price Series.

    Returns
    -------
    Boolean (or NaN) Series: True where close[T] > close[T-1]; NaN on day 0.
    """
    prior_return = closes.pct_change()  # return at close T vs close T-1
    # Signal at close-T = sign of the return that just completed at close-T
    # (i.e. today's return: close[T] > close[T-1])
    bullish = prior_return > 0
    # First row is NaN from pct_change; propagate NaN correctly
    result = bullish.where(~prior_return.isna(), other=float("nan"))
    return result


def faber_sma_signal(closes: pd.Series) -> pd.Series:
    """Faber (2007) 10-month SMA rule: bullish when month-end close > 10-mo SMA.

    Algorithm:
    1. Resample daily closes to month-end close.
    2. Compute 10-period rolling SMA on the monthly series.
    3. Signal = monthly_close > monthly_SMA (NaN during first 10 months).
    4. Forward-fill the monthly signal to daily frequency so the signal only
       transitions at month-end boundaries (Trap B compliance).

    The returned Series is at daily frequency, indexed like closes. The T+1
    execution shift is applied by the caller.

    Parameters
    ----------
    closes:
        Daily close price Series with a DatetimeIndex.

    Returns
    -------
    Boolean (or NaN) Series at daily frequency.
    """
    # Resample to month-end close (pandas 2.2.3: 'ME' not deprecated 'M')
    monthly_close = closes.resample("ME").last()
    monthly_sma = monthly_close.rolling(10).mean()
    monthly_signal = (monthly_close > monthly_sma).where(monthly_sma.notna(), other=float("nan"))

    # Reindex to daily: ffill so each day carries the prior month-end signal
    # This ensures transitions happen only at month boundaries (Trap B)
    daily_signal = monthly_signal.reindex(closes.index, method="ffill")
    return daily_signal


def tsmom_signal(closes: pd.Series) -> pd.Series:
    """12-month time-series momentum: bullish when trailing 12-mo return > 0.

    Based on Moskowitz, Ooi & Pedersen (2012). Simplified to a binary rule on
    the benchmark: if close[month_end_T] / close[month_end_{T-12}] > 1 → True.

    Algorithm:
    1. Resample daily closes to month-end close.
    2. Compute 12-period pct_change on the monthly series.
    3. Signal = monthly_trailing_return > 0 (NaN during first 12 months).
    4. Forward-fill to daily frequency (Trap B compliance).

    Parameters
    ----------
    closes:
        Daily close price Series with a DatetimeIndex.

    Returns
    -------
    Boolean (or NaN) Series at daily frequency.
    """
    monthly_close = closes.resample("ME").last()
    # 12-period pct_change gives the trailing 12-month return
    trailing_12mo = monthly_close.pct_change(12)
    monthly_signal = (trailing_12mo > 0).where(trailing_12mo.notna(), other=float("nan"))

    daily_signal = monthly_signal.reindex(closes.index, method="ffill")
    return daily_signal
