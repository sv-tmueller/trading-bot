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

`python3 -m backtest.run_turtle_breakout --end 2026-06-30` (a strictly later commit than
the frozen section above — see git history). CalmarUS is full-window after-tax US Calmar
(the bar metric); CAGR/maxDD are pre-tax. `rand` = seeded random-entry bracket (same
2N-stop / R·N-target geometry); `always` = always-in (buy-&-hold the vehicle).

**Data windows.** SPY daily 1993-01-29 → 2026-06-29 (8,410 bars, 34 OOS windows);
ES=F daily 2000-09-18 → 2026-06-29 (6,508 bars, 26 windows). Hourly 60m (as-of the run
date, rolling ~730-day cap): **SPY 3,214 bars (2024-08-23 → 2026-06-29); ES=F 10,555
bars (2024-08-23 → 2026-06-30)** — well short of the n_w = 13 the gate needs, as
pre-registered.

### Daily arm (gate-eligible)

| cell | after-tax CalmarUS | > 1.3085 bar? | CAGR (pretax) | maxDD | #trades | random | always-in |
|---|---|---|---|---|---|---|---|
| SPY R2  | **−0.078** | no | −2.4% | −56.6% | 427 | n/a (ruin) | +0.183 |
| SPY R3  | **−0.072** | no | −2.0% | −52.4% | 418 | n/a (ruin) | +0.183 |
| SPY R4  | **−0.071** | no | −2.0% | −52.8% | 417 | n/a (ruin) | +0.183 |
| ES=F R2 | **−0.057** | no | −1.3% | −31.0% | 297 | n/a (ruin) | +0.103 |
| ES=F R3 | **−0.057** | no | −1.4% | −32.5% | 291 | n/a (ruin) | +0.103 |
| ES=F R4 | **−0.057** | no | −1.4% | −32.5% | 290 | n/a (ruin) | +0.103 |

The random-entry daily brackets ruin the after-tax curve (e.g. SPY R2 random ends at
≈ $21,775 from $100,000, pre-tax maxDD −79% → the no-loss-credit US tax on gross winners
drives after-tax equity to a NaN Calmar), i.e. **worse** than the real cells. Both the
real and random brackets are negative; the strategy adds nothing over (cost-eroded) beta.

### Hourly arm (directional, NON-promotable)

| cell | after-tax CalmarUS | CAGR (pretax) | maxDD | #trades | random | always-in |
|---|---|---|---|---|---|---|
| SPY R2  | −0.558 | −6.6%  | −12.2% | 78  | −0.574 | +0.673 |
| SPY R3  | −0.547 | −4.2%  | −9.9%  | 70  | −0.568 | +0.673 |
| SPY R4  | −0.538 | −3.2%  | −9.0%  | 63  | −0.549 | +0.673 |
| ES=F R2 | −0.581 | −16.2% | −30.2% | 203 | −0.643 | +0.656 |
| ES=F R3 | −0.578 | −14.5% | −27.0% | 164 | −0.641 | +0.656 |
| ES=F R4 | −0.567 | −14.5% | −28.2% | 150 | −0.628 | +0.656 |

### Daily per-window after-tax (US) Calmar stability (12-mo OOS windows; sparse caveat)

| cell | median window Calmar | positive windows |
|---|---|---|
| SPY R2  | −0.799 | 6/34 |
| SPY R3  | −0.782 | 6/34 |
| SPY R4  | −0.782 | 6/34 |
| ES=F R2 | −0.767 | 5/26 |
| ES=F R3 | −0.767 | 6/26 |
| ES=F R4 | −0.767 | 6/26 |

### Daily-arm #398 gate (secondary robustness; D1 N=6, D2 per-day returns)

Best-Sharpe cell (ES=F, R2) over 6,480 common days: **DSR 0.0089, PBO 0.0089, bootstrap
ci_low −0.000693 → FAIL** (`dsr 0.0089 < 0.95`; `ci_low −0.000693 ≤ 0`). Read with the
sparse-series caveat, but it points the same way as the primary metric.

---

## Verdict

**NO-GO on all 12 cells.** Not one of the 6 gate-eligible **daily** cells clears the
frozen **1.3085** SPY bar — every daily cell has a *negative* full-window after-tax US
Calmar (−0.057 to −0.078). The daily-arm #398 gate also **fails** (DSR 0.009, negative
bootstrap ci_low). The 6 **hourly** cells (directional only, never gate-eligible) are
worse still (−0.54 to −0.58). The per-window stability is negative in every cell (median
Calmar ≈ −0.77 to −0.80; a minority of windows positive).

The Turtle/Donchian-55 breakout bracket does not merely fail to beat SPY — it **destroys
value**: every cell underperforms even the always-in buy-&-hold of the same vehicle
(+0.18 SPY / +0.10 ES=F full-window after-tax Calmar), and the seeded random-entry
bracket with identical geometry ruins the after-tax curve outright. That the real cells
sit right on top of the random cells is the tell: there is no edge here beyond
(cost-eroded, churned) beta.

### Honest caveats that qualify the read

- **The `always-in` +0.18 (SPY) is below 1.3085 too** — but that is *not* SPY failing its
  own bar. The 1.3085 bar is the **median 12-month OOS-window** after-tax Calmar
  (2013–2025); the +0.18 here is a **full-window 1993–2026** after-tax Calmar that
  includes the 2000–02 and 2008 crashes, a structurally lower number. The bar is the
  frozen comparison; `always-in` is the beta reference, and every cell is far below it.
- **EOW weekly close-out (pre-registered) drives the churn.** Flattening at each ISO
  week-end turns the long-horizon Turtle into a weekly-flattened bracket — hence 400+ SPY
  daily "trades" over 33 years — and, at 10 bps round-trip, the cost drag is a material
  contributor to the negative result. This is an honest property of the *rule as frozen*,
  not a bug; a future long-horizon variant would drop EOW, but that is a different,
  un-pre-registered strategy.
- **ES=F roll splice.** ES is the raw unadjusted front-month splice; roll gaps can
  spuriously trigger breakouts/stops. ES is the robustness leg; **SPY is primary** and
  gives the same verdict.
- **Hourly depth.** The 60m arm is ~730-day-capped (probed above) and directional only;
  its span rolls with the run date and it is never gate-eligible.
- **Leverage.** This is a **1×** test. The operator's aim is to replace the **3× UPRO**
  bot, so any candidate must eventually clear the bar **vs the 3× incumbent**
  (`run_leveraged_regime_study.py`), not just 1× SPY. That is moot here — the strategy is
  negative at 1×, so it does not advance to a 3× comparison.

### Consequence

Candidate A (Turtle/Donchian-55 breakout bracket) is **rejected**. The reusable
`backtest/bracket.py` engine it was built on stands and is available for #431 (ORB) and
any further bracket candidates — the negative result is on the *strategy*, not the
harness. The numbers were examined only after the bar was frozen and committed (git
history: the pre-registration commit precedes this results commit), and the frozen
section was not edited afterward.
