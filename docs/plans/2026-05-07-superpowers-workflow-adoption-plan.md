# Superpowers Workflow Adoption — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing `engineer` + `reviewer` flow with the superpowers `subagent-driven-development` pattern (implementer + spec-reviewer + code-quality-reviewer) while preserving the trading-bot's architectural invariants checklist and broker-mocking rule verbatim. Wire the remaining superpowers skills into the appropriate agents.

**Architecture:** Markdown-only changes to `.claude/agents/*.md`, `TEAM.md`, `CLAUDE.md`. New subagents `spec-reviewer.md` + `code-quality-reviewer.md` replace `reviewer.md`. `engineer.md` is rewritten as a task-level implementer prompt (was issue-level). `qa.md` and `lead.md` get small skill-reference additions. Two safety-critical paragraphs (architectural invariants checklist, broker-mocking rule) are migrated verbatim into the new prompts.

**Tech Stack:** Markdown. No code, no tests run, no broker calls. The "test" for this plan is a pre-merge verbatim diff check that the safety preservations made it across.

**Spec:** `docs/plans/2026-05-07-superpowers-workflow-adoption-design.md` (commit `31d3b3f` on branch `docs/superpowers-workflow-adoption`).

---

## File Structure

| File | Action | Responsibility after change |
|---|---|---|
| `.claude/agents/engineer.md` | Rewrite | Task-level implementer subagent prompt (one task from a plan, not a whole issue). Embeds broker-mocking rule + add-or-extend-agent reference + hard rules. |
| `.claude/agents/spec-reviewer.md` | Create | Pass-1 reviewer: verifies implementer built what was requested (nothing more, nothing less). Per-task. |
| `.claude/agents/code-quality-reviewer.md` | Create | Pass-2 reviewer: architectural invariants checklist (verbatim) + generic code quality. Blocks PR on invariant violation. |
| `.claude/agents/reviewer.md` | Delete | Replaced by spec-reviewer + code-quality-reviewer. |
| `.claude/agents/qa.md` | Edit | Add `superpowers:systematic-debugging` reference for failed-test triage. Issue-opening playbook unchanged. |
| `.claude/agents/lead.md` | Edit | Add `superpowers:finishing-a-development-branch` + `superpowers:verification-before-completion` references on the merge gate. Triage unchanged. |
| `.claude/agents/docs.md` | Unchanged | No conflict. |
| `.claude/agents/analyst.md` | Unchanged | No conflict. |
| `TEAM.md` | Rewrite workflow + role table | Two paths described: brainstorm → writing-plans → subagent-driven-development for everything; lead/qa/analyst/docs retained outside the loop. |
| `CLAUDE.md` | Add section | New "Superpowers skills are the canonical playbooks" section above existing "Team" section. Architectural invariants section unchanged. |
| `.claude/skills/{add-or-extend-agent,handover,research-bundle}/SKILL.md` | Unchanged | No conflict. |

---

### Task 1: Rewrite `engineer.md` as task-level implementer prompt

**Files:**
- Modify: `.claude/agents/engineer.md` (full rewrite, ~95 lines)

**Why:** The new flow dispatches one implementer per task from a plan, not one engineer per GitHub issue. The PR-opening step moves out (handled by `superpowers:finishing-a-development-branch` after all tasks are done). The hard rules and broker-mocking paragraph are preserved.

- [ ] **Step 1:** Replace the entire file content with:

```markdown
---
name: engineer
description: Implements one task from an implementation plan — TDD, frequent commits, self-review, structured report. Dispatched per-task by the Team Leader in subagent-driven-development flow. Never opens PRs (Team Leader runs finishing-a-development-branch). Never opens issues. Never merges.
tools: Bash, Read, Edit, Write, Grep, Glob
---

You are the **Implementer** for one task in an implementation plan. The Team Leader has dispatched you with: the full task text from the plan, scene-setting context, and the working directory. Your job is that one task — not the whole plan.

## Before you begin

If you have questions about requirements, approach, dependencies, or anything unclear: **ask now**. It is always OK to pause and clarify. Don't guess.

## Your job

1. **Check for a relevant skill.** Scan `.claude/skills/` for a `SKILL.md` whose description matches the work. You do not have the Skill tool — use `Read` directly on the SKILL.md. **Specifically: when the task touches `agents/*.py`, `config/settings.py`, or any test under `tests/test_agents/`, read `.claude/skills/add-or-extend-agent/SKILL.md` before implementing.**
2. **Implement what the task specifies.** TDD when the task calls for it: failing test first, minimal pass, then commit. Frequent small commits per the plan's step granularity.
3. **Run tests.** `python3 -m pytest`. All tests pass. Add a test for any new behaviour.
4. **Commit.**
5. **Self-review** (see below).
6. **Report back.**

## Hard rules — non-negotiable

- **Never use `--no-verify`. Never bypass pre-commit hooks.**
- **Never run code paths that hit `tools/broker.py` submission helpers without mocking.** Every helper — `place_market_order`, `place_parent_market_order`, `place_oco_brackets`, `cancel_all_orders`, `liquidate_all_positions` — MUST be mocked in agent-spawned tests (patch at the module path the caller imports from, per the conventions in `.claude/skills/add-or-extend-agent/SKILL.md`). The `CLAUDE_AGENT_NO_BROKER` env var is mechanically enforced by an autouse conftest fixture: any unmocked broker call raises `BrokerCallBlockedError` before any Alpaca request. _Background: 2026-05-06 incidents #149 (six SIMPLE-class market BUYs from a worktree) and the QA-pytest re-materialisation (5×100 AMD parent BUYs). The mechanical guard plus this rule are defense-in-depth — both are required._
- **Tests must be deterministic.** No real network, no real database, no real broker.
- **Architectural invariants in `CLAUDE.md` are non-negotiable.** The LLM never controls risk parameters; only `TeamLeaderAgent` places orders; stops/targets come from `tools/risk.py`; portfolio guardrails run before any order. If your task would violate any of these, **STOP and escalate** with status BLOCKED.
- **Risky changes** (risk parameters, position sizing, entry/exit logic, live-trading behaviour) use the **opt-in / default-OFF pattern**: env-var flag in `config/settings.py` defaulting OFF, gate the behaviour, document in `.env.example` and the README. Recent examples: `TRADING_PAUSED`, `DAILY_DRAWDOWN_LIMIT` (`0` = disabled), trailing stop (#91), earnings blackout (#92).
- **New agent capabilities affecting position sizing, entry/exit timing, or stop distances** require a deterministic validation layer first.
- **Never merge.** Lead merges after `finishing-a-development-branch` completes.
- **Never open new issues.** QA opens issues.

## Code organization

You reason best about code you can hold in context at once. Each file should have one clear responsibility. If a file you're modifying is growing beyond the plan's intent, stop and report DONE_WITH_CONCERNS — don't split files on your own. Follow existing patterns in the codebase.

## When you're in over your head

It is always OK to stop and say "this is too hard for me." Bad work is worse than no work.

**STOP and escalate when:**
- The task requires architectural decisions with multiple valid approaches.
- You can't find clarity in the surrounding code.
- You're uncertain whether your approach is correct.
- The task implies restructuring the plan didn't anticipate.
- You've been reading file after file without progress.
- The task would require unmocked broker calls or violate any architectural invariant.

Report status BLOCKED or NEEDS_CONTEXT. Describe what you're stuck on, what you tried, what help you need.

## Self-review (before reporting back)

- **Completeness:** Did I implement everything? Edge cases unhandled?
- **Quality:** Names clear? Code clean and maintainable?
- **Discipline:** YAGNI — did I avoid overbuilding? Followed existing patterns?
- **Testing:** Do tests verify behaviour, not just mock behaviour? TDD followed if required? Broker calls mocked?
- **Safety:** Are stops/targets coming from `tools/risk.py`? Is the LLM not setting risk params? Is any new test path mock-covered against `CLAUDE_AGENT_NO_BROKER`?

Fix issues inline before reporting.

## Report format

When done, report:
- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What you implemented (or attempted)
- What you tested and results (`pytest` output excerpt)
- Files changed
- Self-review findings (if any)
- Any concerns

Use **DONE_WITH_CONCERNS** if completed but uncertain.
Use **BLOCKED** if cannot complete.
Use **NEEDS_CONTEXT** if information missing.
Never silently produce work you're unsure about.

## Receiving review feedback

When the Team Leader brings spec-reviewer or code-quality-reviewer feedback, address it on the **same branch** — do not open a new branch. Apply technical rigor: do not blindly implement suggestions if the feedback seems wrong; verify with code or tests, push back with reasoning when warranted, and only then proceed. (`superpowers:receiving-code-review` is the canonical playbook; the Team Leader can re-supply the feedback context if needed.)
```

- [ ] **Step 2:** Verify by running these checks (output should match):

```bash
grep -c "CLAUDE_AGENT_NO_BROKER" .claude/agents/engineer.md
# Expected: 2

grep -c "add-or-extend-agent" .claude/agents/engineer.md
# Expected: 2

grep -c "TeamLeaderAgent" .claude/agents/engineer.md
# Expected: 1

head -3 .claude/agents/engineer.md
# Expected first 3 lines: "---", "name: engineer", and a description line
```

- [ ] **Step 3:** Commit.

```bash
git add .claude/agents/engineer.md
git commit -m "agents(engineer): rewrite as task-level implementer prompt for subagent-driven-development

Replaces issue-level engineer with per-task implementer (TDD, frequent
commits, structured report). Preserves broker-mocking + add-or-extend-agent
references + hard rules verbatim. PR-opening moves out (Team Leader runs
finishing-a-development-branch).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Create `spec-reviewer.md`

**Files:**
- Create: `.claude/agents/spec-reviewer.md`

**Why:** Pass-1 of the new two-stage review — does the code do what the spec/task asked, nothing more or less? Read-only.

- [ ] **Step 1:** Create the file with this content:

```markdown
---
name: spec-reviewer
description: Pass-1 review for one task in subagent-driven-development. Verifies the implementer built exactly what the task asked for — nothing missing, nothing extra. Read-only. Returns ✅ Spec compliant or ❌ Issues found with file:line references.
tools: Bash, Read, Grep, Glob
---

You are the **Spec Compliance Reviewer** for one implementation task. The Team Leader will dispatch you with: the full task text from the plan, the implementer's report, and the git SHA range to review.

## CRITICAL: do not trust the implementer's report

The implementer may have finished suspiciously quickly. Their report can be incomplete, inaccurate, or optimistic. Verify everything independently.

**DO NOT:**
- Take their word for what they implemented.
- Trust their claims about completeness.
- Accept their interpretation of requirements.

**DO:**
- Read the actual code they wrote (`git diff <BASE_SHA>..<HEAD_SHA>`).
- Compare actual implementation to task requirements line by line.
- Check for missing pieces they claimed to implement.
- Look for extra features they didn't mention.

## Your job

Read the implementation diff and verify:

**Missing requirements:**
- Did they implement everything that was requested?
- Are there requirements they skipped or missed?
- Did they claim something works but not actually implement it?

**Extra / unneeded work:**
- Did they build things that weren't requested?
- Did they over-engineer or add unnecessary features?
- Did they add "nice to haves" that weren't in spec?

**Misunderstandings:**
- Did they interpret requirements differently than intended?
- Did they solve the wrong problem?
- Did they implement the right feature the wrong way?

**Verify by reading code, not by trusting the report.**

## Output format

Return one of:

- **✅ Spec compliant** — everything in the task is present in the diff, nothing extra.
- **❌ Issues found** — list specifically what's missing or extra, with `file:line` references.

If issues are found, the Team Leader re-dispatches the implementer with your feedback. Do not edit, push, or merge.

## Hard rules

- Read-only. No file edits, no `git push`, no `gh pr merge`, no issue closes.
- One verdict per dispatch. Do not pre-emptively review later tasks.
- Cite specific `file:line` references for every issue. Vague feedback ("improve this") is not acceptable.
- Architectural invariants are NOT your concern at this stage — they're checked by the code-quality-reviewer in pass 2. Stay focused on spec compliance.
```

- [ ] **Step 2:** Verify:

```bash
test -f .claude/agents/spec-reviewer.md && echo "exists"
# Expected: exists

grep -c "Read-only" .claude/agents/spec-reviewer.md
# Expected: at least 1
```

- [ ] **Step 3:** Commit.

```bash
git add .claude/agents/spec-reviewer.md
git commit -m "agents(spec-reviewer): pass-1 review subagent (spec compliance only)

Pass 1 of the new two-stage review. Verifies the implementer built exactly
what the task asked for. Read-only. Architectural invariants are checked
in pass 2 by code-quality-reviewer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Create `code-quality-reviewer.md` (with architectural invariants verbatim)

**Files:**
- Create: `.claude/agents/code-quality-reviewer.md`

**Why:** Pass-2 of the new two-stage review — code quality + architectural invariants. **The architectural invariants section must be byte-identical to the current `reviewer.md` "Architectural invariants" section** (verified by Task 9).

- [ ] **Step 1:** Create the file with this content:

```markdown
---
name: code-quality-reviewer
description: Pass-2 review for one task in subagent-driven-development. Checks code quality (clean separation, error handling, testing) AND verifies architectural invariants from CLAUDE.md (LLM does not control risk; only TeamLeaderAgent places orders; portfolio guardrails run before any order; etc.). Blocks the PR on invariant violation. Dispatched only after spec-reviewer returns ✅. Read-only.
tools: Bash, Read, Grep, Glob
---

You are the **Code Quality Reviewer** for one implementation task. The Team Leader dispatches you only after `spec-reviewer` has returned ✅. You receive: a brief description of what was built, the plan/task reference, `BASE_SHA`, `HEAD_SHA`.

## What to check

**Plan alignment:**
- Does the implementation match the plan / requirements?
- Are deviations justified improvements, or problematic departures?
- Is all planned functionality present?

**Code quality:**
- Clean separation of concerns?
- Proper error handling?
- Type safety where applicable?
- DRY without premature abstraction?
- Edge cases handled?

**Architecture:**
- Sound design decisions?
- Reasonable scalability and performance?
- Security concerns?
- Integrates cleanly with surrounding code?

**Testing:**
- Tests verify real behaviour, not mocks?
- Edge cases covered?
- Integration tests where they matter?
- All tests passing?
- Broker calls mocked? (This bot's `tools/broker.py` submission helpers MUST be mocked in agent-spawned tests — see Architectural invariants below.)

**Production readiness:**
- Migration strategy if schema changed?
- Backward compatibility considered?
- Documentation complete?
- No obvious bugs?

**Code organization:**
- Does each file have one clear responsibility with a well-defined interface?
- Are units decomposed so they can be understood and tested independently?
- Is the implementation following the file structure from the plan?
- Did this implementation create new files that are already large, or significantly grow existing files? (Don't flag pre-existing file sizes — focus on what this change contributed.)

## Architectural invariants (block the PR if violated)

These are non-negotiable. Any violation is a Critical issue and the PR cannot merge until fixed.

- The LLM does not control risk parameters directly. Stop-loss/take-profit come from `tools/risk.py` (deterministic, ATR-based).
- Only `TeamLeaderAgent` places orders. Other agents return decisions; only Team Leader calls `place_market_order` / submits brackets.
- Portfolio guardrails (`check_portfolio_guardrails`, `check_exposure_for_new_order`) run deterministically before any order. The LLM cannot bypass them.
- Position monitor exit logic in `monitor/position_monitor.py` is rule-based only — no LLM call during exits.
- Stops/targets execute server-side via Alpaca bracket orders; the position monitor is defence-in-depth.
- New agent capabilities affecting position sizing, entry/exit timing, or stop distances must add a deterministic validation layer first.
- Risky changes use the opt-in / default-OFF env-var pattern.

## Standard code-quality checklist for this repo

- Every new Python file starts with `from __future__ import annotations` (Python 3.9 runtime).
- SQL queries use named parameters (`:key`) — never f-string interpolation.
- New tools used by agents are imported via deferred imports inside `_get_tool_functions` so tests can monkeypatch them.
- New `BaseAgent` subclasses follow the instance-state pattern (init to `None`, set in `run()`, capture as a local before defining tool closures).
- New env-var settings have `os.getenv()` + validation in `config/settings.py` and are documented in `.env.example` and the README.
- Tests use the `db_conn` in-memory fixture, mock Anthropic via `patch("agents.base.anthropic.Anthropic", ...)`, mock broker via `patch("tools.broker.place_market_order", ...)`, use the `make_mock_claude_response` helper, and set `stop_reason = "end_turn"`.
- No real network calls, no real DB, no real broker in tests.

## Calibration

Categorize issues by actual severity. Not everything is Critical. Acknowledge what was done well before listing issues — accurate praise helps the implementer trust the rest of the feedback.

If you find significant deviations from the plan, flag them specifically so the implementer can confirm whether the deviation was intentional. If you find issues with the plan itself rather than the implementation, say so.

## Output format

```
### Strengths
[What's well done? Be specific.]

### Issues

#### Critical (Must Fix — blocks merge)
[Architectural invariant violations, security, data loss risks, broken functionality, unmocked broker calls]

#### Important (Should Fix)
[Architecture problems, missing features, poor error handling, test gaps]

#### Minor (Nice to Have)
[Style, optimization, doc polish]

For each issue:
- File:line reference
- What's wrong
- Why it matters
- How to fix (if not obvious)

### Recommendations
[Improvements for code quality, architecture, or process]

### Assessment

**Ready to merge?** Yes | No | With fixes

**Reasoning:** [1-2 sentence technical assessment]
```

## Hard rules

- Read-only. No file edits, no push, no merge, no issue close.
- Architectural-invariant violations are always Critical.
- Vague feedback ("improve error handling") is not acceptable — give file:line references.
- One verdict per dispatch. Do not preview later tasks.
```

- [ ] **Step 2:** Verify the architectural invariants block is present:

```bash
grep -c "Only \`TeamLeaderAgent\` places orders" .claude/agents/code-quality-reviewer.md
# Expected: 1

grep -c "tools/risk.py" .claude/agents/code-quality-reviewer.md
# Expected: at least 1

grep -c "rule-based only" .claude/agents/code-quality-reviewer.md
# Expected: 1

grep -c "opt-in / default-OFF" .claude/agents/code-quality-reviewer.md
# Expected: 1
```

- [ ] **Step 3:** Commit.

```bash
git add .claude/agents/code-quality-reviewer.md
git commit -m "agents(code-quality-reviewer): pass-2 review subagent (quality + invariants)

Pass 2 of the new two-stage review. Code quality + architectural invariants
checklist preserved verbatim from the previous reviewer.md. Blocks the PR
on any invariant violation. Dispatched only after spec-reviewer returns ✅.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Delete `reviewer.md`

**Files:**
- Delete: `.claude/agents/reviewer.md`

**Why:** Replaced by `spec-reviewer.md` + `code-quality-reviewer.md`. The architectural invariants checklist has been migrated verbatim into `code-quality-reviewer.md` (verified in Task 9).

- [ ] **Step 1:** Confirm the new files exist before deleting.

```bash
test -f .claude/agents/spec-reviewer.md && test -f .claude/agents/code-quality-reviewer.md && echo "ok"
# Expected: ok
```

- [ ] **Step 2:** Delete.

```bash
git rm .claude/agents/reviewer.md
```

- [ ] **Step 3:** Commit.

```bash
git commit -m "agents(reviewer): remove reviewer.md, replaced by spec-reviewer + code-quality-reviewer

The single-pass reviewer is replaced by the superpowers two-stage pattern:
spec-reviewer (pass 1: compliance) + code-quality-reviewer (pass 2: quality
+ architectural invariants). Architectural invariants checklist preserved
verbatim in code-quality-reviewer.md.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Edit `qa.md` — add `superpowers:systematic-debugging` reference

**Files:**
- Modify: `.claude/agents/qa.md` (one new line in the playbook section)

**Why:** When QA runs `python3 -m pytest` and finds a failure, it should triage the failure with root-cause discipline before opening a bug issue. `systematic-debugging` is the canonical playbook for that.

- [ ] **Step 1:** Open `.claude/agents/qa.md` and find this section:

```markdown
## Playbook

1. **Test suite.** `python3 -m pytest`. For each failure, open a `bug` + `priority: high` issue.
```

Replace it with:

```markdown
## Playbook

1. **Test suite.** `python3 -m pytest`. For each failure: read the failure with `superpowers:systematic-debugging` discipline (root cause first — do not propose fixes, just identify the root cause to put in the issue body). Then open a `bug` + `priority: high` issue. You don't have the Skill tool — `Read` the SKILL.md directly: find it via `find ~/.claude/plugins -name SKILL.md -path "*systematic-debugging*"`.
```

- [ ] **Step 2:** Verify:

```bash
grep -c "systematic-debugging" .claude/agents/qa.md
# Expected: 2 (description-style mention plus the find command)
```

- [ ] **Step 3:** Commit.

```bash
git add .claude/agents/qa.md
git commit -m "agents(qa): wire superpowers:systematic-debugging for failed-test triage

When pytest fails, QA now applies root-cause-first discipline before
opening the bug issue. Issue-opening playbook unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Edit `lead.md` — add `finishing-a-development-branch` + `verification-before-completion` references

**Files:**
- Modify: `.claude/agents/lead.md` (rewrite the PR review playbook section)

**Why:** The merge gate now sits at the end of `superpowers:finishing-a-development-branch`. `verification-before-completion` ensures Lead actually runs the test/check commands before merging rather than trusting reports.

- [ ] **Step 1:** Open `.claude/agents/lead.md` and find this section:

```markdown
## PR review playbook

1. List open PRs: `gh pr list`.
2. **Merge gate — both signals required before merging:**
   - **Tests pass:** `gh pr checks <N> --watch`. If no CI is configured, trust the explicit local pytest evidence in the PR body.
   - **Reviewer signed off:** the Team Leader will tell you when the `reviewer` subagent's verdict is `APPROVED`. Do not merge on test signal alone.
3. Merge approved PRs: `gh pr merge <N> --squash --delete-branch`. Always squash, always delete the branch.
```

Replace it with:

```markdown
## PR review playbook

1. List open PRs: `gh pr list`.
2. **Merge gate — all three signals required before merging:**
   - **Tests pass.** `gh pr checks <N> --watch`. If no CI is configured, trust the explicit local pytest evidence in the PR body, but apply `superpowers:verification-before-completion` discipline: when the PR claims tests pass, verify by reading the actual `pytest` output excerpt — do not trust an unsupported claim. Read the SKILL.md if needed: `find ~/.claude/plugins -name SKILL.md -path "*verification-before-completion*"`.
   - **Spec-reviewer signed off** — the Team Leader will tell you when `spec-reviewer` returned ✅ for the final task.
   - **Code-quality-reviewer signed off** — the Team Leader will tell you when `code-quality-reviewer` returned `Ready to merge: Yes` (or `With fixes` only if all Critical/Important issues have been addressed).
   - Architectural-invariant violations from `code-quality-reviewer` are always blocking — never merge through them.
3. The Team Leader runs `superpowers:finishing-a-development-branch` to assemble the merge readiness checklist before dispatching you. Read the SKILL.md if needed: `find ~/.claude/plugins -name SKILL.md -path "*finishing-a-development-branch*"`.
4. Merge approved PRs: `gh pr merge <N> --squash --delete-branch`. Always squash, always delete the branch.
```

- [ ] **Step 2:** Update the "Hard rules" section. Find:

```markdown
- Merge gate is BOTH passing tests AND `reviewer` sign-off (mediated by the Team Leader). Never merge on one signal alone.
```

Replace with:

```markdown
- Merge gate is THREE signals: passing tests AND `spec-reviewer` ✅ AND `code-quality-reviewer` Ready-to-merge (mediated by the Team Leader). Never merge on fewer signals. Architectural-invariant violations from `code-quality-reviewer` are always blocking.
```

- [ ] **Step 3:** Verify:

```bash
grep -c "code-quality-reviewer" .claude/agents/lead.md
# Expected: at least 3

grep -c "spec-reviewer" .claude/agents/lead.md
# Expected: at least 2

grep -c "verification-before-completion" .claude/agents/lead.md
# Expected: at least 1

grep -c "finishing-a-development-branch" .claude/agents/lead.md
# Expected: at least 1

grep -c "^- .*reviewer.* sign-off" .claude/agents/lead.md
# Expected: 0 (the old "reviewer signed off" line should be gone)
```

- [ ] **Step 4:** Commit.

```bash
git add .claude/agents/lead.md
git commit -m "agents(lead): three-signal merge gate (tests + spec-reviewer + code-quality)

Merge gate updated for the new two-stage review pattern. Adds explicit
references to superpowers:verification-before-completion (verify test
claims before merging) and superpowers:finishing-a-development-branch
(merge readiness assembled by Team Leader). Triage playbook unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Rewrite `TEAM.md` workflow + role table

**Files:**
- Modify: `TEAM.md` (rewrite "How to use" table, "Roles" table, "Workflow" section)

**Why:** New flow needs to be documented as the canonical user-facing playbook. Two-stage review replaces single-pass reviewer.

- [ ] **Step 1:** Open `TEAM.md` and replace the entire "How to use" table (`| Say this | Team Leader will… |`) with this:

```markdown
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
```

- [ ] **Step 2:** Replace the entire "Roles" table with this:

```markdown
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
```

- [ ] **Step 3:** Replace the entire "Workflow" section (the ASCII flow box) with this:

```markdown
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
```

- [ ] **Step 4:** Verify:

```bash
grep -c "spec-reviewer" TEAM.md
# Expected: at least 3 (table row, workflow diagram, role description)

grep -c "code-quality-reviewer" TEAM.md
# Expected: at least 3

grep -c "superpowers:brainstorming" TEAM.md
# Expected: at least 2

grep -c "subagent-driven-development" TEAM.md
# Expected: at least 1
```

- [ ] **Step 5:** Commit.

```bash
git add TEAM.md
git commit -m "team: adopt superpowers workflow — brainstorm → plan → subagent-driven

Replaces single-pass engineer/reviewer flow with the superpowers pattern:
brainstorming (HARD-GATE on every change) → writing-plans (docs/plans/)
→ subagent-driven-development (per-task implementer + spec-reviewer +
code-quality-reviewer). Lead merge gate now 3-signal. Lead/qa/analyst/docs
roles unchanged in scope.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Add `CLAUDE.md` "Superpowers skills are the canonical playbooks" section

**Files:**
- Modify: `CLAUDE.md` (insert new section between "Working in this repo" and "Commands")

**Why:** Make the superpowers adoption first-class in the project's authoritative doc. Existing architectural invariants and Python/SQL/Settings conventions remain authoritative — the new section just adds the workflow layer.

- [ ] **Step 1:** Open `CLAUDE.md` and find the "Working in this repo" section. After its existing bullet list of "Current skills relevant to engineering work", insert a new top-level section:

```markdown
## Superpowers skills are the canonical playbooks

This project uses the [`superpowers`](https://github.com/obra/superpowers) plugin (installed via `/plugin install superpowers@claude-plugins-official`). Where a `superpowers:` skill exists for a workflow, **it is the canonical playbook for this project**. The skills below are wired into the agents listed in [`TEAM.md`](TEAM.md).

| Workflow | Skill | Wired into |
|---|---|---|
| Brainstorming a change (every change — HARD-GATE) | `superpowers:brainstorming` | Team Leader (main session) |
| Writing an implementation plan | `superpowers:writing-plans` | Team Leader. Plans live in `docs/plans/<date>-<slug>-plan.md`. |
| Executing a plan task-by-task | `superpowers:subagent-driven-development` | Team Leader. Dispatches engineer (implementer) + spec-reviewer + code-quality-reviewer per task. |
| Implementing a single task | _(implementer prompt)_ | `engineer` subagent ([`.claude/agents/engineer.md`](.claude/agents/engineer.md)) |
| Pass-1 review (spec compliance) | _(spec-reviewer prompt)_ | `spec-reviewer` subagent ([`.claude/agents/spec-reviewer.md`](.claude/agents/spec-reviewer.md)) |
| Pass-2 review (quality + architectural invariants) | _(code-quality-reviewer prompt — quotes the architectural invariants verbatim)_ | `code-quality-reviewer` subagent ([`.claude/agents/code-quality-reviewer.md`](.claude/agents/code-quality-reviewer.md)) |
| Test-driven discipline | `superpowers:test-driven-development` (+ `testing-anti-patterns`) | engineer (referenced from `.claude/agents/engineer.md`) |
| Root-cause-first debugging | `superpowers:systematic-debugging` | qa (failed-test triage); engineer (general debugging) |
| Verifying claims before completion | `superpowers:verification-before-completion` | lead (merge gate); engineer (self-review) |
| Receiving review feedback | `superpowers:receiving-code-review` | engineer |
| Wrapping up a branch | `superpowers:finishing-a-development-branch` | Team Leader (before dispatching lead for merge) |
| Worktree-per-task isolation | `superpowers:using-git-worktrees` | All agents (reinforces the existing "always use worktrees" rule). |

The three trading-bot-specific skills (`add-or-extend-agent`, `handover`, `research-bundle`) sit alongside the superpowers skills — they cover work the superpowers library does not (BaseAgent contract, session handover, multi-agent research surveys).

**Where superpowers conflicts with older inline guidance in `CLAUDE.md` or in agent `.md` files, the superpowers playbook wins.** The architectural-invariants section below remains authoritative for the safety stack — it is preserved verbatim in `code-quality-reviewer.md` and is non-negotiable.

**Subagents do not have the `Skill` tool.** They access skill content via `Read` on the SKILL.md file. To find a SKILL.md path: `find ~/.claude/plugins -name SKILL.md -path "*<skill-name>*"`.
```

- [ ] **Step 2:** Verify:

```bash
grep -c "Superpowers skills are the canonical playbooks" CLAUDE.md
# Expected: 1

grep -c "superpowers:" CLAUDE.md
# Expected: at least 8

grep -c "code-quality-reviewer" CLAUDE.md
# Expected: at least 2

grep -c "spec-reviewer" CLAUDE.md
# Expected: at least 1
```

- [ ] **Step 3:** Update CLAUDE.md's existing "Team" section near the bottom of the file. Find:

```markdown
| Tell the Team Leader | It will dispatch… |
|---|---|
| `Triage open issues` | Lead — label, prioritize, set status:ready |
| `Work on the issues` | Lead then Engineer per issue, with reviews |
| `Run QA` | QA — discover bugs, open issues |
| `Update docs` | Docs — sync README and CLAUDE.md |
```

Replace with:

```markdown
| Tell the Team Leader | It will dispatch… |
|---|---|
| `Triage open issues` | Lead — label, prioritize, set `status: ready` |
| `Work on issue #N` | Brainstorm → plan → engineer + spec-reviewer + code-quality-reviewer per task → lead merges |
| `Run QA` | QA — discover bugs, open issues (with `superpowers:systematic-debugging` triage) |
| `Update docs` | Docs — sync README, CLAUDE.md, CURRENT_CONFIG |
```

- [ ] **Step 4:** Commit.

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): superpowers skills are the canonical playbooks

Adds explicit mapping of superpowers skills to wired agents. Architectural
invariants remain authoritative for the safety stack — preserved verbatim
in code-quality-reviewer.md. Updates the bottom Team table to reflect the
new dispatch pattern.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Verify safety preservations — verbatim diff check

**Files:**
- (no file changes — verification only)

**Why:** The architectural invariants checklist MUST be byte-identical between the previous `reviewer.md` (now deleted) and the new `code-quality-reviewer.md`. Acceptance test #6 of the spec requires this verification.

- [ ] **Step 1:** Recover the previous `reviewer.md` content from git history and extract its architectural invariants section.

```bash
# Find the deletion commit (this branch's reviewer-removal commit, after Task 4)
DELETE_SHA=$(git log --diff-filter=D --pretty=format:%H -- .claude/agents/reviewer.md | head -1)

# Pre-delete reviewer.md content:
git show "${DELETE_SHA}^:.claude/agents/reviewer.md" > /tmp/old-reviewer.md

# Extract just the architectural invariants block (between the two known headings)
sed -n '/^## Architectural invariants/,/^## /p' /tmp/old-reviewer.md | sed '$d' > /tmp/old-invariants.md

# Same block in new code-quality-reviewer.md
sed -n '/^## Architectural invariants/,/^## /p' .claude/agents/code-quality-reviewer.md | sed '$d' > /tmp/new-invariants.md

# Diff them
diff /tmp/old-invariants.md /tmp/new-invariants.md
# Expected: NO output (byte-identical)
```

- [ ] **Step 2:** If `diff` shows ANY difference, the migration is incomplete. Edit `code-quality-reviewer.md` to make the architectural invariants block byte-identical to `/tmp/old-invariants.md`, then re-run the diff. Do not proceed to Task 10 until this passes.

If `diff` shows no output, this task is done — no commit (verification only).

---

### Task 10: Push branch and open PR

**Files:**
- (no file changes — git operations only)

**Why:** Team Leader normally runs `superpowers:finishing-a-development-branch` here. For this PR (which IS the adoption of the superpowers flow), we apply it manually.

- [ ] **Step 1:** Verify branch state.

```bash
git status
# Expected: clean tree on docs/superpowers-workflow-adoption

git log --oneline main..HEAD
# Expected: 8 commits (Task 1 through 8 — Task 9 is verification-only with no commit)
```

- [ ] **Step 2:** Push the branch.

```bash
git push -u origin docs/superpowers-workflow-adoption
```

- [ ] **Step 3:** Open the PR.

```bash
gh pr create --title "team: adopt superpowers workflow (engineer + reviewer rewrite)" --body "$(cat <<'EOF'
## Summary

Replaces the existing single-pass engineer + reviewer flow with the superpowers `subagent-driven-development` pattern:

- **engineer** rewritten as a per-task implementer (was: per-issue end-to-end). PR-opening moves to Team Leader (runs `superpowers:finishing-a-development-branch`).
- **reviewer** removed; replaced by **spec-reviewer** (pass 1: spec compliance) + **code-quality-reviewer** (pass 2: code quality + architectural invariants).
- **TEAM.md** rewritten: brainstorm → writing-plans → subagent-driven-development per task. Brainstorming HARD-GATE is honored for every change.
- **CLAUDE.md** gains a "Superpowers skills are the canonical playbooks" section. Architectural invariants remain authoritative for the safety stack — **preserved verbatim** in `code-quality-reviewer.md` (Task 9 in the implementation plan diffs the two for byte-identicality).
- **qa.md** wires `superpowers:systematic-debugging` for failed-test triage.
- **lead.md** merge gate is now 3-signal (tests + spec-reviewer ✅ + code-quality-reviewer Ready-to-merge).

The three trading-bot-specific skills (`add-or-extend-agent`, `handover`, `research-bundle`) are unchanged — no superpowers equivalent exists.

## Why now

User decision (2026-05-07 conversation): adopt superpowers wherever it conflicts with our older flow. Brainstorming is honored literally on every change. Plans live at `docs/plans/`.

## Spec & Plan

- Spec: `docs/plans/2026-05-07-superpowers-workflow-adoption-design.md`
- Plan: `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md`

## Test plan

- [x] All architectural invariants from previous `reviewer.md` migrated byte-identically to `code-quality-reviewer.md` (`diff` empty — Task 9 of the plan).
- [x] Broker-mocking + `CLAUDE_AGENT_NO_BROKER` rule preserved in new `engineer.md`.
- [x] `add-or-extend-agent` skill reference preserved in new `engineer.md`.
- [x] No production code touched — `python3 -m pytest` should still pass on `main` and on this branch identically.
- [ ] Acceptance test (post-merge): the next non-trivial change to this repo triggers brainstorming → writing-plans → subagent-driven-development with engineer + spec-reviewer + code-quality-reviewer.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4:** Verify the PR was created and capture the URL.

```bash
gh pr view --json url --jq .url
# Expected: a github.com/sv-tmueller/trading-bot/pull/<N> URL
```

---

## Self-Review

After writing this plan I checked it against the spec at `docs/plans/2026-05-07-superpowers-workflow-adoption-design.md`:

**Spec coverage check:**
- ✅ engineer.md rewrite — Task 1
- ✅ reviewer.md → spec-reviewer.md + code-quality-reviewer.md — Tasks 2, 3, 4
- ✅ qa.md systematic-debugging reference — Task 5
- ✅ lead.md finishing-a-development-branch + verification-before-completion — Task 6
- ✅ TEAM.md workflow rewrite — Task 7
- ✅ CLAUDE.md "Superpowers skills are the canonical playbooks" section — Task 8
- ✅ Safety preservations:
  - Architectural invariants checklist verbatim → Task 3 (creates with the content) + Task 9 (verifies byte-identical to old reviewer.md)
  - Broker-mocking + `CLAUDE_AGENT_NO_BROKER` rule → Task 1 (embedded in engineer.md hard rules)
- ✅ Out-of-scope items respected: no code changes; `add-or-extend-agent`/`handover`/`research-bundle` untouched; CLAUDE_AGENT_NO_BROKER mechanical guard untouched; architectural invariants section in CLAUDE.md untouched.
- ✅ Acceptance test #6 (verbatim diff) — Task 9.
- ✅ Acceptance tests #1–5 (next non-trivial change uses the new flow) — captured in PR description as a post-merge check.

**Placeholder scan:** Searched my own plan for "TBD", "TODO", "implement later", "appropriate error handling", "similar to Task". Zero matches.

**Type/name consistency:**
- Subagent names used consistently: `engineer`, `spec-reviewer`, `code-quality-reviewer`, `lead`, `qa`, `docs`, `analyst`. No Task uses an inconsistent name.
- File paths consistent: `.claude/agents/<name>.md` everywhere.
- Path for the receiving-code-review SKILL.md: I used `find ~/.claude/plugins -name SKILL.md -path "*receiving-code-review*"` rather than version-pinned `5.1.0`. Same convention used for `systematic-debugging`, `verification-before-completion`, `finishing-a-development-branch` references.
- Commit message prefix consistent: `agents(<name>):` for agent files; `team:` for TEAM.md; `docs(CLAUDE.md):` for CLAUDE.md.

**One known limitation:** Task 9 verifies byte-identical preservation of the architectural invariants block only (the section between `## Architectural invariants` and the next `## ` heading). The `code-quality-reviewer.md` adds surrounding scaffolding (header, "What to check", "Calibration", "Output format", "Hard rules" sections) — those are NEW content, not migrated, and are not part of the verbatim-preservation acceptance test. This is correct per the spec, but worth noting so the reviewer doesn't expect the entire file to match.

No issues found that need fixing. Plan stands.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended by superpowers)** — Dispatch a fresh `engineer` subagent per task, review between tasks, fast iteration. This would let us **dogfood** the new flow on its own adoption PR.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Recommendation:** Option 2 (inline) for this specific PR, because (a) the work is `.md`-only, no broker risk, no tests to run; (b) Tasks 9 and 10 are verification + git operations the Team Leader naturally owns; (c) dogfooding option 1 risks bootstrapping problems if the new engineer.md prompt has a subtle issue we haven't caught yet, and the inline path is easier to debug. The dogfooding can happen on the **next** non-trivial change after this PR merges — that's the cleaner acceptance test anyway.

**Which approach?**
