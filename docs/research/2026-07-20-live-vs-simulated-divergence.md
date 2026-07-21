# Live-vs-simulated divergence report

**Date:** 2026-07-20 · **Issue:** #403
**Harness:** `backtest/run_live_divergence.py` (`tests/test_run_live_divergence.py`), fed by
`scripts/export_live_history.sh`

---

## 1. Summary / verdict

Over the live paper-trading window so far (2026-06-05 → 2026-07-20, 30 trading days), the
production 200-DMA rule's real execution **tracks the backtest's execution model closely once the
go-live ramp is excluded**. The only two live fills observed diverge sharply from the modeled
5 bps slippage / 10 bps total cost on a per-fill basis (as expected — a single day's intraday price
swing dwarfs a few bps of assumed slippage), but there is zero signal-parity or execution-parity
divergence across all 30 recorded `regime_state` rows: the DB's `target_state`/`current_state`
always agreed with a pure replay of the rule. **Verdict: no reason yet to distrust the backtest's
forward guidance** — the sample (2 fills, 30 days, one long-only regime with no flips) is small, and
Section 8 states concrete numbers for when that verdict should flip.

---

## 2. Method and reproduction

1. Export the live record (read-only, GET-only PostgREST calls; see
   `scripts/export_live_history.sh`):
   ```bash
   bash scripts/export_live_history.sh --env-file /Users/thomas.mueller/Desktop/github/trading-bot/.env.backfill
   ```
   Writes `live_export/{equity_snapshots,trades,regime_state,audit_log}.csv` (gitignored — this
   directory is never committed).
2. Run the replay + comparison:
   ```bash
   venv/bin/python -m backtest.run_live_divergence --export-dir live_export/
   ```
3. Offline test suite (all pure functions, no network): `venv/bin/python -m pytest tests/test_run_live_divergence.py -q`.

**Snapshot window used for this report:** `equity_snapshots` 2026-06-05 → 2026-07-20 (30 rows),
`trades` 2 fills, `regime_state` 30 rows, `audit_log` (daily-check only) 60 rows.

**Replay design (D3 anchor, per the #403 SUB_PLAN):** `starting_cash` = the earliest snapshot's
`equity_usd` ($999,996.85); simulated one trading day before the window start so the T+1-shifted
signal is valid on day 1, then sliced to the window (the `backtest/walkforward.py` Trap-A idiom).
Tracking error is reported twice — full window, and since the first live fill (2026-06-11) — so the
execution model's fidelity can be read separately from the go-live entry-timing effect. As of this
revision, `compute_tracking`/`run_report` also emit a `starting_cash`-normalized
`terminal_return_diff_cash_normalized` alongside the original close-normalized
`terminal_return_diff` for the full-window comparison — see Section 6 for why both are needed.

**Re-run note (this revision, #403 review round 1):** the export CSVs are the same
2026-07-20-captured snapshot used in the original report (`live_export/` is gitignored and never
re-exported from Supabase for a docs fix), but the yfinance SPY/UPRO fetch was re-run on
2026-07-21 to pick up the `terminal_return_diff_cash_normalized` field. yfinance's own history for
recent trading days can shift slightly between fetches (adjustment recalculation as new bars/
dividends land), so the tracking-error numbers below differ modestly from the original capture
(full-window terminal diff moved from +3.58pp to +4.43pp close-normalized); the fill-slippage and
divergence-date numbers, which only depend on values from specific fixed historical dates, did not
move. All numbers in this doc come from this single fresh run and are internally consistent with
each other.

**Captured output** (this run, `venv/bin/python -m backtest.run_live_divergence --export-dir live_export/`):

```
Live window: 2026-06-05 -> 2026-07-20  (starting cash $999,996.85)

Tracking error (full window):
  n_days                   30
  terminal_return_diff     0.044325
  terminal_equity_ratio    1.112334
  mean_abs_daily_gap       0.031509
  max_abs_daily_gap        0.049735
  daily_return_diff_std    0.010198
  terminal_return_diff_cash_normalized 0.106279

Tracking error (since first live fill):
  n_days                   26
  terminal_return_diff     0.010353
  terminal_equity_ratio    1.112334
  mean_abs_daily_gap       0.002754
  max_abs_daily_gap        0.011832
  daily_return_diff_std    0.002781

Fill slippage: 2 fill(s)
                    fill_time symbol side  qty  fill_price  open_price    cost_bps  delta_vs_slippage_bps  delta_vs_total_bps
2026-06-11 14:37:11.000044+00   UPRO  BUY 7458    133.0571  132.137504   69.593871              64.593871           59.593871
2026-07-07 14:37:04.621727+00   UPRO  BUY   53    141.5266  143.750000 -154.671304            -159.671304         -164.671304

Divergence dates: 0 signal-parity, 0 execution-parity (of 30 rows)
  max |spy_close diff %|  = 2.3432
  max |spy_sma200 diff %| = 0.6776
```

---

## 3. Live window facts

- **Deployed to the Alpaca paper account:** 2026-06-05 (dev Supabase project `qdaxxsuicyiscdvsdowc`).
- **First bot-executed fill:** 2026-06-11 (BUY 7,458 UPRO @ $133.0571) — matches
  `docs/trading-journal/2026-W25.md`.
- **Pre-production bring-up (2026-06-05 → 2026-06-10):** `audit_log` shows irregular invocation
  timestamps (18:44 and 22:30 UTC — outside the standard 13:37/14:37 UTC cron slots), consistent
  with manual smoke-test runs before the scheduled cron went live. Two of these hit
  `error:Error`/`error:OrderTimeoutError` ("BUY ... did not fill within 30000ms; cancelled") at
  22:30 UTC and 13:37 UTC. The 22:30 UTC timeout being "expected outside market hours" is an
  *inference*, not settled fact: `daily-check`'s `/v2/clock` gate is designed to exit
  `skipped:market_closed` before placing any order when the US market is closed, so a 22:30 UTC
  order attempt reaching a live-broker order-timeout path at all is itself the anomaly this doc
  is inferring an explanation for — most plausibly a manual/ad-hoc invocation during
  pre-production bring-up that bypassed or predated the clock gate (or invoked the function
  directly rather than via cron), rather than the standard `daily-check` path behaving as
  documented. This has not been independently confirmed against the dev Supabase project's
  invocation history. From 2026-06-11 onward, the schedule is the standard two-slot cron
  (13:37/14:37 UTC) with no further errors through 2026-07-20.
- **Second fill:** 2026-07-07, BUY 53 UPRO @ $141.5266 (`reason=regime_flip_long` — a small top-up,
  not a CASH→LONG flip; no intervening CASH day appears in the exported `regime_state`, so this is
  most likely a same-day-buy-power sizing adjustment rather than a second entry from flat).
- **Regime flips in-window:** none. `target_state`/`current_state` are `LONG` for all 30 exported
  `regime_state` rows — SPY stayed comfortably above its 200-DMA (recorded `spy_close` $725–$755 vs
  `spy_sma200` $684–$693, a ~6–10% margin) for the entire window.

---

## 4. Signal parity

**0 of 30** `regime_state` rows show a `target_state` disagreeing with a pure replay of the 200-DMA
signal (`replayed_target` = LONG iff the yfinance-derived signal at the prior trading day is True).
Unsurprising given SPY's persistent 6–10% margin above its SMA200 all window — no realistic
data-source drift gets close to flipping that comparison.

**Alpaca-vs-yfinance data-source drift** (recorded `spy_close`/`spy_sma200` vs the yfinance value
for the same prior trading day, all 30 rows):

| | close diff % | sma200 diff % |
|---|---|---|
| max abs | 2.343% (2026-06-05 only) | 0.678% (early window only) |
| max abs, excluding 2026-06-05 | 0.312% | 0.251% |
| steady-state (last 10 rows) | mean ≈ 0.005% | mean ≈ -0.007% |

The single 2.34%/0.68% outlier is the 2026-06-05 row — the pre-production manual invocation
described in Section 3, plausibly reading a different/stale reference bar than the standard
post-open cron path uses. From 2026-06-08 onward the close drift is ≤0.31% and decays to
essentially flat (≤0.02%) within about two weeks; the SMA200 drift is a small, stable ~0.007%
(sign-consistent, Alpaca reading a hair below yfinance) once past the same early transient — this
is the residual data-source drift the SUB_PLAN asked to quantify rather than assume away
(adjustment-methodology differences between Alpaca's `adjustment=all` and yfinance's
`auto_adjust=True` account for a fraction-of-a-percent structural offset, not a few percent).

---

## 5. Execution parity

**0 of 30** `regime_state` rows show `current_state` disagreeing with the replayed position — every
recorded execution state matches what a pure signal replay implies. This means the *only* divergence
between "when the backtest would have entered" and "when the live bot actually entered" is the
**go-live ramp**: a from-scratch replay starting 2026-06-05 would go LONG at the very first simulated
open (SPY was already above its SMA200 on day 1), while the live bot's first confirmed fill was
2026-06-11 — six trading days later, spanning the pre-production bring-up window described in
Section 3 (irregular manual invocations, two order timeouts outside market hours). This is exactly
the "genuine, explainable divergence" the SUB_PLAN flagged in advance.

**Caveat — this axis did not itself detect the ramp.** `compute_divergence_dates`'s
execution-parity check compares the replayed position against `regime_state.current_state` as
*recorded*, and that record read `LONG` for 2026-06-05 → 06-10 despite no live fill existing yet
and equity being flat over that span — i.e. the DB row was written ahead of an actual execution
during bring-up, so the comparison is structurally blind to the ramp in this dataset (0 execution
mismatches, not because the axis caught and explained the ramp, but because the recorded state
already matched the replay for reasons unrelated to a real fill). The go-live ramp was actually
detected by cross-referencing `trades` (first fill 2026-06-11) against the flat 2026-06-05→06-10
equity, not by an execution-parity mismatch — `audit_log` then supplies the "why" (deploy-week
manual testing, not a live-production execution failure). Section 6's since-first-fill tracking
isolates the ramp's cost from the execution model's own fidelity regardless of which axis surfaced
it.

---

## 6. Tracking error

| | Full window (30d) | Since first live fill (26d) |
|---|---|---|
| Terminal return diff, **close-normalized** (live − sim) | +4.433 pp | **+1.035 pp** |
| Terminal return diff, **cash-normalized** (live − sim, ÷ `starting_cash`) | **+10.628 pp** | n/a — see below |
| Terminal equity ratio (live / sim) | 1.1123 | 1.1123 |
| Mean abs daily gap | 3.151% | 0.275% |
| Max abs daily gap | 4.974% | 1.183% |
| Std of daily return diffs | 1.020% | 0.278% |

(Terminal equity ratio is endpoint-only, so it is identical in both columns — both windows end on
the same date.)

**Reconciling the two full-window headline numbers.** `compute_tracking`'s original
`terminal_return_diff` (+4.433 pp) is **close-normalized**: it expresses each curve as a return
relative to *its own* first common-date value, then diffs the two returns. That normalization is an
artifact for this specific comparison. The replay's Trap-A restart already executes the go-live-ramp
entry trade at the very first day of the tracking window (Section 5) — SPY was already above its
SMA200 on day 1 — so by the close of that first day the sim's own equity value already embeds that
day's ~6.3% open-to-close loss on the entry trade. Because close-normalization treats the sim's
first-common-date value as its 100% baseline, that day-one loss is silently absorbed into the
baseline rather than counted as tracking error — understating the true from-equal-cash gap. The live
account, still in cash for that stretch, has no such baseline distortion.

The **cash-normalized** variant (`terminal_return_diff_cash_normalized`, added to `compute_tracking`/
`run_report` in this revision) fixes this: it anchors both curves to the single `starting_cash` value
they were both actually funded with (D3's anchor), rather than to each curve's own first-common-date
value. It reads **+10.628 pp** — within ~0.6 pp of `terminal_equity_ratio − 1` (1.1123 − 1 =
+11.234 pp), the two being close-but-not-identical only because the ratio's denominator is the sim's
*terminal* value (which itself drifted a little from `starting_cash` over the 30 days) rather than
`starting_cash` itself; both numbers agree that the true from-equal-cash full-window gap is
**≈ +10.6–11.2 pp, roughly 2.4x this revision's own +4.433 pp close-normalized headline** (and
roughly 3x the ~+3.58 pp close-normalized figure originally reported in round 1, before the
yfinance re-fetch described in Section 2).
**Corrected ramp magnitude:** the go-live ramp (Section 5) therefore cost the live account on the
order of **10–11 percentage points** of relative terminal return over this 30-day window — not the
+4.433 pp this revision's own close-normalization artifact implies (nor the ~+3.58 pp of the
original round-1 report) — because it both delayed entry by six trading days
*and* caused the close-normalized comparison to hide the sim's own day-one execution loss inside its
baseline.

Once the ramp period is excluded entirely (since-first-fill, which needs no cash-normalization
because both curves are anchored to the same first-common-date equity value in that sub-window — the
live account's actual post-fill balance), the residual gap is **+1.035 pp terminal / 0.275% mean
daily / 1.183% max daily** over 26 days. This is larger than the ~0.18 pp originally reported (a
same-day yfinance re-fetch shifted the late-window prices slightly, per the Section 2 re-run note)
but still small relative to the full-window ramp effect, and — cross-checked against Section 7's
two realized fill-cost deltas (+59.6 bps and −164.7 bps vs modeled total, a net of −52.5 bps) — is
consistent with the execution model (T+1 open fill, 5 bps slippage, 5 bps commission) being a
reasonable approximation of the real Alpaca fills once the entry timing is held equal; it is not
distinguishable from cost-model noise at n=2 fills. (Section 8's tracking-axis threshold is derived
from this since-first-fill residual and is updated below to match this revision's re-run numbers;
it is a re-derivation from the same methodology, not a change in verdict.)

---

## 7. Realized slippage per fill vs modeled

| Fill | Side | Fill price | Same-day open | Realized cost | vs modeled 5 bps slippage | vs modeled 10 bps total |
|---|---|---|---|---|---|---|
| 2026-06-11 14:37:11 UTC (7,458 sh) | BUY | $133.0571 | $132.1375 | **+69.59 bps** | +64.59 bps | +59.59 bps |
| 2026-07-07 14:37:05 UTC (53 sh) | BUY | $141.5266 | $143.7500 | **-154.67 bps** | -159.67 bps | -164.67 bps |

(`cost_bps` sign convention: positive = cost you money relative to the day's open, for both BUY and
SELL — directly comparable to the modeled `SLIPPAGE_BPS`/`COMMISSION_BPS` constants in
`backtest/regime.py`.)

Both realized costs are an order of magnitude larger in absolute terms than the 10 bps modeled total
— but in **opposite directions** (+69.6 bps vs -154.7 bps), consistent with the SUB_PLAN's caveat:
the fill happens at ~9:37 ET (daily-check runs at 13:37/14:37 UTC), about 7 minutes after the 9:30 ET
open, and ordinary intraday price movement over those 7 minutes routinely swamps a modeled 5–10 bps
slippage assumption in either direction. Alpaca is commission-free in practice, so the "vs modeled
10 bps total" column overstates the true expected cost gap somewhat; the "vs modeled 5 bps slippage"
column is the fairer one-sided comparison. With only two fills, there is no reliable central
tendency yet (a straight average of +69.6 and -154.7 is -42.5 bps, i.e. net favorable so far, but
that is not a statistically meaningful sample) — Section 8 sets the sample-size bar for when a
distribution can be trusted.

---

## 8. Threshold recommendation

Concrete, data-derived triggers for when to stop trusting the backtest's forward guidance and
investigate before acting on it further:

- **Cost axis.** With n=2 fills, no median is statistically meaningful yet — do not compute a
  trust/distrust verdict on cost until **at least 10 fills** have accumulated. Once there are 10+:
  **distrust the backtest's cost assumption if the rolling median `|realized cost_bps|` across the
  most recent 10 fills exceeds ~50 bps** (5× the modeled 10 bps total, and comfortably above the
  ~7-minute execution-drift noise floor implied by the two fills observed so far) — and if so,
  re-derive the backtest's CAGR/Sharpe with the realized median cost substituted for
  `SLIPPAGE_BPS + COMMISSION_BPS` before trusting any forward number from it.
- **Signal axis.** **Any future *unexplained* `target_state` divergence (signal-parity mismatch in
  Section 4's terms) = stop trusting the backtest until root-caused.** The observed steady-state
  Alpaca-vs-yfinance data drift is tiny (≤0.31% close, ~0.007% SMA200, Section 4) against a signal
  margin that has been 6–10% all window — so under anything like current conditions, a genuine
  signal disagreement should never occur from data-vendor noise alone, and one occurring is itself
  the signal that something (a stale Alpaca bar, an unadjusted corporate action, a code regression)
  needs investigating before the bot's next decision is trusted.
- **Tracking axis.** Using the since-first-fill residual (+1.035 pp = +103.5 bps over 26 trading
  days ≈ **+84 bps synthetic "per month" pace** at ~21 trading days/month, Section 6 — this pace,
  not the full-window number, is the right noise floor since it excludes the go-live ramp) as the
  current noise floor: **distrust the backtest if the unexplained residual tracking gap — after
  subtracting the sum of that period's per-fill cost deltas (Section 7) from the raw gap — exceeds
  roughly 250 bps/month.** That is a little over 3× what a quiet, no-flip month like this one shows,
  leaving headroom for a few more real fills' worth of cost-model noise before it would trigger,
  while still catching a genuine execution-model breakdown (e.g. repeated missed fills, a
  systematic pricing bug) well before it compounds into a materially wrong forward expectation.

**Re-run cadence:** re-generate this report monthly (or after any regime flip) once there are more
fills to build a real cost distribution and at least one live flip to exercise Section 4/5 with a
nonzero base rate.
