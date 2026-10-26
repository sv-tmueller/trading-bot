"""Tests for backtest/portfolio.py -- the long/short portfolio simulator.

Hand-built weight, price and cash-return frames with known answers pin the
fill timing (close-T target fills at the T+1 open), the rebalance band, the
long-to-short flip, partial resizes, the NaN-price rule, the gross-cap
validation, borrow / financing / cash-interest accrual, and the trade ledger
shape the German annual-netting tax layer consumes.

All offline and synthetic: no network, no broker, no LLM.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from backtest.portfolio import (
    CostModel,
    PortfolioResult,
    round_trips_per_year,
    simulate_portfolio,
)

START = 100_000.0


def _idx(n: int, start: str = "2023-01-02") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _single(weights, prices, symbol: str = "AAA"):
    """One-asset frames (open == close)."""
    idx = _idx(len(weights))
    w = pd.DataFrame({symbol: np.asarray(weights, dtype=float)}, index=idx)
    c = pd.DataFrame({symbol: np.asarray(prices, dtype=float)}, index=idx)
    return w, c.copy(), c


def _zero_cash(idx) -> pd.Series:
    return pd.Series(0.0, index=idx)


def _run(weights, prices, **kw):
    w, o, c = _single(weights, prices)
    cash = kw.pop("cash_returns", _zero_cash(w.index))
    return simulate_portfolio(w, o, c, cash, **kw)


def test_constant_long_weight_buys_once_and_holds():
    n = 8
    r = _run([0.5] * n, [100.0] * n)
    assert isinstance(r, PortfolioResult)
    # Entries are not ledger rows and nothing closes: no trades at all.
    assert r.trades == []
    # Day 0 never trades (targets fill one day later).
    assert r.held_weights["AAA"].iloc[0] == 0.0
    assert r.held_weights["AAA"].iloc[1:].between(0.49, 0.5).all()
    # Exactly one fill: slippage cost of one 0.5 * equity buy at 5 bps.
    assert r.costs["trading"] == pytest.approx(0.5 * START * 5e-4, rel=0.01)
    assert r.equity.iloc[0] == pytest.approx(START)
    assert r.daily_returns.iloc[0] == pytest.approx(0.0)
    assert not r.daily_returns.isna().any()


def test_flip_long_to_short_closes_and_reopens():
    # Flip is filled at the open of index 3 (price 100); price falls after.
    prices = [100.0, 100.0, 100.0, 100.0, 90.0, 80.0]
    r = _run([0.5, 0.5, -0.5, -0.5, -0.5, -0.5], prices)
    rts = [t for t in r.trades if t["kind"] == "round_trip"]
    assert len(rts) == 1 and rts[0]["side"] == "long"
    assert rts[0]["exit_date"] == r.equity.index[3]
    assert rts[0]["exit_reason"] == "reverse"
    # The short is still open at the end of the data: no forced close-out.
    assert len(r.trades) == 1
    assert r.held_weights["AAA"].iloc[-1] < 0
    # Mark-to-market: equity rises while short and price falls.
    assert r.equity.iloc[-1] > r.equity.iloc[2]


def test_partial_resize_emits_partial_not_round_trip():
    r = _run([0.8, 0.8, 0.4, 0.4, 0.4], [100.0] * 5)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t["kind"] == "partial" and t["side"] == "long"
    assert t["exit_reason"] == "resize"
    # Reduced from ~0.8 to ~0.4 of equity: roughly half the position sold.
    assert t["qty"] == pytest.approx(0.4 * START / 100.0, rel=0.02)
    assert r.held_weights["AAA"].iloc[-1] == pytest.approx(0.4, abs=0.01)
    assert round_trips_per_year(r) == 0.0


def _two_assets(n: int, b_nan_days):
    idx = _idx(n)
    w = pd.DataFrame({"AAA": 0.3, "BBB": 0.3}, index=idx)
    o = pd.DataFrame({"AAA": 100.0, "BBB": 50.0}, index=idx)
    c = o.copy()
    for d in b_nan_days:
        o.iloc[d, 1] = np.nan
        c.iloc[d, 1] = np.nan
    return w, o, c


def test_nan_price_asset_never_traded():
    w, o, c = _two_assets(8, b_nan_days=[0, 1, 2])
    r = simulate_portfolio(w, o, c, _zero_cash(w.index))
    held_b = r.held_weights["BBB"]
    # No B position before its first fully priced day (index 3).
    assert (held_b.iloc[:3] == 0.0).all()
    assert held_b.iloc[3] > 0.25
    assert not r.equity.isna().any()
    assert not r.held_weights.isna().any().any()
    assert not r.gross_exposure.isna().any()


def test_nan_price_gap_in_the_middle_is_not_a_trade():
    w, o, c = _two_assets(9, b_nan_days=[5])
    r = simulate_portfolio(w, o, c, _zero_cash(w.index))
    # The held asset is kept and valued at its last finite close.
    assert r.trades == []
    assert not r.equity.isna().any()
    assert not r.held_weights.isna().any().any()
    held_b = r.held_weights["BBB"]
    assert held_b.iloc[5] == pytest.approx(held_b.iloc[4], abs=1e-9)


def test_target_column_without_price_column_raises():
    w, o, c = _two_assets(5, b_nan_days=[])
    with pytest.raises(ValueError):
        simulate_portfolio(
            w, o.drop(columns="BBB"), c.drop(columns="BBB"), _zero_cash(w.index)
        )


def test_nan_target_counts_as_zero():
    w, o, c = _two_assets(6, b_nan_days=[])
    w["BBB"] = np.nan
    r = simulate_portfolio(w, o, c, _zero_cash(w.index))
    assert (r.held_weights["BBB"] == 0.0).all()
    assert r.held_weights["AAA"].iloc[-1] > 0.25


def test_gross_cap_violation_raises():
    idx = _idx(4)
    w = pd.DataFrame({"AAA": 0.6, "BBB": -0.6}, index=idx)  # sum |w| = 1.2
    px = pd.DataFrame({"AAA": 100.0, "BBB": 50.0}, index=idx)
    with pytest.raises(ValueError):
        simulate_portfolio(w, px, px, _zero_cash(idx))


def test_single_column_above_cap_raises():
    w, o, c = _single([1.2] * 4, [100.0] * 4)
    with pytest.raises(ValueError):
        simulate_portfolio(w, o, c, _zero_cash(w.index))


def test_cap_tolerance_accepts_float_noise_at_the_cap():
    w, o, c = _single([1.0000000000000002] * 4, [100.0] * 4)
    r = simulate_portfolio(w, o, c, _zero_cash(w.index))
    assert not r.equity.isna().any()


def test_higher_gross_cap_allows_single_column_up_to_cap_and_pays_financing():
    n = 253
    r = _run([1.5] * n, [100.0] * n, gross_cap=1.5)
    # Borrowed 0.5 * equity from day 1 to day 252 at 100 bps / 252 per day.
    expected = 252 * 0.5 * START * (0.01 / 252)
    assert r.costs["financing"] == pytest.approx(expected, rel=0.05)
    assert r.gross_exposure.iloc[-1] == pytest.approx(1.5, abs=0.02)
    with pytest.raises(ValueError):
        _run([1.6] * 5, [100.0] * 5, gross_cap=1.5)


def test_borrow_cost_accrues_on_shorts():
    n = 253
    r = _run([-0.5] * n, [100.0] * n, costs=CostModel(borrow_bps_annual=252.0))
    # Short from day 1 to day 252: 252 accrual days at 252 bps / 252.
    assert r.costs["borrow"] == pytest.approx(0.5 * START * 0.0252, rel=0.05)
    assert r.costs["financing"] == pytest.approx(0.0, abs=1e-6)
    assert (r.held_weights["AAA"].iloc[1:] < 0).all()


def test_positive_cash_earns_cash_returns():
    n = 10
    cash = pd.Series(0.0001, index=_idx(n))
    r = _run([0.0] * n, [100.0] * n, cash_returns=cash)
    assert r.trades == []
    assert r.equity.iloc[-1] == pytest.approx(START * 1.0001 ** n, rel=1e-9)
    assert r.costs["cash_interest"] == pytest.approx(r.equity.iloc[-1] - START)


def test_short_proceeds_earn_no_cash_interest():
    # Retail model: short-sale proceeds sit in cash but earn nothing. Only the
    # equity (cash net of short notional) earns cash_returns.
    n = 253
    rate = 0.0002
    r = _run(
        [-0.5] * n,
        [100.0] * n,
        cash_returns=pd.Series(rate, index=_idx(n)),
        costs=CostModel(borrow_bps_annual=0.0),
    )
    assert r.costs["cash_interest"] == pytest.approx(
        START * ((1 + rate) ** n - 1), rel=0.01
    )
    assert r.costs["financing"] == pytest.approx(0.0, abs=1e-6)


def test_long_book_cash_interest_is_interest_on_cash():
    # Long-only: cash after accrual is equity minus long value, so dividing by
    # (1 + rate) recovers the cash balance that earned the interest.
    n = 253
    rate = 0.0002
    r = _run(
        [0.5] * n,
        [100.0] * n,
        cash_returns=pd.Series(rate, index=_idx(n)),
    )
    expected = (r.equity * (1 - r.held_weights["AAA"]) * rate / (1 + rate)).sum()
    assert r.costs["cash_interest"] == pytest.approx(expected, rel=1e-9)


def test_cash_interest_floors_at_zero_when_shorts_exceed_cash():
    # Long 1.2 / short 0.3 at gross_cap 1.5 leaves cash at +0.1 of equity, less
    # than the 0.3 short notional: the interest base floors at 0, so interest
    # accrues only on day 0 (before any position) and nothing is financed.
    n = 20
    rate = 0.0002
    idx = _idx(n)
    w = pd.DataFrame({"AAA": 1.2, "BBB": -0.3}, index=idx)
    px = pd.DataFrame({"AAA": 100.0, "BBB": 100.0}, index=idx)
    r = simulate_portfolio(
        w, px, px, pd.Series(rate, index=idx), gross_cap=1.5
    )
    assert r.costs["cash_interest"] == pytest.approx(START * rate, rel=1e-9)
    assert r.costs["financing"] == pytest.approx(0.0, abs=1e-6)


def test_no_leverage_at_one_x_means_no_financing():
    n = 40
    prices = 100.0 * 1.001 ** np.arange(n)
    r = _run([1.0] * n, prices, gross_cap=1.0)
    assert r.costs["financing"] == pytest.approx(0.0, abs=1e-6)
    assert r.trades == []


def test_swap_between_assets_never_levers_a_fully_invested_book():
    n = 8
    idx = _idx(n)
    w = pd.DataFrame({"AAA": 1.0, "BBB": 0.0}, index=idx)
    w.iloc[3:, :] = [0.0, 1.0]
    px = pd.DataFrame({"AAA": 100.0, "BBB": 50.0}, index=idx)
    r = simulate_portfolio(w, px, px, _zero_cash(idx))
    # Reductions run before increases, so the buy is funded by the sale.
    assert r.costs["financing"] == pytest.approx(0.0, abs=1e-6)
    assert r.gross_exposure.max() <= 1.0 + 1e-9
    rts = [t for t in r.trades if t["kind"] == "round_trip"]
    assert len(rts) == 1 and rts[0]["symbol"] == "AAA"
    assert rts[0]["exit_reason"] == "close"


def test_band_ignores_small_change_but_closes_to_zero():
    # 0.50 -> 0.51 stays inside the 0.02 band: still exactly one fill.
    r = _run([0.5, 0.5, 0.51, 0.51, 0.51], [100.0] * 5)
    assert r.trades == []
    assert r.costs["trading"] == pytest.approx(0.5 * START * 5e-4, rel=0.01)
    # 0.01 -> 0 is inside the band but crosses zero: the position closes.
    r2 = _run([0.01, 0.01, 0.0, 0.0, 0.0], [100.0] * 5)
    assert len(r2.trades) == 1
    assert r2.trades[0]["kind"] == "round_trip"
    assert r2.trades[0]["exit_reason"] == "close"
    assert r2.held_weights["AAA"].iloc[-1] == 0.0


def test_move_outside_band_trades_to_exact_target():
    r = _run([0.5, 0.5, 0.6, 0.6, 0.6], [100.0] * 5)
    assert r.trades == []  # an increase is not a ledger row
    assert r.held_weights["AAA"].iloc[-1] == pytest.approx(0.6, abs=0.005)


def test_trades_feed_annual_netting_tax():
    from backtest.tax import DE_FLAT_RATE, apply_annual_netting_tax

    # Gentle drift keeps held weights inside the band, so the only trades are
    # the planned trim (partial) and the planned exit (round trip).
    prices = [100.0, 100.0, 100.5, 101.0, 101.0, 101.5, 101.5, 101.5]
    r = _run([0.8, 0.8, 0.8, 0.4, 0.4, 0.0, 0.0, 0.0], prices)
    kinds = sorted(t["kind"] for t in r.trades)
    assert kinds == ["partial", "round_trip"]
    assert all(t["pnl"] > 0 for t in r.trades)
    after = apply_annual_netting_tax(r.trades, r.equity)
    total_pnl = sum(t["pnl"] for t in r.trades)  # all exits in one year
    assert after.iloc[-1] < r.equity.iloc[-1]
    assert r.equity.iloc[-1] - after.iloc[-1] == pytest.approx(
        DE_FLAT_RATE * total_pnl
    )


def test_adding_to_a_position_blends_entry_price_and_keeps_entry_date():
    prices = [100.0, 100.0, 100.0, 120.0, 120.0, 120.0]
    r = _run([0.4, 0.4, 0.8, 0.8, 0.0, 0.0], prices)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t["kind"] == "round_trip" and t["exit_reason"] == "close"
    assert t["entry_date"] == r.equity.index[1]
    slip = 5e-4
    q1 = 0.4 * START / (100.0 * (1 + slip))
    cash = START - q1 * 100.0 * (1 + slip)
    equity_open = cash + q1 * 120.0
    dq = (0.8 * equity_open - q1 * 120.0) / (120.0 * (1 + slip))
    px1, px2 = 100.0 * (1 + slip), 120.0 * (1 + slip)
    blended = (q1 * px1 + dq * px2) / (q1 + dq)
    assert t["entry_price"] == pytest.approx(blended, rel=1e-9)
    assert t["qty"] == pytest.approx(q1 + dq, rel=1e-9)
    assert t["exit_price"] == pytest.approx(120.0 * (1 - slip))
    assert t["pnl"] == pytest.approx((t["exit_price"] - t["entry_price"]) * t["qty"])
    assert t["return_pct"] == pytest.approx(t["pnl"] / (t["entry_price"] * t["qty"]))


def test_short_pnl_is_entry_minus_exit():
    prices = [100.0, 100.0, 100.0, 90.0, 90.0]
    r = _run([-0.5, -0.5, 0.0, 0.0, 0.0], prices)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t["side"] == "short" and t["kind"] == "round_trip"
    assert t["pnl"] == pytest.approx((t["entry_price"] - t["exit_price"]) * t["qty"])
    assert t["pnl"] > 0


def test_trade_dicts_carry_regime_trade_fields_and_allowed_values():
    from backtest import regime

    weights = [0.8, 0.8, 0.4, 0.4, -0.5, -0.5, -0.5, 0.0, 0.0]
    prices = [100, 100, 101, 102, 103, 104, 100, 99, 99]
    r = _run(weights, prices)
    assert {t["kind"] for t in r.trades} == {"partial", "round_trip"}
    required = {f.name for f in dataclasses.fields(regime.Trade)}
    required |= {"symbol", "side", "kind"}
    for t in r.trades:
        assert required <= set(t)
        assert t["side"] in {"long", "short"}
        assert t["kind"] in {"round_trip", "partial"}
        assert t["symbol"] == "AAA"
        assert t["qty"] > 0 and isinstance(t["qty"], float)


def test_round_trips_per_year_counts_round_trips_over_calendar_span():
    n = 12
    idx = _idx(n)
    w = pd.DataFrame({"AAA": 0.0, "BBB": 0.0}, index=idx)
    w.iloc[1:4, 0] = 0.4
    w.iloc[2:6, 1] = 0.4
    px = pd.DataFrame({"AAA": 100.0, "BBB": 50.0}, index=idx)
    r = simulate_portfolio(w, px, px, _zero_cash(idx))
    assert [t["kind"] for t in r.trades] == ["round_trip", "round_trip"]
    years = (idx[-1] - idx[0]).days / 365.25
    assert round_trips_per_year(r) == pytest.approx(2 / years)


def test_round_trips_per_year_guards_zero_span():
    r = _run([0.5], [100.0])
    assert round_trips_per_year(r) == 0.0


def test_costs_dict_has_documented_keys():
    r = _run([0.5] * 4, [100.0] * 4)
    assert set(r.costs) == {"trading", "borrow", "financing", "cash_interest"}


def test_cost_model_is_frozen_with_documented_defaults():
    cm = CostModel()
    assert (cm.slippage_bps, cm.commission_bps) == (5.0, 0.0)
    assert (cm.borrow_bps_annual, cm.financing_spread_bps_annual) == (50.0, 100.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cm.slippage_bps = 1.0  # type: ignore[misc]
