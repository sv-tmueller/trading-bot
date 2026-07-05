# Roadmap

This document captures the project's release roadmap and how versioned work is organised. Day-to-day issue tracking happens in [GitHub Issues](https://github.com/sv-tmueller/trading-bot/issues); milestones group issues by release.

For currently deployed configuration and parameters, see [`docs/CURRENT_CONFIG.md`](docs/CURRENT_CONFIG.md).

## How we use milestones and labels

- **Milestones** mark release scope. An issue's milestone answers *"which release does this land in?"*
- **Labels** mark cross-cutting properties (`bug`, `enhancement`, `priority:*`, `status:*`, `strategy`, `testing`, etc.) — these are orthogonal to release scope.
- An issue without a milestone is unscoped and treated as backlog until triaged by Lead.

## v1.x — Current sprint

**Milestone:** [`v1.x`](https://github.com/sv-tmueller/trading-bot/milestones/1)

**Theme:** live-trading hardening, observability, and incremental improvements to the long-only trend-following strategy that ships in v1.0.

The bot is in paper trading on the v1.10/v1.11 safety stack as of 2026-04-30. Work in this milestone is scoped to:

- Stability and safety-stack hardening (already shipped: deterministic exposure cap, bracket orders with fresh-quote pricing, kill switch, monitor reconciliation, panic CLI — `docs/research/swing-trading/roadmap.md` candidate 9.1, shipped in v1.13.0 / [#128](https://github.com/sv-tmueller/trading-bot/pull/128))
- Backtest realism (slippage, ADV cap, gap fills — see [#94](https://github.com/sv-tmueller/trading-bot/issues/94))
- Risk-parameter tuning (sector concentration, exposure cap, parameter sweeps — see [#61](https://github.com/sv-tmueller/trading-bot/issues/61), [#63](https://github.com/sv-tmueller/trading-bot/issues/63), [#65](https://github.com/sv-tmueller/trading-bot/issues/65))
- Architecture cleanup that doesn't change strategy direction (broker abstraction — see [#95](https://github.com/sv-tmueller/trading-bot/issues/95), [#96](https://github.com/sv-tmueller/trading-bot/issues/96))

Anything that changes signal direction, sizing math, or risk model belongs in v2.0+ instead.

## v2.0 — Future major

**Milestone:** [`v2.0`](https://github.com/sv-tmueller/trading-bot/milestones/2)

The pre-pivot v2.0 framing (short-side support on the since-retired pre-pivot architecture, tracked under umbrella issue #66, now closed) was superseded by the 2026-05-07 rules-engine pivot and the MVP 2.0 migration (#220).

There is currently no committed theme for the next major — the milestone is empty. Any future strategy change must be a deterministic rule that passes a research-first gate and a fresh brainstorm/spec, per CLAUDE.md ["Architectural invariants"](CLAUDE.md#architectural-invariants). Candidate research lives in [`docs/research/`](docs/research/) (2026-06 survey series; the leveraged-regime study conclusion is a pending operator decision — see [#255](https://github.com/sv-tmueller/trading-bot/issues/255)).

## Parking lot

Ideas captured for future consideration but not yet committed to a release. No milestone — promoted to v1.x or v2.0 when committed.

(Currently empty. As v1.x and v2.0 work proceeds, ideas that don't fit either land here for later triage.)

## Updating this document

This file is the source of truth for *direction*, not for *progress* — issue counts and PR status live in GitHub. Update this file when:

- A new release theme emerges (add a new section)
- A v2.0 phase is reached (move work into v1.x as it becomes near-term)
- An umbrella issue's framing materially changes (sync the prose here)

Routine sprint movement (issues opening, closing, labels changing) does not require a roadmap update.
