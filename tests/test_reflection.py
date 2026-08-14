"""Tests for backtest/reflection.py (#578, nightly reflection engine).

Fixture builders below reuse ``tests/test_hourly_geometry.py``'s ``bars5()`` pattern and its
fill-timing note (a decision/scan's own timestamp is the CANDIDATE BAR'S START; the live fill
lands on the first 5Min bar open at/after ``bar_end + SCAN_OFFSET_MIN``). Digest-shaped scan/
trade dict builders below use the real snake_case field names from
``supabase/functions/_shared/db.ts`` (``HourlyScanRow`` line 483, ``TradeRow`` line 141).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


# ---------------------------------------------------------------------------
# Exit-type classification (step 3): hourly_bracket_exit doesn't say which
# leg filled; hourly_session_close_exit/hourly_kill_switch are unambiguous.
# ---------------------------------------------------------------------------

def test_classify_bracket_exit_clean_stop_long():
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_bracket_exit", fill_price=79.0, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "stop"
    assert deviation == "slippage"


def test_classify_bracket_exit_gap_through_stop_long():
    # fill strictly worse (lower) than the journaled stop -> gap-through-stop.
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_bracket_exit", fill_price=78.50, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "stop"
    assert deviation == "gap"


def test_classify_bracket_exit_clean_target_long():
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_bracket_exit", fill_price=81.959, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "target"
    assert deviation == "slippage"


def test_classify_bracket_exit_short_mirrors_long():
    exit_type, deviation = rfl.classify_exit(
        "SHORT", "hourly_bracket_exit", fill_price=81.0, stop_price=81.0, target_price=78.0,
    )
    assert exit_type == "stop"
    assert deviation == "slippage"

    exit_type, deviation = rfl.classify_exit(
        "SHORT", "hourly_bracket_exit", fill_price=81.50, stop_price=81.0, target_price=78.0,
    )
    assert exit_type == "stop"
    assert deviation == "gap"


def test_classify_session_close_exit_is_flatten():
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_session_close_exit", fill_price=80.5, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "flatten"
    assert deviation == "flatten"


def test_classify_kill_switch_exit_is_kill_switch():
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_kill_switch", fill_price=77.0, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "kill_switch"
    assert deviation == "flatten"


def test_classify_bracket_exit_between_levels_classifies_to_nearest():
    # fill=81.0 sits strictly between stop=79.0 and target=82.0, nearer to target (1.0 away)
    # than stop (2.0 away) -- neither beyond-stop nor tie, so it classifies to the nearest.
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_bracket_exit", fill_price=81.0, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "target"
    assert deviation == "slippage"


def test_classify_bracket_exit_exact_halfway_tie_resolves_to_stop():
    # fill=80.5 is exactly equidistant from stop=79.0 and target=82.0 (1.5 each) -- the
    # documented <= tie-break resolves ties to stop, not target.
    exit_type, deviation = rfl.classify_exit(
        "LONG", "hourly_bracket_exit", fill_price=80.5, stop_price=79.0, target_price=82.0,
    )
    assert exit_type == "stop"
    assert deviation == "slippage"


# ---------------------------------------------------------------------------
# Entry/exit slippage bps and nominal R (step 3): signed bps, adverse positive
# by side; nominal R is what the exit "should" have realized with no
# slippage/gap, given its classified exit_type.
# ---------------------------------------------------------------------------

def test_entry_slippage_bps_long_adverse_is_positive():
    # fill above ref for a long entry is adverse (paid more) -> positive bps.
    bps = rfl.entry_slippage_bps("LONG", fill_price=80.04, entry_ref_price=80.00)
    assert bps == pytest.approx(5.0)


def test_entry_slippage_bps_short_adverse_is_positive():
    # fill above ref for a short entry (sold at a worse -- lower -- price is adverse;
    # here fill is LOWER than ref, so it's adverse for a short too).
    bps = rfl.entry_slippage_bps("SHORT", fill_price=79.96, entry_ref_price=80.00)
    assert bps == pytest.approx(5.0)


def test_exit_slippage_bps_long_worse_fill_is_positive():
    bps = rfl.exit_slippage_bps("LONG", fill_price=81.959, reference_price=82.00)
    assert bps == pytest.approx(5.0)


def test_nominal_r_target_matches_configured_r_multiple():
    r = rfl.nominal_r("target", "LONG", stop_price=79.0, target_price=82.0, risk_per_share=1.0)
    assert r == pytest.approx(2.0)


def test_nominal_r_stop_is_minus_one():
    r = rfl.nominal_r("stop", "LONG", stop_price=79.0, target_price=82.0, risk_per_share=1.0)
    assert r == pytest.approx(-1.0)


def test_nominal_r_flatten_and_kill_switch_are_none():
    assert rfl.nominal_r("flatten", "LONG", stop_price=79.0, target_price=82.0, risk_per_share=1.0) is None
    assert rfl.nominal_r("kill_switch", "LONG", stop_price=79.0, target_price=82.0, risk_per_share=1.0) is None


# ---------------------------------------------------------------------------
# walk_bracket_to_resolution (step 4): the shared bar-walker every
# counterfactual (R-target, stop-width) replays through. Reuses
# backtest.bracket._resolve_bar unchanged -- tie-break/gap/D3-cap are already
# frozen there; this only locks the flatten-cutoff and data-ends behavior
# this module adds on top.
# ---------------------------------------------------------------------------

def test_walk_bracket_resolves_at_target():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),  # entry bar (not tested)
        ("2026-08-06T15:45:00Z", 80.05, 80.20, 80.00, 80.15),
        ("2026-08-06T15:50:00Z", 80.15, 82.05, 80.10, 82.00),  # touches target
    ])
    res = rfl.walk_bracket_to_resolution(
        b5, "LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, target_price=82.0,
    )
    assert res is not None
    assert res["exit_reason"] == "target"
    assert res["exit_price"] == pytest.approx(82.00 * (1 - 5 / 10_000))
    assert str(res["exit_time"]) == "2026-08-06 15:50:00+00:00"


def test_walk_bracket_stop_first_tie_break():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 82.10, 78.90, 80.15),  # both touched -> stop-first
    ])
    res = rfl.walk_bracket_to_resolution(
        b5, "LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, target_price=82.0,
    )
    assert res["exit_reason"] == "stop"
    assert res["exit_price"] == pytest.approx(79.0 * (1 - 5 / 10_000))


def test_walk_bracket_flattens_at_cutoff_before_resolution():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 80.20, 80.00, 80.15),
        ("2026-08-06T18:40:00Z", 80.60, 80.70, 80.50, 80.65),  # neither level touched
    ])
    res = rfl.walk_bracket_to_resolution(
        b5, "LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, target_price=82.0,
        flatten_time="2026-08-06T18:40:00Z",
    )
    assert res["exit_reason"] == "flatten"
    assert res["exit_price"] == pytest.approx(80.60 * (1 - 5 / 10_000))
    assert str(res["exit_time"]) == "2026-08-06 18:40:00+00:00"


def test_walk_bracket_returns_none_when_data_ends_unresolved():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 80.20, 80.00, 80.15),
    ])
    res = rfl.walk_bracket_to_resolution(
        b5, "LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, target_price=82.0,
    )
    assert res is None


def test_walk_bracket_short_mirrors_long():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 80.10, 77.95, 78.00),  # low touches target for a short
    ])
    res = rfl.walk_bracket_to_resolution(
        b5, "SHORT", after_time="2026-08-06T15:40:00Z", stop_price=81.0, target_price=78.0,
    )
    assert res["exit_reason"] == "target"
    assert res["exit_price"] == pytest.approx(78.0 * (1 + 5 / 10_000))


# ---------------------------------------------------------------------------
# Counterfactual geometry helpers (step 4, pinned interpretations 1/2).
# ---------------------------------------------------------------------------

def test_scaled_stop_price_scales_distance_long():
    # entry_ref=80, stop=79 -> distance 1.0; 1.25x -> stop 78.75.
    assert rfl.scaled_stop_price("LONG", entry_ref_price=80.0, stop_price=79.0, multiple=1.25) == \
        pytest.approx(78.75)


def test_scaled_stop_price_scales_distance_short():
    assert rfl.scaled_stop_price("SHORT", entry_ref_price=80.0, stop_price=81.0, multiple=1.5) == \
        pytest.approx(81.5)


def test_target_r_price_cents_quantized_long():
    # entry_ref=80, stop=79 -> distance 1.0; 1.0R -> raw target 81.00 (already whole cents).
    assert rfl.target_r_price("LONG", entry_ref_price=80.0, stop_price=79.0, r_multiple=1.0) == \
        pytest.approx(81.00)


# ---------------------------------------------------------------------------
# session_flatten_time (step 4, pinned interpretation 3): the day's ONE
# flatten-eligible hourly scan, found via is_flatten_scan over every scan on
# the date -- taking the EARLIEST qualifying bar (the live bot flattens at
# the first opportunity).
# ---------------------------------------------------------------------------

DAY_SCAN_GRID = [
    "2026-08-06T13:30:00Z", "2026-08-06T14:30:00Z", "2026-08-06T15:30:00Z",
    "2026-08-06T16:30:00Z", "2026-08-06T17:30:00Z", "2026-08-06T18:30:00Z",
]


def test_session_flatten_time_picks_earliest_qualifying_bar():
    scans = [scan_row(bar_ts=ts) for ts in DAY_SCAN_GRID]
    b5 = bars5([
        ("2026-08-06T19:35:00Z", 80.0, 80.1, 79.9, 80.0),
        ("2026-08-06T19:40:00Z", 80.0, 80.1, 79.9, 80.0),  # first bar at/after 19:37 action instant
    ])
    flatten_time = rfl.session_flatten_time("2026-08-06", scans, b5.index)
    assert str(flatten_time) == "2026-08-06 19:40:00+00:00"


def test_session_flatten_time_none_when_no_scan_qualifies():
    scans = [scan_row(bar_ts="2026-08-06T13:30:00Z")]  # far from close, never flattens
    b5 = bars5([("2026-08-06T14:00:00Z", 80.0, 80.1, 79.9, 80.0)])
    assert rfl.session_flatten_time("2026-08-06", scans, b5.index) is None


# ---------------------------------------------------------------------------
# Per-trade counterfactuals (step 4): R-target, stop-width, MAE-beyond-stop,
# no-flatten.
# ---------------------------------------------------------------------------

def test_r_target_counterfactual_resolves_earlier_than_2r():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 81.10, 80.00, 81.00),  # touches 1.0R target (81.00)
    ])
    cf = rfl.r_target_counterfactual(
        b5, side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        entry_ref_price=80.0, stop_price=79.0, risk_per_share=1.0, r_multiple=1.0,
    )
    assert cf["data"] == "ok"
    assert cf["exit_reason"] == "target"
    assert cf["r"] == pytest.approx((81.00 * (1 - 5 / 10_000) - 80.04) / 1.0)


def test_r_target_counterfactual_unavailable_when_data_ends():
    b5 = bars5([("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05)])
    cf = rfl.r_target_counterfactual(
        b5, side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        entry_ref_price=80.0, stop_price=79.0, risk_per_share=1.0, r_multiple=1.0,
    )
    assert cf["data"] == "unavailable"


def test_stop_width_counterfactual_survives_when_widened_stop_not_touched():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 80.20, 78.90, 80.15),  # dips to 78.90: hits tight stop
        ("2026-08-06T15:50:00Z", 80.15, 82.05, 80.10, 82.00),  # then rallies to target
    ])
    cf = rfl.stop_width_counterfactual(
        b5, side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        entry_ref_price=80.0, stop_price=79.0, target_price=82.0, risk_per_share=1.0,
        multiple=1.25,  # widened stop = 78.75, so the 78.90 dip does NOT touch it
    )
    assert cf["data"] == "ok"
    assert cf["survived"] is True
    assert cf["exit_reason"] == "target"


def test_stop_width_counterfactual_does_not_survive_when_still_touched():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 80.20, 78.00, 80.15),  # dips well past any scaled stop
    ])
    cf = rfl.stop_width_counterfactual(
        b5, side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        entry_ref_price=80.0, stop_price=79.0, target_price=82.0, risk_per_share=1.0,
        multiple=1.25,
    )
    assert cf["survived"] is False
    assert cf["exit_reason"] == "stop"


def test_stop_width_counterfactual_r_denominated_in_original_risk_per_share():
    # Pinned interpretation 1: the counterfactual R stays in the ORIGINAL risk_per_share
    # unit, never the scaled stop's own (wider) distance. multiple=2.0 scales the stop
    # distance to 2.0 (a widened stop of 78.0, distinct from risk_per_share=1.0) -- if r were
    # wrongly divided by the scaled distance instead, it would be exactly half this value.
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 82.05, 80.00, 82.00),  # touches target; stop untouched
    ])
    cf = rfl.stop_width_counterfactual(
        b5, side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        entry_ref_price=80.0, stop_price=79.0, target_price=82.0, risk_per_share=1.0,
        multiple=2.0,
    )
    assert cf["data"] == "ok"
    assert cf["exit_reason"] == "target"
    expected_r = (82.00 * (1 - 5 / 10_000) - 80.04) / 1.0  # denominator = original risk_per_share
    wrong_r_if_scaled_distance_used = (82.00 * (1 - 5 / 10_000) - 80.04) / 2.0
    assert cf["r"] == pytest.approx(expected_r)
    assert cf["r"] != pytest.approx(wrong_r_if_scaled_distance_used)


def test_mae_beyond_stop_r_zero_when_never_touched():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 82.05, 80.10, 82.00),
    ])
    r = rfl.mae_beyond_stop_r(
        b5, side="LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, risk_per_share=1.0,
    )
    assert r == pytest.approx(0.0)


def test_mae_beyond_stop_r_positive_when_price_dips_past_stop():
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 79.20, 77.50, 78.00),  # low 77.50, 1.5R beyond stop(79)
    ])
    r = rfl.mae_beyond_stop_r(
        b5, side="LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, risk_per_share=1.0,
    )
    assert r == pytest.approx(1.5)


def test_mae_beyond_stop_r_none_when_no_bars_after_entry():
    b5 = bars5([("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05)])
    r = rfl.mae_beyond_stop_r(
        b5, side="LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, risk_per_share=1.0,
    )
    assert r is None


def test_mae_beyond_stop_r_bounded_at_until_time_ignores_post_exit_collapse():
    # ROUND-1 REVIEWER MUST-FIX FINDING 4: a collapse AFTER the trade's own real exit is
    # not this trade's excursion -- the position was already closed. With until_time set,
    # the scan must stop at the exit fill and never see the post-exit collapse below stop.
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T16:30:00Z", 81.75, 82.05, 81.70, 82.00),  # the (target) exit bar
        ("2026-08-06T16:35:00Z", 82.00, 82.05, 77.00, 77.50),  # post-exit collapse well below stop
    ])
    r = rfl.mae_beyond_stop_r(
        b5, side="LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, risk_per_share=1.0,
        until_time="2026-08-06T16:30:00Z",
    )
    assert r == pytest.approx(0.0)


def test_mae_beyond_stop_r_unbounded_when_until_time_omitted_sees_post_exit_reversal():
    # Stop exits keep the FULL supplied window (stopped-then-reversed is the diagnostic's
    # own purpose) -- omitting until_time preserves the pre-fix unbounded behavior.
    b5 = bars5([
        ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),
        ("2026-08-06T15:45:00Z", 80.05, 80.10, 78.50, 78.60),  # stops out here
        ("2026-08-06T15:50:00Z", 78.60, 78.80, 77.50, 78.70),  # reverses further past stop
    ])
    r = rfl.mae_beyond_stop_r(
        b5, side="LONG", after_time="2026-08-06T15:40:00Z", stop_price=79.0, risk_per_share=1.0,
    )
    assert r == pytest.approx(1.5)


def test_no_flatten_counterfactual_replays_a_flattened_long_to_resolution():
    b5 = bars5([
        ("2026-08-06T19:40:00Z", 80.50, 80.60, 80.40, 80.55),  # the flatten bar itself
        ("2026-08-06T19:45:00Z", 80.55, 82.05, 80.50, 82.00),  # runs on to target after flatten
    ])
    cf = rfl.no_flatten_counterfactual_for_trade(
        side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        exit_fill_time="2026-08-06T19:40:00Z", exit_fill_price=80.53,
        stop_price=79.0, target_price=82.0, risk_per_share=1.0, exit_type="flatten", bars5=b5,
    )
    assert cf["applicable"] is True
    assert cf["data"] == "ok"
    assert cf["exit_reason"] == "target"


def test_no_flatten_counterfactual_not_applicable_for_a_target_exit():
    cf = rfl.no_flatten_counterfactual_for_trade(
        side="LONG", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=80.04,
        exit_fill_time="2026-08-06T16:35:00Z", exit_fill_price=81.959,
        stop_price=79.0, target_price=82.0, risk_per_share=1.0, exit_type="target",
        bars5=bars5([("2026-08-06T16:35:00Z", 81.9, 82.0, 81.8, 82.0)]),
    )
    assert cf["applicable"] is False


def test_no_flatten_counterfactual_unavailable_for_a_short_flatten():
    cf = rfl.no_flatten_counterfactual_for_trade(
        side="SHORT", entry_fill_time="2026-08-06T15:40:00Z", entry_fill_price=79.96,
        exit_fill_time="2026-08-06T19:40:00Z", exit_fill_price=79.5,
        stop_price=81.0, target_price=78.0, risk_per_share=1.0, exit_type="flatten",
        bars5=bars5([("2026-08-06T19:40:00Z", 79.5, 79.6, 79.4, 79.5)]),
    )
    assert cf["data"] == "unavailable"


# ---------------------------------------------------------------------------
# _bar_open_at (used for the flatten/kill-switch exit-slippage reference):
# at/after semantics, not exact-match -- real Alpaca filled_at values are
# never bar-aligned (round-1 reviewer must-fix finding 1).
# ---------------------------------------------------------------------------

def test_bar_open_at_exact_match():
    b5 = bars5([
        ("2026-08-06T19:35:00Z", 80.00, 80.10, 79.90, 80.00),
        ("2026-08-06T19:40:00Z", 80.50, 80.60, 80.40, 80.55),
    ])
    assert rfl._bar_open_at(b5, "2026-08-06T19:40:00Z") == pytest.approx(80.50)


def test_bar_open_at_non_aligned_time_returns_next_bars_open():
    b5 = bars5([
        ("2026-08-06T19:35:00Z", 80.00, 80.10, 79.90, 80.00),
        ("2026-08-06T19:40:00Z", 80.50, 80.60, 80.40, 80.55),
        ("2026-08-06T19:45:00Z", 80.55, 80.65, 80.45, 80.60),
    ])
    # A real Alpaca filled_at is never bar-aligned -- 19:37:02.364 sits strictly between
    # the 19:35 and 19:40 bars, so the reference must be the FIRST bar at/after it (19:40),
    # never None from a failed exact-match equality check.
    assert rfl._bar_open_at(b5, "2026-08-06T19:37:02.364Z") == pytest.approx(80.50)


def test_bar_open_at_none_when_past_end_of_window():
    b5 = bars5([("2026-08-06T19:35:00Z", 80.00, 80.10, 79.90, 80.00)])
    assert rfl._bar_open_at(b5, "2026-08-06T19:40:00Z") is None


# ---------------------------------------------------------------------------
# compute_trade_record (step 3+4 tie-together): assembles pairing +
# classification + slippage + nominal/realized R + all six counterfactuals
# into the per-trade record the JSONL/markdown renderers consume. Three
# scenario fixtures per the sub-plan: target-ish, stop, flatten.
# ---------------------------------------------------------------------------

TARGET_DAY_BARS = bars5([
    ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),  # entry bar
    ("2026-08-06T15:45:00Z", 80.05, 80.20, 80.00, 80.15),
    ("2026-08-06T15:50:00Z", 80.15, 80.40, 80.10, 80.35),
    ("2026-08-06T15:55:00Z", 80.35, 80.60, 80.30, 80.55),
    ("2026-08-06T16:00:00Z", 80.55, 80.80, 80.50, 80.75),
    ("2026-08-06T16:05:00Z", 80.75, 81.00, 80.70, 80.95),
    ("2026-08-06T16:10:00Z", 80.95, 81.20, 80.90, 81.15),
    ("2026-08-06T16:15:00Z", 81.15, 81.40, 81.10, 81.35),
    ("2026-08-06T16:20:00Z", 81.35, 81.60, 81.30, 81.55),
    ("2026-08-06T16:25:00Z", 81.55, 81.80, 81.50, 81.75),
    ("2026-08-06T16:30:00Z", 81.75, 82.05, 81.70, 82.00),  # touches target 82.00
    ("2026-08-06T16:35:00Z", 82.00, 82.05, 81.90, 82.00),
])

TARGET_DAY_SCANS = [scan_row(bar_ts=ts) for ts in DAY_SCAN_GRID] + [
    scan_row(
        bar_ts="2026-08-06T14:30:00Z", decision="LONG",
        entry_ref_price=80.00, stop_price=79.00, target_price=82.00,
        risk_per_share=1.00, qty=100, entry_order_id="entry-1",
    ),
]


def _target_day_closed_trade():
    result = rfl.pair_hourly_trades(
        [
            trade_row(
                side="BUY", qty=100, fill_price=80.04, fill_time="2026-08-06T15:40:00Z",
                reason="hourly_long_entry", broker_order_id="entry-1",
            ),
            trade_row(
                side="SELL", qty=100, fill_price=81.959, fill_time="2026-08-06T16:30:00Z",
                reason="hourly_bracket_exit", broker_order_id="exit-1",
            ),
        ],
        TARGET_DAY_SCANS,
    )
    return result.closed_trades[0]


def test_compute_trade_record_target_day():
    ct = _target_day_closed_trade()
    rec = rfl.compute_trade_record(ct, TARGET_DAY_BARS, "2026-08-06", TARGET_DAY_SCANS)
    assert rec["entry_order_id"] == "entry-1"
    assert rec["exit_type"] == "target"
    assert rec["deviation_reason"] == "slippage"
    assert rec["entry_slippage_bps"] == pytest.approx(5.0)
    assert rec["exit_slippage_bps"] == pytest.approx(5.0)
    assert rec["nominal_r"] == pytest.approx(2.0)
    assert rec["realized_r"] == pytest.approx((81.959 - 80.04) / 1.0)
    cf = rec["counterfactuals"]
    assert cf["data"] == "ok"
    assert cf["target_1_0r"]["exit_reason"] == "target"
    assert cf["stop_1_25x"]["survived"] is True
    assert cf["no_flatten"]["applicable"] is False
    assert cf["mae_beyond_stop_r"] == pytest.approx(0.0)


TARGET_DAY_BARS_WITH_POST_EXIT_COLLAPSE = bars5([
    ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),  # entry bar
    ("2026-08-06T16:30:00Z", 81.75, 82.05, 81.70, 82.00),  # touches target 82.00 -- the real exit
    ("2026-08-06T16:35:00Z", 82.00, 82.05, 70.00, 71.00),  # post-exit collapse well below stop 79.00
])


def test_compute_trade_record_target_exit_mae_bounded_ignores_post_exit_collapse():
    # ROUND-1 REVIEWER MUST-FIX FINDING 4: for a non-stop exit, MAE-beyond-stop must be
    # bounded at the trade's own real exit fill -- a post-exit collapse far below the
    # original stop happened after the position was already closed, so it must not be
    # reported as this trade's excursion.
    ct = _target_day_closed_trade()
    rec = rfl.compute_trade_record(
        ct, TARGET_DAY_BARS_WITH_POST_EXIT_COLLAPSE, "2026-08-06", TARGET_DAY_SCANS,
    )
    assert rec["exit_type"] == "target"
    assert rec["counterfactuals"]["mae_beyond_stop_r"] == pytest.approx(0.0)


STOP_DAY_BARS = bars5([
    ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),  # entry bar
    ("2026-08-06T15:45:00Z", 80.05, 80.10, 78.50, 78.60),  # gap through stop (78.50 < 79.00)
    ("2026-08-06T15:50:00Z", 78.60, 78.80, 78.40, 78.70),
])

STOP_DAY_SCANS = [scan_row(bar_ts=ts) for ts in DAY_SCAN_GRID] + [
    scan_row(
        bar_ts="2026-08-06T14:30:00Z", decision="LONG",
        entry_ref_price=80.00, stop_price=79.00, target_price=82.00,
        risk_per_share=1.00, qty=100, entry_order_id="entry-stop",
    ),
]


def _stop_day_closed_trade():
    result = rfl.pair_hourly_trades(
        [
            trade_row(
                side="BUY", qty=100, fill_price=80.04, fill_time="2026-08-06T15:40:00Z",
                reason="hourly_long_entry", broker_order_id="entry-stop",
            ),
            trade_row(
                side="SELL", qty=100, fill_price=78.50, fill_time="2026-08-06T15:45:00Z",
                reason="hourly_bracket_exit", broker_order_id="exit-stop",
            ),
        ],
        STOP_DAY_SCANS,
    )
    return result.closed_trades[0]


def test_compute_trade_record_stop_day_gap_through_stop():
    ct = _stop_day_closed_trade()
    rec = rfl.compute_trade_record(ct, STOP_DAY_BARS, "2026-08-06", STOP_DAY_SCANS)
    assert rec["exit_type"] == "stop"
    assert rec["deviation_reason"] == "gap"
    assert rec["nominal_r"] == pytest.approx(-1.0)
    assert rec["realized_r"] == pytest.approx((78.50 - 80.04) / 1.0)
    # A stop exit keeps the FULL supplied window (round-1 reviewer must-fix finding 4):
    # the 15:50 bar (low 78.40, AFTER the 15:45 exit) reverses 0.6R further past the
    # original stop, and that post-exit reversal measurement must still be reported.
    assert rec["counterfactuals"]["mae_beyond_stop_r"] == pytest.approx(0.6)


FLATTEN_DAY_SCANS = [scan_row(bar_ts=ts) for ts in DAY_SCAN_GRID] + [
    scan_row(
        bar_ts="2026-08-06T14:30:00Z", decision="LONG",
        entry_ref_price=80.00, stop_price=79.00, target_price=82.00,
        risk_per_share=1.00, qty=100, entry_order_id="entry-flatten",
    ),
]

FLATTEN_DAY_BARS = bars5([
    ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.95, 80.05),  # entry bar
    ("2026-08-06T15:45:00Z", 80.05, 80.30, 80.00, 80.25),
    ("2026-08-06T19:40:00Z", 80.50, 80.60, 80.40, 80.55),  # flatten fill bar
    ("2026-08-06T19:45:00Z", 80.55, 82.05, 80.50, 82.00),  # runs on after flatten (no_flatten cf)
])


def _flatten_day_closed_trade():
    result = rfl.pair_hourly_trades(
        [
            trade_row(
                side="BUY", qty=100, fill_price=80.04, fill_time="2026-08-06T15:40:00Z",
                reason="hourly_long_entry", broker_order_id="entry-flatten",
            ),
            trade_row(
                side="SELL", qty=100, fill_price=80.45975, fill_time="2026-08-06T19:40:00Z",
                reason="hourly_session_close_exit", broker_order_id="exit-flatten",
            ),
        ],
        FLATTEN_DAY_SCANS,
    )
    return result.closed_trades[0]


def test_compute_trade_record_flatten_day():
    ct = _flatten_day_closed_trade()
    rec = rfl.compute_trade_record(ct, FLATTEN_DAY_BARS, "2026-08-06", FLATTEN_DAY_SCANS)
    assert rec["exit_type"] == "flatten"
    assert rec["deviation_reason"] == "flatten"
    assert rec["nominal_r"] is None
    assert rec["exit_slippage_bps"] == pytest.approx(5.0, abs=0.01)
    assert rec["counterfactuals"]["no_flatten"]["applicable"] is True
    assert rec["counterfactuals"]["no_flatten"]["exit_reason"] == "target"


def _flatten_day_closed_trade_non_aligned_fill():
    result = rfl.pair_hourly_trades(
        [
            trade_row(
                side="BUY", qty=100, fill_price=80.04, fill_time="2026-08-06T15:40:00Z",
                reason="hourly_long_entry", broker_order_id="entry-flatten",
            ),
            trade_row(
                side="SELL", qty=100, fill_price=80.45975, fill_time="2026-08-06T19:37:02.364Z",
                reason="hourly_session_close_exit", broker_order_id="exit-flatten",
            ),
        ],
        FLATTEN_DAY_SCANS,
    )
    return result.closed_trades[0]


def test_compute_trade_record_flatten_exit_slippage_reference_at_or_after_non_aligned_fill():
    # ROUND-1 REVIEWER FINDING 1 (must-fix): real Alpaca filled_at values are never
    # bar-aligned. An exact-match bar lookup for the flatten/kill-switch exit-slippage
    # reference would silently degrade this to None. The reference must be the Open of
    # the first bar at/after the fill time -- here, the 19:40 bar (Open 80.50) -- even
    # though the fill itself lands at 19:37:02.364, strictly between the 19:35 (implicit,
    # absent from this fixture) and 19:40 bars.
    ct = _flatten_day_closed_trade_non_aligned_fill()
    rec = rfl.compute_trade_record(ct, FLATTEN_DAY_BARS, "2026-08-06", FLATTEN_DAY_SCANS)
    assert rec["exit_type"] == "flatten"
    assert rec["exit_slippage_bps"] is not None
    expected = rfl.exit_slippage_bps("LONG", 80.45975, 80.50)  # 19:40 bar's Open
    assert rec["exit_slippage_bps"] == pytest.approx(expected)


SHORT_FLATTEN_DAY_SCANS = [scan_row(bar_ts=ts) for ts in DAY_SCAN_GRID] + [
    scan_row(
        bar_ts="2026-08-06T14:30:00Z", decision="SHORT",
        entry_ref_price=80.00, stop_price=81.00, target_price=78.00,
        risk_per_share=1.00, qty=100, entry_order_id="entry-short-flatten",
    ),
]

# Neither the widened stops (81.25/81.5) nor the tightened targets (79.0/78.5) are ever
# touched; the position flattens cleanly at 19:40, so target/stop/mae all resolve "ok" --
# only no_flatten degrades, because no_flatten_counterfactual is LONG-only (see
# no_flatten_counterfactual_for_trade's own docstring).
SHORT_FLATTEN_DAY_BARS = bars5([
    ("2026-08-06T15:40:00Z", 80.00, 80.10, 79.90, 80.00),  # entry bar
    ("2026-08-06T15:45:00Z", 80.00, 80.10, 79.90, 80.00),
    ("2026-08-06T19:40:00Z", 80.50, 80.60, 80.40, 80.50),  # flatten fill bar
])


def _short_flatten_day_closed_trade():
    result = rfl.pair_hourly_trades(
        [
            trade_row(
                side="SELL", qty=100, fill_price=79.96, fill_time="2026-08-06T15:40:00Z",
                reason="hourly_short_entry", broker_order_id="entry-short-flatten",
            ),
            trade_row(
                side="BUY", qty=100, fill_price=80.5, fill_time="2026-08-06T19:40:00Z",
                reason="hourly_session_close_exit", broker_order_id="exit-short-flatten",
            ),
        ],
        SHORT_FLATTEN_DAY_SCANS,
    )
    return result.closed_trades[0]


def test_compute_trade_record_short_flatten_aggregate_data_is_partial():
    # FINDING 1 (round 1): a SHORT flatten exit's own no_flatten sub-field degrades to
    # "unavailable" (no_flatten_counterfactual is LONG-only), but every other counterfactual
    # resolves cleanly -- the aggregate flag must fold in no_flatten and report "partial",
    # never "ok".
    ct = _short_flatten_day_closed_trade()
    rec = rfl.compute_trade_record(ct, SHORT_FLATTEN_DAY_BARS, "2026-08-06", SHORT_FLATTEN_DAY_SCANS)
    cf = rec["counterfactuals"]
    assert cf["no_flatten"]["applicable"] is True
    assert cf["no_flatten"]["data"] == "unavailable"
    assert cf["target_1_0r"]["data"] == "ok"
    assert cf["target_1_5r"]["data"] == "ok"
    assert cf["stop_1_25x"]["data"] == "ok"
    assert cf["stop_1_5x"]["data"] == "ok"
    assert cf["mae_beyond_stop_r"] is not None
    assert cf["data"] == "partial"


def test_compute_trade_record_degrades_when_scan_missing():
    trades = [
        trade_row(
            side="BUY", qty=100, fill_price=80.0, fill_time="2026-08-06T15:40:00Z",
            reason="hourly_long_entry", broker_order_id="entry-nomatch",
        ),
        trade_row(
            side="SELL", qty=100, fill_price=81.0, fill_time="2026-08-06T16:00:00Z",
            reason="hourly_bracket_exit", broker_order_id="exit-nomatch",
        ),
    ]
    ct = rfl.pair_hourly_trades(trades, []).closed_trades[0]
    rec = rfl.compute_trade_record(ct, TARGET_DAY_BARS, "2026-08-06", [])
    assert rec["exit_type"] == "unknown"
    assert rec["counterfactuals"]["data"] == "unavailable"
    assert "missing scan row" in rec["r_multiple_na_reason"]


# ---------------------------------------------------------------------------
# Trailing-20 fold (step 5): stateless -- ledger's prior reflection.trades
# plus today's, ordered by exit fill time, window = min(n, 20).
# ---------------------------------------------------------------------------

def _synthetic_trade_record(
    exit_fill_time, *, exit_type="target", realized_r=1.0,
    target_1_0r_r=0.5, target_1_5r_r=0.8, stop_1_25x_survived=True,
    entry_slippage_bps=5.0, exit_slippage_bps=5.0,
    target_1_0r_data="ok", target_1_5r_data="ok",
):
    return {
        "exit_fill_time": exit_fill_time,
        "exit_type": exit_type,
        "realized_r": realized_r,
        "entry_slippage_bps": entry_slippage_bps,
        "exit_slippage_bps": exit_slippage_bps,
        "counterfactuals": {
            "target_1_0r": {"data": target_1_0r_data, "r": target_1_0r_r},
            "target_1_5r": {"data": target_1_5r_data, "r": target_1_5r_r},
            "stop_1_25x": {"data": "ok", "survived": stop_1_25x_survived},
            "stop_1_5x": {"data": "ok", "survived": stop_1_25x_survived},
            "no_flatten": {"applicable": False},
            "mae_beyond_stop_r": 0.0,
            "data": "ok",
        },
    }


def test_build_trailing_window_takes_last_20_across_ledger_and_today():
    # 19 prior ledger records (days 1-19) + 2 today's records (days 20-21) -> window
    # drops the OLDEST (day 1), keeping days 2-21 (20 records).
    prior_rows = []
    for day in range(1, 20):
        prior_rows.append({
            "date": f"2026-07-{day:02d}",
            "reflection": {"trades": [_synthetic_trade_record(f"2026-07-{day:02d}T16:00:00Z")]},
        })
    today_records = [
        _synthetic_trade_record("2026-08-06T16:00:00Z"),
        _synthetic_trade_record("2026-08-06T19:00:00Z"),
    ]
    window = rfl.build_trailing_window(prior_rows, today_records)
    assert len(window) == 20
    assert window[0]["exit_fill_time"] == "2026-07-02T16:00:00Z"  # day 1 dropped
    assert window[-1]["exit_fill_time"] == "2026-08-06T19:00:00Z"


def test_build_trailing_window_smaller_than_20_uses_all_available():
    today_records = [_synthetic_trade_record("2026-08-06T16:00:00Z")]
    window = rfl.build_trailing_window([], today_records)
    assert len(window) == 1


def test_build_trailing_window_ignores_pre_reflection_ledger_rows():
    # A pre-ship ledger row has no "reflection" key at all -- must not raise.
    prior_rows = [{"date": "2026-07-01", "verdict": "PASS"}]
    window = rfl.build_trailing_window(prior_rows, [_synthetic_trade_record("2026-08-06T16:00:00Z")])
    assert len(window) == 1


# ---------------------------------------------------------------------------
# Cost check + trailing20 aggregates (step 5).
# ---------------------------------------------------------------------------

def test_compute_cost_check_median_over_fills():
    window = [
        _synthetic_trade_record("2026-08-06T16:00:00Z", entry_slippage_bps=5.0, exit_slippage_bps=5.0),
        _synthetic_trade_record("2026-08-06T17:00:00Z", entry_slippage_bps=15.0, exit_slippage_bps=5.0),
    ]
    cc = rfl.compute_cost_check(window)
    assert cc["n"] == 4
    assert cc["median_abs_slippage_bps"] == pytest.approx(5.0)
    assert cc["model_bps"] == pytest.approx(5.0)
    assert cc["ratio"] == pytest.approx(1.0)


def test_compute_trailing20_cumulative_r_and_stop_survival():
    window = [
        _synthetic_trade_record(
            "2026-08-06T16:00:00Z", exit_type="stop", realized_r=-1.0,
            target_1_0r_r=-1.0, target_1_5r_r=-1.0, stop_1_25x_survived=True,
        ),
        _synthetic_trade_record(
            "2026-08-06T17:00:00Z", exit_type="stop", realized_r=-1.0,
            target_1_0r_r=-1.0, target_1_5r_r=-1.0, stop_1_25x_survived=False,
        ),
    ]
    t20 = rfl.compute_trailing20(window)
    assert t20["n"] == 2
    # cumulative_r columns are {"r", "n"} (round-1 reviewer must-fix finding 3): "live" is
    # the unpaired total over every trade with a realized_r; each cf column is summed over
    # its OWN ok-subset, so a mismatched n is always visible next to the number.
    assert t20["cumulative_r"]["live"] == {"r": pytest.approx(-2.0), "n": 2}
    assert t20["cumulative_r"]["target_1_0r"] == {"r": pytest.approx(-2.0), "n": 2}
    assert t20["stop_survival"]["stop_1_25x"] == {"survived": 1, "total": 2, "pct": 0.5}


def test_compute_trailing20_cumulative_r_n_reflects_cf_columns_own_ok_subset():
    # A trade whose target_1_0r counterfactual is unavailable must not be counted in that
    # column's n, even though it IS counted in "live"'s own n -- the whole point of
    # printing a per-column n is to make that subset mismatch visible.
    window = [
        _synthetic_trade_record("2026-08-06T16:00:00Z", realized_r=1.0, target_1_0r_r=0.5),
        _synthetic_trade_record(
            "2026-08-06T17:00:00Z", realized_r=-5.0, target_1_0r_r=None, target_1_0r_data="unavailable",
        ),
    ]
    t20 = rfl.compute_trailing20(window)
    assert t20["cumulative_r"]["live"] == {"r": pytest.approx(-4.0), "n": 2}
    assert t20["cumulative_r"]["target_1_0r"] == {"r": pytest.approx(0.5), "n": 1}


# ---------------------------------------------------------------------------
# Triggers (step 5) -- boundary semantics pinned exactly by test.
# ---------------------------------------------------------------------------

def _stop_out_window(n_survived, n_total):
    window = []
    for i in range(n_total):
        window.append(_synthetic_trade_record(
            f"2026-08-06T{16+i}:00:00Z", exit_type="stop", realized_r=-1.0,
            stop_1_25x_survived=(i < n_survived),
        ))
    return window


def test_trigger1_fires_at_exactly_60_pct():
    window = _stop_out_window(3, 5)  # 60.0%
    triggers = rfl.compute_triggers(window)
    t1 = triggers[0]
    assert t1["value"] == pytest.approx(0.6)
    assert t1["fired"] is True


def test_trigger1_does_not_fire_below_60_pct():
    window = _stop_out_window(2, 5)  # 40%
    triggers = rfl.compute_triggers(window)
    assert triggers[0]["fired"] is False


def test_trigger1_no_denominator_when_no_stop_outs():
    window = [_synthetic_trade_record("2026-08-06T16:00:00Z", exit_type="target")]
    triggers = rfl.compute_triggers(window)
    t1 = triggers[0]
    assert t1["value"] is None
    assert t1["fired"] is False


def test_trigger2_fires_when_closer_target_beats_live_cumulative():
    window = [
        _synthetic_trade_record("2026-08-06T16:00:00Z", realized_r=0.5, target_1_0r_r=1.0, target_1_5r_r=0.9),
        _synthetic_trade_record("2026-08-06T17:00:00Z", realized_r=0.5, target_1_0r_r=1.0, target_1_5r_r=0.9),
    ]
    triggers = rfl.compute_triggers(window)
    t2 = triggers[1]
    assert t2["fired"] is True


def test_trigger2_does_not_fire_on_a_tie():
    window = [
        _synthetic_trade_record("2026-08-06T16:00:00Z", realized_r=1.0, target_1_0r_r=1.0, target_1_5r_r=1.0),
    ]
    triggers = rfl.compute_triggers(window)
    assert triggers[1]["fired"] is False


def test_trigger2_is_paired_not_diluted_by_cf_unavailable_trades():
    # ROUND-1 REVIEWER MUST-FIX FINDING 3 (lead ruling): trigger 2 compares cumulative live
    # vs cumulative counterfactual over the INTERSECTION of trades where the compared cf
    # column is "ok" -- an UNPAIRED comparison (live summed over every trade, cf summed only
    # over its own ok-subset) would let a big loss the counterfactual has no opinion on
    # inflate the cf's apparent edge and fire the trigger; the paired comparison must not.
    window = [
        _synthetic_trade_record(
            "2026-08-06T16:00:00Z", realized_r=1.0, target_1_0r_r=0.5, target_1_5r_r=0.5,
        ),
        _synthetic_trade_record(
            "2026-08-06T17:00:00Z", realized_r=1.0, target_1_0r_r=0.5, target_1_5r_r=0.5,
        ),
        _synthetic_trade_record(
            "2026-08-06T18:00:00Z", realized_r=-5.0,
            target_1_0r_r=None, target_1_0r_data="unavailable",
            target_1_5r_r=None, target_1_5r_data="unavailable",
        ),
    ]
    # Unpaired (wrong): live = 1+1-5 = -3; best cf = 0.5+0.5 = 1.0 over the 2-trade
    # ok-subset -> 1.0 > -3 would fire.
    unpaired_live = sum(t["realized_r"] for t in window)
    unpaired_best_cf = 1.0
    assert unpaired_best_cf > unpaired_live  # sanity: the unpaired comparison WOULD fire

    triggers = rfl.compute_triggers(window)
    t2 = triggers[1]
    # Paired (correct): live restricted to the SAME 2-trade ok-subset = 1+1 = 2.0; best cf
    # over that subset = 0.5+0.5 = 1.0 -> 1.0 is NOT > 2.0, so the trigger must not fire.
    assert t2["fired"] is False
    assert t2["n"] == 2
    assert t2["value"] == pytest.approx(1.0)
    assert t2["threshold"] == pytest.approx(2.0)


def test_trigger2_selects_by_paired_improvement_not_raw_cf_r():
    # ROUND-2 REVIEWER SHOULD-FIX FINDING 2: the two candidates' pairings can have
    # different intersections, so picking the "best" candidate by raw cf_r (ignoring its
    # own live_r) is the same mismatched-subset class of bug as round-1 finding 3, just in
    # the false-negative direction. Here the 1.0R candidate has the higher raw cf_r (10.0)
    # but over a pairing where live_r (20.0) is even higher -- no improvement, no fire. The
    # 1.5R candidate has a lower raw cf_r (2.0) but over its OWN pairing shows a real
    # improvement over live_r (0.5) -- it should fire. Selecting by raw cf_r picks the 1.0R
    # candidate and false-negatives; selecting by paired improvement (cf_r - live_r) picks
    # the 1.5R candidate and fires.
    window = [
        _synthetic_trade_record(
            "2026-08-06T16:00:00Z", realized_r=20.0,
            target_1_0r_r=10.0, target_1_0r_data="ok",
            target_1_5r_r=None, target_1_5r_data="unavailable",
        ),
        _synthetic_trade_record(
            "2026-08-06T17:00:00Z", realized_r=0.5,
            target_1_0r_r=None, target_1_0r_data="unavailable",
            target_1_5r_r=2.0, target_1_5r_data="ok",
        ),
    ]
    triggers = rfl.compute_triggers(window)
    t2 = triggers[1]
    assert t2["fired"] is True
    assert t2["n"] == 1
    assert t2["value"] == pytest.approx(2.0)
    assert t2["threshold"] == pytest.approx(0.5)


def test_trigger2_ties_toward_the_populated_pairing_when_neither_improves():
    # PR #581 REVIEW ROUND-3 RECORD-AND-SHIP NIT: when neither candidate improves and one
    # pairing is empty (n=0, so live_r == cf_r == 0.0 trivially), the naive max-by-paired-
    # improvement selection picks the empty pairing's diff of exactly 0.0 over the populated
    # pairing's genuinely worse (but real) diff -- displaying zeros instead of the populated
    # pairing's diagnostics. Here the 1.0R candidate has no ok data at all (n=0, diff=0.0);
    # the 1.5R candidate is populated but worse than live (live_r=2.0 > cf_r=1.0, diff=-1.0).
    # Neither improves, so `fired` must stay False regardless of which is selected -- but the
    # record should carry the POPULATED 1.5R pairing's value/threshold/n, not the empty
    # pairing's zeros.
    window = [
        _synthetic_trade_record(
            "2026-08-06T16:00:00Z", realized_r=2.0,
            target_1_0r_r=None, target_1_0r_data="unavailable",
            target_1_5r_r=1.0, target_1_5r_data="ok",
        ),
    ]
    triggers = rfl.compute_triggers(window)
    t2 = triggers[1]
    assert t2["fired"] is False
    assert t2["n"] == 1
    assert t2["value"] == pytest.approx(1.0)
    assert t2["threshold"] == pytest.approx(2.0)


def _cost_window(bps):
    return [_synthetic_trade_record(
        "2026-08-06T16:00:00Z", entry_slippage_bps=bps, exit_slippage_bps=bps,
    )]


def test_trigger3_does_not_fire_at_exactly_2x():
    triggers = rfl.compute_triggers(_cost_window(10.0))  # ratio exactly 2.0
    assert triggers[2]["fired"] is False


def test_trigger3_fires_above_2x():
    triggers = rfl.compute_triggers(_cost_window(10.01))
    assert triggers[2]["fired"] is True


def test_trigger3_does_not_fire_at_exactly_half():
    triggers = rfl.compute_triggers(_cost_window(2.5))  # ratio exactly 0.5
    assert triggers[2]["fired"] is False


def test_trigger3_fires_below_half():
    triggers = rfl.compute_triggers(_cost_window(2.49))
    assert triggers[2]["fired"] is True


# ---------------------------------------------------------------------------
# Renderers (step 6): markdown section + reflection JSON object.
# ---------------------------------------------------------------------------

def test_render_markdown_no_trades_is_one_liner():
    md = rfl.render_markdown("2026-08-06", [], rfl.compute_cost_check([]), rfl.compute_trailing20([]), rfl.compute_triggers([]))
    assert md == "## Reflection\n\nNo closed trades; no reflection."


def test_build_reflection_object_no_trades():
    obj = rfl.build_reflection_object(
        "2026-08-06", [], rfl.compute_cost_check([]), rfl.compute_trailing20([]), rfl.compute_triggers([]),
    )
    assert obj["no_closed_trades"] is True
    assert obj["error"] is None
    assert obj["trades"] == []
    assert obj["engine_version"] == rfl.ENGINE_VERSION


def test_build_reflection_object_with_error():
    obj = rfl.build_reflection_object("2026-08-06", [], {}, {}, [], error="bars file not found")
    assert obj["error"] == "bars file not found"


def test_golden_markdown_render_one_target_trade():
    ct = _target_day_closed_trade()
    rec = rfl.compute_trade_record(ct, TARGET_DAY_BARS, "2026-08-06", TARGET_DAY_SCANS)
    window = rfl.build_trailing_window([], [rec])
    cost_check = rfl.compute_cost_check(window)
    trailing20 = rfl.compute_trailing20(window)
    triggers = rfl.compute_triggers(window)
    md = rfl.render_markdown("2026-08-06", [rec], cost_check, trailing20, triggers)
    golden_path = "tests/fixtures/reflection/golden-2026-08-06.md"
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = f.read()
    assert md == golden


# ---------------------------------------------------------------------------
# compute_reflection (step 7): the top-level orchestration the CLI calls.
# Never raises -- a computation failure degrades into the envelope.
# ---------------------------------------------------------------------------

def _write_target_day_fixture(tmp_path):
    digest = {
        "verification": {
            "scans": TARGET_DAY_SCANS,
            "trades": [
                trade_row(
                    side="BUY", qty=100, fill_price=80.04, fill_time="2026-08-06T15:40:00Z",
                    reason="hourly_long_entry", broker_order_id="entry-1",
                ),
                trade_row(
                    side="SELL", qty=100, fill_price=81.959, fill_time="2026-08-06T16:30:00Z",
                    reason="hourly_bracket_exit", broker_order_id="exit-1",
                ),
            ],
        }
    }
    bars_path = tmp_path / "bars5.csv"
    TARGET_DAY_BARS.reset_index().rename(columns={"index": "timestamp"}).to_csv(bars_path, index=False)
    return digest, str(bars_path)


def test_compute_reflection_envelope_shape(tmp_path):
    digest, bars_path = _write_target_day_fixture(tmp_path)
    envelope = rfl.compute_reflection("2026-08-06", digest, bars_path, [])
    assert envelope["date"] == "2026-08-06"
    assert envelope["markdown"].startswith("## Reflection")
    assert envelope["reflection"]["no_closed_trades"] is False
    assert envelope["reflection"]["error"] is None
    assert len(envelope["reflection"]["trades"]) == 1


def test_compute_reflection_degrades_on_missing_bars_file():
    digest = {"verification": {"scans": [], "trades": []}}
    envelope = rfl.compute_reflection("2026-08-06", digest, "/no/such/file.csv", [])
    assert envelope["reflection"]["error"] is not None
    assert envelope["markdown"].startswith("Reflection: error --")


def test_compute_reflection_error_day_cumulative_r_columns_are_r_n_shape():
    # ROUND-2 REVIEWER MUST-FIX FINDING 1: the error-path fallback must emit the same
    # {"r", "n"} shape as the happy-path trailing20.cumulative_r columns, never a bare
    # float -- error days are designed output (a missing bars file lands here by
    # contract), so the frozen JSONL shape must hold on exactly these rows too.
    digest = {"verification": {"scans": [], "trades": []}}
    envelope = rfl.compute_reflection("2026-08-06", digest, "/no/such/file.csv", [])
    cr = envelope["reflection"]["trailing20"]["cumulative_r"]
    for column in ("live", "target_1_0r", "target_1_5r"):
        assert cr[column] == {"r": 0.0, "n": 0}


def test_compute_reflection_no_trades_day(tmp_path):
    bars_path = tmp_path / "bars5.csv"
    TARGET_DAY_BARS.reset_index().rename(columns={"index": "timestamp"}).to_csv(bars_path, index=False)
    digest = {"verification": {"scans": [], "trades": []}}
    envelope = rfl.compute_reflection("2026-08-06", digest, str(bars_path), [])
    assert envelope["reflection"]["no_closed_trades"] is True
    assert envelope["markdown"] == "## Reflection\n\nNo closed trades; no reflection."


def test_compute_reflection_is_deterministic_across_two_runs(tmp_path):
    digest, bars_path = _write_target_day_fixture(tmp_path)
    e1 = json.dumps(rfl.compute_reflection("2026-08-06", digest, bars_path, []))
    e2 = json.dumps(rfl.compute_reflection("2026-08-06", digest, bars_path, []))
    assert e1 == e2


# ---------------------------------------------------------------------------
# CLI determinism (step 7): backtest/run_nightly_reflection.py over committed
# fixture files -- two runs, byte-identical stdout; envelope parses; markdown
# matches the golden.
# ---------------------------------------------------------------------------

FIXTURES_DIR = "tests/fixtures/reflection"


def _cli_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT
    return env


def _run_cli():
    return subprocess.run(
        [
            sys.executable, "backtest/run_nightly_reflection.py",
            "--date=2026-08-06",
            f"--digest={FIXTURES_DIR}/digest-2026-08-06.json",
            f"--bars={FIXTURES_DIR}/bars5-2026-08-06.csv",
            f"--ledger={FIXTURES_DIR}/ledger-2026-08-06.jsonl",
        ],
        capture_output=True, text=True, cwd=REPO_ROOT, env=_cli_env(),
    )


def test_cli_runs_clean_and_matches_golden_markdown():
    result = _run_cli()
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["date"] == "2026-08-06"
    assert envelope["reflection"]["error"] is None
    with open(f"{FIXTURES_DIR}/golden-2026-08-06.md", "r", encoding="utf-8") as f:
        golden = f.read()
    assert envelope["markdown"] == golden


def test_cli_is_deterministic_across_two_runs():
    r1 = _run_cli()
    r2 = _run_cli()
    assert r1.returncode == 0 and r2.returncode == 0
    assert r1.stdout == r2.stdout


def test_cli_exits_1_on_malformed_digest_json(tmp_path):
    bad_digest = tmp_path / "bad.json"
    bad_digest.write_text("{not json")
    result = subprocess.run(
        [
            sys.executable, "backtest/run_nightly_reflection.py",
            "--date=2026-08-06",
            f"--digest={bad_digest}",
            f"--bars={FIXTURES_DIR}/bars5-2026-08-06.csv",
            f"--ledger={FIXTURES_DIR}/ledger-2026-08-06.jsonl",
        ],
        capture_output=True, text=True, cwd=REPO_ROOT, env=_cli_env(),
    )
    assert result.returncode == 1
    assert result.stdout == ""


def test_cli_exits_1_on_missing_required_arg():
    result = subprocess.run(
        [sys.executable, "backtest/run_nightly_reflection.py", "--date=2026-08-06"],
        capture_output=True, text=True, cwd=REPO_ROOT, env=_cli_env(),
    )
    assert result.returncode == 1
    assert result.stdout == ""


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
