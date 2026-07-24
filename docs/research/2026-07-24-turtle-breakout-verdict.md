# Turtle / Donchian-55 breakout bracket — pre-registered verdict (#430)

**Package P1 of #429** (reusable bracket-exit backtest harness + Candidate A). Design
authority: the SUB_PLAN comment on #430 (architect + locked lead decisions D1–D3).
Mirror pattern: `backtest/run_giveback_study.py` + `docs/research/2026-07-24-giveback-backtest-verdict.md`.

Research-only. No live/TypeScript code, no Alpaca import, no orders. This document
decides only whether the Turtle/Donchian breakout bracket clears the pre-registered
bar; it changes no running behavior.

---

## Pre-registration (committed BEFORE any result is examined)

This section is frozen. It is committed in a separate, earlier commit than the
Results and Verdict below, and is **not edited after the numbers are seen** (provable
from git history, mirroring #425's pre-registration → results commit ordering).

### The bar (verbatim)

> A cell clears the bar only if its **full-window after-tax US Calmar** exceeds the
> SPY buy-and-hold median-window after-tax Calmar of **1.3085475049604838**
> (n_w = 13 non-overlapping 12-month windows, 2013–2025), computed on the same
> after-tax basis (`_after_tax_metrics(...)["calmar_us"]`).

This is the same frozen SPY bar the #314/#420 research program qualifies new
strategies against. **Primary verdict = per-cell after-tax US Calmar vs 1.3085.**

### Grid (frozen, 12 cells) and multiplicity

The grid is **R ∈ {2, 3, 4} × vehicle ∈ {SPY, ES} × bar ∈ {daily, hourly} = 12 cells.**
R is the target multiple (target = entry + R·N); the stop is fixed at entry − 2N.
All 12 cells are disclosed for multiplicity. They split into two arms:

- **Daily arm (6 cells, full-power, gate-eligible):** R{2,3,4} × {SPY, ES}, daily bars.
- **Hourly arm (6 cells, directional only, NON-promotable):** R{2,3,4} × {SPY, ES},
  60-minute bars. yfinance 60m depth is capped (~730 calendar days) and cannot reach
  n_w = 13, so the hourly arm can never carry the gate. It answers only "does hourly
  help or hurt vs daily?" and is explicitly declared non-promotable up front.

### Lead decisions (locked)

- **D1 — DSR trial count.** The #398 overfitting gate (DSR / PBO / block-bootstrap) is
  applied to the **daily arm only**, with **N = 6 trial Sharpes** (the 6 daily cells,
  3R × {SPY, ES}). The hourly arm is declared underpowered/non-promotable and is not
  pooled into the DSR `sr_star`. Rationale: daily and hourly per-observation Sharpes
  are on incompatible observation frequencies; pooling them into one `sr_star` is the
  units/annualization correctness hazard `overfitting_gate.py` warns about. The total
  grid of 12 cells is disclosed in prose for the multiplicity record.
- **D2 — gate observation basis.** The gate is computed on **per-day equity returns**
  (`equity_curve.pct_change()`), not per-window Calmars. The sparse-series caveat below
  is disclosed and the gate is read as a *secondary* robustness check, not the primary
  verdict.
- **D3 — target-gap treatment.** A favorable open gap **above** the target
  (`open ≥ target`) fills at the **target** (conservative cap) — the model never
  credits the extra gap above the target. (Symmetrically, an adverse open gap through
  the stop, `open ≤ stop`, fills at the **open**, no gift.)

### Sparse-series caveat (mandatory)

A bracket's daily equity returns are mostly zeros (flat while flat/between trades), and
many 12-month windows contain 0–1 trades → NaN Calmar (dropped). The DSR/PBO/bootstrap
gate is therefore a **secondary robustness check reported with this caveat, not
over-read**; the **primary verdict is the after-tax US Calmar vs the SPY bar**.

### Entry, stop, target, sizing rules (frozen)

- **Entry signal — Donchian-55 breakout, no look-ahead:**
  `close > high.shift(1).rolling(55).max()` (the rolling max is over the 55 completed
  bars strictly before the signal bar). Long-only; no pyramiding; one lot at a time.
- **N (volatility unit) = ATR(20), Wilder,** via `ta.volatility.AverageTrueRange`,
  taken at the **signal bar (t−1)** — the same bar the breakout is confirmed on.
- **Stop = entry − 2N.** **Target = entry + R·N** (R ∈ {2,3,4}). Levels are absolute,
  computed by the caller and passed to `simulate_bracket`, anchored to the **executed
  entry** (`open_t · (1 + slippage)`).
- **Sizing:** full available cash into one lot at entry, integer shares, `STARTING_CASH`
  = 100,000, `SLIPPAGE_BPS` = 5 and `COMMISSION_BPS` = 5 per side (the `regime.py`
  constants).

### Fill / tie-break / gap conventions (frozen, long-only v1)

Exit tests run **strictly after the entry bar** (the entry bar is never tested for an
exit). `_resolve_bar(open, high, low, stop, target)` on each subsequent bar:

1. **Open-gap first.** `open ≤ stop` → **STOP**, fill = `open` (adverse gap, no gift).
   `open ≥ target` → **TARGET**, fill = `target` (D3 conservative cap, never credit
   above target).
2. **Intra-bar** (open inside the bracket): `low ≤ stop AND high ≥ target` →
   **STOP-first** conservative tie-break, fill = `stop`. Else `low ≤ stop` →
   fill = `stop`; else `high ≥ target` → fill = `target`; else **carry** (mark to
   close).
3. **EOW close-out.** A position still open at the **last bar of an ISO week** (and not
   the final bar of the series) is flattened at that bar's **close** (`exit_reason =
   "eow"`) — weekend-flat, no over-weekend gap risk. The very last bar of the series
   flattens at its close as `exit_reason = "end_of_window"`.
4. **No look-ahead.** Signal on close t−1 → entry at open t → exits tested from t+1;
   Donchian and ATR use only completed prior bars; every trade satisfies
   `exit_date > entry_date`.
5. **Cost model.** Entry executes at `open · (1 + slip)` with a `(1 + comm)` haircut;
   every exit executes at `fill_level · (1 − slip)` with a `(1 − comm)` haircut. The
   trade-ledger dicts match `simulate_from_signal`'s shape
   (`entry_date, exit_date, entry_price, exit_price, qty, pnl, return_pct, exit_reason`)
   so `tax.apply_tax_to_ledger` + `_after_tax_metrics` consume them unchanged.

### Data basis

- **Daily (full-power):** SPY (1993+, n_w ≈ 33) and ES=F (2000+, n_w ≈ 26) via yfinance
  `auto_adjust=True` OHLC — the same basis as the frozen SPY bar.
- **Hourly (directional):** yfinance 60m, depth-capped (~730 calendar days, cannot reach
  n_w = 13). The **actual returned depth is probed and reported at runtime**.
- **Baselines per cell:** SPY buy-and-hold (the 1.3085 bar), a **seeded random-entry
  bracket** (same stop/target geometry, entries shuffled with a fixed seed), and an
  **always-in** row — to catch a bracket that merely captures beta rather than adding
  edge.

### Caveats that qualify any positive read (frozen)

- **ES roll splice.** yfinance `ES=F` is a raw, unadjusted front-month splice; roll gaps
  can spuriously trigger breakouts or stops. **ES is a robustness leg only; SPY is
  primary.**
- **Hourly depth.** The 60m arm is depth-capped and directional; it is never gate-
  eligible. Report the runtime depth.
- **Leverage.** v1 tests **1×** SPY/ES. The operator's aim is to replace the **3× UPRO**
  bot, so a real replacement must eventually clear the bar **vs the 3× incumbent**
  (`run_leveraged_regime_study.py` basis), **not just 1× SPY.** A 1× pass here must not
  be over-read as a replacement-ready result.

---

## Results (filled AFTER the pre-registration commit)

_PENDING — network data run required (yfinance SPY/ES daily + 60m). To be appended in a
strictly later commit than the pre-registration above. No number in this section is ever
written before the data run; a fabricated result is a critical failure._

---

## Verdict

_PENDING — network data run required. GO/NO-GO per cell against the 1.3085 SPY bar
(daily arm gate-eligible; hourly arm directional, non-promotable) will be recorded here,
below the frozen section, after the data run._
