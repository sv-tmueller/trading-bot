# Replace the 200-DMA regime signal with an hourly candlestick long/short rule on SPY (paper-only)

**Date:** 2026-07-27
**Status:** accepted

---

## Context

Batch #464 (operator sign-off at `/tm-advisor` 2026-07-27, after two revise rounds) directs a
strategy-direction overhaul: replace the paper-deployed (never live, #230 go-live never
happened) 3x UPRO / 200-DMA regime bot with a new bot that scans **1-hour SPY candles** and
trades **long or short** on the Alpaca **paper** account, using classic candlestick pattern
detectors (`backtest/candlestick.py`'s 14-detector registry) as the v1 signal.

The decision is made **against a disclosed evidence base**, not a demonstrated edge:

- `docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md` (#422) reaches a class
  NO-GO for short-horizon rule-based entries generally, closing on a cost wall (killing the
  minute end and all intraday crypto) and a data wall (no free intraday history clears the
  repo's own n_w = 13 comparability bar). The one honest nuance: 1-hour US-equity cost drag
  (≈1.7%/yr) is the single cadence/universe cell that survives the cost wall outright, and
  PDT does not bind at the paper account's ~$100k equity class.
- `docs/research/2026-07-26-candlestick-timestop-preregistration.md` (#448) closes the
  candlestick pattern family on **daily** SPY bars at cumulative N=168 (v1 N=28 + v2 N=56 +
  v3 N=84) — 0/168 cells cleared the frozen after-tax-Calmar bar; the pooled #398
  overfitting gate FAILs at every round.
- #457's MES swing-contracts survey closes at cumulative N=24 — 0/24 cells cleared either
  preset.

**The load-bearing distinction:** all three closed studies above are **daily**. This bot
runs on **hourly** bars. #422 §3 establishes that an hourly candlestick grid cannot be
credibly pre-registered and power-tested on any free data source at all (the free feed this
bot's paper account will actually use, IEX from 2020-07, reaches only n_w ≈ 5 against the
frozen n_w = 13 bar). So this is not a re-run of a closed cell — it is a cadence this repo's
own research method says it cannot currently evaluate for free. The bot therefore ships with
**no pre-registered evidence of edge of any kind**, favourable or unfavourable, by explicit
operator direction, with the Alpaca **paper** account as the accepted risk container.

Full detail — the honest evidence context, the signal contract, sizing, order model, safety
stack, persistence, config, and the weekly review loop — is specified in
`docs/superpowers/specs/2026-07-27-hourly-bot-design.md` (the design spec this ADR
ratifies). This ADR exists to record the decision itself, and to make one specific,
invariant-level ruling explicit that the spec depends on but should not itself be the sole
record of (per CLAUDE.md's rule that the Architectural invariants section is never restated
elsewhere as a second source of truth).

## Decision

**Replace** the live decision rule — SPY close vs. its 200-day moving average
(`computeTargetState`, `supabase/functions/_shared/regime.ts`) — with a new composite pure
function, `decideHourly`, that evaluates SPY's completed 1-hour candles against the frozen
14-detector candlestick registry and returns exactly one of `LONG` / `SHORT` / `SKIP` per
bar, per the design spec's §5 signal contract. The new bot trades on the Alpaca **paper**
account only, gated by a three-layer mechanical paper-only guard (spec §8.3) — no live-money
surface exists anywhere in this decision or the batch it belongs to.

**This ADR explicitly ratifies N1(a) from the design spec's sub-plan: for a 14-detector
registry, "one decision rule" (CLAUDE.md's invariant #1) means the single composite pure
function that combines them — `decideHourly`, one function, one frozen configuration
(the registry, the conflict tie-break, the cooldown, and the daily entry cap, frozen
together) — not any one individual detector read in isolation, and not a parallel overlay of
several independently-firing rules.** This is a **redefinition of what "one rule" means**
for a many-detector signal source, not merely an application of the existing text, so it is
recorded here as an explicit ratification rather than left to be inferred from the spec's
prose. The invariant's actual target — preventing multiple, independently-evolving decision
paths from competing or overriding each other unpredictably, the v1.14 failure mode — is
preserved: `decideHourly` is a single, frozen, fully deterministic function with exactly one
output per bar, mechanically invariant-scanned the same way `regime.ts` is today.

The old value (SPY close vs. 200-DMA, evaluated once per trading day, LONG/CASH only on
UPRO) is replaced by the new value (14-detector composite candlestick signal, evaluated once
per completed 1-hour SPY bar, LONG/SHORT/SKIP with session-close flatten, sized 1% risk /
10% notional cap per trade, R=2 bracket target). The old rule's deprecation — pausing entries
on the UPRO bot while its kill-switch keeps guarding until flat — is P1's decision, recorded
in its own ADR (#465; cross-referenced below).

## Consequences

### Positive

- A testable, deterministic live contract: `decideHourly` has exactly one output per bar,
  is I/O-free, and is unit-testable the same way `computeTargetState` is — no second,
  parallel decision path is introduced.
- Honest disclosure: the evidence context (#422/#448/#457) travels with the decision itself,
  so a future reader (human or agent) knows exactly what was and was not known when this bot
  was authorized, rather than discovering the NO-GOs separately and wondering why they were
  not mentioned.
- Mechanical containment: the paper-only guard (three independent layers, spec §8.3) means
  the absence of a demonstrated edge cannot translate into live-money risk regardless of any
  future config mistake or code regression — the worst case is a bad paper-trading result,
  not a bad live one.
- Surfaces and schedules the fix for two real safety gaps in the *existing* live-path code
  (kill-switch blind to shorts; panic long-only and `BOT_TICKER`-keyed) that would otherwise
  have gone unnoticed until this bot's first short position exposed them live.

### Negative

- **This bot ships with no pre-registered evidence of edge, at either polarity.** Unlike the
  three closed studies it cites, there is no verdict — favourable or unfavourable — for the
  hourly-candlestick-on-SPY cell specifically, because the repo's own research method
  (#422 §3) says that cell cannot currently be power-tested on free data. This is a
  materially weaker evidentiary position than "tested and failed."
- Widens the live-path surface materially: shorts (a new position polarity the kill-switch
  and panic do not yet handle correctly), bracket orders (a new order type the client does
  not yet support), and multiple trades per symbol per day (a new claim-key granularity the
  existing per-trading-day claim cannot express). Each of these is a new class of failure
  mode that the 200-DMA/UPRO bot's simpler LONG/CASH-once-daily shape never had to handle.
- The paper-only container is a mitigant, not a proof: a paper account faithfully exercises
  the code paths (fills, brackets, reconciliation) but not the psychological or liquidity
  realities of real capital, so a clean paper run is not by itself sufficient grounds for a
  future go-live decision — that decision, if it ever arises, needs its own pre-registered
  bar, exactly as the 2026-07-06 ADR this one supersedes required for the bot it kept.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Hold the 200-DMA / UPRO bot as-is, do not build the hourly bot | Rejected by explicit operator direction at `/tm-advisor` 2026-07-27 (batch #464): the operator's stated next-generation direction is hourly/minute-candle entries, not the once-daily rule, and the 200-DMA bot's own 2026-07-06 ADR already recorded it as "no Calmar edge over SPY" — holding it is not a null-risk choice, it is holding a bot with its own documented lack of edge. |
| Paper-trade nothing until a candidate clears a pre-registered backtest bar (the discipline every research study in this repo otherwise follows) | Rejected for this specific cell because #422 §3 shows the bar itself cannot be cleared on free data at this cadence — insisting on it would either indefinitely block the operator's stated direction or require an unauthorized data spend (Databento/FirstRate) that the batch does not authorize. The operator's accepted trade-off is to run the paper-only container instead of the usual pre-registration gate, with that trade-off disclosed here and in the spec, rather than silently lowering the bar without saying so. |
| Run the hourly candlestick rule as a research-only backtest first (daily bars, or a paid intraday feed), and only spec/build the live bot if it clears the after-tax-Calmar bar | Rejected as the *sole* path: a daily-bar backtest of an hourly rule would not actually test the rule this bot runs (different cadence, different bar geometry, different feed), and a paid-data intraday backtest is a spend decision outside this batch's authorization (#422 §3's own "what would have to change to revisit" list requires exactly this spend). Kept as a **future** option — nothing in this ADR forecloses running such a study later; it is simply not a precondition for this batch's paper-only build. |
| Treat each of the 14 candlestick detectors as its own independently-firing decision rule (N1(b) in the design spec's sub-plan) | Rejected: no evidence in this repo ranks one detector above another (all 14 were part of the family that returned NO_GO at cumulative N=168 pooled), so picking one detector as "the" rule would be an arbitrary, unranked selection dressed up as a decision. The composite-function reading (N1(a), ratified above) treats the whole registry plus its tie-break/cooldown/cap as one frozen configuration instead. |

## Cross-references

- `docs/superpowers/specs/2026-07-27-hourly-bot-design.md` — the design spec this ADR
  ratifies; contains the full signal contract, sizing, order model, safety stack,
  persistence, config, and weekly review loop.
- P1's deprecation ADR (#465, batch #464) — the operational retirement of the 200-DMA/UPRO
  bot (pause entries, liquidate if held, keep the kill-switch guarding until flat). Not yet
  merged as of this writing; cross-reference by issue number until its filename is known.
  This ADR (P2) carries the supersession rule (the replacement decision rule and its
  ratification); P1's ADR is the operational retirement and should reference this one.
- `docs/decisions/2026-07-06-keep-200dma-regime-signal.md` — the prior ADR that kept the
  200-DMA/UPRO bot as "an absolute-return bet with no Calmar edge over SPY." Its `Status`
  line is updated by this PR to `superseded by 2026-07-27-hourly-candlestick-signal.md`, per
  `docs/decisions/README.md`'s immutability rule (the only permitted edit to a merged
  entry) and this ADR's own sub-plan (D2): as of this PR, no other merged branch has made
  that edit (`git log origin/main -- docs/decisions/2026-07-06-keep-200dma-regime-signal.md`
  shows only the original 2026-07-07 merge commit, and no open PR at the time of this
  writing touches that file) — if #465's PR lands the same one-line edit first, whichever of
  the two merges second should rebase trivially onto a no-op for that line.
- Batch #464's decision log (issue body + comments) — the operator's original direction and
  the lead's D2 comment resolving the design spec's NEEDS_DECISION items (N1-N7), including
  the explicit ratification of N1(a) restated in this ADR's Decision section.
- `docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md` (#422),
  `docs/research/2026-07-26-candlestick-timestop-preregistration.md` (#448), and #457's
  MES swing-contracts survey — the disclosed evidence base.
