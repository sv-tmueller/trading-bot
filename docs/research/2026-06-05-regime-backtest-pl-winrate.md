# Regime-filter backtest — P/L & win rate (UPRO, 5y & 10y)

**Date:** 2026-06-05 · **Issue:** #220 · **Harness:** `backtest/regime.py` (`venv/bin/python main.py backtest`)

## Strategy under test
The live MVP 2.0 strategy: hold **UPRO** (3× S&P 500) when SPY closes **above** its 200-day SMA, else **CASH**. Binary in/out, 100% deploy on LONG. Benchmark for the signal is SPY; vehicle is UPRO.

## Results

| Metric | **Strategy** 5y | B&H UPRO 5y | B&H SPY 5y | **Strategy** 10y | B&H UPRO 10y | B&H SPY 10y |
|---|---|---|---|---|---|---|
| Total return | **+146.4%** | +186.5% | +92.0% | **+554.0%** | +1282.9% | +321.6% |
| CAGR | **+19.8%** | +23.4% | +13.9% | **+20.7%** | +30.0% | +15.5% |
| Max drawdown | **−38.1%** | −63.9% | −24.5% | **−50.2%** | −76.8% | −33.7% |
| Trades (round-trips) | 12 | — | — | 26 | — | — |
| Win rate | 50% | — | — | 38% | — | — |
| Avg win / avg loss | +27.8% / −6.5% | — | — | +40.1% / −5.6% | — | — |

(5y window 2021-06-05→2026-06-05; 10y 2016-06-05→2026-06-05.)

## Interpretation
- **Solid absolute P/L** (~+20% CAGR both windows) and it **beats 1× SPY** clearly — it captures leveraged upside.
- It **trails buy-and-hold UPRO on raw return** (expected: cash periods miss some rebound). **Its value is drawdown reduction**: −38% vs −64% (5y), −50% vs −77% (10y). This is a *risk-management overlay on a 3× vehicle*, not a return-maximizer.
- **Win rate (38–50%) is the wrong lens.** This is a trend strategy: **wins are ~4–7× the size of losses** (+28%/+40% vs −6%/−6%). The edge is asymmetry/expectancy, not hit-rate — many small whipsaw losses, a few large trend wins.

## Caveats (read before quoting these numbers)
- **The 25% kill-switch is NOT modelled** (the daily-bar yfinance feed has no intraday). The live bot's kill-switch would cap intraday drawdowns, so real max-DD should be **better** than shown (with some added whipsaw cost).
- **Cash earns 0%** (conservative). Real T-bill yield during cash periods — material in the 2022–2024 high-rate era — would add a couple of % to CAGR.
- Frictions modelled: 0.05% slippage + 0.05% commission **per side**. Execution at **next day's open** after the signal.
- Uses **real UPRO prices**, so 3× daily-rebalance volatility decay is included (not a synthetic 3×-of-SPX).
- Win rate over a 200-DMA filter is computed on few round-trips (12 / 26), so it's a coarse statistic.

## Bottom line
The regime filter does what it's designed to do: it keeps most of a 3× vehicle's upside while roughly **halving its worst drawdown**, and it beats unleveraged SPY. It is **not** expected to beat buy-and-hold UPRO on raw return in a strong bull — the trade-off is survivability. The unmodelled kill-switch is additional downside protection on top.

## Reproduce
```bash
venv/bin/python main.py backtest --years 5    # also --years 10
# vehicle defaults to UPRO, benchmark SPY, sma 200 (backtest/regime.py)
```
