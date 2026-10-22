# Multi-symbol hourly candlestick rule (SPY top-10 holdings and broad ETFs) -- verdict

**Question:** Should the live hourly candlestick bot (`decideHourly`) trade other symbols in
addition to SPY (the current top-10 SPY holdings, or alternatively broad/sector ETFs) to raise
trade frequency and spread risk without increasing position size?
**Issue:** none filed (operator request, 2026-10-22). **Date:** 2026-10-22.
**Pre-registration:** `docs/research/2026-10-22-multi-symbol-hourly-preregistration.md`
(frozen in commit `a5354e1`, strictly before any cross-symbol result; Addendum A1 added in the
results commit). **Code:** `docs/research/2026-10-22-multi-symbol-hourly-study/`.
**Author:** Claude Code research-analyst session (`CLAUDE_AGENT_NO_BROKER=1` throughout; no
broker call; no production code touched).

## Verdict: do not add symbols -- neither the top-10 stocks nor the ETFs (DIRECTIONAL_NO_GO)

- **There is no edge to spread.** On 10 years of SPY SIP data, on the live harness, the live
  rule loses **-0.139R per trade at 1 bp/side** (95% CI -0.182 to -0.101; n = 2,478). Every
  calendar year from 2016 to 2026 is negative, and it is already negative before costs (-0.031R,
  CI -0.073 to +0.004). The recent live record (+2.86R over 42 trades; +5.1R over the last 20)
  sits inside the noise around that negative mean (§4.1).
- **No symbol shows edge.** Of 19 symbols (SPY, the top-10 issuers, 5 ETFs, 3 controls), **0
  are EDGE**, 7 are NEGATIVE (CI entirely below 0: SPY, META, QQQ, DIA, XLF, BRK-B, JPM) and 12
  are NO_EDGE. The best stand-alone mean R is TSLA's -0.009R. Every one of the 19 is negative at
  the primary cost (1 bp/side).
- **The overfitting gate fails on all three legs** for both candidates (DSR 0.07, PBO 0.82,
  bootstrap CI on the monthly uplift spans 0). **Walk-forward symbol selection loses more than
  SPY alone** (top-10: -1.98% vs -0.59%; ETFs: -0.72% vs -0.59%).
- **Spreading the risk works mechanically, but it spreads a negative expectancy.** The 11
  top-10 books are close to independent (average pairwise daily-P&L correlation +0.07,
  effective number of independent bets 10.2 of 11). Under the operator's constraint (total
  open notional stays within 10%) that turns 1.06 trades/day into 10.9 and makes the loss more
  certain. Sharpe goes from -0.79 to -1.41 and total P&L from -1.38% to -2.16% of equity over
  2.9 years.
- **ETFs instead?** No. They are the cheaper alternative, but every ETF is NO_EDGE or NEGATIVE,
  and with average pairwise correlation +0.26 they give only 4.3 effective bets out of 6.

Power is **DIRECTIONAL** (`n_w = 2`, 729 sessions for the cross-symbol panel). This verdict is
a checkpoint input and authorizes no live change. A `DIRECTIONAL_NO_GO` can legitimately be
re-tested at full power. The prior for such a re-test is poor, though, because the 10-year SPY
baseline (B0) is itself well below zero at realistic cost.

---

## §0 Invariant framing and scope

The live `decideHourly`, `computeBracketGeometry` and `computeSizing` were imported unchanged
into two file-in/file-out Deno emitters (#571's `scripts/emit_hourly_decisions.ts`, reused
verbatim, and the new `emit_proxy_decisions.ts`). No new decision rule was added and no
parameter was tuned per symbol. No LLM is involved, nothing in `supabase/functions/`,
`backtest/` or `scripts/` was modified, and no bar data is committed. Implementation
consequences are covered in §7.

**Deviations from the operator brief (disclosed):**
1. **Data:** Alpaca keys were not available in this session (HTTP 401), so the 10 stocks and 5
   ETFs use Yahoo 1h bars (2023-11-24 to 2026-10-21; :30-aligned grid) instead of Alpaca SIP
   2016+. That gap is why §2's parity gates exist. SPY's 10-year baseline uses #571's staged SIP
   bars on the live grid.
2. **Script location:** the scripts live under `docs/research/` instead of `backtest/` because of
   the analyst role's write scope. §9 lists the ledger records an Engineer should add when moving
   them.
3. **Sides:** the study models long AND short, because the live bot has been placing SHORT
   entries since 2026-09-04 (13 of the 42 trades in `daily-verification.jsonl`), even though
   `docs/CURRENT_CONFIG.md` still lists `HOURLY_SHORTS_ENABLED=false`. That documentation
   discrepancy is an operational finding for the operator.

---

## §1 Universe

SSGA SPY holdings file, "As of 21-Oct-2026" (downloaded 2026-10-22). Top-10 issuers, with
Alphabet counted once and traded as GOOGL: **NVDA 8.04%, AAPL 7.51%, MSFT 5.92%, GOOGL+GOOG
5.29%, AMZN 3.85%, AVGO 2.40%, META 2.30%, TSLA 1.63%, MU 1.54%, LLY 1.52%.** ETFs: QQQ, IWM,
DIA, XLK, XLF. Non-winner controls: BRK-B, JPM, UNH.

---

## §2 Parity gates (all hard gates passed; P0d only under Addendum A1)

| Gate | What it checks | Result | Threshold | Status |
|---|---|---|---|---|
| P0a | study simulator vs #571's published SPY 60m R=2.0 cell | 1805 trades, -0.5381R, exits 1060/147/598, trade-for-trade identical | exact | **PASS** |
| P0b | H_live on Yahoo SPY vs the live journal, 2026-08-03..10-21 | days 35/47 = 0.745; live trades matched 31/42 = 0.738; matched median abs(dR) = 0.135R | >= 0.70 / >= 0.60 (0.60-0.75 = caveat) / <= 0.25R | **PASS (caveat band)** |
| P0c | proxy construction (:30 grid, 1h exits) vs live grid, SPY SIP 2016-2026, C2 | mean R -0.054 vs -0.139 (**delta +0.085R**); win 43.0% vs 41.8% (+1.2 pp); trades/yr 272 vs 234 (x1.16) | abs(dR) <= 0.10; abs(dWin) <= 5 pp | **PASS** |
| P0d | Yahoo vs SIP feed on the proxy grid, SPY 2023-11-24..2026-08-12 | median abs(dClose) 141.24 bps (**FAIL as specified**, dividend back-adjustment); adjustment-neutral 0.03 bps; same-action agreement 0.894; dR -0.018 | <= 2 bps; >= 0.80; <= 0.10 | **PASS under Addendum A1** |

How these gates affect the reading of the results:
- **P0c bias:** the cross-symbol harness (H_proxy) reads about **+0.085R per trade more
  optimistic** than the live-grid harness. Every H_proxy number in §3-§5 should be read with that
  in mind. A symbol at -0.03R on H_proxy is closer to -0.1R on the live grid.
- **Feed sensitivity (P0b, P0d):** with essentially identical bars (bar shape differs by less
  than 0.1 bp), 10.6% of the bars that fire disagree on action between Yahoo and SIP. On the live
  grid, 26% of the live SPY trades (which use IEX bars) are not reproduced on consolidated bars.
  Which trades fire, and therefore any per-symbol result, depends on sub-basis-point data noise.
  The live bot would see IEX bars for the single stocks, which this study could not test.

---

## §3 Results

### §3.1 B0 -- SPY 10-year baseline (live grid, SIP 2016-01-04..2026-08-12, both sides)

| Cost (bps/side) | n | Trades/yr | Mean R [95% CI] | Win | PF | Cum R | Max DD (R) |
|---|---|---|---|---|---|---|---|
| C0 = 0 | 2,478 | 234 | -0.031 [-0.073, +0.004] | 44.4% | 0.93 | -78 | -109 |
| **C2 = 1 (primary)** | 2,478 | 234 | **-0.139 [-0.182, -0.101]** | 41.8% | 0.72 | -344 | -359 |
| C3 = 2.5 | 2,478 | 234 | -0.300 [-0.348, -0.259] | 37.5% | 0.51 | -743 | -756 |
| C1 = 5 (#571) | 2,478 | 234 | -0.569 [-0.631, -0.517] | 31.4% | 0.29 | -1,409 | -1,419 |

Long only at C2: -0.115R [-0.165, -0.066] (n = 1,298). Short only at C2: -0.165R [-0.229,
-0.119] (n = 1,180). Breakeven cost: **-0.29 bps/side**, meaning the rule loses even with zero
cost. Mean R at C2 per calendar year: 2016 -0.157, 2017 -0.161, 2018 -0.158, 2019 -0.094,
2020 -0.246, 2021 -0.154, 2022 -0.096, 2023 -0.140, 2024 -0.144, 2025 -0.030, 2026 (to Aug)
-0.151. No year is positive.

### §3.2 S1 -- per-symbol edge (H_proxy, Yahoo 1h, 2023-11-24..2026-10-21, both sides, C2)

| Symbol | Trades/yr | Mean R [95% CI] | Win | PF | Cum R | Max DD (R) | IS mean R | OOS mean R | Long R | Short R | Breakeven bps/side | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SPY** | 267 | -0.078 [-0.151, -0.016] | 42.8% | 0.83 | -59.9 | -68.0 | -0.075 | -0.081 | -0.062 | -0.095 | +0.09 | NEGATIVE |
| NVDA | 254 | -0.053 [-0.123, +0.023] | 43.1% | 0.87 | -38.7 | -55.8 | -0.093 | -0.015 | -0.054 | -0.051 | -1.03 | NO_EDGE |
| AAPL | 256 | -0.017 [-0.085, +0.050] | 44.8% | 0.95 | -12.8 | -40.8 | +0.022 | -0.056 | +0.006 | -0.043 | +0.57 | NO_EDGE |
| MSFT | 250 | -0.027 [-0.093, +0.028] | 43.1% | 0.93 | -19.6 | -30.5 | -0.007 | -0.047 | -0.030 | -0.024 | +0.40 | NO_EDGE |
| AMZN | 249 | -0.025 [-0.090, +0.039] | 45.1% | 0.93 | -17.8 | -35.8 | -0.002 | -0.046 | -0.049 | +0.004 | +0.31 | NO_EDGE |
| GOOGL | 254 | -0.040 [-0.107, +0.027] | 44.1% | 0.90 | -29.2 | -36.4 | -0.093 | +0.010 | -0.006 | -0.074 | -0.12 | NO_EDGE |
| AVGO | 244 | -0.026 [-0.094, +0.042] | 44.9% | 0.93 | -18.1 | -48.1 | +0.038 | -0.087 | -0.040 | -0.010 | -0.06 | NO_EDGE |
| META | 240 | -0.104 [-0.162, -0.042] | 41.5% | 0.74 | -71.9 | -73.9 | -0.093 | -0.113 | -0.061 | -0.147 | -2.50 | NEGATIVE |
| TSLA | 248 | -0.009 [-0.072, +0.057] | 45.2% | 0.98 | -6.2 | -27.1 | -0.003 | -0.014 | -0.058 | +0.038 | +0.56 | NO_EDGE |
| MU | 250 | -0.025 [-0.099, +0.038] | 44.7% | 0.94 | -18.0 | -39.6 | -0.035 | -0.016 | -0.018 | -0.033 | -0.20 | NO_EDGE |
| LLY | 244 | -0.040 [-0.111, +0.023] | 44.1% | 0.90 | -28.6 | -36.0 | -0.042 | -0.039 | -0.044 | -0.037 | -0.25 | NO_EDGE |
| QQQ | 248 | -0.070 [-0.145, -0.001] | 41.8% | 0.84 | -50.5 | -58.4 | -0.114 | -0.026 | -0.073 | -0.067 | -0.19 | NEGATIVE |
| IWM | 256 | -0.055 [-0.130, +0.015] | 45.0% | 0.87 | -40.9 | -64.4 | -0.091 | -0.021 | -0.068 | -0.041 | -0.11 | NO_EDGE |
| DIA | 259 | -0.090 [-0.161, -0.029] | 42.4% | 0.80 | -67.5 | -81.6 | -0.103 | -0.077 | -0.075 | -0.108 | -0.14 | NEGATIVE |
| XLK | 249 | -0.053 [-0.126, +0.013] | 43.4% | 0.88 | -38.2 | -68.2 | -0.049 | -0.056 | -0.057 | -0.048 | -0.04 | NO_EDGE |
| XLF | 257 | -0.071 [-0.131, -0.011] | 44.5% | 0.83 | -53.0 | -65.1 | -0.066 | -0.077 | -0.032 | -0.107 | -0.18 | NEGATIVE |
| BRK-B | 244 | -0.120 [-0.176, -0.055] | 41.4% | 0.72 | -84.4 | -85.4 | -0.151 | -0.089 | -0.070 | -0.171 | -1.09 | NEGATIVE |
| JPM | 245 | -0.096 [-0.163, -0.028] | 40.1% | 0.78 | -67.7 | -75.6 | -0.040 | -0.150 | -0.076 | -0.114 | -1.11 | NEGATIVE |
| UNH | 247 | -0.036 [-0.105, +0.031] | 45.9% | 0.90 | -26.1 | -41.2 | -0.088 | +0.012 | +0.010 | -0.078 | -0.07 | NO_EDGE |

7 NEGATIVE (SPY, META, QQQ, DIA, XLF, BRK-B, JPM), 12 NO_EDGE, 0 EDGE. IS = sessions up to
2025-04-30, OOS = from 2025-05-01.

What the table shows:
- **No symbol has a positive CI_low, and none is positive in both halves.** Four symbols change
  sign between IS and OOS (AAPL +0.022 -> -0.056, AVGO +0.038 -> -0.087, GOOGL -0.093 -> +0.010,
  UNH -0.088 -> +0.012), which is what noise looks like.
- **Rule mean R and spread at each cost (C0 / C2 / C3 / C1):** SPY +0.008 / -0.078 / -0.205 /
  -0.418. TSLA +0.011 / -0.009 / -0.038 / -0.086. Single stocks' stops are 1.9-4.6x wider in bps
  (median 54-129 bps against SPY's 28), so the same per-side cost costs them 2-4x less in R.
  That is the one structural advantage single names have. It does not help, because the gross
  (C0) mean R is around zero everywhere: the best is AAPL at +0.023, and 14 of 19 symbols are
  already negative before cost. Every breakeven cost is at or below +0.57 bps/side, against a
  measured live SPY median slippage of 0.52 bps.
- **59-session spot check on the live grid (Yahoo 5m, top-of-hour, 2026-08-03..10-21):** over
  exactly the weeks in which live SPY was positive (+15.6R on this harness), the 10 top-10 books
  would have produced a combined **-54.8R** (n = 518). AAPL -21.5, META -16.8, TSLA -13.5 and
  MSFT -13.2 account for most of it. On the same 59 sessions the two harnesses agree on the sign
  of a symbol's mean R for only 9 of the 19 symbols, so at this sample size per-symbol results
  are mostly noise.

### §3.3 S2 -- portfolio view (H_proxy, C2, non-compounding, fraction of equity, 2.9 years)

The SPY median 1R under V0 is 2.81 bp of equity, which is **$287 at $1.02M**. That matches the
operator's "$200-300".

| Variant | Max open notional | Trades/day | Mean daily P&L | Ann. Sharpe | Total P&L | Max DD | Worst day | Total in SPY-R |
|---|---|---|---|---|---|---|---|---|
| V0 SPY only (live) | 10% | 1.06 | -0.19 bp | -0.79 | -1.38% | -1.50% | -0.17% | -49 |
| **A V1** SPY+top10, 10%/11 each | **10%** | 10.93 | -0.30 bp | **-1.41** | **-2.16%** | -2.32% | -0.16% | -77 |
| A V1b SPY+top10, one 10% slot | 10% | 1.33 | +0.41 bp | +0.53 | +2.97% | -3.71% | -0.47% | +106 |
| A V2 SPY+top10, 10% each (**LARGER EXPOSURE**) | up to 110% | 10.93 | -3.25 bp | -1.41 | **-23.73%** | -25.49% | -1.80% | -843 |
| **B V1** SPY+ETFs, 10%/6 each | **10%** | 6.09 | -0.16 bp | -0.88 | -1.19% | -1.54% | -0.15% | -42 |
| B V1b SPY+ETFs, one 10% slot | 10% | 1.41 | -0.19 bp | -0.45 | -1.41% | -2.41% | -0.27% | -50 |
| B V2 SPY+ETFs, 10% each (**LARGER EXPOSURE**) | up to 60% | 6.09 | -0.98 bp | -0.88 | -7.11% | -9.21% | -0.91% | -253 |

**V1b's positive total is not evidence of edge.** It was not a pre-registered gate candidate,
and its per-trade mean R is +0.007. A block-bootstrap CI on its mean daily P&L is [-0.43,
+1.27] bp (t = +0.90). Most of the total comes from two books: NVDA (+2.46%, mean R +0.00
on 216 trades; it is positive in dollars only because its larger-stop trades happened to win)
and MSFT (+1.58%, mean R +0.14 on 91 trades). Shifting each trade by the P0c harness offset (-0.085R) turns it
into **-6.34%**. Post-hoc analysis, labelled as such (`diag_posthoc.py`).

### §3.4 Risk spreading (stand-alone books at 10%, daily P&L, C2)

| Set | K | Avg pairwise corr | N_eff (eigenvalue participation) | Corr with SPY book |
|---|---|---|---|---|
| A SPY+top10 | 11 | +0.072 | **10.15** | +0.03 (LLY) to +0.20 (MSFT) |
| B SPY+ETFs | 6 | +0.256 | **4.34** | QQQ +0.45, XLK +0.36, XLF +0.33, DIA +0.24, IWM +0.21 |
| all 19 | 19 | +0.081 | 14.99 | -- |

- The underlying 1h returns are highly correlated with SPY: NVDA 0.71, AMZN 0.72, MSFT 0.68,
  AVGO 0.68, META 0.66, AAPL 0.63, MU 0.63, GOOGL 0.62, TSLA 0.61, LLY 0.42; QQQ 0.96, DIA 0.92,
  XLK 0.92, IWM 0.85, XLF 0.80. Trade outcomes are nearly uncorrelated anyway, because the books
  enter at different hours and on different sides. When several top-10 positions are open
  together, they are all on the same side only 16.5% of the time (ETFs: 45.5%).
- With the top-10, 2 or more positions are open in 69% of trading bars and 5 or more in 53%.
  Under V1 each position carries 1/11 of the notional, so concurrency adds no exposure beyond
  10%.
- **Interpretation:** the diversification is real. It cuts the variance of each period's
  outcome, but the mean is negative, so cutting the variance mostly makes the loss more
  reliable. Sharpe goes from -0.79 to -1.41.

### §3.5 S3 -- overfitting gate (N = 19 trials) and walk-forward selection

| Candidate | DSR (best trial MU; sr_hat +0.0055 vs sr* 0.0593) | PBO (S = 16) | Monthly uplift vs V0 [95% CI] | Gate |
|---|---|---|---|---|
| A SPY+top10 V1 | 0.0725 (< 0.95) | 0.818 (>= 0.5) | -0.022% [-0.084%, +0.027%] | **FAIL (3/3 legs)** |
| B SPY+ETFs V1 | 0.0725 (< 0.95) | 0.818 (>= 0.5) | +0.005% [-0.033%, +0.041%] | **FAIL (3/3 legs)** |

Only 1 of the 19 trials has a positive daily Sharpe (MU, +0.005 non-annualized). PBO 0.82 means
the symbol that looks best in-sample usually lands in the bottom half out-of-sample.

Walk-forward (include a symbol in each 6-month step if its trailing-12-month mean R > 0; SPY
always included):

| Step | Top-10 selected | Selected | All-in V1 | V0 | ETFs selected | Selected | All-in V1 |
|---|---|---|---|---|---|---|---|
| W1 2024-12..2025-05 | SPY, AAPL, AVGO, TSLA | +0.54% | +0.17% | -0.01% | SPY | -0.01% | -0.29% |
| W2 2025-06..2025-11 | SPY, AVGO | -0.98% | -0.77% | +0.10% | SPY | +0.10% | -0.16% |
| W3 2025-12..2026-05 | SPY, AMZN, GOOGL, AVGO, LLY | -1.14% | -0.56% | -0.27% | SPY | -0.27% | -0.04% |
| W4 2026-06..2026-10-21 | SPY | -0.41% | -0.08% | -0.41% | SPY, QQQ | -0.53% | -0.30% |
| **Total OOS** | | **-1.98%** | -1.24% | **-0.59%** | | **-0.72%** | -0.80% |

---

## §4 Single-stock-specific risks vs SPY

### §4.1 How the live record fits

The live record is +2.86R over 42 trades (mean +0.068R). B0's per-trade standard deviation is
about 1.0R, so 42 trades have a standard error of about 0.15R on the mean. That puts the live
mean about 1.3 SE above B0's -0.139R, within the normal range. On the same weeks, P0b's
simulation gives +8.96R over 40 trades. Aug-Oct 2026 has been a favorable stretch for SPY; it is
not a different regime of the rule.

### §4.2 Risk table (5y daily for gaps/SSR, H_proxy for stops)

| Sym | Median stop (bps) | 1R $ at 10% | 1R $ at V1 (10%/11) | Median 1h range (bps) | Overnight abs(gap) p99 / max (bps) | Gaps >= 5% per yr | SSR days/yr | Median $ vol/hr | Order as % of hourly $ vol |
|---|---|---|---|---|---|---|---|---|---|
| SPY | 28 | 287 | 26 | 28 | 236 / 399 | 0.0 | 0.0 | $4.09B | 0.002% |
| NVDA | 99 | 1,004 | 91 | 90 | 644 / 2,615 | 5.0 | 1.8 | $2.57B | 0.004% |
| AAPL | 59 | 601 | 55 | 54 | 406 / 945 | 1.4 | 0.6 | $1.00B | 0.010% |
| MSFT | 54 | 548 | 50 | 51 | 417 / 1,213 | 1.6 | 0.2 | $837M | 0.012% |
| AMZN | 68 | 698 | 63 | 62 | 699 / 1,253 | 4.8 | 0.8 | $776M | 0.013% |
| GOOGL | 68 | 697 | 63 | 60 | 588 / 1,178 | 3.8 | 0.0 | $570M | 0.018% |
| AVGO | 104 | 1,063 | 97 | 93 | 609 / 1,840 | 4.2 | 1.4 | $454M | 0.022% |
| META | 82 | 834 | 76 | 70 | 842 / 2,453 | 6.2 | 1.4 | $763M | 0.013% |
| TSLA | 129 | 1,315 | 120 | 109 | 797 / 1,452 | 9.4 | 4.6 | $2.53B | 0.004% |
| MU | 118 | 1,204 | 109 | 109 | 799 / 1,810 | 10.9 | 3.4 | $323M | 0.032% |
| LLY | 74 | 755 | 69 | 68 | 518 / 1,441 | 3.2 | 0.6 | $254M | 0.040% |
| QQQ | 42 | 430 | 39 | 39 | 294 / 536 | 0.2 | 0.0 | $2.44B | 0.004% |
| IWM | 49 | 501 | 46 | 45 | 295 / 551 | 0.4 | 0.0 | $831M | 0.012% |
| DIA | 31 | 311 | 28 | 28 | 210 / 367 | 0.0 | 0.0 | $192M | 0.053% |
| XLK | 51 | 524 | 48 | 47 | 344 / 626 | 0.2 | 0.0 | $105M | 0.098% |
| XLF | 39 | 394 | 36 | 34 | 262 / 499 | 0.0 | 0.0 | $223M | 0.046% |

- **Overnight and earnings gaps.** The bot flattens before the close. A scan is a flatten scan
  when `clock.nextClose - now <= HOUR_MS` (or the UTC hour is at or past
  `HOURLY_SCAN_END_HOUR`), at `supabase/functions/hourly-check/logic.ts:714-716`. On a flatten
  scan, `reconcile()` cancels the bracket legs and market-closes the position (`logic.ts:651`
  onward). The live journal confirms this: every non-bracket exit is an `hourly_session_close_exit`
  filled at about 19:07 UTC. So **overnight gap exposure is zero in normal operation.** If a
  flatten scan fails (the live record already has a missed slot on 2026-08-07 and a
  `stale_data` skip on 2026-10-15), the bracket legs are `time_in_force: "day"`
  (`_shared/alpaca.ts:555/595/642`) and expire at the close, which leaves the position
  **unprotected overnight**. In that case a single stock's tail is 2.7-3.6x SPY's at p99 and up to 6.6x at the
  worst case: the p99 gap is
  644-842 bps for NVDA/META/TSLA/MU against 236 bps for SPY, and the worst 5-year gap is 2,615
  bps (NVDA) against 399 bps. At a full 10% notional ($102k), a 26% gap costs about $26.7k (2.6%
  of equity), against about $4.1k for SPY's worst.
- **Earnings and event sessions** (abs(gap) >= 3x the symbol's median). The rule's mean R on
  these sessions shows no consistent sign. Across the 10 stocks the average is -0.008R (n =
  48-120 per name) against about -0.04R on other sessions. GOOGL is -0.248R (n = 89), AAPL
  +0.144R (n = 77). Stops widen on these days, so the dollar risk per trade rises at a fixed
  notional, but R does not get systematically worse.
- **Volatility against the stop geometry.** At the same 10% notional, the dollar risk per trade
  is 1.9x (MSFT) to 4.6x (TSLA) SPY's $287, because the stop is a fixed fraction of the signal
  bar's range. "Same position size" therefore does **not** mean "same risk" unless notional is
  split as in V1.
- **Short side.** SSR (Rule 201) is triggered on 4.6 days/yr for TSLA, 3.4 for MU, 1.8 for NVDA,
  1.4 for AVGO/META, and 0 for SPY and the ETFs. Whether Alpaca accepts or delays a short market
  order on an SSR day was not verified. The live code gates shorts on `shortable` only and does
  not read `easy_to_borrow` (`hourly-check/logic.ts` steps 15-16). Shortability and
  easy-to-borrow status for these names could not be queried, because `/v2/assets` needs keys.
  The bot flattens intraday, so overnight borrow fees should not apply (not verified against
  Alpaca's fee schedule). Rule outcomes on the short side are no worse than on the long side
  for most stocks.
- **IEX feed and data quality.** Order size is not a concern: $102k is at most 0.1% of
  consolidated hourly dollar volume. The live bot reads **IEX** bars (`marketdata.ts`,
  `feed=${cfg.dataFeed}`), and IEX carries a low-single-digit share of consolidated volume (not
  measured here). Even on SPY, 26% of live trades are not reproduced on consolidated bars (P0b).
  For thinner names (XLK, DIA, LLY, MU), IEX hourly OHLC will diverge further, which changes which
  candles fire. None of the single-stock numbers above use IEX bars.
- **Slippage.** Bars cannot measure how far a stop-market order fills past the stop: on 1h bars
  the stop overshoot is about 0 by construction. The live journal shows SPY short stop exits
  with -17 and -32 bps exit slippage on 2026-09-04. The breakeven cost per side (§3.2) is the
  practical headroom, and it is at or below +0.57 bps for every symbol.

---

## §5 Survivorship bias

- **Why it can't rescue the result.** Survivorship bias makes hindsight winners look better on
  the long side. That inflates results, so it can turn a no-edge rule into a false positive, but
  it can't hide a real edge. This study's results are all negative or flat, so the bias makes
  the verdict conservative.
- **How big it is (post-hoc estimate).** Positions are held for 2.1-2.8 hours on average.
  Taking each symbol's buy-and-hold log return over the window (an upper bound, since it
  includes overnight returns the bot never holds) gives a drift of at most about 0.02-0.12R per
  long trade: MU +0.115R (MU's buy-and-hold was +1,091%), SPY +0.084R, NVDA +0.083R, UNH -0.022R
  (UNH's was -23%). The long-minus-short gap does not follow winner status: MU long -0.018 vs
  short -0.033, UNH long +0.010 vs short -0.078. The controls behave like the candidates (BRK-B
  and JPM NEGATIVE, UNH NO_EDGE).
- **Drift control (pre-registered).** The rule beats unconditional same-side entries by +0.02 to
  +0.29R on every symbol. **Post-hoc this turns out to be a stop-width artifact:** the rule's
  fired bars have stops about twice as wide as the average bar's (e.g. SPY 29 vs 16 bps). Once
  the control is limited to the same stop-width range (the rule's interquartile range), the
  uplift falls to -0.10 to +0.09R, mixed in sign and centred near 0. The rule shows **no entry
  selection skill** beyond picking wider-range bars.
- **Point-in-time top-10 membership** was not reconstructed. SSGA publishes only the current
  file, and a list from memory could not be verified. This limitation is stated rather than
  worked around.

---

## §6 ETFs vs single stocks (the cheaper alternative)

| | Top-10 stocks (A) | 5 ETFs (B) |
|---|---|---|
| Edge per book | none (0 EDGE, 1 NEGATIVE: META) | none (0 EDGE, 3 NEGATIVE: QQQ, DIA, XLF) |
| V1 total / Sharpe (10% shared) | -2.16% / -1.41 | -1.19% / -0.88 |
| Effective independent bets | 10.2 of 11 | 4.3 of 6 |
| Gate | FAIL 3/3 | FAIL 3/3 |
| Overnight tail if a flatten fails | p99 2.7-3.6x SPY, worst case up to 6.6x | about 0.9-1.4x SPY |
| SSR / borrow complexity | real (TSLA, MU, NVDA) | none observed |
| Feed (IEX) risk | higher | lower (except thin XLK/DIA) |

ETFs carry less operational risk, but they have no more edge than the stocks and spread the risk
less. Neither option is worth implementing on this evidence.

---

## §7 What the invariants would imply if this were ever revisited

This study recommends no implementation. If a future full-power re-test ever found an edge, the
CLAUDE.md invariants would require the following:

- **One decision rule.** Running the same `decideHourly` on more symbols is still one rule. Any
  portfolio-level entry gate is not: a shared notional cap (V1), a single slot with a symbol
  priority order (V1b), or cross-symbol day caps all change entry gating, and the priority order
  in particular is a new decision element. Each needs a fresh brainstorm, spec and ADR. Today
  `hourly-check` is single-symbol (`const symbol = config.hourlyBotTicker`, `logic.ts:686`).
- **Bar claims.** `bar_claims`' primary key is `(script_name, bar_ts)` (`0011_bar_claims.sql`).
  A second symbol scanned on the same bar would hit a unique violation and back off, so a
  per-symbol key and a migration would be needed. `hourly_scans` is already keyed
  `(symbol, bar_ts)`.
- **Kill switch.** It already takes positions from the broker (`getOpenPositions`), so it
  protects every symbol. But `hourly_kill_switch_active` / `_side` / `_fired_at` are global
  `bot_config` keys, so a fire on one symbol would block or misattribute entries on all the
  others. They would need to be per-symbol.
- **Panic must close every live symbol, side-aware.** It already does: `liquidate` cancels all
  orders, then iterates `getOpenPositions()` and calls `closePosition(symbol)` for each, longs
  and shorts. It is pinned by `panic/logic.test.ts` ("liquidate closes every open position, long
  and short together"). No change needed, though a K-position test would be prudent.
- **Paper-only guard.** It is enforced per order in the Alpaca client (paper flag, base URL,
  account marker) and does not depend on the symbol, so it applies unchanged. API call volume
  would grow roughly with K.
- **Short side.** Gate on `easy_to_borrow` as well as `shortable`, and handle SSR-day
  rejections, for single names.

---

## §8 Recommendation

- **Do not implement** multi-symbol trading. Not the top-10 stocks, not the ETFs, and not the
  per-symbol-10% variant, which multiplies the loss (-23.7% over 2.9 years for SPY+top-10).
- **Why:** trade frequency isn't what's holding the bot back. The decision rule shows no edge on
  SPY over 10 years (negative every year at 1 bp/side) and none on any of the 18 other symbols.
  Adding independent bets with zero or negative expectancy makes the loss more certain, not
  smaller.
- **If the operator wants more evidence:** the only re-test that could change this would run
  the H_live harness on Alpaca SIP 2016+ for these symbols, which needs keys (full power), and
  ideally on IEX bars. Given B0, it is low priority. Edge has to be shown on SPY first.
- **Operational follow-up, separate from this study:** `docs/CURRENT_CONFIG.md` says
  `HOURLY_SHORTS_ENABLED=false`, but SHORT entries have been live since 2026-09-04. Someone
  should reconcile the documentation with the deployed secret.

---

## §9 Ledger records to add (for an Engineer, when moving the scripts to `backtest/`)

`backtest/tested_cells.py` (not edited here, because of the analyst write scope):

```
family="hourly_decide_multi_symbol", cadence="hourly", vehicle="TOP10_2026-10-21",
exit_style="bracket_2R_flatten", n_cells=10, verdict=DIRECTIONAL_NO_GO, power="DIRECTIONAL",
source="docs/research/2026-10-22-multi-symbol-hourly-verdict.md", date="2026-10-22"
family="hourly_decide_multi_symbol", cadence="hourly", vehicle="ETF5_QQQ_IWM_DIA_XLK_XLF",
exit_style="bracket_2R_flatten", n_cells=5, verdict=DIRECTIONAL_NO_GO, power="DIRECTIONAL", ...
family="hourly_decide_multi_symbol", cadence="hourly", vehicle="SPY+CONTROLS_BRKB_JPM_UNH",
exit_style="bracket_2R_flatten", n_cells=4, verdict=DIRECTIONAL_NO_GO, power="DIRECTIONAL", ...
```

19 registered trials in total (one per symbol book). The B0 SPY 10-year run is a baseline
measurement of the live rule, not a new trial.

---

## §10 Reproduction

```bash
export CLAUDE_AGENT_NO_BROKER=1
D=docs/research/2026-10-22-multi-symbol-hourly-study
S=<scratch>
venv/bin/python $D/fetch_yahoo_bars.py --out-dir $S/bars                      # Yahoo, read-only
venv/bin/python $D/prepare_inputs.py --raw-dir $S/bars --out-dir $S/inputs \
    --sip-5m data/intraday/SPY_5min.csv --end-date 2026-10-21                 # prints SHA256s
deno run --allow-env --allow-read --allow-write=$S scripts/emit_hourly_decisions.ts \
    --bars data/intraday/SPY_60min.csv --bars5 data/intraday/SPY_5min.csv \
    --out $S/dec/SPY_sip_60m.csv --period-minutes 60 --shorts-enabled
venv/bin/python $D/run_parity_p0a.py --decisions $S/dec/SPY_sip_60m.csv --bars5 data/intraday/SPY_5min.csv
venv/bin/python $D/run_emitters.py --inputs $S/inputs --out-dir $S/dec
venv/bin/python $D/run_multi_symbol_study.py --inputs $S/inputs --dec $S/dec \
    --sip-5m data/intraday/SPY_5min.csv --journal docs/trading-journal/daily-verification.jsonl \
    --raw $S/bars --stage all
venv/bin/python $D/diag_p0d_adjustment.py $S/inputs        # Addendum A1 evidence
venv/bin/python $D/diag_posthoc.py $S/inputs $S/dec        # post-hoc checks (labelled)
```

Input provenance: #571 SIP `SPY_60min.csv` sha256 `9971bd41...3b74` and `SPY_5min.csv`
`65da7f61...0a79` (re-verified). Yahoo downloads made 2026-10-22. SHA256s of the prepared 1h
proxy files: SPY `cdb0ab52...0f97`, NVDA `4d8068f2...c70c9`, AAPL `190b3388...5c838`, MSFT
`2db17c1b...9397`, AMZN `aa46382b...c1f5`, GOOGL `1539be81...10238`, AVGO `4fb96169...0394`,
META `1af1a6d9...7acd`, TSLA `c4648c1a...cf25`, MU `67f87f2c...6565776`, LLY `833c322d...dd`,
QQQ `9b34b479...15c2`, IWM `2833b75d...39df`, DIA `39d51334...2dd9`, XLK `849b63d4...b058`,
XLF `363f370d...791c`, BRK-B `0f601651...c017`, JPM `ea1ff6eb...22c9`, UNH `8da57e79...4a1f`.
Derived SIP files: `SPY_sip_1h_proxy.csv` `4d86b5fc...70fe4`, `SPY_sip_5m_rth.csv`
`fc2b1c7b...2b008`. `prepare_inputs.py` prints the full hashes. Yahoo may revise history,
so a re-download can differ slightly.
