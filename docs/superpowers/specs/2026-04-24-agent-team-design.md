---
title: Agent Team Structure
date: 2026-04-24
status: approved
---

# Agent Team Structure

A four-role Claude Code session structure for developing and maintaining the trading bot. Each role runs in a separate Claude Code session. GitHub Issues is the single source of truth for all work.

## Roles

| Role | Session trigger | Core responsibility |
|---|---|---|
| Lead | `Act as Lead` | Triage open GitHub Issues, set priorities, identify next task for Engineer |
| Engineer | `Act as Engineer` | Pick up top-priority ready issue, implement, close issue when done |
| QA | `Act as QA` | Run tests, scan codebase for gaps/bugs/TODOs, open new GitHub Issues |
| Docs | `Act as Docs` | Review recent commits, update README/CLAUDE.md/docstrings |

## GitHub Label System

**Type** (set by QA or Lead when opening/triaging):
- `bug` — something broken
- `enhancement` — new feature or improvement
- `testing` — missing/failing tests
- `documentation` — docs gap
- `refactor` — code quality, no behaviour change

**Priority** (set by Lead):
- `priority: high` — blocks other work or is a live issue
- `priority: medium` — important, next sprint
- `priority: low` — nice to have

**Status** (maintained across sessions):
- `status: ready` — prioritized by Lead, Engineer can pick up
- `status: in-progress` — Engineer is working on it
- `status: blocked` — waiting on something external

## Workflow Sequence

```
QA opens issue (type label)
  → Lead triages: adds priority + status:ready
    → Engineer picks up status:ready + highest priority
      → Engineer closes issue on completion
        → Docs reviews git log, updates docs, closes doc issues
```

## Session Playbooks

### Lead

1. `gh issue list` — fetch all open issues
2. Triage any unlabeled issues (add type + priority labels)
3. Add `status: ready` to the top 3–5 prioritized issues
4. Post a brief comment on each `status: ready` issue confirming priority rationale
5. Output a short session summary: what was triaged, what Engineer should tackle next

### Engineer

1. `gh issue list --label "status: ready"` — fetch ready issues sorted by priority
2. Pick the highest-priority one, add `status: in-progress`
3. Implement — follow existing patterns in CLAUDE.md, write/update tests
4. Run `python3 -m pytest` — all green before closing
5. Commit, close issue via commit message (`closes #N`) or `gh issue close`

### QA

1. Run `python3 -m pytest` — log any failures as new GitHub Issues with `bug` label
2. Scan for `TODO`, `FIXME`, missing test coverage, untested edge cases
3. Review last 5–10 commits (`git log`) for changes without matching tests
4. Open a GitHub Issue for each finding with appropriate type label
5. Never implement fixes — report only

### Docs

1. `git log` since last docs commit — identify what changed
2. Update README if commands, architecture, or config changed
3. Update CLAUDE.md if patterns, constraints, or conventions changed
4. Close any open `documentation` issues that are now resolved

## Deliverables (Implementation)

- `TEAM.md` at repo root — operational reference, loaded via CLAUDE.md
- CLAUDE.md updated with a "Team" section pointing to `TEAM.md`
- GitHub labels created on the repo matching the label system above
