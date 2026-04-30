from __future__ import annotations

from abc import ABC, abstractmethod


class BaseBroker(ABC):
    """Execution-layer contract every broker implementation must satisfy.

    The trading bot keeps the LLM out of risk decisions; this ABC is the
    boundary the deterministic risk layer (`tools/risk.py`) and the order
    placement path (`agents/team_leader.py`) call through. Each subclass wraps
    a single broker SDK and is responsible for translating between the bot's
    canonical types (plain dicts, primitive numbers) and the SDK's types.

    Adding a new broker:

    1. Subclass ``BaseBroker`` in ``tools/brokers/<name>.py``.
    2. Implement every abstract method below using the broker's SDK.
    3. Register the name in ``tools/brokers/__init__.py::_BROKERS``.
    4. Add the broker name to the validated set in ``config/settings.py``.
    5. Provide tests in ``tests/test_brokers_<name>.py``.

    Method semantics:

    - ``place_market_order``: must support a bracket variant when both
      ``stop_price`` and ``take_profit_price`` are provided. Brackets must
      persist server-side across days (GTC). Plain market orders are DAY.
      On rejection, raise ``BrokerSubmitError`` with the broker's message.
    - ``close_position``: market-close all shares of ``ticker`` and return
      the broker's order id as a string.
    - ``get_portfolio_value``: total account equity in USD.
    - ``get_positions``: list of ``{ticker, qty, avg_entry_price}`` dicts.
      Whole shares only — the bot never trades fractional.
    - ``get_current_price``: best available mid-price. Implementations must
      raise ``ValueError`` when no usable quote exists rather than returning
      0 or stale data.
    """

    @abstractmethod
    def place_market_order(
        self,
        ticker: str,
        shares: int,
        side: str,
        stop_price: float = None,
        take_profit_price: float = None,
    ) -> dict:
        """Submit a market order. Returns ``{"order_id": str, "fill_price": float | None}``."""

    @abstractmethod
    def close_position(self, ticker: str) -> str:
        """Close the entire position in ``ticker``. Returns the order id."""

    @abstractmethod
    def get_portfolio_value(self) -> float:
        """Total account equity in USD."""

    @abstractmethod
    def get_positions(self) -> list:
        """Open positions as a list of ``{ticker, qty, avg_entry_price}`` dicts."""

    @abstractmethod
    def get_current_price(self, ticker: str) -> float:
        """Best available mid-price. Raise ``ValueError`` when no usable quote exists."""
