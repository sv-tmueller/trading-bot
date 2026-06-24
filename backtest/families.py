"""Strategy-family target-weight builders for the #314 candidate survey.

Three published low-turnover families, each expressed as a daily target-weight
frame (dates x assets, weights in [0,1], row sum <= 1, remainder = cash) so it
feeds straight into ``backtest.regime.simulate_from_signal(target_weights=...)``.

Families (fixed published params — set before any result was seen, no in-sample
tuning):

1. Dual-momentum rotation (Antonacci Global Equities Momentum, GEM standard
   form). Held universe: SPY (US equity), EFA (ex-US equity), AGG (agg bonds).
   Monthly on month-end closes:
     - absolute-momentum hurdle: SPY 12m trailing total return vs BIL 12m
       trailing total return (T-bill proxy, Antonacci's canonical hurdle).
     - risk-off (SPY 12m <= BIL 12m): hold AGG.
     - risk-on  (SPY 12m  > BIL 12m): hold whichever of SPY / EFA has the higher
       12m trailing return.
   Single asset at 100% each month; forward-filled to daily so transitions land
   only at month boundaries (Trap B). The T+1 open fill is applied by the
   simulator's shift.

2. TAA / Faber moving-average timing:
   (a) single-asset 10-month SMA on SPY (the published Faber rule) — 100% SPY
       when month-end close > 10-month SMA, else cash. This reuses the exact
       ``faber_sma_signal`` logic via a one-column {0,1} weight frame.
   (b) Faber 5-asset GTAA-lite: SPY, EFA, AGG, DBC, VNQ. Each asset is held at
       1/5 when its own month-end close > its own 10-month SMA, else that fifth
       sits in cash. Monthly, ffill-to-daily, next-open.

3. Vol-targeting (single-asset SPY, continuous weight): daily target weight =
   min(target_vol / realized_vol, cap), where realized_vol is the 20-day
   trailing annualised vol of SPY daily returns (ddof=1). Warm-up rows -> cash.
   The T+1 open fill is applied by the simulator's shift (do not pre-shift here).

Research-only. Lives in backtest/ and is never imported by supabase/functions/.
No LLM, no broker calls. Every function takes already-fetched price frames so
the network lives in the runner, not here (keeps the unit tests offline).
"""
from __future__ import annotations

import math

import pandas as pd

_MOMENTUM_MONTHS = 12   # GEM trailing-return lookback
_SMA_MONTHS = 10        # Faber moving-average length


def _monthly_close(close: pd.Series) -> pd.Series:
    """Month-end close (pandas 'ME' anchor — matches backtest.baselines)."""
    return close.resample("ME").last()


def gem_weights(
    asset_close: dict,
    daily_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Antonacci GEM monthly target weights, forward-filled to ``daily_index``.

    Parameters
    ----------
    asset_close:
        ``{"SPY": close_series, "EFA": ..., "AGG": ..., "BIL": ...}`` — daily
        close price Series. SPY/EFA/AGG are the held universe; BIL is the
        absolute-momentum hurdle only (never held).
    daily_index:
        The daily trading index to forward-fill the monthly decision onto
        (typically the common index of the held assets' price frames).

    Returns
    -------
    DataFrame indexed by ``daily_index`` with columns ["SPY", "EFA", "AGG"],
    each row one-hot (the chosen asset = 1.0, others 0.0) or all-zero (cash)
    during the 12-month warm-up. Forward-filled from the monthly decision so
    transitions occur only at month boundaries.
    """
    spy_m = _monthly_close(asset_close["SPY"])
    efa_m = _monthly_close(asset_close["EFA"])
    bil_m = _monthly_close(asset_close["BIL"])

    spy_mom = spy_m.pct_change(_MOMENTUM_MONTHS)
    efa_mom = efa_m.pct_change(_MOMENTUM_MONTHS)
    bil_mom = bil_m.pct_change(_MOMENTUM_MONTHS)

    # Decide on each month-end where all three momenta are defined.
    months = spy_mom.index
    choice = pd.Series(index=months, dtype=object)
    for m in months:
        s, e, b = spy_mom.get(m), efa_mom.get(m), bil_mom.get(m)
        if pd.isna(s) or pd.isna(e) or pd.isna(b):
            choice[m] = None  # warm-up: stay in cash
            continue
        if s <= b:
            choice[m] = "AGG"          # risk-off: absolute momentum fails
        else:
            choice[m] = "SPY" if s >= e else "EFA"  # risk-on: relative momentum

    monthly_w = pd.DataFrame(
        0.0, index=months, columns=["SPY", "EFA", "AGG"]
    )
    for m in months:
        c = choice[m]
        if c is not None:
            monthly_w.loc[m, c] = 1.0
        # None -> all-zero row (cash) stays as initialised

    # Forward-fill the monthly weights onto the daily index (Trap B): each day
    # carries the prior month-end decision. Days before the first month-end ->
    # NaN -> treated as cash (the simulator reads NaN as 0).
    daily_w = monthly_w.reindex(monthly_w.index.union(daily_index), method="ffill")
    daily_w = daily_w.reindex(daily_index)
    return daily_w


def faber_single_weights(
    spy_close: pd.Series,
    daily_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Faber single-asset 10-month SMA on SPY as a one-column weight frame.

    100% SPY when the month-end close is above its 10-month SMA, else cash.
    Built from the published Faber monthly rule (resample to month-end, 10-month
    SMA, ffill to daily), returned as a {0,1} one-column frame so it can run on
    the weighted simulator (the simulator dispatches a one-column 0/1 frame to
    the binary path, so the equity curve matches the baseline exactly).
    """
    spy_m = _monthly_close(spy_close)
    sma = spy_m.rolling(_SMA_MONTHS).mean()
    monthly_sig = (spy_m > sma).where(sma.notna(), other=float("nan"))

    daily_sig = monthly_sig.reindex(monthly_sig.index.union(daily_index), method="ffill")
    daily_sig = daily_sig.reindex(daily_index)
    # NaN warm-up -> 0.0 (cash); else 0/1 weight
    weights = daily_sig.map(lambda v: float(v) if pd.notna(v) else 0.0)
    return pd.DataFrame({"SPY": weights}, index=daily_index)


def faber_gtaa_weights(
    asset_close: dict,
    daily_index: pd.DatetimeIndex,
    *,
    assets: tuple = ("SPY", "EFA", "AGG", "DBC", "VNQ"),
) -> pd.DataFrame:
    """Faber 5-asset GTAA-lite monthly target weights, ffilled to daily.

    Each asset is held at ``1/len(assets)`` when its own month-end close is above
    its own 10-month SMA, else that sleeve sits in cash. So the row sum ranges
    from 0 (all five below their SMA -> 100% cash) to 1.0 (all five above).

    Parameters
    ----------
    asset_close:
        ``{asset: daily close Series}`` for every name in ``assets``.
    daily_index:
        Daily index to forward-fill the monthly decision onto.
    assets:
        The five sleeves (default SPY/EFA/AGG/DBC/VNQ). Each gets an equal
        ``1/N`` target weight when its own price is above its own 10-month SMA.
    """
    sleeve = 1.0 / len(assets)
    monthly_frames: dict = {}
    month_index = None
    for a in assets:
        m = _monthly_close(asset_close[a])
        sma = m.rolling(_SMA_MONTHS).mean()
        sig = (m > sma).where(sma.notna(), other=float("nan"))
        monthly_frames[a] = sig
        month_index = sig.index if month_index is None else month_index.union(sig.index)

    monthly_w = pd.DataFrame(0.0, index=month_index, columns=list(assets))
    for a in assets:
        sig = monthly_frames[a].reindex(month_index)
        # held only where the signal is True (above SMA); NaN/False -> 0
        monthly_w[a] = sig.map(lambda v: sleeve if (pd.notna(v) and bool(v)) else 0.0)

    daily_w = monthly_w.reindex(monthly_w.index.union(daily_index), method="ffill")
    daily_w = daily_w.reindex(daily_index)
    return daily_w


def vol_target_weights(
    spy_close: pd.Series,
    daily_index: pd.DatetimeIndex,
    *,
    target_vol: float = 0.10,
    vol_window: int = 20,
    cap: float = 1.0,
) -> pd.DataFrame:
    """Vol-targeting weight builder: daily SPY weight scaled to hit target_vol.

    Parameters
    ----------
    spy_close:
        Daily SPY close price Series (any index superset of daily_index is fine).
    daily_index:
        The daily trading index that the returned frame must be indexed by.
    target_vol:
        Annualised volatility target (default 10% = 0.10).
    vol_window:
        Rolling window in trading days for realized vol (default 20).
    cap:
        Maximum allowed weight — never lever above 100% (default 1.0).

    Returns
    -------
    One-column DataFrame({"SPY": w}, index=daily_index) where

        realized_vol = spy_close.pct_change().rolling(vol_window).std(ddof=1) * sqrt(252)
        w = min(target_vol / realized_vol, cap)

    Warm-up rows (where rolling std is NaN, i.e. fewer than vol_window returns)
    are set to 0.0 (cash). The weight is the close-T value — the simulator owns
    shift(1) to convert it to a next-open fill.
    """
    rets = spy_close.pct_change()
    realized_vol = rets.rolling(vol_window).std(ddof=1) * math.sqrt(252)

    # Compute raw weight; warm-up NaN -> 0.0 (cash).
    raw_w = (target_vol / realized_vol).clip(upper=cap)
    raw_w = raw_w.fillna(0.0)

    # Align to daily_index (reindex, filling any gaps by forward-fill then 0).
    w = raw_w.reindex(daily_index, method="ffill").fillna(0.0)
    return pd.DataFrame({"SPY": w}, index=daily_index)
