# Pre-registered 4h EUR/USD strategy-family spec + evaluation protocol

**Issue:** #372 · **Batch:** #370 (stage 2a) · **Upstream:** #369 (feasibility gate, merged), #255
(the original after-tax-Calmar bar) · **Date:** 2026-07-13
**Author:** Analyst (research-only; no code, no data, no backtest run — this document contains
zero numbers derived from EUR/USD price history)

> **STATUS: PRE-REGISTERED** — frozen before any 4h EUR/USD backtest result exists. Freeze
> effective at the merge commit of the PR closing #372; **the merge SHA is the pre-registration
> timestamp**. Any change to families, grids, semantics, windows, cost presets, tax modes, the
> bar, baselines, or kill criteria after that SHA requires a revision of this document, committed
> with rationale, before results under the changed configuration are examined (§7).

---

## Scope and the no-peeking rule

This document does **not** implement, download, fetch, plot, or otherwise inspect any EUR/USD
price history, and it reports no backtest result. Every numeric value below is one of exactly
three kinds, and each is labeled as such at the point of use:

1. **Published indicator defaults with cited provenance** — Wilder (1978), Bollinger, the Turtle
   System (Faith, *Way of the Turtle*), Donchian's 5/20 system, Moskowitz, Ooi & Pedersen (2012),
   Connors & Alvarez.
2. **#369's cost/win-rate arithmetic, quoted by reference** — the feasibility-gate doc
   (`docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md`), which is itself
   literature-and-arithmetic, not a EUR/USD backtest.
3. **Grid combinatorics** — counting the frozen parameter grids in §4.

No parameter here was chosen, tuned, or "sanity-checked" against recent EUR/USD price action.
Where a family transplants a published rule from its native instrument/bar (daily equities, monthly
signals) onto the native 4h EUR/USD bar, that transplant is flagged explicitly rather than silently
assumed to carry over.

This is the `backtest/families.py` precedent (fixed published params, frozen before any result is
seen) lifted into a standalone pre-registration document, because the survey run itself is
deferred to the next batch and needs a spec to implement against, not a narrative written after the
fact.

---

## §1 Locked execution semantics (quoted by reference)

Batch #370's contract, item 3 ("the P1↔P2 interface"), quoted verbatim:

> **Execution semantics (the P1↔P2 interface):** one position at a time; long and short; fixed
> TP/SL set at entry (no trailing); signal on 4h close → fill next 4h open, stop-first ordering,
> in-progress bar dropped; 100% equity per trade at 1x, no leverage. Changes require a spec
> revision with rationale.

Plus the lead decisions locked in #370's decision log (resolving the #371/#372 NEEDS_DECISION
items before developer dispatch):

- **4h grid anchor: fixed absolute grid** — 00/04/08/12/16/20, UTC-normalized (mirrored from
  #371's lead decision #1).
- **Entry bar TP/SL testing: yes** — the entry bar's own high/low tests TP/SL; the fill is at that
  bar's open, so its extremes occur after entry in time, no look-ahead (mirrored from
  #371's lead decision #2).
- **Symmetric TP = SL = R** (decision #3, this doc's own).
- **Exit policy: TP/SL and walk-forward-window-end close only** — positions held over weekends,
  no opposite-signal exit, signals evaluated only when flat (decision #4).
- **Signal price field: mid close** = (bid_close + ask_close)/2 for all indicator computation;
  fills/costs per #371's model (decision #5).
- **Primary venue presets: XTB CFD base AND CME 6E base (co-primary)** (decision #6).
- **200-SMA baseline transplant: 200 native 4h bars** (decision #7).

**Division of labor.** Execution *mechanics* — gap-through-stop fills at the next open, exits
strictly after entry, same-bar TP/SL with stop-first tie-breaking — are #371's implementation,
governed by its own acceptance criteria. This document pins only: the signal functions (§2–§3),
the TP/SL sizes and grid (§4), and the judging criteria (§5–§6). Where a convention could live in
either place — annualization constants, window alignment — it is pinned **here**, so #371's
harness and the next batch's survey both implement the same numbers without re-deriving them.

---

## §2 Strategy interface contract (the P1↔P2 interface)

Each family is a **pure function** of completed-4h-bar history (all bars strictly before the
current one) that returns exactly one of `{enter-long, enter-short, decline}` per bar, **evaluated
only when flat**. While a position is open, no family function is evaluated; the only way to exit
is TP, SL, or a forced close at walk-forward window end (§5). This is not a second decision rule —
it is the same "enter or decline" pure-function shape the live bot already uses
(`computeTargetState`), applied to a different signal and instrument, and it never runs
concurrently with a live position.

**Computational pinning, applied to every family (the two-independent-implementers bar):**

- **Price field:** all indicators are computed on **mid close** = (bid_close + ask_close)/2 of
  the completed 4h bar, with one explicit carve-out: **high/low enter signal computation only in
  Family T2's channel** (§3) — no other family reads bid or ask alone, or the high/low, for signal
  computation. Outside Family T2, high/low are used only for TP/SL testing, which is #371's
  execution layer, not the signal.
- **Warm-up / NaN handling:** any bar where a required input is NaN (insufficient history for the
  lookback) → `decline`. No family ever signals during its own warm-up period.
- **Flat-only evaluation:** signal functions are not called, and their output is not consulted,
  while a position is open. A family that would have flipped signal mid-trade has no effect until
  the position closes (via TP/SL/window-end) and the next bar is evaluated fresh.
- **Ties:** any exact-equality condition (crossover exactly on the boundary, ROC exactly zero,
  price exactly on a band) resolves to `decline` — never to a spurious direction. This is stated
  once here and applies to every family below; it is restated in each family's own tie clause for
  the two-implementers bar.

---

## §3 The three families

All lookbacks below are stated in **native 4h bars** — this is a transplant convention, stated
explicitly here (mirroring how a rule published on daily or monthly bars gets applied on its own
native bar, e.g. Faber's 10-month SMA applied on monthly closes). No lookback is converted from a
different bar's published length by any implicit "hours per day" arithmetic; each grid value below
is either the literal published parameter (Donchian 20, Turtle 20/55, RSI 14/2, Bollinger 20) or a
stated dyadic multiple flagged as a coverage grid, not a converted one.

### Family T — trend-following (5 shapes)

**T1. MA cross (SMA).** Fast SMA crosses above slow SMA on the just-completed bar → enter-long;
crosses below → enter-short; else `decline`. "Crosses on the just-completed bar" means: fast was
`<=` slow at the prior completed bar and fast `>` slow at this completed bar (enter-long), or the
mirror image for enter-short; any other relationship (including fast `==` slow at the current bar,
or the prior-bar relationship also being on the "wrong" side already) → `decline` (the θ=0 tie
rule, §2, applied to the crossover boundary). **SMA type:** simple moving average of mid close,
unweighted arithmetic mean over the trailing window (the window includes the current completed
bar). Pairs (fast, slow), all in native 4h bars:

| Pair | Provenance |
|---|---|
| (5, 20) | Donchian's published 5/20 moving-average system |
| (20, 50) | The standard intermediate crossover |
| (50, 200) | The golden/death cross |

**T2. Donchian breakout.** Mid close strictly above the prior-N-bar **mid high** → enter-long; mid
close strictly below the prior-N-bar **mid low** → enter-short; else `decline`. **Channel field
(the §2 carve-out):** T2 is the one family whose channel is computed from high/low rather than mid
close alone. The field is pinned as **mid high** = (bid_high + ask_high)/2 and **mid low** =
(bid_low + ask_low)/2 of each bar — a transplant convention consistent with this document's
mid-price convention (§1 decision #5, §2), not a claim that mid high/mid low is itself a published
quantity. The classical-Donchian provenance (the breakout logic, the N-bar window, the published
20/55 lengths below) is otherwise preserved unchanged; only the high/low field is transplanted from
raw bid or ask onto the bid/ask midpoint so the channel is representable in this doc's
single-mid-price data model without picking a side. **Channel excludes the current bar** — the
N-bar mid-high/mid-low window is computed over the N completed bars *strictly before* the bar being
evaluated, so the just-completed bar's own mid-high/mid-low can never trigger its own breakout
(pinned to avoid the classic off-by-one). Exactly-equal-to-the-boundary → `decline` (θ=0 rule).
N ∈ {20, 55} — the published Turtle System 1 (20-day, here 20-bar) and System 2 (55-day, here
55-bar) entry lengths (Faith, *Way of the Turtle*).

Family T total: 3 MA pairs + 2 Donchian lengths = **5 shapes**.

### Family M — momentum (3 shapes)

**M1. Sign-of-trailing-return (TSMOM transplant).** ROC(N) = close / close[N bars ago] − 1.
ROC(N) > 0 → enter-long; ROC(N) < 0 → enter-short; ROC(N) = 0 or NaN → `decline`. This is the
published time-series-momentum shape (Moskowitz, Ooi & Pedersen, 2012 — the same provenance as the
repo's own `tsmom_signal` in `backtest/baselines.py`), transplanted from its native 12-month
lookback onto the native 4h bar. **Threshold θ is fixed at 0** — no dead-zone, no smoothing. N ∈
{12, 24, 48} native 4h bars: 12 is the published-convention numeral carried over from the 12-month
TSMOM lookback (a transplant of the *number*, not a claim that 12 bars ≈ 12 months); 24 and 48 are
its 2x and 4x dyadic multiples, forming **an a-priori coverage grid, explicitly not tuned** to any
observed EUR/USD behavior.

Family M total: **3 shapes**.

### Family R — mean-reversion (3 shapes)

**R1. RSI(14), 30/70 (Wilder).** RSI < 30 → enter-long; RSI > 70 → enter-short; else `decline`
(exactly 30 or 70 → `decline`, θ=0 rule applied to the band boundary). **Smoothing pinned:**
Wilder's original RMA (Wilder's Relative Moving Average, aka Wilder smoothing) recursion — average
gain/loss at bar `t` is `((n-1) * avgGain[t-1] + gain[t]) / n` with `n = 14` — **seeded** by the
simple arithmetic mean of the first 14 gains and first 14 losses (the first 14 bars of the price
series form the seed window and never themselves receive an RSI value; RSI is defined from bar 15
onward, all earlier bars → `decline` under the warm-up rule, §2). Source: Wilder, *New Concepts in
Technical Trading Systems* (1978), the original definition of both RSI and its smoothing
recursion — not a EUR/USD-derived value.

**R2. RSI(2), 10/90 (Connors).** Same Wilder RMA recursion and seeding convention as R1, with
`n = 2` (seed = mean of the first 2 gains/losses). RSI < 10 → enter-long; RSI > 90 → enter-short;
else `decline`. Source: Connors & Alvarez's published short-term RSI(2) rule — **published for
daily-bar US equities; the transplant to the native 4h EUR/USD bar is flagged here, not assumed
equivalent.**

**R3. Bollinger(20, 2).** 20-bar SMA of mid close (same SMA definition as T1) ± 2 standard
deviations of mid close over the same trailing 20-bar window. **`ddof = 0`** (population standard
deviation) — Bollinger's own published definition uses the population formula, not the sample
formula; this is pinned explicitly because it is "the classic two-implementers divergence" (pandas'
`.std()` defaults to `ddof=1`, which would silently produce different band widths from Bollinger's
own definition if used unpinned). Close strictly below the lower band → enter-long; close strictly
above the upper band → enter-short; else `decline` (exactly-on-the-band → `decline`, θ=0 rule).
Source: John Bollinger's published 20-period/2-standard-deviation default.

Family R total: **3 shapes**.

---

## §4 TP/SL grid + combo arithmetic

**Symmetric TP = SL = R** (lead decision #3, §1). R ∈ **{20, 30, 50} bp**.

**Justification for excluding R = 10 bp, quoted from #369 §5.2 (not a backtest result — cost
arithmetic on published/fetched broker schedules):** at R = 20 bp, the required win rate to break
even on cost is 51.4–55.9% across all eight venue/cost-case rows in #369's table (the co-primary
base-case rows sit at 52.0% for XTB and 51.4% for 6E futures, comfortably inside the ~55–60%
plausible-ceiling band #369 states as a carried-over assumption). At R = 10 bp, two cells in that
same table already breach that ceiling on #369's own arithmetic: IC Markets ECN pessimistic
requires **61.8%** and M6E pessimistic requires **60.5%**, both over the ~55–60% band, and IC
Markets ECN base sits at the "bottom edge" of the band (55.2%) rather than comfortably under it.
**R = 10 bp is therefore excluded a priori** — on #369's published win-rate arithmetic, not on any
EUR/USD backtest result, since none has been run.

**Combo table:**

| Family | Shapes | × R | Combos | Cap |
|---|---|---|---|---|
| Trend (T) | 3 MA pairs + 2 Donchian = 5 | 3 | **15** | ≤ 20 ✓ |
| Momentum (M) | 3 lookbacks | 3 | **9** | ≤ 20 ✓ |
| Mean-reversion (R) | 3 shapes | 3 | **9** | ≤ 20 ✓ |
| **Total** | | | **33 cells** | |

Arithmetic check: 5×3=15, 3×3=9, 3×3=9; 15+9+9=33. Every cell is combinatorial (shape count × R
count), not derived from any price data.

---

## §5 Evaluation protocol

**Data.** Per #371's scope: FXCM H1 EUR/USD bid+ask, 2012→2026, resampled to 4h on the fixed
absolute grid (§1). This document **consumes** that data's existence for protocol design; it does
not fetch, inspect, or summarize any value from it.

**Walk-forward windows.** Per `backtest/walkforward.py` conventions (non-overlapping test windows,
pre-roll warm-up prepended, metrics computed on the test sub-window only — the "Trap A" no-look-
ahead rule already used elsewhere in this repo's research code). Pinned specifically for this
survey:

- **Test windows: 12 months each, calendar-year-aligned**, first test window starting
  **2013-01-01, 00:00 UTC** (every window boundary is 00:00 UTC on Jan 1, consistent with the
  UTC-normalized 4h grid, §1 — no other timezone convention is in play) (2012 is warm-up only,
  never scored). This yields roughly 13–14 test windows across the 2012→2026 archive coverage.
- **Pre-roll: 300 native 4h bars**, prepended before each test window so every family's longest
  lookback (Family T's 200-bar SMA) has a full warm-up before the first bar that could score.
- Calendar-year alignment is deliberate, not incidental: it makes the German annual-netting tax
  computation (below) coincide exactly with window boundaries, so no window straddles a tax year.

**Metrics and annualization constants (pinned here, not left to the survey implementer):**
per-window total return, max drawdown, CAGR, after-tax Calmar ratio, Sharpe ratio, trade count,
win rate. Equity is resampled to **daily** before computing Sharpe/volatility, and annualized using
**√260** — the forex 24/5 trading-day count already established in #369 §1, not 252 (US equity/
NYSE calendar) and not 365 (crypto's continuous count).

**Costs (by reference to #369 §4/§5, not recomputed here):**

| Venue | Base `c` | Pessimistic `c` | Role |
|---|---|---|---|
| CME 6E futures | 0.56 bp | 1.00 bp | **Co-primary** |
| XTB CFD | 0.79 bp | 1.75 bp | **Co-primary** |
| IC Markets ECN | 1.04 bp | 2.35 bp | Sensitivity |
| CME M6E futures | 1.23 bp | 2.10 bp | Sensitivity |

**Primary presets: XTB CFD base AND CME 6E base, co-primary** (lead decision #6, §1) — a survivor
must clear the bar (§6) on **both**, not either. Pessimistic rows and IC Markets/M6E are reported
as sensitivity, never as the basis for a survivor claim. #371's empirically-measured FXCM spread
is added as a reconciliation row against these published/fetched presets, not as a fifth cost
preset in its own right. Overnight financing — for positions held across the daily rollover, per
#371's financing model — follows #369 §1's XTB-swap-proxy convention.

**Tax.** German annual-netting model **primary** (#371's new `tax.py` mode — 26.375% flat rate on
each calendar year's net gains, losses offset within the year, per the post-JStG-2024 statute
verified in #369 §7). The existing no-loss-credit model is retained as a **sensitivity row only**
(batch #370 contract item 2), never the basis for a survivor claim.

**The bar (inherited from #255 §2/§5).** A candidate must beat **SPY buy-and-hold's after-tax
Calmar ratio**, computed on the **same calendar test windows** (SPY daily bars, the existing
0.05%+0.05% frictions already used elsewhere in this repo's backtests, same German tax model) —
plus all four dumb baselines below, each pinned precisely so the survey has no discretion in
computing them:

1. **Always-flat.** Operationally: the candidate's **median-window return must be > 0** — a
   candidate that cannot clear zero on the median window has not beaten doing nothing.
2. **EUR/USD buy-and-hold.** Long from the first bar of each test window, held to window end,
   costs applied once at entry and once at the forced window-end close (same cost preset as the
   candidate being compared).
3. **Persistence.** Sign of the last completed 4h bar's mid-close return: go long if positive, short
   if negative, re-evaluated every bar (the "honest churn floor" — a rule with no information
   content beyond yesterday's sign, priced at the same cost preset, so any candidate that merely
   trades often does not look better than trading often for no reason).
4. **200-SMA regime, transplanted.** Mid close vs SMA(200 native 4h bars): long above, flat below
   (lead decision #7, §1) — the same shape as the live bot's own `computeTargetState`, applied to
   EUR/USD on its native 4h bar instead of SPY on its native daily bar. The **daily-SMA alternative
   is flagged, not used**, to keep this baseline on the same native-bar convention as every family
   in §3.

**Baselines are state-based** (persistence and the 200-SMA regime hold a position with no TP/SL
bracket — they exit only by flipping to the opposite state), unlike the 33 candidate cells, which
all use the fixed symmetric TP/SL from §4. This asymmetry is pinned here explicitly, not left
ambiguous: baselines 3 and 4 are not run through the same TP/SL execution layer as the candidate
families, because neither baseline has a natural TP/SL of its own to assign without inventing a
34th free parameter.

**Multiplicity rule, quoted verbatim from batch #370's contract item 5:**

> "≤ ~20 frozen combos per family; judged on median AND worst walk-forward window (never
> best-cell); every cell reported including failures; a survivor must clear the bar on median and
> stay positive on worst window."

---

## §6 Survivor definition + kill criteria

Stated here, before any result exists.

**Survivor.** A single (family, shape, R) cell is a survivor if and only if, at **both** co-primary
presets (XTB CFD base and 6E futures base, §5) and under the primary tax mode (German annual-
netting), all three of the following hold simultaneously:

1. Its **median-window** after-tax Calmar ratio exceeds SPY buy-and-hold's median-window after-tax
   Calmar ratio on the same calendar windows.
2. It beats all four dumb baselines (§5) on the same statistic (median-window after-tax Calmar,
   with baseline 1's always-flat criterion applied as stated: median-window return > 0).
   **Baseline-4 degenerate-window convention:** in any window where baseline 4 (200-SMA regime) is
   flat for the entire window — no position held throughout, hence trade count zero and an
   undefined 0/0 Calmar ratio — that window's baseline-4 return is treated as exactly 0 for the
   comparison, mirroring baseline 1's "median return > 0" convention rather than discarding the
   window or its test.
3. Its **worst-window** total return, after costs and tax, is positive (> 0) — the multiplicity
   control from §5's verbatim rule ("stay positive on worst window").

**Family kill.** If no combo within a family (15 cells for Trend, 9 for Momentum, 9 for
Mean-reversion) satisfies the survivor definition, that family is dead — it does not proceed to
any further stage on this evidence.

**Class kill (the "stop" pattern).** The entire 4h EUR/USD candidate class is dead if **either**:
(a) none of the 33 cells satisfies the survivor definition, **or** (b) every cell that clears the
median criterion (survivor conditions 1–2) nonetheless fails on the worst-window criterion
(condition 3) — i.e. the class only ever looks good on the median statistic and never survives its
own worst window. Consequence, stated in advance: **this class of 4h EUR/USD trading has no
demonstrated edge; do not proceed to an FX-system ADR; the colleague-audit path stays available
only if he shares his actual rules or a broker trade export.**

**Data kill (inherited from #371).** If #371's data/harness package is BLOCKED on validation, the
survey defined by this document does not run at all — there is no fallback survey on unvalidated
or fabricated bars.

**Multiplicity note.** With 33 cells evaluated at a nominal 5% test level, a single marginal
survivor is provisional by construction — the joint median-and-worst-window criterion in §5/§6 is
this document's multiplicity control, not a substitute for treating one lone survivor with
appropriate skepticism. The fresh ADR referenced below is the final judge of whether a survivor (or
a family of them) is strong enough to act on, not this document.

**No second live rule.** A survivor under this protocol does **not**, by itself, authorize a
second live trading rule. CLAUDE.md's Architectural invariant #1 ("one decision rule") governs the
live bot; any candidate that clears this document's bar becomes, at most, a candidate for a
**separate, paper-first FX system**, decided by a **fresh ADR** after results exist. That ADR — not
this pre-registration, and not the next batch's survey run — is the document that would ever
authorize a live change, and only after weighing paper-trading evidence this protocol does not
produce.

---

## §7 Freeze clause

Any later change to the families (§3), the TP/SL grid (§4), the execution semantics (§1), the
walk-forward windows, cost presets, tax modes, the bar, the dumb baselines, or the kill criteria
(§5–§6) **requires a revision of this document, committed with rationale, before results computed
under the changed configuration are examined**. Results already computed under a superseded
revision must still be reported, alongside the revised results, not discarded — so a later change
cannot be used to quietly erase an inconvenient earlier outcome.

---

## §8 Non-goals

- No implementation, no data, no results — the survey run is deferred to the next batch, after
  both #371 (harness) and this document are merged.
- No LLM-based or LLM-assisted strategies of any kind (CLAUDE.md invariant #2, "no LLM in the
  trading path" — this document specifies deterministic pure functions only).
- No trailing stops, no leverage, no pyramiding — deferred by the locked execution semantics in §1
  (fixed TP/SL, no trailing, 1x, one position at a time).
- No claim that the colleague's actual proposed rules are among the three families in §3 — these
  are published, general-purpose deterministic shapes chosen for their existing literature
  provenance, not a reconstruction of his specific rules. The colleague-audit path (his actual
  rules or a broker trade export) remains a separate, still-available option per #369/#370.
- **No authorization of a second live trading rule.** Per CLAUDE.md Architectural invariant #1, a
  survivor under this protocol is evidence for a fresh ADR to weigh, not an instruction to change
  the live 200-DMA/UPRO bot. The live bot is untouched by this document and by any result the
  eventual survey produces on its own.
