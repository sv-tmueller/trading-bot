from __future__ import annotations

import math
import pytest
from strategy.regime import compute_target_state


# --- Bullish regime (SPY > SMA200) ---

def test_bullish_no_ks_from_cash_returns_long():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=380.0,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "LONG"
    assert ks is False


def test_bullish_no_ks_already_long_stays_long():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=380.0,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "LONG"
    assert ks is False


def test_bullish_with_ks_clears_flag_and_re_enters():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=380.0,
                                       current_state="CASH", kill_switch_active=True)
    assert target == "LONG"
    assert ks is False  # flag cleared on bullish re-entry


# --- Bearish regime (SPY <= SMA200) ---

def test_bearish_no_ks_from_long_exits():
    target, ks = compute_target_state(spy_close=380.0, spy_sma200=400.0,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_bearish_no_ks_already_cash_stays_cash():
    target, ks = compute_target_state(spy_close=380.0, spy_sma200=400.0,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_bearish_with_ks_keeps_flag_set():
    target, ks = compute_target_state(spy_close=380.0, spy_sma200=400.0,
                                       current_state="CASH", kill_switch_active=True)
    assert target == "CASH"
    assert ks is True  # flag stays — bearish, no re-entry


# --- Boundary: SPY == SMA200 (strictly greater than required for LONG) ---

def test_boundary_equal_sma_returns_cash():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=400.0,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_boundary_equal_sma_from_long_exits():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=400.0,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


# --- Defensive: NaN SMA (insufficient history) ---

def test_nan_sma_returns_cash_defensively():
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=math.nan,
                                       current_state="CASH", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


def test_nan_sma_with_existing_long_exits_to_cash():
    """If SMA goes NaN unexpectedly mid-strategy (data issue), bot must exit defensively."""
    target, ks = compute_target_state(spy_close=400.0, spy_sma200=math.nan,
                                       current_state="LONG", kill_switch_active=False)
    assert target == "CASH"
    assert ks is False


# --- Validation ---

def test_invalid_current_state_raises():
    with pytest.raises(ValueError, match="current_state"):
        compute_target_state(spy_close=400.0, spy_sma200=380.0,
                             current_state="HOLDING", kill_switch_active=False)


def test_negative_spy_close_raises():
    with pytest.raises(ValueError, match="spy_close"):
        compute_target_state(spy_close=-1.0, spy_sma200=380.0,
                             current_state="CASH", kill_switch_active=False)


def test_negative_sma_raises():
    with pytest.raises(ValueError, match="spy_sma200"):
        compute_target_state(spy_close=400.0, spy_sma200=-380.0,
                             current_state="CASH", kill_switch_active=False)


# --- Truth-table coverage (all 8 combos: regime × current × ks) ---

@pytest.mark.parametrize("spy,sma,cur,ks_in,expected_target,expected_ks", [
    (400, 380, "CASH",  False, "LONG", False),
    (400, 380, "CASH",  True,  "LONG", False),  # ks cleared on bullish
    (400, 380, "LONG",  False, "LONG", False),
    (400, 380, "LONG",  True,  "LONG", False),  # ks cleared on bullish (edge case)
    (380, 400, "CASH",  False, "CASH", False),
    (380, 400, "CASH",  True,  "CASH", True),   # ks preserved
    (380, 400, "LONG",  False, "CASH", False),
    (380, 400, "LONG",  True,  "CASH", True),
])
def test_truth_table(spy, sma, cur, ks_in, expected_target, expected_ks):
    target, ks_out = compute_target_state(spy_close=spy, spy_sma200=sma,
                                           current_state=cur, kill_switch_active=ks_in)
    assert target == expected_target
    assert ks_out == expected_ks
