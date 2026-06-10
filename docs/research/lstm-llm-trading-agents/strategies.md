# Strategies — "LSTM/LLM Autonomous Trading Agents": Merged Top 15 (EN + DE)

This file merges the English-language (S-EN) and German-language (S-DE) survey outputs into the
canonical top 15 for the bundle topic: the "LSTM/LLM autonomous trading agents" genre (the
"100 agents / 1,000 USDT / 1% daily" YouTube format and its academic, practitioner, and regulatory
hinterland). Surveys were performed June 2026 against live web sources.

Entries are ordered: **model-class archetypes (1–5) → agent/tournament patterns (6–9) →
evidence-base entries (10–13) → deterministic baselines (14–15)**. Every verdict is applied against
the repo's architectural invariants: (1) one decision rule, reproducible from price history alone;
(2) no LLM in the trading path; (3) deterministic risk layer in charge. **`skip` is the modal
verdict by design** — this bundle is an evidence check on the genre, and the evidence is
overwhelmingly negative. Where EN and DE covered the same canonical item, the deeper treatment was
kept and the other survey's unique evidence and sources were merged in.

---

## 1. LSTM price prediction (the academic record, EN + DE)

- **Mechanism** — Train a recurrent network on lagged OHLCV (sometimes plus technical indicators) to predict next-period price or direction; trade the predicted sign. The published record is dominated by a known artifact: the network minimizes MSE by approximately echoing the last observed price (lag-1 persistence), which looks accurate on price charts but contains no tradable information. One diagnostic study reduced lag-1 autocorrelation of predictions from 0.89 to 0.23 only after deliberately re-engineering the task, and a 2026 feature-engineering study found a raw LSTM at 47.5% directional accuracy (below coin flip) with prediction-reality correlation of −0.066, attributing it to a ~0.8% signal-to-noise ratio. The German thesis literature replicates the negative result independently: a 2022 DACH small-caps Master's thesis (87 pp., 8 experiment series) concludes the LSTM models "in der Regel" cannot beat naive forecasts or simple moving averages on MAPE — even on supposedly less-efficient small caps.
- **Indicators / patterns**:
  - Lagged closes / log returns, rolling windows (30–60 bars typical)
  - Technical indicators (RSI, MACD, SMA crossovers) and calendar dummies as input features
  - MSE/MAE loss on price level (the canonical mistake) or classification on direction
  - Walk-forward or (often, wrongly) random-shuffle cross-validation; MAPE/RMSE vs naive-forecast baselines in the DE thesis pipeline
- **Typical timeframe** — daily bars in academia; minutes-to-hours in the YouTube/crypto genre.
- **Pros**:
  - Cheap to train; inference is deterministic once weights are frozen
  - Genuinely useful for *volatility* and order-flow microstructure features in some institutional settings (not direction)
  - The DE thesis record contains honest negative results — rare in this space
- **Cons**:
  - Persistence artifact systematically inflates reported accuracy; an LSTM minimizing RMSE on near-random-walk prices converges to "predict roughly yesterday's price"
  - Many published results evaporate under leakage-aware evaluation (a 2025 study showed up to 20.5% RMSE inflation from sequence-construction leakage under k-fold CV)
  - Naive/linear baselines repeatedly match or beat LSTMs out-of-sample; a 2026 arXiv study found the full deep pipeline underperformed a simple linear baseline on investor-flow prediction
  - Direction-accuracy claims (e.g. a 2019 Buchs Bachelor's thesis reporting >70% directional hits on some configurations while overall results were "not significantly better than chance" — secondary summary, original PDF unreachable, treat as unverified) typically vanish OOS or under costs; none of the German theses found demonstrate a profitable trading rule net of costs
  - Training is non-reproducible from price history alone (random init, GPU nondeterminism) — violates the bot's "reproducible from SPY history" property by construction
- **Fit with our bot** — The model class fails its own academic benchmarks in two languages and cannot satisfy the pure-function reproducibility requirement; nothing here merits even a research-layer evaluation ahead of better-evidenced candidates. **`skip`**
- **Evidence quality** — `academic` (the *critiques* are academic; the positive claims are mostly low-tier venues, theses, and Medium posts).
- **Sources**:
  - https://arxiv.org/pdf/2601.07131 (2026) — "The Limits of Complexity": full LSTM pipeline underperforms linear baseline
  - https://arxiv.org/abs/2512.06932 (2025) — "Hidden Leaks in Time Series Forecasting" (LSTM leakage quantification)
  - https://www.researchsquare.com/article/rs-8703148/v1 — persistence-problem mitigation paper (lag-1 autocorr 0.89→0.23)
  - https://www.kaggle.com/code/carlmcbrideellis/lstm-time-series-stock-price-prediction-fail — practitioner demonstration of the echo artifact
  - https://www.grin.com/document/1303518?lang=en (2022) — DACH small-caps LSTM Master's thesis (negative OOS result)
  - https://www.grin.com/document/980345 — German LSTM stock-prediction thesis
  - https://docplayer.org/177628859-Vorhersage-von-aktienkursen-mittels-tiefen-lstm-netzwerken.html (unverified, fetch failed)
  - https://www.ini.rub.de/upload/file/1521461530_7126db755dc03bec85b1/dada-bsc.pdf — Bachelor's thesis, deep LSTM stock prediction

## 2. Transformer / time-series foundation models (Chronos, TimesFM, TimeGPT) for returns

- **Mechanism** — Pre-train a large sequence model on millions of heterogeneous time series, then zero-shot or fine-tune it to forecast asset returns. The direct test exists: "Re(Visiting) Time Series Foundation Models in Finance" (arXiv 2511.18578, 2025) evaluated Chronos, TimesFM, and TimeGPT on daily excess-return forecasting and found them weak zero-shot, *underperforming gradient-boosted trees (CatBoost/LightGBM)* — i.e., the frontier of foundation-model forecasting loses to a 2017-era tabular baseline on the one task this genre cares about.
- **Indicators / patterns**:
  - Pre-trained TSFM checkpoints (Chronos/Amazon, TimesFM/Google, TimeGPT/Nixtla, Moirai)
  - Zero-shot prompting with context windows of past returns; optional fine-tuning
  - Probabilistic forecast heads (quantiles) rarely converted honestly into position sizing
- **Typical timeframe** — daily; some intraday demos.
- **Pros**:
  - Honest, recent, negative benchmark exists — rare in this genre
  - Useful for *forecast plumbing* (seasonality, demand), just not equity risk premia
  - Scale helps a little (larger Chronos/TimesFM variants improve monotonically); zero-shot deployment is operationally simple
- **Cons**:
  - Still loses to boosted trees on returns; no cost-aware trading evaluation
  - Model weights are vendor-controlled, so signals are not reproducible from price history; silent model-version drift
  - M4 precedent: all six pure-ML entries lost to the statistical combination benchmark and only one beat Naïve2
  - API-served models (TimeGPT) put a vendor in the decision path — same auditability problem as an LLM
- **Fit with our bot** — A vendor-served black-box forecaster in the decision path fails reproducibility and adds no demonstrated edge over trivial baselines. **`skip`**
- **Evidence quality** — `academic`.
- **Sources**:
  - https://arxiv.org/abs/2511.18578 (2025) — Re(Visiting) Time Series Foundation Models in Finance
  - https://en.wikipedia.org/wiki/Makridakis_Competitions — M4 results summary
  - https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0194889 (2018) — Makridakis et al., ML vs statistical forecasting
  - https://arxiv.org/pdf/2403.07815 (2024) — Chronos paper (capability claims, no trading evidence)

## 3. Reinforcement learning for trading (FinRL family)

- **Mechanism** — Frame trading as an MDP; train PPO/DDPG/SAC agents on historical bars to maximize portfolio return. The FinRL/FinRL-Meta authors themselves document the core problem: a "simulation-to-reality gap" driven by low SNR data, survivorship bias, and backtest overfitting — "it is possible to tune hyper-parameters and retrain the agent multiple times to obtain better backtesting results," and an agent typically overfits a single validation regime, leaving live performance "in question" (their words).
- **Indicators / patterns**:
  - Gym-style market environments replaying historical data
  - State = price windows + indicators; action = position weight; reward = PnL/Sharpe
  - Training-testing-trading pipeline; live hooks to Alpaca/CCXT/IB
- **Typical timeframe** — daily to minute bars.
- **Pros**:
  - Active, well-maintained open-source ecosystem
  - The maintainers are unusually honest about overfitting (they published a dedicated paper on combating backtest overfitting in crypto DRL, arXiv 2209.05559)
- **Cons**:
  - No credible public live track record for any FinRL-derived strategy; published results are backtests
  - Policy is a neural network: non-reproducible training, opaque decisions, regime-brittle
  - Reward hacking on simulator artifacts (fills at close, zero impact) is endemic
- **Fit with our bot** — A learned policy network in the decision path is non-reproducible and the framework's own authors concede sim-to-real is unsolved. **`skip`**
- **Evidence quality** — `academic` (with candid self-critique).
- **Sources**:
  - https://arxiv.org/pdf/2111.09395 (2021) — FinRL
  - https://arxiv.org/pdf/2211.03107 (2022) — FinRL-Meta (sim-to-real gap, survivorship bias, overfitting discussion)
  - https://arxiv.org/pdf/2209.05559 (2022) — DRL crypto, addressing backtest overfitting

## 4. Sentiment / news-LLM signals (Lopez-Lira & Tang, FinGPT, FinDPO)

- **Mechanism** — Score news headlines with an LLM (good/bad for the stock), go long positive / short negative next day. The strongest paper, Lopez-Lira & Tang ("Can ChatGPT Forecast Stock Price Movements?", arXiv 2304.07619, eventually a top-journal publication), reports ~700% cumulative long-short return Oct 2021–May 2024 *before* transaction costs in a deliberately post-training-cutoff sample; the effect concentrates in small/illiquid names (still >300% after removing sub-$5 and bottom-quintile stocks, again pre-cost) and the paper itself shows returns shrink materially at 10–25 bps per trade — the strategy is high-turnover daily long-short, the costliest possible implementation.
- **Indicators / patterns**:
  - Headline-level LLM scoring prompts (ChatGPT-3.5/4)
  - Daily rebalanced long-short portfolios, hundreds of names
  - FinGPT/FinBERT fine-tunes; FinDPO-style preference optimization
- **Typical timeframe** — daily rebalance, overnight horizon.
- **Pros**:
  - This is the *best-evidenced* LLM-finance result: peer-reviewed, genuinely out-of-sample by training-cutoff design
- **Cons**:
  - Pre-cost paper profits in high-turnover small-cap long-short portfolios are the classic anomaly profile that dies in implementation (see entry 5, Avramov et al.)
  - FinGPT evaluations show a structural bullish bias — it performs in up-markets and underperforms in bearish contexts (arXiv 2507.08015), i.e., it fails exactly when a regime filter matters
  - Requires an LLM at decision time; signal changes with model version; not reproducible
- **Fit with our bot** — A single-asset SPY-regime bot cannot even express a cross-sectional news long-short, and the LLM-at-decision-time requirement is disqualifying regardless. **`skip`**
- **Evidence quality** — `academic`.
- **Sources**:
  - https://arxiv.org/abs/2304.07619 (2023–24) — Lopez-Lira & Tang
  - https://larryswedroe.substack.com/p/can-chatgpt-forecast-stock-price — practitioner summary incl. cost caveats
  - https://arxiv.org/html/2507.08015v1 (2025) — FinGPT capabilities/limitations (directional bias)
  - https://arxiv.org/html/2507.18417v1 (2025) — FinDPO (frictionless-assumption caveat)

## 5. Cross-sectional ML asset pricing (Gu–Kelly–Xiu and its critiques)

- **Mechanism** — The strongest peer-reviewed pro-ML result in finance: Gu, Kelly & Xiu (RFS 2020) ran a horse race of ML models on ~94 firm characteristics; trees and shallow NNs roughly doubled the out-of-sample R² and portfolio performance of linear benchmarks. The decisive critique is Avramov, Cheng & Metzker (Management Science 2023): ML portfolio payoffs fall **62% excluding microcaps**, 68% excluding non-rated firms, 80% excluding distressed firms near downgrades, and deteriorate further under "reasonable trading costs" due to high turnover — the edge lives almost entirely where it cannot be traded.
- **Indicators / patterns**:
  - 90+ firm characteristics (value, momentum, liquidity, accruals...)
  - Gradient-boosted trees, shallow NNs; monthly retrained, decile long-short portfolios
  - Independent replication exists (Tidy Finance reproduces the pipeline)
- **Typical timeframe** — monthly rebalance, cross-section of thousands of stocks.
- **Pros**:
  - Real, replicated, peer-reviewed predictability — the honest ceiling for ML-in-markets claims
  - Models are deterministic at inference and the pipeline is reproducible in principle
- **Cons**:
  - Net-of-cost, investable-universe edge is marginal to nil (Avramov et al.)
  - Profits concentrate in microcaps/distressed names and in high-sentiment, low-liquidity periods
  - Irrelevant to a single-asset regime bot: there is no cross-section of SPY
- **Fit with our bot** — Academically respectable but structurally inapplicable (cross-sectional, multi-signal, cost-fragile) and would require abandoning the one-rule invariant for an edge that nets out near zero. **`skip`**
- **Evidence quality** — `academic` (top journals, replicated).
- **Sources**:
  - https://academic.oup.com/rfs/article/33/5/2223/5758276 (2020) — Gu, Kelly & Xiu
  - https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.4449 (2023) — Avramov, Cheng & Metzker
  - https://www.tidy-finance.org/blog/gu-kelly-xiu-replication/ — independent replication

## 6. LLM-as-trader agent frameworks (TradingAgents, FinMem, ai-hedge-fund, StockBench/LiveTradeBench)

- **Mechanism** — Orchestrate LLM "analyst/trader/risk" roles that read news, fundamentals, and price summaries, debate, and emit BUY/SELL/HOLD. TradingAgents (arXiv 2412.20138, UCLA/MIT-affiliated) reports Sharpe ratios of 5–8 — but on a backtest roughly one quarter long, with ~11 LLM calls plus 20+ tool calls per decision, and no live deployment; the authors themselves flag the Sharpe figures as anomalous. FinMem (arXiv 2311.13743) reports beating baselines on cumulative return/Sharpe with a layered-memory agent, but the FinAgent paper documents FinMem buying into a downtrend on partially-positive news, flipping +6% to −3%.
- **Indicators / patterns**:
  - GPT-4-class models with role prompts (fundamental/sentiment/technical analyst, bull-bear debate)
  - Layered memory stores (FinMem), reflection loops
  - News + fundamentals retrieval; tool calls to price APIs
- **Typical timeframe** — daily decisions; backtests measured in weeks-to-one-quarter.
- **Pros**:
  - Open-source codebases (TauricResearch/TradingAgents, pipiku915/FinMem) so the claims are at least inspectable
  - Live benchmarks now exist (LiveTradeBench, StockBench), which is methodological progress
- **Cons**:
  - **Memorization contamination**: GPT-4 can recall S&P 500 closing prices and WSJ headline dates from its training window almost perfectly; a ScienceDirect (2025) result shows that if a model memorized outcomes, its forecasting ability is *non-identified* — you cannot distinguish prediction from recall. Backtests over pre-cutoff periods are therefore unfalsifiable.
  - Live results don't transfer: LiveTradeBench's own 50-day live runs show performance in one market does not generalize to others, and LMArena-style benchmark rank does not predict trading performance
  - "When Agents Trade" / memory-controlled benchmarks (arXiv 2605.28359) report models that excelled on static benchmarks doing *worse* live
  - Non-determinism, per-decision API cost, prompt sensitivity, and silent model-version updates make the decision path unauditable — exactly the v1.14 failure mode this repo already retired
  - The flagship hobbyist repo (virattt/ai-hedge-fund, ~40k stars) explicitly states it is for education only and is "not intended for real trading or investment" — it publishes no live track record
- **Fit with our bot** — Requires a model SDK at decision time; per invariant 2 there is no envelope. **`skip`**
- **Evidence quality** — `academic` for the benchmark critiques; `marketing`-adjacent for the headline Sharpe claims.
- **Sources**:
  - https://arxiv.org/abs/2412.20138 (2024–25) — TradingAgents
  - https://arxiv.org/abs/2311.13743 (2023) — FinMem
  - https://arxiv.org/pdf/2511.03628 (2025) — LiveTradeBench
  - https://arxiv.org/pdf/2510.02209 (2025) — StockBench
  - https://arxiv.org/html/2605.28359v1 (2026) — memory-controlled benchmark for LLM trading agents
  - https://www.sciencedirect.com/science/article/pii/S0165176525004392 (2025) — LLM memorization makes forecasting non-identified
  - https://arxiv.org/pdf/2601.13770 (2026) — standardized look-ahead-bias benchmark
  - https://github.com/virattt/ai-hedge-fund — educational-only disclaimer
  - https://beginnersinai.org/tradingagents-explained/ (2026) — backtest-length and cost critique

## 7. Multi-agent "tournament" designs (the 100-agents pattern; Alpha Arena, EN + DE)

- **Mechanism** — Run N agents/models in parallel with real or notional capital, rank by PnL, showcase winners. This is structurally a survivorship-bias engine: with 100 agents on leveraged crypto, some always look brilliant over short windows by chance. The largest public instance is Nof1's Alpha Arena: 6 frontier LLMs (GPT-5, Claude Sonnet 4.5, Gemini 2.5 Pro, Grok 4, DeepSeek V3.1, Qwen3 Max), $10k each, live perps on Hyperliquid (Oct–Dec 2025), fully autonomous. Season 1: Qwen3 Max +22.3% (win rate 30.2%), DeepSeek +4.9%, while Claude Sonnet 4.5 −30.8%, Grok 4 −45.3%, Gemini 2.5 Pro −56.7%, GPT-5 −62.7% — four of six lost heavily in ~2 weeks (German coverage snapshots report slightly different figures by date — e.g. Qwen +22.9%, GPT-5 −59% — but identical direction and magnitude). Historical precedent at scale: Sentient Technologies evolved "trillions of virtual traders ('genes')," spliced winners — and liquidated its fund in 2018 after +4% (2017) then losses.
- **Indicators / patterns**:
  - N independent agents (LLM- or model-driven), identical starting capital; live leaderboard
  - LLM reasoning loop over price/indicator context (MACD, RSI mentioned for Qwen); direct exchange execution, leverage (up to ~15x positions per critiques), stop-losses (only some models used them)
  - Prompt = de facto strategy spec ("minimale Prompt-Änderungen führen zu völlig anderen Handelsstrategien" — DE coverage)
  - Eliminated/blown-up agents quietly drop out of the narrative
- **Typical timeframe** — intraday-to-daily decisions; tournament windows of 2–6 weeks (far too short for statistical significance).
- **Pros**:
  - Live, real-money, public PnL is more honest than backtests — Alpha Arena's chief contribution is *documenting LLM traders losing 30–63% in two weeks*
  - Shows what discipline correlates with: the only clear winner (Qwen) traded *least* (43 trades) with strict stops — a property a deterministic low-frequency bot has by construction
- **Cons**:
  - Two-week windows on leveraged crypto cannot separate skill from luck (Boris Tseitlin's critique: one instance per model, no news access, "wall of text" prompts, 15x leverage — results in a crash window ranged −4.5% to −57.9%)
  - Outcomes are prompt- and seed-sensitive; n=1 two-week window in one trending crypto regime — indistinguishable from luck; German coverage itself flags the agents "copied the worst human trading habits"
  - The pattern selects winners ex post; the modal agent loses. It is a content-marketing format, not an evaluation methodology
  - A separate OpenClaw incident: a parsing error autonomously sent ~$441k of tokens to a random address
  - Ecosystem attracts impersonation: a GitHub repo (`alpha-arena-nof1-ai/nof1ai-alpha-arena`) presents itself as Nof1's "open-source trading bot"; it is not linked from nof1.ai and matches known scam-repo patterns — treat as untrustworthy
- **Fit with our bot** — A tournament is a presentation device, not a decision rule; the underlying architecture (non-deterministic model in the decision path, irreproducible from price history) is precisely what the invariants exclude, and the one robust finding (low frequency + hard stops wins) is already embodied deterministically in the 200-DMA + kill-switch stack. **`skip`**
- **Evidence quality** — `practitioner` for the live PnL numbers; `marketing` for the framing around them.
- **Sources**:
  - https://nof1.ai/ — Alpha Arena (official)
  - https://www.bitget.com/news/detail/12560605046390 (2025) — Season 1 final PnL figures
  - https://www.datawallet.com/crypto/alpha-arena-nof1-ai-explained (2025)
  - https://borisagain.substack.com/p/why-alpha-arena-is-literally-the (2025) — methodological critique
  - https://www.bloomberg.com/news/articles/2018-09-07/ai-hedge-fund-sentient-is-said-to-shut-after-less-than-two-years (2018) — Sentient's "trillions of genes" approach and shutdown
  - https://ai-automation-engineers.de/news/2025-12-21-alpha-arena-6-kis-handeln-mit-echtem-geld-qwen-gewinnt-mit-22/ (2025) — DE coverage, Qwen win profile
  - https://cryptoticker.io/de/openclaw-ki-trading-2026-performance-risiken/ (2026) — OpenClaw incident
  - https://investx.fr/de/krypto-news/ki-trading-wettbewerb-grok-deepseek-gewinnen-gpt-gemini-verluste/ — DE coverage
  - https://www.kettner-edelmetalle.de/news/chinesische-ki-triumphiert-uber-us-konkurrenz-deepseek-dominiert-krypto-handelsexperiment-21-10-2025 (2025) — DE coverage

## 8. Automated retraining / online learning (concept drift)

- **Mechanism** — Detect distribution shift (ADWIN/DDM-style detectors, autoregressive drift tests) and retrain the model on recent data, or learn fully online. The genre's pitch ("our agents retrain themselves daily") inverts the actual evidence: in markets, the input-output relationship itself decays as participants adapt — "a model may exploit a certain market pattern, but as traders react and regimes shift, that pattern disappears or inverts." Retraining chases a moving target; drift-based retraining roughly matches scheduled retraining on accuracy and mainly saves compute, not alpha.
- **Indicators / patterns**:
  - Drift detectors (ADDM, ELM-based detection), rolling retrain windows
  - Online/continual learning, replay buffers against catastrophic forgetting
  - Champion-challenger model promotion
- **Typical timeframe** — retrain cadences from daily to monthly.
- **Pros**:
  - Legitimate MLOps hygiene *if* you already have a model worth maintaining
  - Drift detection itself (e.g., on regime statistics) is a deterministic, testable computation
- **Cons**:
  - Retraining on recent noise = fitting the last regime just as it ends; "approaches built on fixed parameters or scheduled retraining tend to lag behind reality... especially under stress"
  - Continuous retraining destroys reproducibility: yesterday's decision can no longer be reproduced from price history plus a fixed rule
  - It is a maintenance treadmill layered on a signal that (per entries 1–6) hasn't demonstrated an edge to maintain
- **Fit with our bot** — The 200-DMA needs no retraining — that is a feature; adopting an auto-retrained model would surrender reproducibility for an undemonstrated edge. **`skip`**
- **Evidence quality** — `academic` / `practitioner` mix.
- **Sources**:
  - https://blog.quantinsti.com/autoregressive-drift-detection-method/ — drift detection in trading, regime framing
  - https://arxiv.org/pdf/2004.05785 (2020) — Learning under Concept Drift: A Review
  - https://www.researchgate.net/publication/295902726 — ELM + explicit drift detection on financial series

## 9. The YouTube "100 agents / 1% daily" genre — incl. the located IMMT project — and the arithmetic against it (EN + DE)

- **Mechanism** — The genre this bundle exists to check, and its specific instance: FOUND. A cluster of YouTube live streams titled "100 AI Agents Trading ETHUSDT Live | LSTM + LLM Signals (Scalping Strategy)" / "AI Trading 100 Agents ETHUSDT Live," plus "IMMT BINANCE FUTURES AI Trading," matching the described genre exactly: 100 agents, 1,000 USDT each, experimental 1% daily target, real-time LONG/SHORT/HOLD with Entry/TP/SL/PnL overlays, LSTM + LLM signal narration, funneling viewers to a Telegram channel (@IMMT_group). Active as of April–June 2026. German-language YouTubers run the same format at smaller scale ("Ich gebe der KI 1.000 € zum Daytraden" — OpenClaw, "Hermes KI", DeepSeek bots): content monetization (views, affiliate broker links) is the actual business model; the trading result is the hook. The 1%/day promise refutes itself arithmetically: 1.01^252 ≈ 12.27, i.e., ~+1,127% per year on trading days (on a 365-day crypto calendar, ~+3,678%); 1,000 USDT becomes ~12,270 USDT in one year and crosses 1,000,000 USDT (1,000×) in under 3 years (1.01^700 ≈ 1,060). For calibration, the best audited-adjacent track record in history — Renaissance's Medallion — averaged ~66% gross / ~39% net per year (1988–2018), i.e., ~0.2% per trading day gross, and recent scholarship (arXiv 2405.10917) argues even the 66% figure overstates the properly compounded return (likely <35% before fees). "1% daily" is ~5× the daily rate of the best fund ever, claimed by anonymous YouTube agents.
- **Indicators / patterns**:
  - Claimed LSTM price model + LLM reasoning layer + "crypto news" feed; live-stream dashboard of 100 agent PnLs
  - Telegram funnel (@IMMT_group); ETHUSDT perpetual futures (Binance), scalping cadence
  - Round-number daily-return targets ("1% pro Tag") asserted, never derived; survivorship by editing — losing runs become "drama" content, not evidence
  - Retail base rates: Brazilian CVM data (Chague, De-Losso & Giovannetti 2020, SSRN 3423101): of 19,646 first-time day traders in mini-Ibovespa futures, 97% of those persisting >300 days lost money; 1.1% earned more than minimum wage; no evidence of learning over time
  - Prop-firm funnel: FPFX Tech analysis of 300k+ accounts — ~14% pass challenges; only ~7% of all traders ever reach a payout; average payout ~4% of account size
- **Typical timeframe** — intraday scalping, continuous live stream; video series of days to a few weeks.
- **Pros**:
  - None verifiable. The stream format at least displays losing agents in real time, if the dashboard is honest — which cannot be confirmed; some DE videos are occasionally honest about losses
  - The 1%-daily claim is cheaply falsifiable with a calculator
- **Cons**:
  - **No verifiable track record exists.** No audited PnL, no exchange-verified account (e.g., no public Hyperliquid-style on-chain wallet as Alpha Arena had), no whitepaper, no named team, no GitHub. Searches for independent reviews of "IMMT AI trading" return nothing — only generic Telegram/AI-trading scam advisories
  - Anyone who could genuinely compound 1%/day would absorb all available market liquidity within a few years; the claim is incompatible with market existence
  - The populations making such claims (day traders, prop-challenge entrants) lose money at 86–97% rates in audited datasets
  - The structure (live "performance," Telegram funnel, unverifiable agents) matches the documented AI-trading-scam template described by NinjaTrader's and Binance's scam-pattern guides: guaranteed-style return targets, no verifiable team, channel-funnel recruitment
  - The 100-agent dashboard is the survivorship-bias engine of entry 7 in retail form: at any moment some agents are green, and those anchor the pitch
  - No controls, no fees/slippage accounting, cherry-picked windows; German coverage of the *specific* "100 Agenten" format is thin — what exists is the 6-model Alpha Arena variant (entry 7)
- **Fit with our bot** — Unfalsifiable claims, LLM in the decision path, no track record to even evaluate; this is the claim class the bot's design explicitly rejects. **`skip`**
- **Evidence quality** — `marketing` (no independent or audited evidence located; flagged explicitly as unverifiable); the base rates refuting the claim are `academic`.
- **Sources**:
  - https://www.youtube.com/watch?v=Fw7Sn2JvTdE — "100 AI Agents Trading ETHUSDT Live | LSTM + LLM Signals"
  - https://www.youtube.com/watch?v=iWrqn3hkDLc (2026-04-30 dated title variant)
  - https://www.youtube.com/watch?v=Kd485potDnc — "IMMT BINANCE FUTURES AI Trading"
  - https://ninjatrader.com/futures/blogs/ai-trading-scams/ — AI-trading scam pattern reference
  - https://www.binance.com/en/blog/security/stay-safe-how-to-spot-and-avoid-telegram-scams-5644955869257264091 — Telegram-funnel scam patterns
  - https://www.youtube.com/watch?v=pRhVwuOnS0E — DE "KI zum Daytraden" format
  - https://www.youtube.com/watch?v=eEyVoxVA8Vg — DE variant
  - https://www.youtube.com/watch?v=oVg7rzMZCeI — DE variant
  - https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101 (2020) — "Day Trading for a Living?" (Brazilian CVM base rates)
  - https://arxiv.org/pdf/2405.10917 (2024) — "Is the annualized compounded return of Medallion over 35%?"
  - https://www.quantifiedstrategies.com/medallion-fund-returns/ — Medallion 66% gross / 39% net summary
  - https://www.financemagnates.com/forex/only-1-in-20-traders-pass-prop-firm-challenges-reports-the-funded-trader/ — prop-firm pass rates
  - https://atmosfunded.com/prop-firm-statistics/ (2026) — FPFX 300k-account statistics

## 10. LLMs as investment advisors: heise/c't and Stiftung Warentest controlled tests (DE)

- **Mechanism** — German Fachpresse ran controlled tests: heise gave five LLMs (Claude Opus 4.1, Gemini 2.5 Pro, GPT-5 Thinking, Grok 4, Perplexity Pro) an identical portfolio-construction prompt (end of Aug 2025) and tracked the resulting depots; Stiftung Warentest has tracked KI-gesteuerte Fonds in its database since 2024 and tested LLM money advice. The key empirical contribution: identical prompts produced five materially different portfolios — the LLM reproducibility problem quantified rather than asserted.
- **Indicators / patterns**:
  - Identical prompt → five materially different portfolios (non-determinism made visible)
  - Factual errors at decision-relevant points (e.g., ChatGPT misreporting an FTSE All-World TER as 0.22% instead of 0.19% — stale training data, no live lookup)
  - Warentest benchmark snapshot: KI-ETFs returned 6.3–16% vs MSCI World 15.3% (to 31 Oct 2025)
- **Typical timeframe** — buy-and-hold portfolio horizon; multi-month tracking.
- **Pros**:
  - Methodologically clean for what it tests; quantifies the reproducibility problem (same prompt ≠ same decision) rather than asserting it
- **Cons**:
  - Warentest's verdict: stay skeptical of AI stock tips — "stringent analytisch denken" is not yet an LLM strength; only one of heise's five models even suggested consulting an advisor
  - Portfolio outcomes diverged "teils deutlich" purely on model choice
  - Failure mode for any LLM-in-the-loop bot: silent non-reproducibility plus confidently wrong inputs
  - Small n, short windows
- **Fit with our bot** — Direct German Fachpresse confirmation of invariant 2's rationale: identical inputs do not yield identical decisions from an LLM, so audit and backtest guarantees collapse. **`skip`**
- **Evidence quality** — `practitioner` (structured journalistic tests; small n, short windows).
- **Sources**:
  - https://www.heise.de/ratgeber/KI-als-Anlageberater-Wie-Sie-mit-ChatGPT-Co-an-der-Boerse-Geld-verdienen-10544920.html (2025)
  - https://www.test.de/aktie-geld-ki-vergleich-performance-etf-boerse-investment-6265886-0/ (2025)

## 11. The DE retail "KI-Trading-Bot" fraud landscape (BaFin / Verbraucherzentrale)

- **Mechanism** — Hundreds of near-identical websites advertise "automatisierter Handel mit künstlicher Intelligenz": deposit from €250, an alleged AI bot trades crypto/CFDs autonomously, dashboards display fabricated gains. BaFin's June 2025 warning alone names **over 700 nearly identical sites**; payouts fail behind fake "Steuerforderungen" and verification fees. There is no model and no trading — the "KI-Agent" is a UI fiction over a payment funnel.
- **Indicators / patterns**:
  - Deepfake celebrity endorsements (per kagels-trading, up ~500% in 2025)
  - Fake regulator/bank logos (Bundesfinanzministerium, Bundesbank, Sparkasse); €250 minimum deposit template
  - "Berater" who pressure follow-up deposits; fabricated P&L dashboards; withdrawal blockers
- **Typical timeframe** — victim lifecycle weeks to months; site series rotate domains continuously (warnings span 2024–2026).
- **Pros**:
  - None as a strategy. As evidence: regulator-grade documentation that the dominant public face of "KI-Trading" in Germany is fraud, not technology
- **Cons**:
  - Total-loss outcomes; Verbraucherzentrale Marktbeobachtung logged complaints on 100+ platforms in twelve months, losses up to six figures
  - Failure mode is not model risk but counterparty fraud — capital never reaches a market
- **Fit with our bot** — Nothing to adopt; the relevant lesson is reputational: any retail-facing "AI bot" framing inherits this association, while a deterministic, auditable design is the exact opposite. **`skip`**
- **Evidence quality** — `marketing` (the claims) / regulator documentation of fraud (the rebuttal).
- **Sources**:
  - https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Verbrauchermitteilung/unerlaubte/2025/meldung_2025_06_03_Investieren_mit_KI.html (2025)
  - https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Verbrauchermitteilung/unerlaubte/2025/meldung_2025_02_04_Plattformreihe_Diverse_Webseiten_Trading_Bot_Handel_Kryptowerten.html (2025)
  - https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Verbrauchermitteilung/unerlaubte/2024/meldung_2024_12_17_ki_trading_bots.html (2024)
  - https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Meldung/2026/meldung_2026_02_12_finanzbetrug_ki_kryptowerten.html (2026)
  - https://www.verbraucherzentrale.de/wissen/geld-versicherungen/vorsicht-betruegerisches-onlinetrading-54699

## 12. Copy-trading / retail auto-trading: practitioner tests and the loss disclosures (DE)

- **Mechanism** — Retail follows "Top Trader" or bot signals via platform mirroring (eToro CopyTrader, WunderTrading, Cryptohopper) or buys "KI-Signal" subscriptions; German review sites document Erfahrungen. The only hard numbers in this genre are the ESMA-mandated loss disclosures the platforms must print on themselves. The German Markttechnik/Trendfolge practitioner scene has also run the honest head-to-head tests: stock3 (then Godmode) ran the evolutionary-algorithm software Genotick on DAX daily data since 1988: +542% — versus **>1,100% for plain buy-and-hold**. kagels-trading's 2026 KI-Trading review concludes most retail "KI" is "AI-Washing": "Was dir als künstliche Intelligenz verkauft wird, ist oft nicht mehr als ein simples Skript mit neuem Etikett."
- **Indicators / patterns**:
  - Signal mirroring with proportional sizing; leaderboards ranked by recent return (selection bias by construction)
  - Crypto bots: grid/DCA presets relabeled as strategies; GPT-wrapper signal services at $50–100/month; rule-based scripts (RSI<30=buy) relabeled as "KI"
  - Genetic/evolutionary rule discovery (Genotick); baseline comparisons: buy-and-hold, simple Trendfolge
- **Typical timeframe** — continuous; follower churn within months; multi-decade backtests in the honest tests.
- **Pros**:
  - The mandated disclosures are the most honest statistics in retail trading: every claim of easy automated profit coexists with a legally required counter-statistic on the same page
  - The practitioner scene's consistent, testable conclusion: AI is useful as a *research assistant* (backtest coding, screening, sentiment digestion) — which matches how this repo already uses Claude (development, never execution)
- **Cons**:
  - eToro's own CFD loss disclosure has ranged 51–76% of retail accounts losing money (varies by period; WHSelfInvest's pages cite 91% for their CFD context); German reviews report bots "kurzfristig interessant, langfristig hinter traditionellen Strategien"
  - Leaderboard copying = buying a recent-winner lottery ticket post-fees; the copied human is a nondeterministic model
  - "AI Trading Bots zeigen in praktischen Tests keine messbaren Vorteile"; kagels' framing that "90% aller Day-Trader verlieren Geld" and AI doesn't change that; bots can look good short-term and decay ("veraltete Strategien", no regime adaptation)
  - Caveat: parts of this ecosystem (trading.de, finanzradar) are affiliate-funded — their bot "Top 10" lists are themselves `marketing`
- **Fit with our bot** — A social/copy execution layer contradicts reproducibility and adds nothing to a one-rule bot; the practitioner literature's positive recommendation — simple, transparent rules beat opaque adaptive systems for retail — *is* our architecture. **`skip`**
- **Evidence quality** — `marketing` (reviews) / the loss-rate disclosures themselves are regulator-forced and reliable; the practitioner head-to-head tests are `practitioner`.
- **Sources**:
  - https://insider-week.com/de/articles/etoro-erfahrungen-2026/ (2026)
  - https://www.wallstreet-online.de/diskussion/500-beitraege/1285671-1-500/verlustquoten-trader-zahlen-broker
  - https://www.kagels-trading.de/wundertrading-bot-erfahrungen/
  - https://www.kagels-trading.de/cryptohopper-erfahrung/
  - https://aktiendepot.com/erfahrungen/etoro-erfahrungsbericht/
  - https://www.kagels-trading.de/ki-trading-erfahrungen/ (2026) — "AI-Washing" verdict
  - https://stock3.com/news/ki-wie-trader-ganz-gross-kasse-machen-5834436 — Genotick vs DAX buy-and-hold test
  - https://www.kagels-trading.de/trading-bots/
  - https://trading.de/lernen/kuenstliche-intelligenz/ (affiliate-funded — flagged)

## 13. AI/ML funds and platforms with live records: AIEQ, Sentient, Quantopian (EN + DE)

- **Mechanism** — Run an AI-driven fund/platform at institutional scale with real capital and public reporting — the closest thing to a controlled experiment for the genre, and the strongest steel-man for "KI schlägt den Markt." Outcomes: **AIEQ** (IBM-Watson-powered ETF, launched 2017, marketed as replacing "1.000 Analysten", still trading) shows ~9–10% annualized over 8 years with 0.83% fees — no AI outperformance, and analysts note it drifted into closet indexing after early underperformance; the German fund press measured 6.7% p.a. at 23.0% standard deviation (Nov 2017–Jun 2023), clearly behind a plain total-market index fund. **Sentient** liquidated in 2018 after <2 years (+4% in 2017, losses in 2018). **Quantopian** (crowdsourced algos, 2011–2020) shut down; research on its own cohort of user algorithms found backtest Sharpe had essentially no predictive power for out-of-sample performance (R² < 0.025).
- **Indicators / patterns**:
  - Genetic/evolutionary trader populations (Sentient), NLP+ML stock scoring (AIEQ/Watson), crowdsourced Python algos (Quantopian)
  - Real capital, audited NAVs / public ETF pricing; institutional data budgets and compliance — everything the retail genre lacks
- **Typical timeframe** — daily-rebalanced equity portfolios; multi-year live windows.
- **Pros**:
  - These are the genre's highest-quality datasets: real money, long windows, fee-inclusive, no cherry-picking possible
- **Cons**:
  - Every scaled, transparent attempt either underperformed cheap beta after fees (AIEQ), died (Sentient), or empirically demonstrated that backtests don't predict live results (Quantopian)
  - fundresearch.de finds "die Mehrzahl der KI-unterstützten Fonds" underperformed (MSCI World ~+13% YTD vs "weit darunter" for nearly all tested products), with only isolated positive outliers — if resourced institutional ML can't beat beta after costs, the 1%-daily retail claim is not credible
  - The Quantopian R²<0.025 finding is the single most damaging statistic for the "train 100 agents, keep the winners" pattern: in-sample winners are noise
- **Fit with our bot** — Not an approach to adopt but the evidence base that vindicates the boring-deterministic design and calibrates expectations for *any* ML overlay proposal against the 200-DMA baseline; nothing to implement. **`skip`** (as an approach; retain as reference evidence).
- **Evidence quality** — `practitioner` (audited fund data, platform-scale studies) with `academic` support.
- **Sources**:
  - https://seekingalpha.com/article/4761215-aieq-example-of-ai-failure — AIEQ track-record critique
  - https://www.newconstructs.com/dont-believe-the-hype-about-this-ai-powered-etf/ — AIEQ closet-indexing/fee critique
  - https://www.bloomberg.com/news/articles/2018-09-07/ai-hedge-fund-sentient-is-said-to-shut-after-less-than-two-years (2018)
  - https://whatworksintrading.substack.com/p/the-rise-and-fall-of-quantopian-lessons — Quantopian post-mortem
  - https://www.quantrocket.com/blog/quantopian-shutting-down/ (2020) — incl. the in/out-of-sample R² finding
  - https://www.fundresearch.de/kuenstliche-intelligenz/nur-wenige-ki-fonds-koennen-ueberzeugen.php — DE fund-press cohort review
  - https://www.test.de/aktie-geld-ki-vergleich-performance-etf-boerse-investment-6265886-0/ — Warentest KI-Fonds tracking

## 14. Stagge-style deterministic anomaly stacking: quantitative Saisonalität (DE)

- **Mechanism** — André Stagge (ex-Union Investment PM, claims €500M+ profits on €2.5bn AuM) markets a stack of small, independent, fully deterministic calendar/anomaly rules — "Turnaround Tuesday" (DAX), "Friday Gold Rush", Triple Witching, Halloween/month-end effects, "Zinshamster" — executed via fixed alerts through Investui/WHSelfInvest. Each rule is reproducible from calendar + price history alone; no model at decision time. This is the German scene's favored *deterministic* alternative to KI-signals.
- **Indicators / patterns**:
  - Calendar position (weekday, month-end, expiry dates, tax days); fixed entry/exit windows per anomaly
  - Market-neutral DAX/MDAX seasonal pairs
  - Diversification across ~8–24 uncorrelated micro-edges
- **Typical timeframe** — hours to a few days per trade; event-driven, low frequency.
- **Pros**:
  - Auditable rules, backtests plus live Musterdepots, honest risk disclosure on the hosting broker's pages ("91% of retail CFD accounts lose money"; "back tested and real past performance do not guarantee future results")
  - Philosophically identical to our bot: pure rules, reproducible, no discretion
- **Cons**:
  - Public performance evidence is promotional (course/broker funnel); per-strategy live numbers not disclosed on the public pages
  - Calendar anomalies are notorious data-mining targets and decay post-publication
  - Stacking many micro-edges multiplies transaction costs and turns "one decision rule" into dozens
- **Fit with our bot** — Individual anomalies are deterministic, pure-function-testable rules that *could* be benchmarked against the 200-DMA baseline in the Python research layer, but adopting any would add a second decision rule and the public evidence base is too promotional to motivate that yet. **`needs envelope`** (envelope: research-layer benchmarking in `backtest/` only — any live adoption is gated behind a fresh brainstorm + spec because it would breach the one-decision-rule invariant).
- **Evidence quality** — `practitioner` (real ex-institutional track record claimed) shading into `marketing` (academy/broker funnel; verify independently before any evaluation).
- **Sources**:
  - https://www.investui.de/de-de/investieren/anlegen/trading-strategien/trader-andre-stagge
  - https://www.whselfinvest.de/de-de/trading-plattform/store/trading-strategien/daytrading-andre-stagge-zinshamster-surfer-superstar
  - https://www.andre-stagge.de/strategien/
  - https://www.andre-stagge.de/wissenschaftliche-publikation/
  - https://bookoffinance.de/einfach-geld-verdienen-und-an-der-boerse-reich-werden/
  - https://finanzmarktwelt.de/saisonalitaet-andre-stagge-ueber-warnsignale-378182/

## 15. Trend-following / 200-DMA regime filters (the bot's own family, EN + DE)

- **Mechanism** — Long the risk asset when price > long-term moving average (Faber's 10-month SMA ≈ 200-DMA), cash otherwise; or time-series momentum (sign of trailing 12-month return, Moskowitz–Ooi–Pedersen JFE 2012). Faber (2007, revisited 2016+) tested on US equities back to 1900 and four other asset classes: the filter's contribution is *risk reduction*, not return enhancement — one diversified-portfolio out-of-sample decade (2006–2016) showed 4.88% vs 3.51% return but volatility cut from 12.81% to 6.55%. Hurst–Ooi–Pedersen extend time-series momentum to ~1880 across asset classes ("A Century of Evidence on Trend-Following Investing"). The German literature covers exactly this rule with unusual rigor: Fairvalue-Magazin (Markus Neumann, updated 2020) aggregates Faber (2006, five asset classes 1973–2012), its own 2002–2017 multi-asset test, and Zakamulin's long-horizon studies.
- **Indicators / patterns**:
  - 200-DMA / 10-month SMA crossover (exactly the bot's `computeTargetState`); binary long/cash
  - 12-month time-series momentum sign as the academic sibling
  - Daily or monthly signal evaluation; variants: Golden/Death Cross (38/200), envelope bands / hysteresis against whipsaw
- **Typical timeframe** — daily-to-monthly signal evaluation, holding periods of months to years.
- **Pros**:
  - The deepest out-of-sample record in the entire survey: ~140 years, multiple asset classes, multiple independent research groups
  - Pure function of price history — reproducible, auditable, zero inference cost; the standing *baseline* that none of archetypes 1–9 has publicly beaten net of costs on the same asset
  - Fairvalue's 2002–2017 test: timing 8.43% return vs 8.19% buy-and-hold, volatility 6.08% vs 9.32%, max drawdown −9.46% vs −27.55%, Sharpe 1.17 vs 0.77; 2008 portfolio loss −7% vs −26%
  - German consensus framing: it is a *risk-management* tool — precisely how our bot uses it (gating a leveraged ETF)
- **Cons**:
  - Whipsaw costs in sideways markets: Fairvalue counted 90 losing vs 37 winning trades (of 263) in its test; German practitioner pages put directional Erfolgsquote at 50–70% depending on regime
  - Expected *raw* return ≈ buy-and-hold or slightly below in long bull runs — Zakamulin: long-run returns 20–26% *below* buy-and-hold for ~30% less risk; the payoff is drawdown control ("not a money-maker" but crash cushioning)
  - ~0.8%/yr German tax+cost drag can erase the edge; outperformance clusters in crash decades (period-selection sensitivity)
  - Post-publication performance of trend rules has been weaker than in-sample (general factor-decay caveat)
- **Fit with our bot** — This is the bot, independently validated and honestly bounded by both literatures. Worthwhile research-layer work: benchmark the current 200-DMA against the 10-month-SMA and 12-month-TSM variants on SPY in `backtest/`, quantify whipsaw frequency and cost drag for UPRO gating, and test band/hysteresis variants as a deterministic wrapper — all pure price functions. **`fits`**
- **Evidence quality** — `academic` (peer-reviewed studies, replicated, plus independent financial journalism summarizing them).
- **Sources**:
  - https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf (2007/2013) — Faber, A Quantitative Approach to Tactical Asset Allocation
  - https://allocatortraining.com/wp-content/uploads/2023/06/A-Quantitative-Approach-to-Tactical-Asset-Allocation.pdf — 10-year revisit
  - https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing (2017) — Hurst, Ooi & Pedersen
  - https://fairmodel.econ.yale.edu/ec439/hurst.pdf — same, full text
  - https://fairvalue-magazin.de/trendfolgestrategie-moving-average/ (2020) — Fairvalue multi-asset test + Zakamulin summary
  - https://www.systematisch-investieren.de/strategien/aktive-strategien/200-tage-strategie/
  - https://www.finanzen.net/ratgeber/trading/grundlagen-einstieg/200-tage-linie/
  - https://trading.de/indikatoren/200-tage-linie/

---

## Cross-cutting observations

### Which archetypes line up with the deterministic-risk invariants

Exactly one of the fifteen: the trend-following / 200-DMA family (entry 15), which *is* the bot's
decision rule — a pure function of price history with the deepest out-of-sample record in the
survey (~140 years, multiple asset classes, two independent national literatures). The only other
entry that even shares the deterministic property is Stagge-style anomaly stacking (entry 14):
reproducible calendar rules with no model at decision time — but it fails the one-decision-rule
invariant on adoption and its public evidence is promotional. Notably, the single robust *positive*
finding from the live LLM-agent experiments — Alpha Arena's sole winner traded least, with hard
stops — describes a property the current architecture has by construction: a low-frequency daily
signal (`computeTargetState`) plus a deterministic intraday drawdown kill-switch.

### Which need envelopes

Only entry 14 (Stagge anomaly stacking), and the envelope is procedural, not technical:
research-layer benchmarking in `backtest/` only, with any live adoption gated behind a fresh
brainstorm + spec because it would add a second decision rule. Nothing LLM-based can be enveloped
into compliance — invariant 2 ("no LLM in the trading path") has no envelope by definition, which
is why entries 4, 6, 7, 9, and 10 are hard `skip`s rather than envelope candidates. This differs
from bundles on conventional strategy topics, where `needs envelope` is a common verdict; here the
genre's defining feature (a model in the decision path) is the disqualifier itself.

### Where the EN and DE literatures agree / disagree

**Agreement is near-total on substance:**
- LSTMs cannot beat naive forecasts out-of-sample (EN: persistence/leakage artifacts, sub-coin-flip directional accuracy; DE: thesis-level replication on DACH small caps).
- LLM decisions are not reproducible (EN: memorization contamination makes forecasting formally non-identified; DE: heise's identical prompt → five materially different portfolios).
- Live AI funds trail cheap beta after fees (EN: AIEQ ~9–10% at 0.83% fees, closet indexing; DE: 6.7% p.a. at 23.0% stdev, "die Mehrzahl der KI-unterstützten Fonds" underperformed).
- The Alpha Arena result (4 of 6 frontier LLMs down 30–63% in ~2 weeks) is reported consistently in both languages, with only snapshot-date differences in the exact PnL figures.
- The 200-DMA is honestly characterized in both literatures as risk management — drawdown and volatility reduction at the cost of some raw return — not as a return enhancer.

**Differences are of emphasis, not conclusion:**
- The DE literature adds an entire evidence layer absent from EN: industrial-scale outright fraud (BaFin's 700+ template sites), which means German retail "KI-Trading" claims start from a credibility deficit no backtest can repair.
- The favored deterministic alternative differs: EN foregrounds time-series momentum (Faber, Hurst–Ooi–Pedersen); DE foregrounds calendar anomalies (Stagge) — both are pure price/calendar functions, but the TSM literature is academically far stronger.
- Minor numeric discrepancy on the 1%-daily annualization: EN computes ~+1,127%/yr (1.01^252, trading days), DE ~+3,678%/yr (1.01^365, crypto calendar). Both are internally consistent for their asset context, and both refute the claim equally.
- The DE practitioner scene contributes a head-to-head the EN survey lacks: an evolutionary-algorithm system (Genotick) underperforming plain DAX buy-and-hold (+542% vs >1,100%) in stock3's own multi-decade test.

### Honest evidence-quality summary

The high-quality evidence in this bundle — peer-reviewed academia and audited live records — is
almost uniformly *negative* about the genre. The only peer-reviewed positives (Gu–Kelly–Xiu
cross-sectional ML; Lopez-Lira & Tang news sentiment) shrink 62–80% once untradeable names are
excluded and die under realistic costs, and neither is expressible by a single-asset regime bot
anyway. The genre's own affirmative claims live almost entirely in the `marketing` tier: YouTube
streams with no audited PnL (IMMT has no verifiable track record at all), affiliate-funded bot
reviews, and — at the bottom — BaFin-documented fraud. The most damaging single statistics are
regulator-forced or platform-scale: Quantopian's R² < 0.025 between backtest and live Sharpe (the
direct refutation of "train 100 agents, keep the winners"), ESMA loss disclosures of 51–91% of
retail CFD accounts losing money, and the Brazilian CVM finding that 97% of persistent day traders
lose. The one entry whose positive evidence deserves follow-up scrutiny (Stagge) is
practitioner-shading-to-marketing and needs independent verification before any research effort.

### Implications for the current architecture

- **`computeTargetState` (the pure function)** — Nothing in either literature argues for replacing or augmenting it with a learned model: every learned alternative surveyed either failed honest evaluation outright or cannot satisfy reproducibility-from-price-history. The supported research action is parameter-robustness work, not signal replacement: benchmark the 200-DMA against the 10-month SMA and 12-month time-series-momentum variants on SPY, and evaluate band/hysteresis variants as deterministic whipsaw dampers — all remain pure functions and preserve every invariant.
- **The kill-switch** — Independently vindicated by the live evidence: the only profitable Alpha Arena agent was the one with strict stops and minimal trading, and the genre's blow-ups (GPT-5 −62.7%, the OpenClaw $441k misdirection) are exactly the failure class a deterministic, broker-sourced drawdown guard exists to bound. No change indicated; keep it deterministic and position-sourced from the broker.
- **The Python research layer and walk-forward backlog item #104** — This bundle is the strongest argument yet for prioritizing the walk-forward harness: Quantopian's R² < 0.025 and FinRL's own backtest-overfitting concessions show that in-sample results in this domain are close to meaningless. Any future variant testing (SMA/TSM parameter benchmarks, whipsaw + cost-drag quantification for UPRO gating, or an eventual Stagge-anomaly benchmark) should run through walk-forward evaluation in `backtest/` before reaching any spec discussion.
- **No LLM in the trading path** — Re-affirmed independently from both literatures: the EN academic record shows LLM trading backtests are unfalsifiable (memorization) and live runs lose; the DE Fachpresse quantified the non-reproducibility directly. The bundle surfaces no envelope under which an LLM in the decision path becomes auditable. Claude's role stays where both literatures say it adds value: research assistant and development tooling, never execution.
