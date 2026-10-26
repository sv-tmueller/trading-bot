"""Long/short portfolio simulator for the AI research pipeline (Task 1).

Turns daily target weights across several ETFs into an equity curve, a
held-weights history and a trade ledger. Research-only: lives in backtest/,
is never imported by supabase/functions/, makes no network or broker call and
uses no LLM. It deliberately does not import backtest.regime (that module
pulls in yfinance and declares ``Trade.qty: int``, while this simulator uses
fractional quantities); trades are plain dicts carrying the ``regime.Trade``
keys plus ``symbol``, ``side`` and ``kind``.

Model (decisions, documented):

- Timing. The target weight row at close T fills at the open of the next row
  (T+1). Row 0 therefore never trades.
- Band. Per asset, "held" is the actual signed weight at the T+1 open before
  trading (``qty * open / equity_at_open``). An asset is traded to its exact
  target weight when ``sign(target) != sign(held)`` (open from flat, close to
  zero, or flip) or when ``|target - held| > rebalance_band``. It is never
  traded only to the band edge.
- Order on a rebalance day. First all reductions, closes and the closing leg
  of flips, then all opens and increases. Increases are sized against equity
  at the open after the reductions, with costs included
  (``qty = dollars / (exec_px * (1 + commission))``), so a fully invested
  1.0x book never needs borrowed cash.
- Lots. One signed position per symbol. Adding to it blends ``entry_price``
  into a weighted average and keeps the original ``entry_date``. Entry and
  exit prices are fill prices including slippage. ``pnl`` is
  ``(exit - entry) * qty`` for longs, ``(entry - exit) * qty`` for shorts,
  minus the commission on both sides for that quantity. ``exit_reason`` is
  ``"close"`` (back to zero, ``round_trip``), ``"reverse"`` (sign flip,
  ``round_trip``) or ``"resize"`` (reduction, ``partial``). Entries and
  increases are not ledger rows.
- No forced close-out at the end of the data. Positions still open on the
  last row are valued at that close in ``equity`` and do not appear in
  ``trades``. This differs on purpose from ``simulate_from_signal`` and
  ``_simulate_weighted``. Consequence: unrealized profit at the end is not
  taxed by ``apply_annual_netting_tax``, which flatters an always-held
  benchmark more than an active candidate (strict side for the pass bar).
- Accruals at close d, on the balances after that day's trades. Borrow:
  short notional x ``borrow_bps_annual / 1e4 / 252``. Cash interest:
  ``max(cash - short_notional, 0)`` earns ``cash_returns[d]`` (a daily
  simple decimal return, for example BIL ``Close.pct_change()``), with
  ``short_notional`` marked at that close. Negative cash, whatever
  ``gross_cap`` is, pays
  ``|cash| * (cash_returns[d] + financing_spread_bps_annual / 1e4 / 252)``.
  They go into ``costs`` and ``equity``, never into a trade's ``pnl``, so the
  tax layer sees no trade for cash interest.
- Cash model (retail, net of shorts). Short-sale proceeds sit in cash but
  earn nothing, as on a retail Alpaca account: interest accrues only on cash
  net of short notional, floored at zero (equivalently, equity before the
  day's accruals minus long market value). A long-only book is unaffected; a
  short book earns interest on its equity only, never on its proceeds, so a
  shorting candidate gets no carry the long-only benchmark could not also
  earn. Financing is still charged only on negative cash, so above a 1.0
  gross cap short proceeds can offset what would otherwise be a margin debit
  (information line only; at a 1.0 cap, cash net of shorts is non-negative
  apart from drift between rebalances). A pre-registration should cite this
  cash, borrow and financing model.
- Missing prices. An asset trades on a day only if both its open and close
  are finite. Otherwise it is not traded that day: the position is kept (0 if
  never opened) and valued at the last finite close. A data gap never forces
  a close. A flat or not yet priced asset contributes exactly 0.0, so
  ``equity`` and ``held_weights`` never hold NaN. A NaN target counts as 0.
- Validation (after ``fillna(0)``): ``ValueError`` if any ``|w|`` exceeds
  ``gross_cap + 1e-9`` or any row's ``sum(|w|)`` exceeds ``gross_cap + 1e-9``,
  or if a target column has no price column. ``gross_cap`` checks target
  weights only; ``gross_exposure`` reports the actual value, which can drift
  above the cap between rebalances.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

_TRADING_DAYS = 252
_CAP_TOL = 1e-9


@dataclass(frozen=True)
class CostModel:
    """Per-side trading costs and annualised carry costs, all in bps."""

    slippage_bps: float = 5.0
    commission_bps: float = 0.0
    borrow_bps_annual: float = 50.0
    financing_spread_bps_annual: float = 100.0


@dataclass
class PortfolioResult:
    """Output of ``simulate_portfolio``.

    ``costs`` has keys ``trading`` (slippage plus commission), ``borrow``,
    ``financing`` and ``cash_interest`` (a positive number is income), all in
    currency units.
    """

    equity: pd.Series
    daily_returns: pd.Series
    gross_exposure: pd.Series
    held_weights: pd.DataFrame
    trades: List[dict]
    costs: Dict[str, float]


def _validate_targets(weights: pd.DataFrame, gross_cap: float) -> None:
    limit = gross_cap + _CAP_TOL
    if (weights.abs() > limit).any().any():
        raise ValueError(
            f"target weight exceeds gross_cap {gross_cap} (per-column bound)"
        )
    if (weights.abs().sum(axis=1) > limit).any():
        raise ValueError(f"row sum(|w|) exceeds gross_cap {gross_cap}")


def simulate_portfolio(
    target_weights: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cash_returns: pd.Series,
    *,
    starting_equity: float = 100_000.0,
    costs: CostModel = CostModel(),
    gross_cap: float = 1.0,
    rebalance_band: float = 0.02,
) -> PortfolioResult:
    """Simulate daily long/short target weights. See the module docstring."""
    index = target_weights.index
    if len(index) == 0:
        raise ValueError("target_weights is empty")
    if not (index.is_unique and index.is_monotonic_increasing):
        raise ValueError("target_weights index must be unique and increasing")
    syms = list(target_weights.columns)
    missing = [s for s in syms if s not in opens.columns or s not in closes.columns]
    if missing:
        raise ValueError(f"no price column for target symbols: {missing}")

    weights = target_weights.astype(float).fillna(0.0)
    _validate_targets(weights, gross_cap)

    n, k = len(index), len(syms)
    W = weights.to_numpy()
    O = opens.reindex(index=index, columns=syms).astype(float).to_numpy()
    C = closes.reindex(index=index, columns=syms).astype(float).to_numpy()
    cash_r = cash_returns.reindex(index).astype(float).fillna(0.0).to_numpy()

    slip = costs.slippage_bps / 1e4
    comm = costs.commission_bps / 1e4
    borrow_daily = costs.borrow_bps_annual / 1e4 / _TRADING_DAYS
    spread_daily = costs.financing_spread_bps_annual / 1e4 / _TRADING_DAYS

    qty = np.zeros(k)
    entry_px = np.zeros(k)
    entry_dt: List[object] = [None] * k
    last_close = np.full(k, np.nan)
    cash = float(starting_equity)

    equity = np.zeros(n)
    held = np.zeros((n, k))
    trades: List[dict] = []
    tot = {"trading": 0.0, "borrow": 0.0, "financing": 0.0, "cash_interest": 0.0}

    def position_values(prices: np.ndarray) -> np.ndarray:
        # A flat (or never priced) asset is exactly 0.0, never 0 * NaN.
        return np.where(qty != 0.0, qty * np.nan_to_num(prices, nan=0.0), 0.0)

    def reduce_position(j: int, size: float, date, open_px: float, reason: str,
                        kind: str) -> None:
        nonlocal cash
        is_long = qty[j] > 0
        px = open_px * (1.0 - slip) if is_long else open_px * (1.0 + slip)
        fee = size * px * comm
        if is_long:
            cash += size * px - fee
            gross = (px - entry_px[j]) * size
        else:
            cash -= size * px + fee
            gross = (entry_px[j] - px) * size
        pnl = gross - fee - entry_px[j] * size * comm
        tot["trading"] += size * open_px * slip + fee
        trades.append({
            "entry_date": entry_dt[j],
            "exit_date": date,
            "entry_price": float(entry_px[j]),
            "exit_price": float(px),
            "qty": float(size),
            "pnl": float(pnl),
            "return_pct": float(pnl / (entry_px[j] * size)),
            "exit_reason": reason,
            "symbol": syms[j],
            "side": "long" if is_long else "short",
            "kind": kind,
        })
        remaining = abs(qty[j]) - size
        if reason in ("close", "reverse") or remaining <= 0.0:
            qty[j] = 0.0
            entry_px[j] = 0.0
            entry_dt[j] = None
        else:
            qty[j] = np.sign(qty[j]) * remaining

    for d in range(n):
        date = index[d]
        open_d, close_d = O[d], C[d]
        tradable = np.isfinite(open_d) & np.isfinite(close_d)

        if d > 0:
            target = W[d - 1]
            mark = np.where(tradable, open_d, last_close)
            pos_val = position_values(mark)
            eq_open = cash + pos_val.sum()
            if eq_open > 0.0:
                held_w = pos_val / eq_open
                to_trade = [
                    j for j in range(k)
                    if tradable[j] and (
                        np.sign(target[j]) != np.sign(qty[j])
                        or abs(target[j] - held_w[j]) > rebalance_band
                    )
                ]
                openers: List[int] = []
                # Phase 1: reductions, closes and the closing leg of flips.
                for j in to_trade:
                    if qty[j] == 0.0:
                        openers.append(j)
                        continue
                    if np.sign(target[j]) != np.sign(qty[j]):
                        reason = "close" if target[j] == 0.0 else "reverse"
                        reduce_position(j, abs(qty[j]), date, open_d[j], reason,
                                        "round_trip")
                        if target[j] != 0.0:
                            openers.append(j)
                        continue
                    target_qty = abs(target[j]) * eq_open / open_d[j]
                    if target_qty < abs(qty[j]):
                        reduce_position(j, abs(qty[j]) - target_qty, date,
                                        open_d[j], "resize", "partial")
                    else:
                        openers.append(j)
                # Phase 2: opens and increases, sized after the reductions.
                eq_after = cash + position_values(mark).sum()
                for j in openers:
                    cur = abs(qty[j]) * open_d[j]
                    dollars = abs(target[j]) * eq_after - cur
                    if dollars <= 0.0:
                        continue
                    is_long = target[j] > 0
                    px = open_d[j] * (1.0 + slip) if is_long else open_d[j] * (1.0 - slip)
                    size = dollars / (px * (1.0 + comm))
                    fee = size * px * comm
                    if is_long:
                        cash -= size * px + fee
                    else:
                        cash += size * px - fee
                    tot["trading"] += size * open_d[j] * slip + fee
                    prev = abs(qty[j])
                    if prev == 0.0:
                        entry_dt[j] = date
                        entry_px[j] = px
                    else:
                        entry_px[j] = (prev * entry_px[j] + size * px) / (prev + size)
                    qty[j] = (1.0 if is_long else -1.0) * (prev + size)

        # Close of day d: mark, then accrue on the post-trade balances.
        last_close = np.where(np.isfinite(close_d), close_d, last_close)
        pos_val_c = position_values(last_close)
        short_notional = float(-pos_val_c[pos_val_c < 0.0].sum())
        cash_pre = cash
        interest_base = max(cash_pre - short_notional, 0.0)
        if interest_base > 0.0:
            interest = interest_base * cash_r[d]
            tot["cash_interest"] += interest
            cash += interest
        elif cash_pre < 0.0:
            fin = -cash_pre * (cash_r[d] + spread_daily)
            tot["financing"] += fin
            cash -= fin
        borrow = short_notional * borrow_daily
        tot["borrow"] += borrow
        cash -= borrow

        eq_close = cash + pos_val_c.sum()
        equity[d] = eq_close
        if eq_close > 0.0:
            held[d] = pos_val_c / eq_close

    equity_s = pd.Series(equity, index=index, name="equity")
    daily = equity_s.pct_change()
    daily.iloc[0] = equity_s.iloc[0] / starting_equity - 1.0
    held_df = pd.DataFrame(held, index=index, columns=syms)
    return PortfolioResult(
        equity=equity_s,
        daily_returns=daily,
        gross_exposure=held_df.abs().sum(axis=1),
        held_weights=held_df,
        trades=trades,
        costs=tot,
    )


def round_trips_per_year(result: PortfolioResult) -> float:
    """Closed positions (kind ``round_trip``) per calendar year, whole basket."""
    count = sum(1 for t in result.trades if t["kind"] == "round_trip")
    idx = result.equity.index
    span_days = (idx[-1] - idx[0]).days if len(idx) else 0
    if span_days <= 0:
        return 0.0
    return count / (span_days / 365.25)
