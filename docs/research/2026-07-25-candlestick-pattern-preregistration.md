# Daily candlestick-pattern study — pre-registration (frozen grid, results pending)

**Question:** Does any classic candlestick **pattern**, traded on **daily** bars with a
bracket exit anchored to the pattern's own extreme, clear the frozen SPY buy-and-hold bar?

**Issues:** refs #422 (short-horizon entry NO-GO), #431 (ORB probe, DATA-BLOCKED)
**Date:** 2026-07-25
**Author:** Claude Code session (research-only; `CLAUDE_AGENT_NO_BROKER=1`; no
production/TypeScript code, no `supabase/`, no `strategy/`, no settings, no broker
integration touched; no order placed).

> **Status: PRE-REGISTRATION ONLY. §7 (Results) is deliberately EMPTY.**
> This document is committed **before** any real-data result exists, in a strictly earlier
> commit than any results will be, per the discipline used by #425, #430 and #431 (provable
> from git history). §2-§6 are frozen and are **not edited after numbers are seen**.

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

## §7 Results

**EMPTY — DATA-BLOCKED. No numbers exist yet, and none are invented here.**

Every market-data host is **403-denied by this environment's egress policy**. Probed and
recorded:

| Blocked (403 CONNECT) | Reachable |
|---|---|
| `query1.finance.yahoo.com`, `fc.yahoo.com`, `data.alpaca.markets`, `stooq.com`, `www.stooq.com`, `api.nasdaq.com`, `api.tiingo.com`, `www.alphavantage.co`, `finnhub.io`, `api.polygon.io`, `databento.com`, `jsr.io` | `github.com`, `registry.npmjs.org`, `pypi.org` |

**Supplying Alpaca keys would not help** — the host itself is denied, which is strictly
worse than #431's key-gated case.

**Unblock paths, either is sufficient:**

1. **Local file (recommended, no network):** drop daily OHLC bars as CSV/Parquet and run
   `python3 -m backtest.run_candlestick_study --data <file>`. Steps in
   `docs/runbooks/orb-data-drop.md`.
2. **Egress allowlist:** permit `data.alpaca.markets` (or Yahoo) in the environment's
   network egress settings, then run without `--data`.

The grid runs unchanged the moment either exists. §7 will then be filled in a **strictly
later commit** than the one freezing §2-§6.

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
| `tests/test_candlestick.py` | 66 detector tests |
| `tests/test_run_candlestick_study.py` | 23 runner tests incl. the negative control |
| `docs/runbooks/orb-data-drop.md` | How to supply bars locally |
