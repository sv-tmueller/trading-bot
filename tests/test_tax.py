"""Tests for backtest/tax.py — the after-tax equity-curve layer.

Hand-built trade ledgers with known holding periods and gains pin the
short-/long-term classification and the per-jurisdiction rates.

Pinned rates (from docs/research/2026-06-23-short-horizon-feasibility-gate.md,
not re-derived here):
  US: short-term 0.35 (held <= 365 days), long-term 0.188 (held > 365 days).
  DE: flat 0.26375, no short/long distinction.

All offline / synthetic — no network.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.tax import (
    US_LONG_TERM_RATE,
    US_SHORT_TERM_RATE,
    DE_FLAT_RATE,
    apply_tax_to_ledger,
    classify_holding,
)


def _ledger(rows: list[dict]) -> list[dict]:
    """Each row: entry_date, exit_date (str), pnl (float)."""
    return [
        {
            "entry_date": pd.Timestamp(r["entry_date"]),
            "exit_date": pd.Timestamp(r["exit_date"]),
            "pnl": float(r["pnl"]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Holding-period classification (365-day boundary)
# ---------------------------------------------------------------------------

def test_classify_holding_short_vs_long_at_365_boundary():
    short = classify_holding(pd.Timestamp("2023-01-01"), pd.Timestamp("2023-06-01"))
    assert short == "short"
    # Exactly 365 days held → still short (boundary: > 365 is long)
    exactly_365 = classify_holding(pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-01"))
    assert exactly_365 == "short"
    # 366 days → long
    over = classify_holding(pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-02"))
    assert over == "long"


# ---------------------------------------------------------------------------
# US: short-term 35%, long-term 18.8%
# ---------------------------------------------------------------------------

def test_us_short_term_gain_taxed_at_35pct():
    ledger = _ledger([
        {"entry_date": "2023-01-02", "exit_date": "2023-04-02", "pnl": 1000.0},  # ~90d -> ST
    ])
    pre_tax = pd.Series(
        {pd.Timestamp("2023-01-02"): 100_000.0, pd.Timestamp("2023-04-02"): 101_000.0}
    )
    after = apply_tax_to_ledger(ledger, pre_tax, jurisdiction="US")
    # tax = 1000 * 0.35 = 350; after-tax end = 101000 - 350 = 100650
    assert after.iloc[-1] == pytest.approx(101_000.0 - 350.0, abs=1e-6)


def test_us_long_term_gain_taxed_at_18_8pct():
    ledger = _ledger([
        {"entry_date": "2022-01-03", "exit_date": "2023-06-01", "pnl": 1000.0},  # >365d -> LT
    ])
    pre_tax = pd.Series(
        {pd.Timestamp("2022-01-03"): 100_000.0, pd.Timestamp("2023-06-01"): 101_000.0}
    )
    after = apply_tax_to_ledger(ledger, pre_tax, jurisdiction="US")
    # tax = 1000 * 0.188 = 188; after-tax end = 101000 - 188 = 100812
    assert after.iloc[-1] == pytest.approx(101_000.0 - 188.0, abs=1e-6)


def test_us_mixed_ledger_short_and_long():
    ledger = _ledger([
        {"entry_date": "2023-01-02", "exit_date": "2023-04-02", "pnl": 1000.0},  # ST 35%
        {"entry_date": "2021-01-04", "exit_date": "2023-09-01", "pnl": 2000.0},  # LT 18.8%
    ])
    idx = [pd.Timestamp(d) for d in
           ["2023-01-02", "2023-04-02", "2023-09-01"]]
    pre_tax = pd.Series([100_000.0, 101_000.0, 103_000.0], index=idx)
    after = apply_tax_to_ledger(ledger, pre_tax, jurisdiction="US")
    # cumulative tax by the last date = 1000*0.35 + 2000*0.188 = 350 + 376 = 726
    assert after.iloc[-1] == pytest.approx(103_000.0 - 726.0, abs=1e-6)
    # On the day only the ST trade has closed, only its tax is deducted
    assert after.loc[pd.Timestamp("2023-04-02")] == pytest.approx(101_000.0 - 350.0, abs=1e-6)


# ---------------------------------------------------------------------------
# DE: flat 26.375%, no short/long distinction
# ---------------------------------------------------------------------------

def test_de_flat_rate_regardless_of_holding_period():
    ledger = _ledger([
        {"entry_date": "2023-01-02", "exit_date": "2023-04-02", "pnl": 1000.0},  # would be ST in US
        {"entry_date": "2021-01-04", "exit_date": "2023-09-01", "pnl": 1000.0},  # would be LT in US
    ])
    idx = [pd.Timestamp(d) for d in ["2023-01-02", "2023-04-02", "2023-09-01"]]
    pre_tax = pd.Series([100_000.0, 101_000.0, 102_000.0], index=idx)
    after = apply_tax_to_ledger(ledger, pre_tax, jurisdiction="DE")
    # both gains taxed at the same flat 0.26375
    expected_tax = (1000.0 + 1000.0) * DE_FLAT_RATE
    assert after.iloc[-1] == pytest.approx(102_000.0 - expected_tax, abs=1e-6)


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_after_tax_strictly_below_pretax_when_gain_realized():
    ledger = _ledger([
        {"entry_date": "2023-01-02", "exit_date": "2023-04-02", "pnl": 1000.0},
    ])
    idx = [pd.Timestamp(d) for d in ["2023-01-02", "2023-04-02", "2023-05-01"]]
    pre_tax = pd.Series([100_000.0, 101_000.0, 101_500.0], index=idx)
    after = apply_tax_to_ledger(ledger, pre_tax, jurisdiction="US")
    # Before the gain is realized, curves coincide; from the exit date on, after < pre
    assert after.loc[pd.Timestamp("2023-01-02")] == pytest.approx(100_000.0)
    assert after.loc[pd.Timestamp("2023-04-02")] < pre_tax.loc[pd.Timestamp("2023-04-02")]
    assert after.loc[pd.Timestamp("2023-05-01")] < pre_tax.loc[pd.Timestamp("2023-05-01")]


def test_losing_trade_gets_no_tax_credit():
    """A realized loss does not refund tax (per-trade tax clamped at >= 0)."""
    ledger = _ledger([
        {"entry_date": "2023-01-02", "exit_date": "2023-04-02", "pnl": -1000.0},
    ])
    idx = [pd.Timestamp(d) for d in ["2023-01-02", "2023-04-02"]]
    pre_tax = pd.Series([100_000.0, 99_000.0], index=idx)
    after = apply_tax_to_ledger(ledger, pre_tax, jurisdiction="US")
    # No tax, no credit: after-tax == pre-tax
    assert after.iloc[-1] == pytest.approx(99_000.0, abs=1e-9)


def test_no_trades_returns_pretax_curve_unchanged():
    idx = [pd.Timestamp(d) for d in ["2023-01-02", "2023-04-02"]]
    pre_tax = pd.Series([100_000.0, 100_000.0], index=idx)
    after = apply_tax_to_ledger([], pre_tax, jurisdiction="US")
    pd.testing.assert_series_equal(after, pre_tax, check_names=False)


def test_rates_match_pinned_values():
    assert US_SHORT_TERM_RATE == pytest.approx(0.35)
    assert US_LONG_TERM_RATE == pytest.approx(0.188)
    assert DE_FLAT_RATE == pytest.approx(0.26375)
