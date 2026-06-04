"""Tests for backtest/options_pricing.py — Black-Scholes price, greeks, IV solve.

Reference values are hand-computed for S=100, K=100, T=1, r=0.05, sigma=0.20, q=0:
    d1 = 0.35, d2 = 0.15
    call = 10.4506, put = 5.5735
    delta_call = N(0.35) = 0.63683, vega = 37.524, gamma = 0.018762,
    theta_call (per year) = -6.4142
"""
from __future__ import annotations

import math

import pytest

from backtest.options_pricing import bs_price, bs_greeks, implied_vol

# Common reference parameters
S, K, T, R, SIG = 100.0, 100.0, 1.0, 0.05, 0.20


def test_call_price_reference():
    assert bs_price(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="call") == pytest.approx(10.4506, abs=0.01)


def test_put_price_reference():
    assert bs_price(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="put") == pytest.approx(5.5735, abs=0.01)


def test_put_call_parity():
    call = bs_price(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="call")
    put = bs_price(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="put")
    # C - P = S - K e^{-rT}   (q = 0)
    assert call - put == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)


def test_call_delta_reference():
    g = bs_greeks(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="call")
    assert g["delta"] == pytest.approx(0.63683, abs=1e-3)


def test_put_delta_reference():
    g = bs_greeks(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="put")
    assert g["delta"] == pytest.approx(-0.36317, abs=1e-3)


def test_vega_gamma_theta_reference():
    g = bs_greeks(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="call")
    assert g["vega"] == pytest.approx(37.524, abs=0.05)      # per 1.00 vol
    assert g["gamma"] == pytest.approx(0.018762, abs=1e-4)
    assert g["theta"] == pytest.approx(-6.4142, abs=0.05)    # per year
    # vega is identical for the put
    gp = bs_greeks(spot=S, strike=K, t=T, r=R, sigma=SIG, kind="put")
    assert gp["vega"] == pytest.approx(g["vega"], abs=1e-9)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("iv", [0.08, 0.20, 0.35, 0.75])
def test_implied_vol_roundtrip(kind, iv):
    price = bs_price(spot=S, strike=105.0, t=0.5, r=R, sigma=iv, kind=kind)
    solved = implied_vol(price=price, spot=S, strike=105.0, t=0.5, r=R, kind=kind)
    assert solved == pytest.approx(iv, abs=1e-4)


def test_call_delta_monotonic_in_spot():
    deltas = [
        bs_greeks(spot=spot, strike=K, t=T, r=R, sigma=SIG, kind="call")["delta"]
        for spot in (80, 90, 100, 110, 120)
    ]
    assert deltas == sorted(deltas)
    assert all(0.0 <= d <= 1.0 for d in deltas)


def test_expiry_returns_intrinsic():
    assert bs_price(spot=120.0, strike=100.0, t=0.0, r=R, sigma=SIG, kind="call") == pytest.approx(20.0)
    assert bs_price(spot=120.0, strike=100.0, t=0.0, r=R, sigma=SIG, kind="put") == pytest.approx(0.0)
    assert bs_price(spot=90.0, strike=100.0, t=0.0, r=R, sigma=SIG, kind="put") == pytest.approx(10.0)


def test_deep_otm_and_itm_sane():
    deep_otm_call = bs_price(spot=50.0, strike=100.0, t=0.25, r=R, sigma=SIG, kind="call")
    assert 0.0 <= deep_otm_call < 0.01
    deep_itm_call = bs_price(spot=150.0, strike=100.0, t=0.25, r=R, sigma=SIG, kind="call")
    assert deep_itm_call == pytest.approx(150.0 - 100.0 * math.exp(-R * 0.25), abs=0.05)


def test_implied_vol_below_intrinsic_is_nan():
    # A price under intrinsic value has no real implied vol.
    intrinsic = 150.0 - 100.0  # deep ITM call, ignoring discounting
    solved = implied_vol(price=intrinsic - 5.0, spot=150.0, strike=100.0, t=0.25, r=R, kind="call")
    assert math.isnan(solved)
