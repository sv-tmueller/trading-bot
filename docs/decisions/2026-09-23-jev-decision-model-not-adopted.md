# Jev decision model: evaluated, not adopted

TypeSafe's Jev typed decision model was evaluated after an operator-shared LinkedIn architecture post; not adopted in the trading path, no shadow study started now.

**Date:** 2026-09-23
**Status:** accepted

---

## Context

On 2026-09-23, after closing #229 and #230 (paper soak tracking and prod go-live, both parked
"not going live for now"), the operator asked for an evaluation of TypeSafe's **Jev** "decision
model" and an architecture described in a LinkedIn post, as part of batch #656 (this entry is
package 1, tracked as #655).

Jev is a vendor product (TypeSafe, distributed via OpenRouter and referenced in Vercel's AI SDK
docs). Per the vendor's own documentation:

- Jev exposes typed `Choice` / `Score` / yes-no outputs with per-label probabilities, rather than
  free-text completions.
- Pricing is input-token-only; scoring is label-token / prefill-only (the model does not generate
  new tokens for the label itself).
- It is described as reproducible on open models via vLLM or SGLang self-hosting, as an
  alternative to the hosted vendor endpoint.

Vendor/documentation links (see Cross-references for the full list):
- https://openrouter.ai/typesafe
- https://openrouter.ai/docs/guides/community/jev
- https://vercel.com/kb/guide/typesafe-jev-and-ai-sdk

The LinkedIn post (URL not recorded by the operator at share time) described an architecture
where a trading program streams telemetry (on the order of ~30 values per second) into Postgres,
and Jev scores that telemetry for hold/close judgments on open positions. Protection rules
(stop-loss, sizing limits) and order execution stay in deterministic code; the post described a
shadow-mode rollout as the next step, not a live one.

The repo's current state at evaluation time: the only live bot is the paper-only hourly
candlestick bot driven by `decideHourly` (`supabase/functions/_shared/hourly_signal.ts`), a single
deterministic decision rule with no model call anywhere in `hourly-check`, `kill-switch`, or
`panic`.

## Decision

Jev, and the Jev-scored hold/close architecture described in the LinkedIn post, are **not
adopted** in the trading path. No shadow study is started now.

This conflicts with two of this repo's architectural invariants (see
[../../CLAUDE.md#architectural-invariants](../../CLAUDE.md#architectural-invariants) for the full,
authoritative text -- cited here by name only, not restated or quoted): "One decision rule" and
"No LLM in the trading path."

### Architecture review

Sound parts of the proposed architecture, taken on their own terms:
- Deterministic execution and protection rules stay in code; Jev's scored judgment would only
  gate a hold/close decision on an already-open position, not place or size an order directly.
- The post's own next step is a shadow rollout, not a live one -- the proposal is already
  structured to be tested before it can affect real orders.
- Typed output (`Choice` / `Score` / yes-no with per-label probabilities) is a meaningfully
  narrower interface than free-text completion, which is easier to audit and to bound.

Weaknesses, weighed against those sound parts:
1. Structurally, "deterministic code executes, a model advises on hold/close" is the same shape
   as the pre-pivot v1.14 "LLM advises, guards control" pattern -- the pattern this repo's own
   pivot moved away from because the guardrails did not stop the model's non-determinism from
   leaking into outcomes.
2. The vendor's latency and uptime claims are not edge evidence -- infrastructure quality says
   nothing about whether the scored judgment is predictive of hold/close outcomes.
3. Per-label probabilities from a hosted classifier are not calibrated probabilities. Without a
   calibration study, a 0.7 "hold" score cannot be read as a 70% chance of a favorable hold.
4. Any backtest run against a hosted model carries training-data lookahead leakage risk (the model
   may have seen data from the backtest period during its own training or fine-tuning). Only a
   forward-only shadow test, on data the model could not have trained on, is clean evidence.
5. A vendor can change the served model version silently. Without a pinned version, a result
   observed on one day is not reproducible or auditable against a later run.

### Revisit conditions

This decision is revisited, not closed permanently. Concretely:

1. **A forward-only, pre-registered shadow study**, run entirely outside `hourly-check`,
   `kill-switch`, and `panic` (so it can never influence a live decision), with every scored
   judgment logged and never read by the trading path, on a pinned model version, starting no
   earlier than the existing 30-closed-trade review checkpoint already defined for the hourly bot
   (design spec "Review checkpoint",
   [docs/superpowers/specs/2026-07-27-hourly-bot-design.md](../superpowers/specs/2026-07-27-hourly-bot-design.md);
   `PROPOSAL_MIN_CLOSED_TRADES` = 30 in
   [docs/runbooks/weekly-review.md](../runbooks/weekly-review.md)). Such a study must pre-register
   its own sample size and pass bar before it starts, the same way the hourly bot's own checkpoint
   was pre-registered.
2. **Any trading-path use** (a live gate on hold/close, sizing, or entry) needs a fresh brainstorm,
   a design spec, and an explicit amendment to the
   [Architectural invariants](../../CLAUDE.md#architectural-invariants) section before it can be
   built, not just a passing shadow study.
3. **Non-trading tooling use** (for example triage or routing inside verification or reflection
   flows, never inside the trading path) is worth a separate look only if volume or cost ever
   justifies Jev's pricing model over a constrained-output small model run locally.

## Consequences

### Positive

- The trading path stays on its single, audited decision rule; no new non-determinism is
  introduced into `hourly-check`, `kill-switch`, or `panic`.
- The evaluation is on record, so a future operator or agent asking "did we look at Jev" finds a
  dated answer instead of re-deriving it from a Slack thread or a closed issue.
- The revisit conditions give a concrete, falsifiable bar (pre-registered forward shadow study,
  pinned model version, existing 30-closed-trade checkpoint) rather than a vague "maybe later."

### Negative

- `FORBIDDEN_STEMS` in `supabase/functions/_shared/invariants.test.ts` matches on SDK import
  specifiers (`anthropic`, `openai`, `cohere`, `mistral`, `generative`, `genai`, `langchain`); it
  would not catch an OpenRouter client import, a Vercel `ai` SDK import, or a raw `fetch` call to
  a model endpoint. This is stated here as a fact about the current mechanical guard, not as a
  request for a code change -- the reviewer's invariant check (a human/agent review gate, not a
  mechanical one) is the only barrier against that class of integration today.
- Revisiting this decision later means someone has to re-read the vendor docs again, since none of
  the vendor claims are independently verified here -- this entry records what was reviewed and
  concluded, not a benchmark result.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Adopt the Jev hold/close architecture as proposed | Rejected now: reintroduces the pre-pivot "model advises, guards control" pattern and conflicts with the "One decision rule" and "No LLM in the trading path" invariants. |
| Run the shadow study now | Deferred, not rejected: the hourly bot does not yet have a closed-trade sample large enough for a meaningful forward comparison; see Revisit conditions. |
| Backtest Jev against historical bars instead of a forward shadow study | Rejected: a hosted model's backtest result carries training-data lookahead leakage risk and cannot be trusted as clean evidence. |
| Self-host Jev via vLLM or SGLang | Only fixes the silent-model-version-drift weakness; does not address the structural "model advises" pattern, the uncalibrated-probability weakness, or the lookahead-leakage weakness of any retrospective test. |
| Non-trading tooling use only (triage/routing in verification or reflection flows) | Deferred: worth revisiting if volume or cost ever justifies it over a constrained-output small model, but not evaluated in depth here. |

## Cross-references

- Vendor / OpenRouter documentation:
  - https://openrouter.ai/typesafe
  - https://openrouter.ai/docs/guides/community/jev
  - https://vercel.com/kb/guide/typesafe-jev-and-ai-sdk
- [Architectural invariants](../../CLAUDE.md#architectural-invariants) (CLAUDE.md)
- [2026-07-27-hourly-candlestick-signal.md](2026-07-27-hourly-candlestick-signal.md) (the current, single live decision rule this decision protects)
- [docs/superpowers/specs/2026-07-27-hourly-bot-design.md](../superpowers/specs/2026-07-27-hourly-bot-design.md) (design spec, including the "Review checkpoint" referenced in Revisit conditions)
- [docs/runbooks/weekly-review.md](../runbooks/weekly-review.md) (`PROPOSAL_MIN_CLOSED_TRADES` referenced in Revisit conditions)
- #655, #656
