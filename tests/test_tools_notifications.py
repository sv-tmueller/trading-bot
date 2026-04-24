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
