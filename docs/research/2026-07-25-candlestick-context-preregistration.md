# Candlestick study v2 — trend-context grid: pre-registration (56 cells)

**Question:** Does adding a **trend context** filter — the thing classic candlestick doctrine
says is essential — rescue any candlestick pattern that failed context-free in v1?

**Issues:** refs #422, #431 · **Predecessor:** `2026-07-25-candlestick-pattern-preregistration.md`
**Date:** 2026-07-25
**Author:** Claude Code session (research-only; no production/TypeScript code, no `supabase/`,
no `strategy/`, no settings, no broker integration touched; no order placed).

---

## §0 Disclosure of ordering (read first — this is not a clean pre-registration)

The repo's discipline is that a pre-registration is committed **strictly before any result is
examined**. This document only partly satisfies that, and pretending otherwise would be worse
than saying so:

| What | When | Clean? |
|---|---|---|
| Grid design (14 arms × R{2,3} × context, cumulative-N rule) | Specified in the **approved plan**, before any v2 number existed | ✅ yes |
| Second context mode (`continuation`) added | During implementation, **before** any v2 number existed | ✅ yes |
| GOOG `DIRECTIONAL` run | **Before** this document was committed | ❌ **no** |
| SPY `PROMOTABLE` read | **Not yet run — unseen** | ✅ still clean |

So: **the v2 grid was frozen before results, but this document was not committed before the
GOOG numbers were seen.** The GOOG figures in §6 are therefore reported as a *directional
harness read*, exactly as v1's §7.0 was, and they are **not** this study's answer. §7 — the
SPY read — remains genuinely unseen, and that is the verdict slot.

> **Addendum (2026-07-26, batch #439 decision D9 — dated, not an in-place rewrite):** the
> SPY `PROMOTABLE` read has since been run. The freeze above (`8d424f7`) held: §7 was filled
> in the strictly later commit `1e19a5f` (PR #446), so the SPY row of the table above moved
> from "not yet run — unseen" to **run, clean** — the read was unseen at freeze time, which
> is what the ✅ certified. Verdict: **NO_GO at cumulative N=84** (see §7).

Why `continuation` was added during implementation: the plan named only the `reversal` reading.
Freezing **both** canonical readings removes my ability to pick the flattering one after seeing
results. That is a tightening of the discipline, not a loosening, and it was decided before any
v2 number existed.

---

## §1 Invariant framing

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants): any
candidate here would be a deterministic pure function of price history that **replaces** the
live 200-DMA/UPRO rule, never a second parallel rule, and imports no model SDK. Nothing here is
live; `compute_target_state` is unchanged; `backtest/` is never imported by
`supabase/functions/`. **This study authorizes nothing live.**

## §2 The bar (verbatim, unchanged from v1)

> A cell clears the bar only if its **full-window after-tax US Calmar** exceeds the SPY
> buy-and-hold median-window after-tax Calmar of **1.3085475049604838** (n_w = 13
> non-overlapping 12-month windows, 2013-2025), on the same after-tax basis.

Secondary, reported but not the verdict: CAGR, max drawdown, trade count, each cell's
**random-entry twin**, the **always-in** benchmark, and the #398 gate outputs.

## §3 The grid (frozen, 56 cells)

**14 pattern arms × R ∈ {2, 3} × context ∈ {`reversal`, `continuation`} = 56 cells.**

Arms and R-grid are inherited unchanged from v1 (`run_candlestick_study.ARMS`, `R_GRID`) — the
registry is the single source of truth, so the two studies cannot drift apart.

`CONTEXT_NONE` is **deliberately excluded**: that is v1's grid, and re-running it here would
double-count 28 trials. Pinned by
`test_run_candlestick_context_study.py::test_v1_context_none_is_not_re_run_in_v2`.

### §3.1 The context rule (frozen)

Trend is defined by **reusing** `regime_signals.sma_signal(closes, window=200)` — the incumbent
200-DMA filter — rather than introducing a second definition of "trend" that could drift from
the live bot's.

| Context | Bullish arms fire when | Bearish arms fire when |
|---|---|---|
| `reversal` (textbook) | close **<** SMA200 (downtrend) | close **>** SMA200 (uptrend) |
| `continuation` (with-trend) | close **>** SMA200 | close **<** SMA200 |

**Warm-up bars are masked OUT, not admitted.** `sma_signal` is NaN for the first 200 bars;
admitting an unknown context would silently make those bars behave like `CONTEXT_NONE` and
contaminate the arm. Pinned by `test_context_warmup_bars_are_masked_out_not_admitted`.

**The random-entry twin draws only from context-admitted bars.** Otherwise the control would
differ from the real cell in two ways at once — entry timing *and* trend regime — and a gap
between them could no longer be attributed to the pattern, which is the only thing the control
exists to isolate. Pinned by `test_random_twin_draws_only_from_context_admitted_bars`.

## §4 Multiplicity — the cumulative rule

This is round 2 of a **widening** search. Widening must not launder multiplicity by resetting
the trial count each round, so two numbers are always reported:

- **this grid:** N = 56
- **cumulative family:** N = 84 (v1's 28 + v2's 56)

**The deflated-Sharpe bar must be computed against the cumulative N.** Stated plainly up front:
**every added round raises the bar.** A survivor found in round 3 needs a larger effect to be
credible than the same effect found in round 1. This is the honest price of more shots on goal,
and it is why the widening is sequenced by defensibility rather than by convenience.

## §5 Power gate and reporting rules

Identical to v1 and mechanically enforced: `UNDERPOWERED` ⇒ **no per-cell table at all**, exit
2. NaN Calmars are classified `no-trades` (never fired — not evidence about the pattern) vs
`RUINED` (traded and the after-tax curve was destroyed — *worse* than negative, not missing).
Every cell is reported; no top-N, no silent truncation.

A **pure-noise negative control** covers this grid too
(`test_pure_noise_clears_no_cell`). A new grid without its own control is not finished: without
it, an all-negative real result is ambiguous between "the filter does not help" and "the filter
is wired up wrong".

---

## §6 GOOG directional read — **NOT this study's answer**

> Real GOOG daily, 2,148 sessions, 2004-08-19 → 2013-03-01, `DIRECTIONAL` (n_w=8 < 13). Wrong
> instrument, wrong era, below the promotion bar. Reported for harness behaviour only.

**0 / 56 cells clear the bar. 0 RUINED. 0 never traded.**

| Top cells | ctx | R | CalmarUS | CAGR | maxDD | #tr | random |
|---|---|---|---|---|---|---|---|
| `hammer` | continuation | 3 | **+0.2929** | +7.20% | −11.04% | 30 | −0.1150 |
| `bullish_pin_bar` | continuation | 3 | +0.1366 | +8.15% | −12.13% | 54 | −0.1062 |
| `morning_star` | continuation | 2 | +0.1236 | +7.92% | −20.91% | 37 | −0.0562 |
| `hammer` | continuation | 2 | +0.1080 | +4.36% | −12.67% | 33 | −0.1140 |

Three honest readings, all of which cut *against* the filter helping:

1. **The context filter did not rescue the class.** Best v2 cell (+0.2929) barely exceeds best
   v1 cell (+0.2792), and both sit below always-in (+0.3827) and far below the 1.3085 bar.
   Adding the doctrine's own essential ingredient moved nothing material.
2. **`continuation` dominating the top is almost certainly a vehicle artifact, not a finding.**
   GOOG ran ~100 → ~800 over this window, so "long in an uptrend" is largely beta exposure. Note
   this is the *opposite* of textbook doctrine (`hammer` is taught as a **reversal** signal), and
   the reversal arms did **not** outperform — which is what one would expect if the ranking is
   being driven by the trend rather than by the patterns.
3. **The RUINED count fell 3 → 0.** A real mechanical effect: filtering cut the churn that drove
   v1's `inside_bar` arms into after-tax ruin. Worth knowing, but it is a turnover effect, not
   evidence of edge.

`hammer` is the top cell in **both** v1 and v2 — a consistent but weak lead (30-45 trades), and
at cumulative N = 84 that consistency is well within what noise produces. Carried forward as
*the first cell to inspect on SPY*, not as a result.

Reproduce: `python3 -m backtest.run_candlestick_context_study --data data/GOOG_daily.csv`

---

## §7 Results (SPY, `PROMOTABLE`)

**Data provenance.** Identical source frame to the v1 doc's §7: fetched via the frozen
`backtest.run_candlestick_study._fetch_daily("SPY", date(2026, 7, 24))` (yfinance,
`auto_adjust=False`, unadjusted OHLC), run 2026-07-26. The unrestricted pull returned a
trailing row (2026-07-24) with a `NaN` Close/Adj Close in the Yahoo feed (Open/High/Low/Volume
present) — a data-quality gap, re-confirmed on re-fetch, not an in-progress bar (today,
2026-07-26, is a Sunday). The fetch was re-run with the explicit `end=date(2026, 7, 24)`
(exclusive in yfinance), dropping exactly that one row. No `_fetch_daily` code was modified.
Result: **8,427 bars, 1993-01-29 → 2026-07-23**, written to the gitignored
`data/SPY_daily.csv`, re-validated by `idata.load_local`. Power:
`PROMOTABLE — n_w=33 >= 13 and 8427 sessions`. always-in after-tax CalmarUS over the full
window: **+0.1445** (see §2 for why this differs from the frozen 1.3085 bar).

### §7.1 Full grid (verbatim, 56/56 cells, no truncation)

```
arm                  dir    ctx             R   CalmarUS  >bar?     CAGR    maxDD   #tr    random     status
bullish_marubozu     long   continuation    3    -0.0056     no  +1.71% -23.70%   120   -0.0358         ok
shooting_star        short  continuation    3    -0.0206     no  +0.07% -19.58%    25   -0.0345         ok
bullish_marubozu     long   continuation    2    -0.0206     no  +1.16% -14.70%   131   -0.0399         ok
bullish_engulfing    long   reversal        3    -0.0214     no  -0.09% -42.69%    40   -0.0230         ok
bullish_engulfing    long   reversal        2    -0.0232     no  -0.11% -41.69%    46   -0.0285         ok
bullish_pin_bar      long   reversal        3    -0.0248     no  +0.26% -27.40%    77   -0.0208         ok
bullish_marubozu     long   reversal        3    -0.0256     no  -0.45% -32.21%    43   +0.0065         ok
morning_star         long   reversal        3    -0.0276     no  -0.54% -55.99%    50   -0.0117         ok
shooting_star        short  continuation    2    -0.0286     no  -0.17% -19.63%    25   -0.0315         ok
bearish_marubozu     short  continuation    2    -0.0293     no  -0.35% -25.55%    44   -0.0342         ok
bullish_pin_bar      long   reversal        2    -0.0296     no  +0.03% -27.47%    85   -0.0286         ok
hammer               long   reversal        3    -0.0307     no  -0.49% -31.48%    52   -0.0086         ok
morning_star         long   reversal        2    -0.0310     no  -0.66% -48.86%    52   -0.0212         ok
morning_star         long   continuation    2    -0.0315     no  +0.78% -26.41%   125   -0.0212         ok
bullish_harami       long   reversal        3    -0.0324     no  -0.56% -40.33%    65   +0.0001         ok
bullish_marubozu     long   reversal        2    -0.0329     no  -1.16% -43.21%    45   +0.0058         ok
hammer               long   reversal        2    -0.0331     no  -0.49% -29.37%    57   -0.0128         ok
inside_bar_long      long   reversal        3    -0.0337     no  +0.20% -51.92%   133   -0.0384         ok
hammer               long   continuation    3    -0.0338     no  +1.09% -15.52%   166   -0.0478         ok
bullish_harami       long   reversal        2    -0.0344     no  -0.66% -36.83%    72   -0.0064         ok
bullish_harami       long   continuation    2    -0.0346     no  +1.13% -20.59%   217   -0.0537         ok
bearish_harami       short  continuation    2    -0.0361     no  -0.43% -29.12%    64   -0.0246         ok
evening_star         short  continuation    3    -0.0373     no  -0.63% -45.27%    46   -0.0345         ok
shooting_star        short  reversal        2    -0.0382     no  -1.15% -35.15%    86   -0.0326         ok
bearish_marubozu     short  continuation    3    -0.0385     no  -0.78% -27.27%    43   -0.0321         ok
bearish_marubozu     short  reversal        2    -0.0392     no  -0.34% -25.59%   100   -0.0397         ok
evening_star         short  continuation    2    -0.0394     no  -0.67% -31.70%    48   -0.0357         ok
shooting_star        short  reversal        3    -0.0395     no  -1.39% -42.13%    85   -0.0268         ok
morning_star         long   continuation    3    -0.0400     no  -0.04% -38.29%   111   -0.0207         ok
hammer               long   continuation    2    -0.0402     no  +0.05% -14.10%   186   -0.0457         ok
bullish_harami       long   continuation    3    -0.0402     no  +0.56% -20.76%   193   -0.0479         ok
bearish_pin_bar      short  continuation    2    -0.0417     no  -1.14% -35.25%    62   -0.0371         ok
bearish_harami       short  continuation    3    -0.0420     no  -1.17% -38.39%    61   -0.0374         ok
bearish_pin_bar      short  continuation    3    -0.0421     no  -1.04% -44.50%    62   -0.0415         ok
bearish_marubozu     short  reversal        3    -0.0434     no  -1.09% -37.41%    93   -0.0409         ok
bullish_engulfing    long   continuation    3    -0.0455     no  +0.00% -25.56%   142   -0.0367         ok
inside_bar_long      long   reversal        2    -0.0457     no  -1.16% -57.58%   140   -0.0409         ok
bearish_pin_bar      short  reversal        2    -0.0481     no  -1.80% -47.72%   181   -0.0483         ok
bullish_engulfing    long   continuation    2    -0.0496     no  -0.47% -35.10%   162   -0.0446         ok
bearish_harami       short  reversal        2    -0.0506     no  -2.09% -52.19%   205   -0.0554         ok
bearish_harami       short  reversal        3    -0.0521     no  -1.81% -49.27%   204   -0.0540         ok
bearish_pin_bar      short  reversal        3    -0.0528     no  -2.44% -58.95%   177   -0.0488         ok
bearish_engulfing    short  continuation    3    -0.0541     no  -2.59% -58.82%    70   -0.0413         ok
bearish_engulfing    short  continuation    2    -0.0556     no  -2.87% -62.93%    73   -0.0419         ok
evening_star         short  reversal        2    -0.0653     no  -3.59% -71.86%   149   -0.0417         ok
evening_star         short  reversal        3    -0.0667     no  -4.23% -77.93%   144   -0.0452         ok
inside_bar_short     short  continuation    3    -0.0686     no  -1.36% -48.86%   131         —         ok
bullish_pin_bar      long   continuation    3    -0.0798     no  -0.49% -36.72%   267   -0.1052         ok
inside_bar_short     short  continuation    2    -0.0804     no  -2.09% -56.77%   146         —         ok
bullish_pin_bar      long   continuation    2    -0.0843     no  -1.51% -48.58%   307   -0.1153         ok
bearish_engulfing    short  reversal        2    -0.1148     no  -2.83% -63.44%   207   -0.0473         ok
bearish_engulfing    short  reversal        3    -0.1320     no  -4.45% -79.72%   196   -0.0497         ok
inside_bar_long      long   continuation    2          —     no  -1.40% -54.19%   433         —     RUINED
inside_bar_long      long   continuation    3          —     no  -0.09% -48.11%   348         —     RUINED
inside_bar_short     short  reversal        2          —     no  -5.07% -83.56%   528         —     RUINED
inside_bar_short     short  reversal        3          —     no  -5.62% -86.75%   494         —     RUINED

cells clearing the 1.3085 bar: 0 / 56
cells with a RUINED after-tax curve: 4 / 56
cells that never traded: 0 / 56

DSR multiplicity — THIS grid: N = 56
DSR multiplicity — CUMULATIVE family (v1 28 + v2 56): N = 84
The cumulative N is the one the deflated-Sharpe bar must use. Widening the search raises that bar; it never lowers it.
```

Every one of the 56 cells is **negative**. Four (`inside_bar_long`/`continuation` both R,
`inside_bar_short`/`reversal` both R) are `RUINED`; the remaining fifty-two are all finite and
negative. Zero cells never traded.

### §7.2 Context does not rescue `hammer`, or anything else

The context filter **does not flip the sign of a single cell**: the best v2 cell
(`bullish_marubozu`/`continuation`/R3, -0.0056) is closer to zero than v1's best context-free
cell (`bullish_marubozu`/R3, -0.0232), but it is still negative, still below always-in
(+0.1445), and still an order of magnitude away from the 1.3085 bar.

`hammer` — the pre-registered cell to inspect first, per both v1 §7.3 and this doc's §6 —
splits by context exactly as summarized in the companion doc: `reversal` (textbook doctrine)
underperforms its own random twin at both R (R3: -0.0307 vs -0.0086; R2: -0.0331 vs -0.0128),
while `continuation` (non-textbook) sits marginally above its twin (R3: -0.0338 vs -0.0478; R2:
-0.0402 vs -0.0457). Doctrine predicts the opposite ranking. This is the same tell the GOOG
directional read (§6) already flagged for `continuation`-side leads: they track being on the
right side of a trending vehicle, not a pattern edge.

The `RUINED` count fell from 13/28 (v1) to 4/56 (v2, on double the cells) — consistent with the
GOOG read's finding that context filtering cuts churn (fewer, more selective entries), a
turnover effect, not evidence of edge.

### §7.3 Pooled #398 gate at cumulative N=84

Identical run to the v1 doc's §7.5 (the gate pools all 84 cells from both grids in a single
invocation — never a per-grid N=56 read):

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

The overall best-of-84 cell is a v2 cell (`bullish_marubozu`/R3/`continuation`) — reported in
full in the v1 doc's §7.5. FAIL on DSR and the bootstrap uplift CI; PASS on PBO alone.

### §7.4 Verdict

**0/56 clear in this grid; 0/84 across the pooled cumulative family.** Per §8's mapping,
"0/56 clear ⇒ the context filter does not rescue the class." Record it: this closes the
`candlestick_pattern_context`/daily/SPY cell in the tested-cell ledger with `NO_GO`. The pooled
N=84 gate (§7.3) also fails, for completeness, though — as in v1 — no cell needed the gate to
be disqualified since none cleared the primary bar.

**Combined with the v1 read:** trend-context, the ingredient classic candlestick doctrine says
is essential, moved the best cell from -0.0232 (context-free) to -0.0056 (context-filtered) —
closer to zero, but still solidly negative and still an order of magnitude away from either the
always-in baseline or the 1.3085 bar. Adding the doctrine's own key ingredient did not rescue
the class on SPY, exactly as it did not on GOOG (§6).

## §8 What a result would authorize

| Outcome | Authorizes |
|---|---|
| 0/56 clear | The context filter does not rescue the class. Record it; move to the next pre-registered round. |
| 1+ clear, #398 gate fails at cumulative N=84 | **Nothing.** Textbook overfit signature. |
| 1+ clear, gate passes, cell sits on its random twin | **Nothing** — that is the tell #430 used to call the Turtle a coin flip. |
| 1+ clear, gate passes, beats its twin and always-in | A **design spec** and a fresh ADR. Not a deployment. |
