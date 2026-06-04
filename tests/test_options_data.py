"""Tests for backtest/options_data.py — PriceSource interface + both sources.

No live network: ModeledSource is deterministic; RealAlpacaSource is exercised
with its `_get` JSON method patched to return fixtures.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backtest.options_data import (
    OptionQuote,
    ModeledSource,
    RealAlpacaSource,
    compute_iv_rank,
)

# A flat 100-price / 0.20-IV world spanning entry through expiry (~2.5 months).
_DATES = [date(2024, 6, 1) + timedelta(days=i) for i in range(0, 80)]
PRICES = {d: 100.0 for d in _DATES}
IVS = {d: 0.20 for d in _DATES}


def test_compute_iv_rank_midpoint():
    series = {date(2024, 1, 1): 0.10, date(2024, 3, 1): 0.30, date(2024, 6, 1): 0.20}
    # current 0.20 sits halfway between low 0.10 and high 0.30 -> 50
    assert compute_iv_rank(series, on=date(2024, 6, 1), lookback_days=365) == pytest.approx(50.0, abs=1e-6)


def test_compute_iv_rank_extremes_and_missing():
    series = {date(2024, 1, 1): 0.10, date(2024, 6, 1): 0.30}
    assert compute_iv_rank(series, on=date(2024, 6, 1), lookback_days=365) == pytest.approx(100.0)
    assert compute_iv_rank(series, on=date(2023, 1, 1)) is None  # no data in window


def test_modeled_underlying_price():
    src = ModeledSource(PRICES, IVS)
    assert src.underlying_price("SPY", date(2024, 6, 3)) == 100.0
    assert src.underlying_price("SPY", date(2030, 1, 1)) is None


def test_modeled_select_put_spread_picks_target_delta_and_width():
    src = ModeledSource(PRICES, IVS)
    legs = src.select_put_spread("SPY", date(2024, 6, 3), dte_min=30, dte_max=45, short_delta=0.30, width=5.0)
    assert legs is not None
    short, long = legs
    # short put near 0.30 delta (puts have negative delta)
    assert short.delta == pytest.approx(-0.30, abs=0.06)
    # long leg is `width` below the short, same expiry
    assert long.strike == pytest.approx(short.strike - 5.0)
    assert long.expiry == short.expiry
    # both are OTM puts below spot, with sane bid < mid < ask
    for q in (short, long):
        assert q.strike < 100.0
        assert q.bid < q.mid < q.ask
        assert q.mid > 0.0
        assert q.iv == pytest.approx(0.20, abs=1e-6)
    # short put richer than the further-OTM long put -> positive credit at mid
    assert short.mid > long.mid


def test_modeled_mark_legs_decays_to_intrinsic_at_expiry():
    src = ModeledSource(PRICES, IVS)
    legs = src.select_put_spread("SPY", date(2024, 6, 3), dte_min=30, dte_max=45, short_delta=0.30, width=5.0)
    short, long = legs
    # Re-mark on the expiry date: with spot 100 above both strikes, both puts expire worthless.
    marked = src.mark_legs("SPY", short.expiry, short_strike=short.strike, long_strike=long.strike, expiry=short.expiry)
    assert marked is not None
    ms, ml = marked
    assert ms.mid == pytest.approx(0.0, abs=1e-9)
    assert ml.mid == pytest.approx(0.0, abs=1e-9)


def test_real_source_requires_keys():
    with pytest.raises(RuntimeError):
        RealAlpacaSource(key=None, secret=None)


def _put_mark(strike: float, mark: float) -> dict:
    return {"strike": strike, "mark": mark}


def test_real_source_builds_spread_from_marks(monkeypatch):
    # Underlying ~100; supply a put chain via a patched chain fetch.
    on = date(2024, 6, 3)
    expiry = date(2024, 7, 19)
    src = RealAlpacaSource(key="k", secret="s")

    monkeypatch.setattr(src, "underlying_price", lambda symbol, d: 100.0)
    monkeypatch.setattr(src, "_select_expiry", lambda symbol, d, lo, hi: expiry)
    # Marks chosen so deeper-OTM strikes are cheaper (a sane put skew shape).
    chain = [
        _put_mark(99.0, 2.6), _put_mark(98.0, 2.1), _put_mark(97.0, 1.7),
        _put_mark(96.0, 1.35), _put_mark(95.0, 1.05), _put_mark(92.0, 0.45),
    ]
    monkeypatch.setattr(src, "_fetch_put_chain_marks", lambda symbol, d, exp: chain)

    legs = src.select_put_spread("SPY", on, dte_min=30, dte_max=50, short_delta=0.30, width=5.0)
    assert legs is not None
    short, long = legs
    assert short.expiry == expiry
    # Real chains have discrete listed strikes -> long is the nearest available
    # strike to (short - width), below the short leg.
    assert long.strike < short.strike
    assert abs(long.strike - (short.strike - 5.0)) <= 1.0
    # spread is modeled around the mark: bid < mark/mid < ask
    assert short.bid < short.mid < short.ask
    # IV + delta were computed (not the null Alpaca returns)
    assert short.iv > 0.0
    assert -1.0 < short.delta < 0.0
