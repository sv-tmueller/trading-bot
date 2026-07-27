# Forex 1h EUR/USD data feasibility note

**Issue:** #468 (P4 of batch #464). **Predecessors:** `2026-07-15-forex-4h-survey-verdict.md`
(the FXCM cache this note reuses, and its recorded power/cache figures), `backtest/fx_data.py`
(the loader itself, #371/#374), `2026-07-24-short-horizon-entry-feasibility-gate.md` (#422 —
the record this note partially corrects). **Date:** 2026-07-27. **Author:** Claude Code
session (research-only; `backtest/`, `tests/`, `docs/research/` only — no `supabase/`, no
`strategy/`, no settings, no broker integration, no order placed).

---

## §0 Invariant framing

Research-only. This note and the code behind it live entirely under `backtest/`, `tests/`,
and `docs/research/` — the offline research path that never writes to Postgres, never calls
an Alpaca order endpoint, and is never imported by any live-bot table or Edge Function
(`docs/architecture/2026-07-05-codebase-map.md`). No LLM is imported anywhere in this
package; `backtest/elliott.py` is pure `pandas`/`numpy` arithmetic. Nothing in this note
authorizes anything live — it measures whether free 1-hour EUR/USD history clears the
frozen power bar and reports the result honestly, whatever it turns out to be.

---

## §1 The load-bearing finding

The issue and batch #464 both framed 1h forex data acquisition as an open question —
"histdata.com / Dukascopy exports; 20+ years exist." **The repo already has a working,
validated, free 1h EUR/USD loader**: `backtest/fx_data.py`, reading FXCM's public H1 archive
(`https://candledata.fxcorporate.com/H1/EURUSD/<year>/<week>.csv.gz`), no credentials, fully
scriptable, cache-first. It was already exercised at `PROMOTABLE` power nine days earlier by
the 4h survey (`2026-07-15-forex-4h-survey-verdict.md` §1–§4): 744 weekly files, 2012 week 1
→ 2026 week 17, 88,186 H1 rows, 73 Saturday rows dropped, 0 duplicates, 14 windows generated
/ 13 scored (2013–2025).

**Three consequences that shape the whole plan:**

1. The 1h data question is ~80% already solved, and the native cadence here is 1h — no
   resample is needed for this package (the 4h survey resampled the same source; this package
   consumes the H1 frame directly).
2. **This note's highest-value content is an honest correction to the record.**
   `2026-07-24-short-horizon-entry-feasibility-gate.md` §3 asserts *"there is no free intraday
   history source that reaches the frozen n_w = 13 comparability bar"* and *"Every free
   source that clears the bar is **daily**."* **That is false for 1h FX** — #422 §3's table
   only enumerated US-equity/futures intraday and never considered FXCM H1, which this repo
   was already using at PROMOTABLE power nine days earlier (§2.5 below has the re-measured
   figures for this exact package). #422's *cost* wall (§2: 2.1%/yr, built on an 0.82
   trades/day assumption borrowed from a BTC scalping demo) also does not bind at 1h FX in
   the way it assumed — §2.6 below restates the cost question in terms of the
   structure-completion rate this package actually measures. **Of #422's three walls, cost
   does not bind and data does not bind for 1h EUR/USD; only the edge wall remains — which is
   why this package produces a DRAFT pre-registration and no verdict.**
3. histdata.com / Dukascopy are an optional depth extension (~2003+ → n_w ≈ 23), documented
   in `docs/runbooks/fx-1h-data-drop.md` but not implemented (lever L1, batch #464 D3 —
   pre-authorized: FXCM H1 is the mandatory and only implemented source this batch).

### Reconciling the recorded `skip` verdict

This package **reverses** a recorded verdict, and that reversal must be argued, not worked
around. `docs/research/swing-trading/roadmap.md:585` records:

> "**strategies.md #12 Elliott Wave** — wave-counting is non-deterministic by construction.
> The German practitioner literature (Tiedje, Weisenhaus) is *deeper* but no more falsifiable.
> Skip."

and `docs/research/swing-trading/strategies.md:415` records:

> "**#12 Elliott Wave** — non-deterministic by construction; the wave count is what's being
> asked of the analyst, and the LLM will produce inconsistent counts run-to-run. Direct
> conflict with the invariant."

and `strategies.md:303` adds:

> "There is no deterministic wave-counting algorithm that has stood up to scrutiny."

**Both verdicts were against an LLM-authored count** — the object being judged was "ask an
LLM to look at a chart and name the wave count," which is exactly the discretionary,
non-reproducible judgement the architectural invariant (`CLAUDE.md` — no LLM in the trading
path) rules out. `strategies.md:378` (on a related mechanizable pattern) itself asks for the
alternative this package builds: *"codify pivot detection deterministically … treat the LLM
only as a confirmation layer, not the count author."* `backtest/elliott.py` (§3 below) does
exactly that, with **no LLM anywhere in the path** — a streaming, causal ZigZag state
machine plus a hard-rule-and-Fibonacci-band grammar plus a total-order, no-backtracking
matcher. Every decision is deterministic and reproducible from the price series alone: two
calls on the same input produce byte-identical labels (§3.5's determinism test).

This does **not** overturn `strategies.md:303`'s claim that no deterministic wave-counting
algorithm has "stood up to scrutiny" — this package's algorithm has not yet been scrutinized
against real returns at all (no performance number is computed in this batch; see §0 and the
non-goals below). What it does overturn is the premise that a deterministic version cannot
exist or cannot be built: it exists, it is unit-tested against synthetic fixtures with known
labels, and its firing rate is measured against real 1h EUR/USD bars — all without an LLM
touching the count. Whether it has any economic edge is a **separate, later, frozen
pre-registration's question** (§5 of the SUB_PLAN; the DRAFT in this PR, per repo convention,
registers no result). The package must not, and does not, claim the algorithm *works* —
only that it is deterministic, falsifiable, and now testable.

---

## §2 Data acquisition

*(Provenance, completeness, power, and cost-stack figures are filled in §2.1–§2.6 after the
cache is populated and `describe_power` is run — see the egress-probe result immediately
below, which resolved which fork of the plan applies.)*

### Egress probe result (first action of this package, per SUB_PLAN §2.2/§6 order 1)

`fx_data.get_week_bytes(2023, 5, fetch=True)` was called first, before any other code in this
package was written. Result, verbatim:

```
REACHABLE, bytes: 2446
```

`candledata.fxcorporate.com` is reachable from this environment. **This resolves the fork to
the "reachable" branch**: the full plan runs — cache population, real provenance figures, and
a measured (not cited) `describe_power` verdict. AC 1 ("feasibility note on record with
measured n_w") is satisfiable in full this batch; there is no `DATA_BLOCKED` fallback to
invoke.

*(§2.1–§2.6 continue below, filled with measured numbers in the batch's step 7.)*
