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

### §2.1 Cache population + provenance

The full FXCM H1 EUR/USD cache was fetched via `run_fx_plumbing_check.build_history(fetch=True,
end_year=2026)` (the same frozen `get_week_bytes → parse_week_csv → concat/sort/dedupe` path the
4h survey used), then loaded through this package's own frozen order (SUB_PLAN §2.1):
`drop_saturday_bars` → `drop_in_progress_bar` → `fx_data.to_ohlc_frame(side="Mid")` →
`intraday_data.validate_ohlc` → `intraday_data.describe_power`.

| Item | Value |
|---|---|
| Cache root | `data/fxcm/H1/EURUSD/` |
| File count (`find data/fxcm -type f \| wc -l`) | **744** |
| Year/week span | 2012 week 1 → 2026 (partial, 17 weeks fetched; archive publishing lag) |
| Cache identity hash (`find data/fxcm -type f \| sort \| xargs shasum -a 256 \| shasum -a 256`) | `32d1e4f36888924c63cf08bee0269663cb0aef03052375c1ed33a4d23d856e2b` — **byte-identical to the 4h survey's own recorded hash** (`2026-07-15-forex-4h-survey-verdict.md` §1). Same 744 files, no vendor drift, no corruption since that run. |
| Fetch date (this session) | 2026-07-27 |
| Raw H1 rows | 88,186 (exact match to the 4h survey's figure) |
| Saturday-UTC rows dropped (`drop_saturday_bars`) | 73 (0.083%) — exact match |
| Duplicates | 0 |

**`evaluate_blocked_reasons` re-run, on the Saturday-dropped history (this package's own
frozen load order runs the drop before validation)**: exactly the **same three adjudicated
reasons** fire, and only those — the whitelist doubles as a cache-integrity check, and it
passes:

```
2024: missing weeks 7.55% > 2.00%
2025: missing weeks 7.55% > 2.00%
all:  crossed-quotes rate 2.3810% > 0.100%
```

(2024/2025 are the pre-adjudicated Dec-2024/Jan-2025 and mid-July-2025 vendor gaps; the
crossed-quotes rate is the pre-adjudicated Bid/Ask independent-sampling quirk, which never
reaches the Mid series the labeler consumes — both fully described in
`2026-07-13-fx-4h-harness-plumbing-check.md` §4–§5 and re-confirmed unchanged here.)

Completeness by year (missing weeks / rows found / % rows missing) — identical to the 4h
survey for every complete year, 2026 correctly excluded from the threshold check as a
partial/still-publishing year:

| Year | Missing weeks | Rows found | % rows missing |
|---|---|---|---|
| 2012 | 0 | 6,224 | 2.14% |
| 2013 | 0 | 6,196 | 2.58% |
| 2014 | 0 | 6,201 | 2.50% |
| 2015 | 1 | 6,186 | 0.87% |
| 2016 | 1 | 6,214 | 0.42% |
| 2017 | 1 | 6,184 | 0.90% |
| 2018 | 0 | 6,245 | 1.81% |
| 2019 | 1 | 6,126 | 1.83% |
| 2020 | 1 | 6,188 | 0.83% |
| 2021 | 1 | 6,237 | 0.05% |
| 2022 | 1 | 6,238 | 0.03% |
| 2023 | 0 | 6,175 | 2.91% |
| 2024 | 4 | 5,891 | 0.00% |
| 2025 | 4 | 5,840 | 0.68% |
| 2026 (partial, excluded) | 36 | 2,041 | 0.00% |

### §2.2 Egress reality (recap)

Covered above — `candledata.fxcorporate.com` is reachable in this environment as of
2026-07-27. Lever **L2 was NOT pulled**: this is the reachable-fork run, not the
DATA_BLOCKED fork.

### §2.3 Depth extension (documented only, not implemented)

See `docs/runbooks/fx-1h-data-drop.md` (new, this PR) — the `--data PATH` contract, the
`/data/` gitignore rule, the depth→verdict table, and the honest, `[to verify at fetch
time]`-tagged assessment of histdata.com and Dukascopy. **Neither vendor is implemented in
this package** (lever L1, batch #464 D3 pre-authorization) — FXCM H1 alone already clears
`PROMOTABLE`.

### §2.4 Session / timezone conventions

Inherited verbatim from `fx_data.py`'s docstring and the 4h verdict, not re-derived: the
FXCM `DateTime` column is already UTC (`tz_localize("UTC")`, no DST-aware conversion); the FX
week runs Sunday ~21–22:00 UTC → Friday ~21–22:00 UTC; weekend gaps are expected, not
`check_gaps` failures; trading-day count for drag arithmetic is **260** (24/5); **no
US-session filter** is applied (`intraday_data.regular_session` is a US RTH window and would
silently discard the Asian and European sessions — this package does not call it).

### §2.5 The exact power measurement

`describe_power(h1_ohlc).summary()`, verbatim:

```
PROMOTABLE: 88112 bars / 4413 sessions / n_w=14 (2012-01-02 -> 2026-05-01) — n_w=14 >= 13 and 4413 sessions; clears the pre-registered power floors
```

| Quantity | Value |
|---|---|
| `n_bars` (post Saturday-drop, post drop-in-progress-bar) | 88,112 |
| `n_sessions` | 4,413 |
| Span | 2012-01-02 → 2026-05-01 |
| **`n_windows` (calendar span)** — `(last − first).days // 365` | **14** |
| **Scored windows** (2013–2025, per the 4h survey's ND1; 2026 partial, unscored) | **13** |

The two figures differ deliberately: `n_windows=14` counts every complete 365-day span the
calendar arithmetic finds (including a partial-2026 window at the tail that a scored study
would exclude), while the **scored** count (13, 2013–2025) is what a frozen pre-registration
would actually evaluate against — this is not a mistake, it is the same ND1 convention the
4h survey documented.

**Assertion, printed by the runner before any calibration number:**

```
assert verdict == 'PROMOTABLE' and n_windows >= 13: True
```

**Headline: 1h EUR/USD is `PROMOTABLE`, measured, this session — not cited, not
`DATA_BLOCKED`.** AC 1 is met in full.

### §2.6 Cost stack at 1h — the firing-rate-as-cost-input result

`backtest/fx_costs.py` reused verbatim, no re-derivation. The measured firing rate (from
`run_fx_ew_calibration.py`, θ=0.30% — the frozen default) replaces #422's borrowed
0.82-trades/day BTC-scalping assumption:

| Structure | Count (θ=0.30%, full cache) | Rate (per bar) | Rate (per session, /4413) |
|---|---|---|---|
| impulse / up | 57 | 0.0647% | 0.0129/day |
| impulse / down | 57 | 0.0647% | 0.0129/day |
| zigzag / up | 203 | 0.2304% | 0.0460/day |
| zigzag / down | 221 | 0.2508% | 0.0501/day |
| **all structures, pooled** | **538** | **0.6106%** | **≈0.1219/day** |

Applying the sub-plan's own drag formula (`trades/day × 260 × cost_rt_fraction`) to the
**measured, pooled** rate — reported as a function of the rate, not a single number, per the
sub-plan's explicit instruction:

| Venue preset (base bp) | Drag/yr at the measured pooled rate (0.1219/day) |
|---|---|
| XTB CFD (0.79 bp) | 0.1219 × 260 × 0.000079 ≈ **0.25%/yr** |
| CME 6E (0.56 bp) | 0.1219 × 260 × 0.000056 ≈ **0.18%/yr** |

Both are roughly **8–12× smaller** than #422's own 2.1%/yr figure (which used a 0.82/day
rate) — confirming §1's claim: **cost does not bind at 1h EUR/USD**, once the trade cadence
is set by the structure-completion rate actually measured here rather than borrowed from an
unrelated BTC-scalping demo.

**Hold-duration proxy** (median bars between consecutive structure completions, all kinds/
directions pooled, no exit model exists in this package so this is a proxy only): **125
bars ≈ 5.2 days**. Applied to `fx_costs.py`'s overnight financing figures (0.397 bp/night
long, 0.0905 bp/night short) purely illustratively: ≈5.2 nights × 0.397 bp ≈ 2.06 bp/trade
(long) or ≈5.2 × 0.0905 ≈ 0.47 bp/trade (short) — again, a proxy, not a claim about any real
hold time (there is no exit model yet).

**Leg-length distribution** (θ=0.30%): median 72.6 pips / 17 bars (p25 49.7 pips / 8 bars,
p75 109.2 pips / 30 bars).

**Realized ratio distributions** (pure description, θ=0.30%, not a fit to anything): median
`W2/W1`=0.613 (n=114), `W3/W1`=2.036 (n=114), `W4/W3`=0.376 (n=114), `W5/W1`=0.899 (n=114),
`WB/WA`=0.666 (n=424), `WC/WA`=0.932 (n=424) — all comfortably inside their respective frozen
Fibonacci bands' central mass, as expected for a grammar that requires them to be.

**Pivots/year across the frozen θ grid** (`elliott.THETA_GRID`): θ=0.20% → 437.1/yr (6,262
total); θ=0.30% → 262.3/yr (3,758 total); θ=0.50% → 128.8/yr (1,845 total).

**Reproducibility**: `sha256(input)=3493e55c6251b05b22f0f6b44ba57eab91d71d7f401e68ac9d53c82657507180`,
`sha256(label digest)=39dfe27c0ff5836f37bef8259f54c3724e1b3e3a5fe5b3ebe84e0bdd18d60f32` (both
printed by `run_fx_ew_calibration.py`, verified reproducible across two runs on the
unchanged cache).

---

## §3 The deterministic Elliott Wave labeler — summary

Full design lives in `backtest/elliott.py`'s module docstring (cited in full there: R. N.
Elliott, *The Wave Principle*, 1938; Frost & Prechter, *Elliott Wave Principle*, 1978). In
short: a causal ZigZag pivot state machine (close-only basis, θ inherited from the frozen
`fx_signals.R_GRID`/`run_fx_plumbing_check.R_PCT` constants, never tuned on wave counts) feeds
a hard-rule-plus-Fibonacci-band grammar (impulse R1–R3/F1–F4, zigzag correction C1/C2–C3,
every band endpoint a `FIB[...]` lookup — no hand-fitted numbers), matched by a total-order,
no-backtracking scanner (impulse takes priority over zigzag at the same starting pivot; first
match wins; the scan resumes at the shared boundary pivot). `structure_signal()` maps
completed structures to `{FADE, FOLLOW}` under the `fx_signals.py` int64/warm-up-zero/no-
pre-shift contract, with **neither mapping baked in** — both arms are frozen for the later
pre-registration, per the candlestick v2 dual-mapping precedent.

**Explicit v1 non-goals (loud, not hidden):** nested/fractal counting (wave 3 subdividing
into its own 5-wave set — the largest doctrinal simplification); diagonals (leading/ending,
which permit W1/W4 overlap); flats and triangles (only the zigzag correction is mechanized);
the alternation guideline (W2 sharp ⇒ W4 sideways); multi-timeframe confluence; wave-2 entry
("start of wave 3", which requires signalling on an *incomplete* structure).

**Do-not-de-scope structural guarantees, all pinned by tests in `tests/test_elliott.py`:**
the no-lookahead truncation property (`label_waves(series[:k])` agrees with
`label_waves(series)` filtered to `signal_ts <= series.index[k-1]`, for every `k`); the
determinism double-call test (plus a differently-constructed-but-identical float array and a
renamed index); the scale-invariance test (multiplying the whole path by a constant leaves
every label unchanged — every ratio is scale-free); the anti-oracle sawtooth negative control
(a pure sawtooth with all legs equal fails `F1` — `W2/W1 = 1.0` is outside `[0.382, 0.886]` —
so no impulse fires on an arbitrary alternating sequence).

**A genuine correctness finding surfaced during TDD, worth recording:** the first matcher
implementation attempted an impulse window as soon as it was *numerically* available in the
current batch call (`i+6 <= len(pivots)`), which is exactly the total pivot count a caller
happens to have on hand — and that count depends on how much history is fed. The truncation
property test caught this immediately: a shorter run committed to a zigzag using only 4
pivots, while a longer run (with 2 more, later-arriving pivots) found a higher-priority
impulse claiming the *same* starting pivot, silently erasing the zigzag a shorter/earlier run
would have reported. The fix (documented in `label_waves`'s docstring) is a halting rule: a
starting position is only ever resolved once its full 6-pivot impulse window is itself fully
confirmed; if only the 4-pivot zigzag window exists so far, the scan halts rather than risk a
future pivot invalidating an early commitment. This is precisely the class of bug the
property test exists to catch, and it did.

---

## §4 Summary verdict

**1h EUR/USD is `PROMOTABLE` (n_w=14, measured this session) via the existing, free FXCM H1
archive — not `DATA_BLOCKED`, not cited-not-measured.** AC 1 is met in full: the feasibility
note is on record with a measured `n_w` and an honest verdict.

Per §1's reconciliation: **of #422's three walls (cost, data, edge), cost does not bind
(§2.6: ~0.18–0.25%/yr, not #422's 2.1%/yr) and data does not bind (§2.5: `PROMOTABLE`, not
"no free intraday source reaches n_w=13") for 1h EUR/USD. Only the edge wall remains open —
which is exactly why this package produces a deterministic, tested labeler and a DRAFT
pre-registration, and computes no performance number of any kind.**

The Elliott Wave `skip` verdict (`roadmap.md:585`, `strategies.md:415`) is reconciled, not
overturned wholesale: it correctly killed an **LLM-authored** wave count as irreproducible.
This package's labeler is a different object — deterministic, unit-tested against synthetic
fixtures with known labels, with no LLM anywhere in the path — and `strategies.md:303`'s
"no deterministic wave-counting algorithm has stood up to scrutiny" remains true in the sense
that matters: this algorithm has not yet been scrutinized against real returns, because this
batch deliberately computes none. That scrutiny is the later, frozen pre-registration's job
(`2026-07-27-forex-1h-elliott-preregistration-DRAFT.md`, this PR — DRAFT, not frozen, no
`tested_cells.py` row).
