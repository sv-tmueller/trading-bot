# GitHub Trading-Bot Projects -- Risk, Sizing and Strategy Combination

**Scope.** Survey of public GitHub repositories with an eye on one question: how do real-world bots and frameworks size positions, cap losses, halt trading, and combine more than one strategy? Input for issue #675 (raise effective risk per trade from ~0.025% of account toward 0.1-1% via risk-based sizing, notional cap as backstop). Methodology: `gh api repos/<owner>/<repo>` for stars / licence / `pushed_at`; `gh api .../contents/<path>` to read the actual risk/sizing source files; README/docs only where code was not enough. **Date: 2026-10-23.** Partial scan, diversity over volume. The `swing-trading` bundle already covered lumibot, OpenAlice, alpaca-mcp-server and several small Alpaca bots; they are not repeated here.

**Lens.** CLAUDE.md "Architectural invariants": one decision rule (`decideHourly`), no LLM in the trading path, mechanical paper-only guard, `bot_config.paused` as the operational kill switch, deterministic panic. Every "what to borrow" bullet below is filtered through that list.

**Where this codebase stands today (for comparison).** Sizing is `computeSizing` in `supabase/functions/hourly-check/logic.ts`: `qty = min(floor(SIZING_RISK_PCT * equity / stopDistance), floor(SIZING_NOTIONAL_CAP_PCT * equity / entryRef))`, defaults `0.01` / `0.10`, bounds `(0, 0.05]` / `(0, 1.0]` in `supabase/functions/_shared/config.ts`. Because SPY hourly stops are ~0.25% of price, the notional leg always binds and realised risk is ~0.025-0.03% of equity (#499, #675). Loss limits: a fixed `EQUITY_FLOOR_PCT = 0.15` floor against `hourly_experiment_start_equity` that writes `bot_config.paused=true`; `HOURLY_MAX_ENTRIES_PER_DAY` (default 3); a post-exit cooldown gate (gate 13); the `kill-switch` function's per-position drawdown check. There is **no daily-loss limit and no consecutive-stop-loss guard**.

## Summary table

| Repo | Stars | Licence | Stack | Strategy scope | Risk-per-trade sizing | Portfolio loss limits | Combines strategies? | LLM? |
|---|---|---|---|---|---|---|---|---|
| freqtrade/freqtrade | 55.8k | GPL-3.0 | Python, ccxt, SQLAlchemy | Crypto spot/futures, one strategy per bot | Notional by default (`stake_amount`); risk sizing only via `custom_stake_amount` callback, clamped to min/max stake | Protections: `StoplossGuard`, `MaxDrawdown`, `CooldownPeriod`, `LowProfitPairs` | No (one strategy per process) | No (FreqAI is ML, not LLM) |
| nautechsystems/nautilus_trader | 30.6k | LGPL-3.0 | Rust core + Python API | Multi-venue, event-driven, any asset class | `calculate_fixed_risk_position_size` (equity x risk / stop distance, minus 2x commission, then `hard_limit`) | `RiskEngine`: `TradingState` ACTIVE / REDUCING / HALTED, order-rate limits, `max_notional_per_order` | Yes (many strategies share one RiskEngine) | No |
| QuantConnect/Lean | 22.2k | Apache-2.0 | C# engine, Python API | Multi-asset, research + live | None per-trade; weights from Portfolio Construction model | `MaximumDrawdownPercentPortfolio` 5%, `MaximumDrawdownPercentPerSecurity` 5%, trailing stop 5%, sector cap 20% | Yes -- the Algorithm Framework (`CompositeAlphaModel` -> PCM -> Risk -> Execution) | No |
| jesse-ai/jesse | 8.7k | MIT | Python | Crypto, multi-symbol/timeframe | `utils.risk_to_qty(capital, risk_pct, entry, stop)`, capped at 100% of capital | None built in | Per-route strategies, no allocator | MCP server for authoring/backtests only |

| hummingbot/hummingbot | 20.6k | Apache-2.0 | Python/Cython, connectors | Market making + directional "controllers" (V2) | Fixed quote amount per controller (`total_amount_quote`); triple-barrier per position | Global P&L kill switch (`kill_switch_rate`, off by default); `max_global_drawdown_quote` / `max_controller_drawdown_quote` | Yes -- many controllers in one script, per-controller budget and drawdown stop | Separate "Condor" AI harness (LLM decides, Hummingbot executes) |
| microsoft/qlib | 49.6k | MIT | Python, ML pipeline | Cross-sectional stock selection (China/US equities) | None per-trade; `risk_degree` = fraction of capital deployed (default 0.95) | None (research backtester) | Model ensembles (`AverageEnsemble`), `NestedExecutor` multi-level strategies | RD-Agent (separate repo) = LLM factor/model mining |
| alpacahq/Momentum-Trading-Example | 724 | none (per GitHub API) | Python, legacy `alpaca_trade_api`, websockets | Intraday momentum on low-priced US stocks | `portfolio_value x 0.001 // (close - stop)` -- 0.1% risk per trade, no notional cap | None; flatten all 15 min before close | No | No |
| barter-rs/barter-rs | 2.4k | MIT | Rust, async engine | Framework (crypto venues) | Left to strategy | `RiskManager` trait returns `RiskApproved` / `RiskRefused`; `TradingState` Enabled/Disabled | Shared engine, one strategy trait | No |

## Detailed entries

### 1. freqtrade/freqtrade -- `https://github.com/freqtrade/freqtrade`
- **Stars / last commit / licence**: 55,788 / 2026-10-23 / GPL-3.0 (per GitHub API; default branch `develop`).
- **Stack**: Python, ccxt for exchange access, SQLAlchemy trade DB, Telegram/REST control, hyperopt, optional FreqAI (ML).
- **Strategy focus**: Crypto spot and futures. One `IStrategy` subclass per bot process; `populate_entry_trend` / `populate_exit_trend` vectorised over a dataframe.
- **Risk handling**:
  - **Sizing is notional-first.** `stake_amount` is a fixed quote-currency amount or `"unlimited"` (`freqtrade/constants.py: UNLIMITED_STAKE_AMOUNT`). With `"unlimited"`, `freqtrade/wallets.py::_calculate_unlimited_stake_amount` splits `(available + tied_up) / max_open_trades` -- equal-notional slots, not equal-risk. `tradable_balance_ratio` defaults to `0.99` (`freqtrade/config_schema/config_schema.py`); `available_capital` optionally overrides the starting balance.
  - **Risk-based sizing is opt-in code.** The strategy hook `custom_stake_amount(..., proposed_stake, min_stake, max_stake, ...)` (`freqtrade/strategy/interface.py`) is where a user writes `risk% x equity / stop distance`. The framework then runs `Wallets.validate_stake_amount`, which clamps the result to `min(max_stake, available_stake)` and refuses (returns 0) if bumping up to the exchange minimum would exceed the request by more than 30%. That is the "risk sizing with a notional backstop" shape #675 wants, with the backstop owned by the framework, not the strategy.
  - **Protections** (`freqtrade/plugins/protections/`), each a lock with `lookback_period[_candles]` and `stop_duration[_candles]` (code defaults 60 min / 60 min in `iprotection.py`):
    - `StoplossGuard` -- `trade_limit` default 10 (code), docs example `lookback_period_candles: 24, trade_limit: 4, stop_duration_candles: 4`; global or per-pair, optional `only_per_side`.
    - `MaxDrawdown` -- `max_allowed_drawdown` default `0.0` and `trade_limit` default 1 in code (so it must be configured); docs example: `> 20%` over 48 candles with `trade_limit: 20` -> stop 12 candles. Two calculation modes: legacy `"ratios"` (default; sums per-trade profit ratios) and `"equity"` (relative account drawdown from a reconstructed starting balance).
    - `CooldownPeriod` -- per-pair re-entry lock after any exit (docs example 2 candles).
    - `LowProfitPairs` -- locks a pair whose recent profit ratio is below `required_profit` (docs example 0.02 over 6 candles).
  - Docs note protection end times are rounded up to the next candle, and protections only run in backtests with `--enable-protections`.
- **How it combines strategies**: It does not. One strategy per bot; users run multiple bots against separate sub-accounts. No allocator.
- **LLM/agent usage**: None in the trading path. FreqAI is classical ML (LightGBM etc.) feeding strategy columns, configured by the user.
- **Architecture notes**: Protections are a plugin list evaluated by a `ProtectionManager` before entries; each returns a `ProtectionReturn` lock with an `until` time, persisted in the DB as `PairLock`s. `has_global_stop` / `has_local_stop` class flags declare whether a protection can lock the whole bot or one pair.
- **What to borrow**:
  - **A `StoplossGuard`-style gate** next to gate 13 (cooldown) in `supabase/functions/hourly-check/logic.ts`: "N stop-outs in the last M hourly bars -> skip entries for K bars", computed from the existing `trades` rows (`hourly_bracket_exit` covers both bracket legs, so a losing exit is identified by fill price vs the entry's `risk_per_share`/entry fill, not by reason alone). Deterministic, state-dependent, audit-log reproducible -- fits invariant 1's narrowed reproducibility clause.
  - **Framework-owned clamp after the risk computation.** Keep `computeSizing`'s risk leg as the primary and the notional leg as a clamp, exactly as freqtrade separates `custom_stake_amount` from `validate_stake_amount`. Log which leg bound (freqtrade logs "adjusting to max_allowed_stake") -- add `bound_by: "risk" | "cap"` to the `hourly_scans` row / `audit_log` notes so #675's acceptance test ("binding-limit switch") is observable in production too.
  - **Explicit drawdown calculation mode.** freqtrade's `ratios` vs `equity` split is a reminder that "drawdown" must name its base. Our equity floor is equity-based against a fixed baseline; document that choice in the #675 ADR.
- **What to avoid**:
  - GPL-3.0: design ideas only, no code lift.
  - Equal-notional `"unlimited"` slot sizing makes risk per trade a function of stop width -- the very bug #499 describes. Do not treat it as a model.
  - `MaxDrawdown` default `max_allowed_drawdown = 0.0` with `trade_limit = 1` is a footgun-by-default (it needs explicit config to do anything sensible). Our protections should ship with non-degenerate, range-validated defaults per the `add-or-extend-agent` recipe.

### 2. nautechsystems/nautilus_trader -- `https://github.com/nautechsystems/nautilus_trader`
- **Stars / last commit / licence**: 30,634 / 2026-10-23 / LGPL-3.0 (per GitHub API; default branch `develop`).
- **Stack**: Rust core (`crates/`), Python bindings (`python/nautilus_trader/`), event-driven message bus, identical code for backtest and live.
- **Strategy focus**: Framework, asset-class agnostic (FX, futures, crypto, equities via adapters). Strategies are actors that emit order commands.
- **Risk handling**:
  - **`RiskEngine`** (`crates/risk/src/engine/mod.rs`, config in `crates/risk/src/engine/config.rs`) sits between every strategy and every execution client. `RiskEngineConfig` defaults: `bypass: false`, `max_order_submit = 100 per 1s`, `max_order_modify = 100 per 1s`, `max_notional_per_order: {}` (per-instrument map, empty by default), `full_position_exit_venues: {}`.
  - **`TradingState`**: `Active`, `Reducing` (only orders that reduce an existing position pass; others denied with `TradingStateReducing`), `Halted` (all new submits and modifies denied with `TradingHalted`). Settable at runtime via `set_trading_state`.
  - Pre-trade checks (`check_order`, `check_order_price`, `check_order_quantity`, `check_orders_risk_for_account`, `check_risk_increase`, `check_cash_sell_balance`): price/quantity precision, missing expire time on GTD, per-order notional vs `max_notional_per_order`, free-balance sufficiency, and amendments that would increase exposure before the venue acknowledges a reduction.
  - **Fixed-risk sizer** (`crates/risk/src/sizing.rs::calculate_fixed_risk_position_size`): `risk_money = equity x risk - 2 x (equity x risk x commission_rate)`; `size = risk_money / exchange_rate / (|entry - stop| in ticks) / tick / multiplier`; then `min(size, hard_limit)`, split across `units`, floored to `unit_batch_size`, then capped at the instrument's `max_quantity`. Zero stop distance returns zero quantity rather than dividing.
- **How it combines strategies**: Multiple strategies run in one `TradingNode`; all share the one `RiskEngine` and portfolio, so per-instrument notional limits and the trading state apply across strategies. No built-in capital allocator between strategies.
- **LLM/agent usage**: None.
- **Architecture notes**: Risk is a separate engine on the message bus, not a helper the strategy may forget to call. Denials are first-class events (`OrderDenied` with a reason string), so a blocked order is auditable. The sizer has its own unit tests (`test_impose_hard_limit`, `test_calculate_for_gbpusd_with_commission`, zero-risk and zero-exchange-rate cases).
- **What to borrow**:
  - **Commission-adjusted risk budget.** Subtract a round-trip cost estimate from `riskBudget` in `computeSizing` (nautilus: `2 x commission_rate x risk_money`). At SPY hourly stop widths, slippage/fees are a material fraction of 1R (the 2026-10-22 verdict measured expectancy at 1 bp/side), so the risk leg should size on net R.
  - **A `REDUCING` state distinct from `paused`.** Today `bot_config.paused=true` halts entries and `panic` liquidates. A `reducing_only` value (or a second key) that lets the bracket legs / session-close flatten run but refuses new entries is what `paused` already does for entries; making the "exits still allowed" guarantee explicit and tested in `hourly-check` is the borrowable part.
  - **Order-rate limit as a mechanical guard.** A per-function "max broker submits per invocation" assertion inside `supabase/functions/_shared/alpaca.ts` (alongside `checkGuard()`) would have bounded the #149 incident class (6 and 5 parent orders in seconds) independently of `CLAUDE_AGENT_NO_BROKER`.
  - **Test cases for the sizer**: hard-limit binding, zero stop distance, commission haircut -- mirror these in `hourly-check/logic.test.ts` for #675's "binding-limit switch" criterion.
- **What to avoid**:
  - LGPL-3.0 and a Rust/Python stack: ideas, not code.
  - `bypass: true` exists as a config flag; any equivalent here (a secret that disables sizing caps) would undermine the default-OFF/fail-closed pattern. Do not add a bypass.

### 3. QuantConnect/Lean -- `https://github.com/QuantConnect/Lean`
- **Stars / last commit / licence**: 22,164 / 2026-10-22 / Apache-2.0 (per GitHub API).
- **Stack**: C# engine with Python strategy API; local CLI or QuantConnect cloud; many brokerages including Alpaca.
- **Strategy focus**: Generic multi-asset research and live trading. The "Algorithm Framework" separates Universe Selection -> Alpha -> Portfolio Construction -> Risk Management -> Execution.
- **Risk handling** (`Algorithm.Framework/Risk/`), each a model returning `PortfolioTarget(symbol, 0)` to liquidate:
  - `MaximumDrawdownPercentPerSecurity(maximumDrawdownPercent = 0.05m)` -- per-holding unrealised loss limit.
  - `MaximumDrawdownPercentPortfolio(maximumDrawdownPercent = 0.05m, isTrailing = false)` -- portfolio-level; non-trailing measures from the starting value, trailing from the running high. When it fires it cancels insights, liquidates all targets, and **resets `_initialised = false`**, i.e. re-arms at the new lower equity and lets the strategy resume on the next rebalance. Not a latching halt.
  - `TrailingStopRiskManagementModel(maximumDrawdownPercent = 0.05m)`, `MaximumUnrealizedProfitPercentPerSecurity(0.05m)` (take-profit), `MaximumSectorExposureRiskManagementModel(maximumSectorExposure = 0.20m)`.
  - `CompositeRiskManagementModel` (`Algorithm/Risk/`) chains several risk models in sequence.
  - Algorithm-level settings (`Common/AlgorithmSettings.cs`): `FreePortfolioValuePercentage = 0.0025` (cash buffer), `MinimumOrderMarginPortfolioPercentage = 0.001` (skip tiny rebalances).
  - **No per-trade "risk % to stop" sizer in the framework.** Sizing is weight-based: the Portfolio Construction model (`EqualWeighting`, `InsightWeighting`, `ConfidenceWeighted`, `RiskParity`, `MeanVarianceOptimization`, `BlackLitterman`, `SectorWeighting` in `Algorithm.Framework/Portfolio/`) emits target percentages.
- **How it combines strategies**: The clearest reference in this survey. `CompositeAlphaModel` (`Algorithm/Alphas/CompositeAlphaModel.cs`) wraps several alpha models and tags each `Insight` with its `SourceModel`; the PCM turns the union of insights into one set of portfolio targets; risk models then veto/trim; execution places orders. Strategies never place orders directly, so there is exactly one sizing/risk path regardless of how many signals exist.
- **LLM/agent usage**: None in the engine.
- **Architecture notes**: Each stage is an interface (`IAlphaModel`, `IPortfolioConstructionModel`, `IRiskManagementModel`, `IExecutionModel`) with a Null default; tests per model under `Tests/Algorithm/Framework/`.
- **What to borrow**:
  - **The "signal -> sizing -> risk veto -> execution" pipeline shape** as the design constraint for any future second signal. If the repo ever needs one (which invariant 1 requires a fresh brainstorm for), it should enter as another alpha feeding one shared sizer (`computeSizing`) and one shared risk layer, never as a parallel bot with its own sizing. Insight tagging (`SourceModel`) maps to a `signal_source` column on `hourly_scans` / `trades`.
  - **Name the drawdown base.** Lean exposes `isTrailing` as an explicit argument. Our `EQUITY_FLOOR_PCT` is non-trailing from `hourly_experiment_start_equity`; if #675 raises size, a trailing variant (from the running high) is the conservative complement and should be a separate, explicitly named setting.
- **What to avoid**:
  - **Auto-re-arming portfolio stop.** `MaximumDrawdownPercentPortfolio` liquidates and then resumes. Our floor's "write `paused=true`, never self-clear" latch (`success:auto_paused`) is stricter and should stay that way.
  - 5% defaults are illustrative, not calibrated; do not copy them as defaults.

### 4. jesse-ai/jesse -- `https://github.com/jesse-ai/jesse`
- **Stars / last commit / licence**: 8,691 / 2026-10-22 / MIT (per GitHub API).
- **Stack**: Python framework with web dashboard, backtest/optimise/live (live via a paid plugin), 300+ indicators.
- **Strategy focus**: Crypto spot/futures; strategies declared as "routes" (exchange, symbol, timeframe, strategy class); README advertises multi-symbol/timeframe support.
- **Risk handling**:
  - `jesse/utils.py::risk_to_qty(capital, risk_per_capital, entry_price, stop_loss_price, precision=8, fee_rate=0)` -> `risk_to_size` -> `size_to_qty`. Core formula: `size = (risk_pct/100 x capital / |entry - stop|) x entry`, then **`min(size, capital)`** -- a built-in 100%-of-capital notional cap. With a fee rate, size is haircut by `(1 - 3 x fee_rate)`. `risk_per_capital` is in percent units (`1` = 1%); `risk_to_size(10000, 1, 0.7, 8.6) ~= 1229` is the docstring example. Zero stop distance raises `ValueError`.
  - No portfolio-level protections (daily loss, max drawdown, cooldown) in the framework; stops/targets are per-strategy (`self.stop_loss`, `self.take_profit`).
- **How it combines strategies**: Several routes can run at once, each with its own strategy instance; there is no cross-route allocator or shared risk budget.
- **LLM/agent usage**: "Jesse MCP" server lets Claude/Codex/Cursor write strategies, run backtests, optimise and run Monte Carlo locally. Authoring-time only per README; no LLM in the live order path. Not a red flag, but it is a shortcut to LLM-tuned parameters, which is exactly the overfitting surface our pre-registration discipline exists to block.
- **Architecture notes**: Small, readable helpers; the risk helper is a pure function with a doctest-style example, which is the right shape for unit testing.
- **What to borrow**:
  - **The canonical #675 shape, already in a popular framework**: risk-based quantity, notional cap at 100% of capital as the backstop. `computeSizing` already has both legs; #675 is mostly re-parameterising (`SIZING_NOTIONAL_CAP_PCT` toward 0.4-1.0) so the risk leg binds. jesse confirms 100% (no leverage) is a mainstream cap value; our `config.ts` upper bound of `1.0` matches.
  - **Fee haircut on size** (`1 - 3 x fee_rate`) as a simpler alternative to nautilus' commission-adjusted risk budget.
- **What to avoid**: Relying on the strategy author to call the helper. In jesse nothing stops a strategy from sizing arbitrarily; our sizing must remain inside `hourly-check` with config-validated bounds, not something `decideHourly` can override.

### 5. hummingbot/hummingbot -- `https://github.com/hummingbot/hummingbot`
- **Stars / last commit / licence**: 20,643 / 2026-10-20 / Apache-2.0 (per GitHub API).
- **Stack**: Python + Cython, 40+ CEX/DEX connectors, CLI client, Strategy V2 framework (controllers + executors), Docker.
- **Strategy focus**: Market making and arbitrage historically; V2 adds directional "controllers" that spawn position executors.
- **Risk handling**:
  - **Global P&L kill switch** (`hummingbot/core/utils/kill_switch.py::ActiveKillSwitch`): polls `trading_core.calculate_profitability()` every 10 s; shuts the bot down when profitability `<= kill_switch_rate < 0` **or** `>= kill_switch_rate > 0`. Config (`hummingbot/client/config/client_config_map.py`): `kill_switch_mode` defaults to `KillSwitchDisabledMode()`; when enabled, `kill_switch_rate` defaults to `10` (percent) -- i.e. the out-of-the-box enabled value is a +10% **profit** stop, and a loss stop requires typing a negative number.
  - **Per-position triple barrier** (`hummingbot/strategy_v2/executors/position_executor/data_types.py::TripleBarrierConfig`): optional `stop_loss`, `take_profit`, `time_limit`, `trailing_stop`; stop-loss and time-limit legs are validated to be MARKET orders.
  - **Directional controller defaults** (`hummingbot/strategy_v2/controllers/directional_trading_controller_base.py`): `max_executors_per_side = 2`, `cooldown_time = 300` s, `leverage = 20`, `position_mode = HEDGE`, `stop_loss = 0.03`, `take_profit = 0.02`, `time_limit = 2700` s; capital per controller `total_amount_quote = 100` (`controller_base.py`).
  - **Drawdown stops for multi-controller scripts** (`scripts/v2_with_controllers.py`): `max_controller_drawdown_quote` and `max_global_drawdown_quote` (both `None` = off by default). Both are trailing peak-to-trough on P&L in quote currency. A controller that breaches is stopped and its unfilled executors cancelled, and it is recorded in `drawdown_exited_controllers` so the auto-restart path skips it; a global breach stops the whole application. A per-controller `manual_kill_switch` flag (`controller_base.py`, updatable at runtime) is the operator's cash-out lever.
- **How it combines strategies**: The most explicit allocation model in this survey: one script hosts many controllers, each with its own capital budget (`total_amount_quote`), its own drawdown stop, and its own manual kill switch, plus one global drawdown stop across all of them.
- **LLM/agent usage**: Not in the core repo. The README points to **Condor**, a separate "AI harness" where "LLM-powered decision-making" drives "deterministic trade execution via the Hummingbot API". That is exactly the LLM-decides pattern our invariant 2 forbids; the core bot is clean.
- **Architecture notes**: Executors own order lifecycle; controllers own signals; the orchestrator script owns cross-controller risk. Risk at three levels (position barrier, controller drawdown, global drawdown/kill switch).
- **What to borrow**:
  - **Latch-out on drawdown**: a breached controller is excluded from auto-restart (`drawdown_exited_controllers`). Our equity floor already latches `bot_config.paused=true`; if a future second signal ever lands, give each signal its own latch key rather than sharing one flag, so one rule's breach does not silently restart the other.
  - **Trailing drawdown from the running P&L peak** as a second protection alongside the fixed-baseline `EQUITY_FLOOR_PCT` in `hourly-check/logic.ts`, especially once #675 raises size: at 0.25% risk per trade, the 15% floor sits ~60 losing trades away from the baseline but a trailing limit would catch a run that first goes up and then gives it all back.
  - **Per-position time barrier** maps onto our session-close flatten (`hourly_session_close_exit`). Nothing to add; it confirms the design.
- **What to avoid**:
  - **Sign-ambiguous kill-switch threshold** whose enabled default is a profit target. Our thresholds should be one-sided, named for what they do (`..._LOSS_PCT`), and range-validated in `config.ts`.
  - `leverage = 20` and a stop wider than the target (`stop_loss 0.03` vs `take_profit 0.02`) as shipped defaults. Defaults teach users; ours stay no-leverage and R-multiple-fixed (`HOURLY_BRACKET_R_MULTIPLE = 2`).
  - Condor-style LLM decisioning (violates invariant 2).

### 6. microsoft/qlib -- `https://github.com/microsoft/qlib`
- **Stars / last commit / licence**: 49,612 / 2026-10-22 / MIT (per GitHub API).
- **Stack**: Python research platform: data layer, ML models (LightGBM, LSTM, Transformer...), backtest engine with nested executors, MLflow-style recorder.
- **Strategy focus**: Cross-sectional stock ranking (predict returns, hold top-k), mostly daily rebalancing; not a live order router.
- **Risk handling**:
  - **Capital-deployment ratio, not per-trade risk.** `BaseSignalStrategy(risk_degree=0.95)` (`qlib/contrib/strategy/signal_strategy.py`): the strategy deploys 95% of capital; `get_risk_degree()` is the documented hook for market timing ("Dynamically risk_degree will result in Market timing").
  - `TopkDropoutStrategy(topk, n_drop, hold_thresh=1, only_tradable=False, forbid_all_trade_at_limit=True)`: holds `topk` names, swaps at most `n_drop` per rebalance (turnover cap), refuses trades at limit-up/limit-down when `forbid_all_trade_at_limit`.
  - `EnhancedIndexingOptimizer(lamb=1, delta=0.2, b_dev=0.01, f_dev=None, scale_return=True, epsilon=5e-5)` (`qlib/contrib/strategy/optimizer/enhanced_indexing.py`): mean-variance with a total-turnover limit (`delta`), benchmark-deviation limit (`b_dev`) and factor-exposure limits (`f_dev`).
  - No stop-loss, no daily loss limit, no kill switch (research tool).
- **How it combines strategies**: At the **model** level, not the order level: `qlib/model/ens/ensemble.py` (`AverageEnsemble`, `RollingEnsemble`) merges predictions before a single strategy turns them into weights; `qlib/backtest/executor.py::NestedExecutor` stacks a slower portfolio strategy over a faster execution strategy.
- **LLM/agent usage**: None in qlib. README promotes **RD-Agent** (separate repo), "LLM-Based Autonomous Evolving Agents" for factor mining and model optimisation -- research-time LLM, not in an order path.
- **Architecture notes**: Strict separation of signal (model output) and strategy (weights) and executor (orders). Config-driven workflows (`qrun` YAML).
- **What to borrow**:
  - **Combine signals before sizing, not after.** If a second signal ever passes a brainstorm, the qlib/Lean pattern is: merge into one decision, then one sizer. That keeps "one decision rule" literally true (the composite is the rule) and avoids two bots competing for one account.
  - **Turnover cap as a risk control** (`n_drop`, `delta`): our `HOURLY_MAX_ENTRIES_PER_DAY` is the same idea for a single-instrument intraday bot. Keep it in the #675 review list (more size x same entry count = more daily risk).
- **What to avoid**: Treating `risk_degree` (capital deployed) as risk. It is exposure, not loss-at-stop; conflating the two is how `SIZING_NOTIONAL_CAP_PCT` ended up binding #499. RD-Agent-style LLM factor mining feeding live parameters would violate invariant 2 unless frozen through a pre-registered backtest first.

### 7. alpacahq/Momentum-Trading-Example -- `https://github.com/alpacahq/Momentum-Trading-Example`
- **Stars / last commit / licence**: 724 / 2023-10-02 / no licence file (per GitHub API; `license` is null). Stale; uses the legacy `alpaca_trade_api` SDK and Polygon streams.
- **Stack**: Single `algo.py` (396 lines), websockets for minute bars, pandas/numpy MACD.
- **Strategy focus**: Intraday momentum on US stocks priced `$2-$13` with prior-day dollar volume `> $500k`; enters on positive, rising MACD.
- **Risk handling** (all in `algo.py`):
  - `risk = 0.001` -- **0.1% of portfolio value per trade**: `shares_to_buy = portfolio_value * risk // (data.close - stop_price)`.
  - Stop from the most recent 5-minute swing low minus $0.01 (`find_stop`), falling back to `default_stop = 0.95` (5% below price). Target = entry + 3 x (entry - stop), i.e. 3R.
  - **No notional cap.** If the stop is tight, quantity can grow to any multiple of equity; there is a `shares_to_buy == 0 -> 1` bump that can push risk above 0.1%.
  - Stops and targets are **client-side**: the loop watches minute bars and submits limit sells; no bracket order.
  - Flattens every remaining position at market 15 minutes before close.
- **How it combines strategies**: No.
- **LLM/agent usage**: None.
- **Architecture notes**: Teaching example; no tests, module-level globals.
- **What to borrow**:
  - **Independent calibration point for #675**: Alpaca's own published intraday example sizes at 0.1% risk per trade, a stop at the latest swing low, and a session-close flatten -- the same shape as our hourly bot, at ~4x our current realised risk (~0.025%) and at the low end of the #675 0.1-1% range.
  - **Why the notional backstop matters**: this example shows the failure mode #675 keeps the cap for (tight stop -> unbounded notional). `computeSizing`'s `qtyCap` is the fix this example lacks.
- **What to avoid**: Client-side stops (our server-side brackets are safer); the min-1-share bump (our `qty` floor of 0 -> no trade is the right behaviour); no licence means no code reuse at all.

### 8. barter-rs/barter-rs -- `https://github.com/barter-rs/barter-rs`
- **Stars / last commit / licence**: 2,354 / 2026-08-24 / MIT (per GitHub API).
- **Stack**: Rust, async event-driven engine, Barter-Data / Barter-Execution crates, crypto venues.
- **Strategy focus**: Framework for live, paper and backtest with one engine.
- **Risk handling**:
  - `barter/src/risk/mod.rs`: `trait RiskManager { fn check(...) }` takes the strategy's generated open/cancel requests and returns four iterators: `RiskApproved<OrderRequestOpen>`, `RiskApproved<OrderRequestCancel>`, `RiskRefused<..>` (each refused request carries a reason). The provided `DefaultRiskManager` approves everything and is documented as "FOR DEMONSTRATION PURPOSES ONLY, NEVER USE FOR REAL TRADING".
  - `barter/src/risk/check/mod.rs`: composable `RiskCheck` trait with a `CheckHigherThan<T>` building block and `util::calculate_quote_notional`.
  - Example `barter/examples/engine_sync_with_risk_manager_open_order_checks.rs` sets `MAX_USDT_NOTIONAL_PER_ORDER = 50` and `MAX_MARKET_ORDER_PRICE_PERCENT_FROM_MARKET = 10%` and filters orders that exceed them.
  - Engine `TradingState` (`barter/src/engine/state/trading/mod.rs`): `Enabled` / `Disabled`. Disabled stops algorithmic order generation but **still actions commands** (open/cancel/close positions), and each state change returns a `TradingStateUpdateAudit` (previous + new state).
- **How it combines strategies**: One `AlgoStrategy` per engine; no allocator.
- **LLM/agent usage**: None.
- **Architecture notes**: The type system enforces the risk gate: execution only accepts `RiskApproved<T>`, so an order cannot bypass the risk manager by accident.
- **What to borrow**:
  - **A branded "risk-approved" type in TS.** Have the sizing/gating step in `hourly-check/logic.ts` return a `RiskApprovedOrder` branded type (constructed only after `computeSizing` + gates pass) and make the guarded `placeBracketOrder` in `supabase/functions/_shared/alpaca.ts` accept only that type. A compile-time complement to the runtime `checkGuard()` and paper-only guard, in the same defence-in-depth spirit as the #149 response.
  - **Audited trading-state changes.** Every `bot_config.paused` flip (panic, equity floor, operator) already lands in `audit_log`; barter's previous/new-state record is a reminder to keep both values in the note so a reviewer can reconstruct the transition without a second query.
  - **Disabled-but-exits-still-work semantics** match nautilus' `REDUCING`; same borrow as entry 2.
- **What to avoid**: Shipping an approve-everything default. Any new protection here should fail closed (the `HOURLY_SHORTS_ENABLED` pattern in `config.ts`).

## Cross-cutting findings

- **Risk-per-trade sizing is a helper, not a default, almost everywhere.** Only nautilus (`calculate_fixed_risk_position_size`), jesse (`risk_to_qty`) and Alpaca's momentum example compute quantity from equity x risk% / stop distance. freqtrade, hummingbot and Lean size by notional or portfolio weight unless the user writes a callback. Our `computeSizing` is already in the minority that does it properly; #675 is a parameter problem, not a missing feature.
- **"Risk leg first, notional clamp second" is the common shape.** nautilus (`hard_limit`, then `max_quantity`), jesse (`min(size, capital)`, i.e. 100% notional), freqtrade (`validate_stake_amount` clamps any custom stake to `max_stake` / available balance). Nobody uses the notional cap as the primary limiter. This supports #675's direction: the cap should only bind on unusually tight stops.
- **Costs are subtracted inside the sizer in the mature frameworks.** nautilus deducts `2 x commission_rate` of the risk budget; jesse haircuts size by `3 x fee_rate`. `computeSizing` does not. On SPY hourly stops (~0.25% of price), 1 bp/side is ~8% of 1R, so the sizing gap matters as size grows.
- **Pre-trade risk lives outside the strategy in the frameworks built for live money.** nautilus `RiskEngine`, barter `RiskManager`, Lean's risk-model stage and freqtrade's `ProtectionManager` all sit between signal and broker and can deny. Our equivalents (gates in `hourly-check/logic.ts`, `checkGuard()` + paper-only guard in `_shared/alpaca.ts`) are the same idea; the gap is that they are in-line code rather than one named stage with a `RiskRefused(reason)` output.
- **Three halt levels recur**: (a) halt new entries, exits still work (nautilus `REDUCING`, barter `Disabled`, our `paused`); (b) halt everything (nautilus `HALTED`); (c) flatten (Lean drawdown models, hummingbot global drawdown, our `panic?action=liquidate`). Ours covers (a) and (c) but (a)'s "exits still work" guarantee is implicit.
- **Latch vs auto-resume is a real split.** Lean's `MaximumDrawdownPercentPortfolio` re-arms itself after liquidating; hummingbot latches breached controllers; our equity floor latches `paused=true` and "never self-clears". Latching is the safer default and should stay.
- **Consecutive-loss / cooldown protections are standard in crypto bots and absent here.** freqtrade's `StoplossGuard` and `CooldownPeriod`, hummingbot's `cooldown_time = 300` s. We have a post-exit cooldown gate but no "N losing exits -> pause K bars" guard and no daily-loss limit. Both become more important at 4-40x the current risk per trade.
- **Default risk values in frameworks are often unsafe or degenerate.** hummingbot's enabled kill switch defaults to a +10% profit stop and 20x leverage; freqtrade's `MaxDrawdown` defaults to `max_allowed_drawdown = 0.0`; barter's default risk manager approves everything. Our `config.ts` pattern (range-validated, fail-closed, documented defaults) is stricter than every framework surveyed.
- **LLMs show up at authoring/research time, not in order paths, in the large projects** (jesse MCP, qlib RD-Agent, hummingbot's separate Condor). Condor is the one place an LLM is put in the decision seat, and it is deliberately kept out of the core repo. Consistent with invariant 2.
- **Multi-strategy combination patterns, ranked by fit with "one decision rule"**: (1) combine signals into one decision before sizing (Lean `CompositeAlphaModel` -> PCM; qlib ensembles) -- compatible if the composite is the single frozen rule; (2) one engine, several strategies, one shared risk layer (nautilus, barter) -- compatible only with a fresh spec; (3) per-strategy capital budget + per-strategy drawdown latch + global drawdown stop (hummingbot V2) -- the safest way to run genuinely separate strategies, but it is "a second decision rule" by definition and needs the brainstorm invariant 1 demands; (4) separate bots on separate accounts (freqtrade) -- simplest, but no shared risk view.

### Default risk parameters seen in the wild

Values verified in source or official docs on 2026-10-23. "Code default" = value used when the user sets nothing; "docs example" = value in the project's own example config.

| Project | Parameter | Value | Source |
|---|---|---|---|
| alpacahq/Momentum-Trading-Example | risk per trade | `0.001` (0.1% of portfolio) | `algo.py` (code) |
| alpacahq/Momentum-Trading-Example | fallback stop / target | 5% below price / 3R | `algo.py` (code) |
| jesse | notional cap in risk sizing | `min(size, capital)` (100% of capital) | `jesse/utils.py::risk_to_size` (code) |
| jesse | docstring example | 1% risk on 10,000 capital | `jesse/utils.py::risk_to_size` (docstring) |
| nautilus_trader | order submit / modify rate | 100 per 1 s each | `crates/risk/src/engine/config.rs` (code) |
| nautilus_trader | max notional per order | none (per-instrument map, empty) | `crates/risk/src/engine/config.rs` (code) |
| nautilus_trader | commission in risk budget | `2 x commission_rate x risk_money` deducted | `crates/risk/src/sizing.rs` (code) |
| freqtrade | `tradable_balance_ratio` | `0.99` | `freqtrade/config_schema/config_schema.py` (code) |
| freqtrade | `max_open_trades` | required, user-set (`-1` = unlimited) | `config_schema.py` (code) |
| freqtrade | `StoplossGuard` | code: `trade_limit 10`, lookback 60 min, stop 60 min; docs example: 4 stops in 24 candles -> 4 candles | `plugins/protections/stoploss_guard.py`, `iprotection.py`, `docs/includes/protections.md` |
| freqtrade | `MaxDrawdown` | code: `max_allowed_drawdown 0.0`, `trade_limit 1`; docs example: 20% over 48 candles (min 20 trades) -> 12 candles | `max_drawdown_protection.py`, `protections.md` |
| freqtrade | `CooldownPeriod` | docs example: 2 candles | `protections.md` |
| freqtrade | `LowProfitPairs` | docs example: < 2% over 6 candles (min 2 trades) -> 60 min | `protections.md` |
| Lean | portfolio max drawdown | 5%, non-trailing by default, re-arms after firing | `MaximumDrawdownPercentPortfolio.cs` (code) |
| Lean | per-security drawdown / trailing stop | 5% / 5% | `MaximumDrawdownPercentPerSecurity.cs`, `TrailingStopRiskManagementModel.cs` (code) |
| Lean | sector exposure cap | 20% | `MaximumSectorExposureRiskManagementModel.cs` (code) |
| Lean | free cash buffer | 0.25% of portfolio | `Common/AlgorithmSettings.cs` (code) |
| hummingbot | global kill switch | disabled; if enabled `kill_switch_rate = 10` (%) checked every 10 s | `client_config_map.py`, `core/utils/kill_switch.py` (code) |
| hummingbot | directional controller | 2 executors/side, cooldown 300 s, SL 3%, TP 2%, time limit 45 min, leverage 20 | `directional_trading_controller_base.py` (code) |
| hummingbot | controller / global drawdown | off (`None`), trailing in quote currency when set | `scripts/v2_with_controllers.py` (code) |
| qlib | capital deployed | 95% (`risk_degree`) | `signal_strategy.py` (code) |
| qlib | turnover / benchmark deviation | `delta 0.2` / `b_dev 0.01` | `enhanced_indexing.py` (code) |
| barter-rs (example) | max notional per order / max price deviation | 50 USDT / 10% from market | `examples/engine_sync_with_risk_manager_open_order_checks.rs` |
| **this repo (today)** | risk per trade / notional cap | `0.01` / `0.10` configured; ~0.025% realised (cap binds) | `_shared/config.ts`, `hourly-check/logic.ts::computeSizing` |
| **this repo (today)** | equity floor / entries per day | 15% from fixed baseline, latching / 3 | `hourly-check/logic.ts` `EQUITY_FLOOR_PCT`, `HOURLY_MAX_ENTRIES_PER_DAY` |

Takeaway for #675: the only per-trade risk value hard-coded by a surveyed project is Alpaca's 0.1%; jesse's docstring uses 1%. Both bracket the 0.1-0.25% starting point suggested in #675. No surveyed framework ships a daily-loss default; the drawdown defaults that exist (Lean 5%, freqtrade docs 20%) are illustrative.

## Roadmap pattern candidates

- **Make the risk leg bind (the #675 change itself)**: raise `SIZING_NOTIONAL_CAP_PCT` so `qtyRisk < qtyCap` at typical SPY hourly stop widths, set `SIZING_RISK_PCT` to the decided value (0.1-0.25%), keep the cap as clamp (jesse, nautilus, freqtrade pattern). Module: `_shared/config.ts`, `hourly-check/logic.ts::computeSizing`.
- **Record which sizing leg bound** (`bound_by: risk | cap`) on each entry in `hourly_scans` / `audit_log` notes (freqtrade "adjusting to max stake" log). Makes #675's acceptance criterion observable in paper.
- **Cost-adjusted risk budget** in `computeSizing` (nautilus `2 x commission_rate`, jesse `3 x fee_rate`): size on net R using a configured per-side cost bps.
- **Consecutive-loss guard** (freqtrade `StoplossGuard`): new gate next to gate 13 in `hourly-check/logic.ts`; "N losing exits within M bars -> skip entries K bars", default-OFF per the `add-or-extend-agent` recipe.
- **Daily loss limit**: "realised + unrealised P&L today <= -X% of start-of-day equity -> no new entries today" (freqtrade `MaxDrawdown` with a one-day lookback is the closest analogue; `equity_snapshots` table already exists). Latching for the session, not across days.
- **Trailing drawdown protection** from the running equity high, complementing the fixed-baseline `EQUITY_FLOOR_PCT` (Lean `isTrailing`, hummingbot `max_global_drawdown_quote`). Latching via `bot_config.paused`.
- **Explicit "reduce-only" semantics** for `paused` (nautilus `REDUCING`, barter `Disabled`): a test-pinned guarantee that bracket legs, session-close flatten and kill-switch exits still run while entries are blocked.
- **Branded `RiskApprovedOrder` type** accepted by `placeBracketOrder` in `_shared/alpaca.ts` (barter `RiskApproved<T>`): compile-time proof that sizing + gates ran.
- **Per-invocation broker-submit cap** in `_shared/alpaca.ts` (nautilus `max_order_submit` rate limit): a third mechanical layer against #149-class runaway order loops.
- **Design note only (needs brainstorm per invariant 1)**: if a second signal is ever proposed, adopt the Lean/qlib "combine before sizing" shape, or hummingbot's per-strategy budget + per-strategy latch + global drawdown, never two independent sizers on one account.
