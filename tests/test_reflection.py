"""Tests for backtest/reflection.py (#578, nightly reflection engine).

Fixture builders below reuse ``tests/test_hourly_geometry.py``'s ``bars5()`` pattern and its
fill-timing note (a decision/scan's own timestamp is the CANDIDATE BAR'S START; the live fill
lands on the first 5Min bar open at/after ``bar_end + SCAN_OFFSET_MIN``). Digest-shaped scan/
trade dict builders below use the real snake_case field names from
``supabase/functions/_shared/db.ts`` (``HourlyScanRow`` line 483, ``TradeRow`` line 141).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import backtest.reflection as rfl


def bars5(rows):
    """rows: list of (timestamp_str, o, h, l, c) -> a 5Min OHLC DataFrame."""
    idx = pd.to_datetime([r[0] for r in rows], utc=True)
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
        },
        index=idx,
    )


def scan_row(
    *,
    symbol="UPRO",
    bar_ts,
    decision="SKIP",
    skip_reason=None,
    detectors_fired=None,
    context_mode="normal",
    entry_ref_price=None,
    stop_price=None,
    target_price=None,
    risk_per_share=None,
    equity_usd=1_000_000.0,
    qty=0,
    entry_order_id=None,
):
    return {
        "symbol": symbol,
        "bar_ts": bar_ts,
        "decision": decision,
        "skip_reason": skip_reason,
        "detectors_fired": detectors_fired or [],
        "context_mode": context_mode,
        "entry_ref_price": entry_ref_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "risk_per_share": risk_per_share,
        "equity_usd": equity_usd,
        "qty": qty,
        "entry_order_id": entry_order_id,
    }


def trade_row(*, symbol="UPRO", side, qty, fill_price, fill_time, reason, broker_order_id):
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "fill_price": fill_price,
        "fill_time": fill_time,
        "reason": reason,
        "broker_order_id": broker_order_id,
    }


# ---------------------------------------------------------------------------
# Pairing (step 3) -- byte-for-byte port of render_weekly_journal.ts's
# pairHourlyTrades: FIFO per symbol by fill_time, panic_cli excluded, scan
# joined by entry_order_id == entry's broker_order_id.
# ---------------------------------------------------------------------------

def test_pairs_one_long_entry_to_its_bracket_exit():
    scans = [
        scan_row(
            bar_ts="2026-08-06T14:30:00Z", decision="LONG",
            entry_ref_price=80.00, stop_price=79.00, target_price=82.00,
            risk_per_share=1.00, qty=100, entry_order_id="entry-1",
        ),
    ]
    trades = [
        trade_row(
            side="BUY", qty=100, fill_price=80.04, fill_time="2026-08-06T15:40:00Z",
            reason="hourly_long_entry", broker_order_id="entry-1",
        ),
        trade_row(
            side="SELL", qty=100, fill_price=81.959, fill_time="2026-08-06T16:35:00Z",
            reason="hourly_bracket_exit", broker_order_id="exit-1",
        ),
    ]
    result = rfl.pair_hourly_trades(trades, scans)
    assert len(result.closed_trades) == 1
    ct = result.closed_trades[0]
    assert ct.side == "LONG"
    assert ct.entry_order_id == "entry-1"
    assert ct.entry_fill_price == 80.04
    assert ct.exit_fill_price == 81.959
    assert ct.exit_reason == "hourly_bracket_exit"
    assert ct.scan is not None and ct.scan["stop_price"] == 79.00
    assert result.open_entries == []
    assert result.orphan_exits == []
    assert result.manual_interventions == []


def test_short_entry_paired_via_reason_not_side():
    scans = [
        scan_row(
            bar_ts="2026-08-06T14:30:00Z", decision="SHORT",
            entry_ref_price=80.00, stop_price=81.00, target_price=78.00,
            risk_per_share=1.00, qty=100, entry_order_id="entry-2",
        ),
    ]
    trades = [
        trade_row(
            side="SELL", qty=100, fill_price=79.96, fill_time="2026-08-06T15:40:00Z",
            reason="hourly_short_entry", broker_order_id="entry-2",
        ),
        trade_row(
            side="BUY", qty=100, fill_price=78.039, fill_time="2026-08-06T16:35:00Z",
            reason="hourly_bracket_exit", broker_order_id="exit-2",
        ),
    ]
    result = rfl.pair_hourly_trades(trades, scans)
    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].side == "SHORT"


def test_panic_cli_is_a_manual_intervention_never_paired():
    trades = [
        trade_row(
            side="BUY", qty=100, fill_price=80.0, fill_time="2026-08-06T15:40:00Z",
            reason="hourly_long_entry", broker_order_id="entry-3",
        ),
        trade_row(
            side="SELL", qty=100, fill_price=79.0, fill_time="2026-08-06T16:00:00Z",
            reason="panic_cli", broker_order_id="panic-1",
        ),
    ]
    result = rfl.pair_hourly_trades(trades, [])
    assert len(result.manual_interventions) == 1
    assert result.manual_interventions[0]["broker_order_id"] == "panic-1"
    # panic_cli never consumes the open entry queue -- it stays open.
    assert len(result.open_entries) == 1
    assert result.closed_trades == []


def test_exit_with_no_open_entry_is_an_orphan():
    trades = [
        trade_row(
            side="SELL", qty=100, fill_price=79.0, fill_time="2026-08-06T16:00:00Z",
            reason="hourly_bracket_exit", broker_order_id="exit-orphan",
        ),
    ]
    result = rfl.pair_hourly_trades(trades, [])
    assert len(result.orphan_exits) == 1
    assert result.closed_trades == []


def test_missing_scan_row_degrades_r_multiple_with_reason():
    trades = [
        trade_row(
            side="BUY", qty=100, fill_price=80.0, fill_time="2026-08-06T15:40:00Z",
            reason="hourly_long_entry", broker_order_id="entry-4",
        ),
        trade_row(
            side="SELL", qty=100, fill_price=81.0, fill_time="2026-08-06T16:00:00Z",
            reason="hourly_bracket_exit", broker_order_id="exit-4",
        ),
    ]
    result = rfl.pair_hourly_trades(trades, [])
    assert len(result.closed_trades) == 1
    ct = result.closed_trades[0]
    assert ct.scan is None
    assert "missing scan row" in ct.r_multiple_na_reason
