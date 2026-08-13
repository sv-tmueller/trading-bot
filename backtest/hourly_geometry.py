"""Sequential bracket-geometry simulator for the hourly-bot study (#571 step D).

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``.
No LLM, no broker calls. Replays a decisions/geometry CSV emitted by
``scripts/emit_hourly_decisions.ts`` (which calls the REAL ``decideHourly``,
``computeBracketGeometry``, ``computeSizing`` TS exports -- never re-derived here) against
5Min OHLC bars, reusing ``backtest/bracket.py::_resolve_bar`` unchanged for exit resolution.

What this module owns (the STATE-DEPENDENT half of the gate ladder -- the emitter only
computes the stateless half): one-position-at-a-time, cooldown (next bar strictly after the
last exit's fill time), day cap, and flatten-scan detection/execution (the scan+7min cadence
mapping, ``docs/research/2026-08-13-hourly-geometry-cadence-sizing-preregistration.md`` §3).

Conventions (frozen in the pre-registration doc, restated here as the implementation):
STOP-first on a both-touched bar (``_resolve_bar``'s own frozen tie-break); exits are live from
the entry fill bar onward; entry/flatten both fill at the open of the first 5Min bar at/after
the action instant (bar close + ``SCAN_OFFSET_MIN``); ``SLIPPAGE_BPS``/``COMMISSION_BPS`` from
``backtest/regime.py``, with price-level R stats applying slippage only (commission is a
dollar haircut applied only in ``replay_equity``, mirroring #499's own replay formula).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.bracket import LONG, _resolve_bar
from backtest.regime import COMMISSION_BPS, SLIPPAGE_BPS, STARTING_CASH

# The live scan cadence offset (bar close -> scan instant), frozen across every cadence.
SCAN_OFFSET_MIN = 7

# HOURLY_MAX_ENTRIES_PER_DAY's frozen default (config.ts).
DAY_CAP_DEFAULT = 3

# Standard NYSE regular-session hours, assumed for every trading date (disclosed
# simplification -- see the pre-registration doc's §3; half-days are not specially modeled).
SESSION_CLOSE_ET = "16:00"

# SIZING_RISK_PCT's frozen default (config.ts) -- the equity-replay step's risk leg.
SIZING_RISK_PCT_DEFAULT = 0.01

# The -15%-from-start equity floor (logic.ts's EQUITY_FLOOR_PCT, restated here for the
# replay's own breach flag -- this module never imports TS, so the constant is duplicated
# by value, not by reference).
EQUITY_FLOOR_PCT = 0.15

_ET = ZoneInfo("America/New_York")


def session_close_utc_ms(date_str: str, close_hhmm: str = SESSION_CLOSE_ET) -> int:
    """UTC epoch-ms of ``close_hhmm`` (exchange-local ET) on ``date_str`` (YYYY-MM-DD).

    DST-aware via ``zoneinfo`` (the real tz database) -- the Python-side analogue of
    ``hourly-check/logic.ts``'s ``etHHMMToUtcMs`` (Intl-based there; both resolve the same
    wall-clock-ET -> UTC-instant question, just via different but equally correct
    DST-aware primitives).
    """
    year, month, day = (int(x) for x in date_str.split("-"))
    hour, minute = (int(x) for x in close_hhmm.split(":"))
    local = datetime(year, month, day, hour, minute, tzinfo=_ET)
    return int(local.astimezone(timezone.utc).timestamp() * 1000)


def is_flatten_scan(
    date_str: str,
    bar_end_ms: int,
    period_minutes: int,
    *,
    scan_offset_min: int = SCAN_OFFSET_MIN,
) -> bool:
    """True iff the scan for a bar ending at ``bar_end_ms`` is a flatten scan.

    Mirrors the live bot's own rule (``logic.ts``: ``clock.nextClose - nowMs <= HOUR_MS``),
    generalized over an arbitrary cadence period: the scan instant is ``bar_end + scan_offset``
    (the live +7-minute cron-to-close offset), and a scan flattens when the session's close is
    at most one cadence period away from that instant. This is itself a registered modeling
    decision (pre-registration doc §3) for the 30m arm, which has no live counterpart.
    """
    action_instant_ms = bar_end_ms + scan_offset_min * 60_000
    close_ms = session_close_utc_ms(date_str)
    return (close_ms - action_instant_ms) <= period_minutes * 60_000


@dataclass(frozen=True)
class Trade:
    """One simulated round trip. Sizing-invariant by construction -- no ``qty`` here."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float   # executed (slippage-applied)
    exit_price: float    # executed (slippage-applied)
    stop_price: float
    target_price: float
    exit_reason: str     # "target" | "stop" | "flatten" | "end_of_window"
    stop_distance: float
    r_realized: float    # (exit_price - entry_price) / stop_distance, long-only


def _to_utc_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    idx = df.index
    return idx.tz_localize("UTC") if idx.tz is None else idx


def _make_trade(position: Dict, exec_exit: float, exit_time: pd.Timestamp, reason: str) -> Trade:
    stop_distance = position["stop_distance"]
    r_realized = (
        (exec_exit - position["entry_price"]) / stop_distance
        if stop_distance else float("nan")
    )
    return Trade(
        entry_time=position["entry_time"],
        exit_time=exit_time,
        entry_price=position["entry_price"],
        exit_price=exec_exit,
        stop_price=position["stop_price"],
        target_price=position["target_price"],
        exit_reason=reason,
        stop_distance=stop_distance,
        r_realized=r_realized,
    )


def simulate_hourly_geometry(
    decisions: Sequence[dict],
    bars5: pd.DataFrame,
    *,
    period_minutes: int,
    day_cap: int = DAY_CAP_DEFAULT,
    slippage_bps: float = SLIPPAGE_BPS,
) -> dict:
    """Long-only sequential gate loop over ``bars5``, driven by ``decisions``.

    ``decisions`` -- one dict per bar of the emitter's cadence grid, each with
    ``timestamp`` (bar-start), ``action_final`` ("LONG"/"SKIP"), and (when LONG)
    ``entry_ref``/``stop_price``/``stop_distance``/``target_price`` for the R arm being
    simulated. ``bars5`` -- a 5Min OHLC DataFrame (``intraday_data.load_local``'s shape),
    spanning at least the same window as ``decisions``.

    Returns ``{"trades": [Trade, ...]}``.
    """
    slip = slippage_bps / 10_000.0

    dec: List[dict] = []
    for row in decisions:
        ts = pd.Timestamp(row["timestamp"])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        bar_start_ms = int(ts.value // 1_000_000)
        bar_end_ms = bar_start_ms + period_minutes * 60_000
        date_str = ts.strftime("%Y-%m-%d")
        dec.append({
            "timestamp_ms": bar_start_ms,
            "date": date_str,
            "action_instant_ms": bar_end_ms + SCAN_OFFSET_MIN * 60_000,
            "is_flatten": is_flatten_scan(date_str, bar_end_ms, period_minutes),
            "action_final": row.get("action_final"),
            "stop_price": row.get("stop_price"),
            "stop_distance": row.get("stop_distance"),
            "target_price": row.get("target_price"),
        })
    dec.sort(key=lambda d: d["timestamp_ms"])

    idx = _to_utc_index(bars5)
    ts_ms = (idx.asi8 // 1_000_000)
    opens = bars5["Open"].to_numpy(dtype=float)
    highs = bars5["High"].to_numpy(dtype=float)
    lows = bars5["Low"].to_numpy(dtype=float)
    closes = bars5["Close"].to_numpy(dtype=float)
    n = len(ts_ms)

    position: Optional[dict] = None
    trades: List[Trade] = []
    entries_today: Dict[str, int] = {}
    last_exit_ms: Optional[int] = None
    d_idx = 0
    n_dec = len(dec)

    for i in range(n):
        t5 = int(ts_ms[i])

        # (a) Exit resolution, strictly after the entry fill bar (exits are live from
        # the fill bar onward -- the fill bar itself is never tested for an exit).
        if position is not None and t5 > position["entry_bar_ms"]:
            res = _resolve_bar(
                opens[i], highs[i], lows[i],
                position["stop_price"], position["target_price"], LONG,
            )
            if res is not None:
                fill_level, reason = res
                exec_exit = fill_level * (1 - slip)
                trades.append(_make_trade(position, exec_exit, idx[i], reason))
                last_exit_ms = t5
                position = None

        # (b) Process every decision whose action instant has arrived by this bar (the
        # "first 5Min bar open at/after the action instant" fill convention).
        while d_idx < n_dec and dec[d_idx]["action_instant_ms"] <= t5:
            row = dec[d_idx]
            d_idx += 1

            if row["is_flatten"]:
                if position is not None:
                    exec_exit = opens[i] * (1 - slip)
                    trades.append(_make_trade(position, exec_exit, idx[i], "flatten"))
                    last_exit_ms = t5
                    position = None
                continue  # flatten scans never enter, regardless of action_final

            if position is None and row["action_final"] == "LONG":
                if last_exit_ms is not None and row["timestamp_ms"] <= last_exit_ms:
                    continue  # cooldown: this decision's OWN bar is not after the last exit
                if entries_today.get(row["date"], 0) >= day_cap:
                    continue  # day cap reached
                exec_entry = opens[i] * (1 + slip)
                position = {
                    "entry_bar_ms": t5,
                    "entry_time": idx[i],
                    "entry_price": exec_entry,
                    "stop_price": row["stop_price"],
                    "target_price": row["target_price"],
                    "stop_distance": row["stop_distance"],
                }
                entries_today[row["date"]] = entries_today.get(row["date"], 0) + 1

    if position is not None:
        exec_exit = closes[-1] * (1 - slip)
        trades.append(_make_trade(position, exec_exit, idx[-1], "end_of_window"))

    return {"trades": trades}


def no_flatten_counterfactual(
    flattened_trades: Sequence[Trade],
    bars5: pd.DataFrame,
    *,
    slippage_bps: float = SLIPPAGE_BPS,
) -> List[Trade]:
    """The registered diagnostic: let each ``flatten``-exited trade run to resolution.

    Independent per trade (does not re-run entries/gating) -- continues the SAME
    stop/target through ``_resolve_bar`` from the bar strictly after the original flatten
    bar, until it naturally resolves or the data ends (``end_of_window``, disclosed as rare).
    """
    slip = slippage_bps / 10_000.0
    idx = _to_utc_index(bars5)
    ts_ms = (idx.asi8 // 1_000_000)
    opens = bars5["Open"].to_numpy(dtype=float)
    highs = bars5["High"].to_numpy(dtype=float)
    lows = bars5["Low"].to_numpy(dtype=float)
    closes = bars5["Close"].to_numpy(dtype=float)
    n = len(ts_ms)

    out: List[Trade] = []
    for t in flattened_trades:
        exit_ms = int(pd.Timestamp(t.exit_time).value // 1_000_000)
        start_i = int(np.searchsorted(ts_ms, exit_ms, side="left"))
        resolved: Optional[Trade] = None
        i = start_i + 1  # strictly after the original flatten bar
        while i < n:
            res = _resolve_bar(opens[i], highs[i], lows[i], t.stop_price, t.target_price, LONG)
            if res is not None:
                fill_level, reason = res
                exec_exit = fill_level * (1 - slip)
                resolved = Trade(
                    entry_time=t.entry_time, exit_time=idx[i],
                    entry_price=t.entry_price, exit_price=exec_exit,
                    stop_price=t.stop_price, target_price=t.target_price,
                    exit_reason=reason, stop_distance=t.stop_distance,
                    r_realized=(
                        (exec_exit - t.entry_price) / t.stop_distance
                        if t.stop_distance else float("nan")
                    ),
                )
                break
            i += 1
        if resolved is None:
            exec_exit = closes[-1] * (1 - slip)
            resolved = Trade(
                entry_time=t.entry_time, exit_time=idx[-1],
                entry_price=t.entry_price, exit_price=exec_exit,
                stop_price=t.stop_price, target_price=t.target_price,
                exit_reason="end_of_window", stop_distance=t.stop_distance,
                r_realized=(
                    (exec_exit - t.entry_price) / t.stop_distance
                    if t.stop_distance else float("nan")
                ),
            )
        out.append(resolved)
    return out


def replay_equity(
    trades: Sequence[Trade],
    cap_pct: float,
    *,
    risk_pct: float = SIZING_RISK_PCT_DEFAULT,
    starting_cash: float = STARTING_CASH,
    commission_bps: float = COMMISSION_BPS,
) -> dict:
    """Replay a sizing-invariant trade ledger under ``min(qtyRisk, qtyCap)`` sizing.

    #499's own established method, reused verbatim: per-trade R stats do not depend on
    quantity, so the base simulation runs once and this function re-derives dollar P&L
    per sizing cap on a compounding equity curve. Commission (unlike slippage) is applied
    here only, as a dollar haircut on both legs -- mirrors #499's appendix replay formula.
    """
    comm = commission_bps / 10_000.0
    equity = float(starting_cash)
    curve = [equity]
    breached = False
    floor = starting_cash * (1 - EQUITY_FLOOR_PCT)
    for t in trades:
        d = t.stop_distance
        qty_risk = int(risk_pct * equity / d) if d and d > 0 else 10**12
        qty_cap = int(cap_pct * equity / t.entry_price) if t.entry_price > 0 else 0
        qty = max(min(qty_risk, qty_cap), 0)
        pnl = qty * t.exit_price * (1 - comm) - qty * t.entry_price * (1 + comm)
        equity += pnl
        curve.append(equity)
        if equity <= floor:
            breached = True
    eq_arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(eq_arr)
    max_dd = float(np.min(eq_arr / peak - 1.0)) if len(eq_arr) else 0.0
    return {
        "ending_equity": equity,
        "total_return": equity / starting_cash - 1.0,
        "max_drawdown": max_dd,
        "breached_15pct_floor": breached,
        "curve": eq_arr,
    }


def cost_drag_diagnostic(trades: Sequence[Trade], *, slippage_bps: float = SLIPPAGE_BPS) -> dict:
    """Quantifies how much of the planned risk unit (``stop_distance``) round-trip
    slippage alone consumes -- the mechanism behind the verdict doc's "cost-geometry
    interaction" finding: a bracket geometry whose stop distance is a small fraction of
    price (the hourly buffer is 5% of an hourly bar's own range) can be materially eroded
    by the SAME frozen ``SLIPPAGE_BPS``/``COMMISSION_BPS`` cost constants a daily-bar
    study (with dollar-wide ATR stops) would treat as negligible.

    Reconstructs each trade's pre-slippage entry reference from its (post-slippage)
    ``entry_price`` (``entry_price = entryRef * (1 + slip)`` for a long), since ``Trade``
    itself only stores the executed price.
    """
    if not trades:
        return {
            "n": 0, "median_cost_over_stop_distance": float("nan"),
            "pct_entry_slippage_exceeds_stop_distance": float("nan"),
        }
    slip = slippage_bps / 10_000.0
    entry_ref = np.array([t.entry_price / (1 + slip) for t in trades])
    cost_price = entry_ref * slip
    stop_d = np.array([t.stop_distance for t in trades])
    frac = np.divide(cost_price, stop_d, out=np.full_like(cost_price, np.inf), where=stop_d > 0)
    return {
        "n": len(trades),
        "median_stop_distance": float(np.median(stop_d)),
        "median_entry_slippage_cost": float(np.median(cost_price)),
        "median_cost_over_stop_distance": float(np.median(frac)),
        "pct_entry_slippage_exceeds_stop_distance": float(np.mean(frac >= 1.0) * 100),
    }


def exit_distribution(trades: Sequence[Trade]) -> Dict[str, int]:
    """Count of trades per exit reason -- the per-arm exit-distribution report."""
    counts: Dict[str, int] = {}
    for t in trades:
        counts[t.exit_reason] = counts.get(t.exit_reason, 0) + 1
    return counts


def expectancy_r(trades: Sequence[Trade]) -> float:
    """Mean realized R across a trade ledger. NaN for an empty ledger."""
    if not trades:
        return float("nan")
    return float(np.mean([t.r_realized for t in trades]))


def load_decisions_csv(path: str, r_multiple: float) -> List[dict]:
    """Load an emitter-output decisions CSV, selecting the target-price column for
    ``r_multiple`` (one of ``scripts/emit_hourly_decisions.ts``'s ``R_MULTIPLES``).
    """
    df = pd.read_csv(path)
    col = f"target_price_r{r_multiple:.1f}".replace(".", "_")
    if col not in df.columns:
        raise ValueError(f"decisions CSV has no column {col!r}; got {list(df.columns)}")

    def _num(v):
        return None if pd.isna(v) else float(v)

    rows: List[dict] = []
    for _, row in df.iterrows():
        rows.append({
            "timestamp": row["timestamp"],
            "action_final": row["action_final"],
            "entry_ref": _num(row["entry_ref"]),
            "stop_price": _num(row["stop_price"]),
            "stop_distance": _num(row["stop_distance"]),
            "target_price": _num(row[col]),
        })
    return rows
