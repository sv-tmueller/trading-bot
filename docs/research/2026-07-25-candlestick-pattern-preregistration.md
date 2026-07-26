# Daily candlestick-pattern study — pre-registration (frozen grid, results pending)

**Question:** Does any classic candlestick **pattern**, traded on **daily** bars with a
bracket exit anchored to the pattern's own extreme, clear the frozen SPY buy-and-hold bar?

**Issues:** refs #422 (short-horizon entry NO-GO), #431 (ORB probe, DATA-BLOCKED)
**Date:** 2026-07-25
**Author:** Claude Code session (research-only; `CLAUDE_AGENT_NO_BROKER=1`; no
production/TypeScript code, no `supabase/`, no `strategy/`, no settings, no broker
integration touched; no order placed).

> **Status: COMPLETE — §7 (Results) is now filled.** This document was committed **before**
> any real-data result existed (freeze: `8d424f7`), in a strictly earlier commit than the
> results (§7 fill: `1e19a5f`, PR #446), per the discipline used by #425, #430 and #431
> (provable from git history). §2-§6 are frozen and were **not edited after numbers were
> seen**; this banner was reworded past-tense at merge time under operator authorization
> (2026-07-26, batch #439 decision D9).

---

## §0 Invariant framing (governs everything below)

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants), any
candidate this study could produce would be a **deterministic pure function of price
history** that **replaces** the live 200-DMA/UPRO rule (`computeTargetState` in
`supabase/functions/_shared/regime.ts`), never a second parallel rule (invariant #1), and
imports **no model SDK** (invariant #2). Nothing here is live. The UPRO bot is untouched,
`compute_target_state` is unchanged, and `backtest/` is never imported by
`supabase/functions/`.

**This study authorizes nothing live.** Clearing the bar would authorize a *design spec*,
not a deployment.

---

## §1 Why this is not a re-run of something already killed

Every entry family this repo has surveyed and killed is an **indicator** computed from
candles:

| Killed family | Where |
|---|---|
| MA-cross (SMA 5/20, 20/50, 50/200) | `2026-07-13-forex-4h-strategy-preregistration.md` §3 → `2026-07-15-forex-4h-survey-verdict.md` (0/33) |
| Breakout (Donchian 20, 55) | same, plus `2026-07-24-turtle-breakout-verdict.md` (0/12) |
| Momentum (ROC/TSMOM 12, 24, 48) | same |
| Mean-reversion (RSI 14, RSI 2) | same |
| Bollinger | same |
| Opening-range breakout | `2026-07-24-orb-probe-verdict.md` (DATA-BLOCKED, not killed) |

Classic candlestick **patterns** are a different functional form: **fixed 1-to-3-bar OHLC
geometry** (body/wick proportions, bar-to-bar containment) rather than a rolling-window
aggregate. In this repo they appear **only as a keyword list** —
`docs/research/swing-trading/keywords.md` §"Candlestick Patterns" — never implemented,
never backtested. That is what makes this untested rather than a repeat.

### §1.1 Honest reconciliation with #422's NO-GO

#422 closed the **short-horizon** rule-based entry class and named three things that would
have to change to revisit it, one of which was "a genuinely-new, **non-candle** signal
shape." A candlestick pattern is, unambiguously, a *candle* shape. **This study does not
claim to satisfy that criterion and does not reopen #422.**

It sidesteps #422 on **cadence**, not on signal novelty. #422's two load-bearing walls are:

1. **Cost wall** — re-derived 72-128%/yr drag at 1-minute cadence.
2. **Data scarcity** — no *free* intraday history reaches the n_w=13 power bar; its §3
   states that **only daily clears**.

Neither wall cares which signal fires. Both are properties of **frequency**. On daily bars:

- a pattern fires on the order of **10-30 bars/year**, not 250+, so the cost multiplier
  that killed the scalping study does not apply;
- daily SPY reaches **1993** (~33 non-overlapping 12-month windows — the same basis on
  which #430's daily Turtle arm was declared gate-eligible), which clears n_w=13.

So the claim is narrow and stated plainly: **an untested signal form, on the one cadence
#422 left open.** An *intraday* candlestick grid would re-run into both walls and is
explicitly out of scope here.

---

## §2 The bar (verbatim, frozen)

> A cell clears the bar only if its **full-window after-tax US Calmar** exceeds the
> SPY buy-and-hold median-window after-tax Calmar of **1.3085475049604838**
> (n_w = 13 non-overlapping 12-month windows, 2013-2025), computed on the same
> after-tax basis (`_after_tax_metrics(...)["calmar_us"]`).

The same frozen SPY bar the #314/#420/#430 research program qualifies new strategies
against. **Primary verdict = per-cell after-tax US Calmar vs 1.3085.**

Secondary, reported but not the verdict: CAGR, max drawdown, trade count, the
**random-entry twin** of each cell, the **always-in** buy-and-hold of the vehicle, and the
#398 overfitting-gate outputs.

---

## §3 The grid (frozen, 28 cells)

**14 pattern arms × R ∈ {2, 3} = 28 cells.** All 28 are disclosed for multiplicity;
**N = 28** is the deflated-Sharpe trial count.

| # | Arm | Pattern | Side | Span (bars) |
|---|---|---|---|---|
| 1 | `bullish_engulfing` | bullish engulfing | long | 2 |
| 2 | `bearish_engulfing` | bearish engulfing | short | 2 |
| 3 | `hammer` | hammer | long | 1 |
| 4 | `shooting_star` | shooting star | short | 1 |
| 5 | `bullish_pin_bar` | bullish pin bar | long | 1 |
| 6 | `bearish_pin_bar` | bearish pin bar | short | 1 |
| 7 | `bullish_marubozu` | bullish marubozu | long | 1 |
| 8 | `bearish_marubozu` | bearish marubozu | short | 1 |
| 9 | `bullish_harami` | bullish harami | long | 2 |
| 10 | `bearish_harami` | bearish harami | short | 2 |
| 11 | `morning_star` | morning star | long | 3 |
| 12 | `evening_star` | evening star | short | 3 |
| 13 | `inside_bar_long` | inside bar | long | 2 |
| 14 | `inside_bar_short` | inside bar | short | 2 |

**Vehicle:** SPY daily (primary). ES=F daily is a **disclosed secondary robustness arm**,
run separately and **not pooled** into the primary DSR `sr_star` — the same treatment #430
gave its hourly arm.

**`doji` is registered as a detector but excluded from the trading grid.** It is a pure
indecision bar with no directional implication; assigning it one would be an unfrozen free
parameter.

### §3.1 Frozen thresholds

Conventional/published values, set before any result was seen
(`backtest/candlestick.py` module constants):

| Constant | Value | Meaning |
|---|---|---|
| `DOJI_BODY_MAX` | 0.10 | body ≤ 10% of range |
| `HAMMER_WICK_MIN` | 2.0 | dominant wick ≥ 2× body |
| `HAMMER_OPP_WICK_MAX` | 0.10 | opposing wick ≤ 10% of range |
| `PIN_WICK_MIN` | 0.66 | dominant wick ≥ ⅔ of range |
| `MARUBOZU_BODY_MIN` | 0.90 | body ≥ 90% of range |
| `STAR_BODY_MAX` | 0.30 | star's middle bar body ≤ 30% of its range |
| `STOP_BUFFER` | 0.001 | 10 bp beyond the pattern extreme |

---

## §4 Frozen exit geometry

Stops are anchored to the **pattern's own extreme** — the thing that distinguishes
candlestick trading from an indicator with an ATR stop:

- **long:** `stop = min(Low over span) × (1 − STOP_BUFFER)`
- **short:** `stop = max(High over span) × (1 + STOP_BUFFER)`
- `risk = |entry_ref − stop|`, where `entry_ref = Open × (1 ± slip)` at the entry bar
- `target = entry_ref ± R × risk`

The extreme is measured at the **signal bar** and shifted onto the **entry bar**, so no
level reads a price the decision could not have seen. A **non-positive risk** (the entry
gapped past its own stop) yields a NaN stop, which the engine treats as "suppress this
entry" rather than sizing off a garbage level.

Exits use the merged long/short bracket engine (`backtest/bracket.py`) with its frozen
conventions: open-gap-first fills, conservative STOP-first intra-bar tie-break, no
look-ahead. Positions are **held across sessions** (`session_close_out=False`,
`eow_close_out=False`) — this is a swing study, not an intraday one.

### §4.1 Disclosed deviations

1. **The inside-bar arms are not breakouts.** Classic inside-bar trading enters on an
   intrabar **break** of the mother bar's extreme. The bracket engine's entry is "at the
   next bar's open", which cannot express an intrabar breakout trigger. So
   `inside_bar_long` / `inside_bar_short` are a **directional bet at the next open after an
   inside bar**. This is a real departure from the textbook rule and is labelled as such in
   the module, the runner, and here.
2. **Engulfing/harami containment is inclusive** (`≤`/`≥`, not `<`/`>`). On a
   continuously-traded instrument the open frequently sits exactly at the prior close, so a
   strict test would make these patterns fire **only on gap days** — the gap, not the
   geometry, would be the signal. This was frozen **before any real-data result existed**:
   the strict form was caught producing structurally zero trades on a *synthetic* no-gap
   frame, and the fix is a definitional correction, not a response to performance.

---

## §5 Power requirement and the mechanical gate

Power is classified by `intraday_data.describe_power` and the runner **enforces** it:

| Verdict | Condition | Runner behavior |
|---|---|---|
| `PROMOTABLE` | n_w ≥ 13 and ≥ 500 sessions | full per-cell table, exit 0 |
| `DIRECTIONAL` | ≥ 500 sessions but n_w < 13 | table printed, **not gate-eligible** |
| `UNDERPOWERED` | < 500 sessions or < 80 bars | **no per-cell table at all**, exit 2 |

The underpowered case prints **nothing per-cell** by design. #431 had to hand-label its
shallow numbers "plumbing smoke" in prose; prose gets skipped when a table gets quoted, so
the gate refuses to emit the table. Pinned by
`tests/test_run_candlestick_study.py::test_main_exits_2_and_prints_no_table_on_an_underpowered_frame`.

Daily SPY 1993+ is `PROMOTABLE` (~33 windows, ~8,400 sessions).

### §5.1 Reporting rules that cannot be softened later

- A NaN after-tax Calmar is **classified, never printed as a bare number**: `no-trades`
  (the pattern never fired — not evidence about the pattern) vs `RUINED` (it traded and the
  after-tax curve was destroyed — *worse* than a negative Calmar, not a missing one). Both
  counts are printed on every run.
- Every cell is reported. **No silent truncation, no top-N.**

---

## §6 Negative control (must hold, checked)

`tests/test_run_candlestick_study.py::test_pure_noise_clears_no_cell` runs the **full frozen
grid** over 3,600 sessions of driftless random-walk bars and asserts **no cell clears the
bar**. Without it, an all-negative real result is ambiguous between "no edge in candlestick
patterns" and "the harness is broken". A harness that manufactured edge would show it where
by construction there is none.

---

## §7 Results (SPY, `PROMOTABLE`) — the pre-registered read

**Data provenance.** Fetched via the frozen `backtest.run_candlestick_study._fetch_daily`
(yfinance, `auto_adjust=False`, unadjusted OHLC — the transport the frozen geometry assumes),
run 2026-07-26. The unrestricted pull (`_fetch_daily("SPY", None)`) returned 8,428 rows
spanning 1993-01-29 → 2026-07-24, but the trailing row (2026-07-24, a Friday — not an
in-progress bar, since today, 2026-07-26, is a Sunday) carried a `NaN` Close/Adj Close in the
Yahoo feed while Open/High/Low/Volume were present; `idata.validate_ohlc` correctly rejected it
as a data-quality gap in the free feed rather than let a NaN close through. Re-fetching
reproduced the identical gap, so the fetch was re-run as `_fetch_daily("SPY", date(2026, 7,
24))` (`end` is exclusive in yfinance), which drops exactly that one incomplete row and nothing
else. **No `_fetch_daily` code was modified** — this used the function's existing `end`
parameter. Result: **8,427 bars, 1993-01-29 → 2026-07-23**, written to the gitignored
`data/SPY_daily.csv` and re-validated by `idata.load_local`.

**Power:** `PROMOTABLE — n_w=33 >= 13 and 8427 sessions; clears the pre-registered power
floors` (`describe_power` summary, verbatim). n_w=33 well above the n_w=13 promotion bar.

**always-in (buy-and-hold) after-tax CalmarUS over the full 1993-2026 window: +0.1445** — a
different construction from the frozen 1.3085 bar (median of 13 non-overlapping 12-month
windows, 2013-2025); reported here as the always-in baseline every cell is also compared
against per §2.

### §7.2 Full grid (verbatim, 28/28 cells, no truncation)

```
arm                  dir       R   CalmarUS  >bar?     CAGR    maxDD   #tr    random     status
bullish_marubozu     long      3    -0.0232     no  +1.18% -42.17%   162   -0.0468         ok
bullish_marubozu     long      2    -0.0385     no  +0.17% -41.60%   178   -0.0478         ok
shooting_star        short     2    -0.0441     no  -1.36% -38.38%   117   -0.0428         ok
shooting_star        short     3    -0.0459     no  -1.36% -38.00%   116   -0.0468         ok
bearish_marubozu     short     2    -0.0603     no  -0.84% -37.90%   148   -0.0513         ok
hammer               long      3    -0.0637     no  +0.59% -36.13%   220   -0.0788         ok
morning_star         long      2    -0.0696     no  +0.11% -52.45%   177   -0.0424         ok
bullish_engulfing    long      3    -0.0714     no  -0.47% -53.20%   180   -0.0327         ok
hammer               long      2    -0.0715     no  -0.30% -32.70%   254   -0.0960         ok
bearish_marubozu     short     3    -0.0744     no  -1.37% -43.11%   135   -0.0552         ok
morning_star         long      3    -0.0811     no  -0.43% -66.65%   158   -0.0249         ok
bearish_harami       short     2    -0.0903     no  -2.57% -59.27%   273         —         ok
bullish_harami       long      2    -0.0995     no  +0.31% -41.95%   294   -0.0575         ok
bearish_pin_bar      short     2    -0.1057     no  -2.95% -64.93%   252   -0.0958         ok
bullish_harami       long      3    -0.1428     no  -0.06% -48.03%   252   -0.0360         ok
bullish_engulfing    long      2          —     no  -0.47% -53.97%   206   -0.0536     RUINED
bearish_engulfing    short     2          —     no  -5.61% -86.17%   289         —     RUINED
bearish_engulfing    short     3          —     no  -6.52% -90.32%   264         —     RUINED
bullish_pin_bar      long      2          —     no  -1.68% -51.55%   401         —     RUINED
bullish_pin_bar      long      3          —     no  -0.39% -45.85%   343         —     RUINED
bearish_pin_bar      short     3          —     no  -3.46% -71.16%   248   -0.1427     RUINED
bearish_harami       short     3          —     no  -3.01% -64.82%   269         —     RUINED
evening_star         short     2          —     no  -4.25% -78.07%   201   -0.0618     RUINED
evening_star         short     3          —     no  -4.79% -82.17%   194   -0.0726     RUINED
inside_bar_long      long      2          —     no  -3.03% -78.06%   569         —     RUINED
inside_bar_long      long      3          —     no  -1.00% -70.59%   456         —     RUINED
inside_bar_short     short     2          —     no  -7.51% -93.04%   697         —     RUINED
inside_bar_short     short     3          —     no  -7.16% -92.13%   637         —     RUINED

cells clearing the 1.3085 bar: 0 / 28
cells with a RUINED after-tax curve: 13 / 28
cells that never traded: 0 / 28
DSR multiplicity (trial count): N = 28
```

Every single one of the 28 cells is **negative** — not merely below the 1.3085 bar. Thirteen
(46%) are `RUINED` (after-tax curve destroyed by the no-loss-credit US tax treatment on gross
winners); the remaining fifteen are all finite and negative. Zero cells never traded.

### §7.3 `hammer`, first — the one lead carried over from GOOG (§7.0)

Per the frozen convention (open with `hammer`, not with whichever cell happens to look best):
`hammer`/R3 is **-0.0637** (random twin **-0.0788**) and `hammer`/R2 is **-0.0715** (random
twin **-0.0960**) — the real cell sits *above* its random twin in both R values, echoing the
GOOG lead's shape, but both are **negative** in absolute terms and both are **far** below both
the always-in baseline (+0.1445) and the 1.3085 bar. The margin over the random twin (~0.015 -
0.025) is an order of magnitude smaller than the gap that would be needed to reach the bar.

The v2 context-split (companion doc's §7) sharpens this: `hammer`/`reversal` — the **textbook**
reading, the one classic doctrine actually predicts — sits *below* its random twin at both R
(R3: -0.0307 vs random -0.0086; R2: -0.0331 vs random -0.0128), while `hammer`/`continuation` —
the *non-textbook* with-trend reading — sits marginally above its twin (R3: -0.0338 vs random
-0.0478; R2: -0.0402 vs random -0.0457). If `hammer` carried genuine reversal edge, the textbook
context should be the one that outperforms; instead it is the one that underperforms. That is
the tell that the v1 context-free lead is a beta/regime artifact, not a pattern edge, consistent
with the same conclusion the GOOG read already drew.

### §7.4 Firing-rate calibration (verbatim, live SPY data)

```
pattern              dir        count     rate  verdict
inside_bar           neutral      964  11.44%  ok
doji                 neutral      847  10.05%  ok
bullish_pin_bar      long         589   6.99%  ok
bullish_harami       long         373   4.43%  ok
bearish_engulfing    short        353   4.19%  ok
hammer               long         314   3.73%  ok
bearish_harami       short        305   3.62%  ok
bearish_pin_bar      short        296   3.51%  ok
bullish_engulfing    long         286   3.39%  ok
bullish_marubozu     long         224   2.66%  ok
morning_star         long         224   2.66%  ok
evening_star         short        222   2.63%  ok
bearish_marubozu     short        173   2.05%  ok
shooting_star        short        135   1.60%  ok

miscalibrated: 0 / 14
```

All 14 detectors fire inside the diagnostic bounds on the pre-registered instrument itself —
the §7.0 GOOG calibration read is confirmed on SPY, not just on a different vehicle.

### §7.5 Pooled #398 gate at cumulative N=84 (verbatim; this run also feeds the v2 doc's §7)

```
Pooled #398 overfitting gate — candlestick family, cumulative N=84
source: local:data/SPY_daily.csv
power: PROMOTABLE: 8427 bars / 8427 sessions / n_w=33 (1993-01-29 -> 2026-07-23) — n_w=33 >= 13 and 8427 sessions; clears the pre-registered power floors
n_trials: 84
best cell: ('bullish_marubozu', 3.0, 'continuation') over 8427 common days
DSR 0.0122 (threshold >= 0.95) -> FAIL
PBO 0.4036 (threshold < 0.5) -> PASS
bootstrap ci_low -0.000529 (threshold > 0) -> FAIL
combined verdict -> FAIL
reasons: dsr 0.0122 < threshold 0.95; bootstrap ci_low -0.000529 <= 0
```

This is **one pooled run across all 84 cells of the cumulative family** (v1's 28 + v2's 56) —
not a per-grid N=28 read. The best cell by non-annualized per-day Sharpe over the whole run is
`bullish_marubozu`/R3/`continuation` (a v2 cell), which is also the single least-negative
full-window Calmar cell of all 84 (-0.0056, per the companion doc's §7 table). Even the
best-of-84 cell fails the gate on two of three sub-checks (DSR and the bootstrap uplift CI; PBO
alone passes at 0.40 < 0.5).

### §7.6 Verdict

**0/28 clear the bar in this grid; 0/84 clear across the pooled family (see the v2 doc's §7 for
the other 56); the pooled N=84 gate FAILS (DSR 0.0122, well below the 0.95 deflation
threshold).** Per §8's mapping, "0 clear ⇒ the class is closed on daily bars." No cell needed
the gate to be disqualified — none cleared the primary bar at all — but the gate result is
recorded anyway because it was pre-committed in step 1, before any SPY number existed, and
because it quantifies just how far even the best-of-84 cell is from a defensible signal: a DSR
of 0.0122 says the best trial's Sharpe is fully explained by having tried 84 configurations,
with essentially none left over as evidence of edge.

**Candlestick patterns, on daily SPY bars, with a bracket exit anchored to the pattern's own
extreme, are a closed direction.** This closes the `candlestick_pattern`/daily/SPY cell in the
tested-cell ledger (§ below in this repo's `backtest/tested_cells.py`) with `NO_GO`.

### §7.0 Real-data harness validation — GOOG, DIRECTIONAL — **NOT the pre-registered read**

> **This is not §7's answer and must never be quoted as one.** The pre-registered read is
> **SPY daily, `PROMOTABLE`**. What follows is a different instrument (GOOG), a different era
> (2004-2013), and `DIRECTIONAL` power (n_w=8 < 13). It exists to validate the harness on real
> candles, and §7 above stays empty until the pre-registered read runs.

**Source.** Real GOOG daily OHLC, 2,148 sessions, 2004-08-19 → 2013-03-01, shipped inside the
`backtesting` PyPI wheel (`backtesting.test.GOOG`) — reachable because `pypi.org` is allowlisted
while every market-data host is not.

**Why bother.** A synthetic random-walk frame **cannot** reveal a miscalibrated threshold. Real
markets gap, trend, and cluster their volatility, so a body/wick ratio that discriminates on
Gaussian noise can fire on a quarter of real bars — or on none. The 71 detector unit tests verify
the detectors' *logic* while leaving their *calibration* entirely unchecked. This closes that gap.

**Result 1 — calibration: PASS, 0/14 miscalibrated.** All 14 detectors fire inside the
diagnostic bounds (0.5% ≤ rate ≤ 25%) on real bars:

| pattern | dir | count | rate | | pattern | dir | count | rate |
|---|---|---|---|---|---|---|---|---|
| `inside_bar` | neutral | 284 | 13.22% | | `bullish_engulfing` | long | 68 | 3.17% |
| `doji` | neutral | 256 | 11.92% | | `hammer` | long | 57 | 2.65% |
| `bullish_pin_bar` | long | 125 | 5.82% | | `evening_star` | short | 51 | 2.37% |
| `bearish_pin_bar` | short | 106 | 4.93% | | `shooting_star` | short | 44 | 2.05% |
| `bearish_engulfing` | short | 97 | 4.52% | | `bullish_marubozu` | long | 37 | 1.72% |
| `bearish_harami` | short | 96 | 4.47% | | `bearish_marubozu` | short | 37 | 1.72% |
| `bullish_harami` | long | 93 | 4.33% | | | | | |
| `morning_star` | long | 70 | 3.26% | | | | | |

**No v2 threshold pre-registration is needed** — §3.1's frozen constants survive contact with
real candles. The real-vs-synthetic differences are also directionally sensible: pin bars fire
~2× more often on real bars (4.9%/5.8% vs 2.9%/2.8%) because real markets genuinely reject
levels, and `doji` fires 11.9% vs 5.2% because real markets have more small-body indecision days.
The detectors respond to real structure, not to noise.

**Result 2 — the 28-cell grid on GOOG: 0/28 clear, 3/28 `RUINED`, 0 never traded.** Three
caveats make this *weaker* than it looks, all of which must travel with the number:

1. The **1.3085 bar is SPY-specific**; judging GOOG cells against it is apples-to-oranges.
2. GOOG went ~100 → ~800 over this window (always-in after-tax CalmarUS **+0.3827**), so *every
   short arm losing* is a **vehicle artifact**, not a finding about bearish patterns.
3. `n_w=8` — not gate-eligible, so the #398 gate was not run.

**The one lead worth carrying forward.** `hammer`/R3 posted **+0.2792** against a random-entry
twin at **−0.1654** — the largest real-vs-control gap in the grid, on 45 trades. It is *not* a
survivor: still below always-in (+0.3827), far below the SPY bar, and at N=28 one or two cells
beating their twins is what noise produces — `morning_star`/R2 was *beaten* by its own twin
(+0.0152 vs +0.1626). Recorded as **a cell to look at first** when the SPY read runs, not as
evidence of edge.

Reproduce: `python3 -m backtest.run_candlestick_study --data data/GOOG_daily.csv` and
`… --firing-rates`.

### §7.1 What has been verified without real data

- **89 tests**, all offline: 66 pattern-detector tests (including a truncation-invariance
  property test for no-look-ahead over all 14 patterns, and a zero-range-bar test over all
  14) and 23 runner tests. Full suite: **622 passed, 0 failed**.
- The CLI drives all 28 cells end to end on a 4,000-bar synthetic frame, exit 0. **Those
  numbers are a pipeline smoke on random data, not a result about candlestick patterns, and
  none is recorded in this document.**

---

## §8 What a result would and would not authorize

| Outcome | What it authorizes |
|---|---|
| **0/28 clear** | The class is closed on daily bars. Record the negative, stop. |
| **1+ clear, #398 gate FAILS** | Nothing. A cell clearing the bar while failing DSR/PBO is the textbook overfit signature at N = 28. |
| **1+ clear, gate PASSES, ES arm disagrees** | Nothing live. Fund a deeper/out-of-sample test first. |
| **1+ clear, gate PASSES, ES arm agrees** | A **design spec** and a fresh ADR — *not* a deployment. Live rollout still needs the full architect → developer → tester → reviewer pipeline and would **replace**, never parallel, the 200-DMA rule. |

A cell beating the bar while sitting **on top of its random-entry twin** is not edge — that
is the tell #430 used to conclude the Turtle breakout was a coin flip. The random-twin
comparison is part of the primary read, not a footnote.

---

## §9 Artifacts

| Path | Role |
|---|---|
| `backtest/candlestick.py` | 14 pattern detectors + registry (the frozen multiplicity source) |
| `backtest/run_candlestick_study.py` | Frozen 28-cell grid runner, power gate, report |
| `backtest/run_candlestick_gate.py` | Pooled #398 gate over the cumulative N=84 family (#443) |
| `tests/test_candlestick.py` | 66 detector tests |
| `tests/test_run_candlestick_study.py` | 23 runner tests incl. the negative control |
| `tests/test_run_candlestick_gate.py` | Gate-application tests: N=84 accounting, noise-must-fail, seed reproducibility, power refusal |
| `docs/runbooks/orb-data-drop.md` | How to supply bars locally |
| `data/SPY_daily.csv` | Gitignored — SPY daily bars used for §7, reproducible via `_fetch_daily("SPY", date(2026, 7, 24))` |
