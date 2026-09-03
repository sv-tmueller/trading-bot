"""SPY intraday bars fetch helper — Alpaca Market Data REST, GET-only (#566 step 1).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker *trading* call, no order endpoint — the only network this module ever
touches is the read-only historical-bars GET (``/v2/stocks/{symbol}/bars``), mirroring
``options_data.RealAlpacaSource`` and ``run_orb_probe._fetch_alpaca``.

Purpose (issue #566, SUB_PLAN Q1/step 1 — the study's hard data-feasibility gate): pull
SPY 60Min/30Min/5Min SIP bars from 2016-01-01 to ``data/intraday/SPY_<tf>.csv`` (local,
gitignored — never committed) and report each frame's power via
``intraday_data.describe_power`` so the study doc can cite row counts + SHA256 instead of
committing bar data. When no keys are available (env unset), ``fetch_and_save`` reports
``source="none"`` and an ``UNDERPOWERED`` ``PowerReport`` — the caller (the
pre-registration/feasibility doc) treats that as DATA-BLOCKED and stops, per the module
docstring in ``intraday_data.py`` and the issue's own stop condition. A fetch that reaches
the network but fails there (bad keys, rate limit, server error) raises
``urllib.error.HTTPError``/``URLError`` instead — the caller must handle that case
separately; it is not converted to a DATA-BLOCKED report by this module.

Fidelity note (adjustment parameter): the live ``hourly-check`` bot's
``marketdata.getHourlyBars`` fetches with ``adjustment=all`` (fully split/dividend
adjusted; see ``supabase/functions/_shared/marketdata.ts`` #265's rationale, restated for
the hourly bot). ``fetch_bars`` defaults to the same (``adjustment="all"``) so the study's
input bars match what ``decideHourly``/``computeBracketGeometry`` actually see live —
this corrects an inverted claim in the issue #566 SUB_PLAN text ("recommend raw — matches
what the live bot sees"), which has it backwards: adjusted, not raw, is what the live bot
sees. Documented as a discovered discrepancy, not silently followed.

Two defect fixes (#571, found at data-staging time, unreachable by this module's own
mocked tests since they never called the real Alpaca host):

1. ``timeframe="60Min"`` 400s against the real API (valid grammar is 1-59Min or 1Hour) --
   ``_api_timeframe`` remaps it to ``"1Hour"`` at request time only; every output-facing
   name (the ``SPY_60min.csv`` stem, this module's own ``DEFAULT_TIMEFRAMES``, every
   caller/test) keeps spelling it ``"60Min"``.
2. The CLI's default ``end`` (today) 403s on ``feed=sip`` for this account tier (a
   recent-SIP embargo); the default is the previous **UTC** date -- computed via
   ``datetime.now(timezone.utc)``, not the host's local date (#575 round-2: a
   local-date computation can undershoot by a day on UTC+ timezones and reopen the
   embargo 403) -- which succeeds for the full 2016-01-01-> window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from backtest.intraday_data import PowerReport, describe_power, validate_ohlc

DATA_HOST = "https://data.alpaca.markets"
DEFAULT_OUT_DIR = "data/intraday"
DEFAULT_START = "2016-01-01"
DEFAULT_TIMEFRAMES = ("60Min", "30Min", "5Min")
DEFAULT_FEED = "sip"
DEFAULT_ADJUSTMENT = "all"
_PAGE_LIMIT = 10_000

# #571 defect fix: Alpaca's bars endpoint grammar is 1-59Min or 1Hour (an exact
# "60Min" 400s). "60Min" is kept as this module's public-facing/output-naming
# timeframe string (the SPY_60min.csv convention predates this fix and every
# caller/test spells it that way) -- only the wire request is remapped.
_API_TIMEFRAME_OVERRIDES = {"60Min": "1Hour"}


def _api_timeframe(timeframe: str) -> str:
    """The timeframe string Alpaca's REST grammar actually accepts for the request."""
    return _API_TIMEFRAME_OVERRIDES.get(timeframe, timeframe)


class FetchUnavailableError(RuntimeError):
    """No Alpaca data keys available (env unset and none passed explicitly).

    The caller's designated DATA-BLOCKED signal — never silently substituted with
    another source. yfinance is a separate, explicit fallback (SUB_PLAN Q1: fallback-only,
    cannot serve the 30Min arm at all — #422) and is deliberately NOT tried automatically
    here.
    """


def resolve_keys() -> "tuple[Optional[str], Optional[str]]":
    """(key, secret) from env, or (None, None).

    Checks both the historical Python-side names (``ALPACA_API_KEY_ID`` /
    ``ALPACA_API_SECRET_KEY`` — ``options_data.RealAlpacaSource``'s and
    ``run_orb_probe._fetch_alpaca``'s convention) and the current TS-side names
    (``ALPACA_API_KEY`` / ``ALPACA_SECRET_KEY`` — ``config.ts``'s convention, per
    ``.env.example``), since an operator's shell may carry either. The KEY_ID-suffixed
    names win when both are set (matches ``run_orb_probe``'s existing precedence).
    """
    key = os.environ.get("ALPACA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
    return key, secret


def _fetch_page(url: str, key: str, secret: str, *, timeout: int = 30) -> dict:
    """Network seam — the ONLY function in this module that touches the network.

    Patched by every offline test via monkeypatch. GET only, read-only market-data
    endpoint; never an order endpoint, never a broker mutation.
    """
    req = urllib.request.Request(
        url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_bars(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    *,
    key: Optional[str] = None,
    secret: Optional[str] = None,
    feed: str = DEFAULT_FEED,
    adjustment: str = DEFAULT_ADJUSTMENT,
    keep_volume: bool = False,
) -> pd.DataFrame:
    """Fetch every bar for ``(symbol, timeframe)`` in ``[start, end]``, oldest-first.

    Paginates on ``next_page_token`` until exhausted. Raises ``FetchUnavailableError``
    if no keys are available (explicit args take precedence over env via
    ``resolve_keys()``). Returns a ``validate_ohlc``-clean DataFrame indexed by bar-start
    UTC timestamp — a malformed bar (NaN, non-positive, High/Low not bracketing
    Open/Close) raises ``DataQualityError`` here rather than downstream.

    ``keep_volume=True`` preserves the Alpaca ``'v'`` field as a ``"Volume"`` column
    alongside the validated OHLC columns. ``validate_ohlc`` strips non-OHLC columns, so
    the volume Series is extracted before validation and reattached afterward. Default
    ``False`` = existing behavior (OHLC only, no Volume column). Backward-compatible.
    """
    env_key, env_secret = resolve_keys()
    key = key or env_key
    secret = secret or env_secret
    if not (key and secret):
        raise FetchUnavailableError(
            "Alpaca data keys not set (ALPACA_API_KEY_ID/ALPACA_API_KEY + "
            "ALPACA_API_SECRET_KEY/ALPACA_SECRET_KEY) — read-only market-data keys, "
            "never a broker order credential."
        )
    rows: list = []
    page_token: Optional[str] = None
    while True:
        params = {
            "timeframe": _api_timeframe(timeframe),
            "start": start,
            "end": end,
            "limit": str(_PAGE_LIMIT),
            "adjustment": adjustment,
            "feed": feed,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token
        url = (
            f"{DATA_HOST}/v2/stocks/{urllib.parse.quote(symbol)}/bars"
            f"?{urllib.parse.urlencode(params)}"
        )
        payload = _fetch_page(url, key, secret)
        rows.extend(payload.get("bars") or [])
        page_token = payload.get("next_page_token")
        if not page_token:
            break

    if not rows:
        cols = ["Open", "High", "Low", "Close"]
        if keep_volume:
            cols.append("Volume")
        return pd.DataFrame(columns=cols)

    raw = pd.DataFrame(rows)
    raw.index = pd.to_datetime(raw["t"], utc=True)

    # Preserve volume before validate_ohlc strips non-OHLC columns (#629).
    vol_series: Optional[pd.Series] = None
    if keep_volume and "v" in raw.columns:
        vol_series = raw["v"].astype(float)

    raw = raw.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close"})
    cleaned = validate_ohlc(raw)

    if keep_volume and vol_series is not None:
        cleaned = cleaned.copy()
        cleaned["Volume"] = vol_series.reindex(cleaned.index).fillna(0.0)

    return cleaned


def compute_sha256(path: "str | os.PathLike") -> str:
    """SHA256 of a file's raw bytes — the provenance record for a never-committed CSV."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(df: pd.DataFrame, path: "str | os.PathLike") -> None:
    """Write an OHLC frame to CSV, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index_label="timestamp")


@dataclass(frozen=True)
class FetchReport:
    """One (symbol, timeframe) fetch attempt's outcome — the unit the study doc cites."""

    symbol: str
    timeframe: str
    source: str          # "alpaca" | "none"
    rows: int
    path: Optional[str]  # local CSV path, or None if nothing was written
    sha256: Optional[str]
    power: PowerReport
    error: Optional[str] = None

    def summary(self) -> str:
        head = f"{self.symbol} {self.timeframe}: source={self.source} rows={self.rows}"
        if self.error:
            return f"{head} — DATA_BLOCKED: {self.error}"
        return f"{head} sha256={self.sha256} — {self.power.summary()}"


def fetch_and_save(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    *,
    out_dir: "str | os.PathLike" = DEFAULT_OUT_DIR,
    key: Optional[str] = None,
    secret: Optional[str] = None,
    feed: str = DEFAULT_FEED,
    adjustment: str = DEFAULT_ADJUSTMENT,
    keep_volume: bool = False,
) -> FetchReport:
    """Fetch one (symbol, timeframe), write it locally, and report row count + SHA256.

    On ``FetchUnavailableError`` (no keys), returns a DATA-BLOCKED report — no file is
    written, ``power.verdict`` is ``UNDERPOWERED`` — instead of raising, so a caller
    sweeping every timeframe of the grid can finish the sweep and report each cell.

    ``keep_volume=True`` is passed through to :func:`fetch_bars` so the saved CSV
    includes a ``"Volume"`` column alongside OHLC (#629). Default ``False`` = existing
    behavior. Backward-compatible.
    """
    try:
        df = fetch_bars(symbol, timeframe, start, end, key=key, secret=secret, feed=feed,
                        adjustment=adjustment, keep_volume=keep_volume)
    except FetchUnavailableError as e:
        return FetchReport(
            symbol=symbol, timeframe=timeframe, source="none", rows=0, path=None,
            sha256=None, power=describe_power(pd.DataFrame(columns=["Open", "High", "Low", "Close"])),
            error=str(e),
        )

    stem = f"{symbol.upper()}_{timeframe.lower()}"
    out_path = Path(out_dir) / f"{stem}.csv"
    write_csv(df, out_path)
    return FetchReport(
        symbol=symbol, timeframe=timeframe, source="alpaca", rows=len(df),
        path=str(out_path), sha256=compute_sha256(out_path), power=describe_power(df),
    )


def _now_utc() -> datetime:
    """Testing seam: real UTC "now". Monkeypatched in tests to pin the default-``end``
    math (#575 round-2 fix) without depending on the host's timezone or the day it runs.
    """
    return datetime.now(timezone.utc)


def main(argv: Optional[list] = None) -> int:
    """CLI: fetch every requested timeframe, print each report, return the blocked count.

    Return value is the number of DATA-BLOCKED timeframes (0 = every requested timeframe
    fetched) — a caller (or an operator) can treat a nonzero return as "consult the
    printed DATA_BLOCKED evidence before proceeding."
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES),
                    help="comma-separated Alpaca timeframe strings, e.g. 60Min,30Min,5Min")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument(
        "--end", default=None,
        help="defaults to yesterday, UTC (not the host's local date) -- feed=sip 403s "
             "on today's date for this account tier (#571, the recent-SIP embargo)",
    )
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--feed", default=DEFAULT_FEED)
    ap.add_argument("--adjustment", default=DEFAULT_ADJUSTMENT)
    ap.add_argument("--keep-volume", action="store_true", default=False,
                    help="preserve the Alpaca 'v' field as a 'Volume' column (#629)")
    args = ap.parse_args(argv)

    end = args.end
    if end is None:
        # #571 defect fix: today's date 403s on feed=sip (recent-data embargo); the
        # previous UTC date succeeds for the full 2016-01-01+ window. #575 round-2 fix:
        # this must be the previous UTC date, not the previous LOCAL date -- on UTC+2,
        # local wall-clock 22:00-24:00 is already tomorrow-local but still today-UTC, so a
        # local-date computation can undershoot by a day and reopen the embargo 403.
        end = (_now_utc().date() - timedelta(days=1)).isoformat()

    timeframes = [tf.strip() for tf in args.timeframes.split(",") if tf.strip()]
    blocked = 0
    for tf in timeframes:
        report = fetch_and_save(
            args.symbol, tf, args.start, end, out_dir=args.out_dir, feed=args.feed,
            adjustment=args.adjustment, keep_volume=args.keep_volume,
        )
        print(report.summary())
        if report.error is not None:
            blocked += 1
    return blocked


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
