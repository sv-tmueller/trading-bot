# Profit-Protecting Giveback Exit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a profit-aware "giveback" exit that banks a fraction of a large unrealized gain instead of letting it round-trip — validated by a pre-registered backtest, then shipped to the live bot **default-OFF**.

**Architecture:** Two phases. **Phase A (Python research)** proves or kills the idea: model the giveback as a *pure transform of the regime signal* fed to the existing backtest engine, run giveback-ON vs -OFF on synthetic-3× (1993+) and real UPRO (2009+), and record a GO/NO-GO against a pre-registered after-tax-Calmar bar. **Phase B (TypeScript live)** implements the same rule behind a default-OFF flag in the intraday `kill-switch` (the exit) and `daily-check` (the re-entry lock), with the pure `computeTargetState` untouched. The two implementations mirror each other the way `regime.ts` mirrors `regime.py`.

**Tech Stack:** Python 3.9 + pandas + yfinance (`backtest/`, `strategy/`); TypeScript on Deno (Supabase Edge Functions); Postgres migrations.

**Spec:** `docs/superpowers/specs/2026-07-24-giveback-exit-design.md` (§ references below point at it).

## Global Constraints

- **CLAUDE.md Architectural invariants are a hard review gate.** Any violation is a must-fix finding. `computeTargetState` / `compute_target_state` (the one entry rule) MUST NOT be modified.
- **Ships default-OFF.** With `GIVEBACK_ENABLED=false`, live behavior and DB writes are byte-identical to pre-change. This is a tested acceptance criterion.
- **No LLM anywhere in the path.**
- Every Python file starts with `from __future__ import annotations`.
- All Alpaca calls in tests MUST be mocked; `CLAUDE_AGENT_NO_BROKER` is set in the test setup (guarded helpers raise `BrokerCallBlockedError`).
- Deno tests: `deno task test`. Python tests: `venv/bin/python -m pytest` (note: `venv/` may not exist — use the interpreter the repo actually has; system `python3` 3.9 is acceptable, disclose if used).
- **Backtest ↔ live parity:** the giveback rule is specified once (spec §3–§6) and implemented identically in Python (Phase A) and TypeScript (Phase B).

---

## File Structure

**Phase A (Python, research-only — no Alpaca import, no orders):**
- Create `backtest/giveback.py` — the pure giveback logic: `apply_giveback()` (signal transform) + `worst_giveback()` (metric).
- Create `tests/test_giveback.py` — unit tests for both.
- Create `backtest/run_giveback_study.py` — the study runner (mirrors `backtest/run_leveraged_regime_study.py`).
- Create `docs/research/2026-07-24-giveback-backtest-verdict.md` — pre-registered bar + ON-vs-OFF result + GO/NO-GO.

**Phase B (TypeScript live):**
- Create `supabase/migrations/0011_giveback.sql` (confirm next free number at implementation time).
- Modify `supabase/functions/_shared/config.ts` — three new settings + validation.
- Modify `supabase/functions/_shared/alpaca.ts` — add `getPositionDetail` returning `{ qty, avgEntryPrice }`.
- Modify `supabase/functions/_shared/db.ts` — `giveback_lock_active` in `RegimeStateRow` + upsert; `'giveback'` trade reason.
- Modify `supabase/functions/_shared/notifications.ts` — `notifyGivebackFired`.
- Modify `supabase/functions/kill-switch/logic.ts` — the giveback exit check.
- Modify `supabase/functions/daily-check/logic.ts` — the re-entry lock gate.
- Modify the corresponding `*.test.ts` files.
- Create `supabase/functions/_shared/giveback_fixture.test.ts` — parity worked-example shared with Phase A.

---

# PHASE A — Backtest & pre-registered verdict

## Task A1: Confirm the synthetic-3× model tracks real UPRO

**Files:**
- Test: `tests/test_giveback.py` (new; this task adds the validation test)
- Reuse (no change): `backtest/synthetic.py` (`build_synthetic_leverage`, `validate_synthetic`, `daily_risk_free`, `fetch_close`).

**Interfaces:**
- Consumes: `synthetic.build_synthetic_leverage(index_close, *, leverage, annual_expense, rf_daily) -> DataFrame`; `synthetic.validate_synthetic(synth_close, real_close, label) -> dict` (returns `daily_return_corr`, `cagr_gap_pp`, …).
- Produces: nothing consumed downstream; this task is a gating check that the §7 "validated against real UPRO" requirement holds before any result is trusted.

- [ ] **Step 1: Write the validation test (network-gated, opt-in).**

```python
from __future__ import annotations

import os
from datetime import date

import pytest

from backtest import synthetic

RUN_NET = os.environ.get("RUN_NET_TESTS") == "1"


@pytest.mark.skipif(not RUN_NET, reason="network test; set RUN_NET_TESTS=1")
def test_synthetic_3x_tracks_real_upro():
    start, end = date(2009, 6, 25), date(2025, 12, 31)
    spy = synthetic.fetch_close("^GSPC", start, end)
    upro = synthetic.fetch_close("UPRO", start, end)
    rf = synthetic.daily_risk_free(start, end)
    synth = synthetic.build_synthetic_leverage(
        spy, leverage=3.0, annual_expense=synthetic.UPRO_EXPENSE, rf_daily=rf
    )
    res = synthetic.validate_synthetic(synth["Close"], upro, "UPRO 3x")
    # Daily-return correlation must be very high; CAGR gap bounded.
    assert res["daily_return_corr"] > 0.99, res
    assert abs(res["cagr_gap_pp"]) < 5.0, res  # within 5 pp/yr over 16y
```

- [ ] **Step 2: Run it.**

Run: `RUN_NET_TESTS=1 python3 -m pytest tests/test_giveback.py::test_synthetic_3x_tracks_real_upro -v`
Expected: PASS. Record `daily_return_corr` and `cagr_gap_pp` — they go verbatim into the verdict doc (Task A4). If correlation < 0.99 or the CAGR gap is large, **stop and report** — the simulation is not trustworthy and §7's basis fails; this is a finding, not something to tune around.

- [ ] **Step 3: Commit.**

```bash
git add tests/test_giveback.py
git commit -m "test: validate synthetic-3x tracks real UPRO on the 2009+ overlap (#420)"
```

---

## Task A2: The giveback logic — `apply_giveback()` (pure signal transform)

The giveback is path-dependent, but given the regime `signal` and the `vehicle_close` series it is a **deterministic transform** of the signal into a giveback-adjusted LONG/CASH position series. This keeps us out of the shared, parity-sensitive `simulate_from_signal` loop: the transformed series feeds the existing engine unchanged.

**Files:**
- Create: `backtest/giveback.py`
- Test: `tests/test_giveback.py` (extend)

**Interfaces:**
- Consumes: a `signal: pd.Series` (values `"LONG"`/`"CASH"`, date-indexed) and `vehicle_close: pd.Series` (same index).
- Produces: `apply_giveback(signal, vehicle_close, *, arm_pct: float, protect_fraction: float) -> pd.Series` — a giveback-adjusted `"LONG"/"CASH"` series. Consumed by Task A4's runner and Task A3's metric.

**Algorithm (spec §3–§5, close-based since a synthetic vehicle has no intraday):**
walk day-by-day tracking `in_pos`, `entry_price`, `peak_price`, `locked`. While in position: `peak_gain = peak_price/entry − 1`, `cur_gain = close/entry − 1`; if `peak_gain ≥ arm_pct` and `cur_gain ≤ protect_fraction * peak_gain` → exit to CASH and set `locked`. `locked` suppresses LONG re-entry and clears the first bearish (`CASH`) signal day. Entry price is the vehicle close on the day the adjusted series turns LONG (1-tick approximation, documented).

- [ ] **Step 1: Write failing tests for the four behaviors.**

```python
from __future__ import annotations

import pandas as pd

from backtest.giveback import apply_giveback


def _mk(signal_vals, prices):
    idx = pd.date_range("2020-01-01", periods=len(prices), freq="D")
    return pd.Series(signal_vals, index=idx), pd.Series(prices, index=idx, dtype=float)


def test_dormant_below_arm_threshold():
    # Peak gain never reaches +20% -> giveback never fires; series == signal.
    sig, px = _mk(["LONG"] * 6, [100, 105, 110, 108, 112, 109])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    assert list(out) == ["LONG"] * 6


def test_fires_when_gain_falls_to_half_of_armed_peak():
    # Peak +20% at 120 (day 2); floor = +10% = 110. Day 3 close 109 -> exit.
    sig, px = _mk(["LONG"] * 5, [100, 115, 120, 109, 108])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    assert list(out) == ["LONG", "LONG", "LONG", "CASH", "CASH"]


def test_reentry_locked_until_regime_resets():
    # After a giveback exit, a still-LONG signal must NOT re-enter until a CASH day.
    sig, px = _mk(["LONG", "LONG", "LONG", "LONG", "CASH", "LONG"],
                  [100, 120, 109, 130, 90, 95])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    # day2 exit; days 3 stays CASH (locked despite LONG signal); day4 CASH clears
    # lock; day5 LONG signal re-enters.
    assert list(out) == ["LONG", "LONG", "CASH", "CASH", "CASH", "LONG"]


def test_floor_ratchets_up_with_a_higher_peak():
    # New peak +40% at 140 -> floor rises to +20% = 120; a dip to 121 does not fire.
    sig, px = _mk(["LONG"] * 5, [100, 120, 140, 121, 119])
    out = apply_giveback(sig, px, arm_pct=0.20, protect_fraction=0.5)
    assert list(out) == ["LONG", "LONG", "LONG", "LONG", "CASH"]
```

- [ ] **Step 2: Run them — expect ImportError / failures.**

Run: `python3 -m pytest tests/test_giveback.py -k "apply or dormant or fires or reentry or ratchets" -v`
Expected: FAIL (`No module named 'backtest.giveback'`).

- [ ] **Step 3: Implement `backtest/giveback.py`.**

```python
"""Profit-protecting giveback exit — pure logic shared by the backtest.

RESEARCH module (no Alpaca import, no orders). 1:1 behavioral mirror of the live
TypeScript in kill-switch/logic.ts + daily-check/logic.ts (spec
docs/superpowers/specs/2026-07-24-giveback-exit-design.md §3-§6). Evaluated on
daily closes: a synthetic leveraged vehicle has no intraday bar.
"""
from __future__ import annotations

import pandas as pd


def apply_giveback(
    signal: pd.Series,
    vehicle_close: pd.Series,
    *,
    arm_pct: float,
    protect_fraction: float,
) -> pd.Series:
    """Transform a LONG/CASH regime signal into a giveback-adjusted position series.

    While LONG, tracks peak gain since entry; once peak gain >= arm_pct, a floor at
    protect_fraction * peak_gain arms. A close at/below the floor exits to CASH and
    locks re-entry until the signal itself next goes CASH (regime reset).
    """
    close = vehicle_close.reindex(signal.index)
    out: list[str] = []
    in_pos = False
    entry = peak = 0.0
    locked = False

    for ts, sig in signal.items():
        px = float(close.loc[ts])
        if locked:
            if sig == "CASH":
                locked = False  # regime reset clears the lock
            out.append("CASH")
            continue
        if sig == "LONG":
            if not in_pos:
                in_pos, entry, peak = True, px, px
            else:
                peak = max(peak, px)
            peak_gain = peak / entry - 1.0
            cur_gain = px / entry - 1.0
            if peak_gain >= arm_pct and cur_gain <= protect_fraction * peak_gain:
                in_pos = False
                locked = True
                out.append("CASH")
            else:
                out.append("LONG")
        else:  # signal CASH
            in_pos = False
            out.append("CASH")

    return pd.Series(out, index=signal.index)
```

- [ ] **Step 4: Run tests — expect PASS.**

Run: `python3 -m pytest tests/test_giveback.py -k "apply or dormant or fires or reentry or ratchets" -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit.**

```bash
git add backtest/giveback.py tests/test_giveback.py
git commit -m "feat: giveback signal transform for the backtest (#420)"
```

---

## Task A3: The `worst_giveback()` metric

**Files:**
- Modify: `backtest/giveback.py` (add function)
- Test: `tests/test_giveback.py` (extend)

**Interfaces:**
- Produces: `worst_giveback(position: pd.Series, vehicle_close: pd.Series) -> float` — the largest peak-to-exit giveback (in gain fraction) across all held positions. `0.0` if never in a position. Consumed by Task A4.

- [ ] **Step 1: Write the failing test.**

```python
from backtest.giveback import worst_giveback


def test_worst_giveback_measures_peak_minus_exit_gain():
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    # LONG 100 -> peak 150 (+50%) -> exit at 120 (+20%): giveback 0.30.
    pos = pd.Series(["LONG", "LONG", "LONG", "CASH", "CASH"], index=idx)
    px = pd.Series([100, 150, 130, 120, 118], index=idx, dtype=float)
    assert abs(worst_giveback(pos, px) - 0.30) < 1e-9
```

- [ ] **Step 2: Run — expect FAIL (ImportError).**

Run: `python3 -m pytest tests/test_giveback.py::test_worst_giveback_measures_peak_minus_exit_gain -v`

- [ ] **Step 3: Implement.**

```python
def worst_giveback(position: pd.Series, vehicle_close: pd.Series) -> float:
    """Largest peak-to-exit giveback (gain fraction) across all held positions."""
    close = vehicle_close.reindex(position.index)
    worst = 0.0
    entry = peak = 0.0
    in_pos = False
    prev = "CASH"
    for ts, state in position.items():
        px = float(close.loc[ts])
        if state == "LONG":
            if not in_pos:
                in_pos, entry, peak = True, px, px
            else:
                peak = max(peak, px)
        if in_pos and (state == "CASH" or ts == position.index[-1]):
            exit_px = px
            giveback = (peak - exit_px) / entry
            worst = max(worst, giveback)
            in_pos = False
        prev = state
    return worst
```

- [ ] **Step 4: Run — expect PASS.**

Run: `python3 -m pytest tests/test_giveback.py::test_worst_giveback_measures_peak_minus_exit_gain -v`

- [ ] **Step 5: Commit.**

```bash
git add backtest/giveback.py tests/test_giveback.py
git commit -m "feat: worst-peak-to-exit-giveback metric (#420)"
```

---

## Task A4: The study runner + pre-registered verdict

**Files:**
- Create: `backtest/run_giveback_study.py`
- Create: `docs/research/2026-07-24-giveback-backtest-verdict.md`
- Reuse: `backtest/synthetic.py`, `backtest/regime.py` (`run_regime_backtest`), and the after-tax + walk-forward + Calmar helpers used by `backtest/run_leveraged_regime_study.py`.

**Interfaces:**
- Consumes: `apply_giveback`, `worst_giveback` (A2/A3); `build_synthetic_leverage`, `validate_synthetic`; the existing 200-DMA `sma_signal`, `run_regime_backtest`, and the study's after-tax-Calmar-over-walk-forward-windows computation (mirror `run_leveraged_regime_study.py` exactly — same tax mode, same window slicer, same `_after_tax_metrics`/`_curve_metrics`).
- Produces: a printed ON-vs-OFF table and the committed verdict doc. No code consumes it; it gates Phase B's *enable-live* decision.

**Pre-registration discipline (critical):** the verdict doc's "Pre-registered bar" section is written and committed **before** the study is run. The bar is: *enable live only if after-tax Calmar (giveback-ON) > after-tax Calmar (giveback-OFF)* on the same history. This is a **relative** bar (ON vs OFF), NOT the frozen SPY-vs-strategy bar (1.3085…) used for new strategies.

- [ ] **Step 1: Write the verdict doc's pre-registration section and commit it BEFORE running anything.**

Create `docs/research/2026-07-24-giveback-backtest-verdict.md` with: issue #420, the pre-registered bar quoted verbatim (Calmar-ON > Calmar-OFF), the history basis (real UPRO 2009+; synthetic-3× 1993+ validated per A1), the arm/fraction defaults (0.20 / 0.50), the intraday-on-daily / close-based caveat (spec §7), and an empty "Results" / "Verdict" section. Commit:

```bash
git add docs/research/2026-07-24-giveback-backtest-verdict.md
git commit -m "docs: pre-register the giveback backtest bar before running (#420)"
```

- [ ] **Step 2: Write `backtest/run_giveback_study.py`.**

Mirror `backtest/run_leveraged_regime_study.py`'s structure. For each history series (synthetic-3× 1993+, real UPRO 2009+): build the 200-DMA `signal` on the benchmark; run TWO arms through `run_regime_backtest` (or `run_synthetic_regime`) — **OFF** = raw signal, **ON** = `apply_giveback(signal, vehicle_close, arm_pct=0.20, protect_fraction=0.50)`; compute per-arm CAGR, max drawdown, after-tax Calmar over the walk-forward windows (identical method to the incumbent study), and `worst_giveback`. Print a table and write the numbers into the verdict doc. The −25% catastrophic stop is out of scope for this comparison (it applies identically to both arms and the engine does not model it) — state that in the doc.

```python
"""Giveback study runner — #420. Research-only; no Alpaca import, no orders.

Compares the 200-DMA-on-3x incumbent (giveback-OFF) against the same strategy
with the profit-protecting giveback (ON), on synthetic-3x (1993+) and real UPRO
(2009+). Pre-registered bar (see the verdict doc): enable live only if after-tax
Calmar improves ON vs OFF.

Usage: python3 -m backtest.run_giveback_study
"""
from __future__ import annotations
# ... imports mirroring run_leveraged_regime_study.py, plus:
from backtest.giveback import apply_giveback, worst_giveback
```

Keep the after-tax / window / Calmar computation byte-identical to the incumbent study (import or copy its helpers) so the two studies are comparable.

- [ ] **Step 3: Run the study once and record the verdict.**

Run: `RUN_NET_TESTS=1 python3 -m backtest.run_giveback_study`
Fill the verdict doc's Results table (CAGR, max drawdown, after-tax Calmar, worst-giveback — ON vs OFF, per history) and write the **Verdict**: GO (Calmar improved → Phase B may enable live after soak) or NO-GO (Calmar did not improve → Phase B still ships the code default-OFF, but the flag is never enabled and the negative is recorded). Do **not** edit the pre-registered bar after seeing results.

- [ ] **Step 4: Commit the runner + completed verdict.**

```bash
git add backtest/run_giveback_study.py docs/research/2026-07-24-giveback-backtest-verdict.md
git commit -m "feat: giveback backtest study + verdict (#420)"
```

---

# PHASE B — Live implementation (ships default-OFF)

> Phase B builds the live capability behind `GIVEBACK_ENABLED=false`. Whether the flag is ever turned **on** is decided by Task A4's verdict; the code is safe to ship either way because default-OFF is byte-identical to today.

## Task B1: Migration — lock flag + trade reason

**Files:**
- Create: `supabase/migrations/0011_giveback.sql`
- Test: `supabase/functions/_shared/db.test.ts` (DB-integration test, gated by `RUN_DB_TESTS`)

**Interfaces:**
- Produces: `regime_state.giveback_lock_active boolean not null default false`, `regime_state.giveback_locked_at timestamptz`; `trades.reason` check now allows `'giveback'`.

- [ ] **Step 1: Write the migration.**

```sql
-- 0011: profit-protecting giveback exit (#420). Adds the re-entry lock columns
-- and the 'giveback' trade reason. Additive; default-OFF feature.
alter table regime_state
    add column if not exists giveback_lock_active boolean not null default false,
    add column if not exists giveback_locked_at timestamptz;

alter table trades drop constraint if exists trades_reason_check;
alter table trades add constraint trades_reason_check check (reason in
    ('regime_flip_long','regime_flip_cash','kill_switch','panic_cli','giveback'));
```

- [ ] **Step 2: Apply against a local Postgres and run the DB test.**

Run: `supabase db reset` (or apply migrations) then `RUN_DB_TESTS=1 deno task test:db`
Expected: PASS — a row can be inserted with `giveback_lock_active=true` and a trade with `reason='giveback'`.

- [ ] **Step 3: Commit.**

```bash
git add supabase/migrations/0011_giveback.sql supabase/functions/_shared/db.test.ts
git commit -m "feat: migration for giveback lock flag + trade reason (#420)"
```

## Task B2: Config settings (default-OFF)

**Files:**
- Modify: `supabase/functions/_shared/config.ts`
- Test: `supabase/functions/_shared/config.test.ts`

**Interfaces:**
- Produces: `StrategyConfig` gains `givebackEnabled: boolean`, `givebackArmPct: number`, `givebackProtectFraction: number`. Consumed by kill-switch (B4) and daily-check (B5).

- [ ] **Step 1: Write failing tests** (mirror the existing `KILL_SWITCH_*` range tests at `config.test.ts`): defaults (`false`, `0.20`, `0.50`); out-of-range `GIVEBACK_ARM_PCT` and `GIVEBACK_PROTECT_FRACTION` throw.

```typescript
Deno.test("giveback defaults: disabled, arm 0.20, fraction 0.50", () => {
  // clear the three env vars, then:
  const c = getStrategyConfig();
  assertEquals(c.givebackEnabled, false);
  assertEquals(c.givebackArmPct, 0.20);
  assertEquals(c.givebackProtectFraction, 0.50);
});

Deno.test("GIVEBACK_PROTECT_FRACTION out of range throws", () => {
  Deno.env.set("GIVEBACK_PROTECT_FRACTION", "1.5");
  assertThrows(() => getStrategyConfig(), Error, "GIVEBACK_PROTECT_FRACTION");
  Deno.env.delete("GIVEBACK_PROTECT_FRACTION");
});
```

- [ ] **Step 2: Run — expect FAIL.** `deno task test -- --filter giveback`

- [ ] **Step 3: Implement in `getStrategyConfig()`** (mirror the `killSwitchDrawdownPct` block; use the existing `floatEnv` helper and a `boolEnv`-style read):

```typescript
const givebackEnabled = (Deno.env.get("GIVEBACK_ENABLED") ?? "false").trim().toLowerCase() === "true";
const givebackArmPct = floatEnv("GIVEBACK_ARM_PCT", 0.20);
if (givebackArmPct <= 0 || givebackArmPct >= 5) {
  throw new Error(`GIVEBACK_ARM_PCT=${givebackArmPct} outside safe bounds (0, 5)`);
}
const givebackProtectFraction = floatEnv("GIVEBACK_PROTECT_FRACTION", 0.50);
if (givebackProtectFraction <= 0 || givebackProtectFraction >= 1) {
  throw new Error(`GIVEBACK_PROTECT_FRACTION=${givebackProtectFraction} outside safe bounds (0, 1)`);
}
// add the three to the returned object + the StrategyConfig interface
```

Also add the three to `.env.example` and the README settings list (per `add-or-extend-agent`).

- [ ] **Step 4: Run — expect PASS.** `deno task test -- --filter giveback`

- [ ] **Step 5: Commit.**

```bash
git add supabase/functions/_shared/config.ts supabase/functions/_shared/config.test.ts .env.example README.md
git commit -m "feat: giveback config settings, default-OFF (#420)"
```

## Task B3: Expose the position's average entry price

**Files:**
- Modify: `supabase/functions/_shared/alpaca.ts`
- Test: `supabase/functions/_shared/alpaca.test.ts`

**Interfaces:**
- Produces: `getPositionDetail(symbol): Promise<{ qty: number; avgEntryPrice: number }>` — reads the same `/v2/positions/{symbol}` response `getPosition` already fetches; `404 → { qty: 0, avgEntryPrice: 0 }`. `getPosition` is left intact. Consumed by B4.

- [ ] **Step 1: Write the failing test** (mock a `/v2/positions/UPRO` response with `qty` and `avg_entry_price`; assert both parsed; assert 404 → `{qty:0, avgEntryPrice:0}`).
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `getPositionDetail` alongside `getPosition` (same fetch, also `requireNumber(j.avg_entry_price, ...)`; export it on the client object at `alpaca.ts:266`).
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit.** `git commit -m "feat: getPositionDetail exposes avg_entry_price (#420)"`

## Task B4: The giveback exit in `kill-switch/logic.ts`

**Files:**
- Modify: `supabase/functions/kill-switch/logic.ts`
- Modify: `supabase/functions/kill-switch/logic.test.ts`

**Interfaces:**
- Consumes: `config.givebackEnabled/givebackArmPct/givebackProtectFraction` (B2), `getPositionDetail` (B3), `getLatestQuote` (existing), the position's entry date (from the most recent `regime_flip_long` trade — add `db.getLastEntry(): Promise<{ entryDate: string } | null>` or read via an existing query), and daily highs since entry.
- Produces: on a giveback fire, liquidates, writes `giveback_lock_active=true`/`giveback_locked_at`, records a trade with `reason='giveback'`, `notifyGivebackFired`, audit outcome `success:giveback_fired`.

**Placement & precedence (spec §6):** evaluate the existing −25% drawdown check **first** (unchanged). Only if it does NOT breach, and `givebackEnabled`, evaluate the giveback. Reuse the existing bid-confirmation (#352) for the giveback down-breach. The giveback is skipped entirely (early, no behavior change) when `givebackEnabled` is false or `peakGain < armPct`.

- [ ] **Step 1: Write failing tests** (inject mocked `deps`), covering: (i) flag OFF → no giveback path touched, outcome unchanged; (ii) armed + breach + bid confirms → liquidates with `reason='giveback'`, sets lock; (iii) armed + breach but bid within floor → `skipped:breach_unconfirmed`, no liquidation, no lock; (iv) below arm → dormant; (v) −25% breach AND giveback would fire → labelled `kill_switch`, not giveback.

```typescript
Deno.test("giveback: armed peak, breach confirmed by bid -> liquidate reason=giveback", async () => {
  // deps: getPositionDetail -> {qty: 100, avgEntryPrice: 100}
  // daily highs since entry incl. 130 (peak +30%); lastPrice 112 (arm 0.20 -> floor 0.5*0.30=+15% = 115; 112 <= 115 -> breach)
  // quote bid 111 (bidGain -> also <= floor) -> confirmed
  // assert liquidate called, trade reason 'giveback', giveback_lock_active true, outcome success:giveback_fired
});
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** the giveback block after the existing `drawdown > -killSwitchDrawdownPct` early-return path is known not to have fired. Compute `entryPrice` (from `getPositionDetail`), `peakPrice = max(daily highs from entryDate..today, lastPrice)`, `peakGain`, `curGain`, `floorGain = givebackProtectFraction * peakGain`. Fire only if `givebackEnabled && peakGain >= givebackArmPct && curGain <= floorGain`, confirming against the quote bid exactly as the existing down-breach does (same fail-toward-protection on a quote outage). On fire, reuse the existing claim → liquidate → state-write → trade → notify sequence, with the giveback reason/outcome and setting the lock columns.

- [ ] **Step 4: Run — expect PASS.** `deno task test -- --filter kill-switch`

- [ ] **Step 5: Commit.** `git commit -m "feat: profit-protecting giveback exit in kill-switch (#420)"`

## Task B5: The re-entry lock gate in `daily-check/logic.ts`

**Files:**
- Modify: `supabase/functions/daily-check/logic.ts`
- Modify: `supabase/functions/daily-check/logic.test.ts`

**Interfaces:**
- Consumes: `latest.giveback_lock_active` from `getLatestRegimeState`.
- Produces: while the lock is set, daily-check does **not** re-enter LONG (stays CASH, carries the flag); the flag is cleared on any bearish day (`spyClose <= spySma200`). `computeTargetState` is untouched.

- [ ] **Step 1: Write failing tests:** (i) lock set + bullish + broker CASH → NO buy, `giveback_lock_active` carried forward, outcome `success` with a `giveback_locked` note; (ii) lock set + bearish → flag cleared, normal CASH; (iii) lock clear → unchanged behavior.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the gate.** After `computeTargetState` (unchanged) and broker reconcile: read `givebackLock = latest?.giveback_lock_active ?? false`. If `givebackLock && targetState === "LONG" && currentState === "CASH"`, override to stay CASH (skip the buy branch) and keep `giveback_lock_active=true` in the upsert. If the regime is bearish (`spyClose <= spySma200`), set `giveback_lock_active=false` in the upsert (reset). Thread the two new columns through the `upsertRegimeState` calls (default carry-forward of `latest?.giveback_lock_active`).

- [ ] **Step 4: Run — expect PASS.** `deno task test -- --filter daily-check`

- [ ] **Step 5: Commit.** `git commit -m "feat: giveback re-entry lock gate in daily-check (#420)"`

## Task B6: Notification helper

**Files:**
- Modify: `supabase/functions/_shared/notifications.ts` + `notifications.test.ts`

**Interfaces:**
- Produces: `notifyGivebackFired({ ticker, peakGainPct, exitGainPct, refPeak, lastPrice, qty, fillPrice })` — mirror `notifyKillSwitchFired` (structured JSON `event_type: "giveback_fired"` + `message`).

- [ ] **Step 1–4:** Write a test asserting the posted payload shape (mirror the `notifyKillSwitchFired` test), run FAIL, implement mirroring the existing helper, run PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: notifyGivebackFired (#420)"`

## Task B7: Backtest ↔ live parity fixture

**Files:**
- Create: `supabase/functions/_shared/giveback_fixture.test.ts`
- Reference: the same worked example as `tests/test_giveback.py::test_fires_when_gain_falls_to_half_of_armed_peak`.

**Interfaces:**
- Consumes: the giveback decision as implemented in TS (extract the pure arm/floor/exit decision from B4 into a tiny pure helper `givebackDecision({entryPrice, peakPrice, lastPrice, armPct, protectFraction}): boolean` so it can be unit-tested without broker mocks and shared with the fixture).

- [ ] **Step 1: Refactor** the B4 arithmetic into a pure `givebackDecision(...)` helper (no I/O) in `kill-switch/logic.ts` (or `_shared/`), called by the exit path.
- [ ] **Step 2: Write the parity test** using the SAME numbers as the Python `test_fires_when_gain_falls_to_half_of_armed_peak` (entry 100, peak 120, price 109, arm 0.20, fraction 0.50 → fire true; price 111 → false), asserting the TS decision matches the Python behavior.
- [ ] **Step 3: Run — expect PASS** (after the helper exists). `deno task test -- --filter giveback`
- [ ] **Step 4: Commit.** `git commit -m "test: backtest<->live giveback parity fixture (#420)"`

---

## Self-Review

**Spec coverage:**
- §3 exit rule → A2 (`apply_giveback`) + B4 (`givebackDecision`) + B7 parity. ✓
- §4 re-entry lock → A2 (lock in the transform) + B5 (daily-check gate). ✓
- §5 stateless peak recompute → B4 (recompute `peakPrice` from bars since entry each tick). ✓
- §6 precedence + bid-confirm → B4 (−25% checked first; bid-confirm reused). ✓
- §7 backtest + pre-registered bar → A1 (validation), A4 (study + verdict, bar pre-committed). ✓
- §8 parity → B7. ✓
- §9 schema/config/notify → B1/B2/B3/B6. ✓
- §10 invariant → Global Constraints + B5 keeps `computeTargetState` untouched. ✓
- §12 acceptance (default-OFF byte-identical) → B2 default false; B4/B5 early-out when disabled; assert in tests. ✓

**Placeholder scan:** the `0011` migration number and the "mirror `run_leveraged_regime_study.py`" reference are the only deferrals; both point at concrete existing artifacts, not undefined behavior.

**Type consistency:** `givebackEnabled/givebackArmPct/givebackProtectFraction` (B2) are the names consumed in B4/B5; `getPositionDetail -> {qty, avgEntryPrice}` (B3) matches B4's consumption; `apply_giveback`/`worst_giveback` signatures match A4's use; `giveback_lock_active`/`giveback_locked_at` consistent across B1/B4/B5.

## Notes on sequencing & sizing

- **Phase A is the gate.** If Task A4 returns NO-GO, Phase B still ships (code is dormant, default-OFF) but the flag is never enabled — record that outcome and stop before a live enablement.
- Phase A (A1–A4) and Phase B (B1–B7) are independent until B7 (parity) references A2's worked example. Natural slicing into `/tm-kickoff` packages: **Package 1** = A1–A4 (research verdict, `size:M`); **Package 2** = B1–B3 (schema/config/broker plumbing, `size:S`); **Package 3** = B4–B7 (live logic + parity, `size:M`). Package 3 depends on Packages 1 (parity numbers) and 2 (config/broker).
