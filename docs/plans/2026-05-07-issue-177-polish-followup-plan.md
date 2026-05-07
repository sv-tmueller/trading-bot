# Issue #177 Polish Follow-Up — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the 9 polish items from issue #177 (deferred from PR #176): TEAM.md verdict-string copy + workflow shorthand footnote, engineer.md worktree pointer + Phase 4 systematic-debugging, qa.md `CLAUDE_AGENT_NO_BROKER` mention + extended systematic-debugging via intro paragraph, CLAUDE.md testing-anti-patterns clarification, add-or-extend-agent SKILL.md `BrokerCallBlockedError` debugging signal, and a plan-doc `grep -c` off-by-one cosmetic fix.

**Architecture:** 6 file edits, all `.md` polish, ~150 line diff total. No production code, no tests, no architectural-invariant impact. Each task is a focused single-file edit with verification grep + commit.

**Tech Stack:** Markdown only.

**Spec:** `docs/plans/2026-05-07-issue-177-polish-followup-design.md` (commit `1c47de1` on branch `docs/177-polish-followup`).

---

## File Structure

| File | Items | Edit summary |
|---|---|---|
| `TEAM.md` | 1, 2 | Tighten line 48 to literal verdict strings; add a verdict-string footnote after the workflow code block. |
| `.claude/agents/engineer.md` | 3, 6 | Add worktree-orientation paragraph after the opening line; append `superpowers:systematic-debugging` reference to Step 2 of "Your job". |
| `.claude/agents/qa.md` | 4, 5 | Add `superpowers:systematic-debugging` intro paragraph at top of `## Playbook`; rewrite step 1 to add `CLAUDE_AGENT_NO_BROKER` debugging signal mention and remove the now-redundant inline systematic-debugging text. |
| `CLAUDE.md` | 7 | Tighten the `(+ testing-anti-patterns)` parenthetical on the test-driven-development row. |
| `.claude/skills/add-or-extend-agent/SKILL.md` | 9 | In the "Hard rule" subsection of Testing conventions, update the outdated "no code-level guard" sentence to reference PR #168 and add a `BrokerCallBlockedError as a debugging signal` paragraph. |
| `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md` | 8 | Cosmetic: change the qa.md verification command's `# Expected: 2` to `# Expected: 1` and explain the line-vs-occurrence count difference. |

---

### Task 1: TEAM.md — verdict-string copy polish + workflow footnote

**Files:**
- Modify: `TEAM.md`

**Why:** Item 1 (TEAM.md:48) — replace generic "✅ / Ready to merge" with the literal verdict strings each reviewer emits. Item 2 (workflow ASCII at TEAM.md:97,104) — `NEEDS_CHANGES` is shorthand; add a footnote rather than splitting the diagram into per-reviewer paths.

- [ ] **Step 1: Edit line 48 (the third bullet under "What it does")**

In `TEAM.md` find the line beginning with `- Per-task: dispatches`. Current text:

```
- Per-task: dispatches `engineer` (implementer) → `spec-reviewer` → `code-quality-reviewer`. Loops `engineer` ↔ each reviewer on `❌` verdicts until both return ✅ / Ready to merge.
```

Replace with:

```
- Per-task: dispatches `engineer` (implementer) → `spec-reviewer` → `code-quality-reviewer`. Loops `engineer` ↔ each reviewer on `❌` verdicts until `spec-reviewer` returns `✅ Spec compliant` AND `code-quality-reviewer` returns `Ready to merge: Yes`.
```

- [ ] **Step 2: Add verdict-string footnote after the workflow code block**

In `TEAM.md` find the closing ` ``` ` of the workflow code block (line ~119) followed by the line `**Every change goes through a PR.** No direct commits to \`main\`.`

INSERT a new paragraph between the closing ``` and the "Every change goes through a PR" line. The structure becomes:

```
... (existing diagram) ...
```                                              ← existing closing fence

**Verdict-string note:** `NEEDS_CHANGES` in the diagram is shorthand for any `❌` outcome that triggers an engineer re-dispatch. The literal verdicts emitted by each reviewer are: `spec-reviewer` returns `✅ Spec compliant` or `❌ Issues found`; `code-quality-reviewer` returns `Ready to merge: Yes | No | With fixes`.

**Every change goes through a PR.** No direct commits to `main`.        ← existing line
```

(Insert the new "**Verdict-string note:** ..." paragraph + a blank line on either side, between the closing fence and the existing "Every change" line.)

- [ ] **Step 3: Verify**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup

# Old phrasing gone
grep -c "until both return ✅ / Ready to merge" TEAM.md
# Expected: 0

# New literal verdict strings present
grep -c "spec-reviewer\` returns \`✅ Spec compliant\` AND" TEAM.md
# Expected: 1

# Footnote present
grep -c "Verdict-string note:" TEAM.md
# Expected: 1

grep -c "Ready to merge: Yes | No | With fixes" TEAM.md
# Expected: 1
```

- [ ] **Step 4: Commit**

```bash
git add TEAM.md
git commit -m "team: tighten verdict-string copy + add NEEDS_CHANGES footnote (#177)

Item 1: line 48 now uses the literal verdict strings each reviewer emits
(✅ Spec compliant; Ready to merge: Yes).

Item 2: workflow ASCII keeps the NEEDS_CHANGES shorthand but a new footnote
explains it as 'any ❌ outcome' and lists the literal per-reviewer verdicts.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: engineer.md — worktree pointer + Phase 4 systematic-debugging

**Files:**
- Modify: `.claude/agents/engineer.md`

**Why:** Item 3 — make the worktree-discipline assumption explicit at task start. Item 6 — wire `superpowers:systematic-debugging` into the bug-fix path (Phase 4 of the systematic-debugging skill: failing test → root cause → minimal fix → verify).

- [ ] **Step 1: Insert worktree-orientation paragraph (item 3)**

In `.claude/agents/engineer.md` find this opening line (line 7):

```
You are the **Implementer** for one task in an implementation plan. The Team Leader has dispatched you with: the full task text from the plan, scene-setting context, and the working directory. Your job is that one task — not the whole plan.
```

Immediately after that line (still BEFORE the `## Before you begin` heading on line 9), insert a blank line and this new paragraph:

```
You are operating in a git worktree the Team Leader created for you (per `superpowers:using-git-worktrees`). Run `git status` at task start to confirm a clean working tree; if you see uncommitted changes you didn't make, stop and report `BLOCKED` — something is wrong with the dispatch.
```

The result: opening line → blank line → new paragraph → blank line → `## Before you begin`.

- [ ] **Step 2: Append systematic-debugging reference to Step 2 of "Your job" (item 6)**

In `.claude/agents/engineer.md` find Step 2 (line 16):

```
2. **Implement what the task specifies.** TDD when the task calls for it: failing test first, minimal pass, then commit. Frequent small commits per the plan's step granularity.
```

Replace with:

```
2. **Implement what the task specifies.** TDD when the task calls for it: failing test first, minimal pass, then commit. Frequent small commits per the plan's step granularity. **For bug-fix tasks**, apply `superpowers:systematic-debugging` discipline first: identify the root cause before proposing any fix. Find the SKILL.md via `find ~/.claude/plugins -name SKILL.md -path "*systematic-debugging*"`.
```

(Same line, with two new sentences appended after "step granularity.")

- [ ] **Step 3: Verify**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup

# Worktree pointer
grep -c "You are operating in a git worktree" .claude/agents/engineer.md
# Expected: 1

grep -c "superpowers:using-git-worktrees" .claude/agents/engineer.md
# Expected: 1

# Phase 4 systematic-debugging
grep -c "For bug-fix tasks" .claude/agents/engineer.md
# Expected: 1

grep -c "superpowers:systematic-debugging" .claude/agents/engineer.md
# Expected: 1
```

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/engineer.md
git commit -m "agents(engineer): worktree pointer + systematic-debugging Phase 4 (#177)

Item 3: explicit worktree-discipline orientation at task start, with a
git status sanity check and superpowers:using-git-worktrees reference.

Item 6: Step 2 of 'Your job' now wires superpowers:systematic-debugging
for bug-fix tasks (root cause first, before proposing any fix).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: qa.md — `CLAUDE_AGENT_NO_BROKER` mention + intro paragraph

**Files:**
- Modify: `.claude/agents/qa.md`

**Why:** Item 5 — extend `superpowers:systematic-debugging` discipline to all `bug`-issue-filing steps (1, 5, 6, 8) via a single intro paragraph, instead of repeating the reference inline at each site. Item 4 — add the `CLAUDE_AGENT_NO_BROKER` debugging-signal note to step 1's `pytest` invocation. With the intro paragraph in place, step 1's existing inline systematic-debugging text becomes redundant; remove it to keep the playbook DRY (this also makes room for the new `CLAUDE_AGENT_NO_BROKER` text without ballooning the bullet).

- [ ] **Step 1: Insert intro paragraph above the numbered list (item 5)**

In `.claude/agents/qa.md` find the `## Playbook` heading on line 9. The line immediately after is blank (line 10), and the numbered list starts at line 11.

INSERT a new paragraph between the heading and the numbered list. The result:

```
## Playbook

For any step below that opens a `bug` issue (steps 1, 5, 6, 8), apply `superpowers:systematic-debugging` discipline before filing the issue body — identify the root cause first; do not propose fixes (engineer fixes; you find and report). The skill content is at `find ~/.claude/plugins -name SKILL.md -path "*systematic-debugging*"` (no Skill tool — use `Read`).

1. **Test suite.** ...
```

(Insert the new paragraph + blank lines on both sides between the `## Playbook` heading and the existing `1. **Test suite.**` line.)

- [ ] **Step 2: Replace step 1's content (item 4 + de-dup of item 5's now-redundant inline)**

In the same file find step 1 (line 11 of the pre-edit file; line will shift due to Step 1's insertion):

```
1. **Test suite.** `python3 -m pytest`. For each failure: read the failure with `superpowers:systematic-debugging` discipline (root cause first — do not propose fixes, just identify the root cause to put in the issue body). Then open a `bug` + `priority: high` issue. You don't have the Skill tool — `Read` the SKILL.md directly: find it via `find ~/.claude/plugins -name SKILL.md -path "*systematic-debugging*"`.
```

Replace with:

```
1. **Test suite.** `python3 -m pytest`. The autouse conftest fixture sets `CLAUDE_AGENT_NO_BROKER` for the test session — if a test raises `BrokerCallBlockedError`, that's the mechanical guard catching an unmocked broker path; treat it as a missing-mock bug to fix (engineer fixes), NOT to silence (do not unset the env var). For each test failure, open a `bug` + `priority: high` issue.
```

(The intro paragraph from Step 1 already covers the systematic-debugging discipline for all `bug`-filing steps including this one, so step 1 no longer repeats it inline.)

- [ ] **Step 3: Verify**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup

# Intro paragraph present
grep -c "For any step below that opens a \`bug\` issue (steps 1, 5, 6, 8)" .claude/agents/qa.md
# Expected: 1

# Step 1 has CLAUDE_AGENT_NO_BROKER mention
grep -c "CLAUDE_AGENT_NO_BROKER" .claude/agents/qa.md
# Expected: 1

grep -c "BrokerCallBlockedError" .claude/agents/qa.md
# Expected: 1

# systematic-debugging count is now 2 (intro paragraph descriptive mention + the find command in intro), down from 2 lines that each had it
grep -o "systematic-debugging" .claude/agents/qa.md | wc -l
# Expected: 2 (intro description + find pattern; step 1's inline mention is gone, but intro contains both descriptive + find references on separate lines)

# Old inline systematic-debugging language gone from step 1
grep -c "read the failure with \`superpowers:systematic-debugging\` discipline" .claude/agents/qa.md
# Expected: 0
```

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/qa.md
git commit -m "agents(qa): intro paragraph + CLAUDE_AGENT_NO_BROKER signal (#177)

Item 5: new intro paragraph above the Playbook numbered list extends
superpowers:systematic-debugging discipline to all bug-issue-filing
steps (1, 5, 6, 8), instead of repeating the reference per-site.

Item 4: step 1's pytest line now mentions the CLAUDE_AGENT_NO_BROKER
autouse conftest fixture and explains BrokerCallBlockedError as a
missing-mock signal (not a failure to silence). The previous step 1
systematic-debugging inline mention is removed (now redundant with
the new intro paragraph).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: CLAUDE.md — testing-anti-patterns parenthetical clarification

**Files:**
- Modify: `CLAUDE.md`

**Why:** Item 7 — `(+ testing-anti-patterns)` could mislead a reader into searching for a standalone `superpowers:testing-anti-patterns` skill. It's a sibling `.md` inside the `test-driven-development/` skill directory.

- [ ] **Step 1: Edit the test-driven-development row in the Workflow/Skill/Wired-into table**

In `CLAUDE.md` find this row (line ~26):

```
| Test-driven discipline | `superpowers:test-driven-development` (+ `testing-anti-patterns`) | engineer (referenced from `.claude/agents/engineer.md`) |
```

Replace with:

```
| Test-driven discipline | `superpowers:test-driven-development` (see also `testing-anti-patterns.md` inside that skill's directory — sibling reference, not a standalone skill) | engineer (referenced from `.claude/agents/engineer.md`) |
```

- [ ] **Step 2: Verify**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup

# Old vague parenthetical gone
grep -c "(+ \`testing-anti-patterns\`)" CLAUDE.md
# Expected: 0

# New explicit clarification present
grep -c "sibling reference, not a standalone skill" CLAUDE.md
# Expected: 1

grep -c "testing-anti-patterns.md\` inside that skill's directory" CLAUDE.md
# Expected: 1
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): clarify testing-anti-patterns is a sibling, not a skill (#177)

Item 7: the parenthetical (+ testing-anti-patterns) on the
superpowers:test-driven-development row could be misread as referring
to a standalone superpowers:testing-anti-patterns skill. Tightened to
make explicit it's a sibling .md inside the TDD skill's directory.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: add-or-extend-agent SKILL.md — `BrokerCallBlockedError` as a debugging signal

**Files:**
- Modify: `.claude/skills/add-or-extend-agent/SKILL.md`

**Why:** Item 9 — when the mechanical guard fires during a test, it's a signal of an unmocked broker path; treat it as a missing-mock bug to fix, not a failure to silence by unsetting the env var. While we're touching this section, the existing "there is currently no code-level guard" sentence is now outdated (PR #168 added exactly that guard) — update it in the same edit so the section stays internally consistent.

- [ ] **Step 1: Update the "no code-level guard" sentence (line 107)**

In `.claude/skills/add-or-extend-agent/SKILL.md` find this paragraph at line 107:

```
Engineer subagents inherit `/opt/trading-bot/.env` via the parent shell. Any test, `python -c`, or `python main.py scan` invocation from a worktree submits real orders to the live paper account — there is currently no code-level guard. All `tools/broker.py` submission helpers (`place_market_order`, `place_parent_market_order`, `place_oco_brackets`, `cancel_all_orders`, `liquidate_all_positions`) MUST be mocked. If you need to verify against a real broker, use a separate sandbox account with explicitly-set env vars, NOT the inherited live keys. Team Leader briefs for any task touching `tools/broker.py`, `agents/team_leader.py::place_order`, or anything that calls them must restate this rule.
```

Replace with:

```
Engineer subagents inherit `/opt/trading-bot/.env` via the parent shell. Any `python -c` or `python main.py scan` invocation from a worktree submits real orders to the live paper account. **`pytest` is now backstopped by the `CLAUDE_AGENT_NO_BROKER` mechanical guard (PR #168) — the autouse conftest fixture sets it for the test session and any unmocked call raises `BrokerCallBlockedError` before reaching Alpaca.** All `tools/broker.py` submission helpers (`place_market_order`, `place_parent_market_order`, `place_oco_brackets`, `cancel_all_orders`, `liquidate_all_positions`) MUST be mocked. If you need to verify against a real broker, use a separate sandbox account with explicitly-set env vars, NOT the inherited live keys. Team Leader briefs for any task touching `tools/broker.py`, `agents/team_leader.py::place_order`, or anything that calls them must restate this rule.
```

(Two changes: drop "test" from the list of execution paths since pytest is now guarded; replace "— there is currently no code-level guard." with the bolded sentence about `CLAUDE_AGENT_NO_BROKER` + `BrokerCallBlockedError`.)

- [ ] **Step 2: Add `BrokerCallBlockedError` debugging-signal paragraph**

In the same file find line 109 (the italics paragraph that ends the Hard rule subsection):

```
_2026-05-06: six SIMPLE-class market BUY orders for AMD ×4, GOOG, MSFT escaped from an Engineer worktree, draining buying power from $99k to $2,239. Surgically cancelled before market open. See issue #149 and the architectural invariant in `CLAUDE.md`._
```

Immediately after that line (still BEFORE the `### Fixtures and mocks` heading on line 111), insert a blank line and this new paragraph:

```
**`BrokerCallBlockedError` is a debugging signal, not a bug to silence.** When a test raises `BrokerCallBlockedError`, the mechanical guard caught a missing mock — add the mock at the module path the caller imports from (typical patterns shown under "Fixtures and mocks" below). Do NOT unset `CLAUDE_AGENT_NO_BROKER` or set it to empty to make the failure go away; that defeats the safety net.
```

The result: italics paragraph → blank line → new paragraph → blank line → `### Fixtures and mocks`.

- [ ] **Step 3: Verify**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup

# Old "no code-level guard" claim gone
grep -c "there is currently no code-level guard" .claude/skills/add-or-extend-agent/SKILL.md
# Expected: 0

# New mechanical-guard mention present
grep -c "CLAUDE_AGENT_NO_BROKER\` mechanical guard (PR #168)" .claude/skills/add-or-extend-agent/SKILL.md
# Expected: 1

# Debugging-signal paragraph present
grep -c "BrokerCallBlockedError\` is a debugging signal" .claude/skills/add-or-extend-agent/SKILL.md
# Expected: 1

grep -c "do NOT unset \`CLAUDE_AGENT_NO_BROKER\`" .claude/skills/add-or-extend-agent/SKILL.md
# Expected: 1

# The 3 section headings around the change are unchanged
grep -c "^### Hard rule — never execute against the live Alpaca paper account" .claude/skills/add-or-extend-agent/SKILL.md
# Expected: 1

grep -c "^### Fixtures and mocks" .claude/skills/add-or-extend-agent/SKILL.md
# Expected: 1
```

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/add-or-extend-agent/SKILL.md
git commit -m "skills(add-or-extend-agent): BrokerCallBlockedError debugging signal (#177)

Item 9 + a small consistency fix in the same paragraph:

- The 'there is currently no code-level guard' sentence was outdated
  (PR #168 added the CLAUDE_AGENT_NO_BROKER mechanical guard for the
  pytest path). Replaced with an accurate statement of the guard.

- New paragraph: when a test raises BrokerCallBlockedError, treat it
  as the signal of a missing mock, not a failure to silence by
  unsetting the env var.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: superpowers-workflow-adoption-plan.md — `grep -c` off-by-one

**Files:**
- Modify: `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md`

**Why:** Item 8 — historical plan-doc cosmetic fix. The verification command for qa.md's systematic-debugging count was annotated `Expected: 2`, but `grep -c` counts matching lines (= 1, both substrings on the same line). The shipped qa.md content is correct as-is; only the plan's expected value was wrong.

- [ ] **Step 1: Update the verification expected value**

In `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md` find lines ~469-470:

```
grep -c "systematic-debugging" .claude/agents/qa.md
# Expected: 2 (description-style mention plus the find command)
```

Replace with:

```
grep -c "systematic-debugging" .claude/agents/qa.md
# Expected: 1 (grep -c counts matching lines; both mentions live on the same line in the prescribed item-1 wording — use `grep -o "systematic-debugging" .claude/agents/qa.md | wc -l` for the occurrence count = 2)
```

- [ ] **Step 2: Verify**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup

# Old expected value gone
grep -c "Expected: 2 (description-style mention plus the find command)" docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md
# Expected: 0

# New corrected expected value present
grep -c "grep -c counts matching lines; both mentions live on the same line" docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md
# Expected: 1
```

- [ ] **Step 3: Commit**

```bash
git add docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md
git commit -m "docs(plans): cosmetic plan-doc grep-c off-by-one fix (#177)

Item 8: Task 5 Step 2 verification of the prior plan said 'Expected: 2'
for grep -c systematic-debugging on qa.md. grep -c counts matching
LINES (=1); both mentions are on the same line. Substantive content
of qa.md is correct; only the plan's expected count was wrong.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Final code review of the entire branch

**Files:**
- (no file changes — review only)

**Why:** Per `superpowers:subagent-driven-development`, dispatch a final code reviewer for the entire implementation after all per-task work is done. This catches cross-task coherence issues and any residual stale references that surface only when looking at the whole branch.

- [ ] **Step 1: The Team Leader dispatches a final code reviewer subagent**

The Team Leader runs `superpowers:requesting-code-review`'s code-reviewer template with:

- `BASE_SHA`: `main` (commit `556da16`)
- `HEAD_SHA`: latest on `docs/177-polish-followup`
- DESCRIPTION: "Issue #177 polish follow-up — 6 markdown files edited per the plan."
- PLAN_OR_REQUIREMENTS: "`docs/plans/2026-05-07-issue-177-polish-followup-plan.md` Tasks 1-6."

The reviewer evaluates:
- All 9 items from issue #177 addressed?
- Cross-doc consistency (e.g., engineer.md's worktree pointer matches CLAUDE.md's intent; qa.md's `CLAUDE_AGENT_NO_BROKER` text aligns with add-or-extend-agent SKILL.md's update)?
- No collateral changes outside the 6 files in the plan?
- Architectural-invariants section in CLAUDE.md still byte-identical to `main`?
- Tests still pass (no production code touched)?

If the reviewer flags Critical or Important issues, the Team Leader dispatches a fix-implementer to address them on the same branch, then re-reviews until clean.

---

### Task 8: Push branch and open PR

**Files:**
- (no file changes — git operations only)

**Why:** Final step — push the branch to origin, open the PR with `Closes #177` in the body, hand off to lead for the 3-signal merge gate.

- [ ] **Step 1: Verify branch state**

```bash
cd /opt/trading-bot/.claude/worktrees/177-polish-followup
git status
# Expected: clean tree on docs/177-polish-followup

git log --oneline main..HEAD | wc -l
# Expected: ≥7 commits (design + plan + 6 implementation tasks; possibly plus residual fixes)
```

- [ ] **Step 2: Run pytest as verification-before-completion baseline**

```bash
/opt/trading-bot/venv/bin/python -m pytest --tb=line -q 2>&1 | tail -10
# Expected: 361 passed, 1 warning (matches main; this PR touches no production code so test count is unchanged)
```

- [ ] **Step 3: Push the branch**

```bash
git push -u origin docs/177-polish-followup
```

- [ ] **Step 4: Open the PR with `Closes #177`**

```bash
gh pr create --title "docs: issue #177 polish follow-up (post-superpowers-adoption)" --body "$(cat <<'EOF'
## Summary

Applies the 9 polish items from issue #177 (deferred from PR #176):

- **TEAM.md** — verdict-string copy polish + workflow ASCII `NEEDS_CHANGES` footnote.
- **`engineer.md`** — explicit worktree pointer + `superpowers:systematic-debugging` Phase 4 wiring on Step 2.
- **`qa.md`** — intro paragraph extends `systematic-debugging` to all `bug`-filing steps (1, 5, 6, 8); step 1 now mentions `CLAUDE_AGENT_NO_BROKER` and `BrokerCallBlockedError` as a missing-mock signal.
- **CLAUDE.md** — `testing-anti-patterns` parenthetical clarified as a sibling reference, not a standalone skill.
- **`add-or-extend-agent` SKILL.md** — outdated "no code-level guard" sentence updated to reference PR #168; new `BrokerCallBlockedError` debugging-signal paragraph.
- **Prior plan doc** — cosmetic `grep -c` off-by-one fix.

## Spec & Plan

- Spec: `docs/plans/2026-05-07-issue-177-polish-followup-design.md`
- Plan: `docs/plans/2026-05-07-issue-177-polish-followup-plan.md`

This is the second dogfood of the new superpowers workflow (brainstorming → writing-plans → subagent-driven-development with engineer + spec-reviewer + code-quality-reviewer per task).

## Test plan

- [x] All 9 items from issue #177 addressed (one task per file in the implementation plan).
- [x] No production code touched — `python3 -m pytest` count identical to `main` (361 passed).
- [x] Architectural invariants section in CLAUDE.md byte-identical to `main`.
- [x] Final cross-cutting code review: Ready to push and open PR — Yes.

Closes #177.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Capture PR URL**

```bash
gh pr view --json url --jq .url
# Expected: a github.com/sv-tmueller/trading-bot/pull/<N> URL
```

---

## Self-Review

I checked this plan against the spec at `docs/plans/2026-05-07-issue-177-polish-followup-design.md`:

**Spec coverage:**
- ✅ Item 1 (TEAM.md:48 verdict-string) — Task 1 Step 1
- ✅ Item 2 (TEAM.md NEEDS_CHANGES shorthand → footnote) — Task 1 Step 2
- ✅ Item 3 (engineer.md worktree pointer) — Task 2 Step 1
- ✅ Item 4 (qa.md CLAUDE_AGENT_NO_BROKER mention) — Task 3 Step 2
- ✅ Item 5 (qa.md extend systematic-debugging via intro paragraph) — Task 3 Step 1
- ✅ Item 6 (engineer.md Phase 4 systematic-debugging) — Task 2 Step 2
- ✅ Item 7 (CLAUDE.md testing-anti-patterns clarification) — Task 4 Step 1
- ✅ Item 8 (plan grep-c off-by-one) — Task 6 Step 1
- ✅ Item 9 (add-or-extend-agent SKILL.md BrokerCallBlockedError signal) — Task 5 Steps 1+2
- ✅ Final cross-cutting review — Task 7
- ✅ Push + PR with `Closes #177` — Task 8

**Placeholder scan:** No "TBD", "TODO", "implement later", "Add appropriate error handling", or "similar to Task N" in this plan. All file paths exact; all replacement strings verbatim.

**Type / name consistency:**
- Worktree path used consistently: `/opt/trading-bot/.claude/worktrees/177-polish-followup/` everywhere.
- File paths use the exact same casing across tasks.
- Commit message subjects all reference `(#177)` for traceability.
- Task 5's edit notes that it bundles two changes (the outdated-sentence fix + the new debugging-signal paragraph) — this is intentional scope expansion; the design doc covers it under the "include while we're touching this section" justification. Flagged for reviewer awareness.

**One known intentional bundling:** Task 5 includes both the BrokerCallBlockedError paragraph (item 9 verbatim) AND a small fix to an outdated "no code-level guard" sentence in the same paragraph. The design doc (Out of scope section) does NOT explicitly authorize the latter, but the two are tightly coupled — without the sentence update, the section would internally contradict itself (saying "no code-level guard" while immediately telling readers to debug `BrokerCallBlockedError` from that very guard). Reviewer should confirm this minor scope expansion is acceptable; if not, drop the sentence update and accept the resulting one-line internal inconsistency, file separately.

No issues found that need fixing inline. Plan stands.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-05-07-issue-177-polish-followup-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Recommendation: Option 1 (subagent-driven).** PR #176 dogfooded option 2 (inline) because the meta-PR was creating the very flow it would be merged under. THIS PR has the new flow already in place on `main` — running it via subagent-driven-development is the cleanest second dogfood, and validates that the engineer + spec-reviewer + code-quality-reviewer chain works end-to-end on a real (small) issue.

**Which approach?**
