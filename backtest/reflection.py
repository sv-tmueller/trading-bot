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
    idx = df.index
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
    """Placeholder -- implemented incrementally per the sub-plan's ordered steps."""
    raise NotImplementedError
