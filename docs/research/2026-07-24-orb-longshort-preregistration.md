# Long/short Opening-Range Breakout — pre-registration (#434)

**Question:** Does an Opening-Range Breakout with an explicit bracket, traded **both long
and short** across a grid of opening-range lengths and profit targets, clear the standing
promotion bar on full-power intraday data?

**Issue:** #434, following #431 (P2 of batch #429) · **Origin:** operator direction
(2026-07-24) to build out the candlestick strategy · **Date:** 2026-07-24
**Author:** Claude Code session (research-only; no production/TypeScript code, no
`strategy/`, no settings, no broker integration touched; no order placed; no network
performed by any module added here).

> **Status: PRE-REGISTRATION ONLY. The results section below is deliberately EMPTY.**
> This document is committed **before** any result exists, per the standing discipline that
> the bar cannot drift to fit the numbers. The run is currently **DATA-BLOCKED** — see §6.

---

## §0 Invariant framing (stated first, governs everything below)

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- Any candidate this produces would be a **deterministic pure function of price history**
  that **replaces** the live 200-DMA/UPRO rule, never a second parallel rule (invariant #1,
  one decision rule).
- **No LLM in the trading path** (invariant #2). Every module added for this study lives in
  `backtest/` and is never imported by `supabase/functions/`.
- **This document authorizes nothing live.** The UPRO/200-DMA bot runs unchanged. A live
  port happens only after a GO verdict here, default-OFF, per the giveback precedent (#420
  ran Phase A to a verdict *before* Phase B's live port).
- Engineer subagents never execute against the live broker; `CLAUDE_AGENT_NO_BROKER` applies.

---

## §1 Why this exists — what #431 could not answer

#431 probed ORB and returned **DATA-BLOCKED**. Two separate limitations were in play, and
they are worth separating because only one of them was about data:

1. **Data.** Free SPY 5-min reaches ~n_w ≈ 9 (2016+ via keyed Alpaca), short of the n_w = 13
   promotion bar; the yfinance fallback reached ~60 sessions. Nothing was runnable.
2. **Engine.** The bracket engine was **long-only v1**. Zarattini & Aziz (2023) — the one
   intraday candidate with a published positive result — trade **long and short**. So even
   with perfect data, #431 could only ever have tested **one arm of a two-armed strategy**.
   That was its disclosed "Deviation #1".

Limitation (2) is now closed: the engine supports shorts (#434), and the ORB geometry is
parameterised. Limitation (1) is not closed and is the reason §7 is empty.

**Honest framing:** this does not overturn #422's NO-GO on the short-horizon rule-based
entry *class*. ORB was explicitly named there as the **revisit trigger**, not as a settled
kill. This pre-registration is that revisit, run properly rather than by citation.

---

## §2 The frozen rule

Long-and-short ORB, filled at the next bar's open, flat overnight.

| Element | Frozen choice |
|---|---|
| **Opening range (OR)** | High/Low across the first `or_bars` bars of each US regular session |
| **Long entry** | First later bar of the SAME session whose **Close breaks above the OR high** → enter at the **next bar's open** |
| **Short entry** | First later bar whose **Close breaks below the OR low** → enter at the **next bar's open** |
| **Entries per session** | **One per direction**, never on an OR bar, never on a session's last bar, never across a session boundary |
| **Stop** | Opposite side of the OR (long: OR low; short: OR high) |
| **Target** | `R` multiples of per-share risk, or exit-at-session-close |
| **Overnight** | Never held — EOD flat (`session_close_out=True`, `eow_close_out=False`) |
| **Cost model** | `SLIPPAGE_BPS` + `COMMISSION_BPS` per side (the same 5+5 bps/side = 20 bps round trip #430 used) |

Entry geometry is measured against the **slippage-adjusted entry reference** — the price the
engine will actually fill at — not the raw Open.

### Deviations from the source, disclosed up front

- **Entry trigger.** The paper trades in the first candle's direction at the second bar's
  open; this triggers on a **Close breaking the OR**. Chosen for no-look-ahead alignment
  with the bracket engine, carried over from #431's frozen choice.
- **Instrument.** The paper is QQQ/TQQQ over 2016–2023; the grid below is written for SPY.
  A leveraged-vehicle arm is **not** in this grid — adding one later is a new registration,
  not an edit to this one.
- **Session-last-bar exclusion.** Not in the paper. Required for correctness: the engine
  never tests the entry bar for an exit, so an entry on a session's last bar would ride
  overnight. Documented as a fix, not a tuning choice.

---

## §3 The frozen grid and multiplicity

**direction {long, short} × or_bars {1, 3, 6} × target {close, R=5, R=10} = 18 cells.**

On 5-minute bars `or_bars` 1/3/6 is a **5 / 15 / 30-minute** opening range. `target=close`
is the paper's simplest exit-at-close variant; `R=10` is its base-model target.

**All 18 cells are disclosed and reported.** No cell is dropped after results are seen. The
DSR trial count for the #398 overfitting gate is **N = 18** unless the loaded data forces a
declared non-promotable arm, in which case the split is stated in the results section before
the numbers.

---

## §4 The bar (verbatim, frozen)

> A cell clears the bar only if its **full-window after-tax US Calmar** exceeds the SPY
> buy-and-hold median-window after-tax Calmar of **1.3085475049604838**
> (n_w = 13 non-overlapping 12-month windows, 2013–2025), computed on the same after-tax
> basis (`_after_tax_metrics(...)["calmar_us"]`).

This is the same frozen SPY bar #425/#430 used, so results stay comparable across the
program. **Primary verdict = per-cell after-tax Calmar vs 1.3085.**

Two secondary checks, neither able to overturn a primary failure:

- **Random-entry baseline.** Every cell has a seeded random-entry twin with identical
  bracket geometry and the same number of entries. A cell that does not beat its twin has no
  timing edge — it is capturing session volatility. This is the check that killed #430.
- **Always-in baseline.** Buy-and-hold of the same vehicle over the same window.
- **#398 gate** (DSR / PBO / block-bootstrap) as a robustness read.

---

## §5 Power requirements

| Threshold | Value | Meaning |
|---|---|---|
| `PROMOTION_N_W` | 13 | Non-overlapping 12-month windows for gate eligibility |
| `PROBE_MIN_SESSIONS` | 500 | Directional-read floor; below this, results are not a read |
| `MIN_WINDOW_BARS` | 80 | Below this the frame is not a usable series at all |

These are enforced **mechanically** by `intraday_data.describe_power`, which returns one of
`PROMOTABLE` / `DIRECTIONAL` / `UNDERPOWERED`. `run_orb_study.py` refuses to print any
per-cell table on an `UNDERPOWERED` frame and exits non-zero.

This is deliberate. #431 had to hand-label its shallow numbers "plumbing smoke" in prose, and
prose is easy to skip past — a table of numbers, once written down, tends to get quoted.
Here the refusal is a property of the code.

---

## §6 Data situation — why this is DATA-BLOCKED

**In the session that authored this document, every market-data host is 403-denied by the
environment's egress policy.** Probed and confirmed denied at the gateway:

`query1.finance.yahoo.com`, `fc.yahoo.com`, `data.alpaca.markets`, `stooq.com`,
`api.nasdaq.com`, `api.tiingo.com`, `www.alphavantage.co`, `finnhub.io`, `api.polygon.io`,
`databento.com`

Only `github.com`, `registry.npmjs.org` and `pypi.org` are reachable. **Supplying Alpaca
keys would not help** — the data host itself is denied, not merely unauthenticated. This is
strictly worse than #431's situation, where the host was reachable but key-gated.

### The unblock paths, in order of cost

1. **Local file (no egress needed, no spend).** Export intraday bars anywhere — a broker's
   own export, a workstation with open egress, an existing dataset — and drop them at
   `data/intraday/SPY_5min.csv` (or pass `--data PATH`). `load_local` accepts CSV/Parquet
   with flexible column naming and validates the frame before it is simulated. **This is the
   recommended path**: it needs nothing from anyone but the operator.
2. **Allowlist `data.alpaca.markets`** in the environment's network egress settings, then
   supply the read-only data keys. Reaches ~n_w ≈ 9 (2016+) — a **DIRECTIONAL** read only,
   never gate-eligible.
3. **Paid full-power intraday data** (Databento / FirstRate class) to reach n_w = 13. Note
   that #431 recommended **against** this spend on its evidence, and nothing here overturns
   that recommendation — it is recorded as an option, not a proposal.

Paths 1 and 2 both yield a **DIRECTIONAL** read at best. **Only path 3 can produce a
gate-eligible verdict.** A DIRECTIONAL result is worth having — it is what decides whether
path 3 is worth funding — but it cannot promote anything on its own.

---

## §7 Results

**Power-gate assessment:** DIRECTIONAL — 242601 bars / 2667 sessions / n_w=10
(2016-01-04 → 2026-08-12). n_w=10 is below the n_w=13 promotion bar (§5), so this is a
directional read only, NOT gate-eligible. No cell can promote on this data regardless of
performance.

Source: `local:data/intraday/SPY_5min.csv`
Grid: 18 cells (direction × or_bars[1, 3, 6] × target['close', 'R=5', 'R=10']) — all
disclosed for multiplicity
Bar: after-tax US Calmar > 1.3085 (SPY B&H median window, n_w=13)
Always-in benchmark: after-tax US Calmar 0.386

| dir | or_bars | target | CalmarUS | CAGR | maxDD | #trades | random | > bar? |
|---|---|---|---|---|---|---|---|---|
| long | 1 | close | nan | -32.5% | -98.5% | 2245 | nan | no |
| long | 1 | R=5 | nan | -32.3% | -98.4% | 2245 | nan | no |
| long | 1 | R=10 | nan | -32.5% | -98.5% | 2245 | nan | no |
| long | 3 | close | nan | -30.5% | -97.9% | 2099 | nan | no |
| long | 3 | R=5 | nan | -30.4% | -97.9% | 2099 | nan | no |
| long | 3 | R=10 | nan | -30.5% | -97.9% | 2099 | nan | no |
| long | 6 | close | nan | -30.5% | -97.9% | 1983 | nan | no |
| long | 6 | R=5 | nan | -30.3% | -97.8% | 1983 | nan | no |
| long | 6 | R=10 | nan | -30.5% | -97.9% | 1983 | nan | no |
| short | 1 | close | nan | -34.1% | -98.8% | 2151 | nan | no |
| short | 1 | R=5 | nan | -33.5% | -98.7% | 2151 | nan | no |
| short | 1 | R=10 | nan | -33.9% | -98.8% | 2151 | nan | no |
| short | 3 | close | nan | -33.0% | -98.6% | 2003 | nan | no |
| short | 3 | R=5 | nan | -32.6% | -98.5% | 2003 | nan | no |
| short | 3 | R=10 | nan | -33.0% | -98.6% | 2003 | nan | no |
| short | 6 | close | nan | -31.2% | -98.2% | 1833 | nan | no |
| short | 6 | R=5 | nan | -30.7% | -98.0% | 1833 | nan | no |
| short | 6 | R=10 | nan | -31.0% | -98.1% | 1833 | nan | no |

Cells clearing the bar: 0 / 18

**Verdict: DIRECTIONAL_NO_GO.** All 18 cells show catastrophic performance — CAGR ranges
from −30.3% to −34.1%, maximum drawdown from −97.8% to −98.8%, and after-tax Calmar is
`nan` across every cell (negative CAGR makes Calmar undefined). The random-entry twins
are likewise `nan`, so the timing-edge comparison is unreadable — though irrelevant given
the primary metric's total failure. Even on a purely directional basis (ignoring the
n_w=13 gate), no cell remotely approaches the 1.3085 Calmar bar or the 0.386 always-in
benchmark. ORB long/short on SPY 5-min is a decisive negative.

Reproduce with:

```bash
python3 -m backtest.run_orb_study --data data/intraday/SPY_5min.csv
```

---

## §8 What a verdict here would and would not mean

- **A cell clearing the bar on PROMOTABLE data** → a candidate worth a fresh ADR and a
  default-OFF live port. Not an immediate strategy change; UPRO stays live until the full
  gauntlet is passed.
- **A cell clearing the bar on DIRECTIONAL data** → grounds to fund full-power data (§6
  path 3). **Not** grounds to trade it.
- **No cell clearing the bar** → ORB joins the killed set, and #422's revisit trigger is
  spent. That is a complete and valuable deliverable: an honest negative closes the
  operator's stated direction with a measured number instead of a citation, which is exactly
  what was missing when this work started.

The steady-growth goal underneath this direction has an evidence-backed alternative path in
**#421 (diversification on daily bars)**, which the #422 feasibility gate named as the
natural next move. That remains true regardless of how this study resolves.
