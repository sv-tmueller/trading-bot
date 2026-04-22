from __future__ import annotations

import pytest
from tools.portfolio import get_portfolio_stats, get_open_positions_with_prices
from tools.database import insert_trade


def test_portfolio_stats_no_trades(db_conn):
    stats = get_portfolio_stats(db_conn, portfolio_value=100_000)
    assert stats["open_count"] == 0
    assert stats["deployed_pct"] == 0.0
    assert stats["daily_pnl_pct"] == 0.0


def test_portfolio_stats_with_open_trade(db_conn):
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    stats = get_portfolio_stats(db_conn, portfolio_value=100_000, current_prices={"AMD": 155.0})
    assert stats["open_count"] == 1
    assert stats["unrealized_pnl"] == pytest.approx(500.0)


def test_open_positions_with_prices(db_conn):
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    positions = get_open_positions_with_prices(db_conn, current_prices={"AMD": 155.0})
    assert len(positions) == 1
    assert positions[0]["unrealized_pnl"] == pytest.approx(500.0)
    assert positions[0]["pct_to_stop"] == pytest.approx((155.0 - 145.5) / 155.0, rel=0.01)
    assert positions[0]["pct_to_target"] == pytest.approx((159.0 - 155.0) / 155.0, rel=0.01)


def test_deployed_pct_computed_correctly(db_conn):
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 100.0,
        "shares": 100,
        "stop_loss": 95.0,
        "take_profit": 110.0,
    })
    # deployed = 100 * 100 = 10_000 / 100_000 = 0.10
    stats = get_portfolio_stats(db_conn, portfolio_value=100_000, current_prices={"AMD": 100.0})
    assert stats["deployed_pct"] == pytest.approx(0.10)
