# Trading Bot Project: Context Handover for Claude Code

> Handover document from a Claude chat session. Use this as background context for upcoming Claude Code work on the Alpaca swing trading bot.

---

## 1. Project Overview

- **What:** Fully automated swing trading bot
- **Stack:** Python, Alpaca REST/WebSocket API
- **Hosting:** IONOS VPS (Docker), single-user
- **Style:** Vibecoded; rapid iteration
- **Strategy class:** Swing trading (multi-day holds), US equities
- **Status:** Bot exists and runs. Currently improving the backtest engine before scaling capital.

**Owner profile:** Hamburg-based, German resident, English+German bilingual, ServiceNow consulting background, comfortable with Python but treats this project as a vibecoded side project, not production-critical infra. Direct, decision-oriented communication preferred. **No em dashes anywhere in output.**

---

## 2. Strategic Context: Why Alpaca, Not IBKR

A broker comparison was done earlier. Conclusion: **stay on Alpaca for the bot, use IBKR (or a German broker) for actual long-term investment depot.** Do not conflate the two.

### Why Alpaca is right for the bot

- Clean REST + WebSocket, API-key auth, JSON in/out
- Identical paper and live endpoints (frictionless promotion)
- High LLM coding accuracy (large public training corpus)
- Stateless: no local gateway process to babysit
- Free IEX market data, sufficient for swing timescales
- Single Docker container fits the existing VPS setup

### Why IBKR was rejected for this use case

- Requires a long-running Java gateway (TWS or IB Gateway, or CP Gateway)
- Sessions reset daily, 6-minute idle timeout, 24-hour max session, daily IBKR maintenance windows force reconnects
- 2FA on every gateway restart
- Per-exchange market data subscriptions (~$4.50 + $10/month bundles)
- LLM coding accuracy noticeably lower; more boilerplate

### Where IBKR would win, but does not matter here

Margin rates, asset breadth (futures/options/FX/bonds), global equities, EUR base, SmartRouting. None of these move the needle on a multi-day-hold US equity strategy.

### German tax reality (applies to both)

- Both are foreign brokers from a Finanzamt perspective; neither withholds Abgeltungsteuer at source
- Anlage KAP must be filed manually
- IBKR provides an "Informativer Steuerbericht"; Alpaca does not. Helper tools exist for IBKR (BubbleTax, Alpha Convert)
- **US ETFs (SPY/QQQ/VOO) lose Teilfreistellung**, full 26.375% on gains. Build the strategy around individual equities, not US ETFs.

### Capital sizing rule

Cap Alpaca exposure at experimental capital that can be manually tax-reported. Long-term wealth (Vanguard FTSE All-World, etc.) belongs on a German-tax-friendly broker (CapTrader/BANX as IBKR Introducing Brokers, or Trade Republic/ING/comdirect/Scalable).

Port to IBKR only after 6+ months of proven live edge, as a deliberate scaling milestone.

---

## 3. Current Workstream: Backtest Engine Upgrade

The backtest engine is being upgraded. Three sequenced decisions have been made.

### Decision 1: Which improvement first?

**Chosen: Realistic frictions** (slippage, commission, ADV cap, partial fills, after-hours gaps).

Rejected alternatives and why:

- **Walk-forward optimization:** Gold standard, but walk-forward on a frictionless engine produces better-fitted fiction. Do this last.
- **Parameter sweeps + sensitivity:** A heatmap of unrealistic returns just shows which parameters maximally exploit unrealistic execution.
- **Better metrics + equity curve:** Cheapest to add, lowest information yield. Precise Sharpe on biased returns is a precise lie. Worth doing, but not first.

**Reasoning:** Every other option is a measurement or optimization layer built on top of the engine. If the engine reports fiction, those layers polish fiction. Swing trading specifically lives or dies on overnight gaps, so honest gap modeling is non-negotiable.

**Final order, end to end:**

1. Realistic frictions
2. Better metrics + equity curve
3. Parameter sweeps + sensitivity
4. Walk-forward optimization

### Decision 2: Friction model default behavior?

**Chosen: On by default, `--no-frictions` flag to disable.**

Rejected alternatives:

- **Off by default, opt-in via flags:** Inverts the path of least resistance; future-self forgets the flag and optimizes on fiction.
- **Realistic only, no escape hatch:** Slightly purer but loses two genuinely useful capabilities (signal-alpha isolation, legacy reproduction).

**Two additions agreed on:**

1. **Stamp the report.** Every backtest output must include the full friction config: slippage bps, ADV cap, commission constants, code version hash. This makes old reports interpretable rather than non-comparable.
2. **Treat cutover as a recalibration event, not a regression.** Run the current best strategy under the new friction model once, save that as the new baseline, discard frictionless results from decision-making going forward. Do not maintain dual numbers.

### Decision 3: PR sequencing?

The work has been split into two PRs:

- **PR 1:** Broker abstraction (architectural layer)
- **PR 2:** Realistic friction model (built on PR 1)

**Chosen: PR 1 only, then review, then PR 2.**

Rejected alternatives:

- **Both PRs back-to-back on parallel branches:** Architectural feedback on PR 1 cascades into rework on PR 2. Sunk-cost bias makes you reluctant to accept PR 1 changes once PR 2 exists. Review fatigue degrades the deeper review.
- **Single combined PR:** Cannot revert friction model independently of abstraction; harder to bisect bugs.

**Process suggestion adopted:** When opening PR 1 as draft, write the PR description **as if PR 2 already exists**. List the methods PR 2 will call and the contract assumptions it will make. Forces the abstraction to be reviewed for its actual use case.

---

## 4. Concrete Implementation Guidance

### PR 1: Broker Abstraction

**Purpose:** Decouple strategy/backtest engine from Alpaca specifics, enable swap to IBKR (or any other broker) later, enable in-memory simulation in backtests.

**Minimum surface to nail down:**

- Order placement (market, limit, bracket, stop)
- Order cancellation
- Position queries
- Account/cash queries
- Market data fetch (historical bars, quotes)
- Clock / market-open status

**Things the abstraction must handle from day one:**

- Async vs sync contract (pick one and document; sync is fine for swing timescales)
- Error contract (typed exceptions, not string parsing)
- Idempotency keys for orders (so daemon restarts do not double-submit)
- A clear "BacktestBroker" implementation alongside the AlpacaBroker so PR 2 has somewhere to plug in

**PR description should include:** the exact method signatures PR 2 will consume, plus a stub `BacktestBroker` class showing where friction logic will live.

### PR 2: Realistic Friction Model

**Plugged into:** the `BacktestBroker` from PR 1.

**Components:**

1. **Slippage model**
   - Default: 5 bps for liquid large-caps, 10 bps for mid-caps (configurable)
   - Better long-term: spread-based for limits, midpoint-plus-half-spread for markets, or % of ATR
2. **ADV cap**
   - Reject or partially fill orders that exceed X% of recent average daily volume
   - Default cap value to be agreed (start with 1% ADV)
3. **Commission constants (Alpaca-specific)**
   - SEC fee: ~0.0000278 of sale value (sells only)
   - FINRA TAF: ~0.000166 per share, capped per trade
   - No equity commission on Alpaca
4. **Gap handling**
   - Earnings gaps, weekend gaps, news gaps
   - Stop loss can be jumped (fill at next open, not at stop price)
   - Take profit can be skipped (gap-through means market fill, not limit fill)
5. **Partial fills (optional v1, recommended v2)**
   - Limit orders may fill partially or not at all
   - Simple model: fill probability proportional to (limit price closeness to NBBO) and ADV-cap headroom

**Defaults:** All on. Disable via `--no-frictions` CLI flag. Stamp every report with the resolved config.

### Sanity Check After Implementation

Run current backtest twice:

1. With new friction model on (defaults)
2. Frictionless

If "great" becomes "marginal" between (2) and (1), that confirms the friction work was needed and the prior numbers were misleading. Document the delta in the recalibration baseline.

---

## 5. Hard Constraints / Style Rules

- **No em dashes anywhere.** Use commas, colons, semicolons, parentheses, or separate sentences.
- **Honest by default, escape hatches named explicitly.** Applies to flags and config.
- **Frictionless mode is for diagnostics only,** not for performance numbers.
- **Don't maintain dual numbers post-cutover.** New friction model is the only truth going forward.
- **No US ETFs in the strategy** (Teilfreistellung loss). Individual equities only.
- **Idempotent everything.** Daemon restarts must not double-submit, double-count, or corrupt state.

---

## 6. Open Questions for the Claude Code Session

These were not resolved in the chat and need decisions during implementation:

1. Sync vs async API for the broker abstraction (recommend sync for simplicity, swing timescales tolerate it)
2. Concrete ADV cap default value (start at 1%, revisit after first realistic backtest)
3. How granular the slippage model should be in v1 (flat bps by liquidity bucket vs per-symbol ATR-based)
4. Whether partial fills go in PR 2 or a follow-up PR 3
5. Where to store the friction config: CLI flags only, YAML config file, or both

---

## 7. Quick Reference: Decisions Already Made

| Question | Answer |
|---|---|
| Broker for the bot | Alpaca |
| Broker for long-term wealth | Not Alpaca (German broker or IBKR via Introducing Broker) |
| First backtest improvement | Realistic frictions |
| Friction default | On, `--no-frictions` to disable |
| PR sequencing | PR 1 (broker abstraction) first, review, then PR 2 (frictions) |
| Stamp reports with config? | Yes, always |
| Maintain frictionless numbers in parallel? | No, recalibrate and move on |
| US ETFs in strategy? | No (German tax) |

---

*End of handover. Start the next session by reading this file, then jump into PR 1.*
