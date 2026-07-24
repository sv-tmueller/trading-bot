"""Opening-Range Breakout (ORB) free-data probe — Candidate B runner (#431, P2 of #429).

Research-only. Lives in backtest/ and is never imported by supabase/functions/. No LLM,
no broker *trading* calls, no broker-client import. The only network is a **read-only**
historical-bars pull (Alpaca data host or yfinance); no order endpoint is ever touched.
Mirror pattern: run_turtle_breakout.py + docs/research/2026-07-24-turtle-breakout-verdict.md.

This is an UNDERPOWERED, DIRECTIONAL probe, not a promotion test (see
docs/research/2026-07-24-orb-probe-verdict.md). Free SPY 5-min reaches only ~n_w≈9
(2016+), short of the n_w=13 promotion bar, so the pre-registered question is narrow:

    Does the long-only ORB show a POSITIVE after-cost edge vs a seeded random-entry
    baseline AND vs always-in buy-&-hold, on free SPY 5-min (2016+)?

The deliverable verdict is "worth paying for full-power intraday data? yes/no" — NOT a
GO/NO-GO promotion.

Frozen rule (long-only variant of Zarattini & Aziz 2023, engine is long-only v1):
  - Opening range (OR) = the first 5-min bar of each US session (its High / Low).
  - Entry (long-only): the first later bar of the SAME session whose Close breaks above
    the OR high; enter at the NEXT bar's open (close-t -> open-t+1 shift, no look-ahead),
    one entry per session, never on the OR bar, never across a session boundary.
  - Stop = OR low (opposite side of the opening range — the paper's explicit stop).
  - Target variants (frozen grid): None (exit-at-session-close, the paper's simplest),
    R=5, R=10 multiples of the per-share risk (entry - OR low); the paper's base is 10R.
  - Session/EOD close-out: never hold overnight (bracket.session_close_out=True); EOW off.
  These absolute stop/target levels are computed HERE and passed to simulate_bracket —
  the engine never hardcodes the geometry.

Long/short caveat: the paper trades both sides; the bracket engine is long-only, so this
probe tests the LONG arm only. Disclosed in the verdict doc.

Run: python3 -m backtest.run_orb_probe [--end YYYY-MM-DD] [--start YYYY-MM-DD]
All numbers come from a live read-only pull at run time; no price is ever fabricated.
"""
from __future__ import annotations

import argparse
import os
from datetime import date
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from backtest.bracket import simulate_bracket
from backtest.regime import (
    COMMISSION_BPS,
    SLIPPAGE_BPS,
    STARTING_CASH,
    simulate_from_signal,
)
from backtest.run_candidate_survey import _after_tax_metrics

# --- Frozen rule + probe parameters (pre-registered) --------------------------------
TARGET_VARIANTS: Tuple[Optional[float], ...] = (None, 5.0, 10.0)  # None=exit-at-close
PROBE_START = date(2016, 1, 1)   # free intraday history floor (2016+)
RANDOM_SEED = 42                 # seeded random-entry baseline (reproducible)

# Realistic intraday cost model. Intraday churn is high, so cost is load-bearing; the
# scalping cost-wall demo (run_scalping_cost_wall.py) charges a crossed-spread + fee round
# trip. Here, per side: SLIPPAGE_BPS (crossed half-spread) + COMMISSION_BPS from regime.py
# (the same 5+5 bps/side = 20 bps round trip the turtle bracket used) — not omitted.
_SLIPPAGE_BPS = SLIPPAGE_BPS
_COMMISSION_BPS = COMMISSION_BPS

_MIN_WINDOW_BARS = 80            # below this the fetch is treated as "data unavailable"
# Directional-read power floor: the pre-registered read lives on 2016+ Alpaca depth. Free
# yfinance 5-min is ~60-session-capped, far below this, so it can only ever be a plumbing
# smoke, never the read. When n_sessions < this floor the result is DATA-BLOCKED.
PROBE_MIN_SESSIONS = 500

_ALPACA_DATA_HOST = "https://data.alpaca.markets"


# ---------------------------------------------------------------------------
# Data — read-only. Alpaca 2016+ first (keyed), else yfinance (~60d cap). Patch seam.
# ---------------------------------------------------------------------------

def _fetch_alpaca(start: date, end: date) -> Optional[pd.DataFrame]:
    """Read-only SPY 5-min bars from the Alpaca DATA host, or None if unavailable.

    Uses the historical-bars GET endpoint only (never an order endpoint). Requires
    ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY (the read-only data keys, same names as
    options_data.RealAlpacaSource). Returns None on missing keys or any error so the
    caller falls back cleanly. Regular-session bars only (13:30-21:00 UTC covers both
    US DST offsets).
    """
    key = os.environ.get("ALPACA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        return None
    import json
    import urllib.parse
    import urllib.request

    rows: list[dict] = []
    page_token: Optional[str] = None
    try:
        while True:
            params = {
                "timeframe": "5Min", "start": f"{start.isoformat()}T00:00:00Z",
                "end": f"{end.isoformat()}T23:59:59Z", "limit": "10000",
                "adjustment": "all", "feed": "iex",
            }
            if page_token:
                params["page_token"] = page_token
            url = f"{_ALPACA_DATA_HOST}/v2/stocks/SPY/bars?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={
                "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read())
            rows.extend(payload.get("bars") or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break
    except Exception:  # noqa: BLE001 — read-only fetch; degrade to fallback, never crash
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["t"], utc=True)
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close"})
    return _regular_session(df[["Open", "High", "Low", "Close"]].dropna().sort_index())


def _fetch_yfinance(start: date, end: date) -> pd.DataFrame:
    """Fallback: yfinance SPY 5-min (depth-capped ~60 calendar days FROM NOW)."""
    import yfinance as yf

    df = yf.download("SPY", period="60d", interval="5m",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Open", "High", "Low", "Close"]].dropna()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return _regular_session(out.sort_index())


def _regular_session(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only US regular-session bars (13:30-21:00 UTC spans both EDT and EST)."""
    if df.empty:
        return df
    minutes = df.index.hour * 60 + df.index.minute
    return df[(minutes >= 13 * 60 + 30) & (minutes < 21 * 60)]


def _fetch(start: date, end: date) -> Tuple[str, pd.DataFrame]:
    """SPY 5-min OHLC, read-only. Try Alpaca 2016+ first, else yfinance. Patch seam."""
    alpaca = _fetch_alpaca(start, end)
    if alpaca is not None and len(alpaca):
        return "alpaca", alpaca
    return "yfinance", _fetch_yfinance(start, end)


# ---------------------------------------------------------------------------
# ORB signal + absolute bracket levels (the geometry lives here, not the engine).
# ---------------------------------------------------------------------------

def _session_key(df: pd.DataFrame) -> pd.Series:
    """Per-bar session key = the bar's normalized (midnight) timestamp (US RTH = 1 UTC date)."""
    return pd.Series(df.index.normalize(), index=df.index)


def _opening_range(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """OR high/low (first bar of each session, broadcast to every bar) + is-first-bar flag."""
    sess = _session_key(df)
    or_high = df.groupby(sess)["High"].transform("first")
    or_low = df.groupby(sess)["Low"].transform("first")
    is_first = ~sess.duplicated()
    return or_high, or_low, is_first, sess


def _entry_trigger(df: pd.DataFrame) -> pd.Series:
    """Long-only ORB entry_trigger aligned to df.index (True = enter at THIS bar's open).

    Signal: first bar of a session (after the OR bar) whose Close > OR high. The engine
    enters at the next bar's open, so shift the signal by one bar; drop any entry that
    lands on a session's first (OR) bar, which would be a cross-session leak.
    """
    or_high, _or_low, is_first, sess = _opening_range(df)
    breaks = (df["Close"] > or_high) & (~is_first)
    first_break = breaks & (breaks.groupby(sess).cumsum() == 1)
    trigger = first_break.shift(1, fill_value=False) & (~is_first)
    return trigger


def _orb_levels(
    df: pd.DataFrame, entry_trigger: pd.Series, or_low: pd.Series,
    r: Optional[float], *, slippage_bps: int = _SLIPPAGE_BPS,
) -> Tuple[pd.Series, Optional[pd.Series]]:
    """Absolute stop (= OR low) and target (entry + R*risk, or None) for each ORB entry.

    entry_ref ~= Open*(1+slip) at the entry bar; risk = entry_ref - OR low. The entry bar
    is in the same session as its OR (guaranteed by _entry_trigger), so OR low read at the
    entry bar is the correct session's. Levels meaningful only where an entry triggers.
    """
    slip = slippage_bps / 10_000.0
    entry_ref = df["Open"] * (1 + slip)
    stop = or_low.where(entry_trigger)
    if r is None:
        target = None
    else:
        target = (entry_ref + r * (entry_ref - or_low)).where(entry_trigger)
    return stop, target


def _build_cell(df: pd.DataFrame, r: Optional[float]) -> dict:
    """One ORB cell over df: long-only, session-flat, per-entry OR-low stop / R-target."""
    _oh, or_low, _isf, _sess = _opening_range(df)
    trigger = _entry_trigger(df)
    stop, target = _orb_levels(df, trigger, or_low, r)
    return simulate_bracket(
        df, trigger, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=_SLIPPAGE_BPS, commission_bps=_COMMISSION_BPS,
        eow_close_out=False, session_close_out=True,
    )


def _build_random_cell(df: pd.DataFrame, r: Optional[float], seed: int = RANDOM_SEED) -> dict:
    """Random-entry bracket: same OR-low-stop / R-target geometry, entries SHUFFLED.

    Places the same NUMBER of entries as the real signal at random valid intra-session
    bars (never a session's OR bar), seeded. A real edge must beat this random baseline.
    """
    _oh, or_low, is_first, _sess = _opening_range(df)
    real_trigger = _entry_trigger(df)
    k = int(real_trigger.sum())
    valid = np.flatnonzero((~is_first).to_numpy())
    rng = np.random.default_rng(seed)
    trig = pd.Series(False, index=df.index)
    if k > 0 and len(valid) > 0:
        chosen = rng.choice(valid, size=min(k, len(valid)), replace=False)
        trig.iloc[np.sort(chosen)] = True
    stop, target = _orb_levels(df, trig, or_low, r)
    return simulate_bracket(
        df, trig, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=_SLIPPAGE_BPS, commission_bps=_COMMISSION_BPS,
        eow_close_out=False, session_close_out=True,
    )


def _always_in(df: pd.DataFrame) -> dict:
    """Always-long SPY over the same bars (buy & hold) — the beta baseline."""
    oc = df[["Open", "Close"]]
    sig = pd.Series(True, index=df.index)
    return simulate_from_signal(
        vehicle_df=oc, is_bullish_close_t=sig,
        starting_cash=STARTING_CASH,
        slippage_bps=_SLIPPAGE_BPS, commission_bps=_COMMISSION_BPS,
    )


# ---------------------------------------------------------------------------
# Probe driver + directional read.
# ---------------------------------------------------------------------------

def _n_sessions(df: pd.DataFrame) -> int:
    return int(df.index.normalize().nunique()) if len(df) else 0


def run_orb(end: Optional[date] = None, start: Optional[date] = None) -> dict:
    """Fetch read-only SPY 5-min, run the frozen ORB grid + baselines + the directional read.

    Guards the whole build on ``len(df) >= _MIN_WINDOW_BARS`` (#430 should-fix): an empty
    or too-short fetch reports ``data_available=False`` instead of raising ``IndexError``.
    """
    end = end or date.today()
    start = start or PROBE_START
    src, df = _fetch(start, end)
    n_sess = _n_sessions(df)
    depth = {
        "source": src,
        "n_bars": len(df),
        "n_sessions": n_sess,
        "span": (df.index[0], df.index[-1]) if len(df) else None,
    }

    if len(df) < _MIN_WINDOW_BARS:
        return {
            "depth": depth, "data_available": False, "powered": False,
            "cells": {}, "always_in": None, "start": start, "end": end,
        }

    always = _after_tax_metrics(_always_in(df), df.index)
    cells: dict = {}
    for r in TARGET_VARIANTS:
        sim = _build_cell(df, r)
        rand = _build_random_cell(df, r)
        cells[r] = {
            "metrics": _after_tax_metrics(sim, df.index),
            "random": _after_tax_metrics(rand, df.index),
            "always_in": always,
            "n_trades": sim["trade_count"],
            "sim": sim,
        }

    return {
        "depth": depth,
        "data_available": True,
        "powered": n_sess >= PROBE_MIN_SESSIONS,
        "cells": cells,
        "always_in": always,
        "start": start,
        "end": end,
    }


def _beats(cell: dict) -> Optional[bool]:
    """Directional read for a cell: does ORB beat BOTH random-entry AND always-in?

    Compared on after-tax US Calmar; NaN (ruin/degenerate) counts as "not beaten".
    Returns None if the cell's own Calmar is undefined.
    """
    c = cell["metrics"]["calmar_us"]
    if isinstance(c, float) and np.isnan(c):
        return None

    def _lt(x: float) -> bool:
        # ORB beats a baseline if its Calmar exceeds the baseline's (NaN baseline = ruin,
        # which ORB trivially beats when ORB is finite).
        return (isinstance(x, float) and np.isnan(x)) or c > x

    return _lt(cell["random"]["calmar_us"]) and _lt(cell["always_in"]["calmar_us"])


def _fmt(x, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x*100:+.1f}%" if pct else f"{x:.3f}"


def _label(r: Optional[float]) -> str:
    return "EOD-close" if r is None else f"R={int(r)}"


def _print_report(res: dict) -> None:
    print("\n" + "=" * 100)
    print("OPENING-RANGE BREAKOUT (ORB) FREE-DATA PROBE (#431) — long-only, session-flat")
    print("UNDERPOWERED directional read (free SPY 5-min ~n_w<=9), NOT a promotion test.")
    print("=" * 100)

    d = res["depth"]
    span = f"{d['span'][0]} -> {d['span'][1]}" if d["span"] else "no data"
    print(f"\nData source: {d['source']}   bars: {d['n_bars']}   sessions: {d['n_sessions']}")
    print(f"Span: {span}")
    print(f"Power floor (directional read): {PROBE_MIN_SESSIONS} sessions  ->  "
          f"{'POWERED' if res['powered'] else 'UNDERPOWERED / DATA-BLOCKED'}")

    if not res["data_available"]:
        print("\nDATA-BLOCKED: fetch returned too few bars to run the probe. The pre-registered")
        print("read needs the Alpaca paper/data keys (2016+ 5-min) or a paid intraday source.")
        return

    if not res["powered"]:
        print("\n*** The numbers below are a PLUMBING SMOKE on a shallow sample (n_sessions <")
        print("*** power floor). They are NOT the pre-registered directional read. DO NOT")
        print("*** interpret them as an ORB edge/no-edge verdict — the read is DATA-BLOCKED.")

    header = (f"{'variant':<12} {'CalmarUS':>9} {'CAGR':>8} {'maxDD':>8} {'#trd':>5} "
              f"{'rand':>8} {'always':>8} {'beats?':>7}")
    print("\n" + header)
    print("-" * len(header))
    for r in TARGET_VARIANTS:
        cell = res["cells"][r]
        m = cell["metrics"]
        beats = _beats(cell)
        bs = "n/a" if beats is None else ("YES" if beats else "no")
        print(f"{_label(r):<12} {_fmt(m['calmar_us']):>9} {_fmt(m['cagr_pretax'], pct=True):>8} "
              f"{_fmt(m['max_dd'], pct=True):>8} {cell['n_trades']:>5} "
              f"{_fmt(cell['random']['calmar_us']):>8} "
              f"{_fmt(cell['always_in']['calmar_us']):>8} {bs:>7}")

    print("\nLong/short caveat: the engine is long-only, so this is the LONG arm of the")
    print("Zarattini & Aziz long/short ORB. Costs: 5+5 bps/side (20 bps round trip).")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="backtest.run_orb_probe")
    parser.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    parser.add_argument("--start", default=None, help="first date (YYYY-MM-DD; default 2016-01-01)")
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else PROBE_START
    _print_report(run_orb(end=end, start=start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
