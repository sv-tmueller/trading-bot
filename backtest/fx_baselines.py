"""The 4 dumb baselines (#376, spec §5) -- STATE functions, not entry-event
functions. Each is consumed by ``fx_execution.simulate_fx_state`` (no
TP/SL bracket; exits only via a state flip or window end, per spec §5's
pinned candidate/baseline asymmetry).

Research-only. Lives in ``backtest/`` and is never imported by
``supabase/functions/``. No LLM, no broker calls, no orders.

Interpretive pins (SUB_PLAN §3, not spec text -- flagged, reasoned, tested):
  (a) Persistence's zero-return bar resolves to FLAT, per §2's global
      theta=0 tie rule (the spec does not explicitly restate the tie rule
      for this baseline, but §2 states it applies to "every family below").
  (b) Buy-and-hold's state fill mechanics: state is 0 before the last
      pre-roll bar and 1 from that bar onward, so that
      ``simulate_fx_state`` (which reads state[i-1] to decide bar i's
      fill) lands the entry EXACTLY on the test window's first bar's open
      -- the only reading consistent with §1's T -> T+1 semantics.
"""
from __future__ import annotations

import pandas as pd


def always_flat_state(index: pd.Index) -> pd.Series:
    """Baseline 1: always-flat. All-zero state -- never enters a position.
    Its survivor criterion (spec §6) is applied to the CANDIDATE, not
    computed here: "median-window return > 0"."""
    return pd.Series(0, index=index, dtype="int64")


def buy_and_hold_state(index: pd.Index, from_ts: pd.Timestamp) -> pd.Series:
    """Baseline 2: EUR/USD buy-and-hold. State 0 before ``from_ts``
    (exclusive) and 1 from ``from_ts`` onward (inclusive) -- ``from_ts`` is
    the LAST PRE-ROLL bar, so the T -> T+1 fill (applied by
    ``simulate_fx_state``) lands on the test window's first bar's open."""
    sig = pd.Series(0, index=index, dtype="int64")
    sig[index >= from_ts] = 1
    return sig


def persistence_state(mid_close: pd.Series) -> pd.Series:
    """Baseline 3: persistence -- sign of the last completed 4h bar's
    mid-close return, re-evaluated every bar. Zero-return bar (or the first
    bar, with no prior close) -> flat (interpretive pin (a) above)."""
    ret = mid_close.diff()
    sig = pd.Series(0, index=mid_close.index, dtype="int64")
    sig[ret > 0] = 1
    sig[ret < 0] = -1
    return sig


def sma200_regime_state(mid_close: pd.Series, n: int = 200) -> pd.Series:
    """Baseline 4: 200-SMA regime, transplanted (spec §5 lead decision #7):
    mid close vs SMA(200 NATIVE 4h bars) -- long above, flat below (never
    short; the daily-SMA alternative is flagged, not used, per the spec)."""
    sma = mid_close.rolling(n).mean()
    sig = pd.Series(0, index=mid_close.index, dtype="int64")
    sig[mid_close > sma] = 1
    return sig
