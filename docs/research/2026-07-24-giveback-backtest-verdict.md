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

_PENDING — network run required. Numbers recorded here after the A1 slow test is run._

---

## Results (filled AFTER the pre-registration commit)

_PENDING — network run required. ON-vs-OFF table (per vehicle): full-window after-tax
US Calmar, after-tax DE Calmar, CAGR, max drawdown, worst peak-to-exit giveback._

---

## Verdict

_PENDING — GO / NO-GO recorded after the study is run. A NO-GO is a valid deliverable:
Phase B still ships the code default-OFF, but the flag is never enabled and the negative
is recorded here._
