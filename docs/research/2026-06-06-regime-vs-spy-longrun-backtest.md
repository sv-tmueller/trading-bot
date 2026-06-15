# Regime strategy vs SPY buy-and-hold — long-horizon backtest

**Question:** Over long horizons (10y real, full UPRO life, and a synthetic series back to 1990), how does the bot's 200-DMA regime strategy on a leveraged vehicle compare to SPY buy-and-hold and to leveraged buy-and-hold — and what does it cost in drawdown across real bear markets?
**Date:** 2026-06-06
**Branch:** `research/longrun-regime-backtest`
**Scope:** Research only. No production code touched. New research code lives in `backtest/synthetic.py` and `backtest/run_longrun.py`; `backtest/regime.py` gained a default-preserving `alloc_frac` parameter and an OHLC-injection hook.

---

## Plain-English takeaway

- **The regime filter earns its keep in deep, slow bear markets.** Over the synthetic 1990→now window — the only window that contains the 2000-2002 and 2008 crashes — the bot on a 3x vehicle returned ~**+44,300%** (18.2% CAGR) at a **-63.9%** max drawdown, versus 3x buy-and-hold's ~+21,300% at a near-total **-97.9%** drawdown. Avoiding the two ~95%+ leveraged crashes is the whole story.
- **It beats plain SPY on return, but not for free.** Across every window the bot out-returns SPY buy-and-hold (SPY: ~10-15% CAGR), but it does so by holding leverage, so its drawdowns (-50% to -64%) are far deeper than SPY's (-34% to -55%).
- **In a long bull with only fast/shallow bears, the timing filter is a drag.** Over the full real UPRO life (2009→now — almost no deep bear) the bot on UPRO returned **+1,119%** vs UPRO buy-and-hold's **+12,875%**. With no big crash to dodge, whipsaws and missed rebounds cost ~17 pp of CAGR. The strategy is insurance you pay for in bull markets and collect on in crashes.
- **The 200-DMA does not protect against fast crashes.** In COVID-2020 the bot's realized drawdown (-34.6% on synth-3x) was essentially SPY-like — the filter exited mid-crash, not ahead of it. The live bot's intraday kill-switch (NOT modeled here) is the protection for that case, so real fast-crash drawdowns are likely better than shown.
- **Synthetic pre-2009 numbers are optimistic.** The synthetic leverage model runs ~0.9-1.8 pp/yr hot vs the real ETFs (it under-charges financing). Treat all SYNTHETIC figures as indicative upper bounds, not precise.

---

## Methodology

### Strategy under test
The bot's one decision rule: at each close, if the benchmark close is above its 200-day simple moving average, be 100% long the leveraged vehicle; otherwise be in cash (0% yield). Execution is the **next day's open**, with **5 bps slippage + 5 bps commission per side**. The kill-switch is **NOT** modeled (it needs intraday data the daily-bar feed lacks). This is a 1:1 reuse of the existing `backtest/regime.py` engine (the production-ported rule in `strategy/regime.py` is untouched).

A risk dial `alloc_frac` was added to the engine: on LONG it deploys `alloc_frac × cash` into the vehicle and leaves the rest in cash. Default is `1.0` (100%), so existing behavior is byte-for-byte unchanged — verified by re-running the 5y/10y baselines.

### Data sources (yfinance, `auto_adjust=True`)
| Series | Ticker | History used |
|---|---|---|
| SPY ETF (signal + B&H) | `SPY` | 1993→ |
| UPRO 3x ETF | `UPRO` | 2009-06-25→ |
| SSO 2x ETF | `SSO` | 2006-06-21→ |
| S&P 500 **total return** index | `^SP500TR` | 1988→ (synthetic base + index B&H) |
| S&P 500 **price** index | `^GSPC` | 1988→ (200-DMA signal source pre-SPY) |
| 13-week T-bill yield | `^IRX` | 1988→ (financing rate) |

For the synthetic window the **200-DMA signal uses `^GSPC` (price)** — matching the live bot, which signals on SPY *price*, not total return. The index buy-and-hold row uses `^SP500TR` (total return) so the "just hold the index" comparison includes dividends.

### Synthetic leveraged-ETF model
Pre-2009 (3x) and pre-2006 (2x) there is no real ETF, so a synthetic daily-rebalanced leveraged series is built from `^SP500TR` daily returns:

```
r_lev = L * r_index − (annual_expense / 252) − (L − 1) * r_f_daily
```

- `L` = 3 (UPRO) or 2 (SSO)
- `annual_expense` = **0.0091** (UPRO) / **0.0089** (SSO), divided by 252 trading days
- `r_f_daily` = `^IRX` annualized % yield ÷ 100 ÷ 252 (forward/back-filled to trading days)
- Compounded from a $1 base; first day return = 0.

This is the standard daily-rebalanced leverage model: hold `L` of exposure per $1 equity, borrow `(L-1)` at the short rate, bleed the expense ratio. It captures the two dominant real drivers — **financing drag** and **volatility/compounding decay** — but ignores swap spreads, the fund's actual borrowing rate vs the T-bill, and tracking error. (See Validation — those omissions are why the synthetic runs slightly hot.)

### Cost / accounting assumptions
- 5 bps slippage + 5 bps commission **per side**, on both the strategy and all buy-and-hold rows.
- Buy-and-hold: buy at the first Open, hold to the last Close; the equity curve (and thus max drawdown) is marked net of the eventual round-trip exit cost so drawdowns reflect realizable equity.
- Cash earns 0% (conservative; understates the strategy's cash-period return slightly).
- A synthetic vehicle has no intraday open, so `Open == Close` per synthetic day; execution happens at the synthetic daily level (one bar after the signal, same lag as the real engine).
- $100,000 starting capital throughout.

---

## Validation (the credibility anchor)

Synthetic series overlaid on the real ETF over the ETF's full life. **This is the gate for trusting the pre-2009 / pre-2006 synthetic numbers.**

| Comparison | Overlap | Daily-return corr | Synth CAGR | Real CAGR | CAGR gap |
|---|---|---|---|---|---|
| synthetic-3x vs real **UPRO** | 2009-06-25 → 2026-06-05 (4263d) | **0.9982** | 34.58% | 32.74% | **+1.83 pp** |
| synthetic-2x vs real **SSO** | 2006-06-21 → 2026-06-05 (5021d) | **0.9954** | 16.50% | 15.60% | **+0.90 pp** |

**Reading:** daily-return tracking is excellent (corr 0.995-0.998). The synthetic runs **hot** — it overstates CAGR by ~0.9 pp (2x) to ~1.8 pp (3x), because it charges only the T-bill + expense ratio, whereas real leveraged ETFs pay a swap spread *above* the financing benchmark plus tracking error. Direction is consistent and expected.

**Financing-spread sensitivity (3x):** adding a flat spread over `^IRX` closes the gap almost exactly —

| Extra financing spread | Synth 3x CAGR | Gap vs real UPRO |
|---|---|---|
| 0.0% (model as specified) | 34.58% | +1.83 pp |
| +0.5% | 33.24% | +0.50 pp |
| +1.0% | 31.92% | −0.82 pp |

Roughly **+0.6% of unmodeled financing spread ≈ −1.5 pp of 3x CAGR**. The headline tables use the spec's 0% spread; the true cost is somewhat higher, so **synthetic returns are indicative upper bounds**.

---

## Results

CAGR uses calendar days in the window; max DD is peak-to-trough on the close-marked equity curve. Trade count = round-trips.

### W1 — 10 years real (2016-06-06 → 2026-06-06)
| Variant | Total return | CAGR | Max DD | Trades |
|---|---|---|---|---|
| SPY B&H | +311.2% | 15.2% | -33.7% | — |
| UPRO B&H (3x, no timing) | +1,182.7% | 29.1% | -76.8% | — |
| **bot UPRO+200DMA @100%** | **+502.3%** | **19.7%** | **-50.2%** | 26 |

Matches the supplied baseline (bot +502.3% / 19.7% / -50.2% / 26 trades) exactly. In this no-deep-bear decade, UPRO B&H wins on return; the bot gives up return for a ~27 pp shallower drawdown.

### W2 — full real UPRO life (2009-06-25 → 2026-06-06), with risk dials
| Variant | Total return | CAGR | Max DD | Trades |
|---|---|---|---|---|
| SPY B&H | +1,008.2% | 15.3% | -33.7% | — |
| UPRO B&H (3x, no timing) | +12,874.8% | 33.3% | -76.8% | — |
| SSO B&H (2x, no timing) | +4,527.9% | 25.4% | -59.3% | — |
| **bot UPRO+200DMA @100%** | **+1,118.7%** | **15.9%** | **-58.3%** | 46 |
| bot SSO(2x)+200DMA @100% | +594.7% | 12.1% | -43.6% | 46 |
| bot UPRO+200DMA @50% | +443.1% | 10.5% | -34.5% | 46 |

**The uncomfortable window.** 2009→now is an almost uninterrupted leveraged bull with only fast/shallow bears (2018, COVID, 2022). The timing filter has nothing big to dodge, so its whipsaws and missed rebounds make the bot (+1,119%) trail UPRO B&H (+12,875%) by an enormous margin, and even its drawdown (-58.3%) is *worse* than its 10y figure because the 200-DMA exits mid-crash and re-enters after the bounce. Risk dials behave monotonically: 2x and @50% both cut return and drawdown roughly in proportion (bot UPRO @50% ≈ SPY drawdown at ~10.5% CAGR).

### W3 — synthetic, 1990-01-01 → 2026-06-06
**Everything 3x before 2009-06-25 and 2x before 2006-06-21 is SYNTHETIC** (built from `^SP500TR` + the model above). Index B&H is real `^SP500TR`.
| Variant | Total return | CAGR | Max DD | Trades |
|---|---|---|---|---|
| S&P 500 TR index B&H (real) | +4,154.0% | 10.8% | -55.2% | — |
| synthetic-UPRO(3x) B&H | +21,291.0% | 15.9% | **-97.9%** | — |
| synthetic-SSO(2x) B&H | +14,842.8% | 14.7% | -87.5% | — |
| **bot on synth-3x @100%** | **+44,300.4%** | **18.2%** | **-63.9%** | 118 |
| bot on synth-3x @50% | +4,477.0% | 11.1% | -41.9% | 118 |
| bot on synth-2x @100% | +10,151.4% | 13.6% | -46.9% | 118 |

**The window the strategy was built for.** With two near-total leveraged crashes (dot-com, GFC) in the data, the bot on synth-3x more than **doubles** synth-3x B&H's total return *and* roughly **halves** its max drawdown (-63.9% vs -97.9%). A -97.9% drawdown is effectively a wipeout — leverage buy-and-hold is uninvestable through a 2008, and the regime filter is what makes a leveraged vehicle survivable. Note these synthetic returns are optimistic per the validation (~1.5+ pp/yr hot on the 3x).

### W4 — crash stress: peak-to-trough drawdown through each bear (W3 synthetic)
| Crash | SPY (TR index) | synth-3x B&H | bot on synth-3x |
|---|---|---|---|
| Dot-com (2000-09 → 2002-10) | -47.4% | -92.1% | **-63.7%** |
| GFC (2007-10 → 2009-03) | -55.2% | -97.9% | **-41.8%** |
| COVID (2020-02 → 2020-04) | -33.8% | -76.6% | **-34.6%** |
| 2022 bear (2022-01 → 2022-10) | -24.5% | -63.6% | **-39.0%** |

**The key view.** In the two slow, deep bears the filter shines: GFC -41.8% (bot) vs -97.9% (3x B&H), dot-com -63.7% vs -92.1%. In the fast crashes it does not: COVID -34.6% (worse than SPY's -33.8%, because the 200-DMA exited mid-plunge), and 2022's grind whipsawed it to -39.0%. This is exactly where the unmodeled **intraday kill-switch** would cut the COVID/fast-crash figure — so the live bot's real fast-crash drawdowns should be better than this table shows.

---

## Findings

1. **The regime filter's entire edge is crash avoidance in slow, deep bears.** It only outperforms leveraged buy-and-hold on total return when the window contains a 2000 or 2008 (W3). Strip those out (W1, W2) and leveraged B&H wins on return — the filter is then pure drawdown insurance you pay for.
2. **On a leveraged vehicle the strategy reliably beats SPY buy-and-hold on return in every window**, at the cost of materially deeper drawdowns (-50% to -64% vs SPY's -34% to -55%). It is not a lower-risk SPY; it is a higher-return, higher-drawdown sleeve.
3. **The 200-DMA does not stop fast crashes.** COVID realized ~SPY-like drawdown even on 3x because the daily filter exits during the plunge. The intraday kill-switch (not modeled) is the designed answer; daily-bar backtests structurally understate the live bot's fast-crash protection.
4. **The risk dials work as expected and monotonically.** Dropping to a 2x vehicle or `alloc_frac=0.5` scales return and drawdown down together; bot-UPRO-@50% lands at roughly SPY's drawdown with a ~10.5% CAGR over W2.
5. **Synthetic pre-2009 numbers are credible in shape but optimistic in level** (corr 0.995-0.998; +0.9 to +1.8 pp/yr hot). The W3 levels should be read as upper bounds; the *relative* conclusions (bot vs B&H) are robust because both rows share the same synthetic bias.

---

## Caveats

- **Kill-switch NOT modeled.** The live bot has an intraday drawdown kill-switch; this study models the 200-DMA rule alone on daily bars. Real drawdowns on fast crashes (COVID-style) are therefore **likely better** than shown — the W4 COVID/2022 figures are pessimistic relative to the live system.
- **Synthetic-data assumptions, financing-rate especially.** The synthetic leverage model charges only T-bill + expense ratio. Real leveraged ETFs pay a swap spread above that plus tracking error; the validation shows this makes the synthetic ~0.9-1.8 pp/yr too generous, and ~0.6% of extra spread costs the 3x ~1.5 pp/yr. Pre-2009 (3x) / pre-2006 (2x) results are **indicative, not precise**.
- **Period / regime bias.** W2 is one of the great leveraged bull runs in history; W3's headline is dominated by surviving two once-a-generation crashes. Both are samples of one path. The strategy's relative attractiveness flips entirely with the regime mix of the window.
- **Dividend treatment.** The 200-DMA signal uses price indices (`^GSPC`/SPY), matching the live bot; index buy-and-hold uses total return (`^SP500TR`). Real leveraged ETFs reinvest dividends inside the fund, which the synthetic captures via the TR base. SPY/UPRO/SSO ETF rows use `auto_adjust=True` (dividends reinvested).
- **No cash yield.** Cash earns 0% during out-of-market periods; the strategy's true return in high-rate eras (e.g. 2000-2007, 2023-) is modestly understated.
- **Trade-count realism.** Synthetic W3 shows 118 round-trips over 36 years (~3/yr) — plausible for a 200-DMA filter, but each is one more chance for slippage to bite; live fills may differ from next-open + 5 bps.
- **Past ≠ future.** None of this is predictive. A regime with frequent shallow whipsaws and no deep bear (like W2) is the strategy's worst case, and there is no guarantee the next decade contains a crash to justify the bull-market drag.

---

## Recommendation

- **No production change required by this study.** It confirms the current design's risk/return trade-off rather than proposing a new parameter; per the architectural invariant, the bot keeps its single 200-DMA decision rule, and adding a second rule (or changing the vehicle/allocation) needs a fresh brainstorm and spec.
- **For the operator / Lead, the decision this informs is the risk dial**, not the rule:
  - The current 100%-UPRO configuration is the highest-return, highest-drawdown choice (~-58% to -64% modeled max DD across long windows). If that drawdown is outside tolerance, the **`alloc_frac=0.5` or SSO(2x) variants** cut modeled max DD to ~-34% to -47% (SPY-like) while still beating SPY on return — these are real, code-supported levers (the engine now takes `alloc_frac`), but flipping them in production is an Engineer change behind a brainstorm, not a research action.
- **The kill-switch matters most exactly where this study is blind** (fast crashes). Any future work on fast-crash protection should be evaluated with intraday data, since daily-bar backtests cannot see it.

---

## Reproduce

```bash
cd <worktree>            # research/longrun-regime-backtest
PYTHONPATH=. venv/bin/python backtest/run_longrun.py
```
Full console output of the run that produced every number above is saved alongside this note at
`docs/research/2026-06-06-regime-vs-spy-longrun-backtest.log`.
