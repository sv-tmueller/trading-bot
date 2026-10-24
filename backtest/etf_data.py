"""Holdout-locked daily ETF loader for the AI research pipeline (research only).

Development mode never returns a row after DEV_END, whatever the source
returns. Holdout mode (2022+) is released for a candidate only after its
development result is recorded, and only once. The lock is mechanical: it
lives in files under ``<pipeline_dir>/<candidate_id>/``.

Output contract for both phases: per ticker, a DataFrame with Open, High, Low,
Close columns and a time-zone-free, midnight-normalized, sorted DatetimeIndex.
No network access happens unless the default yfinance fetch is used.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

DEV_END = date(2021, 12, 31)
HOLDOUT_START = date(2022, 1, 1)
PIPELINE_DIR = Path("docs/research/pipeline")

_OHLC = ["Open", "High", "Low", "Close"]
_PHASES = ("development", "holdout")
_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class HoldoutLockedError(RuntimeError):
    """The holdout may not be read or written right now."""


def _check_candidate_id(candidate_id: str) -> None:
    if not isinstance(candidate_id, str) or not _CANDIDATE_ID_RE.match(candidate_id):
        raise ValueError(f"invalid candidate_id: {candidate_id!r}")


def _fetch_yfinance(ticker: str) -> pd.DataFrame:
    """Adjusted daily OHLC from yfinance (imported lazily; network)."""
    import yfinance as yf

    df = yf.download(ticker, start="1990-01-01", auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[_OHLC].dropna()


def _normalize(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in _OHLC if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: fetched frame is missing columns {missing}")
    out = df[_OHLC].copy()
    idx = pd.to_datetime(out.index)
    if idx.tz is not None:
        # Strip without converting (repo convention); converting to New York
        # time first would move UTC-midnight stamps back a day and leak rows.
        idx = idx.tz_localize(None)
    out.index = idx.normalize()
    return out.sort_index()


def load_daily_bars(
    tickers: List[str],
    *,
    phase: str,
    candidate_id: Optional[str] = None,
    pipeline_dir: Path = PIPELINE_DIR,
    fetch: Optional[Callable[[str], pd.DataFrame]] = None,
) -> Dict[str, pd.DataFrame]:
    if phase not in _PHASES:
        raise ValueError(f"unknown phase: {phase!r}")

    if phase == "holdout":
        # Check the lock before any fetch: a locked call never touches the source.
        if candidate_id is None:
            raise HoldoutLockedError("holdout requires a candidate_id")
        _check_candidate_id(candidate_id)
        cdir = Path(pipeline_dir) / candidate_id
        if not (cdir / "development_result.json").exists():
            raise HoldoutLockedError(
                f"holdout locked for {candidate_id}: no development result recorded"
            )
        if (cdir / "holdout_result.json").exists():
            raise HoldoutLockedError(f"holdout already run for {candidate_id}")

    fetch_fn = fetch if fetch is not None else _fetch_yfinance
    cutoff = pd.Timestamp(HOLDOUT_START)
    out: Dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = _normalize(ticker, fetch_fn(ticker))
        if phase == "development":
            df = df[df.index < cutoff]
        out[ticker] = df
    return out


def record_result(
    candidate_id: str,
    phase: str,
    payload: dict,
    *,
    pipeline_dir: Path = PIPELINE_DIR,
) -> Path:
    _check_candidate_id(candidate_id)
    if phase not in _PHASES:
        raise ValueError(f"unknown phase: {phase!r}")
    cdir = Path(pipeline_dir) / candidate_id
    if (cdir / "holdout_result.json").exists():
        raise HoldoutLockedError(f"holdout already recorded for {candidate_id}")
    if phase == "holdout" and not (cdir / "development_result.json").exists():
        raise HoldoutLockedError(
            f"cannot record holdout for {candidate_id}: no development result"
        )
    # Serialize first: a payload that fails must not leave a partial file
    # that would use up the holdout.
    text = json.dumps(payload, sort_keys=True, indent=2)
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / f"{phase}_result.json"
    path.write_text(text + "\n")
    return path
