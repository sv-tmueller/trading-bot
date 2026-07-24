"""Long/short ORB study runner (#434) — the full-grid successor to #431's probe.

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker *trading* import, no orders. Data comes from a LOCAL file
(``backtest/intraday_data.py``); this runner performs no network I/O at all.

Relationship to ``run_orb_probe.py`` — that module is a **pinned reproducibility artifact**
for the merged #431 verdict and stays byte-identical, exactly as ``run_scalping_cost_wall.py``
is pinned to #311. This is a separate runner, so #431's frozen result remains reproducible
while the grid here is free to widen.

What widened, and why
---------------------
#431 could only test a long-only, 1-bar-OR, OR-low-stop cell. Zarattini & Aziz (2023) trade
**long and short**, so the long-only restriction meant the probe tested one arm of a
two-armed strategy — its disclosed "Deviation #1". With shorts in the engine (#434) and the
opening-range length parameterised, the frozen grid becomes:

    direction {long, short} x or_bars {1, 3, 6} x R {None, 5, 10}  =  18 cells

``or_bars`` on 5-minute bars is a 5 / 15 / 30-minute opening range. ``R=None`` is the
paper's exit-at-close variant; 10 is its base-model target. All 18 cells are reported for
multiplicity — none is dropped after seeing results.

The power gate is not optional
------------------------------
``describe_power`` decides whether the loaded data can carry a read at all. On an
UNDERPOWERED frame this runner refuses to print a verdict table and exits DATA-BLOCKED.
That is deliberate: #431 had to hand-label its shallow numbers "plumbing smoke" in prose,
and prose is easy to skip. Here the refusal is mechanical.

Run:
    python3 -m backtest.run_orb_study --data data/intraday/SPY_5min.csv
"""
from __future__ import annotations

import argparse
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from backtest.bracket import LONG, SHORT, simulate_bracket
from backtest.intraday_data import (
    describe_power,
    regular_session,
    resolve_intraday,
)
from backtest.orb import build_orb, opening_range, orb_levels
from backtest.regime import (
    COMMISSION_BPS,
    SLIPPAGE_BPS,
    STARTING_CASH,
    simulate_from_signal,
)
from backtest.run_candidate_survey import _after_tax_metrics

# --- Frozen grid (pre-registered; see the verdict doc) ------------------------------
DIRECTIONS: Tuple[str, ...] = (LONG, SHORT)
OR_BARS_GRID: Tuple[int, ...] = (1, 3, 6)          # 5 / 15 / 30-min OR on 5-min bars
TARGET_GRID: Tuple[Optional[float], ...] = (None, 5.0, 10.0)
N_CELLS = len(DIRECTIONS) * len(OR_BARS_GRID) * len(TARGET_GRID)   # 18

# The standing promotion bar: SPY buy-&-hold median-window after-tax Calmar
# (n_w=13, 2013-2025), identical to #430/#425 so results stay comparable.
SPY_BAR = 1.3085475049604838

RANDOM_SEED = 42


def build_cell(df: pd.DataFrame, direction: str, or_bars: int,
               r: Optional[float]) -> dict:
    """One ORB cell. EOD-flat (never overnight), so eow_close_out is off."""
    trig, stop, target = build_orb(
        df, or_bars=or_bars, direction=direction, r=r, slippage_bps=SLIPPAGE_BPS,
    )
    return simulate_bracket(
        df, trig, stop, target,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=False, session_close_out=True,
        direction=direction,
    )


def build_random_cell(df: pd.DataFrame, direction: str, or_bars: int,
                      r: Optional[float], seed: int = RANDOM_SEED) -> dict:
    """Same bracket geometry, entries SHUFFLED to random valid bars (seeded).

    Places the same NUMBER of entries as the real signal. A real edge must beat this;
    if it does not, the bracket is capturing session vol rather than the ORB's timing.
    """
    trig, _stop, _target = build_orb(
        df, or_bars=or_bars, direction=direction, r=r, slippage_bps=SLIPPAGE_BPS,
    )
    k = int(trig.sum())
    # Valid = any non-OR bar (the same bars a real entry could have landed on).
    or_high, or_low, is_or_bar, _sess = opening_range(df, or_bars)
    valid = np.flatnonzero((~is_or_bar).to_numpy())
    rng = np.random.default_rng(seed)
    rand_trig = pd.Series(False, index=df.index)
    if k > 0 and len(valid) > 0:
        chosen = rng.choice(valid, size=min(k, len(valid)), replace=False)
        rand_trig.iloc[np.sort(chosen)] = True
    # Recompute the levels AGAINST THE SHUFFLED BARS. Reusing the real cell's levels
    # would be wrong twice over: they are NaN off the real entry bars, and each shuffled
    # bar needs the geometry measured from its OWN open and its own session's OR.
    rand_stop, rand_target = orb_levels(
        df, rand_trig, or_high, or_low, r,
        direction=direction, slippage_bps=SLIPPAGE_BPS,
    )
    return simulate_bracket(
        df, rand_trig, rand_stop, rand_target,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=False, session_close_out=True,
        direction=direction,
    )


def always_in(df: pd.DataFrame) -> dict:
    """Buy-&-hold the vehicle — the beta baseline for this window."""
    return simulate_from_signal(
        vehicle_df=df[["Open", "Close"]],
        is_bullish_close_t=pd.Series(True, index=df.index),
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
    )


def run_grid(df: pd.DataFrame) -> list:
    """Every frozen cell, with its seeded random-entry twin. Returns a list of dicts."""
    rows = []
    for direction in DIRECTIONS:
        for or_bars in OR_BARS_GRID:
            for r in TARGET_GRID:
                real = build_cell(df, direction, or_bars, r)
                rand = build_random_cell(df, direction, or_bars, r)
                m_real = _after_tax_metrics(real, df.index)
                m_rand = _after_tax_metrics(rand, df.index)
                rows.append({
                    "direction": direction,
                    "or_bars": or_bars,
                    "target": "close" if r is None else f"R={r:g}",
                    "calmar_us": m_real["calmar_us"],
                    "cagr_pretax": m_real["cagr_pretax"],
                    "max_dd": m_real["max_dd"],
                    "trades": real["trade_count"],
                    "random_calmar_us": m_rand["calmar_us"],
                    "beats_bar": bool(m_real["calmar_us"] > SPY_BAR),
                })
    return rows


def format_report(rows: list, bench: dict, power_summary: str, source: str) -> str:
    """Render the per-cell table. Multiplicity is stated, never hidden."""
    lines = [
        "# ORB long/short study (#434)",
        "",
        f"Source: {source}",
        f"Power:  {power_summary}",
        f"Grid:   {N_CELLS} cells "
        f"(direction x or_bars{list(OR_BARS_GRID)} x target{['close', 'R=5', 'R=10']}) "
        "— all disclosed for multiplicity",
        f"Bar:    after-tax US Calmar > {SPY_BAR:.4f} (SPY B&H median window, n_w=13)",
        f"Always-in benchmark: after-tax US Calmar {bench['calmar_us']:.3f}",
        "",
        "| dir | or_bars | target | CalmarUS | CAGR | maxDD | #trades | random | > bar? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['direction']} | {r['or_bars']} | {r['target']} | "
            f"{r['calmar_us']:.3f} | {r['cagr_pretax'] * 100:.1f}% | "
            f"{r['max_dd'] * 100:.1f}% | {r['trades']} | "
            f"{r['random_calmar_us']:.3f} | {'YES' if r['beats_bar'] else 'no'} |"
        )
    winners = [r for r in rows if r["beats_bar"]]
    lines += ["", f"Cells clearing the bar: {len(winners)} / {len(rows)}"]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Long/short ORB study (research-only).")
    ap.add_argument("--data", default=None,
                    help="path to a local intraday CSV/Parquet file")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--timeframe", default="5Min")
    ap.add_argument("--regular-session-only", action="store_true", default=True)
    args = ap.parse_args(argv)

    source, df, power = resolve_intraday(
        local_path=args.data, symbol=args.symbol, timeframe=args.timeframe,
    )
    if df is None:
        print("DATA-BLOCKED — no usable intraday data.")
        print(f"  {power.reason}")
        print("\nDrop an exported CSV/Parquet at data/intraday/"
              f"{args.symbol.upper()}_{args.timeframe.lower()}.csv "
              "(or pass --data PATH) and re-run.")
        return 2

    if args.regular_session_only:
        df = regular_session(df)
        power = describe_power(df)

    print(f"Source: {source}")
    print(f"Power:  {power.summary()}\n")

    # The mechanical refusal: underpowered data yields no verdict table.
    if not power.is_readable:
        print("DATA-BLOCKED — the loaded frame is below the directional-read floor.")
        print("No cell results are printed: on this depth they would be plumbing")
        print("smoke, not a read. Supply deeper history to get a verdict.")
        return 2

    rows = run_grid(df)
    bench = _after_tax_metrics(always_in(df), df.index)
    print(format_report(rows, bench, power.summary(), source))
    if power.verdict == "DIRECTIONAL":
        print("\nNOTE: DIRECTIONAL read only — below the n_w=13 promotion bar, so no")
        print("cell here is gate-eligible regardless of how good it looks.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
