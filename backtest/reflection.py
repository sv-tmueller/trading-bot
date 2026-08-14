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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
