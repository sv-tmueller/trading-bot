"""Firing-rate calibration for the deterministic Elliott Wave labeler (#468).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls, no order endpoint. Modelled on
``run_candlestick_study.py --firing-rates`` and ``run_fx_plumbing_check.py``.

*** This is a CALIBRATION REPORT, not a strategy result. *** It measures how often the
labeler's structures complete on the real 1h EUR/USD frame and whether that rate is
sane -- it makes NO performance claim of any kind. Two rules are pinned by
``tests/test_run_fx_ew_calibration.py`` and must never be relaxed:

  - **Exempt from the power gate.** Per the candlestick precedent ("firing rates are a
    property of the detectors, not a performance claim, so a shallow frame answers them
    safely"), the power verdict is PRINTED but never gates this report -- even an
    UNDERPOWERED frame gets a firing-rate read.
  - **No performance number of any kind.** No Calmar, Sharpe, equity curve, PnL, "return"
    of any kind, win rate, or profit figure is ever printed here. A ``TOO_COMMON`` /
    ``TOO_RARE`` verdict is a finding to DISCLOSE, never a licence to retune ``theta`` in
    place -- theta is frozen (``elliott.THETA_GRID``); changing it needs a fresh freeze.

Data sources
------------
Two ways to supply bars, in this precedence:

  1. ``--data PATH`` -- a local OHLC file (CSV/Parquet, see ``intraday_data.load_local``
     for accepted column spellings), no network. See
     ``docs/runbooks/fx-1h-data-drop.md`` for the full contract.
  2. Otherwise, the FXCM H1 EUR/USD archive via ``run_fx_plumbing_check.build_history``
     (cache-first; pass ``--fetch`` to download any missing weekly files), then the
     frozen H1 load order (SUB_PLAN §2.1): drop Saturday bars -> drop the in-progress
     final bar -> ``fx_data.to_ohlc_frame`` (Mid side) -> ``intraday_data.validate_ohlc``.

Usage
-----
    python3 -m backtest.run_fx_ew_calibration [--data FILE] [--fetch] [--end-year YYYY]
        [--theta 0.003]
Exit codes: ``0`` the report ran (regardless of power); ``2`` no bars available at all.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from backtest import elliott as ew
from backtest import fx_data
from backtest import intraday_data as idata
from backtest import run_fx_plumbing_check as rfpc

#: Firing-rate bounds for a STRUCTURE (impulse or zigzag), diagnostic only -- gates
#: nothing in any grid. Mirrors candlestick.py's FIRING_RATE_MAX=0.25 / MIN=0.005
#: pattern, but scaled down: a multi-pivot wave structure is intrinsically far rarer
#: than a 1-3 bar candlestick pattern (#422's own 0.82 trades/day BTC-scalping estimate,
#: re-examined in the feasibility note §2.6, implies an order of magnitude below a
#: single-bar detector's rate). MAX=0.05: a structure completing on more than 1 in 20
#: bars would mean the grammar is essentially unconstrained, not discriminating.
#: MIN=0.0001: fewer than roughly 9 completions over the full ~88k-bar FXCM H1 cache
#: would be too rare for this calibration to say anything meaningful about the rate.
#:
#: NOTE: a TOO_COMMON/TOO_RARE verdict here is a finding to DISCLOSE. theta is frozen
#: (elliott.THETA_GRID) -- do not retune it in place; freeze any change as a fresh
#: pre-registration (mirrors the candlestick.py precedent verbatim).
FIRING_RATE_MAX = 0.05
FIRING_RATE_MIN = 0.0001


def _cache_identity_hash(root: str) -> Optional[str]:
    """``find <root> -type f | sort | xargs shasum -a 256 | shasum -a 256`` in Python:
    sha256 each file, sha256 the concatenation of ``<hex>  <path>\\n`` lines (sorted by
    path) -- a cache-integrity fingerprint. Returns ``None`` if the root doesn't exist.
    """
    if not os.path.isdir(root):
        return None
    lines = []
    for dirpath, _dirs, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            lines.append(f"{digest}  {path}\n")
    lines.sort()
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _load_fxcm_h1(*, fetch: bool, end_year: int) -> "tuple[pd.DataFrame, dict]":
    """Frozen H1 load order (SUB_PLAN §2.1): build_history -> drop_saturday_bars ->
    drop_in_progress_bar -> to_ohlc_frame(side='Mid'). Raises whatever
    ``run_fx_plumbing_check.build_history`` raises on a fully-empty, non-fetched cache
    (a ``SystemExit`` -- caught by the caller and turned into a DATA-BLOCKED exit)."""
    history, manifest = rfpc.build_history(fetch=fetch, end_year=end_year)
    history, n_saturday = fx_data.drop_saturday_bars(history)
    history = fx_data.drop_in_progress_bar(history)
    ohlc = fx_data.to_ohlc_frame(history, side="Mid")
    provenance = {
        "manifest": manifest,
        "n_saturday_dropped": n_saturday,
        "cache_root": fx_data.CACHE_ROOT,
        "cache_hash": _cache_identity_hash(fx_data.CACHE_ROOT),
    }
    return ohlc, provenance


def _leg_lengths_pips_and_bars(pivots: pd.DataFrame) -> "tuple[np.ndarray, np.ndarray]":
    """Per-leg length (consecutive pivot to pivot) in pips (1 pip = 0.0001) and in bars."""
    if len(pivots) < 2:
        return np.array([]), np.array([])
    prices = pivots["pivot_price"].to_numpy(dtype=float)
    idxs = pivots["pivot_idx"].to_numpy()
    pips = np.abs(np.diff(prices)) / 0.0001
    bars = np.diff(idxs).astype(float)
    return pips, bars


def _print_header(title: str) -> None:
    print("\n" + "=" * 96)
    print(title)
    print("=" * 96)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="backtest.run_fx_ew_calibration",
        description=(
            "Elliott Wave firing-rate CALIBRATION (#468) -- NOT a strategy result. "
            "See module docstring."
        ),
    )
    ap.add_argument("--data", default=None,
                     help="local OHLC file (CSV/Parquet); bypasses the FXCM fetch")
    ap.add_argument("--fetch", action="store_true",
                     help="download missing FXCM weekly files into the local cache")
    ap.add_argument("--end-year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--theta", type=float, default=ew.DEFAULT_THETA,
                     help="reversal threshold used for the structure report (default 0.30%%)")
    args = ap.parse_args(argv)

    provenance: dict = {}
    if args.data:
        source = f"local:{args.data}"
        try:
            ohlc = idata.load_local(args.data)
        except Exception as exc:                        # noqa: BLE001 - report, never crash
            print(f"DATA-BLOCKED: could not load {args.data}: {exc}", file=sys.stderr)
            return 2
    else:
        source = "fxcm:H1:EURUSD"
        try:
            ohlc, provenance = _load_fxcm_h1(fetch=args.fetch, end_year=args.end_year)
        except SystemExit as exc:
            print(f"DATA-BLOCKED: {exc}", file=sys.stderr)
            return 2

    if ohlc is None or len(ohlc) == 0:
        print("DATA-BLOCKED: no bars available.", file=sys.stderr)
        return 2

    ohlc = idata.validate_ohlc(ohlc)
    power = idata.describe_power(ohlc)

    print("*** CALIBRATION REPORT -- no strategy claim. See module docstring. ***")
    print("Elliott Wave firing-rate calibration (#468)")
    print(f"Run started: {datetime.now(timezone.utc).isoformat()}")
    print(f"source: {source}")

    if provenance:
        _print_header("1. PROVENANCE")
        print(f"cache root: {provenance.get('cache_root')}")
        print(f"cache identity hash: {provenance.get('cache_hash')}")
        print(f"Saturday-UTC rows dropped: {provenance.get('n_saturday_dropped')}")
        manifest = provenance.get("manifest") or {}
        if manifest:
            completeness = fx_data.completeness_report(manifest)
            print("completeness by year (missing weeks / rows found / pct rows missing):")
            for year, rep in sorted(completeness.items()):
                print(
                    f"  {year}: missing_weeks={rep['n_missing_weeks']} "
                    f"rows_found={rep['n_rows_found']} "
                    f"pct_rows_missing={rep['pct_rows_missing']*100:.2f}%"
                )

    _print_header("2. POWER (printed, NOT a gate for this report)")
    print(power.summary())
    print(f"n_bars={power.n_bars}  n_sessions={power.n_sessions}  "
          f"span={power.first} -> {power.last}")
    promotable = power.verdict == "PROMOTABLE" and power.n_windows >= idata.PROMOTION_N_W
    print(
        f"assert verdict == 'PROMOTABLE' and n_windows >= {idata.PROMOTION_N_W}: {promotable}"
    )

    _print_header("3. PIVOTS PER YEAR, BY THETA (elliott.THETA_GRID -- frozen, not tuned here)")
    span_years = (power.last - power.first).days / 365.25 if power.n_bars and power.last else 0.0
    for theta in ew.THETA_GRID:
        pivots_theta = ew.find_pivots(ohlc, theta=theta)
        rate = (len(pivots_theta) / span_years) if span_years else float("nan")
        print(f"theta={theta:.2%}  pivots={len(pivots_theta)}  pivots/year={rate:.1f}")

    _print_header(f"4. STRUCTURES AT theta={args.theta:.2%} (--theta; default frozen 0.30%)")
    pivots = ew.find_pivots(ohlc, theta=args.theta)
    labels = ew.label_waves(ohlc, theta=args.theta)
    pips, bars = _leg_lengths_pips_and_bars(pivots)
    if len(pips):
        print(
            f"leg length (pips): median={np.median(pips):.1f}  "
            f"p25={np.percentile(pips, 25):.1f}  p75={np.percentile(pips, 75):.1f}"
        )
        print(
            f"leg length (bars): median={np.median(bars):.1f}  "
            f"p25={np.percentile(bars, 25):.1f}  p75={np.percentile(bars, 75):.1f}"
        )
    else:
        print("leg length: no confirmed legs at this theta")

    print()
    print(f"{'kind':<10} {'direction':<10} {'count':>7} {'rate':>9}  verdict")
    n_bars = power.n_bars or 1
    for kind in ("impulse", "zigzag"):
        for direction in ("up", "down"):
            count = int(
                ((labels["kind"] == kind) & (labels["direction"] == direction)).sum()
            ) if len(labels) else 0
            rate = count / n_bars
            if rate > FIRING_RATE_MAX:
                verdict = "TOO_COMMON"
            elif rate < FIRING_RATE_MIN:
                verdict = "TOO_RARE"
            else:
                verdict = "ok"
            print(f"{kind:<10} {direction:<10} {count:>7} {rate:>8.4%}  {verdict}")
    print(f"bounds: min {FIRING_RATE_MIN:.2%}  max {FIRING_RATE_MAX:.0%}")

    if len(labels):
        completion_bar_idx = labels["end_idx"].to_numpy()
        if len(completion_bar_idx) > 1:
            gaps = np.diff(np.sort(completion_bar_idx)).astype(float)
            print(
                f"median bars between consecutive completions (hold-duration PROXY, "
                f"no exit model exists in this package): {np.median(gaps):.1f}"
            )
        print()
        print("realized ratio distributions (pure description, not a fit):")
        for col in ("w2_w1", "w3_w1", "w4_w3", "w5_w1", "wb_wa", "wc_wa"):
            vals = labels[col].dropna()
            if len(vals):
                print(f"  median {col} = {vals.median():.3f}  (n={len(vals)})")
    else:
        print("no completed structures at this theta -- nothing to describe")

    _print_header("5. REPRODUCIBILITY")
    input_bytes = ohlc["Close"].to_numpy(dtype=float).tobytes()
    input_hash = hashlib.sha256(input_bytes).hexdigest()
    if len(labels):
        digest_cols = ["kind", "direction", "start_idx", "end_idx"]
        label_bytes = labels[digest_cols].astype(str).to_numpy().tobytes()
    else:
        label_bytes = b"<no labels>"
    label_hash = hashlib.sha256(label_bytes).hexdigest()
    print(f"sha256(input)={input_hash}")
    print(f"sha256(label digest)={label_hash}")

    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
