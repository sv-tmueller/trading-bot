# Research Bundles

Format and conventions for `docs/research/<topic>/` directories. Each subdirectory is a self-contained research artefact intended to inform — not implement — product decisions on this trading bot.

## Why these exist

A research bundle is the input to a build/skip decision, not its output. The format keeps multiple bundles comparable, forces honest evidence-quality calls, and makes the architectural-invariant lens (the *"LLM must never control risk parameters directly"* rule from `CLAUDE.md`) load-bearing on every recommendation.

A bundle is **not**:
- A design document (those live in PRs and issues).
- An implementation plan (the bundle's `roadmap.md` produces candidates and priorities; the actual implementation plan happens later, per candidate, in its own PR).
- A blog post (no marketing tone, no "this is the future" framing — be honest about evidence quality).

## File contract

Every bundle has exactly these four files. The orchestrator skill (`.claude/skills/research-bundle/`) generates all four; if you write one by hand, follow the same shape.

### `keywords.md`
~100 high-signal terms relevant to the topic, organised into ~10–14 categories — typically: momentum / trend / volatility / volume indicators, candlestick patterns, continuation & reversal chart patterns, strategy archetypes, market structure, risk management, timeframes & sessions, psychology / regime, asset universe & screening, order types. Brief inline glosses only for ambiguous abbreviations. Used as a vocabulary baseline by the rest of the bundle and by future agents.

### `strategies.md`
Top 15 approaches / strategies / techniques, merged from English and (where applicable) German sources. For each:

- **Mechanism** — entry / exit / stop in 2–4 sentences, with concrete numbers where the canonical version specifies them.
- **Indicators / patterns** — bullet list of the technical building blocks.
- **Typical timeframe** — daily, weekly, multi-day, etc.
- **Pros** — bullets, real ones.
- **Cons** — bullets, including failure modes.
- **Fit with our bot** — 1–3 sentences ending with a bolded verdict: **`fits`**, **`needs envelope`** (with one-sentence envelope description), or **`skip`**.
- **Evidence quality** — `academic` (peer-reviewed or replicated), `practitioner` (well-known trader / book / serious blog), or `marketing` (course-seller / hype). Be honest.
- **Sources** — real URLs from actual web searches, with year if visible. No fabrication. If a strategy is well-known but uncitable, drop it from the top 15.

Closes with a **"Cross-cutting observations"** section: which archetypes line up with the deterministic-risk invariant; which need envelopes; where EN and DE literatures disagree on a canonical strategy; an honest evidence-quality summary; high-level implications for `RiskReviewAgent` and `tools/risk.py`.

### `github-projects.md`
Survey of public GitHub repositories. Cap depends on bundle scope (default ≤8 — diversity over volume; protects against streaming timeouts on long surveys). For each:

- **Stars / last commit / licence** — via `gh api repos/<owner>/<repo>` (`stargazers_count`, `pushed_at`, `license.spdx_id`). **Do not list `unknown` for fields the API exposes.**
- **Stack** — SDK, scheduler, DB, frameworks.
- **Strategy focus** — what the bot actually trades and how.
- **Risk handling** — stops, brackets, sizing, kill-switch, guardrails. Flag bots that lack a deterministic risk layer.
- **LLM / agent usage** — which provider, what role, whether the LLM controls risk parameters (red flag).
- **Architecture notes** — module layout, test infrastructure.
- **What to borrow** — concrete bullets tied to specific modules in this codebase (e.g. `tools/risk.py`, `agents/base.py`).
- **What to avoid** — red flags, anti-patterns, licence concerns.

Summary table at top, **"Cross-cutting findings"** at bottom. No fabrication — drop any repo that cannot be verified.

### `roadmap.md`
Feature candidates clustered from `strategies.md` + `github-projects.md`, mapped against current architecture. For each:

- **Description** — one line; names the module(s) it would touch.
- **Source** — references back into the sibling files (by name) or "codebase-driven" if purely operational.
- **Pros / Cons** — bullets.
- **Fit with the deterministic-risk invariant** — explicit verdict: **`fits`**, **`needs envelope`** (with envelope described in one sentence), or **`violates`** (with recommendation to skip or radically scope-cut).
- **Priority** — exactly one of: **`now`** (next 1–2 sprints, high value, low risk, fits the invariant), **`next`** (after current quarter, design-only), **`later`** (significant design or research first), **`skip`** (recommend against — explain in one sentence).
- **Rough effort** — `S` (≤1 day), `M` (1–5 days), `L` (1–3 weeks), `XL` (multi-month or research-grade).

Closes with a **"Cross-cutting recommendations"** section:
- The 3–5 highest-leverage `now` items, ranked.
- Anything labelled `skip` or `violates` that should be called out as an explicit non-goal.
- A short note on *why* the deterministic-risk invariant rules out certain otherwise-attractive candidates.
- An honest paragraph on which candidates are likely to actually move trading performance vs. which are pure operational hygiene.

If a candidate already exists in the codebase, the roadmap does not re-propose it — it proposes the *extension* and acknowledges the base is shipped.

## The architectural-invariant lens

`CLAUDE.md` states: *"The LLM must never control risk parameters directly."* Every `strategies.md` and `roadmap.md` entry must end with an explicit verdict against this rule.

- **`fits`** — works with our existing deterministic-risk layer (ATR stops, bracket orders, portfolio guardrails, exposure gate).
- **`needs envelope`** — viable only if a deterministic wrapper is added first. The envelope must be named (e.g. "ATR-floor on stops", "fixed sizing regardless of LLM suggestion", "hard veto on max-hold > N days").
- **`skip` / `violates`** — would let the LLM set stop distance, position size, or order side directly. Goes on the non-goals list.

The verdicts are non-negotiable consequences of the invariant. They are not subjective. If a strategy or candidate cannot be cleanly tagged, the bundle author must dig deeper until it can.

## Producing a bundle

Use the `research-bundle` skill: `/research-bundle <topic>` (and optionally `<sources=en|de|en+de>`, `<repos=N>`). The skill orchestrates four parallel research agents (keywords, GitHub survey, EN strategies, DE strategies), a merge agent (consolidated top-15), and a roadmap agent (synthesis against the live codebase), then opens a draft PR.

Skill location: [`.claude/skills/research-bundle/SKILL.md`](../../.claude/skills/research-bundle/SKILL.md).

## Existing bundles

- [`swing-trading/`](swing-trading/) — first bundle; produced 2026-04-30 via PR #98. Reference example for the format.
