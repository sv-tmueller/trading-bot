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

**EMPTY — the pre-registered read has not been run.** No number is invented.

Every market-data host remains **403-denied** by this environment's egress policy (re-probed;
Yahoo, Alpaca and `jsr.io` all still blocked). The operator has elected to allowlist the hosts;
**as of this commit that allowlist is not yet live.**

Unblock: allowlist `query1.finance.yahoo.com` + `fc.yahoo.com`, or supply bars via `--data`
(see `docs/runbooks/orb-data-drop.md`). §7 gets filled in a **strictly later commit** than this
freeze.

## §8 What a result would authorize

| Outcome | Authorizes |
|---|---|
| 0/56 clear | The context filter does not rescue the class. Record it; move to the next pre-registered round. |
| 1+ clear, #398 gate fails at cumulative N=84 | **Nothing.** Textbook overfit signature. |
| 1+ clear, gate passes, cell sits on its random twin | **Nothing** — that is the tell #430 used to call the Turtle a coin flip. |
| 1+ clear, gate passes, beats its twin and always-in | A **design spec** and a fresh ADR. Not a deployment. |
