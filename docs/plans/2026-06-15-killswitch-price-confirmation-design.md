# Kill-switch price confirmation (B1b) — spec

**Date:** 2026-06-15
**Issue:** [#269](https://github.com/sv-tmueller/trading-bot/issues/269) (finding 8)
**Status:** Brainstorm-approved (operator sign-off 2026-06-15)
**Ratifies:** Proposal B of [`2026-06-11-invocation-hardening-and-killswitch-confirmation-design.md`](2026-06-11-invocation-hardening-and-killswitch-confirmation-design.md) — see there for the full options analysis (B1a / B1b / B2 / B3 / B4) and the quantified true-fire-vs-false-fire cost trade-off. This spec locks the decision and adds the post-#293 integration.

## Problem
`kill-switch/logic.ts` computes UPRO drawdown from a single `getLatestTradePrice` call pinned to the thin **IEX** feed (~2% of US consolidated volume). One stale or odd-lot print ≥ `KILL_SWITCH_DRAWDOWN_PCT` below the 30-day reference high triggers a **full, irreversible liquidation** of the 3× position. The reference highs (`getDailyCloses`) are IEX-only too.

## Decision
**Option B1b — dual-breach (trade + quote-midpoint confirmation), plus an `ALPACA_DATA_FEED` config knob (default `iex`). Not B2; not buying SIP now.** Confirmation is conditional on the two data sources disagreeing: it adds **zero latency** to confirmed true fires and suppresses the outlier-print false fire. The quote-outage path **fails toward protection**. (Rationale: 2026-06-11 doc §B.1–B.3, tied to the stated goal — minimize risk and drawdown on a 3× vehicle, where the dominant risk is the *true* crash.)

## Design

### 1. Market-data helper — `supabase/functions/_shared/marketdata.ts`
`getLatestQuote(symbol): Promise<{ bid: number; ask: number; mid: number }>` → `GET /v2/stocks/{symbol}/quotes/latest?feed=${ALPACA_DATA_FEED}`; `mid = (bid + ask) / 2`. Missing `quote`, or non-numeric bid/ask → throw `DataError` (consistent with `getLatestTradePrice` / `getDailyCloses`).

### 2. Config knob — `supabase/functions/_shared/config.ts`
New `ALPACA_DATA_FEED` setting, default **`iex`**, validated against `iex | sip` (throws on out-of-range, like the other settings). Single source for the feed used by `getLatestTradePrice`, `getLatestQuote`, and `getDailyCloses`. Default-unchanged → ships inert; enabling SIP later is a `supabase secrets set`, not a deploy. (Recipe: `.claude/skills/add-or-extend-agent`.)

### 3. Confirmation branch — `supabase/functions/kill-switch/logic.ts`
After the existing within-threshold early-return, when the **trade-price** drawdown breaches the threshold:
1. Fetch `getLatestQuote(BOT_TICKER)`; compute a second drawdown from `mid` against the same reference high.
2. **Both breach** → proceed to liquidate (existing fired path, outcome unchanged; `audit_log` / `regime_state` notes carry both the trade price and the midpoint).
3. **Trade breaches, midpoint does not** → outcome **`skipped:breach_unconfirmed`**, **no** `liquidate`, `notifyError` (every suppressed fire is alerted), `position_drawdown_pct` still persisted.
4. **Quote fetch throws / no quote** → **fail toward protection**: liquidate on the trade alone + notify (a data outage must never disarm the switch).
5. **Neither breaches** → `success:within_threshold` (unchanged).

### 4. Composition with the #293 per-date claim
The confirmation slots **before** `claimTradeDate` (which stays the last gate before `liquidate`):
`within-threshold? → [B1b confirm] → claimTradeDate → liquidate`.
An **unconfirmed** breach (`skipped:breach_unconfirmed`) therefore consumes **no** claim — a genuine breach later the same trading day can still claim and fire.

## Outcomes / audit_log
Adds one outcome string `skipped:breach_unconfirmed` (consistent with the existing `skipped:*` taxonomy). All other outcome strings unchanged.

## Tests (all mocked; injected `deps`)
- `getLatestQuote`: happy path; missing `quote` → `DataError`; non-numeric bid/ask → `DataError`; feed param honors `ALPACA_DATA_FEED`.
- kill-switch logic: both breach → liquidates (outcome unchanged, notes carry both prices); trade breaches / midpoint doesn't → `skipped:breach_unconfirmed`, **no** `liquidate`, `notifyError` called, `position_drawdown_pct` persisted; quote fetch throws → liquidates on trade alone + notify (fail-toward-protection); neither breaches → `success:within_threshold`.
- Composition: an unconfirmed breach does **not** call `claimTradeDate`.
- `config.ts`: `ALPACA_DATA_FEED` default `iex`; invalid value throws.

## Invariants (standing AC)
No LLM; one decision rule untouched (`computeTargetState`); the drawdown **threshold** math is unchanged — this only adds a confirmation gate before the existing `liquidate`. No migration. ~1 engineer-day.

## Out of scope
- Lookback-high feed thinness (IEX daily highs) — only perturbs the effective threshold, not trigger integrity; the `ALPACA_DATA_FEED` knob covers the eventual SIP upgrade for trigger + lookback at once.
- Buying the SIP subscription — deferred to the live-money cutover (gated on soak evidence per the margin-assessment doc).
- Option B2 (two-tick state machine) — rejected (charges true-fire latency as a flat premium against a rarer, smaller-loss event).
