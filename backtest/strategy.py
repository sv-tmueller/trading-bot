from __future__ import annotations

import numpy as np
import pandas as pd
import ta as ta_lib
from backtesting import Strategy


class EMAStrategy(Strategy):
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_lower: float = 40.0
    rsi_upper: float = 60.0
    volume_multiplier: float = 1.5
    atr_period: int = 14
    atr_multiplier: float = 1.5
    rr_ratio: float = 2.0
    max_hold_days: int = 5
    strict_crossover: bool = True

    def init(self) -> None:
        def _ema(arr: np.ndarray, window: int) -> np.ndarray:
            return ta_lib.trend.ema_indicator(pd.Series(arr), window=window).values

        def _rsi(arr: np.ndarray, window: int) -> np.ndarray:
            return ta_lib.momentum.rsi(pd.Series(arr), window=window).values

        def _atr(
            high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int
        ) -> np.ndarray:
            return ta_lib.volatility.average_true_range(
                pd.Series(high), pd.Series(low), pd.Series(close), window=window
            ).values

        def _vol_sma(arr: np.ndarray) -> np.ndarray:
            return pd.Series(arr).rolling(20).mean().values

        self._ema_f = self.I(_ema, self.data.Close, self.ema_fast)
        self._ema_s = self.I(_ema, self.data.Close, self.ema_slow)
        self._rsi_ind = self.I(_rsi, self.data.Close, self.rsi_period)
        self._atr_ind = self.I(
            _atr, self.data.High, self.data.Low, self.data.Close, self.atr_period
        )
        self._vol_sma = self.I(_vol_sma, self.data.Volume)

    def next(self) -> None:
        if self.position:
            current_bar = len(self.data) - 1
            for trade in list(self.trades):
                if current_bar - trade.entry_bar >= self.max_hold_days:
                    trade.close()
            return

        ema_f = self._ema_f[-1]
        ema_s = self._ema_s[-1]
        ema_f_prev = self._ema_f[-2]
        ema_s_prev = self._ema_s[-2]
        rsi = self._rsi_ind[-1]
        atr = self._atr_ind[-1]
        vol_sma = self._vol_sma[-1]

        if any(np.isnan(v) for v in (ema_f, ema_s, ema_f_prev, ema_s_prev, rsi, atr, vol_sma)):
            return

        if self.strict_crossover:
            ema_ok = bool((ema_f > ema_s) and (ema_f_prev <= ema_s_prev))
        else:
            ema_ok = bool(ema_f > ema_s)
        rsi_ok = self.rsi_lower <= rsi <= self.rsi_upper
        vol_ok = (self.data.Volume[-1] / vol_sma) >= self.volume_multiplier

        if not (ema_ok and rsi_ok and vol_ok):
            return

        stop_dist = atr * self.atr_multiplier
        entry = self.data.Close[-1]
        sl = entry - stop_dist
        tp = entry + stop_dist * self.rr_ratio
        shares = max(1, int((self.equity * 0.01) / stop_dist))

        self.buy(size=shares, sl=sl, tp=tp)
