"""Tests for backtest/hourly_geometry.py (#571 step D).

Covers: STOP-first tie-break (via the reused _resolve_bar), flatten-scan timing (the
scan+7min / sessionClose-period cadence mapping), cooldown, day cap, the no-flatten
counterfactual, and the sizing-cap equity replay. All synthetic data -- no staged CSVs
read here (those are exercised only by backtest/run_hourly_geometry_study.py, run
manually against data/intraday/).

Timing note (load-bearing for every fixture below): a 60m decision's own timestamp is
the CANDIDATE BAR'S START. The live scan -- and therefore any fill -- happens at
bar_close + SCAN_OFFSET_MIN (7min), i.e. bar_start + period_minutes + 7 minutes. For a
14:00 UTC 60m bar that is 15:07 UTC; the fill lands on the first 5Min bar at/after that
instant (15:10). Every fixture's 5Min bars are placed at that ~67-minute offset from the
decision's own timestamp, not immediately after it.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest.hourly_geometry import (
    Trade,
    cost_drag_diagnostic,
    is_flatten_scan,
    no_flatten_counterfactual,
    replay_equity,
    session_close_utc_ms,
    simulate_hourly_geometry,
)


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


def decision(ts, action_final="SKIP", entry_ref=None, stop_price=None, stop_distance=None,
             target_price=None):
    return {
        "timestamp": ts,
        "action_final": action_final,
        "entry_ref": entry_ref,
        "stop_price": stop_price,
        "stop_distance": stop_distance,
        "target_price": target_price,
    }


# ---------------------------------------------------------------------------
# session_close_utc_ms / is_flatten_scan -- the scan+7min cadence mapping (Q3)
# ---------------------------------------------------------------------------

def test_session_close_utc_ms_is_16_00_et_edt():
    # 2024-06-03 is a Monday in EDT (UTC-4): 16:00 ET -> 20:00 UTC.
    ms = session_close_utc_ms("2024-06-03")
    assert pd.Timestamp(ms, unit="ms", tz="UTC") == pd.Timestamp("2024-06-03T20:00:00Z")


def test_is_flatten_scan_true_when_53_minutes_of_headroom_remain_at_60m():
    # Candidate bar 18:00-19:00 UTC (15:00-16:00 ET EDT); scan at 19:07 UTC;
    # sessionClose(20:00) - 19:07 = 53min <= 60min period -> flatten.
    bar_end_ms = int(pd.Timestamp("2024-06-03T19:00:00Z").value // 1_000_000)
    assert is_flatten_scan("2024-06-03", bar_end_ms, period_minutes=60) is True


def test_is_flatten_scan_false_with_113_minutes_of_headroom_at_60m():
    # Candidate bar 17:00-18:00 UTC (14:00 ET); scan at 18:07 UTC;
    # sessionClose(20:00) - 18:07 = 113min > 60min -> not flatten.
    bar_end_ms = int(pd.Timestamp("2024-06-03T18:00:00Z").value // 1_000_000)
    assert is_flatten_scan("2024-06-03", bar_end_ms, period_minutes=60) is False


def test_is_flatten_scan_30m_flattens_later_in_the_day_than_60m():
    # Candidate bar 18:30-19:00 UTC (30m); scan at 19:07; sessionClose 20:00 - 19:07 =
    # 53min > 30min period -> NOT flatten (30m arm gets one more actionable bar than 60m).
    bar_end_ms = int(pd.Timestamp("2024-06-03T19:00:00Z").value // 1_000_000)
    assert is_flatten_scan("2024-06-03", bar_end_ms, period_minutes=30) is False
    # The next half-hour bar (19:00-19:30) IS the 30m flatten scan (23min <= 30min).
    bar_end_ms2 = int(pd.Timestamp("2024-06-03T19:30:00Z").value // 1_000_000)
    assert is_flatten_scan("2024-06-03", bar_end_ms2, period_minutes=30) is True


# ---------------------------------------------------------------------------
# simulate_hourly_geometry -- tie-break, entry/exit fills
# ---------------------------------------------------------------------------

def test_stop_first_tie_break_on_a_both_touched_bar():
    """A post-entry 5Min bar that touches both stop and target resolves STOP-first
    (the frozen conservative tie-break, reused unchanged from bracket.py::_resolve_bar).
    """
    b = bars5([
        ("2024-06-03T15:10:00Z", 100.0, 100.0, 100.0, 100.0),  # entry fill bar (14:00 bar + 67min)
        ("2024-06-03T15:15:00Z", 100.0, 106.0, 94.0, 100.0),   # touches both stop(95)/target(105)
    ])
    decisions = [
        decision("2024-06-03T14:00:00+00:00", "LONG",
                 entry_ref=100.0, stop_price=95.0, stop_distance=5.0, target_price=105.0),
    ]
    result = simulate_hourly_geometry(decisions, b, period_minutes=60, day_cap=3, slippage_bps=0)
    trades = result["trades"]
    assert len(trades) == 1
    assert trades[0].exit_reason == "stop"


def test_target_hit_gives_positive_r_realized_near_configured_r():
    b = bars5([
        ("2024-06-03T15:10:00Z", 100.0, 100.0, 100.0, 100.0),
        ("2024-06-03T15:15:00Z", 100.0, 106.0, 99.5, 100.0),  # hits target(105) only
    ])
    decisions = [
        decision("2024-06-03T14:00:00+00:00", "LONG",
                 entry_ref=100.0, stop_price=95.0, stop_distance=5.0, target_price=105.0),
    ]
    result = simulate_hourly_geometry(decisions, b, period_minutes=60, day_cap=3, slippage_bps=0)
    trades = result["trades"]
    assert len(trades) == 1
    assert trades[0].exit_reason == "target"
    # entry at 100 (no slippage), exit at target 105 -> r_realized = (105-100)/5 = 1.0
    assert trades[0].r_realized == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Flatten timing
# ---------------------------------------------------------------------------

def test_open_position_is_flattened_at_the_session_close_scan():
    # Entry at the 14:00 UTC bar (fills 15:10); never hits stop/target; the 18:00-19:00
    # UTC candidate bar (scanned 19:07 UTC) is a flatten scan at 60m cadence -- position
    # must close at that scan's fill bar (first 5Min bar open at/after 19:07 -> 19:10).
    b = bars5([
        ("2024-06-03T15:10:00Z", 100.0, 100.5, 99.5, 100.0),  # entry fill bar
        ("2024-06-03T15:15:00Z", 100.0, 100.2, 99.8, 100.0),  # never touches stop/target
        ("2024-06-03T19:10:00Z", 101.0, 101.2, 100.8, 101.0),  # flatten fill bar (>= 19:07)
        ("2024-06-03T19:15:00Z", 101.0, 101.1, 100.9, 101.0),
    ])
    decisions = [
        decision("2024-06-03T14:00:00+00:00", "LONG",
                 entry_ref=100.0, stop_price=90.0, stop_distance=10.0, target_price=140.0),
        decision("2024-06-03T18:00:00+00:00", "SKIP"),  # the flatten-scan row itself
    ]
    result = simulate_hourly_geometry(decisions, b, period_minutes=60, day_cap=3, slippage_bps=0)
    trades = result["trades"]
    assert len(trades) == 1
    assert trades[0].exit_reason == "flatten"
    assert trades[0].exit_price == pytest.approx(101.0)


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def test_cooldown_allows_a_new_entry_once_its_own_bar_start_is_after_the_last_exit():
    # Trade 1: 14:00 bar -> fills 15:10, target-hit exit at 15:15 (last_exit=15:15).
    # Trade 2: 16:00 bar -- its OWN bar start (16:00) is after 15:15, so cooldown clears;
    # fills 17:10, target-hit exit at 17:15.
    b = bars5([
        ("2024-06-03T15:10:00Z", 100.0, 100.0, 100.0, 100.0),
        ("2024-06-03T15:15:00Z", 100.0, 106.0, 99.5, 100.0),   # trade 1 target hit
        ("2024-06-03T17:10:00Z", 101.0, 101.0, 101.0, 101.0),
        ("2024-06-03T17:15:00Z", 101.0, 107.0, 100.5, 101.0),  # trade 2 target hit
    ])
    decisions = [
        decision("2024-06-03T14:00:00+00:00", "LONG",
                 entry_ref=100.0, stop_price=95.0, stop_distance=5.0, target_price=105.0),
        decision("2024-06-03T16:00:00+00:00", "LONG",
                 entry_ref=101.0, stop_price=96.0, stop_distance=5.0, target_price=106.0),
    ]
    result = simulate_hourly_geometry(decisions, b, period_minutes=60, day_cap=3, slippage_bps=0)
    assert len(result["trades"]) == 2
    assert [t.exit_reason for t in result["trades"]] == ["target", "target"]


def test_cooldown_blocks_a_next_hour_signal_whose_bar_start_precedes_the_prior_exit():
    # Trade 1: 14:00 bar -> fills 15:10, exits (target) at 15:15.
    # The 15:00 bar's OWN start (15:00) is <= the exit's fill time (15:15) -> cooldown
    # blocks it, even though its fill instant (16:10) would be well after the exit.
    b = bars5([
        ("2024-06-03T15:10:00Z", 100.0, 100.0, 100.0, 100.0),
        ("2024-06-03T15:15:00Z", 100.0, 106.0, 99.5, 100.0),  # trade 1 target hit
    ])
    decisions = [
        decision("2024-06-03T14:00:00+00:00", "LONG",
                 entry_ref=100.0, stop_price=95.0, stop_distance=5.0, target_price=105.0),
        decision("2024-06-03T15:00:00+00:00", "LONG",
                 entry_ref=100.5, stop_price=95.5, stop_distance=5.0, target_price=105.5),
    ]
    result = simulate_hourly_geometry(decisions, b, period_minutes=60, day_cap=3, slippage_bps=0)
    assert len(result["trades"]) == 1


# ---------------------------------------------------------------------------
# Day cap
# ---------------------------------------------------------------------------

def test_day_cap_blocks_the_next_entry_once_reached():
    # day_cap=1: trade 1 (14:00 bar) enters and exits; trade 2 (16:00 bar) would clear
    # cooldown (its bar start is well after trade 1's exit) but is blocked by the day cap.
    b = bars5([
        ("2024-06-03T15:10:00Z", 100.0, 100.0, 100.0, 100.0),
        ("2024-06-03T15:15:00Z", 100.0, 106.0, 99.5, 100.0),  # trade 1 target hit
    ])
    decisions = [
        decision("2024-06-03T14:00:00+00:00", "LONG",
                 entry_ref=100.0, stop_price=95.0, stop_distance=5.0, target_price=105.0),
        decision("2024-06-03T16:00:00+00:00", "LONG",
                 entry_ref=101.0, stop_price=96.0, stop_distance=5.0, target_price=106.0),
    ]
    result = simulate_hourly_geometry(decisions, b, period_minutes=60, day_cap=1, slippage_bps=0)
    assert len(result["trades"]) == 1


# ---------------------------------------------------------------------------
# no_flatten_counterfactual
# ---------------------------------------------------------------------------

def test_no_flatten_counterfactual_lets_a_flattened_trade_run_to_target():
    flattened = [
        Trade(
            entry_time=pd.Timestamp("2024-06-03T15:10:00Z"),
            exit_time=pd.Timestamp("2024-06-03T19:10:00Z"),
            entry_price=100.0, exit_price=101.0,
            stop_price=90.0, target_price=110.0,
            exit_reason="flatten", stop_distance=10.0,
            r_realized=(101.0 - 100.0) / 10.0,
        ),
    ]
    b = bars5([
        ("2024-06-03T19:10:00Z", 101.0, 101.2, 100.8, 101.0),  # the flatten bar itself
        ("2024-06-03T19:15:00Z", 101.0, 101.5, 100.9, 101.0),
        ("2024-06-03T19:20:00Z", 101.0, 111.0, 100.9, 101.0),  # target(110) hit here
    ])
    out = no_flatten_counterfactual(flattened, b, slippage_bps=0)
    assert len(out) == 1
    assert out[0].exit_reason == "target"
    assert out[0].exit_price == pytest.approx(110.0)
    assert out[0].entry_price == pytest.approx(100.0)  # entry unchanged from the original trade


# ---------------------------------------------------------------------------
# replay_equity
# ---------------------------------------------------------------------------

def test_replay_equity_compounds_and_flags_a_15pct_breach():
    # risk_pct=1.0 keeps the risk leg from binding ahead of the cap, so a single -20%
    # trade at cap_pct=1.0 (full notional) breaches the -15% floor outright.
    losers = [
        Trade(
            entry_time=pd.Timestamp("2024-01-01T00:00:00Z"),
            exit_time=pd.Timestamp("2024-01-01T01:00:00Z"),
            entry_price=100.0, exit_price=80.0,  # -20%
            stop_price=90.0, target_price=110.0,
            exit_reason="stop", stop_distance=10.0, r_realized=-2.0,
        ),
    ]
    result = replay_equity(
        losers, cap_pct=1.0, risk_pct=1.0, starting_cash=100_000.0, commission_bps=0,
    )
    assert result["ending_equity"] < 100_000.0
    assert result["breached_15pct_floor"] is True
    assert result["total_return"] < 0


def test_cost_drag_diagnostic_quantifies_round_trip_cost_against_stop_distance():
    # entry_price is stored post-slippage; reconstructing the pre-slippage entry ref lets
    # the diagnostic compare round-trip cost in price terms against the planned risk unit.
    slip = 5 / 10_000.0
    entry_ref = 100.0
    trades = [
        Trade(
            entry_time=pd.Timestamp("2024-01-01T00:00:00Z"),
            exit_time=pd.Timestamp("2024-01-01T01:00:00Z"),
            entry_price=entry_ref * (1 + slip), exit_price=99.0,
            stop_price=95.0, target_price=110.0,
            exit_reason="stop", stop_distance=0.05,  # tiny stop -- cost should dominate
            r_realized=-2.0,
        ),
        Trade(
            entry_time=pd.Timestamp("2024-01-01T02:00:00Z"),
            exit_time=pd.Timestamp("2024-01-01T03:00:00Z"),
            entry_price=entry_ref * (1 + slip), exit_price=110.0,
            stop_price=95.0, target_price=110.0,
            exit_reason="target", stop_distance=10.0,  # wide stop -- cost negligible
            r_realized=1.0,
        ),
    ]
    result = cost_drag_diagnostic(trades, slippage_bps=5)
    assert result["n"] == 2
    assert result["pct_entry_slippage_exceeds_stop_distance"] == pytest.approx(50.0)
    assert result["median_cost_over_stop_distance"] > 0


def test_replay_equity_smaller_cap_produces_a_smaller_magnitude_return():
    winners = [
        Trade(
            entry_time=pd.Timestamp("2024-01-01T00:00:00Z"),
            exit_time=pd.Timestamp("2024-01-01T01:00:00Z"),
            entry_price=100.0, exit_price=110.0,
            stop_price=95.0, target_price=110.0,
            exit_reason="target", stop_distance=5.0, r_realized=2.0,
        )
    ]
    full = replay_equity(winners, cap_pct=1.0, starting_cash=100_000.0, commission_bps=0)
    tenth = replay_equity(winners, cap_pct=0.10, starting_cash=100_000.0, commission_bps=0)
    assert tenth["total_return"] < full["total_return"]
    assert tenth["breached_15pct_floor"] is False
