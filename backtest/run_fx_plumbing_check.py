"""FXCM 4h EUR/USD PLUMBING CHECK (#371, batch #370).

*** This is a PLUMBING CHECK, not a strategy result. *** It proves the data
loader, resampler, validator, cost model, and bar-loop simulator fit
together end to end on real data — it makes NO strategy claim. The trivial
SMA(50) baseline used below is arbitrary (picked to exercise both trade
directions), not tuned, and its costs-off/on delta is the deliverable, not
its absolute P/L.

Research-only. Lives in ``backtest/`` and is never imported by
``supabase/functions/``. No LLM, no broker calls, no orders.

Data source & re-fetch instructions
------------------------------------
See ``backtest/fx_data.py``'s module docstring for the FXCM archive URL
template, week-numbering convention, and the empirical archive-timezone
finding. In short::

    venv/bin/python backtest/run_fx_plumbing_check.py --fetch

downloads any missing weekly files (2012 -> the most recent week the
archive has published) into the gitignored ``data/fxcm/H1/EURUSD/`` cache.
Without ``--fetch`` this script is CACHE-ONLY and exits with
``SystemExit("BLOCKED: ...")`` if the cache is completely empty.

Usage
-----
    venv/bin/python backtest/run_fx_plumbing_check.py [--fetch] [--end-year YYYY]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from backtest import fx_costs, fx_data, fx_execution

START_YEAR = 2012
_WEEK_NUMBERS = list(range(1, 54))  # FXCM's own numbering: 1..53 (53 absent most years)

# Trivial baseline params — picked from the gate doc's own R grid, NOT tuned.
SMA_WINDOW = 50
R_PCT = 0.0030  # 30bp symmetric TP/SL
STARTING_EQUITY = 100_000.0

# Pre-registered BLOCKED thresholds (#371 SUB_PLAN) — evaluated per COMPLETE
# historical year only; the current, still-publishing year is reported but
# explicitly excluded from the threshold check (see main()). Crossed-quotes
# shares the same 0.1% threshold family as coherence (reviewer round-1
# must-fix 3).
MAX_PCT_MISSING_WEEKS = 0.02
MAX_PCT_MISSING_ROWS = 0.05
MAX_PCT_COHERENCE_VIOLATIONS = 0.001
MAX_PCT_CROSSED_QUOTES = 0.001

RE_FETCH_INSTRUCTIONS = (
    "Re-fetch instructions: data source is FXCM's public H1 candle archive "
    "at https://candledata.fxcorporate.com/H1/EURUSD/<year>/<week>.csv.gz "
    "(week numbers are FXCM's own numbering, not ISO -- see backtest/fx_data.py's "
    "module docstring). Run with --fetch to download any missing weekly files "
    "into the gitignored data/fxcm/H1/EURUSD/ cache; without --fetch this "
    "script is CACHE-ONLY and exits BLOCKED if the cache is empty."
)


def build_history(*, fetch: bool, end_year: int) -> tuple:
    """Load (or fetch) every available FXCM week from START_YEAR..end_year,
    concatenate into one sorted, deduped H1 DataFrame, and build the
    ``{year: {week: n_rows_or_None}}`` manifest ``fx_data.completeness_report``
    consumes.

    A week is recorded as ``None`` (missing) whether the archive itself has
    no such file (``WeekNotFoundError``, a real 404) or it simply isn't
    cached yet and ``fetch=False`` (``FileNotFoundError``) — this script
    cannot distinguish the two without hitting the network, which is exactly
    the distinction ``--fetch`` resolves.
    """
    manifest: dict = {}
    frames = []
    for year in range(START_YEAR, end_year + 1):
        manifest[year] = {}
        for week in _WEEK_NUMBERS:
            try:
                raw = fx_data.get_week_bytes(year, week, fetch=fetch)
            except (fx_data.WeekNotFoundError, FileNotFoundError):
                manifest[year][week] = None
                continue
            df = fx_data.parse_week_csv(raw)
            manifest[year][week] = len(df)
            frames.append(df)

    if not frames:
        raise SystemExit(
            "BLOCKED: no cached FXCM data found and --fetch was not given. "
            "Re-run with --fetch to populate data/fxcm/H1/EURUSD/ (see "
            "backtest/fx_data.py's module docstring for the archive URL "
            "template and re-fetch instructions)."
        )

    history = pd.concat(frames).sort_index()
    history = history[~history.index.duplicated(keep="first")]
    return history, manifest


def evaluate_blocked_reasons(
    completeness: dict,
    *,
    complete_years: list,
    pct_coherence: float,
    pct_crossed_quotes: float,
    n_saturday_bars: int,
    max_pct_missing_weeks: float = MAX_PCT_MISSING_WEEKS,
    max_pct_missing_rows: float = MAX_PCT_MISSING_ROWS,
    max_pct_coherence: float = MAX_PCT_COHERENCE_VIOLATIONS,
    max_pct_crossed_quotes: float = MAX_PCT_CROSSED_QUOTES,
) -> list:
    """Pure threshold-evaluation helper (reviewer round-1 must-fix 3):
    mechanically decides which pre-registered BLOCKED thresholds are
    crossed, given already-computed validation numbers. No I/O, no
    printing — every crossing is APPENDED to the returned list (nothing is
    short-circuited), so ``main()`` can print every reason before deciding
    whether to continue.

    Parameters
    ----------
    completeness:
        ``fx_data.completeness_report()``'s output:
        ``{year: {..., "pct_missing_weeks", "pct_rows_missing"}}``.
    complete_years:
        Years to actually evaluate against the missing-weeks/rows
        thresholds (the current, still-publishing year is excluded by the
        caller before this function ever sees it as "complete").
    pct_coherence, pct_crossed_quotes:
        Overall violation rates (fraction, e.g. 0.0238 for 2.38%).
    n_saturday_bars:
        From ``fx_data.check_weekend_bars`` — ANY Saturday-UTC bar is a
        hard BLOCKED signal (the mechanical check that would have caught
        reviewer round-1 must-fix 1's timezone bug).

    Returns
    -------
    List of ``(label, reason)`` tuples; empty means nothing crossed.
    """
    reasons: list = []
    for year in complete_years:
        rep = completeness[year]
        if rep["pct_missing_weeks"] > max_pct_missing_weeks:
            reasons.append((
                year,
                f"missing weeks {rep['pct_missing_weeks']*100:.2f}% > "
                f"{max_pct_missing_weeks*100:.2f}%",
            ))
        if rep["pct_rows_missing"] > max_pct_missing_rows:
            reasons.append((
                year,
                f"missing rows {rep['pct_rows_missing']*100:.2f}% > "
                f"{max_pct_missing_rows*100:.2f}%",
            ))
    if pct_coherence > max_pct_coherence:
        reasons.append((
            "all",
            f"coherence violation rate {pct_coherence*100:.4f}% > "
            f"{max_pct_coherence*100:.3f}%",
        ))
    if pct_crossed_quotes > max_pct_crossed_quotes:
        reasons.append((
            "all",
            f"crossed-quotes rate {pct_crossed_quotes*100:.4f}% > "
            f"{max_pct_crossed_quotes*100:.3f}%",
        ))
    if n_saturday_bars > 0:
        reasons.append((
            "all",
            f"{n_saturday_bars} Saturday-UTC bars found (expected 0 -- "
            "timezone-localization bug indicator)",
        ))
    return reasons


def _classify_gaps(history: pd.DataFrame) -> dict:
    """Friday-close -> Sunday-open weekend gaps are EXPECTED (sanity, not a
    failure per the SUB_PLAN); anything else is an unexplained gap worth
    flagging. A gap is classified 'weekend' if it falls in [40h, 56h]
    (covers the normal ~48-51h FX weekend). NOTE: this window does NOT cover
    a full ~72h holiday-Monday gap (weekend + a whole extra closed day) —
    those land in "other" gaps instead and are explained there (see the
    research note's month-distribution breakdown, which shows the
    Dec/Jan concentration this produces)."""
    diffs = history.index.to_series().diff().dropna()
    non_hourly = diffs[diffs != pd.Timedelta("1h")]
    weekend_like = non_hourly[
        (non_hourly >= pd.Timedelta("40h")) & (non_hourly <= pd.Timedelta("56h"))
    ]
    other = non_hourly[~non_hourly.index.isin(weekend_like.index)]
    return {
        "n_weekend_gaps": len(weekend_like),
        "weekend_gap_hours_median": (
            float(weekend_like.dt.total_seconds().median() / 3600) if len(weekend_like) else None
        ),
        "n_other_gaps": len(other),
        "other_gap_samples": list(other.index[:10]),
    }


def _sma_signal(mid_close: pd.Series, window: int) -> pd.Series:
    """Trivial baseline: close vs N-bar SMA -- long above, short below.
    Exercises both trade directions; NOT a strategy claim (see banner)."""
    sma = mid_close.rolling(window).mean()
    sig = pd.Series(0, index=mid_close.index)
    sig[mid_close > sma] = 1
    sig[mid_close < sma] = -1
    return sig


def _print_header(title: str) -> None:
    print("\n" + "=" * 96)
    print(title)
    print("=" * 96)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.run_fx_plumbing_check",
        description=(
            "FXCM 4h EUR/USD PLUMBING CHECK (#371, batch #370) -- proves the "
            "data loader, resampler, validator, cost model, and bar-loop "
            "simulator fit together end to end on real archive data. NOT a "
            "strategy result. " + RE_FETCH_INSTRUCTIONS
        ),
        epilog=RE_FETCH_INSTRUCTIONS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="download any missing weekly files into the local cache (else cache-only)",
    )
    parser.add_argument(
        "--end-year", type=int, default=datetime.now(timezone.utc).year,
        help="last calendar year to include (default: current UTC year)",
    )
    args = parser.parse_args(argv)

    print("*** PLUMBING CHECK — no strategy claim. See module docstring. ***")
    print(f"FXCM H1 EUR/USD -> 4h harness plumbing check (#371, batch #370)")
    print(f"Run started: {datetime.now(timezone.utc).isoformat()}")
    print(f"Year range: {START_YEAR}-{args.end_year}  |  fetch={'ON' if args.fetch else 'cache-only'}")

    history, manifest = build_history(fetch=args.fetch, end_year=args.end_year)

    _print_header("1. RAW H1 HISTORY")
    print(f"Rows: {len(history)}  |  {history.index[0]} -> {history.index[-1]}")

    # --- Validation ---------------------------------------------------
    _print_header("2. VALIDATION")
    dupes = fx_data.check_duplicates(history)
    mono = fx_data.check_monotonic(history)
    coherence = fx_data.check_ohlc_coherence(history)
    weekend_bars = fx_data.check_weekend_bars(history)
    gaps = _classify_gaps(history)
    print(f"Duplicates: {dupes['n_duplicates']}")
    print(f"Monotonic: {mono['is_monotonic']}  (n_non_monotonic={mono['n_non_monotonic']})")
    print(f"OHLC coherence violations: {coherence['n_coherence_violations']}")
    print(f"Crossed quotes (ask<bid): {coherence['n_crossed_quotes']}")
    print(f"Non-positive prices: {coherence['n_non_positive_prices']}")
    print(
        f"Saturday-UTC bars: {weekend_bars['n_saturday_bars']} (expected 0 -- "
        f"mechanical timezone-localization check) | Sunday-UTC bars: "
        f"{weekend_bars['n_sunday_bars']} (session-open bars, expected > 0)"
    )
    pct_coherence = coherence["n_coherence_violations"] / max(len(history), 1)
    pct_crossed_quotes = coherence["n_crossed_quotes"] / max(len(history), 1)
    print(f"Coherence violation rate: {pct_coherence*100:.4f}%  (threshold: {MAX_PCT_COHERENCE_VIOLATIONS*100:.3f}%)")
    print(f"Crossed-quotes rate: {pct_crossed_quotes*100:.4f}%  (threshold: {MAX_PCT_CROSSED_QUOTES*100:.3f}%)")
    print(f"Weekend gaps (Fri close -> Sun open): {gaps['n_weekend_gaps']} "
          f"(median {gaps['weekend_gap_hours_median']}h)")
    print(f"Other (unexplained) gaps: {gaps['n_other_gaps']}")
    if gaps["other_gap_samples"]:
        print(f"  sample timestamps: {gaps['other_gap_samples']}")

    completeness = fx_data.completeness_report(manifest)
    _print_header("3. WEEKLY-FILE + ROW-COUNT COMPLETENESS BY YEAR")
    print(f"{'year':>6} | {'missing wks':>11} | {'pct wks':>8} | {'rows found':>10} | {'pct rows missing':>17}")
    print("-" * 96)
    complete_years = [y for y in completeness if y != args.end_year]
    for year, rep in completeness.items():
        flag = ""
        if year in complete_years:
            if rep["pct_missing_weeks"] > MAX_PCT_MISSING_WEEKS:
                flag += " [WEEKS>2%]"
            if rep["pct_rows_missing"] > MAX_PCT_MISSING_ROWS:
                flag += " [ROWS>5%]"
        else:
            flag = " (current/partial year — archive publishing lag, excluded from BLOCKED check)"
        print(
            f"{year:>6} | {rep['n_missing_weeks']:>11} | {rep['pct_missing_weeks']*100:7.2f}% | "
            f"{rep['n_rows_found']:>10} | {rep['pct_rows_missing']*100:16.2f}%{flag}"
        )

    blocked_reasons = evaluate_blocked_reasons(
        completeness,
        complete_years=complete_years,
        pct_coherence=pct_coherence,
        pct_crossed_quotes=pct_crossed_quotes,
        n_saturday_bars=weekend_bars["n_saturday_bars"],
    )
    if blocked_reasons:
        print("\nBLOCKED thresholds crossed (mechanical gate fired -- investigate before proceeding):")
        for year, reason in blocked_reasons:
            print(f"  - {year}: {reason}")

    # --- Empirical spread ------------------------------------------------
    _print_header("4. EMPIRICAL SPREAD (FXCM bid/ask, pips) — measurement/cross-check only")
    spread = fx_data.empirical_spread_pips(history)
    print(f"Overall: median={spread.median():.2f}  mean={spread.mean():.2f}  p95={spread.quantile(0.95):.2f}")
    by_hour = spread.groupby(history.index.hour).median()
    print("By hour of day (UTC), median pips:")
    print(by_hour.round(2).to_string())
    by_year = spread.groupby(history.index.year).median()
    print("\nBy year, median pips:")
    print(by_year.round(2).to_string())
    print(
        "\nReconciliation vs #369 gate doc presets (spot/CFD spread component only): "
        "IC Markets ~0.1 pip avg (1.0 pessimistic), XTB ~0.5 pip min. "
        "Simulation below runs on MID prices with the gate doc's venue presets "
        "as the cost model (target venues are IC/XTB/6E, not FXCM retail); "
        "FXCM bid/ask is measurement/cross-check only, per the SUB_PLAN."
    )

    _print_header("4b. CROSSED-QUOTES BY HOUR OF DAY (UTC) — magnitude + distribution")
    crossed_mask = history["AskClose"] < history["BidClose"]
    crossed_by_hour = crossed_mask.groupby(history.index.hour).sum().astype(int)
    print("Crossed-quote count by hour of day (UTC):")
    print(crossed_by_hour.to_string())
    if crossed_mask.any():
        neg = (history.loc[crossed_mask, "AskClose"] - history.loc[crossed_mask, "BidClose"]) / 0.0001
        print(
            f"\nMagnitude (pips, negative=crossed): median={neg.median():.2f}  "
            f"mean={neg.mean():.2f}  max_abs={neg.abs().max():.2f}"
        )

    # --- Resample to 4h ---------------------------------------------------
    _print_header("5. RESAMPLE TO 4h (fixed grid 00/04/08/12/16/20 UTC)")
    bars_4h, resample_report = fx_data.resample_to_4h(history)
    # Drop the in-progress final bar AT LOAD, in fx_data.py (no-look-ahead
    # convention) — applies even to a static archive pull, so the harness is
    # safe if ever pointed at a live-updating cache.
    n_bars_before_drop = resample_report["n_bars"]
    bars_4h = fx_data.drop_in_progress_bar(bars_4h)
    print(
        f"4h bars: {n_bars_before_drop} before dropping the in-progress final bar, "
        f"{len(bars_4h)} after (the {len(bars_4h)} figure is what feeds the baseline "
        f"below)  |  partial boundary buckets: {resample_report['n_partial_boundary_buckets']}"
    )
    n_weeks_found = sum(1 for weeks in manifest.values() for n in weeks.values() if n is not None)
    print(f"Expected ~30 bars/week x {n_weeks_found} weeks found ~= {30*n_weeks_found} (sanity order-of-magnitude)")

    # --- Trivial baseline: SMA(50) on 4h mid closes -----------------------
    _print_header("6. TRIVIAL BASELINE — SMA(50), 4h mid close, symmetric R=30bp (NOT a strategy claim)")
    mid_bars = bars_4h.rename(columns={
        "MidOpen": "Open", "MidHigh": "High", "MidLow": "Low", "MidClose": "Close",
    })[["Open", "High", "Low", "Close"]]
    signal = _sma_signal(mid_bars["Close"], SMA_WINDOW)

    off = fx_execution.simulate_fx(
        mid_bars, signal, tp_pct=R_PCT, sl_pct=R_PCT, cost_rt=0.0, overnight=None,
        starting_equity=STARTING_EQUITY,
    )
    print(f"{'venue':<28} | {'cost mode':<12} | {'net return':>11} | {'max DD':>8} | {'#trades':>7}")
    print("-" * 96)
    print(
        f"{'(costs OFF)':<28} | {'-':<12} | {off['total_return']*100:+10.2f}% | "
        f"{off['max_drawdown']*100:7.1f}% | {off['trade_count']:7d}"
    )

    for key, preset in fx_costs.PRESETS.items():
        for mode, cost_bp in (("base", preset.base_bp), ("pessimistic", preset.pessimistic_bp)):
            overnight = None
            if preset.has_overnight:
                overnight = {
                    1: fx_costs.overnight_bp_for(preset, "long") / 10_000.0,
                    -1: fx_costs.overnight_bp_for(preset, "short") / 10_000.0,
                }
            on = fx_execution.simulate_fx(
                mid_bars, signal, tp_pct=R_PCT, sl_pct=R_PCT,
                cost_rt=cost_bp / 10_000.0, overnight=overnight,
                starting_equity=STARTING_EQUITY,
            )
            print(
                f"{preset.name:<28} | {mode:<12} | {on['total_return']*100:+10.2f}% | "
                f"{on['max_drawdown']*100:7.1f}% | {on['trade_count']:7d}"
            )

    print(f"\nBaseline costs-off/on DELTA is the pipeline proof, not a strategy result — "
          f"see docs/research/ note for the full write-up.")
    print("\nDone. All numbers above came from the cached/fetched FXCM archive; no price was fabricated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
