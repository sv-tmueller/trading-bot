# MVP 2.0 — PCS-RIV Backtest (Phase 1 kill-gate)

From __future__ note: research memo, not code.

- **Status:** complete
- **Date:** 2026-06-04
- **Verdict:** **KILL** — the Put-Credit-Spread-on-Regime+IV rule as specified does not clear SPY buy-and-hold under any tested parameterization.
- **Arm run:** modeled (Black-Scholes from SPY + VIX, yfinance). Real Alpaca arm not run — see Caveats.
- **Reproduce:** `venv/bin/python -m backtest.run_pcs_riv --start 2015 [--sweep]`

## TL;DR

Over 2015-01 → 2026-06 (11.4y, 2871 trading days), PCS-RIV on SPY **lost money** at the baseline and at best **broke even** across a 12-point parameter sweep. SPY buy-and-hold returned **+343% (Sharpe 0.83)**; the strategy's best case was **+3.0% (Sharpe 0.14)**. Win rates were high (61–74%) but profit factors hovered at or below 1.0 — the classic premium-selling failure: many small wins, occasional large losses, thin edge eaten by (conservative, modeled) fills. **This is the v1.14 "indistinguishable from a coin flip" lesson, repeating.**

## Method

- **Underlying:** SPY. **Regime gate:** SPY close > SMA(200) (reuses `strategy.regime.compute_target_state`).
- **IV/pricing:** option prices via Black-Scholes with IV = VIX/100 (ATM proxy; skew ignored). IV-rank computed on the VIX series (52wk-style).
- **Entry:** regime-bullish AND IV-rank ≥ threshold → sell put credit spread (short ≈ target delta, long `width` below, ~30–45 DTE).
- **Exit:** 50% credit captured | ≤ 21 DTE | regime flip | expiry.
- **Costs:** conservative fills (sell bid / buy ask) with a **modeled 5% spread per leg** (real bid/ask is OPRA-gated — see `mvp2-alpaca-options-data-spike.md`) + per-contract fees. Risk-fraction sizing (5% of equity per spread).

## Baseline (short_delta 0.30, width 5, IV-rank ≥ 30)

| strategy | total | CAGR | max DD | Sharpe | trades | win |
|---|---|---|---|---|---|---|
| PCS-RIV | **−30.2%** | −3.1% | −35.5% | **−0.60** | 66 | 61% |
| SPY buy-and-hold | +343.3% | 13.9% | −33.7% | **0.83** | — | — |

Profit factor 0.44. Worse drawdown than SPY for a deeply negative return.

## Parameter sweep (modeled arm, sorted by Sharpe)

| width | delta | IV-rank | total | CAGR | Sharpe | trades | win | PF |
|---|---|---|---|---|---|---|---|---|
| 25 | 0.30 | 30 | +3.0% | 0.3% | **0.14** | 79 | 71% | 1.14 |
| 25 | 0.20 | 30 | +1.9% | 0.2% | 0.11 | 82 | 74% | 1.13 |
| 25 | 0.30 | 50 | −0.8% | −0.1% | −0.05 | 22 | 64% | 0.89 |
| 25 | 0.20 | 50 | −0.9% | −0.1% | −0.06 | 23 | 65% | 0.84 |
| 10 | 0.30 | 30 | −3.1% | −0.3% | −0.06 | 73 | 68% | 0.92 |
| 10 | 0.20 | 30 | −3.6% | −0.3% | −0.11 | 79 | 71% | 0.87 |
| 10 | 0.20 | 50 | −4.6% | −0.4% | −0.26 | 21 | 57% | 0.51 |
| 10 | 0.30 | 50 | −8.3% | −0.8% | −0.35 | 19 | 47% | 0.40 |
| 5 | 0.20 | 30 | −16.2% | −1.5% | −0.41 | 74 | 69% | 0.59 |
| 5 | 0.20 | 50 | −10.7% | −1.0% | −0.43 | 19 | 53% | 0.27 |
| 5 | 0.30 | 50 | −16.7% | −1.6% | −0.54 | 19 | 42% | 0.25 |
| 5 | 0.30 | 30 | −30.2% | −3.1% | −0.60 | 66 | 61% | 0.44 |

**Best-case Sharpe 0.14 vs SPY 0.83 → KILL.** Wider spreads (more credit, better risk/reward) climb from catastrophic to ~breakeven, but nothing approaches buy-hold.

## Why it fails (not just a parameter artifact)

The deepest problem is structural, not tunable: **the regime gate only sells puts in uptrends — exactly when SPY directional gains dominate.** A put-credit-spread caps upside at the credit, so the strategy systematically forgoes the large moves its own trend filter is identifying, while still eating the occasional sharp drawdown. High win rate (you win most months) masks a profit factor ≤ 1 (the losers are bigger). Over a historic bull market this is a guaranteed underperformance of buy-hold.

## Caveats

1. **Modeled, not real fills.** IV from flat VIX ignores put skew, so real OTM credits would be modestly higher → real results slightly better than modeled. But the gap (0.14 vs 0.83 Sharpe; 0.3% vs 13.9% CAGR) is far too large for skew to close.
2. **5% modeled spread.** A lower spread assumption lifts the tight-width rows but cannot push the best (wide) rows above buy-hold.
3. **Real Alpaca arm not run.** It needs `RealAlpacaSource._fetch_put_chain_marks` (the live chain crawl) and would cover only ~2.4y (2024→now) of the same bull market. Given the decisive, robust modeled result, it would confirm, not overturn. Available as a follow-up if desired.
4. **2015–2026 was a strong bull.** The strategy might fare better in flat/choppy regimes — but the regime gate explicitly excludes those, so that potential is unreachable as specified.

## What this kills — and what it doesn't

- **Kills:** PCS-RIV *as specified* (regime-gated put-credit-spread on SPY). Do not build infra for it.
- **Does NOT kill:** the MVP 2.0 *infrastructure* thesis (Vercel + Supabase + Alpaca, LLM-as-advisor), which is strategy-agnostic. It also doesn't kill options income strategies in general — only this gated structure.

## Recommendation

Per the Phase 1 gate, **stop here for this hypothesis — $0 spent on OPRA or infra.** Options next:
1. Test a different strategy candidate on the same (now-built) engine — e.g., the **naked/cash-secured short put** (no long leg capping the structure differently), or a strategy that sells premium in *non*-trending regimes (invert the gate), or a directional debit structure that participates in the trend.
2. Reconsider whether an options layer earns its complexity over the deterministic equity bot at all.

The engine (`options_pricing` / `options_data` / `pcs_riv`) is reusable for any of these — swapping the rule is cheap.
