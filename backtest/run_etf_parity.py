"""yfinance vs Alpaca daily-bar parity check for the AI research pipeline.

Research only. Compares adjusted daily closes from yfinance (the pipeline's
loader) with Alpaca's split- and dividend-adjusted ``1Day`` bars over the
development window, and reports the median and 99th percentile of the
absolute daily-return difference in basis points.

The only Alpaca reference is the existing read-only bars helper
(``run_fetch_spy_intraday.fetch_bars``); keys come from the environment.
There is no start/end flag: the window is fixed to ``[WINDOW_START,
DEV_END]`` so this script cannot read the 2022+ holdout.

Exit code: 0 when every ticker passes, 1 when any fails or errors, 2 on bad
arguments.
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Callable, List, Optional

import pandas as pd

from backtest.etf_data import DEV_END, _normalize, load_daily_bars
from backtest.run_fetch_spy_intraday import fetch_bars

MEDIAN_ABS_DIFF_BPS_MAX = 1.0  # strict <
P99_ABS_DIFF_BPS_MAX = 10.0  # strict <
WINDOW_START = date(2019, 1, 1)
ALPACA_TIMEFRAME = "1Day"
ALPACA_ADJUSTMENT = "all"  # splits + dividends, matches yfinance auto_adjust=True
ALPACA_START = "2019-01-01"
# RFC-3339 so the final session's bar (stamped 05:00Z) is not cut off by a
# date-only midnight end.
ALPACA_END = f"{DEV_END.isoformat()}T23:59:59Z"


def _check_index(name: str, s: pd.Series) -> None:
    if getattr(s.index, "tz", None) is not None:
        raise ValueError(f"{name}: index must be time-zone-free")
    if s.index.has_duplicates:
        raise ValueError(f"{name}: index has duplicate dates")


def compare_daily_returns(yf_close: pd.Series, alpaca_close: pd.Series) -> dict:
    """Compare daily returns of two close series on their shared dates.

    The join happens before ``pct_change`` so a day missing on one side makes
    both sides span the same multi-day interval instead of creating false
    diffs. Days present on only one side are dropped. No overlap fails closed.
    Raises ValueError on a tz-aware or duplicated index; a NaN close counts as a missing day.
    """
    _check_index("yf_close", yf_close)
    _check_index("alpaca_close", alpaca_close)
    joined = pd.concat([yf_close, alpaca_close], axis=1, join="inner")
    joined.columns = ["yf", "alpaca"]
    rets = joined.dropna().sort_index().pct_change().dropna()
    diffs = (rets["alpaca"] - rets["yf"]).abs() * 10_000
    n_days = int(len(diffs))
    if n_days == 0:
        median = p99 = float("nan")
        passed = False
    else:
        median = float(diffs.median())
        p99 = float(diffs.quantile(0.99))
        passed = bool(median < MEDIAN_ABS_DIFF_BPS_MAX and p99 < P99_ABS_DIFF_BPS_MAX)
    return {
        "n_days": n_days,
        "median_abs_diff_bps": median,
        "p99_abs_diff_bps": p99,
        "passed": passed,
    }


def _in_window(close: pd.Series) -> pd.Series:
    return close[
        (close.index >= pd.Timestamp(WINDOW_START)) & (close.index <= pd.Timestamp(DEV_END))
    ]


def run_parity(
    tickers: List[str],
    *,
    yf_fetch: Optional[Callable[[str], pd.DataFrame]] = None,
    alpaca_fetch: Optional[Callable[..., pd.DataFrame]] = None,
) -> List[dict]:
    rows: List[dict] = []
    for ticker in tickers:
        row = {
            "ticker": ticker,
            "n_days": 0,
            "median_abs_diff_bps": float("nan"),
            "p99_abs_diff_bps": float("nan"),
            "passed": False,
            "n_yf": 0,
            "n_alpaca": 0,
            "error": None,
        }
        try:
            yf_close = _in_window(
                load_daily_bars([ticker], phase="development", fetch=yf_fetch)[ticker]["Close"]
            )
            fn = alpaca_fetch if alpaca_fetch is not None else fetch_bars
            raw = fn(
                ticker,
                ALPACA_TIMEFRAME,
                ALPACA_START,
                ALPACA_END,
                adjustment=ALPACA_ADJUSTMENT,
            )
            alpaca_close = _in_window(_normalize(ticker, raw)["Close"])
            row["n_yf"] = int(len(yf_close))
            row["n_alpaca"] = int(len(alpaca_close))
            row.update(compare_daily_returns(yf_close, alpaca_close))
        except Exception as exc:  # one bad ticker must not abort the rest
            row["error"] = repr(exc)
        rows.append(row)
    return rows


_HEADER = (
    f"{'ticker':<8} {'n_days':>7} {'median_bps':>11} {'p99_bps':>9} "
    f"{'n_yf':>6} {'n_alpaca':>9} verdict"
)


def format_row(row: dict) -> str:
    verdict = "PASS" if row["passed"] else "FAIL"
    line = (
        f"{row['ticker']:<8} {row['n_days']:>7d} {row['median_abs_diff_bps']:>11.3f} "
        f"{row['p99_abs_diff_bps']:>9.3f} {row['n_yf']:>6d} {row['n_alpaca']:>9d} {verdict}"
    )
    if row.get("error"):
        line += f"  {row['error']}"
    return line


def main(
    argv: Optional[List[str]] = None,
    *,
    yf_fetch: Optional[Callable[[str], pd.DataFrame]] = None,
    alpaca_fetch: Optional[Callable[..., pd.DataFrame]] = None,
) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tickers", required=True, help="comma-separated tickers")
    args = ap.parse_args(argv)
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        ap.error("--tickers must name at least one ticker")
    rows = run_parity(tickers, yf_fetch=yf_fetch, alpaca_fetch=alpaca_fetch)
    print(_HEADER)
    for row in rows:
        print(format_row(row))
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
