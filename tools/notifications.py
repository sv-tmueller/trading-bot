from __future__ import annotations

import urllib.request
import urllib.error
import json
from config import settings


def _post(payload) -> None:
    """POST a payload to the n8n webhook, silently no-op'ing if it's unset.

    Two payload shapes are supported:
    - **dict** — serialised verbatim. Used by the rules-engine pivot's
      structured event types (#196), which encode `event_type` plus
      event-specific fields so downstream automations can route on shape.
    - **str** — wrapped as ``{"message": <str>}`` before serialising.
      Preserved for backwards compatibility with the legacy notifiers
      (``notify_scan_complete``, ``notify_error``, ``notify_panic`` etc.)
      which all post free-form Discord-style strings.
    """
    if not settings.N8N_WEBHOOK_URL:
        return
    if isinstance(payload, dict):
        body = json.dumps(payload).encode()
    else:
        body = json.dumps({"message": payload}).encode()
    req = urllib.request.Request(
        settings.N8N_WEBHOOK_URL,
        data=body,
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
    order_outcomes: dict = None,
) -> None:
    """Post the morning-scan summary to Discord.

    `approved` and `rejected` are deterministic per-ticker counts (issue #139):
    `approved` = orders the broker accepted (or "would accept" in dry-run);
    `rejected` = orders blocked by the safety stack (exposure gate, invalid
    bracket, broker submit error). `order_outcomes`, when provided, is the
    per-ticker dict from `team_leader.run()` and unlocks per-ticker BUY/SELL
    rendering anchored to the deterministic ledger rather than the LLM's prose
    `decisions` list. Falls back to the legacy `decisions`-driven rendering
    when `order_outcomes` is None so old callers (and tests) still work.
    """
    if dry_run:
        lines = [f"🧪 **Morning Scan (DRY RUN) — {date}**"]
    else:
        lines = [f"🤖 **Morning Scan — {date}**"]
    lines.append(f"📈 {tldr or market_context}")
    if order_outcomes is not None:
        # Deterministic rendering — one line per actual broker outcome.
        for entry in order_outcomes.get("buy", []):
            lines.append(f"🟢 BUY {entry['ticker']} — {entry['shares']} shares")
        for entry in order_outcomes.get("sell", []):
            lines.append(f"🔴 SELL {entry['ticker']} — {entry['shares']} shares")
        if dry_run:
            for entry in order_outcomes.get("dry_run", []):
                action = entry.get("side", "buy").upper()
                emoji = "🟢" if action == "BUY" else "🔴"
                lines.append(f"{emoji} {action} {entry['ticker']} — {entry['shares']} shares (DRY RUN)")
    else:
        # Legacy path — reads the LLM's `decisions` list. Kept for backwards
        # compatibility but considered untrusted (issue #139).
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


# ---------------------------------------------------------------------------
# Rules-engine pivot (#196): structured-payload event types.
#
# Each helper posts a JSON dict ({"event_type": "...", ...fields}) so the
# n8n flow downstream can route on shape rather than parsing free-form
# Discord prose. Keyword-only signatures keep call sites self-documenting.
# ---------------------------------------------------------------------------


def notify_regime_flip(
    *,
    target_state: str,
    spy_close: float,
    spy_sma200: float,
    ticker: str,
    fill_price: float,
    qty: int,
    account_value: float,
) -> None:
    """Emitted whenever the SPY/SMA200 regime filter flips state and we trade
    on it (LONG entry or CASH exit). Includes the SPY snapshot that drove the
    decision plus the resulting fill so downstream audit can reconcile.
    """
    _post({
        "event_type": "regime_flip",
        "target_state": target_state,
        "spy_close": spy_close,
        "spy_sma200": spy_sma200,
        "ticker": ticker,
        "fill_price": fill_price,
        "qty": qty,
        "account_value": account_value,
    })


def notify_kill_switch_fired(
    *,
    ticker: str,
    drawdown_pct: float,
    ref_high: float,
    last_price: float,
    qty: int,
    fill_price: float,
) -> None:
    """Emitted when the per-position drawdown kill switch closes a holding.
    `drawdown_pct` is signed (negative for a loss); `ref_high` is the high-
    water mark used as the drawdown reference.
    """
    _post({
        "event_type": "kill_switch_fired",
        "ticker": ticker,
        "drawdown_pct": drawdown_pct,
        "ref_high": ref_high,
        "last_price": last_price,
        "qty": qty,
        "fill_price": fill_price,
    })


def notify_trade_failed(
    *,
    symbol: str,
    side: str,
    qty: int,
    reason: str,
) -> None:
    """Emitted when the broker rejects an order. `reason` is the broker's
    (or our pre-submit gate's) machine-readable code, e.g.
    ``"insufficient_buying_power"``.
    """
    _post({
        "event_type": "trade_failed",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "reason": reason,
    })


def notify_tws_disconnected(
    *,
    host: str,
    port: int,
    attempts: int,
    error_msg: str,
) -> None:
    """Emitted when the IBKR TWS/Gateway connection cannot be re-established
    after `attempts` retries. `error_msg` is the last error string from the
    underlying client.
    """
    _post({
        "event_type": "tws_disconnected",
        "host": host,
        "port": port,
        "attempts": attempts,
        "error_msg": error_msg,
    })


def notify_state_desync(
    *,
    db_state: str,
    broker_state: str,
    symbol: str,
    action_taken: str,
) -> None:
    """Emitted when the persisted `regime_state` (DB) disagrees with broker
    truth on reconciliation. `action_taken` describes the corrective step
    the bot performed (e.g. ``"DB updated to CASH"``).
    """
    _post({
        "event_type": "state_desync",
        "db_state": db_state,
        "broker_state": broker_state,
        "symbol": symbol,
        "action_taken": action_taken,
    })
