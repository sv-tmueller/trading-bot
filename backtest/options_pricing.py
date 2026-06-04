"""Black-Scholes pricing, greeks, and implied-vol solve — pure, I/O-free.

Free-tier Alpaca options data carries no greeks or implied volatility (see
`docs/research/mvp2-alpaca-options-data-spike.md`), so the PCS-RIV backtest
computes them here. Kept dependency-light (stdlib `math` only — no scipy) so
the same module can serve the live evaluation layer later.

Conventions:
- `t` is time to expiry in years; `r` the continuous risk-free rate; `q` the
  continuous dividend yield (default 0). `sigma` is annualised volatility.
- `vega` is per 1.00 change in vol (divide by 100 for per-1%); `theta` is per
  year (divide by 365 for per-day). Greeks use the standard Black-Scholes-Merton
  formulae with continuous dividend yield.
"""
from __future__ import annotations

import math
from typing import Literal

Kind = Literal["call", "put"]

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _intrinsic(spot: float, strike: float, r: float, t: float, kind: Kind) -> float:
    """Value at expiry (t<=0) or in the degenerate sigma<=0 case."""
    if kind == "call":
        return max(spot - strike * math.exp(-r * t), 0.0)
    return max(strike * math.exp(-r * t) - spot, 0.0)


def _d1_d2(*, spot: float, strike: float, t: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    vol_sqrt_t = sigma * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def bs_price(
    *,
    spot: float,
    strike: float,
    t: float,
    r: float,
    sigma: float,
    kind: Kind,
    q: float = 0.0,
) -> float:
    """Black-Scholes-Merton price of a European call or put."""
    if kind not in ("call", "put"):
        raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")
    if t <= 0.0 or sigma <= 0.0:
        return _intrinsic(spot, strike, r, max(t, 0.0), kind)

    d1, d2 = _d1_d2(spot=spot, strike=strike, t=t, r=r, sigma=sigma, q=q)
    disc_r = math.exp(-r * t)
    disc_q = math.exp(-q * t)
    if kind == "call":
        return spot * disc_q * _norm_cdf(d1) - strike * disc_r * _norm_cdf(d2)
    return strike * disc_r * _norm_cdf(-d2) - spot * disc_q * _norm_cdf(-d1)


def bs_greeks(
    *,
    spot: float,
    strike: float,
    t: float,
    r: float,
    sigma: float,
    kind: Kind,
    q: float = 0.0,
) -> dict[str, float]:
    """Return {delta, gamma, theta, vega}. vega per 1.00 vol; theta per year."""
    if kind not in ("call", "put"):
        raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")
    if t <= 0.0 or sigma <= 0.0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    d1, d2 = _d1_d2(spot=spot, strike=strike, t=t, r=r, sigma=sigma, q=q)
    disc_r = math.exp(-r * t)
    disc_q = math.exp(-q * t)
    pdf_d1 = _norm_pdf(d1)
    sqrt_t = math.sqrt(t)

    gamma = disc_q * pdf_d1 / (spot * sigma * sqrt_t)
    vega = spot * disc_q * pdf_d1 * sqrt_t
    common_theta = -(spot * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
    if kind == "call":
        delta = disc_q * _norm_cdf(d1)
        theta = common_theta - r * strike * disc_r * _norm_cdf(d2) + q * spot * disc_q * _norm_cdf(d1)
    else:
        delta = -disc_q * _norm_cdf(-d1)
        theta = common_theta + r * strike * disc_r * _norm_cdf(-d2) - q * spot * disc_q * _norm_cdf(-d1)
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def implied_vol(
    *,
    price: float,
    spot: float,
    strike: float,
    t: float,
    r: float,
    kind: Kind,
    q: float = 0.0,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float:
    """Solve for the volatility that reproduces `price`. NaN if no real solution.

    Newton-Raphson seeded at sigma=0.5, with a bisection fallback over
    [1e-6, 5.0] when Newton steps out of bounds or stalls.
    """
    if kind not in ("call", "put"):
        raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")
    if t <= 0.0:
        return math.nan
    # A price below intrinsic (or above the underlying) has no real implied vol.
    intrinsic = _intrinsic(spot, strike, r, t, kind)
    if price < intrinsic - 1e-12:
        return math.nan

    lo, hi = 1e-6, 5.0
    sigma = 0.5
    for _ in range(max_iter):
        diff = bs_price(spot=spot, strike=strike, t=t, r=r, sigma=sigma, kind=kind, q=q) - price
        if abs(diff) < tol:
            return sigma
        vega = spot * math.exp(-q * t) * _norm_pdf(
            _d1_d2(spot=spot, strike=strike, t=t, r=r, sigma=sigma, q=q)[0]
        ) * math.sqrt(t)
        if vega < 1e-12:
            break
        step = diff / vega
        next_sigma = sigma - step
        if next_sigma <= lo or next_sigma >= hi:
            break
        sigma = next_sigma
    else:
        return math.nan

    # Bisection fallback.
    lo_diff = bs_price(spot=spot, strike=strike, t=t, r=r, sigma=lo, kind=kind, q=q) - price
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        mid_diff = bs_price(spot=spot, strike=strike, t=t, r=r, sigma=mid, kind=kind, q=q) - price
        if abs(mid_diff) < tol:
            return mid
        if (mid_diff > 0) == (lo_diff > 0):
            lo, lo_diff = mid, mid_diff
        else:
            hi = mid
    return 0.5 * (lo + hi)
