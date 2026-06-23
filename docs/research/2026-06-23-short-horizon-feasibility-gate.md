# Short-horizon deterministic strategy — feasibility gate

**Question:** Can a deterministic, short-horizon (≈5-minute loop, intraday/scalping) rule that
manages one trade at a time — long/short with entry, stop-loss, take-profit — plausibly clear
#255's bar of **beating SPY on after-tax Calmar**, once realistic transaction cost, the PDT rule,
and tax drag are priced in? If the high-churn end cannot clear the bar, say so and stop.
**Issue:** #309 (batch #308)
**Date:** 2026-06-23
**Author:** Analyst (research-only; no production code, settings, backtester, or broker integration touched)

> **Method note.** This is a **literature-and-arithmetic** scoping doc, gated cheap-math-first per
> the architect's SUB_PLAN on #309. No backtests were run; no intraday backtester was built; no order
> was placed. Every numeric input is stated with a source or an explicit assumption. The arithmetic
> in Phase 1 is reviewer-re-derivable from the stated inputs (the `c/(2R)` and `trades_per_day × 252 × c`
> formulas below). The gate failed at (c) on costs alone, so Phase 2 sections (d)/(e)/(f) are stubs,
> not a full survey — writing the survey would manufacture a positive the math does not support and
> would balloon this `size:M` package.

---

## Assumptions stated up front

| Input | Value used | Source / basis |
|---|---|---|
| Asset class A | US-listed equity ETF on Alpaca **US Trading API** | Existing integration; `supabase/functions/_shared/alpaca.ts`. EU/Xetra equities are **Broker-API-only**, not reachable from a self-directed account today (`docs/research/alpaca-eu-expansion.md`). "Equities via Alpaca" therefore = US Trading API. |
| Asset class B | Crypto pair on Alpaca | New broker surface; **paper-only, no integration** (hard non-goal of #308/#309). |
| Account size | **≥ $25,000** assumed for the equity case (paper account ran ~$99k per `docs/research/2026-06-11-margin-increase-assessment.md`); **both sides of the $25k PDT line are shown** in (a). | — |
| Equity round-trip cost `c` | base **3 bps** of notional (range 1–5 bps tested) | Commission-free US-listed (fees ≈ 0); `c` = spread + slippage. Top-of-book spread on a liquid ETF (SPY/QQQ) is ~1 bp; assume ~1 bp slippage per side. Round trip = full spread crossed once each way + slippage ×2. Assumption, verify against live Alpaca fills. |
| Crypto round-trip cost `c` | base **60 bps** (fees-only floor **50 bps**; range to 80 bps) | Alpaca crypto fee schedule, **Tier 1 (0–$100k 30-day volume): maker 0.15% / taker 0.25% per side** (`docs.alpaca.markets/docs/crypto-fees`, fetched 2026-06-23). Market entries/exits are **taker**: 0.25% × 2 = **0.50% fees round-trip**, before a wider crypto spread + slippage (assume ~10 bps round-trip). |
| Take-profit / stop-loss size `R` | tested at 10 bps (tight scalp), 30 bps, 50 bps, 100 bps | The operator's sketch (TP/SL each loop) implies tight `R`. Symmetric TP/SL assumed. |
| US tax rates | short-term ≈ **35%** (ordinary), long-term ≈ **18.8%** (15–20% + 3.8% NIIT) | Representative US federal brackets; assumption, order-of-magnitude only. |
| EU/German tax rate | flat **≈ 26.375%** (25% Abgeltungsteuer + 5.5% Soli) | German flat capital-gains regime; **no short/long distinction**. Assumption per the logged tax decision on #308. |
| PDT rule | pattern day trader = **4+ day trades / 5 business days** in a margin account → **$25,000 minimum equity** required | FINRA Rule 4210; well-established. Applies to **equities only**, not crypto. |
| Plausible win-rate ceiling | ~**55–60%** sustained out-of-sample for a deterministic short-horizon rule | **Stated assumption**, not a sourced figure (Phase 2's literature survey is a stub). Used **only** to adjudicate the borderline equity 5/day cell; the robust core of the no-go (crypto ≥100% win rate, equity 10–20/day at 75–151%/yr drag) does **not** depend on it — see (c). |

---

## (g) Replace, not add — invariant framing (stated first, it governs everything below)

Per the batch contract (#308, locked decision 1) and **CLAUDE.md Architectural invariant #1 ("one
decision rule")**: any short-horizon class scoped here would **replace** the current regime-UPRO rule
(`computeTargetState`), swapping one deterministic rule for another. It would **never** run as a
second parallel live rule. One rule in, one rule out — the invariant holds by construction.

Cadence and the LLM line: a **5-minute *deterministic* loop is invariant-compatible** — it is the
same pure-function-on-a-bar decision the bot already makes, evaluated more often. The decision rule
stays reproducible from price history alone (invariant #1) and imports no model SDK (invariant #2,
"no LLM in the trading path"). What is **not** compatible is an **LLM deciding each loop** — the exact
shape of the YouTube crypto-scalper that prompted #308, and the exact surface the rules-engine pivot
removed. This doc assumes the deterministic case throughout; the LLM case is out of bounds before any
arithmetic.

---

# Phase 1 — Feasibility gate (cheap math first)

## (a) Cost break-even gate

**Definitions (held constant so the table is re-derivable).** A "trade" = one **round trip** (entry
fill + exit fill). `c` = round-trip cost as a fraction of notional = spread (crossed once each way) +
slippage ×2 + fees ×2. For a symmetric take-profit / stop-loss of size `R` (fraction of notional), the
required **win-rate uplift over 50%** to break even on cost is:

```
required win-rate uplift ≈ c / (2R)        (symmetric TP/SL of size R)
annualized cost drag      ≈ trades_per_day × 252 × c
```

### Equity ETF on Alpaca (commission-free US-listed; fees ≈ 0; `c` = spread + slippage)

Annualized cost drag (% of equity/yr), by `c` and trades/day (**2/5/10/20 columns = sub-$25k
PDT-illegal**, see callout below):

| `c` (round-trip) | 1/day | 2/day ⛔<$25k | 5/day ⛔<$25k | 10/day ⛔<$25k | 20/day ⛔<$25k |
|---|---|---|---|---|---|
| 1 bp (ultra-cheap) | 2.5% | 5.0% | 12.6% | 25.2% | 50.4% |
| 2 bps (cheap) | 5.0% | 10.1% | 25.2% | 50.4% | 100.8% |
| **3 bps (base)** | **7.6%** | **15.1%** | **37.8%** | **75.6%** | **151.2%** |
| 5 bps (wide) | 12.6% | 25.2% | 63.0% | 126.0% | 252.0% |

> **PDT line (HARD regulatory cut for equities).** Under **$25k** account equity, the PDT rule caps
> you at **3 day trades per rolling 5 business days** (FINRA Rule 4210) — i.e. **< 1 day trade/day**.
> The entire 2/5/10/20-trades/day region of this table is **legally unreachable below $25k**; a
> high-churn equity rule is **disqualified outright** for a sub-$25k account. **At/above $25k** the
> rule does not bind, so the table applies in full — and the *cost* arithmetic then kills the
> high-churn region on its own (see below). Account-size assumption: ≥ $25k (so the no-go rests on
> cost, not PDT); but for any operator running < $25k the PDT cut is an additional, independent
> disqualifier. Equities are also **US-market-hours only**; PDT does **not** apply to crypto.

Required win rate to cover cost, base `c` = 3 bps, by `R`:

| `R` (symmetric TP/SL) | `c/(2R)` | Win rate needed just to break even on cost |
|---|---|---|
| 10 bps (tight scalp) | 15.0 pp | **65.0%** |
| 30 bps | 5.0 pp | 55.0% |
| 50 bps | 3.0 pp | 53.0% |

The tighter the scalp (small `R`, the operator's sketch), the more punishing the cost: a 10-bp TP/SL
needs a **65% win rate before tax and before any profit** — and that is at the optimistic 3-bp cost.

### Crypto pair on Alpaca (NOT commission-free)

Alpaca charges a tiered crypto fee; a retail scalper sits in **Tier 1: maker 0.15% / taker 0.25% per
side**. Market orders are **taker**, so fees alone are **0.50% round-trip** — before spread/slippage.

Annualized cost drag (% of equity/yr), by `c` and trades/day:

| `c` (round-trip) | 1/day | 2/day | 5/day | 10/day | 20/day |
|---|---|---|---|---|---|
| 50 bps (fees only, taker) | 126% | 252% | 630% | 1,260% | 2,520% |
| **60 bps (base, + spread/slip)** | **151%** | **302%** | **756%** | **1,512%** | **3,024%** |
| 80 bps (wide) | 202% | 403% | 1,008% | 2,016% | 4,032% |

> These use 252 trading days for consistency with the equity formula; crypto trades **24/7 (~365
> days)**, so the true drag is ~45% higher than shown — the table **understates** the crypto kill.

Required win rate to cover cost, fees-only `c` = 50 bps, by `R`:

| `R` (symmetric TP/SL) | `c/(2R)` | Win rate needed just to break even on cost |
|---|---|---|
| 10 bps | 250 pp | **impossible (>100%)** |
| 50 bps | 50 pp | **100.0%** |
| 100 bps | 25 pp | 75.0% |

For crypto, a symmetric scalp with `R` ≤ the round-trip fee needs a **100% win rate just to break even
on fees**. At the operator's tight-`R` sketch the strategy is mathematically unwinnable on cost alone.

## (b) After-tax handicap vs #255's after-tax Calmar bar

#255 (PR #306) sets the bar as **beating SPY on after-tax Calmar** (CAGR ÷ max drawdown, net of cost
and tax, on identical OOS walk-forward windows). Churn fights tax as a **second** handicap on top of
cost. Modelled under **both** regimes per the logged decision on #308, neither hidden:

| | **US (ST vs LT)** | **EU / German flat-rate** |
|---|---|---|
| Rate on a realized gain | ST ≈ **35%** (ordinary) vs LT ≈ **18.8%** | flat **≈ 26.375%**, **no short/long distinction** |
| Rate-gap penalty for churn | **≈ 16 pp** of every realized gain (35% − 18.8%) — a high-churn rule realizes **all** gains short-term and forfeits the LT rate | **0 pp** — the regime collapses the rate-gap to nothing |
| Remaining handicap | rate gap **plus** loss of deferral/compounding | **deferral/compounding loss only** |

**Honest framing of the incumbent.** The literal incumbent is **not** a clean >1-year holder: it fires
~2.4 trades/yr at a ~2–5 month average hold (`docs/research/2026-06-11-margin-increase-assessment.md`),
so in the US it is itself *mostly short-term*. The relevant comparison the task names is churn vs an
**idealized low-turnover / deferring alternative** (the ">1yr holding" case): against that, US churn
gives up ~16 pp per realized gain plus deferral; German churn gives up only deferral.

**Points of pre-tax Calmar the churn strategy must add to neutralize the tax disadvantage.** Tax
scales CAGR multiplicatively and max drawdown is pre-tax (tax-invariant), so **after-tax Calmar =
pre-tax Calmar × (1 − τ)**. The answer is therefore a clean, turnover-independent multiplier. To tie
the after-tax Calmar of all-short-term churn (rate τ_ST) to a hold-for-LT alternative (rate τ_LT) on
the same pre-tax return: `Calmar_churn × (1 − τ_ST) = Calmar_LT × (1 − τ_LT)`, so
`Calmar_churn / Calmar_LT = (1 − τ_LT) / (1 − τ_ST)`.
- **US:** `(1 − 0.188) / (1 − 0.35) = 1.249` → the churn strategy must add **~25% to its pre-tax
  Calmar** just to neutralize the short-term rate penalty (plus an unquantified deferral/compounding
  loss on top). A 25% pre-tax Calmar uplift over the idealized deferring alternative — before any
  excess over SPY — is a steep tax-only handicap.
- **Germany:** flat rate, so τ is the same for churn and hold (`(1 − 0.26375)/(1 − 0.26375) = 1.000`)
  → the rate-gap handicap is **~0% pre-tax Calmar**; only the deferral/compounding loss remains, a
  small single-digit drag.

**Jurisdiction is load-bearing for the *tax* term but not for the verdict** — see (c). The cost no-go
in (a) lands first and is jurisdiction-independent, so tax is the **second nail**, not the deciding one.

> **Finding — jurisdiction ambiguity (recorded per #308).** The operator's signals point at EU/Germany
> (`.eu` email, German research sources, `alpaca-eu-expansion.md`) while the live Alpaca account is
> factually US (USD-denominated, US Trading API, UPRO a US ETF). The tax handicap differs materially
> between the two regimes (16-pp rate gap vs none). **Recommendation:** the operator should **confirm
> tax residence before any build batch.** This is a clean follow-up, not a blocker for this scoping doc.

## (c) Go / no-go on the high-churn end

**Threshold, stated before the verdict (common unit derived from (a)+(b), not a fresh parameter).**
The high-churn (intraday/scalping, ≈5/10/20 trades/day) end is a **no-go** if the **annualized cost
drag plus tax handicap** at a plausible 5-minute-cadence trade count **exceeds the excess after-tax
return any deterministic short-horizon edge could plausibly deliver**, such that the **required net
per-trade win rate to clear it exceeds a plausible ceiling** (a **stated assumption** of ~55–60%
sustained out-of-sample for a deterministic rule — Phase 2's literature survey is a stub, so this is
tagged as an assumption, not a cited figure). The verdict must follow arithmetically from (a)+(b).
**The robust core of the no-go does not rest on that soft ceiling:** crypto needs a ≥100% win rate
(definitional, from the 0.50% round-trip fee) and equity at 10–20 trades/day carries 75–151%/yr cost
drag (pure magnitude). The ceiling is load-bearing **only** for the borderline equity 5/day cell.

**Verdict: NO-GO on the high-churn end, robustly, under both tax regimes.**

| Region | Verdict | Why (from the stated inputs) |
|---|---|---|
| **Equity, ≥ 5 trades/day** | **No-go** | Cost drag alone is **37.8%/yr at 5/day** and **75.6%/yr at 10/day** at base 3-bp cost; even at an ultra-optimistic 1-bp cost it is 12.6% / 25.2%/yr. No deterministic short-horizon edge clears that *and* SPY's after-tax Calmar. **Jurisdiction-independent** — costs alone. |
| **Equity, < $25k account** | **No-go (regulatory)** | PDT caps you at <1 day trade/day; the entire high-churn region is legally unreachable. Independent of cost and tax. |
| **Crypto, any high frequency** | **No-go (hardest)** | Fees alone are **0.50% round-trip → 126%/yr drag at just 1 trade/day**, 1,260%/yr at 10/day. A tight symmetric scalp needs a **100% win rate to break even on fees**. Mathematically unwinnable. Jurisdiction-independent. |
| Tax overlay | strengthens the no-go | US churn must add ~25% to its pre-tax Calmar just to neutralize the short-term rate penalty; Germany adds only a deferral-only drag. Both **add to**, never offset, the cost no-go. |

**The no-go is robust to input uncertainty.** It does not hinge on any single uncertain number:
across the full stated equity range (1–5 bps) the high-churn region is killed at 10–20 trades/day in
every cell, and crypto is killed at **1 trade/day** by the **directly-sourced** Tier-1 taker fee
(0.25%/side). The verdict holds under both tax regimes because the deciding term — transaction cost —
is jurisdiction-independent.

**Scope of the verdict (precise).** This no-go is on the **high-churn / scalping region specifically
(≈5–20+ trades/day, the operator's 5-minute-TP/SL sketch)**. It does **not** kill lower-frequency
**swing-or-slower** rules: at 1 trade/day equity drag is ~2.5–12.6%/yr and at the incumbent's ~2.4
trades/**year** it is negligible. But low-frequency swing is **already #255's surveyed domain** (§6:
TS/cross-sectional momentum, dual-momentum rotation, mean-reversion swing, vol-targeting, judged on
after-tax Calmar via the #263 walk-forward harness). That is precisely **why we stop here rather than
re-survey it** — the cheap math has done its job: it rules out the new (high-churn) region and routes
the surviving (swing) region back to the channel that already owns it.

**STOP.** Phase 2 is therefore not developed. The Phase-2 headers below are retained for completeness
(acceptance criteria d/e/f) but are stubs, because the gate failed at (c) on costs alone.

---

# Phase 2 — Scope (NOT developed; gate failed at (c))

## (d) Candidate survey of short-horizon rule families — *not developed*

Gate failed at (c) on costs alone, so the high-churn rule-family survey is not written here. The
families the task names (mean-reversion, breakout, momentum, vol-targeting) and their swing-horizon
forms are **already in #255's survey scope** (§6) and are judged there on after-tax Calmar via the
#263 walk-forward harness — that is the correct home for them, not a high-churn re-survey. The
equities-via-Alpaca vs crypto fork is settled adversely above and need not be elaborated: equities
high-churn dies on cost (and PDT < $25k), crypto high-churn dies on the directly-sourced Tier-1 taker
fee (100% win rate needed to break even). **No follow-up survey of the high-churn region is
recommended.**

## (e) Data + backtest-infra plan — *not developed (sized as a follow-up only if a survivor ever emerges)*

Not built. For the record, validating *any* sub-5-minute rule would require, as a **follow-up** (not
this package): intraday bars (1-min or finer) from a paid vendor (the current `backtest/` feed is
daily-bar yfinance — `backtest/regime.py`), a fill/slippage model honest about spread and taker fees,
and a PDT/market-hours-aware execution layer added to `backtest/walkforward.py`. Since the gate failed,
**this infra is not recommended for build.** A swing-or-slower survivor from #255 needs none of it —
the existing daily-bar harness already covers that horizon.

## (f) Proposed goal / metric — *inherited from #255, unchanged*

No new metric is proposed. Any future short-horizon candidate is judged against **#255's existing bar**:
beat SPY on **after-tax Calmar** on identical OOS walk-forward windows, net of cost and tax, and beat
the dumb baselines (fee-adjusted B&H, persistence, Faber 10-mo, TSMOM 12-mo) — #255 §5. This doc adds
the **prior** that the high-churn end of that space is ruled out before it reaches the harness.

---

## Bottom line

The high-churn / intraday-scalping idea behind #308 is a **robust no-go**, and the honest negative
result is the deliverable:

- **Cost kills it first, jurisdiction-independently.** Equity cost drag is **37.8%/yr at 5 trades/day,
  75.6%/yr at 10/day** (base 3-bp round-trip); crypto is far worse — **126%/yr at just 1 trade/day** on
  Alpaca's Tier-1 0.50% round-trip taker fee, and a tight symmetric scalp needs a **100% win rate to
  break even on fees**.
- **PDT independently disqualifies** the equity high-churn region for any account under **$25k**.
- **Tax is the second nail, not the decider:** US churn must add **~25% to its pre-tax Calmar** to
  neutralize the short-term rate penalty (after-tax Calmar = pre-tax Calmar × (1 − τ)); Germany's flat
  ~26.375% adds only a deferral loss. The verdict holds either way.
- **What is *not* killed** is swing-or-slower trading — and that is **already #255's surveyed domain**,
  which is exactly why this gate stops here and routes it back rather than re-surveying it.
- **Recommendation:** do **not** commission a high-churn build or an intraday backtester. Pursue the
  short-horizon ambition only through #255's existing swing-or-slower candidate survey, judged on
  after-tax Calmar. **Confirm the operator's tax residence** before any build batch (clean follow-up).
