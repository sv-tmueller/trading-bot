from __future__ import annotations

import time

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from config import settings


class BrokerSubmitError(Exception):
    """Raised when Alpaca rejects an order submission (insufficient BP, wash-trade, halted, etc.).

    Also raised post-submit if the broker reports a terminal non-fill status
    (canceled / expired / rejected / suspended / stopped) so the caller's existing
    rejection path fires (notify, no DB row).
    """
    pass


class BrokerOcoSubmitError(Exception):
    """Raised when the post-fill OCO bracket submission fails (#133).

    The parent market order has already filled — the position is open without
    server-side protection. Caller (team_leader.place_order) catches this,
    notifies, and relies on the position monitor's soft-stop as the recovery
    path. The trade row is still written so the monitor can act on it.
    """
    pass


# Alpaca order statuses that mean "this order is never going to fill" — terminal
# non-fill outcomes that must surface to the caller as BrokerSubmitError so the
# existing rejection path in team_leader.place_order kicks in.
# `partially_filled` is intentionally NOT in this set: a partial fill IS a fill,
# and the broker's `filled_avg_price` is meaningful for the shares we got.
_TERMINAL_NON_FILL_STATUSES: frozenset = frozenset(
    {"canceled", "expired", "rejected", "suspended", "stopped"}
)
_TERMINAL_FILL_STATUSES: frozenset = frozenset({"filled", "partially_filled"})


def _order_status_str(order) -> str:
    """Coerce Alpaca SDK status (enum or str) to its lower-case string value."""
    status = getattr(order, "status", None)
    if status is None:
        return ""
    # OrderStatus enum exposes `.value`; raw strings pass through.
    val = getattr(status, "value", status)
    return str(val).lower()


def _poll_for_fill(client: TradingClient, order_id: str, ticker: str) -> tuple:
    """Poll `client.get_order_by_id` until terminal status or timeout.

    Returns (filled_avg_price_or_none, status_string). Caller handles the
    decision tree: filled → use price, terminal non-fill → raise, timeout →
    fall back to pre-order quote.

    Polling is bounded by `settings.FILL_POLL_TIMEOUT_S` (default 10s) and
    paced by `settings.FILL_POLL_INTERVAL_S` (default 0.5s). Market orders
    during regular hours typically resolve in <1s. We do NOT raise on poll
    errors mid-loop (transient broker hiccups shouldn't kill the order we
    already submitted) — we treat them as "no info this tick" and try again,
    falling back to timeout behaviour if the loop expires.
    """
    deadline = time.monotonic() + settings.FILL_POLL_TIMEOUT_S
    interval = settings.FILL_POLL_INTERVAL_S
    last_status = ""
    while time.monotonic() < deadline:
        try:
            order = client.get_order_by_id(order_id)
        except Exception as e:
            print(f"[poll_for_fill] {ticker} {order_id} get_order_by_id transient error: {e}")
            time.sleep(interval)
            continue
        last_status = _order_status_str(order)
        if last_status in _TERMINAL_FILL_STATUSES:
            avg = getattr(order, "filled_avg_price", None)
            return (float(avg) if avg is not None else None), last_status
        if last_status in _TERMINAL_NON_FILL_STATUSES:
            return None, last_status
        time.sleep(interval)
    return None, last_status  # timeout — last_status is whatever the broker last reported


def get_trading_client() -> TradingClient:
    return TradingClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
        paper=(settings.TRADING_MODE == "paper"),
    )


def place_parent_market_order(ticker: str, shares: int, side: str) -> dict:
    """Submit a plain (non-bracket) market order and poll for the fill.

    Returns ``{"order_id": str, "fill_price": float | None}``. On terminal
    non-fill status raises ``BrokerSubmitError`` — same contract as the legacy
    ``place_market_order`` non-bracket path. On poll timeout, ``fill_price`` is
    None and the caller is expected to fall back to a pre-order quote.

    This is the parent leg of the new (#133) two-step bracket flow:
    parent → poll → OCO bracket re-anchored to the actual fill price. Atomic
    Alpaca brackets are not used because they commit children to the
    pre-order quote at submission, breaking the realised-R:R invariant.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid order side: {side!r}. Must be 'buy' or 'sell'.")
    client = get_trading_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    request = MarketOrderRequest(
        symbol=ticker,
        qty=shares,
        side=order_side,
        time_in_force=TimeInForce.DAY,
    )
    try:
        order = client.submit_order(request)
    except Exception as e:
        print(f"[place_parent_market_order] ALPACA REJECTED {ticker} {side} {shares}: {e}")
        raise BrokerSubmitError(str(e)) from e

    order_id = str(order.id)

    # `submit_order` returns immediately; the fill confirmation comes async
    # (see #132 — Alpaca paper accepts in ~1 RTT, fills in another). Use the
    # response's filled_avg_price if Alpaca already populated it (rare on
    # paper), otherwise poll get_order_by_id until terminal status / timeout.
    initial_avg = getattr(order, "filled_avg_price", None)
    if initial_avg is not None:
        return {"order_id": order_id, "fill_price": float(initial_avg)}

    fill_price, terminal_status = _poll_for_fill(client, order_id, ticker)

    if terminal_status in _TERMINAL_NON_FILL_STATUSES:
        # Order will never fill → surface to caller as a broker-rejection so
        # the existing notify/no-DB-row path runs.
        msg = f"order {order_id} terminal status={terminal_status!r} (no fill)"
        print(f"[place_parent_market_order] ALPACA NON-FILL {ticker} {side} {shares}: {msg}")
        raise BrokerSubmitError(msg)

    if fill_price is None:
        # Timeout (or no `filled_avg_price` despite a fill status — defensive).
        # Don't raise: the order may still fill seconds later; we want the
        # trade row to exist with a best-effort fill_price (None → caller
        # falls back to pre-order quote and logs).
        print(
            f"[place_parent_market_order] FILL POLL TIMEOUT {ticker} {side} {shares} "
            f"order_id={order_id} last_status={terminal_status!r} after "
            f"{settings.FILL_POLL_TIMEOUT_S}s — caller will fall back to pre-order quote"
        )

    return {"order_id": order_id, "fill_price": fill_price}


def place_oco_brackets(
    ticker: str,
    shares: int,
    parent_side: str,
    take_profit_price: float,
    stop_price: float,
) -> dict:
    """Submit an OCO (one-cancels-other) bracket pair against an EXISTING position.

    Used post-fill (#133) so the take-profit limit and stop-loss are anchored
    to the actual filled price — not the pre-order quote — keeping realised
    R:R within ±5% of `RR_RATIO_MIN` regardless of fill drift.

    `parent_side` is the side of the parent (entry) order. The OCO is the
    OPPOSITE side: a long entry (`parent_side="buy"`) needs a sell-side OCO
    to close the position; a short entry needs a buy-side OCO to cover.

    Time-in-force is GTC so the protective legs survive across sessions until
    one fires (and cancels the other) — DAY would expire them at close.

    Raises `BrokerOcoSubmitError` if Alpaca rejects the OCO submission. The
    parent has already filled at this point, so the caller is responsible for
    surfacing the failure (notify_error) and recording the trade so the
    position monitor's soft-stop can act as the recovery layer.
    """
    if parent_side not in ("buy", "sell"):
        raise ValueError(f"Invalid parent_side: {parent_side!r}. Must be 'buy' or 'sell'.")
    if shares <= 0:
        raise ValueError(f"shares must be > 0 (got {shares})")
    if stop_price is None or stop_price <= 0:
        raise ValueError(f"stop_price must be > 0 (got {stop_price})")
    if take_profit_price is None or take_profit_price <= 0:
        raise ValueError(f"take_profit_price must be > 0 (got {take_profit_price})")

    client = get_trading_client()
    # Closing side is the opposite of the entry side.
    oco_side = OrderSide.SELL if parent_side == "buy" else OrderSide.BUY

    # Alpaca's OCO order_class requires a LimitOrderRequest envelope; the
    # take_profit leg's limit_price IS the parent limit_price (same value),
    # and the stop_loss leg holds the stop_price. Both legs share the same
    # qty as the parent fill.
    request = LimitOrderRequest(
        symbol=ticker,
        qty=shares,
        side=oco_side,
        time_in_force=TimeInForce.GTC,
        order_class=OrderClass.OCO,
        limit_price=round(take_profit_price, 2),
        take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
        stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
    )
    try:
        order = client.submit_order(request)
    except Exception as e:
        print(
            f"[place_oco_brackets] ALPACA REJECTED OCO {ticker} {oco_side} {shares} "
            f"stop={stop_price} target={take_profit_price}: {e}"
        )
        raise BrokerOcoSubmitError(str(e)) from e

    return {"order_id": str(order.id), "status": "submitted"}


def place_market_order(
    ticker: str,
    shares: int,
    side: str,
    stop_price: float = None,
    take_profit_price: float = None,
) -> dict:
    """Backwards-compatible wrapper around the new parent + OCO flow (#133).

    When both `stop_price` and `take_profit_price` are passed, this used to
    submit a single atomic Alpaca BRACKET order with the children anchored to
    the pre-order quote. That broke the realised-R:R invariant under fill
    drift (#133). The new flow:

    1. Submit just the parent market order via `place_parent_market_order`.
    2. Poll for the actual fill.
    3. If both bracket params were supplied, submit a separate OCO pair via
       `place_oco_brackets` using the SAME stop/target the caller passed in.
       Re-anchoring those values to the fill price is the caller's job
       (`agents/team_leader.place_order` does this so it keeps the bracket
       math in one place with the validation gate).

    If the OCO submission fails after a successful parent fill, raises
    `BrokerOcoSubmitError`. The return value still includes the parent
    `order_id` and `fill_price` so the caller can record the trade and let
    the position monitor's soft-stop act as the recovery layer.

    The shape of the return value is unchanged from #132:
    ``{"order_id": str, "fill_price": float | None}``.
    """
    parent = place_parent_market_order(ticker, shares, side)

    is_bracket = stop_price is not None and take_profit_price is not None
    if is_bracket and side == "buy" and parent.get("fill_price") is not None:
        # Submit OCO with the values the caller computed. team_leader is
        # expected to have re-anchored stop/target to `parent["fill_price"]`
        # before calling — the legacy code path that anchored against the
        # pre-order quote is what #133 specifically closes.
        place_oco_brackets(
            ticker=ticker,
            shares=shares,
            parent_side=side,
            take_profit_price=take_profit_price,
            stop_price=stop_price,
        )

    return parent


def close_position(ticker: str) -> str:
    client = get_trading_client()
    order = client.close_position(ticker)
    return str(order.id)


def cancel_all_orders() -> list[dict]:
    """Cancel every open order at the broker (parent + bracket children).

    Used by `main.py panic --cancel-orders`. Returns a list of cancelled order
    summaries — one row per order Alpaca attempted to cancel — so the panic CLI
    can report exactly what happened in the audit log and Discord ping. Raises
    on broker error so the panic command exits non-zero (the operator must see
    failures, never a silent swallow).
    """
    client = get_trading_client()
    responses = client.cancel_orders()
    return [
        {
            "order_id": str(getattr(r, "id", "")),
            "status": getattr(r, "status", None),
        }
        for r in (responses or [])
    ]


def liquidate_all_positions() -> list[dict]:
    """Market-close every open position and cancel any open orders.

    Used by `main.py panic --liquidate --confirm`. Calls
    `client.close_all_positions(cancel_orders=True)` so Alpaca takes care of
    cancelling the protective bracket child legs (take_profit + stop_loss)
    before issuing the market-close orders for each position. Returns a list of
    close-order summaries. Raises on broker error so the panic command exits
    non-zero.
    """
    client = get_trading_client()
    responses = client.close_all_positions(cancel_orders=True)
    return [
        {
            "symbol": getattr(r, "symbol", None),
            "order_id": str(getattr(r, "order_id", "") or ""),
            "status": getattr(r, "status", None),
        }
        for r in (responses or [])
    ]


def get_portfolio_value() -> float:
    client = get_trading_client()
    account = client.get_account()
    return float(account.portfolio_value)


def get_alpaca_positions() -> list[dict]:
    client = get_trading_client()
    positions = client.get_all_positions()
    return [
        {
            "ticker": pos.symbol,
            "qty": int(float(pos.qty)),  # whole shares only — bot never places fractional orders
            "avg_entry_price": float(pos.avg_entry_price),
        }
        for pos in positions
    ]


def get_current_price(ticker: str) -> float:
    data_client = StockHistoricalDataClient(
        settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY
    )
    feed = DataFeed.SIP if settings.DATA_FEED == "sip" else DataFeed.IEX
    request = StockLatestQuoteRequest(symbol_or_symbols=ticker, feed=feed)
    quote = data_client.get_stock_latest_quote(request)
    q = quote[ticker]
    bid = float(q.bid_price)
    ask = float(q.ask_price)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    raise ValueError(f"No valid quote for {ticker}: bid={bid}, ask={ask}")
