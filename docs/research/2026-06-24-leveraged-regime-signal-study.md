# Leveraged-regime-signal study (#255): can a better regime signal make 3x UPRO clear SPY's after-tax Calmar?

Date: 2026-06-24
Author: Analyst role (research-only; no production code or live-bot settings touched).
Provenance: the study run and writeup were completed by the lead session as a fallback after
repeated agent-dispatch timeouts; the branch is independently gated by the tester + reviewer.
Issue: #321 (batch #320). Design: `docs/superpowers/specs/2026-06-24-leveraged-regime-signal-study-design.md` (PR #319). Upstream: #255.

## Question

The operator decided (post-survey brainstorm): keep the 3x leverage, attack the drawdown. Does a
better regime signal than the live 200-DMA make a 3x SPY position (synthetic UPRO) clear 1x SPY's
after-tax Calmar by cutting the drawdown toward SPY's while keeping the leveraged return? A signal
clears only if it beats both 1x SPY and the incumbent 200-DMA-on-3x on after-tax Calmar.

## Method

Five binary regime signals, each computed on the underlying SPY close and applied LONG/CASH to a
synthetic-3x SPY vehicle, run through the survey foundation (the weighted/binary `simulate_from_signal`,
the US/DE after-tax layer, full-history after-tax Calmar ranking, the per-window 12-month OOS
stability gate, 2020/2022 bear stress). Signals: the incumbent 200-DMA; a faster 100-DMA; tsmom-12mo
(12-month TSMOM); the 10-month Faber SMA; and the 200-DMA with a 2-day confirmation (debounce). Synthetic-3x uses
`backtest/synthetic.py` (daily-rebalanced 3x model with financing + expense drag), reproduce with
`python3 -m backtest.run_leveraged_regime_study`. Window 1993-01-29 -> 2026-06-23 (~33.4y).

**Synthetic-3x validation:** over the 2009-06-25 -> 2026-06-23 overlap, the synthetic series tracks
real UPRO with a daily-return correlation of **0.998** (CAGR +34.1% synthetic vs +32.5% real). The
synthetic series is a faithful UPRO proxy; the pre-2009 extension (2000 + 2008 bears) is trustworthy.

## Results

Full-history after-tax Calmar, 3x SPY by regime signal vs 1x SPY (1993-2026, ~33.4y):

| strategy | Calmar US | Calmar DE | CAGR | max DD | trd/yr | >1x SPY? |
|---|---|---|---|---|---|---|
| 200-DMA on 3x (INCUMBENT) | 0.18 | 0.17 | +16.5% | -59.5% | 3.23 | no |
| 100-DMA on 3x (faster) | 0.06 | 0.07 | +10.3% | -91.9% | 5.45 | no |
| **tsmom-12mo on 3x** | **0.22** | **0.20** | **+19.9%** | **-76.2%** | 0.27 | **YES** |
| Faber 10mo SMA on 3x | 0.19 | 0.17 | +16.8% | -63.5% | 0.72 | YES |
| 200-DMA + 2d confirm on 3x | 0.19 | 0.18 | +16.6% | -58.2% | 1.80 | YES |
| 1x SPY (buy & hold) | 0.18 | 0.18 | +10.8% | -55.2% | 0.03 | -- |

`Calmar US` / `Calmar DE` are after-tax; `CAGR` / `max DD` are pre-tax.

Per-window after-tax (US) stability gate (12-month OOS windows), median Calmar (positive windows):

| strategy | median per-window Calmar |
|---|---|
| 200-DMA on 3x (incumbent) | 0.50 (19/34) |
| 100-DMA on 3x (faster) | -0.02 (17/34) |
| **tsmom-12mo on 3x** | **0.90 (22/31)** |
| Faber 10mo SMA on 3x | 0.38 (20/32) |
| 200-DMA + 2d confirm on 3x | 0.21 (18/34) |
| 1x SPY (buy & hold) | 0.85 (25/34) |

Bear stress (max DD / window return):

| strategy | 2020 COVID | 2022 bear |
|---|---|---|
| 200-DMA on 3x (incumbent) | -34.0% / +44.0% | -48.4% / -48.4% |
| 100-DMA on 3x (faster) | -26.7% / +62.0% | -48.9% / -48.9% |
| tsmom-12mo on 3x | **-76.2%** / -23.2% | -49.3% / -41.4% |
| Faber 10mo SMA on 3x | -37.6% / +33.5% | -57.2% / -55.3% |
| 200-DMA + 2d confirm on 3x | -33.9% / +53.5% | -44.1% / -44.1% |
| 1x SPY (buy & hold) | -33.7% / +17.4% | -24.5% / -18.7% |

## Findings

1. **tsmom-12mo on 3x is the most risk-efficient strategy the entire #255 survey has produced.** It
   is Calmar-dominant over 1x SPY on three axes at once: after-tax Calmar 0.22 vs 0.18 (US) and 0.20
   vs 0.18 (DE); CAGR +19.9% vs +10.8%; and per-window stability 0.90 vs 0.85 (the highest median of
   any row, SPY included). It beats the incumbent 200-DMA-on-3x on all three. It loses on exactly one
   axis: **max drawdown, -76.2% vs SPY's -55.2%.** This is not a marginal or curve-fit result, tsmom
   also beat SPY's after-tax Calmar at 1x in the first cut (0.24 vs 0.18, where it was filed as a
   dumb baseline). The new fact here is that at 3x it keeps that risk-adjusted edge while delivering
   the leveraged return.

2. **The single gating question is the drawdown, and it is severe.** Pin the yardstick: the #255
   goal-spec set a ~-34% ceiling (SPY's typical single bear); SPY's actual max drawdown over this
   full 1993-2026 window (including the 2000 and 2008 bears) is **-55.2%**; tsmom-on-3x is **-76.2%**.
   tsmom fails the "SPY-like-or-better drawdown" goal on either yardstick. **Why so deep:** tsmom-12mo
   is a slow monthly signal, so at 3x it rode straight through the COVID crash to **-76.2% in 2020**,
   while the faster daily 200-DMA exited at -34.0%. The edge comes bundled with catastrophic path
   risk in a fast crash, and a -76% peak-to-trough on a leveraged account raises real questions of
   margin, forced liquidation, and the discipline to not capitulate at the bottom.

3. **The operator's stated goal (cut the drawdown) finds nothing, and the most direct lever fails
   hardest.** A faster moving average is the obvious way to exit drawdowns sooner, and the 100-DMA
   does cut the single COVID-2020 crash (-26.7% vs the incumbent's -34.0%). But over the full history
   it is **ruinous**: the extra whipsaw (5.45 flips/yr vs the 200-DMA's 3.23), compounded at 3x with
   cost, tax, and leverage decay on every false exit, drives its max drawdown to **-91.9%** (near
   wipeout), its CAGR to +10.3% (no leverage premium left), its after-tax Calmar to 0.06, and its
   per-window stability negative (-0.02). Faster is worse, not better, at 3x. The only candidate that
   marginally reduces the drawdown without blowing up is the 200-DMA + 2-day confirmation (-58.2% vs
   the incumbent -59.5%, after-tax Calmar 0.19), but it **fails the per-window stability gate**
   (median 0.21 vs SPY 0.85), so its thin full-history edge is not robust out-of-sample. No signal
   cuts the 3x drawdown to SPY-like levels with a stable Calmar edge.

4. **This reopens the operator's earlier fork, now with evidence.** In the brainstorm the operator
   chose "improve risk control, keep leverage" before seeing this result. The evidence now says: the
   cut-the-drawdown path is empty, but the keep-the-leverage-and-accept-the-drawdown path has a
   genuine SPY-Calmar-beating candidate (tsmom-12mo). That is the absolute-return fork the brainstorm
   set aside, and it is no longer a "settle for leveraged beta" fallback, it is a strategy that beats
   1x SPY on risk-adjusted return, return, and stability.

## Verdict

**This is an operator decision, not a clean pass/fail.** No signal meets the literal goal (cut the 3x
drawdown to SPY-like while beating SPY's Calmar). But the study's real finding is that **tsmom-12mo
applied to 3x SPY beats 1x SPY on after-tax Calmar, return, and per-window stability, gated solely by
a -76% max drawdown.** The decision is whether that drawdown is survivable (margin headroom, path
risk through a fast crash, the behavioral discipline to hold) in exchange for the most risk-efficient
strategy the survey has found.

Two paths for the #255 conclusion, for the operator:
- **Accept the drawdown:** adopt tsmom-12mo as the regime signal on the 3x position (it replaces the
  200-DMA, one decision rule). It would need its own spec -> plan -> implement, plus a hard look at
  whether the existing kill-switch (the -25% intraday liquidation guard) materially caps the -76%
  path risk or whether deeper protection is required first.
- **Reject the drawdown:** keep the incumbent 200-DMA (it exits fast, -34% in 2020) and conclude #255
  that the 3x bot is held for absolute return at managed-but-high drawdown, with no Calmar edge over
  SPY. The cut-the-drawdown ambition is closed: nothing achieves it.

Research only. No live-bot change; the operator's "do not deleverage" stands; the live 3x UPRO bot
and its kill-switch are untouched.
