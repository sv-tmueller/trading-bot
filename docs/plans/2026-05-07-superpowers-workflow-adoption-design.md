# Superpowers Workflow Adoption — Design

**Date:** 2026-05-07
**Status:** Draft (awaiting user approval)
**Owner:** Team Leader (main session)

## Problem

We installed the `superpowers@claude-plugins-official` plugin (v5.1.0). It ships 14 process skills plus a SessionStart hook that auto-injects `superpowers:using-superpowers` into every conversation. Several skills overlap with — and in places contradict — the workflow our `TEAM.md` + `.claude/agents/*.md` files already prescribe. The user has decided to adopt the superpowers path wherever there is a conflict, while preserving the trading-bot-specific safety mechanisms in `CLAUDE.md`.

## Decision

Replace the conflicting agent definitions and workflow conventions with superpowers-driven equivalents. Preserve the two trading-bot-specific safety mechanisms verbatim by merging them into the new prompts.

## Out of scope

- The three custom skills (`add-or-extend-agent`, `handover`, `research-bundle`) stay — no superpowers equivalent exists.
- No changes to trading-bot code (`agents/`, `tools/`, `monitor/`, `storage/`, `main.py`, `config/settings.py`).
- No changes to the `CLAUDE_AGENT_NO_BROKER` mechanical guard (PR #168) — that is the canonical broker safety boundary and is enforced at the env-var level regardless of which agent flow runs.
- No changes to the architectural invariants in `CLAUDE.md` § "Architectural invariants" — they remain non-negotiable and are surfaced to every flow that runs.

## Conflict map

| Superpowers skill | Conflicts with | Resolution |
|---|---|---|
| `subagent-driven-development` | Single-pass `engineer` + single-pass `reviewer` flow in `TEAM.md` | Replace: implementer + spec-reviewer + code-quality-reviewer pattern |
| `brainstorming` (HARD-GATE) | Issue-driven flow where the issue body IS the spec | Replace: brainstorming runs before any implementation — every change, every issue, every Q&A turn that involves implementation |
| `writing-plans` + `executing-plans` | Built-in `Plan` agent, ad-hoc planning, GitHub issue as spec | Replace: brainstorm → writing-plans (writes plan to `docs/plans/`) → executing-plans / subagent-driven-development |
| `dispatching-parallel-agents` | Anthropic guidance already in the system prompt | Compatible, no action |
| `using-git-worktrees` | `feedback_worktree_for_parallel_work` user memory | Reinforces existing rule; reference from agent prompts |
| `verification-before-completion` | `feedback_triple_check_before_shipping` user memory | Reinforces; reference from agent prompts |
| `systematic-debugging` | (gap — no existing debugging playbook) | Pure addition; reference from engineer + qa |
| `test-driven-development` (+ `testing-anti-patterns`) | Existing pytest discipline (compatible) | Reference from engineer; works with `add-or-extend-agent` |
| `receiving-code-review` | `engineer.md` NEEDS_CHANGES loop | Reference from engineer |
| `requesting-code-review` | Team Leader → reviewer dispatch | Reference from Team Leader |
| `finishing-a-development-branch` | engineer PR-open + lead merge gate | Reference from engineer + lead |

## Safety preservations (must survive the migration)

These two rules are the bot's safety net. Both must be present verbatim in the **new** prompts (implementer + code-quality-reviewer), not merely inherited from `CLAUDE.md`.

### 1. Architectural invariants checklist (currently in `reviewer.md` lines 36-44)

The reviewer (in the new flow: code-quality-reviewer subagent) MUST block the PR if any of the following are violated:

- The LLM does not control risk parameters directly. Stop-loss/take-profit come from `tools/risk.py` (deterministic, ATR-based).
- Only `TeamLeaderAgent` places orders.
- Portfolio guardrails (`check_portfolio_guardrails`, `check_exposure_for_new_order`) run deterministically before any order. The LLM cannot bypass them.
- Position monitor exit logic in `monitor/position_monitor.py` is rule-based only — no LLM call during exits.
- Stops/targets execute server-side via Alpaca bracket orders; the position monitor is defence-in-depth.
- New agent capabilities affecting position sizing, entry/exit timing, or stop distances must add a deterministic validation layer first.
- Risky changes use the opt-in / default-OFF env-var pattern.

### 2. Broker mocking + `CLAUDE_AGENT_NO_BROKER` (currently in `CLAUDE.md` § "Architectural invariants" final bullet)

The implementer (in the new flow: implementer subagent) MUST be told:

- Engineer subagents must never execute against the live Alpaca paper account.
- Every `tools/broker.py` submission helper (`place_market_order`, `place_parent_market_order`, `place_oco_brackets`, `cancel_all_orders`, `liquidate_all_positions`) MUST be mocked in agent-spawned tests (patch at the module path the caller imports from).
- The `CLAUDE_AGENT_NO_BROKER` env var is mechanically enforced (autouse conftest fixture). Any unmocked broker call from a test path raises `BrokerCallBlockedError`.
- Background: incidents 2026-05-06 #149 (six SIMPLE-class market BUYs from worktree) and the QA-pytest re-materialisation (5×100 AMD parent BUYs).

## Per-file change plan

| File | Action | Notes |
|---|---|---|
| `.claude/agents/engineer.md` | **Rewrite** | New playbook follows `superpowers:subagent-driven-development` implementer phase. Preserve from current: read-the-spec step, branch + PR steps, broker-mocking rule, `add-or-extend-agent` skill reference, hard rules. |
| `.claude/agents/reviewer.md` | **Rewrite** | Two-stage review: (1) spec-reviewer (per-acceptance-criterion check), (2) code-quality-reviewer (architectural invariants checklist preserved verbatim, plus generic code-quality patterns). |
| `.claude/agents/qa.md` | **Edit** | Add reference to `superpowers:systematic-debugging` for failed-test triage. Keep issue-opening playbook unchanged. |
| `.claude/agents/lead.md` | **Edit** | No structural change. Add reference to `superpowers:finishing-a-development-branch` and `superpowers:verification-before-completion` for merge gate. |
| `.claude/agents/docs.md` | Unchanged | No conflict. |
| `.claude/agents/analyst.md` | Unchanged | No conflict. |
| `TEAM.md` | **Rewrite workflow section** | Two paths: (a) **brainstorm-first for everything** — `brainstorming` → `writing-plans` (→ `docs/plans/`) → `executing-plans` or `subagent-driven-development`; (b) for triaged backlog items where the issue body IS the spec, brainstorming may be brief but is still required (per user's explicit choice to honor the HARD-GATE on every change). |
| `CLAUDE.md` | **Add section** | New "Superpowers skills are the canonical playbooks" section listing the relevant skills and noting they take precedence where they conflict with older inline guidance. Existing architectural invariants section unchanged (still authoritative for the safety stack). |
| `.claude/skills/add-or-extend-agent/SKILL.md` | Unchanged | Domain-specific, no conflict. Continues to be referenced from the new engineer prompt. |
| `.claude/skills/handover/SKILL.md` | Unchanged | No conflict. |
| `.claude/skills/research-bundle/SKILL.md` | Unchanged | No conflict. |

## New flow (replaces TEAM.md workflow section)

```
User states intent
  ↓
Team Leader (main session) invokes superpowers:brainstorming
  ↓ (writes spec to docs/plans/<date>-<slug>-design.md, gets user approval)
Team Leader invokes superpowers:writing-plans
  ↓ (writes plan to docs/plans/<date>-<slug>-plan.md, gets user approval)
Team Leader invokes superpowers:subagent-driven-development
  ↓
  Per-task loop:
    Dispatch implementer subagent (project-customised prompt)
      ↓
    Dispatch spec-reviewer subagent
      ↓ (NEEDS_CHANGES → loop back to implementer)
    Dispatch code-quality-reviewer subagent (architectural invariants checklist)
      ↓ (NEEDS_CHANGES → loop back to implementer)
    Mark task complete
  ↓
Team Leader invokes superpowers:finishing-a-development-branch
  ↓ (lead subagent merges per existing merge gate)
Team Leader dispatches docs subagent for README/CLAUDE.md/CURRENT_CONFIG sync
```

The two retained roles outside the superpowers loop:

- **lead** — still triages issues and gate-keeps merges (no superpowers equivalent for triage; merge-gate references `finishing-a-development-branch`).
- **qa** — still discovers bugs and opens issues (no superpowers equivalent for issue-opening).
- **analyst** — still does backtest research, writes to `docs/research/` (no superpowers equivalent).

## Risks and unknowns

1. **Process overhead on small changes.** The brainstorming HARD-GATE applies to every change. Even a one-line typo fix will go through brainstorm → spec doc → plan doc → implementation. The user has explicitly opted in (this conversation, 2026-05-07). If it proves untenable in practice we'll revisit; rollback is uninstalling the plugin.
2. **Two parallel docs trees.** `docs/plans/` (new, superpowers-driven) and `docs/research/` (existing, analyst-driven) and `docs/handover/` (existing, session-handover-driven). They serve different purposes; should remain separate. If overlap emerges, address in a future cleanup PR.
3. **Subagent context isolation.** `subagent-driven-development` mandates fresh subagent per task with explicit context. Our existing `engineer` subagent already inherits no session state — this is compatible. The risk is the new implementer prompt missing a key invariant; mitigated by the safety preservations above.
4. **`CLAUDE_AGENT_NO_BROKER` cross-check.** The mechanical guard fires regardless of which agent flow runs. Migration cannot accidentally weaken broker safety because the env var fires at the tool level, not the prompt level. This is the single most important safety property, unchanged.
5. **Adoption of `brainstorming` for itself.** This very PR was brainstormed (the conversation up to this design doc IS the brainstorm session). Acceptance test: did the process produce a clearer outcome than jumping straight to implementation? Subjective; user judges.

## Acceptance test

After the PR merges, the next non-trivial change to this repo:

1. Triggers a `superpowers:brainstorming` invocation from the Team Leader before any code is written.
2. Produces a spec doc at `docs/plans/<date>-<slug>-design.md`.
3. Produces a plan doc at `docs/plans/<date>-<slug>-plan.md`.
4. Dispatches at least one implementer subagent that reads the new `engineer.md` prompt.
5. Dispatches both a spec-reviewer and a code-quality-reviewer subagent before merge.
6. The code-quality-reviewer's architectural-invariants checklist is identical to today's `reviewer.md` content (verbatim preservation verified by diff).

## Rollback plan

If the new flow proves untenable:

1. `/plugin uninstall superpowers@claude-plugins-official` removes the bootstrap and skills.
2. `git revert <merge-commit>` restores the prior `engineer.md`, `reviewer.md`, `TEAM.md`, `CLAUDE.md`, `qa.md`, `lead.md`.
3. Cherry-pick option (Option B from the conversation) becomes the fallback: copy 4–5 selected SKILL.md files into `.claude/skills/` without the bootstrap pressure.

## Open questions (resolved during brainstorming)

- **Brainstorming scope?** Honor literally — every change, regardless of size. *(Resolved: user 2026-05-07)*
- **Plans path?** `docs/plans/` (not `docs/superpowers/specs/`). *(Resolved: user 2026-05-07)*
- **Keep custom skills?** Yes — no superpowers equivalent. *(Implicit in scope decision.)*

## References

- Plugin: <https://github.com/obra/superpowers> (MIT, v5.1.0, sha `f2cbfbef`)
- Installed at: `/home/trader/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0`
- SessionStart hook: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/hooks/session-start`
- Broker safety incidents: PR #150 (#149 root-cause), PR #172 (#168 mechanical guard)
- User memory references: `feedback_worktree_for_parallel_work`, `feedback_triple_check_before_shipping`
