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
    dry_run: bool = False,
) -> None:
    if dry_run:
        lines = [f"🧪 **Morning Scan (DRY RUN) — {date}**"]
    else:
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


def notify_paused(date_iso: str) -> None:
    _post(
        f"🛑 **Trading paused — {date_iso}**\n"
        f"⏭ Skipping morning scan (TRADING_PAUSED=true)"
    )


def notify_monitor(date: str, time: str, checked: int, closed: list) -> None:
    lines = [f"👁 **Position Monitor — {date} {time}**"]
    if checked == 0:
        lines.append("📭 No open positions")
    else:
        holding = checked - len(closed)
        lines.append(f"📊 {checked} position{'s' if checked != 1 else ''} checked — {holding} holding")
        for a in closed:
            lines.append(f"🔴 Closed {a.ticker} — {a.reason}")
    _post("\n".join(lines))


def notify_error(context: str, error: str) -> None:
    if len(error) <= 500:
        snippet = error
    else:
        snippet = error[:240] + "\n...\n" + error[-240:]
    _post(f"⚠️ **Bot Error — {context}**\n```{snippet}```")


def notify_order_rejected(ticker: str, shares: int, reason: str) -> None:
    _post(f"🛑 **Order rejected** — {ticker} {shares}sh\n{reason}")


def notify_panic(action: str, results: list, dry_run: bool = False) -> None:
    """Post a Discord alert summarising a `main.py panic` invocation.

    `action` is the human-readable headline ("cancel-orders", "liquidate",
    "pause", or a composite). `results` is a list of dicts (typically the
    return values of `cancel_all_orders` / `liquidate_all_positions`); each
    row is rendered as a single line. `dry_run=True` flags the alert as a
    preview — used by `--liquidate` without `--confirm`.
    """
    suffix = " (DRY RUN)" if dry_run else ""
    lines = [f"🛑 **PANIC — {action}**{suffix}"]
    if not results:
        lines.append("📭 nothing to do")
    else:
        lines.append(f"📊 {len(results)} item{'s' if len(results) != 1 else ''}:")
        for r in results:
            symbol = r.get("symbol") or r.get("ticker") or ""
            order_id = r.get("order_id") or r.get("id") or ""
            status = r.get("status")
            descriptor = " ".join(p for p in [symbol, str(order_id) if order_id else "", f"[{status}]" if status is not None else ""] if p)
            lines.append(f"• {descriptor or r}")
    _post("\n".join(lines))


def notify_performance_summary(stats: dict) -> None:
    days = stats["days"]
    trade_count = stats["trade_count"]
    if trade_count == 0:
        _post(f"📈 **Performance Summary** — no closed trades in the last {days} days")
        return
    _post(
        f"📈 **Performance Summary — trailing {days}d**\n"
        f"{trade_count} trades | Win rate: {stats['win_rate']:.1%} | "
        f"PnL: ${stats['total_pnl_dollars']:+.2f} | Avg R: {stats['avg_r_multiple']:+.2f}"
    )


def _fmt_optional(value, fmt: str, fallback: str = "n/a") -> str:
    if value is None:
        return fallback
    if value == float("inf"):
        return "∞"
    return format(value, fmt)


def notify_backtest(result: dict) -> None:
    params = result["params"]
    agg = result["aggregate"]
    pf = _fmt_optional(agg.get("profit_factor"), ".2f")
    wl = _fmt_optional(agg.get("winner_loser_ratio"), ".2f")
    exp = _fmt_optional(agg.get("expectancy_pct"), "+.2f")
    _post(
        f"📊 Backtest ({params['years']}y, EMA {params['ema_fast']}/{params['ema_slow']})\n"
        f"{agg['trades']} trades across {len(result['tickers'])} tickers\n"
        f"Win rate: {agg['win_rate'] * 100:.1f}% | "
        f"Return: {agg['total_return'] * 100:+.1f}% | "
        f"Max DD: {agg['max_drawdown'] * 100:.1f}%\n"
        f"Profit factor: {pf} | "
        f"Winner:Loser: {wl} | "
        f"Expectancy: {exp}%"
    )
