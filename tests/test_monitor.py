from __future__ import annotations

import sqlite3
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    # Second pass: price pulls back to 155 — must not lower stop or HWM.
    with patch("monitor.position_monitor.get_current_price", return_value=155.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    # Pass 2: drop to 155 — below new trailed stop 155.5 → close.
    with patch("monitor.position_monitor.get_current_price", return_value=155.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-soft") as mock_broker_close:
        actions = run_monitor(db_conn, today="2026-04-22")

    # Soft stop fires because price <= stop_loss.
    assert len(actions) == 1
    assert actions[0].action == "close"
    assert actions[0].reason == "stop_loss"
    mock_broker_close.assert_called_once_with("AMD")
    assert get_open_trades(db_conn) == []


# --- Per-trade exception isolation tests (issue #115) ---


def test_run_monitor_isolates_per_trade_failure(db_conn):
    """A transient broker error on one ticker must not abort the cycle —
    subsequent trades must still be evaluated and notify_error must fire once
    with the failing ticker name in the message."""
    from tools.database import insert_trade, get_open_trades

    # Two open trades: AMD (will fail on get_current_price) and NVDA (normal).
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    insert_trade(db_conn, {
        "ticker": "NVDA",
        "entry_date": "2026-04-21",
        "entry_price": 800.0,
        "shares": 10,
        "stop_loss": 780.0,
        "take_profit": 840.0,
    })

    alpaca_open = [
        {"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0},
        {"ticker": "NVDA", "qty": 10, "avg_entry_price": 800.0},
    ]

    def price_side_effect(ticker: str) -> float:
        if ticker == "AMD":
            raise ConnectionError("urllib3 connection blip")
        if ticker == "NVDA":
            return 810.0
        raise AssertionError(f"unexpected ticker {ticker}")

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_current_price", side_effect=price_side_effect), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"), \
         patch("monitor.position_monitor.notify_error") as mock_notify_error:
        actions = run_monitor(db_conn, today="2026-04-22")

    # Both trades must appear in the actions list.
    assert len(actions) == 2
    by_ticker = {a.ticker: a for a in actions}
    assert set(by_ticker) == {"AMD", "NVDA"}

    # AMD failed → marked hold/skipped_error (cycle accounting honest).
    assert by_ticker["AMD"].action == "hold"
    assert by_ticker["AMD"].reason == "skipped_error"

    # NVDA evaluated normally → in range, holding.
    assert by_ticker["NVDA"].action == "hold"
    assert by_ticker["NVDA"].reason == ""

    # notify_error called exactly once, with AMD ticker in message.
    assert mock_notify_error.call_count == 1
    call_args = mock_notify_error.call_args
    assert call_args.args[0] == "position_monitor"
    assert "AMD" in call_args.args[1]

    # Both trades remain open in the DB (AMD was skipped, NVDA was holding).
    open_now = {row["ticker"] for row in get_open_trades(db_conn)}
    assert open_now == {"AMD", "NVDA"}


# --- monitor_actions persistence tests (issue #131) ---


def _fetch_actions_rows(conn) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM monitor_actions ORDER BY id"
    ).fetchall()]


def test_run_monitor_persists_stop_loss_row(db_conn):
    """Soft-stop close writes one monitor_actions row with action_type='stop_loss'."""
    from tools.database import insert_trade

    trade_id = insert_trade(db_conn, {
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-1"):
        run_monitor(db_conn, today="2026-04-22")

    rows = _fetch_actions_rows(db_conn)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == trade_id
    assert rows[0]["ticker"] == "AMD"
    assert rows[0]["action_type"] == "stop_loss"
    assert rows[0]["reason"] == "stop_loss"
    assert rows[0]["current_price"] == 145.0
    assert rows[0]["stop_price"] == 145.5
    assert rows[0]["take_profit_price"] == 159.0
    # action_time must be a non-empty ISO-8601-ish UTC string with tz offset.
    assert rows[0]["action_time"]
    assert "T" in rows[0]["action_time"]


def test_run_monitor_persists_take_profit_row(db_conn):
    """Soft-target close writes a 'take_profit' row."""
    from tools.database import insert_trade

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-20",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    with patch("monitor.position_monitor.get_current_price", return_value=160.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-1"):
        run_monitor(db_conn, today="2026-04-22")

    rows = _fetch_actions_rows(db_conn)
    assert len(rows) == 1
    assert rows[0]["action_type"] == "take_profit"
    assert rows[0]["reason"] == "take_profit"
    assert rows[0]["current_price"] == 160.0


def test_run_monitor_persists_max_hold_row(db_conn, monkeypatch):
    """Max-hold close writes a 'max_hold' row."""
    from tools.database import insert_trade
    from config import settings as _s

    monkeypatch.setattr(_s, "MAX_HOLD_DAYS", 5)

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-15",   # 7 days before "today"
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    # Price in range (no stop, no target) → only max_hold can fire.
    with patch("monitor.position_monitor.get_current_price", return_value=152.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close", return_value="order-1"):
        run_monitor(db_conn, today="2026-04-22")

    rows = _fetch_actions_rows(db_conn)
    assert len(rows) == 1
    assert rows[0]["action_type"] == "max_hold"
    assert rows[0]["reason"] == "max_hold"


def test_run_monitor_persists_hold_row(db_conn):
    """Hold path still writes one 'hold' row per evaluated trade."""
    from tools.database import insert_trade

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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    rows = _fetch_actions_rows(db_conn)
    assert len(rows) == 1
    assert rows[0]["action_type"] == "hold"
    # In-memory hold has reason="" — persisted as NULL (helper coerces falsy → None).
    assert rows[0]["reason"] is None
    assert rows[0]["current_price"] == 153.0


def test_run_monitor_persists_reconciled_row(db_conn):
    """Phantom-close reconciliation writes a 'reconciled' row."""
    from tools.database import insert_trade

    trade_id = insert_trade(db_conn, {
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    rows = _fetch_actions_rows(db_conn)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == trade_id
    assert rows[0]["action_type"] == "reconciled"
    assert rows[0]["reason"] == "broker_closed"
    assert rows[0]["current_price"] == 146.0


def test_run_monitor_persists_skipped_error_row_and_continues(db_conn):
    """A transient broker exception writes a 'skipped_error' row AND the loop continues."""
    from tools.database import insert_trade, get_open_trades

    insert_trade(db_conn, {
        "ticker": "AMD",   # will fail on get_current_price
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    insert_trade(db_conn, {
        "ticker": "NVDA",  # will hold normally
        "entry_date": "2026-04-21",
        "entry_price": 800.0,
        "shares": 10,
        "stop_loss": 780.0,
        "take_profit": 840.0,
    })

    alpaca_open = [
        {"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0},
        {"ticker": "NVDA", "qty": 10, "avg_entry_price": 800.0},
    ]

    def price_side_effect(ticker: str) -> float:
        if ticker == "AMD":
            raise ConnectionError("urllib3 connection blip")
        return 810.0

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_current_price", side_effect=price_side_effect), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"), \
         patch("monitor.position_monitor.notify_error") as mock_notify_error:
        actions = run_monitor(db_conn, today="2026-04-22")

    # Loop continued — both trades evaluated.
    assert len(actions) == 2
    by_ticker = {a.ticker: a for a in actions}
    assert by_ticker["AMD"].reason == "skipped_error"
    assert by_ticker["NVDA"].action == "hold"

    # Two monitor_actions rows: one skipped_error (AMD), one hold (NVDA).
    rows_by_ticker = {r["ticker"]: r for r in _fetch_actions_rows(db_conn)}
    assert set(rows_by_ticker) == {"AMD", "NVDA"}
    assert rows_by_ticker["AMD"]["action_type"] == "skipped_error"
    assert rows_by_ticker["AMD"]["reason"] == "skipped_error"
    # AMD's price is unknown — current_price snapshot is 0.0 from the in-memory MonitorAction.
    assert rows_by_ticker["AMD"]["current_price"] == 0.0
    assert rows_by_ticker["NVDA"]["action_type"] == "hold"
    assert rows_by_ticker["NVDA"]["current_price"] == 810.0

    # The original notify_error from the broker blip fired once. The audit-trail
    # write succeeded so it didn't add a second notify_error.
    assert mock_notify_error.call_count == 1
    assert "AMD" in mock_notify_error.call_args.args[1]

    # Both trades remain open (AMD skipped, NVDA holding).
    open_now = {row["ticker"] for row in get_open_trades(db_conn)}
    assert open_now == {"AMD", "NVDA"}


def test_run_monitor_db_write_failure_does_not_abort_loop(db_conn):
    """If insert_monitor_action raises on one ticker, notify_error fires and the loop continues."""
    from tools.database import insert_trade, insert_monitor_action as real_insert

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-21",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })
    insert_trade(db_conn, {
        "ticker": "NVDA",
        "entry_date": "2026-04-21",
        "entry_price": 800.0,
        "shares": 10,
        "stop_loss": 780.0,
        "take_profit": 840.0,
    })

    alpaca_open = [
        {"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0},
        {"ticker": "NVDA", "qty": 10, "avg_entry_price": 800.0},
    ]

    def flaky_insert(conn, action):
        if action["ticker"] == "AMD":
            raise sqlite3.OperationalError("disk I/O error")
        return real_insert(conn, action)

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_current_price", return_value=153.0), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"), \
         patch("monitor.position_monitor.insert_monitor_action", side_effect=flaky_insert) as mock_insert, \
         patch("monitor.position_monitor.notify_error") as mock_notify_error:
        actions = run_monitor(db_conn, today="2026-04-22")

    # Loop must complete — both in-memory actions still produced.
    assert len(actions) == 2
    # insert_monitor_action was attempted for both trades.
    assert mock_insert.call_count == 2

    # NVDA row landed; AMD row didn't (insert raised).
    rows = _fetch_actions_rows(db_conn)
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"NVDA"}

    # notify_error fired for the failed audit-trail write, with AMD in the message.
    assert mock_notify_error.call_count == 1
    msg = mock_notify_error.call_args.args[1]
    assert "insert_monitor_action failed" in msg
    assert "AMD" in msg


# --- daily_stats writer tests (issue #137) ---


def _fetch_daily_stat(conn, today: str) -> dict:
    row = conn.execute(
        "SELECT * FROM daily_stats WHERE date = :d",
        {"d": today},
    ).fetchone()
    return dict(row) if row else None


def test_run_monitor_writes_daily_stats_row_per_pass(db_conn):
    """Every monitor pass writes (or upserts) one daily_stats row for today."""
    from tools.database import insert_trade

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]
    with patch("monitor.position_monitor.get_current_price", return_value=153.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = _fetch_daily_stat(db_conn, "2026-04-22")
    assert row is not None
    assert row["date"] == "2026-04-22"
    assert row["trades_opened"] == 1
    assert row["trades_closed"] == 0
    assert row["portfolio_value"] == 100_000.0


def test_run_monitor_daily_stats_upsert_is_idempotent(db_conn):
    """Two monitor passes on the same date must produce exactly one row, with the latest snapshot."""
    from tools.database import insert_trade

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": "2026-04-22",
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 145.5,
        "take_profit": 159.0,
    })

    alpaca_open = [{"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0}]

    # Pass 1: NAV 100k.
    with patch("monitor.position_monitor.get_current_price", return_value=153.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    # Pass 2 same day: NAV 101k — must overwrite, not insert a duplicate.
    with patch("monitor.position_monitor.get_current_price", return_value=154.0), \
         patch("monitor.position_monitor.get_alpaca_positions", return_value=alpaca_open), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=101_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    rows = db_conn.execute(
        "SELECT * FROM daily_stats WHERE date = :d", {"d": "2026-04-22"}
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["portfolio_value"] == 101_000.0


def test_run_monitor_daily_stats_writes_zero_row_when_no_activity(db_conn):
    """No open trades, no closes today — the row still gets written with zeros."""
    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[]), \
         patch("monitor.position_monitor.get_current_price", return_value=0.0), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = _fetch_daily_stat(db_conn, "2026-04-22")
    assert row is not None
    assert row["trades_opened"] == 0
    assert row["trades_closed"] == 0
    assert row["win_count"] == 0
    assert row["loss_count"] == 0
    assert row["portfolio_value"] == 100_000.0
    assert row["daily_pnl"] == 0.0


def test_run_monitor_daily_stats_broker_failure_writes_null_portfolio_value(db_conn):
    """If get_portfolio_value raises, the row still lands with NULL portfolio_value."""
    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[]), \
         patch("monitor.position_monitor.get_current_price", return_value=0.0), \
         patch("monitor.position_monitor.get_portfolio_value", side_effect=ConnectionError("alpaca down")), \
         patch("monitor.position_monitor.broker_close"), \
         patch("monitor.position_monitor.notify_error") as mock_notify_error:
        run_monitor(db_conn, today="2026-04-22")

    row = _fetch_daily_stat(db_conn, "2026-04-22")
    assert row is not None
    assert row["portfolio_value"] is None
    # The trade-aggregation columns are still present (DB-only inputs).
    assert row["trades_opened"] == 0
    assert row["trades_closed"] == 0
    # notify_error fires once for the broker NAV failure.
    assert mock_notify_error.call_count == 1
    assert "get_portfolio_value" in mock_notify_error.call_args.args[1]


def test_run_monitor_daily_stats_db_failure_does_not_abort_loop(db_conn):
    """A failure inside upsert_daily_stat must NOT crash run_monitor — fires notify_error instead."""
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
         patch("monitor.position_monitor.get_portfolio_value", return_value=100_000.0), \
         patch("monitor.position_monitor.upsert_daily_stat",
               side_effect=sqlite3.OperationalError("disk I/O error")), \
         patch("monitor.position_monitor.broker_close"), \
         patch("monitor.position_monitor.notify_error") as mock_notify_error:
        actions = run_monitor(db_conn, today="2026-04-22")

    # The per-trade loop completed — AMD was evaluated.
    assert len(actions) == 1
    # DB row for the position is still open (no exit fired).
    assert len(get_open_trades(db_conn)) == 1
    # The daily_stats failure surfaced via notify_error.
    msgs = [c.args[1] for c in mock_notify_error.call_args_list]
    assert any("daily_stats upsert failed" in m for m in msgs)


def test_run_monitor_daily_stats_counts_opens_and_closes_for_today(db_conn):
    """trades_opened reflects today's entries; trades_closed reflects today's exits with win/loss math."""
    # Two trades opened today.
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("AMD", "2026-04-22", None, 150.0, None, 100, 145.5, 159.0, None, None, None, None, None),
    )
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("NVDA", "2026-04-22", None, 800.0, None, 5, 780.0, 840.0, None, None, None, None, None),
    )
    # One trade closed today as a win, one as a loss.
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("META", "2026-04-15", "2026-04-22", 500.0, 520.0, 10, 490.0, 530.0, "take_profit", 200.0, 0.04, 7, 2.0),
    )
    db_conn.execute(
        """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price,
               shares, stop_loss, take_profit, exit_reason, pnl_dollars, pnl_pct, hold_days, r_multiple)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("TSLA", "2026-04-15", "2026-04-22", 200.0, 195.0, 20, 195.0, 210.0, "stop_loss", -100.0, -0.025, 7, -1.0),
    )
    db_conn.commit()

    # AMD and NVDA stay in range so the loop holds (no extra closes that
    # would skew the daily_pnl) — broker shows both open, monitor sees both
    # in the in-DB open set, and the price is mid-bracket for each.
    def price_in_range(ticker: str) -> float:
        if ticker == "AMD":
            return 151.0
        if ticker == "NVDA":
            return 810.0
        raise AssertionError(f"unexpected ticker {ticker}")

    with patch("monitor.position_monitor.get_alpaca_positions", return_value=[
            {"ticker": "AMD", "qty": 100, "avg_entry_price": 150.0},
            {"ticker": "NVDA", "qty": 5, "avg_entry_price": 800.0},
         ]), \
         patch("monitor.position_monitor.get_current_price", side_effect=price_in_range), \
         patch("monitor.position_monitor.get_portfolio_value", return_value=125_000.0), \
         patch("monitor.position_monitor.broker_close"):
        run_monitor(db_conn, today="2026-04-22")

    row = _fetch_daily_stat(db_conn, "2026-04-22")
    assert row is not None
    assert row["trades_opened"] == 2
    assert row["trades_closed"] == 2
    assert row["win_count"] == 1
    assert row["loss_count"] == 1
    assert row["win_rate"] == pytest.approx(0.5)
    assert row["avg_r_multiple"] == pytest.approx(0.5)
    assert row["daily_pnl"] == pytest.approx(100.0)
    assert row["portfolio_value"] == 125_000.0
    # drawdown is left None for now (follow-up work).
    assert row["drawdown"] is None
