# Invariant enforcement in the template operating model

**Date:** 2026-06-14
**Status:** Approved (brainstorm) — feeds Batch 2 / package P1
**Related:** Batch "operating-model migration"; CLAUDE.md "Architectural invariants"; #276 (Batch 1, which partially retired the legacy team)

## Problem

Batch 2 retires the legacy dev team (`engineer` / `spec-reviewer` / `code-quality-reviewer` / `lead` + `TEAM.md`) and adopts the template `advisor → kickoff → architect / developer / reviewer / tester` model. The retired `code-quality-reviewer` was the only agent charged with enforcing the architectural safety invariants on every change.

Two findings make this urgent and reshape the fix:

1. **The template model has no invariant enforcement.** The word "invariant" appears nowhere in `tm-advisor`, `tm-kickoff`, or the `architect` / `developer` / `reviewer` / `tester` agents. The template `reviewer` Pass-2 only checks "the CLAUDE.md code style and writing style sections." Retiring `code-quality-reviewer` with no replacement would silently drop safety-invariant enforcement for a live-money trading bot.

2. **The retired enforcer was already stale.** `code-quality-reviewer.md`'s invariants are pre-pivot Python (`tools/risk.py`, `TeamLeaderAgent` placing orders, `monitor/position_monitor.py`, a `from __future__ import annotations` checklist). None survived the MVP 2.0 TypeScript / Alpaca / Supabase pivot. It was a *misleading* gate, not a working one. The current invariants live only in CLAUDE.md's "Architectural invariants" section (authoritative since #281).

## Principle: single source of truth

The architectural invariants are defined in exactly one place — CLAUDE.md's "Architectural invariants" section. No enforcement artifact restates the invariant *text*; each one references the section. This is precisely what prevents the staleness that rotted the old agent.

## Design — two layers

### Layer 1 — Mechanical (deterministic, no LLM judgment)

New test: `supabase/functions/_shared/invariants.test.ts`.

- Scans every non-test `.ts` file under `supabase/functions/` (excludes `*.test.ts`).
- **Fails** if any model-SDK / agent-instantiation import appears. Forbidden specifiers, matched case-insensitively in import / `from` / `require` positions (not in comments): `anthropic`, `@anthropic-ai`, `openai`, `cohere`, `mistral` / `mistralai`, `generativeai`, `@google/genai`, `langchain`.
- Enforces invariant **"No LLM in the trading path"** with a check that cannot be rationalized around. The import scan is the practical proxy for "imports no model SDK and instantiates no agent" — you cannot instantiate an agent without importing its SDK.
- Runs inside `deno task test`, which the **tester** stage already runs per package, so a violation fails the package before it reaches review.

Baseline: clean today (no such imports anywhere in `supabase/functions/`), so the test is green on creation.

The **broker-guard** invariant ("agent-spawned tests never reach the live broker") needs nothing new: `checkGuard()` on the mutating helpers is already enforced and tested (`alpaca.test.ts` — `CLAUDE_AGENT_NO_BROKER` → `BrokerCallBlockedError` on `placeMarketOrder` / `liquidate` / `cancelAllOrders`).

### Layer 2 — Process (LLM review, for the judgment-based invariants)

The grep cannot catch "one decision rule," "opt-in / default-OFF for risky changes," "panic is the deterministic kill button," etc. CLAUDE.md's rewritten operating-model section gains a short rule:

> **Architectural invariants are a hard review gate.** The [Architectural invariants](#architectural-invariants) section is the single source of truth — never restate it elsewhere. Every code-touching work package carries the standing acceptance criterion *"Satisfies all CLAUDE.md Architectural invariants; any violation is a must-fix review finding,"* which the advisor stamps when filing the issue. The architect, developer, and reviewer verify the change against that section; the reviewer treats any violation as a blocking `CHANGES_REQUESTED` finding. Invariant #1 ("No LLM in the trading path") is additionally enforced mechanically by `supabase/functions/_shared/invariants.test.ts`.

This needs **zero edits to template-owned files**: the reviewer already reads the issue's acceptance criteria (Pass-1) and CLAUDE.md (Pass-2), so pointing both at the invariants section is enough.

## Scope boundaries

- **No template-owned file is edited** (`architect` / `developer` / `reviewer` / `tester.md`, `tm-*` skills/workflows). They stay exactly as synced.
- **Upstream track (not here):** fix the template `reviewer` to read any project's CLAUDE.md invariants section and block on violation, then sync down. That generalizes Layer 2 across template projects.
- **Separate track (not here):** a CI gate running `deno task test` on PRs (the repo has no CI test gate yet — flagged in the #276 report). Until it exists, the tester stage is what runs the mechanical check.

## How this feeds Batch 2 / P1

P1 ("Cut over the dev operating model + preserve invariant enforcement") gains these acceptance criteria:

- `supabase/functions/_shared/invariants.test.ts` exists, scans the trading path for forbidden model-SDK imports, and passes (`deno task test` green, `deno lint` clean).
- CLAUDE.md's new operating-model section contains the "Architectural invariants are a hard review gate" rule (Layer 2), **referencing — not restating** — the invariants section.
- The "Architectural invariants" section text itself is byte-for-byte unchanged.
