# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working in this repo

Before starting any task, check the available skills list (printed in your system-reminder context) and the contents of `.claude/skills/` for a workflow that matches the user's request. If one matches, invoke it via the Skill tool (main session) or read its `SKILL.md` directly (subagents — Read tool only). Skills hold the procedural how-tos; this file holds the standing rules and architectural invariants. Both are required reading.

Current skills relevant to engineering work:
- **`add-or-extend-agent`** — authoring or modifying `agents/*.py`, wiring new tools, writing agent tests, adding a new env-driven setting.
- **`handover`** — writing a session handover doc so a future session can resume cold.
- **`research-bundle`** — multi-agent research surveys for product-direction decisions.

## Commands

```bash
# Run all tests
python3 -m pytest

# Run a single test file
python3 -m pytest tests/test_monitor.py -v

# Run a single test
python3 -m pytest tests/test_monitor.py::test_stop_loss_triggered -v

# Run the morning scan manually
python3 main.py scan

# Dry-run scan — full agent pipeline, no orders placed or recorded
python3 main.py scan --dry-run

# Run the position monitor manually
python3 main.py monitor

# Print trailing-30d performance summary (win rate, PnL, avg R) and post to Discord
python3 main.py summary

# Initialise the database (first time only)
python3 -c "from storage.init_db import init_db; init_db()"

# Run a backtest (defaults: 3 years, settings.py params)
python3 main.py backtest

# Backtest with custom parameters
python3 main.py backtest --years 3 --rsi-lower 35 --rsi-upper 70
python3 main.py backtest --ema-fast 10 --ema-slow 30 --atr-multiplier 2.0 --rr-ratio 2.5
```

## Python version

Runtime is Python 3.9. **Every Python file must start with `from __future__ import annotations`** — this enables modern type hint syntax on 3.9. Never use `list[dict]` or `dict[str, Any]` without this import.

## Architecture

### Agent pipeline (daily)

`main.py` runs four Claude agents sequentially each morning:

```
MarketIntelligenceAgent → StrategyAgent → RiskReviewAgent → TeamLeaderAgent
```

Each agent subclasses `BaseAgent` (`agents/base.py`) which handles the full Anthropic tool-use loop, token accumulation across turns, and DB logging. Agents return plain dicts. The Team Leader is the **only agent that places orders**.

### BaseAgent pattern, tool routing

Authoring playbook (`BaseAgent` subclass contract, instance-state-for-closures rule, tool-routing `__name__` rule): see [`.claude/skills/add-or-extend-agent/SKILL.md`](.claude/skills/add-or-extend-agent/SKILL.md). Read it before adding a new agent or wiring a new tool into an existing one.

### Database

SQLite via `storage/schema.sql`. All queries use named parameters (`:key` syntax). `conn.row_factory = sqlite3.Row` is always set so rows behave like dicts. Foreign keys are enabled with `PRAGMA foreign_keys = ON`.

The `agent_logs` table tracks every agent run with input/output token counts for cost tracking. `get_daily_token_costs()` in `tools/database.py` calculates USD cost using claude-sonnet-4-6 pricing ($3/M input, $15/M output).

### Data feed

Alpaca free paper accounts require `DataFeed.IEX`. Paid live accounts use `DataFeed.SIP`. Controlled via `DATA_FEED` env var (default: `iex`). Both `tools/market_data.py` and `tools/broker.py` read `settings.DATA_FEED`.

### Notifications

`tools/notifications.py` POSTs to an n8n webhook (`N8N_WEBHOOK_URL` env var) which forwards to Discord. Uses only stdlib `urllib` — no extra dependency. Silently skips if the env var is unset or the request fails, so a notification outage never crashes the bot. Use `http://localhost:5678` not the public n8n URL (Cloudflare Access blocks unauthenticated external requests).

### Position monitor

`monitor/position_monitor.py` is **rule-based only** (no LLM). Runs hourly via cron. Checks stop-loss → take-profit → max-hold in that priority order. Imports are at module level (not inside functions) so they can be patched in tests. Each per-trade iteration in `run_monitor` is wrapped in try/except — a transient broker/network blip on one ticker fires `notify_error` and records a `hold/skipped_error` `MonitorAction`, but the loop continues so the rest of the book still gets its soft-stop check.

### Settings

`config/settings.py` validates env vars at import time and raises `ValueError` for out-of-range values. The recipe for adding a new setting (env read, validation, `.env.example`, README, opt-in/default-OFF pattern for risky changes) is in [`.claude/skills/add-or-extend-agent/SKILL.md`](.claude/skills/add-or-extend-agent/SKILL.md).

## Testing conventions

Mock idioms, fixtures, helper-function naming, and the agent-test triad (happy path / name check / JSON fallback) are documented in [`.claude/skills/add-or-extend-agent/SKILL.md`](.claude/skills/add-or-extend-agent/SKILL.md). Read it before writing or modifying agent tests.

## Key constraints

- `MAX_HOLD_DAYS`, `RISK_PER_TRADE`, `MAX_POSITIONS` are validated at startup — invalid values raise immediately
- Stop-loss priority: `stop_loss → take_profit → max_hold → hold` — order matters
- `place_market_order` validates `side` is exactly `"buy"` or `"sell"` — raises `ValueError` otherwise
- `get_current_price` returns mid-price `(bid + ask) / 2`, with fallback if either is zero
- Morning scan is idempotent: `main.py scan` sets `_scan_already_ran = True` after the first successful run and skips subsequent calls within the same process — prevents double-firing if cron overlaps
- Morning scan must run **pre-market** (cron at `25 13 * * 1-5` UTC, 5 min before NYSE open). Signals are computed on daily bars in `tools/market_data.py`; running after 13:30 UTC means the last bar is still forming and `volume_ratio` collapses to ~0, killing every entry. Yesterday's closed bar is the input; orders fill at today's open.

## Architectural invariants

**The LLM must never control risk parameters directly.** This is non-negotiable.

Specifically:
- Stop-loss and take-profit values are always calculated by `tools/risk.py` (ATR-based, deterministic). The LLM receives them as inputs — it cannot set or override them.
- Position monitor exit logic in `monitor/position_monitor.py` is rule-based only. No LLM call is made during exits.
- Portfolio guardrails (`check_portfolio_guardrails` in `tools/risk.py`) run deterministically before any order is placed. The LLM cannot bypass them.
- The order-placement path has a deterministic exposure gate inside `team_leader.place_order` that calls `tools/risk.py::check_exposure_for_new_order` against broker truth (`get_alpaca_positions`) before submission. It fails closed on broker outage and cannot be bypassed by the LLM (the gate lives in the tool implementation, not the prompt).
- Only `TeamLeaderAgent` places orders, and only with stop/target values that come from `pending_stops`/`pending_targets` — pre-approved by the risk layer.
- Stops and take-profits execute server-side via Alpaca **bracket orders** (entry + take_profit + stop_loss legs submitted in one call). The `position_monitor` soft-stop check is defense-in-depth, not the primary mechanism — exits fire regardless of monitor process or data-API reachability.
- ATR is plumbed `risk_review` → `main.py` → `team_leader` so brackets are anchored to a **fresh quote at submission**, not the LLM's stale prior-close estimate. This keeps the realised R:R within ±5% of `RR_RATIO_MIN` under typical fill drift.
- Operational kill switch: `TRADING_PAUSED=true` in `.env` halts new entries — `main.py scan` exits immediately, no agents run. The position monitor is unaffected and continues exit handling. The faster path is `python main.py panic` (see below) — same effect on `TRADING_PAUSED`, plus order cancellation and liquidation, with no LLM in the path.
- Panic CLI is the deterministic kill button: `main.py panic --cancel-orders | --liquidate --confirm | --pause` calls Alpaca and writes `.env` directly. No agents are imported, no `Anthropic()` is instantiated, no risk math runs. Audit row in `agent_logs` (`agent_name="panic"`) is written before the broker call and updated in `finally` with the per-action result, so a partial run is recoverable from the DB. `--pause` writes to `.env` anchored at the repo root, not cwd.
- `team_leader.place_order` runs the deterministic safety stack — `check_exposure_for_new_order` against broker truth, `validate_bracket_params` — in **both** the live path and `dry_run=True`. Only the broker SUBMIT and DB INSERT are skipped in dry-run. This makes `python main.py scan --dry-run` an honest smoke test: an over-cap or malformed candidate is rejected the same way it would be live, instead of being green-lit and only failing under real cron.
- Tool exceptions cannot crash the scan: `BaseAgent._handle_tool_calls` returns failures (and the unknown-tool branch) as `tool_result` blocks with `is_error: True` so the LLM can react instead of the morning pipeline aborting mid-loop.

**Any new LLM capability added to this bot must be bounded by deterministic pre/post conditions.** If you are adding a new agent or extending an existing one to make decisions that affect position sizing, entry/exit timing, or stop distances — stop and add a deterministic validation layer first.

_Rationale: LLM outputs are non-deterministic and can behave unexpectedly under novel market conditions. The deterministic rules engine is the safety net that makes the system auditable and prevents runaway losses._

## Team

The main session always acts as **Team Leader** — it orchestrates Lead, Engineer, QA, and Docs as subagents. You never need to switch sessions. See [`TEAM.md`](TEAM.md) for the full playbook.

| Tell the Team Leader | It will dispatch… |
|---|---|
| `Triage open issues` | Lead — label, prioritize, set status:ready |
| `Work on the issues` | Lead then Engineer per issue, with reviews |
| `Run QA` | QA — discover bugs, open issues |
| `Update docs` | Docs — sync README and CLAUDE.md |
