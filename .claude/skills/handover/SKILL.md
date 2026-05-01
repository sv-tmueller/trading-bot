---
name: handover
description: Use this skill to write a session handover document in `docs/handover/YYYY-MM-DD-<slug>.md` so a future Claude Code session can resume work without losing context. Invoke when the user wants to wrap up a session, hand off mid-task, capture state before a break, or pre-load context for the next conversation. Triggers include `/handover [<slug>]`, "write a handover", "create a session handover", "handover doc for the next session", "save context for tomorrow", "wrap up the session".
---

# Handover

Produce a single self-contained Markdown file in `docs/handover/` that lets a future Claude Code session resume this work cold — no chat history, no shared memory, just the doc and the live repo. Pure documentation; no code or behavioural changes.

The format contract for the artifact lives in [`docs/handover/README.md`](../../../docs/handover/README.md). **Read it before writing** — it defines every section the document must contain. This skill is the orchestrator; the README is the contract.

## Inputs

- `<slug>` (optional, kebab-case) — short subject of the handover. Defaults to a slug derived from the dominant topic of the session (e.g. `exposure-cap-tuning`, `bracket-order-bugfix`, `v2-shorts-spike`). Used in the filename `YYYY-MM-DD-<slug>.md`.

The date prefix is today's UTC date. Multiple handovers per day are allowed — disambiguate with a more specific slug.

## Pre-flight

Do all of these before writing.

1. **Read `CLAUDE.md` in full.** The handover must surface the architectural invariants — *"The LLM must never control risk parameters directly"*, the deterministic-risk layer, the kill switch, the pre-market scan timing, the IEX/SIP feed gate. These are non-obvious to a cold reader and easy to violate without reminder.
2. **Read `docs/handover/README.md`** for the section-by-section contract.
3. **Read `TEAM.md`** so role boundaries (Lead / Engineer / Reviewer / QA / Analyst / Docs) are reflected accurately in any "next steps" the handover proposes.
4. **Capture live state** — run these in parallel:
   - `git status` and `git branch --show-current` — uncommitted changes, current branch.
   - `git log --oneline -20` — recent commit context.
   - `gh pr list --repo sv-tmueller/trading-bot --state open` — open PRs (draft and ready).
   - `gh issue list --repo sv-tmueller/trading-bot --state open` — open issues, their labels and status.
   - `git stash list` — anything stashed mid-session.
5. **Check for an in-flight worktree.** If the session was running in a worktree (e.g. for a research bundle), record the worktree path and branch — the next session will need to know whether to keep, merge, or discard it.
6. **Check `docs/handover/` for the previous handover.** If one exists from the same calendar day on the same slug, ask the user whether to (a) overwrite, (b) append a "Session 2" addendum, or (c) pick a more specific slug.

## Writing the handover

Single pass, written by the main session — no subagent dispatch. The document must:

- Follow every section in the format contract (`docs/handover/README.md`). Skipping a section is not allowed; if a section has nothing to report, write `_None._` explicitly so the reader knows it was considered.
- Quote real artefacts: branch names, PR numbers, issue numbers, file paths with line numbers, commit SHAs. **No paraphrasing where a link or reference exists.**
- Make every "next step" actionable as a literal prompt the user can paste back. Vague aspirations like "continue working on shorts" are forbidden — write the exact issue number, the exact branch, the exact file to open first.
- Surface invariants the next session is most likely to forget — the deterministic-risk rule, `TRADING_PAUSED`, the pre-market cron window, the bracket-order anchoring to fresh quotes. Pull these forward into the **Don't forget** section even if they were not touched this session.
- Be honest about open questions and dead ends. If a hypothesis was tried and failed, name it so the next session does not repeat the work.
- Stay under ~400 lines. A handover that nobody re-reads is worse than a shorter one that is actually loaded.

## Filename and location

`docs/handover/YYYY-MM-DD-<slug>.md` — UTC date, kebab-case slug. Today's date comes from the session, not from the local clock of any tool — if `currentDate` is provided in context, use that.

## Branch and PR

1. Create or check out a dedicated branch for the handover commit. Naming: `handover/<slug>-<date>` (e.g. `handover/exposure-cap-tuning-2026-05-01`). Do **not** reuse a feature branch — handovers should not piggy-back on in-flight work, because the handover may be merged before the feature is ready.
2. Commit the new file only. Commit message: `docs: handover — <slug> (<date>)`.
3. Push the branch with `git push -u origin <branch>`; retry on network errors with exponential backoff (2s / 4s / 8s / 16s).
4. Open a **draft PR** with title `Handover: <slug> (<date>)`. Body lists the key next-step prompts so a reviewer can sanity-check the actionability.
5. Leave the PR as draft. The user reviews and flips to ready themselves; the handover is meant to be a personal artefact and the user decides when (or whether) it lands on `main`.

## When to invoke

- Explicit `/handover` from the user.
- User says they are about to step away, end the session, or hand off to another contributor.
- Session has accumulated significant decisions or in-flight work that would be expensive to reconstruct from `git log` alone (research detours, parameter sweeps, partially designed features).
- Before context is about to be auto-compressed and important state is at risk of being lost — propose writing a handover proactively in that case.

## When NOT to invoke

- Trivial one-shot edits where the PR description is already a complete record.
- The session is mid-tool-use and the work is not yet committable. Finish or stash first; a handover that points at uncommitted state on a different machine is useless.
- The user has just asked to start fresh on a different topic — a handover is for resuming, not for archiving an abandoned thread.

## Quality bar

- Every link resolves. Every PR number, issue number, branch name, and file path is real.
- Every "next step" is a literal prompt, not a paraphrase.
- The deterministic-risk invariant is restated where any next step touches risk, sizing, stops, or order placement.
- A reader who has never seen this session before can act on the document with no follow-up questions.

## Non-goals

- No code changes to the bot.
- No new tests.
- No new agents in `.claude/agents/`.
- The handover is not a design document — link out to specs in `docs/superpowers/specs/` or research in `docs/research/` rather than restating their content.
- The handover is not a changelog — that lives in PR descriptions and `README.md` release notes.
