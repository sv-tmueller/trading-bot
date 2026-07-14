"""Frozen venue cost presets — pinned VERBATIM to the #369 gate doc.

Research-only (#371, batch #370). Lives in ``backtest/`` and is never
imported by ``supabase/functions/``. No LLM, no broker calls, no orders.

Values (round-trip cost `c`, in **basis points of notional**) are copied
verbatim from ``docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md``
§4.1-4.3 — they are NOT re-derived here; see that doc for sourcing/citations
and the underlying spread/commission/slippage math.

Overnight financing (spot/CFD only, per-direction)
---------------------------------------------------
The gate doc's XTB EURUSD swap figures (long -$4.525/night, short
-$1.032/night per 100,000-EUR lot) are reused there "as a proxy for all
proportional venues (spot ECN and CFD alike)" (§1) — applied identically to
IC Markets and XTB here. Converted to bp/night on the gate's own $114,000
notional convention (100,000 EUR x 1.14 EURUSD ref price, §5): a 100k-EUR lot
is $114,000 notional, not a flat $100,000.

The futures presets (6E, M6E) carry ``has_overnight=False`` — a genuine
structural advantage of the futures wrapper (no daily rollover charge), not
modeled away (gate doc §5.1).

Note: this harness's per-direction financing (0.397 bp/night long, 0.0905
bp/night short) is deliberately MORE PRECISE than the gate doc's own
long/short-AVERAGED 0.153 bp/night proxy (used there for a single-cadence
sanity table, §5) — the research note (docs/research/) reconciles the two.

Trade Republic is explicitly EXCLUDED as a preset (gate doc §4.4/§8: the
unpublished certificate issuer spread, bracketed 10-30bp, already exceeds
every proportional venue's entire round-trip cost at every position size
swept — no finite crossover size; also fails the API/ToS check independently).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Gate doc §5's notional convention: 100,000 EUR lot x 1.14 EURUSD ref price.
_NOTIONAL_USD = 114_000.0

# XTB EURUSD overnight swap, USD per 100k-EUR lot per night (gate doc §1/§4.2,
# sourced from dailyforex.com's XTB review, fetched 2026-07-13). Negative =
# cost; we return the abs() magnitude in bp, consistent with cost_rt's own
# "positive number = cost" convention used throughout fx_execution.py.
_XTB_SWAP_USD_PER_NIGHT = {"long": -4.525, "short": -1.032}


@dataclass(frozen=True)
class VenuePreset:
    """One venue's round-trip cost, base and pessimistic, in bp of notional."""

    name: str
    base_bp: float
    pessimistic_bp: float
    has_overnight: bool  # False for futures (no daily rollover charge)


IC_MARKETS_ECN = VenuePreset(
    name="IC Markets ECN (spot)", base_bp=1.04, pessimistic_bp=2.35, has_overnight=True,
)
XTB_CFD = VenuePreset(
    name="XTB CFD", base_bp=0.79, pessimistic_bp=1.75, has_overnight=True,
)
CME_6E = VenuePreset(
    name="CME 6E (futures)", base_bp=0.56, pessimistic_bp=1.00, has_overnight=False,
)
CME_M6E = VenuePreset(
    name="CME M6E (futures)", base_bp=1.23, pessimistic_bp=2.10, has_overnight=False,
)

PRESETS = {
    "ic_markets": IC_MARKETS_ECN,
    "xtb": XTB_CFD,
    "6e": CME_6E,
    "m6e": CME_M6E,
}


def overnight_financing_bp_per_night(direction: str) -> float:
    """Per-direction overnight financing cost, in bp/night, on the gate
    doc's $114,000 notional convention. Returns a POSITIVE bp magnitude
    (cost), consistent with ``cost_rt``'s sign convention elsewhere in this
    harness — the underlying XTB swap ledger entries are negative (a cost),
    which is why we take the absolute value here.

    'long' -> ~0.397 bp/night, 'short' -> ~0.0905 bp/night.
    """
    if direction not in _XTB_SWAP_USD_PER_NIGHT:
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
    usd_per_night = _XTB_SWAP_USD_PER_NIGHT[direction]
    return abs(usd_per_night) / _NOTIONAL_USD * 10_000.0


def overnight_bp_for(preset: VenuePreset, direction: str) -> Optional[float]:
    """Overnight financing bp/night for a given preset+direction, or None
    for a futures preset (structural: no daily rollover charge)."""
    if not preset.has_overnight:
        return None
    return overnight_financing_bp_per_night(direction)
