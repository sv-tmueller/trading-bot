# MVP 2.0 — Alpaca Options Data Spike (Phase 1, Task 1)

From __future__ note: research memo, not code. No `from __future__ import annotations` required.

- **Status:** complete
- **Date:** 2026-06-04
- **Account:** paper keys, **Basic** (free) market-data tier, **no OPRA agreement signed**
- **Purpose:** determine whether free-tier Alpaca options data can support the PCS-RIV backtest gate (issue #220, Phase 1)

## TL;DR

- **Real options-data floor ≈ 2024-01-18.** No SPY contracts expire before 2024-01-03; earliest bar data is 2024-01-18 (Alpaca launched options in 2024). **Real-data backtest window ≈ 2.4 years** — statistically thin for a ~monthly strategy.
- **Trade data is FREE.** Historical option `bars` (OHLC of trades) and `trades` (prints) return on Basic with no OPRA. Bar fields: `o,h,l,c,v,n,vw` — **trade prices only, no greeks/IV**.
- **Bid/ask QUOTES are OPRA-gated.** The `quotes` endpoint returns **HTTP 404 "Not Found"** on the free tier for every window tested. No real NBBO bid/ask without the $99/mo Algo Trader Plus subscription.
- **Consequence:** real bid/ask fills are not free. The **spread — the dominant cost in a credit spread — must be *modeled* regardless of source.** The "real data" advantage shrinks to real *mid* marks (from trades) vs modeled Black-Scholes mids; the spread is an assumption either way.

## What was tested (read-only, paper keys)

| Probe | Result |
|---|---|
| Earliest inactive SPY contracts | expirations from **2024-01-03**; none ≤ 2023-12-31 |
| Bars `SPY240621C00480000` from 2023-06-01 | first bar **2024-01-18**, 107 daily bars (HTTP 200) |
| Bar fields | `o,h,l,c,v,n,vw` — trade OHLC + volume + VWAP; **no greeks/IV** |
| Quotes (bid/ask), multiple windows | **HTTP 404 "Not Found"** (OPRA-gated) |
| Trades (prints) | **HTTP 200** — price/size/time/condition/exchange |
| Snapshot `feed=opra` (earlier check) | `"OPRA agreement is not signed"` |
| Snapshot `feed=indicative` | works; `greeks: null`, `impliedVolatility: null` |
| `feed` param on bars | rejected (`unexpected query parameter`) — bars have no feed concept |

## Implications for the Phase 1 plan

1. `RealAlpacaSource` uses **bars/trades** for option marks and **models the spread** (configurable bps on mid + OCC/reg fees). It is **"semi-real,"** not real-fill. The `quotes` endpoint is unusable on Basic.
2. Both price sources (real-mark and modeled-BS) carry a **modeled spread** — so the gate's pass/fail hinges on a spread *assumption*. Run it **conservatively (wide)** and report sensitivity.
3. Greeks/IV are computed by `options_pricing.py` in all cases (confirmed absent from free data).
4. **Real bid/ask fills require OPRA ($99/mo).** Defer to Phase 2 validation on the 1-month-free trial — *after* the gate says GO. The gate itself does not need OPRA.

## Bottom line

The cheap gate is viable on free data: real trade marks (2024-01→now) and modeled BS (2015→now), both with a conservative modeled spread. **If PCS-RIV can't clear SPY buy-and-hold under generous spread assumptions, kill it for $0.** If it looks promising, validate real fills on the OPRA free month before any infra spend.
