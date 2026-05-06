from __future__ import annotations

"""Tests for the agent-context broker guard (issue #168).

The guard sits at the very top of every `tools/broker.py` submission helper.
When `CLAUDE_AGENT_NO_BROKER` is set (any of "1", "true", "yes",
case-insensitive), each helper raises `BrokerCallBlockedError` BEFORE
constructing the Alpaca client or hitting the wire. The autouse
`_block_live_broker_in_tests` fixture in `tests/conftest.py` sets the env
var for the entire test suite, so the "guard ON" tests below verify the
common path. The "guard OFF" tests explicitly clear the env var to verify
that production behaviour (cron) is unchanged.

Why this exists: 2026-05-06 incident — a QA subagent's `pytest` reached
live broker via an unmocked code path and submitted 5×100 AMD parent BUYs
(500-share margin position, $-101k cash). PR #150's docs/skill rule is
manual-compliance only; this is the mechanical enforcement layer.
"""

import pytest
from unittest.mock import MagicMock, patch

from tools.broker import (
    BrokerCallBlockedError,
    cancel_all_orders,
    liquidate_all_positions,
    place_market_order,
    place_oco_brackets,
    place_parent_market_order,
)


# ---------------------------------------------------------------------------
# Guard ON — relies on the autouse conftest fixture setting CLAUDE_AGENT_NO_BROKER=1.
# Each of the five protected helpers must raise BrokerCallBlockedError BEFORE
# any Alpaca SDK call. We don't mock get_trading_client here on purpose: if the
# guard is missing or runs too late, the test would either reach a real
# TradingClient constructor (the very thing we're trying to prevent) or get a
# different exception class. The guard must intercept first.
# ---------------------------------------------------------------------------


def test_place_market_order_blocked_when_guard_on():
    with pytest.raises(BrokerCallBlockedError) as excinfo:
        place_market_order("AMD", 100, "buy")
    msg = str(excinfo.value)
    assert "place_market_order" in msg
    assert "CLAUDE_AGENT_NO_BROKER" in msg
    assert "issue #168" in msg


def test_place_parent_market_order_blocked_when_guard_on():
    with pytest.raises(BrokerCallBlockedError) as excinfo:
        place_parent_market_order("AMD", 100, "buy")
    msg = str(excinfo.value)
    assert "place_parent_market_order" in msg
    assert "CLAUDE_AGENT_NO_BROKER" in msg


def test_place_oco_brackets_blocked_when_guard_on():
    with pytest.raises(BrokerCallBlockedError) as excinfo:
        place_oco_brackets(
            ticker="AMD",
            shares=100,
            parent_side="buy",
            take_profit_price=160.0,
            stop_price=145.0,
        )
    msg = str(excinfo.value)
    assert "place_oco_brackets" in msg
    assert "CLAUDE_AGENT_NO_BROKER" in msg


def test_cancel_all_orders_blocked_when_guard_on():
    with pytest.raises(BrokerCallBlockedError) as excinfo:
        cancel_all_orders()
    assert "cancel_all_orders" in str(excinfo.value)
    assert "CLAUDE_AGENT_NO_BROKER" in str(excinfo.value)


def test_liquidate_all_positions_blocked_when_guard_on():
    with pytest.raises(BrokerCallBlockedError) as excinfo:
        liquidate_all_positions()
    assert "liquidate_all_positions" in str(excinfo.value)
    assert "CLAUDE_AGENT_NO_BROKER" in str(excinfo.value)


def test_guard_runs_before_argument_validation():
    """The guard must intercept BEFORE the per-helper argument validators
    (e.g. `Invalid order side`, `shares must be > 0`). Otherwise an invalid
    call from a test could bypass the guard via a ValueError and the
    operator would not learn the call was actually agent-context.
    """
    # Bad side ("BUY" vs "buy") would normally raise ValueError; the guard
    # must fire first.
    with pytest.raises(BrokerCallBlockedError):
        place_market_order("AMD", 100, "BUY")
    with pytest.raises(BrokerCallBlockedError):
        place_parent_market_order("AMD", 100, "BUY")
    with pytest.raises(BrokerCallBlockedError):
        place_oco_brackets(
            ticker="AMD",
            shares=0,  # would normally raise ValueError("shares must be > 0")
            parent_side="buy",
            take_profit_price=160.0,
            stop_price=145.0,
        )


def test_guard_recognises_truthy_string_values(monkeypatch):
    """Spec: "1", "true", "yes" all activate the guard, case-insensitively."""
    for val in ("1", "true", "TRUE", "True", "yes", "YES", "Yes"):
        monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", val)
        with pytest.raises(BrokerCallBlockedError):
            place_market_order("AMD", 100, "buy")


# ---------------------------------------------------------------------------
# Guard OFF — explicitly clear the env var inside the test body so production
# behaviour (cron, where the var is unset) is exercised. Each helper is mocked
# at the SDK level so we never actually reach Alpaca; we're verifying the
# guard does NOT fire when the var is empty/unset/falsy.
# ---------------------------------------------------------------------------


def test_place_market_order_works_when_guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-prod"
    submitted.filled_avg_price = "150.00"
    mock_client.submit_order.return_value = submitted
    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 1, "buy")
    assert result["order_id"] == "ord-prod"
    assert result["fill_price"] == pytest.approx(150.00)


def test_place_parent_market_order_works_when_guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-prod-parent"
    submitted.filled_avg_price = "150.00"
    mock_client.submit_order.return_value = submitted
    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_parent_market_order("AMD", 1, "buy")
    assert result["order_id"] == "ord-prod-parent"


def test_place_oco_brackets_works_when_guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)
    mock_client = MagicMock()
    oco = MagicMock()
    oco.id = "ord-prod-oco"
    mock_client.submit_order.return_value = oco
    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_oco_brackets(
            ticker="AMD",
            shares=1,
            parent_side="buy",
            take_profit_price=160.0,
            stop_price=145.0,
        )
    assert result["order_id"] == "ord-prod-oco"


def test_cancel_all_orders_works_when_guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)
    mock_client = MagicMock()
    mock_client.cancel_orders.return_value = []
    with patch("tools.broker.get_trading_client", return_value=mock_client):
        assert cancel_all_orders() == []


def test_liquidate_all_positions_works_when_guard_off(monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_NO_BROKER", raising=False)
    mock_client = MagicMock()
    mock_client.close_all_positions.return_value = []
    with patch("tools.broker.get_trading_client", return_value=mock_client):
        assert liquidate_all_positions() == []


def test_guard_off_for_empty_string(monkeypatch):
    """Spec: empty string in `.env.example` is the production default — must NOT block."""
    monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", "")
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-empty"
    submitted.filled_avg_price = "150.00"
    mock_client.submit_order.return_value = submitted
    with patch("tools.broker.get_trading_client", return_value=mock_client):
        # Should NOT raise BrokerCallBlockedError.
        result = place_market_order("AMD", 1, "buy")
    assert result["order_id"] == "ord-empty"


def test_guard_off_for_falsy_strings(monkeypatch):
    """Common falsy strings ("0", "false", "no") must NOT activate the guard.

    Important so an operator who sets `CLAUDE_AGENT_NO_BROKER=false` to
    explicitly opt out gets the production behaviour they expect.
    """
    mock_client = MagicMock()
    submitted = MagicMock()
    submitted.id = "ord-falsy"
    submitted.filled_avg_price = "150.00"
    mock_client.submit_order.return_value = submitted
    for val in ("0", "false", "FALSE", "no", "anything-else"):
        monkeypatch.setenv("CLAUDE_AGENT_NO_BROKER", val)
        with patch("tools.broker.get_trading_client", return_value=mock_client):
            # Should NOT raise — guard is off for these values.
            result = place_market_order("AMD", 1, "buy")
        assert result["order_id"] == "ord-falsy"


# ---------------------------------------------------------------------------
# Conftest-fixture interaction sanity check.
# ---------------------------------------------------------------------------


def test_autouse_fixture_sets_env_var_by_default():
    """Inside a test that does NOT call `monkeypatch.delenv`, the autouse
    conftest fixture must have set CLAUDE_AGENT_NO_BROKER=1 already.
    Without this guarantee, the suite-wide safety net would be silently
    inactive and a forgotten mock could materialise a live order.
    """
    import os
    assert os.environ.get("CLAUDE_AGENT_NO_BROKER", "").lower() in ("1", "true", "yes")
