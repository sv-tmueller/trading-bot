"""Tests for the weighted (multi-asset target-weight) extension of
simulate_from_signal in backtest/regime.py.

The binary single-asset path (signature: vehicle_df + is_bullish_close_t) MUST
remain byte-for-byte identical — that is covered by the existing
tests/test_simulate_from_signal.py golden tests, which still run unchanged.

This file adds:
1. backward-compat: a one-column 0/1 target-weight frame reproduces the binary
   result exactly (it dispatches to the untouched binary loop).
2. a 2-asset 50/50 frame produces the expected blended return.
3. next-open fill: a known weight-change date fills at the NEXT open.

All offline / synthetic — no network.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest.regime import simulate_from_signal


def _make_df(prices_open: list[float], prices_close: list[float],
             start: str = "2023-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(prices_open))
    return pd.DataFrame({"Open": prices_open, "Close": prices_close}, index=idx)


# ---------------------------------------------------------------------------
# 1. Backward-compat: one-column 0/1 weights == binary result (exact)
# ---------------------------------------------------------------------------

def test_one_column_binary_weights_reproduce_binary_path():
    """A single-column {0,1} weight frame == the old binary call, to 1e-9.

    The one-column 0/1 case must dispatch to the existing binary loop (int
    share truncation, transition-only trades), so the equity curve matches the
    legacy result exactly, not approximately.
    """
    prices = [100.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
    vehicle = _make_df(prices, prices)

    closes = pd.Series(prices, index=vehicle.index)
    sma = closes.rolling(3).mean()
    is_bullish = (closes > sma).fillna(False)

    # Legacy binary call
    binary = simulate_from_signal(
        vehicle_df=vehicle,
        is_bullish_close_t=is_bullish,
        starting_cash=10_000.0,
        slippage_bps=5,
        commission_bps=5,
    )

    # Same signal expressed as a one-column 0/1 weight frame
    weights = pd.DataFrame({"VEH": is_bullish.astype(float)}, index=vehicle.index)
    weighted = simulate_from_signal(
        target_weights=weights,
        asset_px={"VEH": vehicle},
        starting_cash=10_000.0,
        slippage_bps=5,
        commission_bps=5,
    )

    assert weighted["ending_equity"] == pytest.approx(binary["ending_equity"], rel=1e-9)
    assert weighted["total_return"] == pytest.approx(binary["total_return"], rel=1e-9)
    assert weighted["max_drawdown"] == pytest.approx(binary["max_drawdown"], rel=1e-9)
    assert weighted["trade_count"] == binary["trade_count"]
    # Equity curves coincide point-for-point
    pd.testing.assert_series_equal(
        weighted["equity_curve"], binary["equity_curve"], rtol=1e-9, check_names=False
    )


# ---------------------------------------------------------------------------
# 2. Two-asset 50/50 blended return
# ---------------------------------------------------------------------------

def test_two_asset_fifty_fifty_blended_return():
    """Constant 50/50 over two assets = buy once at T+1 open, hold to end.

    Both assets are flat at 100 until day 1 close, then asset A rises to 120 and
    asset B to 110 by the last day. Weights are 0.5/0.5 from day 0 (close-T),
    shifted to execute at the day-1 open (both still 100). With transition-only
    trading the portfolio is bought once and held:

        end_value ≈ start * (0.5 * (120/100) + 0.5 * (110/100))  net of entry cost
                  ≈ start * (0.60 + 0.55) = start * 1.15   (gross of cost)

    Costs: a single entry per asset at 0.05% slippage + 0.05% commission. With a
    tiny cost the blended return sits a hair below +15%.
    """
    n = 6
    a_open = [100.0] * n
    a_close = [100.0, 100.0, 105.0, 110.0, 115.0, 120.0]
    b_open = [100.0] * n
    b_close = [100.0, 100.0, 102.5, 105.0, 107.5, 110.0]

    df_a = _make_df(a_open, a_close)
    df_b = _make_df(b_open, b_close)

    weights = pd.DataFrame(
        {"A": [0.5] * n, "B": [0.5] * n}, index=df_a.index
    )

    result = simulate_from_signal(
        target_weights=weights,
        asset_px={"A": df_a, "B": df_b},
        starting_cash=10_000.0,
        slippage_bps=5,
        commission_bps=5,
    )

    # Gross blended return is +15%; costs (one entry per leg) shave a few bps.
    # Entry execution price = open * (1 + 5bps) and commission another 5bps,
    # so each leg is bought ~0.10% above its 100 open -> blended ~+14.85%.
    assert result["total_return"] == pytest.approx(0.15, abs=0.004), (
        f"expected ~+15% blended, got {result['total_return']:.4%}"
    )
    # Sanity: ending equity above start, curve present
    assert result["ending_equity"] > 11_400.0
    assert isinstance(result["equity_curve"], pd.Series)


def test_two_asset_equal_weight_below_full_allocation_is_cash_remainder():
    """Weights that sum to < 1 leave the remainder in cash (no leverage)."""
    n = 6
    a = _make_df([100.0] * n, [100.0, 100.0, 110.0, 120.0, 130.0, 140.0])
    b = _make_df([100.0] * n, [100.0, 100.0, 110.0, 120.0, 130.0, 140.0])
    # 0.3 + 0.3 = 0.6 invested, 0.4 cash
    weights = pd.DataFrame({"A": [0.3] * n, "B": [0.3] * n}, index=a.index)

    result = simulate_from_signal(
        target_weights=weights,
        asset_px={"A": a, "B": b},
        starting_cash=10_000.0,
        slippage_bps=0,
        commission_bps=0,
    )
    # 60% invested in assets that go 100 -> 140 (+40%); 40% in cash (0%).
    # blended = 0.6 * 1.40 + 0.4 * 1.0 = 0.84 + 0.40 = 1.24 -> +24%
    assert result["total_return"] == pytest.approx(0.24, abs=0.005)


# ---------------------------------------------------------------------------
# 3. Next-open fill for the weighted path
# ---------------------------------------------------------------------------

def test_weighted_signal_fills_at_next_open():
    """A weight that turns on at close-T must fill at the T+1 OPEN, not T close.

    Asset opens are distinct from closes so the fill price is identifiable.
    Weight is 0 (flat) for days 0-1, then 1.0 from day 2 (close-T) onward.
    The shift means the first fill is at day 3's open. Day-3 open is 200; if the
    fill leaked to day-2 (open 150) the ending equity would differ.
    """
    opens = [100.0, 120.0, 150.0, 200.0, 210.0, 220.0]
    closes = [110.0, 130.0, 160.0, 205.0, 215.0, 225.0]
    df = _make_df(opens, closes)

    # weight turns on at close of day 2 (index position 2)
    w = [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    weights = pd.DataFrame({"X": w}, index=df.index)

    result = simulate_from_signal(
        target_weights=weights,
        asset_px={"X": df},
        starting_cash=10_000.0,
        slippage_bps=0,
        commission_bps=0,
    )

    # Fill at day-3 open = 200. Held to day-5 close = 225.
    # qty = floor(10000 / 200) = 50 shares; cost = 50*200 = 10000, cash = 0.
    # ending equity = 50 * 225 = 11250.
    assert result["trade_count"] >= 1
    first_trade = result["trades"][0]
    assert first_trade["entry_price"] == pytest.approx(200.0, abs=1e-9), (
        f"fill must be at day-3 open (200), got {first_trade['entry_price']}"
    )
    assert result["ending_equity"] == pytest.approx(11_250.0, abs=1.0)


# ---------------------------------------------------------------------------
# 4. Partial-trim lot-accounting: regression guard for known limitation
# ---------------------------------------------------------------------------

def test_partial_trim_carries_original_lot_anchor():
    """Pin the known partial-trim accounting limitation in _simulate_weighted.

    KNOWN LIMITATION (do not silently change): when a strictly-positive weight
    is *reduced* (not closed to zero), the emitted Trade carries the ORIGINAL
    entry_date and entry_price from when the position was first opened.  The
    anchor is reset only on a full exit (shares -> ~0).  Adding shares to an
    open lot (weight rises) does NOT create a new anchor or blend the basis.

    Concretely: weight 0.5 -> 0.7 (add) -> 0.4 (partial trim) over a rising
    price path (100 -> 110 -> 120) produces a trim Trade with:
      entry_date = original open date (not the add date)
      entry_price = original open price (not the add price or average cost)

    This overstates holding period for tax classification (all trimmed shares
    look as old as the first buy) and understates cost basis for the trimmed
    lot (using original price 100 rather than a blended ~104 FIFO basis).
    Both effects flatter long-horizon after-tax results for continuous-weight
    strategies by making gains appear longer-held and basis appear lower.

    This test encodes ACTUAL behavior so any change to the lot-accounting
    logic is flagged immediately.
    """
    idx = pd.bdate_range("2023-01-02", periods=7)
    # Rising prices: 100 on days 0-1, 110 on days 2-3, 120 on days 4-6
    px = [100.0, 100.0, 110.0, 110.0, 120.0, 120.0, 120.0]
    df = pd.DataFrame({"Open": px, "Close": px}, index=idx)

    # Weight path (close-T -> executes at T+1 open):
    #   day 0 close 0.5 -> BUY at day 1 open (price 100)  [anchor set: 2023-01-03, 100]
    #   day 2 close 0.7 -> ADD  at day 3 open (price 110)  [anchor NOT updated]
    #   day 4 close 0.4 -> TRIM at day 5 open (price 120)  [anchor unchanged: 2023-01-03, 100]
    weights = pd.DataFrame(
        {"SPY": [0.5, 0.5, 0.7, 0.7, 0.4, 0.4, 0.4]},
        index=idx,
    )

    result = simulate_from_signal(
        target_weights=weights,
        asset_px={"SPY": df},
        starting_cash=10_000.0,
        slippage_bps=0,
        commission_bps=0,
    )

    # There must be at least one intra-run rebalance trade (the trim)
    rebalance_trades = [t for t in result["trades"] if t["exit_reason"] == "rebalance"]
    assert len(rebalance_trades) >= 1, "expected at least one rebalance (trim) trade"

    trim = rebalance_trades[0]

    # The trim trade must carry the ORIGINAL entry date (day 1 open = 2023-01-03),
    # not the add date (day 3 open = 2023-01-05).
    original_entry_date = pd.Timestamp("2023-01-03")
    assert trim["entry_date"] == original_entry_date, (
        f"partial trim should carry original entry_date {original_entry_date.date()}, "
        f"got {trim['entry_date'].date()} -- lot-accounting limitation changed"
    )

    # The trim trade must carry the ORIGINAL entry price (100.0, not the add
    # price of 110.0 or any blended average).
    assert trim["entry_price"] == pytest.approx(100.0, abs=1e-9), (
        f"partial trim should carry original entry_price 100.0, "
        f"got {trim['entry_price']:.4f} -- lot-accounting limitation changed"
    )
