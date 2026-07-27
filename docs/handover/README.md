# Session Handovers

Format and conventions for `docs/handover/YYYY-MM-DD-<slug>.md` files. Each handover is a self-contained Markdown document that lets a future Claude Code session resume work cold — no chat history, no shared memory, just the doc and the live repo.

## Why these exist

Claude Code sessions do not persist across runs. Long sessions accumulate decisions, dead ends, partial implementations, and architectural reasoning that would cost real time to reconstruct from `git log` alone. A handover captures the load-bearing context so the next session pays the lookup cost once — at write time — instead of re-deriving it.

A handover is **not**:
- A design document (those live in `docs/superpowers/specs/` and in PRs).
- A research artefact (those live in `docs/research/<topic>/`).
- A changelog (PR descriptions and README release notes own that).
- A status report for humans (this is written for the next Claude session — terse, technical, link-heavy).

## File contract

Every handover document has exactly the sections below, in this order. Skipping a section is not allowed; if a section has nothing to report, write `_None._` explicitly so the reader knows it was considered, not forgotten.

The orchestrator skill (`.claude/skills/handover/SKILL.md`) writes the file; the contract here is enforced regardless of who writes it.

### Front matter (top of file)

A short header with three lines, in this order:

```
**Date:** YYYY-MM-DD (UTC)
**Slug:** kebab-case-slug
**Author:** Claude Code session (model name, e.g. claude-opus-4-7)
```

No YAML — keep it plain Markdown so it renders cleanly in a GitHub PR preview.

### 1. Sit-rep

One paragraph, ≤6 sentences. What is the bot doing right now? What is the active branch and PR? What did this session set out to do, and where did it end up? A reader who has never seen this session must understand the lay of the land from this paragraph alone.

### 2. In-flight branches & PRs

Bullet list. For each open branch or PR touched this session:

- **Branch / PR** — `<branch-name>` / `#<PR-number>` (state: draft | ready | merged | abandoned).
- **Purpose** — one line.
- **Status** — what is done, what is not, what is blocking. Reference specific files and line numbers where the next session should pick up.
- **Next action** — the literal next step. If waiting on a reviewer or CI, say so.

If there are none, write `_None._`.

### 3. Open issues being worked

Bullet list of GitHub issues this session engaged with, including ones that were investigated but not opened as PRs. For each:

- **`#N` — <title>** — labels (especially `status:*` and `priority:*`).
- **What we learned** — one line. Includes ruled-out approaches.
- **Next move** — pick up, route through the current operating model (`/tm-advisor` / `/tm-kickoff`, or a direct QA / Docs ask, per the [Team](../../CLAUDE.md#team) section of `CLAUDE.md`), or close as won't-fix.

### 4. Decisions made this session

Bullet list of decisions that are not obviously visible in the diff. Each bullet:

- **Decision** — one line.
- **Rationale** — one line, including any rejected alternatives.
- **Consequence** — what changes for the next session as a result (e.g. "do not retry approach X", "the regime math now lives in `supabase/functions/_shared/regime.ts:computeTargetState`").

These are the bullets a future session would otherwise have to re-derive by reading PR review threads. Capture them here.

### 5. Open questions

Things requiring user input or further research before progress can continue. For each:

- **Question** — phrased as a question.
- **What blocks the answer** — missing data, missing decision, missing access, etc.
- **Suggested next step** — who or what would unblock it (often: ask the user, run an analyst spike, wait for live-trading data).

### 6. Files to read first

Top 5–10 files the next session should load to be useful in this area, in priority order. Each entry:

- `path/to/file.ts:line` — one-line reason.

Bias toward the files this session actually edited or relied on. Do not list every file in the repo.

### 7. Don't forget

Repo-specific invariants and gotchas that the next session is most likely to violate. Always include the items below verbatim if they apply to anything in **Next steps**, and add session-specific items on top:

- **No LLM in the trading path.** The `daily-check`, `kill-switch`, and `panic` Edge Functions import no model SDK and instantiate no agent. Enforced mechanically by `supabase/functions/_shared/invariants.test.ts`.
- **One decision rule.** SPY close vs SPY 200-DMA, modulated by the kill-switch flag, computed by the pure function `computeTargetState` in `supabase/functions/_shared/regime.ts`. Never add a second decision rule without a fresh brainstorm and design spec.
- **`bot_config.paused=true` is the operational kill switch.** It halts new entries (`daily-check` exits `skipped:trading_paused`); the kill-switch function is unaffected and keeps protecting an open position. Set and cleared via the `panic` Edge Function (`action=pause` / `action=resume`).
- **Never execute against the live broker from an agent context.** With `CLAUDE_AGENT_NO_BROKER` set, the mutating helpers on `supabase/functions/_shared/alpaca.ts` (`placeMarketOrder`, `liquidate`, `cancelAllOrders`) raise `BrokerCallBlockedError`. Mock all Alpaca calls in tests — each function's `logic.ts` takes an injected `deps` object.
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime; Python is research-only — the production bot is TypeScript on Deno).

The authoritative statement of the safety contract is the [Architectural invariants](../../CLAUDE.md#architectural-invariants) section of `CLAUDE.md` — the bullets above are reminders drawn from it, not a restatement; where they drift, `CLAUDE.md` wins.

Add session-specific gotchas above the standing list (e.g. "branch X has uncommitted ATR experiments stashed under stash@{0}").

### 8. Suggested next prompts

Three to five literal prompts the user can paste into a fresh Claude Code session to resume cleanly. Each prompt:

- Stands alone — a fresh session has no context.
- Names the branch / issue / PR / file the work attaches to.
- Is something the current operating model can act on (`/tm-advisor <description>` to start a change, `/tm-kickoff #N` to implement a sized issue, `Run QA`, `Update docs`, etc., per the [Team](../../CLAUDE.md#team) section of `CLAUDE.md`).

Order them by priority — the first prompt is the one the user should paste first if they only have time for one thing.

## Naming and location

- Path: `docs/handover/YYYY-MM-DD-<slug>.md`.
- Date: today's UTC date. If `currentDate` is provided in session context, use that.
- Slug: kebab-case, concise — a few words capturing the dominant topic of the session (e.g. `mvp2-migration-execution`, `candlestick-search-egress-blocked`, `contracts-survey-prep`).
- Multiple handovers per day are allowed if the slug is more specific. If two handovers would collide, append a session number to the slug (e.g. `bugfix-session-2`).

## Producing a handover

Use the `handover` skill: `/handover [<slug>]`. The skill captures live git / PR / issue state, reads `CLAUDE.md`'s [Architectural invariants](../../CLAUDE.md#architectural-invariants) section (for the §7 material) and [Team](../../CLAUDE.md#team) section (for role boundaries), writes the document against this contract, commits it on a dedicated `handover/<slug>-<date>` branch, opens a draft PR, and posts a short session-tally wrap-up in chat (PRs merged, what is now live, branches still open, bot code touched / untouched). The wrap-up is for the current user; the doc is for the next session.

Skill location: [`.claude/skills/handover/SKILL.md`](../../.claude/skills/handover/SKILL.md).

## Existing handovers

The dated `YYYY-MM-DD-<slug>.md` files in this directory are the existing handovers, newest by date prefix — see [`2026-07-25-contracts-survey-prep.md`](2026-07-25-contracts-survey-prep.md) for a format-current reference example.
