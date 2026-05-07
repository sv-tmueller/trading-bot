**Date:** 2026-05-07 (UTC)
**Slug:** superpowers-adoption
**Author:** Claude Code session (claude-opus-4-7)

## 1. Sit-rep

The bot is in its normal post-v1.14 operating state on `main` at commit `d09ccc8`. **No production code changed this session.** What did change: the project adopted the [`superpowers`](https://github.com/obra/superpowers) plugin (v5.1.0, MIT, installed via `/plugin install superpowers@claude-plugins-official`) as the **canonical workflow playbook** — the new Team-Leader flow is `superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:subagent-driven-development` → `superpowers:finishing-a-development-branch` → 3-signal Lead merge gate. The single-pass `reviewer` subagent was deleted and replaced by **two** subagents (`spec-reviewer` for pass-1 spec compliance; `code-quality-reviewer` for pass-2 quality + architectural invariants). The `engineer` subagent was rewritten from issue-level to task-level. Two PRs landed both via the new flow: **#176** (the meta workflow rewrite, 18 commits, 3 review-loop iterations) and **#178** (a 9-item polish follow-up to #176, 8 commits, **zero** review-loop iterations — the second pass ran clean). The discipline tightens fast with practice.

## 2. In-flight branches & PRs

- **PR #176** — `team: adopt superpowers workflow (engineer + reviewer rewrite)` (state: **merged**, squash commit `556da16`).
  - **Purpose** — adopt superpowers as the canonical workflow + preserve safety stack.
  - **Status** — done. Architectural invariants block byte-identical between deleted `reviewer.md` and new `code-quality-reviewer.md` (md5 `a716544dc31b9a885003e5f7bead4576`).
  - **Next action** — none.

- **PR #178** — `docs: issue #177 polish follow-up (post-superpowers-adoption)` (state: **merged**, squash commit `d09ccc8`).
  - **Purpose** — apply 9 deferred polish items from #176's reviews (TEAM.md verdict-strings, engineer.md worktree pointer + Phase 4 systematic-debugging, qa.md intro + `CLAUDE_AGENT_NO_BROKER` mention, CLAUDE.md `testing-anti-patterns` clarification, `add-or-extend-agent` SKILL.md `BrokerCallBlockedError` debugging-signal, prior-plan grep-c off-by-one).
  - **Status** — done. Closed issue #177 via `Closes #177`.
  - **Next action** — none.

- **PR #116** _(not this session)_ — `docs: simplify README quickstart SSH line` (state: **open** since 2026-05-04). Has its own worktree at `.claude/worktrees/readme-ssh-tweak`.
  - **Next action** — older session's docs PR; review and merge or close. Out of this session's scope.

- **PR #93** _(not this session)_ — `feat(brokers): BaseBroker ABC + AlpacaBroker adapter` (state: **draft** since 2026-04-30).
  - **Next action** — abandoned-looking; review draft, decide to land or close. Out of this session's scope.

## 3. Open issues being worked

- **`#177` — Post-superpowers-adoption polish (follow-up to #176)** — labels `documentation`, `priority: low`. **State: closed** (auto-closed by PR #178 merge).
  - **What we learned** — Filed by Team Leader (not QA) collecting reviewer feedback from PR #176. Each item had file:line references; the implementation plan (PR #178) was a clean dogfood of the new flow.
  - **Next move** — done. A future session running on the next backlog issue is the natural third dogfood.

- **Deferred-but-not-filed minors from PR #178 reviews** _(Minor items, not blocking, not yet ticketed)_:
  - `qa.md:11` intro paragraph enumerates `(steps 1, 5, 6, 8)`; step 2 (TODO/FIXME scan) can also open `bug` issues — enumeration could be `(steps 1, 2, 5, 6, 8)`.
  - `docs/plans/2026-05-07-superpowers-workflow-adoption-plan.md:470` footnote prose says "in the prescribed item-1 wording" but post-Task-3 the two `systematic-debugging` mentions live in the new intro paragraph (line 11), not item 1 (line 13). Numerical claim is correct; only the location label is mildly stale.
  - **Next move** — file as a single `documentation`/`priority: low` issue if a future session has a slow afternoon. Or roll into the next polish-follow-up PR opportunistically.

## 4. Decisions made this session

- **Decision** — Adopt superpowers plugin as **canonical** project playbook, replacing conflicting parts of TEAM.md / agent .md files with superpowers-driven equivalents.
  - **Rationale** — User chose Option A from the friction analysis (`docs/plans/2026-05-07-superpowers-workflow-adoption-design.md`): full install with conflicts replaced, rather than Option B (uninstall + cherry-pick). Honors the discipline of the upstream skill library; avoids hand-built reinventions.
  - **Consequence** — Any future workflow change first checks if a `superpowers:` skill exists; the superpowers playbook wins where it conflicts with older inline guidance. Architectural invariants in CLAUDE.md remain authoritative for the safety stack — preserved verbatim in `code-quality-reviewer.md`.

- **Decision** — Honor `superpowers:brainstorming` HARD-GATE on **every** change, regardless of size.
  - **Rationale** — User explicit opt-in: "brainstorm is used for everything in superpowers regardless of simple q/a or big strat? Go for it. I want it." (this session, 2026-05-07).
  - **Consequence** — Even one-line typo fixes go through brainstorm → spec → plan → implementation. Spec doc can be short ("a few sentences for truly simple projects" per the skill) but is still required. Codified in `TEAM.md:121-123`.

- **Decision** — Plans and design docs live at `docs/plans/<date>-<slug>-{design,plan}.md`, **not** the superpowers default `docs/superpowers/specs/`.
  - **Rationale** — User redirected at brainstorming time to avoid a third top-level docs tree (alongside existing `docs/research/` and `docs/handover/`).
  - **Consequence** — When invoking `superpowers:writing-plans` or `superpowers:brainstorming`, override the default path to `docs/plans/`.

- **Decision** — Replace single-pass `reviewer` subagent with two subagents: `spec-reviewer` (pass-1) + `code-quality-reviewer` (pass-2).
  - **Rationale** — Matches the superpowers `subagent-driven-development` pattern. Two-stage review separates "did you build what was asked" from "is what you built well-built", with fresh-context dispatch each time.
  - **Consequence** — Lead's merge gate is now **3 signals** (tests + spec-reviewer ✅ + code-quality-reviewer Ready-to-merge), not 2. Architectural-invariant violations from code-quality-reviewer are always blocking.

- **Decision** — `engineer` subagent rewritten from issue-level (do whole issue end-to-end including PR) to task-level (one task from a plan; report DONE; never opens PRs).
  - **Rationale** — Matches superpowers implementer pattern; PR-opening moves to Team Leader via `superpowers:finishing-a-development-branch`.
  - **Consequence** — Engineer dispatch is now per-task (N dispatches per PR, where N = plan task count). Team Leader handles PR-opening + dispatching Lead for merge.

- **Decision** — Broker-execution prohibition added to BOTH `spec-reviewer.md` and `code-quality-reviewer.md` Hard rules (in addition to `engineer.md`'s existing rule and the `CLAUDE_AGENT_NO_BROKER` mechanical guard).
  - **Rationale** — Defense-in-depth flagged as Critical by code-quality-reviewer during PR #176 Task 2 review. Reviewers have `Bash` access; without the rule, a literal-minded subagent told to "verify everything independently" could trip the mechanical guard.
  - **Consequence** — Five independent layers now protect against agent-context broker calls: (1) `engineer.md` Hard rule, (2) `spec-reviewer.md` Hard rule, (3) `code-quality-reviewer.md` Hard rule, (4) CLAUDE.md architectural invariants, (5) `CLAUDE_AGENT_NO_BROKER` autouse conftest fixture (PR #168 mechanical guard).

- **Decision** — `BrokerCallBlockedError` is a **debugging signal**, not a failure to silence by unsetting `CLAUDE_AGENT_NO_BROKER`. Codified in `add-or-extend-agent/SKILL.md`.
  - **Rationale** — A future implementer encountering this error in a test must understand it indicates a missing mock, not a bug in the test infrastructure. The "no code-level guard" sentence in the same skill section was outdated post-#168 and was updated in the same edit.
  - **Consequence** — When a test path hits `BrokerCallBlockedError`, the fix is to add the mock at the module path the caller imports from — never to unset/empty the env var.

## 5. Open questions

- **Should the writing-plans skill template tighten its verification commands to avoid the line-vs-occurrence and capital-vs-lowercase patterns that surfaced twice in this session?**
  - **What blocks the answer** — needs a few more dogfooded plans to confirm whether the imprecision pattern repeats. Two data points (PR #176 Task 5 grep-c off-by-one; PR #178 Task 5 capital-D-vs-lowercase-d) is suggestive but not statistically meaningful.
  - **Suggested next step** — capture as a follow-up observation in a future polish issue once a third plan ships. No action this session.

- **Are the deferred Minor items from PR #178 reviews worth filing as a single low-priority issue, or should they roll into the next opportunistic polish PR?**
  - **What blocks the answer** — user judgment on backlog hygiene.
  - **Suggested next step** — ask the user if and when they want a third polish-follow-up issue filed. Not blocking.

- **Do the older open PRs (#116 docs SSH; #93 BaseBroker draft) belong in the new flow's backlog, or are they out-of-scope holdovers?**
  - **What blocks the answer** — user decision; #93 has been in DRAFT since 2026-04-30 with no recent commits.
  - **Suggested next step** — user reviews and either revives, abandons, or hands to Lead-triage.

## 6. Files to read first

- `CLAUDE.md:14-37` — new "Superpowers skills are the canonical playbooks" section. The skill→agent wiring map and the precedence rule ("superpowers playbook wins where it conflicts").
- `TEAM.md:1-123` — rewritten `## How to use`, `## Roles`, `## Workflow` sections + the brainstorming HARD-GATE call-out in the trailing paragraph.
- `.claude/agents/engineer.md:1-9` — frontmatter + worktree-orientation paragraph (PR #178 added) + `## Before you begin`. The Hard rules section starting at line 24 contains the broker-mocking rule (preserved verbatim from PR #176).
- `.claude/agents/spec-reviewer.md:1-59` — the entire pass-1 reviewer prompt. Note Hard rule on broker-execution at line 57.
- `.claude/agents/code-quality-reviewer.md:46-58` — Architectural invariants block (byte-identical to the deleted `reviewer.md`).
- `.claude/agents/qa.md:9-15` — new intro paragraph + step 1 with `CLAUDE_AGENT_NO_BROKER` debugging-signal text.
- `.claude/agents/lead.md:18-28, 36` — 3-signal merge gate playbook + Hard rule update.
- `.claude/skills/add-or-extend-agent/SKILL.md:105-113` — Hard rule subsection now mentions PR #168 mechanical guard + new `BrokerCallBlockedError` debugging-signal paragraph.
- `docs/plans/2026-05-07-superpowers-workflow-adoption-design.md` — the WHY for the workflow change. Spec preservation rules. Acceptance test #6 (verbatim diff).
- `docs/plans/2026-05-07-issue-177-polish-followup-plan.md` — example of a clean, byte-exact plan that ran with zero review-loop iterations. Use as a template for future plans.

## 7. Don't forget

Session-specific (above the standing list):

- **`superpowers:brainstorming` HARD-GATE applies to every change** — even a one-line typo fix. User explicit opt-in. Plans for trivial work can be short, but must exist in `docs/plans/<date>-<slug>-{design,plan}.md` and get user approval.
- **Plans path is `docs/plans/`**, not the superpowers default `docs/superpowers/specs/`. Override the skill default at write time.
- **Subagents have no `Skill` tool** — they access skill content via `Read` on `find ~/.claude/plugins -name SKILL.md -path "*<skill>*"` paths. Pin this in any new subagent dispatch.
- **`reviewer` subagent no longer exists** — the `.claude/agents/reviewer.md` file was deleted in PR #176 (commit `032c958`). Dispatching `subagent_type: "reviewer"` will fail. Use `spec-reviewer` then `code-quality-reviewer`.
- **Lead's merge gate is 3 signals**, not 2: tests pass + `spec-reviewer` returns `✅ Spec compliant` + `code-quality-reviewer` returns `Ready to merge: Yes`. Architectural-invariant violations from code-quality-reviewer are always blocking.
- **Architectural invariants are byte-identical** between `CLAUDE.md` § "Architectural invariants" and `.claude/agents/code-quality-reviewer.md` § "Architectural invariants". Editing either without editing the other breaks the verbatim-preservation acceptance criterion.
- **Worktree convention** — handover branches go in `.claude/worktrees/handover-<slug>/`. Feature/issue branches go in `.claude/worktrees/<slug>/`. Never branch/commit against the main `/opt/trading-bot` checkout.

Standing list (always relevant):

- The LLM must never control risk parameters directly. Stops and targets come from `tools/risk.py`; the position monitor is rule-based; only `TeamLeaderAgent` places orders, and only with pre-approved values.
- Stops and take-profits execute server-side via Alpaca **OCO bracket orders submitted post-fill** (anchored to actual fill price via `_poll_for_fill`). The position monitor is defence-in-depth, not the primary exit mechanism.
- Morning scan must run **pre-market** (cron `25 13 * * 1-5` UTC). Running after 13:30 UTC produces ~zero `volume_ratio` and kills every entry.
- `TRADING_PAUSED=true` halts new entries but does not affect the position monitor. `python main.py panic` is the deterministic kill button.
- Free Alpaca paper accounts require `DataFeed.IEX`; live SIP requires a paid account. Controlled via `DATA_FEED` env var.
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime).
- Engineer subagents must never execute against the live Alpaca paper account. `pytest` is backstopped by the `CLAUDE_AGENT_NO_BROKER` autouse conftest fixture (PR #168 mechanical guard); any unmocked broker call raises `BrokerCallBlockedError`. **Treat that error as a missing-mock signal, not a failure to silence.**

## 8. Suggested next prompts

Order by priority — paste the first one if you only have time for one thing.

1. **`Triage open issues`** — there are ~20 open issues in the backlog (mostly low-priority docs/refactor from a prior QA pass; a few `priority: high` bugs at #155 / #154 / #153). Lead will label, prioritize, and set `status: ready` on the top 3-5. This is the most valuable single move because it sets up the next several sessions of work.

2. **`Work on issue #155`** — third dogfood of the new flow on a real `priority: high` bug (`_poll_for_fill` timeout silently writes phantom trade row with pre-order quote). Touches `agents/team_leader.py` and likely `tools/broker.py`-adjacent code, so this exercises the engineer.md broker-mocking discipline and the `add-or-extend-agent` SKILL.md test-conventions for real. The first dogfood (#176) had 3 Critical fix loops; the second (#178) had zero. The third will tell us whether zero is the new floor.

3. **`Work on issue #154`** — alternative `priority: high` bug (partial-fill OCO mismatch leaves position unprotected). Similar safety-stack territory to #155; pick whichever the user prefers. Working both as separate PRs would double the dogfood data.

4. **`Run QA`** — fresh QA pass post-workflow-change. Especially valuable to confirm the new agent set (`spec-reviewer`, `code-quality-reviewer`) doesn't have rough edges that the meta-PR's reviews missed. QA opens issues; the new flow will dispatch them.

5. **`Open an issue collecting the deferred Minor items from PR #178 reviews`** — the qa.md step-2 enumeration polish + the prior-plan footnote prose-location label staleness. Single low-priority `documentation` issue. Opportunistic — only if you want backlog hygiene before picking up real work.
