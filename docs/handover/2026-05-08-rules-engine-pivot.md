**Date:** 2026-05-08 (UTC)
**Slug:** rules-engine-pivot
**Author:** Claude Code session (claude-opus-4-7)

## 1. Sit-rep

The bot is mid-pivot from a 4-agent LLM swing trader on 12 US large-caps to a deterministic 200-DMA regime-filter rules engine on 3USL UCITS (`WSPL.DE`, EUR, Xetra) executed via IBKR. This session ran brainstorming + writing-plans + the first 5 of 17 implementation tasks of the pivot, all tracked on PR [#193](https://github.com/sv-tmueller/trading-bot/pull/193) (`spec/rules-engine-pivot`). The new bot's foundation is in place — env vars, schema migration, pure-function regime filter, backtester, IBKR broker connection layer — but no live cron path is wired yet. The remaining 12 tasks have been split into 9 GitHub issues (#194–#202) with explicit dependency markers. The 5y backtest of the new strategy on UPRO (proxy for 3USL) returned +127% / −38% max DD / 12 trades — within the spec's expected envelope.

## 2. In-flight branches & PRs

- **Branch / PR** — `spec/rules-engine-pivot` / **#193** (state: ready, but mid-pivot)
  - **Purpose** — Pivot from LLM swing trader to deterministic 200-DMA regime-filter bot on 3USL/IBKR.
  - **Status** — Spec doc + implementation plan + Tasks 1-5 merged. HEAD at `0612233`. 12 tasks remain (see §3). 121 pre-existing tests fail because Task 2's schema migration intentionally dropped tables they reference; failing tests are deleted in the cleanup bundle (#200). Do NOT mark this PR ready for merge until #194–#202 are complete.
  - **Next action** — Open #194 first (IBKR market-order placement). Once merged, #195/#196 unblock, then #197/#198/#199 can run in parallel, then #200 cleanup, then #201 docs. #202 (cron + VPS ops doc) is independent and can run any time.

- **Branch / PR** — `handover/superpowers-adoption-2026-05-07` / **#179** (state: draft) — unrelated, prior session's handover. Do not touch.

- **Branch / PR** — `docs/readme-ssh-line` / **#116** (state: ready) — unrelated, pre-existing.

- **Branch / PR** — `claude/evaluate-mql5-trading-Kt8Os` / **#93** (state: draft) — unrelated, pre-existing.

- **Local-only state quirk** — `main` is 7 commits ahead of `origin/main` because some `git merge --ff-only` commands during this session ran from `/opt/trading-bot` (main checkout) instead of the spec worktree. This is **harmless**: the same 7 commits also live on `spec/rules-engine-pivot` and are pushed there. Do **not** push local `main` — leave it diverged. The spec branch is canonical. If it bothers you, `git -C /opt/trading-bot reset --hard origin/main` cleans it up.

## 3. Open issues being worked

The 12 remaining pivot tasks were converted to 9 GitHub issues. Tasks 12-15 are bundled into #200 because their order matters (see issue body for why).

### Wave 1 — broker + notifier (parallel)

- **#194 — feat(broker): IBKR market-order placement** (Task 6) — labels: `enhancement`, `priority: medium`.
  - **What we learned** — Task 5 already wired the `_check_guard` pattern; Task 6 just needs to extend it. Engineer should be careful that the guard fires BEFORE `IB.placeOrder()` is ever called (the test for this asserts `MockIB.placeOrder.assert_not_called()` when guard is active).
  - **Next move** — Engineer subagent. Branch off current `spec/rules-engine-pivot` HEAD.

- **#195 — feat(broker): IBKR liquidate + cancel-all** (Task 7) — labels: `enhancement`, `priority: medium`.
  - **Depends on** #194 (`liquidate` wraps `place_market_order`).
  - **Next move** — After #194 merges, engineer subagent.

- **#196 — feat(notify): regime-pivot event types** (Task 8) — labels: `enhancement`, `priority: medium`.
  - **What we learned** — Parallel-safe; touches only `tools/notifications.py`. Can be developed alongside #194/#195.
  - **Next move** — Engineer subagent. Independent.

### Wave 2 — integration (parallel after Wave 1)

- **#197 — feat: daily_check.py entry point** (Task 9) — labels: `enhancement`, `priority: high`.
  - **Largest single task in the pivot** — ~150 LOC + 7 mocked-IBKR integration tests. Depends on all of Wave 1.
  - **Next move** — After #194/#195/#196 merged, dedicated engineer subagent. **Recommend its own session** because of the integration complexity.

- **#198 — feat: monitor/kill_switch.py hourly drawdown** (Task 10) — labels: `enhancement`, `priority: high`.
  - **Independent of #197** — different file, different cron entry. Can develop in parallel.
  - **Next move** — After #194/#195/#196 merged, separate engineer subagent.

- **#199 — feat(panic): migrate panic CLI to IBKR** (Task 11) — labels: `enhancement`, `priority: medium`.
  - **Independent of #197/#198** — only touches `main.py` panic block.
  - **Note** — Folds in fix for issue #192 (`_pause_trading_in_env` writing inside repo dir): anchor the `.env` write at `Path(__file__).resolve().parent`.

### Wave 3 — cleanup (sequential, single bundle)

- **#200 — chore: decommission v1.14 (Tasks 12+13+14+15 bundled)** — labels: `refactor`, `priority: medium`.
  - **MUST stay together.** If split into 4 separate issues, `main.py`'s import graph breaks mid-merge. The order is: drop obsolete settings → rewrite `main.py` modes → delete `agents/` → delete `tools/risk.py`+`broker.py`+`monitor/position_monitor.py`. Issue body explains why.
  - **Depends on** #197, #198, #199 all merged AND verified.
  - **Net effect** — codebase shrinks from ~8,000 LOC to ~2,500 LOC. The 121 pre-existing test failures resolve themselves because the failing test files are deleted.

### Wave 4 — docs

- **#201 — docs: rewrite for rules-engine architecture** (Task 16) — labels: `documentation`, `priority: low`.
  - **Depends on** #200 (so `requirements.txt` is final).

- **#202 — ops: cron migration + IBKR/VPS setup doc** (Task 17) — labels: `documentation`, `priority: medium`.
  - **INDEPENDENT** — can be opened and merged any time. Pure scripts + docs. Does not touch Python.

### Pre-existing issues NOT addressed by this pivot (out of scope)

The pivot does NOT touch issues #156–#192 (mostly pre-existing v1.14 bugs and refactors). Several will become moot when the cleanup bundle (#200) deletes the relevant code:
- #156 (record_monitor_action vs insert_monitor_action drift) — moot after #200 deletes monitor/position_monitor.py
- #158 (dead `oco_failed` flag in team_leader) — moot after #200 deletes agents/team_leader.py
- #159 (BaseAgent has no tool-use turn limit) — moot after #200 deletes agents/base.py
- #163 (pending_indicators ema_fast/ema_slow always None) — moot
- #167 (trades.shares is REAL) — moot, new `trades` schema uses INTEGER
- #169 (signals trade_id ON DELETE CASCADE) — moot, signals table dropped
- #182 (MAX_POSITIONS / DAILY_DRAWDOWN_LIMIT LLM-trusted) — moot, those vars removed
- #185 (panic --liquidate doesn't auto-pause) — addressed by #199's TRADING_PAUSED write
- #186 (daily_pnl realized vs unrealized inconsistency) — moot, helper deleted

## 4. Decisions made this session

- **Decision** — Bot becomes a deterministic rules engine; no LLM in the trading-decision path.
  - **Rationale** — The 5y backtest of the existing LLM bot returned +12.8% over 5 years vs SPY +86%. The strategy has near-zero edge after costs. LLM latency (1-10s) is also too high for sub-daily decisions. Removing the LLM eliminates an entire failure class without losing edge.
  - **Consequence** — All `agents/*.py` files will be deleted in #200. `BaseAgent` contract goes away. The `add-or-extend-agent` skill is no longer load-bearing post-pivot. **Do not retry approaches that involve LLM-driven trade decisions.** The deterministic safety stack (exposure gate, OCO brackets) gets a simplified replacement (`tools/ibkr_broker.py` plus the `regime_state.kill_switch_active` flag).

- **Decision** — Vehicle is **3USL** (`WSPL.DE`, WisdomTree S&P 500 3× Daily Leveraged UCITS, Xetra, EUR), not UPRO directly.
  - **Rationale** — UPRO is US-listed; under PRIIPs/MiFID II, EU retail can't buy it without IBKR Professional Client status (€500k portfolio threshold). 3USL is UCITS, EUR-native, retail-accessible. Trade-off accepted: no Teilfreistellung (worse DE tax, ~26% Abgeltungsteuer on full gain) + ETN structure (counterparty risk to WisdomTree's swap counterparty).
  - **Consequence** — `BOT_TICKER=WSPL.DE` is the default in `config/settings.py`. The `.split(".")[0]` symbol-stripping logic in `tools/ibkr_broker.get_position` is documented as **only safe for venue-suffixed UCITS or single-class US tickers** — would conflate `BRK.B` with `BRK.A` if the universe expands. Latent for now.

- **Decision** — Re-entry after kill-switch fires has **no time delay** — bot re-enters as soon as `SPY > SMA(200)`.
  - **Rationale** — User preference. Simpler rule. The risk (re-buying a falling knife after intraday recovery) is mitigated by the fact that real crashes also push SPY below 200-DMA, so the regime filter holds the bot in cash.
  - **Consequence** — `compute_target_state` clears `kill_switch_active` flag whenever `SPY > SMA(200)`, regardless of how recently the kill-switch fired. Tests in `tests/test_strategy_regime.py` lock this in.

- **Decision** — DB-vs-IBKR state desync is **auto-reconciled**, not fail-fast.
  - **Rationale** — User preference for self-healing. If user manually closes a position via IBKR UI, the bot's next daily_check picks it up and continues normally.
  - **Consequence** — `daily_check.py` reads `ibkr.get_position` after computing the regime decision and updates DB to match before deciding whether to flip. Notifies Discord on desync but does not halt.

- **Decision** — Tasks 12-15 are **bundled into a single issue (#200)**, not split.
  - **Rationale** — Splitting opens a broken-build window: Task 13 deleting `agents/` while `main.py` still imports them would fail to load. Task 15 must rewrite `main.py` modes BEFORE deletions land.
  - **Consequence** — One large engineer dispatch executes all 4 sub-tasks sequentially in correct order. Two-stage review on the final state.

- **Decision** — Old DB data (trades, agent_logs, signals) is **NOT migrated** by Task 2's schema rewrite.
  - **Rationale** — Schemas are incompatible (different fields, different reason taxonomies). Old `trades` rows have `entry_price`/`stop_loss`/`take_profit`/`r_multiple`; new `trades` has `fill_price`/`reason`/`ibkr_order_id`. The data isn't worth a complex transform.
  - **Consequence** — Live `trading_bot.db` on the VPS will lose its history at cutover. Operator should snapshot/archive the old DB before running `init_db()` on the new schema.

## 5. Open questions

- **Question** — Does yfinance have enough 3USL price history (`WSPL.DE`) to run the regime backtest directly, or do we need to keep using UPRO as a proxy?
  - **What blocks the answer** — Need to actually fetch `WSPL.DE` from yfinance and check the start date. WisdomTree launched 3USL ~2014 in Europe; yfinance coverage may start later.
  - **Suggested next step** — During #198 (kill_switch implementation), engineer can run `yf.download("WSPL.DE", period="max")` and confirm. If insufficient, document the UPRO-as-proxy approach in `backtest/regime.py` docstring.

- **Question** — What's IBKR's Tiered commission per Xetra order on 3USL? Plan estimates ~€1.25 minimum + 0.05%, total <€10/year on 4-8 trades — but unverified.
  - **What blocks the answer** — Live IBKR account opened + a paper trade observed.
  - **Suggested next step** — Operator opens IBKR paper account first (this is a Task 9 prerequisite anyway). After first paper trade, check `Trade.commissionReport.commission` for actual fee. Add to docs if material.

- **Question** — Should TWS run as systemd `ibgateway.service` or via a tmux session?
  - **What blocks the answer** — User preference + operator comfort.
  - **Suggested next step** — Issue #202 documents the systemd path; user can decide otherwise during VPS setup. Either works.

- **Question** — Does `BOT_TICKER == BOT_BENCHMARK` need an explicit cross-check in `config/settings.py`?
  - **What blocks the answer** — A typo'd `BOT_TICKER=SPY` would make the regime filter compare the asset against itself (always-bullish). Pass-2 reviewer flagged this as nice-to-have for #196's notification or for `daily_check.py`.
  - **Suggested next step** — Add the check in #197 (daily_check) implementation as a one-line ValueError raise at module load.

## 6. Files to read first

- `docs/superpowers/specs/2026-05-07-rules-engine-pivot-design.md` — the canonical design spec for the entire pivot. Read this first before touching any pivot code.
- `docs/superpowers/plans/2026-05-07-rules-engine-pivot.md` — the 17-task implementation plan with full TDD steps, test code, and exact commands for each task. The 9 GitHub issues all reference specific Task N sections of this file.
- `tools/ibkr_broker.py:1-95` — current state of the IBKR broker module after Tasks 5. The pattern (`_check_guard()` first, then `IB()` instantiation) is what every new helper in #194/#195 must follow.
- `strategy/regime.py:1-60` — the entire trading decision in one pure function. Tests at `tests/test_strategy_regime.py` lock in 21 cases including the truth table.
- `backtest/regime.py:1-200` — new regime backtester. Run `python3 backtest/regime.py --benchmark SPY --vehicle UPRO --years 5 --sma 200` to validate.
- `storage/schema.sql` and `storage/migrations/2026_05_07_rules_engine_pivot.sql` — new schema (post-pivot 3-table design).
- `config/settings.py:101-128` — new env vars (`IBKR_*`, `BOT_TICKER`, `BOT_BENCHMARK`, `REGIME_SMA_DAYS`, `KILL_SWITCH_*`). Old vars still present (Task 12 removes them in #200).
- `CLAUDE.md` — architectural invariants, especially the `CLAUDE_AGENT_NO_BROKER` guard rule. **The guard is preserved across the pivot** and now applies to `tools/ibkr_broker.py`.
- `TEAM.md` — team workflow with the superpowers skills wired in. Engineer / spec-reviewer / code-quality-reviewer subagents are the canonical dispatch path.

## 7. Don't forget

Pivot-specific gotchas (above the standing list):

- **`spec/rules-engine-pivot` is the trunk for this work, NOT `main`.** All 9 issues (#194–#202) target that branch. Do not merge to `main` until PR #193 is green and the user explicitly authorises.
- **The `CLAUDE_AGENT_NO_BROKER` guard is the safety net.** Every IBKR helper in `tools/ibkr_broker.py` MUST call `_check_guard()` BEFORE any `IB()` instantiation or network call. Tests must assert `MockIB.placeOrder.assert_not_called()` (not just that the exception was raised). This is the lesson from incidents #149 and #168.
- **Engineer subagents inherit `/opt/trading-bot/.env`** which currently still has Alpaca credentials. The autouse `CLAUDE_AGENT_NO_BROKER=true` conftest fixture protects against accidental Alpaca calls during tests, but **do not run `python main.py scan` from a per-task worktree** — it would still try to reach Alpaca until #200 deletes that path.
- **Mid-pivot test failures (~121) are expected** until #200 lands. Treat focused suites (`test_storage.py`, `test_strategy_regime.py`, `test_backtest_regime.py`, `test_tools_ibkr_broker.py`, `test_config.py`) as the green-bar reference for individual task PRs.
- **Don't merge cleanup before integration.** #200 must come AFTER #197/#198/#199 are merged AND a paper-account smoke test confirms the new path works. Premature deletion would brick the bot.
- **Tasks 6, 7 must be sequential** (same file, build on each other). Tasks 8, 9, 10, 11 can be parallel after Wave 1 is done. See §3 above for the dependency map.

Standing repo invariants — restated because several apply to upcoming work:

- The LLM must never control risk parameters directly. Stops, targets, exposure caps come from deterministic code; only `TeamLeaderAgent` placed orders pre-pivot, and post-pivot the order-placement path is `daily_check.py` (rule-based, no LLM). This invariant is **trivially satisfied** post-pivot because there is no LLM at all in the trading path.
- ~~Stops and take-profits execute server-side via Alpaca bracket orders.~~ **Pivot replaces this:** the new bot uses single market orders into 3USL (LONG) or out (CASH), with the 30-trading-day drawdown kill-switch as defense-in-depth.
- ~~Morning scan must run pre-market (cron `25 13 * * 1-5` UTC).~~ **Pivot replaces this:** new cron is `30 22 * * 1-5` UTC (post-US-close, ≥1.5h after) for `daily_check.py` plus `5 14-21 * * 1-5` UTC for hourly `monitor/kill_switch.py`. See #202.
- `TRADING_PAUSED=true` halts new entries but does not affect the kill-switch monitor. Preserved across the pivot.
- ~~Free Alpaca paper accounts require `DataFeed.IEX`.~~ **Pivot replaces this:** Alpaca is removed entirely. IBKR uses TWS / IB Gateway on port 4002 (paper) / 4001 (live). The `DATA_FEED` env var becomes vestigial (yfinance is the data source for `daily_check`).
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime).

## 8. Suggested next prompts

In priority order — paste the first one if you only have time for one thing.

1. **`Work on issue #194`** — IBKR market-order placement. This unblocks #195/#197/#198/#199. Start here. The Team Leader (you) brainstorms-then-dispatches engineer; engineer reads Task 6 in the plan; two-stage review; fast-forward into `spec/rules-engine-pivot`.

2. **`Work on issue #196 in parallel with #194`** — Notifier event types. Independent of #194/#195, can run alongside them. Especially useful if you want to start a second session and parallelise the broker work and the notifier work.

3. **`Work on issue #202`** — Cron migration + IBKR/VPS ops doc. Pure docs, blocked on nothing, can be merged any time. Useful for a session where you don't want to touch Python.

4. **`Work on issue #197`** — Once #194, #195, #196 are merged. This is the largest task (`daily_check.py`), the integration point for the whole new bot. Recommend its own dedicated session — engineer subagent will need full plan-Task-9 context.

5. **`Run QA on PR #193`** — After all 9 issues land, run a QA sweep against the rules-engine bot before flipping the cron and the IBKR account from paper to live. Look for: regime-flip race conditions, kill-switch escalation paths, idempotency on duplicate cron fires, Discord delivery on each event type.
