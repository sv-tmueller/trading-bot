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
