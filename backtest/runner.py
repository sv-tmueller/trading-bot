from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from backtesting import Backtest

from config import settings
from config.watchlist import WATCHLIST
from backtest.data import fetch_data
from backtest.strategy import EMAStrategy
from backtest.report import format_terminal, notify_backtest


def _safe_float(value) -> Optional[float]:
    """Convert a stats value to float, returning None for NaN / missing."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check without importing math
        return None
    return f


def _compute_trade_metrics(trades: pd.DataFrame) -> dict:
    """Compute winner/loser stats from a per-trade DataFrame.

    Expects a `ReturnPct` column (fraction, not %). Handles empty,
    all-winner and all-loser cases without raising.
    """
    if trades is None or len(trades) == 0:
        return {
            "avg_winner_pct": None,
            "avg_loser_pct": None,
            "winner_loser_ratio": None,
        }

    winners = trades[trades["ReturnPct"] > 0]["ReturnPct"]
    losers = trades[trades["ReturnPct"] <= 0]["ReturnPct"]

    avg_winner_pct = float(winners.mean()) * 100 if len(winners) > 0 else None
    avg_loser_pct = float(losers.mean()) * 100 if len(losers) > 0 else None

    if avg_winner_pct is not None and avg_loser_pct is not None and avg_loser_pct != 0:
        winner_loser_ratio = avg_winner_pct / abs(avg_loser_pct)
    else:
        winner_loser_ratio = None

    return {
        "avg_winner_pct": avg_winner_pct,
        "avg_loser_pct": avg_loser_pct,
        "winner_loser_ratio": winner_loser_ratio,
    }


def _compute_aggregate_metrics(all_trades: pd.DataFrame) -> dict:
    """Pool every trade from every ticker and compute aggregate metrics
    weighted by trade (not by ticker).

    Expects `ReturnPct` (fraction) and `PnL` (dollars) columns.
    """
    if all_trades is None or len(all_trades) == 0:
        return {
            "profit_factor": None,
            "expectancy_pct": None,
            "avg_winner_pct": None,
            "avg_loser_pct": None,
            "winner_loser_ratio": None,
        }

    winners_pnl = all_trades[all_trades["PnL"] > 0]["PnL"]
    losers_pnl = all_trades[all_trades["PnL"] <= 0]["PnL"]

    gross_wins = float(winners_pnl.sum()) if len(winners_pnl) > 0 else 0.0
    gross_losses = float(losers_pnl.sum()) if len(losers_pnl) > 0 else 0.0

    if gross_losses < 0 and gross_wins > 0:
        profit_factor = gross_wins / abs(gross_losses)
    elif gross_losses == 0 and gross_wins > 0:
        profit_factor = float("inf")  # all winners
    else:
        profit_factor = None

    # Expectancy: mean % return per trade
    expectancy_pct = float(all_trades["ReturnPct"].mean()) * 100

    per_trade = _compute_trade_metrics(all_trades)

    return {
        "profit_factor": profit_factor,
        "expectancy_pct": expectancy_pct,
        "avg_winner_pct": per_trade["avg_winner_pct"],
        "avg_loser_pct": per_trade["avg_loser_pct"],
        "winner_loser_ratio": per_trade["winner_loser_ratio"],
    }


def run_backtest(
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
    portfolio: bool = False,
) -> dict:
    if portfolio:
        from backtest.portfolio import run_portfolio_backtest
        from backtest.report import format_portfolio

        result = run_portfolio_backtest(
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
        print(format_portfolio(result))
        return result
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

    strategy_params = {k: v for k, v in params.items() if k != "years"}

    end = date.today()
    try:
        start = date(end.year - years, end.month, end.day)
    except ValueError:
        start = date(end.year - years, end.month, 28)
    period_str = f"{start.isoformat()} → {end.isoformat()}"
    if years == 1:
        print("⚠️  Single-year backtest — results may not reflect strategy robustness across different market regimes.")

    ticker_results: dict = {}
    pooled_trades: list = []
    for ticker in WATCHLIST:
        df = fetch_data(ticker, years=years)
        bt = Backtest(df, EMAStrategy, cash=100_000, commission=0.001, exclusive_orders=True)
        stats = bt.run(**strategy_params)

        n_trades = int(stats["# Trades"])
        win_rate = float(stats["Win Rate [%]"]) / 100 if n_trades > 0 else 0.0
        total_return = float(stats["Return [%]"]) / 100
        max_dd = float(stats["Max. Drawdown [%]"]) / 100

        trades_df = getattr(stats, "_trades", None)
        trade_metrics = _compute_trade_metrics(trades_df)

        if trades_df is not None and len(trades_df) > 0:
            pooled_trades.append(trades_df[["ReturnPct", "PnL"]].copy())

        ticker_results[ticker] = {
            "trades": n_trades,
            "win_rate": win_rate,
            "total_return": total_return,
            "max_drawdown": max_dd,
            "profit_factor": _safe_float(stats["Profit Factor"]) if "Profit Factor" in stats else None,
            "expectancy_pct": _safe_float(stats["Expectancy [%]"]),
            "best_trade_pct": _safe_float(stats["Best Trade [%]"]),
            "worst_trade_pct": _safe_float(stats["Worst Trade [%]"]),
            "avg_winner_pct": trade_metrics["avg_winner_pct"],
            "avg_loser_pct": trade_metrics["avg_loser_pct"],
            "winner_loser_ratio": trade_metrics["winner_loser_ratio"],
        }

    all_trades = sum(v["trades"] for v in ticker_results.values())
    if all_trades > 0:
        agg_win_rate = (
            sum(v["win_rate"] * v["trades"] for v in ticker_results.values()) / all_trades
        )
    else:
        agg_win_rate = 0.0
    agg_return = sum(v["total_return"] for v in ticker_results.values()) / len(ticker_results)
    worst_dd = min(v["max_drawdown"] for v in ticker_results.values())

    pooled_df = (
        pd.concat(pooled_trades, ignore_index=True) if pooled_trades else pd.DataFrame(columns=["ReturnPct", "PnL"])
    )
    agg_metrics = _compute_aggregate_metrics(pooled_df)

    result = {
        "params": params,
        "period": period_str,
        "tickers": ticker_results,
        "aggregate": {
            "trades": all_trades,
            "win_rate": round(agg_win_rate, 4),
            "total_return": round(agg_return, 4),
            "max_drawdown": round(worst_dd, 4),
            "profit_factor": agg_metrics["profit_factor"],
            "expectancy_pct": agg_metrics["expectancy_pct"],
            "avg_winner_pct": agg_metrics["avg_winner_pct"],
            "avg_loser_pct": agg_metrics["avg_loser_pct"],
            "winner_loser_ratio": agg_metrics["winner_loser_ratio"],
        },
    }

    print(format_terminal(result))
    notify_backtest(result)
    return result
