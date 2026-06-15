# GitHub survey — LSTM/LLM autonomous trading agents

Evidence check on the "LSTM + LLM reasoning + auto-retraining + live evaluation" genre
(the 100-agents / 1%-daily YouTube pitch). 8 repos surveyed, picked for diversity:
2 LLM-agent traders, 1 financial-LLM toolkit, 2 RL/ML research frameworks, 1 ML-augmented
retail bot, 2 small "LSTM bot" repos representative of what YouTube projects actually run.
All metadata verified via `gh api repos/<owner>/<repo>` on 2026-06-10.

## Summary

| Repo | Stars | Last push | Licence | LLM in decision path? | One-line takeaway |
|---|---:|---|---|---|---|
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 84,830 | 2026-06-01 | Apache-2.0 | **Yes** — LLM agents debate and emit BUY/SELL/HOLD | Research framework, no broker execution; even the "risk team" is three LLM debaters |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 59,930 | 2026-06-09 | MIT | **Yes** — LLM picks action + quantity (numerically capped) | Educational only; deterministic volatility-based position caps wrap the LLM |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 51,292 | 2026-06-09 | GPL-3.0 | No | Best-in-class deterministic risk scaffolding around optional ML (FreqAI); copyleft licence |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 44,224 | 2026-04-22 | MIT | No | Industrial quant-research platform; its rolling-retrain / walk-forward machinery is the part worth borrowing |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 20,456 | 2026-06-01 | MIT | Yes (forecasts), but nothing executes | LLM fine-tuning toolkit (LoRA sentiment/forecaster), not a trading bot |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 15,382 | 2026-05-25 | MIT | No (RL policy, not LLM) | RL framework with an Alpaca paper-trading loop; turbulence gate is its only risk-off guard |
| [yacoubb/stock-trading-ml](https://github.com/yacoubb/stock-trading-ml) | 662 | 2022-05-18 | GPL-3.0 | No | The canonical "LSTM predicts the price" tutorial repo; persistence-trap, zero risk layer, dead since 2022 |
| [SC4RECOIN/LSTM-Crypto-Price-Prediction](https://github.com/SC4RECOIN/LSTM-Crypto-Price-Prediction) | 363 | 2021-08-10 | MIT | No | Honest negative result: ~80% validation accuracy still lost 11% vs buy-and-hold once fees applied |

---

## 1. TauricResearch/TradingAgents — multi-agent LLM trading framework

- **Stars / last commit / licence:** 84,830 / pushed 2026-06-01 / Apache-2.0. Python.
- **Stack:** Python, LangGraph-style agent graph (`tradingagents/graph/`), multi-provider LLM
  clients (`llm_clients/`: OpenAI, Anthropic, Google, Azure; tests also cover DeepSeek, Ollama,
  Minimax). Data via Alpha Vantage, yfinance, Reddit, Stocktwits (`dataflows/`). Rich-based CLI,
  Docker. No scheduler, no DB — checkpoints to `~/.tradingagents` files.
- **Strategy focus:** per-ticker daily decision. Pipeline: analyst agents (fundamentals, market,
  news, sentiment, social) → bull/bear researcher debate → research manager → trader → risk
  debate (aggressive/conservative/neutral debaters) → portfolio manager emits final
  BUY/SELL/HOLD; `graph/signal_processing.py` extracts the decision. Has a crypto asset mode.
  **It does not place orders** — output is a recommendation, there is no broker module.
- **Risk handling:** **no deterministic risk layer.** "Risk management" is three LLM prompt
  personas arguing (`agents/risk_mgmt/{aggressive,conservative,neutral}_debator.py`). No stops,
  no sizing, no kill-switch. Acceptable only because nothing executes.
- **LLM / agent usage:** the LLM *is* the entire decision path (deep-think + quick-think model
  tiers, configurable temperature). If anyone wires this to a broker, the LLM controls order
  side outright — red flag for live use.
- **Architecture notes:** clean package split `agents` / `dataflows` / `graph` / `llm_clients`;
  ~28 pytest files including `test_market_data_validator.py`, `test_signal_processing.py`,
  `test_ticker_symbol_handling.py` — unusually good test discipline for this genre.
  `default_config.py` has a single env-var → config-key override table with type coercion.
- **What to borrow:**
  - The `dataflows/market_data_validator.py` idea — a dedicated validation pass on fetched bars
    (stale/garbage detection) — maps onto `supabase/functions/_shared/marketdata.ts`, which
    today relies on the single stale-data guard in `daily-check`.
  - The env-override table in `default_config.py` (one declarative map, coercion from the
    default's type) is the same shape as `config.ts`'s validated settings; worth comparing if
    `config.ts` grows.
  - Their per-edge-case test files (symbol handling, no-data handling) are a good checklist for
    `marketdata.ts` / `regime.ts` test coverage.
- **What to avoid:** LLM-as-risk-manager; non-reproducible decisions (same inputs, different
  outputs); multiple deep-think LLM calls per ticker per day (cost); the framework's prestige
  (84k stars, arXiv paper) does not include any live or paper P&L evidence.

## 2. virattt/ai-hedge-fund — LLM persona ensemble

- **Stars / last commit / licence:** 59,930 / pushed 2026-06-09 / MIT. Python.
- **Stack:** Python + Poetry, LangChain/LangGraph, FastAPI backend with SQLAlchemy/Alembic
  (web app persistence only, not trading state), React frontend, Financial Datasets API for
  market data, multi-provider LLMs (OpenAI, Anthropic, Groq, DeepSeek, local Ollama).
- **Strategy focus:** ~18 persona agents (Buffett, Graham, Burry, Druckenmiller, Taleb, …) each
  emit a signal; a **deterministic** `risk_manager.py` computes volatility-adjusted position
  limits with correlation analysis; an **LLM** `portfolio_manager.py` then picks
  `action ∈ {buy, sell, short, cover, hold}` and an integer share quantity, capped by the
  risk manager's `max_shares`. README is explicit: educational only, **no broker, no execution**.
- **Risk handling:** partial deterministic layer — volatility-percentile position caps and
  correlation-aware limits computed in plain NumPy/pandas before the LLM sees anything. No
  stop-losses, no kill-switch (nothing is live). Flag: caps bound size but the LLM still chooses
  direction.
- **LLM / agent usage:** LLM controls order side and (capped) size — red flag pattern if ever
  connected to a broker; here it is contained by the no-execution scope.
- **Architecture notes:** one file per persona under `src/agents/`; a properly factored
  backtester (`src/backtesting/{engine,metrics,benchmarks,portfolio,trader}.py`) with
  integration tests using mocks (`tests/backtesting/integration/` — long-only, long-short,
  short-only suites).
- **What to borrow:**
  - The backtesting package layout (engine / metrics / benchmarks / output as separate modules,
    integration-tested against mocks) is a good template for issue #104's walk-forward harness
    in the Python research layer (`backtest/`).
  - The "deterministic numeric guard wraps whatever makes the decision" pattern is structurally
    the same idea as `alpaca.ts`'s `checkGuard()` on mutating calls — validation that the
    guard, not the decision-maker, is the last line.
- **What to avoid:** 18 persona agents is exactly the multi-signal ensemble this repo's v1.14
  pivot rejected — signals average to noise; paid Financial Datasets API dependency for
  anything beyond a few free tickers; no live or paper track record.

## 3. AI4Finance-Foundation/FinGPT — financial LLM toolkit (not a bot)

- **Stars / last commit / licence:** 20,456 / pushed 2026-06-01 / MIT. Jupyter Notebook + Python.
- **Stack:** HuggingFace transformers + LoRA fine-tuning (Llama-2/3, ChatGLM2, Falcon),
  notebooks at repo root, subprojects under `fingpt/` (Benchmark, Forecaster, RAG,
  MultiAgentsRAG, Sentiment v1/v3, FinancialReportAnalysis). No scheduler, no DB, no broker.
- **Strategy focus:** it doesn't trade. Products are fine-tuned financial LLMs: sentiment
  classifiers and **FinGPT-Forecaster** (Dow-30 LoRA model that outputs a next-week
  up/down prediction plus a narrative). Anything "trading" is left to the sibling FinRL project.
- **Risk handling:** none — out of scope; nothing executes.
- **LLM / agent usage:** the LLM is the product. Forecaster output is a directional call with
  free-text reasoning — unverifiable narrative attached to a binary prediction.
- **Architecture notes:** research-grade: notebooks as primary artifacts, a `tests/` dir that is
  minimal, subprojects with separate READMEs and uneven maintenance.
- **What to borrow:**
  - The only transferable idea is from `FinGPT_Benchmark`: score model outputs against realized
    labels on a held-out time window. That framing (prediction vs realized outcome, scored
    continuously) is what a live paper-soak scorecard for the regime bot should do — relevant
    to the evaluation side of #104.
- **What to avoid:** notebooks-as-product (irreproducible runs); treating chat-style forecasts
  as tradeable signals; the "RLHF robo-advisor" framing is aspirational marketing with no
  deployed system behind it.

## 4. AI4Finance-Foundation/FinRL — RL trading framework with Alpaca paper loop

- **Stars / last commit / licence:** 15,382 / pushed 2026-05-25 / MIT. Jupyter Notebook + Python.
- **Stack:** Python, gym-style environments (`finrl/meta/`), agents via Stable-Baselines3 /
  ElegantRL / RLlib, data from Yahoo Finance and Alpaca. **Live paper trading:**
  `finrl/meta/paper_trading/alpaca.py` runs a trained policy against the Alpaca paper API.
  No DB; `unit_tests/` exists but is thin (a handful of files for downloaders, one env test)
  relative to the surface area.
- **Strategy focus:** portfolio RL — the policy network outputs a continuous action vector
  mapped to share deltas across tickers; train/test/trade pipeline (`train.py`, `test.py`,
  `trade.py`).
- **Risk handling:** a **turbulence index** gate (env forces liquidation when market turbulence
  exceeds a threshold — a deterministic regime override) plus an `hmax` per-trade share cap.
  No stop-losses, no kill-switch in the paper-trading loop itself. Flag: the RL policy directly
  sets sizes; the guard lives in the env wrapper, not around the broker calls.
- **LLM / agent usage:** none in the decision path (RL policy networks, not LLMs).
- **Architecture notes:** `finrl/{agents,meta,applications}`; `config.py` constants plus a
  committed `config_private.py` template (secrets-in-repo pattern — avoid). Tutorial notebooks
  split into a separate FinRL-Tutorials repo.
- **What to borrow:**
  - The train → backtest → **same pipeline** → paper-trade discipline is the cleanest statement
    of "live paper scoring" in the survey: the artifact you backtest is byte-identical to the
    one you deploy. The repo already has this property (`regime.ts` is a 1:1 port of
    `strategy/regime.py`); #104's walk-forward should preserve it by validating the Python and
    TS implementations against the same fixtures.
  - The turbulence gate is conceptually the same mechanism as the kill-switch drawdown guard:
    a deterministic, signal-independent override. Useful precedent that one such override
    (not several) is the standard shape.
  - Their Alpaca paper loop polls the market clock before acting — same pattern as
    `kill-switch`'s `/v2/clock` early-exit.
- **What to avoid:** RL reward-hacking and overfit backtests (widely reported reproducibility
  problems with published FinRL results); test coverage far too thin for the surface area;
  `config_private.py` committed-secrets pattern.

## 5. microsoft/qlib — quant ML platform; the walk-forward reference

- **Stars / last commit / licence:** 44,224 / pushed 2026-04-22 / MIT. Python.
- **Stack:** Python (pip `pyqlib`), own flat-file point-in-time data store (no external DB),
  YAML-driven `qrun` workflows, MLflow-style experiment recorder, CI via GitHub Actions.
  Model zoo includes LightGBM, **LSTM/ALSTM** (`qlib/contrib/model/pytorch_lstm.py`,
  `pytorch_alstm.py`), GRU, Transformer, TRA, HIST and more, each with a benchmark config
  under `examples/benchmarks/`.
- **Strategy focus:** cross-sectional alpha — factor sets (Alpha158/Alpha360) → model score →
  top-k portfolio construction → backtest through a realistic nested executor (daily decision,
  intraday execution simulation) with cost/slippage modeling. Research platform: **no live
  broker**, but an online-serving module updates production signals.
- **Risk handling:** backtest-side risk analysis and portfolio optimizers; no live-trading risk
  layer because order execution is out of scope.
- **LLM / agent usage:** none in the decision path (the RD-Agent research-automation project is
  separate and upstream of, not inside, any trading loop).
- **Architecture notes:** the strongest separation of concerns in the survey: data handler /
  model / strategy / executor / evaluator are independent, swappable components configured
  declaratively. **Rolling retraining is first-class**: `examples/model_rolling/`,
  `examples/benchmarks_dynamic/baseline/rolling_benchmark.py`,
  `examples/online_srv/rolling_online_management.py` implement exactly the
  retrain-on-a-rolling-window, evaluate-on-the-next-window loop.
- **What to borrow:**
  - **For issue #104 (walk-forward backtest): this is the reference implementation.** The
    rolling task pattern — train/fit on window N, score on window N+1, roll, aggregate — is
    directly portable to the Python research layer (`backtest/` + `strategy/regime.py`), where
    "fit" for the regime strategy is just parameter selection (SMA length, drawdown threshold).
  - The experiment recorder (every run logged with config + metrics, comparable across runs) is
    the research-side analog of `audit_log` — the 2026-06-05 regime backtest doc would slot
    into such a record series.
  - Point-in-time data discipline (never let later data leak into earlier decisions) is the
    institutional version of the stale-data guard.
- **What to avoid:** adopting the platform itself — it's heavyweight for a one-rule bot; the
  abstraction level (factor zoo, nested executors) only pays off with many candidate models,
  which this repo's invariants deliberately forbid.

## 6. freqtrade/freqtrade — ML-augmented retail bot done properly

- **Stars / last commit / licence:** 51,292 / pushed 2026-06-09 / **GPL-3.0**. Python.
- **Stack:** Python 3.11+, CCXT (crypto exchanges), SQLite via SQLAlchemy for trade state,
  long-running bot daemon (own loop, not cron), Telegram bot + REST/web UI control plane,
  Docker. CI with ~137 test files and codecov — by far the most tested project in the survey.
- **Strategy focus:** user-defined strategy classes over OHLCV candles. **FreqAI** is the
  optional ML layer: per-pair models (LightGBM/XGBoost/CatBoost, PyTorch MLP/Transformer, or
  RL) trained on user-defined features/labels, **self-adaptively retrained on a schedule during
  live operation** (sliding train window, background-thread retrains), with outlier detection
  (SVM/DBSCAN/dissimilarity index) to suppress predictions on out-of-distribution data.
- **Risk handling:** the deterministic gold standard of the survey, layered and mandatory:
  per-strategy **stoploss is required**, trailing stops, ROI take-profit table, position sizing
  (`stake_amount`, `max_open_trades`), **protections** (StoplossGuard, MaxDrawdown,
  CooldownPeriod) that pause trading on loss clusters, exchange-side stoploss support,
  **dry-run default**, and `/stop` / `/stopentry` runtime controls. The ML model only ever
  feeds entry/exit signals into this scaffolding — it cannot bypass a stop.
- **LLM / agent usage:** none.
- **Architecture notes:** FreqAI splits model lifecycle (`freqai_interface.py`) from data
  management (`data_kitchen.py`, `data_drawer.py`); prediction models are thin plug-ins.
  Crucially, **the backtesting module emulates the live retraining cadence** ("realistic
  backtesting … that automates retraining" — i.e. walk-forward by construction).
- **What to borrow:**
  - **FreqAI's backtest-emulates-live-retraining is the second pillar for #104**: a
    walk-forward harness should replay the exact decision cadence production runs (daily
    `daily-check` semantics), not vectorize over the whole history.
  - Protections-as-composable-guards (drawdown pause, cooldown after stop cluster) are a
    natural vocabulary if the kill-switch ever needs a second condition — each guard is small,
    deterministic, and independently testable, like `computeTargetState`.
  - Dry-run-by-default and runtime `/stop` mirror the repo's paper-first soak and the `panic`
    function — validation that these are the conventions of the only mature project here.
- **What to avoid:** GPL-3.0 — do not vendor code into this MIT-adjacent codebase, borrow
  ideas only; configuration sprawl (hundreds of keys) versus `config.ts`'s handful of validated
  settings; crypto-exchange mechanics (funding, pairlists) don't map to Alpaca equities.

## 7. SC4RECOIN/LSTM-Crypto-Price-Prediction — the honest YouTube-genre bot

- **Stars / last commit / licence:** 363 / pushed 2021-08-10 / MIT. Python.
- **Stack:** Keras LSTM, python-binance, scikit-learn/scipy; flat scripts (`lstm.py`,
  `technical_analysis/*.py`, `historical_data/get_data.py`); data persisted as `.npy`/`.json`
  files. No tests, no scheduler, no DB. Dead since 2021.
- **Strategy focus:** BTC trend classification. Labels come from the derivative of a
  Savitzky-Golay-smoothed price (a forward-looking filter, used only for historical labeling);
  features are MACD histogram, stochastic RSI, DPO, Coppock curve, and a ridge-regression price
  interpolation. Binary buy/sell, all-in/all-out wallet simulation against Binance fees.
- **Risk handling:** **none.** No stops, no sizing (100% in or out), no kill-switch.
- **LLM / agent usage:** none.
- **Architecture notes:** single-author research scripts; the README is the documentation.
- **What to borrow:** the README's candor, not the code. Despite ~80% validation accuracy, the
  out-of-sample trading sim **lost 11.26% while buy-and-hold gained 6.51%** once the 0.1% fee
  was included (a retrain managed −7.45% vs −22.15% hold). This is the cleanest public
  demonstration that *classification accuracy ≠ P&L*. Concrete carry-over: #104's walk-forward
  harness must report fee-adjusted P&L against a buy-and-hold benchmark, never accuracy.
- **What to avoid:** forward-looking label filters anywhere near evaluation data; all-in binary
  position management; and note that the typical YouTube "1%/day LSTM bot" is a *less honest*
  version of exactly this repo.

## 8. yacoubb/stock-trading-ml — the "getting rich quick" tutorial repo

- **Stars / last commit / licence:** 662 / pushed 2022-05-18 / **GPL-3.0**. Python.
- **Stack:** Keras/TensorFlow LSTM, Alpha Vantage CSV data; five flat scripts
  (`save_data_to_csv.py`, `basic_model.py`, `tech_ind_model.py`, `trading_algo.py`,
  `util.py`). No tests. Dead since 2022; companion Medium article
  "Getting rich quick with machine learning and stock market predictions".
- **Strategy focus:** predict the next price point from a 50-step OHLCV history (optionally +
  technical indicators); `trading_algo.py` simulates buying/selling on the predicted delta.
- **Risk handling:** **none.** No stops, no sizing logic beyond the toy sim, no live trading.
- **LLM / agent usage:** none.
- **Architecture notes:** the workflow is "edit the model file, retrain, run the sim" — no
  reproducibility, no evaluation beyond chart overlays and the toy sim.
- **What to borrow:** nothing for the trading path. Its value is as a **known-bad baseline**:
  next-price LSTM regressors collapse toward persistence (predicting ≈ yesterday's price),
  which looks excellent on overlay charts and in MSE but is untradeable. #104's walk-forward
  harness should therefore include a persistence baseline among its benchmarks — any candidate
  model must beat it, which instantly disqualifies this whole model class.
- **What to avoid:** evaluating models by price-overlay charts or MSE; GPL-3.0 if anyone were
  tempted to copy the preprocessing code; Alpha Vantage free-tier rate limits make even the
  data step flaky today.

---

## Cross-cutting findings

**Deterministic risk layer: 1 of 8 has a production-grade one.** Only freqtrade enforces a
mandatory, deterministic risk stack (required stoploss, protections, dry-run default) around
its ML. Two more have partial numeric guards that never face a live broker (ai-hedge-fund's
volatility position caps; FinRL's turbulence gate inside the env). TradingAgents' "risk
management" is literally three LLM personas debating. FinGPT, qlib (out of scope), and both
small LSTM repos have none. The pattern is stark: **risk-layer maturity tracks whether the
project has real users with real money** — and only freqtrade does.

**Verified live track record: 0 of 8.** Nobody in the survey publishes audited or even
self-reported live returns. freqtrade explicitly refuses to claim profitability; TradingAgents
and ai-hedge-fund disclaim real trading entirely; FinRL ships a paper-trading loop but no
results; qlib and FinGPT publish research benchmarks, not P&L. The only out-of-sample trading
numbers in the entire survey are SC4RECOIN's — and they are losses. The YouTube
"100 agents / 1% daily" genre rests on a corpus in which **no public representative
demonstrates verifiable live profitability**, and its most honest member demonstrates the
opposite.

**Implications for this repo's invariants:**

1. **One decision rule (SPY vs 200-DMA, pure function in `regime.ts`) — reinforced.** The two
   most credible projects (qlib, freqtrade) treat the signal as a small swappable component and
   pour their engineering into *evaluation* (rolling retrains, realistic backtests, fees), not
   into signal count. The multi-agent ensembles (TradingAgents' debates, ai-hedge-fund's 18
   personas) reproduce the v1.14 architecture this repo already measured as a coin flip.
2. **No LLM in the trading path — reinforced, including by the LLM projects themselves.**
   Neither of the two flagship LLM-agent repos (145k combined stars) connects to a broker; both
   carry explicit "not for real trading" disclaimers, and where an LLM picks size
   (ai-hedge-fund) it is fenced by deterministic numeric caps. Not one surveyed project
   actually wires an LLM to order execution — the genre's own authors do not trust it with the
   thing this repo's invariant forbids.
3. **Deterministic risk layer — reinforced, and the survey suggests where to spend next.** The
   single mature project converges on exactly this repo's shape: deterministic stops/guards the
   model cannot bypass (≈ `kill-switch` + `alpaca.ts` `checkGuard()`), runtime stop controls
   (≈ `panic`), paper-first defaults. The highest-value imports are evaluation-side, aimed at
   issue #104: qlib's rolling train/score windows as the walk-forward skeleton for `backtest/`,
   FreqAI's "backtest replays the live cadence" framing for fidelity with `daily-check`, plus
   two mandatory baselines — buy-and-hold with fees (SC4RECOIN's lesson) and persistence
   (yacoubb's lesson) — and a live paper-soak scorecard that scores predictions against
   realized outcomes the way FinRL's train→paper pipeline and FinGPT's benchmark framing do.
