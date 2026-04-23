from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_data(ticker: str, years: int = 1) -> pd.DataFrame:
    period = f"{years}y"
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df
