**Date:** 2026-05-01 (UTC)
**Slug:** handover-skill-bootstrap
**Author:** Claude Code session (claude-opus-4-7)

## 1. Sit-rep

This session bootstrapped a brand-new `handover` skill so that any future Claude Code session can resume a piece of work cold from a single Markdown doc. Two new files landed: `.claude/skills/handover/SKILL.md` (orchestrator) and `docs/handover/README.md` (format contract). Both shipped via PR [#108](https://github.com/sv-tmueller/trading-bot/pull/108) (draft) on branch `claude/add-handover-skill-LOKDg`. The skill was then dogfooded — this very document is the first live invocation of `/handover`. No bot code was touched; the deterministic-risk layer, agent pipeline, settings, and broker integration are unchanged. Paper-trading state, kill switch (`TRADING_PAUSED`), and cron schedule are exactly as `main` had them at commit `6f8221b`.

## 2. In-flight branches & PRs

- **PR [#108](https://github.com/sv-tmueller/trading-bot/pull/108)** — `claude/add-handover-skill-LOKDg` (state: **draft**).
  - **Purpose:** add the `handover` skill + `docs/handover/README.md` format contract.
  - **Status:** committed at `9eb9504`, pushed, draft PR opened. No CI configured for this repo (`get_check_runs` returned 0). No reviewer comments. Ready for human spot-check (markdown render, link resolution).
  - **Next action:** flip to ready and merge once you've eyeballed the rendered SKILL.md and README.md on GitHub. After merge, every fresh session will see `handover` in its skills list.
- **PR [#93](https://github.com/sv-tmueller/trading-bot/pull/93)** — `claude/evaluate-mql5-trading-Kt8Os` (state: **draft**, **not from this session**).
  - **Purpose:** `BaseBroker` ABC + `AlpacaBroker` adapter; closes [#95](https://github.com/sv-tmueller/trading-bot/issues/95).
  - **Status:** open since 2026-04-30, last touched 2026-04-30 09:49 UTC. Predates this session — not advanced today.
  - **Next action:** unrelated to this session. Flagged here only because the format contract requires listing all open PRs touched or relevant; do **not** treat it as in-flight from the handover-skill thread.
- **This handover doc itself** lives on its own branch (`handover/handover-skill-bootstrap-2026-05-01`) per the skill's branch-and-PR rule — it must not piggy-back on the handover-skill feature branch.

## 3. Open issues being worked

This session did not engage with any issue. All current open issues belong to other threads. Listing them here only as a snapshot so the next session has a one-glance view of the backlog state at handover time:

- **`#102`** — SPY 200-SMA regime gate. Labels: `enhancement`, `strategy`, `priority: high`, `status: ready`.
- **`#103`** — `main.py panic` CLI. Labels: `enhancement`, `priority: high`, `status: ready`.
- **`#104`** — Walk-forward backtest harness. Labels: `enhancement`, `priority: medium`, `status: ready`.
- **`#94`** — Realistic frictions in portfolio backtest. Labels: `enhancement`, `priority: medium`, `status: ready`.
- **`#95`** — Broker abstraction (covered by draft PR #93). Labels: `enhancement`, `priority: medium`, `status: ready`.
- **`#96`** — Broker abstraction completeness gaps. Labels: `enhancement`, `priority: medium`, `status: ready`.
- **`#63`** — Sector concentration. Labels: `enhancement`, `strategy`, `priority: medium`, `status: ready`.
- **`#65`** — Portfolio-mode-aware parameter sweep. Labels: `strategy`, `priority: low`, `status: ready`.
- **`#66`** — Short-side strategy support. Labels: `enhancement`, `strategy`, `priority: medium` (no status label — un-triaged for `status: ready`).
- **`#61`** — Raise `MAX_PORTFOLIO_EXPOSURE`. Labels: `enhancement`, `strategy`, `priority: high`, **`status: blocked`**.
- **`#106`** — Alpaca EU / Xetra evaluation. Labels: `enhancement`, `priority: low`, **`status: blocked`**.

`status: ready` count is 8. Lead's next pick should respect priority: `#102`, `#103` are `priority: high` and ready.

## 4. Decisions made this session

- **Decision:** mirror the `research-bundle` pattern exactly — `.claude/skills/<skill>/SKILL.md` orchestrator paired with `docs/<topic>/README.md` format contract.
  **Rationale:** `research-bundle` already proved the split works; consistency reduces the surface area someone has to learn before authoring or maintaining a skill. Rejected alternative: cram everything into `SKILL.md`. That conflates "how to run the workflow" with "what the artefact must contain", which makes hand-written artefacts (skill bypass) impossible to validate.
  **Consequence:** future skills that produce a documented artefact should follow the same split. The `docs/<topic>/README.md` is the contract, the `SKILL.md` is the orchestrator.
- **Decision:** handover docs land on a dedicated `handover/<slug>-<date>` branch, never piggy-backed on a feature branch.
  **Rationale:** a handover may be merged before its referenced feature work is ready; keeping it isolated keeps the merge order independent.
  **Consequence:** **do not commit handover docs onto in-flight feature branches**, even when convenient.
- **Decision:** make every section in the format contract mandatory; explicit `_None._` is required when empty.
  **Rationale:** silent omission is indistinguishable from oversight by a cold reader; an explicit `_None._` proves the section was considered.
  **Consequence:** the next session evaluating a future handover for completeness can grep for missing sections vs missing values.
- **Decision:** suggested-next-prompts must be literal paste-ready text, not paraphrases.
  **Rationale:** vague aspirations ("continue working on shorts") cost a fresh session 5–10 minutes of context-rebuild. Literal prompts cost zero.
  **Consequence:** every handover ends with 3–5 actionable prompts that a fresh session can execute without follow-up questions.
- **Decision:** the deterministic-risk invariant is restated in the **Don't forget** section of every handover, even when the session did not touch risk code.
  **Rationale:** the invariant is the load-bearing constraint of the codebase; no handover should ever fail to surface it.
  **Consequence:** the contract bakes the standing list (deterministic risk, bracket orders, pre-market cron, `TRADING_PAUSED`, IEX/SIP feed gate, `from __future__ import annotations`) directly into the README so it cannot be forgotten.

## 5. Open questions

- **Should the handover skill auto-trigger before context auto-compaction?** The SKILL.md says *"propose writing a handover proactively"* in that case, but the actual hook would have to live in `settings.json`. Today's skill is purely user-invoked.
  **Blocks:** no decision yet on whether auto-compaction warning events are reliable enough to trigger on, and whether the handover would interrupt mid-tool-use work.
  **Suggested next step:** if you want this, ask Claude in a fresh session: *"What hook events does Claude Code expose around context auto-compaction, and would they cleanly drive the handover skill?"* — then decide.
- **`docs/handovers/` (plural) vs `docs/handover/` (singular).** Issue [#96](https://github.com/sv-tmueller/trading-bot/issues/96) references `docs/handovers/2026-04-30-broker-rationale-and-frictions-roadmap.md` (plural folder). That file does not exist in this repo — it appears to be a phantom reference (possibly written when a session intended to create a handover that never landed). The new skill standardised on `docs/handover/` (singular).
  **Blocks:** decision on whether to (a) leave issue #96 as-is and let the phantom reference age out, (b) edit the issue body to remove the broken link, or (c) create a back-dated handover under the singular path that recovers the broker-rationale content.
  **Suggested next step:** ask the user. Lowest-effort option is (a). Highest-fidelity option is (c) but requires reconstructing context from PR #93's body and issue #96 itself.
- **Should the handover doc be merged to `main` or left unmerged?** SKILL.md says *"the user decides when (or whether) it lands on main"*. Today both PR #108 (skill) and the handover-doc PR (this) are draft.
  **Blocks:** preference call — handover docs as durable repo artefacts (merged) vs ephemeral session aids (kept on long-lived draft PRs).
  **Suggested next step:** pick a default and document it in the README. Recommend "merge always" — the doc is small, costs nothing on `main`, and a merged copy is the only reliable copy a fresh session can find.

## 6. Files to read first

- `.claude/skills/handover/SKILL.md` — the orchestrator. Start here to understand the workflow.
- `docs/handover/README.md` — the format contract. Defines every required section and the standing **Don't forget** list.
- `.claude/skills/research-bundle/SKILL.md:1-86` — the reference pattern this skill mirrors.
- `docs/research/README.md:1-86` — the matching format contract for research-bundle. Compare side-by-side with `docs/handover/README.md` to see the parallel.
- `CLAUDE.md:104-128` — the architectural-invariants section the handover **Don't forget** list is derived from.
- `TEAM.md:11-22` — Team Leader → role dispatch table; the suggested next prompts must be expressible in this vocabulary.

## 7. Don't forget

Session-specific:
- This handover lives on a dedicated branch (`handover/handover-skill-bootstrap-2026-05-01`), not on the skill feature branch (`claude/add-handover-skill-LOKDg`). When merging, treat them as independent PRs.
- `docs/handover/` is **singular**. Issue [#96](https://github.com/sv-tmueller/trading-bot/issues/96) references the plural `docs/handovers/` — that path does not exist; do not create it.

Standing list (always restate per the format contract):
- The LLM must never control risk parameters directly. Stops and targets come from `tools/risk.py`; the position monitor is rule-based; only `TeamLeaderAgent` places orders, and only with pre-approved values.
- Stops and take-profits execute server-side via Alpaca **bracket orders**. The position monitor is defence-in-depth, not the primary exit mechanism.
- Morning scan must run **pre-market** (cron `25 13 * * 1-5` UTC). Running after 13:30 UTC produces ~zero `volume_ratio` and kills every entry.
- `TRADING_PAUSED=true` halts new entries but does not affect the position monitor.
- Free Alpaca paper accounts require `DataFeed.IEX`; live SIP requires a paid account. Controlled via `DATA_FEED` env var.
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime).

## 8. Suggested next prompts

Paste these into a fresh Claude Code session, in order of priority.

1. `Review and merge PR #108 — the handover skill. Spot-check the markdown render of .claude/skills/handover/SKILL.md and docs/handover/README.md on GitHub, confirm all internal links resolve, then dispatch lead to merge if it looks clean.`
2. `Review and merge the handover-doc PR on branch handover/handover-skill-bootstrap-2026-05-01. It is the first live invocation of the new skill — useful to validate the format contract on a real artefact before more handovers accumulate.`
3. `Triage open issues — work through #102 (SPY 200-SMA regime gate, priority:high, status:ready) and #103 (panic CLI, priority:high, status:ready) next. Both fit the deterministic-risk invariant cleanly per docs/research/swing-trading/roadmap.md.`
4. `Decide the docs/handovers (plural) phantom reference in issue #96. Options: (a) leave as-is, (b) edit the issue to remove the broken link, (c) back-fill a real handover at docs/handover/2026-04-30-broker-rationale-and-frictions-roadmap.md from PR #93's body. Recommend (a) unless you need the broker-rationale context recovered.`
5. `Investigate whether Claude Code exposes a hook event for context auto-compaction warnings, and whether driving the handover skill from such a hook is sound. Don't implement — research only, report back.`
