# SPY market intraday momentum (first half-hour predicts last half-hour) -- verdict

**Question:** Does the "market intraday momentum" effect (Gao, Han, Li & Zhou 2018, JFE) give
SPY a real, tradeable edge on 2016-2026 data that this bot could use *instead of* the hourly
candlestick rule (`decideHourly`)?
**Issue:** none filed (operator request, 2026-10-22). **Date:** 2026-10-22.
**Pre-registration:** `docs/research/2026-10-22-spy-intraday-momentum-preregistration.md`
(frozen in commit `0742897`, strictly before any momentum result; Addendum A1 added in the
results commit). **Code:** `docs/research/2026-10-22-spy-intraday-momentum-study/`.
**Author:** Claude Code research-analyst session (`CLAUDE_AGENT_NO_BROKER=1` throughout; no
broker call; no production code touched).

## Verdict: NO_EDGE. Do not replace the candlestick rule with intraday momentum.

- **The effect is not present on SPY 2016-2026.** In `r13 = a + b1 * r1`, b1 = +0.016 with
  HAC t = +0.59 and R^2 = 0.14% (n = 2,643). The 12th half-hour adds nothing significant
  (r12: b = +0.073, t = +0.99). Both together explain 0.36% of the last half-hour's variance.
  Without the three March-2020 circuit-breaker sessions, b1 turns negative (-0.013, t -0.79).
- **Decay test (H2): "inconclusive" under the frozen rule.** The reason is that there is
  nothing to decay from. b1 is +0.005 (t 0.19) in 2016-2017 and +0.017 (t 0.58) in 2018-2026,
  and the interaction t is +0.28. Only one calendar year is significant, 2021, and its sign is
  *negative* (b1 = -0.099, t -2.81, a reversal). Our whole sample also post-dates the paper's
  working-paper circulation.
- **As a trading rule it loses before costs and loses clearly after them.** The headline
  configuration V1-E1 (trade the sign of r1 at 15:30, exit at the close) averages -0.29 bps
  per trade gross (95% CI -1.52 to +1.17). It averages -1.29 bps at the measured live cost of
  0.5 bps/side and **-2.29 bps at the primary 1 bp/side (CI -3.52 to -0.83)**. Its break-even
  cost is -0.15 bps/side, so it does not break even at zero cost. **None of the 6
  pre-registered configurations is positive at 0.5 or 1 bp/side.** The best gross figure is
  +0.44 bps/trade (V2-E1, CI -1.11 to +2.21). That is below the 1-2 bps a round trip costs.
- **The overfitting gate fails** (DSR 0.0014, bootstrap CI on monthly P&L [-0.036%,
  -0.0001%]). Walk-forward selection loses -2.82% of equity (-$28.8k) over 2018-2026.
- **It is not better than the incumbent.** At 1 bp/side and the same 10% notional, the
  candlestick rule (B0) loses -1.65 bps/trade and -$41.8k over 10.6 years. Momentum V1-E1
  loses -2.29 bps/trade and -$61.7k. The low-frequency variants lose less in total only
  because they trade less. Per trade, none of them beats B0 by more than noise.

Power is **DIRECTIONAL** (`n_w = 10 < 13`). This verdict authorizes no live change. Given
that the point estimates are at or below zero before costs, a re-test on longer data has a
poor prior.

---

## §0 Invariant framing and scope

The study evaluated intraday momentum only as a *replacement candidate* for `decideHourly`,
never as a second rule. No LLM is involved, no Alpaca client is constructed, nothing in
`supabase/functions/`, `backtest/` or `scripts/` was modified, and no bar data is committed.
The baseline B0 replays the unchanged live rule through the unchanged emitter
(`scripts/emit_hourly_decisions.ts`).

**Deviations from the pre-registration / brief (disclosed):**
1. **Implementation deviation in the first run (corrected).** The first execution of
   `run_momentum_study.py` wrongly added `RV1` (the V3 volatility measure) to the session
   eligibility filter. That dropped 3 sessions (2020-03-09, 2020-03-12, 2020-03-16, which are
   circuit-breaker days with missing 09:3x bars). §1.2 makes eligibility depend only on the
   price-point bars, so the code was corrected to match it, and all numbers below come from
   the corrected run. First-run figures, for the record: b1 = -0.0125 (t -0.79); V1-E1 mean
   -0.49 bps gross and -2.49 bps at 1 bp/side; gate best V3-E1, DSR 0.0008, FAIL. The verdict
   is the same either way. The swing shows how much 3 extreme days move the full-sample
   regression (§3.1). See Addendum A1 in the pre-registration.
2. **Year count in the head-to-head (§5):** both rules use all 2,667 sessions as the year
   denominator so that they share one denominator. That gives momentum trades/yr 249.1 there
   vs 251.3 in §3 (eligible sessions). The P&L figures are unaffected.
3. **Script location:** the scripts are under `docs/research/` because the analyst role can
   only write there. The B0 replay uses a verbatim vendored copy of the unmerged multi-symbol
   simulator (`vendored_multi_symbol_hourly.py`, from commit `248da4f`).
4. **Not tested** (pre-registered as out of scope): volume conditioning (the bars have no
   volume), recession and macro-news-day conditioning (no calendar input).

---

## §1 Data and parity

| Check | Result |
|---|---|
| Bars | Alpaca SIP 5Min, `adjustment=all`, sha256 `65da7f61...0a79` (same file as #571 and the multi-symbol study), 2016-01-04 .. 2026-08-12 |
| Power (`describe_power`) | DIRECTIONAL, `n_w = 10` |
| Sessions | 2,667; 21 half-days excluded; 3 more excluded (2016-01-04: no previous close; 2019-08-12: no bars after 15:30; 2019-08-13: its previous close missing) -> **2,643 eligible** |
| MOC proxy fallback | 0 eligible sessions lack the 16:00 bar |
| **P0: B0 parity** | **PASS**, exact: n = 2,478, 234 trades/yr, -0.031R gross / -0.139R at 1 bp/side, matching the multi-symbol verdict §3.1 |
| **D1: dividend neutrality** | ex-date overnight mean -2.05 bps vs +4.10 bps on other sessions -> D1 = **-6.15 bps** (a raw series would be about -30 to -45). Above the -20 bps switch threshold, so the primary keeps the 42 ex-dates. R2 (ex-dates excluded) is reported throughout and changes nothing |
| Internal consistency (post-hoc) | r1 and r13 rebuilt from the separately staged `SPY_30min.csv` match the 5-min-derived values exactly (max diff 0.000 bps, sign agreement 1.0000, n = 2,643). This confirms the timezone, DST and bar-alignment handling |
| Close proxies | `X_moc` (16:00 bar open) vs `X_mkt` (15:55 bar close): median diff 0.0 bps, p99 1.1 bps. E1 and E2 are near-duplicates on this data |

---

## §2 Key numbers

| Item | Value |
|---|---|
| r13 ~ r1, full 2016-2026 | b1 = +0.0160, HAC t = +0.59, R^2 = 0.14% (n = 2,643, NW lag 8) |
| r13 ~ r12 | b12 = +0.0728, t = +0.99, R^2 = 0.24% |
| r13 ~ r1 + r12 | b1 +0.0148 (t 0.56), b12 +0.0697 (t 0.93), R^2 = 0.36% |
| pre-2018 / post-2018 b1 | +0.0054 (t 0.19, n = 499) / +0.0168 (t 0.58, n = 2,144); interaction t = +0.28 |
| V1-E1 (r1 sign, 15:30 -> 15:59 mkt) | 251 trades/yr; **-0.29 bps gross; -1.29 @ 0.5; -2.29 @ 1 [-3.52, -0.83]; -4.29 @ 2**; break-even -0.15 bps/side |
| V1-E1 @ 1 bp, $ on $1.02M | total -6.04% = **-$61,655** over 10.6 years; Sharpe -1.17 [-2.14, -0.36]; max DD -6.30% (-$64,284) |
| Best config (gate) V3-E1 | 80 trades/yr; -0.62 bps gross; -2.62 @ 1 bp [-5.28, +0.23]; -$22,476 total |
| Overfitting gate (N = 6) | DSR 0.0014 (FAIL), PBO 0.00 (pass, see §3.3), monthly CI [-0.0359%, -0.0001%] (FAIL) -> **FAIL** |
| Walk-forward 2018-2026 | -2.82% (-$28,809) |
| B0 candlestick @ 1 bp, same sizing | 234 trades/yr; -1.65 bps/trade [-3.16, -0.44]; -4.10% = -$41,830; Sharpe -0.67 |

---

## §3 Results

### §3.1 Predictive regressions (H1, H2)

Newey-West HAC (Bartlett), lag `floor(4 (T/100)^(2/9))`. r1 = previous close -> 10:00, r12 =
15:00 -> 15:30, r13 = 15:30 -> close.

| Sample | n | b1 (t) | R^2 r1 | b12 (t) | R^2 r12 | R^2 both |
|---|---|---|---|---|---|---|
| Full 2016-2026 | 2,643 | +0.0160 (+0.59) | 0.14% | +0.0728 (+0.99) | 0.24% | 0.36% |
| Pre-2018 (2016-2017) | 499 | +0.0054 (+0.19) | 0.03% | -0.0923 (-0.97) | 1.00% | 1.01% |
| Post-2018 (2018-2026) | 2,144 | +0.0168 (+0.58) | 0.15% | +0.0908 (+1.12) | 0.35% | 0.47% |
| IS 2016-2020 | 1,245 | +0.0496 (+1.18) | 1.16% | -0.0149 (-0.11) | 0.01% | 1.20% |
| OOS 2021-2026 | 1,398 | -0.0233 (-1.64) | 0.40% | +0.1513 (+2.76) | 1.51% | 1.94% |
| Full, ex-dates excluded (R2) | 2,601 | +0.0161 (+0.59) | 0.15% | +0.0855 (+1.20) | 0.33% | 0.45% |
| High-RV1 tercile days (diag.) | 840 | -0.0102 (-0.41) | 0.05% | | | |
| Other days (diag.) | 1,680 | -0.0209 (-1.62) | 0.26% | | | |

b1 by year: 2016 +0.012 (t 0.36), 2017 -0.018 (-0.59), 2018 -0.032 (-0.56), 2019 +0.001
(0.04), 2020 +0.078 (1.23), **2021 -0.099 (-2.81)**, 2022 -0.024 (-0.84), 2023 +0.023
(0.91), 2024 -0.026 (-0.96), 2025 -0.021 (-0.62), 2026 to Aug +0.012 (0.60). The
unconditional last half-hour averages -0.44 bps (sd 31 bps); corr(r1, r13) = +0.038.

What the table shows:
- **H1 is not supported.** No sample reaches t >= 1.96 for b1 with a positive sign. The
  paper's high-volatility amplification is also absent: b1 on high-RV1 days is negative.
- **The full-sample sign depends on three days.** 2020-03-09, 03-12 and 03-16 had r1 of
  -588, -574 and -936 bps, and each kept falling into the close (r13 -126, -115, -268 bps).
  With them b1 = +0.016; without them b1 = -0.013 (post-hoc; trimming the top 1% |r1| gives
  -0.017, t -1.29). Crash days of that kind are where the momentum story is strongest, but
  three days are not a tradeable edge, and on those days V3's volatility measure is
  undefined, so V3 does not trade them.
- **H2 = "inconclusive" under the frozen rule.** Post-2018 b1 is not below half of
  pre-2018's, and it is not significant. The plain reading is that the effect was not there
  in 2016-2017 either. The only significant year (2021) shows a reversal.
- **r12 in 2021-2026 (t +2.76) is one cell among 18** (6 samples x 3 models), it is
  insignificant in the full sample, and its sign flips vs 2016-2017. A post-hoc r12-sign
  trading check (`diag_posthoc.py`, not a candidate) earns +0.72 bps gross (CI -0.32 to
  +1.82) and -1.28 bps at 1 bp/side over the full sample, and -1.31 bps in 2021+. It is not
  worth a follow-up pre-registration at retail cost levels.

### §3.2 Trading configurations (H3), 2,643 eligible sessions, 10% notional, $1.02M

Mean net bps per trade by cost (bps/side); 95% moving-block CIs at 1 bp; $ = total over
2016-01-05 .. 2026-08-12.

| Config | Trades/yr | 0 | 0.5 | **1** [95% CI] | 2 | Break-even bps/side | Win @1 | PF @1 | Sharpe @1 [CI] | Total @1 | Total @0.5 | Max DD @1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **V1-E1** r1, 15:59 mkt | 251 | -0.29 | -1.29 | **-2.29** [-3.52, -0.83] | -4.29 | -0.15 | 43.1% | 0.78 | -1.17 [-2.14, -0.36] | -$61,655 | -$34,769 | -$64,284 |
| V1-E2 r1, MOC | 251 | -0.32 | -1.32 | -2.32 [-3.54, -0.86] | -4.32 | -0.16 | 43.1% | 0.77 | -1.18 [-2.16, -0.37] | -$62,453 | -$35,566 | -$65,046 |
| V2-E1 r1 & r12 agree, mkt | 128 | +0.44 | -0.56 | -1.56 [-3.11, +0.21] | -3.56 | +0.22 | 43.7% | 0.85 | -0.52 [-1.36, +0.07] | -$21,345 | -$7,687 | -$21,929 |
| V2-E2 r1 & r12 agree, MOC | 128 | +0.40 | -0.60 | -1.60 [-3.15, +0.18] | -3.60 | +0.20 | 43.5% | 0.84 | -0.53 [-1.37, +0.06] | -$21,823 | -$8,165 | -$22,421 |
| V3-E1 r1 on high-vol days, mkt | 80 | -0.62 | -1.62 | -2.62 [-5.28, +0.23] | -4.62 | -0.31 | 45.1% | 0.83 | -0.51 [-1.29, +0.10] | -$22,476 | -$13,908 | -$26,868 |
| V3-E2 r1 on high-vol days, MOC | 80 | -0.67 | -1.67 | -2.67 [-5.34, +0.17] | -4.67 | -0.34 | 45.1% | 0.82 | -0.52 [-1.30, +0.09] | -$22,888 | -$14,320 | -$27,145 |

R-equivalent (unit conversion only; there is no stop): net bps / 26.48 bps (B0's median stop).
V1-E1 at 1 bp = -0.087R; V3-E1 = -0.099R; V2-E1 = -0.059R. Gross: V1-E1 -0.011R, V2-E1
+0.017R.

**Scale, for the operator's "more profit at the same size" question.** At 10% notional on
$1.02M, 1 bp of net edge per trade is $10.20. At ~250 trades/yr, each +1 bp/trade of edge is
worth about **$2,550/yr (0.25% of equity)**. Even a strategy that cleared costs by a full basis
point would add a few thousand dollars a year at today's size. Here the measured edge is
negative.

Non-trial diagnostics (all at 1 bp/side unless noted):
- **Always long 15:30 -> close** (drift control): -0.44 bps gross, -2.44 bps net. The last
  half-hour has no drift to harvest either.
- **Long-only / short-only legs of V1-E1:** -2.66 bps (140/yr) / -1.83 bps (111/yr). Both
  sides lose, so dropping shorts (`HOURLY_SHORTS_ENABLED=false`) does not rescue it. The same
  holds for V2 (-1.45 / -1.71) and V3 (-2.61 / -2.64).
- **Entry 5 min later (15:35):** V1-E1 +0.24 bps gross, -1.76 bps net; V2-E1 +0.70 gross,
  -1.30 net. A slower implementation does not change the picture. The small gross improvement
  is noise-level (CIs span zero).
- **Ex-dividend dates excluded (R2):** V1-E1 -0.34 gross, -2.34 net; V2-E1 +0.56 / -1.44;
  V3-E1 -0.88 / -2.88. Unchanged.

### §3.3 IS / OOS, walk-forward, by year

| Config | IS 2016-2020 gross | IS @1 [CI] | OOS 2021-2026 gross | OOS @1 [CI] |
|---|---|---|---|---|
| V1-E1 | +0.09 | -1.91 [-3.76, +0.43] | -0.63 | -2.63 [-3.98, -1.10] |
| V1-E2 | +0.05 | -1.95 [-3.79, +0.39] | -0.65 | -2.65 [-4.00, -1.13] |
| V2-E1 | +0.89 | -1.11 [-3.43, +1.96] | +0.06 | -1.94 [-3.74, -0.01] |
| V2-E2 | +0.85 | -1.15 [-3.47, +1.88] | +0.03 | -1.97 [-3.76, -0.04] |
| V3-E1 | +0.41 | -1.59 [-6.16, +4.07] | -1.47 | -3.47 [-6.51, -0.46] |
| V3-E2 | +0.34 | -1.66 [-6.20, +4.00] | -1.51 | -3.51 [-6.53, -0.50] |

Every configuration is weaker out of sample than in sample, and every one is negative net in
both halves.

**Walk-forward** (expanding window, yearly re-selection by trailing Sharpe at 1 bp):
2018 V3-E1 -0.49%, 2019 V3-E1 -0.15%, 2020 V3-E1 +0.16%, 2021 V3-E1 -0.45%, 2022 V3-E1
-0.92%, 2023 V2-E1 -0.16%, 2024 V2-E1 -0.28%, 2025 V2-E1 -0.42%, 2026 V2-E1 -0.13%.
**Concatenated OOS: -2.82% of equity (-$28,809).** Every trailing Sharpe used for selection
was itself negative (-0.24 to -0.85 annualized). The selector was choosing the least-bad
loser, not a winner.

**By year, V1-E1 mean net bps at 1 bp:** 2016 -2.5, 2017 -3.1, 2018 -2.8, 2019 -2.1, 2020
+0.8, 2021 -5.5, 2022 -3.9, 2023 -0.0, 2024 -2.3, 2025 -2.1, 2026 -1.4. Only 2020 (the COVID
crash year) is positive. V3-E1: 2020 +1.3 and 2023 +0.4 (15 trades) are the only positive
years.

**Overfitting gate** (N = 6 trials, 1 bp/side, daily P&L, baseline = cash). Non-annualized
daily Sharpes: V1-E1 -0.073, V1-E2 -0.074, V2-E1 -0.033, V2-E2 -0.033, V3-E1 -0.032,
V3-E2 -0.033. Best = V3-E1. **DSR 0.0014 (< 0.95, FAIL); PBO 0.000 (< 0.5, pass); monthly
P&L mean -0.017% with CI [-0.0359%, -0.0001%] (FAIL). Gate FAIL.** The PBO pass carries no
information about profitability. When every configuration loses roughly the cost it pays,
the one that trades least ranks best in every split, so in-sample rank "transfers"
perfectly.

### §3.4 Verdict ladder (frozen §6)

- Best config V3-E1: mean net at 1 bp = -2.62 bps <= 0 -> **NO_EDGE**.
- V1-E1 (designated primary): -2.29 bps -> **NO_EDGE**.
- At the measured live cost (0.5 bps/side, labelled): every configuration is <= -0.56 bps ->
  **NO_EDGE**.

---

## §4 Head-to-head with the hourly candlestick rule (H4)

Same sessions (2016-01-04 .. 2026-08-12), same 10% notional, same costs. B0 = the unchanged
live `decideHourly`, both sides, replayed through the parity-verified simulator. Year count =
2,667 sessions for both rules.

| Rule | Trades/yr | Gross bps/trade | @0.5 bps | @1 bp [95% CI] | Total @0.5 | Total @1 | Sharpe @1 [CI] | Max DD @1 |
|---|---|---|---|---|---|---|---|---|
| **B0 candlestick (current)** | 234 | +0.35 | -0.65 | -1.65 [-3.16, -0.44] | -$16,554 | -$41,830 | -0.67 [-1.32, -0.16] | -$55,832 |
| Momentum V1-E1 | 249 | -0.29 | -1.29 | -2.29 [-3.52, -0.83] | -$34,769 | -$61,655 | -1.16 [-2.11, -0.37] | -$64,284 |
| Momentum V3-E1 (gate best) | 79 | -0.62 | -1.62 | -2.62 [-5.28, +0.23] | -$13,908 | -$22,476 | -0.50 [-1.28, +0.07] | -$26,868 |
| Momentum V2-E1 | 127 | +0.44 | -0.56 | -1.56 [-3.11, +0.21] | -$7,687 | -$21,345 | -0.52 [-1.36, +0.07] | -$21,929 |

(The V2-E1 row's Sharpe and max DD come from §3.2, i.e. the eligible-session daily series. Its
totals are identical on either denominator.)

Monthly P&L difference at 1 bp (block bootstrap, 2,000 resamples): V1-E1 minus B0 -0.015%
per month, CI [-0.059%, +0.036%]; V3-E1 minus B0 +0.015%, CI [-0.021%, +0.055%]. Neither is
distinguishable from zero. Daily P&L correlation with B0: -0.08 (V1-E1), -0.07 (V3-E1). The
rules never overlap in time: B0 is flat by about 15:10 ET.

Reading: the candlestick rule's B0 native mean is -0.139R per trade at 1 bp, but in
bps-of-notional at 10% size it is -1.65 bps/trade, which is *less* negative than momentum
V1-E1's -2.29. The momentum variants that lose fewer dollars do so only because they trade
one-half (V2) to one-third (V3) as often, and so pay one-half to one-third of the costs. That
is "trade less", not "found an edge", and it is equally available by trading the existing
rule less. **Replacing B0 with intraday momentum would swap one zero-edge rule for another.**

(B0's "R-equivalent" with the 26.48 bps unit is -0.062R at 1 bp. That differs from its native
-0.139R because native R divides each trade by its own stop, which overweights tight-stop
trades. Dollar figures are the like-for-like comparison.)

---

## §5 Feasibility for this bot (assessment only; not recommended given NO_EDGE)

If a future, better-evidenced version of this signal were ever adopted, these would be the
required changes:

1. **One decision rule.** Under CLAUDE.md Architectural invariants it must **replace**
   `decideHourly` (the frozen 14-detector registry, tie-break and cooldown) as the single
   decision rule, never run beside it. That means a fresh brainstorm, a design spec and an
   ADR. The new rule is a pure function of (previous close, 10:00 price, optionally the
   15:00/15:30 prices, trailing RV1 history), so signal reproducibility from bars is
   preserved.
2. **Scheduling.** `hourly-check` runs at `7 13-21 * * 1-5` UTC (:07 past each hour), and
   its session-close flatten happens at the scan where `clock.nextClose - now <= 1 h` (the
   15:07 ET run, fills about 15:10). A 15:30 ET entry needs a new cron slot. Two UTC slots
   (19:30 and 20:30, gated by `/v2/clock` and the time-to-close) would cover DST, following
   the daily-check two-slot pattern. The existing 15:07 flatten logic would have to go, or
   be redefined, because the new rule's position only exists after 15:30.
3. **Exit at the close.** E1 (market order at about 15:59) needs a second invocation at
   about 15:59 ET. Edge Function cold start plus the order poll leave little margin, and a
   market order that arrives after 16:00 must never be queued into the next session (that
   would need fail-toward-flat handling). E2 (MOC) needs a new guarded helper, or a
   `time_in_force: "cls"` option. Today `placeMarketOrder` hard-codes `time_in_force: "day"`
   (`_shared/alpaca.ts`). Alpaca's MOC submission/cancel cutoff (believed to be 15:50 ET) and
   paper-account support for `cls` are **[to verify]**. On this data E1 and E2 price within
   about 0.5 bps of each other (p90), so MOC would be preferred for operational simplicity:
   one invocation at 15:30 places the entry and the MOC exit.
4. **Paper-only guard.** Any new order helper (`cls`/MOC) must sit behind the same three
   checks (`paper === true`, paper base URL, `/v2/account` paper marker) and `checkGuard()`
   (`CLAUDE_AGENT_NO_BROKER`), with mocked tests.
5. **Panic (side-aware).** `panic?action=liquidate` already calls `cancelAllOrders()` and then
   the side-aware `closePosition()`. A resting MOC order adds a new hazard: if panic fires
   after the exchange's MOC cancel cutoff, the MOC may not be cancellable. A panic market
   close plus a later MOC fill could then open a *reverse* position at the close. That
   interaction would need explicit design and tests.
6. **Shorts.** The rule is two-sided. `docs/CURRENT_CONFIG.md` lists
   `HOURLY_SHORTS_ENABLED=false`, while the multi-symbol study found live SHORT entries since
   2026-09-04. A long-only version also loses (§3.2).
7. **Data feed.** Live bars default to IEX (`ALPACA_DATA_FEED=iex`); this study used SIP.
   r1's sign on small-move days would sometimes differ on IEX.
8. **Frequency trade-off.** At most 1 trade per day (V1 about 250/yr, V2 about 128/yr, V3
   about 80/yr), against B0's 234/yr at up to 3 per day. At 10% notional, a 30-minute hold
   at about 31 bps sd moves about $320 per trade (1 sd). Per-trade risk is similar to B0's
   1R of about $270-290.

---

## §6 Caveats

- **Power:** `n_w = 10` -> DIRECTIONAL. That is about 2,640 daily observations, enough to
  rule out an R^2 of the size the literature reports for 1993-2013 (a few percent) with HAC
  t-stats far from significance. It is not enough to rule out a tiny effect, and a tiny
  effect would be untradeable anyway.
- **Price proxies:** E1 uses the 15:55 bar close as the 15:59 fill, and E2 uses the 16:00
  bar open as the auction print. Neither is the official closing price. The two differ by a
  median of 0.0 bps, so this cannot flip the sign of anything here.
- **Costs:** 0.5 bps/side is the measured live SPY median. A MOC fill pays no half-spread
  but can still carry auction impact. At 10% notional (about 130-150 SPY shares) impact is
  negligible. Even at 0 cost, no configuration has a CI above zero.
- **Conditioning not tested:** volume (no volume data), recessions, macro-news days. The
  2020 crash days are the clearest momentum days in the sample. A "crash-only" rule would
  trade a handful of times per decade.
- **Literature context (qualitative):** later work attributes market intraday momentum to
  hedging flows, e.g. dealer gamma hedging (Baltussen, Da, Lammers & Martens 2021, JFE).
  That would make its sign regime-dependent, which fits the positive 2020 / negative 2021
  pattern here. This is offered as context only; it was not tested.

---

## §7 Recommendation

- **Do not implement** intraday momentum as a replacement for `decideHourly`. It has no
  edge on SPY 2016-2026 at any cost level, it fails the overfitting gate, and it loses more
  per trade than the current rule.
- No Engineer change is proposed. The operator question "more profit without larger
  positions" remains open. Two zero-edge rules (candlestick, intraday momentum) have now been
  measured on the same harness. The 10% notional cap means even a real 1 bp/trade edge is
  worth only about $2.5k/yr per 250 trades.
- If the backtest scripts are moved to `backtest/`, add `backtest/tested_cells.py` ledger
  records for the 6 configurations (V1/V2/V3 x E1/E2, SPY 5Min SIP 2016-2026, NO_EDGE).

---

## §8 Reproduction

```bash
export CLAUDE_AGENT_NO_BROKER=1
D=docs/research/2026-10-22-spy-intraday-momentum-study
S=<scratch>
B=/Users/TM/Desktop/github/trading-bot/data/intraday     # gitignored staged SIP bars
deno run --allow-env --allow-read --allow-write=$S scripts/emit_hourly_decisions.ts \
    --bars $B/SPY_60min.csv --bars5 $B/SPY_5min.csv \
    --out $S/dec/SPY_sip_60m.csv --period-minutes 60 --shorts-enabled
venv/bin/python $D/run_parity_b0.py --decisions $S/dec/SPY_sip_60m.csv --bars5 $B/SPY_5min.csv
venv/bin/python $D/run_momentum_study.py --bars5 $B/SPY_5min.csv \
    --b0-decisions $S/dec/SPY_sip_60m.csv --json-out $S/momentum_results.json
venv/bin/python $D/diag_posthoc.py --bars5 $B/SPY_5min.csv --bars30 $B/SPY_30min.csv   # post-hoc
```

Input provenance: `SPY_5min.csv` sha256 `65da7f617079...a0a79`, `SPY_60min.csv`
`9971bd413ef1...e3b74` (both re-verified this session). Python 3.9.6, numpy 2.0.2, pandas
2.2.3, deno 2.9.4. All bootstraps are seeded (seed 0), so every number above is
bit-reproducible.
