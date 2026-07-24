"""Profit-protecting giveback exit — pure logic shared by the backtest.

RESEARCH module (no Alpaca import, no orders). Behavioral mirror of the live
TypeScript that Phase B will add to kill-switch/logic.ts + daily-check/logic.ts
(spec docs/superpowers/specs/2026-07-24-giveback-exit-design.md §3-§6). Evaluated
on daily closes: a synthetic leveraged vehicle has no intraday bar.
"""
from __future__ import annotations

import pandas as pd

# Ratio gains (close/entry - 1) carry float rounding, so a price rising exactly
# arm_pct lands a hair below the threshold (120/100 - 1 == 0.19999999999999996).
# A tiny tolerance keeps the arm/floor comparisons faithful to the intended
# boundary (a +arm_pct peak arms; a close at the floor fires).
_EPS = 1e-9


def apply_giveback(
    signal: pd.Series,
    vehicle_close: pd.Series,
    *,
    arm_pct: float,
    protect_fraction: float,
) -> pd.Series:
    """Transform a LONG/CASH regime signal into a giveback-adjusted position series.

    While LONG, tracks peak gain since entry; once peak gain >= ``arm_pct`` a floor
    at ``protect_fraction * peak_gain`` arms. A close at/below the floor exits to
    CASH and locks re-entry until the signal itself next goes CASH (regime reset).
    The floor ratchets up with each higher peak. Entry price is the vehicle close
    on the day the adjusted series turns LONG (a 1-tick approximation; the engine
    computes P&L on realized fills the same way for both arms).
    """
    close = vehicle_close.reindex(signal.index)
    out: list[str] = []
    in_pos = False
    entry = peak = 0.0
    locked = False

    for ts, sig in signal.items():
        px = float(close.loc[ts])
        if locked:
            if sig == "CASH":
                locked = False  # regime reset clears the lock
            out.append("CASH")
            continue
        if sig == "LONG":
            if not in_pos:
                in_pos, entry, peak = True, px, px
            else:
                peak = max(peak, px)
            peak_gain = peak / entry - 1.0
            cur_gain = px / entry - 1.0
            if (
                peak_gain >= arm_pct - _EPS
                and cur_gain <= protect_fraction * peak_gain + _EPS
            ):
                in_pos = False
                locked = True
                out.append("CASH")
            else:
                out.append("LONG")
        else:  # signal CASH
            in_pos = False
            out.append("CASH")

    return pd.Series(out, index=signal.index)
