"""MES swing-contracts study — frozen 24-cell grid (#457, PR A of the two-PR delivery).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls. This PR fetches and references NO real SPY (or any other) market
data anywhere — every test in ``tests/test_run_mes_swing_study.py`` runs on synthetic OHLC.
The live read (PR B) fetches SPY daily bars via the already-frozen
``run_candlestick_study._fetch_daily`` helper, imported unchanged.

What this answers
------------------
Do any of 12 classic edge-trigger arms (trend/momentum/mean-reversion, long+short),
re-parameterized for a **daily equity-index bar** with a **turtle-style ATR bracket exit**,
clear the frozen SPY buy-and-hold after-tax Calmar bar under the MES wrapper's own verified
cost bracket? See ``docs/research/2026-07-26-mes-contracts-survey-preregistration.md`` for
the full pre-registration (grid rationale, registry-survival justification per arm, cost/
capital disclosures, the binding stopping rule).

Frozen grid (D1)
----------------
12 arms x R in {2, 3} = 24 cells. Every arm is an EDGE trigger (fires once per excursion,
never re-triggers while the underlying state persists) — trend arms reuse
``fx_signals.sma_cross_signal`` directly (already edge-native: 0 except at the exact
crossing bar); momentum/mean-reversion arms reuse ``fx_signals.roc_signal``/``rsi_signal``
(persistent state) and derive the edge via ``_edge_trigger`` (first bar of each same-signed
run). ``build_cell`` shifts the edge by one bar (``signal.shift(1)``), so entries fire at the
next bar's open — no look-ahead.

Exit geometry, frozen verbatim from the Turtle convention
(``run_turtle_breakout._bracket_levels``): stop = entry - 2*ATR(20 Wilder, read at t-1),
target = entry + R*ATR(20), mirrored for shorts (stop above entry, target below). Both
close-out modes are off (``eow_close_out=False``, ``session_close_out=False``) and
``max_bars=None`` — the only exits are stop, target, and end-of-window, exactly like the
candlestick precedent.

Cost model (D4): two co-primary presets, ``commission_bps`` = round-trip/2, ``slippage_bps``
= 0 (the RT figure already carries the spread leg per the spec-verification note). A cell
"clears" only at BOTH presets.

Scoring (D3): per-cell primary statistic is the MEDIAN of the per-window (calendar-year
12-month windows, 2013-2025 primary set capped at the frozen ``PRIMARY_WINDOW_END``
(2025-12-31) so a trailing partial year is never scored, n_w=13 when the frame spans it)
after-tax Calmar under the German ``annual_netting`` tax mode — the cell clears only if that
median exceeds ``MES_SURVEY_BAR`` AND the WORST scored window stays positive. Secondary,
reported but never verdict-bearing: full-window ``calmar_us``/``calmar_de`` (deduct-at-exit,
cross-family comparability with turtle/candlestick) and an all-available-window (1994->
whenever the frame reaches back that far, uncapped by ``PRIMARY_WINDOW_END``) median/worst as
an era-sensitivity read. Both secondary reads and the primary statistic are also computed for
the ``always_in`` benchmark and printed alongside every cell (stopping-rule condition 3).

Run: ``python3 -m backtest.run_mes_swing_study [--data FILE] [--vehicle SPY] [--end ...]``
Exit codes: ``0`` the grid ran; ``2`` data unavailable or underpowered (no table printed).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Callable, Optional, Tuple

import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange

from backtest import fx_signals
from backtest import intraday_data as idata
from backtest import tax
from backtest.bracket import LONG, SHORT, simulate_bracket
from backtest.regime import STARTING_CASH
from backtest.run_candidate_survey import _curve_metrics
from backtest.run_candlestick_study import SPY_BAR as _CANDLESTICK_SPY_BAR
from backtest.run_candlestick_study import _fetch_daily
from backtest.walkforward import _slice_windows

# --- Edge-trigger derivation -----------------------------------------------------------


def _edge_trigger(cond: pd.Series) -> pd.Series:
    """True only on the FIRST bar of each True-run in ``cond`` — no re-trigger while the
    underlying state persists. Turns a persistent state test (e.g. "ROC > 0") into a single
    entry EVENT at the bar the state was entered, exactly what "crosses above/below" means
    in the frozen grid's arm table.
    """
    c = cond.fillna(False)
    prev = c.shift(1, fill_value=False)
    return c & ~prev


def _sma_cross_edge(close: pd.Series, fast: int, slow: int, direction: str) -> pd.Series:
    """T1/T2: ``fx_signals.sma_cross_signal`` is already EDGE-NATIVE (0 except at the exact
    crossing bar, by construction of its own cross_up/cross_down boolean masks) — select
    this arm's direction with no further derivation."""
    sig = fx_signals.sma_cross_signal(close, fast, slow)
    return sig == (1 if direction == LONG else -1)


def _roc_cross_edge(close: pd.Series, n: int, direction: str) -> pd.Series:
    """M1/M2: ``fx_signals.roc_signal`` is a PERSISTENT state (stays +1 every bar ROC(n)
    stays positive) — edge-trigger it so a long streak fires once, at the crossing bar."""
    state = fx_signals.roc_signal(close, n)
    target = 1 if direction == LONG else -1
    return _edge_trigger(state == target)


def _rsi_cross_edge(close: pd.Series, n: int, low: float, high: float, direction: str) -> pd.Series:
    """V1/V2: ``fx_signals.rsi_signal`` is likewise persistent while RSI stays past the
    threshold; edge-trigger to the first bar of each excursion."""
    state = fx_signals.rsi_signal(close, n, low, high)
    target = 1 if direction == LONG else -1
    return _edge_trigger(state == target)


# --- Frozen 12-arm registry (D1) --------------------------------------------------------

ArmSignalFn = Callable[[pd.DataFrame], pd.Series]

#: (arm_id, direction, signal_fn). ``signal_fn(df)`` returns a boolean Series aligned to
#: ``df.index`` -- True at the SIGNAL bar (not yet shifted to the entry bar; ``build_cell``
#: does that). Six families x {long, short} = 12 arms, per the sub-plan's frozen table.
ARMS: Tuple[Tuple[str, str, ArmSignalFn], ...] = (
    ("T1L", LONG, lambda df: _sma_cross_edge(df["Close"], 10, 50, LONG)),
    ("T1S", SHORT, lambda df: _sma_cross_edge(df["Close"], 10, 50, SHORT)),
    ("T2L", LONG, lambda df: _sma_cross_edge(df["Close"], 20, 100, LONG)),
    ("T2S", SHORT, lambda df: _sma_cross_edge(df["Close"], 20, 100, SHORT)),
    ("M1L", LONG, lambda df: _roc_cross_edge(df["Close"], 63, LONG)),
    ("M1S", SHORT, lambda df: _roc_cross_edge(df["Close"], 63, SHORT)),
    ("M2L", LONG, lambda df: _roc_cross_edge(df["Close"], 126, LONG)),
    ("M2S", SHORT, lambda df: _roc_cross_edge(df["Close"], 126, SHORT)),
    ("V1L", LONG, lambda df: _rsi_cross_edge(df["Close"], 2, 10, 90, LONG)),
    ("V1S", SHORT, lambda df: _rsi_cross_edge(df["Close"], 2, 10, 90, SHORT)),
    ("V2L", LONG, lambda df: _rsi_cross_edge(df["Close"], 14, 30, 70, LONG)),
    ("V2S", SHORT, lambda df: _rsi_cross_edge(df["Close"], 14, 30, 70, SHORT)),
)

R_GRID: Tuple[float, ...] = (2.0, 3.0)
N_CELLS = len(ARMS) * len(R_GRID)          # 24 -- the multiplicity count (D2)
#: Fresh family (D2): round 1 has no prior trials to inherit, so cumulative == this grid.
CUMULATIVE_N = N_CELLS

# --- ATR bracket geometry, frozen verbatim from the Turtle convention (D1) -------------

ATR_WINDOW = 20
STOP_N = 2.0


def _atr(df: pd.DataFrame, window: int = ATR_WINDOW) -> pd.Series:
    """ATR (Wilder) via ``ta`` — matches ``run_turtle_breakout._atr`` exactly."""
    return AverageTrueRange(
        df["High"], df["Low"], df["Close"], window=window
    ).average_true_range()


def _bracket_levels(
    df: pd.DataFrame, entry_trigger: pd.Series, r: float, direction: str,
    *, slippage_bps: float = 0.0,
) -> Tuple[pd.Series, pd.Series]:
    """Absolute stop/target levels, mirrored for shorts.

    Long:  stop = entry - 2*ATR(t-1), target = entry + R*ATR(t-1).
    Short: stop = entry + 2*ATR(t-1), target = entry - R*ATR(t-1).
    ``entry ~= Open*(1 +/- slip)`` — the same convention ``simulate_bracket`` fills at.
    """
    n_signal = _atr(df).shift(1)
    slip = slippage_bps / 10_000.0
    if direction == SHORT:
        entry_ref = df["Open"] * (1 - slip)
        stop = entry_ref + STOP_N * n_signal
        target = entry_ref - r * n_signal
    else:
        entry_ref = df["Open"] * (1 + slip)
        stop = entry_ref - STOP_N * n_signal
        target = entry_ref + r * n_signal
    stop = stop.where(entry_trigger)
    target = target.where(entry_trigger)
    return stop, target


# --- Cost model (D4): two co-primary presets --------------------------------------------

#: Verified MES round-trip bp bracket, spec-verification §4 at L=7000 (the worst-bp end of
#: the frozen 7000-8000 index-level bracket): base 0.70 bp, pessimistic 1.06 bp round trip.
BASE_COST_RT_BP = 0.70
PESSIMISTIC_COST_RT_BP = 1.06

#: (label, commission_bps PER SIDE == RT/2). slippage is pinned to 0 -- the RT figure
#: already includes the spread leg (spec-verification §4's inherited-convention disclosure).
COST_PRESETS: Tuple[Tuple[str, float], ...] = (
    ("base", BASE_COST_RT_BP / 2.0),
    ("pessimistic", PESSIMISTIC_COST_RT_BP / 2.0),
)
SLIPPAGE_BPS = 0.0
RANDOM_SEED = 42

#: Frozen bar (verbatim from the forex 4h survey's own computation, #398 §4). A unit test
#: pins equality against run_candlestick_study.SPY_BAR so the two constants cannot drift.
MES_SURVEY_BAR = 1.3085475049604838
assert MES_SURVEY_BAR == _CANDLESTICK_SPY_BAR  # drift-proofing, enforced at import time too

#: Primary per-window statistic basis (D3): calendar-year 12-month windows, 2013-2025.
PRIMARY_WINDOW_START = date(2013, 1, 1)
#: Frozen cap on the primary (verdict-bearing) window set (round-1 review finding 2): the
#: bar's own survey excludes a trailing partial year, so the primary set must too -- only
#: FULL calendar-year windows with te <= this date are scored. The era read (all-available
#: windows) stays un-capped so it keeps reading whatever the frame actually spans.
PRIMARY_WINDOW_END = date(2025, 12, 31)


# --- Cell construction --------------------------------------------------------------------


def build_cell(
    df: pd.DataFrame, arm: Tuple[str, str, ArmSignalFn], r: float,
    commission_bps: float, slippage_bps: float = SLIPPAGE_BPS,
) -> dict:
    """One frozen MES-swing cell: detect the arm's edge, shift to next-open, ATR-bracket."""
    _, direction, signal_fn = arm
    signal = signal_fn(df)
    entry_trigger = signal.shift(1, fill_value=False)
    stop, target = _bracket_levels(df, entry_trigger, r, direction, slippage_bps=slippage_bps)
    return simulate_bracket(
        df, entry_trigger, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=slippage_bps, commission_bps=commission_bps,
        eow_close_out=False, session_close_out=False,
        direction=direction, max_bars=None,
    )


def build_random_cell(
    df: pd.DataFrame, arm: Tuple[str, str, ArmSignalFn], r: float,
    commission_bps: float, slippage_bps: float = SLIPPAGE_BPS, seed: int = RANDOM_SEED,
) -> dict:
    """Random-entry twin: same entry COUNT, same geometry/direction/cost, entries shuffled.

    Mirrors ``run_turtle_breakout._build_random_cell`` exactly. The control that separates
    "this arm has edge" from "any ATR bracket with this geometry would have done that".
    """
    _, direction, signal_fn = arm
    signal = signal_fn(df)
    real_trigger = signal.shift(1, fill_value=False)
    k = int(real_trigger.sum())
    n_signal = _atr(df).shift(1)
    valid = np.flatnonzero((~n_signal.isna()).to_numpy())
    rng = np.random.default_rng(seed)
    trig = pd.Series(False, index=df.index)
    if k > 0 and len(valid) > 0:
        chosen = rng.choice(valid, size=min(k, len(valid)), replace=False)
        trig.iloc[np.sort(chosen)] = True
    stop, target = _bracket_levels(df, trig, r, direction, slippage_bps=slippage_bps)
    return simulate_bracket(
        df, trig, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=slippage_bps, commission_bps=commission_bps,
        eow_close_out=False, session_close_out=False,
        direction=direction, max_bars=None,
    )


def always_in(df: pd.DataFrame, commission_bps: float, slippage_bps: float = SLIPPAGE_BPS) -> dict:
    """Buy-and-hold the vehicle over the same index — the beta baseline for this window."""
    trigger = pd.Series(False, index=df.index)
    trigger.iloc[0] = True
    stop = pd.Series(np.nan, index=df.index)
    stop.iloc[0] = 0.0  # unreachable stop: never exits early
    return simulate_bracket(
        df, trigger, stop, None,
        starting_cash=STARTING_CASH,
        slippage_bps=slippage_bps, commission_bps=commission_bps,
        eow_close_out=False, session_close_out=False,
        direction=LONG,
    )


# --- Per-window annual-netting scoring (D3) ---------------------------------------------

#: SMA(100)/ROC(126) is the deepest warm-up in the grid; ATR(20) is shallow by comparison.
_MAX_LOOKBACK_DAYS = 150
_MIN_WINDOW_BARS = 80


def _align_tz(d: date, idx: pd.DatetimeIndex) -> pd.Timestamp:
    """Tz-normalize a plain ``date`` to match ``df.index`` before it reaches pandas
    comparison/``_slice_windows`` machinery — the ``--data``/``idata.load_local`` path
    produces a UTC-aware index, while a plain ``date`` (e.g. the frozen
    ``PRIMARY_WINDOW_START``/``PRIMARY_WINDOW_END``) constructs a tz-naive ``pd.Timestamp``;
    comparing the two directly raises inside pandas.
    """
    ts = pd.Timestamp(d)
    if idx.tz is not None and ts.tzinfo is None:
        ts = ts.tz_localize(idx.tz)
    elif idx.tz is None and ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def _primary_windows(
    df: pd.DataFrame, test_start: date, window_end: Optional[date] = None,
) -> list:
    """The calendar-year window set used by ``_per_window_scores``, filtered to FULL
    windows with ``te <= window_end`` when a cap is given (round-1 review finding 2). With
    ``window_end=None`` this is the raw (uncapped) era read.
    """
    idx = df.index
    ts_start = _align_tz(test_start, idx)
    windows = _slice_windows(
        all_dates=idx, test_start=ts_start,
        window_months=12, max_lookback_days=_MAX_LOOKBACK_DAYS,
    )
    if window_end is not None:
        ts_end = _align_tz(window_end, idx)
        windows = [w for w in windows if w[2] <= ts_end]
    return windows


def _per_window_scores(
    df: pd.DataFrame, cell_fn: Callable[[pd.DataFrame], dict], test_start: date,
    window_end: Optional[date] = None,
) -> dict:
    """Median/worst per-window (12mo, calendar-aligned) after-tax DE annual-netting Calmar.

    Mirrors ``run_turtle_breakout._per_window_calmar``'s pre-roll/window-slice/NaN-drop
    convention exactly, with ``tax.apply_annual_netting_tax`` in place of the US
    deduct-at-exit model (D3 — the instrument's actual tax regime). Warm-up bars are never
    scored: each window rebuilds the cell on a pre-rolled sub-frame and measures the TEST
    sub-window only.

    ``window_end``, when given, caps the window set to FULL windows ending at or before it
    (the frozen ``PRIMARY_WINDOW_END`` for the primary statistic) — a trailing partial year
    must never enter the verdict-bearing median/worst. ``None`` (the era read) keeps every
    window the frame's own span produces.
    """
    idx = df.index
    windows = _primary_windows(df, test_start, window_end)
    calmars: list = []
    for pr_start, ts, te in windows:
        mask = (idx >= pr_start) & (idx <= te)
        widx = idx[mask]
        if len(widx) < _MIN_WINDOW_BARS:
            continue
        sim = cell_fn(df.loc[widx])
        eq = sim["equity_curve"]
        eq_test = eq.loc[(eq.index >= ts) & (eq.index <= te)]
        if len(eq_test) < 2:
            continue
        test_trades = [t for t in sim["trades"] if ts <= t["exit_date"] <= te]
        after = tax.apply_annual_netting_tax(test_trades, eq_test)
        c = _curve_metrics(after)["calmar"]
        if not (isinstance(c, float) and np.isnan(c)):
            calmars.append(c)
    if not calmars:
        return {"median_calmar": float("nan"), "worst_calmar": float("nan"),
                "n_windows": 0, "n_positive": 0}
    arr = np.array(calmars, dtype=float)
    return {
        "median_calmar": float(np.median(arr)),
        "worst_calmar": float(arr.min()),
        "n_windows": len(arr),
        "n_positive": int((arr > 0).sum()),
    }


# --- Grid runner + report (populated fully in TDD step 2) ------------------------------


def cell_status(p: dict) -> str:
    """Classify a preset's primary statistic so a NaN median is never printed bare.

    - ``no-trades``         — the arm never fired on this frame: nothing to judge.
    - ``no-scored-windows`` — it traded, but every primary window was dropped (NaN/no-trade
                              in every window) -- too sparse to judge, distinct from a
                              genuine ruin (round-1 review finding 10).
    - ``RUINED``            — defensive fallback: a non-finite median despite scored
                              windows existing (not currently reachable from
                              ``_per_window_scores``'s own return contract, kept for
                              robustness against a future scoring change).
    - ``ok``                — a finite median Calmar to compare against the bar.
    """
    if p["trade_count"] == 0:
        return "no-trades"
    if p["n_windows"] == 0:
        return "no-scored-windows"
    if not np.isfinite(p["median_calmar"]):
        return "RUINED"
    return "ok"


def _sort_key(row: dict, label: str) -> tuple:
    p = row["presets"][label]
    rank = {"ok": 0, "RUINED": 1, "no-scored-windows": 2, "no-trades": 3}[cell_status(p)]
    median = p["median_calmar"]
    return (rank, -median if np.isfinite(median) else 0.0)


def run_grid(df: pd.DataFrame) -> list:
    """Every frozen (arm, R) cell, at both co-primary cost presets. One row per cell."""
    rows = []
    for arm in ARMS:
        for r in R_GRID:
            presets = {}
            for label, commission_bps in COST_PRESETS:
                def cell_fn(d, _arm=arm, _r=r, _c=commission_bps):
                    return build_cell(d, _arm, _r, _c)

                def rand_fn(d, _arm=arm, _r=r, _c=commission_bps):
                    return build_random_cell(d, _arm, _r, _c)

                full_sim = cell_fn(df)
                primary = _per_window_scores(
                    df, cell_fn, PRIMARY_WINDOW_START, PRIMARY_WINDOW_END
                )
                era = _per_window_scores(df, cell_fn, df.index[0].date())
                rand_primary = _per_window_scores(
                    df, rand_fn, PRIMARY_WINDOW_START, PRIMARY_WINDOW_END
                )

                after_us = tax.apply_tax_to_ledger(
                    full_sim["trades"], full_sim["equity_curve"], jurisdiction="US"
                )
                after_de = tax.apply_tax_to_ledger(
                    full_sim["trades"], full_sim["equity_curve"], jurisdiction="DE"
                )
                clears = (
                    np.isfinite(primary["median_calmar"])
                    and primary["median_calmar"] > MES_SURVEY_BAR
                    and np.isfinite(primary["worst_calmar"])
                    and primary["worst_calmar"] > 0
                )
                presets[label] = {
                    "median_calmar": primary["median_calmar"],
                    "worst_calmar": primary["worst_calmar"],
                    "n_windows": primary["n_windows"],
                    "n_positive": primary["n_positive"],
                    "clears": clears,
                    "era_median_calmar": era["median_calmar"],
                    "era_worst_calmar": era["worst_calmar"],
                    "era_n_windows": era["n_windows"],
                    "full_calmar_us": _curve_metrics(after_us)["calmar"],
                    "full_calmar_de": _curve_metrics(after_de)["calmar"],
                    "random_median_calmar": rand_primary["median_calmar"],
                    "trade_count": full_sim["trade_count"],
                }
            rows.append({
                "arm": arm[0],
                "direction": arm[1],
                "r": r,
                "presets": presets,
                "clears_both": all(presets[label]["clears"] for label, _ in COST_PRESETS),
            })
    return rows


def compute_benchmark(df: pd.DataFrame) -> dict:
    """The always-in (buy-and-hold) benchmark, scored through the SAME D3 pipeline as every
    grid cell (primary window set, both co-primary presets), plus its own full-window
    secondaries for symmetry (round-1 review finding 3).

    Stopping-rule condition 3 ("beats ... the always-in benchmark on the same frame and the
    same basis") must be adjudicable from the printed report alone — without this, PR B
    would have to compute the benchmark ad hoc, re-opening the wiggle room the freeze closes.
    """
    benchmark = {}
    for label, commission_bps in COST_PRESETS:
        def bench_fn(d, _c=commission_bps):
            return always_in(d, _c)

        full_sim = bench_fn(df)
        primary = _per_window_scores(df, bench_fn, PRIMARY_WINDOW_START, PRIMARY_WINDOW_END)
        era = _per_window_scores(df, bench_fn, df.index[0].date())
        after_us = tax.apply_tax_to_ledger(
            full_sim["trades"], full_sim["equity_curve"], jurisdiction="US"
        )
        after_de = tax.apply_tax_to_ledger(
            full_sim["trades"], full_sim["equity_curve"], jurisdiction="DE"
        )
        benchmark[label] = {
            "median_calmar": primary["median_calmar"],
            "worst_calmar": primary["worst_calmar"],
            "n_windows": primary["n_windows"],
            "n_positive": primary["n_positive"],
            "era_median_calmar": era["median_calmar"],
            "era_worst_calmar": era["worst_calmar"],
            "era_n_windows": era["n_windows"],
            "full_calmar_us": _curve_metrics(after_us)["calmar"],
            "full_calmar_de": _curve_metrics(after_de)["calmar"],
            "trade_count": full_sim["trade_count"],
        }
    return benchmark


def _fmt_stat(value: float, width: int = 10) -> str:
    """Format a Calmar-like statistic, never as a bare NaN."""
    return f"{value:>+{width}.4f}" if np.isfinite(value) else f"{'—':>{width}}"


def format_report(
    rows: list, power: "idata.PowerReport", source: str, benchmark: dict,
) -> str:
    """Render both co-primary preset tables (cells + the always-in benchmark row) plus the
    D3 secondary-column table(s). Callers MUST NOT call this on an underpowered frame."""
    out = [
        "MES swing-contracts study — frozen 24-cell grid (12 edge-trigger arms x R{2,3})",
        f"source: {source}",
        f"power: {power.verdict} — {power.reason}",
        f"bars: {power.n_bars}  span: {power.first} -> {power.last}",
        f"frozen MES survey bar (median-window after-tax DE annual-netting Calmar): "
        f"{MES_SURVEY_BAR}",
    ]
    for label, commission_bps in COST_PRESETS:
        rt_bp = commission_bps * 2.0
        out += [
            "",
            f"--- cost preset: {label} ({rt_bp:.2f} bp round trip) ---",
            f"{'arm':<9} {'dir':<6} {'R':>3} {'median':>10} {'worst':>10} {'>bar?':>6} "
            f"{'n_w':>4} {'#tr':>5} {'random':>9} {'status':>18}",
        ]
        for row in sorted(rows, key=lambda r: _sort_key(r, label)):
            p = row["presets"][label]
            status = cell_status(p)
            med_txt = _fmt_stat(p["median_calmar"]) if status == "ok" else f"{'—':>10}"
            worst_txt = _fmt_stat(p["worst_calmar"]) if status == "ok" else f"{'—':>10}"
            rand = p["random_median_calmar"]
            rand_txt = f"{rand:>+9.4f}" if np.isfinite(rand) else f"{'—':>9}"
            out.append(
                f"{row['arm']:<9} {row['direction']:<6} {row['r']:>3.0f} "
                f"{med_txt} {worst_txt} {'YES' if p['clears'] else 'no':>6} "
                f"{p['n_windows']:>4} {p['trade_count']:>5} {rand_txt} {status:>18}"
            )
        bp = benchmark[label]
        bstatus = cell_status(bp)
        bmed_txt = _fmt_stat(bp["median_calmar"]) if bstatus == "ok" else f"{'—':>10}"
        bworst_txt = _fmt_stat(bp["worst_calmar"]) if bstatus == "ok" else f"{'—':>10}"
        out.append(
            f"{'ALWAYS_IN':<9} {'-':<6} {'-':>3} "
            f"{bmed_txt} {bworst_txt} {'n/a':>6} "
            f"{bp['n_windows']:>4} {bp['trade_count']:>5} {'n/a':>9} {bstatus:>18}"
        )
        cleared_here = [r for r in rows if r["presets"][label]["clears"]]
        out.append(f"cells clearing at {label}: {len(cleared_here)} / {len(rows)}")

    out += [
        "",
        "--- D3 secondary columns (reported, never verdict-bearing) ---",
    ]
    for label, _commission_bps in COST_PRESETS:
        out += [
            "",
            f"--- secondary columns: {label} ---",
            f"{'arm':<9} {'dir':<6} {'R':>3} {'era_med':>10} {'era_wst':>10} "
            f"{'era_nw':>6} {'full_us':>10} {'full_de':>10} {'n_pos':>5}",
        ]
        for row in sorted(rows, key=lambda r: _sort_key(r, label)):
            p = row["presets"][label]
            out.append(
                f"{row['arm']:<9} {row['direction']:<6} {row['r']:>3.0f} "
                f"{_fmt_stat(p['era_median_calmar'])} {_fmt_stat(p['era_worst_calmar'])} "
                f"{p['era_n_windows']:>6} {_fmt_stat(p['full_calmar_us'])} "
                f"{_fmt_stat(p['full_calmar_de'])} {p['n_positive']:>5}"
            )
        bp = benchmark[label]
        out.append(
            f"{'ALWAYS_IN':<9} {'-':<6} {'-':>3} "
            f"{_fmt_stat(bp['era_median_calmar'])} {_fmt_stat(bp['era_worst_calmar'])} "
            f"{bp['era_n_windows']:>6} {_fmt_stat(bp['full_calmar_us'])} "
            f"{_fmt_stat(bp['full_calmar_de'])} {bp['n_positive']:>5}"
        )

    clears_both = [r for r in rows if r["clears_both"]]
    out += [
        "",
        f"cells clearing at BOTH co-primary presets: {len(clears_both)} / {len(rows)}",
        "",
        f"this grid N = {N_CELLS}",
        f"cumulative family N = {CUMULATIVE_N}",
    ]
    if clears_both:
        out.append("clearing cells: " + ", ".join(
            f"{r['arm']}/R{r['r']:.0f}" for r in clears_both
        ))
    return "\n".join(out)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None,
                     help="local CSV/Parquet of daily bars (no network)")
    ap.add_argument("--vehicle", default="SPY", help="ticker for the network path")
    ap.add_argument("--end", default=None, help="last date (YYYY-MM-DD; default today)")
    args = ap.parse_args(argv)

    end = date.fromisoformat(args.end) if args.end else None

    if args.data:
        source = f"local:{args.data}"
        try:
            df = idata.load_local(args.data)
        except Exception as exc:                       # noqa: BLE001 - report, never crash
            print(f"DATA-BLOCKED: could not load {args.data}: {exc}", file=sys.stderr)
            return 2
    else:
        source = f"yfinance:{args.vehicle}:1d"
        try:
            df = _fetch_daily(args.vehicle, end)
        except Exception as exc:                       # noqa: BLE001
            print(f"DATA-BLOCKED: fetch failed: {exc}", file=sys.stderr)
            return 2

    if df is None or len(df) == 0:
        print(
            "DATA-BLOCKED: no bars available. Supply bars with --data instead.",
            file=sys.stderr,
        )
        return 2

    power = idata.describe_power(df)
    if power.verdict == "UNDERPOWERED":
        print(
            f"UNDERPOWERED: {power.reason}\n"
            f"bars={power.n_bars} span={power.first} -> {power.last}\n"
            "No per-cell results are printed: numbers from this frame would be plumbing "
            "smoke, not a read.",
            file=sys.stderr,
        )
        return 2

    rows = run_grid(df)
    benchmark = compute_benchmark(df)
    print(format_report(rows, power, source, benchmark))
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
