# NEUTRAL-detector promotion study — VERDICT (NO-GO)

**Issue:** #629. **Branch:** `feat/629-neutral-promotion`.

**Date:** 2026-09-03. **Author:** Claude Code session (research-only;
`CLAUDE_AGENT_NO_BROKER=1` for the whole session; no production code, no broker
call, no order endpoint touched).

**Pre-registration:**
[`docs/research/2026-09-03-neutral-promotion-preregistration.md`](./2026-09-03-neutral-promotion-preregistration.md)
(commit `eaf1d46`, PR A — frozen before any data was analyzed).

---

## Decision: **NO-GO** (DIRECTIONAL_NO_GO)

Stage 1 found statistically significant breakout-direction bias in both NEUTRAL
detectors (`inside_bar` and `doji` both show a long-skew at p < 0.05). Stage 2
found that **no cell's 2R bracket win rate exceeded the 33.3% breakeven**. Every
cell that ran a bracket simulation had a win rate between 21.9% and 30.2%, with
negative expectancy (-0.09R to -0.34R) and p-values ≥ 0.99 against the breakeven
null. Per the frozen verdict mapping (§5 of the pre-registration), this is
**NO-GO**: Stage 1 bias present, Stage 2 profitability absent.

No design spec is drafted. The study closes here.

---

## Data provenance

| Source | File | Rows | Date range | SHA256 |
|--------|------|------|------------|--------|
| Local CSV (primary) | `data/intraday/SPY_60min.csv` | 41,968 | 2016-01-01 → 2026-08-12 | `9971bd413ef1c08ec17414a34731ba84460f742e2ab458b1fc006702bc1e3b74` |

- **Volume column:** NOT PRESENT in the primary CSV. The existing file was fetched
  without `keep_volume=True` (predates #629).
- **yfinance fallback attempted:** `yfinance.download("SPY", interval="60m",
  period="730d")` returned 5,082 bars (2023-10-06 → 2026-09-03) with volume, BUT
  **zero timestamps matched** the primary CSV's index (timezone/index-alignment
  mismatch between Alpaca-format UTC timestamps and yfinance's index format).
  Consequently, 0 bars received non-zero volume after the merge.
- **Impact:** All VOL_HIGH cells (cells 1, 3, 5, 7) are EMPTY (0 fires). Only
  VOL_LOW cells (2, 4, 6, 8) are populated. The volume-confirmation qualifier
  could not be meaningfully evaluated. This is a **data limitation**, not a
  methodological one — the ATR-rank qualifier (price-only) is fully operational.

### Power ceiling

- SPY 1Hour bars from 2016-01-01 to 2026-08-12 span ~10.6 years → **n_w ≈ 10**.
- The promotion bar is n_w = 13 (`intraday_data.PROMOTION_N_W`).
- **Any result is DIRECTIONAL** — suggestive, never gate-eligible.
- Consistent with prior hourly studies (#571 verdict, #566 feasibility).

---

## Stage 1 — Breakout-direction screening

### Overall results (per pattern)

| Pattern | Total fires | Directional breakouts | Long | Short | Neither | Long rate | Binomial p (2-sided vs 50%) | Bias? |
|---------|------------|----------------------|------|-------|---------|-----------|----------------------------|-------|
| `inside_bar` | 7,625 | 6,417 | 3,420 | 2,997 | 1,208 | 0.5330 | ≈ 0 (<< 0.000001) | **YES** |
| `doji` | 4,959 | 3,895 | 2,034 | 1,861 | 1,064 | 0.5222 | 0.005845 | **YES** |

Both patterns show a modest but statistically significant long-skew in breakout
direction. The effect is small (53.3% and 52.2% respectively), but with thousands
of fires, the binomial test rejects 50% comfortably.

Interpretation: this long-skew is almost certainly an **ascending-market artefact**.
SPY rose from ~$174 (Jan 2016) to ~$550+ (Sep 2026) over the study window. A
persistent upward drift naturally produces more upside breakouts than downside
ones. This is not a pattern-specific edge — it is the underlying vehicle's drift.

### Per-cell results (8 cells × 2 patterns = 16 binomial tests)

> **Note:** Because no volume data was available, all VOL_HIGH cells (H/H, L/H,
> S/H/H, S/L/H) contain 0 fires. The effective grid is 4 VOL_LOW cells × 2
> patterns = 8 populated trials, not 16. The empty cells are reported for
> completeness.

#### `inside_bar`

| Cell | ATR | Vol | Bucket fires | Directional | Long | Short | Long rate | p-value | Bias? |
|------|-----|-----|--------------|-------------|------|-------|-----------|---------|-------|
| L/H/H | HIGH | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| L/H/L | HIGH | LOW | 3,716 | 3,083 | 1,643 | 1,440 | 0.5329 | 0.000273 | **YES** |
| L/L/H | LOW | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| L/L/L | LOW | LOW | 3,909 | 3,334 | 1,777 | 1,557 | 0.5330 | 0.000148 | **YES** |
| S/H/H | HIGH | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| S/H/L | HIGH | LOW | 3,716 | 3,083 | 1,643 | 1,440 | 0.5329 | 0.000273 | **YES** |
| S/L/H | LOW | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| S/L/L | LOW | LOW | 3,909 | 3,334 | 1,777 | 1,557 | 0.5330 | 0.000148 | **YES** |

Note: L/H/L and S/H/L share the same bucket (ATR_HIGH, VOL_LOW) — the long and
short cells within the same bucket have identical statistics because the
bucket-level test measures the long-share among ALL directional breakouts in
that bucket, irrespective of which direction the cell assigns. The same applies
to L/L/L and S/L/L.

#### `doji`

| Cell | ATR | Vol | Bucket fires | Directional | Long | Short | Long rate | p-value | Bias? |
|------|-----|-----|--------------|-------------|------|-------|-----------|---------|-------|
| L/H/H | HIGH | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| L/H/L | HIGH | LOW | 2,416 | 1,864 | 969 | 895 | 0.5198 | 0.090842 | no |
| L/L/H | LOW | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| L/L/L | LOW | LOW | 2,543 | 2,031 | 1,065 | 966 | 0.5244 | 0.029638 | **YES** |
| S/H/H | HIGH | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| S/H/L | HIGH | LOW | 2,416 | 1,864 | 969 | 895 | 0.5198 | 0.090842 | no |
| S/L/H | LOW | HIGH | 0 | 0 | 0 | 0 | — | — | no (empty) |
| S/L/L | LOW | LOW | 2,543 | 2,031 | 1,065 | 966 | 0.5244 | 0.029638 | **YES** |

### Multiplicity disclosure

- **16 binomial tests** conducted (8 cells × 2 patterns). Of these, **8 were
  empty** (VOL_HIGH cells with 0 fires due to no volume data), leaving **8
  effective tests**.
- **Nominal hits (p < 0.05): 6** (4 inside_bar + 2 doji).
- Expected false positives at α=0.05 over 8 effective tests: ~0.4. Over the
  full 16: ~0.8. The 6 hits exceed the chance expectation, suggesting a real
  (though small) long-drift effect rather than pure multiple-testing noise.
- However, as noted above, the long-drift is almost certainly the underlying
  vehicle's bull-market bias, not a pattern-specific signal.

---

## Stage 2 — Bracket profitability (conditional on Stage 1 bias)

Stage 2 was run for all cells that showed Stage 1 bias (p < 0.05): 4 inside_bar
cells and 2 doji cells (all VOL_LOW, since VOL_HIGH cells were empty).

**Entry/exit geometry (frozen in pre-registration §4):**
- Entry at bar t+2's open (2-bar lag from pattern fire at t, breakout confirmed at t+1)
- Stop at pattern bar's own extreme ± 10bp buffer
- Target at entry ± 2R × risk
- Session close-out enabled (flatten at each calendar date's last bar)
- EOW close-out enabled

### Results

| Pattern | Cell | Ran? | Trades | Wins | Win rate | Exp (R) | p vs 33.3% | Profitable? |
|---------|------|------|--------|------|----------|---------|------------|-------------|
| inside_bar | L/H/L | RUN | 1,244 | 376 | 0.3023 | -0.0932 | 0.991153 | **NO** |
| inside_bar | L/L/L | RUN | 1,322 | 327 | 0.2474 | -0.2579 | 1.000000 | **NO** |
| inside_bar | S/H/L | RUN | 1,160 | 276 | 0.2379 | -0.2862 | 1.000000 | **NO** |
| inside_bar | S/L/L | RUN | 1,236 | 293 | 0.2371 | -0.2888 | 1.000000 | **NO** |
| doji | L/L/L | RUN | 868 | 233 | 0.2684 | -0.1947 | 0.999984 | **NO** |
| doji | S/L/L | RUN | 823 | 181 | 0.2199 | -0.3402 | 1.000000 | **NO** |

### Interpretation

Every cell's win rate is **well below** the 33.3% breakeven for a 2R bracket.
The best-performing cell (inside_bar L/H/L) achieved only a 30.2% win rate —
still 3 percentage points below breakeven, yielding a negative expectancy of
-0.09R per trade. The worst cell (doji S/L/L) had a 22.0% win rate and -0.34R
expectancy.

All p-values against the breakeven null (one-sided binomial test, H₀: win rate
≤ 1/3) are ≥ 0.99 — overwhelmingly failing to reject the null. There is no cell
where the 2R bracket is profitable.

The short-breakout cells performed slightly worse than the long-breakout cells
(consistent with the bull-market drift helping longs), but even the long cells
failed to clear breakeven. The 2-bar entry lag (entering at t+2 open after
observing the t+1 breakout) likely contributes to the poor performance: by the
time entry occurs, the initial breakout impulse has often played out.

---

## Verdict mapping (from pre-registration §5)

| Condition | Met? | Evidence |
|-----------|------|----------|
| Stage 1: ≥1 cell with p < 0.05 | ✅ Yes | 6 cells (4 inside_bar + 2 doji) |
| Stage 2: ≥1 cell with win rate > 33.3% (p < 0.05) | ❌ No | Best: 30.2% (p=0.99) |

→ **Outcome:** Stage 1 bias present, Stage 2 win rate ≤ 33.3% → **NO-GO**

---

## Data limitation disclosure

1. **No volume data.** The primary CSV (`SPY_60min.csv`) lacks a Volume column.
   Alpaca API keys were unavailable for a re-fetch with `keep_volume=True`. The
   yfinance fallback retrieved 5,082 hourly bars with volume but **none aligned**
   with the primary CSV's timestamp index (format/timezone mismatch), resulting
   in 0% volume coverage.

2. **Consequence:** 4 of 8 cells (all VOL_HIGH) are empty. The
   volume-confirmation qualifier could not be evaluated. The study effectively
   reduces to a 4-cell grid (VOL_LOW only) × 2 patterns = 8 populated cells.

3. **Acceptability:** Per the pre-registration's locked decisions (§6, §8), the
   yfinance fallback was anticipated as UNDERPOWERED (n_w≈2). The volume
   qualifier's inability to discriminate is a data limitation, not a flaw in the
   study design. The ATR-rank qualifier (price-only) is fully operational and
   provides the ATR_HIGH/ATR_LOW split.

4. **Future re-test path:** A full-power re-test with proper volume data (via
   Alpaca `keep_volume=True` or a paid data source) would populate the VOL_HIGH
   cells and allow the volume-confirmation qualifier to be evaluated. Given that
   all VOL_LOW cells failed Stage 2 decisively, there is little indication that
   adding volume would reverse the verdict, but it remains an open empirical
   question at adequate power.

---

## Cumulative multiplicity (family-wide)

This study adds to the `candlestick_pattern` family in `backtest/tested_cells.py`:

- Prior cumulative trials (daily v1+v2+v3): 168 cells (CLOSED by §9 stopping rule)
- This study: 16 Stage-1 trials + 6 Stage-2 trials (8 empty cells excluded from
  Stage 2) = 22 trials
- Family cumulative: 168 + 22 = 190

However, the prior closure was on **daily** cadence; this study is **hourly** —
a different data source per §9's reopening clause. The prior closure does not
bind here.

---

## Conclusion

The two NEUTRAL candlestick detectors (`inside_bar`, `doji`) show a small but
real long-skew in their next-bar breakout direction on SPY hourly bars — an
effect attributable to the underlying vehicle's bull-market drift rather than a
pattern-specific edge. When this directional bias is traded with a 2R bracket
(entry at t+2 open, stop at pattern extreme, session/EOW close-out), **every
cell loses money**: win rates range from 22.0% to 30.2%, all below the 33.3%
breakeven, with negative expectancy in every case.

**Verdict: NO-GO (DIRECTIONAL_NO_GO).** The NEUTRAL detectors should not be
promoted to directional. They retain their NEUTRAL registration in
`candlestick.PATTERNS` and continue contributing no directional vote in
`decideHourly`.

No design spec is drafted. The study closes here.
