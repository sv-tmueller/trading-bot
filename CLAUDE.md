# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

### BaseAgent pattern

Subclasses must implement three methods:
- `get_tools()` — Anthropic tool definitions (JSON schema)
- `_get_tool_functions()` — callables matching those tool names; use **deferred imports** inside this method so tools can be monkeypatched in tests
- `parse_output(response)` — extract dict from Claude's text response, always include a JSON fallback

Instance state used by tool closures (e.g. `self._conn`) must be:
1. Initialised to `None` in `__init__`
2. Set in `run()` before calling `super().run()`
3. Captured as a local variable before defining closures: `conn = self._conn`

### Tool routing

`_handle_tool_calls` routes by `fn.__name__`. If you import a function and wrap it under a different name, set `wrapper.__name__ = "tool_name"` to match the tool definition, or import with an alias and name the inner function correctly.

### Database

SQLite via `storage/schema.sql`. All queries use named parameters (`:key` syntax). `conn.row_factory = sqlite3.Row` is always set so rows behave like dicts. Foreign keys are enabled with `PRAGMA foreign_keys = ON`.

The `agent_logs` table tracks every agent run with input/output token counts for cost tracking. `get_daily_token_costs()` in `tools/database.py` calculates USD cost using claude-sonnet-4-6 pricing ($3/M input, $15/M output).

### Data feed

Alpaca free paper accounts require `DataFeed.IEX`. Paid live accounts use `DataFeed.SIP`. Controlled via `DATA_FEED` env var (default: `iex`). Both `tools/market_data.py` and `tools/broker.py` read `settings.DATA_FEED`.

### Notifications

`tools/notifications.py` POSTs to an n8n webhook (`N8N_WEBHOOK_URL` env var) which forwards to Discord. Uses only stdlib `urllib` — no extra dependency. Silently skips if the env var is unset or the request fails, so a notification outage never crashes the bot. Use `http://localhost:5678` not the public n8n URL (Cloudflare Access blocks unauthenticated external requests).

### Position monitor

`monitor/position_monitor.py` is **rule-based only** (no LLM). Runs hourly via cron. Checks stop-loss → take-profit → max-hold in that priority order. Imports are at module level (not inside functions) so they can be patched in tests.

### Settings

`config/settings.py` validates env vars at import time and raises `ValueError` for out-of-range values. Adding a new setting: add `os.getenv()` call with a safe default, add validation if needed, document in `.env.example` and README.

## Testing conventions

- Tests use an in-memory SQLite DB via the `db_conn` fixture in `tests/conftest.py`
- Mock Anthropic with `patch("agents.base.anthropic.Anthropic", return_value=mock_client)`
- Mock broker calls with `patch("tools.broker.place_market_order", ...)` etc.
- Helper function for mock responses must be named `make_mock_claude_response`
- All agent tests cover: happy path (with value assertions), name check, JSON fallback path
- `stop_reason = "end_turn"` in mocks — tool-use loop is not exercised in unit tests

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
- Operational kill switch: `TRADING_PAUSED=true` in `.env` halts new entries — `main.py scan` exits immediately, no agents run. The position monitor is unaffected and continues exit handling.

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
