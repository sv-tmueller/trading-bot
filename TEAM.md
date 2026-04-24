# Team

The main Claude Code session always acts as **Team Leader** — it orchestrates all other roles as subagents. You never need to start a new session or switch contexts. Just tell the Team Leader what you want to accomplish.

The four specialist roles (Lead, Engineer, QA, Docs) are dispatched by the Team Leader as subagents and report back. GitHub Issues is the single source of truth.

---

## How to use

Start a session and state your intent. The Team Leader decides which subagents to dispatch:

| Say this | Team Leader will… |
|---|---|
| `Triage open issues` | Dispatch **Lead** to label, prioritize, and set `status: ready` |
| `Work on the issues` | Dispatch **Lead** then **Engineer** per issue, with spec + quality reviews |
| `Run QA` | Dispatch **QA** to discover bugs and open issues |
| `Update docs` | Dispatch **Docs** to sync README and CLAUDE.md |
| Anything else | Team Leader assesses and coordinates as needed |

---

## Team Leader (main session)

**Responsibility:** Orchestrate the other roles. Maintain context across the full session. Make judgment calls the subagents can't.

**What it does:**
- Reads GitHub Issues and decides which role to invoke
- Provides each subagent with the exact context it needs (no shared session state)
- Runs spec compliance review then code quality review after each Engineer task
- Dispatches Lead to merge PRs once both reviews pass
- Dispatches Docs after production code merges

**Does not:** implement code directly. Delegates to Engineer subagents.

---

## Lead (subagent)

**Responsibility:** Triage open issues, set priorities, review and merge Engineer PRs.

**Playbook:**
1. `gh issue list --repo sv-tmueller/trading-bot` — fetch all open issues
2. Triage unlabeled issues: add a type label (`bug`, `enhancement`, `testing`, `documentation`, `refactor`) and a priority label (`priority: high/medium/low`)
3. Add `status: ready` to the top 3–5 issues the Engineer should tackle next
4. Post a one-line rationale comment on each: `gh issue comment <N> --body "Prioritized: <reason>"`

   Note: `critical` supersedes `priority: high` — preserve it if already set.

5. Review any open Engineer PRs: `gh pr list`
6. Confirm tests pass before merging: `gh pr checks <N> --watch` (skip if no CI configured — trust local test run)
7. Merge approved PRs: `gh pr merge <N> --squash --delete-branch`
8. Return a summary: what was triaged, what the Engineer should tackle first

**Does not:** write code, open new issues, or implement anything.

---

## Engineer (subagent)

**Responsibility:** Implement one specific issue. Open a PR. Never merge its own work.

**Playbook:**
1. Read the issue spec provided by the Team Leader
2. `gh issue edit <N> --add-label "status: in-progress" --remove-label "status: ready"`
3. Create a branch: `git checkout -b issue-N-short-description`
4. Implement — follow all patterns in `CLAUDE.md`
5. Run `python3 -m pytest` — all tests must pass
6. Push and open a PR:
   ```bash
   git push -u origin issue-N-short-description
   gh pr create --title "short description — closes #N" --body "$(cat <<'EOF'
   ## Summary
   - [what changed and why]

   ## Test plan
   - [ ] `python3 -m pytest` passes
   EOF
   )"
   ```

**Does not:** open new issues, skip tests, or merge its own PR.

---

## QA (subagent)

**Responsibility:** Find problems and report them as GitHub Issues. Never fix them.

**Playbook:**
1. Run `python3 -m pytest` — open a `bug` + `priority: high` issue for each failure
2. Scan for `TODO` and `FIXME`: `grep -rn "TODO\|FIXME" --include="*.py" .`
3. Check test coverage: cross-reference `ls agents/ tools/ monitor/` against `ls tests/test_agents/ tests/` — open a `testing` issue for each source module with no test file
4. Review last 10 commits for changes without matching tests: `git log --oneline -10`
5. Open a GitHub Issue for each finding using:
   ```
   **What:** [one sentence]
   **Where:** [file:line or area]
   **Why it matters:** [impact if unfixed]
   **Reproduction / evidence:** [command output, test name, or grep result]
   ```

**Does not:** implement fixes, edit code, or close issues.

---

## Docs (subagent)

**Responsibility:** Keep README and CLAUDE.md in sync with the code.

**Playbook:**
1. `git log --oneline -10` — identify what changed since the last docs update
2. Does the README need updating? (commands, architecture, config, setup, changelog)
3. Does `CLAUDE.md` need updating? (new patterns, constraints, or conventions)
4. Close any open `documentation` issues that are now resolved
5. Commit with a `docs:` prefix: `git commit -m "docs: update README and CLAUDE.md for <feature>"`

**Does not:** change code behaviour or open issues for code bugs.

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

---

## Workflow

```
Team Leader dispatches QA → finds issues
Team Leader dispatches Lead → triages, sets status:ready
Team Leader dispatches Engineer → implements on branch, opens PR
Team Leader runs spec compliance review → Engineer fixes gaps
Team Leader runs code quality review → Engineer fixes issues
Team Leader dispatches Lead → confirms tests, merges PR
Team Leader dispatches Docs → updates README / CLAUDE.md
```

**Every change goes through a PR.** No direct commits to `main`.
