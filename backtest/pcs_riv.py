"""Put-Credit-Spread-on-Regime+IV (PCS-RIV) backtest harness.

The Phase 1 kill-gate strategy (issue #220). Deterministic rule:

    Entry (per underlying, when flat):  SPY > SMA(sma_days)  AND  IV-rank >= threshold
        -> sell a put credit spread: short ~short_delta put, long `width` below,
           expiry in [dte_min, dte_max].
    Exit (first to trigger):  50% of credit captured | <= time_stop_dte to expiry |
                              regime flips bearish | expiry | end of window.

Fills are conservative (sell at bid, buy at ask); the spread is modeled by the
PriceSource (real bid/ask is OPRA-gated — see the data-spike memo). The regime
gate reuses `strategy.regime.compute_target_state`. Metrics mirror
`backtest/regime.py` plus win rate / profit factor / Sharpe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional

from backtest.options_data import PriceSource, compute_iv_rank
from strategy.regime import compute_target_state

CONTRACT_MULTIPLIER = 100


@dataclass
class Trade:
    underlying: str
    entry_date: date
    exit_date: date
    short_strike: float
    long_strike: float
    expiry: date
    credit: float
    width: float
    contracts: int
    pnl: float
    exit_reason: str


@dataclass
class _Position:
    underlying: str
    entry_date: date
    short_strike: float
    long_strike: float
    expiry: date
    credit: float  # per-share net credit received at open
    width: float
    contracts: int
    entry_fee: float


def _rolling_sma(closes: list, sma_days: int) -> list:
    """SMA aligned to `closes`; NaN (None) until enough history."""
    out: list = []
    for i in range(len(closes)):
        if i + 1 < sma_days:
            out.append(None)
        else:
            out.append(sum(closes[i + 1 - sma_days : i + 1]) / sma_days)
    return out


def _close_cost(source: PriceSource, symbol: str, on: date, pos: _Position) -> Optional[float]:
    """Per-share cost to close the spread on `on` (buy short at ask, sell long at bid).

    At/after expiry, settle at exact intrinsic (no modeled spread on a settled value).
    """
    if on >= pos.expiry:
        spot = source.underlying_price(symbol, on)
        if spot is None:
            return None
        intrinsic = max(0.0, pos.short_strike - spot) - max(0.0, pos.long_strike - spot)
        return min(max(intrinsic, 0.0), pos.width)
    legs = source.mark_legs(symbol, on, short_strike=pos.short_strike, long_strike=pos.long_strike, expiry=pos.expiry)
    if legs is None:
        return None
    short, long = legs
    return min(max(short.ask - long.bid, 0.0), pos.width)


def run_pcs_riv_backtest(
    *,
    source: PriceSource,
    underlyings: list,
    spy_closes: Mapping[date, float],
    iv_series: Mapping[date, float],
    trading_dates: Optional[list] = None,
    sma_days: int = 200,
    dte_min: int = 30,
    dte_max: int = 45,
    short_delta: float = 0.30,
    width: float = 5.0,
    iv_rank_threshold: float = 30.0,
    iv_rank_lookback_days: int = 365,
    profit_target: float = 0.50,
    time_stop_dte: int = 21,
    starting_cash: float = 100_000.0,
    risk_per_trade: float = 0.05,
    fee_per_contract: float = 0.05,
    regime_mode: str = "bullish",
) -> dict:
    if regime_mode not in ("bullish", "any", "bearish"):
        raise ValueError(f"regime_mode must be bullish|any|bearish, got {regime_mode!r}")
    dates = sorted(trading_dates) if trading_dates is not None else sorted(spy_closes)
    closes = [spy_closes[d] for d in dates]
    sma = _rolling_sma(closes, sma_days)

    cash = starting_cash
    positions: dict = {}
    trades: list = []
    equity_curve: list = []

    def bullish(i: int) -> bool:
        if sma[i] is None:
            return False
        target, _ = compute_target_state(
            spy_close=closes[i], spy_sma200=sma[i], current_state="CASH", kill_switch_active=False
        )
        return target == "LONG"

    def regime_ok(i: int) -> bool:
        """Whether the entry regime condition holds (generalised gate)."""
        if regime_mode == "any":
            return True
        return bullish(i) if regime_mode == "bullish" else not bullish(i)

    def close_position(pos: _Position, on: date, cost: float, reason: str) -> float:
        captured = pos.credit - cost
        exit_fee = fee_per_contract * pos.contracts * 2
        pnl = captured * pos.contracts * CONTRACT_MULTIPLIER - pos.entry_fee - exit_fee
        trades.append(
            Trade(
                underlying=pos.underlying, entry_date=pos.entry_date, exit_date=on,
                short_strike=pos.short_strike, long_strike=pos.long_strike, expiry=pos.expiry,
                credit=pos.credit, width=pos.width, contracts=pos.contracts,
                pnl=pnl, exit_reason=reason,
            )
        )
        return pnl

    for i, on in enumerate(dates):
        is_ok = regime_ok(i)

        # --- manage open positions (exits) ---
        for sym in list(positions):
            pos = positions[sym]
            cost = _close_cost(source, sym, on, pos)
            if cost is None:
                continue  # data gap; hold
            dte = (pos.expiry - on).days
            reason: Optional[str] = None
            if on >= pos.expiry:
                reason = "expiry"
            elif cost <= (1.0 - profit_target) * pos.credit:
                reason = "profit_target"
            elif dte <= time_stop_dte:
                reason = "time_stop"
            elif not is_ok:
                reason = "regime_flip"
            if reason is not None:
                cash += close_position(pos, on, cost, reason)
                del positions[sym]

        # --- entries ---
        if is_ok:
            iv_rank = compute_iv_rank(iv_series, on=on, lookback_days=iv_rank_lookback_days)
            if iv_rank is not None and iv_rank >= iv_rank_threshold:
                equity_now = cash + _open_mtm(source, positions, on)
                for sym in underlyings:
                    if sym in positions:
                        continue
                    legs = source.select_put_spread(
                        sym, on, dte_min=dte_min, dte_max=dte_max, short_delta=short_delta, width=width
                    )
                    if legs is None:
                        continue
                    short, long = legs
                    credit = short.bid - long.ask
                    spread_width = short.strike - long.strike
                    max_loss = spread_width - credit
                    if credit <= 0 or max_loss <= 0:
                        continue
                    contracts = int((risk_per_trade * equity_now) / (max_loss * CONTRACT_MULTIPLIER))
                    if contracts < 1:
                        continue
                    entry_fee = fee_per_contract * contracts * 2
                    cash -= entry_fee
                    positions[sym] = _Position(
                        underlying=sym, entry_date=on, short_strike=short.strike, long_strike=long.strike,
                        expiry=short.expiry, credit=credit, width=spread_width, contracts=contracts, entry_fee=entry_fee,
                    )

        equity_curve.append((on, cash + _open_mtm(source, positions, on)))

    # Close any survivors at the last date.
    if positions:
        last = dates[-1]
        for sym in list(positions):
            pos = positions[sym]
            cost = _close_cost(source, sym, last, pos)
            if cost is None:
                cost = pos.credit  # no mark: assume closed at credit (zero P&L on the spread)
            cash += close_position(pos, last, cost, "end_of_window")
            del positions[sym]
        equity_curve[-1] = (last, cash)

    return _metrics(starting_cash, cash, equity_curve, trades, dates)


def _open_mtm(source: PriceSource, positions: dict, on: date) -> float:
    """Unrealized P&L of all open spreads marked on `on`."""
    total = 0.0
    for sym, pos in positions.items():
        cost = _close_cost(source, sym, on, pos)
        if cost is None:
            continue
        total += (pos.credit - cost) * pos.contracts * CONTRACT_MULTIPLIER
    return total


def _metrics(starting_cash: float, ending_cash: float, equity_curve: list, trades: list, dates: list) -> dict:
    equities = [e for _, e in equity_curve]
    ending_equity = equities[-1] if equities else starting_cash
    total_return = ending_equity / starting_cash - 1.0

    n_years = (dates[-1] - dates[0]).days / 365.25 if len(dates) > 1 else 0.0
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 and total_return > -1 else 0.0

    max_dd = 0.0
    peak = equities[0] if equities else starting_cash
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, e / peak - 1.0)

    rets = [equities[i] / equities[i - 1] - 1.0 for i in range(1, len(equities)) if equities[i - 1] > 0]
    sharpe = 0.0
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = var ** 0.5
        if std > 0:
            sharpe = mean / std * (252 ** 0.5)

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0

    return {
        "starting_cash": starting_cash,
        "ending_equity": ending_equity,
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "trade_count": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trades": [t.__dict__ for t in trades],
        "equity_curve": equity_curve,
    }
