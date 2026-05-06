from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime, timezone
from config import settings
from tools.database import (
    get_open_trades,
    close_trade,
    insert_monitor_action,
    compute_daily_stat,
    upsert_daily_stat,
)
from tools.broker import (
    get_current_price,
    close_position as broker_close,
    get_alpaca_positions,
    get_portfolio_value,
)
from tools.notifications import notify_error


@dataclass
class MonitorAction:
    trade_id: int
    ticker: str
    action: str   # "hold" | "close" | "reconciled"
    reason: str   # "" | "stop_loss" | "take_profit" | "max_hold" | "broker_closed"
    current_price: float


def _action_type_for_row(action: MonitorAction) -> str:
    """Map the in-memory MonitorAction onto the persisted action_type enum.

    The schema enum is the authoritative set: stop_loss / take_profit /
    max_hold / reconciled / hold / skipped_error. close+<reason> collapses
    to the reason itself (so a stop_loss close becomes 'stop_loss', not
    'close'). Reconciled rows keep 'reconciled'. Hold + skipped_error reason
    becomes 'skipped_error' so analysts can filter transient failures.
    """
    if action.action == "reconciled":
        return "reconciled"
    if action.action == "close":
        return action.reason   # "stop_loss" | "take_profit" | "max_hold"
    if action.action == "hold" and action.reason == "skipped_error":
        return "skipped_error"
    return "hold"


def _persist_action_row(
    conn,
    action: MonitorAction,
    trade: dict,
    action_time: str,
) -> None:
    """Insert one monitor_actions row, swallowing DB errors so the loop continues.

    Per the issue (#131) the audit-trail write must NOT break the existing
    per-trade isolation guarantee in run_monitor — a DB write failure on one
    iteration fires notify_error and keeps the rest of the book moving. The
    snapshot uses post-trail values for stop_price (so a row written after
    _apply_trailing_stop reflects the just-ratcheted stop, matching what the
    monitor actually decided against).
    """
    try:
        insert_monitor_action(conn, {
            "trade_id": action.trade_id,
            "ticker": action.ticker,
            "action_time": action_time,
            "action_type": _action_type_for_row(action),
            "reason": action.reason or None,
            "current_price": action.current_price,
            "stop_price": trade.get("stop_loss"),
            "take_profit_price": trade.get("take_profit"),
        })
    except Exception as e:
        notify_error(
            "position_monitor",
            f"insert_monitor_action failed for {action.ticker} "
            f"(trade_id={action.trade_id}): {type(e).__name__}: {e}",
        )


def evaluate_position(
    position: dict,
    current_price: float,
    today: str,
    max_hold_days: int = None,
) -> MonitorAction:
    max_hold_days = max_hold_days if max_hold_days is not None else settings.MAX_HOLD_DAYS
    entry_date = datetime.strptime(position["entry_date"], "%Y-%m-%d").date()
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    hold_days = (today_date - entry_date).days

    if current_price <= position["stop_loss"]:
        return MonitorAction(position["id"], position["ticker"], "close", "stop_loss", current_price)
    if current_price >= position["take_profit"]:
        return MonitorAction(position["id"], position["ticker"], "close", "take_profit", current_price)
    if hold_days >= max_hold_days:
        return MonitorAction(position["id"], position["ticker"], "close", "max_hold", current_price)
    return MonitorAction(position["id"], position["ticker"], "hold", "", current_price)


def _reconcile_phantom_closes(
    conn,
    open_trades: list,
    today: str,
    live_positions: list = None,
) -> tuple[list, list]:
    """Detect trades the broker already closed (bracket child fired) and update DB.

    Bracket stops/targets execute server-side at Alpaca, so the broker may
    close a position between monitor runs. The DB still shows it open until we
    reconcile here. Returns (still_open_trades, reconciled_actions).

    `live_positions` (issue #134): callers that have already fetched broker
    positions for the cycle pass them in here so we don't double-call Alpaca.
    When None we fall back to fetching ourselves with the original fail-open
    semantics — kept as a second defense layer in case a future caller
    forgets to pre-fetch.
    """
    if live_positions is None:
        try:
            live_positions = get_alpaca_positions()
        except Exception:
            # Fail-open on reconciliation: better to run soft-stop on stale data
            # than skip the entire monitor cycle when Alpaca is unreachable.
            return open_trades, []

    live_tickers = {p["ticker"] for p in live_positions}
    still_open: list = []
    reconciled: list = []
    for trade in open_trades:
        if trade["ticker"] not in live_tickers:
            try:
                price = get_current_price(trade["ticker"])
            except Exception:
                price = trade["entry_price"]   # best-effort accounting
            entry_price = trade["entry_price"]
            stop_distance = entry_price - trade["stop_loss"]
            pnl_dollars = (price - entry_price) * trade["shares"]
            r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
            entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            today_date = datetime.strptime(today, "%Y-%m-%d").date()
            hold_days = (today_date - entry_date).days
            # Infer which bracket leg fired by comparing price to stop/target (0.5% slippage tolerance).
            if price <= trade["stop_loss"] * 1.005:
                exit_reason = "stop_loss"
            elif price >= trade["take_profit"] * 0.995:
                exit_reason = "take_profit"
            else:
                exit_reason = "manual"
            close_trade(conn, trade["id"], {
                "exit_date": today,
                "exit_price": price,
                "exit_reason": exit_reason,
                "pnl_dollars": round(pnl_dollars, 2),
                "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                "hold_days": hold_days,
                "r_multiple": round(r_multiple, 3),
            })
            action = MonitorAction(trade["id"], trade["ticker"], "reconciled", "broker_closed", price)
            _persist_action_row(conn, action, trade, datetime.now(timezone.utc).isoformat())
            reconciled.append(action)
        else:
            still_open.append(trade)
    return still_open, reconciled


def _apply_trailing_stop(conn, trade: dict, current_price: float) -> dict:
    """Ratchet trailing_high and stop_loss upward when TRAILING_STOP_ENABLED.

    Returns the (possibly mutated) trade dict so the caller can use the new
    stop_loss in the subsequent priority check. Stops only ratchet UP — never
    down. Falls back to the initial stop distance baked in at entry when a
    fresh ATR is not available.
    """
    if not settings.TRAILING_STOP_ENABLED:
        return trade

    entry_price = trade["entry_price"]
    initial_stop = trade["stop_loss"]
    initial_distance = entry_price - initial_stop
    if initial_distance <= 0:
        return trade

    # Use the initial stop distance (entry-time ATR × multiplier) as the
    # trailing distance. Cheap, deterministic, no extra data fetch — and the
    # original stop is already volatility-anchored.
    trail_distance = initial_distance

    prior_high = trade.get("trailing_high")
    new_high = max(prior_high or entry_price, current_price)

    proposed_stop = new_high - trail_distance
    new_stop = max(initial_stop, proposed_stop)

    updates = {}
    if new_high != (prior_high or entry_price) or prior_high is None:
        updates["trailing_high"] = new_high
    if new_stop > initial_stop:
        updates["stop_loss"] = new_stop

    if updates:
        sets = ", ".join(f"{k} = :{k}" for k in updates)
        conn.execute(
            f"UPDATE trades SET {sets} WHERE id = :id",
            {**updates, "id": trade["id"]},
        )
        conn.commit()
        # Reflect the update in the in-memory row so evaluate_position sees it.
        trade = {**trade, **updates}
    return trade


def _write_daily_stat(conn, today: str) -> None:
    """Upsert today's daily_stats row at the end of every monitor pass (issue #137).

    Called on every pass (not just the last cron of the day) because:
      1. ON CONFLICT(date) DO UPDATE makes repeated writes idempotent — each
         pass overwrites with the latest snapshot, so duplicates are harmless.
      2. End-of-pass is more robust than "only the last pass" — cron timing
         can shift (DST, queue delays) and we'd rather have a stat row that
         updates throughout the day than a missed write.

    Failure isolation: a daily-stats write failure must NEVER abort the
    monitor cron. Wrapped in its own try/except — fires notify_error and
    returns. Broker NAV failure is handled in two layers: get_portfolio_value
    fail -> portfolio_value=None (row still written); upsert fail ->
    notify_error and continue.
    """
    try:
        try:
            portfolio_value = get_portfolio_value()
        except Exception as e:
            # Broker outage: still write the row, just with NULL portfolio_value
            # (the trade-aggregation columns are local DB reads and don't need
            # the broker). Fail-soft per #137 punch list.
            notify_error(
                "position_monitor",
                f"get_portfolio_value failed during daily_stats upsert: "
                f"{type(e).__name__}: {e}",
            )
            portfolio_value = None
        stat = compute_daily_stat(conn, today, portfolio_value=portfolio_value)
        upsert_daily_stat(conn, stat)
    except Exception as e:
        notify_error(
            "position_monitor",
            f"daily_stats upsert failed for {today}: {type(e).__name__}: {e}",
        )


def run_monitor(conn, today: str = None) -> list:
    """Hourly check on open positions.

    Stops and targets now execute server-side at Alpaca via bracket orders.
    This monitor's primary jobs are:
      1. Reconcile broker-truth: if Alpaca already closed a position
         (bracket child fired), close it in the DB.
      2. Trigger max_hold exits — bracket orders can't enforce time limits.
      3. Soft stop/target check kept as defense-in-depth: if Alpaca's bracket
         leg fails to fill (broker outage, halted symbol), this is the backup.
         Keep redundant — costs nothing on the happy path.

    Top-of-loop broker fetch (issue #134): the FIRST broker call of the cycle
    is wrapped in its own try/except so a transient connection-reset / timeout
    aborts only THIS cycle, not the cron schedule. On failure we fire
    notify_error, return an empty action list, and skip the daily_stats upsert
    (which depends on broker NAV plus trade aggregation). The next hourly cron
    fire is the retry path — we explicitly do NOT retry inline. Historical
    evidence: monitor.log line "MONITOR ERROR: ('Connection aborted.',
    ConnectionResetError(104, 'Connection reset by peer'))" on 2026-05-04
    15:00 UTC — exactly the failure mode this guard addresses.
    """
    today = today or date_cls.today().isoformat()
    trades = get_open_trades(conn)

    # Step 0 (issue #134): pre-fetch broker positions ONCE at the top of the
    # cycle, isolated from the rest of the work. A failure here means we have
    # no broker truth for either the phantom-close reconciliation or any other
    # downstream check — there is nothing useful left to do this hour, so skip
    # the cycle cleanly. notify_error has its own rate-limit shape so a
    # sustained outage won't turn into a spam storm.
    try:
        live_positions = get_alpaca_positions()
    except Exception as exc:
        notify_error(
            "monitor",
            f"top-of-cycle broker fetch failed: {type(exc).__name__}: {exc}; "
            f"cycle skipped, retry next hour",
        )
        return []

    # Step 1: reconcile broker-side closures so we don't act on phantom rows.
    # Pass the pre-fetched positions in so we don't double-call Alpaca.
    trades, reconciled = _reconcile_phantom_closes(
        conn, trades, today, live_positions=live_positions
    )
    actions: list = list(reconciled)

    # Step 2 & 3: evaluate stop/target/max-hold for everything still open.
    # Each iteration is isolated: a transient broker/network error on one
    # ticker must not skip the soft-stop defense-in-depth for the rest.
    # Every iteration also writes exactly one monitor_actions row (issue #131)
    # — including the skipped_error branch so the cycle accounting is honest
    # even when the underlying broker call failed.
    for trade in trades:
        action_time = datetime.now(timezone.utc).isoformat()
        try:
            price = get_current_price(trade["ticker"])
            # Apply trailing-stop ratchet (no-op when TRAILING_STOP_ENABLED is false).
            trade = _apply_trailing_stop(conn, trade, price)
            action = evaluate_position(trade, price, today)

            if action.action == "close":
                broker_close(trade["ticker"])
                entry_price = trade["entry_price"]
                stop_distance = entry_price - trade["stop_loss"]
                r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
                pnl_dollars = (price - entry_price) * trade["shares"]
                entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
                today_date = datetime.strptime(today, "%Y-%m-%d").date()
                hold_days = (today_date - entry_date).days
                close_trade(conn, trade["id"], {
                    "exit_date": today,
                    "exit_price": price,
                    "exit_reason": action.reason,
                    "pnl_dollars": round(pnl_dollars, 2),
                    "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                    "hold_days": hold_days,
                    "r_multiple": round(r_multiple, 3),
                })

            _persist_action_row(conn, action, trade, action_time)
            actions.append(action)
        except Exception as e:
            notify_error(
                "position_monitor",
                f"Skipping {trade['ticker']} (id={trade['id']}): {type(e).__name__}: {e}",
            )
            skipped = MonitorAction(trade["id"], trade["ticker"], "hold", "skipped_error", 0.0)
            _persist_action_row(conn, skipped, trade, action_time)
            actions.append(skipped)

    # End-of-pass: upsert today's daily_stats row (issue #137). Idempotent
    # over the day — each pass overwrites the same row with the latest
    # snapshot. Wrapped in its own helper so a write failure here does NOT
    # abort the monitor cron (mirrors the per-trade isolation pattern).
    _write_daily_stat(conn, today)

    return actions
