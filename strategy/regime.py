"""Pure regime-filter logic. The entire trading decision lives in one function.

Decision rule (Mebane Faber, 2007):
    if SPY > SMA(200):  target = LONG    (kill-switch flag cleared if previously set)
    else:               target = CASH   (kill-switch flag preserved if set)

This module is intentionally I/O-free. All I/O happens in callers (`daily_check.py`,
`monitor/kill_switch.py`). That makes the function trivially testable and removes
any path where business logic could be perturbed by network/clock/DB state.
"""
from __future__ import annotations

import math
from typing import Literal

State = Literal["LONG", "CASH"]


def compute_target_state(
    *,
    spy_close: float,
    spy_sma200: float,
    current_state: State,
    kill_switch_active: bool,
) -> tuple[State, bool]:
    """Compute target portfolio state and updated kill-switch flag.

    Args:
        spy_close: Today's SPY closing price. Must be > 0.
        spy_sma200: Today's 200-day SMA of SPY. NaN is acceptable (insufficient
            history) and triggers defensive CASH. Must be >= 0 if not NaN.
        current_state: The bot's current position state ('LONG' or 'CASH').
        kill_switch_active: Whether a recent kill-switch event is suppressing
            re-entry. Cleared automatically when SPY > SMA200.

    Returns:
        (target_state, new_kill_switch_active).

    Raises:
        ValueError: on invalid inputs (negative prices, unknown state).
    """
    if spy_close <= 0:
        raise ValueError(f"spy_close must be > 0, got {spy_close}")
    if not math.isnan(spy_sma200) and spy_sma200 < 0:
        raise ValueError(f"spy_sma200 must be >= 0 or NaN, got {spy_sma200}")
    if current_state not in ("LONG", "CASH"):
        raise ValueError(f"current_state must be LONG or CASH, got {current_state!r}")

    # Defensive: if SMA200 unavailable, force CASH and preserve any kill-switch flag.
    if math.isnan(spy_sma200):
        return "CASH", kill_switch_active

    # Strictly greater than — exact equality treated as bearish.
    is_bullish = spy_close > spy_sma200

    if is_bullish:
        return "LONG", False  # bullish always clears the kill-switch flag

    # Bearish: stay in / move to CASH; preserve any existing flag.
    return "CASH", kill_switch_active
