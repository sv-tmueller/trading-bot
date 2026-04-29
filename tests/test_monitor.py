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

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    with patch("monitor.position_monitor.get_current_price", return_value=145.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
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

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    with patch("monitor.position_monitor.get_current_price", return_value=153.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close", return_value="order-1"):
        actions = run_monitor(db_conn, today="2026-04-22")

    assert len(actions) == 1
    assert actions[0].action == "hold"
    # Trade should still be open
    assert len(get_open_trades(db_conn)) == 1


# --- In-monitor reconciliation tests (issue #73) ---


def test_run_monitor_reconciles_broker_closed_position(db_conn):
    """If Alpaca already closed a position (bracket child fired), the monitor must mark it closed in the DB without calling broker_close again."""
    from tools.database import insert_trade, get_open_trades

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    # Alpaca has nothing open — bracket child closed it server-side.
    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[]), \
         patch("monitor.position_monitor.get_current_price", return_value=146.0), \
         patch("monitor.position_monitor.broker_close") as mock_broker_close:
        actions = run_monitor(db_conn, today="2026-04-22")

    assert len(actions) == 1
    assert actions[0].action == "reconciled"
    assert actions[0].reason == "broker_closed"
    # Must NOT issue a redundant close — the broker already did.
    mock_broker_close.assert_not_called()
    # DB row is now closed.
    assert get_open_trades(db_conn) == []
    row = db_conn.execute("SELECT exit_reason, exit_price FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["exit_reason"] == "stop_loss"
    assert row["exit_price"] == 146.0


def test_run_monitor_reconciles_phantom_close_near_stop(db_conn):
    """Phantom close with price near the stop level reconciles as stop_loss."""
    from tools.database import insert_trade

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[]), \
         patch("monitor.position_monitor.get_current_price", return_value=145.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = db_conn.execute("SELECT exit_reason FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["exit_reason"] == "stop_loss"


def test_run_monitor_reconciles_phantom_close_near_target(db_conn):
    """Phantom close with price near the take-profit level reconciles as take_profit."""
    from tools.database import insert_trade

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[]), \
         patch("monitor.position_monitor.get_current_price", return_value=158.5), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = db_conn.execute("SELECT exit_reason FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["exit_reason"] == "take_profit"


def test_run_monitor_reconciles_phantom_close_mid_range(db_conn):
    """Phantom close mid-range (outside slippage tolerance for both legs) reconciles as manual."""
    from tools.database import insert_trade

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[]), \
         patch("monitor.position_monitor.get_current_price", return_value=152.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = db_conn.execute("SELECT exit_reason FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["exit_reason"] == "manual"


# --- Trailing-stop tests (issue #67) ---


def test_schema_has_trailing_high_column(db_conn):
    """The trades table must expose the trailing_high column after init."""
    cols = {row[1] for row in db_conn.execute("PRAGMA table_info(trades)")}
    assert "trailing_high" in cols


def test_trailing_off_does_not_mutate_stop_or_trailing_high(db_conn, monkeypatch):
    """With TRAILING_STOP_ENABLED=false the monitor must leave stop_loss/trailing_high untouched."""
    from tools.database import insert_trade
    from config import settings as _s

    monkeypatch.setattr(_s, "TRAILING_STOP_ENABLED", False)

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    with patch("monitor.position_monitor.get_current_price", return_value=158.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = db_conn.execute("SELECT stop_loss, trailing_high FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["stop_loss"] == 145.5
    assert row["trailing_high"] is None


def test_trailing_on_ratchets_stop_up_on_new_high(db_conn, monkeypatch):
    """When the price makes a new high, stop_loss must move up by the initial stop distance."""
    from tools.database import insert_trade
    from config import settings as _s

    monkeypatch.setattr(_s, "TRAILING_STOP_ENABLED", True)

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,    # initial distance = 4.5
        "take_profit": 165.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    # Price rallies to 158 — new trailing high. Expect stop = 158 - 4.5 = 153.5.
    with patch("monitor.position_monitor.get_current_price", return_value=158.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = db_conn.execute("SELECT stop_loss, trailing_high FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["trailing_high"] == 158.0
    assert row["stop_loss"] == pytest.approx(153.5)


def test_trailing_on_does_not_ratchet_down_on_pullback(db_conn, monkeypatch):
    """After a high, a pullback must NOT lower stop_loss or trailing_high."""
    from tools.database import insert_trade
    from config import settings as _s

    monkeypatch.setattr(_s, "TRAILING_STOP_ENABLED", True)

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 165.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]

    # First pass: price 158 — stop ratchets to 153.5, trailing_high=158.
    with patch("monitor.position_monitor.get_current_price", return_value=158.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    # Second pass: price pulls back to 155 — must not lower stop or HWM.
    with patch("monitor.position_monitor.get_current_price", return_value=155.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-23")

    row = db_conn.execute("SELECT stop_loss, trailing_high FROM trades WHERE ticker = 'AMD'").fetchone()
    assert row["trailing_high"] == 158.0
    assert row["stop_loss"] == pytest.approx(153.5)


def test_trailing_on_stop_hit_closes_position(db_conn, monkeypatch):
    """Once the trailed stop is hit, the position must close as a stop_loss exit."""
    from tools.database import insert_trade, get_open_trades
    from config import settings as _s

    monkeypatch.setattr(_s, "TRAILING_STOP_ENABLED", True)

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,    # initial distance = 4.5
        "take_profit": 170.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]

    # Pass 1: rally to 160 — trailing stop becomes 155.5.
    with patch("monitor.position_monitor.get_current_price", return_value=160.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    # Pass 2: drop to 155 — below new trailed stop 155.5 → close.
    with patch("monitor.position_monitor.get_current_price", return_value=155.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.broker_close", return_value="order-trail") as mock_close:
        actions = run_monitor(db_conn, today="2026-04-23")

    assert any(a.action == "close" and a.reason == "stop_loss" for a in actions)
    mock_close.assert_called_once_with("AMD")
    assert get_open_trades(db_conn) == []


def test_run_monitor_reconcile_failure_does_not_block_soft_stop(db_conn):
    """If get_alpaca_positions raises, the monitor must still run the soft stop check (defense-in-depth)."""
    from tools.database import insert_trade, get_open_trades

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-20",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    with patch("monitor.position_monitor.get_alpaca_positions", side_effect=ConnectionError("alpaca down")), \
         patch("monitor.position_monitor.get_current_price", return_value=145.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-soft") as mock_broker_close:
        actions = run_monitor(db_conn, today="2026-04-22")

    # Soft stop fires because price <= stop_loss.
    assert len(actions) == 1
    assert actions[0].action == "close"
    assert actions[0].reason == "stop_loss"
    mock_broker_close.assert_called_once_with("AMD")
    assert get_open_trades(db_conn) == []
