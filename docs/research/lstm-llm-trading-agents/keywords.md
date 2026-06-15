# LSTM/LLM Autonomous Trading Agents — Keywords

A high-signal vocabulary used as input for further web research into the "LSTM + LLM autonomous trading agent" genre (typified by YouTube experiments running 100 agents × 1,000 USDT on crypto perpetuals with a 1% daily target). Categories are tailored to this topic: model architectures, retraining pipelines, backtest integrity, LLM-agent patterns, perps mechanics, and the marketing vocabulary of the genre itself. Used as a vocabulary baseline by the rest of the bundle.

## ML Model Architectures for Time Series

- LSTM — Long Short-Term Memory
- GRU — Gated Recurrent Unit
- TCN — Temporal Convolutional Network
- Transformer / attention mechanism
- PatchTST — patch-based time-series Transformer
- TFT — Temporal Fusion Transformer
- N-BEATS / N-HiTS
- DLinear — linear baseline that often beats deep forecasters
- State-space models / Mamba
- Time-series foundation models (Chronos, TimesFM, Lag-Llama, Moirai)

## Features & Forecasting Targets

- OHLCV bars
- Log returns
- Direction classification vs price regression
- Lookback window / forecast horizon
- Feature engineering / technical-indicator features
- Normalization leakage — scaler fit on full dataset including test period
- Stationarity / differencing
- Random-walk hypothesis / martingale property of returns
- Signal-to-noise ratio

## Training & Retraining Pipeline

- Walk-forward optimization
- Rolling vs expanding window
- Online learning / incremental retraining
- Concept drift
- Covariate shift / data drift
- Drift detection (ADWIN — adaptive windowing; DDM — Drift Detection Method)
- Model decay
- Champion–challenger deployment
- Hyperparameter search (Optuna, grid search)

## Backtest Integrity & Overfitting Pathologies

- Look-ahead bias
- Data leakage
- Survivorship bias
- Curve fitting / overfitting
- Purged k-fold CV with embargo
- In-sample vs out-of-sample
- Deflated Sharpe Ratio
- PBO — Probability of Backtest Overfitting
- CSCV — Combinatorially Symmetric Cross-Validation
- Multiple-testing / strategy-selection bias
- Backtest–live gap
- Transaction-cost and slippage modeling

## Performance Metrics

- Sharpe ratio / Sortino ratio
- Calmar ratio
- CAGR — Compound Annual Growth Rate
- Max drawdown
- Profit factor
- Win rate / hit rate
- Expectancy
- Alpha / beta vs benchmark

## LLM-Agent Frameworks & Patterns

- ReAct — reason-and-act prompting loop
- Reflexion / self-reflection
- Tool use / function calling
- RAG — Retrieval-Augmented Generation
- Multi-agent debate
- Role-play agent teams (analyst / trader / risk-manager personas)
- Layered agent memory
- FinMem / FinAgent / TradingAgents (academic LLM-trading frameworks)
- FinGPT / FinRL (AI4Finance ecosystem)
- AI-Trader (HKUDS)
- Alpha Arena (Nof1) — live LLM trading competition on Hyperliquid
- Agent Market Arena / LiveTradeBench / InvestorBench — LLM-trading benchmarks
- Structured output / JSON mode
- Hallucination / prompt injection

## Sentiment & News Signals

- FinBERT — finance-tuned BERT for sentiment
- News sentiment score
- Social sentiment (X/Twitter, Reddit, StockTwits)
- Crypto Fear & Greed Index
- Alternative data
- Sentiment decay / news staleness

## Reinforcement Learning for Trading

- DQN — Deep Q-Network
- PPO — Proximal Policy Optimization
- A2C / SAC — Advantage Actor-Critic / Soft Actor-Critic
- Action space (long / flat / short)
- Reward shaping / transaction-cost-aware reward
- Gym-style market environment
- Sim-to-real gap

## Crypto-Perpetuals Mechanics

- Perpetual futures ("perps")
- USDT-margined (linear) vs coin-margined (inverse) contracts
- Funding rate
- Mark price vs index price vs last price
- Liquidation price
- Initial margin / maintenance margin
- Cross vs isolated margin
- Leverage
- ADL — Auto-Deleveraging
- Maker / taker fees
- Scalping on perps

## Risk Management

- Position sizing (fixed-fractional, Kelly criterion)
- Stop-loss / take-profit
- Daily loss limit
- Max drawdown limit / kill switch
- Exposure cap / leverage cap
- Volatility targeting
- Risk of ruin
- Fat tails / gap risk

## Performance-Claim & Marketing Vocabulary (the genre)

- "1% daily" compounding claim — implies ~3,700% annualized
- 100-agent spectacle — many parallel accounts so some always look profitable
- Survivorship curation — promoting winning agents, hiding losers
- Live-stream P&L / screenshot P&L
- Cherry-picked trades / win-rate inflation
- Martingale / grid bot / DCA bot — loss-averaging schemes marketed as "AI"
- Signal group / signal seller
- Copy trading
- Prop-firm challenge / funded account (FTMO-style)
- Verified track record (Myfxbook-style) vs backtest-only claims
- "Passive income" framing / affiliate-referral funnel

## Baselines & Regime Filters

- Buy-and-hold
- 200-DMA regime filter — 200-day simple moving average
- Time-series momentum / trend following
- Dual momentum
- Volatility-targeted benchmark
- Random-entry baseline
- Cost-adjusted benchmark comparison

## Datasets & Benchmarks

- Binance klines API / testnet
- CCXT — unified crypto-exchange API library
- Alpaca market data
- yfinance
- Point-in-time data / survivorship-bias-free data (CRSP-style)
- Tick vs bar data
- M4 / M6 forecasting competitions
- LOBSTER — limit order book dataset

## Live Evaluation & Paper Trading

- Paper trading / forward testing
- Shadow mode
- Live-to-backtest slippage gap
- Implementation shortfall
- Execution latency
- Audit log / trade reconciliation
- Track-record length / statistical significance of live results
- Equity-curve monitoring / alerting
