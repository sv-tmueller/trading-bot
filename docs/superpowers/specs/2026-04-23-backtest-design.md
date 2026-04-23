# Backtesting Module Design

**Date:** 2026-04-23
**Status:** Approved

## Overview

Add a `python3 main.py backtest` command that runs the current EMA crossover strategy against 1–3 years of historical daily data using `backtesting.py` and `yfinance`. Each ticker in the watchlist is tested independently. Results are printed to the terminal and sent as a TLDR to Discord. The same `run_backtest()` function is importable by agents for autonomous parameter testing.

---

## Architecture

New module `backtest/` alongside existing `agents/`, `tools/`, `monitor/`:

```
backtest/
    __init__.py
    runner.py      # entry point, called from main.py and agents
    strategy.py    # backtesting.py Strategy subclass
    data.py        # yfinance data fetcher
    report.py      # terminal table + Discord TLDR formatter
```

`main.py` gets a new `backtest` branch that parses CLI args and calls `run_backtest(**params)`.

---

## Data

- Source: `yfinance` via `data.py`
- `yfinance.download(ticker, period="1y")` returns adjusted OHLCV DataFrame
- Lookback: `"1y"` (default), `"2y"`, `"3y"` — maps directly to yfinance period strings
- Tickers: all 8 from `config/watchlist.py` (AMD, NOW, SHEL, NVDA, MSFT, GOOGL, META, AMZN)
- Fresh fetch on each run, no local caching

---

## Strategy Parameters

Defaults mirror `config/settings.py` exactly so a default run tests the live bot's current configuration:

| Parameter | Default | Source |
|---|---|---|
| `ema_fast` | 20 | `settings.EMA_FAST` |
| `ema_slow` | 50 | `settings.EMA_SLOW` |
| `rsi_period` | 14 | `settings.RSI_PERIOD` |
| `rsi_lower` | 40 | `settings.RSI_LOWER` |
| `rsi_upper` | 60 | `settings.RSI_UPPER` |
| `volume_multiplier` | 1.5 | `settings.VOLUME_MULTIPLIER` |
| `atr_period` | 14 | `settings.ATR_PERIOD` |
| `atr_multiplier` | 1.5 | `settings.ATR_STOP_MULTIPLIER` |
| `rr_ratio` | 2.0 | `settings.RR_RATIO_MIN` |
| `max_hold_days` | 5 | `settings.MAX_HOLD_DAYS` |
| `years` | 1 | CLI / programmatic arg |

All parameters are keyword-only with defaults, so callers override only what they need.

---

## Entry & Exit Logic

Mirrors the live bot exactly:

**Entry** — all three conditions must be true on the same bar:
1. EMA crossover: `ema_fast > ema_slow` AND `ema_fast_prev <= ema_slow_prev`
2. RSI in range: `rsi_lower ≤ RSI ≤ rsi_upper`
3. Volume confirmation: `volume / volume_sma_20 ≥ volume_multiplier`

**Position sizing:**
- Stop distance = `ATR × atr_multiplier`
- Shares = `floor((portfolio_value × 0.01) / stop_distance)`
- Stop-loss = `entry_price - stop_distance`
- Take-profit = `entry_price + (stop_distance × rr_ratio)`

**Exit** — first condition met wins (same priority as live monitor):
1. Price ≤ stop_loss → exit `stop_loss`
2. Price ≥ take_profit → exit `take_profit`
3. Hold days ≥ max_hold_days → exit `max_hold`

**Portfolio constraint note:** `backtesting.py` runs one ticker at a time. The max-5-positions constraint is not simulated — each ticker is tested independently. This is labeled clearly in output.

---

## Interfaces

### CLI

```bash
# defaults: 1 year, settings.py params
python3 main.py backtest

# overrides
python3 main.py backtest --years 2 --ema-fast 10 --ema-slow 30 --rsi-lower 35 --rsi-upper 65
```

All strategy parameters are optional CLI flags. Any omitted flag uses the `settings.py` default.

### Programmatic (for agents)

```python
from backtest.runner import run_backtest

result = run_backtest(years=1, ema_fast=10, ema_slow=30)
```

Returns a plain dict:

```python
{
    "params": {"ema_fast": 10, "ema_slow": 30, ...},
    "period": "2024-04-23 → 2025-04-23",
    "tickers": {
        "AMD": {"trades": 4, "win_rate": 0.50, "avg_r": 1.2, "return": 0.031, "max_drawdown": -0.024},
        ...
    },
    "aggregate": {
        "trades": 31,
        "win_rate": 0.548,
        "avg_r": 1.4,
        "total_return": 0.182,
        "max_drawdown": -0.041
    }
}
```

---

## Output

### Terminal

```
Backtest: 2024-04-23 → 2025-04-23  |  EMA 20/50  RSI 40-60  Hold ≤5d
(each ticker independent — max-positions constraint not simulated)

Ticker   Trades   Win%    Avg R   Total Return   Max DD
------   ------   ----    -----   ------------   ------
AMD          4    50.0%   1.2R        +3.1%       -2.4%
NVDA         6    66.7%   1.8R        +7.4%       -1.9%
...
------
TOTAL       31    54.8%   1.4R       +18.2%       -4.1%
```

If run with parameter overrides, the header shows the overridden values.

### Discord TLDR

Sent via existing `tools/notifications.py` webhook pattern:

```
Backtest (1y, EMA 20/50)
31 trades across 8 tickers
Win rate: 54.8% | Avg R: 1.4R | Return: +18.2% | Max DD: -4.1%
```

When run with parameter overrides, the header includes the changed params so each autonomous test run is identifiable in Discord history.

---

## New Dependencies

| Package | Version constraint | Purpose |
|---|---|---|
| `backtesting` | `>=0.6.5` | Backtest engine |
| `yfinance` | `>=0.2` | Historical data |

Add both to `requirements.txt`.

---

## Testing

Follows existing project conventions — no network calls, no real DB needed.

- **Fixture:** 60-bar synthetic OHLCV DataFrame constructed in `conftest.py` (minimum to warm up EMA50)
- **test_backtest_signal:** fixture contains a clear EMA crossover with RSI/volume conditions met → verifies exactly 1 trade opened and closed
- **test_backtest_no_signal:** fixture with no crossover → verifies 0 trades
- **test_backtest_param_override:** pass `ema_fast=5, ema_slow=10` → verifies strategy uses overridden values
- **test_report_keys:** pass a mock result dict to `report.py` → verifies all aggregate keys present

`data.py`'s `fetch_data()` is monkeypatched in tests (same pattern as `tools/market_data.py`).
