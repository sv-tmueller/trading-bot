"""Nightly reflection engine (#578, spec `docs/superpowers/specs/2026-08-14-reflection-loop-design.md`
sec 3/4). Stage 1 of the three-stage reflection loop (sec 2): fully deterministic, no LLM, no
network, no DB -- turns one trading day's record into a `## Reflection` markdown section plus a
structured `reflection` object for the daily-verification JSONL ledger row.

This module is the FROZEN INTERFACE the next batch (verification-workflow wiring, #578's
sibling package) codes against: the input schema below, the output envelope in `compute_reflection`,
and every field name in the `reflection` object are goldened by `tests/test_reflection.py`.

Research-only. Lives in ``backtest/`` and is never imported by ``supabase/functions/``. No LLM
SDK, no broker client import, no second decision rule -- this module only reports on trades the
live bot already made; it never feeds back into config or the trading path (spec sec 6/7).

Input contract (frozen; the CLI ``backtest/run_nightly_reflection.py`` reads all three local
files, no network, no DB):

- ``--digest``: the `status` verify digest JSON. Only ``.verification.scans`` (``HourlyScanRow``
  values, ``supabase/functions/_shared/db.ts`` line 483) and ``.verification.trades``
  (``TradeRow`` values, ``db.ts`` line 141) are read -- the same shape
  ``scripts/daily_verify.ts`` already consumes (lines 32-67), so this engine needs no new
  DB access pattern.
- ``--bars``: the day's 5Min OHLC bars, ``backtest/intraday_data.py::load_local``'s shape
  (a DataFrame indexed by UTC timestamp with Open/High/Low/Close columns). The wiring batch
  fetches this file; this engine is agnostic to how wide the window is (a narrower window
  than the full day degrades individual counterfactuals to ``data: "unavailable"``, never
  raises).
- ``--ledger``: ``docs/trading-journal/daily-verification.jsonl``, one JSON object per line
  (``scripts/daily_verify.ts``'s ``LedgerRow``). Prior rows may carry a ``reflection.trades``
  array (this engine's own prior output) -- pre-ship rows have no ``reflection`` key at all
  (no backfill, spec sec 7), so the trailing window starts small.

Output envelope (stdout, one line of JSON): ``{date, markdown, reflection}``. Exit 0 once the
CLI's own arguments and the three files parse as well-formed JSON/CSV; a reflection-computation
failure (e.g. a malformed bar frame, an unresolvable trade) degrades to
``reflection: {engine_version, error: "<reason>", ...}`` and ``markdown: "Reflection: error --
<reason>"`` rather than raising (spec sec 4) -- only a CLI argument or JSON-parse failure at the
input boundary itself exits 1 with nothing printed, mirroring ``scripts/daily_verify.ts``'s own
CLI discipline.

Reuse, never re-derive (the load-bearing imports this module must never reimplement):

- ``backtest.bracket._resolve_bar`` -- the frozen open-gap-first / STOP-first tie-break / D3
  target-cap fill resolver, imported exactly like ``backtest/hourly_geometry.py`` line 31.
- ``backtest.hourly_geometry.no_flatten_counterfactual`` -- the registered "let a flattened
  trade run to resolution" diagnostic, reused for the per-trade flatten counterfactual.
- ``backtest.hourly_geometry.session_close_utc_ms`` / ``is_flatten_scan`` -- the scan+7min
  cadence mapping that identifies the day's one flatten-eligible hourly scan, reused to derive
  the same-day flatten cutoff a still-open counterfactual would have hit.
- The trade **pairing** walk (entry/exit reason sets, FIFO per symbol, ``panic_cli`` excluded,
  scan join via ``entry_order_id``) is a byte-for-byte Python port of
  ``scripts/render_weekly_journal.ts``'s ``pairHourlyTrades`` (same reason-string sets, same
  ordering) -- kept in sync manually across the TS/Python boundary, the same precedent as
  ``EQUITY_FLOOR_PCT`` in ``hourly_geometry.py``.

Pinned interpretations (architect calls, batch #577 lead-approved):

1. **Stop-width scaling is DISTANCE scaling, not buffer-only.** "Stop at 1.25x/1.5x the frozen
   buffer distance" means ``stop_k = entry_ref -/+ k * (entry_ref - stop_price)`` (long; short
   mirrored), holding the target price UNCHANGED and expressing the counterfactual R in the
   ORIGINAL ``risk_per_share`` (stop distance) unit -- never the scaled one. Scaling only the
   0.05-of-range buffer would move the stop about 1 percent (meaningless), and the journaled
   scan row carries no signal-bar high/low to rescale the buffer alone.
2. **Counterfactual geometry is derived from ``entry_ref_price``** (the journaled reference,
   matching how ``computeBracketGeometry`` itself derives stop/target), cents-quantized the
   same way; but the counterfactual's **entry point in time and price is the actual fill**
   (same entry, alternate exit only) and every counterfactual R-multiple is computed against
   that same actual entry fill price, so it is directly comparable to the trade's own realized R.
3. **Flatten cutoff for a still-open counterfactual**: a still-open counterfactual flattens at
   the REAL trade's own flatten fill time when the real trade itself flattened
   (``hourly_session_close_exit``/``hourly_kill_switch``); otherwise at the day's one
   flatten-eligible scan (identified via ``is_flatten_scan`` applied to every scan row on the
   date, taking the EARLIEST bar that qualifies -- the live bot flattens at the first
   opportunity, so later-qualifying scans are moot).
4. **MAE-beyond-stop is computed uniformly for every closed trade** (not only realized
   stop-outs): the worst excursion past the ORIGINAL (unscaled) stop level seen in any bar from
   strictly after entry through the end of the supplied bar window. A trade that never
   approached its stop reports ``0`` -- by construction of ``_resolve_bar``'s own STOP-first
   tie-break, a trade that exited at target never touched its stop on any earlier bar either.
5. **Deviation reason** is exactly one of three words (spec sec 3's own vocabulary --
   "gap, slippage, flatten"): ``"gap"`` when a bracket exit filled strictly beyond the stop
   level (a gap-through-stop), ``"flatten"`` for ``hourly_session_close_exit``/
   ``hourly_kill_switch`` exits, ``"slippage"`` for every other (clean stop/target) fill -- the
   frozen ``SLIPPAGE_BPS`` cost is the only source of nominal-vs-realized divergence there.

Trailing-20 (spec sec 2 key decision 2): a STATELESS fold over the ledger's prior
``reflection.trades`` records plus today's freshly computed trades, ordered by exit fill time,
window = ``min(n, 20)`` with ``n`` printed next to every number -- never carried state, since the
spec fetches only the day's own bars and cannot recompute a prior day's counterfactuals nightly.

Deterministic hypothesis triggers (spec sec 3, exactly three in v1; boundary semantics pinned by
test): (1) "at least 60%" of the trailing stop-outs would have survived at 1.25x stop width --
fires at exactly 0.60 (``>=``); (2) a closer R-target (1.0 or 1.5) beats live (2R) cumulatively
over the trailing window -- fires on a strict cumulative-R improvement; (3) realized cost
(median absolute per-fill slippage bps) diverges from the frozen 5bps model by more than 2x or
less than 0.5x -- "more than 2x" does NOT fire at exactly 2.0 (strict ``>``/``<``). No minimum-n
gate: the engine files no issues (the weekly agent and the operator judge noise), so it evaluates
whatever window it has and always prints ``n``.

Next-batch pointer (spec sec 8 packaging item 2, out of scope here): wiring this engine into
``.github/workflows/daily-verification.yml`` (needs setup-python + pip install), appending the
markdown section after "Changed since the previous verified day", and merging the ``reflection``
object onto the JSONL ledger row are the next package's job -- this module is the frozen contract
that package codes against, not the caller.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.bracket import LONG, SHORT, _resolve_bar
from backtest.intraday_data import load_local
from backtest.hourly_geometry import SCAN_OFFSET_MIN, is_flatten_scan
from backtest.hourly_geometry import Trade as _GeometryTrade
from backtest.hourly_geometry import no_flatten_counterfactual as _no_flatten_counterfactual
from backtest.regime import SLIPPAGE_BPS

ENGINE_VERSION = "reflection-v1"

# Cross-referenced with scripts/render_weekly_journal.ts lines 320-325 (pairHourlyTrades'
# own ENTRY_REASONS/EXIT_REASONS) -- kept in sync manually across the TS/Python boundary,
# same precedent as EQUITY_FLOOR_PCT in backtest/hourly_geometry.py.
ENTRY_REASONS = frozenset({"hourly_long_entry", "hourly_short_entry"})
EXIT_REASONS = frozenset(
    {"hourly_bracket_exit", "hourly_session_close_exit", "hourly_kill_switch"}
)
PANIC_REASON = "panic_cli"


def _side_for_entry_reason(reason: str) -> str:
    return "SHORT" if reason == "hourly_short_entry" else "LONG"


@dataclass
class ClosedTrade:
    """One paired round-trip -- the Python analogue of pairHourlyTrades' ClosedTradeResult
    (render_weekly_journal.ts line 327), plus the joined scan row this engine additionally
    needs for counterfactual geometry (stop/target/risk_per_share/detectors_fired)."""

    symbol: str
    side: str
    entry_fill_price: float
    entry_fill_time: str
    entry_order_id: str
    exit_fill_price: float
    exit_fill_time: str
    exit_order_id: str
    exit_reason: str
    qty: int
    scan: Optional[Dict[str, Any]]
    r_multiple: Optional[float]
    r_multiple_na_reason: Optional[str]


@dataclass
class PairingResult:
    closed_trades: List[ClosedTrade]
    open_entries: List[Dict[str, Any]]
    orphan_exits: List[Dict[str, Any]]
    manual_interventions: List[Dict[str, Any]]


def classify_exit(
    side: str,
    exit_reason: str,
    fill_price: float,
    stop_price: Optional[float],
    target_price: Optional[float],
) -> "tuple[str, str]":
    """Classifies a paired exit into ``(exit_type, deviation_reason)``.

    ``exit_type`` is one of ``"target" | "stop" | "flatten" | "kill_switch"``.
    ``hourly_bracket_exit`` alone doesn't say which OCO leg filled (pinned rule): a fill
    at or beyond the journaled ``stop_price`` on the adverse side is classified STOP (a fill
    strictly beyond it is a gap-through-stop); otherwise the exit is classified by whichever
    of ``stop_price``/``target_price`` the fill landed nearest to.

    ``deviation_reason`` is exactly one of the three words spec sec 3 uses for "the
    mechanical reason for the deviation" between nominal and realized R: ``"gap"`` (a
    gap-through-stop), ``"flatten"`` (session-close or kill-switch -- both are time/risk
    forced exits, not a bracket leg), or ``"slippage"`` (every other, clean stop/target
    fill -- the frozen SLIPPAGE_BPS cost is the only source of divergence there).
    """
    if exit_reason == "hourly_session_close_exit":
        return "flatten", "flatten"
    if exit_reason == "hourly_kill_switch":
        return "kill_switch", "flatten"

    # hourly_bracket_exit: disambiguate the OCO leg from the fill price alone.
    is_long = side == "LONG"
    beyond_stop = fill_price <= stop_price if is_long else fill_price >= stop_price
    if beyond_stop:
        gapped = fill_price < stop_price if is_long else fill_price > stop_price
        return "stop", ("gap" if gapped else "slippage")

    d_stop = abs(fill_price - stop_price)
    d_target = abs(fill_price - target_price)
    exit_type = "stop" if d_stop <= d_target else "target"
    return exit_type, "slippage"


def entry_slippage_bps(side: str, fill_price: float, entry_ref_price: float) -> float:
    """Signed bps of the entry fill vs the journaled reference, adverse positive by side."""
    adverse = (fill_price - entry_ref_price) if side == "LONG" else (entry_ref_price - fill_price)
    return adverse / entry_ref_price * 10_000.0


def exit_slippage_bps(side: str, fill_price: float, reference_price: float) -> float:
    """Signed bps of the exit fill vs its classified reference level, adverse positive."""
    adverse = (reference_price - fill_price) if side == "LONG" else (fill_price - reference_price)
    return adverse / reference_price * 10_000.0


def nominal_r(
    exit_type: str,
    side: str,
    stop_price: float,
    target_price: float,
    risk_per_share: float,
) -> Optional[float]:
    """What the exit "should" have realized (no slippage/gap) given its classified type.

    ``None`` for flatten/kill_switch exits: there is no fixed nominal outcome for a
    time/risk-forced exit, only for a bracket leg. For a stop exit this is always exactly
    ``-1.0`` (the unit-risk definition of ``risk_per_share``). For a target exit,
    ``entry_ref_price`` is not needed: since ``risk_per_share = |entry_ref - stop_price|``
    and ``target_price = entry_ref +/- R * risk_per_share`` (``computeBracketGeometry``'s own
    identity), ``R`` recovers algebraically from stop/target/risk_per_share alone.
    """
    if exit_type == "stop":
        return -1.0
    if exit_type == "target":
        sign = 1 if side == "LONG" else -1
        return sign * (target_price - stop_price) / risk_per_share - 1.0
    return None


def _round_to_cents(value: float) -> float:
    """Mirrors supabase/functions/_shared/num.ts's roundToCents (Math.round semantics --
    round-half-up-toward-+Infinity, not Python's round()'s banker's rounding)."""
    return math.floor(value * 100 + 0.5) / 100


def _direction(side: str) -> str:
    return LONG if side == "LONG" else SHORT


def _to_utc_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    return _ensure_utc_index(df.index)


def _ensure_utc_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_localize("UTC") if idx.tz is None else idx


def scaled_stop_price(
    side: str, entry_ref_price: float, stop_price: float, multiple: float
) -> float:
    """Pinned interpretation 1: scale the journaled stop DISTANCE, not the buffer alone.

    ``stop_k = entry_ref -/+ multiple * (entry_ref - stop_price)`` (long; short mirrored).
    Not cents-quantized (this is a diagnostic distance scaling, not a value that ever
    reaches computeBracketGeometry's own rounding step -- see pinned interpretation 2,
    which applies only to the R-target counterfactual's derived price).
    """
    distance = entry_ref_price - stop_price if side == "LONG" else stop_price - entry_ref_price
    scaled = distance * multiple
    return entry_ref_price - scaled if side == "LONG" else entry_ref_price + scaled


def target_r_price(
    side: str, entry_ref_price: float, stop_price: float, r_multiple: float
) -> float:
    """Pinned interpretation 2: derive the counterfactual target from ``entry_ref_price``
    exactly like ``computeBracketGeometry`` (raw target, then cents-quantized)."""
    stop_distance = abs(entry_ref_price - stop_price)
    raw_target = (
        entry_ref_price + r_multiple * stop_distance
        if side == "LONG"
        else entry_ref_price - r_multiple * stop_distance
    )
    return _round_to_cents(raw_target)


def walk_bracket_to_resolution(
    bars5: pd.DataFrame,
    side: str,
    after_time: Any,
    stop_price: float,
    target_price: Optional[float],
    *,
    flatten_time: Any = None,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Optional[Dict[str, Any]]:
    """Replays a bracket strictly after ``after_time`` until ``backtest.bracket._resolve_bar``
    fires or ``flatten_time`` is reached, whichever comes first (pinned interpretation 3).

    Reuses ``_resolve_bar`` unchanged -- the open-gap-first / STOP-first tie-break / D3
    target-cap conventions are frozen there, never re-derived here. Returns
    ``{"exit_price", "exit_reason", "exit_time"}`` or ``None`` when the supplied bar window
    ends with the position still open (the caller degrades that counterfactual to
    ``data: "unavailable"`` rather than raising).
    """
    direction = _direction(side)
    slip = slippage_bps / 10_000.0
    idx = _to_utc_index(bars5)
    ts_ms = idx.asi8 // 1_000_000
    opens = bars5["Open"].to_numpy(dtype=float)
    highs = bars5["High"].to_numpy(dtype=float)
    lows = bars5["Low"].to_numpy(dtype=float)

    after_ms = int(pd.Timestamp(after_time).value // 1_000_000)
    flatten_ms = (
        int(pd.Timestamp(flatten_time).value // 1_000_000) if flatten_time is not None else None
    )
    start_i = int(np.searchsorted(ts_ms, after_ms, side="right"))

    for i in range(start_i, len(ts_ms)):
        if flatten_ms is not None and ts_ms[i] >= flatten_ms:
            fill = opens[i] * (1 - slip) if direction == LONG else opens[i] * (1 + slip)
            return {"exit_price": float(fill), "exit_reason": "flatten", "exit_time": idx[i]}
        res = _resolve_bar(opens[i], highs[i], lows[i], stop_price, target_price, direction)
        if res is not None:
            level, reason = res
            fill = level * (1 - slip) if direction == LONG else level * (1 + slip)
            return {"exit_price": float(fill), "exit_reason": reason, "exit_time": idx[i]}
    return None


def session_flatten_time(
    date_str: str,
    scans_for_date: List[Dict[str, Any]],
    bars_index: pd.DatetimeIndex,
    *,
    period_minutes: int = 60,
) -> Optional[pd.Timestamp]:
    """The day's ONE flatten-eligible hourly scan's fill time, or ``None``.

    Reuses ``is_flatten_scan``/``session_close_utc_ms`` (imported, never re-derived) over
    every scan bar_ts on the date -- more than one bar can technically qualify (headroom
    keeps shrinking as the day goes on), so this takes the EARLIEST qualifying bar: the
    live bot flattens at the first opportunity, so later-qualifying scans are moot.
    """
    seen: set = set()
    candidate_bar_ends: List[int] = []
    for s in scans_for_date:
        bar_ts = s.get("bar_ts")
        if not bar_ts or bar_ts in seen:
            continue
        seen.add(bar_ts)
        bar_start_ms = int(pd.Timestamp(bar_ts).value // 1_000_000)
        bar_end_ms = bar_start_ms + period_minutes * 60_000
        if is_flatten_scan(date_str, bar_end_ms, period_minutes):
            candidate_bar_ends.append(bar_end_ms)
    if not candidate_bar_ends:
        return None
    action_instant_ms = min(candidate_bar_ends) + SCAN_OFFSET_MIN * 60_000
    idx = _ensure_utc_index(bars_index)
    ts_ms = idx.asi8 // 1_000_000
    pos = int(np.searchsorted(ts_ms, action_instant_ms, side="left"))
    if pos >= len(ts_ms):
        return None
    return idx[pos]


def r_target_counterfactual(
    bars5: pd.DataFrame,
    *,
    side: str,
    entry_fill_time: Any,
    entry_fill_price: float,
    entry_ref_price: float,
    stop_price: float,
    risk_per_share: float,
    r_multiple: float,
    flatten_time: Any = None,
) -> Dict[str, Any]:
    """Same entry, alternate (closer) R-target -- stop unchanged (pinned interpretation 2)."""
    target_k = target_r_price(side, entry_ref_price, stop_price, r_multiple)
    res = walk_bracket_to_resolution(
        bars5, side, entry_fill_time, stop_price, target_k, flatten_time=flatten_time,
    )
    if res is None:
        return {"r_multiple": r_multiple, "data": "unavailable"}
    sign = 1 if side == "LONG" else -1
    r = sign * (res["exit_price"] - entry_fill_price) / risk_per_share
    return {
        "r_multiple": r_multiple,
        "exit_price": res["exit_price"],
        "exit_reason": res["exit_reason"],
        "exit_time": str(res["exit_time"]),
        "r": r,
        "data": "ok",
    }


def stop_width_counterfactual(
    bars5: pd.DataFrame,
    *,
    side: str,
    entry_fill_time: Any,
    entry_fill_price: float,
    entry_ref_price: float,
    stop_price: float,
    target_price: float,
    risk_per_share: float,
    multiple: float,
    flatten_time: Any = None,
) -> Dict[str, Any]:
    """Same entry and target, alternate (wider) stop (pinned interpretation 1). ``survived``
    is true iff the widened stop was NOT the counterfactual's own exit."""
    stop_k = scaled_stop_price(side, entry_ref_price, stop_price, multiple)
    res = walk_bracket_to_resolution(
        bars5, side, entry_fill_time, stop_k, target_price, flatten_time=flatten_time,
    )
    if res is None:
        return {"multiple": multiple, "data": "unavailable"}
    sign = 1 if side == "LONG" else -1
    # Counterfactual R stays in the ORIGINAL risk_per_share unit (never the scaled stop's
    # own distance) -- pinned interpretation 1.
    r = sign * (res["exit_price"] - entry_fill_price) / risk_per_share
    return {
        "multiple": multiple,
        "stop_price": stop_k,
        "exit_price": res["exit_price"],
        "exit_reason": res["exit_reason"],
        "exit_time": str(res["exit_time"]),
        "r": r,
        "survived": res["exit_reason"] != "stop",
        "data": "ok",
    }


def mae_beyond_stop_r(
    bars5: pd.DataFrame,
    *,
    side: str,
    after_time: Any,
    stop_price: float,
    risk_per_share: float,
) -> Optional[float]:
    """Worst excursion past the ORIGINAL stop level, in R units, seen in any bar strictly
    after ``after_time`` through the end of the supplied window (pinned interpretation 4).

    Computed uniformly for every trade, not only realized stop-outs: by construction of
    ``_resolve_bar``'s own STOP-first tie-break, a trade whose real exit was "target" never
    touched its stop on any earlier bar either, so this naturally reports ``0.0`` for it.
    """
    idx = _to_utc_index(bars5)
    ts_ms = idx.asi8 // 1_000_000
    after_ms = int(pd.Timestamp(after_time).value // 1_000_000)
    start_i = int(np.searchsorted(ts_ms, after_ms, side="right"))
    if start_i >= len(ts_ms):
        return None
    if side == "LONG":
        worst = float(np.min(bars5["Low"].to_numpy(dtype=float)[start_i:]))
        beyond = max(0.0, stop_price - worst)
    else:
        worst = float(np.max(bars5["High"].to_numpy(dtype=float)[start_i:]))
        beyond = max(0.0, worst - stop_price)
    return beyond / risk_per_share


def no_flatten_counterfactual_for_trade(
    *,
    side: str,
    entry_fill_time: Any,
    entry_fill_price: float,
    exit_fill_time: Any,
    exit_fill_price: float,
    stop_price: float,
    target_price: float,
    risk_per_share: float,
    exit_type: str,
    bars5: pd.DataFrame,
) -> Dict[str, Any]:
    """Delegates to ``backtest.hourly_geometry.no_flatten_counterfactual`` (the registered
    "let a flattened trade run to resolution" diagnostic) -- never re-derived here.

    Only applicable to an actual ``"flatten"`` exit (a scheduled session-close, not a
    kill-switch liquidation, which is risk- not time-based). ``no_flatten_counterfactual``
    itself is LONG-only (it hardcodes ``LONG`` into ``_resolve_bar``, per its own module) --
    a short flatten degrades to ``data: "unavailable"`` rather than silently mis-simulating
    a mirrored exit the reused function was never written to support.
    """
    if exit_type != "flatten":
        return {"applicable": False}
    if side != "LONG":
        return {"applicable": True, "data": "unavailable"}
    geom_trade = _GeometryTrade(
        entry_time=pd.Timestamp(entry_fill_time),
        exit_time=pd.Timestamp(exit_fill_time),
        entry_price=entry_fill_price,
        exit_price=exit_fill_price,
        stop_price=stop_price,
        target_price=target_price,
        exit_reason="flatten",
        stop_distance=risk_per_share,
        r_realized=(exit_fill_price - entry_fill_price) / risk_per_share if risk_per_share else float("nan"),
    )
    results = _no_flatten_counterfactual([geom_trade], bars5)
    if not results:
        return {"applicable": True, "data": "unavailable"}
    r = results[0]
    return {
        "applicable": True,
        "data": "ok",
        "exit_price": r.exit_price,
        "exit_reason": r.exit_reason,
        "exit_time": str(r.exit_time),
        "r": r.r_realized,
    }


TARGET_R_MULTIPLES = (1.0, 1.5)
STOP_WIDTH_MULTIPLES = (1.25, 1.5)


def _bar_open_at(bars5: pd.DataFrame, ts: Any) -> Optional[float]:
    """The Open of the bar at exactly ``ts``, or ``None`` when that bar isn't present
    (missing/partial bars degrade gracefully -- spec sec 4)."""
    idx = _to_utc_index(bars5)
    target_ms = int(pd.Timestamp(ts).value // 1_000_000)
    ts_ms = idx.asi8 // 1_000_000
    pos = int(np.searchsorted(ts_ms, target_ms, side="left"))
    if pos >= len(ts_ms) or int(ts_ms[pos]) != target_ms:
        return None
    return float(bars5["Open"].to_numpy(dtype=float)[pos])


def compute_trade_record(
    ct: ClosedTrade,
    bars5: pd.DataFrame,
    date_str: str,
    day_scans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assembles one closed trade's full reflection record: classification, slippage,
    nominal/realized R, deviation reason, and all six counterfactuals (pinned interpretations
    1-4). Degrades gracefully (never raises) when the entry's scan row or the bars needed for
    a given counterfactual are unavailable -- each counterfactual reports its own
    ``data: "unavailable"`` rather than failing the whole trade record.
    """
    record: Dict[str, Any] = {
        "entry_order_id": ct.entry_order_id,
        "symbol": ct.symbol,
        "side": ct.side,
        "qty": ct.qty,
        "entry_fill_price": ct.entry_fill_price,
        "entry_fill_time": ct.entry_fill_time,
        "exit_fill_price": ct.exit_fill_price,
        "exit_fill_time": ct.exit_fill_time,
        "exit_order_reason": ct.exit_reason,
        "realized_r": ct.r_multiple,
    }
    if ct.r_multiple_na_reason is not None:
        record["r_multiple_na_reason"] = ct.r_multiple_na_reason

    scan = ct.scan
    if scan is None or scan.get("stop_price") is None or scan.get("target_price") is None:
        record["exit_type"] = "unknown"
        record["deviation_reason"] = None
        record["nominal_r"] = None
        record["entry_slippage_bps"] = None
        record["exit_slippage_bps"] = None
        record["detectors_fired"] = []
        record["counterfactuals"] = {"data": "unavailable"}
        return record

    entry_ref_price = scan["entry_ref_price"]
    stop_price = scan["stop_price"]
    target_price = scan["target_price"]
    risk_per_share = scan.get("risk_per_share")
    record["detectors_fired"] = scan.get("detectors_fired") or []

    exit_type, deviation_reason = classify_exit(
        ct.side, ct.exit_reason, ct.exit_fill_price, stop_price, target_price,
    )
    record["exit_type"] = exit_type
    record["deviation_reason"] = deviation_reason

    if entry_ref_price is not None:
        record["entry_slippage_bps"] = entry_slippage_bps(ct.side, ct.entry_fill_price, entry_ref_price)
    else:
        record["entry_slippage_bps"] = None

    if exit_type == "target":
        reference = target_price
    elif exit_type == "stop":
        reference = stop_price
    else:  # flatten / kill_switch: reference is the bar open at the exit's own fill time.
        reference = _bar_open_at(bars5, ct.exit_fill_time)
    record["exit_slippage_bps"] = (
        exit_slippage_bps(ct.side, ct.exit_fill_price, reference) if reference is not None else None
    )

    record["nominal_r"] = (
        nominal_r(exit_type, ct.side, stop_price, target_price, risk_per_share)
        if risk_per_share else None
    )

    if risk_per_share is None or risk_per_share <= 0:
        record["counterfactuals"] = {"data": "unavailable"}
        return record

    flatten_time = None
    if exit_type in ("flatten", "kill_switch"):
        flatten_time = ct.exit_fill_time
    else:
        flatten_time = session_flatten_time(date_str, day_scans, bars5.index)

    counterfactuals: Dict[str, Any] = {}
    all_ok = True
    for r_multiple in TARGET_R_MULTIPLES:
        key = f"target_{str(r_multiple).replace('.', '_')}r"
        cf = r_target_counterfactual(
            bars5, side=ct.side, entry_fill_time=ct.entry_fill_time,
            entry_fill_price=ct.entry_fill_price, entry_ref_price=entry_ref_price,
            stop_price=stop_price, risk_per_share=risk_per_share, r_multiple=r_multiple,
            flatten_time=flatten_time,
        )
        counterfactuals[key] = cf
        all_ok = all_ok and cf.get("data") == "ok"

    for multiple in STOP_WIDTH_MULTIPLES:
        key = f"stop_{str(multiple).replace('.', '_')}x"
        cf = stop_width_counterfactual(
            bars5, side=ct.side, entry_fill_time=ct.entry_fill_time,
            entry_fill_price=ct.entry_fill_price, entry_ref_price=entry_ref_price,
            stop_price=stop_price, target_price=target_price, risk_per_share=risk_per_share,
            multiple=multiple, flatten_time=flatten_time,
        )
        counterfactuals[key] = cf
        all_ok = all_ok and cf.get("data") == "ok"

    counterfactuals["no_flatten"] = no_flatten_counterfactual_for_trade(
        side=ct.side, entry_fill_time=ct.entry_fill_time, entry_fill_price=ct.entry_fill_price,
        exit_fill_time=ct.exit_fill_time, exit_fill_price=ct.exit_fill_price,
        stop_price=stop_price, target_price=target_price, risk_per_share=risk_per_share,
        exit_type=exit_type, bars5=bars5,
    )

    mae = mae_beyond_stop_r(
        bars5, side=ct.side, after_time=ct.entry_fill_time, stop_price=stop_price,
        risk_per_share=risk_per_share,
    )
    counterfactuals["mae_beyond_stop_r"] = mae
    all_ok = all_ok and mae is not None
    counterfactuals["data"] = "ok" if all_ok else "unavailable"
    record["counterfactuals"] = counterfactuals
    return record


TRAILING_WINDOW = 20
COST_MODEL_BPS = float(SLIPPAGE_BPS)  # frozen 5bps assumption (spec sec 3)

# Boundary semantics pinned by test (module docstring): trigger 1 fires AT the threshold
# ("at least"); trigger 3 fires strictly beyond its thresholds ("more than"/"less than").
TRIGGER_1_THRESHOLD = 0.60
TRIGGER_3_HIGH_MULTIPLE = 2.0
TRIGGER_3_LOW_MULTIPLE = 0.5


def build_trailing_window(
    ledger_rows: List[Dict[str, Any]], today_records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Stateless fold (spec sec 2 key decision 2): prior ledger rows' own
    ``reflection.trades`` records plus today's freshly computed ones, ordered by exit fill
    time, window = ``min(n, 20)``. A pre-ship ledger row with no ``reflection`` key
    contributes nothing (no backfill) rather than raising.
    """
    all_records: List[Dict[str, Any]] = []
    for row in ledger_rows:
        reflection = row.get("reflection") or {}
        all_records.extend(reflection.get("trades") or [])
    all_records.extend(today_records)
    all_records.sort(key=lambda t: t["exit_fill_time"])
    return all_records[-TRAILING_WINDOW:]


def compute_cost_check(window: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Median absolute per-fill slippage bps (entry + exit, 2 fills/trade) over the
    trailing window vs the frozen 5bps model."""
    fills = []
    for t in window:
        if t.get("entry_slippage_bps") is not None:
            fills.append(abs(t["entry_slippage_bps"]))
        if t.get("exit_slippage_bps") is not None:
            fills.append(abs(t["exit_slippage_bps"]))
    if not fills:
        return {"n": 0, "median_abs_slippage_bps": None, "model_bps": COST_MODEL_BPS, "ratio": None}
    median = float(np.median(fills))
    return {
        "n": len(fills),
        "median_abs_slippage_bps": median,
        "model_bps": COST_MODEL_BPS,
        "ratio": median / COST_MODEL_BPS,
    }


def _stop_survival(window: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    """Denominator is REAL stop-outs only (trigger 1's own wording) -- the stop-width
    counterfactual is computed uniformly for every trade (pinned interpretation 4), but a
    trade that actually exited at target trivially "survives" a wider stop and would
    otherwise inflate the denominator with a vacuous result."""
    survived = 0
    total = 0
    for t in window:
        if t.get("exit_type") != "stop":
            continue
        cf = (t.get("counterfactuals") or {}).get(key)
        if cf is None or cf.get("data") != "ok":
            continue
        total += 1
        if cf.get("survived"):
            survived += 1
    pct = (survived / total) if total > 0 else None
    return {"survived": survived, "total": total, "pct": pct}


def _cumulative_r(window: List[Dict[str, Any]], key: Optional[str]) -> float:
    total = 0.0
    for t in window:
        if key is None:
            v = t.get("realized_r")
        else:
            cf = (t.get("counterfactuals") or {}).get(key)
            v = cf.get("r") if cf and cf.get("data") == "ok" else None
        if v is not None:
            total += v
    return total


def compute_trailing20(window: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The same metrics the day's own numbers sit beside (spec sec 3 "trailing summary")."""
    return {
        "n": len(window),
        "cumulative_r": {
            "live": _cumulative_r(window, None),
            "target_1_0r": _cumulative_r(window, "target_1_0r"),
            "target_1_5r": _cumulative_r(window, "target_1_5r"),
        },
        "stop_survival": {
            "stop_1_25x": _stop_survival(window, "stop_1_25x"),
            "stop_1_5x": _stop_survival(window, "stop_1_5x"),
        },
        "cost_ratio": compute_cost_check(window)["ratio"],
    }


def compute_triggers(window: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The three deterministic hypothesis triggers (spec sec 3), evaluated over whatever
    window it is given (no minimum-n gate -- the engine files nothing, spec sec 2/7)."""
    trailing20 = compute_trailing20(window)

    survival = trailing20["stop_survival"]["stop_1_25x"]
    trigger1_value = survival["pct"]
    trigger1_fired = trigger1_value is not None and trigger1_value >= TRIGGER_1_THRESHOLD
    trigger1 = {
        "id": 1,
        "name": "stop-width survival",
        "value": trigger1_value,
        "threshold": TRIGGER_1_THRESHOLD,
        "fired": trigger1_fired,
        "n": survival["total"],
    }
    if trigger1_fired:
        trigger1["hypothesis"] = (
            f"widen the hourly bracket's stop to 1.25x its current width "
            f"({survival['survived']}/{survival['total']} trailing stop-outs would have survived)"
        )

    live_r = trailing20["cumulative_r"]["live"]
    r_1_0 = trailing20["cumulative_r"]["target_1_0r"]
    r_1_5 = trailing20["cumulative_r"]["target_1_5r"]
    best_r_multiple, best_r = max([(1.0, r_1_0), (1.5, r_1_5)], key=lambda p: p[1])
    trigger2_fired = best_r > live_r
    trigger2 = {
        "id": 2,
        "name": "closer R-target",
        "value": best_r,
        "threshold": live_r,
        "fired": trigger2_fired,
        "n": trailing20["n"],
    }
    if trigger2_fired:
        trigger2["hypothesis"] = (
            f"tighten the hourly bracket's target to {best_r_multiple:g}R "
            f"(cumulative {best_r:.2f}R vs live {live_r:.2f}R over the trailing window)"
        )

    cost_ratio = trailing20["cost_ratio"]
    trigger3_fired = cost_ratio is not None and (
        cost_ratio > TRIGGER_3_HIGH_MULTIPLE or cost_ratio < TRIGGER_3_LOW_MULTIPLE
    )
    trigger3 = {
        "id": 3,
        "name": "cost divergence",
        "value": cost_ratio,
        "threshold": [TRIGGER_3_LOW_MULTIPLE, TRIGGER_3_HIGH_MULTIPLE],
        "fired": trigger3_fired,
        "n": compute_cost_check(window)["n"],
    }
    if trigger3_fired:
        direction = "above" if cost_ratio > TRIGGER_3_HIGH_MULTIPLE else "below"
        trigger3["hypothesis"] = (
            f"re-examine the frozen {COST_MODEL_BPS:g}bps cost model "
            f"(realized median slippage is {direction} it by {cost_ratio:.2f}x)"
        )

    return [trigger1, trigger2, trigger3]


def pair_hourly_trades(trades: List[Dict[str, Any]], scans: List[Dict[str, Any]]) -> PairingResult:
    """Python port of scripts/render_weekly_journal.ts's pairHourlyTrades (lines 364-431).

    Same rules, byte-for-byte: entries/exits paired FIFO per symbol keyed off `reason` (not
    `side` -- BUY/SELL alone can't distinguish a long entry from a short exit); `panic_cli`
    fills are never paired (reported as manual interventions regardless of any queued entry);
    the scan join is by `entry_order_id == entry's broker_order_id` (trades has no bar_ts
    column, so provenance is keyed on the entry's own broker order id, spec sec 9/14).
    """
    scan_by_entry_order_id: Dict[str, Dict[str, Any]] = {}
    for s in scans:
        eoid = s.get("entry_order_id")
        if eoid:
            scan_by_entry_order_id[eoid] = s

    open_queue_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    closed_trades: List[ClosedTrade] = []
    orphan_exits: List[Dict[str, Any]] = []
    manual_interventions: List[Dict[str, Any]] = []

    ordered = sorted(trades, key=lambda t: t["fill_time"])
    for t in ordered:
        if t["reason"] == PANIC_REASON:
            manual_interventions.append(t)
            continue
        if t["reason"] in ENTRY_REASONS:
            open_queue_by_symbol.setdefault(t["symbol"], []).append(t)
            continue
        if t["reason"] in EXIT_REASONS:
            queue = open_queue_by_symbol.setdefault(t["symbol"], [])
            if not queue:
                orphan_exits.append(t)
                continue
            entry_trade = queue.pop(0)
            scan_row_ = scan_by_entry_order_id.get(entry_trade["broker_order_id"])
            risk_per_share = scan_row_.get("risk_per_share") if scan_row_ else None
            r_multiple: Optional[float] = None
            r_multiple_na_reason: Optional[str] = None
            if scan_row_ is None:
                r_multiple_na_reason = (
                    f"missing scan row for entry {entry_trade['broker_order_id']}"
                )
            elif risk_per_share is None or risk_per_share <= 0:
                r_multiple_na_reason = "risk_per_share unavailable"
            else:
                sign = 1 if _side_for_entry_reason(entry_trade["reason"]) == "LONG" else -1
                r_multiple = sign * (t["fill_price"] - entry_trade["fill_price"]) / risk_per_share
            closed_trades.append(
                ClosedTrade(
                    symbol=t["symbol"],
                    side=_side_for_entry_reason(entry_trade["reason"]),
                    entry_fill_price=entry_trade["fill_price"],
                    entry_fill_time=entry_trade["fill_time"],
                    entry_order_id=entry_trade["broker_order_id"],
                    exit_fill_price=t["fill_price"],
                    exit_fill_time=t["fill_time"],
                    exit_order_id=t["broker_order_id"],
                    exit_reason=t["reason"],
                    qty=entry_trade["qty"],
                    scan=scan_row_,
                    r_multiple=r_multiple,
                    r_multiple_na_reason=r_multiple_na_reason,
                )
            )

    open_entries: List[Dict[str, Any]] = []
    for queue in open_queue_by_symbol.values():
        open_entries.extend(queue)

    return PairingResult(
        closed_trades=closed_trades,
        open_entries=open_entries,
        orphan_exits=orphan_exits,
        manual_interventions=manual_interventions,
    )


STANDING_RESTRAINTS = (
    "Counterfactuals are diagnostic, not trials: nothing is selected on them until a "
    "hypothesis is pre-registered and studied (spec sec 3, #398). Sample sizes are printed "
    "next to every number."
)

NO_TRADES_LINE = "No closed trades; no reflection."


def _fmt(value: Optional[float], decimals: int = 2, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.{decimals}f}{suffix}"


def _fmt_cf_line(label: str, cf: Dict[str, Any]) -> str:
    if cf.get("applicable") is False:
        return f"- Counterfactual {label}: not applicable"
    if cf.get("data") != "ok":
        return f"- Counterfactual {label}: data unavailable"
    exit_reason = cf.get("exit_reason", "n/a")
    r = _fmt(cf.get("r"))
    if "survived" in cf:
        survived = "survived" if cf["survived"] else "stopped out"
        return f"- Counterfactual {label}: {survived}, exit {exit_reason}, r={r}"
    return f"- Counterfactual {label}: exit {exit_reason}, r={r}"


def _render_trade_block(rec: Dict[str, Any]) -> str:
    lines = [f"### {rec['entry_order_id']} -- {rec['symbol']} {rec['side']}", ""]
    detectors = ", ".join(rec.get("detectors_fired") or []) or "none"
    lines.append(f"- Detectors: {detectors}")
    lines.append(
        f"- Entry: {rec['entry_fill_price']:.4f} @ {rec['entry_fill_time']} "
        f"(slippage {_fmt(rec['entry_slippage_bps'], 2, 'bps')})"
    )
    lines.append(
        f"- Exit: {rec['exit_fill_price']:.4f} @ {rec['exit_fill_time']} "
        f"({rec['exit_order_reason']} -> {rec['exit_type']}, "
        f"slippage {_fmt(rec['exit_slippage_bps'], 2, 'bps')})"
    )
    lines.append(
        f"- Nominal R: {_fmt(rec['nominal_r'])} -- Realized R: {_fmt(rec['realized_r'])} "
        f"(deviation: {rec['deviation_reason'] or 'n/a'})"
    )
    cf = rec["counterfactuals"]
    if cf.get("data") == "unavailable" and len(cf) == 1:
        lines.append("- Counterfactuals: data unavailable")
    else:
        lines.append(_fmt_cf_line("target 1.0R", cf["target_1_0r"]))
        lines.append(_fmt_cf_line("target 1.5R", cf["target_1_5r"]))
        lines.append(_fmt_cf_line("stop 1.25x", cf["stop_1_25x"]))
        lines.append(_fmt_cf_line("stop 1.5x", cf["stop_1_5x"]))
        lines.append(_fmt_cf_line("no-flatten", cf["no_flatten"]))
        lines.append(f"- MAE beyond stop: {_fmt(cf.get('mae_beyond_stop_r'))}R")
    return "\n".join(lines)


def _render_cost_check(cost_check: Dict[str, Any]) -> str:
    return (
        f"### Cost check\n\n"
        f"n={cost_check['n']} fill(s), median |slippage| "
        f"{_fmt(cost_check['median_abs_slippage_bps'], 2, 'bps')} vs "
        f"{cost_check['model_bps']:.2f}bps model (ratio {_fmt(cost_check['ratio'], 2, 'x')})"
    )


def _render_trailing20(trailing20: Dict[str, Any]) -> str:
    n = trailing20["n"]
    cr = trailing20["cumulative_r"]
    ss = trailing20["stop_survival"]

    def _survival(s: Dict[str, Any]) -> str:
        if s["total"] == 0:
            return "n/a (0/0)"
        return f"{s['pct'] * 100:.0f}% ({s['survived']}/{s['total']})"

    lines = [
        f"### Trailing-20 (n={n})",
        "",
        "| metric | live (2R) | target 1.0R | target 1.5R |",
        "| --- | --- | --- | --- |",
        f"| cumulative R | {_fmt(cr['live'])} | {_fmt(cr['target_1_0r'])} | {_fmt(cr['target_1_5r'])} |",
        "",
        "| metric | stop 1.25x | stop 1.5x |",
        "| --- | --- | --- |",
        f"| stop-out survival | {_survival(ss['stop_1_25x'])} | {_survival(ss['stop_1_5x'])} |",
        "",
        f"cost ratio: {_fmt(trailing20['cost_ratio'], 2, 'x')}",
    ]
    return "\n".join(lines)


def _render_triggers(triggers: List[Dict[str, Any]]) -> str:
    lines = ["### Triggers", ""]
    for t in triggers:
        verdict = "FIRED" if t["fired"] else "not fired"
        if t["id"] == 1:
            value = "n/a" if t["value"] is None else f"{t['value'] * 100:.0f}%"
            detail = f"{value} (threshold {t['threshold'] * 100:.0f}%, n={t['n']})"
        elif t["id"] == 2:
            detail = f"best {_fmt(t['value'])}R vs live {_fmt(t['threshold'])}R (n={t['n']})"
        else:
            detail = f"{_fmt(t['value'], 2, 'x')} (n={t['n']})"
        lines.append(f"{t['id']}. {t['name']}: {detail} -- {verdict}")
        if t.get("hypothesis"):
            lines.append(f"   - suggested hypothesis: {t['hypothesis']}")
    return "\n".join(lines)


def render_markdown(
    date: str,
    trade_records: List[Dict[str, Any]],
    cost_check: Dict[str, Any],
    trailing20: Dict[str, Any],
    triggers: List[Dict[str, Any]],
) -> str:
    """Renders the ``## Reflection`` section (spec sec 4's frozen field/section order):
    standing restraints, one block per closed trade, the cost-check block, the trailing-20
    table, then ``### Triggers``. ``No closed trades; no reflection.`` for an empty day."""
    if not trade_records:
        return f"## Reflection\n\n{NO_TRADES_LINE}"

    sections = ["## Reflection", "", STANDING_RESTRAINTS, ""]
    for rec in trade_records:
        sections.append(_render_trade_block(rec))
        sections.append("")
    sections.append(_render_cost_check(cost_check))
    sections.append("")
    sections.append(_render_trailing20(trailing20))
    sections.append("")
    sections.append(_render_triggers(triggers))
    return "\n".join(sections)


def build_reflection_object(
    date: str,
    trade_records: List[Dict[str, Any]],
    cost_check: Dict[str, Any],
    trailing20: Dict[str, Any],
    triggers: List[Dict[str, Any]],
    *,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """The structured ``reflection`` object appended to the JSONL ledger row (spec sec 4).
    Field names here are the frozen contract the wiring batch codes against."""
    return {
        "engine_version": ENGINE_VERSION,
        "no_closed_trades": len(trade_records) == 0,
        "error": error,
        "trades": trade_records,
        "cost_check": cost_check,
        "trailing20": trailing20,
        "triggers": triggers,
    }


def load_ledger_jsonl(text: str) -> list[dict]:
    """Parses the daily-verification JSONL ledger text into a list of row dicts.

    Raises ``ValueError`` on any unparsable line -- malformed input, per the CLI contract
    (exit 1, nothing printed), not a per-trade degrade.
    """
    rows: list[dict] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def compute_reflection(
    date: str,
    digest: dict,
    bars_path: str,
    ledger_rows: list[dict],
) -> dict:
    """Top-level orchestration (spec sec 4): parses the digest's ``verification`` block,
    loads the day's bars, pairs and scores every closed trade, folds the trailing-20 window,
    and renders both output artifacts.

    Never raises: any failure (a missing/malformed bars file, an unresolvable trade) is
    caught and degrades into ``{"error": "<reason>"}`` on the reflection object and
    ``"Reflection: error -- <reason>"`` as the markdown, per spec sec 4 -- a reflection
    failure must never fail the caller's (daily-verification's) own seven-check verdict.
    """
    try:
        verification = digest.get("verification") or {}
        scans = verification.get("scans") or []
        trades = verification.get("trades") or []
        bars5 = load_local(bars_path)

        pairing = pair_hourly_trades(trades, scans)
        trade_records = [
            compute_trade_record(ct, bars5, date, scans) for ct in pairing.closed_trades
        ]
        window = build_trailing_window(ledger_rows, trade_records)
        cost_check = compute_cost_check(window)
        trailing20 = compute_trailing20(window)
        triggers = compute_triggers(window)

        markdown = render_markdown(date, trade_records, cost_check, trailing20, triggers)
        reflection = build_reflection_object(date, trade_records, cost_check, trailing20, triggers)
        return {"date": date, "markdown": markdown, "reflection": reflection}
    except Exception as exc:  # noqa: BLE001 -- top-level degrade boundary, never re-raises.
        reason = str(exc)
        reflection = build_reflection_object(
            date, [], {"n": 0, "median_abs_slippage_bps": None, "model_bps": COST_MODEL_BPS, "ratio": None},
            {"n": 0, "cumulative_r": {"live": 0.0, "target_1_0r": 0.0, "target_1_5r": 0.0},
             "stop_survival": {"stop_1_25x": {"survived": 0, "total": 0, "pct": None},
                               "stop_1_5x": {"survived": 0, "total": 0, "pct": None}},
             "cost_ratio": None},
            [], error=reason,
        )
        return {"date": date, "markdown": f"Reflection: error -- {reason}", "reflection": reflection}
