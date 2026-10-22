# Multi-symbol hourly candlestick rule (SPY top-10 holdings and broad ETFs) -- pre-registration

**Question:** Should the live hourly candlestick bot (`decideHourly`) trade other symbols in
addition to SPY -- specifically the current top-10 SPY holdings, or alternatively a handful of
broad/sector ETFs -- to raise trade frequency and spread risk across more individual trades
WITHOUT increasing position size (total open notional stays within today's 10% cap)?

**Issue:** none filed (operator request to the research analyst, 2026-10-22).
**Date:** 2026-10-22. **Author:** Claude Code research-analyst session (research-only;
`CLAUDE_AGENT_NO_BROKER=1` for every shell; no broker call, no order endpoint, no production
code touched). **Branch:** `research/multi-symbol-hourly`.
**Closest prior work (conventions inherited, not re-derived):**
`2026-07-25-candlestick-pattern-preregistration.md` (frozen 14-detector registry),
`2026-08-13-hourly-geometry-cadence-sizing-preregistration.md` / `-verdict.md` (#571: the
emitter/simulator split, the 5Min fill convention, the flatten-scan model -- "#571" below),
`2026-09-03-15min-candlestick-study-verdict.md` (cost-wall framing),
`2026-07-21-overfitting-gate-usage.md` (gate thresholds).

This document is committed **before** any cross-symbol result exists. The only number computed
before this commit is gate P0a (§4.1), which re-derives an already-published #571 figure to
validate the simulator; it is recorded here as harness evidence, not as a study result.

---

## §0 Invariant framing

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- **One decision rule.** The study replays the live `decideHourly`
  (`supabase/functions/_shared/hourly_signal.ts`, frozen 14-detector registry, tie-break,
  `contextMode="none"`) and the live `computeBracketGeometry` / `computeSizing`
  (`supabase/functions/hourly-check/logic.ts`) **unchanged**, imported directly into two
  file-in/file-out Deno emitters. Running the same rule on more symbols is not a second rule;
  any portfolio-level gate studied here (§7: shared notional cap, single-position-across-symbols)
  would be a change to entry gating that needs its own brainstorm, spec and ADR before it could
  ship. This study authorizes no live change.
- **No LLM in the trading path.** No model SDK anywhere in this package.
- **Mechanical paper-only guard / engineer subagents never reach the broker.** No module in
  this package constructs an Alpaca client. The only network used is Yahoo Finance read-only
  bar downloads (§2) and one SSGA holdings file download (§1).
- **Panic / kill switch.** Not touched. Implementation implications for multi-symbol trading
  (side-aware panic over all symbols, per-symbol kill-switch flags) are assessed in the
  verdict doc, not changed here.

Script location (disclosed deviation from the operator's "scripts in `backtest/`" request):
this package was produced under the research-analyst role, which may only write under
`docs/research/`. The study code therefore lives in
`docs/research/2026-10-22-multi-symbol-hourly-study/` and imports `backtest/` modules
read-only (`bracket._resolve_bar`, `hourly_geometry.is_flatten_scan` and
`simulate_hourly_geometry`, `overfitting_gate`). No existing `backtest/` file, and not
`backtest/tested_cells.py`, is modified; the verdict doc lists the ledger records an Engineer
should add when relocating the scripts.

---

## §1 Symbol universe (frozen)

**Source:** State Street SPDR SPY daily holdings file
(`https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx`),
downloaded 2026-10-22, header "Holdings: As of 21-Oct-2026".

Top holdings by weight (GOOGL and GOOG are one issuer, Alphabet; combined 5.29%):

| Rank (issuer) | Ticker | Weight (%) |
|---|---|---|
| 1 | NVDA | 8.04 |
| 2 | AAPL | 7.51 |
| 3 | MSFT | 5.92 |
| 4 | GOOGL (+GOOG) | 2.94 + 2.35 = 5.29 |
| 5 | AMZN | 3.85 |
| 6 | AVGO | 2.40 |
| 7 | META | 2.30 |
| 8 | TSLA | 1.63 |
| 9 | MU | 1.54 |
| 10 | LLY | 1.52 |

(Next: BRK.B 1.50, AMD 1.35, JPM 1.33.) Alphabet is traded as **GOOGL only** -- trading both
share classes would double one issuer's exposure on near-identical price paths.

Study universe, 19 symbols:

- **Baseline:** SPY.
- **Top-10 issuers:** NVDA, AAPL, MSFT, AMZN, GOOGL, AVGO, META, TSLA, MU, LLY.
- **ETF alternative (operator's list):** QQQ, IWM, DIA, XLK, XLF.
- **Non-winner large-cap controls (survivorship, §6.4):** BRK-B, JPM, UNH -- large, liquid
  names that are NOT in today's top 10. They are chosen to include names whose 2024-2026 path
  was flat-to-negative (UNH in particular). No claim is made about their point-in-time SPY
  rank; they are controls, not candidates.

---

## §2 Data (primary path blocked; disclosed fallback)

**Primary path (BLOCKED in this session):** Alpaca SIP `1Hour` + `5Min`, `adjustment=all`,
2016-01-01 onward -- the #571 path, which matches the live bot's bar grid. Alpaca market-data
keys are not present in this session's environment (`data.alpaca.markets` returns HTTP 401
without keys; no key was looked up or borrowed from any other source). The staged #571 SPY
SIP files (`data/intraday/SPY_60min.csv` sha256 `9971bd41...b74`, `SPY_5min.csv` sha256
`65da7f61...79`, re-verified byte-for-byte this session) cover **SPY only**, 2016-01-04 to
2026-08-12.

**Fallback path (used for every non-SPY symbol):** Yahoo Finance via `yfinance` 1.2.0,
read-only, `auto_adjust=False` (split-adjusted by Yahoo; dividends not adjusted), regular
session only, downloaded 2026-10-22 by `fetch_yahoo_bars.py`, normalized by
`prepare_inputs.py` (4-dp rounding of Yahoo float noise; bars after NY date 2026-10-21 dropped
so the in-progress 2026-10-22 session is excluded):

| Frame | Coverage | Per symbol |
|---|---|---|
| 1h (`<SYM>_1h_proxy.csv`) | 2023-11-24 to 2026-10-21 | 5,075 bars / 729 sessions |
| 5m (`<SYM>_5m.csv`) | 2026-07-30 to 2026-10-21 | 4,602 bars / 59 sessions |
| 1d (raw) | 2021-10-22 to 2026-10-21 | gap/SSR diagnostics only |

All 19 symbols have identical bar counts in both intraday frames. Per-file SHA256s are
printed by `prepare_inputs.py` and recorded in the verdict doc's reproduction section. No bar
data is committed (`data/` is gitignored; inputs live in a scratch directory).

**Power (binding on every result):** 729 sessions, `n_w = 2` (complete 12-month windows) per
`backtest/intraday_data.describe_power` -> **DIRECTIONAL** (above the 500-session directional
floor, far below the `n_w = 13` promotion bar). Nothing in this study can be gate-eligible for
promotion; the best possible outcome is "directional candidate, re-test on Alpaca SIP 2016+".

**Two structural limits of the fallback, both handled by parity gates (§4):**
1. Yahoo's 1h bars are aligned to :30 (09:30, 10:30, ..., 14:30 ET full bars plus a 15:30-16:00
   stub). The live bot sees top-of-hour bars (10:00, ..., 15:00 ET full bars). Candlestick
   detectors are sensitive to bar boundaries, so the proxy grid produces different fires.
2. Exits on the proxy grid resolve on 1h bars (no multi-year 5m history), so a bar touching both
   stop and target resolves STOP-first (the frozen conservative tie-break) more often than on 5m.

---

## §3 Harnesses (frozen)

Common to both: the live rule (`decideHourly`, `contextMode="none"`, trailing 10 full bars),
live geometry (`HOURLY_STOP_BUFFER_PCT=0.05` of the signal bar's range beyond its low/high,
`HOURLY_BRACKET_R_MULTIPLE=2`, whole-cent quantization, stop first), live sizing validity
(`HOURLY_MIN_STOP_DISTANCE=0.05`, `qty > 0`), one position per symbol, cooldown (signal bar start
must be strictly after the symbol's last exit), day cap 3 entries per symbol per session,
flatten scan when `sessionClose - (barEnd + 7 min) <= 60 min` (live:
`clock.nextClose - now <= HOUR_MS`), kill switch never active, never paused.

**Sides (registered primary = long AND short).** `CURRENT_CONFIG.md` lists
`HOURLY_SHORTS_ENABLED=false`, but the live record shows SHORT entries every week since
2026-09-04 (13 of the 42 trades in `docs/trading-journal/daily-verification.jsonl`; the last
`shorts_disabled` skip is 2026-09-02). The study therefore models the bot **as it is actually
trading**: both sides. Long-only and short-only are reported as diagnostics (§6.4), not as
extra trials. (The config-doc discrepancy is an operational finding for the operator, outside
this study's scope.)

- **H_live (reference harness, top-of-hour grid).** Signals from the UNCHANGED #571 emitter
  `scripts/emit_hourly_decisions.ts --shorts-enabled` (SHORT rows read from `action_raw` with
  `sizing_valid=true`; LONG rows are byte-identical to #571's). Entry/flatten fill at the open
  of the first 5Min bar at/after barEnd + 7 min; entryRef = that same price; exits resolve on
  5Min bars strictly after the fill bar via `bracket._resolve_bar` (#571's exact convention).
  Used for: SPY on SIP 2016-2026 (baseline B0), SPY on Yahoo 5m for live parity (P0b), and every
  symbol on Yahoo 5m over the 59-session 5m window (concordance diagnostic, §6.6).
- **H_proxy (cross-symbol harness, Yahoo :30 grid).** Signals from
  `emit_proxy_decisions.ts`, which imports the same three live functions unchanged. A bar is full
  iff it starts at :30 and ends at or before the session close (inferred per session as last bar
  start + 30 min, which also catches half-days). Entry fills at the open of the next bar (the
  bar starting at the signal bar's end -- 7 minutes earlier than live; entryRef = that open).
  Scan events at a bar's open are processed first (flatten, entry), then every open position,
  including one entered at that open, is resolved against that bar's high/low (STOP-first).
  This gives 5 actionable signal bars per session (09:30-13:30 ET starts; the 14:30 bar's scan
  is the flatten scan) versus 4 on the live grid.

Simulation is cost-free at the price-path level; costs are applied per side afterwards (§5),
so every cost model sees the identical trade path.

---

## §4 Parity gates (run in this order; a FAIL at any hard gate stops the study)

### §4.1 P0a -- simulator reproduces #571 (DONE before this commit; harness evidence only)

The study simulator (`multi_symbol_hourly.simulate`, `order="571"`), fed #571's own input
(`action_final == LONG`, R=2, 5 bps slippage per side, staged SPY SIP bars), must reproduce
#571's published 60m R=2.0 cell exactly.

Result (`run_parity_p0a.py`): `#571 module in-process: trades=1805 expectancy(R)=-0.5381
exits={flatten 1060, target 147, stop 598}`; `study simulator: trades=1805
expectancy(R)=-0.5381` (same exit counts); trade-for-trade match True; published-figure match
True. **PASS.**

### §4.2 P0b -- H_live on Yahoo SPY reproduces the live journal (hard gate)

Window: every session from 2026-08-03 to 2026-10-21 that has a record in
`docs/trading-journal/daily-verification.jsonl` (the 2026-08-17..08-28 no-record gap and the
2026-09-07 holiday excluded). SHORT entries enabled in the simulation from 2026-09-03 (inferred
switch date, §3). Bars: Yahoo 5m resampled to top-of-hour (live grid); live runs on IEX, Yahoo
is consolidated -- feed-level OHLC differences are an expected, disclosed source of mismatch.

- **Day level:** fraction of sessions whose simulated (LONG entries, SHORT entries) count pair
  equals the live `decision_counts` pair. Threshold **>= 0.70**.
- **Trade level** (per-trade list, 2026-08-13 onward, 42 trades): fraction of live trades matched
  by a simulated trade with the same session, same entry hour (UTC) and same side. Threshold
  **>= 0.60** (hard); 0.60-0.75 passes with a disclosed caveat.
- **R level:** on matched trades, median |R_sim(1 bp/side) - R_live| **<= 0.25R**.

### §4.3 P0c -- proxy construction distortion on SPY SIP (hard gate)

Same feed, two harnesses: H_proxy on SIP 5Min resampled to the :30 grid
(`SPY_sip_1h_proxy.csv`) versus H_live on SIP, 2016-01-04 to 2026-08-12, both sides, primary
cost (1 bp/side). Thresholds: **|delta mean R| <= 0.10R** and **|delta win rate| <= 5 pp**.
Trades/yr ratio reported (expected about 1.25 from 5 vs 4 actionable bars).

### §4.4 P0d -- Yahoo vs SIP feed on the proxy grid (hard gate)

H_proxy on Yahoo SPY versus H_proxy on SIP SPY over the overlap 2023-11-24 to 2026-08-12:
median |delta close| on timestamp-matched bars **<= 2 bps**; on bars where either feed fires a
LONG/SHORT, same-action agreement **>= 0.80**; **|delta mean R| <= 0.10R** (1 bp/side).

If P0b, P0c or P0d FAILS, the study stops: no per-symbol or portfolio number is published as a
result, and the verdict doc reports exactly which gate failed and by how much.

---

## §5 Cost model (frozen)

Per side (entry and exit each), applied to executed prices, both in R and in return on notional:

| Label | bps/side | Role |
|---|---|---|
| C0 | 0 | signal-only diagnostic |
| **C2** | **1.0** | **primary.** Live SPY median absolute slippage is 0.52 bps over 40 fills (2026-10-21 `cost_check`); Alpaca is commission-free; covers small regulatory sell fees |
| C3 | 2.5 | single-stock stressed (wider spreads in AVGO/LLY/MU-class names, stop-market slippage) |
| C1 | 5.0 | #571's frozen `SLIPPAGE_BPS` (continuity with every prior hourly study) |

Also reported per symbol: **breakeven cost** (bps/side at which mean R = 0).

---

## §6 Metrics (frozen)

### §6.1 Per-symbol (H_proxy, both sides, C2 primary; C0/C3/C1 sensitivity)

Trades/yr (trades / (sessions/252)), mean R with 95% moving-block-bootstrap CI over the
time-ordered trade sequence (`overfitting_gate.block_bootstrap_ci`, default block length
`round(n^(1/3))`, `n_boot=2000`, seed 0), win rate (R > 0), profit factor, cumulative R, max
drawdown of the cumulative-R curve, median stop distance (bps of price), breakeven cost.
Split: **IS** = sessions <= 2025-04-30, **OOS** = 2025-05-01 to 2026-10-21.

**Per-symbol classification (pre-registered):**
- **EDGE**: full-window CI_low > 0 AND OOS mean R > 0 AND rule-minus-drift-control uplift > 0 (§6.4).
- **NEGATIVE**: full-window CI_high < 0.
- **NO_EDGE**: everything else.

### §6.2 Walk-forward symbol selection

Six-month OOS steps W1 2024-12-01..2025-05-31, W2 2025-06-01..2025-11-30, W3
2025-12-01..2026-05-31, W4 2026-06-01..2026-10-21. At each step a symbol from the candidate set
is included iff its trailing-12-month mean R (C2, both sides) > 0; SPY is always included.
Reported per candidate set (top-10; ETFs): concatenated OOS P&L of the selected V1 portfolio
versus SPY-only (V0) and versus the fixed all-in V1 portfolio.

### §6.3 Portfolio (non-compounding, fraction of equity, C2)

- **V0** SPY only, 10% notional (today's live sizing; the 10% cap binds on every hourly trade
  because stops are always far below 10% of price).
- **V1 shared cap** K symbols, each book capped at 10%/K notional, books independent. Max total
  open notional 10%. **Operator's constraint.**
- **V1b single slot** one position at a time across the K symbols at 10% notional; same-instant
  ties broken by fixed priority (SPY first, then SSGA weight order; ETFs: SPY, QQQ, IWM, DIA,
  XLK, XLF). Max total open notional 10%.
- **V2 per-symbol 10%** -- **LARGER EXPOSURE** (up to K x 10% open notional), comparison only.

For each: trades/day, mean daily P&L (bps of equity), annualized Sharpe of daily P&L, total
P&L, max drawdown, worst day, and total P&L in "SPY-R units" (divided by the median SPY 1R as a
fraction of equity under V0).

Risk spreading: correlation matrix of stand-alone daily P&L (each symbol at 10%), average
pairwise correlation, correlation of each symbol with SPY, **effective number of independent
bets** `N_eff = (sum eigenvalues)^2 / sum eigenvalues^2` of that correlation matrix; correlation
of 1h close-to-close returns with SPY's; concurrency (share of trading hours with k open
positions; share of multi-position hours where all positions are on the same side).

### §6.4 Survivorship mitigations (registered)

1. **Long and short reported separately** for every symbol (today's top 10 are hindsight
   winners; uptrend drift inflates LONG and deflates SHORT).
2. **Drift control:** for every actionable full bar, an unconditional entry on each side with the
   same live geometry/sizing functions (emitter columns `ctrl_*`), resolved statelessly to its
   stop/target/flatten. Rule uplift = rule mean R minus control mean R, same side, same cost. Edge
   that is only drift shows up as uplift ~ 0.
3. **Non-winner controls** BRK-B, JPM, UNH run through the identical pipeline.
4. Point-in-time top-10 membership per year is **not** attempted: SSGA publishes only the
   current file, and a membership list from memory would not be verifiable. Flagged explicitly.

### §6.5 Overfitting gate (inputs frozen per the usage note)

- Trials **N = 19** (one per symbol book: live rule, both sides, C2, 10% notional). Long/short
  splits, cost sensitivities and portfolio variants are replays of these 19, not new trials.
- **DSR** (`deflated_sharpe_ratio`): `returns_best` = daily P&L of the best full-window daily
  Sharpe among the 19; `all_trial_sharpes` = all 19 daily Sharpes. Pass `>= 0.95`.
- **PBO** (`probability_of_backtest_overfitting`): (T sessions x 19) daily P&L matrix,
  `n_splits = 16`. Pass `< 0.5`.
- **Bootstrap uplift**: monthly P&L of the candidate portfolio minus V0, `block_bootstrap_ci`,
  default block length, `n_boot = 2000`, seed 0. Pass `ci_low > 0`. Candidates: **A** = SPY +
  top-10 (V1), **B** = SPY + 5 ETFs (V1).
- `evaluate_gate` requires all three.

### §6.6 Single-stock-specific risks (descriptive)

- Flatten-before-close confirmation (code citation) and bracket-leg time-in-force.
- Overnight gap distribution (daily, 5y): p50/p95/p99/max |open/prev close - 1|; sessions with
  |gap| >= 5% per year (exposure only if a flatten scan fails).
- Event sessions (|gap| >= 3x the symbol's median |gap|, a proxy for earnings/news): rule mean R
  and median stop distance on event vs other sessions.
- Volatility vs stop geometry: median stop distance in bps; 1R in dollars at $1.02M equity under
  V0-style 10% and V1 (10%/11); median hourly range (bps).
- Short side: SSR (Rule 201) trigger days per year (daily low <= 0.9 x previous close);
  shortability / easy-to-borrow is NOT queryable without Alpaca keys (stated, not guessed).
- Feed/liquidity: median hourly consolidated share and dollar volume; order notional as a share
  of hourly dollar volume; IEX share is not measured (keys) -- any IEX figure is labelled an
  estimate.
- 59-session concordance: H_live (Yahoo 5m, top-of-hour) vs H_proxy on every symbol, same window.

---

## §7 Decision rules (frozen)

1. Any hard parity gate fails -> STOP, no results, report the failure.
2. **Add top-10 stocks (directional candidate)** only if Portfolio A passes the full overfitting
   gate (§6.5) AND the walk-forward OOS P&L of the selected top-10 portfolio exceeds V0's over
   W1-W4. Otherwise: **do not add**.
3. **ETFs instead** -- same test for Portfolio B.
4. If SPY itself is not EDGE under C2 on both the 10-year SIP baseline (B0) and the proxy window,
   the verdict states that there is no demonstrated edge to spread, and that adding symbols
   multiplies trade count around a mean that is not shown to be positive.
5. Even a pass is DIRECTIONAL (n_w = 2): the strongest permitted recommendation is "re-test the
   named symbols on Alpaca SIP 2016+ (H_live harness) before any spec/ADR". No live change
   follows from this study alone.

---

## §8 Non-goals

- No change to `decideHourly`, the detector registry, geometry, sizing, cadence, or any config.
- No new decision rule; no symbol-specific tuning (no per-symbol R, buffer or detector subset).
- No broker call; no Alpaca key lookup; no committed bar data.
- No issue filed; no PR opened; nothing merged (operator instruction).

---

## §9 Reproduction (scripts frozen in this commit)

```bash
export CLAUDE_AGENT_NO_BROKER=1
D=docs/research/2026-10-22-multi-symbol-hourly-study
venv/bin/python $D/fetch_yahoo_bars.py --out-dir <scratch>/bars
venv/bin/python $D/prepare_inputs.py --raw-dir <scratch>/bars --out-dir <scratch>/inputs \
    --sip-5m data/intraday/SPY_5min.csv --end-date 2026-10-21
deno run --allow-env --allow-read --allow-write=<scratch> scripts/emit_hourly_decisions.ts \
    --bars data/intraday/SPY_60min.csv --bars5 data/intraday/SPY_5min.csv \
    --out <scratch>/dec/SPY_sip_60m.csv --period-minutes 60 --shorts-enabled
venv/bin/python $D/run_parity_p0a.py --decisions <scratch>/dec/SPY_sip_60m.csv \
    --bars5 data/intraday/SPY_5min.csv
# P0b-P0d, the study, and the verdict tables: run_multi_symbol_study.py (added in the
# results commit; it may only consume the frozen definitions above).
```
