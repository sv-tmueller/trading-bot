# NEUTRAL-detector promotion study — pre-registration (8 cells, two-stage)

**Question:** Do the two NEUTRAL candlestick detectors (`inside_bar`, `doji`) exhibit
directional predictive value on SPY hourly bars when conditioned on a frozen 3-binary-qualifier
set (8 cells), using a two-stage analysis: (1) breakout-direction screening vs 50% chance,
then (2) conditional bracket profitability at 2R vs 33.3% breakeven?

**Issue:** #629. **Branch:** `feat/629-neutral-promotion`.

**Predecessors:**
- `docs/research/2026-07-26-candlestick-timestop-preregistration.md` — the daily candlestick
  widening programme, closed by §9's stopping rule at cumulative N=168, 0 survivors.
- `docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md` (#422) — the cost-wall /
  data-scarcity gate that identifies 1h US-equity ETF as the sole cost-survivable intraday
  corner but marks it not-gate-eligible on free data.
- `docs/superpowers/specs/2026-07-27-hourly-bot-design.md` — the hourly bot design spec, §1 of
  which establishes that the hourly cadence is not a re-run of the closed daily grids.
- `docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md` (#571) — the hourly
  bracket-geometry study, DIRECTIONAL_NO_GO, establishing n_w=10 < 13 for SPY 1Hour from 2016.

**Date:** 2026-09-03. **Author:** Claude Code session (research-only;
`CLAUDE_AGENT_NO_BROKER=1` for the whole session; no production code, no broker call, no order
endpoint touched).

---

> **Freeze declaration.** This document is committed and pushed in PR A **before** any data is
> fetched or analyzed. The grid, protocol, qualifier definitions, entry/exit geometry, and verdict
> mapping below are frozen. PR B (the results) branches from this commit. No result number appears
> anywhere in this document or in the commits behind it.

---

## §0 Invariant framing (governs everything below)

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- **Invariant #1 (one decision rule).** Promoting a NEUTRAL detector to directional creates a
  **new decision pathway** — the NEUTRAL patterns currently contribute no directional vote in
  `decideHourly` (`supabase/functions/_shared/hourly_signal.ts`); making them directional would
  amend the frozen 14-detector registry and the voting function. This study **authorizes nothing
  live**. If the verdict is GO, a design spec
  (`docs/superpowers/specs/2026-09-03-neutral-detector-promotion-design.md`) must address the
  registry amendment and `hourly_signal.ts` voting change before any code is touched. A GO verdict
  at DIRECTIONAL power authorises that spec, not a deployment.

- **Invariant #2 (no LLM in the trading path).** Pure statistical analysis. No model SDK, no
  agent instantiation. Every module touched lives under `backtest/` and is never imported by
  `supabase/functions/`.

- **`backtest/` is never imported by `supabase/functions/`.** Research only. The only shared-
  module change is a backward-compatible `keep_volume` parameter on
  `backtest/run_fetch_spy_intraday.py:fetch_bars` (default `False` = existing behavior).

- **Engineer subagents never execute against the live broker.** `CLAUDE_AGENT_NO_BROKER=1` for
  the session. No order endpoint is touched; the only network call is the read-only historical-
  bars GET already wired into `run_fetch_spy_intraday.py`.

---

## §1 Why this exists, and why it is not a re-run of something already killed

Three prior programmes are closed:

1. **Daily candlestick widening programme** — closed by §9's stopping rule at cumulative N=168,
   0 survivors (`2026-07-26-candlestick-timestop-preregistration.md`).
2. **Short-horizon rule-based entries** — class NO-GO (`2026-07-24-short-horizon-entry-
   feasibility-gate.md`, #422).
3. **Hourly bracket-geometry/sizing** — DIRECTIONAL_NO_GO (`2026-08-13-hourly-geometry-cadence-
   sizing-verdict.md`, #571).

This investigation is **not** a re-run of any of these for four reasons:

**(a) Different cadence.** The daily candlestick programme operated on daily SPY bars. This study
targets **hourly** SPY bars — a different data source per §9's reopening clause ("Reopening
requires new *information*: a new data source, a new instrument class, a published result").
Hourly ≠ daily; the information set is different.

**(b) Untested pattern.** `doji` was **never tested** in the daily grids. The daily programme's
arms list (`run_candlestick_study.ARMS`) excludes doji entirely — it was noted in the
`candlestick.py` module docstring as "an unfrozen free parameter," never promoted to a trial.
`inside_bar` was tested as a next-open directional bet (long arm buys the mother-bar-high break,
short arm sells the mother-bar-low break), but **not** as a breakout-*conditioned* pattern with
ATR/volume qualifiers. Neither pattern has been tested with the qualifier set defined in §3.

**(c) Novel context qualifiers.** The daily v2 study used a trend-context axis (above/below
50-period SMA). This study introduces two **new** qualifiers: ATR percentile rank and volume
confirmation. These are different conditioning variables from the trend-context axis, so the
cells are not the same cells.

**(d) Different analytical framework.** Prior studies went straight to bracket simulation and the
#398 gate. This study uses a **two-stage** design: Stage 1 screens for directional bias
(binomial test vs 50%) before committing to a bracket simulation. This is a cheaper, more
sensitive first filter that the prior programme did not employ.

### §1.1 Relationship to §9's stopping rule

§9 of the candlestick-timestop pre-registration states: *"Reopening requires new information (a
new data source, a new instrument class, a published result), argued in a fresh brainstorm and a
new pre-registration — never a new grid over the same SPY history."*

This study meets the "new data source" criterion: it uses **hourly** SPY bars, not the daily bars
of the closed programme. It meets the "new pre-registration" criterion: this document. It was
authorized by issue #629, which represents the fresh brainstorm. The §9 stopping rule bound the
**daily candlestick widening programme** (v1 context-free, v2 trend-context, v3 time-stop);
this is a different programme at a different cadence with different qualifiers and a different
analytical framework.

### §1.2 Relationship to #422 (cost-wall reconciliation)

#422's §2 cost-wall table identifies 1h US-equity ETF as the sole cost-survivable intraday
corner (≈1.7%/yr cost drag), but §3 marks it not-gate-eligible on free data (no free intraday
source reaches n_w=13). The hourly bot design spec (§1) resolved this by building the bot
"anyway, with the evidence disclosed" — accepting paper-only as the risk container.

This study inherits that posture: it runs on the same SPY 1Hour bars the live bot sees, discloses
the power ceiling (n_w≈10 < 13, §8), and labels any result DIRECTIONAL — suggestive, never
gate-eligible. The cost wall does not bind at the research stage (no live trades are placed);
it would bind if a GO verdict led to a live deployment, at which point the design spec must
address it.

---

## §2 Patterns under investigation

Two NEUTRAL detectors from `backtest/candlestick.py`:

| Pattern | Detector | Span | Current direction |
|---------|----------|------|-------------------|
| `inside_bar` | `cs.inside_bar(df)` | 2 bars | NEUTRAL (compression; direction from breakout) |
| `doji` | `cs.doji(df)` | 1 bar | NEUTRAL (indecision; body ≤ 10% of range) |

Both are registered as NEUTRAL in `candlestick.PATTERNS` — they contribute no directional vote
in the live `decideHourly` composite. This study asks whether they *should* — whether the
breakout after a NEUTRAL fire is predictable enough to support a directional trade.

---

## §3 Frozen qualifier set (3 binaries → 8 cells)

All qualifiers are computed at the **signal bar** (bar `t`, the bar on which the pattern fires),
using only information available up to and including bar `t`'s close (no look-ahead).

### Qualifier 1: Breakout direction (measured at bar t+1)

At bar `t+1` (the bar after the pattern fires), classify the breakout:

- **Long breakout:** bar `t+1`'s high exceeds bar `t`'s high (`high[t+1] > high[t]`)
- **Short breakout:** bar `t+1`'s low breaks below bar `t`'s low (`low[t+1] < low[t]`)
- **Neither:** bar `t+1`'s range is entirely inside bar `t`'s range (another inside bar, or
  simply no directional resolution)

This qualifier is the **dependent variable** in Stage 1 (we test whether it departs from 50%
long/50% short among bars that do break out) and the **partitioning variable** in Stage 2
(long-breakout cells get long brackets, short-breakout cells get short brackets).

### Qualifier 2: ATR percentile rank (computed at bar t)

- **Window:** 20-bar ATR (average true range over the 20 bars ending at bar `t`).
- **Percentile rank:** the ATR at bar `t` ranked against the preceding 252 bars' ATR values
  (approximately one trading year of hourly bars). Rank = fraction of preceding-252 ATR values
  that are ≤ the current ATR.
- **Binary split:** `ATR_HIGH` if rank > 0.50 (above median), `ATR_LOW` if rank ≤ 0.50.

### Qualifier 3: Volume confirmation (computed at bar t)

- **Average:** 20-bar simple moving average of volume, computed over bars `t-19` through `t`.
- **Binary split:** `VOL_HIGH` if bar `t`'s volume > 20-bar average, `VOL_LOW` if ≤ average.

### Cell enumeration (8 cells)

| Cell | Breakout dir | ATR rank | Volume |
|------|-------------|----------|--------|
| 1 | Long | HIGH | HIGH |
| 2 | Long | HIGH | LOW |
| 3 | Long | LOW | HIGH |
| 4 | Long | LOW | LOW |
| 5 | Short | HIGH | HIGH |
| 6 | Short | HIGH | LOW |
| 7 | Short | LOW | HIGH |
| 8 | Short | LOW | LOW |

Cells with "Neither" breakout are counted and reported but do not enter Stage 2 (no direction =
no bracket). Their count is disclosed for completeness.

---

## §4 Two-stage protocol

### Stage 1 — Breakout-direction screening (ALL fires, ALL 8 cells)

**Objective:** Determine whether NEUTRAL fires show a breakout-direction bias departing from
50% chance, overall and per cell.

**Protocol:**

1. Detect all `inside_bar` and `doji` fires on SPY 1Hour bars.
2. For each fire, classify the bar `t+1` breakout (long / short / neither).
3. Among fires where a breakout occurs (long or short, excluding neither), test whether the
   long-breakout rate differs from 50% using a two-sided exact binomial test
   (`scipy.stats.binomtest`).
4. Report:
   - Overall (per pattern): total fires, breakouts, long-breakout rate, binomial p-value.
   - Per cell (8 cells × 2 patterns = 16 trials): sample size, long-breakout count, rate, p-value.
5. **Multiplicity disclosure:** 16 binomial tests. No Bonferroni correction applied at
   DIRECTIONAL power (the study is powered for suggestion, not gate-eligibility), but the
   count is reported and any cell with p < 0.05 is flagged as "nominal" given 16 trials
   (expected ~0.8 false positives at α=0.05 by chance alone).

**Stop condition:** If no cell shows a departure from 50% (all p-values ≥ 0.05), document NO-GO
and skip Stage 2.

### Stage 2 — Bracket profitability (conditional on Stage 1 showing bias)

**Objective:** For cells where Stage 1 shows directional bias (p < 0.05), test whether a 2R
bracket trade in the biased direction is profitable (win rate > 33.3% breakeven).

**Entry/exit geometry (frozen):**

- **Pattern:** `inside_bar` or `doji`, detected at bar `t`.
- **Breakout confirmation:** observed at bar `t+1` (does `high[t+1] > high[t]` for long, or
  `low[t+1] < low[t]` for short?). This is an intrabar event at `t+1`.
- **Entry:** bar `t+2`'s open. This is a **2-bar lag** from the pattern fire — the most
  conservative timing that observes the breakout at `t+1`'s close and enters at `t+2`'s open,
  consistent with the no-look-ahead contract. (Disclosed deviation from the existing
  `run_candlestick_study` convention, which enters at `t+1`'s open. The 2-bar lag sacrifices
  some signal freshness for confirmation rigor.)
- **Stop:** the pattern bar's own extreme — for long, `low[t]` minus a 10bp buffer
  (`STOP_BUFFER = 0.001`); for short, `high[t]` plus 10bp. Anchored to the pattern, not the
  breakout bar, mirroring `run_candlestick_study.bracket_levels`.
- **Target:** `entry ± R · risk` where `R = 2.0` (the frozen R-multiplier). Risk = |entry −
  stop|. At 2R, the breakeven win rate is 1/(1+2) = 33.3%.
- **Direction:** long for long-breakout cells, short for short-breakout cells.
- **Session close-out:** enabled (`session_close_out=True`) — positions are flattened at each
  calendar date's last bar, mirroring the live bot's intraday-flat convention. EOW close-out
  also enabled (default).

**Win rate test:** exact binomial test of the win rate against 33.3% breakeven
(`scipy.stats.binomtest(k, n, p=1/3, alternative='greater')`).

**Reporting:** All 8 cells reported regardless of whether Stage 2 runs for them. Cells that did
not qualify for Stage 2 are marked "not tested (no Stage 1 bias)." Cells that qualified are
reported with trade count, win count, win rate, expectancy in R, and the binomial p-value vs
33.3%.

---

## §5 Verdict mapping (frozen, binding)

| Outcome | Verdict | Action |
|---------|---------|--------|
| No cell shows Stage 1 directional bias (all p ≥ 0.05) | **NO-GO** | Study closes. Ledger entry: `DIRECTIONAL_NO_GO`. No design spec. |
| Stage 1 bias in ≥1 cell, but Stage 2 win rate ≤ 33.3% (or insufficient trades) | **NO-GO** | Study closes. Ledger entry: `DIRECTIONAL_NO_GO`. No design spec. |
| Stage 1 bias AND Stage 2 win rate > 33.3% (p < 0.05) in ≥1 cell | **GO (DIRECTIONAL)** | Design spec drafted (`docs/superpowers/specs/2026-09-03-neutral-detector-promotion-design.md`). Ledger entry: `PENDING` (spec pending). Result is suggestive, not gate-eligible. |
| Data cannot be obtained at sufficient volume coverage | **DATA_BLOCKED** | Study pauses. Ledger entry: `DATA_BLOCKED`. Not evidence of anything. |

**Power ceiling (n_w≈10 < 13):** Regardless of outcome, any result is **DIRECTIONAL** —
suggestive, never gate-eligible. A GO verdict authorizes a design spec, not a deployment. The
design spec must propose a full-power re-test path (longer history, paid data, or a different
instrument) before any live change.

---

## §6 Data plan

**Primary source:** Alpaca Market Data API via `backtest/run_fetch_spy_intraday.py` with
`keep_volume=True`. SPY 1Hour bars, `adjustment="all"`, `feed="sip"`,
2016-01-01 → previous UTC date.

**Fallback:** If Alpaca keys are unavailable, use yfinance (`yfinance.download("SPY",
interval="60m", period="730d")`) which provides ~5,000 hourly bars with volume over the trailing
~730 days. This is substantially shorter than the Alpaca window (n_w≈2 vs n_w≈10) and will be
disclosed as a power reduction.

**Local cache:** Existing `data/intraday/SPY_60min.csv` (41,968 bars, 2016-2026, no volume) is
used for Stage 1 breakout-direction screening (which does not require volume). Volume-dependent
analyses (the ATR-rank qualifier uses price only; the volume-confirmation qualifier requires the
Volume column) use whatever volume-bearing data is available.

**Provenance:** SHA256 of the data file(s) and a `describe_power` report are recorded in the
verdict document.

---

## §7 Multiplicity disclosure

- **Stage 1:** 8 cells × 2 patterns = 16 binomial tests. At α=0.05, the family-wise false-
  positive expectation is 0.8 by chance alone. No correction applied (DIRECTIONAL power); the
  count is reported and nominal hits are flagged.
- **Stage 2:** Up to 8 cells × 2 patterns = 16 bracket simulations (fewer if Stage 1 eliminates
  cells). Each is a one-sided binomial test vs 33.3%.
- **Cumulative family:** This study adds to the `candlestick_pattern` family in
  `backtest/tested_cells.py`. The cumulative trial count inherited from prior rounds is 168
  (daily v1+v2+v3). This study's 16 Stage-1 trials + up to 16 Stage-2 trials are disclosed
  alongside, but the prior closure was on a different cadence (daily) and does not bind here.

---

## §8 Power-ceiling disclosure

SPY 1Hour bars from 2016-01-01 to 2026-09-02 span approximately 10 years. With 12-month
non-overlapping windows, n_w = ⌊(last − first).days / 365⌋ ≈ 10. The promotion bar is n_w = 13
(`intraday_data.PROMOTION_N_W`). Therefore:

- **Any result is DIRECTIONAL** — suggestive, never gate-eligible.
- A GO verdict authorizes a design spec, not a deployment.
- The design spec must propose a full-power re-test path before any live change.
- The n_w≈10 figure is consistent with the prior hourly studies (#571 verdict, #566 feasibility).

If the yfinance fallback is used (730 days), n_w drops to ≈2, which is UNDERPOWERED. In that case,
only the Stage 1 breakout-direction screening (which can run on the full 2016-2026 dataset
without volume) retains DIRECTIONAL power; the volume-qualified cells are reported at
UNDERPOWERED and treated as supplementary evidence.

---

## §9 Files expected to be touched

| # | File | Action | PR |
|---|------|--------|----|
| 1 | `docs/research/2026-09-03-neutral-promotion-preregistration.md` | CREATE | A (this file) |
| 2 | `backtest/run_fetch_spy_intraday.py` | MODIFY (add `keep_volume` param) | B |
| 3 | `backtest/run_neutral_promotion_study.py` | CREATE | B |
| 4 | `docs/research/2026-09-03-neutral-promotion-verdict.md` | CREATE | B |
| 5 | `backtest/tested_cells.py` | MODIFY (append ledger entry) | B |
| 6 | `docs/superpowers/specs/2026-09-03-neutral-detector-promotion-design.md` | CONDITIONAL CREATE (if GO) | B |

No production code (`supabase/`, `strategy/`, `web/`, `main.py`, `.github/`, `scripts/`) is
touched. The only shared-module change is the backward-compatible `keep_volume` parameter on
`backtest/run_fetch_spy_intraday.py`.

---

## Verification (freeze only — no data analyzed yet)

```bash
# Pre-registration is committed before any result
git log --oneline -- docs/research/2026-09-03-neutral-promotion-preregistration.md
git log --oneline -- docs/research/2026-09-03-neutral-promotion-verdict.md
# The prereg commit hash must be strictly earlier than the verdict commit hash

# No production code touched
git diff --stat main -- supabase/ strategy/ web/ main.py .github/ scripts/
# Expect: empty

# Novelty check against prior closures
python3 -m backtest.tested_cells --check candlestick_pattern daily SPY  # expect CLOSED
python3 -m backtest.tested_cells --check candlestick_pattern hourly SPY  # expect WEAK or NOVEL
```
