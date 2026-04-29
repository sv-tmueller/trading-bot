"""Earnings calendar helpers backed by yfinance, with caching and fail-open semantics."""

from __future__ import annotations

import functools
from datetime import date, datetime
from typing import Optional

import yfinance as yf


@functools.lru_cache(maxsize=512)
def _fetch_earnings_dates(ticker: str) -> tuple:
    """Return a tuple of ``date`` objects from yfinance, sorted ascending. Empty tuple on any failure."""
    try:
        tk = yf.Ticker(ticker)
        df = tk.earnings_dates
        if df is None:
            return ()
        idx = getattr(df, "index", None)
        if idx is None or len(idx) == 0:
            return ()
        out: list[date] = []
        for ts in df.index:
            try:
                if hasattr(ts, "to_pydatetime"):
                    dt = ts.to_pydatetime()
                elif isinstance(ts, datetime):
                    dt = ts
                else:
                    continue
                out.append(dt.date())
            except Exception:
                continue
        return tuple(sorted(set(out)))
    except Exception:
        return ()


def get_next_earnings_date(ticker: str, today: Optional[date] = None) -> Optional[date]:
    """Return the next future earnings date for ``ticker``, or ``None`` if unknown."""
    today = today or date.today()
    dates = _fetch_earnings_dates(ticker)
    future = [d for d in dates if d >= today]
    return future[0] if future else None


def get_last_earnings_date(ticker: str, today: Optional[date] = None) -> Optional[date]:
    """Return the most recent past earnings date for ``ticker``, or ``None`` if unknown."""
    today = today or date.today()
    dates = _fetch_earnings_dates(ticker)
    past = [d for d in dates if d < today]
    return past[-1] if past else None


def is_in_blackout_window(ticker: str, today: date, blackout_days: int) -> bool:
    """Return True if ``ticker`` has any earnings date within ``blackout_days`` of ``today``."""
    if blackout_days <= 0:
        return False
    nxt = get_next_earnings_date(ticker, today=today)
    if nxt is not None and 0 <= (nxt - today).days <= blackout_days:
        return True
    last = get_last_earnings_date(ticker, today=today)
    if last is not None and 0 <= (today - last).days <= blackout_days:
        return True
    return False


def clear_cache() -> None:
    """Drop the lru_cache — used in tests."""
    _fetch_earnings_dates.cache_clear()
