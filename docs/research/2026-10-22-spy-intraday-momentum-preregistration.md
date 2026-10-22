# SPY market intraday momentum (first half-hour predicts last half-hour) -- pre-registration

**Question:** Does the "market intraday momentum" effect (Gao, Han, Li & Zhou 2018) give SPY a
real, tradeable edge on 2016-2026 data that this bot could use *instead of* the hourly
candlestick rule (`decideHourly`)?

**Issue:** none filed (operator request to the research analyst, 2026-10-22).
**Date:** 2026-10-22. **Author:** Claude Code research-analyst session (research-only;
`CLAUDE_AGENT_NO_BROKER=1` in every shell; no broker call, no order endpoint, no production code
touched). **Branch:** `research/spy-intraday-momentum`.
**Motivation:** the hourly candlestick rule has no edge (2026-09-03 15-min study verdict;
2026-10-22 multi-symbol verdict on branch `research/multi-symbol-hourly`: SPY 10y -0.139R/trade
at 1 bp/side, -0.031R at zero cost). The operator wants more profit without larger positions;
the position taken with the operator is that a real edge must come before trade frequency.
**Source:** Gao, L., Han, Y., Li, S. Z., & Zhou, G. (2018). Market intraday momentum. *Journal
of Financial Economics*, 129(2), 394-414. Their sample is SPY 1993-2013. Their core claims, as
relayed in the brief and relied on here only qualitatively: the first half-hour return
(previous close to 10:00 ET, overnight gap included) predicts the last half-hour return
(15:30-16:00 ET); the 12th half-hour return (15:00-15:30) adds predictive power; the effect is
stronger on high-volatility days, high-volume days, in recessions and on macro-news days.
**Conventions inherited (not re-derived):** `2026-07-21-overfitting-gate-usage.md` (gate
thresholds), `2026-10-22-multi-symbol-hourly-preregistration.md` (cost grid, baseline B0
harness, CI method, power floors).

This document is committed **before** any intraday-momentum result exists. §9 lists exactly what
was computed before this commit (baseline parity and data-integrity checks only; no statistic
relating r1 or r12 to the last half-hour was computed).

---

## §0 Invariant framing

Per CLAUDE.md [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- **One decision rule.** The momentum rule is studied strictly as a *replacement candidate* for
  `decideHourly`, never as a second rule running beside it. Nothing here authorizes a live
  change; any adoption would need its own brainstorm, design spec and ADR.
- **No LLM in the trading path.** No model SDK anywhere in this package.
- **Paper-only guard / engineer subagents never reach the broker.** No module in this package
  constructs an Alpaca client or touches the network. Inputs are local staged files.
- **Panic / kill switch.** Not touched. Implementation implications are assessed in the verdict
  doc (feasibility section), not changed here.

Script location: the analyst role may only write under `docs/research/`, so the study code
lives in `docs/research/2026-10-22-spy-intraday-momentum-study/` and imports `backtest/`
modules read-only (`overfitting_gate`, `intraday_data`). The hourly-candlestick baseline replay
uses a verbatim vendored copy of the multi-symbol study's simulator
(`vendored_multi_symbol_hourly.py`, from commit `248da4f`; only a 4-line provenance comment
added) because that branch is unmerged.

---

## §1 Data (frozen)

- **Bars:** `/Users/TM/Desktop/github/trading-bot/data/intraday/SPY_5min.csv` (gitignored, not
  committed), Alpaca SIP, `adjustment=all`, UTC timestamps, OHLC, no volume, extended hours
  included. sha256 `65da7f617079260f974525a3023d7cd58d29640583d0a952f1952db5a8ea0a79`
  (identical to #571 and the multi-symbol study). Coverage 2016-01-04 .. 2026-08-12, 2,667
  regular sessions.
- **Baseline input:** `SPY_60min.csv` sha256
  `9971bd413ef1c08ec17414a34731ba84460f742e2ab458b1fc006702bc1e3b74`, run through the UNCHANGED
  `scripts/emit_hourly_decisions.ts --period-minutes 60 --shorts-enabled --bars5 SPY_5min.csv`.
- **Clock:** every timestamp is converted to `America/New_York` (handles DST); a bar is
  identified by its NY start time. Bar "HH:MM" below = the 5-min bar *starting* at HH:MM ET.
- **No data beyond 2026-08-12** is available (no Alpaca keys in this session). No other source
  is used.
- **Power (binding):** `backtest/intraday_data.describe_power` on this file gives `n_w = 10`
  complete 12-month windows (< the `n_w = 13` promotion bar) -> **DIRECTIONAL**. The best
  possible outcome of this study is therefore a directional result, not a promotion.

### §1.1 Price points (per session d)

| Symbol | Definition |
|---|---|
| `C_prev` | previous regular session's close: close of its 15:55 bar (12:55 bar if that session was a half-day) |
| `P10` | close of the 09:55 bar (price at 10:00) |
| `P15` | close of the 14:55 bar (price at 15:00) |
| `P1530` | close of the 15:25 bar (price at 15:30) |
| `E_in` | open of the 15:30 bar (entry fill, primary) |
| `E_in_late` | open of the 15:35 bar (entry fill, delay robustness only) |
| `X_mkt` | close of the 15:55 bar (exit E1: proxy for a market order sent at 15:59; last SIP trade before 16:00) |
| `X_moc` | open of the 16:00 bar (exit E2: proxy for the closing-auction print, the first SIP print at/after 16:00:00); falls back to `X_mkt` if no 16:00 bar |
| `C_d` | close of the 15:55 bar (the regression's close) |

Returns: `r1 = P10 / C_prev - 1`; `r12 = P1530 / P15 - 1`; `r13 = C_d / P1530 - 1` (simple
returns).

### §1.2 Session exclusions (frozen)

1. **Half-days** (NYSE 13:00 ET early closes) are excluded from every regression and trade
   sample (21 sessions): 2016-11-25, 2017-07-03, 2017-11-24, 2018-07-03, 2018-11-23,
   2018-12-24, 2019-07-03, 2019-11-29, 2019-12-24, 2020-11-27, 2020-12-24, 2021-11-26,
   2022-11-25, 2023-07-03, 2023-11-24, 2024-07-03, 2024-11-29, 2024-12-24, 2025-07-03,
   2025-11-28, 2025-12-24. (The data has post-13:00 bars on these days; they are after-hours
   trading, not a last half-hour.) A half-day's 12:55 close is still used as `C_prev` for the
   next session.
2. A session missing any bar needed for its price points (09:55, 14:55, 15:25, 15:30, 15:55)
   is excluded; a session whose previous session lacks its close bar is excluded. (Known
   case: 2019-08-12 has no bars after 15:30, so it and 2019-08-13 drop.)
3. The first session in the file (no `C_prev`) is excluded.

### §1.3 Dividend adjustment (frozen handling)

The staged bars are dividend back-adjusted (`adjustment=all`). A correct back-adjustment makes
the ex-date overnight return dividend-neutral (no mechanical drop of roughly 0.3-0.5% in `r1`);
a raw series would carry that drop and bias `r1` toward "short" on every ex-date.

- **Ex-dividend dates** (SPY pays quarterly; ex-date = third Friday of Mar/Jun/Sep/Dec, moved to
  2026-06-18 because 2026-06-19 is a holiday): 42 dates from 2016-03-18 through 2026-06-18.
- **Data check D1 (run by the study script, printed):** mean overnight return
  (`P_open_0930 / C_prev - 1`) on ex-dates minus the mean on all other sessions. A raw
  (unadjusted) series would put this near -30 to -45 bps. **Rule:** if D1 < -20 bps the
  as-staged series is treated as NOT dividend-neutral and the primary sample switches to
  "ex-dates excluded"; otherwise the primary uses the as-staged series with ex-dates included.
  (D1's value was already looked at before this commit, see §9: about -9 bps, so the expected
  primary is "included".)
- **Robustness R2 (always reported):** every primary number recomputed with the 42 ex-dates
  excluded.
- Entry and exit happen within one session, so the adjustment factor (constant within a
  session) cannot affect the trade's own return.

---

## §2 Hypotheses

- **H1 (effect exists, 2016-2026):** in `r13 = a + b1 * r1 + e`, `b1 > 0` with Newey-West HAC
  t-stat >= 1.96. Also reported: `r13 ~ r12`, and `r13 ~ r1 + r12` (`b12 > 0`, HAC t >= 1.96
  for "r12 adds power").
- **H2 (decay since publication):** `b1` estimated on 2016-2017 ("pre-2018") vs 2018-01-01 ..
  2026-08-12 ("post-2018"), plus a pooled interaction test `r13 ~ r1 + r1 * D_post` (HAC). Also
  `b1` by calendar year. **Classification:** "decayed" if post-2018 `b1` has HAC t < 1.96 AND
  its point estimate is below half of the pre-2018 point estimate; "persistent" if post-2018
  `b1` has HAC t >= 1.96; otherwise "inconclusive". Caveat fixed in advance: the paper
  circulated as a working paper before 2016, so our whole sample is post-circulation, and
  pre-2018 is only about 500 sessions.
- **H3 (tradeable):** at least one of the §3 configurations earns a positive net mean return
  per trade at the primary cost (1 bp/side) that survives the §6 criteria.
- **H4 (beats the incumbent):** the momentum rule's net P&L at the same sizing and cost exceeds
  the hourly candlestick rule's (B0) on the same sessions. Reported head-to-head; not a gate.

HAC: Bartlett kernel, lag `L = floor(4 * (T/100)^(2/9))` (Newey-West 1994 rule), computed per
sample. Regressions are OLS with intercept on the §1.2-filtered sessions; `R^2` reported in %.

---

## §3 Trading configurations (the trial set, K = 6)

Every configuration enters at most once per session at `E_in` (15:30) and exits the same
session at the close. Side = sign of the signal; zero signal = no trade. No stop, no target,
no leverage, no overnight holding. Long AND short (the paper's timing strategy is two-sided).

Signal variants (3):
- **V1 -- r1 sign.** Long if `r1 > 0`, short if `r1 < 0`, every eligible session.
- **V2 -- r1 and r12 agree.** Long if `r1 > 0` and `r12 > 0`; short if both `< 0`; otherwise
  flat.
- **V3 -- r1 sign on high-volatility days.** As V1, but only when the session's first-half-hour
  realized volatility `RV1` is in the top tercile of its own trailing history; otherwise flat.
  `RV1 = sqrt(sum of squared 5-min log returns over the six 09:30-09:55 bars)`, each return =
  `log(close / open)` for the 09:30 bar and `log(close_k / close_{k-1})` thereafter (overnight
  gap excluded). Threshold = 2/3 quantile of `RV1` over the previous up-to-252 eligible
  sessions (strictly prior, no look-ahead), requiring at least 120 prior sessions (V3 is flat
  before that). Volume conditioning (the paper's other strong split) is impossible: the bars
  have no volume. Recession and macro-news conditioning are not tested (no calendar input;
  avoided to keep K small).

Exit models (2):
- **E1 -- market order at 15:59:** exit at `X_mkt`.
- **E2 -- market-on-close (MOC):** exit at `X_moc`.

`K = 3 x 2 = 6` configurations. **Primary designated configuration: V1-E1** (the paper's
headline signal; a plain market order the existing Alpaca client can already place). The
overfitting gate (§6) is applied to the best of the 6 by full-sample Sharpe, with all 6 counted
as trials.

Non-trial diagnostics (reported, never selectable, never promoted): always-long 15:30->close
(drift control); long-only and short-only legs of each configuration; entry-delay robustness
(`E_in_late`, 15:35); ex-dividend-excluded robustness (R2); per-year tables.

---

## §4 Sizing and cost model (frozen)

- **Sizing:** identical to the live `computeSizing` notional cap: each trade has notional =
  `SIZING_NOTIONAL_CAP_PCT = 10%` of equity. (Without a stop the risk leg
  `SIZING_RISK_PCT = 1%` / stop distance never binds; for the B0 replay it also never binds on
  SPY, since stops are about 26 bps.) Non-compounding. Dollar figures use equity
  **$1,020,000**, i.e. $102,000 per trade, so 1 bp of notional = $10.20.
- **Per-trade return on notional:** long `(X*(1-c) - E*(1+c)) / E`; short
  `(E*(1-c) - X*(1+c)) / E`, `c` = cost per side.
- **Cost grid (bps per side):** 0, **0.5** (measured live SPY median slippage, about 0.52),
  **1 (primary)**, 2. Break-even cost per side = gross mean bps / 2 (linear).
- **R-equivalent:** the momentum rule uses no stop, so R is reported only as a unit conversion
  for comparison with the candlestick rule: R-equivalent = net bps per trade / B0's median stop
  distance in bps (26.5 bps, measured on the B0 replay, see §9).
- **Same costs for B0:** B0 is evaluated at the same cost grid with the same notional, on the
  same sessions (2016-01-04 .. 2026-08-12).

---

## §5 Metrics (per configuration, per cost)

Trades, trades/yr (eligible sessions / 252 as the year count), mean net return per trade in bps
with 95% CI (moving-block bootstrap via `overfitting_gate.block_bootstrap_ci`, block length
`round(n^(1/3))`, `n_boot = 2000`, seed 0), mean in R-equivalent, win rate, profit factor,
annualized Sharpe of the daily P&L series (all eligible sessions, 0 on flat days, x sqrt(252))
with a 95% moving-block bootstrap CI (same block rule, `n_boot = 2000`, seed 0), total P&L (%
of equity and $), max drawdown of cumulative non-compounded P&L (% of equity and $), break-even
cost.

**Splits:**
- **IS / OOS:** IS = 2016-01-04 .. 2020-12-31; OOS = 2021-01-01 .. 2026-08-12. All 6 configs
  reported on both.
- **Walk-forward (expanding, yearly):** for each test year Y = 2018 .. 2026, select the config
  with the highest daily-P&L Sharpe at 1 bp/side over all sessions before Y, and trade it in
  Y. Report the selected config per year and the concatenated OOS P&L.
- **By year:** mean net bps/trade at 1 bp for V1-E1 and for the best config.

---

## §6 Pass/fail thresholds and verdict ladder (frozen)

**Overfitting gate** (`backtest/overfitting_gate.evaluate_gate`, thresholds unchanged):
- DSR >= 0.95 on the best config's daily P&L at 1 bp/side, `all_trial_sharpes` = the 6
  configs' non-annualized daily Sharpes (N = 6).
- PBO < 0.5, CSCV with `S = 16` on the `(T, 6)` daily-P&L matrix at 1 bp/side.
- Bootstrap: monthly P&L of the best config minus baseline, `ci_low > 0`. **Baseline = cash
  (zero P&L)**, the strict choice; uplift over B0 is reported separately as head-to-head (a
  negative-expectancy baseline would make "uplift" trivially easy). Block length
  `round(n^(1/3))`, `n_boot = 1000`, seed 0 (the module defaults).

**Verdict ladder** (applied to the gate's best config; V1-E1 reported alongside regardless):

- **EDGE (DIRECTIONAL)** -- all of: (a) mean net bps/trade at 1 bp/side has 95% CI low > 0;
  (b) the overfitting gate passes on all three legs; (c) OOS (2021+) mean net bps/trade at
  1 bp/side > 0; (d) walk-forward concatenated OOS P&L at 1 bp/side > 0. Because power is
  DIRECTIONAL (`n_w = 10 < 13`), this would justify a design brainstorm plus a paper shadow
  run, not a live switch.
- **WEAK** -- point estimate of mean net bps/trade at 1 bp/side > 0, but any of (a)-(d) fails.
- **NO_EDGE** -- point estimate at 1 bp/side <= 0.

Separately reported, never overriding the ladder: the same ladder evaluated at 0.5 bps/side
(the measured live cost), labelled as such.

---

## §7 Head-to-head with the current hourly candlestick rule (B0)

B0 = the unchanged live `decideHourly` + live geometry, both sides, replayed by the vendored
multi-symbol simulator (top-of-hour grid, 5Min fills and exits, flatten scan, cooldown, day cap
3), exactly the multi-symbol study's §3.1 baseline. Parity gate **P0** (§9) must reproduce that
study's published B0 exactly before any comparison is made. Compared on the same sessions, same
10% notional, same cost grid: trades/yr, mean net bps/trade, total P&L (% and $), annualized
Sharpe, max DD, daily-P&L correlation, and the bootstrap CI of the monthly P&L difference
(momentum best config minus B0, and V1-E1 minus B0). B0 flattens at the 15:07 ET scan (fills
about 15:10), so the two rules never hold a position at the same time.

---

## §8 What would change the conclusions (stated in advance)

- If D1 shows the series is not dividend-neutral, the primary switches per §1.3.
- If P0 fails, the head-to-head is not reported (momentum results still are).
- Any later change to a definition, sample, threshold or the trial set is made only by a dated
  addendum below this document, never by editing it, and is disclosed in the verdict.

---

## §9 Computed before this commit (harness and data-integrity evidence only)

- **P0 -- B0 parity: PASS.** `run_parity_b0.py` on the unchanged emitter's output reproduces
  the published B0 exactly: 2,667 sessions (10.58 years); n = 2,478, 234 trades/yr, mean R
  -0.031 [-0.073, +0.004] at 0 bps and -0.139 [-0.182, -0.101] at 1 bp/side, win 41.8%.
  B0's median stop distance is 26.5 bps of entry (mean 35.8); its last exits are at 15:10 ET.
- **Session structure:** 2,667 sessions; every session has a 09:30 first bar; 2,666 have a
  15:55 bar (2019-08-12 stops at 15:30); half-days carry after-hours bars to 15:55, hence the
  explicit half-day list (confirmed in the data by a post-13:00 range collapse on those dates).
  Missing 14:55/15:25/15:30 bars occur only on half-days.
- **Close proxies:** `X_moc` (16:00 bar open) vs `X_mkt` (15:55 bar close): median absolute
  difference 0.0 bps, p90 0.48 bps, p99 1.12 bps, max 9.5 bps (2,666 sessions). E1 and E2 are
  therefore near-duplicates on this data; both are kept as pre-declared trials.
- **D1 preview:** overnight return on the 41 third-Friday ex-dates in the file up to
  2026-03-20 averaged -4.95 bps vs +3.95 bps on all sessions (sd about 73 bps), i.e. about
  -9 bps, far from the -30 to -45 bps a raw series would show.

No statistic involving `r13`, or relating `r1`/`r12` to anything after 15:30, was computed
before this commit.
