**Date:** 2026-05-01 (UTC)
**Slug:** agent-authoring-skill-extraction
**Author:** Claude Code session (claude-opus-4-7)

## 1. Sit-rep

Second skill-engineering session of 2026-05-01. Earlier today the `handover` skill landed (PR [#108](https://github.com/sv-tmueller/trading-bot/pull/108)) plus its first live artefact (PR [#109](https://github.com/sv-tmueller/trading-bot/pull/109)). This session followed up by extracting the procedural agent-authoring content from `CLAUDE.md` into a new `add-or-extend-agent` skill and adding skill-discoverability machinery so future sessions actually invoke skills rather than re-deriving rules. Shipped via PR [#110](https://github.com/sv-tmueller/trading-bot/pull/110), squash-merged at `4ed160a`. Three skills now live on `main`: `add-or-extend-agent`, `handover`, `research-bundle`. No bot code touched; deterministic-risk layer, agent pipeline, settings, broker integration unchanged. Working tree clean on `main`.

## 2. In-flight branches & PRs

- **PR [#110](https://github.com/sv-tmueller/trading-bot/pull/110)** — `claude/extract-agent-authoring-skill` → **merged** at `4ed160a`. Adds the skill, trims four `CLAUDE.md` sections to breadcrumbs, adds top-level "Working in this repo" directive, updates `engineer` subagent playbook with skill-readout step.
- **PR [#108](https://github.com/sv-tmueller/trading-bot/pull/108)** — handover skill, **merged** at `5721466` earlier today.
- **PR [#109](https://github.com/sv-tmueller/trading-bot/pull/109)** — first handover artefact, **merged** at `7aed793` earlier today.
- **PR [#93](https://github.com/sv-tmueller/trading-bot/pull/93)** — `claude/evaluate-mql5-trading-Kt8Os` (state: **draft**, **not from this session**). Broker abstraction. Last touched 2026-04-30 09:49 UTC. Listed for completeness; not in flight here.
- **This handover doc** lives on its own branch `handover/agent-authoring-skill-extraction-2026-05-01` per the skill's branch-and-PR rule.

## 3. Open issues being worked

This session opened, closed, and engaged with no GitHub issues. The backlog snapshot at handover time matches earlier today (one issue updated comments — #106 — by the monthly Alpaca-EU watch agent):

- **`#102`** — SPY 200-SMA regime gate. `enhancement`, `strategy`, `priority: high`, `status: ready`.
- **`#103`** — `main.py panic` CLI. `enhancement`, `priority: high`, `status: ready`.
- **`#104`** — Walk-forward backtest harness. `enhancement`, `priority: medium`, `status: ready`.
- **`#94`** — Realistic frictions in portfolio backtest. `enhancement`, `priority: medium`, `status: ready`.
- **`#95`** — Broker abstraction (covered by draft PR #93). `enhancement`, `priority: medium`, `status: ready`.
- **`#96`** — Broker abstraction completeness gaps. `enhancement`, `priority: medium`, `status: ready`. Still references the phantom path `docs/handovers/` (plural) — see Open questions.
- **`#63`** — Sector concentration. `enhancement`, `strategy`, `priority: medium`, `status: ready`.
- **`#65`** — Portfolio-mode-aware parameter sweep. `strategy`, `priority: low`, `status: ready`.
- **`#66`** — Short-side strategy support. `enhancement`, `strategy`, `priority: medium` (no status label).
- **`#61`** — Raise `MAX_PORTFOLIO_EXPOSURE`. `enhancement`, `strategy`, `priority: high`, **`status: blocked`**.
- **`#106`** — Alpaca EU / Xetra evaluation. `enhancement`, `priority: low`, **`status: blocked`**. New comment 2026-05-01 09:08 UTC (monthly watch agent).

`status: ready` count is 8. Highest-priority pickups remain `#102` and `#103`.

## 4. Decisions made this session

- **Decision:** the agent-authoring procedural content is one cohesive extraction, not multiple smaller skills.
  **Rationale:** the BaseAgent pattern, tool-routing rule, agent-test triad, and "add a new setting" recipe all surface together when adding or extending an agent. Splitting them across skills would force a session to invoke two or three skills sequentially. Rejected alternative: `add-agent`, `agent-tests`, `add-setting` as three separate skills.
  **Consequence:** future adjacent procedural content (e.g. broker authoring, market-data adapter authoring) should be evaluated against the same rule — group by *workflow*, not by *file*.
- **Decision:** discoverability is mitigated by (1) a top-level CLAUDE.md directive, (2) breadcrumb pointers at the trimmed CLAUDE.md spots, (3) a parallel pointer in `engineer.md`. **No `UserPromptSubmit` hook added.**
  **Rationale:** the skill list is already auto-surfaced via `<system-reminder>`. The gap is *using* skills, not *noticing* them — a high-attention CLAUDE.md directive closes that. A hook would duplicate already-loaded context for marginal reliability gain and add per-prompt noise.
  **Consequence:** **do not add a hook unless the directive proves insufficient in practice.** First evidence of insufficiency: a session edits `agents/*.py` without reading `add-or-extend-agent/SKILL.md`. If that happens twice, revisit.
- **Decision:** `engineer` subagent gets the same content via `Read`, not via the Skill tool.
  **Rationale:** subagents have their own context and the engineer's tool list is `Bash, Read, Edit, Write, Grep, Glob` — no Skill tool. Adding the Skill tool to engineer would change its permission surface; safer to keep the skill SKILL.md dual-purpose (invokable + readable).
  **Consequence:** any future skill that needs to be readable by the engineer subagent should be authored as a self-contained Markdown doc — no orchestration that requires the Skill tool to function.
- **Decision:** ruled out `docs/agents-as-python-files.md` as an extraction candidate.
  **Rationale:** it is a decision record (why agents are `.py` not `.md`), not a procedure. Decision records stay in `docs/`; only procedural content moves to skills.
  **Consequence:** when surveying for future extractions, distinguish three content types — *standing rules / invariants* (CLAUDE.md), *decision records* (`docs/`), *procedural how-tos* (skills). Only the third moves.
- **Decision:** branch off latest `main` (`claude/extract-agent-authoring-skill`), not the harness-assigned `claude/add-handover-skill-LOKDg`.
  **Rationale:** the assigned branch was a single-purpose vehicle for the handover-skill issue, which had already merged. Creating a fresh branch off main matched the actual scope.
  **Consequence:** **the harness branch instruction is for the *initial* issue, not for follow-up work in the same session.** Follow-ups warrant a new branch with a descriptive name; user explicit-or-implicit consent counts as authorisation per the executing-with-care rules.

## 5. Open questions

- **Is the CLAUDE.md directive enough, or do we need a `UserPromptSubmit` hook?** Decided not to add one this session. Verifiable only through field use — first session that edits `agents/*.py` without reading the skill is the data point that would force a hook.
  **Blocks:** real-world telemetry. No way to test in advance.
  **Suggested next step:** observe the next 2–3 sessions that touch agent code; if they consistently miss the skill, add a `UserPromptSubmit` hook via the `update-config` skill.
- **Phantom `docs/handovers/` (plural) reference in issue [#96](https://github.com/sv-tmueller/trading-bot/issues/96).** Carried over from the previous handover; still unresolved. The repo's standard is `docs/handover/` (singular). #96 cites `docs/handovers/2026-04-30-broker-rationale-and-frictions-roadmap.md` which does not exist.
  **Blocks:** preference call: leave as-is, edit issue body, or back-fill the missing doc from PR #93's body.
  **Suggested next step:** ask the user — easiest is to leave as-is; highest-fidelity is to back-fill.
- **Are there other procedural extraction candidates we did not survey?** This session focused exclusively on `CLAUDE.md`. `README.md` has user-facing how-to (install, run, configure) but those are user docs, not Claude playbooks. `TEAM.md` is descriptive. `ROADMAP.md` is process-but-thin. `docs/CURRENT_CONFIG.md` is data, not procedure. **Likely no further extractable content** without authoring brand-new skills (e.g. "release-the-bot" workflow, "respond-to-an-incident" workflow), which is a different exercise.
  **Blocks:** scope decision — extract from existing repo content vs author new workflow skills.
  **Suggested next step:** if the user wants more skills, the conversation flips to *what new workflows would benefit from skill-form documentation* rather than *what existing content can be moved*.

## 6. Files to read first

- `.claude/skills/add-or-extend-agent/SKILL.md` — the new skill. Authoring playbook for any future agent-pipeline change.
- `CLAUDE.md:5-12` — the new "Working in this repo" directive plus the three-skill catalogue. **This is the discoverability mechanism**; if a future session ignores it, the discoverability strategy is failing.
- `CLAUDE.md:65-67`, `CLAUDE.md:87-89`, `CLAUDE.md:91-93` — the breadcrumbs that replaced the trimmed procedural sections.
- `.claude/agents/engineer.md:9-16` — engineer subagent's updated playbook step 2 (skill scan).
- `docs/handover/README.md` — the format contract this handover follows.
- `docs/handover/2026-05-01-handover-skill-bootstrap.md` — the morning's handover; reference example for the format.

## 7. Don't forget

Session-specific:
- The repo now standardises on `docs/handover/` (singular). Issue [#96](https://github.com/sv-tmueller/trading-bot/issues/96) still references the plural path; do not create `docs/handovers/`.
- Three skills live on `main`: `add-or-extend-agent`, `handover`, `research-bundle`. Update `CLAUDE.md:9-12` if a fourth lands.
- The `engineer` subagent does not have the Skill tool. New skills meant to be readable by `engineer` must be self-contained in their `SKILL.md` (no orchestration that depends on the Skill tool firing).
- This handover branches off `main` (PR base = `main`), unlike the bootstrap handover earlier today which had to base off the skill branch. The bootstrap pattern was a one-off.

Standing list (always restate per the format contract):
- The LLM must never control risk parameters directly. Stops and targets come from `tools/risk.py`; the position monitor is rule-based; only `TeamLeaderAgent` places orders, and only with pre-approved values.
- Stops and take-profits execute server-side via Alpaca **bracket orders**. The position monitor is defence-in-depth, not the primary exit mechanism.
- Morning scan must run **pre-market** (cron `25 13 * * 1-5` UTC). Running after 13:30 UTC produces ~zero `volume_ratio` and kills every entry.
- `TRADING_PAUSED=true` halts new entries but does not affect the position monitor.
- Free Alpaca paper accounts require `DataFeed.IEX`; live SIP requires a paid account. Controlled via `DATA_FEED` env var.
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime).

## 8. Suggested next prompts

Paste these into a fresh Claude Code session, in priority order.

1. `Triage open issues and start work on #102 (SPY 200-SMA regime gate, priority:high, status:ready). It's a small, deterministic, fits-the-invariant change — canonical first use of the new add-or-extend-agent skill. Dispatch lead → engineer → reviewer → lead per TEAM.md.`
2. `Work on issue #103 (main.py panic CLI, priority:high, status:ready). Pure deterministic safety net — extends the existing TRADING_PAUSED kill switch. Read CLAUDE.md architectural invariants first; the CLI is the deterministic primitive, no LLM.`
3. `Decide what to do about the phantom docs/handovers/ (plural) reference in issue #96. Options: (a) leave as-is, (b) edit the issue body to remove the broken link, (c) back-fill a real handover at docs/handover/2026-04-30-broker-rationale-and-frictions-roadmap.md from PR #93's body. Recommend (a) unless you need the broker-rationale context recovered.`
4. `Audit whether the next session correctly invokes the add-or-extend-agent skill when touching agents/*.py. If it ignores the skill twice in a row, run /update-config to add a UserPromptSubmit hook that reminds Claude to scan .claude/skills/ before starting work on agent code.`
5. `Survey the repo for new workflow skill candidates that don't exist yet — e.g. "release-the-bot" (tag, changelog, deploy), "respond-to-an-incident" (kill switch, liquidate, post-mortem). Distinct from the previous "extract from CLAUDE.md" exercise; this is greenfield workflow authoring.`
