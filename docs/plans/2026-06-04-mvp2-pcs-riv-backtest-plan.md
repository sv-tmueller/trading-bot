# MVP 2.0 Phase 1 — PCS-RIV Backtest Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task (engineer → spec-reviewer → code-quality-reviewer per task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer one question on free historical data — *does the Put-Credit-Spread-on-Regime+IV (PCS-RIV) rule show risk-adjusted edge that clears its costs, or is it another coin flip?* This is the **kill gate** for MVP 2.0: no Vercel/Supabase/broker work happens unless the backtest beats SPY buy-and-hold after realistic costs.

**Architecture:** Pure offline Python in this repo (the `analyst` + `docs/research/` convention). Three new modules under `backtest/`, plus a findings doc. The 200-DMA regime gate is **reused** from `strategy/regime.py::compute_target_state` — not reimplemented. The harness mirrors the shape of `backtest/regime.py` (Trade dataclass → run loop → metrics dict → `main_cli`, explicit slippage/commission). No infra, no LLM, no real-time data, no order placement.

**Tech Stack:** Python 3.9 (`from __future__ import annotations` in every file). pandas + numpy (via pandas) for series math. Black-Scholes + implied-vol solve implemented by hand (Newton-Raphson with bisection fallback) — **no scipy dependency**. Historical data: yfinance for underlyings + VIX (already a dep); Alpaca options data via stdlib `urllib` (matches `tools/notifications.py`; read-only GET on `data.alpaca.markets`, **no order path, outside the broker-guard surface**). No new pip dependencies required.

**Spec:** issue #220 — decision-record comment (#issuecomment-4625386305) + Phase 1 strategy spec comment (#issuecomment-4625463457).

---

## Key constraint (resolved by Task 1 — see `docs/research/mvp2-alpaca-options-data-spike.md`)

Spike result: **real options-data floor ≈ 2024-01-18** (~2.4y of real data), **trade bars/trades are free**, but **bid/ask quotes are OPRA-gated (HTTP 404 on Basic)** and historical data carries **no greeks/IV**. The harness uses **two price sources** behind one interface:
- `real` — Alpaca historical trade **bars/trades** + **modeled spread** (quotes unavailable on free tier). Real marks, modeled fills, short sample (2024-01→now); **indicative**.
- `modeled` — Black-Scholes prices from underlying + VIX-proxied IV (2015→now; modeled fills; **directional**).

Because the bid/ask **spread is modeled in *both* sources**, the gate's pass/fail hinges on a spread assumption — run it conservatively (wide) and report sensitivity. Real bid/ask fills require OPRA ($99/mo) and are deferred to Phase 2 validation on the free month, only if the gate says GO.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backtest/options_pricing.py` | Create | Pure functions: Black-Scholes price, implied-vol solve, greeks (delta/gamma/theta/vega). No I/O. |
| `backtest/options_data.py` | Create | Historical data loader behind a `PriceSource` interface: `RealAlpacaSource` (stdlib `urllib`, read-only) + `ModeledSource` (BS from yfinance underlying + VIX). Returns a uniform chain/quote shape. |
| `backtest/pcs_riv.py` | Create | The PCS-RIV backtest. Reuses `strategy.regime` for the gate. Trade/Position dataclasses, run loop, metrics dict, `main_cli`. Mirrors `backtest/regime.py`. |
| `tests/test_options_pricing.py` | Create | Unit tests for pricing/greeks/IV-solve against known BS reference values. |
| `tests/test_options_data.py` | Create | Loader tests with mocked HTTP (Alpaca) + a deterministic ModeledSource case. No live network. |
| `tests/test_pcs_riv.py` | Create | Harness tests: synthetic chains exercising each entry/exit branch + a costs-vs-mid assertion. |
| `docs/research/mvp2-pcs-riv-backtest.md` | Create (after runs) | Findings: metrics tables, equity curves, real-vs-modeled comparison, kill/go recommendation. |

`main.py` is **not** touched in Phase 1 — `backtest/pcs_riv.py::main_cli` is invoked directly. Wiring a `main.py` subcommand is deferred to avoid scope creep.

---

### Task 1: Data spike — confirm Alpaca options history floor + data shape ✅ DONE

**Status:** Complete (2026-06-04). Findings: `docs/research/mvp2-alpaca-options-data-spike.md`.

**Result:** Real-data floor ≈ 2024-01-18 (~2.4y). Trade `bars`/`trades` free; `quotes` (bid/ask) OPRA-gated (HTTP 404); no greeks/IV in free data. → `RealAlpacaSource` uses bars/trades + modeled spread (Task 3); greeks/IV computed (Task 2).

- [x] **Step 1:** Enumerated expired SPY contracts (earliest expiry 2024-01-03), pulled bars (first bar 2024-01-18) + probed quotes (404) + trades (200).
- [x] **Step 2:** Confirmed greeks/IV absent from free historical data — computed by `options_pricing.py`.
- [x] **Verify:** Floor, fields, and spread-modeling path recorded in the research memo. Read-only calls only; no orders.

### Task 2: `backtest/options_pricing.py` — Black-Scholes, IV solve, greeks (TDD)

**Files:** Create `backtest/options_pricing.py`, `tests/test_options_pricing.py`.

**Why:** Free data has no greeks/IV; the strategy is defined on delta + IV-rank. Pure, reusable, and the same module can serve the live layer later.

- [ ] **Step 1:** Write tests first: BS put/call price vs published reference values; put-call parity; `delta` monotonic in spot; `implied_vol(price(iv)) == iv` round-trip within tol; deep-ITM/OTM and near-expiry edge cases return sane (non-NaN) values.
- [ ] **Step 2:** Implement `bs_price`, `bs_greeks`, `implied_vol` (Newton-Raphson, bisection fallback on non-convergence). Risk-free rate a parameter (default a fixed constant; documented).
- [ ] **Verify:** `python3 -m pytest tests/test_options_pricing.py -v` green.

### Task 3: `backtest/options_data.py` — `PriceSource` interface + both sources (TDD)

**Files:** Create `backtest/options_data.py`, `tests/test_options_data.py`.

**Why:** Decouple the harness from the data origin so real-vs-modeled is a swap, not a rewrite.

- [ ] **Step 1:** Define `PriceSource` (given underlying, date, target DTE/delta → returns the put strikes + bid/ask/mid needed for the spread). Tests: `ModeledSource` produces deterministic BS quotes from a fixed underlying+IV; `RealAlpacaSource` parses a **mocked** Alpaca JSON payload (patch the `urllib` call — no live network in tests).
- [ ] **Step 2:** Implement both. `RealAlpacaSource` is read-only GET on `bars`/`trades` (quotes are OPRA-gated — do not use), derives a mid from trade marks and **models the bid/ask spread** (configurable bps + OCC/reg fees). Keys from env (`ALPACA_API_KEY_ID`/`ALPACA_API_SECRET_KEY`), raises a clear error if unset — never imports or touches any order path. IV-rank series helper (trailing 1y ATM IV; VIX proxy allowed for SPY).
- [ ] **Verify:** `python3 -m pytest tests/test_options_data.py -v` green; no network in the test run.

### Task 4: `backtest/pcs_riv.py` — the PCS-RIV harness (TDD)

**Files:** Create `backtest/pcs_riv.py`, `tests/test_pcs_riv.py`.

**Why:** The strategy under test. Encodes the spec rule exactly.

- [ ] **Step 1:** Write tests first on **synthetic** chains, one per branch: opens only when `compute_target_state(...) == LONG` **and** IV-rank ≥ threshold; short leg picked nearest 0.30 delta; long leg at configured width; exits at 50% credit / 21 DTE / regime flip (whichever first); P&L = credit − cost-to-close − fees; **a fill-at-mid run beats a mid±half-spread run** (proves cost sensitivity is wired).
- [ ] **Step 2:** Implement the run loop reusing `strategy.regime.compute_target_state` for the gate and the `backtest/regime.py` metrics pattern (CAGR, Sharpe, max drawdown, win rate, profit factor; equity curve). One open position per underlying; fixed risk per trade.
- [ ] **Verify:** `python3 -m pytest tests/test_pcs_riv.py -v` green; full suite still green.

### Task 5: Run + findings doc

**Files:** Create `docs/research/mvp2-pcs-riv-backtest.md`.

**Why:** The deliverable the kill/go decision is made on.

- [ ] **Step 1:** Baseline run on both sources (`real` ~2024→now; `modeled` 2015→now), SPY + QQQ. Benchmarks: SPY buy-hold + the v1.0 200-DMA bot (`backtest/regime.py`) over matching windows.
- [ ] **Step 2:** Param sweep: IV-rank {30,50} · short delta {0.20,0.30} · profit target {25%,50%} · width · **regime gate on/off**.
- [ ] **Verify:** Findings doc states, per source, whether risk-adjusted return clears SPY buy-hold after costs, with the explicit **KILL or GO** recommendation and the real-vs-modeled caveats.

---

## Out of scope (Phase 1)

Vercel, Supabase, any broker call (paper or live), the nightly LLM, real-time data, TypeScript, `main.py` wiring. Those are Phase 2+ and only if this gate says GO.
