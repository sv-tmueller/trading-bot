"""After-tax equity-curve layer for the #314 candidate strategy survey.

Walks a trade ledger, classifies each realized gain short- vs long-term by
holding period, applies a jurisdiction rate, and deducts the tax from the
pre-tax equity curve at each trade's exit date (cumulative, forward-filled to
daily). The result is an after-tax equity curve aligned to the pre-tax index.

Research-only. Lives in backtest/ and is never imported by supabase/functions/.
No LLM, no broker calls.

Model (decisions, documented):
- Deduct-at-exit: after_tax(t) = pre_tax(t) - cumulative_tax(t), where the
  cumulative tax steps up by each closed trade's tax on its exit_date and is
  held flat (ffill) until the next close. So before a gain is realized the two
  curves coincide; once a winning trade closes, after-tax sits strictly below.
- Holding period: exit minus entry in calendar days. > 365 days -> long-term;
  <= 365 -> short-term (the US ST/LT boundary). DE is flat regardless.
- Losses: no tax credit. Per-trade tax is clamped at >= 0 (a realized loss
  neither adds nor refunds tax). This is the conservative, no-carryforward
  model; it keeps the after-tax curve a clean handicap on gains only.

Rates are pinned to docs/research/2026-06-23-short-horizon-feasibility-gate.md
(the #308 logged tax decision). They are NOT re-derived here.
"""
from __future__ import annotations

import pandas as pd

# Pinned tax rates (see module docstring).
US_SHORT_TERM_RATE = 0.35     # ordinary income, held <= 365 days
US_LONG_TERM_RATE = 0.188     # 15-20% + 3.8% NIIT, held > 365 days
DE_FLAT_RATE = 0.26375        # 25% Abgeltungsteuer + 5.5% Soli, no ST/LT split

_LONG_TERM_DAYS = 365  # > this many calendar days held => long-term (US)


def classify_holding(entry_date: pd.Timestamp, exit_date: pd.Timestamp) -> str:
    """Return 'short' or 'long' by the 365-day holding boundary.

    Held for more than 365 calendar days -> 'long'; otherwise 'short'.
    Exactly 365 days is 'short' (the boundary is strict: > 365 is long).
    """
    held_days = (exit_date - entry_date).days
    return "long" if held_days > _LONG_TERM_DAYS else "short"


def _trade_tax(pnl: float, holding: str, jurisdiction: str) -> float:
    """Tax owed on one realized trade. Losses owe nothing (clamped >= 0)."""
    if pnl <= 0:
        return 0.0
    j = jurisdiction.upper()
    if j == "US":
        rate = US_LONG_TERM_RATE if holding == "long" else US_SHORT_TERM_RATE
    elif j == "DE":
        rate = DE_FLAT_RATE  # flat — holding period ignored
    else:
        raise ValueError(f"unknown jurisdiction {jurisdiction!r}; expected 'US' or 'DE'")
    return pnl * rate


def apply_tax_to_ledger(
    trades: list,
    pre_tax_equity: pd.Series,
    *,
    jurisdiction: str,
) -> pd.Series:
    """Deduct realized-gain tax from a pre-tax equity curve.

    Parameters
    ----------
    trades:
        List of trade dicts (as produced by simulate_from_signal), each with
        ``entry_date``, ``exit_date`` (Timestamps) and ``pnl`` (float).
    pre_tax_equity:
        Pre-tax equity curve indexed by trading date.
    jurisdiction:
        'US' (short 35% / long 18.8% at the 365-day boundary) or
        'DE' (flat 26.375%, no short/long distinction).

    Returns
    -------
    After-tax equity curve, same index as ``pre_tax_equity``. Identical to the
    input before any gain is realized; strictly below it from the first winning
    trade's exit date onward.
    """
    if len(trades) == 0:
        return pre_tax_equity.copy()

    # Tax owed on each exit date (summed across trades closing the same day)
    tax_by_date: dict = {}
    for t in trades:
        holding = classify_holding(t["entry_date"], t["exit_date"])
        tax = _trade_tax(t["pnl"], holding, jurisdiction)
        if tax > 0.0:
            tax_by_date[t["exit_date"]] = tax_by_date.get(t["exit_date"], 0.0) + tax

    if not tax_by_date:
        return pre_tax_equity.copy()

    # Cumulative tax stepped onto the equity index, ffilled, zero before first exit
    tax_series = pd.Series(tax_by_date, dtype=float).sort_index()
    cumulative = tax_series.cumsum()
    # Align onto the equity index: each date carries the cumulative tax of all
    # exits up to and including it (ffill), 0 before the first exit.
    cum_on_index = cumulative.reindex(
        pre_tax_equity.index.union(cumulative.index), method="ffill"
    ).reindex(pre_tax_equity.index).fillna(0.0)

    return pre_tax_equity - cum_on_index
