"""Historical option price sources for the PCS-RIV backtest.

`PriceSource` is the interface the harness depends on; two implementations:

- `ModeledSource` — deterministic Black-Scholes quotes from an underlying price
  series + an IV series. The workhorse for the long-window (2015→now) arm and
  for unit tests (no network).
- `RealAlpacaSource` — read-only Alpaca historical *trade* data (bars/trades;
  bid/ask quotes are OPRA-gated, see `docs/research/mvp2-alpaca-options-data-spike.md`).
  It derives a mid from trade marks, computes IV + greeks locally, and **models**
  the bid/ask spread. It is read-only data access and never touches any order path.

IV-rank is a standalone helper (`compute_iv_rank`) fed a VIX/IV series by the
harness, keeping `PriceSource` purely about option quotes.
"""
from __future__ import annotations

import abc
import json
import math
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Mapping, Optional

from backtest.options_pricing import bs_greeks, bs_price, implied_vol

DEFAULT_RISK_FREE = 0.04
DATA_HOST = "https://data.alpaca.markets"


@dataclass(frozen=True)
class OptionQuote:
    strike: float
    expiry: date
    mid: float
    bid: float
    ask: float
    iv: float
    delta: float
    kind: str = "put"


def compute_iv_rank(
    series: Mapping[date, float],
    *,
    on: date,
    lookback_days: int = 365,
) -> Optional[float]:
    """52-week-style IV rank in [0, 100]: where today's IV sits in its range.

    Returns None if the trailing window holds no observations. Returns 0.0 for a
    degenerate flat window (no range).
    """
    window_start = on - timedelta(days=lookback_days)
    window = {d: v for d, v in series.items() if window_start <= d <= on}
    if not window:
        return None
    current = window[max(window)]
    lo, hi = min(window.values()), max(window.values())
    if hi == lo:
        return 0.0
    return (current - lo) / (hi - lo) * 100.0


class PriceSource(abc.ABC):
    @abc.abstractmethod
    def underlying_price(self, symbol: str, on: date) -> Optional[float]:
        ...

    @abc.abstractmethod
    def select_put_spread(
        self,
        symbol: str,
        on: date,
        *,
        dte_min: int,
        dte_max: int,
        short_delta: float,
        width: float,
    ) -> Optional[tuple[OptionQuote, OptionQuote]]:
        ...

    @abc.abstractmethod
    def mark_legs(
        self,
        symbol: str,
        on: date,
        *,
        short_strike: float,
        long_strike: float,
        expiry: date,
    ) -> Optional[tuple[OptionQuote, OptionQuote]]:
        ...


def _model_spread(mid: float, spread_frac: float) -> tuple[float, float]:
    """Symmetric modeled bid/ask around a mid (spread is OPRA-gated on free data)."""
    half = max(0.0, spread_frac) * mid
    return max(0.0, mid - half), mid + half


class ModeledSource(PriceSource):
    """Deterministic Black-Scholes quotes from injected price + IV series."""

    def __init__(
        self,
        prices: Mapping[date, float],
        ivs: Mapping[date, float],
        *,
        r: float = DEFAULT_RISK_FREE,
        q: float = 0.0,
        spread_frac: float = 0.05,
        strike_step: float = 1.0,
        scan_steps: int = 80,
    ) -> None:
        self._prices = dict(prices)
        self._ivs = dict(ivs)
        self._r = r
        self._q = q
        self._spread_frac = spread_frac
        self._strike_step = strike_step
        self._scan_steps = scan_steps

    def underlying_price(self, symbol: str, on: date) -> Optional[float]:
        return self._prices.get(on)

    def _quote(self, *, strike: float, expiry: date, on: date, spot: float, iv: float) -> OptionQuote:
        t = max((expiry - on).days, 0) / 365.0
        mid = bs_price(spot=spot, strike=strike, t=t, r=self._r, sigma=iv, kind="put", q=self._q)
        delta = bs_greeks(spot=spot, strike=strike, t=t, r=self._r, sigma=iv, kind="put", q=self._q)["delta"]
        bid, ask = _model_spread(mid, self._spread_frac)
        return OptionQuote(strike=strike, expiry=expiry, mid=mid, bid=bid, ask=ask, iv=iv, delta=delta)

    def select_put_spread(self, symbol, on, *, dte_min, dte_max, short_delta, width):
        spot = self.underlying_price(symbol, on)
        iv = self._ivs.get(on)
        if spot is None or iv is None:
            return None
        expiry = on + timedelta(days=round((dte_min + dte_max) / 2))
        start = math.floor(spot / self._strike_step) * self._strike_step
        candidates = [start - i * self._strike_step for i in range(self._scan_steps)]
        candidates = [k for k in candidates if k > 0]
        best = min(
            candidates,
            key=lambda k: abs(
                abs(self._quote(strike=k, expiry=expiry, on=on, spot=spot, iv=iv).delta) - short_delta
            ),
        )
        long_strike = best - width
        if long_strike <= 0:
            return None
        return (
            self._quote(strike=best, expiry=expiry, on=on, spot=spot, iv=iv),
            self._quote(strike=long_strike, expiry=expiry, on=on, spot=spot, iv=iv),
        )

    def mark_legs(self, symbol, on, *, short_strike, long_strike, expiry):
        spot = self.underlying_price(symbol, on)
        iv = self._ivs.get(on)
        if spot is None or iv is None:
            return None
        return (
            self._quote(strike=short_strike, expiry=expiry, on=on, spot=spot, iv=iv),
            self._quote(strike=long_strike, expiry=expiry, on=on, spot=spot, iv=iv),
        )


class RealAlpacaSource(PriceSource):
    """Read-only Alpaca historical trade data; models the bid/ask spread.

    Never imports or touches any order-placing path — data GET requests only.
    """

    def __init__(
        self,
        *,
        key: Optional[str] = None,
        secret: Optional[str] = None,
        r: float = DEFAULT_RISK_FREE,
        q: float = 0.0,
        spread_frac: float = 0.05,
        timeout: int = 15,
    ) -> None:
        self._key = key or os.environ.get("ALPACA_API_KEY_ID")
        self._secret = secret or os.environ.get("ALPACA_API_SECRET_KEY")
        if not (self._key and self._secret):
            raise RuntimeError(
                "Alpaca data keys not set (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY). "
                "RealAlpacaSource is read-only data access and never places orders."
            )
        self._r = r
        self._q = q
        self._spread_frac = spread_frac
        self._timeout = timeout

    # --- HTTP (patched in tests) -------------------------------------------
    def _get(self, host: str, path: str, params: dict) -> dict:
        url = f"{host}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={"APCA-API-KEY-ID": self._key, "APCA-API-SECRET-KEY": self._secret},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    def underlying_price(self, symbol: str, on: date) -> Optional[float]:
        start = datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        payload = self._get(
            DATA_HOST,
            f"/v2/stocks/{symbol}/bars",
            {"timeframe": "1Day", "start": start.isoformat(), "end": end.isoformat(), "limit": 1},
        )
        bars = payload.get("bars") or []
        return float(bars[0]["c"]) if bars else None

    def _select_expiry(self, symbol: str, on: date, dte_min: int, dte_max: int) -> Optional[date]:
        payload = self._get(
            "https://paper-api.alpaca.markets",
            "/v2/options/contracts",
            {
                "underlying_symbols": symbol,
                "expiration_date_gte": (on + timedelta(days=dte_min)).isoformat(),
                "expiration_date_lte": (on + timedelta(days=dte_max)).isoformat(),
                "limit": 1,
            },
        )
        contracts = payload.get("option_contracts") or []
        return date.fromisoformat(contracts[0]["expiration_date"]) if contracts else None

    def _fetch_put_chain_marks(self, symbol: str, on: date, expiry: date) -> list:
        """Return [{strike, mark}] for puts of `expiry` as marked on `on`.

        Wraps the bars endpoint; replaced in unit tests. Left intentionally thin —
        full multi-contract pagination is integration-tested live in Phase 1 Task 5.
        """
        raise NotImplementedError("live chain fetch is exercised in Task 5")

    def _quote_from_mark(self, *, strike: float, expiry: date, on: date, spot: float, mark: float) -> Optional[OptionQuote]:
        t = max((expiry - on).days, 0) / 365.0
        iv = implied_vol(price=mark, spot=spot, strike=strike, t=t, r=self._r, kind="put", q=self._q)
        if math.isnan(iv):
            return None
        delta = bs_greeks(spot=spot, strike=strike, t=t, r=self._r, sigma=iv, kind="put", q=self._q)["delta"]
        bid, ask = _model_spread(mark, self._spread_frac)
        return OptionQuote(strike=strike, expiry=expiry, mid=mark, bid=bid, ask=ask, iv=iv, delta=delta)

    def select_put_spread(self, symbol, on, *, dte_min, dte_max, short_delta, width):
        spot = self.underlying_price(symbol, on)
        if spot is None:
            return None
        expiry = self._select_expiry(symbol, on, dte_min, dte_max)
        if expiry is None:
            return None
        quotes = [
            q
            for row in self._fetch_put_chain_marks(symbol, on, expiry)
            if (q := self._quote_from_mark(strike=float(row["strike"]), expiry=expiry, on=on, spot=spot, mark=float(row["mark"]))) is not None
        ]
        if not quotes:
            return None
        short = min(quotes, key=lambda q: abs(abs(q.delta) - short_delta))
        long = min(quotes, key=lambda q: abs(q.strike - (short.strike - width)))
        if long.strike >= short.strike:
            return None
        return short, long

    def mark_legs(self, symbol, on, *, short_strike, long_strike, expiry):
        spot = self.underlying_price(symbol, on)
        if spot is None:
            return None
        marks = {float(row["strike"]): float(row["mark"]) for row in self._fetch_put_chain_marks(symbol, on, expiry)}
        if short_strike not in marks or long_strike not in marks:
            return None
        short = self._quote_from_mark(strike=short_strike, expiry=expiry, on=on, spot=spot, mark=marks[short_strike])
        long = self._quote_from_mark(strike=long_strike, expiry=expiry, on=on, spot=spot, mark=marks[long_strike])
        if short is None or long is None:
            return None
        return short, long
