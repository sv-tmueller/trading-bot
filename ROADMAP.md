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

- Stability and safety-stack hardening (already shipped: deterministic exposure cap, bracket orders with fresh-quote pricing, kill switch, monitor reconciliation)
- Backtest realism (slippage, ADV cap, gap fills — see [#94](https://github.com/sv-tmueller/trading-bot/issues/94))
- Risk-parameter tuning (sector concentration, exposure cap, parameter sweeps — see [#61](https://github.com/sv-tmueller/trading-bot/issues/61), [#63](https://github.com/sv-tmueller/trading-bot/issues/63), [#65](https://github.com/sv-tmueller/trading-bot/issues/65))
- Architecture cleanup that doesn't change strategy direction (broker abstraction — see [#95](https://github.com/sv-tmueller/trading-bot/issues/95), [#96](https://github.com/sv-tmueller/trading-bot/issues/96))

Anything that changes signal direction, sizing math, or risk model belongs in v2.0+ instead.

## v2.0 — Future major

**Milestone:** [`v2.0`](https://github.com/sv-tmueller/trading-bot/milestones/2)

**Theme:** bidirectional regime coverage. The bot is currently structurally a directional bet on bull markets — v2.0 adds short-side capability so it can be profitable in both trending-bull and trending-bear weeks.

**Umbrella issue:** [#66](https://github.com/sv-tmueller/trading-bot/issues/66) — short-side strategy support. The 2026-04-30 comment on that issue captures the v2 framing, the architectural impact analysis, and the open design questions.

### Decision gates (research-first phasing)

Before any live plumbing for shorts:

1. **Bearish signal must show standalone positive expectancy.** Backtest the symmetric inverse signal (EMA20 < EMA50, etc.) on 5y/10y data. Kill the idea here if PF < 1.1 on the inverse alone — trend-following inverted often loses (trends persist longer than they reverse).
2. **Combined long+short backtest must improve Sharpe vs long-only.** No point adding shorts if they only add variance.
3. **Deterministic risk caps must exist before any LLM proposes a short.** Short side has unbounded theoretical upside; CLAUDE.md invariant addition required (max short notional, max gross/net exposure, max long-vs-short skew).

### Architectural changes for v2.0

Bigger than the v1.10/v1.11 safety stack combined. Touches:

- Strategy agent (bearish signal generation)
- Risk layer (separate `MAX_NET_EXPOSURE` vs `MAX_GROSS_EXPOSURE`, short-specific stop logic)
- Position sizer (direction-agnostic share count, sign convention)
- Broker (`place_short_order`, bracket leg orientation flip)
- Monitor (exit comparisons flip for shorts)
- Schema (`side` column on trades)
- Agent prompts (long/short candidate format)
- CLAUDE.md invariants (short risk caps)

When v2.0 work begins, [#66](https://github.com/sv-tmueller/trading-bot/issues/66) splits into three phased issues (research spike → combined backtest → live plumbing), each gated on the previous decision.

## Parking lot

Ideas captured for future consideration but not yet committed to a release. No milestone — promoted to v1.x or v2.0 when committed.

(Currently empty. As v1.x and v2.0 work proceeds, ideas that don't fit either land here for later triage.)

## Updating this document

This file is the source of truth for *direction*, not for *progress* — issue counts and PR status live in GitHub. Update this file when:

- A new release theme emerges (add a new section)
- A v2.0 phase is reached (move work into v1.x as it becomes near-term)
- An umbrella issue's framing materially changes (sync the prose here)

Routine sprint movement (issues opening, closing, labels changing) does not require a roadmap update.
