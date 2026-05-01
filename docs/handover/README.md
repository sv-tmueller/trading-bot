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
- **Next move** — pick up, hand to another role (Lead / Engineer / QA / Analyst / Docs), or close as won't-fix.

### 4. Decisions made this session

Bullet list of decisions that are not obviously visible in the diff. Each bullet:

- **Decision** — one line.
- **Rationale** — one line, including any rejected alternatives.
- **Consequence** — what changes for the next session as a result (e.g. "do not retry approach X", "the stop-loss math now lives in `tools/risk.py:atr_stop`").

These are the bullets a future session would otherwise have to re-derive by reading PR review threads. Capture them here.

### 5. Open questions

Things requiring user input or further research before progress can continue. For each:

- **Question** — phrased as a question.
- **What blocks the answer** — missing data, missing decision, missing access, etc.
- **Suggested next step** — who or what would unblock it (often: ask the user, run an analyst spike, wait for live-trading data).

### 6. Files to read first

Top 5–10 files the next session should load to be useful in this area, in priority order. Each entry:

- `path/to/file.py:line` — one-line reason.

Bias toward the files this session actually edited or relied on. Do not list every file in the repo.

### 7. Don't forget

Repo-specific invariants and gotchas that the next session is most likely to violate. Always include the items below verbatim if they apply to anything in **Next steps**, and add session-specific items on top:

- The LLM must never control risk parameters directly. Stops and targets come from `tools/risk.py`; the position monitor is rule-based; only `TeamLeaderAgent` places orders, and only with pre-approved values.
- Stops and take-profits execute server-side via Alpaca **bracket orders**. The position monitor is defence-in-depth, not the primary exit mechanism.
- Morning scan must run **pre-market** (cron `25 13 * * 1-5` UTC). Running after 13:30 UTC produces ~zero `volume_ratio` and kills every entry.
- `TRADING_PAUSED=true` halts new entries but does not affect the position monitor.
- Free Alpaca paper accounts require `DataFeed.IEX`; live SIP requires a paid account. Controlled via `DATA_FEED` env var.
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime).

Add session-specific gotchas above the standing list (e.g. "branch X has uncommitted ATR experiments stashed under stash@{0}").

### 8. Suggested next prompts

Three to five literal prompts the user can paste into a fresh Claude Code session to resume cleanly. Each prompt:

- Stands alone — a fresh session has no context.
- Names the branch / issue / PR / file the work attaches to.
- Is something a Team-Leader-orchestrated workflow can act on (`Triage open issues` / `Work on issue #N` / `Run QA` / `Update docs` / etc., per `TEAM.md`).

Order them by priority — the first prompt is the one the user should paste first if they only have time for one thing.

## Naming and location

- Path: `docs/handover/YYYY-MM-DD-<slug>.md`.
- Date: today's UTC date. If `currentDate` is provided in session context, use that.
- Slug: kebab-case, ≤30 chars, captures the dominant topic of the session (e.g. `exposure-cap-tuning`, `bracket-order-bugfix`, `v2-shorts-spike`).
- Multiple handovers per day are allowed if the slug is more specific. If two handovers would collide, append a session number to the slug (e.g. `bugfix-session-2`).

## Producing a handover

Use the `handover` skill: `/handover [<slug>]`. The skill captures live git / PR / issue state, reads `CLAUDE.md` and `TEAM.md` for invariants and role boundaries, writes the document against this contract, commits it on a dedicated `handover/<slug>-<date>` branch, and opens a draft PR.

Skill location: [`.claude/skills/handover/SKILL.md`](../../.claude/skills/handover/SKILL.md).

## Existing handovers

_None yet — this contract goes live with the skill that produced it._
