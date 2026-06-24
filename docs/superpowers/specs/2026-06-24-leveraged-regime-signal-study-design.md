# Leveraged-regime-signal study: design

Date: 2026-06-24
Issue: #255 (strategy direction). Follows the candidate survey (#314 first cut, #315 second cut; both merged) and PR #306 (the #255 goal spec).
Status: design approved in brainstorm 2026-06-24; research-only, no live-bot change.

## Context

The #255 candidate survey is complete across both cuts: **no low-turnover 1x strategy beats SPY's
after-tax Calmar** (GEM dual-momentum, Faber single + GTAA, vol-targeting all fail; the strongest
single signal is the dumb tsmom-12mo baseline). Separately, #254 + the W25 soak read the live **3x
UPRO / 200-DMA regime bot** as roughly SPY's return at ~2x the drawdown, i.e. leveraged beta, not edge.

The operator's decision (brainstorm 2026-06-24): **keep the 3x leverage, attack the drawdown.** Do
not deleverage; instead test whether a better regime signal than the 200-DMA can cut the leveraged
bot's drawdown enough to finally clear SPY's after-tax Calmar bar (the bar the 1x survey could not).
This stays inside the **one-decision-rule invariant**: the winning signal *replaces* the 200-DMA
(still: trend -> LONG UPRO / CASH), it is not a second rule.

## Question and bar

**Question:** does replacing the 200-DMA regime filter with a better trend signal make 3x UPRO
clear 1x SPY's after-tax Calmar, by cutting max drawdown toward SPY's (~-34%) while keeping
CAGR >= SPY?

**Bar (a signal clears only if both hold):**
1. Beats **1x SPY** on full-history after-tax Calmar (CAGR >= SPY and max DD cut enough that
   Calmar > SPY), the #255 bar, applied to the leveraged position.
2. Beats the **incumbent 3x/200-DMA bot** on after-tax Calmar (it must be a real improvement on what
   is already live).

**If nothing clears:** the 200-DMA stands, and #255 concludes that 3x is an absolute-return bet, not
a risk-adjusted edge, returning the operator to that fork honestly, with evidence.

## Signals tested (4)

All low-turnover trend filters, so the no-loss-credit tax-model limitation (flagged on batch #317)
does NOT bite here, so these can be evaluated as-is.

1. **200-DMA**: the incumbent baseline (SPY close vs its 200-day SMA).
2. **tsmom-12mo**: 12-month time-series momentum; the strongest single signal in the 1x survey.
3. **Faster MA**: a 10-month / ~210-day SMA (faster exit than the 200-DMA, to leave drawdowns sooner).
4. **200-DMA + confirmation**: the 200-DMA with a whipsaw filter (e.g. require 2 consecutive
   breaching closes, or price-and-slope) to cut false exits.

## Leverage model

**Synthetic 3x SPY, daily-rebalanced**, reusing `backtest/synthetic.py` from #254. Synthetic
leverage is preferred over real UPRO because it extends history to 1993 (capturing the 2000 and 2008
bears that real UPRO, inception 2009, misses) and models the daily-rebalance volatility decay
honestly. **Cross-check** the synthetic series against real UPRO over the overlapping window
(2009->) for realism. The regime filter trades LONG synthetic-3x / CASH.

## Harness and method

Reuse the survey foundation (no reimplementation):
- The #263 walk-forward machinery + the weighted simulator (`simulate_from_signal`).
- Per-window CAGR + Calmar (`walkforward.py`), the US/DE after-tax layer (`backtest/tax.py`), the
  0.05% + 0.05% per-side cost model.
- Full-history after-tax Calmar as the ranking basis; the per-window 12-month OOS pass as the
  stability gate; 2020 + 2022 bear stress.
- No look-ahead: signal on the completed bar, executed next open.

Each of the 4 signals runs on synthetic 3x SPY, ranked against each other, the incumbent 3x/200-DMA
bot, and 1x SPY.

## Deliverable

A `docs/research/` findings doc with the ranked table (after-tax Calmar US/DE, CAGR, max DD,
turnover, vs SPY, vs incumbent, 2020/2022 bear) and a verdict against the bar. If a signal clears,
it earns its own spec -> plan -> implement (a separate change that swaps the live bot's regime
signal, replacing the 200-DMA). Nothing clears -> 200-DMA stands; #255 concludes.

## Scope, constraints, invariants

- **Research-only, one `size:M` package.** No production trading code changes; the live bot and the
  intraday kill-switch are untouched by the study (the study is about the slower regime filter only).
- **Invariants intact:** one decision rule (the winner replaces the 200-DMA, not a second rule); no
  LLM in any path; no live-bot change. Any implementation of a winner is a separate, later change
  with its own brainstorm-gated spec.
- **Out of scope:** intraday/high-frequency variants (ruled out, #308/#309); changing the leverage
  multiple (operator: do not deleverage); ensembles or multi-signal blends (a single replacement
  rule only; a broad search was the rejected approach C).

## Non-goals

- Not a decision to change the live bot. The study informs a *future* decision; it acts on nothing.
- Not a tax-model fix (not needed for these low-turnover signals; the no-loss-credit fix remains a
  separate flagged item for any future high-turnover candidate).
