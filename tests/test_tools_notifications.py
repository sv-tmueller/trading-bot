from __future__ import annotations


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


def test_notify_regime_flip_payload_carries_message_field(mocker):
    """The structured-event payload must include a non-empty `message` string so
    the n8n flow's `{{ $json.body.message }}` Discord template renders something."""
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

    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert isinstance(payload.get("message"), str)
    assert payload["message"]
    # Message should mention the ticker and target state so the operator can
    # tell what the alert is about without expanding the JSON body.
    assert "WSPL.DE" in payload["message"]
    assert "LONG" in payload["message"]


def test_notify_regime_flip_dry_run_message_carries_dry_run_marker(mocker):
    """In dry-run the `message` body must carry the [DRY-RUN] prefix too — not just
    the title — because Discord cards bind to `message`, not `title`."""
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

    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert "[DRY-RUN]" in payload["message"]


def test_notify_kill_switch_fired_payload_carries_message_field(mocker):
    """notify_kill_switch_fired payload must include a non-empty Discord-renderable
    `message` field with the ticker and drawdown context."""
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

    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert isinstance(payload.get("message"), str)
    assert payload["message"]
    assert "WSPL.DE" in payload["message"]


def test_notify_trade_failed_payload_carries_message_field(mocker):
    """notify_trade_failed payload must include a non-empty Discord-renderable
    `message` field with the symbol/side/reason."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_trade_failed

    notify_trade_failed(
        symbol="WSPL.DE",
        side="BUY",
        qty=100,
        reason="insufficient_buying_power",
    )

    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert isinstance(payload.get("message"), str)
    assert payload["message"]
    assert "WSPL.DE" in payload["message"]
    assert "insufficient_buying_power" in payload["message"]


def test_notify_tws_disconnected_payload_carries_message_field(mocker):
    """notify_tws_disconnected payload must include a non-empty Discord-renderable
    `message` field with the host:port context."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_tws_disconnected

    notify_tws_disconnected(
        host="127.0.0.1",
        port=4002,
        attempts=3,
        error_msg="connect refused",
    )

    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert isinstance(payload.get("message"), str)
    assert payload["message"]
    assert "127.0.0.1" in payload["message"]
    assert "4002" in payload["message"]


def test_notify_state_desync_payload_carries_message_field(mocker):
    """notify_state_desync payload must include a non-empty Discord-renderable
    `message` field with the symbol and DB-vs-broker delta."""
    mocker.patch("tools.notifications.settings.N8N_WEBHOOK_URL", "http://localhost:5678/webhook")
    mock_urlopen = mocker.patch("tools.notifications.urllib.request.urlopen")
    from tools.notifications import notify_state_desync

    notify_state_desync(
        db_state="LONG",
        broker_state="CASH",
        symbol="WSPL.DE",
        action_taken="DB updated to CASH",
    )

    payload = _decode_dict_payload(mock_urlopen.call_args[0][0])
    assert isinstance(payload.get("message"), str)
    assert payload["message"]
    assert "WSPL.DE" in payload["message"]
    assert "LONG" in payload["message"]
    assert "CASH" in payload["message"]


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
