# Hourly bracket-geometry, cadence, and sizing study — verdict

**Issue:** #571 (steps 2-5 of #566's batch). **Pre-registration:**
`docs/research/2026-08-13-hourly-geometry-cadence-sizing-preregistration.md` (grid, staged-data
anchor, conventions — restated nowhere below, only cited). **Date:** 2026-08-13. **Author:**
Claude Code session (research-only; `CLAUDE_AGENT_NO_BROKER=1` for the whole session; no
network anywhere in this package).

**Verdict: DIRECTIONAL_NO_GO.** All 6 cells (`R ∈ {1.0, 1.5, 2.0} × cadence ∈ {60m, 30m}`)
produce a deeply negative expectancy (-0.53R to -0.77R mean per trade); every cell breaches
the -15%-from-start equity floor at every sizing cap tested. This is a **checkpoint input**
only (DIRECTIONAL power, `n_w=10 < 13` — §7) — it is suggestive, not gate-eligible, and
authorizes no live change (§8).

---

## §0 Invariant framing

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants): this
package replays the live `decideHourly`/`computeBracketGeometry`/`computeSizing` exports
unchanged, adds no second decision rule, and touches no live parameter, cadence, or sizing
value. No network anywhere in this package (the bars were staged before this session — see the
pre-registration doc §2). No broker call is reachable from any module added in this package
(`CLAUDE_AGENT_NO_BROKER=1` was set for the whole session; the grep checks in §9 confirm it).

---

## §1 Grid confirmation

The grid run below is byte-for-byte the pre-registration doc's §1 grid: `R ∈ {1.0, 1.5, 2.0} ×
cadence ∈ {60m, 30m}`, 6 cells, sizing-cap replay at `{0.10, 0.25, 0.50, 1.00}` (a replay of the
same 6 ledgers, not a 7th trial — §6). No cell, R value, or cadence was added or dropped after
seeing any result.

**Implementation correction, disclosed (found while building the simulator, before any result
existed):** the emitter's first cut used the candidate (signal) bar's own close as `entryRef`
for `computeBracketGeometry`/`computeSizing`. That price is up to ~1h07m stale by the time the
live bot would actually read `getLatestTradePrice()` (scan time, bar close + 7min) — and the
hourly bracket's stop buffer (`HOURLY_STOP_BUFFER_PCT = 0.05` of an hourly bar's own range) is
frequently well under a dollar, so ordinary drift over that gap can already put the "entry"
past its own stop or target before any trade is even simulated. This was corrected (commit
`fix(scripts): key entryRef off the fill-instant price, not the stale candidate close`) to use
the SAME 5Min-bar-open the actual fill executes at — exactly what the sub-plan's own "Risks"
section already specified ("the study uses next-5Min-bar opens" for geometry, not the
signal-bar close). This is a fidelity correction to the frozen Q3 conventions' *implementation*,
not a change to the registered grid, R values, or cadences — no result existed before the fix
landed.

---

## §2 Sanity gate (step C — reproducing the live Aug 3-12 decision record)

`scripts/emit_hourly_decisions.ts` run against the staged 60m bars (`SPY_60min.csv`), restricted
to 2026-08-03 through 2026-08-12, raw `decideHourly` LONG fires by day:

| Date | Raw LONG fire(s) (60m, this session's SIP replay) | Live entry recorded (daily journal) |
|---|---|---|
| 2026-08-03 | none | none |
| 2026-08-04 | none | none |
| 2026-08-05 | none | none |
| 2026-08-06 | 14:00, 16:00, 18:00 UTC | yes (1 entry) |
| 2026-08-07 | 19:00 UTC | yes (1 entry) |
| 2026-08-10 | 18:00, 19:00 UTC | **none** |
| 2026-08-11 | 17:00, 19:00 UTC | yes (1 entry) |
| 2026-08-12 | 16:00 UTC | yes (1 entry) |

**Result: 4/4 live entry-days reproduced (2026-08-06, 07, 11, 12), plus one day
(2026-08-10) with a raw SIP signal fire that produced no live entry.** Every live entry day has
a matching raw fire — the harder direction to get right (a bug would more plausibly show as a
*miss*, not an extra). The one discrepancy is a single extra day, not a missed day.

**Explanation, not treated as a harness bug:** the live bot runs on **IEX** bars
(`config.ts`'s `dataFeed` default); this study's staged bars are **SIP**. The two feeds
aggregate different trade prints into the same nominal hour, so a candlestick pattern present
in one feed's OHLC values can be absent in the other's for the same wall-clock hour — exactly
the risk the sub-plan's Q1 flagged and pre-registered a disclosed (non-selective) concordance
check for, rather than claiming SIP and IEX would agree bar-for-bar. With only one day of
disagreement across 8 trading days and 48 candidate hourly bars (and the disagreement running
in the "extra signal on SIP" direction, not "missed signal"), this is consistent with ordinary
feed-level OHLC noise, not a harness defect. No code in `scripts/emit_hourly_decisions.ts` was
changed on the basis of this gate (the entryRef fix in §1 was found independently, during
simulator development, and does not touch `decideHourly`'s signal path at all).

Reproduce: `scripts/emit_hourly_decisions.ts --bars data/intraday/SPY_60min.csv --bars5
data/intraday/SPY_5min.csv --period-minutes 60`, then filter the output to
`2026-08-03 <= timestamp < 2026-08-13` and inspect `action_raw`.

---

## §3 Per-arm exit distribution and expectancy (all 6 cells)

Verbatim from `python3 -m backtest.run_hourly_geometry_study` (§9 reproduces the exact
invocation):

```
--- cadence=60m R=1.0 ---
trades: 1832  expectancy(R): -0.5346
exit distribution: {'target': 493, 'flatten': 784, 'stop': 555}
no-flatten counterfactual: 784 flattened trades, as-flattened expectancy(R): -0.2712, counterfactual expectancy(R): -0.2545
cost drag: median stop_distance=$0.9500 median entry-slippage cost=$0.1783 (median cost/stop_distance=0.188); 2.3% of trades have entry slippage alone >= the whole stop distance

--- cadence=60m R=1.5 ---
trades: 1815  expectancy(R): -0.5361
exit distribution: {'flatten': 965, 'target': 264, 'stop': 586}
no-flatten counterfactual: 965 flattened trades, as-flattened expectancy(R): -0.1745, counterfactual expectancy(R): -0.1335
cost drag: median stop_distance=$0.9600 median entry-slippage cost=$0.1784 (median cost/stop_distance=0.187); 2.3% of trades have entry slippage alone >= the whole stop distance

--- cadence=60m R=2.0 ---
trades: 1805  expectancy(R): -0.5381
exit distribution: {'flatten': 1060, 'target': 147, 'stop': 598}
no-flatten counterfactual: 1060 flattened trades, as-flattened expectancy(R): -0.1020, counterfactual expectancy(R): -0.0631
cost drag: median stop_distance=$0.9600 median entry-slippage cost=$0.1785 (median cost/stop_distance=0.186); 2.3% of trades have entry slippage alone >= the whole stop distance

--- cadence=30m R=1.0 ---
trades: 4194  expectancy(R): -0.7666
exit distribution: {'target': 1623, 'stop': 1685, 'flatten': 886}
no-flatten counterfactual: 886 flattened trades, as-flattened expectancy(R): -0.3301, counterfactual expectancy(R): -0.3936
cost drag: median stop_distance=$0.7050 median entry-slippage cost=$0.1794 (median cost/stop_distance=0.252); 5.9% of trades have entry slippage alone >= the whole stop distance

--- cadence=30m R=1.5 ---
trades: 3944  expectancy(R): -0.7422
exit distribution: {'target': 988, 'flatten': 1189, 'stop': 1767}
no-flatten counterfactual: 1189 flattened trades, as-flattened expectancy(R): -0.1537, counterfactual expectancy(R): -0.1681
cost drag: median stop_distance=$0.7200 median entry-slippage cost=$0.1796 (median cost/stop_distance=0.247); 5.4% of trades have entry slippage alone >= the whole stop distance

--- cadence=30m R=2.0 ---
trades: 3814  expectancy(R): -0.7390
exit distribution: {'stop': 1803, 'flatten': 1391, 'target': 620}
no-flatten counterfactual: 1391 flattened trades, as-flattened expectancy(R): -0.0207, counterfactual expectancy(R): -0.0303
cost drag: median stop_distance=$0.7200 median entry-slippage cost=$0.1805 (median cost/stop_distance=0.245); 5.2% of trades have entry slippage alone >= the whole stop distance
```

**No cell clears a positive expectancy.** All 6 arms land between -0.53R and -0.77R mean
realized R per trade — decisively negative, not a marginal miss.

### §3.1 The dominant mechanism: bracket-geometry / transaction-cost interaction

The exit-type breakdown alone does not explain the magnitude — target/stop counts are close to
balanced at R=1.0 (493 target vs 555 stop, 60m), which on a *pure* ±1R basis would net only
about -0.03R, not -0.53R. The gap is the **cost drag** row: this study reuses
`backtest/regime.py`'s frozen `SLIPPAGE_BPS=5`/`COMMISSION_BPS=5` (the same constants #499 used
for the DAILY-bar candlestick family, where ATR/pattern-extreme stops are typically multiple
dollars wide). The hourly bracket's stop distance is far tighter (`HOURLY_STOP_BUFFER_PCT=0.05`
of an *hourly* bar's own range) — median **$0.95** (60m) / **$0.70-0.72** (30m) against a SPY
price in the hundreds. A single side's slippage alone (median **$0.178-0.181**) is therefore
**~19% (60m) to ~25% (30m) of the entire stop distance** — and round-trip (entry + exit
slippage, ignoring commission, which this study's R stats deliberately exclude per the
pre-registration's convention) consumes roughly double that. This mechanically shifts every
trade's realized R negative by a fixed fraction of the risk unit, regardless of whether
`decideHourly`'s underlying signal has any directional accuracy at all — a stop-touch that
lands EXACTLY at the nominal stop level already realizes roughly -1.2R to -1.5R once slippage
alone is included (matches the observed 60m median stop-exit R of -1.46, not the nominal -1.0).
**2.3% (60m) to 5.9% (30m) of trades have entry-side slippage alone consume the whole stop
distance** — these are the extreme negative-R outliers (as bad as -12R) seen in individual
trades, but the systematic median-level shift (not just the tail) is the larger effect on the
aggregate expectancy.

This is a genuine, quantified, disclosed finding about how the **frozen** `HOURLY_STOP_BUFFER_PCT`
geometry interacts with the **frozen** `regime.py` cost constants at hourly cadence — neither
value is changed by this study (both are live parameters; changing either needs its own
brainstorm and ADR, per the non-goals). It is the leading candidate explanation for the
negative expectancy across every cell, ahead of "the candlestick signal has no edge" (which the
target/stop balance at R=1.0 does not, by itself, support) and ahead of pure winner-truncation
(§5 below bounds that effect and shows it does not close the gap either).

This "unviable" verdict is scoped strictly to **this study's frozen backtest cost model**
(`SLIPPAGE_BPS`/`COMMISSION_BPS=5`) and is not an attribution of, or claim about, the live paper
bot's own ~5-trade record over 2026-08-06 through 08-12 (§2): those live fills carry real but
different, unmeasured costs.

---

## §4 30m vs 60m comparison

| Cadence | Mean expectancy(R) across R{1.0,1.5,2.0} | Trade count range | Cost drag (median cost/stop_distance) |
|---|---|---|---|
| 60m | -0.536 | 1,805-1,832 | 0.186-0.188 |
| 30m | -0.749 | 3,814-4,194 | 0.245-0.252 |

**30m is worse at every R**, by roughly 0.2R on average. Two compounding reasons, both visible
in the table: (1) the 30m stop distance is tighter in dollar terms (median $0.70-0.72 vs
$0.95-0.96 for 60m — a half-hour bar's own range is naturally narrower than an hour's), which
raises the cost-drag fraction from ~19% to ~25% of the risk unit; (2) 30m trades more than
twice as often (3,814-4,194 vs 1,805-1,832), so the SAME per-trade cost drag compounds over
roughly 2.2x as many round trips. Neither cadence approaches breakeven, but 60m is the
comparatively less-bad cadence at every R tested.

---

## §5 No-flatten counterfactual (isolating winner truncation)

For every trade the main run flattened at session close, `no_flatten_counterfactual` continues
that SAME position (same stop/target) forward through `_resolve_bar` until it naturally
resolves or the data ends. "As-flattened" is that subgroup's actual realized R at the flatten
fill (the main run's own number); "counterfactual" is the same subgroup's R had it been allowed
to keep running:

| Cadence | R | Flattened trades | As-flattened expectancy(R) | Counterfactual expectancy(R) | Delta |
|---|---|---|---|---|---|
| 60m | 1.0 | 784 | -0.2712 | -0.2545 | +0.0167 |
| 60m | 1.5 | 965 | -0.1745 | -0.1335 | +0.0410 |
| 60m | 2.0 | 1,060 | -0.1020 | -0.0631 | +0.0389 |
| 30m | 1.0 | 886 | -0.3301 | -0.3936 | -0.0635 |
| 30m | 1.5 | 1,189 | -0.1537 | -0.1681 | -0.0144 |
| 30m | 2.0 | 1,391 | -0.0207 | -0.0303 | -0.0096 |

**Winner truncation is real but cadence-dependent, not a uniform effect.** At 60m, removing the
flatten consistently HELPS (+0.017R to +0.041R) — the classic truncation story: some positions
were cut off on their way to target and running them further recovers part of that. At 30m,
removing the flatten consistently HURTS very slightly (-0.010R to -0.064R) — at that cadence,
the positions still open at session close are, on average, already sitting closer to a local
favorable point than an unfavorable one, and continuing to hold them into the (thinner,
noisier) after-hours/next-session price action gives back a little of that rather than gaining
more. Either way, **the effect is small in magnitude (well under 0.1R at every cell) and never
flips the sign positive** — winner truncation is a second-order effect here, not the driver of
the deeply negative headline numbers in §3; §3.1's cost-geometry interaction is.

Disclosed caveat: `_resolve_bar` continues the no-flatten counterfactual on the 5Min bar series
regardless of session hours, so part of this resolution happens on extended-hours bars where a
live bracket leg would not actually execute; given the effect's magnitude above (<0.1R, already
second-order), this does not change the conclusion.

---

## §6 Equity replay per sizing cap (`{0.10, 0.25, 0.50, 1.00}`)

Per #499's established method (a replay of the same 6 trade ledgers — not 6 additional
trials): `qty = min(floor(SIZING_RISK_PCT · equity / stopDistance), floor(cap · equity /
entryPrice))`, compounding trade-by-trade from a $100,000 nominal start.

| Cadence | R | cap=0.10 | cap=0.25 | cap=0.50 | cap=1.00 |
|---|---|---|---|---|---|
| 60m | 1.0 | -30.05% | -59.36% | -83.27% | -96.99% |
| 60m | 1.5 | -29.71% | -58.85% | -82.87% | -96.84% |
| 60m | 2.0 | -29.52% | -58.61% | -82.66% | -96.75% |
| 30m | 1.0 | -55.23% | -86.61% | -97.81% | -99.58% |
| 30m | 1.5 | -52.51% | -84.57% | -97.27% | -99.51% |
| 30m | 2.0 | -51.14% | -83.40% | -97.05% | -99.49% |

**Every cell breaches the -15%-from-start equity floor at every sizing cap tested, including
the smallest (0.10).** This is a direct, mechanical consequence of §3's negative per-trade
expectancy compounding over 1,800-4,200 trades — no cap size makes this grid viable at the
frozen geometry and cost model. This equity-floor breach is a **finding to flag**, not a live
event: `bot_config.paused`/the -15% floor is modeled as never firing DURING the simulation
itself (Q3's "modeled by assumption"); this replay is a separate, after-the-fact accounting
pass precisely so a breach like this one is visible rather than silently absorbed.

---

## §7 Power disclosure (binding on every number above)

Per the pre-registration doc's §2/§8: 2,738 sessions, **`n_w=10 < 13`** the #398 promotion
floor. **DIRECTIONAL power only.** No DSR/PBO/bootstrap statistic is computed anywhere in this
package; nothing here is a gate-eligible read. Every number in §3-§6 is a **checkpoint input**,
not a promotion attempt — the magnitude and consistency of the negative result (every cell,
every cap, a well-quantified mechanism in §3.1) make it a strong directional signal despite the
power ceiling, but it is not, and is not claimed to be, a statistically gated conclusion.

---

## §8 Checkpoint framing and non-goals

- **Input to the ~Aug 26-28 review, not a live change.** Nothing in this package modifies
  `HOURLY_STOP_BUFFER_PCT`, `HOURLY_BRACKET_R_MULTIPLE`, any cadence, or any sizing constant —
  the live hourly bot is unaffected regardless of this verdict. A live parameter change (e.g.
  widening the stop buffer to reduce the cost-drag fraction found in §3.1) needs its own
  brainstorm and ADR.
- **No new decision rule.** `decideHourly` and the frozen 14-detector registry were imported
  and called unchanged; nothing about the signal itself was touched or re-tuned.
- **No re-fetching or committing of bar data.** The staged local CSVs (pre-registration doc §2)
  are the only input; `git ls-files data/` is empty in every commit of this package (verified
  in §9).
- **What this DOES license:** the ~Aug 26-28 checkpoint should treat "hourly bracket geometry at
  the current `HOURLY_STOP_BUFFER_PCT`/cost-constant combination" as a closed direction absent
  new information (a wider stop buffer, a different cost assumption, or full-power data), and
  should weigh §3.1's cost-drag mechanism specifically if a future round wants to revisit this
  family — the natural next axis is stop-buffer width, not R or cadence (both already swept
  here).

---

## §9 Verification / reproduction

```bash
CLAUDE_AGENT_NO_BROKER=1 deno task test        # 1040 passed, 24 ignored
deno task lint                                  # clean
deno task fmt:check                             # clean
venv/bin/python -m pytest tests/ -q             # 934 passed
git diff --stat main -- supabase/functions/ supabase/migrations/ .env.example README.md  # empty
git ls-files data/                              # empty
grep -rn "createAlpacaClient\|/v2/orders" scripts/emit_hourly_decisions.ts backtest/hourly_geometry.py backtest/run_hourly_geometry_study.py  # no matches
```

Regenerate the decisions CSVs and the full grid (never committed — local scratch only):

```bash
CLAUDE_AGENT_NO_BROKER=1 deno run --allow-env --allow-read=data,scripts,supabase/functions \
    --allow-write=<out-dir> scripts/emit_hourly_decisions.ts \
    --bars data/intraday/SPY_60min.csv --bars5 data/intraday/SPY_5min.csv \
    --out <out-dir>/decisions_60m.csv --period-minutes 60
CLAUDE_AGENT_NO_BROKER=1 deno run --allow-env --allow-read=data,scripts,supabase/functions \
    --allow-write=<out-dir> scripts/emit_hourly_decisions.ts \
    --bars data/intraday/SPY_30min.csv --bars5 data/intraday/SPY_5min.csv \
    --out <out-dir>/decisions_30m.csv --period-minutes 30
venv/bin/python -m backtest.run_hourly_geometry_study \
    --decisions-60m <out-dir>/decisions_60m.csv --decisions-30m <out-dir>/decisions_30m.csv \
    --bars5 data/intraday/SPY_5min.csv
```

---

## §10 `tested_cells.py` ledger flip

Both `hourly_bracket_geometry_sizing` records (`cadence="hourly"` and `cadence="30m"`,
`vehicle="SPY"`) flip from `PENDING`/`power="NONE"` to `verdict=DIRECTIONAL_NO_GO`/
`power="DIRECTIONAL"` — `DIRECTIONAL_NO_GO`, not `NO_GO`, because power here is `DIRECTIONAL`
(`n_w=10 < 13`), per this ledger's own vocabulary (`NO_GO` is reserved for a `PROMOTABLE`-power
read; a `DIRECTIONAL_NO_GO` is explicitly re-testable at full power). `cumulative_trials(
"hourly_bracket_geometry_sizing")` goes from `0` (PENDING rows are excluded) to `6` (this
round's 6 registered trials — the sizing-cap replay is not counted separately, per §1/§6).
