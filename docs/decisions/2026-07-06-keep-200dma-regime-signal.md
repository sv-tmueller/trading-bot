# Keep the 200-DMA regime signal; hold the 3x UPRO bot as an absolute-return bet

**Date:** 2026-07-06
**Status:** accepted

---

## Context

Issue #255 opened a goals-first review of the live 3x UPRO / 200-DMA regime bot, prompted by the
2009->now backtest (#254) showing the bot roughly matching SPY's CAGR at about 2x SPY's drawdown.
The goal doc (`docs/superpowers/specs/2026-06-20-strategy-direction-goal-design.md`, PR #306) set a
falsifiable bar: any candidate must beat 1x SPY's **after-tax Calmar ratio** (CAGR / max drawdown) on
identical out-of-sample walk-forward windows, net of costs and tax, with a drawdown ceiling around
SPY's own (~-34%). If nothing clears the bar, the goal doc's own stated floor is to hold 1x SPY (or
ship nothing further) rather than ship a candidate that doesn't demonstrate an edge.

Three research artifacts followed, in order:

- **First-cut candidate survey** (#314, PR #316): a broad archetype survey (momentum, dual-momentum
  rotation, tactical allocation, mean-reversion, vol-targeting, risk-parity-lite) found nothing
  cleared the after-tax Calmar bar.
- **Vol-targeting second cut** (#315, PR #318): a focused second pass on vol-targeting/low-beta
  tilts, also cleared nothing.
- **Leveraged-regime-signal study** (design PR #319, study #321/PR #322,
  `docs/research/2026-06-24-leveraged-regime-signal-study.md`): tested whether a *better regime
  signal* than the incumbent 200-DMA could make 3x SPY clear 1x SPY's after-tax Calmar by cutting the
  drawdown toward SPY's while keeping the leveraged return. It found:
  - **tsmom-12mo on 3x SPY is Calmar-dominant over 1x SPY** — after-tax Calmar 0.22 vs 0.18, CAGR
    +19.9% vs +10.8%, per-window stability 0.90 vs 0.85 — but carries a **-76.2% max drawdown**,
    more than double SPY's own -34% (SPY's -55.2% here reflects the full 1993-2026 window; the
    goal doc's ~-34% ceiling is SPY's typical single-bear drawdown).
  - Faster signals fail outright: the **100-DMA** is ruinous at 3x (-91.9% max DD, whipsaw-driven);
    the **200-DMA + 2-day confirmation** only marginally reduces drawdown and fails the per-window
    OOS stability gate.
  - **No signal cuts the 3x drawdown to SPY-like levels while holding a stable Calmar edge.**

Separately, the 2026-06-26 give-back observation on #255 gave a concrete, live data point on
drawdown tolerance: the dev paper bot's unrealized gain round-tripped from +$72.7k to roughly +$7k
on only a -10.4% UPRO drawdown from its 30-day high — both the kill-switch (-25% threshold) and the
200-DMA correctly stayed silent (nothing crashed; the leveraged gain simply gave back with a normal
SPY pullback). The operator's reaction to that live give-back, even though every safeguard behaved
exactly as designed, is evidence that the -76% path risk of tsmom-12mo is well outside the
operator's demonstrated tolerance.

## Decision

Keep the 200-DMA regime signal as the bot's one decision rule. The 3x UPRO bot is held as an
**absolute-return bet, not a risk-adjusted edge over SPY** — no candidate surveyed under #255
clears the after-tax-Calmar bar the goal doc set at a survivable drawdown. This concludes #255
(operator decision, batch #340, 2026-07-06). No parameter, code, or production change results from
this decision.

## Consequences

### Positive

- #255 is resolved with a recorded, evidence-based rationale instead of remaining open indefinitely.
- #230 (go-live) is unblocked as a pure operator decision — it no longer waits on an open
  strategy-direction question.
- The bot keeps its existing, already-live, already-tested one-decision-rule contract
  (`computeTargetState` in `supabase/functions/_shared/regime.ts`); no new signal, spec, or backtest
  is required.

### Negative

- The bot's absolute-return risk is accepted as-is: a binary 3x/200-DMA position can draw down on
  the order of -58% to -60% (per the #321 study's incumbent row) in a deep bear, roughly double
  SPY's typical -34%. This is a known, accepted risk, not a residual one to be revisited under this
  decision.
- The after-tax Calmar goal set by the #255 goal doc is explicitly **not met**. No candidate
  surveyed across three research passes cleared it at a drawdown the operator is willing to hold
  through. This is recorded as an honest null result, not a hidden gap.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Adopt tsmom-12mo as the regime signal on 3x SPY | Calmar-dominant over 1x SPY (0.22 vs 0.18 after-tax, CAGR +19.9% vs +10.8%, stability 0.90 vs 0.85) but carries a **-76.2% max drawdown**, far outside the operator's demonstrated tolerance (the 2026-06-26 give-back reaction at only -10.4%). Would also require its own brainstorm + spec + backtest as a second decision rule, and a hard look at whether the kill-switch materially caps that path risk. |
| Faster signal: 100-DMA on 3x | Cuts the single COVID-2020 crash (-26.7% vs the incumbent's -34.0%) but is ruinous over full history: -91.9% max drawdown, after-tax Calmar 0.06, negative per-window stability. Faster is worse, not better, at 3x. |
| 200-DMA + 2-day confirmation | Only marginally reduces drawdown (-58.2% vs incumbent -59.5%) and fails the per-window OOS stability gate (median 0.21 vs SPY's 0.85) — its thin full-history edge is not robust out-of-sample. |
| Deleverage to 1x SPY | Rejected by the operator earlier in #255 ("do not deleverage" stands) — the operator wants to keep the 3x leverage and accept the drawdown as an absolute-return bet rather than match SPY's risk profile. |
| Ship nothing / hold 1x SPY | This is the goal doc's own honest-outcome floor (section 7) for the case where no candidate clears the bar. It is subsumed by this decision: keeping the current bot **is** the "ship nothing further" outcome, just expressed as "keep what's live" rather than "replace it with 1x SPY." |
