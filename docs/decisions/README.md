# Development Decision Log

Format and conventions for `docs/decisions/YYYY-MM-DD-<slug>.md` files. Each entry records a significant choice made during development or operations so that future contributors — human or agent — can reconstruct the reasoning without digging through PR threads.

## Why these exist

Code tells you *what* the bot does. The decision log tells you *why* it does it that way and what was rejected. Without it, the same debates recur: why is the SMA window 200 days and not 150? Why does the kill-switch check the live broker position rather than `regime_state`? Why are Edge Functions used instead of a cron container? The answers live here.

A decision entry is **not**:
- A design document for work in progress (those live in `docs/plans/` and in PRs).
- A research artefact evaluating future options (those live in `docs/research/<topic>/`).
- A session handover (those live in `docs/handover/`).
- A changelog (PR descriptions and `git log` own that).

## When to write one

Write a decision entry for any choice that:

- Changes the **architecture** — new module, new external dependency, new persistence layer, new runtime.
- Changes **strategy parameters** — SMA window, drawdown threshold, ticker, lookback period, regime filter logic.
- Changes **process** — how the bot is deployed, monitored, or operated; how the team works.
- Resolves a **non-obvious trade-off** — where a reasonable engineer might later question the choice and reopen it.

When in doubt, write one. A short entry that turns out to be unnecessary costs little; a missing entry that forces a rederivation costs a lot.

## Immutability rule

Entries are **immutable once merged**. Do not edit a past entry to reflect a later outcome or correction. If a decision is superseded, write a new dated entry that references the old one and marks itself as the replacement. Update the old entry's `Status` field to `superseded by YYYY-MM-DD-<slug>.md` — that single-field edit is the only permitted change to a merged entry.

This rule preserves the historical record: you can always read the log chronologically and understand what was true at each point in time.

## File contract

One Markdown file per decision. Use `TEMPLATE.md` as the starting point.

## Naming and location

- Path: `docs/decisions/YYYY-MM-DD-<slug>.md`.
- Date: the date the decision was made (UTC). Use `currentDate` from session context when writing during a Claude Code session.
- Slug: kebab-case, ≤30 chars, names the subject of the decision (e.g. `use-supabase-edge-functions`, `200-day-sma-window`, `kill-switch-uses-broker-position`).
- If two decisions on the same day would collide, append a counter: `2026-06-14-foo-2.md`.

## Existing decisions

_None yet — the log opens with the entries that will be written as live decisions arise._
