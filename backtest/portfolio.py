"""Portfolio-level backtest simulator.

Unlike the per-ticker runner in `backtest/runner.py` (which backtests each
ticker independently with its own $100k), this module simulates a **single
shared portfolio** that enforces the same constraints the live bot uses:

    * ``MAX_POSITIONS``             — maximum concurrent open positions
    * ``MAX_PORTFOLIO_EXPOSURE``    — combined notional cap as a fraction of equity
    * ``RISK_PER_TRADE``            — fraction of *current* equity risked per trade
    * ``MAX_HOLD_DAYS``             — exit by this hold duration

The simulator is deliberately rule-based — no LLM calls. When more than
``MAX_POSITIONS`` candidates fire on the same day, we rank by a simple
deterministic proxy for the live Team Leader's score.

    score = volume_ratio * (1 - abs(rsi - 50) / 50)

Rationale: higher relative volume and an RSI closer to neutral both correlate
with quality entry setups. Candidates that are selected but are rejected by
the portfolio gates (``max_positions``, ``max_exposure``) are logged for
post-hoc analysis.

Exit priority mirrors ``monitor/position_monitor.py`` — stop, then target,
then max-hold — but this module intentionally has no runtime dependency on
that module so it stays self-contained within ``backtest/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import ta as ta_lib

from config import settings
from config.watchlist import WATCHLIST
from backtest.data import fetch_data


STARTING_CASH = 100_000.0
COMMISSION = 0.001  # 0.1% per fill — matches per-ticker Backtest call


@dataclass
class OpenPosition:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    stop: float
    target: float
    score: float
    # index on this ticker's DataFrame for the entry bar — used for max-hold
    entry_bar_index: int
    # Highest price seen since entry — used by the optional trailing stop.
    trailing_high: Optional[float] = None
    # Initial stop distance (entry_price - stop) frozen at open; trailing
    # stops use this as the volatility-anchored trail distance.
    initial_stop_distance: float = 0.0


@dataclass
class ClosedTrade:
    ticker: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    exit_reason: str   # "stop" | "target" | "max_hold"
    score: float
    pnl_dollars: float
    return_pct: float  # fraction


@dataclass
class RejectedSignal:
    date: pd.Timestamp
    ticker: str
    reason: str   # "max_positions" | "max_exposure"
    score: float


# ---------------------------------------------------------------------------
# Indicators (shared with per-ticker path in terms of library & params)
# ---------------------------------------------------------------------------


def compute_indicators(
    df: pd.DataFrame,
    *,
    ema_fast: int,
    ema_slow: int,
    rsi_period: int,
    atr_period: int,
) -> pd.DataFrame:
    """Add EMA/RSI/ATR/Volume-SMA columns to a raw OHLCV DataFrame.

    Uses the same ``ta`` library calls as ``backtest/strategy.py``.
    """
    out = df.copy()
    out["ema_fast"] = ta_lib.trend.ema_indicator(out["Close"], window=ema_fast)
    out["ema_slow"] = ta_lib.trend.ema_indicator(out["Close"], window=ema_slow)
    out["rsi"] = ta_lib.momentum.rsi(out["Close"], window=rsi_period)
    out["atr"] = ta_lib.volatility.average_true_range(
        out["High"], out["Low"], out["Close"], window=atr_period
    )
    out["vol_sma"] = out["Volume"].rolling(20).mean()
    return out


def entry_signal(
    row: pd.Series,
    prev_row: pd.Series,
    *,
    rsi_lower: float,
    rsi_upper: float,
    volume_multiplier: float,
    strict_crossover: bool,
) -> bool:
    """Return True if the row's bar triggers an entry.

    Mirrors ``backtest/strategy.py:EMAStrategy.next()`` signal logic exactly.
    """
    values = [
        row.get("ema_fast"),
        row.get("ema_slow"),
        prev_row.get("ema_fast"),
        prev_row.get("ema_slow"),
        row.get("rsi"),
        row.get("atr"),
        row.get("vol_sma"),
    ]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in values):
        return False

    ema_f, ema_s, ema_f_prev, ema_s_prev, rsi, _atr, vol_sma = values

    if strict_crossover:
        ema_ok = bool((ema_f > ema_s) and (ema_f_prev <= ema_s_prev))
    else:
        ema_ok = bool(ema_f > ema_s)
    rsi_ok = rsi_lower <= rsi <= rsi_upper
    vol_ok = vol_sma > 0 and (row["Volume"] / vol_sma) >= volume_multiplier
    return bool(ema_ok and rsi_ok and vol_ok)


def candidate_score(row: pd.Series) -> float:
    """Deterministic proxy for the live Team Leader's ranking.

    ``score = volume_ratio * (1 - abs(rsi - 50) / 50)``

    Higher relative volume and RSI closer to neutral => higher score.
    """
    vol_sma = row.get("vol_sma", 0.0)
    if not vol_sma or np.isnan(vol_sma):
        return 0.0
    vol_ratio = row["Volume"] / vol_sma
    rsi = row.get("rsi", 50.0)
    if np.isnan(rsi):
        return 0.0
    return float(vol_ratio * (1.0 - abs(rsi - 50.0) / 50.0))


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


@dataclass
class PortfolioSimulator:
    years: int
    ema_fast: int
    ema_slow: int
    rsi_period: int
    rsi_lower: float
    rsi_upper: float
    volume_multiplier: float
    atr_period: int
    atr_multiplier: float
    rr_ratio: float
    max_hold_days: int
    strict_crossover: bool
    max_positions: int = settings.MAX_POSITIONS
    max_portfolio_exposure: float = settings.MAX_PORTFOLIO_EXPOSURE
    risk_per_trade: float = settings.RISK_PER_TRADE
    tickers: list = field(default_factory=lambda: list(WATCHLIST))
    data_loader: object = fetch_data

    # --- runtime state (populated in run()) ---
    data: dict = field(default_factory=dict, init=False)
    cash: float = field(default=STARTING_CASH, init=False)
    open_positions: list = field(default_factory=list, init=False)
    closed_trades: list = field(default_factory=list, init=False)
    rejected: list = field(default_factory=list, init=False)
    equity_curve: list = field(default_factory=list, init=False)

    # --- helpers -----------------------------------------------------------

    def _load(self) -> None:
        for ticker in self.tickers:
            raw = self.data_loader(ticker, years=self.years)
            if raw is None or raw.empty:
                continue
            self.data[ticker] = compute_indicators(
                raw,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                rsi_period=self.rsi_period,
                atr_period=self.atr_period,
            )

    def _mark_to_market(self, day: pd.Timestamp) -> float:
        equity = self.cash
        for pos in self.open_positions:
            df = self.data[pos.ticker]
            if day in df.index:
                price = float(df.loc[day, "Close"])
            else:
                # fall back to last known close up to this day
                sub = df.loc[:day]
                price = float(sub["Close"].iloc[-1]) if len(sub) else pos.entry_price
            equity += pos.shares * price
        return equity

    def _check_exit(self, pos: OpenPosition, day: pd.Timestamp) -> Optional[ClosedTrade]:
        df = self.data[pos.ticker]
        if day not in df.index:
            return None
        row = df.loc[day]
        bar_index = df.index.get_loc(day)
        hold_bars = bar_index - pos.entry_bar_index

        # Priority: stop -> target -> max_hold. We test stop first; if the bar
        # is a hard gap-down through stop, exit at stop price (same convention
        # as backtesting.py). Similarly for target on a gap-up.
        low = float(row["Low"])
        high = float(row["High"])
        close = float(row["Close"])

        # Trailing stop ratchet (opt-in, default OFF). Update before exit
        # checks so today's bar can fire against the freshly raised stop.
        # Trail distance uses today's ATR × TRAILING_STOP_ATR_MULT when
        # available, otherwise falls back to the entry-time stop distance.
        if settings.TRAILING_STOP_ENABLED and pos.initial_stop_distance > 0:
            new_high = max(pos.trailing_high or pos.entry_price, high)
            pos.trailing_high = new_high
            atr_today = row.get("atr") if hasattr(row, "get") else None
            if atr_today is not None and not (isinstance(atr_today, float) and np.isnan(atr_today)) and atr_today > 0:
                trail_distance = float(atr_today) * settings.TRAILING_STOP_ATR_MULT
            else:
                trail_distance = pos.initial_stop_distance
            proposed_stop = new_high - trail_distance
            if proposed_stop > pos.stop:
                pos.stop = proposed_stop

        if low <= pos.stop:
            return self._close(pos, day, pos.stop, "stop")
        if high >= pos.target:
            return self._close(pos, day, pos.target, "target")
        if hold_bars >= self.max_hold_days:
            return self._close(pos, day, close, "max_hold")
        return None

    def _close(
        self,
        pos: OpenPosition,
        day: pd.Timestamp,
        exit_price: float,
        reason: str,
    ) -> ClosedTrade:
        gross = pos.shares * exit_price
        self.cash += gross * (1.0 - COMMISSION)
        pnl = (exit_price - pos.entry_price) * pos.shares - (
            (pos.entry_price + exit_price) * pos.shares * COMMISSION
        )
        ret_pct = (exit_price - pos.entry_price) / pos.entry_price
        trade = ClosedTrade(
            ticker=pos.ticker,
            entry_date=pos.entry_date,
            exit_date=day,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            shares=pos.shares,
            exit_reason=reason,
            score=pos.score,
            pnl_dollars=pnl,
            return_pct=ret_pct,
        )
        self.closed_trades.append(trade)
        return trade

    def _open(
        self,
        ticker: str,
        day: pd.Timestamp,
        entry_price: float,
        shares: int,
        stop: float,
        target: float,
        score: float,
        bar_index: int,
    ) -> None:
        notional = shares * entry_price
        self.cash -= notional * (1.0 + COMMISSION)
        self.open_positions.append(
            OpenPosition(
                ticker=ticker,
                entry_date=day,
                entry_price=entry_price,
                shares=shares,
                stop=stop,
                target=target,
                score=score,
                entry_bar_index=bar_index,
                trailing_high=None,
                initial_stop_distance=max(entry_price - stop, 0.0),
            )
        )

    # --- public API --------------------------------------------------------

    def run(self) -> dict:
        self._load()
        if not self.data:
            return self._empty_result()

        # Unified, ascending trading calendar across all tickers.
        all_dates = sorted(set().union(*[df.index for df in self.data.values()]))

        for day in all_dates:
            # 1. Exit pass
            still_open = []
            for pos in self.open_positions:
                closed = self._check_exit(pos, day)
                if closed is None:
                    still_open.append(pos)
            self.open_positions = still_open

            # 2. Collect entry candidates
            candidates = []
            for ticker, df in self.data.items():
                if day not in df.index:
                    continue
                if any(p.ticker == ticker for p in self.open_positions):
                    continue
                idx = df.index.get_loc(day)
                if idx == 0:
                    continue
                row = df.iloc[idx]
                prev = df.iloc[idx - 1]
                if not entry_signal(
                    row,
                    prev,
                    rsi_lower=self.rsi_lower,
                    rsi_upper=self.rsi_upper,
                    volume_multiplier=self.volume_multiplier,
                    strict_crossover=self.strict_crossover,
                ):
                    continue
                candidates.append(
                    {
                        "ticker": ticker,
                        "row": row,
                        "bar_index": idx,
                        "score": candidate_score(row),
                    }
                )

            # 3. Rank & gate
            candidates.sort(key=lambda c: c["score"], reverse=True)

            # Equity snapshot at start of entry pass (mark-to-market with today's close).
            equity = self._mark_to_market(day)

            for cand in candidates:
                if len(self.open_positions) >= self.max_positions:
                    self.rejected.append(
                        RejectedSignal(day, cand["ticker"], "max_positions", cand["score"])
                    )
                    continue

                row = cand["row"]
                entry = float(row["Close"])
                atr = float(row["atr"])
                if np.isnan(atr) or atr <= 0:
                    continue
                stop_dist = atr * self.atr_multiplier
                stop = entry - stop_dist
                target = entry + stop_dist * self.rr_ratio
                shares = int((equity * self.risk_per_trade) / stop_dist)
                if shares < 1:
                    continue

                # Exposure gate — sum current notional + candidate notional.
                current_notional = 0.0
                for p in self.open_positions:
                    pdf = self.data[p.ticker]
                    if day in pdf.index:
                        current_notional += p.shares * float(pdf.loc[day, "Close"])
                    else:
                        current_notional += p.shares * p.entry_price
                candidate_notional = shares * entry
                if (current_notional + candidate_notional) / max(equity, 1e-9) > self.max_portfolio_exposure:
                    self.rejected.append(
                        RejectedSignal(day, cand["ticker"], "max_exposure", cand["score"])
                    )
                    continue

                # Skip if we don't have the cash to fund the entry.
                if candidate_notional * (1.0 + COMMISSION) > self.cash:
                    self.rejected.append(
                        RejectedSignal(day, cand["ticker"], "max_exposure", cand["score"])
                    )
                    continue

                self._open(
                    ticker=cand["ticker"],
                    day=day,
                    entry_price=entry,
                    shares=shares,
                    stop=stop,
                    target=target,
                    score=cand["score"],
                    bar_index=cand["bar_index"],
                )

            self.equity_curve.append((day, self._mark_to_market(day)))

        # Close any still-open positions at the last known close of their ticker
        # so we can fairly report total return.
        last_day = all_dates[-1]
        for pos in list(self.open_positions):
            df = self.data[pos.ticker]
            price = float(df["Close"].iloc[-1])
            self._close(pos, last_day, price, "end_of_data")
        self.open_positions = []

        return self._build_result(all_dates)

    # --- results -----------------------------------------------------------

    def _empty_result(self) -> dict:
        return {
            "aggregate": {
                "trades": 0,
                "win_rate": 0.0,
                "total_return": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": None,
                "expectancy_pct": None,
                "avg_winner_pct": None,
                "avg_loser_pct": None,
                "winner_loser_ratio": None,
                "final_equity": STARTING_CASH,
            },
            "trades": [],
            "rejected": [],
            "period": "",
        }

    def _build_result(self, all_dates) -> dict:
        trades = self.closed_trades
        n = len(trades)

        if n == 0:
            agg = {
                "trades": 0,
                "win_rate": 0.0,
                "total_return": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": None,
                "expectancy_pct": None,
                "avg_winner_pct": None,
                "avg_loser_pct": None,
                "winner_loser_ratio": None,
                "final_equity": STARTING_CASH,
            }
        else:
            wins = [t for t in trades if t.pnl_dollars > 0]
            losses = [t for t in trades if t.pnl_dollars <= 0]
            win_rate = len(wins) / n
            gross_wins = sum(t.pnl_dollars for t in wins)
            gross_losses = sum(t.pnl_dollars for t in losses)
            if gross_losses < 0 and gross_wins > 0:
                pf = gross_wins / abs(gross_losses)
            elif gross_losses == 0 and gross_wins > 0:
                pf = float("inf")
            else:
                pf = None
            avg_winner_pct = (
                (sum(t.return_pct for t in wins) / len(wins)) * 100 if wins else None
            )
            avg_loser_pct = (
                (sum(t.return_pct for t in losses) / len(losses)) * 100 if losses else None
            )
            expectancy_pct = (sum(t.return_pct for t in trades) / n) * 100
            if avg_winner_pct is not None and avg_loser_pct not in (None, 0):
                wl = avg_winner_pct / abs(avg_loser_pct)
            else:
                wl = None

            # Equity-curve metrics
            equity_series = pd.Series(
                {d: eq for d, eq in self.equity_curve}
            ).sort_index()
            final_equity = float(equity_series.iloc[-1])
            total_return = (final_equity - STARTING_CASH) / STARTING_CASH
            running_max = equity_series.cummax()
            drawdown = (equity_series - running_max) / running_max
            max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0

            agg = {
                "trades": n,
                "win_rate": win_rate,
                "total_return": total_return,
                "max_drawdown": max_drawdown,
                "profit_factor": pf,
                "expectancy_pct": expectancy_pct,
                "avg_winner_pct": avg_winner_pct,
                "avg_loser_pct": avg_loser_pct,
                "winner_loser_ratio": wl,
                "final_equity": final_equity,
            }

        trade_log = [
            {
                "date": t.exit_date.strftime("%Y-%m-%d") if hasattr(t.exit_date, "strftime") else str(t.exit_date),
                "entry_date": t.entry_date.strftime("%Y-%m-%d") if hasattr(t.entry_date, "strftime") else str(t.entry_date),
                "ticker": t.ticker,
                "side": "long",
                "shares": t.shares,
                "entry_price": round(t.entry_price, 4),
                "exit_price": round(t.exit_price, 4),
                "return_pct": round(t.return_pct, 6),
                "pnl_dollars": round(t.pnl_dollars, 2),
                "exit_reason": t.exit_reason,
                "score": round(t.score, 4),
            }
            for t in trades
        ]

        rejected_log = [
            {
                "date": r.date.strftime("%Y-%m-%d") if hasattr(r.date, "strftime") else str(r.date),
                "ticker": r.ticker,
                "reason": r.reason,
                "score": round(r.score, 4),
            }
            for r in self.rejected
        ]

        period = ""
        if all_dates:
            period = (
                f"{pd.Timestamp(all_dates[0]).date().isoformat()} → "
                f"{pd.Timestamp(all_dates[-1]).date().isoformat()}"
            )

        return {
            "aggregate": agg,
            "trades": trade_log,
            "rejected": rejected_log,
            "period": period,
        }


def run_portfolio_backtest(
    years: int = 3,
    ema_fast: int = settings.EMA_FAST,
    ema_slow: int = settings.EMA_SLOW,
    rsi_period: int = settings.RSI_PERIOD,
    rsi_lower: float = settings.RSI_LOWER,
    rsi_upper: float = settings.RSI_UPPER,
    volume_multiplier: float = settings.VOLUME_MULTIPLIER,
    atr_period: int = settings.ATR_PERIOD,
    atr_multiplier: float = settings.ATR_STOP_MULTIPLIER,
    rr_ratio: float = settings.RR_RATIO_MIN,
    max_hold_days: int = settings.MAX_HOLD_DAYS,
    strict_crossover: bool = settings.STRICT_CROSSOVER,
    tickers: Optional[list] = None,
    data_loader=fetch_data,
) -> dict:
    """Run the portfolio simulator and return the enriched result dict."""
    sim = PortfolioSimulator(
        years=years,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_period=rsi_period,
        rsi_lower=rsi_lower,
        rsi_upper=rsi_upper,
        volume_multiplier=volume_multiplier,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier,
        rr_ratio=rr_ratio,
        max_hold_days=max_hold_days,
        strict_crossover=strict_crossover,
        tickers=list(tickers) if tickers is not None else list(WATCHLIST),
        data_loader=data_loader,
    )
    result = sim.run()

    params = dict(
        years=years,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_period=rsi_period,
        rsi_lower=rsi_lower,
        rsi_upper=rsi_upper,
        volume_multiplier=volume_multiplier,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier,
        rr_ratio=rr_ratio,
        max_hold_days=max_hold_days,
        strict_crossover=strict_crossover,
    )
    result["params"] = params
    if not result.get("period"):
        end = date.today()
        try:
            start = date(end.year - years, end.month, end.day)
        except ValueError:
            start = date(end.year - years, end.month, 28)
        result["period"] = f"{start.isoformat()} → {end.isoformat()}"
    return result
