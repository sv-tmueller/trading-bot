"""NEUTRAL-detector promotion study — two-stage 8-cell grid on SPY 1Hour (#629).

Research-only. Never imported by ``supabase/functions/``. No LLM, no broker calls,
no order endpoint. The only network is a read-only yfinance download (fallback for
volume) and/or the existing local CSV (no network at all).

What this answers
-----------------
Do the two NEUTRAL candlestick detectors (``inside_bar``, ``doji``) exhibit directional
predictive value on SPY hourly bars when conditioned on a frozen 3-binary-qualifier set
(8 cells)?  Two stages:

1. **Stage 1 — breakout-direction screening.** For each fire at bar ``t``, classify
   bar ``t+1``'s breakout (long / short / neither).  Test whether the long-breakout
   rate departs from 50% (two-sided exact binomial test), overall and per cell.
2. **Stage 2 — bracket profitability (conditional).** For cells with Stage 1 bias
   (p < 0.05), run a 2R bracket simulation with entry at bar ``t+2``'s open, stop
   anchored to the pattern's own extreme, session + EOW close-out.  Test win rate
   vs 33.3% breakeven (one-sided exact binomial test).

See ``docs/research/2026-09-03-neutral-promotion-preregistration.md`` for the frozen
protocol, qualifier definitions, entry/exit geometry, and verdict mapping.

Data limitations
----------------
- Primary source (Alpaca with ``keep_volume=True``) requires API keys; if unavailable,
  the existing ``data/intraday/SPY_60min.csv`` (41,968 bars, 2016-2026, no Volume) is
  used for Stage 1 (breakout-direction screening needs price only).
- Volume-qualification uses yfinance as a fallback (``yfinance.download("SPY",
  interval="60m", period="730d")``), limited to ~730 days → n_w≈2, UNDERPOWERED.
  Volume-qualified cells are reported at reduced power and treated as supplementary.

Run::

    CLAUDE_AGENT_NO_BROKER=1 venv/bin/python -m backtest.run_neutral_promotion_study \
        [--data data/intraday/SPY_60min.csv] [--verbose]

Exit codes: ``0`` the study ran; ``2`` data unavailable.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from backtest import candlestick as cs
from backtest.bracket import LONG, SHORT, simulate_bracket
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, STARTING_CASH

# ── Frozen constants (match the pre-registration) ───────────────────────────────

PATTERNS_STUDIED: Tuple[str, ...] = ("inside_bar", "doji")

# ATR qualifier
ATR_WINDOW = 20
ATR_RANK_LOOKBACK = 252  # ~1 trading year of hourly bars

# Volume qualifier
VOLUME_WINDOW = 20

# Breakout classification
BREAKOUT_LONG = "long"
BREAKOUT_SHORT = "short"
BREAKOUT_NEITHER = "neither"

# Stage 2 geometry
STOP_BUFFER = 0.001  # 10 bp beyond the pattern extreme
R_MULTIPLIER = 2.0
BREAKEVEN_WIN_RATE = 1.0 / (1.0 + R_MULTIPLIER)  # 33.3%

# Significance threshold
ALPHA = 0.05

# 8 cells: (breakout_dir, atr_rank, volume)
CELL_LABELS: List[Tuple[str, str, str]] = [
    (BREAKOUT_LONG, "HIGH", "HIGH"),
    (BREAKOUT_LONG, "HIGH", "LOW"),
    (BREAKOUT_LONG, "LOW", "HIGH"),
    (BREAKOUT_LONG, "LOW", "LOW"),
    (BREAKOUT_SHORT, "HIGH", "HIGH"),
    (BREAKOUT_SHORT, "HIGH", "LOW"),
    (BREAKOUT_SHORT, "LOW", "HIGH"),
    (BREAKOUT_SHORT, "LOW", "LOW"),
]


def cell_label(cell: Tuple[str, str, str]) -> str:
    """Compact label like 'L/H/H' for a cell tuple."""
    d = "L" if cell[0] == BREAKOUT_LONG else "S"
    a = "H" if cell[1] == "HIGH" else "L"
    v = "H" if cell[2] == "HIGH" else "L"
    return f"{d}/{a}/{v}"


# ── Data loading ────────────────────────────────────────────────────────────────

def load_hourly_bars(path: str) -> pd.DataFrame:
    """Load SPY 1Hour bars from a local CSV. Returns OHLC(V) DataFrame."""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    # Ensure column names match candlestick.py expectations
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "open":
            col_map[c] = "Open"
        elif cl == "high":
            col_map[c] = "High"
        elif cl == "low":
            col_map[c] = "Low"
        elif cl == "close":
            col_map[c] = "Close"
        elif cl == "volume":
            col_map[c] = "Volume"
    df = df.rename(columns=col_map)
    required = {"Open", "High", "Low", "Close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required OHLC columns: {missing}")
    return df


def compute_sha256(path: str) -> str:
    """SHA256 of a file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_volume_fallback() -> Optional[pd.DataFrame]:
    """Try yfinance for SPY 60m bars with volume (~730 days). Returns DF or None."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        df = yf.download("SPY", interval="60m", period="730d", progress=False)
        if df is None or df.empty:
            return None
        # Flatten MultiIndex columns if present (yfinance returns tuples)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        col_map = {}
        for c in df.columns:
            cl = c.lower().strip()
            if cl == "open":
                col_map[c] = "Open"
            elif cl == "high":
                col_map[c] = "High"
            elif cl == "low":
                col_map[c] = "Low"
            elif cl == "close":
                col_map[c] = "Close"
            elif cl == "volume":
                col_map[c] = "Volume"
        df = df.rename(columns=col_map)
        if "Volume" not in df.columns:
            return None
        return df
    except Exception:
        return None


# ── Qualifier computation ──────────────────────────────────────────────────────

def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = ATR_WINDOW) -> pd.Series:
    """Average True Range over ``window`` bars ending at each bar."""
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def compute_atr_rank(atr: pd.Series, lookback: int = ATR_RANK_LOOKBACK) -> pd.Series:
    """Percentile rank of ATR at each bar vs preceding ``lookback`` bars' ATR values.

    Rank = fraction of preceding-``lookback`` ATR values that are ≤ the current ATR.
    """
    def _rank(val: float, window_vals: pd.Series) -> float:
        if len(window_vals) == 0:
            return np.nan
        return float((window_vals <= val).sum()) / len(window_vals)

    ranks = pd.Series(np.nan, index=atr.index, dtype=float)
    vals = atr.values
    n = len(vals)
    for i in range(n):
        if np.isnan(vals[i]):
            continue
        start = max(0, i - lookback)
        if i - start == 0:
            continue
        window_vals = atr.iloc[start:i]
        window_vals = window_vals.dropna()
        if len(window_vals) == 0:
            continue
        ranks.iloc[i] = float((window_vals <= vals[i]).sum()) / len(window_vals)
    return ranks


def compute_volume_qualifier(volume: pd.Series, window: int = VOLUME_WINDOW) -> pd.Series:
    """Volume qualifier: True if bar volume > 20-bar SMA of volume."""
    avg = volume.rolling(window).mean()
    return volume > avg


# ── Stage 1: Breakout-direction screening ──────────────────────────────────────

def classify_breakout(df: pd.DataFrame, fire_idx: int) -> str:
    """Classify bar t+1's breakout relative to bar t's range.

    Long: high[t+1] > high[t]; Short: low[t+1] < low[t]; Neither: neither condition.
    If both conditions hold simultaneously, the bar that moved more (by absolute % of
    range) wins — but in practice this is extremely rare on hourly SPY.
    """
    if fire_idx + 1 >= len(df):
        return BREAKOUT_NEITHER
    h_t = df["High"].iloc[fire_idx]
    l_t = df["Low"].iloc[fire_idx]
    h_next = df["High"].iloc[fire_idx + 1]
    l_next = df["Low"].iloc[fire_idx + 1]

    broke_high = h_next > h_t
    broke_low = l_next < l_t

    if broke_high and broke_low:
        # Ambiguous: choose the larger relative break
        break_up = (h_next - h_t) / h_t if h_t > 0 else 0
        break_down = (l_t - l_next) / l_t if l_t > 0 else 0
        return BREAKOUT_LONG if break_up >= break_down else BREAKOUT_SHORT
    if broke_high:
        return BREAKOUT_LONG
    if broke_low:
        return BREAKOUT_SHORT
    return BREAKOUT_NEITHER


def run_stage1(df: pd.DataFrame, has_volume: bool) -> Tuple[List[dict], List[dict]]:
    """Stage 1: detect fires, classify breakouts, compute qualifiers, run binomial tests.

    Returns (overall_results, cell_results) where each entry is a dict.
    """
    # Compute ATR and ATR rank
    atr = compute_atr(df["High"], df["Low"], df["Close"])
    atr_rank = compute_atr_rank(atr)
    atr_binary = (atr_rank > 0.50).fillna(False)  # ATR_HIGH

    # Volume qualifier
    if has_volume and "Volume" in df.columns:
        vol_qual = compute_volume_qualifier(df["Volume"]).fillna(False)
        volume_source = "present"
    else:
        vol_qual = pd.Series(False, index=df.index)
        volume_source = "absent"

    all_overall: List[dict] = []
    all_cells: List[dict] = []

    for pattern_name in PATTERNS_STUDIED:
        signal = cs.detect(pattern_name, df)
        fire_indices = np.where(signal.values)[0]

        # Need t+1 to exist for breakout classification
        valid_fires = [i for i in fire_indices if i + 1 < len(df)]
        n_fires = len(valid_fires)

        if n_fires == 0:
            all_overall.append({
                "pattern": pattern_name,
                "total_fires": 0,
                "breakouts": 0,
                "long_count": 0,
                "short_count": 0,
                "neither_count": 0,
                "long_rate": np.nan,
                "binom_p": np.nan,
                "verdict": "no-fires",
            })
            # Empty cells
            for cell in CELL_LABELS:
                all_cells.append({
                    "pattern": pattern_name,
                    "cell": cell_label(cell),
                    "breakout_dir": cell[0],
                    "atr_rank": cell[1],
                    "volume": cell[2],
                    "n": 0,
                    "long_count": 0,
                    "long_rate": np.nan,
                    "binom_p": np.nan,
                    "bias": "n/a",
                })
            continue

        # Classify breakouts
        breakouts = [classify_breakout(df, i) for i in valid_fires]
        long_count = sum(1 for b in breakouts if b == BREAKOUT_LONG)
        short_count = sum(1 for b in breakouts if b == BREAKOUT_SHORT)
        neither_count = sum(1 for b in breakouts if b == BREAKOUT_NEITHER)
        n_directional = long_count + short_count

        # Overall binomial test: among directional breakouts, is long_rate != 50%?
        if n_directional > 0:
            bt = binomtest(long_count, n_directional, p=0.5, alternative="two-sided")
            long_rate = long_count / n_directional
            p_val = bt.pvalue
        else:
            long_rate = np.nan
            p_val = np.nan

        all_overall.append({
            "pattern": pattern_name,
            "total_fires": n_fires,
            "breakouts": n_directional,
            "long_count": long_count,
            "short_count": short_count,
            "neither_count": neither_count,
            "long_rate": long_rate,
            "binom_p": p_val,
            "verdict": "bias" if (p_val is not np.nan and p_val < ALPHA) else "no-bias",
        })

        # Per-cell breakdown
        for cell in CELL_LABELS:
            cell_dir, cell_atr, cell_vol = cell

            # Filter fires by cell qualifiers (computed at signal bar t)
            cell_fire_idxs = []
            for idx_pos, fi in enumerate(valid_fires):
                # ATR qualifier at bar t
                fi_atr_high = bool(atr_binary.iloc[fi])
                atr_match = (cell_atr == "HIGH" and fi_atr_high) or (cell_atr == "LOW" and not fi_atr_high)

                # Volume qualifier at bar t
                if has_volume and "Volume" in df.columns:
                    fi_vol_high = bool(vol_qual.iloc[fi])
                    vol_match = (cell_vol == "HIGH" and fi_vol_high) or (cell_vol == "LOW" and not fi_vol_high)
                else:
                    # No volume data: all fires go into VOL_LOW (conservative)
                    vol_match = (cell_vol == "LOW")

                # Breakout direction must match cell
                bk = breakouts[idx_pos]
                dir_match = (bk == cell_dir)

                if atr_match and vol_match and dir_match:
                    cell_fire_idxs.append(fi)

            cell_n = len(cell_fire_idxs)
            cell_long = sum(1 for fi in cell_fire_idxs
                            if classify_breakout(df, fi) == BREAKOUT_LONG)

            if cell_n > 0:
                cell_long_rate = cell_long / cell_n
                # For short cells, we test whether short_rate != 50%
                # But by construction, all fires in a short cell ARE short breakouts,
                # so the rate is 100% by selection. The meaningful test is the
                # OVERALL long-vs-short balance, not within-cell.
                #
                # Actually, re-reading the pre-reg: Stage 1 tests whether the
                # long-breakout RATE differs from 50% AMONG FIRES THAT BREAK OUT,
                # per cell. So within a cell, we count how many of ALL fires (not
                # just matching-direction ones) broke long vs short.
                #
                # Let me reconsider: the cell is DEFINED by the breakout direction.
                # So the test should be: among all fires in this (atr, vol) bucket,
                # does the long-breakout rate depart from 50%?

                # Recompute: for this cell's (atr, vol) bucket, count ALL breakouts
                cell_bucket_fires = []
                for fi in valid_fires:
                    fi_atr_high = bool(atr_binary.iloc[fi])
                    atr_match = (cell_atr == "HIGH" and fi_atr_high) or (cell_atr == "LOW" and not fi_atr_high)
                    if has_volume and "Volume" in df.columns:
                        fi_vol_high = bool(vol_qual.iloc[fi])
                        vol_match = (cell_vol == "HIGH" and fi_vol_high) or (cell_vol == "LOW" and not fi_vol_high)
                    else:
                        vol_match = (cell_vol == "LOW")
                    if atr_match and vol_match:
                        cell_bucket_fires.append(fi)

                bucket_breakouts = [classify_breakout(df, fi) for fi in cell_bucket_fires]
                bucket_long = sum(1 for b in bucket_breakouts if b == BREAKOUT_LONG)
                bucket_short = sum(1 for b in bucket_breakouts if b == BREAKOUT_SHORT)
                bucket_directional = bucket_long + bucket_short

                if bucket_directional > 0:
                    bucket_long_rate = bucket_long / bucket_directional
                    bt_cell = binomtest(bucket_long, bucket_directional, p=0.5, alternative="two-sided")
                    cell_p = bt_cell.pvalue
                else:
                    bucket_long_rate = np.nan
                    cell_p = np.nan

                bias = "bias" if (cell_p is not np.nan and cell_p < ALPHA) else "no-bias"
                all_cells.append({
                    "pattern": pattern_name,
                    "cell": cell_label(cell),
                    "breakout_dir": cell_dir,
                    "atr_rank": cell_atr,
                    "volume": cell_vol,
                    "n_fires_in_bucket": len(cell_bucket_fires),
                    "n_directional": bucket_directional,
                    "long_count": bucket_long,
                    "short_count": bucket_short,
                    "long_rate": bucket_long_rate,
                    "binom_p": cell_p,
                    "bias": bias,
                })
            else:
                # Still report the bucket stats even if no matching-direction fires
                cell_bucket_fires = []
                for fi in valid_fires:
                    fi_atr_high = bool(atr_binary.iloc[fi])
                    atr_match = (cell_atr == "HIGH" and fi_atr_high) or (cell_atr == "LOW" and not fi_atr_high)
                    if has_volume and "Volume" in df.columns:
                        fi_vol_high = bool(vol_qual.iloc[fi])
                        vol_match = (cell_vol == "HIGH" and fi_vol_high) or (cell_vol == "LOW" and not fi_vol_high)
                    else:
                        vol_match = (cell_vol == "LOW")
                    if atr_match and vol_match:
                        cell_bucket_fires.append(fi)

                bucket_breakouts = [classify_breakout(df, fi) for fi in cell_bucket_fires]
                bucket_long = sum(1 for b in bucket_breakouts if b == BREAKOUT_LONG)
                bucket_short = sum(1 for b in bucket_breakouts if b == BREAKOUT_SHORT)
                bucket_directional = bucket_long + bucket_short

                if bucket_directional > 0:
                    bucket_long_rate = bucket_long / bucket_directional
                    bt_cell = binomtest(bucket_long, bucket_directional, p=0.5, alternative="two-sided")
                    cell_p = bt_cell.pvalue
                else:
                    bucket_long_rate = np.nan
                    cell_p = np.nan

                all_cells.append({
                    "pattern": pattern_name,
                    "cell": cell_label(cell),
                    "breakout_dir": cell_dir,
                    "atr_rank": cell_atr,
                    "volume": cell_vol,
                    "n_fires_in_bucket": len(cell_bucket_fires),
                    "n_directional": bucket_directional,
                    "long_count": bucket_long,
                    "short_count": bucket_short,
                    "long_rate": bucket_long_rate,
                    "binom_p": cell_p,
                    "bias": "no-bias" if (cell_p is not np.nan and cell_p >= ALPHA) else "n/a",
                })

    return all_overall, all_cells


# ── Stage 2: Conditional bracket simulation ────────────────────────────────────

def run_stage2(
    df: pd.DataFrame,
    pattern_name: str,
    cell: Tuple[str, str, str],
    cell_results: List[dict],
    has_volume: bool,
) -> Optional[dict]:
    """Stage 2: bracket simulation at 2R for cells with Stage 1 bias.

    Entry at bar t+2's open (2-bar lag from pattern fire).
    Stop at pattern bar's own extreme ± buffer.
    Target at entry ± R * risk.
    Session + EOW close-out enabled.
    """
    # Check if this cell showed Stage 1 bias
    cell_entry = None
    for cr in cell_results:
        if cr["pattern"] == pattern_name and cr["cell"] == cell_label(cell):
            cell_entry = cr
            break

    if cell_entry is None:
        return None

    if cell_entry.get("bias") != "bias":
        return {
            "pattern": pattern_name,
            "cell": cell_label(cell),
            "stage2_run": False,
            "reason": "no Stage 1 bias",
            "trade_count": 0,
            "win_count": 0,
            "win_rate": np.nan,
            "expectancy_R": np.nan,
            "binom_p_vs_breakeven": np.nan,
        }

    # Identify fires in this cell's bucket that match the cell's breakout direction
    atr = compute_atr(df["High"], df["Low"], df["Close"])
    atr_rank = compute_atr_rank(atr)
    atr_binary = (atr_rank > 0.50).fillna(False)

    if has_volume and "Volume" in df.columns:
        vol_qual = compute_volume_qualifier(df["Volume"]).fillna(False)
    else:
        vol_qual = pd.Series(False, index=df.index)

    signal = cs.detect(pattern_name, df)
    fire_indices = np.where(signal.values)[0]

    cell_dir, cell_atr, cell_vol = cell
    direction = LONG if cell_dir == BREAKOUT_LONG else SHORT

    # Collect entry indices: fires where breakout at t+1 matches cell_dir,
    # AND the (atr, vol) qualifiers match, AND t+2 exists.
    entry_indices = []
    for fi in fire_indices:
        if fi + 2 >= len(df):
            continue

        # Qualifiers at bar t
        fi_atr_high = bool(atr_binary.iloc[fi])
        atr_match = (cell_atr == "HIGH" and fi_atr_high) or (cell_atr == "LOW" and not fi_atr_high)

        if has_volume and "Volume" in df.columns:
            fi_vol_high = bool(vol_qual.iloc[fi])
            vol_match = (cell_vol == "HIGH" and fi_vol_high) or (cell_vol == "LOW" and not fi_vol_high)
        else:
            vol_match = (cell_vol == "LOW")

        if not (atr_match and vol_match):
            continue

        # Breakout direction at t+1
        bk = classify_breakout(df, fi)
        if bk != cell_dir:
            continue

        entry_indices.append(fi)

    if not entry_indices:
        return {
            "pattern": pattern_name,
            "cell": cell_label(cell),
            "stage2_run": False,
            "reason": "no qualifying trades",
            "trade_count": 0,
            "win_count": 0,
            "win_rate": np.nan,
            "expectancy_R": np.nan,
            "binom_p_vs_breakeven": np.nan,
        }

    # Build entry triggers and bracket levels
    # Entry at t+2's open; signal detected at t; breakout confirmed at t+1's close
    entry_trigger = pd.Series(False, index=df.index)
    stop_prices = pd.Series(np.nan, index=df.index)
    target_prices = pd.Series(np.nan, index=df.index)

    slip = SLIPPAGE_BPS / 10_000.0

    for fi in entry_indices:
        entry_idx = fi + 2  # t+2 open
        if entry_idx >= len(df):
            continue

        # Pattern extreme at bar t (the signal bar)
        if pattern_name == "inside_bar":
            # Span = 2 bars (mother + inside); use min(low[t-1:t+1]) for long,
            # max(high[t-1:t+1]) for short. But the pre-reg says "pattern bar's
            # own extreme" — for inside_bar the "pattern bar" is bar t, and the
            # "own extreme" is the mother bar (t-1)'s extreme since the inside
            # bar is contained by it. We use the mother bar's extreme.
            if direction == LONG:
                stop_level = df["Low"].iloc[fi - 1] * (1 - STOP_BUFFER) if fi >= 1 else np.nan
            else:
                stop_level = df["High"].iloc[fi - 1] * (1 + STOP_BUFFER) if fi >= 1 else np.nan
        else:
            # doji: 1-bar pattern, stop at bar t's own extreme
            if direction == LONG:
                stop_level = df["Low"].iloc[fi] * (1 - STOP_BUFFER)
            else:
                stop_level = df["High"].iloc[fi] * (1 + STOP_BUFFER)

        if np.isnan(stop_level):
            continue

        # Entry reference price at t+2's open
        entry_open = df["Open"].iloc[entry_idx]
        if direction == LONG:
            entry_ref = entry_open * (1 + slip)
            risk = entry_ref - stop_level
            if risk <= 0:
                continue
            target_level = entry_ref + R_MULTIPLIER * risk
        else:
            entry_ref = entry_open * (1 - slip)
            risk = stop_level - entry_ref
            if risk <= 0:
                continue
            target_level = entry_ref - R_MULTIPLIER * risk

        entry_trigger.iloc[entry_idx] = True
        stop_prices.iloc[entry_idx] = stop_level
        target_prices.iloc[entry_idx] = target_level

    # Run bracket simulation
    sim = simulate_bracket(
        df, entry_trigger, stop_prices, target_prices,
        starting_cash=STARTING_CASH,
        slippage_bps=SLIPPAGE_BPS, commission_bps=COMMISSION_BPS,
        eow_close_out=True, session_close_out=True,
        direction=direction,
    )

    trades = sim["trades"]
    n_trades = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)

    if n_trades > 0:
        win_rate = wins / n_trades
        # Expectancy in R: average pnl / average risk per trade
        # Approximate R-multiple from return_pct: for 2R, a winner gains ~2R, loser loses ~1R
        # More precisely, compute from pnl vs position size
        # Simpler: use exit_reason to determine win/loss
        win_R = R_MULTIPLIER  # approximate
        loss_R = -1.0
        expectancy_R = (wins * win_R + (n_trades - wins) * loss_R) / n_trades if n_trades > 0 else np.nan

        # Binomial test vs 33.3% breakeven (one-sided greater)
        bt = binomtest(wins, n_trades, p=BREAKEVEN_WIN_RATE, alternative="greater")
        p_val = bt.pvalue
    else:
        win_rate = np.nan
        expectancy_R = np.nan
        p_val = np.nan

    return {
        "pattern": pattern_name,
        "cell": cell_label(cell),
        "stage2_run": True,
        "reason": "ran",
        "trade_count": n_trades,
        "win_count": wins,
        "win_rate": win_rate,
        "expectancy_R": expectancy_R,
        "binom_p_vs_breakeven": p_val,
        "sim_total_return": sim["total_return"],
        "sim_max_drawdown": sim["max_drawdown"],
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="data/intraday/SPY_60min.csv",
                    help="path to SPY 1Hour CSV (default: data/intraday/SPY_60min.csv)")
    ap.add_argument("--verbose", action="store_true", default=False)
    args = ap.parse_args(argv)

    print("=" * 80)
    print("NEUTRAL-detector promotion study — #629")
    print("=" * 80)

    # Load data
    try:
        df = load_hourly_bars(args.data)
    except FileNotFoundError:
        print(f"\nERROR: data file not found: {args.data}")
        return 2
    except Exception as e:
        print(f"\nERROR loading data: {e}")
        return 2

    sha = compute_sha256(args.data)
    has_volume = "Volume" in df.columns
    n_bars = len(df)
    date_range = f"{df.index[0]} to {df.index[-1]}"
    n_years = (df.index[-1] - df.index[0]).days / 365.25
    n_weeks = int(n_years)  # approx non-overlapping 12-month windows

    print(f"\nData: {args.data}")
    print(f"  SHA256: {sha}")
    print(f"  Bars: {n_bars:,}")
    print(f"  Date range: {date_range}")
    print(f"  Years: ~{n_years:.1f}  (n_w ≈ {n_weeks})")
    print(f"  Volume column: {'YES' if has_volume else 'NO'}")

    if not has_volume:
        print("\n  No Volume column in CSV. Attempting yfinance fallback...")
        vol_df = fetch_volume_fallback()
        if vol_df is not None and "Volume" in vol_df.columns:
            print(f"  yfinance: retrieved {len(vol_df)} bars with volume ({vol_df.index[0]} to {vol_df.index[-1]})")
            # Merge volume into df on index
            # Align by timestamp (both should be UTC hour-starts)
            df["Volume"] = vol_df["Volume"].reindex(df.index).ffill().fillna(0.0)
            has_volume = True
            vol_bars = int((df["Volume"] > 0).sum())
            print(f"  Merged: {vol_bars} bars with non-zero volume (of {n_bars} total)")
            print(f"  Volume coverage: {vol_bars/n_bars*100:.1f}% of bars")
            print(f"  ⚠ UNDERPOWERED: yfinance covers ~730 days only (n_w≈2)")
        else:
            print("  yfinance fallback failed or no volume available.")
            print("  Volume-qualified cells will be reported as DATA-LIMITED.")

    print(f"\n  Power level: {'DIRECTIONAL' if n_weeks >= 5 else 'UNDERPOWERED'} (n_w={'≈'+str(n_weeks)})")
    print(f"  Promotion bar: n_w=13 → {'NOT MET' if n_weeks < 13 else 'MET'}")

    # ── Stage 1 ──
    print("\n" + "=" * 80)
    print("STAGE 1 — Breakout-direction screening")
    print("=" * 80)

    overall_results, cell_results = run_stage1(df, has_volume)

    print(f"\nOverall results (per pattern):")
    print(f"  {'Pattern':<15} {'Fires':>7} {'Dir':>5} {'Long':>6} {'Short':>6} {'Neith':>6} {'LR':>8} {'p-val':>10} {'Bias?':>6}")
    for r in overall_results:
        lr_str = f"{r['long_rate']:.4f}" if r['long_rate'] is not np.nan and not np.isnan(r['long_rate']) else "—"
        p_str = f"{r['binom_p']:.6f}" if r['binom_p'] is not np.nan and not np.isnan(r['binom_p']) else "—"
        bias_str = "YES" if r['verdict'] == "bias" else "no"
        print(f"  {r['pattern']:<15} {r['total_fires']:>7} {r['breakouts']:>5} {r['long_count']:>6} {r['short_count']:>6} {r['neither_count']:>6} {lr_str:>8} {p_str:>10} {bias_str:>6}")

    print(f"\nPer-cell results (8 cells × 2 patterns = 16 trials):")
    print(f"  {'Pattern':<15} {'Cell':<8} {'Bucket':>7} {'Dir':>5} {'Long':>6} {'Short':>6} {'LR':>8} {'p-val':>10} {'Bias?':>6}")
    for r in cell_results:
        lr = r.get('long_rate')
        pv = r.get('binom_p')
        lr_str = f"{lr:.4f}" if lr is not np.nan and not np.isnan(lr) else "—"
        p_str = f"{pv:.6f}" if pv is not np.nan and not np.isnan(pv) else "—"
        bias_str = "YES" if r.get('bias') == "bias" else "no"
        nd = r.get('n_directional', 0)
        nb = r.get('n_fires_in_bucket', 0)
        print(f"  {r['pattern']:<15} {r['cell']:<8} {nb:>7} {nd:>5} {r.get('long_count',0):>6} {r.get('short_count',0):>6} {lr_str:>8} {p_str:>10} {bias_str:>6}")

    # Multiplicity disclosure
    n_tests = len(cell_results)
    n_bias = sum(1 for r in cell_results if r.get("bias") == "bias")
    expected_fp = n_tests * ALPHA
    print(f"\n  Multiplicity: {n_tests} binomial tests at α={ALPHA}.")
    print(f"  Nominal hits: {n_bias}. Expected false positives by chance: ~{expected_fp:.1f}.")

    # ── Stage 2 (conditional) ──
    any_bias = any(r.get("bias") == "bias" for r in cell_results)

    print("\n" + "=" * 80)
    print("STAGE 2 — Bracket profitability (conditional on Stage 1 bias)")
    print("=" * 80)

    if not any_bias:
        print("\n  No cell showed Stage 1 directional bias. Stage 2 skipped (NO-GO per verdict mapping).")
        stage2_results = []
    else:
        stage2_results = []
        for pattern_name in PATTERNS_STUDIED:
            for cell in CELL_LABELS:
                s2 = run_stage2(df, pattern_name, cell, cell_results, has_volume)
                if s2 is not None:
                    stage2_results.append(s2)
                    wr = s2.get("win_rate")
                    wr_str = f"{wr:.4f}" if wr is not np.nan and not np.isnan(wr) else "—"
                    pv = s2.get("binom_p_vs_breakeven")
                    p_str = f"{pv:.6f}" if pv is not np.nan and not np.isnan(pv) else "—"
                    er = s2.get("expectancy_R")
                    er_str = f"{er:.4f}" if er is not np.nan and not np.isnan(er) else "—"
                    ran = "RUN" if s2.get("stage2_run") else "skip"
                    print(f"  {pattern_name:<15} {s2['cell']:<8} {ran:>5} trades={s2.get('trade_count',0):>4} wins={s2.get('win_count',0):>4} WR={wr_str:>8} exp_R={er_str:>8} p={p_str:>10}")

    # ── Verdict ──
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    if not any_bias:
        verdict = "NO-GO"
        print(f"\n  Verdict: {verdict}")
        print(f"  Reason: No cell showed Stage 1 directional bias (all p ≥ {ALPHA}).")
        print(f"  Action: Study closes. Ledger: DIRECTIONAL_NO_GO. No design spec.")
    else:
        any_stage2_win = False
        for s2 in stage2_results:
            if s2.get("stage2_run") and s2.get("binom_p_vs_breakeven") is not np.nan:
                if not np.isnan(s2["binom_p_vs_breakeven"]) and s2["binom_p_vs_breakeven"] < ALPHA:
                    any_stage2_win = True
                    break

        if any_stage2_win:
            verdict = "GO (DIRECTIONAL)"
            print(f"\n  Verdict: {verdict}")
            print(f"  Reason: Stage 1 bias AND Stage 2 win rate > 33.3% (p < {ALPHA}) in ≥1 cell.")
            print(f"  Action: Design spec to be drafted. Ledger: PENDING. Suggestive, not gate-eligible.")
        else:
            verdict = "NO-GO"
            print(f"\n  Verdict: {verdict}")
            print(f"  Reason: Stage 1 bias present but Stage 2 win rate ≤ 33.3% (or insufficient trades).")
            print(f"  Action: Study closes. Ledger: DIRECTIONAL_NO_GO. No design spec.")

    print(f"\n  Power: DIRECTIONAL (n_w≈{n_weeks} < 13). Suggestive, never gate-eligible.")
    print(f"  Multiplicity: {n_tests} Stage-1 tests + {len(stage2_results)} Stage-2 tests disclosed.")

    if not has_volume:
        print(f"\n  ⚠ DATA LIMITATION: No volume column in primary CSV.")
        print(f"    Volume-qualified cells (VOL_HIGH) could not be properly evaluated.")
        print(f"    yfinance fallback covers ~730 days only (UNDERPOWERED).")
        print(f"    ATR-rank qualifier (price-only) is unaffected.")

    print("\n" + "=" * 80)
    print("Study complete.")
    print("=" * 80)

    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
