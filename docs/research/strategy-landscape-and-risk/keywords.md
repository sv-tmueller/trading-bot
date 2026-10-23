# Strategy Landscape and Risk Keywords

A high-signal vocabulary for researching how profitable algorithmic bots, quant funds / CTAs, and human retail / prop traders build strategies, combine them, and size and limit risk. Context: issue #675 (raising effective risk per trade from ~0.025% of account toward 0.1-1% via risk-based sizing). Indicator and candlestick vocabulary is already covered in [`../swing-trading/keywords.md`](../swing-trading/keywords.md) and is not repeated here.

Glosses are given only where a term is ambiguous or has competing definitions. Numeric conventions are noted only where checked against the sources listed at the bottom.

## Strategy Archetypes

- Trend following
- TSMOM -- time-series momentum (an asset vs its own past return; Moskowitz/Ooi/Pedersen 2012 used the trailing 12-month excess return across 58 futures)
- Cross-sectional momentum (an asset vs its peers; rank-and-hold winners/losers)
- Mean reversion
- Statistical arbitrage / pairs trading
- Cointegration
- Carry
- VRP -- volatility risk premium (systematic short-vol / option-selling)
- Market making
- Event-driven (earnings, index rebalances, M&A)
- Seasonality / calendar anomalies (turn-of-month, overnight effect)
- Breakout (range / opening-range / Donchian)

## Edge and Performance Metrics

- Expectancy (average win x win rate - average loss x loss rate)
- R-multiple (P&L expressed in units of initial risk, 1R = entry-to-stop distance x size)
- Win rate / hit rate
- Payoff ratio (average win / average loss)
- Profit factor (gross profit / gross loss)
- Sharpe ratio
- Sortino ratio
- Calmar ratio (annual return / max drawdown; sometimes MAR ratio, which uses full-history CAGR)
- Ulcer index
- Information ratio

## Backtest Validity and Overfitting

- DSR -- deflated Sharpe ratio (Bailey and Lopez de Prado 2014; corrects for multiple testing and non-normal returns)
- PBO -- probability of backtest overfitting (Bailey, Borwein, Lopez de Prado, Zhu; estimated via CSCV)
- CSCV -- combinatorially symmetric cross-validation
- Data snooping / p-hacking
- Survivorship bias
- Look-ahead bias
- Walk-forward analysis
- Out-of-sample / holdout
- Factor zoo
- Alpha decay

## Position Sizing

- Fixed fractional
- Percent risk per trade (dollar risk = account x risk %; size = dollar risk / stop distance)
- Fixed notional / fixed dollar (contrast with risk-based sizing)
- Kelly criterion
- Fractional Kelly / half-Kelly (half-Kelly keeps ~75% of full-Kelly growth at ~half the volatility; beyond 2x Kelly expected growth turns negative)
- Optimal f (Ralph Vince)
- Volatility targeting / vol scaling
- ATR-based sizing
- Inverse-volatility weighting
- Risk parity

## Loss Limits and Drawdown Controls

- Daily loss limit
- Weekly / monthly loss limit (Elder's "6% rule": stop opening trades for the rest of the month once losses plus open risk reach 6% of equity; exact wording varies by source)
- Max drawdown (peak-to-trough)
- Trailing drawdown vs static drawdown (trailing follows the equity high-water mark; static is measured from starting balance)
- High-water mark
- Circuit breaker / kill switch
- Drawdown-based de-leveraging (cut size after X% drawdown)
- Risk of ruin
- Max consecutive losses

## Portfolio Construction and Combining Strategies

- Strategy diversification
- Correlation / correlation breakdown (correlations converge toward 1 in crises)
- Effective number of bets
- Risk budgeting
- Ensemble / signal blending
- Strategy allocation (capital vs risk allocation across strategies)
- Regime switching
- Meta-labeling (Lopez de Prado; a secondary model decides whether to act on, and how much to size, a primary signal)
- Core-satellite
- Portfolio heat (sum of open risk across all positions)

## Fund / CTA Risk Practice

- Gross exposure vs net exposure
- Leverage cap
- Annualized volatility target (portfolio-level)
- VaR -- value at risk
- Expected shortfall / CVaR
- Stress testing / scenario analysis
- Sector / single-name concentration limit
- Correlated-exposure cap

## Prop-Firm and Retail Norms

- Funded account / evaluation (challenge)
- Profit target
- Max daily loss (FTMO 2-Step: 5% daily / 10% overall; the newer 1-Step is reported at 3% daily with end-of-day trailing max loss -- rules change, check the firm's page)
- Max overall loss
- Consistency rule (caps any single day's share of total profit; threshold varies by firm)
- Profit split
- 1% rule (ambiguous: canonically "risk at most 1% of account if the stop is hit", often misread as "put 1% of account into the position")
- 2% rule (same ambiguity; per-trade max loss at the stop, popularized by Elder; CME notes the 2% threshold is arbitrary)

## Execution and Costs

- Slippage
- Bid-ask spread
- Market impact
- Commissions / fees
- Turnover
- Cost wall (the point where turnover-driven costs erase gross edge; common in high-frequency retail backtests)
- Implementation shortfall

## Bot Ecosystem

- Grid bot
- DCA bot -- dollar-cost averaging (also "Martingale DCA" safety orders, which add size into losses)
- Copy trading / social trading
- Signal provider
- Freqtrade (stoploss, ROI table, protections, hyperopt)
- Hummingbot (market-making / arbitrage connectors)
- QuantConnect / LEAN (alpha, portfolio construction, risk management, execution models)
- Paper trading / forward test

## Market Regime

- Bull / bear regime
- High-vol / low-vol regime (VIX level)
- Trending vs range-bound (choppy)
- Volatility clustering
- Crisis alpha (trend followers profiting in sustained sell-offs)

## Psychology and Behaviour

- Overtrading
- Revenge trading
- Disposition effect (selling winners too early, holding losers too long)
- Loss aversion
- Tilt
- Rule drift / discretionary override

## Order Types and Risk Tools

- Bracket order
- OCO -- one-cancels-other
- Stop-loss (stop-market)
- Stop-limit
- Trailing stop
- Time stop
- Take-profit / profit target
- Gap risk (stop filled far through its price on an overnight gap)

## Sources

- https://papers.ssrn.com/abstract=2089463 (Moskowitz, Ooi, Pedersen, "Time Series Momentum")
- https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data
- https://papers.ssrn.com/abstract=2460551 (Bailey and Lopez de Prado, "The Deflated Sharpe Ratio")
- https://papers.ssrn.com/abstract=2326253 (Bailey, Borwein, Lopez de Prado, Zhu, "The Probability of Backtest Overfitting")
- https://ryanoconnellfinance.com/kelly-criterion/
- https://quantvault.org/kelly-criterion-interview-guide.html
- https://tradingfunder.com/ftmo-rules/
- https://www.pineconnector.com/blogs/pico-blog/ftmo-challenge-rules-automated-traders
- https://www.cmegroup.com/education/courses/trade-and-risk-management/the-2-percent-rule.html
- https://incrediblecharts.com/trading/2_percent_rule.php
- https://www.incrediblecharts.com/trading/6_percent_rule.php
- https://crosstrade.io/learn/risk-management/one-percent-rule
- https://tradethatswing.com/the-1-risk-rule-for-day-trading-and-swing-trading/
