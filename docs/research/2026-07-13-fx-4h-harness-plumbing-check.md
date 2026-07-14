# 4h EUR/USD data + cost-modeled backtest harness — PLUMBING CHECK

> **This is a PLUMBING CHECK, not a strategy result.** It proves the data loader, resampler,
> validator, cost model, and bar-loop simulator fit together end to end on real FXCM archive data.
> The trivial SMA(50) baseline used in §8 is arbitrary (picked only to exercise both trade
> directions), never tuned, and its costs-off/on **delta** is the deliverable — not its absolute
> P/L, which is expected to be (and is) deeply negative. No live trading conclusion follows from
> this document. **Issue:** #371 (batch #370) · **Date:** 2026-07-13, corrected 2026-07-14 (PR #374
> reviewer round-1 must-fix 1) · **Author:** Analyst (research-only; no production code, settings,
> or broker integration touched; no order placed)

> **Correction notice (2026-07-14):** the original 2026-07-13 version of this note wrongly stated
> the archive's `DateTime` column was America/New_York local time, DST-aware. It is **UTC**. The
> wrong localization shifted 14 years of bars +4h/+5h, producing 1,312 impossible Saturday-UTC bars
> and mislabeling every hour-of-day statistic below. §2, the Saturday-bar validation check, §4/§4b
> (crossed-quotes hour distribution), §6 (spread by hour), §8 (baseline numbers), and the
> re-derivation pointers in §10 are all regenerated in this version from a corrected re-run against
> the same cached archive; see PR #374 for the full review thread.

---

## 1. What was built

Three new research-only modules in `backtest/` plus a CLI runner, per the #371 SUB_PLAN:

| File | Contents |
|---|---|
| `backtest/fx_data.py` | Patchable `_fetch_week` network seam, raw-bytes cache, strict-format CSV parse + mid-price OHLC, fixed-grid 4h resample, pre-registered validation checks (including `check_weekend_bars`, added in the fix round), empirical spread series |
| `backtest/fx_costs.py` | Frozen venue cost presets pinned verbatim to `docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` (#369) §4/§5 |
| `backtest/fx_execution.py` | `simulate_fx` — long/short, single-position, fixed-TP/SL 4h bar-loop simulator (batch #370's five locked execution semantics) |
| `backtest/tax.py` (extended) | New `apply_annual_netting_tax` — German-style within-year netting, independent of the existing `apply_tax_to_ledger` (untouched, its tests still green) |
| `backtest/run_fx_plumbing_check.py` | This note's numbers, reproducibly, via `--fetch`; `--help` surfaces the re-fetch instructions (argparse `description=`/`epilog=`) |

All new Python files start with `from __future__ import annotations` (3.9 compatibility). No new
dependencies (`pandas`/`requests` already in `requirements.txt`). Nothing under `supabase/` is
touched; no broker client is imported anywhere; no order is ever placed.

### Re-fetch instructions

```bash
venv/bin/python backtest/run_fx_plumbing_check.py --fetch          # populate/refresh the cache
venv/bin/python backtest/run_fx_plumbing_check.py                  # cache-only; BLOCKED if empty
venv/bin/python backtest/run_fx_plumbing_check.py --help           # re-fetch instructions surfaced here too
```

Data source: `https://candledata.fxcorporate.com/H1/EURUSD/<year>/<week>.csv.gz` (FXCM's public H1
candle archive). Cache lives at `data/fxcm/H1/EURUSD/<year>/<week>.csv.gz`, gitignored
(`/data/` — never committed; raw bytes exactly as served, so it is re-derivable forever from the
same URL template). **Original fetch date: 2026-07-13** (data observed available from 2012 week 1
through 2026 week 17 / 2026-05-02 — the archive lags "now" by roughly 2–3 months). **This
correction's re-run: 2026-07-14, cache-only, same cache** (no re-fetch needed — the correction is
in the parsing, not the raw bytes).

---

## 2. Empirical timezone finding — CORRECTED (stated first, per the SUB_PLAN)

The original version of this note misread the evidence. Re-examining the **raw cached bytes**
directly (not the parsed/localized output) for the same two weeks:

```
$ zcat data/fxcm/H1/EURUSD/2023/5.csv.gz | head -2
DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose
01/29/2023 22:00:00.000,1.08644,1.08662,1.08586,1.08662,1.08701,1.08701,1.08606,1.08672

$ zcat data/fxcm/H1/EURUSD/2023/28.csv.gz | head -2
DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose
07/09/2023 21:00:00.000,1.097,1.097,1.0958,1.0964,1.09735,1.09735,1.09627,1.09689
```

| Week | Raw `DateTime` (as printed, verbatim, no conversion applied yet) | Day |
|---|---|---|
| 2023 week 5 (winter) | `01/29/2023 22:00:00.000` | Sunday |
| 2023 week 28 (summer) | `07/09/2023 21:00:00.000` | Sunday |

The raw column itself reads **22:00 in winter and 21:00 in summer** — not a constant 17:00 in both
seasons. A genuinely America/New_York-local archive would print the *same* local clock time
(17:00) year-round regardless of DST; it does not. What *does* stay constant is the **UTC**
interpretation: 17:00 EST = 22:00 UTC, and 17:00 EDT = 21:00 UTC — exactly the two raw values
above. **The `DateTime` column is already UTC.** `backtest/fx_data.parse_week_csv` now localizes
directly via `tz_localize("UTC")`, applying **no** DST-aware conversion
(`test_parse_week_csv_winter_and_summer_opens_are_both_utc_verbatim` pins this in an offline test).

The previous (wrong) `tz_localize("America/New_York")` took these already-UTC values and shifted
them a further +5h (winter) / +4h (summer), landing the same rows on Monday instead of Sunday and,
for other rows within each week, spilling some onto an impossible Saturday.

### Mechanical "zero Saturday bars" check (new; would have caught this bug)

`fx_data.check_weekend_bars` counts bars landing on Saturday (should be exactly 0 — FX is closed
globally Friday ~21-22:00 UTC through Sunday ~21-22:00 UTC) and on Sunday (session-open bars,
should be > 0), and is wired into `run_fx_plumbing_check.py`'s `blocked_reasons` via the new
`evaluate_blocked_reasons` pure helper. Re-running against the full corrected history:

- **Saturday-UTC bars: 73** (out of 88,186 rows, 0.083%) — down from what the wrong localization
  would have produced (~1,312, ~1.5%), but not zero. **Mechanical gate fires; investigated below.**
- **Sunday-UTC bars: 1,945** (session-open bars — expected and clean).

**Investigation (73 residual Saturday bars across 27 affected weeks — explained, not blocking):**
these are NOT the timezone bug (which would produce a large, systematic, constant-offset population
across every year 2012–2026); instead they appear in only 4 years (2023: 1, **2024: 43**, **2025:
28**, 2026: 1) and, within an affected week, are always trailing rows of that week's file. Rows per
affected week (all 27, computed directly from the cache — `data/fxcm/H1/EURUSD/`, grouped by
weekly file):

| Trailing rows | Weeks |
|---|---|
| 1 | 5 |
| 2 | 8 |
| 3 | 9 |
| 4 | 2 |
| 5 | 2 |
| 7 | 1 |
| **Total** | **27 weeks, 73 rows** |

The five weeks trailing 4 or more rows, with their UTC span:

| Week | Rows | UTC span |
|---|---|---|
| 2024 week 32 | 4 | `2024-08-10 08:00` → `16:00` |
| 2025 week 20 | 5 | `2025-05-17 17:00` → `21:00` |
| 2025 week 31 | 7 | `2025-08-02 08:00` → `21:00` |
| 2025 week 33 | 4 | `2025-08-16 12:00` → `18:00` |
| 2025 week 34 | 5 | `2025-08-23 08:00` → `17:00` |

Most weeks trail 1–3 rows (22 of 27, per the histogram above); the five weeks above trail 4–7, and
of those five, four (2025 weeks 20, 31, 33, 34) reach into 17:00–21:00 UTC Saturday — see the
table; 2024 week 32 is the exception, ending earlier at 16:00 UTC. Example of the common (1-3 row)
case, verified against the raw bytes (`data/fxcm/H1/EURUSD/2024/11.csv.gz`, tail):

```
03/15/2024 20:00:00.000,1.08893,1.08901,1.0886,1.08875,1.08894,1.08905,1.08868,1.08891
03/16/2024 09:00:00.000,1.08875,1.08875,1.08874,1.08875,1.08891,1.08892,1.08891,1.08891
03/16/2024 10:00:00.000,1.08875,1.08875,1.08874,1.08875,1.08891,1.08892,1.08891,1.08891
```

The normal Friday-close bar (`2024-03-15 20:00 UTC`) is followed directly by two Saturday rows,
not by the expected Sunday reopen. This is consistent with an FXCM archive **weekly-file
boundary/batching quirk** concentrated in 2024–2025 (the same two years already flagged in §5 for
missing weeks — this harness's cached archive shows independent evidence of vendor data-quality
degradation in that window from two unrelated checks), not a code defect: OHLC coherence on these
rows is 0 violations (checked identically to every other row) and the magnitude is tiny overall
(0.083% of all rows).

**Two outlier prints (NOT benign — surfaced explicitly, not glossed over):** of the 73 Saturday
bars, 71 have a market-plausible intra-hour mid range (`MidHigh − MidLow`), median **0.10 pips**.
The remaining 2 are market-implausible one-hour price jumps:

| Timestamp (UTC) | Mid Open | Mid High | Mid Low | Mid Close | Mid range (pips) |
|---|---|---|---|---|---|
| 2023-12-16 14:00 | 1.089425 | 1.099325 | 1.089425 | 1.099325 | **99.0** |
| 2025-08-30 20:00 | 1.168565 | 1.168565 | 1.166255 | 1.166260 | **23.1** |

(Bid-side range 98.3 / 22.4 pips, ask-side 99.7 / 23.8 pips — both sides agree the jump is real in
the raw feed, not a Bid/Ask-construction artifact; median of the other 71 bars is 0.10 pips, so
these two are ~230x and ~1,000x the typical Saturday-bar range respectively.) These 2 bars feed
directly into the 4h bars the simulator's high/low TP/SL exit test consumes (§4h resample, fixed
grid), so — unlike the other 71, genuinely-benign trailing prints — they are not waved through on
"tiny magnitude" alone: a 99-pip or 23-pip one-hour range is outside any plausible EURUSD move and
should be treated as a bad print, not a real market event.

**Verdict: explained, not BLOCKED, with an explicit carve-out.** The mechanical gate firing (73 > 0)
correctly forced this investigation; 71 of the 73 bars are genuine, tiny, non-propagating vendor
batching artifacts, but the 2 outlier prints above are a distinct, more serious data-quality issue
that the survey batch must not silently absorb: **the survey batch should exclude or winsorize
Saturday-UTC bars from its 4h series (or, at minimum, exclude these 2 specific prints) per its
pre-registered data-quality protocol** before running any strategy on this cache. This is flagged
here (and in §5) as an open item for the survey batch, alongside the Dec-2024/Jan-2025 and Jul-2025
vendor gaps — all four sit in the same 2023–2025 window this harness's independent checks show
degraded vendor data quality.

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
(Unaffected by the §2 correction — this finding is derived from FXCM's own filenames, not from
parsed bar timestamps.)

---

## 4. Validation results — CORRECTED (full history: 2012 week 1 → 2026 week 17)

Ran via `venv/bin/python backtest/run_fx_plumbing_check.py --end-year 2026` (cache-only re-run
against the same archive bytes as the original note — only the parsing changed).

| Check | Result | Threshold | Verdict |
|---|---|---|---|
| Raw H1 rows | 88,186 (`2012-01-02 03:00 UTC` → `2026-05-01 20:00 UTC`) | — | unchanged row count; date range shifted vs the original (wrong) note because the bogus +4h/+5h offset is gone |
| Duplicate timestamps | 0 | — | clean |
| Monotonic index | `True` (0 out-of-order) | — | clean |
| OHLC coherence (Bid, Ask, **and Mid**) | 0 violations | — | clean |
| Non-positive prices | 0 | — | clean |
| Crossed quotes (`AskClose < BidClose`) | 2,098 / 88,186 = **2.3791%** | 0.1% | over threshold — mechanically gated, **investigated below** |
| **Saturday-UTC bars (new check)** | **73 / 88,186 = 0.083%** | 0 | over threshold — mechanically gated, **investigated in §2** |
| Sunday-UTC bars (new check, context only) | 1,945 | — | expected (session-open bars) |
| 4h bars after resample | 22,811 before dropping the in-progress final bar, **22,810 after** (the figure used by §8's baseline) — partial boundary buckets: 1,526 | ~30 bars/week × 744 weeks found ≈ 22,320 | matches the SUB_PLAN's ~23k-bar estimate |

The row count (88,186) and the crossed-quotes count (2,098) are **unchanged** from the original
note — both are properties of individual rows' Bid/Ask values, unaffected by which UTC hour a row
is labeled with. What changed: the 4h-bucket boundaries (grid is fixed-UTC, so shifting every
timestamp back by 4-5h changes which bars land in which bucket), the partial-boundary-bucket count
(1,526, was 1,538), the total 4h-bar count (22,811/22,810, was 22,818), every hour-of-day
statistic, and the day-of-week labeling (the Saturday-bar bug).

### Crossed-quotes investigation — CORRECTED hour distribution (reviewer round-1 must-fix 2)

The original note's claim that crossed quotes are "spread roughly evenly across all 24 hours" was
**false**. The corrected by-hour count (mechanically recomputed, `AskClose < BidClose`, UTC hour):

| Hour (UTC) | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Count | 52 | 64 | 57 | 44 | 59 | 69 | 98 | 102 | 106 | 103 | 123 | 94 |

| Hour (UTC) | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Count | 113 | 122 | **147** | 134 | 120 | 118 | 96 | 97 | 54 | 58 | **26** | 42 |

This is a **~3-5x diurnal concentration** in the main trading-session hours (roughly 06:00–19:00
UTC, London/NY overlap included, range 94–147) versus the thin overnight/off-session hours
(20:00–05:00 UTC, range 26–69): the peak hour (14:00 UTC, 147) is 5.65x the thinnest hour (22:00
UTC, 26). Magnitude is unchanged from the original note — median −0.10 pip, mean −0.19 pip, max
−2.20 pips — still tiny.

Critically, the note's underlying conclusion is unchanged by this correction, and is in fact
**strengthened**: the crossings concentrate in the busiest, most liquid session hours, which
**rules out** a thin-liquidity artifact (that would predict the opposite — concentration in
overnight hours) and instead supports FXCM's H1 archive independently sampling the last bid tick
and the last ask tick within each hourly bucket (more ticks per hour during peak session -> more
chances for a sub-2-pip last-tick crossing) — a vendor microstructure quirk, not a corrupted or
unusable bar.

**This crossing never propagates into anything the simulator consumes.** The Bid-side and Ask-side
OHLC bars are each independently coherent (0 violations, confirmed above) and — because
`MidField = (BidField + AskField) / 2` is a linear combination of two independently-coherent OHLC
series — the **Mid OHLC the simulator actually trades on is guaranteed coherent by construction**,
confirmed directly (0 Mid violations, mechanically checked via `check_ohlc_coherence`'s three-way
Bid/Ask/Mid loop).

**Verdict: the mechanical gate fired (2.3791% > 0.1%) and was investigated and adjudicated — not
BLOCKED.** (Reviewer round-1 must-fix 3: this threshold now reaches `blocked_reasons` mechanically
via `evaluate_blocked_reasons`, not by narrative adjudication alone; the printed BLOCKED-reasons
list for this run includes both the 2024/2025 missing-weeks crossings, the crossed-quotes
crossing, and the Saturday-bars crossing, all four investigated in this note.)

---

## 5. Weekly-file + row-count completeness by year

Unaffected by the §2 correction (this table is keyed by FXCM's own filename year/week, not by
parsed bar timestamps — reconfirmed identical on re-run):

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

**Open item flagged for the survey batch (reviewer round-1 should-fix 7):** both the Dec-2024/
Jan-2025 (~3.5wk) and Jul-2025 (2wk) vendor gaps fall inside the last two years of history, which
is exactly the window a walk-forward out-of-sample split is most likely to use for its most recent
test fold — the survey batch should account for these as real, vendor-confirmed data holes (not
silently interpolate across them) when it sizes and dates its walk-forward windows.

### "Other" (non-weekend) gap distribution — sanity, not failure

Reconfirmed identical on the corrected re-run (this classification is diff-based between
consecutive bars, invariant to a per-week constant timezone offset): 89 non-hourly, non-weekend-
length gaps across the full history (median 30h). Grouping by calendar month:

| Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Count | 16 | 1 | 2 | 2 | 6 | 11 | 6 | 17 | 9 | 0 | 2 | 17 |

Strong concentration in **December (17) and January (16)**, plus **August (17)** — consistent with
US federal holidays and the vendor's own year-end publishing gap shortening a trading week
(Christmas, New Year) and a summer vendor-gap window. The three large outliers (217h, 367h, 385h)
are the already-explained Dec-2024/Jan-2025 gap above, not new anomalies.

---

## 6. Empirical spread (FXCM bid/ask) — measurement/cross-check only

Per-bar spread = `AskClose − BidClose`, in pips, over the full 2012–2026 history — **overall
statistics are unchanged** by the §2 correction (they don't depend on hour-of-day labeling):

| Statistic | Value |
|---|---|
| Median | 0.20 pips |
| Mean | 0.40 pips |
| p95 | 1.20 pips |

**By hour of day — CORRECTED.** The original note's claim ("widest at 00:00–01:00 UTC") was based
on the wrong hour labels. Recomputed median pips by UTC hour: flat at **0.2 pips for every hour
00:00–19:00 and 23:00**, widening to **0.4 pips at 22:00** and peaking at **1.3 pips at 21:00**
(with 20:00 at 0.7 pips) — i.e. the widest spread sits right around the Friday-close / early-
Sunday-open session boundary in UTC terms, exactly where thin liquidity is expected, not at an
arbitrary overnight hour. By year, the median ranges 0.1–0.4 pips (unaffected by the correction):
tightest 2019–2021 (0.1) and a touch wider in the earliest (2012: 0.4) and most recent (2025–2026:
0.3) years.

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

Unaffected by the §2 correction (not data-dependent):

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

## 8. Trivial baseline — SMA(50) on 4h mid closes, symmetric R=30bp — CORRECTED

**Not a strategy claim.** Params are arbitrary (picked from the gate doc's own R grid, unmodified)
and exercise both trade directions (long above the SMA, short below). Run over the full 2012–2026
history, **22,810 4h bars after dropping the in-progress final bar** (22,811 before the drop — the
§2/§4 correction shifted the fixed-UTC grid's bucket boundaries relative to the raw H1 bars, so
this count and every result below differ from the original note's 22,817/22,818; that is expected
and is exactly the kind of number this plumbing check exists to regenerate honestly, not preserve).

| Venue | Cost mode | Net return | Max DD | # trades |
|---|---|---|---|---|
| *(costs OFF)* | — | **−56.91%** | −58.0% | 6,015 |
| IC Markets ECN | base | −79.48% | −79.7% | 6,015 |
| IC Markets ECN | pessimistic | −90.67% | −90.7% | 6,015 |
| XTB CFD | base | −76.15% | −76.4% | 6,015 |
| XTB CFD | pessimistic | −86.61% | −86.7% | 6,015 |
| CME 6E | base | −69.23% | −69.6% | 6,015 |
| CME 6E | pessimistic | −76.39% | −76.6% | 6,015 |
| CME M6E | base | −79.44% | −79.6% | 6,015 |
| CME M6E | pessimistic | −87.82% | −87.9% | 6,015 |

**Costs-off/on delta** (percentage points added to the loss, by venue, base case):

| Venue | Delta (base) | Delta (pessimistic) |
|---|---|---|
| CME 6E | −12.3pp (cheapest — no overnight charge) | −19.5pp |
| XTB CFD | −19.2pp | −29.7pp |
| IC Markets ECN | −22.6pp | −33.8pp |
| CME M6E | −22.5pp | −30.9pp |

The baseline has **no edge even at zero cost** (a raw SMA(50)/±30bp rule churning ~6,000 trades over
14 years is exactly the high-frequency, no-signal regime the #369 gate doc's cost arithmetic warns
about) — the deliverable here is that the cost model correctly and monotonically worsens every
venue's result, cheapest-venue-first (6E futures, with no overnight charge, has the smallest drag,
consistent with the gate doc's own venue ranking), proving the pipeline plumbs end to end on real
data. **No strategy conclusion follows from this table.** The trade count (6,015) is unchanged from
the original note despite the different bar total and grid alignment — a coincidence of this
particular SMA(50)/R=30bp parameterization, not a general invariant.

---

## 9. Annual netting tax — worked example (hand-verifiable)

Unaffected by the §2 correction (a self-contained worked example, not data-dependent).
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

- `CLAUDE_AGENT_NO_BROKER=1 venv/bin/python -m pytest tests/ -q` — full suite green (see PR
  description for pasted output; the 2 pre-existing yfinance TLS failures are unrelated to this
  package and present on `origin/main`).
- `venv/bin/python backtest/run_fx_plumbing_check.py --end-year 2026` (cache-only) — this note's
  numbers come directly from that corrected run's printed tables (excerpted above).
- **Reviewer re-derivation pointers (corrected, reviewer round-1 should-fix 5):**
  - One week's row count: **2020 week 5 has 120 H1 rows** (`24×5`, a normal winter week spanning
    `2020-01-26 22:00 UTC` → `2020-01-31 21:00 UTC` inclusive — not 121; the original note's "121
    (24×5+1)" was wrong).
  - One 4h bar from its **four** H1 bars (not six — a 4-hour bucket on the fixed grid aggregates
    exactly four hourly bars): any `resample_to_4h` bucket — `Open`=first H1 open, `Close`=last H1
    close, `High`/`Low`=max/min over the four.
  - One preset from the gate doc (§7 table above, cross-check against
    `docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §4.1–4.3).
  - The annual-netting figure in §9.
- **Bar-count labeling reconciled (reviewer round-1 should-fix 6):** the runner now prints both the
  pre-drop (22,811) and post-drop (22,810) 4h-bar counts explicitly and labels which one feeds the
  baseline (22,810) — no more single ambiguous figure split across two sections.
- **Architectural invariants (CLAUDE.md):** research-only; no LLM anywhere in this code; no broker
  import; `simulate_fx` is a pure function of a bar history and a signal series (no I/O, no
  network, no state).
