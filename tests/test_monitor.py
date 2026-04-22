from __future__ import annotations

import pytest
from monitor.position_monitor import evaluate_position, MonitorAction


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
