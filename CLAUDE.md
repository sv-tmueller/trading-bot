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

# Run the position monitor manually
python3 main.py monitor

# Initialise the database (first time only)
python3 -c "from storage.init_db import init_db; init_db()"

# Run a backtest (defaults: 1 year, settings.py params)
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
