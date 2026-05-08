from __future__ import annotations

from unittest.mock import MagicMock


def test_post_skips_when_no_webhook_url(mocker):
    """_post must return silently when N8N_WEBHOOK_URL is not set."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import _post
    _post("hello")
    mock_urlopen.assert_not_called()


def test_post_sends_when_webhook_url_set(mocker):
    """_post must call urlopen when N8N_WEBHOOK_URL is configured."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import _post
    _post("hello")
    mock_urlopen.assert_called_once()


def test_post_swallows_network_errors(mocker):
    """_post must not raise even if urlopen throws."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mocker.patch("tools.notifications.urllib.request.urlopen", side_effect=Exception("timeout"))
    from tools.notifications import _post
    _post("hello")  # must not raise


def test_notify_scan_complete_includes_date_and_decisions(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_scan_complete
    notify_scan_complete(
        date="2026-04-24",
        market_context="bullish",
        tldr="AMD crossover",
        approved=1,
        rejected=2,
        decisions=[{"action": "buy", "ticker": "AMD", "shares": 10}],
        cost_usd=0.0042,
    )
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "2026-04-24" in msg
    assert "AMD" in msg
    assert "1 approved" in msg
    assert "2 rejected" in msg
    assert "0.0042" in msg


def test_notify_scan_complete_dry_run_marks_header(mocker):
    """When dry_run=True the posted header must carry the 🧪 marker and the words 'DRY RUN'."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_scan_complete

    notify_scan_complete(
        date="2026-05-04",
        market_context="bullish",
        tldr="AMD crossover",
        approved=1,
        rejected=0,
        decisions=[{"action": "buy", "ticker": "AMD", "shares": 41}],
        cost_usd=0.1521,
        dry_run=True,
    )

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    import json
    posted = json.loads(req.data.decode())["message"]
    assert "🧪" in posted
    assert "DRY RUN" in posted
    assert "2026-05-04" in posted


def test_notify_scan_complete_default_has_no_dry_run_marker(mocker):
    """With dry_run omitted (default False) the message must remain the live-scan format."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_scan_complete

    notify_scan_complete(
        date="2026-05-04",
        market_context="bullish",
        tldr="AMD crossover",
        approved=1,
        rejected=0,
        decisions=[{"action": "buy", "ticker": "AMD", "shares": 41}],
        cost_usd=0.1521,
    )

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    import json
    posted = json.loads(req.data.decode())["message"]
    assert "🧪" not in posted
    assert "DRY RUN" not in posted
    assert "🤖" in posted


def test_notify_scan_complete_with_order_outcomes_renders_buys_and_sells(mocker):
    """Issue #139: when order_outcomes is supplied, message body comes from the deterministic ledger."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_scan_complete

    notify_scan_complete(
        date="2026-05-05",
        market_context="bullish",
        tldr="3 candidates",
        approved=2,
        rejected=2,
        decisions=[],   # LLM decisions list is now ignored when outcomes are supplied
        cost_usd=0.1253,
        order_outcomes={
            "buy": [{"ticker": "AMD", "shares": 50}, {"ticker": "MSFT", "shares": 50}],
            "sell": [],
            "rejected": [
                {"ticker": "AAPL", "shares": 101, "side": "buy", "reason": "exposure cap"},
                {"ticker": "SHEL", "shares": 358, "side": "buy", "reason": "exposure cap"},
            ],
            "dry_run": [],
        },
    )
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "BUY AMD" in msg
    assert "BUY MSFT" in msg
    # Ground-truth count must reflect the deterministic outcomes — 2 approved / 2 rejected
    # (matching what notify_order_rejected actually fired earlier in the scan).
    assert "2 approved" in msg
    assert "2 rejected" in msg


def test_notify_scan_complete_with_order_outcomes_ignores_llm_decisions_list(mocker):
    """Issue #139: even if the LLM hallucinates decisions, the body uses outcomes['buy']."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_scan_complete

    # The 2026-05-04 hallucination shape: LLM says AMD was placed, but the
    # deterministic safety stack rejected it.
    hallucinated_decisions = [
        {"ticker": "AMD", "action": "buy", "shares": 41, "reasoning": "Full go decision"},
    ]
    notify_scan_complete(
        date="2026-05-04",
        market_context="bullish",
        tldr="AMD",
        approved=0,
        rejected=1,
        decisions=hallucinated_decisions,
        cost_usd=0.05,
        order_outcomes={
            "buy": [],   # ground truth
            "sell": [],
            "rejected": [{"ticker": "AMD", "shares": 41, "side": "buy", "reason": "exposure cap"}],
            "dry_run": [],
        },
    )
    msg = mock_post.call_args[0][0]
    # AMD must NOT appear as a placed BUY (LLM lie was that it was bought).
    assert "BUY AMD" not in msg
    assert "0 approved" in msg
    assert "1 rejected" in msg


def test_notify_scan_complete_dry_run_outcomes_render_with_dry_run_marker(mocker):
    """Dry-run outcomes are marked so the operator sees they're hypothetical."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_scan_complete

    notify_scan_complete(
        date="2026-05-06",
        market_context="bullish",
        tldr="dry-run candidate",
        approved=1,
        rejected=0,
        decisions=[],
        cost_usd=0.01,
        dry_run=True,
        order_outcomes={
            "buy": [],
            "sell": [],
            "rejected": [],
            "dry_run": [{"ticker": "AMD", "shares": 50, "side": "buy"}],
        },
    )
    msg = mock_post.call_args[0][0]
    assert "🧪" in msg
    assert "DRY RUN" in msg
    # The hypothetical AMD line is present and tagged.
    assert "AMD" in msg


def test_notify_scan_complete_legacy_path_still_works_without_outcomes(mocker):
    """Backwards compatibility: callers that don't pass order_outcomes still get the old behaviour."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_scan_complete

    # No order_outcomes → falls back to rendering the LLM decisions list (legacy).
    notify_scan_complete(
        date="2026-04-24",
        market_context="bullish",
        tldr="legacy",
        approved=1,
        rejected=0,
        decisions=[{"action": "buy", "ticker": "AMD", "shares": 10}],
        cost_usd=0.001,
    )
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "BUY AMD" in msg
    assert "10 shares" in msg


def test_notify_no_candidates_includes_tldr(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_no_candidates
    notify_no_candidates("2026-04-24", "RSI overextended", ["NVDA"], 0.0012)
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "RSI overextended" in msg
    assert "NVDA" in msg
    assert "0.0012" in msg


def test_notify_no_approved_includes_date(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_no_approved
    notify_no_approved("2026-04-24", 0.0021)
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "2026-04-24" in msg
    assert "No trades approved" in msg
    assert "0.0021" in msg


def test_notify_paused_posts_to_webhook(mocker):
    """notify_paused must post a single 'Trading paused' message to the webhook."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_paused
    notify_paused("2026-04-29")
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "2026-04-29" in msg
    assert "Trading paused" in msg


def test_notify_paused_swallows_errors_via_post(mocker):
    """notify_paused must fail silently when the webhook call errors (matches other helpers)."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mocker.patch("tools.notifications.urllib.request.urlopen", side_effect=Exception("timeout"))
    from tools.notifications import notify_paused
    notify_paused("2026-04-29")  # must not raise


def test_notify_monitor_no_positions(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_monitor
    notify_monitor("2026-04-24", "14:00", 0, [])
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "No open positions" in msg


def test_notify_monitor_with_closed_position(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_monitor
    closed = MagicMock()
    closed.ticker = "AMD"
    closed.reason = "stop_loss"
    notify_monitor("2026-04-24", "15:00", 1, [closed])
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "AMD" in msg
    assert "stop_loss" in msg


def test_notify_error_includes_context(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_error
    notify_error("morning_scan", "Traceback: something went wrong")
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "morning_scan" in msg
    assert "something went wrong" in msg


def test_notify_error_long_traceback_keeps_head_and_tail(mocker):
    """Long tracebacks must show both the entry frame (head) and the exception line (tail)."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_error

    head_marker = "Traceback (most recent call last):\n  File \"/opt/trading-bot/main.py\", line 136, in run_morning_scan"
    filler = "\n".join(
        f"  File \"/opt/trading-bot/agents/frame_{i}.py\", line {i}, in some_function"
        for i in range(80)
    )
    tail_marker = "ZeroDivisionError: float division by zero"
    long_traceback = head_marker + "\n" + filler + "\n" + tail_marker
    assert len(long_traceback) > 1500

    notify_error("morning_scan", long_traceback)

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    import json
    posted = json.loads(req.data.decode())["message"]
    assert "morning_scan" in posted
    assert "run_morning_scan" in posted
    assert tail_marker in posted
    assert "\n...\n" in posted


def test_notify_error_long_traceback_total_length_bounded(mocker):
    """Posted message length must stay bounded even for very large tracebacks."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_error

    notify_error("morning_scan", "X" * 5000)

    req = mock_urlopen.call_args[0][0]
    import json
    posted = json.loads(req.data.decode())["message"]
    assert len(posted) <= 525


def test_notify_order_rejected_includes_ticker_and_reason(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_order_rejected
    notify_order_rejected("AMD", 100, "exposure cap breached (25% > 20%)")
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "AMD" in msg
    assert "100" in msg
    assert "exposure cap breached" in msg


def test_notify_panic_includes_action_and_results(mocker):
    """notify_panic posts a 🛑 alert with the action name and a per-row summary."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_panic
    results = [
        {"symbol": "AMD", "order_id": "close-1", "status": 207},
        {"symbol": "NVDA", "order_id": "close-2", "status": 207},
    ]
    notify_panic("liquidate", results)
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "PANIC" in msg
    assert "liquidate" in msg
    assert "AMD" in msg
    assert "NVDA" in msg
    assert "DRY RUN" not in msg


def test_notify_panic_dry_run_marker(mocker):
    """When dry_run=True the headline must include DRY RUN."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_panic
    notify_panic("liquidate", [{"ticker": "AMD"}], dry_run=True)
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "DRY RUN" in msg
    assert "AMD" in msg


def test_notify_panic_empty_results_renders_nothing_to_do(mocker):
    """No work items must still produce a single ping (so the operator gets confirmation)."""
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_panic
    notify_panic("cancel-orders", [])
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "PANIC" in msg
    assert "cancel-orders" in msg
    assert "nothing to do" in msg


def test_notify_panic_swallows_post_errors(mocker):
    """notify_panic must not raise even if the webhook call fails (matches other helpers)."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mocker.patch("tools.notifications.urllib.request.urlopen", side_effect=Exception("timeout"))
    from tools.notifications import notify_panic
    notify_panic("pause", [{"status": "ok"}])  # must not raise


def test_notify_performance_summary_calls_post(mocker):
    mock_post = mocker.patch("tools.notifications._post")
    from tools.notifications import notify_performance_summary
    stats = {
        "days": 30,
        "trade_count": 5,
        "win_count": 3,
        "loss_count": 2,
        "win_rate": 0.6,
        "total_pnl_dollars": 250.0,
        "avg_r_multiple": 1.5,
    }
    notify_performance_summary(stats)
    mock_post.assert_called_once()
    msg = mock_post.call_args[0][0]
    assert "trailing 30d" in msg
    assert "5 trades" in msg
    assert "60.0%" in msg
    assert "+250.00" in msg
    assert "+1.50" in msg


# ---------------------------------------------------------------------------
# Rules-engine pivot (#196): structured-payload event types
#
# These helpers post JSON dicts (not free-form strings) to the n8n webhook so
# downstream automations can route on `event_type` rather than parsing prose.
# ---------------------------------------------------------------------------


def _decode_dict_payload(req):
    """Read the dict payload posted to urlopen back into a dict."""
    import json
    return json.loads(req.data.decode())


def test_notify_regime_flip_long_payload(mocker):
    """notify_regime_flip emits an event_type='regime_flip' JSON payload with the SPY/regime context."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_regime_flip

    notify_regime_flip(
        target_state="LONG",
        spy_close=400.0,
        spy_sma200=380.0,
        ticker="WSPL.DE",
        fill_price=50.0,
        qty=100,
        account_value=10000.0,
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload["event_type"] == "regime_flip"
    assert payload["target_state"] == "LONG"
    assert payload["ticker"] == "WSPL.DE"
    assert payload["fill_price"] == 50.0
    assert payload["spy_close"] == 400.0
    assert payload["spy_sma200"] == 380.0
    assert payload["qty"] == 100
    assert payload["account_value"] == 10000.0


def test_notify_regime_flip_dry_run_marks_payload(mocker):
    """When dry_run=True the payload must carry dry_run: true and a [DRY-RUN] title prefix."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_regime_flip

    notify_regime_flip(
        target_state="LONG",
        spy_close=400.0,
        spy_sma200=380.0,
        ticker="WSPL.DE",
        fill_price=50.0,
        qty=100,
        account_value=10000.0,
        dry_run=True,
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload["event_type"] == "regime_flip"
    assert payload["dry_run"] is True
    assert payload.get("title", "").startswith("[DRY-RUN]")


def test_notify_regime_flip_default_has_no_dry_run(mocker):
    """With dry_run omitted (default False) the payload's dry_run field is False
    and the title has no [DRY-RUN] prefix."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_regime_flip

    notify_regime_flip(
        target_state="LONG",
        spy_close=400.0,
        spy_sma200=380.0,
        ticker="WSPL.DE",
        fill_price=50.0,
        qty=100,
        account_value=10000.0,
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload.get("dry_run", False) is False
    assert not payload.get("title", "").startswith("[DRY-RUN]")


def test_notify_kill_switch_fired_payload(mocker):
    """notify_kill_switch_fired emits the drawdown context required for post-trade audit."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_kill_switch_fired

    notify_kill_switch_fired(
        ticker="WSPL.DE",
        drawdown_pct=-0.27,
        ref_high=68.5,
        last_price=50.0,
        qty=100,
        fill_price=49.5,
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload["event_type"] == "kill_switch_fired"
    assert payload["drawdown_pct"] == -0.27
    assert payload["fill_price"] == 49.5
    assert payload["ticker"] == "WSPL.DE"
    assert payload["ref_high"] == 68.5
    assert payload["last_price"] == 50.0
    assert payload["qty"] == 100


def test_notify_trade_failed_payload(mocker):
    """notify_trade_failed emits the broker-rejection reason so the operator can triage."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_trade_failed

    notify_trade_failed(
        symbol="WSPL.DE",
        side="BUY",
        qty=100,
        reason="insufficient_buying_power",
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload["event_type"] == "trade_failed"
    assert payload["reason"] == "insufficient_buying_power"
    assert payload["symbol"] == "WSPL.DE"
    assert payload["side"] == "BUY"
    assert payload["qty"] == 100


def test_notify_tws_disconnected_payload(mocker):
    """notify_tws_disconnected emits the IBKR-connection failure context."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_tws_disconnected

    notify_tws_disconnected(
        host="127.0.0.1",
        port=4002,
        attempts=3,
        error_msg="connect refused",
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload["event_type"] == "tws_disconnected"
    assert payload["attempts"] == 3
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 4002
    assert payload["error_msg"] == "connect refused"


def test_notify_state_desync_payload(mocker):
    """notify_state_desync emits the DB-vs-broker delta and the corrective action taken."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_state_desync

    notify_state_desync(
        db_state="LONG",
        broker_state="CASH",
        symbol="WSPL.DE",
        action_taken="DB updated to CASH",
    )

    mock_urlopen.assert_called_once()
    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert payload["event_type"] == "state_desync"
    assert payload["db_state"] == "LONG"
    assert payload["broker_state"] == "CASH"
    assert payload["symbol"] == "WSPL.DE"
    assert payload["action_taken"] == "DB updated to CASH"


def test_silent_when_webhook_unset(mocker):
    """When N8N_WEBHOOK_URL is empty, structured-payload notifiers must not raise or call urlopen."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_regime_flip

    notify_regime_flip(
        target_state="LONG",
        spy_close=400.0,
        spy_sma200=380.0,
        ticker="WSPL.DE",
        fill_price=50.0,
        qty=100,
        account_value=10000.0,
    )  # must not raise

    mock_urlopen.assert_not_called()
