from __future__ import annotations

import pandas as pd
import ta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from config import settings


def get_data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)


def fetch_bars(ticker: str, days: int = 60) -> pd.DataFrame:
    from datetime import datetime, timedelta, timezone
    client = get_data_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 15)  # buffer for weekends/holidays
    feed = DataFeed.SIP if settings.DATA_FEED == "sip" else DataFeed.IEX
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=feed,
    )
    bars = client.get_stock_bars(request).df
    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.xs(ticker, level=0)
    bars = bars[["open", "high", "low", "close", "volume"]].tail(days)
    return bars


def compute_signals(
    bars: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> dict:
    close = bars["close"]
    volume = bars["volume"]

    ema_fast_series = ta.trend.ema_indicator(close, window=ema_fast)
    ema_slow_series = ta.trend.ema_indicator(close, window=ema_slow)
    rsi_series = ta.momentum.rsi(close, window=rsi_period)
    atr_series = ta.volatility.average_true_range(
        bars["high"], bars["low"], close, window=atr_period
    )
    avg_volume = volume.rolling(20).mean()

    ema_f = ema_fast_series.iloc[-1]
    ema_s = ema_slow_series.iloc[-1]
    ema_f_prev = ema_fast_series.iloc[-2]
    ema_s_prev = ema_slow_series.iloc[-2]

    crossover = bool((ema_f > ema_s) and (ema_f_prev <= ema_s_prev))

    return {
        "ema_fast": round(float(ema_f), 4),
        "ema_slow": round(float(ema_s), 4),
        "rsi": round(float(rsi_series.iloc[-1]), 2),
        "volume_ratio": round(float(volume.iloc[-1] / avg_volume.iloc[-1]), 3),
        "atr": round(float(atr_series.iloc[-1]), 4),
        "ema_crossover": crossover,
    }


def is_entry_signal(
    signals: dict,
    rsi_lower: float = 40,
    rsi_upper: float = 60,
    volume_multiplier: float = 1.5,
) -> bool:
    return (
        signals["ema_crossover"] is True
        and rsi_lower <= signals["rsi"] <= rsi_upper
        and signals["volume_ratio"] >= volume_multiplier
    )
