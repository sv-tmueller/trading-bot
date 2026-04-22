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
    except urllib.error.URLError:
        pass  # never let a notification failure crash the bot


def notify_scan_complete(
    date: str,
    market_context: str,
    candidates_found: int,
    approved: int,
    rejected: int,
    decisions: list,
    cost_usd: float,
) -> None:
    lines = [f"🤖 **Morning Scan — {date}**"]
    lines.append(f"📈 Market: {market_context}")
    lines.append(f"📊 Candidates: {candidates_found} found | ✅ Approved: {approved} | ❌ Rejected: {rejected}")
    for d in decisions:
        action = d.get("action", "").upper()
        ticker = d.get("ticker", "")
        shares = d.get("shares", "")
        emoji = "🟢" if action == "BUY" else "🔴"
        lines.append(f"{emoji} {action} {ticker} — {shares} shares")
    lines.append(f"💰 Token cost: ${cost_usd:.4f}")
    _post("\n".join(lines))


def notify_no_candidates(date: str, reason: str, cost_usd: float) -> None:
    _post(
        f"🤖 **Morning Scan — {date}**\n"
        f"⏭ No trade candidates: {reason}\n"
        f"💰 Token cost: ${cost_usd:.4f}"
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
