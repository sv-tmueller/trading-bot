from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from monitor.position_monitor import evaluate_position, MonitorAction, run_monitor


def test_stop_loss_triggered():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-20",
    }
    action = evaluate_position(position, current_price=145.0, today="2026-04-22")
    assert action.action == "close"
    assert action.reason == "stop_loss"
    assert action.trade_id == 1
    assert action.ticker == "AMD"


def test_take_profit_triggered():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-20",
    }
    action = evaluate_position(position, current_price=160.0, today="2026-04-22")
    assert action.action == "close"
    assert action.reason == "take_profit"


def test_max_hold_triggered():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-15",
    }
    # 7 days later, max_hold_days=5 → should close
    action = evaluate_position(position, current_price=152.0, today="2026-04-22", max_hold_days=5)
    assert action.action == "close"
    assert action.reason == "max_hold"


def test_hold_when_in_range():
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-21",
    }
    action = evaluate_position(position, current_price=152.0, today="2026-04-22")
    assert action.action == "hold"
    assert action.reason == ""


def test_stop_loss_takes_priority_over_max_hold():
    # Both stop hit AND max hold exceeded — stop_loss should win (checked first)
    position = {
        "id": 1, "ticker": "AMD", "entry_price": 150.0,
        "shares": 100, "stop_loss": 145.5, "take_profit": 159.0,
        "entry_date": "2026-04-01",
    }
    action = evaluate_position(position, current_price=145.0, today="2026-04-22", max_hold_days=5)
    assert action.action == "close"
    assert action.reason == "stop_loss"


def test_run_monitor_closes_stop_loss_position(db_conn):
    from tools.database import insert_trade, get_open_trades

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-20",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    with patch("monitor.position_monitor.get_current_price", return_value=145.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-1"):
        actions = run_monitor(db_conn, today="2026-04-22")

    assert len(actions) == 1
    assert actions[0].action == "close"
    assert actions[0].reason == "stop_loss"
    # Trade should now be closed in DB
    assert get_open_trades(db_conn) == []


def test_run_monitor_holds_position_in_range(db_conn):
    from tools.database import insert_trade, get_open_trades

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    with patch("monitor.position_monitor.get_current_price", return_value=153.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-1"):
        actions = run_monitor(db_conn, today="2026-04-22")

    assert len(actions) == 1
    assert actions[0].action == "hold"
    # Trade should still be open
    assert len(get_open_trades(db_conn)) == 1
