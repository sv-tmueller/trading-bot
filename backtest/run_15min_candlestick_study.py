"""15-Minute candlestick-PATTERN study runner — dual-cadence grid (refs #422, #571, #630).

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker *trading*
calls, no order endpoint. The only network is a read-only historical-bars pull, and the
``--data-*`` paths need no network at all.

What this answers
-----------------
Does any classic candlestick pattern, traded on **15-minute** SPY bars with a bracket
exit anchored to the pattern's own extreme, produce a win rate / profit factor /
after-tax Calmar that improves materially on the same pattern's **hourly** baseline?
And does the cost wall at 15-min cadence erase any edge?

Imports the shared cadence-agnostic primitives (``ARMS``, ``PATTERN_SPAN``,
``bracket_levels``, ``build_cell``, ``build_random_cell``) from
``run_candlestick_study`` — the geometry is frozen and unchanged. What differs here is
the data cadence, the session-close-out (EOD flat, since 15-min candlestick setups are
intraday), the hourly baseline comparison, and the cost-wall diagnostics.

Prior expectations
-------------------
#422's short-horizon feasibility gate found 6.1%/yr drag at 15m cadence (3bp table),
borderline-to-over. #571 found hourly stop distances already tight enough for a single
side's slippage to consume ~19% of the risk unit. At 15m, stop distances tighten further,
so the prior is NO-GO — but the study runs to produce the evidence.

Data
----
Primary: 15Min SPY bars fetched via ``run_fetch_spy_intraday.fetch_bars`` (Alpaca) or
loaded from a local CSV (``--data-15m``). Baseline: 60Min SPY bars (``--data-60m``).
Both are filtered to regular session hours (13:30-21:00 UTC) via
``intraday_data.regular_session`` before any detection or simulation runs.

``doji`` is registered as a pattern but is **excluded from the trading grid** (NEUTRAL);
its firing rate is reported but no bracket simulation runs.

Run::

    python3 -m backtest.run_15min_candlestick_study \\
        --data-15m data/intraday/SPY_15min.csv --data-60m data/intraday/SPY_60min.csv

Exit codes: ``0`` the grid ran; ``2`` data unavailable or underpowered (no table printed).
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from backtest import candlestick as cs
from backtest import intraday_data as idata
from backtest.bracket import LONG, SHORT
from backtest.run_candlestick_study import (
    ARMS,
    PATTERN_SPAN,
    R_GRID,
    N_CELLS,
    SPY_BAR,
    bracket_levels,
    build_cell,
    build_random_cell,
)
from backtest.run_candidate_survey import _after_tax_metrics
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, STARTING_CASH


# --- Cost-wall constants (reference #422's methodology) ------------------------------
#: Round-trip cost per trade in basis points: entry + exit slippage + commission.
ROUND_TRIP_BPS = 2 * (SLIPPAGE_BPS + COMMISSION_BPS)  # 20bp total

#: #422's 15m cost-wall figure (annualized drag at 3bp/table): 6.1%/yr.
COST_WALL_REF_422 = 0.061


def _load_bars(path: Optional[str], timeframe: str) -> Tuple[str, pd.DataFrame]:
    """Load bars from a local CSV. Returns ``(source, df)`` or raises."""
    if path is None:
        raise FileNotFoundError(
            f"No --data-{timeframe} path supplied and Alpaca keys are not set."
        )
    df = idata.load_local(path)
    return f"local:{path}", df


def _filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only regular-session bars (13:30-21:00 UTC)."""
    return idata.regular_session(df)


# --- Performance metrics --------------------------------------------------------------

def _win_rate_pf(sim: dict) -> Tuple[float, float]:
    """Compute win rate (%) and profit factor from a simulation's trade ledger.

    Win rate = fraction of trades with positive ``return_pct``.
    Profit factor = sum(winning PnL) / abs(sum(losing PnL)).
    Returns ``(0.0, 0.0)`` when there are no trades.
    """
    trades = sim["trades"]
    n = len(trades)
    if n == 0:
        return 0.0, 0.0
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    wr = len(wins) / n
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and losses.sum() != 0 else (
        float("inf") if len(wins) > 0 else 0.0
    )
    return wr, pf


def _build_cell_eod(df: pd.DataFrame, arm: Tuple[str, str, str], r: float) -> dict:
    """Build a cell with ``session_close_out=True`` — EOD flat for intraday setups."""
    _, pattern, direction = arm
    span = PATTERN_SPAN[pattern]
    signal = cs.detect(pattern, df)
    entry_trigger = signal.shift(1, fill_value=False)
    stop, target = bracket_levels(df, entry_trigger, direction, span, r)
    return simulate_bracket_session(
        df, entry_trigger, stop, target, direction=direction,
    )


def simulate_bracket_session(
    df: pd.DataFrame,
    entry_trigger: pd.Series,
    stop_prices: pd.Series,
    target_prices: Optional[pd.Series],
    *,
    direction: str = LONG,
) -> dict:
    """Wrapper around ``simulate_bracket`` with ``session_close_out=True``.

    15-min candlestick setups are intraday; holding overnight is outside the pattern's
    design. ``eow_close_out`` stays True (default) but is redundant when
    ``session_close_out`` flattens at every session boundary.
    """
    from backtest.bracket import simulate_bracket
    return simulate_bracket(
        df, entry_trigger, stop_prices, target_prices,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=True, session_close_out=True,
        direction=direction,
    )


def _build_random_cell_eod(
    df: pd.DataFrame, arm: Tuple[str, str, str], r: float, seed: int = 42
) -> dict:
    """Random-entry twin with ``session_close_out=True``."""
    _, pattern, direction = arm
    span = PATTERN_SPAN[pattern]
    mask = pd.Series(True, index=df.index)  # CONTEXT_NONE
    signal = cs.detect(pattern, df) & mask
    n_signals = int(signal.sum())

    rng = np.random.default_rng(seed)
    admissible = mask.to_numpy(dtype=bool)
    eligible = np.array(
        [i for i in range(span, len(df) - 1) if admissible[i]], dtype=int
    )
    shuffled = pd.Series(False, index=df.index)
    if n_signals > 0 and len(eligible) > 0:
        picks = rng.choice(eligible, size=min(n_signals, len(eligible)), replace=False)
        shuffled.iloc[picks] = True

    entry_trigger = shuffled.shift(1, fill_value=False)
    stop, target = bracket_levels(df, entry_trigger, direction, span, r)
    return simulate_bracket_session(
        df, entry_trigger, stop, target, direction=direction,
    )


def run_perf_grid(df: pd.DataFrame) -> list:
    """Run the 14-arm × R{2,3} performance grid on ``df`` (session-close-out).

    Returns one row dict per (arm, R) cell with win rate, profit factor, after-tax
    Calmar, trade count, max drawdown, and random-twin Calmar.
    """
    rows = []
    for arm in ARMS:
        for r in R_GRID:
            sim = _build_cell_eod(df, arm, r)
            rand = _build_random_cell_eod(df, arm, r)
            wr, pf = _win_rate_pf(sim)
            rows.append({
                "arm": arm[0],
                "direction": arm[2],
                "r": r,
                "win_rate": wr,
                "profit_factor": pf,
                "metrics": _after_tax_metrics(sim, df.index),
                "random_calmar_us": _after_tax_metrics(rand, df.index)["calmar_us"],
                "trade_count": sim["trade_count"],
                "max_drawdown": sim["max_drawdown"],
            })
    return rows


# --- Cost-wall diagnostics ------------------------------------------------------------

def _median_stop_distance(df: pd.DataFrame, arm: Tuple[str, str, str], r: float) -> float:
    """Median dollar stop distance for a given arm/R on ``df``."""
    _, pattern, direction = arm
    span = PATTERN_SPAN[pattern]
    signal = cs.detect(pattern, df)
    entry_trigger = signal.shift(1, fill_value=False)
    stop, _ = bracket_levels(df, entry_trigger, direction, span, r)

    slip = SLIPPAGE_BPS / 10_000.0
    if direction == LONG:
        entry_ref = df["Open"] * (1 + slip)
    else:
        entry_ref = df["Open"] * (1 - slip)
    risk = (entry_ref - stop).abs()
    live = stop.notna() & risk.notna() & (risk > 0)
    if not live.any():
        return float("nan")
    return float(risk[live].median())


def cost_wall_diag(df_15m: pd.DataFrame, df_60m: pd.DataFrame) -> dict:
    """Compute cost-wall diagnostics for 15m vs 60m cadence.

    References #422's methodology: annualized drag = trades/day × 252 × c,
    where c is the round-trip cost fraction. Cross-references #422's 3bp table
    figure of 6.1%/yr for 15m US equity ETF.

    Also computes #571's cost-drag fraction: median entry slippage / median stop
    distance, and the percentage of trades where entry slippage alone exceeds the
    whole stop distance.
    """
    diag: dict = {
        "15m": {},
        "60m": {},
    }

    for label, df in (("15m", df_15m), ("60m", df_60m)):
        total_trades = 0
        stop_distances = []
        slip_ratios = []

        slip_frac = SLIPPAGE_BPS / 10_000.0
        for arm in ARMS:
            _, pattern, direction = arm
            span = PATTERN_SPAN[pattern]
            signal = cs.detect(pattern, df)
            entry_trigger = signal.shift(1, fill_value=False)
            stop, _ = bracket_levels(df, entry_trigger, direction, span, r=R_GRID[0])

            if direction == LONG:
                entry_ref = df["Open"] * (1 + slip_frac)
            else:
                entry_ref = df["Open"] * (1 - slip_frac)
            risk = (entry_ref - stop).abs()
            live = stop.notna() & risk.notna() & (risk > 0)
            if not live.any():
                continue

            sim = _build_cell_eod(df, arm, R_GRID[0])
            total_trades += sim["trade_count"]

            sd = risk[live]
            stop_distances.extend(sd.to_numpy())

            # Entry slippage in dollars (single side)
            entry_slip = (df["Open"] * slip_frac)[live]
            slip_ratios.extend((entry_slip / sd).to_numpy())

        n_days = df.index.normalize().nunique()
        trades_per_day = total_trades / n_days if n_days > 0 else 0.0
        ann_drag = trades_per_day * 252 * ROUND_TRIP_BPS / 10_000.0

        med_sd = float(np.median(stop_distances)) if stop_distances else float("nan")
        med_slip_cost = float(np.median(slip_ratios)) if slip_ratios else float("nan")
        pct_slip_ge_stop = (
            float(np.mean(np.array(slip_ratios) >= 1.0)) if slip_ratios else 0.0
        )

        diag[label] = {
            "total_trades": total_trades,
            "sessions": n_days,
            "trades_per_day": trades_per_day,
            "ann_drag_pct": ann_drag,
            "median_stop_dist": med_sd,
            "median_slip_over_stop": med_slip_cost,
            "pct_slip_ge_stop": pct_slip_ge_stop,
        }

    return diag


# --- Formatting -----------------------------------------------------------------------

def format_firing_rates(
    rates_15m: pd.DataFrame,
    rates_60m: pd.DataFrame,
    power_15m: "idata.PowerReport",
    power_60m: "idata.PowerReport",
    source_15m: str,
    source_60m: str,
) -> str:
    """Format the per-pattern firing-rate calibration table for both cadences."""
    out = [
        "Firing-rate calibration — 15m vs 60m",
        f"15m source: {source_15m}  power: {power_15m.verdict}",
        f"60m source: {source_60m}  power: {power_60m.verdict}",
        "",
        f"{'pattern':<22} {'dir':<8} {'15m cnt':>8} {'15m rate':>9}  "
        f"{'60m cnt':>8} {'60m rate':>9}  {'bounds':>14}",
    ]
    for name in cs.PATTERNS:
        dir_str = cs.PATTERNS[name][1]
        r15 = rates_15m.loc[name] if name in rates_15m.index else None
        r60 = rates_60m.loc[name] if name in rates_60m.index else None
        c15 = int(r15["count"]) if r15 is not None else 0
        rate15 = r15["rate"] if r15 is not None else 0.0
        c60 = int(r60["count"]) if r60 is not None else 0
        rate60 = r60["rate"] if r60 is not None else 0.0
        ok = "ok"
        if r15 is not None and r15["verdict"] != "ok":
            ok = f"15m:{r15['verdict']}"
        if r60 is not None and r60["verdict"] != "ok":
            ok += f" 60m:{r60['verdict']}" if "15m:" in ok else f"60m:{r60['verdict']}"
        out.append(
            f"{name:<22} {dir_str:<8} {c15:>8} {rate15:>8.2%}  "
            f"{c60:>8} {rate60:>8.2%}  {ok:>14}"
        )
    bad_15 = rates_15m[rates_15m["verdict"] != "ok"]
    bad_60 = rates_60m[rates_60m["verdict"] != "ok"]
    out += [
        "",
        f"15m miscalibrated: {len(bad_15)} / {len(rates_15m)}",
        f"60m miscalibrated: {len(bad_60)} / {len(rates_60m)}",
        f"bounds: [{cs.FIRING_RATE_MIN:.1%}, {cs.FIRING_RATE_MAX:.0%}]",
    ]
    return "\n".join(out)


def format_perf_table(
    rows_15m: list,
    rows_60m: list,
    power_15m: "idata.PowerReport",
    power_60m: "idata.PowerReport",
    source_15m: str,
    source_60m: str,
) -> str:
    """Format the per-arm performance comparison table (15m vs 60m baseline)."""
    out = [
        "15-Minute candlestick study — per-arm performance vs hourly baseline",
        f"15m source: {source_15m}  power: {power_15m.verdict} — {power_15m.reason}",
        f"60m source: {source_60m}  power: {power_60m.verdict} — {power_60m.reason}",
        f"frozen SPY bar (median-window after-tax Calmar): {SPY_BAR:.4f}",
        "",
        f"{'arm':<22} {'dir':<6} {'R':>4}  "
        f"{'15m WR':>7} {'15m PF':>7} {'15m Cal':>9} {'15m #tr':>6}  "
        f"{'60m WR':>7} {'60m PF':>7} {'60m Cal':>9} {'60m #tr':>6}  "
        f"{'rand Cal':>9}",
    ]

    # Index 60m rows by (arm, r) for quick lookup
    idx_60m = {(r["arm"], r["r"]): r for r in rows_60m}

    for row in rows_15m:
        r60 = idx_60m.get((row["arm"], row["r"]))
        m15 = row["metrics"]
        wr15 = row["win_rate"]
        pf15 = row["profit_factor"]
        tc15 = row["trade_count"]
        cal15 = m15["calmar_us"]
        cal15_txt = f"{cal15:>+9.4f}" if np.isfinite(cal15) else f"{'—':>9}"

        if r60 is not None:
            wr60 = r60["win_rate"]
            pf60 = r60["profit_factor"]
            tc60 = r60["trade_count"]
            cal60 = r60["metrics"]["calmar_us"]
            cal60_txt = f"{cal60:>+9.4f}" if np.isfinite(cal60) else f"{'—':>9}"
        else:
            wr60 = pf60 = tc60 = 0.0
            cal60_txt = f"{'—':>9}"

        rand = row["random_calmar_us"]
        rand_txt = f"{rand:>+9.4f}" if np.isfinite(rand) else f"{'—':>9}"

        pf15_txt = f"{pf15:>7.2f}" if np.isfinite(pf15) else f"{'∞':>7}"
        pf60_txt = f"{pf60:>7.2f}" if np.isfinite(pf60) else f"{'∞':>7}"

        out.append(
            f"{row['arm']:<22} {row['direction']:<6} {row['r']:>4.0f}  "
            f"{wr15:>6.1%} {pf15_txt} {cal15_txt} {tc15:>6}  "
            f"{wr60:>6.1%} {pf60_txt} {cal60_txt} {tc60:>6}  "
            f"{rand_txt}"
        )

    return "\n".join(out)


def format_cost_wall(diag: dict) -> str:
    """Format the cost-wall diagnostic table."""
    d15 = diag["15m"]
    d60 = diag["60m"]
    return "\n".join([
        "Cost-wall assessment — 15m vs 60m (refs #422, #571)",
        "",
        f"  {'metric':<40} {'15m':>14} {'60m':>14}",
        f"  {'-'*40} {'-'*14} {'-'*14}",
        f"  {'total trades (R=2 grid)':<40} {d15['total_trades']:>14,} {d60['total_trades']:>14,}",
        f"  {'sessions':<40} {d15['sessions']:>14,} {d60['sessions']:>14,}",
        f"  {'trades/day':<40} {d15['trades_per_day']:>14.1f} {d60['trades_per_day']:>14.1f}",
        f"  {'annualized drag (%/yr, 20bp RT)':<40} {d15['ann_drag_pct']:>13.1%} {d60['ann_drag_pct']:>13.1%}",
        f"  {'median stop distance ($)':<40} {d15['median_stop_dist']:>14.4f} {d60['median_stop_dist']:>14.4f}",
        f"  {'median slippage / stop distance':<40} {d15['median_slip_over_stop']:>14.1%} {d60['median_slip_over_stop']:>14.1%}",
        f"  {'% trades slip ≥ stop dist':<40} {d15['pct_slip_ge_stop']:>13.1%} {d60['pct_slip_ge_stop']:>13.1%}",
        "",
        f"#422's 15m cost-wall reference: {COST_WALL_REF_422:.1%}/yr drag at 3bp table",
        f"This study's 15m annualized drag: {d15['ann_drag_pct']:.1%}/yr at {ROUND_TRIP_BPS}bp RT",
        "#571's 60m cost-drag: ~19% of stop distance (single-side slippage alone)",
    ])


# --- Main -----------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-15m", default=None,
                    help="local CSV/Parquet of 15Min bars (primary)")
    ap.add_argument("--data-60m", default=None,
                    help="local CSV/Parquet of 60Min bars (baseline)")
    ap.add_argument("--firing-rates", action="store_true",
                    help="print the per-pattern firing-rate calibration table and exit")
    ap.add_argument("--vehicle", default="SPY", help="ticker label for the report")
    args = ap.parse_args(argv)

    # --- Load data ---
    try:
        src_15m, df_15m_raw = _load_bars(args.data_15m, "15m")
    except Exception as exc:                        # noqa: BLE001
        print(f"DATA-BLOCKED: 15m: {exc}", file=sys.stderr)
        return 2
    try:
        src_60m, df_60m_raw = _load_bars(args.data_60m, "60m")
    except Exception as exc:                        # noqa: BLE001
        print(f"DATA-BLOCKED: 60m: {exc}", file=sys.stderr)
        return 2

    if len(df_15m_raw) == 0 or len(df_60m_raw) == 0:
        print("DATA-BLOCKED: one or both frames are empty.", file=sys.stderr)
        return 2

    # Filter to regular session hours
    df_15m = _filter_rth(df_15m_raw)
    df_60m = _filter_rth(df_60m_raw)

    power_15m = idata.describe_power(df_15m)
    power_60m = idata.describe_power(df_60m)

    # --- Firing-rate calibration (exempt from power gate) ---
    rates_15m = cs.firing_rates(df_15m)
    rates_60m = cs.firing_rates(df_60m)

    if args.firing_rates:
        print(format_firing_rates(
            rates_15m, rates_60m, power_15m, power_60m, src_15m, src_60m
        ))
        return 0

    # --- Power gate ---
    if power_15m.verdict == "UNDERPOWERED" or power_60m.verdict == "UNDERPOWERED":
        # Print firing rates (detector property, exempt from gate) but withhold perf.
        print(format_firing_rates(
            rates_15m, rates_60m, power_15m, power_60m, src_15m, src_60m
        ))
        print(file=sys.stdout)
        msg_parts = []
        if power_15m.verdict == "UNDERPOWERED":
            msg_parts.append(f"15m: {power_15m.reason}")
        if power_60m.verdict == "UNDERPOWERED":
            msg_parts.append(f"60m: {power_60m.reason}")
        print(
            f"UNDERPOWERED: {'; '.join(msg_parts)}\n"
            "No per-arm performance table is printed: numbers from this frame "
            "would be plumbing smoke, not a read.",
            file=sys.stderr,
        )
        return 2

    # --- Performance grid ---
    rows_15m = run_perf_grid(df_15m)
    rows_60m = run_perf_grid(df_60m)

    print(format_perf_table(
        rows_15m, rows_60m, power_15m, power_60m, src_15m, src_60m
    ))

    # --- Cost-wall diagnostics ---
    diag = cost_wall_diag(df_15m, df_60m)
    print()
    print(format_cost_wall(diag))

    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
