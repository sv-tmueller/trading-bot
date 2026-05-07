# Team

The main Claude Code session always acts as **Team Leader** — it orchestrates the six specialist roles (Lead, Engineer, Reviewer, QA, Analyst, Docs) by dispatching them as registered Claude Code subagents. You never need to start a new session or switch contexts. Just tell the Team Leader what you want to accomplish.

The role playbooks live as subagent definitions in [`.claude/agents/`](.claude/agents/). Each `.md` file is the source of truth for that role — `TEAM.md` is the human-readable index.

---

## How to use

Start a session and state your intent. The Team Leader runs `superpowers:brainstorming` first (regardless of perceived simplicity — that's the HARD-GATE), produces a spec at `docs/plans/<date>-<slug>-design.md`, then runs `superpowers:writing-plans` to produce a plan at `docs/plans/<date>-<slug>-plan.md`. Once you approve, the Team Leader dispatches subagents per the table below.

| Say this | Team Leader will… |
|---|---|
| `Triage open issues` | Dispatch **lead** to label, prioritize, and set `status: ready` |
| `Work on issue #N` | Brainstorm → writing-plans → subagent-driven-development. Per-task: dispatch **engineer** (implementer) → **spec-reviewer** → **code-quality-reviewer**. After all tasks complete: `superpowers:finishing-a-development-branch` → **lead** merges. |
| `Investigate <topic>` or `Research issue #N` | Dispatch **analyst** to run backtests and write findings to `docs/research/` |
| `Run QA` | Dispatch **qa** to discover bugs and open issues |
| `Update docs` | Dispatch **docs** to sync README, CLAUDE.md, and CURRENT_CONFIG |
| Anything else | Brainstorm first, then propose a plan |

Run `/agents` in Claude Code to inspect the registered subagents.

---

## Roles

| Role | File | Responsibility | Can edit code? |
|---|---|---|---|
| **Team Leader** | _(main session)_ | Run brainstorming → writing-plans → subagent-driven-development. Dispatch lead/engineer/spec-reviewer/code-quality-reviewer/qa/docs/analyst per the flow. | No (delegates) |
| **lead** | [`.claude/agents/lead.md`](.claude/agents/lead.md) | Triage issues, set priorities, gate-keep merges (3-signal gate: tests + spec-reviewer + code-quality-reviewer) | No |
| **engineer** | [`.claude/agents/engineer.md`](.claude/agents/engineer.md) | Implement one task from a plan (TDD, frequent commits, structured report). Never opens PRs (Team Leader runs `finishing-a-development-branch`) | Yes |
| **spec-reviewer** | [`.claude/agents/spec-reviewer.md`](.claude/agents/spec-reviewer.md) | Pass-1 review per task: did the implementer build exactly what the task asked? Read-only | No |
| **code-quality-reviewer** | [`.claude/agents/code-quality-reviewer.md`](.claude/agents/code-quality-reviewer.md) | Pass-2 review per task: code quality + architectural invariants checklist. Blocks PR on invariant violation. Read-only | No |
| **qa** | [`.claude/agents/qa.md`](.claude/agents/qa.md) | Find problems, open GitHub issues (uses `superpowers:systematic-debugging` for root-cause triage on failed tests) | No |
| **analyst** | [`.claude/agents/analyst.md`](.claude/agents/analyst.md) | Backtest-driven research; writes findings to `docs/research/` only | docs/research only |
| **docs** | [`.claude/agents/docs.md`](.claude/agents/docs.md) | Sync README, CLAUDE.md, TEAM.md, CURRENT_CONFIG with code; changelog discipline | Docs only |

---

## Team Leader (main session)

The main session **is** the Team Leader. It is not a registered subagent — it is the session itself.

**What it does:**
- Reads GitHub Issues and decides which role to invoke.
- Dispatches each subagent with the exact context it needs (no shared session state).
- After each `engineer` PR, dispatches `reviewer` for a spec + quality pass; loops `engineer` ↔ `reviewer` until the verdict is `APPROVED`.
- Dispatches `lead` to merge PRs once both tests and reviewer have signed off.
- Dispatches `docs` after production code merges.

**Does not:** implement code directly. Delegates to the `engineer` subagent.

---

## GitHub Label Reference

| Label | Set by | Meaning |
|---|---|---|
| `bug` | qa / lead | Something broken |
| `critical` | qa / lead | High-severity bug; supersedes `priority: high` |
| `enhancement` | qa / lead | New feature or improvement |
| `strategy` | lead | Strategic or architectural improvement |
| `testing` | qa | Missing or failing tests |
| `documentation` | qa / docs | Docs gap |
| `refactor` | qa / lead | Code quality, no behaviour change |
| `priority: high` | lead | Blocks other work or is a live issue |
| `priority: medium` | lead | Important, next sprint |
| `priority: low` | lead | Nice to have |
| `status: ready` | lead | Engineer can pick up |
| `status: in-progress` | engineer | Being worked on |
| `status: blocked` | engineer | Waiting on something external |

---

## Workflow

```
User states intent
  │
  ▼
Team Leader: superpowers:brainstorming
  │  (writes docs/plans/<date>-<slug>-design.md, gets user approval)
  ▼
Team Leader: superpowers:writing-plans
  │  (writes docs/plans/<date>-<slug>-plan.md, gets user approval)
  ▼
Team Leader: superpowers:subagent-driven-development
  │
  ▼
  Per-task loop:
    Dispatch engineer (implementer) ─────────┐
      │                                       │
      ▼                                       │
    Dispatch spec-reviewer                    │
      │                                       │
      ├── ❌ NEEDS_CHANGES ──────────────────┘ (re-dispatch engineer)
      │
      └── ✅ Spec compliant
          │
          ▼
        Dispatch code-quality-reviewer
          │
          ├── ❌ NEEDS_CHANGES ──────────────┐ (re-dispatch engineer)
          │                                   │
          └── ✅ Ready to merge ──────────────┤
                                              │
  ◀───────── Mark task complete ◀─────────────┘
  │
  ▼ (loop until all tasks done)
  
Team Leader: superpowers:finishing-a-development-branch
  │  (assembles merge readiness)
  ▼
Team Leader dispatches lead → 3-signal merge gate → squash merge
  │
  ▼
Team Leader dispatches docs → sync README / CLAUDE.md / CURRENT_CONFIG
```

**Every change goes through a PR.** No direct commits to `main`.

**Brainstorming applies to every change**, including bug fixes and small refactors. The HARD-GATE in `superpowers:brainstorming` is honored on this project regardless of perceived simplicity — see `docs/plans/2026-05-07-superpowers-workflow-adoption-design.md` for rationale.
