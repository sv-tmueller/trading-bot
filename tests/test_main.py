from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch


def _make_agent_mock(return_value: dict):
    mock = MagicMock()
    mock.run.return_value = return_value
    return mock


def test_inter_agent_handoff_is_valid_json(db_conn):
    """Strategy, risk, and leader agents must receive valid JSON, not Python repr."""
    market_briefing = {
        "market_context": "bullish",
        "watchlist_summary": "AMD up 2%",
        "flagged_positions": [],
        "top_movers": ["AMD"],
    }
    candidates = {
        "candidates": [{"ticker": "AMD", "score": 0.8}],
        "tldr": "AMD crossover",
        "tickers_to_watch": [],
    }
    reviewed = {
        "approved": [{"ticker": "AMD", "shares": 100, "stop_loss": 140.0, "take_profit": 160.0}],
        "rejected": [],
    }
    decisions = {"decisions": [], "summary": "done"}

    mi_mock = _make_agent_mock(market_briefing)
    strategy_mock = _make_agent_mock(candidates)
    risk_mock = _make_agent_mock(reviewed)
    leader_mock = _make_agent_mock(decisions)

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent", return_value=mi_mock), \
         patch("main.StrategyAgent", return_value=strategy_mock), \
         patch("main.RiskReviewAgent", return_value=risk_mock), \
         patch("main.TeamLeaderAgent", return_value=leader_mock), \
         patch("main.get_daily_token_costs", return_value={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}), \
         patch("main.notify_scan_complete"), \
         patch("main.notify_error"), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.database.get_open_trades", return_value=[]):
        from main import run_morning_scan
        run_morning_scan()

    # Each handoff must be valid JSON
    strategy_arg = strategy_mock.run.call_args[0][0]
    parsed = json.loads(strategy_arg)
    assert parsed["market_context"] == "bullish"

    risk_arg = risk_mock.run.call_args[0][0]
    parsed = json.loads(risk_arg)
    assert "candidates" in parsed

    leader_arg = leader_mock.run.call_args[0][0]
    parsed = json.loads(leader_arg)
    assert "approved" in parsed


def test_run_morning_scan_calls_notify_error_on_exception(db_conn):
    """If any agent raises, notify_error must be called and the exception must not propagate."""
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error") as mock_notify_error, \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.database.get_open_trades", return_value=[]):
        MockMI.return_value.run.side_effect = RuntimeError("API timeout")
        from main import run_morning_scan
        run_morning_scan()  # must NOT raise

    mock_notify_error.assert_called_once()
    context, error_text = mock_notify_error.call_args[0]
    assert context == "morning_scan"
    assert "API timeout" in error_text


def test_run_position_monitor_calls_notify_error_on_exception(db_conn):
    """If run_monitor raises, notify_error must be called."""
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.run_monitor", side_effect=RuntimeError("connection refused")), \
         patch("main.notify_error") as mock_notify_error:
        from main import run_position_monitor
        run_position_monitor()  # must NOT raise

    mock_notify_error.assert_called_once()
    context, error_text = mock_notify_error.call_args[0]
    assert context == "position_monitor"
    assert "connection refused" in error_text


def test_run_morning_scan_closes_conn_on_exception(db_conn):
    """DB connection must be closed even when an agent raises."""
    mock_conn = MagicMock()
    mock_conn.row_factory = None

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=mock_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error"), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.database.get_open_trades", return_value=[]):
        MockMI.return_value.run.side_effect = RuntimeError("boom")
        from main import run_morning_scan
        run_morning_scan()

    mock_conn.close.assert_called_once()


def test_run_position_monitor_closes_conn_on_exception(db_conn):
    """DB connection must be closed even when run_monitor raises."""
    mock_conn = MagicMock()

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=mock_conn), \
         patch("main.run_monitor", side_effect=RuntimeError("boom")), \
         patch("main.notify_error"):
        from main import run_position_monitor
        run_position_monitor()

    mock_conn.close.assert_called_once()


def test_run_morning_scan_early_exits_when_trading_paused(db_conn):
    """When TRADING_PAUSED=true, scan must early-exit before instantiating any agent or touching the DB."""
    with patch("main.is_trading_day", return_value=True), \
         patch("config.settings.TRADING_PAUSED", True), \
         patch("main.get_db") as mock_get_db, \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.StrategyAgent") as MockStrategy, \
         patch("main.RiskReviewAgent") as MockRisk, \
         patch("main.TeamLeaderAgent") as MockLeader, \
         patch("main.notify_paused") as mock_notify_paused, \
         patch("main.notify_error") as mock_notify_error:
        from main import run_morning_scan
        run_morning_scan()

    # No agent instantiated
    MockMI.assert_not_called()
    MockStrategy.assert_not_called()
    MockRisk.assert_not_called()
    MockLeader.assert_not_called()
    # No DB connection opened
    mock_get_db.assert_not_called()
    # One Discord ping sent, no error
    mock_notify_paused.assert_called_once()
    mock_notify_error.assert_not_called()


def test_run_position_monitor_unaffected_by_trading_paused(db_conn):
    """TRADING_PAUSED must NOT block the position monitor — existing exits must keep working."""
    with patch("main.is_trading_day", return_value=True), \
         patch("config.settings.TRADING_PAUSED", True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.run_monitor", return_value=[]) as mock_run_monitor, \
         patch("main.notify_monitor") as mock_notify_monitor, \
         patch("main.notify_error") as mock_notify_error:
        from main import run_position_monitor
        run_position_monitor()

    mock_run_monitor.assert_called_once()
    mock_notify_monitor.assert_called_once()
    mock_notify_error.assert_not_called()


def test_run_position_monitor_groups_reconciled_with_closed(db_conn):
    """Reconciled actions must be reported as closed, not held (issue #78)."""
    from monitor.position_monitor import MonitorAction
    actions = [
        MonitorAction(trade_id=1, ticker="AMD", action="close", reason="stop_loss", current_price=140.0),
        MonitorAction(trade_id=2, ticker="NVDA", action="reconciled", reason="broker_closed", current_price=500.0),
        MonitorAction(trade_id=3, ticker="TSLA", action="hold", reason="", current_price=250.0),
    ]
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.run_monitor", return_value=actions), \
         patch("main.notify_monitor") as mock_notify_monitor, \
         patch("main.notify_error") as mock_notify_error:
        from main import run_position_monitor
        run_position_monitor()

    mock_notify_error.assert_not_called()
    mock_notify_monitor.assert_called_once()
    # Signature: notify_monitor(date, time, checked, closed)
    _date, _time, checked, closed = mock_notify_monitor.call_args[0]
    assert checked == 3
    assert len(closed) == 2
    closed_actions = {a.action for a in closed}
    assert closed_actions == {"close", "reconciled"}


def test_run_morning_scan_skips_if_already_ran_today(db_conn):
    """If team_leader already ran today, the scan must exit without calling any agent."""
    from tools.database import log_agent_output
    from datetime import date
    log_agent_output(db_conn, {
        "cycle_date": date.today().isoformat(),
        "agent_name": "team_leader",
        "input_summary": "prev run",
        "output_summary": "prev run",
        "full_reasoning": "prev run",
        "tokens_used": 100,
        "input_tokens": 80,
        "output_tokens": 20,
    })

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error"):
        from main import run_morning_scan
        run_morning_scan()

    MockMI.assert_not_called()


# --- Reconciliation tests ---

def _make_amd_open_trade():
    return [{"ticker": "AMD", "qty": 10, "avg_entry_price": 150.0}]


def test_reconcile_no_discrepancy(db_conn):
    """Alpaca returns AMD, DB has AMD open — no notify_error call."""
    with patch("tools.database.get_open_trades", return_value=[{"ticker": "AMD"}]), \
         patch("tools.broker.get_alpaca_positions", return_value=_make_amd_open_trade()), \
         patch("main.notify_error") as mock_notify_error:
        from main import _reconcile_positions
        _reconcile_positions(db_conn)

    mock_notify_error.assert_not_called()


def test_reconcile_ghost_position(db_conn):
    """Alpaca returns AMD, DB has no open trades — notify_error called with 'ghost' and 'AMD' in message."""
    with patch("tools.database.get_open_trades", return_value=[]), \
         patch("tools.broker.get_alpaca_positions", return_value=_make_amd_open_trade()), \
         patch("main.notify_error") as mock_notify_error:
        from main import _reconcile_positions
        _reconcile_positions(db_conn)

    mock_notify_error.assert_called_once()
    context, message = mock_notify_error.call_args[0]
    assert context == "reconciliation"
    assert "ghost" in message.lower() and "AMD" in message


def test_reconcile_phantom_db_entry(db_conn):
    """Alpaca returns nothing, DB has AMD open — notify_error called with 'phantom' and 'AMD' in message."""
    with patch("tools.database.get_open_trades", return_value=[{"ticker": "AMD"}]), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("main.notify_error") as mock_notify_error:
        from main import _reconcile_positions
        _reconcile_positions(db_conn)

    mock_notify_error.assert_called_once()
    context, message = mock_notify_error.call_args[0]
    assert context == "reconciliation"
    assert "phantom" in message.lower() and "AMD" in message


# --- Panic CLI (issue #103) ---


def test_run_panic_liquidate_without_confirm_is_dry_run(db_conn):
    """--liquidate without --confirm must NOT touch the broker and must exit non-zero."""
    with patch("tools.broker.cancel_all_orders") as mock_cancel, \
         patch("tools.broker.liquidate_all_positions") as mock_liquidate, \
         patch("tools.broker.get_alpaca_positions", return_value=[{"ticker": "AMD", "qty": 10, "avg_entry_price": 150.0}]), \
         patch("main.notify_panic") as mock_notify, \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic(liquidate=True, confirm=False)

    assert rc != 0
    mock_cancel.assert_not_called()
    mock_liquidate.assert_not_called()
    # Dry-run alert was posted
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    assert kwargs.get("dry_run") is True or (len(args) >= 3 and args[2] is True)


def test_run_panic_cancel_orders_calls_broker_and_notifies(db_conn):
    """--cancel-orders must call cancel_all_orders and post a Discord alert."""
    cancelled = [{"order_id": "ord-1", "status": 207}]
    with patch("tools.broker.cancel_all_orders", return_value=cancelled) as mock_cancel, \
         patch("tools.broker.liquidate_all_positions") as mock_liquidate, \
         patch("main.notify_panic") as mock_notify, \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic(cancel_orders=True)

    assert rc == 0
    mock_cancel.assert_called_once()
    mock_liquidate.assert_not_called()
    mock_notify.assert_called_once()
    headline_arg = mock_notify.call_args[0][0]
    assert "cancel" in headline_arg


def test_run_panic_liquidate_with_confirm_calls_broker(db_conn):
    """--liquidate --confirm must call liquidate_all_positions on the broker."""
    closed = [{"symbol": "AMD", "order_id": "close-1", "status": 207}]
    with patch("tools.broker.cancel_all_orders") as mock_cancel, \
         patch("tools.broker.liquidate_all_positions", return_value=closed) as mock_liquidate, \
         patch("main.notify_panic") as mock_notify, \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic(liquidate=True, confirm=True)

    assert rc == 0
    mock_cancel.assert_not_called()
    mock_liquidate.assert_called_once()
    mock_notify.assert_called_once()
    headline_arg = mock_notify.call_args[0][0]
    assert "liquidate" in headline_arg


def test_run_panic_pause_writes_env_var(tmp_path, db_conn, monkeypatch):
    """--pause must atomically write TRADING_PAUSED=true to .env (anchored to repo root)."""
    env_file = tmp_path / ".env"
    env_file.write_text("TRADING_MODE=paper\nTRADING_PAUSED=false\nMAX_POSITIONS=5\n")
    # Override the repo-root anchor so we hit our fixture path, not the live repo .env.
    monkeypatch.setattr("main._REPO_ROOT", tmp_path)

    with patch("main.notify_panic"), \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic(pause=True)

    assert rc == 0
    after = env_file.read_text()
    assert "TRADING_PAUSED=true" in after
    assert "TRADING_PAUSED=false" not in after


def test_pause_trading_in_env_anchors_to_repo_root_not_cwd(tmp_path, monkeypatch):
    """Regression: default env_path must anchor to repo root, NOT the caller's cwd.

    Bug report: invoking `python /opt/trading-bot/main.py panic --pause` from any cwd
    other than /opt/trading-bot wrote a stray .env to that cwd and the live bot kept
    scanning unpaused. Silent failure during incident response is unacceptable.
    """
    # Stage a fake repo root with a real .env we'll inspect after the call.
    fake_repo_root = tmp_path / "repo"
    fake_repo_root.mkdir()
    repo_env = fake_repo_root / ".env"
    repo_env.write_text("TRADING_PAUSED=false\n")
    # And a separate cwd that is NOT the repo root.
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    # Anchor the function to our fake repo root.
    monkeypatch.setattr("main._REPO_ROOT", fake_repo_root)

    from main import _pause_trading_in_env
    changed = _pause_trading_in_env()  # no env_path arg — must use the anchor

    assert changed is True
    # Repo-root .env was modified.
    assert "TRADING_PAUSED=true" in repo_env.read_text()
    # And no stray .env was written to the cwd.
    assert not (other_cwd / ".env").exists(), (
        "FOOTGUN: _pause_trading_in_env wrote a .env to the cwd instead of the repo root. "
        "Live bot would keep scanning unpaused."
    )


def test_pause_trading_in_env_appends_when_missing(tmp_path):
    """If TRADING_PAUSED is not present, _pause_trading_in_env must append it."""
    env_file = tmp_path / ".env"
    env_file.write_text("TRADING_MODE=paper\nMAX_POSITIONS=5\n")

    from main import _pause_trading_in_env
    changed = _pause_trading_in_env(env_path=env_file)

    assert changed is True
    after = env_file.read_text()
    assert "TRADING_PAUSED=true" in after
    # Existing keys preserved
    assert "TRADING_MODE=paper" in after
    assert "MAX_POSITIONS=5" in after


def test_pause_trading_in_env_replaces_when_false(tmp_path):
    """If TRADING_PAUSED=false, it must be flipped to true (not duplicated)."""
    env_file = tmp_path / ".env"
    env_file.write_text("TRADING_PAUSED=false\nMAX_POSITIONS=5\n")

    from main import _pause_trading_in_env
    changed = _pause_trading_in_env(env_path=env_file)

    assert changed is True
    after = env_file.read_text()
    assert "TRADING_PAUSED=true" in after
    assert "TRADING_PAUSED=false" not in after
    # Should appear exactly once
    assert after.count("TRADING_PAUSED=") == 1


def test_pause_trading_in_env_idempotent_when_already_true(tmp_path):
    """If TRADING_PAUSED=true is already present, the function must report no-op (False)."""
    env_file = tmp_path / ".env"
    env_file.write_text("TRADING_PAUSED=true\nMAX_POSITIONS=5\n")
    before = env_file.read_text()

    from main import _pause_trading_in_env
    changed = _pause_trading_in_env(env_path=env_file)

    assert changed is False
    assert env_file.read_text() == before


def test_pause_trading_in_env_creates_missing_file(tmp_path):
    """If .env does not exist, _pause_trading_in_env must create it with TRADING_PAUSED=true."""
    env_file = tmp_path / ".env"
    assert not env_file.exists()

    from main import _pause_trading_in_env
    changed = _pause_trading_in_env(env_path=env_file)

    assert changed is True
    assert env_file.exists()
    assert "TRADING_PAUSED=true" in env_file.read_text()


def test_run_panic_audit_log_written_before_broker_call(db_conn):
    """The agent_logs row must be written BEFORE the broker call so a partial failure is recoverable."""
    from datetime import date

    # Wrap db_conn so run_panic's close() doesn't close our fixture (it stays usable from the test)
    conn_wrapper = MagicMock(wraps=db_conn)
    conn_wrapper.close = MagicMock()  # no-op so the test can keep querying the in-memory DB

    audit_seen_when_called = {"value": False}

    def _check_audit(*args, **kwargs):
        # When this broker call fires, the audit row must already exist
        rows = db_conn.execute(
            "SELECT * FROM agent_logs WHERE agent_name = 'panic' AND cycle_date = ?",
            (date.today().isoformat(),),
        ).fetchall()
        audit_seen_when_called["value"] = len(rows) >= 1
        return [{"order_id": "ord-1", "status": 207}]

    with patch("tools.broker.cancel_all_orders", side_effect=_check_audit), \
         patch("main.notify_panic"), \
         patch("main.get_db", return_value=conn_wrapper):
        from main import run_panic
        rc = run_panic(cancel_orders=True)

    assert rc == 0
    assert audit_seen_when_called["value"], "audit_log row was NOT present when broker was called"


def test_run_panic_no_flags_exits_non_zero(db_conn):
    """Calling panic with no actionable flag must exit non-zero with usage text."""
    with patch("tools.broker.cancel_all_orders") as mock_cancel, \
         patch("tools.broker.liquidate_all_positions") as mock_liquidate, \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic()

    assert rc != 0
    mock_cancel.assert_not_called()
    mock_liquidate.assert_not_called()


def test_run_panic_cancel_first_then_liquidate(db_conn):
    """When both --cancel-orders and --liquidate --confirm are set, cancel runs FIRST."""
    call_order = []

    def _record_cancel():
        call_order.append("cancel")
        return []

    def _record_liquidate():
        call_order.append("liquidate")
        return []

    with patch("tools.broker.cancel_all_orders", side_effect=_record_cancel), \
         patch("tools.broker.liquidate_all_positions", side_effect=_record_liquidate), \
         patch("main.notify_panic"), \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic(cancel_orders=True, liquidate=True, confirm=True)

    assert rc == 0
    assert call_order == ["cancel", "liquidate"], (
        "cancel_all_orders must run before liquidate_all_positions so unfilled "
        "bracket entries don't race the liquidation"
    )


def test_run_panic_broker_failure_returns_nonzero_and_notifies(db_conn):
    """Broker failure must propagate to a non-zero exit code AND fire notify_error."""
    with patch("tools.broker.cancel_all_orders", side_effect=RuntimeError("alpaca 503")), \
         patch("main.notify_panic"), \
         patch("main.notify_error") as mock_err, \
         patch("main.get_db", return_value=db_conn):
        from main import run_panic
        rc = run_panic(cancel_orders=True)

    assert rc != 0
    mock_err.assert_called_once()
    context, message = mock_err.call_args[0]
    assert context == "panic"
    assert "alpaca 503" in message


def test_reconcile_failure_does_not_block_scan(db_conn):
    """get_alpaca_positions raises — scan still runs (notify_error called but agents proceed)."""
    market_briefing = {
        "market_context": "bullish",
        "watchlist_summary": "AMD up 2%",
        "flagged_positions": [],
        "top_movers": ["AMD"],
    }
    candidates = {
        "candidates": [{"ticker": "AMD", "score": 0.8}],
        "tldr": "AMD crossover",
        "tickers_to_watch": [],
    }
    reviewed = {
        "approved": [{"ticker": "AMD", "shares": 100, "stop_loss": 140.0, "take_profit": 160.0}],
        "rejected": [],
    }
    decisions = {"decisions": [], "summary": "done"}

    mi_mock = _make_agent_mock(market_briefing)
    strategy_mock = _make_agent_mock(candidates)
    risk_mock = _make_agent_mock(reviewed)
    leader_mock = _make_agent_mock(decisions)

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent", return_value=mi_mock), \
         patch("main.StrategyAgent", return_value=strategy_mock), \
         patch("main.RiskReviewAgent", return_value=risk_mock), \
         patch("main.TeamLeaderAgent", return_value=leader_mock), \
         patch("main.get_daily_token_costs", return_value={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}), \
         patch("main.notify_scan_complete"), \
         patch("main.notify_error") as mock_notify_error, \
         patch("tools.broker.get_alpaca_positions", side_effect=RuntimeError("network error")):
        from main import run_morning_scan
        run_morning_scan()  # must NOT raise

    # notify_error called for the reconciliation failure
    assert mock_notify_error.called
    # But agents still ran
    mi_mock.run.assert_called_once()
