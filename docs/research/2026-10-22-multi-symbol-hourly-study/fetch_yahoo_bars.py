"""Stage the multi-symbol hourly study's input bars from Yahoo Finance (read-only GET).

Research-only. Never imported by ``supabase/functions/``. No broker call, no order
endpoint, no Alpaca key. Writes CSVs (``timestamp,Open,High,Low,Close,Volume``, UTC
timestamps) into ``--out-dir`` -- a scratch directory, never committed.

Why Yahoo and not Alpaca: the pre-registration's primary data path (Alpaca SIP
``1Hour``/``5Min``, ``adjustment=all``, 2016+) needs Alpaca market-data keys, which were
not present in this session's environment (``data.alpaca.markets`` answers 401 without
keys). Yahoo is the disclosed fallback; its limits (1h history ~730 sessions, bars aligned
to :30 not top-of-hour, 5m history ~60 days) are why the pre-registration adds the
proxy-harness parity gates (P0b-P0d) before any cross-symbol number is trusted.

Frames per symbol:
  * ``<SYM>_1h_yahoo.csv``  -- interval=1h, period=730d, regular session only (bars start
    at 09:30 ET; the 15:30 ET bar is a 30-minute stub).
  * ``<SYM>_5m_yahoo.csv``  -- interval=5m, period=60d, regular session only.
  * ``<SYM>_1d_yahoo.csv``  -- interval=1d, period=5y (overnight-gap diagnostics only).

``auto_adjust=False``: Yahoo intraday prices are split-adjusted regardless; dividend
adjustment is left off so price levels stay close to what actually traded (matters for
the frozen ``HOURLY_MIN_STOP_DISTANCE=$0.05`` gate and whole-cent quantization).

Usage::

    venv/bin/python docs/research/2026-10-22-multi-symbol-hourly-study/fetch_yahoo_bars.py \
        --out-dir <scratch>/bars
"""
from __future__ import annotations

import argparse
import hashlib
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# Frozen in the pre-registration (§2). GOOGL stands in for the Alphabet issuer
# (GOOGL + GOOG are one company; trading both would double one exposure).
TOP10 = ("NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "AVGO", "META", "TSLA", "MU", "LLY")
BASELINE = ("SPY",)
ETFS = ("QQQ", "IWM", "DIA", "XLK", "XLF")
CONTROLS = ("BRK-B", "JPM", "UNH")
ALL_SYMBOLS = BASELINE + TOP10 + ETFS + CONTROLS

FRAMES = (
    ("1h_yahoo", dict(interval="1h", period="730d")),
    ("5m_yahoo", dict(interval="5m", period="60d")),
    ("1d_yahoo", dict(interval="1d", period="5y")),
)


def _download(symbol: str, interval: str, period: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(
        symbol, interval=interval, period=period, auto_adjust=False,
        prepost=False, progress=False, threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"empty download for {symbol} {interval} {period}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.index.name = "timestamp"
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--symbols", nargs="*", default=list(ALL_SYMBOLS))
    args = ap.parse_args(argv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for sym in args.symbols:
        for suffix, kw in FRAMES:
            df = _download(sym, **kw)
            path = out / f"{sym}_{suffix}.csv"
            df.to_csv(path)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"{sym:6s} {suffix:9s} rows={len(df):6d} {df.index[0]} -> {df.index[-1]} sha256={sha}")
            time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
