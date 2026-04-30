# Team

The main Claude Code session always acts as **Team Leader** — it orchestrates the six specialist roles (Lead, Engineer, Reviewer, QA, Analyst, Docs) by dispatching them as registered Claude Code subagents. You never need to start a new session or switch contexts. Just tell the Team Leader what you want to accomplish.

The role playbooks live as subagent definitions in [`.claude/agents/`](.claude/agents/). Each `.md` file is the source of truth for that role — `TEAM.md` is the human-readable index.

---

## How to use

Start a session and state your intent. The Team Leader decides which subagent to dispatch:

| Say this | Team Leader will… |
|---|---|
| `Triage open issues` | Dispatch **lead** to label, prioritize, and set `status: ready` |
| `Work on the issues` | Dispatch **lead** → **engineer** → **reviewer** → **lead** (merge) per issue |
| `Review PR #N` | Dispatch **reviewer** for a spec + quality pass on the open PR |
| `Investigate <topic>` or `Research issue #N` | Dispatch **analyst** to run backtests and write findings to `docs/research/` |
| `Run QA` | Dispatch **qa** to discover bugs and open issues |
| `Update docs` | Dispatch **docs** to sync README, CLAUDE.md, and CURRENT_CONFIG |
| Anything else | Team Leader assesses and coordinates as needed |

Run `/agents` in Claude Code to inspect the registered subagents.

---

## Roles

| Role | File | Responsibility | Can edit code? |
|---|---|---|---|
| **Team Leader** | _(main session)_ | Orchestrate other roles, run review loop, dispatch merges, dispatch docs updates | No (delegates) |
| **lead** | [`.claude/agents/lead.md`](.claude/agents/lead.md) | Triage issues, set priorities, gate-keep merges (tests + reviewer sign-off) | No |
| **engineer** | [`.claude/agents/engineer.md`](.claude/agents/engineer.md) | Implement one specific issue, open a PR, address reviewer feedback (never merges) | Yes |
| **reviewer** | [`.claude/agents/reviewer.md`](.claude/agents/reviewer.md) | Spec-compliance + code-quality review on open PRs (read-only) | No |
| **qa** | [`.claude/agents/qa.md`](.claude/agents/qa.md) | Find problems, open GitHub issues (never fixes) | No |
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
Team Leader dispatches qa       → finds issues
Team Leader dispatches analyst  → researches strategy/risk issues, writes docs/research/
Team Leader dispatches lead     → triages, sets status:ready
Team Leader dispatches engineer → implements on branch, opens PR
Team Leader dispatches reviewer → spec + quality review (verdict: APPROVED | NEEDS_CHANGES)
Team Leader dispatches engineer → addresses NEEDS_CHANGES (loop until APPROVED)
Team Leader dispatches lead     → confirms tests + reviewer APPROVED, merges PR
Team Leader dispatches docs     → updates README / CLAUDE.md / CURRENT_CONFIG
```

**Every change goes through a PR.** No direct commits to `main`.
