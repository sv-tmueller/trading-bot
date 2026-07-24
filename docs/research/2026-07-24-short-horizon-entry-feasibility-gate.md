# Short-horizon rule-based ENTRY system — feasibility gate (define + decide)

**Question:** Does a frequent (hourly/minute-candle) rule-based **entry** system — the operator's
stated next-generation direction — have a plausible, testable edge on some instrument universe, or is
it answered "no" before a survey by the accumulated cost-wall, edge-absence, and data-scarcity
evidence already in this repo?
**Issue:** #422 (Piece 3 of the strategy-evolution decomposition) · **Operator directive:** 2026-07-24
(next-gen strategy should drive entries from hourly/minute candles, not the once-daily 200-DMA)
**Date:** 2026-07-24
**Author:** Analyst (research-only; `CLAUDE_AGENT_NO_BROKER=1` set for the whole session; no
production/TypeScript code, no `strategy/`, no `backtest/*.py`, no settings, no broker integration
touched; no order placed; no new URL fetched — this gate is citation + cost-math + power-derivation
offline, per the same method as the two prior feasibility gates).

> **Method note.** This is a **synthesis-and-arithmetic** gate, gated cheap-math-first, exactly like
> `docs/research/2026-06-23-short-horizon-feasibility-gate.md` (#309) and
> `docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` (#368). No backtest was run. Every
> numeric input below is either (a) cited to an existing repo doc with a section anchor, (b) shown as
> re-derivable arithmetic from the `trades_per_day × days_per_year × c` and DSR formulas the repo
> already uses, or (c) explicitly labelled **[unverified]** / **[assumption]**. The cost-drag table in
> §2 was re-derived in a throwaway scratchpad helper (`gate_calc.py`, not committed) to avoid
> arithmetic slips, and reproduces the scalping demo's own empirical drag (1h crypto ≈39% drag
> matching that study's −33.5% net; 15m ≈142% matching −74%). No fact is filled from memory. The gate
> reaches a **NO-GO**; per this repo's honesty convention an honest negative is the deliverable, and
> the load-bearing single reason is stated in §5 before the supporting detail.

---

## §0 Invariant framing (stated first, governs everything below)

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants), any candidate
this direction could produce would be a **deterministic pure function of price/cost history** that
**replaces** the live 200-DMA/UPRO rule (`computeTargetState` in
`supabase/functions/_shared/regime.ts`), never a second parallel rule (invariant #1, one decision
rule), and imports **no model SDK** (invariant #2, no LLM in the trading path). A more-frequent
*deterministic* loop is invariant-compatible in principle — the same bar-close decision the bot
already makes, evaluated more often — exactly as #309 §(g) and #368 §2 already established. What is
out of bounds regardless of any cost result is an **LLM deciding each candle** (the shape the
rules-engine pivot removed; `trader.dev`/`tradingkit.com` were ruled out on this ground in #368 §8).
This gate assumes the deterministic case throughout. **It authorizes nothing live**; the UPRO bot is
untouched.

---

## §1 The candidate space, enumerated

The operator's "hourly/minute entries" direction spans **universe × candle frequency × rule family**.
Enumerated in full so the decision covers the whole space, not a convenient slice.

**Universes** (EU-retail-reachable, per the batch #413 access facts):

| # | Universe | Reachable API | Per-trip round-trip cost `c` (round-trip) | Prior kill status |
|---|---|---|---|---|
| U1 | Intraday US equities/ETFs (SPY/QQQ-class) | Alpaca US Trading API (`alpaca.ts`) | base **3 bp** (range 1–5 bp), commission-free + spread/slip (#309 §a) | high-churn killed on cost + PDT (#309) |
| U2 | Index / micro-index futures (ES/MES) | IBKR TWS/Client Portal (`2026-07-21-contracts-facts-verification.md` §3) | MES bp **[unverified]** — CME-blocked; IBKR commission+fee **$1.20/contract round trip verified** (`…facts-verification.md` §2.2); FX-micro analogue **1.23–2.10 bp** used as a labelled proxy (`2026-07-13-forex…gate.md` §4.3) | not directly tested intraday |
| U3 | FX majors (EUR/USD-class) | XTB/IC Markets/IBKR (`2026-07-13-forex…gate.md` §8) | **0.56–2.35 bp** (cheapest sourced) | **4h class-killed, 0/33** (`2026-07-15-forex-4h-survey-verdict.md`) |
| U4 | Crypto (BTC/ETH) | Bybit/Alpaca (research-only; hard non-goal to integrate) | **13 bp** (Bybit) → **50 bp** (Alpaca taker) | **no edge even at zero cost** (`2026-06-23-scalping-cost-wall-demonstration.md`) |

**Frequencies** (the operator's "hourly and minute"): **1h, 15m, 1m**. (The prior forex kill sat at
**4h**; the scalping kill spanned **1h/15m/5m**.)

**Rule families** — the standard set the 4h forex survey pre-registered and killed, which is exactly
what "rules-based entry" means in this repo:

| Family | Shapes (as frozen + killed in `2026-07-13-forex-4h-strategy-preregistration.md` §3) |
|---|---|
| Trend / MA-cross | SMA 5/20, 20/50, 50/200 |
| Breakout | Donchian 20, 55 |
| Momentum | ROC/TSMOM 12, 24, 48 |
| Mean-reversion (oscillator) | RSI(14) 30/70, RSI(2) 10/90 |
| Mean-reversion (band) | Bollinger(20, 2) |
| (Intraday breakout, colleague-tested) | London Open-Range-Breakout — killed by the colleague, "Intraday-Frage endgültig geschlossen" (`2026-07-20-colleague-repo-audit.md` §2) |

The full space is therefore **4 universes × 3 frequencies × ~6 rule families ≈ 72 conceptual cells**.
The two axes that decide the gate are **universe × frequency** (cost + data) and **rule family**
(edge). §2–§3 kill on the first two; §4 shows the third is already killed.

---

## §2 Cost-wall arithmetic per (universe × frequency)

**Formula (repo-standard, re-derivable):** annualized cost drag `= trades_per_day × days_per_year × c`.
`c` = round-trip cost as a fraction of notional (#309 §a, #368 §3).

**Trades/day per frequency** — anchored to the **empirical** scalping-demo trade counts (real BTC,
one year: 1h→301, 15m→1094, 5m→3298 trades — `2026-06-23-scalping-cost-wall-demonstration.md` §Results),
i.e. 0.82 / 3.00 / 9.04 trades per 24h calendar day, extrapolated to **35.5/day at 1m** (5× the 5m bar
count, ~0.85 exponent). Scaled by session length for each universe: equity RTH 6.5h (×0.271), futures
~23h (×0.958), FX 24/5 (×1.0), crypto 24/7 (×1.0). `days_per_year`: equity/futures 252, FX 260, crypto
365 (the same conventions #309/#368 pinned). These are a **realistic active-entry-rule** point
estimate, not a worst case; a pure always-in bar-flip rule would trade more, a slow trend rule less.

**Annualized cost drag (%/yr):**

| Universe | `c` (round-trip) | 1h | 15m | 1m |
|---|---|---|---|---|
| U1 US equity ETF | 3 bp | **1.7%** | **6.1%** | **72.7%** |
| U2 Index/micro futures | 1.5 bp **[unverified proxy]** | **3.0%** | **10.9%** | **128.6%** |
| U3 FX majors | 1 bp | **2.1%** | **7.8%** | **92.3%** |
| U4 Crypto (Bybit 13 bp) | 13 bp | **39.1%** | **142.2%** | **1,684%** |
| U4 Crypto (Alpaca 50 bp) | 50 bp | **150.5%** | **547%** | **6,477%** |

(trades/day used — equity {1h 0.22, 15m 0.81, 1m 9.6}; futures {0.79, 2.87, 34.0}; FX {0.82, 3.0, 35.5};
crypto {0.82, 3.0, 35.5}.)

**Cross-check against the empirical anchor.** The 1h-crypto 39.1% and 15m-crypto 142.2% drags land on
top of the scalping demo's own realized net returns (−33.5% at 1h, −73.8% at 15m,
`…scalping-cost-wall…` §Results) — the arithmetic is not free-floating, it reproduces a real backtest.

**Reading, against a ~15%/yr drag sanity budget (the #368 §1 order-of-magnitude ceiling; SPY's own
long-run CAGR is ~10%/yr):**

- **1m — killed on cost alone, every universe** (72–128% equity/futures/FX, 1,684–6,477% crypto). This
  is #309's `trades_per_day × c` arithmetic and the scalping demo's empirical −34%→−74%→−98%
  frequency sweep restated: **finer cadence is a cost-multiplication engine, not a profit engine.**
- **Crypto — killed at every intraday frequency** (39% at 1h Bybit, worse at Alpaca), and separately
  killed on edge (see §4). No intraday-crypto cell survives.
- **15m — borderline-to-over on cost** for equity (6.1%, but PDT-illegal sub-$25k, see below), futures
  (10.9% [unverified proxy]), FX (7.8%, but already 4h-class-killed). Survivable on drag alone only at
  the cheapest venues, at the edge of the budget.
- **1h — survivable on cost** for equity (1.7%), futures (3.0% [unverified]), FX (2.1%); crypto still
  dead (39%).

**PDT overlay (U1 equities only, hard regulatory cut).** FINRA Rule 4210 caps a sub-$25k margin
account at 3 day-trades / 5 business days (#309 §a). At the trades/day above: 1h = 1.1/5d (**under** the
cap), 15m = 4.1/5d (**over** — illegal sub-$25k), 1m = 48/5d (**far over**). So for any operator running
< $25k, the intraday-equity 15m/1m cells are **legally unreachable** independent of cost. PDT does not
apply to futures, FX, or crypto.

**Cost-wall verdict:** the minute end (1m) is killed on cost everywhere; all intraday crypto is killed
on cost; 15m survives cost only at the cheapest venues and the edge of the budget (and is PDT-blocked
for sub-$25k equity). **The only cleanly cost-survivable cells are 1h US-equity, 1h index-futures
[unverified cost], and 1h FX** — plus 15m at those same three universes at the budget edge. Everything
that survives §2 must still clear the edge bar (§4) and the data bar (§3) — and it does not.

---

## §3 Power / overfitting bar — which surviving cells can even be *tested*

The pre-registered promotion bar for any candidate to the live bot is fixed
(`2026-07-21-leveraged-contracts-preregistration.md` §4): the **#398 overfitting gate**
(`DSR ≥ 0.95`, `PBO < 0.5`, moving-block-bootstrap `CI_low > 0` on uplift vs baseline —
`2026-07-21-overfitting-gate-usage.md`) **and** beating SPY buy-and-hold's median-window after-tax
Calmar of **1.3085475049604838** on the frozen **n_w = 13** calendar-year windows (2013–2025).

**History requirement (cadence-independent to first order).** From the PSR z-statistic
(`2026-07-21-contracts-survey-data-feasibility.md` §3), required *years* of history depends only on the
assumed true annualized Sharpe, not on candle frequency: **≈10.8 y at SR_ann 0.5, ≈2.7 y at 1.0,
≈1.2 y at 1.5** (re-derived, matches that doc). Separately, the frozen **n_w = 13** comparability bar
requires ≈14 years of calendar-aligned windows.

**Free intraday history vs the n_w = 13 bar** (all measured live in
`2026-07-21-contracts-survey-data-feasibility.md`, probes P1/P3/P6–P8):

| Path × cadence | Free history floor | n_w achievable | Clears n_w = 13? |
|---|---|---|---|
| SPY-proxy **daily**, yfinance (`walkforward.py:41`) | 1993-01-29 (P6, 33 y) | 13–14 | **Yes** — but **daily, not intraday** |
| ES **daily**, yfinance `ES=F` | 2000-09-18 (P7, 26 y) | 13+ | Quantity yes; unadjusted-roll splice caveat; **daily, not intraday** |
| SPY-proxy **5Min SIP** | 2016 (P1) | ≈9 | **No** — short by 3–4 windows |
| SPY-proxy **5Min/1Min IEX** | 2020-07 (P1) | ≈5 | **No** — short by 7–8 windows |
| MES-native **any intraday** | 2019-05 (P8) | ≈5–6 | **No** — native-only |
| ES/MES **intraday, free yfinance** | ≤60 days (§1.1 cite) | ~0 | **No — orders of magnitude short** |
| ES/MES **intraday, paid** (Databento 16 y / FirstRate since-2007) | reaches | 13+ | **Yes, at cost** — spend not authorized |

**The binding data fact for #422 specifically:** **there is no free intraday history source that
reaches the frozen n_w = 13 comparability bar.** Every free source that clears the bar is **daily**
(SPY 1993, ES 2000) — i.e. the incumbent's own cadence, not the "hourly/minute" cadence this issue is
about. The best free *intraday* option (SPY 5Min SIP, back to 2016) reaches only n_w ≈ 9; IEX
(2020-07) reaches n_w ≈ 5; MES-native n_w ≈ 5–6. **So the operator's exact requested cell — an
hourly/minute rule surveyed against the frozen after-tax-Calmar bar — cannot be tested credibly for
free at all.** Paid vendors (Databento/FirstRate) could, but that is a spend + integration decision the
survey is not authorized to make, and — decisively — it would be spending to test **rule families that
are already killed** (§4) at a **cadence the cost wall punishes** (§2).

**Consequence:** of the cost-survivable cells in §2 (1h/15m US-equity, index-futures, FX), **none can
clear the power/data bar on free data.** They are simultaneously (a) unable to be credibly tested and
(b) — even if tested — running already-killed rule families with no demonstrated edge (§4).

---

## §4 Reconciliation against the prior kills — the crux, stated honestly

The task's hard question: does the accumulated evidence **generalize** to the broader short-horizon
rule-based-entry class, or is there a **specific, defensible untested corner** worth a pre-registered
survey? The honest answer, anchored to numbers:

**Three independent lines of evidence kill exactly these rule families at short horizon:**

1. **4h EUR/USD survey — class kill, 0/33** (`2026-07-15-forex-4h-survey-verdict.md`). All 33
   pre-registered (family, shape, R) cells — the exact MA-cross / Donchian / ROC / RSI / Bollinger set
   in §1 — evaluated in full; **zero survivors**; best cell median after-tax Calmar **0.337** vs SPY's
   **1.309** (Table 6.1 + Appendix). All three families (Trend, Momentum, Mean-reversion) dead
   individually. The kill was reason (a): *no cell clears the median bar at all.*
2. **Scalping cost-wall — no edge even at zero cost** (`2026-06-23-scalping-cost-wall-demonstration.md`).
   A faithful multi-confirmation entry rule on real BTC: costs-off net **−1.64%**, profit factor
   **1.02**, win rate **37%** — a coin flip — with **break-even cost 0.000%**. Finer frequency deepened
   the loss **−34% → −74% → −98%** (1h→15m→5m). There is no gross edge for any cost to fund.
3. **Colleague's independent intraday work — closed** (`2026-07-20-colleague-repo-audit.md` §2/§3):
   *"every London-Open-Range-Breakout variant he tried lost… 'Intraday-Frage endgültig geschlossen'"*
   (intraday question definitively closed); his 4h Donchian breakout was never promoted; his daily FX
   regime (ADX-gated momentum / z-score mean-reversion — the same families) scored full-history Sharpe
   **−0.25**. Three research programs (ours × 2, his) converged on the same negative.

**Does it generalize?** Yes, for the rule-family axis. The 4h verdict's kill is explicitly *"independent
of the instrument each was originally tested on"* (`2026-07-21-leveraged-contracts-preregistration.md`
§3): a MA-cross is a MA-cross whether it runs on EUR/USD, SPY, or MES — the instrument does not
manufacture direction-signal edge. **"Rules-based" does not create edge — the killed candidates were
rules-based** (#422 body). The entry signal is where edge must come from, and short-horizon entry edge
is precisely what has failed every test here.

**Is there a defensible untested corner?** The contracts pre-registration
(`2026-07-21-leveraged-contracts-preregistration.md` §3, "Genuinely untested space") named the only
residual candidates not covered by the dead-cell registry: **(a)** re-parameterized regions of the
killed shapes at a futures-appropriate cadence, **(b)** volatility-regime gating (distinct from the
already-killed ADX-gated *direction* families), cross-sectional/relative-value between MES and a slower
reference, and **(c)** options-structure (vol-surface) families. Assessed honestly against **this
issue's intraday scope**:

- Corners (a) and (b) are **not intraday**. That pre-registration recommends the **MES wrapper for a
  candidate that "is still likely to hold across at least one session rather than scalp intraday — the
  intraday shape is itself already killed"** (§2.5, citing §3). Those untested corners live at
  **daily/swing** cadence and are already owned by the separate contracts direction (#406), where free
  **daily** data (SPY 1993, n_w = 33; ES 2000, n_w = 26) can actually test them. They are **out of
  scope for #422's hourly/minute-entry question.**
- Corner (c), options vol-structure, is **not "rule-based candle entry"** (it is a volatility-surface
  signal, a different instrument class), and its real options-data floor is **~2024-01-18 → ~2.4 years**
  (`mvp2-alpaca-options-data-spike.md`, cited in the contracts pre-reg §2.1) — far short of n_w = 13.
  It is also the runner-up, not the recommended wrapper. Not an intraday-rule-entry candidate.

So within the class #422 actually defines — **short-horizon (hourly/minute) rule-based entry** — there
is **no defensible untested corner**: every rule family is killed by three independent lines of
evidence, the genuinely-untested shapes are either daily/swing (already routed to #406) or a different
instrument class with insufficient data, the cost wall kills the minute end and all crypto outright,
and no free intraday data source can even test the cost-survivable 1h/15m cells against the frozen bar.

---

## §5 Verdict — NO-GO (do not run a survey)

**NO-GO. #422 is answered "no" for the short-horizon rule-based ENTRY class as posed.** Do not
dispatch a pre-registered intraday-entry survey.

**Single most decisive reason (stated as one sentence):** the exact rule families this direction
would use are already **class-killed three independent times** (forex 4h 0/33 survivors, best 0.337 vs
SPY 1.309; scalping demo no gross edge even at **zero cost**; colleague's London-ORB "endgültig
geschlossen"), and the two economics gates independently close what little is untested — the **cost
wall** kills the minute end and all intraday crypto outright (72–6,477%/yr drag), and the **data wall**
means the only cost-survivable corner (1h US-equity / index-futures) **cannot be credibly tested for
free**, because no free intraday history reaches the frozen **n_w = 13** comparability bar (SPY 5Min
SIP n_w ≈ 9, IEX n_w ≈ 5, MES-native n_w ≈ 5–6; only *daily* SPY/ES clear it).

This is a genuine, valuable negative, not padded pessimism: it holds across all four universes, all
three frequencies, and every rule family, and it rests on directly-cited repo evidence plus
re-derivable arithmetic — not a single "promising direction" is dressed up as one.

### What would have to change to revisit

Revisiting requires **all three**, not any one:

1. **A pre-cost gross-edge demonstration at intraday cadence** on some instrument — the load-bearing
   missing thing. The scalping study found the *opposite* (no edge at zero cost); the forex survey
   found the *opposite* (0/33). A credible new signal would need to show positive gross expectancy
   *before* costs, at hourly-or-finer cadence, on real bars. (The colleague-trade-export path that
   could have supplied this was already closed — his intraday work also lost.)
2. **Authorized data spend** (Databento / FirstRate) to obtain intraday history reaching n_w = 13, since
   no free intraday source does. This is a real budget decision, not currently authorized.
3. **A genuinely new signal shape** not in the dead-cell registry *and* intraday-specific — note that
   direction-signal families are exhausted, so this would likely be a microstructure/order-flow shape,
   which is **not** "rule-based candle entry" and would need a fresh brainstorm + design spec under the
   one-decision-rule invariant before it could even be scoped.

### Where the residual research appetite should go instead (not a new issue — a routing note)

The only genuinely-untested corners the evidence leaves open (vol-regime gating, cross-sectional/RV on
an MES-class wrapper) are **daily/swing, not intraday**, and are **already pre-registered** under the
contracts direction (`2026-07-21-leveraged-contracts-preregistration.md` §3/§6, issue #406), where free
**daily** data (SPY 1993, n_w = 33) can test them against the same after-tax-Calmar bar. That is the
correct home for any "smaller trading windows" ambition that survives this gate — **not** an
hourly/minute rule-based-entry survey, which this document answers "no." The live 200-DMA/UPRO bot is
untouched; nothing here is a second decision rule.

---

## §6 Reconciliation with prior gates (no contradiction)

| | #309 (equity/crypto scalp) | #311 (empirical BTC scalp) | #368 (forex cadence sweep) | 4h FX survey verdict | **This gate (#422)** |
|---|---|---|---|---|---|
| Scope | high-churn cost gate | one strategy, real data | moderate-cadence cost floor | 33 frozen cells, real data | **whole intraday-entry class (universe × freq × family)** |
| Result | no-go on cost | no edge at zero cost | cost floor *survivable* on cheap venues | **class kill 0/33** | **NO-GO** (edge already killed + cost + data) |
| New contribution | — | empirical cost wall | forex ≠ equity on cost | the definitive edge kill | ties the three kills to the operator's exact hourly/minute framing; adds the **free-intraday-data-cannot-reach-n_w=13** power constraint as the second, independent wall |

- **No contradiction with #368's "cost floor is survivable."** #368 showed FX *cost* is cheap enough
  at moderate cadence — but it explicitly stated *"clearing the cost gate is necessary, not
  sufficient"* (§9), and the subsequent 4h **survey** then found **no edge** (0/33). This gate inherits
  both: cost is survivable at 1h on the cheapest venues, but the edge is already demonstrated absent and
  the intraday data to re-test it credibly does not exist for free.
- **This gate does not touch invariant #1.** No survivor exists, so there is no candidate to weigh
  against the one-decision-rule contract; the live bot is unaffected.

---

## §7 Bottom line

The operator's intuition — drive entries from hourly/minute candles — is intuitive but, on the
evidence this repo has already accumulated, **unproven and, as a *rules-based* class, answered "no."**
Three independent research programs killed exactly these rule families at short horizon; the cost wall
makes the minute end and all intraday crypto mathematically unwinnable; and no free intraday data
source can even test the one cost-survivable corner against the frozen after-tax-Calmar bar. **NO-GO —
do not run an intraday-rule-based-entry survey.** The residual, genuinely-untested corners are
daily/swing on an MES-class wrapper and are already pre-registered under #406, which is where that
appetite belongs. Operator intuition remains a reason to *look*, per the issue — but the place left to
look is not the hourly/minute rule-based-entry cell, and this gate is the record of why.
