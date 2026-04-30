from __future__ import annotations

from tools.brokers.base import BaseBroker


class AlpacaBroker(BaseBroker):
    """``BaseBroker`` adapter over the Alpaca SDK.

    Delegates every call to the module-level functions in ``tools/broker.py``.
    That module is the canonical Alpaca implementation and the patch surface
    used by the existing test suite (``patch("tools.broker.<fn>")``); this
    adapter intentionally does not reimplement that logic so a single source
    of truth keeps both call paths in sync.
    """

    def place_market_order(
        self,
        ticker: str,
        shares: int,
        side: str,
        stop_price: float = None,
        take_profit_price: float = None,
    ) -> dict:
        from tools import broker as _b
        return _b.place_market_order(
            ticker,
            shares,
            side,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    def close_position(self, ticker: str) -> str:
        from tools import broker as _b
        return _b.close_position(ticker)

    def get_portfolio_value(self) -> float:
        from tools import broker as _b
        return _b.get_portfolio_value()

    def get_positions(self) -> list:
        from tools import broker as _b
        return _b.get_alpaca_positions()

    def get_current_price(self, ticker: str) -> float:
        from tools import broker as _b
        return _b.get_current_price(ticker)
