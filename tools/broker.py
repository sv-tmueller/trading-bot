from __future__ import annotations

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from config import settings


class BrokerSubmitError(Exception):
    """Raised when Alpaca rejects an order submission (insufficient BP, wash-trade, halted, etc.)."""
    pass


def get_trading_client() -> TradingClient:
    return TradingClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
        paper=(settings.TRADING_MODE == "paper"),
    )


def place_market_order(
    ticker: str,
    shares: int,
    side: str,
    stop_price: float = None,
    take_profit_price: float = None,
) -> dict:
    """Submit a market order. If both stop_price and take_profit_price are given, submit as a bracket order so stops/targets live broker-side."""
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid order side: {side!r}. Must be 'buy' or 'sell'.")
    client = get_trading_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    is_bracket = stop_price is not None and take_profit_price is not None
    if is_bracket:
        # Bracket orders need GTC because parent + child legs persist across days
        # until take_profit or stop_loss fires; DAY would cancel children at close.
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=order_side,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
        )
    else:
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
    try:
        order = client.submit_order(request)
    except Exception as e:
        print(f"[place_market_order] ALPACA REJECTED {ticker} {side} {shares}: {e}")
        raise BrokerSubmitError(str(e)) from e
    fill_price = float(order.filled_avg_price) if order.filled_avg_price is not None else None
    return {"order_id": str(order.id), "fill_price": fill_price}


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
