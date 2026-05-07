# Issue #177 Polish Follow-Up — Design

**Date:** 2026-05-07
**Status:** Draft (awaiting user approval)
**Issue:** [#177](https://github.com/sv-tmueller/trading-bot/issues/177)
**Owner:** Team Leader (main session)

## Problem

PR #176 adopted the superpowers workflow. Per-task and cross-cutting reviews surfaced 9 polish items — none Critical, none Important, all explicitly deferred from #176 to keep its scope tight. Issue #177 captures them as a single follow-up.

## Decision

Apply all 9 items from issue #177 verbatim, plus two formatting defaults already approved (item 5 as intro paragraph in qa.md; item 6 in engineer.md Step 2).

## Out of scope

- Production code (`agents/`, `tools/`, `monitor/`, `storage/`, `main.py`, `config/settings.py`, `tests/`).
- New tests (no behaviour change).
- The `CLAUDE_AGENT_NO_BROKER` mechanical guard or the architectural-invariants section in `CLAUDE.md`.
- New superpowers skills (we're polishing existing wiring, not adding capabilities).
- Anything in `docs/handover/` or `docs/research/`.

## Per-file change plan

| File | Items | Edit |
|---|---|---|
| `TEAM.md` | 1, 2 | (a) Tighten the line at TEAM.md:48 to use literal verdict strings (`✅ Spec compliant` / `Ready to merge: Yes`). (b) Replace `NEEDS_CHANGES` shorthand in the workflow ASCII at TEAM.md:97,104 with the literal verdict strings (`❌ Issues found` / `Ready to merge: No`), or add a footnote. |
| `.claude/agents/engineer.md` | 3, 6 | (a) Add a worktree-orientation one-liner near the top (reference `superpowers:using-git-worktrees`, suggest a `git status` sanity check at task start). (b) In Step 2 of "Your job" (Implement what the task specifies), append a sentence wiring `superpowers:systematic-debugging` for bug-fix tasks. |
| `.claude/agents/qa.md` | 4, 5 | (a) Add a `CLAUDE_AGENT_NO_BROKER` mention near step 1's `pytest` invocation: the autouse conftest fixture is the safety net; if `BrokerCallBlockedError` fires, it's a signal of an unmocked path, not a bug to silence. (b) Add an intro paragraph at the top of `## Playbook`: "For any failure-detection step (1, 5, 6, 8), apply `superpowers:systematic-debugging` discipline before filing the issue body." |
| `CLAUDE.md` | 7 | At the row for `superpowers:test-driven-development`, clarify the parenthetical `(+ testing-anti-patterns)` — it's a sibling `.md` inside the TDD skill directory, not a standalone skill. Tighten to `(see also testing-anti-patterns.md inside that skill's directory)` or similar. |
| `.claude/skills/add-or-extend-agent/SKILL.md` | 9 | Add a one-line note in the testing conventions section: when the `CLAUDE_AGENT_NO_BROKER` mechanical guard fires (`BrokerCallBlockedError`), treat it as a signal that a broker call needs mocking — do NOT set `CLAUDE_AGENT_NO_BROKER=` to silence the failure. |
| `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md` | 8 | At the qa.md verification command (Task 5 Step 2 of that plan, ~line 469-470), change `# Expected: 2` to `# Expected: 1 (grep -c counts lines; both mentions are on the same line — use grep -o ... \| wc -l for occurrence count = 2)`. Cosmetic plan-doc fix only; the shipped qa.md content is correct as-is. |

## Tasks (preview — full plan in writing-plans phase)

6 implementation tasks (one per file) + final cross-cutting review + push/PR = 8 tasks. Each task: edit + verification grep + commit.

## Risks

1. **Scope creep on prompt edits.** Easy to over-edit prompts beyond the issue's specifics. Mitigation: each implementation task names the exact lines/sections to touch; reviewers will catch any drift.
2. **Order independence.** All 6 file edits are independent — no task depends on another. The plan can run sequentially in any order without conflicts.
3. **Acceptance test re-use.** This is the second dogfood of the new workflow. If the flow itself has issues, this PR will surface them. Treat any deviation from `brainstorm → plan → per-task implementer + spec-reviewer + code-quality-reviewer → 3-signal merge` as a finding to track separately (NOT a blocker for this PR's content).

## Acceptance test

After merge:
1. The 9 issue items are all addressed (verified by grep against each item's keyword).
2. No production code touched (`git diff main..<merge-commit>` shows changes confined to `.md` files).
3. Tests still pass (361 passed identically to pre-PR baseline).
4. The architectural-invariants section in CLAUDE.md is byte-identical pre/post.
5. Issue #177 closed by the merge (via `gh issue close` or PR body `Closes #177`).

## Rollback plan

`git revert <merge-commit>` — pure docs PR, no code, trivial to revert. No data migration concerns.

## References

- Issue: https://github.com/sv-tmueller/trading-bot/issues/177
- Predecessor PR: https://github.com/sv-tmueller/trading-bot/pull/176 (commit `556da16`)
- Workflow design: `docs/plans/2026-05-07-superpowers-workflow-adoption-design.md` (already on main)
- Workflow plan: `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md` (already on main; item 8 of this design touches it)
