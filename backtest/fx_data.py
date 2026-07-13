"""FXCM EUR/USD H1 archive loader — offline cache, parse, resample, validate.

Research-only (#371, batch #370). Lives in ``backtest/`` and is never imported
by ``supabase/functions/``. No LLM, no broker calls, no orders.

Data source & re-fetch instructions
------------------------------------
FXCM's public candle archive serves raw H1 (1-hour) bid/ask OHLC at::

    https://candledata.fxcorporate.com/H1/EURUSD/<year>/<week>.csv.gz

Week numbers are FXCM's own numbering, **not** ISO week numbers: week 1 is the
first archived week of a year (which may start mid-week around New Year), and
some years carry a week 53 whose bars span into the following January (a
short holiday week — see the research note's week-numbering finding). Files
are plain gzip'd CSV with columns::

    DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose

``DateTime`` is ``MM/DD/YYYY HH:MM:SS.000`` and is parsed with an *explicit*
``format=`` string — never dateutil-inferred (a strictness requirement; see
``parse_week_csv``).

**Empirical timezone finding** (confirmed by fetching real archive weeks):
the archive's ``DateTime`` column is expressed in **America/New_York local
time, DST-aware** — a winter (EST) week opens Sunday 17:00 ET (= 22:00 UTC)
and a summer (EDT) week opens Sunday 17:00 ET (= 21:00 UTC), i.e. the *UTC*
open time shifts by an hour across the DST boundary while the *local* open
time (17:00) does not. This is **not** a fixed-UTC archive — every timestamp
below is normalized to UTC via ``tz_localize("America/New_York")`` before use.

Fetched files are cached **verbatim** (raw bytes, exactly as served — never
re-derived) under ``data/fxcm/H1/EURUSD/<year>/<week>.csv.gz``. ``/data/`` is
gitignored — downloaded data is **never committed**; provenance is this
docstring plus the research note's fetch-date log. To (re-)populate the
cache::

    venv/bin/python backtest/run_fx_plumbing_check.py --fetch

Data has been observed available from 2012 week 1 through roughly the most
recent 2-3 months (the archive lags "now"); missing years/weeks are reported
by the validation pass (``completeness_report``), never silently skipped.
"""
from __future__ import annotations

import gzip
import io
import os
from typing import Optional

import pandas as pd

BASE_URL = "https://candledata.fxcorporate.com/H1/EURUSD"
CACHE_ROOT = "data/fxcm/H1/EURUSD"
ARCHIVE_TZ = "America/New_York"
DATETIME_FORMAT = "%m/%d/%Y %H:%M:%S.%f"
RAW_COLUMNS = [
    "DateTime",
    "BidOpen", "BidHigh", "BidLow", "BidClose",
    "AskOpen", "AskHigh", "AskLow", "AskClose",
]
EXPECTED_ROWS_PER_WEEK = 120  # 24h x 5 trading days, a 24/5-math proxy


class WeekNotFoundError(Exception):
    """Raised when the archive itself has no file for a given (year, week)
    (an HTTP 404) — distinct from "not yet cached locally"."""


def _fetch_week(year: int, week: int) -> bytes:
    """Network seam — the ONLY function in this module that touches the
    network. Patched by every offline test via monkeypatch. Returns the raw
    gzip bytes exactly as served.
    """
    import requests

    url = f"{BASE_URL}/{year}/{week}.csv.gz"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        raise WeekNotFoundError(f"{url} -> HTTP 404")
    resp.raise_for_status()
    return resp.content


def cache_path(year: int, week: int, *, root: str = CACHE_ROOT) -> str:
    """Cache file path mirroring the archive's own year/week layout."""
    return os.path.join(root, str(year), f"{week}.csv.gz")


def read_cache(year: int, week: int, *, root: str = CACHE_ROOT) -> Optional[bytes]:
    """Return cached raw bytes, or None if not cached."""
    path = cache_path(year, week, root=root)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def write_cache(year: int, week: int, raw: bytes, *, root: str = CACHE_ROOT) -> str:
    """Write raw bytes to the cache path, creating parent dirs as needed."""
    path = cache_path(year, week, root=root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)
    return path


def get_week_bytes(
    year: int, week: int, *, fetch: bool = False, root: str = CACHE_ROOT
) -> bytes:
    """Cache-first accessor for one week's raw bytes.

    - Cache hit: return cached bytes, never touch the network.
    - Cache miss, ``fetch=False``: raise ``FileNotFoundError`` (the BLOCKED
      path for ``run_fx_plumbing_check.py`` run without ``--fetch``).
    - Cache miss, ``fetch=True``: call ``_fetch_week`` and persist the result.
      ``WeekNotFoundError`` (a real 404) propagates uncaught — callers that
      sweep a whole year decide how to treat a missing week themselves.
    """
    cached = read_cache(year, week, root=root)
    if cached is not None:
        return cached
    if not fetch:
        raise FileNotFoundError(
            f"no cached data for {year}/week {week} under {root!r}; "
            "re-run with --fetch"
        )
    raw = _fetch_week(year, week)
    write_cache(year, week, raw, root=root)
    return raw


def parse_week_csv(raw_gzip: bytes) -> pd.DataFrame:
    """Parse one week's raw gzip CSV bytes into an H1 DataFrame.

    - Strict datetime parsing via an explicit ``format=`` string (never
      dateutil-inferred) — a malformed/ambiguous date raises ``ValueError``.
    - Adds mid-price OHLC columns: ``Mid<Field> = (Bid<Field> + Ask<Field>) / 2``.
    - Localizes the naive ``DateTime`` as America/New_York wall-clock time
      (the empirical archive-timezone finding — see module docstring), then
      converts to UTC. Index name: ``datetime_utc``.

    Raises ``ValueError`` if the CSV's columns don't match the expected
    FXCM archive schema.
    """
    text = gzip.decompress(raw_gzip).decode("utf-8")
    df = pd.read_csv(io.StringIO(text))
    if list(df.columns) != RAW_COLUMNS:
        raise ValueError(f"unexpected columns: {list(df.columns)}; expected {RAW_COLUMNS}")

    dt_naive = pd.to_datetime(df["DateTime"], format=DATETIME_FORMAT)
    dt_utc = dt_naive.dt.tz_localize(ARCHIVE_TZ).dt.tz_convert("UTC")

    out = df.drop(columns=["DateTime"]).copy()
    out.index = dt_utc
    out.index.name = "datetime_utc"

    for field in ("Open", "High", "Low", "Close"):
        out[f"Mid{field}"] = (out[f"Bid{field}"] + out[f"Ask{field}"]) / 2.0

    return out


def resample_to_4h(df: pd.DataFrame) -> tuple:
    """Resample H1 bid/ask/mid OHLC onto the FIXED absolute UTC grid
    00/04/08/12/16/20 (lead decision, batch #370 decision log — not aligned
    to the data's own first timestamp). Empty (weekend) buckets are dropped.
    Partial boundary buckets (a bucket holding fewer than the full 4 hourly
    bars — typically the week's first/last bucket) are counted, not dropped.

    ``origin="epoch"`` (1970-01-01 00:00:00 UTC, itself on a 4h boundary)
    pins the grid to fixed absolute UTC hours regardless of where the data
    starts.

    Returns
    -------
    (resampled_df, report) where report = {
        "n_bars": int, "n_partial_boundary_buckets": int,
    }
    """
    ohlc_fields = {
        "BidOpen": "first", "BidHigh": "max", "BidLow": "min", "BidClose": "last",
        "AskOpen": "first", "AskHigh": "max", "AskLow": "min", "AskClose": "last",
        "MidOpen": "first", "MidHigh": "max", "MidLow": "min", "MidClose": "last",
    }
    counts = df["MidClose"].resample("4h", origin="epoch").count()
    resampled = df.resample("4h", origin="epoch").agg(ohlc_fields)
    resampled = resampled.dropna(how="all")
    non_empty_counts = counts.reindex(resampled.index)
    n_partial = int((non_empty_counts < 4).sum())
    resampled.index.name = "datetime_utc"
    report = {"n_bars": len(resampled), "n_partial_boundary_buckets": n_partial}
    return resampled, report


# ---------------------------------------------------------------------------
# Validation checks — each pure, returns a report dict, no side effects.
# ---------------------------------------------------------------------------

def check_duplicates(df: pd.DataFrame) -> dict:
    """Duplicate timestamps in the index."""
    dupe_mask = df.index.duplicated(keep=False)
    return {
        "n_duplicates": int(df.index.duplicated(keep="first").sum()),
        "duplicate_timestamps": sorted(set(df.index[dupe_mask])),
    }


def check_monotonic(df: pd.DataFrame) -> dict:
    """Non-monotonic (out-of-order) timestamps in the index."""
    is_mono = bool(df.index.is_monotonic_increasing)
    diffs = df.index.to_series().diff()
    n_non_monotonic = int((diffs.dropna() <= pd.Timedelta(0)).sum())
    return {"is_monotonic": is_mono, "n_non_monotonic": n_non_monotonic}


def check_gaps(df: pd.DataFrame, *, expected_delta: str = "1h") -> dict:
    """Consecutive-timestamp deltas that are not exactly ``expected_delta``
    (default one hour, the H1 bar spacing).

    Intended for use WITHIN a single contiguous run (e.g. one week's H1
    bars); a multi-week concatenation will show an expected Friday-close ->
    Sunday-open weekend gap every week, which is sanity, not a failure — see
    the research note for that reporting (callers filter weekend gaps out
    themselves before calling this on a full history).
    """
    diffs = df.index.to_series().diff().dropna()
    gap_mask = diffs != pd.Timedelta(expected_delta)
    return {
        "n_gaps": int(gap_mask.sum()),
        "gap_after_timestamps": list(diffs.index[gap_mask]),
    }


def check_ohlc_coherence(df: pd.DataFrame) -> dict:
    """OHLC coherence (low <= open,close <= high, both bid and ask sides),
    crossed quotes (ask < bid, checked on Close), and non-positive prices
    (any raw price column <= 0)."""
    violations = 0
    for side in ("Bid", "Ask"):
        o = df[f"{side}Open"]
        h = df[f"{side}High"]
        l = df[f"{side}Low"]
        c = df[f"{side}Close"]
        violations += int((l > o).sum() + (l > c).sum() + (h < o).sum() + (h < c).sum())

    crossed = int((df["AskClose"] < df["BidClose"]).sum())

    non_positive = 0
    for col in RAW_COLUMNS[1:]:
        non_positive += int((df[col] <= 0).sum())

    return {
        "n_coherence_violations": violations,
        "n_crossed_quotes": crossed,
        "n_non_positive_prices": non_positive,
    }


def empirical_spread_pips(df: pd.DataFrame) -> pd.Series:
    """Per-bar spread = AskClose - BidClose, in pips (1 pip = 0.0001 for a
    EURUSD-class pair)."""
    return (df["AskClose"] - df["BidClose"]) / 0.0001


def completeness_report(week_rows: dict) -> dict:
    """Weekly-file + row-count completeness, per pre-registered thresholds.

    Parameters
    ----------
    week_rows:
        ``{year: {week: n_rows_or_None}}``. ``None`` means the archive
        returned a real 404 for that week (missing), not merely "not yet
        fetched" (callers only include weeks they attempted).

    Returns
    -------
    ``{year: {n_expected_weeks, n_missing_weeks, missing_weeks,
    pct_missing_weeks, n_rows_found, pct_rows_missing}}`` — the two
    pre-registered BLOCKED thresholds (>2% missing weeks, >5% missing rows,
    per year) are evaluated by the caller (``run_fx_plumbing_check.py``)
    against these percentages.
    """
    report = {}
    for year, weeks in week_rows.items():
        n_expected = len(weeks)
        missing_weeks = sorted(w for w, n in weeks.items() if n is None)
        found = {w: n for w, n in weeks.items() if n is not None}
        n_rows_found = sum(found.values()) if found else 0
        expected_rows = EXPECTED_ROWS_PER_WEEK * len(found) if found else 0
        pct_rows_missing = (
            max(0.0, (expected_rows - n_rows_found) / expected_rows) if expected_rows else 0.0
        )
        report[year] = {
            "n_expected_weeks": n_expected,
            "n_missing_weeks": len(missing_weeks),
            "missing_weeks": missing_weeks,
            "pct_missing_weeks": (len(missing_weeks) / n_expected) if n_expected else 0.0,
            "n_rows_found": n_rows_found,
            "pct_rows_missing": pct_rows_missing,
        }
    return report
