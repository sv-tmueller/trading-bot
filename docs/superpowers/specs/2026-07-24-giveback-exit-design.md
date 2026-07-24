# Design spec: profit-protecting giveback exit

**Issue:** #420 · **Date:** 2026-07-24 · **Status:** DESIGN (approved in brainstorm/grill 2026-07-24)
**Piece 1 of the strategy-evolution decomposition** (siblings: #421 diversification, #422 short-horizon entry study).

> This document specifies the behavior only. It authorizes no live change: the feature ships
> **default-OFF** and is enabled only after it clears the pre-registered backtest bar in §7. The live
> UPRO / 200-DMA regime bot behaves **identically** until the flag is flipped.

---

## §1 Motivation

The live bot holds a 3× position (UPRO) while SPY is above its 200-DMA and exits only on (a) a bearish
200-DMA cross, evaluated once per day, or (b) the intraday kill-switch, a −25% trailing stop from the
rolling high. It has **no profit-protection exit**: a position that ran to ~+13% at peak (W25 journal)
handed the gain back, because nothing banks an unrealized gain short of the −25% catastrophic stop.

The operator's goal is to **realize** a meaningful fraction of a large gain rather than watch it
round-trip — without being shaken out by ordinary volatility. This spec adds exactly that: a
profit-aware "giveback" floor layered on the existing intraday exit loop.

### The re-entry finding (load-bearing)
The bot has **no working re-entry suppressor today**. `computeTargetState` (the one pure decision
rule) returns LONG on any bullish day and clears `kill_switch_active` — the flag does not gate
re-entry. So an exit taken while SPY is still above its 200-DMA is **re-bought at the next
daily-check**, at essentially the same price. A giveback exit is therefore only meaningful when paired
with a genuine re-entry lock (§4); without it the feature banks nothing but a round-trip in fees.

---

## §2 Scope and non-goals

**In scope:** an intraday profit-protecting exit on the current instrument (UPRO), its re-entry lock,
its coexistence with the existing exits, the schema/config to support it, and a pre-registered
backtest that decides whether it is ever enabled live.

**Non-goals:**
- No change to the entry signal — the one 200-DMA rule is untouched. Shorter-candle / more-frequent
  entry is #422, gated behind its own feasibility study.
- No change to the −25% catastrophic stop's own behavior, including its re-entry behavior.
- No new instrument (that is #421). The giveback logic is instrument-agnostic and will transfer, but
  this spec validates and ships it on UPRO only.
- No LLM anywhere in the path (CLAUDE.md invariant #1).

---

## §3 The exit rule

All quantities are measured as **gain since the position's average entry price**.

Let:
- `entryPrice` = the broker's `avg_entry_price` for the current LONG position.
- `entryDate` = the fill date of the most recent `regime_flip_long` trade for the current position.
- `peakPrice` = `max(daily highs from entryDate..today, lastPrice)` — see §5 for how this is sourced.
- `peakGain` = `peakPrice / entryPrice − 1`.
- `currentGain` = `lastPrice / entryPrice − 1`.
- `floorGain` = `GIVEBACK_PROTECT_FRACTION × peakGain`.

The giveback **fires** (liquidate) when **all** hold:
1. `GIVEBACK_ENABLED` is true, **and**
2. `peakGain ≥ GIVEBACK_ARM_PCT` (armed), **and**
3. `currentGain ≤ floorGain` (breach).

Two tunable knobs, defaulted to the operator's own numbers:
- `GIVEBACK_ARM_PCT = 0.20` — below a +20% peak gain the giveback is dormant; only the −25% stop
  applies, so ordinary volatility cannot trip it and small gains are deliberately unprotected.
- `GIVEBACK_PROTECT_FRACTION = 0.50` — the floor is half the peak gain and ratchets up as the peak
  grows (peak +20% → floor +10%; peak +40% → floor +20%). The trailing band widens with the gain,
  letting a large trend breathe.

Because these are expressed in UPRO's own (already-3×) return space, they are "sized to the leverage"
for the current instrument; a future instrument (#421) would re-tune them.

---

## §4 The re-entry lock

- On a giveback fire, set a **new** `regime_state.giveback_lock_active = true` (with a forensic
  `giveback_locked_at` timestamp). This flag is distinct from `kill_switch_active`, which does not
  suppress re-entry.
- `daily-check` gates on it: while `giveback_lock_active` is true, it **does not re-enter LONG** even
  when the regime is bullish. It stays CASH and carries the flag forward.
- The flag **clears** on any `daily-check` where the regime is bearish (`spyClose ≤ spySma200`). Once
  the trend has genuinely reset to cash, the next bullish cross is a fresh, normal entry.
- **`computeTargetState` is not modified.** The lock is a caller-side gate in `daily-check/logic.ts`,
  so the one pure decision rule stays a 1:1 mirror of `regime.py` and the invariant surface is
  minimal.

The deliberate consequence (operator-accepted): after banking a gain the bot can sit in cash through a
still-bullish stretch, missing upside. This opportunity cost is the exact thing §7 measures.

---

## §5 Peak tracking — stateless recompute (decided)

The since-entry peak is **recomputed each tick**, not persisted:
- `entryPrice` from the broker's `avg_entry_price` (extend the position read; see §6).
- `entryDate` from the most recent `regime_flip_long` trade row.
- Daily highs from `entryDate..today` (a bounded extra fetch beyond the current
  `killSwitchLookbackDays + 10`), combined with the current `lastPrice`.

Rationale: consistent with the codebase's broker-truth / no-mutable-state philosophy (the existing
`refHigh` is recomputed statelessly every run), and it avoids the "stale peak leaks across a
re-entry" bug class that a persisted high-water mark would introduce. Cost: a variable-size bar fetch
back to the entry date. This was chosen over the persisted-column alternative in the grill.

---

## §6 Coexistence, precedence, and confirmation

- **Both exits are evaluated every kill-switch tick.** The −25% catastrophic stop is checked **first**;
  if it breaches, the run liquidates and records the existing `kill_switch` reason / outcome. Only if
  the −25% stop does **not** breach is the giveback evaluated. So a simultaneous breach is always
  labelled as the more severe `kill_switch` event.
- **Bid-confirmation is reused (#352).** The giveback down-breach is confirmed against the quote bid
  before liquidating (`bidGain = bid/entryPrice − 1` must also be ≤ `floorGain`), with the same
  fail-toward-protection behavior on a quote outage. A 3× position is never liquidated on a single
  thin print.
- **The 200-DMA daily flip is unchanged** — a bearish cross still exits to CASH regardless of the
  giveback.
- The existing per-day trade claim (#293) still bounds this to at most one liquidation per day.

---

## §7 Backtest and the pre-registered ship gate

The feature is enabled live **only** if it clears this bar, which is committed **before** the run.

- **History basis:** real UPRO (2009+) as the fidelity anchor, plus **simulated 3× SPY back to 1993**
  (modeling the expense ratio, the swap financing/borrow cost, and the daily-rebalance volatility
  decay that arises automatically from compounding 3× daily returns). The simulation is **validated
  against real UPRO over the 2009–2025 overlap**; a material divergence is a reported finding, not
  something to paper over. The pre-2009 extension exists to test the feature through 2000–02 and 2008,
  the drawdown regimes where a giveback earns its keep.
- **Reported, giveback-ON vs giveback-OFF, same history:** CAGR, max drawdown, after-tax Calmar, and
  the **worst peak-to-exit giveback** (largest unrealized peak gain handed back before exit).
- **Pre-registered ship bar:** enable live **only if after-tax Calmar improves** (giveback-ON >
  giveback-OFF). CAGR / max-drawdown / worst-giveback are reported alongside for the human call, but
  Calmar is the gate. If the bar is not cleared, the flag stays OFF and the feature does not ship live.
- **Intraday-on-daily modeling caveat:** live fires intraday (5-min polling); the backtest runs on
  daily bars, so it models a giveback firing on the day the bar's **low** breaches `floorGain`, with a
  conservative fill at the floor level. This mirrors how intraday stops are modeled on daily bars
  elsewhere in the repo and is stated as an explicit modeling choice.

---

## §8 Backtest ↔ live parity

The live path is TypeScript (`kill-switch/logic.ts`, `daily-check/logic.ts`); the backtest is Python
(`backtest/`, `strategy/regime.py`). The giveback rule (§3–§6) is the single source of truth and is
implemented in both, kept in parity the way `regime.ts` mirrors `regime.py`. Any change to the rule
changes both.

---

## §9 Schema and config changes

- **Migration** (new `supabase/migrations/0011_giveback.sql` — 0001–0010 already exist; confirm the
  next free number at implementation time):
  - `regime_state`: add `giveback_lock_active boolean not null default false` and
    `giveback_locked_at timestamptz`.
  - `trades`: extend the `reason` check constraint to include `'giveback'`.
- **`_shared/alpaca.ts`:** extend the position read to also return `avg_entry_price` (present in the
  same Alpaca response `getPosition` already fetches) — e.g. a `getPositionDetail` returning
  `{ qty, avgEntryPrice }`, leaving `getPosition` intact.
- **`_shared/config.ts`** (per `add-or-extend-agent`): `GIVEBACK_ENABLED` (bool, default **false**),
  `GIVEBACK_ARM_PCT` (default 0.20, validated `0 < x < 5`), `GIVEBACK_PROTECT_FRACTION`
  (default 0.50, validated `0 < x < 1`). Read and range-validated at function start; invalid values
  throw immediately.
- **`_shared/notifications.ts`:** `notifyGivebackFired` mirroring `notifyKillSwitchFired`.
- **Audit outcome:** `success:giveback_fired`; trade recorded with `reason = 'giveback'`.

---

## §10 Invariant analysis

The giveback is arguably a **second exit rule**, which CLAUDE.md's one-decision-rule invariant guards.
It is kept defensible by construction:
- `computeTargetState` (the sole entry/regime rule, mechanically invariant-tested) is **untouched**;
- the feature is **additive, config-gated, default-OFF** — with the flag off, every code path and DB
  write is byte-for-byte the current behavior;
- it is an **exit/risk** rule (edge-neutral risk shaping), not a second **entry** signal, which is the
  category the invariant most protects.

The reviewer/architect must still treat it as a live-trading-path change and verify the default-OFF
guarantee holds.

---

## §11 Rollout sequence

1. This spec (approved) → implementation plan (`writing-plans`).
2. Model the giveback in the Python backtester; run the §7 pre-registered test; record the verdict.
3. Implement the live TS behind `GIVEBACK_ENABLED=false` (+ migration + config + parity).
4. Paper soak on the dev Alpaca account with the flag enabled there only.
5. Enable live **only if** the §7 Calmar bar was cleared; otherwise the feature stays dormant and the
   result is recorded as an honest negative.

---

## §12 Acceptance criteria

- Satisfies all CLAUDE.md Architectural invariants; any violation is a must-fix review finding.
- With `GIVEBACK_ENABLED=false`, behavior and DB writes are identical to pre-change (proven by test).
- The exit rule (§3), re-entry lock (§4), precedence + bid-confirm (§6) implemented and unit-tested,
  with all Alpaca calls mocked (`CLAUDE_AGENT_NO_BROKER` set in tests).
- Backtest and live implement the same rule (§8); a shared fixture demonstrates parity on a worked
  example.
- The §7 backtest is run with the ship bar pre-registered before results are examined; the verdict
  (enable / do-not-enable) is recorded.
- `deno task test` green; migration applies cleanly.
