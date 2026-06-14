---
name: add-or-extend-agent
description: Use this skill when adding a new env-driven setting in `supabase/functions/_shared/config.ts` or `supabase secrets set`. Captures the settings recipe (env read + range-validation in config.ts, .env.example doc, README, opt-in/default-OFF pattern). Triggers include "add a new env-driven setting", "add a config option", "add a feature flag", or any work that edits `config.ts` settings.
---

# Add or Extend a Setting

Procedural playbook for adding a new configurable setting to the trading bot. Every rule below has been the source of a real bug at least once.

This skill is **dual-purpose**: the main session invokes it via the Skill tool; the `engineer` subagent reads it via the `Read` tool when its issue touches settings. Same content, two consumption paths.

## When this skill applies

- Adding a new env-driven setting or feature flag to the bot (often to gate a new behaviour or expose a tunable).
- The setting surfaces in `supabase/functions/_shared/config.ts` — read from a Supabase secret and range-validated at function start.
- Note: the pre-2026-05-07 Python bot stored settings in a `settings.py` module and a `.env` file. The current stack uses `supabase secrets set` / `config.ts` instead. The recipe is the same in spirit; only the mechanics differ.

If the work is purely logic-side (no new configurable knob), this skill is overkill — read `CLAUDE.md` and write the logic. The skill kicks in once the change needs a user-facing knob.

## Adding a new env-driven setting

Required when a new behaviour needs a tunable parameter or feature flag. Recipe:

1. **Read in `supabase/functions/_shared/config.ts`** — add the new setting inside the `loadConfig()` function (or the top-level export object). Read from `Deno.env.get("NEW_SETTING")` with a sensible default:
   ```typescript
   const newSetting = parseFloat(Deno.env.get("NEW_SETTING") ?? "0.5");
   ```
2. **Validate immediately** if the setting has bounds. Throw a clear error for out-of-range values so the function fails fast at cold-start rather than silently misbehaving at trade time:
   ```typescript
   if (newSetting < 0.0 || newSetting > 1.0) {
     throw new Error(`NEW_SETTING must be in [0, 1], got ${newSetting}`);
   }
   ```
3. **Export the validated value** as part of the config object returned by `loadConfig()` (or as a named export if the file uses that style). Every Edge Function that needs it imports from `_shared/config.ts` — do not read `Deno.env.get` directly in function code.
4. **Set the secret** for the deployed environment:
   ```bash
   supabase secrets set NEW_SETTING=0.5
   ```
   Document the default and valid range in the command comment.
5. **Document in `.env.example`** with a brief inline comment (this file is the canonical "what secrets does this bot need?" reference for new operators):
   ```
   NEW_SETTING=0.5   # <what it controls>, range [0, 1]
   ```
6. **Document in `README.md`** (Settings or Configuration section) — what the setting does, default, valid range, and which Edge Function(s) consume it.
7. **Risky changes use the opt-in / default-OFF pattern.** Anything touching risk parameters, position sizing, or live-trading behaviour must default to disabled (`0`, `false`, or empty string) and be gated on the flag before taking effect. Recent precedents: `KILL_SWITCH_DRAWDOWN_PCT` (non-zero = enabled), `bot_config.paused` (runtime kill via panic action).

## Hard rule — never execute against the live broker in tests

Engineer subagents inherit the project's Alpaca secrets via the parent shell. Any `deno test` or ad-hoc invocation could submit real orders if it reaches a live broker path. The mutating helpers on `supabase/functions/_shared/alpaca.ts` (`placeMarketOrder`, `liquidate`, `cancelAllOrders`) call `checkGuard()` and raise `BrokerCallBlockedError` when `CLAUDE_AGENT_NO_BROKER` is set. All Alpaca calls MUST be mocked in tests — the `logic.ts` modules take an injected `deps` object, so pass mocks directly. Do NOT unset `CLAUDE_AGENT_NO_BROKER` to silence a `BrokerCallBlockedError`; that defeats the safety net.

_See architectural invariant in `CLAUDE.md` and incident history (#149) for the rationale._

## Architectural invariant — non-negotiable

**No LLM in the trading path.** The `daily-check`, `kill-switch`, and `panic` Edge Functions import no model SDK. Any new setting you add must be consumed by deterministic TypeScript logic only — not fed to a model for interpretation.

If you are unsure whether your change adds a second decision rule, stop, re-read the "One decision rule" invariant in `CLAUDE.md`, and open a brainstorm issue. It is cheaper to scope correctly than to backfill a revert.

## Quick checklist before opening the PR

- [ ] New setting read from `Deno.env.get("NEW_SETTING")` inside `config.ts` `loadConfig()`.
- [ ] Range validated immediately; throws on invalid value.
- [ ] Exported via the config object (not via direct `Deno.env.get` calls in function code).
- [ ] `supabase secrets set` command documented in PR description.
- [ ] `.env.example` entry added with inline comment.
- [ ] `README.md` Settings section updated.
- [ ] Risky change? Default is OFF (0 / false / empty). Gated before taking effect.
- [ ] No LLM call added. No second decision rule introduced.
