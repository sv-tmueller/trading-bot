---
name: add-or-extend-agent
description: Use this skill when authoring or modifying code under `agents/*.py`, adding a new agent to the daily pipeline, wiring a new tool into an existing agent, writing tests for an agent, or adding a new env-driven setting in `config/settings.py`. Captures the BaseAgent subclass contract, the tool-routing `__name__` rule, the agent-test triad (happy path / name check / JSON fallback), and the "add a new setting" recipe. Triggers include "add a new agent", "extend the X agent", "wire a new tool into agent Y", "write tests for agent Z", "add a new env-driven setting", or any work that edits `agents/base.py` or its subclasses.
---

# Add or Extend an Agent

Procedural playbook for authoring or modifying agents in this trading bot. Pure how-to — every rule below has been the source of a real bug at least once.

This skill is **dual-purpose**: the main session invokes it via the Skill tool; the `engineer` subagent reads it via the `Read` tool when its issue touches `agents/*.py`. Same content, two consumption paths.

## When this skill applies

- Adding a new agent to the pipeline (`MarketIntelligenceAgent → StrategyAgent → RiskReviewAgent → TeamLeaderAgent`).
- Extending an existing agent with a new tool, prompt change, or output field.
- Adding a new env-driven setting in `config/settings.py` (often paired with the above).
- Writing or updating tests for any agent.

If the work is purely tool-side (`tools/*.py`, no `agents/` change), this skill is overkill — read `CLAUDE.md` and write the tool. The skill kicks in once the new tool is going to be wired into an agent's tool list.

## BaseAgent subclass contract

Every agent inherits from `BaseAgent` (`agents/base.py`). Subclasses must implement exactly three methods:

- **`get_tools()`** — returns the list of Anthropic tool definitions (JSON schema). One entry per tool the agent can call.
- **`_get_tool_functions()`** — returns a `dict[str, callable]` whose keys match the tool `name` fields from `get_tools()`. **Use deferred imports inside this method** so the underlying functions can be monkeypatched in tests:

  ```python
  def _get_tool_functions(self):
      from tools.market_data import compute_ticker_signals
      from tools.risk import atr_stop
      return {
          "compute_ticker_signals": compute_ticker_signals,
          "atr_stop": atr_stop,
      }
  ```

- **`parse_output(response)`** — extracts the agent's structured dict from Claude's text response. **Always include a JSON fallback** for the case where Claude does not produce the expected envelope; tests assert on this path explicitly.

## Instance state used by tool closures

This is the rule that has caused the most subtle bugs. If your agent's tools need access to instance state (e.g. `self._conn`, `self._candidates`), follow this exact three-step pattern:

1. **Initialise to `None` in `__init__`** — declares the slot, makes the absence visible.
2. **Set in `run()` before calling `super().run()`** — populates the slot for the current run.
3. **Capture as a local variable before defining closures** — `conn = self._conn` then close over `conn`, never over `self`.

```python
class StrategyAgent(BaseAgent):
    def __init__(self, ...):
        super().__init__(...)
        self._conn = None  # step 1

    def run(self, conn, ...):
        self._conn = conn  # step 2
        return super().run(...)

    def _get_tool_functions(self):
        conn = self._conn  # step 3 — local capture
        def fetch_candidates():
            return conn.execute("SELECT ...").fetchall()
        return {"fetch_candidates": fetch_candidates}
```

Skipping step 3 (closing over `self` instead of `conn`) makes the closure see whatever `self._conn` is at call time, which breaks tests that swap connections per-test and silently passes when the prior run's state happens to still be valid.

## Tool routing — the `__name__` rule

`BaseAgent._handle_tool_calls` routes incoming tool calls by `fn.__name__`. The string in `get_tools()[i]["name"]` must equal the `__name__` of the callable returned by `_get_tool_functions()`.

If you import a function and wrap it under a different name, set `wrapper.__name__` to match the tool definition:

```python
def _get_tool_functions(self):
    from tools.market_data import compute_ticker_signals as _cts
    def compute_ticker_signals(*args, **kwargs):  # local rename for clarity
        return _cts(*args, **kwargs)
    compute_ticker_signals.__name__ = "compute_ticker_signals"  # explicit
    return {"compute_ticker_signals": compute_ticker_signals}
```

The cleanest form is to import the function under its target name (no wrapper) so `__name__` is correct by construction. Reach for the explicit `__name__ =` assignment only when the wrapper genuinely needs to exist (e.g. for adding logging or a guard).

## Adding a new env-driven setting

Required when the agent needs a tunable parameter or feature flag. Recipe:

1. **Read in `config/settings.py`:**
   ```python
   NEW_SETTING = float(os.getenv("NEW_SETTING", "0.5"))
   ```
2. **Validate at import time** if the setting has bounds. Raise `ValueError` for out-of-range values:
   ```python
   if not 0.0 <= NEW_SETTING <= 1.0:
       raise ValueError(f"NEW_SETTING must be in [0, 1], got {NEW_SETTING}")
   ```
3. **Document in `.env.example`** with a brief inline comment.
4. **Document in `README.md`** (Settings or Configuration section) — what the setting does, default, valid range.
5. **Risky changes use the opt-in / default-OFF pattern.** Anything touching risk parameters, position sizing, or live-trading behaviour must default to disabled (`0`, `false`, or empty string) and be gated on the flag. Recent precedents: `TRADING_PAUSED`, `DAILY_DRAWDOWN_LIMIT` (`0` = disabled), trailing stop (#91), earnings blackout (#92).

## Testing conventions

Every agent test file lives under `tests/test_agents/` and follows these idioms.

### Hard rule — never execute against the live Alpaca paper account (incident #149)

Engineer subagents inherit `/opt/trading-bot/.env` via the parent shell. Any `python -c` or `python main.py scan` invocation from a worktree submits real orders to the live paper account. **`pytest` is now backstopped by the `CLAUDE_AGENT_NO_BROKER` mechanical guard (PR #168) — the autouse conftest fixture sets it for the test session and any unmocked call raises `BrokerCallBlockedError` before reaching Alpaca.** All `tools/broker.py` submission helpers (`place_market_order`, `place_parent_market_order`, `place_oco_brackets`, `cancel_all_orders`, `liquidate_all_positions`) MUST be mocked. If you need to verify against a real broker, use a separate sandbox account with explicitly-set env vars, NOT the inherited live keys. Team Leader briefs for any task touching `tools/broker.py`, `agents/team_leader.py::place_order`, or anything that calls them must restate this rule.

_2026-05-06: six SIMPLE-class market BUY orders for AMD ×4, GOOG, MSFT escaped from an Engineer worktree, draining buying power from $99k to $2,239. Surgically cancelled before market open. See issue #149 and the architectural invariant in `CLAUDE.md`._

**`BrokerCallBlockedError` is a debugging signal, not a bug to silence.** When a test raises `BrokerCallBlockedError`, the mechanical guard caught a missing mock — add the mock at the module path the caller imports from (typical patterns shown under "Fixtures and mocks" below). Do NOT unset `CLAUDE_AGENT_NO_BROKER` or set it to empty to make the failure go away; that defeats the safety net.

### Fixtures and mocks

- **In-memory SQLite via `db_conn`** — defined in `tests/conftest.py`. Always use this; never touch a real DB.
- **Mock Anthropic** with the import path patch:
  ```python
  with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
      ...
  ```
- **Mock broker calls** at the module path the agent imports from — typically:
  ```python
  patch("tools.broker.place_market_order", ...)
  patch("tools.broker.get_alpaca_positions", ...)
  ```
- **Mock response helper** — the helper that constructs a fake Anthropic response **must be named `make_mock_claude_response`**. Tests across the suite import this name; renaming breaks the convention.

### What every agent test must cover

Three test cases minimum, in this order:

1. **Happy path with value assertions** — drive the agent end-to-end with a realistic mocked response, assert on the parsed-output dict's actual values (not just shape).
2. **Name check** — assert the agent's `name` attribute is the string the rest of the system expects (`"market_intelligence"`, `"strategy"`, `"risk_review"`, `"team_leader"`). Catches silent renames.
3. **JSON fallback path** — drive the agent with a response that does **not** contain the expected envelope, assert that `parse_output` still returns a usable dict via the JSON fallback. This is the failure-mode test; do not skip it.

### `stop_reason` convention

Mock responses use `stop_reason = "end_turn"`. The full tool-use loop is **not** exercised in unit tests — it would require multi-turn mocking and the convention of the suite is to skip it. If you genuinely need to test multi-turn tool-use behaviour, that goes in an integration test under `tests/test_integration/` (not in `tests/test_agents/`).

## Architectural invariant — non-negotiable

**The LLM must never control risk parameters directly.** If the agent you are adding or extending will make decisions affecting position sizing, entry/exit timing, or stop distances — stop. Add a deterministic validation layer in `tools/risk.py` first. The LLM receives the validated values as inputs; it cannot set or override them.

This is enforced regardless of how the agent is prompted. Risk parameters must originate from `tools/risk.py` and be plumbed through `pending_stops`/`pending_targets` (or equivalent) so the order-placement path can verify them against deterministic rules before submission.

If you are unsure whether your change touches risk, default to assuming it does and add the validator. It is cheaper to remove an unnecessary check than to backfill one after a runaway loss.

## Quick checklist before opening the PR

- [ ] Three `BaseAgent` methods implemented (`get_tools`, `_get_tool_functions`, `parse_output`).
- [ ] Tool callable `__name__` matches the tool definition `name` for every tool.
- [ ] Instance state for closures: init `None`, set in `run()`, captured as local before closure.
- [ ] Deferred imports inside `_get_tool_functions()`.
- [ ] `parse_output` includes a JSON fallback path.
- [ ] Three agent tests: happy path, name check, JSON fallback.
- [ ] If a new setting was added: env read + validation + `.env.example` + README.
- [ ] If the change affects risk: deterministic validator added to `tools/risk.py` first.
- [ ] `from __future__ import annotations` at the top of every new Python file.
