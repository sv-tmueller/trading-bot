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


def test_no_op_when_in_cash(tmp_path, monkeypatch):
    db = tmp_path / "ks.db"
    init_db(db)
    monkeypatch.setattr("monitor.kill_switch.DB_PATH", str(db))
    # No regime_state row — defaults to CASH

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
