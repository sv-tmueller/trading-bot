# 4h EUR/USD strategy survey — verdict

**Result of executing the frozen pre-registration** (`docs/research/2026-07-13-forex-4h-strategy-preregistration.md`,
freeze SHA `e409bf8`) against the real, pinned FXCM cache and real SPY history. Batch #378, issue #379.

**Status: CLASS KILL.** All 33 pre-registered (family, shape, R) cells were evaluated in full. Zero
cells satisfy the spec §6 survivor definition, at either co-primary preset, under the primary tax
mode. This is an unambiguous, non-marginal result: the best-performing cell across every cost row
and both tax modes reaches a median after-tax Calmar of 0.337 — nowhere close to SPY buy-and-hold's
1.309 median after-tax Calmar over the same windows (Table 6.1, Appendix). No cell clears the §6
condition 1 median-Calmar-vs-SPY bar under any cost preset or tax mode tested. This is a genuine
honest negative, not a "promising direction" dressed up as one: the 4h EUR/USD candidate class, as
pre-registered, has no demonstrated edge on this data.

---

## 1. Cache + input assumptions

| Input | Value |
|---|---|
| FXCM H1 EUR/USD cache | `data/fxcm/H1/EURUSD/` — 744 weekly files, 2012 week 1 → 2026 week 17 |
| Cache identity hash (`find ... \| sort \| xargs shasum -a 256 \| shasum -a 256`) | `32d1e4f36888924c63cf08bee0269663cb0aef03052375c1ed33a4d23d856e2b` |
| Cache fetch date | 2026-07-13 (per batch #378 pre-flight facts; NOT refreshed for this run — pinned, per SUB_PLAN §4) |
| Spread input (`--spread-pips`) | **0.20 pips** — the measured FXCM median spread from the merged #374 note (§6: "Median 0.20 pips"), passed explicitly on the CLI (not a buried constant) |
| SPY source | `yfinance`, `auto_adjust=True`, ticker `SPY` |
| SPY fetch date | 2026-07-15 (this run) |
| SPY span fetched | 2012-10-01 → 2026-05-01 (span of the FX survey's pre-roll-to-test-end windows) |
| SPY sample adjusted closes (drift diagnosis) | 2012-10-01: 113.83; 2012-10-03: 114.41; 2026-05-01: 718.80 |
| Tax modes | `annual_netting` (German calendar-year netting) — **primary**; `de_sensitivity` (no-loss-credit deduct-at-exit) — sensitivity only, never a survivor basis |
| Co-primary cost presets | XTB CFD base (0.79 bp) **and** CME 6E futures base (0.56 bp) — a survivor must clear the bar on **both** |
| JSON artifact | `data/fx_survey/2026-07-15-full-run.json` (gitignored, not committed) |
| JSON sha256 | `7ee39ccf666e9f283c4f53afd52dbefabfd3a4916aa1b603b0c7d63b0cd1cd1e` |

---

## 2. Data validation + adjudicated crossings

`prepare_history(fetch=False, end_year=2026, adjudicated_reasons=ADJUDICATED_CROSSINGS)` ran the
full #371 validation gate. Exactly the three crossings pre-adjudicated (BLIND, before any strategy
result existed) in the merged #374 note (`docs/research/2026-07-13-fx-4h-harness-plumbing-check.md`)
fired, and only those three — no unforeseen fourth gate reason (the one scope risk SUB_PLAN §10
flagged):

| Label | Reason (exact string, matched against the whitelist) | #374 note reference |
|---|---|---|
| 2024 | `missing weeks 7.55% > 2.00%` | §5, "2024/2025 investigation" — Dec-2024/Jan-2025 vendor gap (weeks 51, 52/2024 + 1, 2/2025), cross-checked against GBPUSD/USDJPY, confirmed vendor-side, not a EUR/USD-specific defect |
| 2025 | `missing weeks 7.55% > 2.00%` | §5, same section — mid-July 2025 vendor gap (weeks 29, 30/2025), independently confirmed across three pairs |
| all | `crossed-quotes rate 2.3791% > 0.100%` | §4, "Crossed-quotes investigation" — a vendor microstructure quirk (independent last-bid/last-ask tick sampling per hourly bucket), concentrated in peak session hours (ruling out a thin-liquidity artifact); never propagates into the Mid OHLC the simulator trades on (Mid is a linear combination of two independently-coherent Bid/Ask series, guaranteed coherent by construction) |

Because these are exact-string, cache-pinned matches, a drifted or refreshed cache would have
changed the percentages and re-BLOCKed on an unmatched reason — the whitelist doubled as a
cache-integrity check, and it passed.

**Saturday-UTC carve-out:** 73 rows dropped (0.083% of 88,186 raw H1 rows), unconditionally, before
resampling to 4h. This includes the 2 outlier "bad prints" the #374 note flagged as not benign
(2023-12-16 14:00 UTC, 99.0-pip range; 2025-08-30 20:00 UTC, 23.1-pip range) — both timestamps fall
on a Saturday, so both are removed by the unconditional carve-out before the 4h series the
simulator consumes is ever built. The note's own "open item for the survey batch" (exclude or
winsorize these two prints) is therefore already satisfied by the pipeline's frozen order of
operations (Saturday carve-out **before** resample), with no special-casing needed.

**Duplicates:** 0 duplicate H1 timestamps.

**Completeness by year** (missing-weeks / rows-missing, unaffected by the crossings above except
2024/2025 which cross the missing-weeks threshold as adjudicated):

| Year | Missing weeks | % weeks | Rows found | % rows missing |
|---|---|---|---|---|
| 2012 | 0 | 0.00% | 6,224 | 2.14% |
| 2013 | 0 | 0.00% | 6,196 | 2.58% |
| 2014 | 0 | 0.00% | 6,201 | 2.50% |
| 2015 | 1 | 1.89% | 6,186 | 0.87% |
| 2016 | 1 | 1.89% | 6,214 | 0.42% |
| 2017 | 1 | 1.89% | 6,184 | 0.90% |
| 2018 | 0 | 0.00% | 6,245 | 1.81% |
| 2019 | 1 | 1.89% | 6,126 | 1.83% |
| 2020 | 1 | 1.89% | 6,188 | 0.83% |
| 2021 | 1 | 1.89% | 6,237 | 0.05% |
| 2022 | 1 | 1.89% | 6,238 | 0.03% |
| 2023 | 0 | 0.00% | 6,175 | 2.91% |
| **2024** | **4** | **7.55%** | 5,891 | 0.00% |
| **2025** | **4** | **7.55%** | 5,840 | 0.68% |
| 2026 (partial, excluded from the gate) | 36 | 67.92% | 2,041 | 0.00% |

## 3. Data-shape actuals vs SUB_PLAN's expected sanity check

| Metric | Expected (SUB_PLAN §2) | Actual | Match |
|---|---|---|---|
| `history_rows` | 88,186 | 88,186 | exact |
| `n_saturday_dropped` | 73 | 73 | exact |
| `bars_4h_len` | "slightly under 22,810" | 22,772 | under, as expected (post drop-in-progress-bar on this run's exact end-of-cache boundary, `2026-05-01 16:00 UTC`) |
| `n_duplicates` | (not estimated) | 0 | — |
| Windows generated | ~13–14 | 14 (2013–2026; 13 scored, 2026 unscored per ND1) | exact |

---

## 4. Window coverage + skip/gap table

No window was skipped for insufficient bars (every FX window has ≥ 2 pre-roll and ≥ 2 test bars;
`skipped: False` for all 14 rows, identically across every cell — this is a per-window, not
per-cell, property). Nominal full-year 4h bar count is ~1,560–1,612 depending on leap-year/weekend
placement; the two vendor gaps documented in §2 visibly reduce the 2024 and 2025 test-window bar
counts below the surrounding years' range, exactly as flagged in the #374 note as "an open item for
the survey batch to account for, not silently interpolate across":

| Year | Scored | `n_pre_roll_bars` | `n_test_bars` (nominal ~1,560–1,612) | Note |
|---|---|---|---|---|
| 2013 | Yes | 1,902 | 1,602 | |
| 2014 | Yes | 1,903 | 1,603 | |
| 2015 | Yes | 1,898 | 1,598 | |
| 2016 | Yes | 1,905 | 1,605 | |
| 2017 | Yes | 1,897 | 1,597 | |
| 2018 | Yes | 1,898 | 1,598 | |
| 2019 | Yes | 1,890 | 1,590 | |
| 2020 | Yes | 1,909 | 1,609 | |
| 2021 | Yes | 1,911 | 1,611 | |
| 2022 | Yes | 1,912 | 1,612 | |
| 2023 | Yes | 1,874 | 1,574 | |
| **2024** | Yes | 1,824 | **1,524** | reduced by the Dec-2024/Jan-2025 vendor gap |
| **2025** | Yes | 1,809 | **1,509** | reduced by the mid-July-2025 vendor gap (+ tail of the Dec/Jan gap) |
| 2026 | **No** (ND1) | 831 | 531 | partial trailing year, reported as unscored coverage, never fed into any survivor statistic |

(Bar counts shown for cell `T1_sma_5_20_R20`; identical across all 33 cells x 9 cost rows x 2 tax
modes, since `n_pre_roll_bars`/`n_test_bars` are properties of the window and the prepared `bars_4h`
series, not of the candidate signal or cost/tax parameters.)

---

## 5. The frozen threshold, quoted verbatim (before any result)

> **Survivor.** A single (family, shape, R) cell is a survivor if and only if, at **both** co-primary
> presets (XTB CFD base and 6E futures base, §5) and under the primary tax mode (German annual-
> netting), all three of the following hold simultaneously:
>
> 1. Its **median-window** after-tax Calmar ratio exceeds SPY buy-and-hold's median-window after-tax
>    Calmar ratio on the same calendar windows.
> 2. It beats all four dumb baselines (§5) on the same statistic (median-window after-tax Calmar,
>    with baseline 1's always-flat criterion applied as stated: median-window return > 0).
>    **Baseline-4 degenerate-window convention:** in any window where baseline 4 (200-SMA regime) is
>    flat for the entire window — no position held throughout, hence trade count zero and an
>    undefined 0/0 Calmar ratio — that window's baseline-4 return is treated as exactly 0 for the
>    comparison, mirroring baseline 1's "median return > 0" convention rather than discarding the
>    window or its test.
> 3. Its **worst-window** total return, after costs and tax, is positive (> 0) — the multiplicity
>    control from §5's verbatim rule ("stay positive on worst window").
>
> **Family kill.** If no combo within a family (15 cells for Trend, 9 for Momentum, 9 for
> Mean-reversion) satisfies the survivor definition, that family is dead — it does not proceed to
> any further stage on this evidence.
>
> **Class kill (the "stop" pattern).** The entire 4h EUR/USD candidate class is dead if **either**:
> (a) none of the 33 cells satisfies the survivor definition, **or** (b) every cell that clears the
> median criterion (survivor conditions 1–2) nonetheless fails on the worst-window criterion
> (condition 3) — i.e. the class only ever looks good on the median statistic and never survives its
> own worst window. Consequence, stated in advance: **this class of 4h EUR/USD trading has no
> demonstrated edge; do not proceed to an FX-system ADR; the colleague-audit path stays available
> only if he shares his actual rules or a broker trade export.**

> **Multiplicity rule, quoted verbatim from batch #370's contract item 5:**
>
> "≤ ~20 frozen combos per family; judged on median AND worst walk-forward window (never
> best-cell); every cell reported including failures; a survivor must clear the bar on median and
> stay positive on worst window."

---

## 6. Main tables (primary tax = `annual_netting`, all 33 cells, frozen cell-ID order)

SPY buy-and-hold's median-window after-tax Calmar (the bar every cell is measured against):
**1.3085475049604838** (n = 13 scored windows, 2013–2025).

| Cell ID | XTB median Calmar | XTB worst-window return | 6E median Calmar | 6E worst-window return | Cond. 1 | Cond. 2 | Cond. 3 | Survivor |
|---|---|---|---|---|---|---|---|---|
| T1_sma_5_20_R20 | -0.616 | -7.28% | -0.512 | -6.98% | False | False | False | **No** |
| T1_sma_5_20_R30 | -0.262 | -6.87% | -0.187 | -6.53% | False | False | False | **No** |
| T1_sma_5_20_R50 | -0.412 | -9.00% | -0.343 | -8.62% | False | False | False | **No** |
| T1_sma_20_50_R20 | -0.282 | -2.70% | -0.224 | -2.59% | False | False | False | **No** |
| T1_sma_20_50_R30 | -0.147 | -4.46% | -0.087 | -4.31% | False | False | False | **No** |
| T1_sma_20_50_R50 | -0.063 | -4.23% | -0.027 | -3.92% | False | False | False | **No** |
| T1_sma_50_200_R20 | -0.482 | -2.13% | -0.415 | -2.08% | False | False | False | **No** |
| T1_sma_50_200_R30 | -0.507 | -3.41% | -0.450 | -3.35% | False | False | False | **No** |
| T1_sma_50_200_R50 | 0.200 | -4.60% | 0.316 | -4.51% | False | **True** | False | **No** |
| T2_donchian_20_R20 | -0.788 | -8.37% | -0.744 | -7.95% | False | False | False | **No** |
| T2_donchian_20_R30 | -0.604 | -10.43% | -0.552 | -9.96% | False | False | False | **No** |
| T2_donchian_20_R50 | -0.521 | -8.80% | -0.450 | -8.22% | False | False | False | **No** |
| T2_donchian_55_R20 | -0.638 | -5.39% | -0.503 | -5.14% | False | False | False | **No** |
| T2_donchian_55_R30 | -0.545 | -4.32% | -0.500 | -3.96% | False | False | False | **No** |
| T2_donchian_55_R50 | -0.481 | -5.38% | -0.455 | -4.83% | False | False | False | **No** |
| M1_roc_12_R20 | -0.931 | -32.89% | -0.918 | -30.82% | False | False | False | **No** |
| M1_roc_12_R30 | -0.822 | -23.14% | -0.773 | -21.72% | False | False | False | **No** |
| M1_roc_12_R50 | -0.557 | -16.10% | -0.495 | -14.97% | False | False | False | **No** |
| M1_roc_24_R20 | -0.955 | -30.75% | -0.929 | -28.63% | False | False | False | **No** |
| M1_roc_24_R30 | -0.727 | -17.71% | -0.596 | -16.17% | False | False | False | **No** |
| M1_roc_24_R50 | -0.599 | -12.46% | -0.506 | -11.33% | False | False | False | **No** |
| M1_roc_48_R20 | -0.965 | -31.70% | -0.953 | -29.61% | False | False | False | **No** |
| M1_roc_48_R30 | -0.828 | -20.40% | -0.766 | -18.91% | False | False | False | **No** |
| M1_roc_48_R50 | -0.551 | -12.58% | -0.509 | -11.14% | False | False | False | **No** |
| R1_rsi_14_R20 | -0.574 | -6.73% | -0.524 | -6.27% | False | False | False | **No** |
| R1_rsi_14_R30 | 0.053 | -6.43% | 0.156 | -6.00% | False | **True** | False | **No** |
| R1_rsi_14_R50 | -0.087 | -7.51% | -0.014 | -7.13% | False | False | False | **No** |
| R2_rsi_2_R20 | -0.759 | -11.64% | -0.699 | -10.65% | False | False | False | **No** |
| R2_rsi_2_R30 | -0.488 | -10.74% | -0.383 | -9.80% | False | False | False | **No** |
| R2_rsi_2_R50 | -0.492 | -9.19% | -0.424 | -8.18% | False | False | False | **No** |
| R3_boll_20_2_R20 | -0.679 | -9.09% | -0.593 | -8.68% | False | False | False | **No** |
| R3_boll_20_2_R30 | -0.312 | -7.41% | -0.025 | -6.99% | False | False | False | **No** |
| R3_boll_20_2_R50 | -0.214 | -6.59% | -0.142 | -5.98% | False | False | False | **No** |

**No cherry-picking, no reordering by performance** — the table above is in the frozen cell-ID
order emitted by `fx_signals.build_cells()` (shape-major, R-minor within shape), exactly as pre-
registered in spec §3/§4.

Zero of 33 cells satisfy condition 1 (beat SPY's median Calmar) at both co-primary venues
simultaneously. Two cells (`T1_sma_50_200_R50`, `R1_rsi_14_R30`) clear condition 2 (beats all four
dumb baselines) at both venues, but neither is close on condition 1, and both fail condition 3
(negative worst-window return at both venues) regardless. No cell is a survivor.

---

## 7. Baselines + SPY bar

**Baseline 1 (always-flat), applied as the median-return > 0 criterion** — not a simulated baseline;
this is `median_total_return` from the "Cond. 2" evaluation above (a candidate whose own
median-window total return is ≤ 0 already fails condition 2 regardless of the other three
baselines).

**Baselines 2–4 (simulated, state-based, no TP/SL), primary tax mode, co-primary venues** (n = 13
scored windows each; the baseline-4 degenerate-window convention — flat-whole-window return/Calmar
treated as exactly 0 — is defined but was **not triggered** on this run: no `sma200_regime` window
had zero trades):

| Baseline | Venue | Median Calmar | Median total return | Worst-window return |
|---|---|---|---|---|
| EUR/USD buy-and-hold | XTB base | -0.459 | -4.80% | -13.62% |
| EUR/USD buy-and-hold | 6E base | -0.354 | -3.03% | -11.89% |
| Persistence | XTB base | -0.856 | -14.26% | -18.45% |
| Persistence | 6E base | -0.792 | -11.89% | -16.18% |
| 200-SMA regime | XTB base | -0.411 | -3.36% | -12.59% |
| 200-SMA regime | 6E base | -0.354 | -2.70% | -11.84% |

**SPY buy-and-hold, after-tax (annual_netting), per calendar window** (source of the §6 "bar";
median = **1.3085475049604838**, the frozen digest value in the JSON. A reporting-only recomputation
of the per-window breakdown below, refetched from `yfinance` on 2026-07-15 for this table, reproduces
the median to **1.3085323112253744** — a relative difference of ~1.2e-5, consistent with the
`auto_adjust`-rescaling micro-revisions `yfinance`/Yahoo routinely applies between two fetches minutes
apart, not a data-quality concern; the frozen JSON value above is the one THE ONE RUN actually
computed and is the reported result):

| Year | After-tax Calmar | Total return |
|---|---|---|
| 2013 | 3.273 | 20.37% |
| 2014 | 1.309 | 9.45% |
| 2015 | -0.041 | -0.48% |
| 2016 | 1.153 | 10.46% |
| 2017 | 2.188 | 13.67% |
| 2018 | -0.278 | -5.34% |
| 2019 | 3.816 | 25.03% |
| 2020 | 0.309 | 10.37% |
| 2021 | 2.444 | 20.21% |
| 2022 | -0.773 | -18.66% |
| 2023 | 1.998 | 19.56% |
| 2024 | 1.477 | 15.79% |
| 2025 | 0.695 | 12.93% |
| 2026 (unscored, ND1) | 1.691 | 7.65% |

---

## 8. Mechanical §6 outcome

**Class kill, reason (a): no cell clears the median criterion.**

`class_kill(survivor_results) = {"class_dead": True, "reason": "a_no_cell_clears_median"}`. Zero of
the 33 cells satisfy condition 1 (median-window after-tax Calmar > SPY's, at both co-primary venues)
— the necessary first gate for any survivor. This is reason (a), not (b): it is not the case that
cells clear the median bar but then fail on the worst window; **no cell clears the median bar at
all.**

Per the spec's own stop consequence, quoted verbatim (§6):

> "this class of 4h EUR/USD trading has no demonstrated edge; do not proceed to an FX-system ADR;
> the colleague-audit path stays available only if he shares his actual rules or a broker trade
> export."

All three families are dead individually as well: `family_kills = {"T": True, "M": True, "R": True}`
— Trend (15 cells), Momentum (9 cells), and Mean-reversion (9 cells) each have zero survivors.

No survivor exists, so the §6 "No second live rule" / multiplicity clauses do not apply here — there
is no candidate to weigh against them. The live bot's Architectural invariant #1 (one decision rule)
is unaffected; nothing in this result touches it.

---

## 9. Reconciliation

- **Freeze SHA:** `e409bf8`. `git diff e409bf8..HEAD -- docs/research/2026-07-13-forex-4h-strategy-preregistration.md` is empty — the frozen spec is byte-untouched by this batch.
- **Zero-frozen-changes proof:** this PR's diff touches only `backtest/run_fx_survey.py` (the `--full` CLI path), `backtest/fx_survey.py` (the two carried nits + the ND-A `adjudicated_reasons` parameter), `tests/` (new offline tests), and this doc. `fx_signals.py`, `fx_baselines.py`, `fx_execution.py`, `fx_costs.py`, `fx_data.py`, and the frozen spec are byte-untouched.
- **Repro command:**
  ```
  REQUESTS_CA_BUNDLE=/etc/ssl/cert.pem venv/bin/python -m backtest.run_fx_survey --full \
      --spread-pips 0.20 --end-year 2026 --json data/fx_survey/2026-07-15-full-run.json
  ```
- **Execution log:**

  | # | Timestamp (approx, this session) | Invocation | Outcome |
  |---|---|---|---|
  | 1 | 2026-07-15, pre-flight | `prepare_history(fetch=False, end_year=2026, adjudicated_reasons=ADJUDICATED_CROSSINGS)` only (no `run_survey` — not a scoring execution) | Succeeded; confirmed exactly the 3 pre-adjudicated crossings fire and no unforeseen 4th BLOCKED reason exists, before committing to THE ONE RUN |
  | 2 | 2026-07-15 | **THE ONE RUN** — `venv/bin/python -m backtest.run_fx_survey --full --spread-pips 0.20 --end-year 2026 --json data/fx_survey/2026-07-15-full-run.json` | Succeeded on the first and only invocation. Exit 0. stdout log preserved (`data/fx_survey/2026-07-15-full-run-stdout.log`, gitignored). Zero crashes, zero BLOCKED, zero re-runs. |

  **Exactly one scoring execution** (an invocation producing candidate-cell results on real data)
  occurred: run #2. Run #1 is a data-validation-only pre-flight (`prepare_history` alone, no
  `run_survey` call) explicitly anticipated by SUB_PLAN §10's scope-risk note, not a scoring run, and
  is not counted against the one-run discipline. No re-run occurred after run #2 completed; no
  harness defect was suspected or found post-completion.

---

## Appendix — sensitivity (never a survivor basis)

Robustness check across every cost row and both tax modes, to show the class kill is not an
artifact of the co-primary base-cost/primary-tax choice: the single best (cell, cost-row) pair
across **all** 33 cells x all 9 cost rows x `annual_netting` is `T1_sma_50_200_R50` on the FXCM
measured-spread reconciliation row (the cheapest cost input tested), median Calmar **0.337** — still
far short of SPY's 1.309. Zero of 33 cells beat SPY's median Calmar under **any** cost row or tax
mode tested below.

| Cost row / tax mode | Best cell | Median Calmar | Worst-window return | Cells beating SPY |
|---|---|---|---|---|
| XTB CFD pessimistic (`annual_netting`) | T1_sma_50_200_R50 | 0.151 | -4.76% | 0/33 |
| CME 6E pessimistic (`annual_netting`) | T1_sma_50_200_R50 | 0.292 | -4.58% | 0/33 |
| IC Markets ECN base (`annual_netting`, sensitivity) | T1_sma_50_200_R50 | 0.187 | -4.65% | 0/33 |
| IC Markets ECN pessimistic (`annual_netting`, sensitivity) | T1_sma_50_200_R50 | 0.122 | -4.86% | 0/33 |
| CME M6E base (`annual_netting`, sensitivity) | T1_sma_50_200_R50 | 0.280 | -4.62% | 0/33 |
| CME M6E pessimistic (`annual_netting`, sensitivity) | T1_sma_50_200_R50 | 0.234 | -4.76% | 0/33 |
| FXCM measured-spread reconciliation row (`annual_netting`) | T1_sma_50_200_R50 | 0.337 | -4.45% | 0/33 |
| XTB CFD base (`de_sensitivity` tax mode) | T1_sma_50_200_R50 | -0.154 | -5.11% | 0/33 |
| CME 6E base (`de_sensitivity` tax mode) | T1_sma_50_200_R50 | -0.060 | -5.02% | 0/33 |

`de_sensitivity` (the no-loss-credit deduct-at-exit tax model) and every non-co-primary cost row
above are sensitivity only, never a survivor basis (spec §5) — reported here purely to demonstrate
robustness of the class-kill conclusion.
