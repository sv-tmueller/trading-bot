"""Intraday bar loading + power accounting for the ORB program (#434).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker *trading* calls — the only network any caller does is a read-only
historical-bars pull, and this module's primary path does no network at all.

Why a local-file path exists
----------------------------
#431's ORB probe came back **DATA-BLOCKED**: the Alpaca 2016+ read is key-gated and the
yfinance fallback reaches ~60 sessions. In this session it is worse — *every* market-data
host (Yahoo, Alpaca, Stooq, Nasdaq, Tiingo, AlphaVantage, Finnhub, Polygon, Databento) is
403-denied by the environment's egress policy, so no keyed fetch can succeed either.

A local file sidesteps that entirely: bars exported anywhere (a broker's own export, a
paid vendor, a workstation with open egress) can be dropped in and the harness runs with
no network whatsoever. That turns a blocked environment into a solvable one without
weakening any methodology.

The honesty rule this module enforces
-------------------------------------
``describe_power`` reports what a frame can and cannot support, and ``PowerReport.verdict``
is the single place that decides. A frame short of the floors is **UNDERPOWERED** and a
caller must not present its numbers as a read — that is exactly the "plumbing smoke"
distinction #431 had to draw by hand. Provenance is always reported alongside, so a result
can never silently look deeper than the data behind it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import pandas as pd

# Power floors, carried over from #431's frozen pre-registration.
PROMOTION_N_W = 13          # non-overlapping 12-month windows the #398 gate needs
PROBE_MIN_SESSIONS = 500    # directional-read floor; below this = DATA-BLOCKED
MIN_WINDOW_BARS = 80        # below this the frame is not a usable series at all

OHLC = ("Open", "High", "Low", "Close")

# Accepted spellings for each canonical column, lowercased for matching.
_COLUMN_ALIASES = {
    "Open": ("open", "o", "px_open", "opening"),
    "High": ("high", "h", "px_high"),
    "Low": ("low", "l", "px_low"),
    "Close": ("close", "c", "px_close", "closing", "last"),
}
_TIMESTAMP_ALIASES = (
    "timestamp", "time", "datetime", "date", "t", "ts", "bar_time", "index",
)


class DataQualityError(ValueError):
    """A loaded frame is not usable as an OHLC bar series."""


@dataclass(frozen=True)
class PowerReport:
    """What a bar frame can and cannot support statistically."""

    n_bars: int
    n_sessions: int
    first: Optional[pd.Timestamp]
    last: Optional[pd.Timestamp]
    n_windows: int              # complete non-overlapping 12-month windows
    verdict: str                # "PROMOTABLE" | "DIRECTIONAL" | "UNDERPOWERED"
    reason: str

    @property
    def is_readable(self) -> bool:
        """True when the frame clears at least the directional-read floor."""
        return self.verdict in ("PROMOTABLE", "DIRECTIONAL")

    def summary(self) -> str:
        span = (
            f"{self.first:%Y-%m-%d} -> {self.last:%Y-%m-%d}"
            if self.first is not None else "empty"
        )
        return (
            f"{self.verdict}: {self.n_bars} bars / {self.n_sessions} sessions / "
            f"n_w={self.n_windows} ({span}) — {self.reason}"
        )


def _canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename OHLC columns from any accepted spelling; raise if one is missing."""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for canon, aliases in _COLUMN_ALIASES.items():
        if canon in df.columns:
            continue
        for alias in (canon.lower(),) + aliases:
            if alias in lookup:
                rename[lookup[alias]] = canon
                break
    out = df.rename(columns=rename)
    missing = [c for c in OHLC if c not in out.columns]
    if missing:
        raise DataQualityError(
            f"missing OHLC column(s) {missing}; got columns {list(df.columns)}"
        )
    return out


def _index_from_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """Promote a timestamp column to a UTC DatetimeIndex if the index isn't one."""
    if isinstance(df.index, pd.DatetimeIndex):
        out = df
    else:
        lookup = {str(c).strip().lower(): c for c in df.columns}
        col = next((lookup[a] for a in _TIMESTAMP_ALIASES if a in lookup), None)
        if col is None:
            raise DataQualityError(
                "no DatetimeIndex and no recognisable timestamp column "
                f"(looked for {_TIMESTAMP_ALIASES}); got {list(df.columns)}"
            )
        out = df.set_index(pd.to_datetime(df[col], utc=True, errors="coerce"))
        out = out.drop(columns=[col])
    idx = pd.to_datetime(out.index, utc=True, errors="coerce")
    if idx.isna().any():
        raise DataQualityError("timestamp column contains unparseable values")
    out = out.copy()
    out.index = idx
    return out


def validate_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, de-duplicate and sanity-check an OHLC frame. Returns the cleaned frame.

    Rejects frames that cannot be simulated honestly: non-positive prices, NaNs, or bars
    whose High/Low do not bracket their own Open/Close (a sign of a mis-mapped column or a
    corrupt export — silently simulating those produces confident nonsense).
    """
    out = df[list(OHLC)].astype(float)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    if out.isna().any().any():
        raise DataQualityError("OHLC contains NaN values")
    if (out <= 0).any().any():
        raise DataQualityError("OHLC contains non-positive prices")
    hi, lo = out["High"], out["Low"]
    body_max = out[["Open", "Close"]].max(axis=1)
    body_min = out[["Open", "Close"]].min(axis=1)
    bad = (hi < lo) | (hi < body_max - 1e-9) | (lo > body_min + 1e-9)
    if bool(bad.any()):
        first_bad = out.index[bad][0]
        raise DataQualityError(
            f"{int(bad.sum())} bar(s) where High/Low do not bracket Open/Close "
            f"(first at {first_bad}) — check column mapping"
        )
    return out


def describe_power(df: pd.DataFrame) -> PowerReport:
    """Report how much statistical weight a frame can carry, and name the verdict."""
    n_bars = len(df)
    if n_bars == 0:
        return PowerReport(0, 0, None, None, 0, "UNDERPOWERED", "frame is empty")
    sessions = pd.Index(df.index).normalize().unique()
    n_sessions = len(sessions)
    first, last = df.index[0], df.index[-1]
    n_windows = int(((last - first).days) // 365)

    if n_bars < MIN_WINDOW_BARS:
        verdict, reason = "UNDERPOWERED", (
            f"{n_bars} bars < {MIN_WINDOW_BARS}-bar minimum; not a usable series"
        )
    elif n_sessions < PROBE_MIN_SESSIONS:
        verdict, reason = "UNDERPOWERED", (
            f"{n_sessions} sessions < the {PROBE_MIN_SESSIONS}-session directional floor; "
            "results are plumbing smoke, NOT a read"
        )
    elif n_windows < PROMOTION_N_W:
        verdict, reason = "DIRECTIONAL", (
            f"n_w={n_windows} < the n_w={PROMOTION_N_W} promotion bar; a directional read "
            "only, NOT gate-eligible"
        )
    else:
        verdict, reason = "PROMOTABLE", (
            f"n_w={n_windows} >= {PROMOTION_N_W} and {n_sessions} sessions; "
            "clears the pre-registered power floors"
        )
    return PowerReport(n_bars, n_sessions, first, last, n_windows, verdict, reason)


def load_local(path: "str | os.PathLike") -> pd.DataFrame:
    """Load intraday bars from a local CSV or Parquet file. No network.

    Column names are matched case-insensitively against the common spellings, and the
    timestamp may be the index or any recognisably-named column. The result is validated
    by ``validate_ohlc``, so a mis-mapped or corrupt file fails loudly here rather than
    producing plausible-looking numbers downstream.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no intraday data file at {p}")
    suffix = p.suffix.lower()
    if suffix in (".parquet", ".pq"):
        raw = pd.read_parquet(p)
    elif suffix in (".csv", ".txt", ".gz"):
        raw = pd.read_csv(p)
    else:
        raise DataQualityError(
            f"unsupported file type {suffix!r} (want .csv, .txt, .gz, .parquet, .pq)"
        )
    return validate_ohlc(_canonical_columns(_index_from_timestamp(raw)))


def regular_session(
    df: pd.DataFrame, start_utc: str = "13:30", end_utc: str = "21:00"
) -> pd.DataFrame:
    """Keep only US regular-session bars. The window covers both US DST offsets."""
    if df.empty:
        return df
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return df[(idx.time >= pd.Timestamp(start_utc).time())
              & (idx.time <= pd.Timestamp(end_utc).time())]


def resolve_intraday(
    local_path: "Optional[str | os.PathLike]" = None,
    search_dirs: Sequence[str] = ("data/intraday", "data"),
    symbol: str = "SPY",
    timeframe: str = "5Min",
) -> Tuple[str, Optional[pd.DataFrame], PowerReport]:
    """Resolve intraday bars, preferring a local file. Returns ``(source, df, power)``.

    Resolution order is local-explicit -> local-conventional -> nothing. Network sources
    are deliberately NOT attempted here: in this environment every market-data host is
    egress-denied, so a fetch path would only add a slow, confusing failure. A caller that
    has network can still fetch and hand the frame to ``validate_ohlc``/``describe_power``.

    When nothing is found the returned df is ``None`` and the report's verdict is
    ``UNDERPOWERED`` — callers must treat that as DATA-BLOCKED and emit no numbers.
    """
    candidates = []
    if local_path is not None:
        candidates.append(Path(local_path))
    stem = f"{symbol.upper()}_{timeframe.lower()}"
    for d in search_dirs:
        for ext in (".parquet", ".pq", ".csv", ".csv.gz"):
            candidates.append(Path(d) / f"{stem}{ext}")

    for cand in candidates:
        if cand.exists():
            df = load_local(cand)
            return f"local:{cand}", df, describe_power(df)

    looked = ", ".join(str(c) for c in candidates)
    return (
        "none",
        None,
        PowerReport(0, 0, None, None, 0, "UNDERPOWERED",
                    f"no local intraday file found (looked at: {looked}); "
                    "all market-data hosts are egress-denied in this environment"),
    )
