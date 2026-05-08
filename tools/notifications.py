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
      Preserved for ``notify_error`` and ``notify_panic`` which both post
      free-form Discord-style strings.
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


def notify_error(context: str, error: str) -> None:
    if len(error) <= 500:
        snippet = error
    else:
        snippet = error[:240] + "\n...\n" + error[-240:]
    _post(f"⚠️ **Bot Error — {context}**\n```{snippet}```")


def notify_panic(action: str, results: list, dry_run: bool = False) -> None:
    """Post a Discord alert summarising a `main.py panic` invocation.

    `action` is the human-readable headline ("cancel-orders", "liquidate",
    "pause", or a composite). `results` is a list of dicts (typically the
    return values of `cancel_all_orders` / liquidate); each row is rendered
    as a single line. `dry_run=True` flags the alert as a preview — used by
    `--liquidate` without `--confirm`.
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
    dry_run: bool = False,
) -> None:
    """Emitted whenever the SPY/SMA200 regime filter flips state and we trade
    on it (LONG entry or CASH exit). Includes the SPY snapshot that drove the
    decision plus the resulting fill so downstream audit can reconcile.

    When ``dry_run=True``, the payload includes ``dry_run: true`` and the
    ``title`` field is prefixed with ``[DRY-RUN]`` so n8n / Discord templates
    can branch on it. Used by ``daily_check.py --dry-run`` to publish a
    hypothetical flip alert during the soak window without placing an order.
    """
    title_prefix = "[DRY-RUN] " if dry_run else ""
    _post({
        "event_type": "regime_flip",
        "title": f"{title_prefix}regime_flip {target_state}",
        "target_state": target_state,
        "spy_close": spy_close,
        "spy_sma200": spy_sma200,
        "ticker": ticker,
        "fill_price": fill_price,
        "qty": qty,
        "account_value": account_value,
        "dry_run": dry_run,
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
