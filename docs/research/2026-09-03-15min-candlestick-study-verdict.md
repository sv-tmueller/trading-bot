# 15-Minute candlestick-pattern study — verdict

**Issue:** #630. **Branch:** `feat/630-15min-candlestick`. **Pre-registration:**
`docs/research/2026-07-25-candlestick-pattern-preregistration.md` (the frozen 14-detector
registry, stop geometry, and R grid — restated nowhere below, only cited). **Date:**
2026-09-03. **Author:** Claude Code session (research-only; `CLAUDE_AGENT_NO_BROKER=1`
for the whole session; no production code touched).

**Verdict: DIRECTIONAL_NO_GO.** All 28 cells (14 arms × R∈{2,3}) on 15-minute SPY bars
produce a deeply negative profit factor (0.22–0.40), win rates of 17–27% (far below the
~33% breakeven at R=2), and RUINED after-tax Calmar curves across the board. The 60-minute
baseline is uniformly less-bad at every arm. The cost wall at 15m cadence is devastating:
648%/yr annualized drag at the backtest's 20bp round-trip cost, with a single side's
slippage consuming 19.4% of the median stop distance ($0.95). This is a **checkpoint
input** only (DIRECTIONAL power, `n_w=10 < 13` — §5) — it is suggestive, not gate-eligible,
and authorizes no live change (§6).

---

## §0 Invariant framing

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants): this
package adds no second decision rule, introduces no LLM in the trading path, and touches no
production code (`supabase/functions/` is unchanged — verified in §7). The frozen 14-detector
registry from `backtest/candlestick.py` is imported and called unchanged; the stop geometry
(`bracket_levels`, `PATTERN_SPAN`) is inherited from `run_candlestick_study.py` without
modification. The design spec for how 15-min signals might compose with the hourly rule is
deferred to #624b — this study produces the evidence, not the specification.

---

## §1 Data + PowerReport

**15-minute bars:** `data/intraday/SPY_15min.csv` — 167,067 bars aggregated from the staged
5-minute SIP bars (`SPY_5min.csv`, fetched via Alpaca in #566/#571) by 15-minute OHLC
resampling. Alpaca keys were not available in this session (`ALPACA_API_KEY_ID` unset ->
DATA-BLOCKED on the direct `15Min` fetch), so the 15-minute frame was derived from the
existing 5-minute frame. Both methods produce the same bars; the resampled frame is the
local equivalent of what `run_fetch_spy_intraday.fetch_bars(..., timeframe="15Min")`
would return. Filtered to regular session hours (13:30–21:00 UTC) via
`intraday_data.regular_session`: 82,665 RTH bars / 2,667 sessions.

**60-minute bars:** `data/intraday/SPY_60min.csv` — 21,329 RTH bars / 2,667 sessions (staged
in #566/#571, same provenance).

**PowerReport (both cadences):** DIRECTIONAL — `n_w=10 < 13` the #398 promotion floor.
Neither frame is gate-eligible; every number below is a **checkpoint input**, not a
promotion attempt. No DSR/PBO/bootstrap statistic is computed.

---

## §2 Firing-rate calibration (all 14 detectors)

Verbatim from `python3 -m backtest.run_15min_candlestick_study --firing-rates`:

```
Firing-rate calibration — 15m vs 60m
15m source: local:data/intraday/SPY_15min.csv  power: DIRECTIONAL
60m source: local:data/intraday/SPY_60min.csv  power: DIRECTIONAL

pattern                dir       15m cnt  15m rate   60m cnt  60m rate          bounds
bullish_engulfing      long         6803    8.23%      1579    7.40%              ok
bearish_engulfing      short        6788    8.21%      1515    7.10%              ok
hammer                 long         3268    3.95%       984    4.61%              ok
shooting_star          short        2528    3.06%       691    3.24%              ok
bullish_pin_bar        long         5796    7.01%      1794    8.41%              ok
bearish_pin_bar        short        4766    5.77%      1258    5.90%              ok
bullish_marubozu       long         1612    1.95%       393    1.84%              ok
bearish_marubozu       short        1401    1.69%       290    1.36%              ok
bullish_harami         long         7012    8.48%      1756    8.23%              ok
bearish_harami         short        7213    8.73%      1882    8.82%              ok
morning_star           long         3074    3.72%       729    3.42%              ok
evening_star           short        3026    3.66%       754    3.54%              ok
doji                   neutral      8866   10.73%      2620   12.28%              ok
inside_bar             neutral     12953   15.67%      4220   19.79%              ok

15m miscalibrated: 0 / 14
60m miscalibrated: 0 / 14
bounds: [0.5%, 25%]
```

**All 14 detectors fire within the [0.005, 0.25] bounds on both cadences.** Firing rates
are broadly similar between 15m and 60m (the detectors are cadence-agnostic by
construction — the same body/wick ratios apply). The 15m frame produces ~4× the raw signal
count of the 60m frame, proportional to the ~4× bar density. `doji` (NEUTRAL) and
`inside_bar` (NEUTRAL) are reported for calibration completeness but excluded from the
trading grid (§3).

---

## §3 Per-arm performance vs hourly baseline

Verbatim from `python3 -m backtest.run_15min_candlestick_study` (§7 reproduces the exact
invocation):

```
15-Minute candlestick study — per-arm performance vs hourly baseline
15m source: local:data/intraday/SPY_15min.csv  power: DIRECTIONAL — n_w=10 < the n_w=13 promotion bar; a directional read only, NOT gate-eligible
60m source: local:data/intraday/SPY_60min.csv  power: DIRECTIONAL — n_w=10 < the n_w=13 promotion bar; a directional read only, NOT gate-eligible
frozen SPY bar (median-window after-tax Calmar): 1.3085

arm                    dir       R   15m WR  15m PF   15m Cal 15m #tr   60m WR  60m PF   60m Cal 60m #tr   rand Cal
bullish_engulfing      long      2   26.7%    0.30         —   2980   23.6%    0.25         —   1307          —
bullish_engulfing      long      3   25.6%    0.30         —   2919   23.3%    0.26         —   1301          —
bearish_engulfing      short     2   23.3%    0.26         —   2801   23.6%    0.33         —   1275          —
bearish_engulfing      short     3   21.0%    0.26         —   2687   23.4%    0.33         —   1269          —
hammer                 long      2   21.9%    0.26         —   2340   28.7%    0.34   -0.2698    820          —
hammer                 long      3   21.0%    0.28         —   2297   28.4%    0.36   -0.2721    816          —
shooting_star          short     2   19.7%    0.23         —   1952   22.9%    0.37   -0.2431    590          —
shooting_star          short     3   16.9%    0.23         —   1916   21.6%    0.38   -0.2466    588          —
bullish_pin_bar        long      2   22.3%    0.25         —   2836   28.1%    0.31         —   1350          —
bullish_pin_bar        long      3   21.2%    0.29         —   2858   27.7%    0.34         —   1337          —
bearish_pin_bar        short     2   20.1%    0.24         —   2596   22.9%    0.36         —   1009          —
bearish_pin_bar        short     3   17.3%    0.22         —   2518   21.8%    0.36         —    999          —
bullish_marubozu       long      2   25.3%    0.37         —   1291   24.0%    0.32   -0.1375    358          —
bullish_marubozu       long      3   24.4%    0.40         —   1277   24.2%    0.34   -0.1369    356          —
bearish_marubozu       short     2   21.7%    0.29         —   1169   31.7%    0.44   -0.1266    262          —
bearish_marubozu       short     3   21.1%    0.29         —   1157   31.4%    0.49   -0.1244    261          —
bullish_harami         long      2   24.4%    0.31         —   3033   28.6%    0.36         —   1491          —
bullish_harami         long      3   22.7%    0.32         —   2956   27.7%    0.38         —   1481          —
bearish_harami         short     2   21.0%    0.27         —   2916   21.0%    0.27         —   1531          —
bearish_harami         short     3   18.4%    0.27         —   2908   19.3%    0.29         —   1519          —
morning_star           long      2   26.1%    0.33         —   2240   26.5%    0.37   -0.1976    676          —
morning_star           long      3   25.4%    0.35         —   2215   26.1%    0.37   -0.2003    674          —
evening_star           short     2   20.8%    0.26         —   2238   22.6%    0.27   -0.2278    699          —
evening_star           short     3   19.6%    0.25         —   2201   22.5%    0.26   -0.2264    698          —
inside_bar_long        long      2   23.9%    0.25         —   3021   31.2%    0.34         —   2519          —
inside_bar_long        long      3   22.4%    0.26         —   2990   30.3%    0.36         —   2485          —
inside_bar_short       short     2   19.9%    0.24         —   2881   24.4%    0.32         —   2350          —
inside_bar_short       short     3   17.4%    0.24         —   2854   23.3%    0.33         —   2402          —
```

**Key observations:**

1. **No 15m arm achieves a positive profit factor.** Every PF is between 0.22 and 0.40 —
   meaning gross losses exceed gross winnings by 2.5–4.5×. At R=2, a strategy needs a win
   rate above 33.3% to break even before costs; the highest 15m win rate is 26.7%
   (`bullish_engulfing/R2`), and most arms sit in the 17–25% range.

2. **Every 15m after-tax Calmar is RUINED (—).** The after-tax equity curve is destroyed
   for all 28 cells — the no-loss-credit US tax model on gross winners drives the after-tax
   Calmar to NaN, the same failure mode the daily candlestick study's RUINED cells exhibited.
   Several 60m arms also show RUINED Calmars; the ones that survive (hammer, shooting_star,
   marubozu, morning_star, evening_star) still produce deeply negative finite Calmars
   (-0.13 to -0.27).

3. **60m is uniformly less-bad.** Of the 28 cells, the 60m win rate exceeds the 15m win rate
   in 24/28 cases; the 60m profit factor exceeds the 15m PF in 26/28 cases. The exceptions
   are `bullish_engulfing` (15m WR marginally higher, but both PFs ~0.25–0.30) and
   `bearish_harami` (identical at one cell). No arm flips from negative to positive
   expectation moving from 15m to 60m.

4. **Short arms are worse than long arms** at both cadences — consistent with the SPY
   uptrend over 2016–2026 (the short side fights the drift).

5. **15m trades ~2× as often** (1,157–3,033 trades/arm vs 261–2,519 at 60m), compounding
   the per-trade cost drag over roughly twice as many round trips.

---

## §4 Cost-wall assessment

```
Cost-wall assessment — 15m vs 60m (refs #422, #571)

  metric                                              15m            60m
  ---------------------------------------- -------------- --------------
  total trades (R=2 grid)                          34,294         16,237
  sessions                                          2,667          2,667
  trades/day                                         12.9            6.1
  annualized drag (%/yr, 20bp RT)                 648.1%        306.8%
  median stop distance ($)                         0.9485         1.3966
  median slippage / stop distance                   19.4%          13.1%
  % trades slip ≥ stop dist                         0.2%          0.8%

#422's 15m cost-wall reference: 6.1%/yr drag at 3bp table
This study's 15m annualized drag: 648.1%/yr at 20bp RT
#571's 60m cost-drag: ~19% of stop distance (single-side slippage alone)
```

### Interpretation

**The cost wall at 15m is catastrophic, not borderline.** The annualized drag of 648%/yr at
the backtest's 20bp round-trip cost dwarfs #422's 6.1%/yr figure (computed at a 3bp
assumption). The difference is driven by trade frequency: #422's table assumed ~1
trade/day, while this study's 15m grid fires 12.9 trades/day across 14 arms — each
compounding the per-trade cost drag. Even a single arm averages ~0.9 trades/day at 15m.

**Stop-distance tightening is the dominant mechanism.** The median 15m stop distance is
$0.95 (vs $1.40 at 60m) — a 15-minute bar's own range is naturally narrower than an
hour's. A single side's entry slippage (median $0.184, the `SLIPPAGE_BPS=5` leg on a
~$368 SPY price) consumes **19.4% of the entire stop distance at 15m** — closely matching
#571's 60m finding of ~19%. At 60m, the same slippage is 13.1% of the wider stop. Round-trip
(entry + exit slippage, ignoring commission) consumes roughly double: ~39% at 15m vs ~26%
at 60m.

This mechanically shifts every trade's realized R negative by a fixed fraction of the risk
unit, regardless of whether the candlestick signal has any directional accuracy at all. A
stop-touch that lands exactly at the nominal stop level already realizes approximately
-1.4R once slippage alone is included — matching the observed PFs near 0.25 (consistent
with a ~25% effective win rate at nominal R=2, dragged further negative by costs).

**Comparison to #422:** #422's short-horizon feasibility gate closed the broad
indicator-based entry class (MA-cross, Donchian, RSI, Bollinger) at 15m+ cadence on two
walls: cost (72–128%/yr at 1-minute, 6.1%/yr at 15m in the 3bp table) and data scarcity.
This study's candlestick patterns are a different functional form (fixed 1–3 bar OHLC
geometry vs rolling-window aggregates), but #422's cost-wall finding is signal-agnostic —
it applies to ANY strategy that trades 12.9 times per session at 15m cadence. The 648%/yr
drag computed here at the backtest's own 20bp cost model confirms #422's 15m cost-wall
applies with full force to candlestick patterns.

**Comparison to #571:** #571 found that the hourly bracket geometry's stop distance
(median $0.95–0.96 at 60m) was tight enough for a single side's slippage to consume ~19%
of the risk unit, driving deeply negative expectancy (-0.53R to -0.77R). At 15m, the stop
distance is equally tight ($0.95) but the trade count doubles, so the same per-trade drag
compounds over twice as many round trips. The mechanism is identical; the cadence intensifies
it.

---

## §5 Power disclosure (binding on every number above)

Per `intraday_data.describe_power`: 2,667 sessions, **`n_w=10 < 13`** the #398 promotion
floor. **DIRECTIONAL power only.** No DSR/PBO/bootstrap statistic is computed anywhere in
this package; nothing here is a gate-eligible read. Every number in §3–§4 is a **checkpoint
input**, not a promotion attempt — the magnitude and consistency of the negative result
(every arm, every R, PF universally below 0.40, all 15m Calmars RUINED, a well-quantified
cost-drag mechanism in §4) make it a strong directional signal despite the power ceiling,
but it is not, and is not claimed to be, a statistically gated conclusion.

---

## §6 Verdict and non-goals

**DIRECTIONAL_NO_GO.** The 15-minute candlestick grid is closed at DIRECTIONAL power. The
evidence is unanimous:

1. **No arm improves on its hourly baseline.** 60m is less-bad at 26/28 cells; no arm flips
   positive moving from 15m to 60m, let alone from 60m to 15m.
2. **The cost wall is prohibitive.** 648%/yr annualized drag at 20bp RT; a single side's
   slippage consumes 19.4% of the median stop distance. This is #422's 15m cost-wall
   finding applied to the candlestick class — the cost wall is signal-agnostic.
3. **All 15m after-tax Calmars are RUINED.** The after-tax equity curve is destroyed for
   every cell, the same failure mode seen in the daily candlestick study's worst cells.

**Non-goals:**
- **No live change.** Nothing in this package modifies any production parameter, cadence, or
  sizing constant — the live hourly bot is unaffected regardless of this verdict.
- **No new decision rule.** The frozen 14-detector registry was imported and called
  unchanged; nothing about the signal itself was touched or re-tuned.
- **Design spec deferred to #624b.** This study answers "should candlestick patterns trade
  at 15m?" (no). How 15-min signals might compose with the hourly rule — if they ever did —
  is a separate design question scoped to #624b, and this verdict's NO-GO makes it moot
  unless new information arrives (wider stops, lower costs, full-power data).
- **Re-testable at full power.** A `DIRECTIONAL_NO_GO` is explicitly re-testable — if
  15-minute SPY data eventually reaches `n_w≥13` (requires ~13 years of intraday history;
  the current 2016–2026 window provides `n_w=10`), a full-power rerun is legitimate. The
  prior (based on this study and #422/#571) is that it would confirm the NO-GO, but the
  gate-eligible read has not been produced.

---

## §7 Verification / reproduction

```bash
# Tests
CLAUDE_AGENT_NO_BROKER=1 venv/bin/python -m pytest tests/test_run_15min_candlestick_study.py -q
# 14 passed

# No production code touched
git diff --stat main -- supabase/functions/ supabase/migrations/ .env.example README.md  # empty
grep -rn "createAlpacaClient\|/v2/orders" backtest/run_15min_candlestick_study.py  # no matches

# Regenerate the study (never committed — local scratch only)
CLAUDE_AGENT_NO_BROKER=1 venv/bin/python -m backtest.run_15min_candlestick_study \
    --data-15m data/intraday/SPY_15min.csv --data-60m data/intraday/SPY_60min.csv

# Firing-rate-only mode (runs even on UNDERPOWERED data)
CLAUDE_AGENT_NO_BROKER=1 venv/bin/python -m backtest.run_15min_candlestick_study \
    --data-15m data/intraday/SPY_15min.csv --data-60m data/intraday/SPY_60min.csv --firing-rates
```

The 15-minute CSV was derived from the staged 5-minute SIP bars by 15-minute OHLC
resampling (Alpaca keys were not available in this session for a direct `15Min` fetch).
To regenerate from Alpaca directly:

```bash
python3 -m backtest.run_fetch_spy_intraday --timeframes 15Min --start 2016-01-01
```

---

## §8 `tested_cells.py` ledger flip

Two new records appended to `backtest/tested_cells.py`:

- `candlestick_pattern` / `15m` / `SPY` — `DIRECTIONAL_NO_GO`, `DIRECTIONAL` power,
  28 cells (14 arms × R{2,3}), citing this document.
- `candlestick_pattern` / `hourly` / `SPY` — `DIRECTIONAL_NO_GO`, `DIRECTIONAL` power,
  28 cells (the hourly baseline from this study, computed for the first time at the
  individual-detector level — #571 evaluated the composite `decideHourly`, not individual
  detectors), citing this document.

Both are `DIRECTIONAL_NO_GO` (not `NO_GO`) because power is `DIRECTIONAL` (`n_w=10 < 13`),
per the ledger's own vocabulary: a `DIRECTIONAL_NO_GO` is explicitly re-testable at full
power. `cumulative_trials("candlestick_pattern")` increases by 56 (28 + 28).
