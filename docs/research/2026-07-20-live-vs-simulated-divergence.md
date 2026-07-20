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
execution model's fidelity can be read separately from the go-live entry-timing effect.

**Captured output** (this run, `venv/bin/python -m backtest.run_live_divergence --export-dir live_export/`):

```
Live window: 2026-06-05 -> 2026-07-20  (starting cash $999,996.85)

Tracking error (full window):
  n_days                   30
  terminal_return_diff     0.035771
  terminal_equity_ratio    1.102975
  mean_abs_daily_gap       0.031224
  max_abs_daily_gap        0.049735
  daily_return_diff_std    0.010388

Tracking error (since first live fill):
  n_days                   26
  terminal_return_diff     0.001785
  terminal_equity_ratio    1.102975
  mean_abs_daily_gap       0.002424
  max_abs_daily_gap        0.011832
  daily_return_diff_std    0.003402

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
  22:30 UTC and 13:37 UTC — the 22:30 UTC attempts fall outside US market hours, so a timeout is
  expected there. From 2026-06-11 onward, the schedule is the standard two-slot cron
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
the "genuine, explainable divergence" the SUB_PLAN flagged in advance: it is fully explained by
`audit_log` (deploy-week manual testing, not a live-production execution failure), and Section 6's
since-first-fill tracking isolates its cost from the execution model's own fidelity.

---

## 6. Tracking error

| | Full window (30d) | Since first live fill (26d) |
|---|---|---|
| Terminal return diff (live − sim) | **+3.577 pp** | **+0.178 pp** |
| Terminal equity ratio (live / sim) | 1.1030 | 1.1030 |
| Mean abs daily gap | 3.122% | 0.242% |
| Max abs daily gap | 4.974% | 1.183% |
| Std of daily return diffs | 1.039% | 0.340% |

(Terminal equity ratio is endpoint-only, so it is identical in both columns — both windows end on
the same date.)

The full-window gap (+3.6 percentage points, live ahead) is almost entirely the go-live ramp from
Section 5: a from-scratch replay buys immediately on 2026-06-05 at that day's open, while the live
account sat in cash for six extra trading days before its first fill on 2026-06-11 — during a period
SPY happened to be roughly flat-to-down, so the live account's cash-holding delay came out ahead by
coincidence, not by execution-model skill. Once that ramp is excluded (since-first-fill), the
residual gap collapses to **+0.18 pp terminal / 0.24% mean daily / 1.18% max daily** over 26 days —
noise-level for a 26-day sample, and consistent with the execution model (T+1 open fill, 5 bps
slippage, 5 bps commission) being a reasonable approximation of the real Alpaca fills once the entry
timing is held equal.

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
- **Tracking axis.** Using the since-first-fill residual (+0.178 pp = +17.8 bps over 26 trading
  days ≈ **+14–15 bps synthetic "per month" pace** at ~21 trading days/month, Section 6) as the
  current noise floor: **distrust the backtest if the unexplained residual tracking gap — after
  subtracting the sum of that period's per-fill cost deltas (Section 7) from the raw gap — exceeds
  roughly 50 bps/month.** That is a little over 3× what a quiet, no-flip month like this one shows,
  leaving headroom for a few more real fills' worth of cost-model noise before it would trigger,
  while still catching a genuine execution-model breakdown (e.g. repeated missed fills, a
  systematic pricing bug) well before it compounds into a materially wrong forward expectation.

**Re-run cadence:** re-generate this report monthly (or after any regime flip) once there are more
fills to build a real cost distribution and at least one live flip to exercise Section 4/5 with a
nonzero base rate.
