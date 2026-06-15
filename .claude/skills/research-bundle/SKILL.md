---
name: research-bundle
description: Use this skill to generate a 4-file research bundle (keywords, strategies, github-projects, roadmap) in `docs/research/<topic>/` via multi-agent dispatch. Invoke when the user wants to challenge an existing solution with external research, scope a new product direction before building, or survey alternatives. Triggers include `/research-bundle <topic>`, "do a research bundle on X", "survey alternatives for X", "multi-agent research X", or "challenge our current approach to X with external research".
---

# Research Bundle

Produce a 4-file research bundle in `docs/research/<topic>/` to inform — not implement — product decisions on this trading bot. Pure documentation; no code or behavioural changes.

The format contract for each file lives in [`docs/research/README.md`](../../../docs/research/README.md). **Read it before dispatching agents** — it defines what each file must contain. This skill is the orchestrator; the README is the contract.

## Inputs

- `<topic>` (required, kebab-case) — the slug used as the directory name and as the subject of all research. Examples: `pairs-trading`, `options-wheel`, `regime-detection`, `sizing-algorithms`.
- `<sources>` (optional, default `en+de`) — language source mix. `en` for English-only, `de` for German-only, `en+de` for both. German practitioner literature (Voigt, Schäfermeier, godmode-trader, stock3, kagels-trading) is high-signal for trading topics; skip for topics with no meaningful DE coverage (e.g. US-equity-microstructure).
- `<repos>` (optional, default `≤8`) — cap on the GitHub-projects survey. Tight scope protects against streaming timeouts that have been observed on long-running web-survey agents.

## Pre-flight

Do all of these before dispatching agents.

1. **Read `CLAUDE.md` in full.** Internalise the **Architectural invariants** section — *"The LLM must never control risk parameters directly."* This is the lens applied to every deliverable. The verdicts (`fits` / `needs envelope` / `skip` / `violates`) are non-negotiable consequences of this rule.
2. **Read `docs/research/README.md`** for the file format contract.
3. **Check `docs/research/<topic>/` does not already exist.** If it does, ask the user whether to (a) extend the existing bundle, (b) overwrite, or (c) abort.
4. **Create a worktree** for the work — never branch against the main `/opt/trading-bot` checkout. Branch name: `research/<topic>-<short-id>` or similar.

## Phase 1 — parallel research (4 agents, background)

Dispatch in parallel using the Agent tool with `subagent_type: general-purpose` and `run_in_background: true`. Long-running web research benefits from parallelism here.

- **Agent K — `keywords.md`** (writes file directly). Produces ~100 high-signal terms in ~10–14 categories per the README contract.
- **Agent S-EN — English-source strategies** (returns structured Markdown findings — does NOT write a file; output is consumed by the Phase 2 merge agent).
- **Agent S-DE — German-source strategies** (returns structured findings — does NOT write a file). Skip this agent if `<sources>` is `en`. Prefer godmode-trader, stock3, finanzen.net, kagels-trading, WHSelfInvest. For trading topics, explicitly include Voigt'sche Markttechnik, Trendfolge, Marktphasen-Modell / Stan Weinstein, Saisonalität, Schäfermeier ORB, André Stagge anomaly stacking. Also have Agent S-EN cover Wyckoff and Ichimoku in depth.
- **Agent G — `github-projects.md`** (writes file directly). Capped at `<repos>` repos for diversity, not volume. Use `gh api repos/<owner>/<repo>` for stars / licence / `pushed_at`; WebFetch only for README content. **Do not list `unknown`** for fields the API exposes. Instruct the agent to write the file as soon as 4 repos are documented and to keep editing — protects against streaming timeouts.

Each Phase 1 agent receives an explicit instruction: commit your file (if you write one) on the working branch and push; do not touch any other file; do not modify the PR.

## Phase 2 — merge strategies (1 agent)

After Agents S-EN and S-DE complete, dispatch Agent M with their outputs verbatim in its prompt. It writes `strategies.md` directly:

- Picks the canonical top 15 (resolving overlap on Elliott / Wyckoff / Ichimoku — keep the deeper DE treatment when both languages cover the same canonical strategy).
- Every entry ends with a bolded verdict: **`fits`**, **`needs envelope`** (with one-sentence envelope description), or **`skip`**. No exceptions.
- Closes with "Cross-cutting observations".

If `<sources>` was `en`, Agent M just receives Agent S-EN's findings — still writes the same file shape.

## Phase 3 — roadmap (1 agent)

After `strategies.md` and `github-projects.md` are committed, dispatch Agent R. It reads:

- `CLAUDE.md`
- `supabase/functions/_shared/` (shared TS modules: `config.ts`, `regime.ts`, `alpaca.ts`, `marketdata.ts`, `db.ts`, `notifications.ts`)
- The three Edge Functions: `supabase/functions/daily-check/`, `supabase/functions/kill-switch/`, `supabase/functions/panic/`
- Research-only Python: `backtest/`, `strategy/`
- The just-written `strategies.md` and `github-projects.md`

Writes `roadmap.md` per the README contract: candidates clustered by theme, every candidate carries a `fits` / `needs envelope` / `violates` verdict and a `now` / `next` / `later` / `skip` priority, plus an `S` / `M` / `L` / `XL` effort estimate. Treats the existing "Roadmap pattern candidates" section in `github-projects.md` as input, not the final list — re-rank against `strategies.md` and de-dupe.

If a candidate already exists in the codebase (check `git log` and current files before proposing), Agent R does not re-propose it — it proposes the *extension* and acknowledges the base is shipped.

## Phase 4 — PR

1. Push the branch with `-u origin <branch>`; retry on network errors with exponential backoff (2s / 4s / 8s / 16s).
2. Open a **draft PR** with a summary listing each file and the multi-agent methodology.
3. PR body explicitly notes that `roadmap.md` recommendations respect the *"LLM never controls risk parameters"* invariant.
4. Leave as draft. The user reviews and flips to ready manually after spot-checking markdown render and link resolution.
5. If a PR for this branch already exists (rare — happens if a previous session crashed mid-run), push additional commits to the existing PR rather than opening a new one.

## Quality bar — enforce on every dispatch

- Cite real, recent URLs from actual web searches. **No fabricated repos, papers, or statistics.**
- Use `gh api` for repo metadata; do not list `unknown` for fields the API exposes.
- Be skeptical of marketing fluff (paid courses, "100% win rate" claims). Flag weak-evidence findings explicitly under **Evidence quality**.
- For every strategy and every roadmap item, declare the deterministic-risk verdict honestly. **`skip` and `violates` are valid and welcome.**
- Be transparent in agent reports: actual coverage, dropped items, source mix. If a survey only found 6 verifiable repos, document 6 — not 10 with 4 guesses.

## Non-goals

- No code changes to the bot.
- No new tests.
- No new agents in `.claude/agents/`.
- The roadmap is a research artifact, not an implementation plan. Do not write code in `roadmap.md`; do not propose specific PRs from it.

## Reference example

`docs/research/swing-trading/` (delivered 2026-04-30 via PR #98) is the reference example for the format. New bundles should be readable side-by-side with it.
