# Agent Team Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up a four-role Claude Code session structure (Lead, Engineer, QA, Docs) backed by GitHub Issues, with a `TEAM.md` operational reference at the repo root and matching GitHub labels.

**Architecture:** `TEAM.md` at repo root is the single operational reference for all roles. `CLAUDE.md` gains a short "Team" section that points to it so every Claude Code session sees it automatically. GitHub labels provide the triage vocabulary that connects the roles.

**Tech Stack:** GitHub CLI (`gh`), Markdown, `CLAUDE.md` convention

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `TEAM.md` | Create | Operational reference — role triggers, responsibilities, session playbooks |
| `CLAUDE.md` | Modify (append) | Add "Team" section pointing to `TEAM.md` |
| GitHub labels | Create via `gh` | Triage vocabulary for Lead/QA/Engineer workflow |

---

### Task 1: Create GitHub labels

**Files:**
- No file changes — GitHub API via `gh` CLI

- [ ] **Step 1: Create type labels**

```bash
gh label create "bug" --repo sv-tmueller/trading-bot --color "d73a4a" --description "Something broken"
gh label create "enhancement" --repo sv-tmueller/trading-bot --color "a2eeef" --description "New feature or improvement"
gh label create "testing" --repo sv-tmueller/trading-bot --color "e4e669" --description "Missing or failing tests"
gh label create "documentation" --repo sv-tmueller/trading-bot --color "0075ca" --description "Docs gap"
gh label create "refactor" --repo sv-tmueller/trading-bot --color "cfd3d7" --description "Code quality, no behaviour change"
```

Expected: Each command prints the label name. If a label already exists, add `--force` to overwrite.

- [ ] **Step 2: Create priority labels**

```bash
gh label create "priority: high" --repo sv-tmueller/trading-bot --color "b60205" --description "Blocks other work or is a live issue"
gh label create "priority: medium" --repo sv-tmueller/trading-bot --color "e99695" --description "Important, next sprint"
gh label create "priority: low" --repo sv-tmueller/trading-bot --color "f9d0c4" --description "Nice to have"
```

- [ ] **Step 3: Create status labels**

```bash
gh label create "status: ready" --repo sv-tmueller/trading-bot --color "0e8a16" --description "Prioritized by Lead, Engineer can pick up"
gh label create "status: in-progress" --repo sv-tmueller/trading-bot --color "fbca04" --description "Engineer is working on it"
gh label create "status: blocked" --repo sv-tmueller/trading-bot --color "e4e669" --description "Waiting on something external"
```

- [ ] **Step 4: Verify labels exist**

```bash
gh label list --repo sv-tmueller/trading-bot
```

Expected output includes all 11 labels: bug, enhancement, testing, documentation, refactor, priority: high, priority: medium, priority: low, status: ready, status: in-progress, status: blocked.

- [ ] **Step 5: Commit placeholder (no files changed — note in git log)**

```bash
git commit --allow-empty -m "chore: create GitHub issue labels for team workflow"
```

---

### Task 2: Create TEAM.md

**Files:**
- Create: `TEAM.md`

- [ ] **Step 1: Write TEAM.md**

Create `/TEAM.md` with this exact content:

```markdown
# Team

Four Claude Code session roles for developing and maintaining this project. Each role runs in a separate session. GitHub Issues is the single source of truth.

## Starting a session

Tell Claude which role to play at the start of every session:

| Say this | Role |
|---|---|
| `Act as Lead` | Triage and prioritize GitHub Issues |
| `Act as Engineer` | Implement the top-priority ready issue |
| `Act as QA` | Discover bugs and gaps, open GitHub Issues |
| `Act as Docs` | Update documentation based on recent changes |

---

## Lead

**Responsibility:** Triage open issues, set priorities, tell the Engineer what to work on next.

**Session playbook:**
1. `gh issue list --repo sv-tmueller/trading-bot` — fetch all open issues
2. Triage any unlabeled issues: add a type label (`bug`, `enhancement`, `testing`, `documentation`, `refactor`) and a priority label (`priority: high/medium/low`)
3. Add `status: ready` to the top 3–5 issues the Engineer should tackle next
4. Post a one-line comment on each `status: ready` issue explaining the priority rationale
5. Output a session summary: what was triaged, what the Engineer should tackle first

**Does not:** write code, open new issues, or implement anything.

---

## Engineer

**Responsibility:** Implement the highest-priority ready issue. Close it when done.

**Session playbook:**
1. `gh issue list --repo sv-tmueller/trading-bot --label "status: ready"` — fetch ready issues
2. Pick the highest-priority one (`priority: high` first, then `priority: medium`)
3. Add `status: in-progress` label: `gh issue edit <N> --add-label "status: in-progress" --remove-label "status: ready"`
4. Implement — follow all patterns in `CLAUDE.md`
5. Run `python3 -m pytest` — all tests must be green before closing
6. Commit with `closes #N` in the message, which auto-closes the issue on push

**Does not:** open new issues, skip tests, or close issues before tests pass.

---

## QA

**Responsibility:** Find problems and report them as GitHub Issues. Never fix them.

**Session playbook:**
1. Run `python3 -m pytest` — open a `bug` + `priority: high` issue for each failure
2. Scan for `TODO` and `FIXME` in the codebase: `grep -rn "TODO\|FIXME" --include="*.py" .`
3. Check test coverage gaps: `python3 -m pytest --tb=no -q` and review which modules lack test files
4. Review last 10 commits for changes without matching test updates: `git log --oneline -10`
5. Open a GitHub Issue for each finding with the appropriate type label and a clear reproduction step or description

**Issue template to use:**
```
**What:** [one sentence description]
**Where:** [file:line or area of the codebase]
**Why it matters:** [impact if left unfixed]
**Reproduction / evidence:** [command output, test name, or grep result]
```

**Does not:** implement fixes, edit code, or close issues.

---

## Docs

**Responsibility:** Keep README, CLAUDE.md, and inline docs in sync with the code.

**Session playbook:**
1. `git log --oneline -10` — identify what changed since the last docs update
2. For each change: does the README need updating? (commands, architecture, config, setup)
3. Does `CLAUDE.md` need updating? (new patterns, constraints, or conventions introduced)
4. Are there any open `documentation` issues that are now resolved? Close them.
5. Commit all doc updates in one commit: `git commit -m "docs: update docs for recent changes"`

**Does not:** change code behaviour, open issues for code bugs, or skip the git log review.

---

## GitHub Label Reference

| Label | Set by | Meaning |
|---|---|---|
| `bug` | QA / Lead | Something broken |
| `enhancement` | QA / Lead | New feature or improvement |
| `testing` | QA | Missing or failing tests |
| `documentation` | QA / Docs | Docs gap |
| `refactor` | QA / Lead | Code quality, no behaviour change |
| `priority: high` | Lead | Blocks other work or is a live issue |
| `priority: medium` | Lead | Important, next sprint |
| `priority: low` | Lead | Nice to have |
| `status: ready` | Lead | Engineer can pick up |
| `status: in-progress` | Engineer | Being worked on |
| `status: blocked` | Engineer | Waiting on something external |

## Workflow

```
QA opens issue (type label)
  → Lead triages: adds priority + status:ready
    → Engineer picks up: adds status:in-progress, implements, closes
      → Docs reviews git log, updates docs, closes documentation issues
```
```

- [ ] **Step 2: Verify the file reads correctly**

```bash
head -5 TEAM.md
```

Expected:
```
# Team

Four Claude Code session roles for developing and maintaining this project. Each role runs in a separate session. GitHub Issues is the single source of truth.
```

- [ ] **Step 3: Commit**

```bash
git add TEAM.md
git commit -m "docs: add TEAM.md — four-role Claude Code session structure"
```

---

### Task 3: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (append section at end)

- [ ] **Step 1: Append Team section to CLAUDE.md**

Add the following block at the very end of `CLAUDE.md`:

```markdown

## Team

This project uses a four-role Claude Code session structure. See [`TEAM.md`](TEAM.md) for the full playbook.

| Say this at session start | Role |
|---|---|
| `Act as Lead` | Triage and prioritize GitHub Issues |
| `Act as Engineer` | Implement the top-priority ready issue |
| `Act as QA` | Discover bugs and gaps, open GitHub Issues |
| `Act as Docs` | Update documentation based on recent changes |
```

- [ ] **Step 2: Verify CLAUDE.md ends with the Team section**

```bash
tail -12 CLAUDE.md
```

Expected output is the Team section table above.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Team section to CLAUDE.md pointing to TEAM.md"
```

---

## Self-Review

**Spec coverage:**
- ✅ `TEAM.md` created with all four role playbooks
- ✅ CLAUDE.md updated with Team section
- ✅ GitHub labels created (11 labels: 5 type, 3 priority, 3 status)
- ✅ Workflow sequence documented

**Placeholder scan:** No TBDs, no incomplete steps.

**Consistency:** Label names used in `TEAM.md` match exactly what is created in Task 1. `gh` commands use repo `sv-tmueller/trading-bot` throughout.
