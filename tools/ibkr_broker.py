"""IBKR broker wrapper using `ib_insync`.

This module owns all interaction with TWS / IB Gateway. It enforces the
`CLAUDE_AGENT_NO_BROKER` guard at the top of every submission/connection
helper so any forgotten mock in a test fails fast instead of reaching live
broker (per the lessons in CLAUDE.md issues #149, #168).
"""
from __future__ import annotations

import time
from typing import Optional

from ib_insync import IB, Stock, MarketOrder

from config.settings import is_claude_agent_no_broker


class BrokerCallBlockedError(RuntimeError):
    """Raised when a broker call is attempted with the agent-context guard active."""


class IBKRConnectionError(RuntimeError):
    """Raised when we can't establish a TWS connection after retries."""


def _check_guard(op: str) -> None:
    if is_claude_agent_no_broker():
        raise BrokerCallBlockedError(
            f"CLAUDE_AGENT_NO_BROKER is set; refusing to perform {op!r}. "
            "Mock the broker in tests."
        )


def connect_ibkr(
    *,
    host: str,
    port: int,
    client_id: int,
    max_retries: int = 3,
    backoff_s: float = 5.0,
    timeout_s: int = 10,
) -> IB:
    """Connect to TWS / IB Gateway with retries and exponential-ish backoff.

    Returns a connected ``IB`` instance. Caller is responsible for calling
    ``ib.disconnect()`` (use ``with`` block via ``ibkr_session()``).
    """
    _check_guard("connect_ibkr")
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        ib = IB()
        try:
            ib.connect(host, port, clientId=client_id, timeout=timeout_s)
            if ib.isConnected():
                return ib
            last_err = ConnectionError("connect succeeded but isConnected() == False")
        except Exception as e:  # noqa: BLE001
            last_err = e
        # Backoff applies to BOTH failure paths (raised exception OR isConnected==False)
        # so a flaky TWS that returns isConnected()==False isn't hammered with
        # back-to-back retries at full speed.
        if attempt < max_retries:
            time.sleep(backoff_s)
    raise IBKRConnectionError(
        f"Failed to connect to IBKR at {host}:{port} after {max_retries} attempts: {last_err}"
    )


def get_position(ib: IB, symbol: str) -> int:
    """Return the integer share count for ``symbol`` (0 if no position).

    Matches by contract symbol prefix — Xetra symbols like ``WSPL.DE`` come
    back from IBKR as ``WSPL`` (no exchange suffix), so we strip the suffix
    when comparing.

    .. warning::
        This helper assumes any dot in ``symbol`` is a venue suffix (e.g.,
        ``.DE``, ``.L``, ``.PA``). It is **not safe** for US class-share
        tickers like ``BRK.B`` or ``BRK.A`` — those would be conflated. The
        bot's current universe is single-vehicle UCITS (``WSPL.DE``), so the
        limitation is latent. If extending the universe to US class shares,
        switch to an exchange-suffix allowlist.
    """
    short = symbol.split(".")[0]
    for pos in ib.positions():
        if pos.contract.symbol == short:
            return int(pos.position)
    return 0


def get_account_value(ib: IB, currency: str = "EUR") -> float:
    """Return Net Liquidation value in the requested currency."""
    for av in ib.accountSummary():
        if av.tag == "NetLiquidation" and av.currency == currency:
            return float(av.value)
    raise RuntimeError(f"No NetLiquidation entry in {currency} found in accountSummary")
