# GitHub Trading-Bot Projects — Survey

**Scope.** Survey of public GitHub repositories adjacent to this codebase (Python swing-trading bots, Alpaca integrations, LLM-augmented bots, larger frameworks) to identify patterns worth borrowing and red flags to avoid. Methodology: `gh api repos/<owner>/<repo>` for stars / license / `pushed_at`; WebFetch for README content. **Date: 2026-04-30.** **This is a partial scan, not exhaustive** — eight repos chosen for diversity over volume; many obvious candidates (vectorbt, backtrader proper, quantconnect/Lean) were not fetched. Treat findings as directional, not authoritative.

## Summary table

| Repo | Stars | Stack | Strategy | LLM? | Risk | Verdict |
|---|---|---|---|---|---|---|
| Lumiwealth/lumibot | 1.4k | Multi-broker (Alpaca/IBKR/Tradier/Schwab/CCXT) | Framework, agnostic | Yes (agent runtime + MCP) | Per-strategy, broker-abstracted | Borrow agent-runtime ideas |
| mathesco-git/alpaca-trading-bot | 2 | alpaca-py, FastAPI, SQLAlchemy, APScheduler | VWAP/RSI day + Golden-Cross swing | No | ATR sizing, trailing stops, kill switch | Closest peer — borrow heavily |
| gr8monk3ys/trading-bot | 3 | Alpaca, FastAPI, uv | Momentum + Adaptive + regime detection | Yes (Claude via .claude/, llm/) | Kill-switch script, audit utils | Useful for structure |
| abzdel/Swing-Trading-Stock-Bot | 48 | alpaca-trade-api, btalib/talib | SMA + RSI + pivots, daily | No | None visible — paper only | Avoid as template — too thin |
| TraderAlice/OpenAlice | 3.8k | TS/Python, Alpaca/IBKR/CCXT | Generic AI agent | Yes (Claude SDK + Vercel AI) | Guard pipeline, git-stage workflow | Borrow guard pipeline + replay |
| huygiatrng/AlpacaTradingAgent | 183 | LangGraph, alpaca-py | News+sentiment+fundamental synthesis | Yes (OpenAI / GPT-5-mini) | Margin checks; no stops visible | Borrow analyst-team shape |
| alpacahq/alpaca-mcp-server | 687 | alpaca-py, MCP | N/A — broker tool surface | Designed for LLM clients | Brackets exposed as a tool | Reference impl for tool design |
| rvanhezel/automated_alpaca_execution | 0 | Alpaca + TwelveData | Predefined bracket bot | No | Bracket orders + .env config | Tiny but bracket-first |

## Detailed entries

### 1. Lumiwealth/lumibot — `https://github.com/Lumiwealth/lumibot`
- **Stars / last commit / license**: 1,374 / 2026-04-30 / GPL-3.0 (per GitHub API; a PyPI dependency badge in the README references MIT, which is unrelated to the project's own license).
- **Stack**: Broker-agnostic framework supporting Alpaca, IBKR, Tradier, Schwab, CCXT. Python 3.x. No single SDK wrapped.
- **Strategy focus**: Generic — stocks, options, crypto, futures, forex; 25+ example strategies. Strategy lifecycle hook is `on_trading_iteration()`.
- **Risk handling**: Order placement via `create_order()` / `submit_order()`; bracket support not surfaced in README. Risk is per-strategy responsibility, not framework-enforced.
- **LLM/agent usage**: Yes — built-in "AI agent runtime" with MCP server support. Uses DuckDB for time-series so prompts don't carry raw bars. Backtests support deterministic agent replay. Companion BotSpot platform offers natural-language strategy authoring.
- **Architecture**: Clean separation — strategies / brokers / data sources / traders / agent runtime are modular. pytest with coverage; documented acceptance suite. "Same code runs backtest and live trading."
- **Borrow**:
  - **DuckDB-for-context pattern**: stop putting raw bars in prompts; load them into a queryable store and let the agent run SQL via tools. Directly applicable to our `MarketIntelligenceAgent`.
  - **Deterministic agent replay in backtests**: cache LLM responses by `(prompt_hash, market_state_hash)` so backtests don't re-bill or drift between runs.
  - **Strategy lifecycle hook** (`on_trading_iteration`) is a cleaner interface than our ad-hoc agent pipeline if we ever extend to intraday.
- **Avoid**: GPL-3.0 means any direct code lift propagates the licence to our project — design ideas only. Framework lock-in: lumibot is opinionated and hard to retrofit; our agent-pipeline + ATR risk layer is closer to a custom system than a strategy plugin.

### 2. mathesco-git/alpaca-trading-bot — `https://github.com/mathesco-git/alpaca-trading-bot`
- **Stars / last commit / license**: 2 / 2026-03-16 / no licence file (per GitHub API).
- **Stack**: `alpaca-py >= 0.21`, Python 3.10+ (built on 3.14), APScheduler `BackgroundScheduler` (US/Eastern), SQLAlchemy 2.0 + SQLite, FastAPI dashboard, Jinja2.
- **Strategy focus**: Two strategies running concurrently. Day: VWAP breakout + volume surge + RSI(14) > 55 on 5-min bars. Swing: Golden Cross (50 SMA over 200) OR RSI < 30 in uptrend on daily bars; exit on Death Cross with 2.0× ATR trailing stop.
- **Risk handling**: Position size = `equity * 2% * allocation% / (ATR * stop_multiplier)`. Pre-trade gate enforces (a) max positions (5 day / 10 swing), (b) allocation-vs-buying-power, (c) single-trade risk cap. Day trades use fixed 1.5× ATR stop + 2.0× ATR target. Swing uses ratchet-only trailing stop, no fixed take-profit. `ENABLE_TRADING` flag = monitor-only kill switch. **Brackets not visible** — stops are monitored every 60s by a price-loop, not server-side.
- **LLM/agent usage**: None in trading logic. Sentiment uses keyword matching, not ML.
- **Architecture**: 35 tests covering alpaca_client, data, risk_manager, executor, signals, scheduler, dashboard, db. Clean module boundaries: `core/`, `db/`, `dashboard/`, `utils/`. Singleton clients with TTL caches (10–30s). `asyncio.to_thread` to keep dashboard non-blocking. Exponential backoff on 429s. Heartbeat log + health-check job.
- **Borrow**:
  - **Three-check pre-trade gate** (max positions, allocation, single-trade risk) is exactly the shape of our `check_portfolio_guardrails` — adopt the explicit "single-trade risk cap" if we don't already have it.
  - **TTL-cached singleton broker clients** (10s account, 15s prices) — would reduce calls in our morning scan and monitor.
  - **Heartbeat / health-check job** that detects 5+ consecutive Alpaca failures and alerts; we should add this alongside our existing notifications.
  - **Composite `(strategy_type, status)` index** on trades — useful when we add strategy variants.
- **Avoid**: No bracket orders — relies on a 60s monitoring loop for stops. That's the exact pattern our CLAUDE.md calls out as defense-in-depth, not primary. If the monitor goes down, exits don't fire. Our bracket-order design is strictly safer.

### 3. gr8monk3ys/trading-bot — `https://github.com/gr8monk3ys/trading-bot`
- **Stars / last commit / license**: 3 / 2026-04-28 / GPL-3.0 (207 commits on main).
- **Stack**: Alpaca, `uv` package manager, FastAPI dashboard, pytest with `.coveragerc`. Python version pinned via `.python-version`.
- **Strategy focus**: `MomentumStrategy`, `AdaptiveStrategy`, plus a regime detector under `factors/`. Strategies live in `strategies/`, broker glue in `brokers/`, execution in `execution/`.
- **Risk handling**: Dedicated `scripts/kill_switch.py` with `--cancel-orders` and `--liquidate` flags. `utils/` contains "risk, reconciliation, audit" helpers. Pre-flight `go_live_precheck_summary.json`. Specific stop/bracket mechanics not visible in README.
- **LLM/agent usage**: Yes — `.claude/` directory, `CLAUDE.md`, `AGENTS.md`, dedicated `llm/` module. Implementation details not exposed in the README.
- **Architecture**: Modular by domain (brokers, engine, strategies, execution, factors, ml, research). Engine handles backtest/eval/validation/replay. Docker + Railway + Raspberry-Pi profiles. FastAPI web dashboard.
- **Borrow**:
  - **Standalone kill-switch script** with `--cancel-orders` / `--liquidate` flags is operationally cleaner than our `TRADING_PAUSED` env-only flag — add a `main.py panic` command.
  - **Pre-flight `go_live_precheck` artifact** that gates a config from going live — would harden our deploy story.
  - **Replay logic in the engine** — pair with cached LLM responses to make agent runs reproducible.
- **Avoid**: Low stars and unverified production use; treat as inspiration, not prior art. GPL-3.0 means no copy-paste without re-licensing implications.

### 4. abzdel/Swing-Trading-Stock-Bot — `https://github.com/abzdel/Swing-Trading-Stock-Bot`
- **Stars / last commit / license**: 48 / **2020-12-15 (5+ years stale)** / no licence file (per GitHub API).
- **Stack**: Python 3.7 (!), legacy `tradeapi` (alpaca-trade-api), btalib + talib, raw `requests`/`json`. CSV for state.
- **Strategy focus**: SMA crossovers, RSI, pivot/support/resistance levels on daily bars.
- **Risk handling**: Single `equity_limit` for allocation. **No stops, no brackets, no sizing formula**. Author states "paper only until bugs eliminated."
- **LLM/agent usage**: None.
- **Architecture**: Four scripts (scrape, place orders, sell, orchestrator). No tests. No backtest. No monitor. State is CSV files in `/data/`.
- **Borrow**: Almost nothing — file separation by phase (scrape → buy → sell) is a fine pedagogical structure but we already do better.
- **Avoid**:
  - **CSV-as-state**: race conditions, no transactions. Our SQLite + foreign keys is the right call.
  - **No risk layer**: live-trading this would be reckless. Reaffirms why our deterministic risk module is the architectural invariant it is.
  - **Python 3.7 + legacy SDK + last push 2020-12-15**: a stack and a repo both effectively abandoned. Don't borrow patterns from it.

### 5. TraderAlice/OpenAlice — `https://github.com/TraderAlice/OpenAlice`
- **Stars / last commit / license**: 3,805 / 2026-04-30 / AGPL-3.0 (649 commits on master).
- **Stack**: TypeScript 81% + Python 18.8%, Node 22+, pnpm, Turborepo. Brokers: CCXT, Alpaca, IBKR (via TWS/Gateway with `RequestBridge`).
- **Strategy focus**: Generic agent-driven — equities, crypto, commodities, forex, macro. Strategy is whatever the LLM decides, gated by guards.
- **Risk handling**: **"Guard pipeline"** runs pre-execution: max position size, cooldown between trades, symbol whitelist. **"Trading-as-Git"**: orders are *staged*, *committed* with a message, and require explicit *push* approval before execution — gives a literal audit trail. Account snapshots + equity curve.
- **LLM/agent usage**: Yes, multi-provider via `ProviderRouter` — Claude Agent SDK as default (uses local Claude Code login, no API key), Vercel AI SDK fallback (Anthropic/OpenAI/Google). Switchable at runtime.
- **Architecture**: Four layers — Interface (Web/Telegram/MCP), Core (AgentCenter/ProviderRouter/ToolCenter/EventLog), Domain (UTA/MarketData/Analysis/News/Brain), Automation (Cron/Heartbeat). UTA = Unified Trading Account, one per broker connection with isolated git history + guard config. vitest test suite (unit + e2e + provider).
- **Borrow**:
  - **Guard pipeline as a named first-class layer** with composable checks (max position, cooldown, whitelist) — formalises what we have scattered between `tools/risk.py` and `team_leader.place_order`. Cooldown specifically is missing from our system and would prevent re-entry whipsaw.
  - **Trading-as-Git pattern** — staged-then-pushed orders with commit messages — is essentially a structured audit log with human-in-the-loop gating. Even if we don't adopt git literally, a "pending order" status with explicit approve step would be useful for live mode.
  - **EventLog as a core component** rather than scattered DB writes — gives us a clean substrate for replay and post-mortem.
- **Avoid**: TypeScript-first means we can't lift code directly. AGPL is restrictive — design ideas are fine but copying source has reciprocal-license consequences. The 3.8k stars in <1 year suggest some hype/velocity risk; production maturity unverified.

### 6. huygiatrng/AlpacaTradingAgent — `https://github.com/huygiatrng/AlpacaTradingAgent`
- **Stars / last commit / license**: 183 / 2026-04-17 / Apache-2.0.
- **Stack**: LangGraph, Alpaca (paper + live), Finnhub, FRED, CoinDesk, optional Twitter sentiment. Python version not stated.
- **Strategy focus**: Multi-agent LLM synthesis rather than a fixed indicator strategy. Agents debate; the trader agent acts on the synthesis.
- **Risk handling**: README mentions "margin trading controls and risk management" plus margin requirement evaluation, but **no specific stop-loss, sizing formula, kill switch, or bracket details visible**. This is a red flag for a 183-star repo using real broker access.
- **LLM/agent usage**: **Yes — most directly comparable to our pipeline.** Five specialist analysts (Market, Social Sentiment, News, Fundamental, Macro) plus a bullish/bearish Researcher pair plus a Trader agent. Uses OpenAI (recommends `gpt-5-mini` for testing). Configurable parallel-analyst execution with delays to throttle the API.
- **Architecture**: `tradingagents/`, `cli/`, `webui/`, `tests/`. LangGraph orchestrates the agent graph.
- **Borrow**:
  - **Specialist-analyst decomposition** (Market / News / Fundamental / Macro / Sentiment) is a richer version of our `MarketIntelligenceAgent` — splitting it into 2–3 sub-analysts whose outputs feed `StrategyAgent` would improve traceability and let us cache each analyst's response independently.
  - **Bullish/Bearish researcher pair** before the trader — cheap "red team" that we could implement as a single extra agent call inside `RiskReviewAgent`, forcing it to articulate the bear case.
  - **Configurable parallel-analyst delay** to dodge rate limits — useful when we add more agents.
- **Avoid**:
  - **No deterministic risk layer described in README** — our CLAUDE.md explicitly forbids letting LLMs control risk parameters. If this repo really lets the trader agent set stops, that's the exact anti-pattern. Any borrow here must stay on the *analysis* side, not the *order* side.
  - LangGraph adds heavy framework dependencies; our `BaseAgent` loop is simpler and gives us the same affordances.

### 7. alpacahq/alpaca-mcp-server — `https://github.com/alpacahq/alpaca-mcp-server`
- **Stars / last commit / license**: 687 / 2026-04-17 / MIT.
- **Stack**: Python 3.10+, official Alpaca MCP server. Wraps both trading and market-data APIs via JSON specs (`specs/trading-api.json`, `specs/market-data-api.json`).
- **Strategy focus**: N/A — this is the broker tool surface, not a strategy.
- **Risk handling**: No risk tools per se. Brackets *are* exposed as a supported order type ("market, limit, stop, stop-limit, trailing-stop, brackets"). Disclaimers note insights are not advice.
- **LLM/agent usage**: Built specifically for LLM clients — Claude Desktop, Cursor, Claude Code, VS Code, PyCharm, Gemini CLI.
- **Architecture**: Three-layer test suite: integrity (spec/toolset consistency, no creds), construction (mocked creds), integration (live paper). Tools grouped into 9 domains (account, trading, positions, watchlists, assets, stock data, crypto data, options, news). Spec-driven via `sync-specs.sh`.
- **Borrow**:
  - **Spec-driven tool definitions** with sync script — our agent tool definitions are hand-maintained in Python; pulling them from a JSON spec would prevent drift when the SDK changes.
  - **Three-layer test taxonomy** (integrity / construction / integration) is a cleaner separation than our current pytest layout. Worth replicating.
  - **Toolset grouping** (account, trading, data, positions, watchlists) — if we ever expose tools to a Claude Desktop user, this is a solid domain split.
- **Avoid**: This is a broker server, not a bot. Don't try to make our bot consume it — we already have direct `alpaca-py` calls and adding an MCP layer would just add latency and a process. Consider it a *reference* for tool ergonomics only.

### 8. rvanhezel/automated_alpaca_execution — `https://github.com/rvanhezel/automated_alpaca_execution`
- **Stars / last commit / license**: 0 / 2025-03-10 (>1 year stale) / no licence file (per GitHub API).
- **Stack**: Python 3.12+, Alpaca + TwelveData. `.env` for secrets, `run.cfg` for config, `main.py` entry. Minimal.
- **Strategy focus**: Predefined stocks, fixed bracket orders. Not a signal generator.
- **Risk handling**: Bracket orders with stop-loss + take-profit are the entire risk model. No sizing, kill switch, or backtest.
- **LLM/agent usage**: None.
- **Architecture**: `src/`, `main.py`, `run.cfg`, output folder. Logging present.
- **Borrow**:
  - **Bracket-first ethos** — even with zero stars and no strategy, the design centres on submitting bracket orders, mirroring our invariant that exits run server-side. A useful sanity-check that bracket-as-primary is the right shape.
  - **External config file (`run.cfg`) plus `.env` separation** — clean pattern for config that's not secret.
- **Avoid**: Tiny, unmaintained, no tests, no sizing. Reference only — not a template.

## Cross-cutting findings

- **Brackets are the minority.** Of the 8 repos surveyed, only 3 surface bracket orders as a primary exit mechanism (alpaca-mcp-server, automated_alpaca_execution, and lumibot indirectly). The popular swing/AI bots (mathesco, Th3M4dH4ck3r-style, abzdel, AlpacaTradingAgent) rely on monitoring loops or simply omit stops. **Our bracket-order invariant puts us in the safer minority.**
- **LLM-driven bots almost universally lack a deterministic risk layer.** OpenAlice's "guard pipeline" is the exception; AlpacaTradingAgent, claude-trading-bot, and others advertise "AI risk management" without naming a deterministic check. This validates our CLAUDE.md invariant and is the single biggest differentiator we should keep.
- **Scheduler convergence on APScheduler.** The mid-tier bots (mathesco) and many tutorials gravitate to APScheduler with US/Eastern timezone. Our cron-based approach is fine but APScheduler in-process would let us co-locate scan + monitor + health-check with shared TTL caches.
- **Test coverage is thin almost everywhere.** Only mathesco (35 tests), lumibot, alpaca-mcp-server, and gr8monk3ys show real test infrastructure. Several 100+ star LLM bots have no visible tests. We're already above the median; the alpaca-mcp-server three-tier model (integrity / construction / integration) is the bar to chase.
- **`alpaca-py` has decisively replaced `alpaca-trade-api`** in any repo started after early 2024. The legacy SDK appears in older or unmaintained projects (abzdel, jasona7). We're already on the right side of this.
- **Multi-agent decomposition is in fashion** — AlpacaTradingAgent (5 analysts + researchers + trader), OpenAlice (AgentCenter + ProviderRouter), lumibot (agent runtime). Most do not bound the LLM with deterministic gates. **The interesting design space is "many specialised analysts + one deterministic risk wall + one trader."**
- **Kill-switch UX varies widely.** Env-flag (mathesco's `ENABLE_TRADING`, our `TRADING_PAUSED`) is most common. gr8monk3ys ships a dedicated `kill_switch.py` script with `--cancel-orders --liquidate` flags. The script form is operationally cleaner during an incident.
- **State storage trends to SQLAlchemy + SQLite.** The most production-shaped peer (mathesco) uses SQLAlchemy ORM with composite indexes. Our hand-written `storage/schema.sql` + named-parameter queries is leaner; ORM would only pay off if our schema grew significantly.

## Roadmap pattern candidates

- **Add a cooldown check to `tools/risk.py`** (OpenAlice guard pipeline). After an exit, block re-entry on the same symbol for N bars. Prevents whipsaw and is trivial to implement against existing trade history.
- **Add a `main.py panic` (or `kill_switch.py`) script** with `--cancel-orders` and `--liquidate` flags (gr8monk3ys). Operational cleanliness vs. our env-only `TRADING_PAUSED` flag.
- **Split `MarketIntelligenceAgent` into 2–3 specialist sub-analysts** (AlpacaTradingAgent pattern: market/news/macro), with parallel calls and per-analyst response caching. Improves traceability and lets us cache hot paths separately.
- **Add a "bear case" pass inside `RiskReviewAgent`** (AlpacaTradingAgent's bullish/bearish researcher pair). One extra prompt, forces the model to articulate the downside before approving the trade.
- **Adopt a three-tier test taxonomy** (alpaca-mcp-server): integrity (no creds, schema/spec consistency), construction (mocked clients), integration (live paper). Cleaner than our current single-tier pytest layout.
- **Add a heartbeat / health-check job** that detects N consecutive Alpaca API failures and posts a critical alert (mathesco). Sits naturally next to our existing notifications module.

