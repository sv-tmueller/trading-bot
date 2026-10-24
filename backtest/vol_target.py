"""Volatility-target sizing and the vol-targeted SPY benchmark (research-only).

Research-only: no network, no broker, no LLM, no production code. Pure
numpy/pandas helpers that turn long/flat/short signals into target weights for
the weighted simulator (``backtest.regime.simulate_from_signal(target_weights=
...)``), plus the benchmark every candidate must beat: SPY run through exactly
the same sizing mechanism and the same gross cap (design spec 5.2 criterion 2).

Time semantics (no lookahead)
-----------------------------
Row T of ``asset_returns`` is the simple return from close T-1 to close T.
Every estimate at row T uses exactly the ``lookback`` rows T-lookback+1 .. T
(counted by position, including T), with ddof=1. The weight at T is therefore a
close-T target. **This module applies no shift**: the simulator applies the
fill at the T+1 open, the same convention as ``families.vol_target_weights``.
Shifting here as well would add a second, silent day of lag.

Warm-up and NaN rules
---------------------
An asset can be sized at T only if its window holds ``lookback`` finite
returns; otherwise its weight is 0 that day. With all-finite returns rows
0 .. lookback-2 are zero; when row 0 is the ``pct_change`` NaN the first
``lookback`` rows are zero. NaN in the signal / raw-weight frame counts as 0.
Unused columns with NaN returns never poison a row (only the active, sizable
columns enter the quadratic form).

The module never outputs inf or NaN: a zero or non-finite vol (constant price,
exactly offsetting columns) gives weight 0 for that asset or row.

Name overlap
------------
``backtest.families`` also exports a ``vol_target_weights``. That one is the
single-asset SPY builder with a 20-day vol window (``run_candidate_survey``
uses it). The function here is different: a 60-day rolling *portfolio*
covariance, multi-asset, with shorts. Modules that import both must alias one.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Daily vols at or below this are treated as zero (weight 0, never a division).
_MIN_DAILY_VOL = 1e-12
_TRADING_DAYS = 252
# Relative haircut that keeps sum|w| <= gross_cap after float rescaling.
_CAP_HAIRCUT = 1e-12


def _check_params(
    *,
    lookback: int,
    target_vol: float | None = None,
    gross_cap: float | None = None,
) -> None:
    if lookback < 2:
        raise ValueError(f"lookback must be >= 2, got {lookback}")
    if target_vol is not None and not (math.isfinite(target_vol) and target_vol > 0):
        raise ValueError(f"target_vol must be finite and > 0, got {target_vol}")
    if gross_cap is not None and not (math.isfinite(gross_cap) and gross_cap > 0):
        raise ValueError(f"gross_cap must be finite and > 0, got {gross_cap}")


def _check_alignment(weights: pd.DataFrame, asset_returns: pd.DataFrame) -> None:
    """Raise unless the frames line up in a way that rules out lookahead."""
    idx = asset_returns.index
    if not weights.index.equals(idx):
        raise ValueError("weights index must equal asset_returns index")
    if not idx.is_unique or not idx.is_monotonic_increasing:
        raise ValueError("index must be unique and increasing")
    missing = [c for c in weights.columns if c not in asset_returns.columns]
    if missing:
        raise ValueError(f"columns missing from asset_returns: {missing}")


def _prepare(weights: pd.DataFrame, asset_returns: pd.DataFrame):
    """Return (W, R) float arrays; R is restricted to the weight columns.

    W has NaN replaced by 0. R keeps its NaN (they decide which assets are
    sizable at each row).
    """
    _check_alignment(weights, asset_returns)
    w = weights.to_numpy(dtype=float, copy=True)
    if np.isinf(w).any():
        raise ValueError("weights must not contain inf")
    w[np.isnan(w)] = 0.0
    r = asset_returns[list(weights.columns)].to_numpy(dtype=float)
    return w, r


def inverse_vol_weights(
    signals: pd.DataFrame,
    asset_returns: pd.DataFrame,
    *,
    lookback: int = 60,
) -> pd.DataFrame:
    """Equal-risk weights from long/flat/short signals.

    ``signals`` are in {-1, 0, 1} (NaN counts as 0; any other value raises
    ``ValueError``). The weight is ``signal / vol_i`` with ``vol_i`` the
    ``lookback``-day sample std (ddof=1) of asset i's returns ending at T,
    normalised so ``sum(|w|) = 1`` on rows with at least one sizable signal.
    Rows where no signaled asset can be sized (warm-up, zero vol, no signal)
    are all zero.

    The output has gross 1 up to float rounding, so it is NOT safe against a
    gross cap on its own: pass it through ``vol_target_weights``, which
    enforces the cap exactly.
    """
    _check_params(lookback=lookback)
    sig, rets = _prepare(signals, asset_returns)
    if not np.isin(sig, (-1.0, 0.0, 1.0)).all():
        raise ValueError("signals must be in {-1, 0, 1}")

    out = np.zeros_like(sig)
    for t in range(lookback - 1, len(sig)):
        active = np.flatnonzero(sig[t] != 0)
        if active.size == 0:
            continue
        window = rets[t - lookback + 1 : t + 1][:, active]
        ok = np.isfinite(window).all(axis=0)
        if not ok.any():
            continue
        cols = active[ok]
        vol = window[:, ok].std(axis=0, ddof=1)
        good = np.isfinite(vol) & (vol > _MIN_DAILY_VOL)
        if not good.any():
            continue
        cols = cols[good]
        raw = sig[t, cols] / vol[good]
        out[t, cols] = raw / np.abs(raw).sum()
    return pd.DataFrame(out, index=signals.index, columns=signals.columns)


def vol_target_weights(
    raw_weights: pd.DataFrame,
    asset_returns: pd.DataFrame,
    *,
    target_vol: float = 0.10,
    lookback: int = 60,
    gross_cap: float = 1.0,
) -> pd.DataFrame:
    """Scale raw weights to a target annual vol, then enforce the gross cap.

    ``scale = target_vol / sqrt(w' S w * 252)`` with S the ``lookback``-day
    sample covariance ending at T. ``w' S w`` is computed as the ddof=1 sample
    variance of the window's portfolio return series ``R_window @ w``: this is
    algebraically the same quantity, never inverts S, and is always >= 0 (a
    singular S, identical columns or more assets than days, is fine). No
    shrinkage is applied.

    The active set is the columns with raw weight != 0 (NaN counts as 0).
    Active columns that cannot be sized at T (fewer than ``lookback`` finite
    returns) get weight 0 and drop out of the quadratic form. A row whose
    portfolio daily vol is not finite or <= ``_MIN_DAILY_VOL`` is all zero.

    If ``sum(|w|) > gross_cap`` after scaling the row is rescaled to the cap
    (signs and proportions kept) and given a tiny relative haircut, so the
    output satisfies ``sum(|w|) <= gross_cap`` exactly, with no tolerance.
    There is no per-column clipping. Rows inside the warm-up window are 0.

    Not the same function as ``backtest.families.vol_target_weights`` (20-day
    single-asset SPY builder); see the module docstring.
    """
    _check_params(lookback=lookback, target_vol=target_vol, gross_cap=gross_cap)
    raw, rets = _prepare(raw_weights, asset_returns)

    out = np.zeros_like(raw)
    for t in range(lookback - 1, len(raw)):
        active = np.flatnonzero(raw[t] != 0)
        if active.size == 0:
            continue
        window = rets[t - lookback + 1 : t + 1][:, active]
        ok = np.isfinite(window).all(axis=0)
        if not ok.any():
            continue
        cols = active[ok]
        w = raw[t, cols]
        port = window[:, ok] @ w
        daily_vol = float(np.std(port, ddof=1))
        if not math.isfinite(daily_vol) or daily_vol <= _MIN_DAILY_VOL:
            continue
        w = w * (target_vol / (daily_vol * math.sqrt(_TRADING_DAYS)))
        gross = float(np.abs(w).sum())
        if gross > gross_cap:
            w = w * (gross_cap / gross)
            while float(np.abs(w).sum()) > gross_cap:
                w = w * (1.0 - _CAP_HAIRCUT)
        out[t, cols] = w
    return pd.DataFrame(out, index=raw_weights.index, columns=raw_weights.columns)


def benchmark_weights(
    asset_returns: pd.DataFrame,
    *,
    symbol: str = "SPY",
    target_vol: float = 0.10,
    lookback: int = 60,
    gross_cap: float = 1.0,
) -> pd.DataFrame:
    """The benchmark: ``symbol`` alone through the candidates' own mechanism.

    Raw weight 1.0 on ``symbol`` and 0 elsewhere, passed through
    ``vol_target_weights`` with the same target vol, lookback and gross cap
    (spec 5.2 criterion 2). Returns every column of ``asset_returns``; all
    columns other than ``symbol`` are 0.
    """
    if symbol not in asset_returns.columns:
        raise ValueError(f"symbol {symbol!r} not in asset_returns columns")
    raw = pd.DataFrame(0.0, index=asset_returns.index, columns=asset_returns.columns)
    raw[symbol] = 1.0
    return vol_target_weights(
        raw,
        asset_returns,
        target_vol=target_vol,
        lookback=lookback,
        gross_cap=gross_cap,
    )
