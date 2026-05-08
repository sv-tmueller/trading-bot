from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from storage.init_db import init_db


def _seed_vehicle_history(prices):
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(prices))
    df = pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                       "Close": prices, "Volume": 1_000_000}, index=dates)
    return df


def _seed_db_with_long_position(db_path):
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, 'LONG', 'LONG', 0)",
        ("2026-05-06", 400.0, 380.0))
    conn.commit()
    conn.close()


def _seed_db_with_state(db_path, state):
    """Seed regime_state with a single row whose current_state and target_state
    both equal ``state`` and kill_switch_active=0. Used for short-circuit tests."""
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO regime_state (date, spy_close, spy_sma200, target_state, "
        "current_state, kill_switch_active) VALUES (?, ?, ?, ?, ?, 0)",
        ("2026-05-06", 400.0, 380.0, state, state))
    conn.commit()
    conn.close()


def test_no_op_when_no_regime_state(tmp_path, monkeypatch):
    """No regime_state row at all — `not latest` short-circuit defaults to CASH."""
    db = tmp_path / "ks.db"
    init_db(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))
    # No regime_state row — `not latest` short-circuit fires

    with patch("monitor.kill_switch.connect_ibkr") as connect_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        connect_mock.assert_not_called()


def test_no_op_when_current_state_is_cash(tmp_path, monkeypatch):
    """regime_state row exists but current_state='CASH' — second branch of the
    `current_state != LONG` short-circuit. No vehicle fetch, no broker connect."""
    db = tmp_path / "ks.db"
    _seed_db_with_state(db, "CASH")
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    with patch("monitor.kill_switch.connect_ibkr") as connect_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        connect_mock.assert_not_called()


def test_no_op_when_drawdown_within_threshold(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    # 30 days of slowly rising prices, today only -10% from high
    prices = np.concatenate([np.linspace(50, 60, 25), [54.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr") as connect_mock, \
         patch("monitor.kill_switch.liquidate") as liq_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        connect_mock.assert_not_called()  # no IBKR call needed
        liq_mock.assert_not_called()


def test_kill_switch_fires_on_threshold_breach(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    # 30 days where high was 100, now 70 (-30% drawdown)
    prices = np.concatenate([np.linspace(50, 100, 25), [70.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr", return_value=MagicMock()), \
         patch("monitor.kill_switch.liquidate") as liq_mock, \
         patch("monitor.kill_switch.get_position", return_value=100), \
         patch("monitor.kill_switch.notify_kill_switch_fired") as notify_mock:
        liq_mock.return_value = {"order_id": "K1", "fill_price": 69.5,
                                  "qty": 100, "fill_time": "2026-05-07T15:30:00"}
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        liq_mock.assert_called_once()
        notify_mock.assert_called_once()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    trade = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert state["kill_switch_active"] == 1
    assert state["current_state"] == "CASH"
    assert trade["reason"] == "kill_switch"


def test_kill_switch_fires_at_exact_boundary(tmp_path, monkeypatch):
    """Boundary regression: drawdown == -KILL_SWITCH_DRAWDOWN_PCT exactly fires.

    Pins the strict-vs-loose semantics of the `if drawdown > -threshold: return 0`
    short-circuit in monitor/kill_switch.py — equality must fall through and
    trigger liquidation. A future refactor that flips this to `>=` would silently
    let a 25.0% drawdown through; this test catches that regression.
    """
    from config import settings

    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    # Construct prices so last_price / ref_high - 1 == -KILL_SWITCH_DRAWDOWN_PCT exactly.
    # With np.linspace(50, 100, 25) ++ [75.0]*5, the last 30 values include 100.0
    # (max of last 30) and end at 75.0; drawdown = 75/100 - 1 = -0.25 = -default_pct.
    assert settings.KILL_SWITCH_DRAWDOWN_PCT == 0.25, (
        "Boundary test built around default 0.25; rebuild prices if default changes")
    prices = np.concatenate([np.linspace(50, 100, 25), [75.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr", return_value=MagicMock()), \
         patch("monitor.kill_switch.liquidate") as liq_mock, \
         patch("monitor.kill_switch.get_position", return_value=100), \
         patch("monitor.kill_switch.notify_kill_switch_fired"):
        liq_mock.return_value = {"order_id": "K_BOUNDARY", "fill_price": 74.9,
                                  "qty": 100, "fill_time": "2026-05-07T15:30:00"}
        from monitor.kill_switch import main
        rc = main()
        assert rc == 0
        # The pin: equality at the threshold MUST fire liquidate.
        liq_mock.assert_called_once()


def test_liquidate_failure_escalates(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    _seed_db_with_long_position(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))

    prices = np.concatenate([np.linspace(50, 100, 25), [70.0] * 5])
    yf_df = _seed_vehicle_history(prices)

    from tools.ibkr_broker import OrderTimeoutError
    with patch("monitor.kill_switch.yf.download", return_value=yf_df), \
         patch("monitor.kill_switch.connect_ibkr", return_value=MagicMock()), \
         patch("monitor.kill_switch.liquidate", side_effect=OrderTimeoutError("oops")), \
         patch("monitor.kill_switch.get_position", return_value=100), \
         patch("monitor.kill_switch.notify_kill_switch_fired"), \
         patch("monitor.kill_switch.notify_trade_failed") as fail_mock:
        from monitor.kill_switch import main
        rc = main()
        assert rc == 1  # error exit
        fail_mock.assert_called()

    # Post-failure DB state: audit_log captures the error outcome, and
    # regime_state must NOT flip to CASH — the position is still open at the
    # broker because the liquidate failed. Catches a silent regression where
    # state is flipped before liquidate confirmation, or where the audit row
    # is left untouched on the timeout branch.
    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    state = conn.execute("SELECT * FROM regime_state ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    assert audit["outcome"] is not None and audit["outcome"].startswith("error:")
    assert "kill_switch_liquidate_failed" in audit["outcome"]
    assert state["current_state"] == "LONG"
    assert state["kill_switch_active"] == 0
