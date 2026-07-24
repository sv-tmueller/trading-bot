# Giveback backtest — pre-registered ON-vs-OFF verdict (#420)

**Package 1 of #420** (`docs/plans/2026-07-24-giveback-exit-plan.md`, Tasks A1–A4).
Design spec: `docs/superpowers/specs/2026-07-24-giveback-exit-design.md` §7.

Research-only. No live/TypeScript code, no Alpaca import, no orders. This document
decides only whether Phase B (the live default-OFF implementation) may ever *enable*
the flag; it does not itself change any running behavior.

---

## Pre-registration (committed BEFORE any result is examined)

This section is frozen. It is committed in a separate, earlier commit than the
Results and Verdict below, and is **not edited after the numbers are seen** (provable
from git history).

### Pre-registered ship bar (verbatim)

> Enable the live feature later **only if after-tax Calmar (giveback-ON) > after-tax
> Calmar (giveback-OFF)** on the same history.

This is a **relative** bar (ON vs OFF), not the frozen SPY-vs-strategy bar used to
qualify a new strategy. The gate metric is, precisely, the **full-window after-tax
US Calmar** — `_after_tax_metrics(sim, common)["calmar_us"]` — computed identically
for both arms. This is the incumbent leveraged-regime study's own beat-comparison
basis (`run_leveraged_regime_study.py`), so the ON-vs-OFF comparison is computed the
same way as the study it extends.

**Gate:** GO iff `calmar_us(ON) > calmar_us(OFF)` on the same history, per vehicle.
`calmar_de`, CAGR, max drawdown, and worst peak-to-exit giveback are reported
alongside for the human call, but full-window `calmar_us` is the gate.

### History basis

- **Real UPRO (2009+)** — the fidelity anchor.
- **Synthetic-3× SPY (1993+)** — models the expense ratio, swap financing, and the
  daily-rebalance volatility decay of compounding 3× daily returns; extends the test
  back through the 2000–02 and 2008 drawdowns where a giveback earns its keep.
- The synthetic-3× model is validated against real UPRO over the 2009–2025 overlap
  (Task A1) before any result is trusted; a material divergence is a reported finding,
  not something to paper over.

### Parameters

- Arm threshold `arm_pct = 0.20` (peak unrealized gain that arms the floor).
- Protect fraction `protect_fraction = 0.50` (floor = 0.50 × peak gain).
- Re-entry after a giveback exit is locked until the 200-DMA signal itself next goes
  CASH (a regime reset), matching spec §4.

### Modeling caveat (honest statement of the actual convention)

The backtest runs on **daily** bars; the live feature fires **intraday** (5-min
polling). The synthetic-3× vehicle has `Open == Close` and the engine drops High/Low,
so there is **no intraday low in this model**. The giveback is therefore detected on
the **daily close** (`apply_giveback` compares the day's close to the armed floor),
and the resulting position change is executed by the shared engine at the **next day's
open** (`simulate_from_signal` shifts the close-T signal by one bar and fills at the
following open, net of slippage/commission) — the same execution model both arms use.

This is **not** spec §7's "the day's low breaches `floorGain`, fill at the floor level"
description: that language assumes an intraday low the daily-bar synthetic does not
carry. Close-based detection + next-open fill is a defensible simplification with no
free lunch (next-open fills slip and can gap through the floor), but it is a genuine
approximation of the live intraday rule and is disclosed as such. Both arms are
modeled the same way, so the ON-vs-OFF comparison is fair.

### Out of scope

The −25% catastrophic stop (spec) is **out of scope** for this comparison: neither arm
has it and the engine does not model a hard stop. Its presence or absence affects both
arms identically and does not bear on the ON-vs-OFF Calmar gate.

---

## Task A1 — synthetic-3× vs real UPRO validation

Run once (`tests/test_giveback.py::test_synthetic_3x_tracks_real_upro`, `-m slow`),
synthetic-3× built from **SPY auto-adjusted (total-return) closes**:

| quantity | value | bar |
|---|---|---|
| overlap | 2009-06-25 → 2025-12-30 (4155 days) | — |
| daily-return correlation | **0.9982** | > 0.99 ✓ |
| CAGR gap (synth − real) | **+1.58 pp/yr** | \|gap\| < 5.0 ✓ |
| synthetic-3× CAGR | 34.08% | — |
| real UPRO CAGR | 32.50% | — |

The model tracks real UPRO tightly on both daily correlation and CAGR, so the §7
basis holds and the study results below are trustworthy.

---

## Results (filled AFTER the pre-registration commit)

`python3 -m backtest.run_giveback_study --end 2025-12-31`, arm_pct=0.20,
protect_fraction=0.50. CAGR / max drawdown are pre-tax; Calmar is after-tax
(US = gate, DE alongside); worstGB is the largest peak-to-exit giveback.

### Synthetic-3× SPY — 1993-01-29 → 2025-12-30 (8287 trading days)

| arm | after-tax Calmar US | after-tax Calmar DE | CAGR | max DD | worst giveback |
|---|---|---|---|---|---|
| giveback-OFF | **0.179** | 0.170 | +16.6% | −59.5% | +169.6% |
| giveback-ON  | **0.054** | 0.057 | +8.6%  | −67.6% | +73.3%  |

### Real UPRO — 2009-06-25 → 2025-12-30 (4155 trading days)

| arm | after-tax Calmar US | after-tax Calmar DE | CAGR | max DD | worst giveback |
|---|---|---|---|---|---|
| giveback-OFF | **0.271** | 0.249 | +21.3% | −58.3% | +88.8% |
| giveback-ON  | **0.072** | 0.075 | +10.1% | −65.0% | +74.0% |

The giveback does what it is designed to do on the one metric it targets — it
cuts the worst peak-to-exit giveback (roughly halved on the synthetic, 169.6%→73.3%;
a smaller ~17% reduction on UPRO, 88.8%→74.0%). But it pays for that with about half
the CAGR and, notably, a **worse** max
drawdown on both histories: exiting after a pullback and then staying locked out
until the 200-DMA next turns CASH repeatedly banks a partial gain and then re-enters
the leveraged vehicle at a higher basis, so subsequent declines bite from a worse
spot. The gate metric — full-window after-tax US Calmar — falls sharply in both
cases.

---

## Verdict

**NO-GO.** The pre-registered bar — enable live only if after-tax US Calmar (ON) >
after-tax US Calmar (OFF) on the same history — is **not** cleared on either vehicle:

- Synthetic-3× (1993+): 0.054 (ON) vs 0.179 (OFF) — Calmar **fell**.
- Real UPRO (2009+): 0.072 (ON) vs 0.271 (OFF) — Calmar **fell**.

The giveback does not clear the bar on any history. Consequences per the plan:

- The feature is **not** enabled live. If Phase B ships the code (Packages 2 & 3),
  it ships **default-OFF and the flag is never turned on** — with `GIVEBACK_ENABLED=false`
  live behavior is byte-identical to today, so shipping the dormant code is safe, but
  there is no evidence-backed reason to enable it, and this negative is the record of
  that. Given the strength of the negative (Calmar roughly a third of OFF, CAGR
  halved, drawdown worse), the human may reasonably decide not to build Phase B at all.
- This is a valid, recorded outcome of the pre-registration: the numbers were examined
  only after the bar was frozen and committed (see git history — the pre-registration
  commit precedes this results commit), and the bar was not edited afterward.

### Scope note repeated for the reader

The −25% catastrophic stop is out of scope here (neither arm models it), and the
model uses close-based detection + next-open fill on daily bars, not the spec §7
intraday-low language — see the Modeling caveat above. Both approximations apply
equally to both arms, so they do not explain the ON-vs-OFF gap.
