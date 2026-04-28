# Why agents are `.py` files, not `.md` skills

**Status:** decided
**Date:** 2026-04-28

## The question

Claude Code uses `.md` skill/subagent files. This bot has agents as `.py` files (`agents/strategy.py`, `agents/team_leader.py`, etc.) with system prompts embedded as Python strings. Should they be `.md` instead? And why are there no skills for things like `stock-research`, `strategy-analysis`, or `backtests`?

## The answer

`.md` skills and this bot's agents target **two different runtimes**:

| | Claude Code skills (`.md`) | This bot's agents (`.py`) |
|---|---|---|
| Runtime | Claude Code CLI, interactive | Headless Python process, cron-driven |
| Trigger | Human types `/skill` | `25 13 * * 1-5` UTC |
| Format | Markdown + frontmatter | Class subclassing `BaseAgent` |
| Tool execution | CLI's tool harness | Anthropic SDK tool-use loop in `agents/base.py` |
| State | Conversation context | SQLite (`agent_logs`, `pending_stops`, etc.) |

A `.md` skill cannot express what these agents need:

- Tool definitions paired with **Python callables** (`compute_ticker_signals` → `fetch_bars` + `compute_signals`)
- The tool-use loop, token accumulation, DB logging in `BaseAgent`
- Structured JSON parsing via `parse_output`
- Broker order placement (`TeamLeaderAgent`)

Replacing `.py` with `.md` would still require a Python loader, tool registry, response parser, and DB plumbing — i.e. reinventing `BaseAgent`.

## Why no skills for stock-research / strategy-analysis / backtests

These are not interactive workflows. They run on cron or via `python3 main.py {scan,monitor,backtest}`. Skills only fit when a human invokes something from Claude Code.

The bot's "skills" already exist — as deterministic Python modules the agents call as tools:

- `tools/market_data.py` — bars, EMA/RSI/ATR, entry signal
- `tools/risk.py` — ATR-based stops, portfolio guardrails
- `backtest/` — historical simulation

This is required by the architectural invariant in `CLAUDE.md`: **the LLM must never control risk parameters directly**. Stops, targets, guardrails, and exits are deterministic code, not prompts. Turning them into skills would invert that.

## The legitimate version of the challenge

Should system prompts be extracted from `.py` strings into separate `.md` files, loaded at runtime?

**Pros:** cleaner diffs on prompt edits; non-coders could edit prompts; potentially dual-purpose as Claude Code skills.

**Cons:** adds a loader for ~20-line prompts; prompts reference Python settings (`{settings.EMA_FAST}`) so you'd need templating; four agents, ~500 LOC total today.

**Decision:** keep prompts in `.py`. Revisit if any single prompt grows past ~50 lines or non-engineers start editing prompt content — at that point, split to `agents/prompts/*.md` loaded via `importlib.resources`.
