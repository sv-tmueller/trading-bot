# Team

The main Claude Code session always acts as **Team Leader** — it orchestrates the four specialist roles (Lead, Engineer, QA, Docs) by dispatching them as registered Claude Code subagents. You never need to start a new session or switch contexts. Just tell the Team Leader what you want to accomplish.

The role playbooks live as subagent definitions in [`.claude/agents/`](.claude/agents/). Each `.md` file is the source of truth for that role — `TEAM.md` is the human-readable index.

---

## How to use

Start a session and state your intent. The Team Leader decides which subagent to dispatch:

| Say this | Team Leader will… |
|---|---|
| `Triage open issues` | Dispatch **lead** to label, prioritize, and set `status: ready` |
| `Work on the issues` | Dispatch **lead** then **engineer** per issue, with spec + quality reviews |
| `Run QA` | Dispatch **qa** to discover bugs and open issues |
| `Update docs` | Dispatch **docs** to sync README and CLAUDE.md |
| Anything else | Team Leader assesses and coordinates as needed |

Run `/agents` in Claude Code to inspect the registered subagents.

---

## Roles

| Role | File | Responsibility | Can edit code? |
|---|---|---|---|
| **Team Leader** | _(main session)_ | Orchestrate other roles, run reviews, dispatch merges, dispatch docs updates | No (delegates) |
| **lead** | [`.claude/agents/lead.md`](.claude/agents/lead.md) | Triage issues, set priorities, review and merge PRs | No |
| **engineer** | [`.claude/agents/engineer.md`](.claude/agents/engineer.md) | Implement one specific issue, open a PR (never merges own work) | Yes |
| **qa** | [`.claude/agents/qa.md`](.claude/agents/qa.md) | Find problems, open GitHub issues (never fixes) | No |
| **docs** | [`.claude/agents/docs.md`](.claude/agents/docs.md) | Sync README, CLAUDE.md, TEAM.md, CURRENT_CONFIG with code | Docs only |

---

## Team Leader (main session)

The main session **is** the Team Leader. It is not a registered subagent — it is the session itself.

**What it does:**
- Reads GitHub Issues and decides which role to invoke.
- Dispatches each subagent with the exact context it needs (no shared session state).
- After each Engineer task, runs a spec compliance review then a code quality review.
- Dispatches `lead` to merge PRs once both reviews pass.
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
Team Leader dispatches lead     → triages, sets status:ready
Team Leader dispatches engineer → implements on branch, opens PR
Team Leader runs spec review    → engineer fixes gaps
Team Leader runs quality review → engineer fixes issues
Team Leader dispatches lead     → confirms tests, merges PR
Team Leader dispatches docs     → updates README / CLAUDE.md
```

**Every change goes through a PR.** No direct commits to `main`.
