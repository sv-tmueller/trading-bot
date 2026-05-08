# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working in this repo

Before starting any task, check the available skills list (printed in your system-reminder context) and the contents of `.claude/skills/` for a workflow that matches the user's request. If one matches, invoke it via the Skill tool (main session) or read its `SKILL.md` directly (subagents — Read tool only). Skills hold the procedural how-tos; this file holds the standing rules and architectural invariants. Both are required reading.

Current skills relevant to engineering work:
- **`add-or-extend-agent`** — recipe for adding a new env-driven setting (env read, validation, `.env.example`, README, opt-in/default-OFF pattern). The historical "agent" content (BaseAgent contract, tool routing) is no longer applicable post-2026-05-07 pivot but the settings recipe is still canonical.
- **`handover`** — writing a session handover doc so a future session can resume cold.
- **`research-bundle`** — multi-agent research surveys for product-direction decisions.

## Superpowers skills are the canonical playbooks

This project uses the [`superpowers`](https://github.com/obra/superpowers) plugin (installed via `/plugin install superpowers@claude-plugins-official`). Where a `superpowers:` skill exists for a workflow, **it is the canonical playbook for this project**. The skills below are wired into the agents listed in [`TEAM.md`](TEAM.md).

| Workflow | Skill | Wired into |
|---|---|---|
| Brainstorming a change (every change — HARD-GATE) | `superpowers:brainstorming` | Team Leader (main session) |
| Writing an implementation plan | `superpowers:writing-plans` | Team Leader. Plans live in `docs/plans/<date>-<slug>-plan.md`. |
| Executing a plan task-by-task | `superpowers:subagent-driven-development` | Team Leader. Dispatches engineer (implementer) + spec-reviewer + code-quality-reviewer per task. |
| Implementing a single task | _(implementer prompt)_ | `engineer` subagent ([`.claude/agents/engineer.md`](.claude/agents/engineer.md)) |
| Pass-1 review (spec compliance) | _(spec-reviewer prompt)_ | `spec-reviewer` subagent ([`.claude/agents/spec-reviewer.md`](.claude/agents/spec-reviewer.md)) |
| Pass-2 review (quality + architectural invariants) | _(code-quality-reviewer prompt — quotes the architectural invariants verbatim)_ | `code-quality-reviewer` subagent ([`.claude/agents/code-quality-reviewer.md`](.claude/agents/code-quality-reviewer.md)) |
| Test-driven discipline | `superpowers:test-driven-development` (see also `testing-anti-patterns.md` inside that skill's directory — sibling reference, not a standalone skill) | engineer (referenced from `.claude/agents/engineer.md`) |
| Root-cause-first debugging | `superpowers:systematic-debugging` | qa (failed-test triage); engineer (general debugging) |
| Verifying claims before completion | `superpowers:verification-before-completion` | lead (merge gate); engineer (self-review) |
| Receiving review feedback | `superpowers:receiving-code-review` | engineer |
| Wrapping up a branch | `superpowers:finishing-a-development-branch` | Team Leader (before dispatching lead for merge) |
| Worktree-per-task isolation | `superpowers:using-git-worktrees` | All agents (reinforces the existing "always use worktrees" rule). |

The three trading-bot-specific skills (`add-or-extend-agent`, `handover`, `research-bundle`) sit alongside the superpowers skills — they cover work the superpowers library does not.

**Where superpowers conflicts with older inline guidance in `CLAUDE.md` or in agent `.md` files, the superpowers playbook wins.** The architectural-invariants section below remains authoritative for the safety stack — it is preserved verbatim in `code-quality-reviewer.md` and is non-negotiable.

**Subagents do not have the `Skill` tool.** They access skill content via `Read` on the SKILL.md file. To find a SKILL.md path: `find ~/.claude/plugins -name SKILL.md -path "*<skill-name>*"`.

## Commands

```bash
# Run all tests
python3 -m pytest

# Run a single test file
python3 -m pytest tests/test_daily_check.py -v

# Run a single test
python3 -m pytest tests/test_daily_check.py::test_bullish_first_run_buys -v

# Run today's regime check + flip (cron does this automatically at 22:30 UTC)
venv/bin/python daily_check.py
venv/bin/python daily_check.py --dry-run    # full pipeline, no broker orders

# Hourly drawdown check (cron does this automatically during US market hours)
venv/bin/python -m monitor.kill_switch

# Backtest the regime strategy
venv/bin/python main.py backtest --years 5

# Trailing 30-day trade summary
venv/bin/python main.py summary

# Kill button (deterministic, no LLM)
venv/bin/python main.py panic --pause
venv/bin/python main.py panic --cancel-orders
venv/bin/python main.py panic --liquidate --confirm

# Initialise the database (first time only)
python3 -c "from storage.init_db import init_db; init_db()"
```

## Python version

Runtime is Python 3.9. **Every Python file must start with `from __future__ import annotations`** — this enables modern type hint syntax on 3.9. Never use `list[dict]` or `dict[str, Any]` without this import.

## Architecture

### Daily flow

`daily_check.py` runs once per weekday (cron, post-US-close). It computes the 200-DMA regime
filter on SPY, reconciles with IBKR, and flips between LONG (`BOT_TICKER`) and CASH if needed.
Wraps the entire flow in an `audit_log` row; every exit path writes a deterministic `outcome`
string (`success`, `dry_run:*`, `skipped:*`, `error:*`).

### Hourly kill-switch

`monitor/kill_switch.py` runs hourly during US market hours. If `BOT_TICKER` drawdown from its
30-trading-day rolling high exceeds `KILL_SWITCH_DRAWDOWN_PCT`, it liquidates and sets
`kill_switch_active=1` in `regime_state`.

### Database

SQLite via `storage/schema.sql`. All queries use named parameters (`:key` syntax). `conn.row_factory = sqlite3.Row` is always set so rows behave like dicts. Foreign keys are enabled with `PRAGMA foreign_keys = ON`.

The post-pivot tables are:
- `regime_state` — one row per trading day with `spy_close`, `spy_sma200`, `target_state`, `current_state`, `position_drawdown_pct`, `kill_switch_active`, `kill_switch_fired_at`.
- `trades` — broker fills (`symbol`, `side`, `qty`, `fill_price`, `fill_time`, `ibkr_order_id`, `reason`).
- `audit_log` — one row per script invocation (`script_name`, `started_at`, `finished_at`, `outcome`, `notes`). Used for forensics and partial-recovery — `outcome` is written before exit so a crashed run leaves a row with no `finished_at`.

### Notifications

`tools/notifications.py` POSTs to an n8n webhook (`N8N_WEBHOOK_URL` env var) which forwards to Discord. Uses only stdlib `urllib` — no extra dependency. Silently skips if the env var is unset or the request fails, so a notification outage never crashes the bot. Use `http://localhost:5678` not the public n8n URL (Cloudflare Access blocks unauthenticated external requests).

The post-pivot helpers post structured JSON dicts (`event_type` + event-specific fields) so the n8n flow can route on shape: `notify_regime_flip`, `notify_kill_switch_fired`, `notify_trade_failed`, `notify_tws_disconnected`, `notify_state_desync`. The string-payload helpers `notify_error` (used by panic + daily_check generic-exception) and `notify_panic` are also kept.

### Settings

`config/settings.py` validates env vars at import time and raises `ValueError` for out-of-range values. The recipe for adding a new setting (env read, validation, `.env.example`, README, opt-in/default-OFF pattern for risky changes) is in [`.claude/skills/add-or-extend-agent/SKILL.md`](.claude/skills/add-or-extend-agent/SKILL.md).

## Testing conventions

Mock idioms and broker-call mocking patterns: `tools/ibkr_broker.py` submission helpers (`connect_ibkr`, `place_market_order`, `liquidate`, `cancel_all_orders`, `get_position`, `get_account_value`) MUST be mocked in any test that exercises a path which would call them. The `CLAUDE_AGENT_NO_BROKER` autouse conftest fixture (`tests/conftest.py`) sets the env var so every helper raises `BrokerCallBlockedError` before any IBKR call — this is the mechanical safety net, but tests should still mock cleanly so the assertions are meaningful.

Patch at the module path the caller imports from. Example: `daily_check.py` does `from tools.ibkr_broker import place_market_order`, so tests patch `daily_check.place_market_order`, not `tools.ibkr_broker.place_market_order`.

## Key constraints

- `IBKR_PORT`, `IBKR_CLIENT_ID`, `REGIME_SMA_DAYS`, `KILL_SWITCH_DRAWDOWN_PCT`, `KILL_SWITCH_LOOKBACK_DAYS`, `BOT_TICKER`, `BOT_BENCHMARK` are validated at startup — invalid values raise immediately.
- `daily_check.py` must run **post-US-close** (cron at `30 22 * * 1-5` UTC, ~5h after NYSE close, 1.5h after yfinance daily bar publishes). Running before yfinance has the closed bar will hit the stale-data guard and exit with `skipped:stale_data` in audit_log.
- `daily_check.py` is idempotent: re-running on the same trading day computes the same `target_state`, sees `current_state` already matches, and writes a no-op `regime_state` row.
- The bot has one decision rule. It is testable as a pure function (`strategy.regime.compute_target_state`). Do not add second decision rules without a fresh brainstorm and spec.
- `daily_check.py` honors `TRADING_PAUSED` — `python main.py panic --pause` is the operational kill switch.

## Architectural invariants

- **One decision rule.** The bot trades on exactly one signal: SPY close vs SPY 200-DMA, modulated by the kill-switch flag. The signal is computed by a pure function (`strategy.regime.compute_target_state`) so every decision is reproducible from the SPY history alone. Do not add a second decision rule (sentiment overlay, sector tilt, etc.) without a fresh brainstorm and design spec — the rules-engine pivot exists precisely because the LLM-driven multi-signal v1.14 bot was indistinguishable from a coin flip on 5y data.
- **No LLM in the trading path.** `daily_check.py` and `monitor/kill_switch.py` import nothing from `anthropic` and do not instantiate any agent. The only Claude session in the repo is the operator's interactive Team Leader for development work — it never executes orders.
- **Operational kill switch.** `TRADING_PAUSED=true` in `.env` halts new entries — `daily_check.py` writes `skipped:trading_paused` to `audit_log` and exits 0 without contacting IBKR. The kill-switch monitor is unaffected and continues exit handling. The faster path is `python main.py panic --pause` — same effect on `TRADING_PAUSED`, plus order cancellation and liquidation in one invocation.
- **Panic CLI is the deterministic kill button.** `main.py panic --cancel-orders | --liquidate --confirm | --pause` calls IBKR and writes `.env` directly. No LLM is imported in this path. Audit row in `audit_log` (`script_name="panic"`) is written before the broker call and updated in `finally` with the per-action result, so a partial run is recoverable from the DB. `--pause` writes to `.env` anchored at the repo root via `Path(__file__).resolve().parent`, not cwd.
- **Engineer subagents must never execute against the live broker.** Subagents spawn into worktrees that inherit `/opt/trading-bot/.env` via the parent shell, so any `pytest`, ad-hoc `python -c`, or `python daily_check.py` invocation would submit real orders to the live account. Every `tools/ibkr_broker.py` submission helper — `connect_ibkr`, `place_market_order`, `liquidate`, `cancel_all_orders`, `get_position`, `get_account_value` — MUST be mocked in agent-spawned tests (patch at the module path the caller imports from). Integration tests that need a real broker must use a separate sandbox account with explicitly-set env vars, or be explicitly skipped in agent contexts. **Mechanically enforced via the `CLAUDE_AGENT_NO_BROKER` env var (#168) — when set, all submission helpers raise `BrokerCallBlockedError` before any IBKR call. Production cron leaves the var unset; pytest sets it via an autouse conftest fixture so any forgotten mock fails fast instead of materialising a live order.** _Rationale: 2026-05-06 incident #149 — six SIMPLE-class market BUY orders for AMD ×4, GOOG, MSFT were submitted from an Engineer worktree at 05:56-05:57 UTC, draining buying power from $99k to $2,239 and leaving positions that would have filled unprotected at market open if not surgically cancelled. Re-materialised ~30 minutes after issue #168 was filed when a QA subagent's `pytest` reached live broker via an unmocked path and submitted 5×100 AMD parent BUYs (500-share, $-101k margin position; recovered via panic CLI). The production cron path was unaffected in both incidents; the gap was on the agent-test side and is now closed by the mechanical guard plus the docs/skill rule (defense-in-depth)._ The rule applies post-pivot to `tools/ibkr_broker.py` exactly as it applied pre-pivot to `tools/broker.py`.

_Rationale: deterministic rules engines are auditable; LLM outputs are not. The v1.14 incident history showed that even with deterministic guardrails wrapped around an LLM, the LLM's non-determinism leaked through at the points where it set sizes, picked instruments, or narrated outcomes. The post-pivot bot has none of that surface area — there is no decision the LLM can corrupt because there is no LLM in the path._

## Team

The main session always acts as **Team Leader** — it orchestrates the specialist subagents listed in [`TEAM.md`](TEAM.md). You never need to switch sessions. See [`TEAM.md`](TEAM.md) for the full playbook.

| Tell the Team Leader | It will dispatch... |
|---|---|
| `Triage open issues` | Lead — label, prioritize, set `status: ready` |
| `Work on issue #N` | Brainstorm -> plan -> engineer + spec-reviewer + code-quality-reviewer per task -> lead merges |
| `Run QA` | QA — discover bugs, open issues (with `superpowers:systematic-debugging` triage) |
| `Update docs` | Docs — sync README, CLAUDE.md, CURRENT_CONFIG |
