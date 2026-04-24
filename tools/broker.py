from __future__ import annotations

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import settings


def get_trading_client() -> TradingClient:
    return TradingClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
        paper=(settings.TRADING_MODE == "paper"),
    )


def place_market_order(ticker: str, shares: int, side: str) -> dict:
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
    order = client.submit_order(request)
    fill_price = float(order.filled_avg_price) if order.filled_avg_price is not None else None
    return {"order_id": str(order.id), "fill_price": fill_price}


def close_position(ticker: str) -> str:
    client = get_trading_client()
    order = client.close_position(ticker)
    return str(order.id)


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
            "qty": int(float(pos.qty)),
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
