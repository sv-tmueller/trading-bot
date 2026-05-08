from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Each test gets a fresh DB so panic's audit_log INSERT doesn't pollute prod."""
    db_path = tmp_path / "panic.db"
    monkeypatch.setattr("storage.init_db.DB_PATH", db_path, raising=False)
    monkeypatch.setattr("main.DB_PATH", db_path, raising=False)
    yield


def test_run_panic_no_flags_returns_usage_error():
    from main import run_panic
    rc = run_panic()
    assert rc == 1


def test_run_panic_liquidate_without_confirm_is_dry_run():
    """--liquidate without --confirm must NOT touch the broker beyond a position read."""
    with patch("main.connect_ibkr") as mock_connect, \
         patch("main.get_position", return_value=42), \
         patch("main.cancel_all_orders") as mock_cancel, \
         patch("main.liquidate") as mock_liquidate, \
         patch("main.notify_panic") as mock_notify:
        mock_connect.return_value = MagicMock()
        from main import run_panic
        rc = run_panic(liquidate=True, confirm=False)
        assert rc == 2  # dry-run exit code
        mock_cancel.assert_not_called()
        mock_liquidate.assert_not_called()
        mock_notify.assert_called_once()
        # dry_run kwarg present
        assert mock_notify.call_args.kwargs.get("dry_run") is True


def test_run_panic_cancel_orders_calls_ibkr_and_notifies():
    """--cancel-orders must connect to IBKR, call cancel_all_orders, post Discord."""
    with patch("main.connect_ibkr") as mock_connect, \
         patch("main.cancel_all_orders", return_value=3) as mock_cancel, \
         patch("main.notify_panic") as mock_notify:
        ib_mock = MagicMock()
        mock_connect.return_value = ib_mock
        from main import run_panic
        rc = run_panic(cancel_orders=True)
        assert rc == 0
        mock_cancel.assert_called_once_with(ib_mock)
        mock_notify.assert_called_once()
        # notify_panic called with action="cancel-orders" and a count payload
        args, kwargs = mock_notify.call_args
        assert args[0] == "cancel-orders"
        # disconnect called
        ib_mock.disconnect.assert_called_once()


def test_run_panic_liquidate_with_confirm_calls_ibkr_liquidate():
    """--liquidate --confirm must call ibkr_broker.liquidate(BOT_TICKER) and notify."""
    fill = {"order_id": "X1", "fill_price": 49.0, "qty": 100, "fill_time": "2026-05-08T12:00:00"}
    with patch("main.connect_ibkr") as mock_connect, \
         patch("main.liquidate", return_value=fill) as mock_liquidate, \
         patch("main.notify_panic") as mock_notify:
        ib_mock = MagicMock()
        mock_connect.return_value = ib_mock
        from main import run_panic
        rc = run_panic(liquidate=True, confirm=True)
        assert rc == 0
        # liquidate(ib, symbol=BOT_TICKER) shape
        args, kwargs = mock_liquidate.call_args
        assert args[0] is ib_mock
        # symbol kwarg present (don't hardcode WSPL.DE — pull from settings)
        from config import settings
        assert kwargs.get("symbol") == settings.BOT_TICKER
        mock_notify.assert_called_once()
        ib_mock.disconnect.assert_called_once()


def test_run_panic_liquidate_no_position_returns_ok():
    """liquidate returning None (no position) is success path, not failure."""
    with patch("main.connect_ibkr") as mock_connect, \
         patch("main.liquidate", return_value=None), \
         patch("main.notify_panic"):
        mock_connect.return_value = MagicMock()
        from main import run_panic
        rc = run_panic(liquidate=True, confirm=True)
        assert rc == 0


def test_run_panic_tws_connection_failure_returns_error_does_not_call_broker():
    """If connect_ibkr raises, no broker action is taken and exit code is non-zero."""
    from tools.ibkr_broker import IBKRConnectionError
    with patch("main.connect_ibkr", side_effect=IBKRConnectionError("TWS down")), \
         patch("main.cancel_all_orders") as mock_cancel, \
         patch("main.liquidate") as mock_liquidate, \
         patch("main.notify_error") as mock_notify_err:
        from main import run_panic
        rc = run_panic(cancel_orders=True)
        assert rc == 1
        mock_cancel.assert_not_called()
        mock_liquidate.assert_not_called()
        mock_notify_err.assert_called_once()


def test_run_panic_pause_writes_env_atomic(tmp_path, monkeypatch):
    """--pause writes TRADING_PAUSED=true to repo-root .env; broker untouched."""
    env_path = tmp_path / ".env"
    env_path.write_text("TRADING_MODE=paper\nTRADING_PAUSED=false\n")
    monkeypatch.setattr("main._REPO_ROOT", tmp_path)

    with patch("main.connect_ibkr") as mock_connect, \
         patch("main.notify_panic") as mock_notify:
        from main import run_panic
        rc = run_panic(pause=True)
        assert rc == 0
        mock_connect.assert_not_called()  # pause is broker-free
        text = env_path.read_text()
        assert "TRADING_PAUSED=true" in text
        assert "TRADING_PAUSED=false" not in text
        mock_notify.assert_called_once()
