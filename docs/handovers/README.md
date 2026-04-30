# Session handovers

Durable context from Claude sessions that made meaningful decisions. Read these before starting work in a fresh session.

## Naming

`YYYY-MM-DD-<slug>.md`. Slug is kebab-case, descriptive but concise (under 60 chars). One file per session, or split by topic if a session covered unrelated areas.

## What goes in a handover

1. **Decisions made** with consequences.
2. **Rejected paths** with the reason for rejection. This is the most valuable part. Without it, future sessions repeat work.
3. **Selection criteria** used to evaluate options.
4. **Constraints surfaced** (style, tax, infra, broker preferences).
5. **Open questions** flagged for later.

## What does NOT go in a handover

- Full code listings (those live in PRs and commits).
- Pleasantries, recaps of well-known facts, or restating CLAUDE.md.
- Status updates ("we did X today"). Handovers are forward-looking context, not changelogs.

## When to write one

- The user asks you to "document", "handover", "save context", or similar.
- The session made a non-trivial architectural or strategic decision (especially when alternatives were rejected).
- You are about to end a session that produced shipped or specced work.

The repo is the source of truth, not the chat transcript. Write the handover so the next session can act without reading prior chats.
