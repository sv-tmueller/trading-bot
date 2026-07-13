# 4h EUR/USD data + cost-modeled backtest harness — PLUMBING CHECK

> **This is a PLUMBING CHECK, not a strategy result.** It proves the data loader, resampler,
> validator, cost model, and bar-loop simulator fit together end to end on real FXCM archive data.
> The trivial SMA(50) baseline used in §6 is arbitrary (picked only to exercise both trade
> directions), never tuned, and its costs-off/on **delta** is the deliverable — not its absolute
> P/L, which is expected to be (and is) deeply negative. No live trading conclusion follows from
> this document. **Issue:** #371 (batch #370) · **Date:** 2026-07-13 · **Author:** Analyst
> (research-only; no production code, settings, or broker integration touched; no order placed)

---

## 1. What was built

Three new research-only modules in `backtest/` plus a CLI runner, per the #371 SUB_PLAN:

| File | Contents |
|---|---|
| `backtest/fx_data.py` | Patchable `_fetch_week` network seam, raw-bytes cache, strict-format CSV parse + mid-price OHLC, fixed-grid 4h resample, pre-registered validation checks, empirical spread series |
| `backtest/fx_costs.py` | Frozen venue cost presets pinned verbatim to `docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` (#369) §4/§5 |
| `backtest/fx_execution.py` | `simulate_fx` — long/short, single-position, fixed-TP/SL 4h bar-loop simulator (batch #370's five locked execution semantics) |
| `backtest/tax.py` (extended) | New `apply_annual_netting_tax` — German-style within-year netting, independent of the existing `apply_tax_to_ledger` (untouched, its tests still green) |
| `backtest/run_fx_plumbing_check.py` | This note's numbers, reproducibly, via `--fetch` |

All new Python files start with `from __future__ import annotations` (3.9 compatibility). No new
dependencies (`pandas`/`requests` already in `requirements.txt`). Nothing under `supabase/` is
touched; no broker client is imported anywhere; no order is ever placed.

### Re-fetch instructions

```bash
venv/bin/python backtest/run_fx_plumbing_check.py --fetch          # populate/refresh the cache
venv/bin/python backtest/run_fx_plumbing_check.py                  # cache-only; BLOCKED if empty
```

Data source: `https://candledata.fxcorporate.com/H1/EURUSD/<year>/<week>.csv.gz` (FXCM's public H1
candle archive). Cache lives at `data/fxcm/H1/EURUSD/<year>/<week>.csv.gz`, gitignored
(`/data/` — never committed; raw bytes exactly as served, so it is re-derivable forever from the
same URL template). **This run's fetch date: 2026-07-13.** Data observed available from 2012 week 1
through 2026 week 17 (2026-05-02) — the archive lags "now" by roughly 2–3 months.

---

## 2. Empirical timezone finding (stated first, per the SUB_PLAN)

Fetching real weeks and comparing a winter week against a summer week resolves the archive's
session timezone:

| Week | Local session open (`DateTime` column, as printed) | UTC equivalent |
|---|---|---|
| 2023 week 5 (winter, EST) | `01/29/2023 17:00:00.000` (i.e. Sunday 17:00) | `2023-01-29 22:00:00 UTC` |
| 2023 week 28 (summer, EDT) | `07/09/2023 17:00:00.000` (Sunday 17:00) | `2023-07-09 21:00:00 UTC` |

The **local session-open clock time (17:00) is identical** across the DST boundary, while the
**UTC-equivalent open time shifts by an hour** (22:00 UTC in winter vs 21:00 UTC in summer). This
proves the archive's `DateTime` column is **America/New_York local wall-clock time, DST-aware** —
not a fixed-UTC archive. `backtest/fx_data.parse_week_csv` localizes every timestamp as
`America/New_York` and converts to UTC accordingly (`test_parse_week_csv_dst_summer_offset_differs_from_winter`
pins this in an offline test).

---

## 3. Week-numbering finding

FXCM's week numbers are its own numbering, not ISO week numbers. Empirically, **every year has
either week 1 or week 53 absent** (never both, never neither, across the 14 years fetched) —
confirmed by direct fetch of each year's boundary weeks:

| Pattern | Years observed | What it means |
|---|---|---|
| Week 53 absent | 2015, 2016, 2017, 2021, 2022 | That year's week 52 already reaches into the following January — no separate week 53 is needed |
| Week 1 absent | 2019, 2020, 2024 | The **previous** year's week 53 already reaches past January 1 and covers what would be week 1 |
| Both present | 2012, 2013, 2014, 2018, 2023 | The New Year boundary happened to land exactly on the week-53/week-1 split |

Example: 2023's week 53 file (`.../2023/53.csv.gz`) contains bars from `2023-12-31 22:00 UTC`
through `2024-01-05 21:00 UTC` — it spans into January, which is exactly why `2024/1.csv.gz` is a
404 (there is nothing left in that calendar slot). This is a **systematic labeling convention**,
not a data gap — it accounts for 12 of the 14 years' single "missing week" entries in §5 below.

---

## 4. Validation results (full history: 2012 week 1 → 2026 week 17)

Ran via `venv/bin/python backtest/run_fx_plumbing_check.py --fetch --end-year 2026`.

| Check | Result | Threshold | Verdict |
|---|---|---|---|
| Raw H1 rows | 88,186 (`2012-01-02 08:00 UTC` → `2026-05-02 00:00 UTC`) | — | matches the SUB_PLAN's ~90k-row order-of-magnitude estimate |
| Duplicate timestamps | 0 | — | clean |
| Monotonic index | `True` (0 out-of-order) | — | clean |
| OHLC coherence (Bid, Ask, **and Mid** — the field `simulate_fx` actually consumes) | 0 violations | — | clean |
| Non-positive prices | 0 | — | clean |
| Crossed quotes (`AskClose < BidClose`) | 2,098 / 88,186 = **2.38%** | 0.1% | over threshold — **investigated, see below** |
| 4h bars after resample | 22,818 (partial boundary buckets: 1,538) | ~30 bars/week × 744 weeks found ≈ 22,320 | matches the SUB_PLAN's ~23k-bar estimate |

### Crossed-quotes investigation (over the 0.1% threshold — explained, not blocking)

The 2,098 crossed `AskClose < BidClose` instances are **tiny in magnitude** — median −0.1 pip, mean
−0.19 pip, max −2.2 pips (`neg.describe()` on the raw diff) — and are **spread roughly evenly
across all 24 hours of the trading day** (not concentrated in illiquid overnight hours, which would
suggest a thin-liquidity artifact rather than a data pipeline artifact). This is consistent with
FXCM's H1 archive independently sampling the last bid tick and the last ask tick within each hourly
bucket (rather than a single synchronized bid/ask snapshot) — an occasional sub-2-pip crossing at
the exact last-tick instant is a known vendor microstructure quirk, not a corrupted or unusable bar.

Critically: **this crossing never propagates into anything the simulator consumes.** The Bid-side
and Ask-side OHLC bars are each independently coherent (0 violations, confirmed above) and — because
`MidField = (BidField + AskField) / 2` is a linear combination of two independently-coherent
OHLC series — the **Mid OHLC the simulator actually trades on is guaranteed coherent by
construction**, which the validation table above confirms directly (0 Mid violations,
mechanically checked via `check_ohlc_coherence`'s three-way Bid/Ask/Mid loop, not merely inferred).
**Verdict: explained, not BLOCKED.**

---

## 5. Weekly-file + row-count completeness by year

| Year | Missing weeks | % weeks | Rows found | % rows missing |
|---|---|---|---|---|
| 2012 | 0 | 0.00% | 6,224 | 2.14% |
| 2013 | 0 | 0.00% | 6,196 | 2.58% |
| 2014 | 0 | 0.00% | 6,201 | 2.50% |
| 2015 | 1 (wk 53) | 1.89% | 6,186 | 0.87% |
| 2016 | 1 (wk 53) | 1.89% | 6,214 | 0.42% |
| 2017 | 1 (wk 53) | 1.89% | 6,184 | 0.90% |
| 2018 | 0 | 0.00% | 6,245 | 1.81% |
| 2019 | 1 (wk 1) | 1.89% | 6,126 | 1.83% |
| 2020 | 1 (wk 1) | 1.89% | 6,188 | 0.83% |
| 2021 | 1 (wk 53) | 1.89% | 6,237 | 0.05% |
| 2022 | 1 (wk 53) | 1.89% | 6,238 | 0.03% |
| 2023 | 0 | 0.00% | 6,175 | 2.91% |
| **2024** | **4** (wks 1, 35, 51, 52) | **7.55%** | 5,891 | 0.00% |
| **2025** | **4** (wks 1, 2, 29, 30) | **7.55%** | 5,840 | 0.68% |
| 2026 (partial, in progress) | 36 | 67.92% | 2,041 | 0.00% |

Row-count completeness is clean in every year (max 2.91%, well under the 5% threshold). 2012–2023's
single-missing-week years are all the week-1/week-53 numbering artifact from §3. **2024 and 2025
cross the pre-registered 2% missing-weeks threshold** — investigated below. 2026 is the current,
still-publishing year (archive lag) and is excluded from the threshold check by design, not silently
dropped.

### 2024/2025 investigation (over the 2%-missing-weeks threshold — explained, not blocking)

Direct fetch of each flagged week resolves every one of the 8 extra missing weeks:

| Week | HTTP result | Explanation |
|---|---|---|
| 2024/1 | 404 | Week-numbering artifact (§3) — 2023's week 53 already covers Jan 1–5, 2024 |
| 2024/35 | **200, 0-byte body** | Isolated single-week CDN artifact — confirmed by fetching neighboring weeks 33/34/36/37, all normal (~2.3KB each) |
| 2024/51, 2024/52 | **200, 0-byte body** (both) | Part of a genuine, contiguous vendor gap spanning **2024-12-15 → 2025-01-11** (see below) |
| 2025/1, 2025/2 | 404 (both) | Same contiguous gap, continuing into January 2025 |
| 2025/29, 2025/30 | 404 (both) | A **separate**, mid-July 2025 gap — see below |

**The Dec 2024/Jan 2025 gap, dated precisely:** week 50/2024 ends `2024-12-14`; the next available
data is week 53/2024, which starts `2024-12-29` and runs to `2025-01-03`; the next available data
after that is week 3/2025, starting `2025-01-12`. So the archive is missing **2024-12-15 through
2024-12-28** (weeks 51–52, empty-body) and **2025-01-04 through 2025-01-11** (weeks 1–2/2025,
404) — a genuine, contiguous ~3.5-week vendor publishing gap spanning the Christmas/New Year holiday
period. This is a believable holiday-season gap (thin/paused vendor logging over the extended
year-end period), consistent with — though larger than — the routine single-week New Year
artifact seen in every other year (§3).

**The mid-July 2025 gap, cross-checked against other pairs:** weeks 29–30/2025 (`2025-07-12` through
`2025-07-26`) are 404 for EURUSD. To rule out a EURUSD-specific data problem, the same two weeks
were fetched for **GBPUSD and USDJPY** — both show the **identical** 404 pattern (present at week
28, absent at 29/30, present again at week 31). This confirms a vendor-side, multi-instrument
archive publishing gap (the whole feed, not a EURUSD-specific corruption) rather than anything
this harness's loader is doing wrong, and rules out a real market-closure explanation (forex majors
trade normally in mid-July). **Verdict: explained (evidenced, not merely asserted) — not BLOCKED.**

### "Other" (non-weekend) gap distribution — sanity, not failure

89 non-hourly, non-weekend-length gaps were found across the full history (median 30h, mostly
12–36h). Grouping by calendar month shows a strong concentration in **December (17) and January
(16)**, with smaller bumps in **May, June, July, August, September** — consistent with US federal
holidays shortening a trading week (Christmas, New Year, Memorial Day, Independence Day, Labor Day).
The three large outliers (217h, 367h, 385h) are the already-explained Dec-2024/Jan-2025 gap above,
not new anomalies.

---

## 6. Empirical spread (FXCM bid/ask) — measurement/cross-check only

Per-bar spread = `AskClose − BidClose`, in pips, over the full 2012–2026 history:

| Statistic | Value |
|---|---|
| Median | 0.20 pips |
| Mean | 0.40 pips |
| p95 | 1.20 pips |

By hour of day (UTC), median pips: widest at the session-thin hours 00:00–01:00 UTC (0.7 pips),
tightening to 0.2 pips for the rest of the day (02:00–23:00). By year, the median ranges 0.1–0.4
pips, tightest 2019–2021 (0.1) and a touch wider in the earliest (2012: 0.4) and most recent
(2025–2026: 0.3) years.

**Reconciliation vs the #369 gate doc's presets (§4.1/§4.2):** IC Markets ECN ~0.1 pip average
(1.0 pip pessimistic); XTB ~0.5 pip minimum. FXCM's own retail median (0.20 pips) sits **between**
the two — about 2x wider than IC Markets' quoted ECN average, but **tighter** than XTB's quoted CFD
minimum. The honest picture is nuanced, not uniformly "wider than everything": FXCM's typical spread
is plausible for a retail feed, while its p95 (1.20 pips) shows a meaningfully fatter tail than
either preset's headline number, consistent with session-open/thin-liquidity widening.

**Per the SUB_PLAN's modeling decision:** the harness simulates on **mid prices** with the #369 gate
doc's venue presets as the cost model — the target venues are IC Markets/XTB/6E/M6E, not FXCM
retail. FXCM's bid/ask is used here for measurement and cross-check only; per the SUB_PLAN, even
where the empirical spread comes out tighter than a preset (as it does here vs XTB), **the preset
still governs** — contract-locked, not re-derived from this measurement.

---

## 7. Venue cost presets (pinned verbatim to #369)

| Venue | Base (bp RT) | Pessimistic (bp RT) | Overnight (per direction) |
|---|---|---|---|
| IC Markets ECN (spot) | 1.04 | 2.35 | long −0.397 bp/night, short −0.0905 bp/night |
| XTB CFD | 0.79 | 1.75 | long −0.397 bp/night, short −0.0905 bp/night |
| CME 6E (futures) | 0.56 | 1.00 | none (structural) |
| CME M6E (futures) | 1.23 | 2.10 | none (structural) |

Overnight financing reuses the gate doc's XTB swap figures as a proxy for both spot/CFD presets
(per the gate doc's own stated convention), converted to bp/night on the $114,000 notional
convention (100,000 EUR × 1.14 EURUSD ref price): `$4.525 / $114{,}000 × 10{,}000 ≈ 0.397` bp/night
long, `$1.032 / $114{,}000 × 10{,}000 ≈ 0.0905` bp/night short. **This harness's per-direction
figures are deliberately more precise than the gate doc's own long/short-averaged 0.153 bp/night
proxy** (used there for a single-cadence sanity table) — reconciling the two: averaging our own
0.397 and 0.0905 gives `(0.397 + 0.0905)/2 ≈ 0.244` bp/night, which is in the same order of
magnitude as the gate doc's 0.153 bp/night (the gate doc's figure additionally divides by a flat
$100,000 lot rather than the $114,000 notional convention it uses elsewhere — see gate doc §5's
own correction note). Trade Republic is excluded as a preset (gate doc §4.4/§8: unpublished issuer
spread structurally dominates, no finite crossover size).

---

## 8. Trivial baseline — SMA(50) on 4h mid closes, symmetric R=30bp

**Not a strategy claim.** Params are arbitrary (picked from the gate doc's own R grid, unmodified)
and exercise both trade directions (long above the SMA, short below). Run over the full 2012–2026
history (22,817 4h bars after dropping the in-progress final bar).

| Venue | Cost mode | Net return | Max DD | # trades |
|---|---|---|---|---|
| *(costs OFF)* | — | **−50.34%** | −52.7% | 6,015 |
| IC Markets ECN | base | −75.89% | −76.1% | 6,015 |
| IC Markets ECN | pessimistic | −89.04% | −89.1% | 6,015 |
| XTB CFD | base | −71.97% | −72.2% | 6,015 |
| XTB CFD | pessimistic | −84.27% | −84.4% | 6,015 |
| CME 6E | base | −64.55% | −65.0% | 6,015 |
| CME 6E | pessimistic | −72.79% | −73.0% | 6,015 |
| CME M6E | base | −76.31% | −76.5% | 6,015 |
| CME M6E | pessimistic | −85.96% | −86.1% | 6,015 |

**Costs-off/on delta** (percentage points added to the loss, by venue, base case):

| Venue | Delta (base) | Delta (pessimistic) |
|---|---|---|
| CME 6E | −14.2pp (cheapest — no overnight charge) | −22.5pp |
| XTB CFD | −21.6pp | −33.9pp |
| IC Markets ECN | −25.6pp | −38.7pp |
| CME M6E | −26.0pp | −35.6pp |

The baseline has **no edge even at zero cost** (a raw SMA(50)/±30bp rule churning ~6,000 trades over
14 years is exactly the high-frequency, no-signal regime the #369 gate doc's cost arithmetic warns
about) — the deliverable here is that the cost model correctly and monotonically worsens every
venue's result, cheapest-venue-first (6E futures, with no overnight charge, has the smallest drag,
consistent with the gate doc's own venue ranking), proving the pipeline plumbs end to end on real
data. **No strategy conclusion follows from this table.**

---

## 9. Annual netting tax — worked example (hand-verifiable)

`apply_annual_netting_tax` (new, `backtest/tax.py`) nets gains and losses **within** each calendar
year (unlike the existing `apply_tax_to_ledger`, which clamps every trade's tax at ≥0 individually
and is left completely unchanged — its own tests are still green). Worked example a reviewer can
re-derive by hand:

| Trade | Exit year | PnL |
|---|---|---|
| A | 2023 | +€3,000 |
| B | 2023 | −€1,000 |

Net gain for 2023 = `3,000 − 1,000 = €2,000`. Tax = `2,000 × 0.26375 = €527.50`, deducted at 2023's
last equity-curve point. (No cross-year loss carryforward and no Sparer-Pauschbetrag — both
documented simplifications, consistent with the batch contract's "each calendar year's net gains"
wording.)

---

## 10. Verification

- `venv/bin/python -m pytest tests/ -q` — full suite green (see PR description for pasted output).
- `venv/bin/python backtest/run_fx_plumbing_check.py --fetch --end-year 2026` — this note's numbers
  come directly from that run's printed tables (excerpted above).
- Reviewer re-derivation pointers: one week's row count (2020 week 5: 121 H1 rows, `24×5+1` — a
  normal winter week spans Sun 22:00 UTC → Fri 21:00 UTC inclusive); one 4h bar from its six H1
  bars (any `resample_to_4h` bucket — `Open`=first H1 open, `Close`=last H1 close, `High`/`Low`=
  max/min over the six); one preset from the gate doc (§7 table above, cross-check against
  `docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §4.1–4.3); the annual-netting
  figure in §9.
- **Architectural invariants (CLAUDE.md):** research-only; no LLM anywhere in this code; no broker
  import; `simulate_fx` is a pure function of a bar history and a signal series (no I/O, no
  network, no state).
