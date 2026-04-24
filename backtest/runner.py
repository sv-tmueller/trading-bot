from __future__ import annotations

from datetime import date

from backtesting import Backtest

from config import settings
from config.watchlist import WATCHLIST
from backtest.data import fetch_data
from backtest.strategy import EMAStrategy
from backtest.report import format_terminal, notify_backtest


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
) -> dict:
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
    for ticker in WATCHLIST:
        df = fetch_data(ticker, years=years)
        bt = Backtest(df, EMAStrategy, cash=100_000, commission=0.001, exclusive_orders=True)
        stats = bt.run(**strategy_params)

        n_trades = int(stats["# Trades"])
        win_rate = float(stats["Win Rate [%]"]) / 100 if n_trades > 0 else 0.0
        total_return = float(stats["Return [%]"]) / 100
        max_dd = float(stats["Max. Drawdown [%]"]) / 100

        ticker_results[ticker] = {
            "trades": n_trades,
            "win_rate": win_rate,
            "total_return": total_return,
            "max_drawdown": max_dd,
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

    result = {
        "params": params,
        "period": period_str,
        "tickers": ticker_results,
        "aggregate": {
            "trades": all_trades,
            "win_rate": round(agg_win_rate, 4),
            "total_return": round(agg_return, 4),
            "max_drawdown": round(worst_dd, 4),
        },
    }

    print(format_terminal(result))
    notify_backtest(result)
    return result
