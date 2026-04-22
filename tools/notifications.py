from __future__ import annotations

import urllib.request
import urllib.error
import json
from config import settings


def _post(message: str) -> None:
    if not settings.N8N_WEBHOOK_URL:
        return
    payload = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        settings.N8N_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[notifications] failed to send: {e}")


def notify_scan_complete(
    date: str,
    market_context: str,
    tldr: str,
    approved: int,
    rejected: int,
    decisions: list,
    cost_usd: float,
) -> None:
    lines = [f"🤖 **Morning Scan — {date}**"]
    lines.append(f"📈 {tldr or market_context}")
    for d in decisions:
        action = d.get("action", "").upper()
        ticker = d.get("ticker", "")
        shares = d.get("shares", "")
        emoji = "🟢" if action == "BUY" else "🔴"
        lines.append(f"{emoji} {action} {ticker} — {shares} shares")
    lines.append(f"✅ {approved} approved | ❌ {rejected} rejected | 💰 ${cost_usd:.4f}")
    _post("\n".join(lines))


def notify_no_candidates(date: str, tldr: str, tickers_to_watch: list, cost_usd: float) -> None:
    watch = ", ".join(tickers_to_watch) if tickers_to_watch else "none"
    _post(
        f"🤖 **Morning Scan — {date}**\n"
        f"⏭ No trades today — {tldr}\n"
        f"👀 Watch: {watch}\n"
        f"💰 ${cost_usd:.4f}"
    )


def notify_no_approved(date: str, cost_usd: float) -> None:
    _post(
        f"🤖 **Morning Scan — {date}**\n"
        f"🚫 No trades approved by risk review\n"
        f"💰 Token cost: ${cost_usd:.4f}"
    )


def notify_monitor(date: str, time: str, checked: int, closed: list) -> None:
    if closed:
        lines = [f"👁 **Position Monitor — {date} {time}**"]
        for a in closed:
            lines.append(f"🔴 Closed {a.ticker} — {a.reason}")
        _post("\n".join(lines))
    # stay silent when nothing happened — no noise for routine checks


def notify_error(context: str, error: str) -> None:
    _post(f"⚠️ **Bot Error — {context}**\n```{error[:500]}```")
