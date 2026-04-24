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
4. Post a one-line comment on each `status: ready` issue explaining the priority rationale: `gh issue comment <N> --body "Prioritized: <reason>"`

Note: `critical` label supersedes `priority: high` — preserve it if already set on an issue.

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
6. Commit with `closes #N` in the message and push directly to `main`. This auto-closes the issue. If working on a branch, close the issue manually after the PR merges: `gh issue close <N>`

**Does not:** open new issues, skip tests, or close issues before tests pass.

---

## QA

**Responsibility:** Find problems and report them as GitHub Issues. Never fix them.

**Session playbook:**
1. Run `python3 -m pytest` — open a `bug` + `priority: high` issue for each failure
2. Scan for `TODO` and `FIXME` in the codebase: `grep -rn "TODO\|FIXME" --include="*.py" .`
3. Check test coverage gaps by cross-referencing source modules against test files:
   `ls agents/ tools/ monitor/` — source modules
   `ls tests/test_agents/ tests/` — test files
   Open a `testing` issue for any source module with no corresponding test file.
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

**Responsibility:** Keep README and CLAUDE.md in sync with the code.

**Session playbook:**
1. `git log --oneline -10` — identify what changed since the last docs update
2. For each change: does the README need updating? (commands, architecture, config, setup)
3. Does `CLAUDE.md` need updating? (new patterns, constraints, or conventions introduced)
4. Are there any open `documentation` issues that are now resolved? Close them.
5. Commit all doc updates in one commit with a `docs:` prefix and a subject naming the specific documents updated, e.g. `git commit -m "docs: update README and CLAUDE.md for <feature>"`

**Does not:** change code behaviour, open issues for code bugs, or skip the git log review.

---

## GitHub Label Reference

| Label | Set by | Meaning |
|---|---|---|
| `bug` | QA / Lead | Something broken |
| `critical` | QA / Lead | High-severity bug; supersedes `priority: high` |
| `enhancement` | QA / Lead | New feature or improvement |
| `strategy` | Lead | Strategic or architectural improvement |
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
