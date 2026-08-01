# Design spec: hourly-candlestick long/short bot (SPY, Alpaca paper)

**Issue:** #466 (P2 of batch #464) · **Date:** 2026-07-27 · **Status:** DESIGN

> This document specifies the behavior only. It authorizes **nothing live**. The bot it
> describes is **paper-only by mechanical guard** (§8) — no live-money surface exists in
> this spec or the batch it belongs to. It supersedes the retired 200-DMA / UPRO regime rule
> on the merge of the Batch 2 build that implements this spec (the ADR at
> `docs/decisions/2026-07-27-hourly-candlestick-signal.md` records that supersession now;
> the rule itself does not change until Batch 2 ships). No code, migration, or CLAUDE.md
> edit is made by this package — this is the contract Batch 2 builds against and Batch 3
> deploys.

---

## §0 Banner (restated for scanners)

- Paper-only. No live order of any kind is authorized by this document.
- Supersedes the SPY-close-vs-200-DMA rule (`computeTargetState`, `_shared/regime.ts`) as
  the bot's **one decision rule**, per the one-decision-rule invariant, once Batch 2 lands.
- No LLM anywhere in this design. The signal is a pure function.
- This spec answers every question Batch 2's developer would otherwise have to invent; an
  architect should be able to sub-plan the Batch 2 build from this document alone (self-test
  in §D of the sub-plan; file-set list in §14).

---

## §1 Motivation and operator direction

Batch #464 (operator sign-off 2026-07-27, after two revise rounds at `/tm-advisor`) directs:

- Deprecate the UPRO / 200-DMA bot immediately. It is paper-deployed only (#230 go-live never
  happened), so deprecation costs nothing live.
- Build an **hourly-candle, long/short signal on SPY**, traded on the Alpaca **paper**
  account, candlestick pattern detectors as signal v1 (P3, #467).
- Proceed **by operator direction with the evidence base disclosed** — this bot ships with
  no pre-registered evidence of edge (§2). Paper-only is the accepted risk container.
- Programme structure: Batch 1 (this batch: deprecate + spec + signal port + forex research
  leg) → Batch 2 (`hourly-check` Edge Function build to this spec) → Batch 3 (deploy to dev,
  cron on, first paper trades, weekly review loop).

This spec is P2 of Batch 1. It does not itself deprecate anything, port any detector, or
touch code — that is P1 (#465), P3 (#467), and Batch 2 respectively.

---

## §2 Honest evidence context

This section is placed early, not buried in an appendix, because the operator direction in
§1 is explicitly "build it anyway, with the evidence disclosed" — a future reader must see
exactly what was known at design time without digging.

**Three independent research passes have closed rule families that a naive reading might
assume this bot resembles:**

1. **Short-horizon rule-based entries — class NO-GO** (`docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md`,
   #422). §5's verdict: *"the exact rule families this direction would use are already
   class-killed three independent times... the cost wall kills the minute end and all
   intraday crypto outright (72–6,477%/yr drag), and the data wall means the only
   cost-survivable corner (1h US-equity / index-futures) cannot be credibly tested for free,
   because no free intraday history reaches the frozen n_w = 13 comparability bar."*
   - §2's cost-wall table: **1h US-equity ETF cost drag ≈ 1.7%/yr** — the *favourable*
     nuance, stated honestly: this is the one cadence/universe cell that survives the cost
     wall outright (15-minute is borderline and PDT-illegal sub-$25k; 1-minute is killed
     everywhere).
   - §3's data-scarcity finding: no free intraday source clears the pre-registered n_w = 13
     comparability bar. SPY 5Min SIP reaches only n_w ≈ 9; **the free feed this bot's paper
     account actually uses, IEX from 2020-07, reaches only n_w ≈ 5** — 7–8 windows short.
     Only *daily* SPY/ES history clears the bar, which is the incumbent's own cadence, not
     this bot's.
2. **Candlestick pattern family (daily, SPY) — NO-GO at cumulative N=168**
   (`docs/research/2026-07-26-candlestick-timestop-preregistration.md`, #448). The pooled
   #398 overfitting gate across all three rounds (v1 context-free N=28, v2 trend-context
   N=56, v3 time-stop N=84; `backtest/tested_cells.py`'s three `candlestick_pattern*` CLOSED
   rows) returns DSR FAIL / PBO PASS / bootstrap-CI FAIL → combined FAIL at every round. 0
   of 168 cells cleared the frozen 1.3085 after-tax-Calmar SPY bar. §9 of that document
   closes the entire candlestick widening programme (no round 4).
3. **MES swing-contracts survey — NO-GO at cumulative N=24** (#457,
   `backtest/tested_cells.py`'s `mes_swing` CLOSED row). 0/24 cells cleared either preset;
   the pooled #398 gate FAILs.

**The nuance that makes this honest, not just a list of NO-GOs:** all three closed grids
above are **daily**. This bot runs on **1-hour bars**. It is therefore not a re-run of a
closed cell — `backtest/candlestick.py`'s own module docstring states the cadence caveat
explicitly: *"Cadence is load-bearing — read before using this on intraday bars... [an]
intraday grid must carry #422's cost and power caveats explicitly and is not gate-eligible
on free data."* §3 of #422 is unambiguous on why: an hourly candlestick grid **cannot be
credibly pre-registered and tested on free data at all** — not "was tested and failed," but
"cannot be evaluated to the repo's own power standard on the data this bot can actually get
for free." That is a materially different — and honestly worse, from an evidentiary-rigor
standpoint — starting position than the closed daily grids: those at least reached a
verdict. This bot ships with **no verdict of any kind**, by operator direction, with
paper-only as the accepted risk container (§8).

**One more favourable arithmetic point, stated honestly, with its own caveat:** at the
Alpaca paper account's ~$100k class of equity, FINRA's PDT rule (3 day-trades / 5 business
days for sub-$25k margin accounts) does **not bind** — §2 of #422 computes 1h equity trading
at ~1.1 day-trades per 5 business days, under the cap regardless of account size class. But
this bot's own §7 order model closes every bracket intraday (session-close flatten, N3
decision below) — **every filled trade is, by construction, a day trade** — so the PDT
statement is conditional on the account staying above the $25k threshold; it is not a
structural exemption the way the FX/futures universes in #422 are.

**What this section is not:** a licence to retune detectors in place if the live firing
rate looks different from the daily-calibrated one (§4 requires disclosure, not
retuning), and not a claim that daily-grid failure predicts hourly-grid failure — the point
is precisely that no one knows, on free data, at this cadence.

---

## §3 Scope and non-goals

**In scope:**
- The hourly cadence, completed-candle semantics, and staleness guard for SPY 1h bars (§4).
- The composite decision rule `decideHourly` sitting on top of P3's `scanCandles(bars)`
  (§5), including the conflict tie-break and cooldown/cap rules.
- Sizing (§6), the bracket order model for both directions (§7), the safety stack (§8),
  persistence (§9), config (§10), the weekly review loop (§11), and the CLAUDE.md amendment
  text (§12, PROPOSED only).

**Non-goals (this package, per #464/#466):**
- **No code, no migrations, no CLAUDE.md edit.** This is the contract; Batch 2 builds it.
- **No new backtest claims.** §2 cites the existing research record; it generates no new
  numbers.
- **No retuning of the 14 detectors or their thresholds** — those are P3's frozen port
  (#467) of `backtest/candlestick.py`'s `PATTERNS` registry, unchanged.
- **The short-side safety-stack retrofit is its own Batch 2 package** (§8, §14; N7). This
  spec states its requirements; it does not design the implementation.
- **No Elliott Wave / forex** — that is P4 (#468), a separate research leg.

---

## §4 Cadence, universe, and completed-candle semantics

**Universe:** SPY to start; extensible in principle, but v1 trades exactly one symbol —
consistent with keeping the composite rule's single-symbol claim/cooldown state simple
(§5, §9).

**Cadence — reuse the kill-switch's wide-window + in-function-gate shape, not
daily-check's two-slot device.** The two-slot trick
(`supabase/migrations/0006_daily_check_open_schedule.sql`) exists to make a *once-daily*
action land exactly once across US DST. An hourly scan is a different shape, already
solved by the kill-switch: **one** `pg_cron` job over a wide UTC window, Mon-Fri, plus an
in-function `alpaca.getClock()` gate that exits `skipped:market_closed` — no DST logic in
code (`supabase/migrations/0002_schedule.sql:40-54` is the pattern; the gate is
`supabase/functions/kill-switch/logic.ts:126-129`).

- Cron: `hourly-check` job, `pg_cron` expression covering `13-21 UTC, Mon-Fri` (same window
  as the kill-switch's `*/5 13-21 * * 1-5`, but firing once per hour, not every 5 minutes).
- **Minute pin is a hard constraint, not merely "not divisible by 5" (must-fix round 1
  finding 1).** Alpaca's `1Hour` bars are wall-clock-hour aligned and end on the hour
  (`:00`), so a scan firing `MM` minutes past the hour sees a newest-completed bar that is
  already `MM` minutes old **by construction**, before any feed latency is even counted.
  This couples the cron minute directly to `HOURLY_STALENESS_TOLERANCE_MIN` (default `10`,
  §10): **`cronMinuteOffset + expectedFeedLatencyMin < HOURLY_STALENESS_TOLERANCE_MIN`** is
  a hard requirement, not a coincidence to discover at deploy time. The sub-plan's own
  illustrative minute, `:17`, **violates this constraint** (17 > 10 exceeds the default
  tolerance outright — every run would exit `skipped:stale_data`) and must not be used; this
  spec corrects that example. A minute such as **`:07`** satisfies both this inequality (7
  minutes + a small assumed feed-latency budget stays under the 10-minute default) and the
  original collision-avoidance requirement (not divisible by 5, so it never lands on the
  kill-switch's `*/5` grid). Batch 2 must re-verify this inequality against whatever minute
  and tolerance it actually deploys — raising `HOURLY_STALENESS_TOLERANCE_MIN` to paper over
  a badly-chosen minute, instead of choosing a minute that satisfies the inequality at the
  default tolerance, is explicitly the wrong fix.
- The function's own `getClock()` gate is authoritative for open/closed and holidays; the
  cron predicate fires unconditionally within the window (the codebase map's documented
  pattern — cron fires regardless of market state, gating lives entirely in the Edge
  Function).

**Completed-candle semantics — port daily-check's two-part discipline**
(`supabase/functions/daily-check/logic.ts:110-133`):

1. **Filter to strictly completed bars.** The bars feed can return an in-progress bar during
   market hours; the signal must never see it.
2. **Staleness guard.** There is no `getCalendar()` analogue for hour boundaries (Alpaca's
   calendar endpoint is date-granular), so the hourly guard is: `now − barEndTime ≤
   HOURLY_STALENESS_TOLERANCE_MIN` (config, §10) **and** the `getClock()` gate above. A bar
   older than the tolerance, with the market open, is `skipped:stale_data`.

**Guard precedence — deterministic order (must-fix round 1 finding 1).** The gates below run
in a fixed order every scan, so a given run always resolves to exactly one outcome rather
than depending on which check happens to be coded first:

1. `getClock()` — market closed ⇒ `skipped:market_closed`.
2. Filter to strictly completed bars, then **exclude partial session-edge bars** (below). If
   the newest bar that would otherwise be the signal bar is excluded as partial, the scan is
   `skipped:partial_bar` — **this check runs before the staleness guard.**
3. Only if step 2 leaves an eligible, non-partial, completed bar: apply the staleness guard
   (`now − barEndTime ≤ HOURLY_STALENESS_TOLERANCE_MIN`). A bar that fails this check is
   `skipped:stale_data`.

This ordering exists specifically so the **first scan of a trading session** — where the
newest wall-clock-hour bar is a truncated session-open stub (below) — always resolves to
`skipped:partial_bar`, never `skipped:stale_data`. The two skip reasons are selected by this
fixed precedence, not by incidental code order.

**Partial session-edge bars are excluded from the signal.** Alpaca's `1Hour` timeframe bars
are **wall-clock-hour aligned, not session aligned** — the first bar of the RTH session
(9:30–10:30 ET) and the last bar (a short stub before the 16:00 ET close, since 15:00–16:00
ET is itself a full hour but session length may not divide evenly depending on the exact
Alpaca alignment) can be partial. A partial bar's body/wick geometry is not a real hourly
candle and would corrupt every detector that reasons about proportional body/wick size.
Decision: **exclude any bar whose observed duration is shorter than a full hour from the
signal** (still journaled, marked `partial_bar` in `hourly_scans.skip_reason` if it would
otherwise have been the signal bar).

**`[to verify]` — Batch 2 must confirm the exact bar alignment before the first live scan.**
This spec does not assert Alpaca's exact `1Hour` bar boundaries from memory. Required
verification step: a **read-only** `GET /v2/stocks/SPY/bars?timeframe=1Hour&...` call (no
guard needed — `getDailyCloses`-style helpers are unguarded reads) during a live RTH session,
recording the returned bar-start timestamps and whether the first/last bars of the session
are shorter than 60 minutes. **Fallback if verification is delayed:** treat every bar whose
`start` timestamp does not fall on a clean top-of-hour boundary in the exchange's local time
as suspect and exclude it defensively (over-exclusion, never under-exclusion, is the
fail-safe direction here).

**Feed and geometry risk — its own subsection, easy to miss.** `_shared/marketdata.ts`
builds every bars/trades/quotes URL with `feed=${cfg.dataFeed}`
(`supabase/functions/_shared/marketdata.ts:31,49,67`), and `cfg.dataFeed` defaults to `iex`
(`supabase/functions/_shared/config.ts:95-98`, `.env.example`). IEX prints are a small slice
of consolidated SPY volume, so **IEX hourly OHLC geometry is not SIP geometry** — and the 14
detectors' frozen thresholds (`FIRING_RATE_MIN = 0.005` / `FIRING_RATE_MAX = 0.25` in
`backtest/candlestick.py`) were calibrated on **consolidated daily** SPY bars, a different
feed and a different cadence from what this bot will see live.

**Requirement (not a licence to retune):** the live journal (`hourly_scans`, §9) must record
enough — every fire, per detector, per bar — to compute per-detector firing rates on the
real feed during the paper soak. A live firing rate outside `[0.005, 0.25]` is a **disclosed
finding**, reported in the weekly review (§11), never a trigger to retune the detector
in-flight — the same rule as the Python module's own docstring convention (frozen unless a
version bump).

---

## §5 Signal contract

**The rule is one composite pure function**, `decideHourly(bars, cfg) → { action:
"LONG"|"SHORT"|"SKIP", reason, detectorsFired[] }`, sitting on top of P3's
`scanCandles(bars)` (#467's acceptance criteria: *"module exports a deterministic
`scanCandles(bars)` → per-detector signal surface usable by Batch 2's function"*). It is
I/O-free and unit-testable, following the `computeTargetState` precedent
(`supabase/functions/_shared/regime.ts`) — mechanically invariant-scanned by
`supabase/functions/_shared/invariants.test.ts`.

**This redefines what "one decision rule" (CLAUDE.md invariant #1) means for a 14-detector
registry — ratified explicitly, not inferred.** Per the lead's decision on the sub-plan's
N1: **the composite pure function is the rule.** One function, one frozen configuration
(the 14-detector registry + tie-break + cooldown, all frozen together), no parallel
overlay. `decideHourly` is the single decision rule the invariant protects, in exactly the
sense `computeTargetState` was — this is stated explicitly in the ADR (§13 below; the ADR's
Decision section), because it redefines what the invariant text means rather than merely
applying it.

**Direction.** Each detector's direction comes from the frozen registry entry
`PATTERNS[name][1]` in `backtest/candlestick.py`. Two entries — `doji` and `inside_bar` —
are registered `NEUTRAL` with the comment *"need a breakout side from the caller"*
(`backtest/candlestick.py:292`, entries at `:309-310`). **v1 has no breakout side.** These
two detectors are **journal-only diagnostics and never trigger an entry** — they are
recorded in `detectorsFired` when they fire, but excluded from the direction vote below.

**Multiple same-direction fires on one bar → exactly one entry.** If two or more
same-direction (all-bullish or all-bearish) detectors fire on the same completed bar, the
result is a single `LONG` or `SHORT` action; all firing names are journaled. **No
confluence sizing bonus** — sizing (§6) is identical whether one or five same-direction
detectors fired. Confluence weighting was an explicit non-goal in #448.

**Conflict tie-break: `SKIP`.** If ≥1 bullish detector and ≥1 bearish detector fire on the
same bar, the action is `SKIP` with `reason = "signal_conflict"` (audit outcome
`skipped:signal_conflict`). Rationale: the whole candlestick family returned NO_GO at
cumulative N=168 across all three rounds (§2) — **no evidence in this repo ranks one
detector above another**. Any priority ordering (e.g. "bearish_marubozu beats
bullish_harami") would be a post-hoc rule invented from a failed grid, which this repo's
research method (pre-registration, no in-flight retuning) forbids by the same discipline
`docs/research/2026-07-26-candlestick-timestop-preregistration.md` applies to its own
grids.

**Worked example — conflict tie-break.** Bar closes with `bullish_harami` firing (bullish)
and `shooting_star` firing (bearish) on the same completed hourly bar:

| Detector | Direction | Fires? |
|---|---|---|
| `bullish_harami` | BULLISH | yes |
| `shooting_star` | BEARISH | yes |
| (12 others) | — | no |

Bullish count = 1, bearish count = 1 → both ≥ 1 → **`SKIP`**, `reason =
"signal_conflict"`, `detectorsFired = ["bullish_harami", "shooting_star"]`. The bar is
journaled (`hourly_scans`, §9) with `decision = "SKIP"`, `skip_reason =
"signal_conflict"`; no order is placed.

**Context mode.** `contextMode ∈ {none, reversal, continuation}`
(`CONTEXT_MODES`, `backtest/candlestick.py:327`), a frozen config setting, default `none` —
the context-free v1 form, matching the closed v1 grid's own default. Warm-up bars (no
`t-1`/`t-2` history, or, when `contextMode != none`, fewer than `CONTEXT_SMA_WINDOW` bars of
context history) are **masked out**, never admitted as a signal — same rule as the Python
detector module.

**Semantic trap, stated loudly:** `CONTEXT_SMA_WINDOW = 200`
(`backtest/candlestick.py:329`) means **200 bars**, not 200 days. On this bot's **1-hour**
bars, 200 bars is roughly 30 US trading sessions (≈6.5 RTH hours/session), not the ~200
trading days the incumbent 200-DMA rule used. `contextMode = none` (the default) sidesteps
this entirely for v1; any future move to `reversal`/`continuation` mode must carry this unit
correction explicitly in its own spec revision.

**One position at a time, broker-sourced.** Position state comes from
`alpaca.getPosition(symbol)`, never from the DB — the standing broker-truth rule
(`supabase/functions/kill-switch/logic.ts:97-101`, #237; restated in the codebase map,
`docs/architecture/2026-07-05-codebase-map.md:35`: *"broker position is source of truth"*).
A non-zero position (either sign) blocks any new entry decision that bar.

**Cooldown and the entry cap — decided (lead's D2 on N4).** Cooldown is the scan cadence
itself: **at most one entry decision per hourly bar**, and after an exit, **no re-entry
until the next completed bar after the exit** (derived from the journal's timestamp of the
last exit — a stateless recompute, not a mutable flag, matching the giveback spec's §5
reasoning: `docs/superpowers/specs/2026-07-24-giveback-exit-design.md` §5). **Max 3 entries
per symbol per day** — generous against the ~0.22 trades/day modeled in #422 §2, while
capping worst-case intraday cost drag. Both numbers are frozen for v1 and reviewable at the
4-week/30-trade checkpoint (§11, N5).

**Post-kill-switch-fire semantics — decided (must-fix round 1 finding 2), adapted from
`regime.ts`'s `killSwitchActive` precedent.** The incumbent encodes the flag as an input to
`computeTargetState` (`_shared/regime.ts`): bearish preserves it, bullish clears it — because
the incumbent is long-only, "bullish" *is* "the direction opposite the forced-CASH state."
This bot is long/short-symmetric, so the precedent generalizes to: **the flag clears exactly
when the next decision opposes the side that was stopped out**, not on any decision at all.

- **Flag storage.** Not `regime_state` (§9 keeps that table unextended, scoped to the
  retired bot). The retrofit package (§8.1) writes three `bot_config` keys on a kill-switch
  fire for this bot — the same key/value store that already holds `paused`, so no new
  migration is needed: `hourly_kill_switch_active` (boolean), `hourly_kill_switch_side`
  (`'LONG'|'SHORT'` — the side of the position that was stopped out), and
  `hourly_kill_switch_fired_at` (timestamptz, for the audit trail).
- **Re-entry rule.** While `hourly_kill_switch_active = true`, `hourly-check` runs an early
  deterministic gate — the same shape as the `bot_config.paused` gate (§8.3) — **before**
  the position-open check: if the current scan's `decideHourly` output is `SKIP`, or is the
  **same** side as `hourly_kill_switch_side`, no entry is placed and the scan is
  `skipped:kill_switch_active` (§9). Only a decision on the **opposite** side from
  `hourly_kill_switch_side` is allowed through — mirroring "bullish clears the flag" for a
  bot where either side can be the one that got stopped out. **Relative order (nit, round 2):
  this gate runs *after* §7's reconciliation contract** (the every-scan step that writes
  newly-closed exit legs and re-legs or flattens a naked position, run before any new-entry
  decision) — matching §7's own "on every scan, before deciding" wording, so this gate always
  sees post-reconciliation broker truth rather than a stale pre-reconciliation view.
- **Clearing condition.** The first scan whose decision opposes `hourly_kill_switch_side`
  both clears the flag (sets `hourly_kill_switch_active = false`,
  `hourly_kill_switch_side = null`) **and** is the entry that is allowed through — clearing
  and re-entry happen atomically at the same decision point, exactly as in `regime.ts`
  (bullish both clears the flag and sets the LONG target in the same call). This is
  deliberately **not** time-based (no "wait N hours/days") — the incumbent's rule was never
  time-based either; it is signal-based, and this is the direction-aware generalization of
  that same rule.
- **Both directions blocked, not just the stopped-out one, until cleared.** Unlike the
  incumbent (where a bearish signal simply reproduces the existing forced-CASH state, so the
  flag is inert while bearish), this bot's cooldown/cap rules would otherwise permit a
  same-side re-entry as soon as one hour later. The gate above exists precisely to override
  that — a kill-switch fire is a drawdown safety event, not a normal exit, and must not be
  treated as merely starting the standard next-bar cooldown.

---

## §6 Sizing

Equity is read via `alpaca.getAccountValue()` → `/v2/account`'s `equity` field, USD
(`supabase/functions/_shared/alpaca.ts:110-113`; Alpaca accounts are USD-denominated).

**Order of computation: stop first, then quantity.**

```
riskBudget  = SIZING_RISK_PCT × equity                    // default 0.01 (1%)
stopDistance = |entryRef − stopPrice|                     // from the bracket geometry, §7
qtyRisk     = floor(riskBudget / stopDistance)
qtyCap      = floor(SIZING_NOTIONAL_CAP_PCT × equity / entryRef)   // default 0.10 (10%)
qty         = min(qtyRisk, qtyCap)
```

Whole shares only (`Math.floor`, matching `daily-check/logic.ts:211`); `trades.qty` is
`integer` — `0005_numeric_money.sql`'s comment states explicitly *"qty stays integer (whole
shares)"*. No fractional shares, in either direction.

`entryRef` = `getLatestTradePrice(symbol)` at order time (the `daily-check` precedent,
`logic.ts:210`), while the **signal** and the bracket geometry (`stopPrice`, `targetPrice`)
come from the completed bar that triggered the decision. Every JSON→number boundary goes
through `requireNumber` (`_shared/num.ts`).

**Geometry-invalid guard — should-fix round 1 finding 12, added.** Because `entryRef` is
read fresh at order time while `stopPrice` was fixed from the completed signal bar, price can
move between them. Two failure modes are otherwise unguarded: (a) **inverted geometry** —
`entryRef` has moved to the wrong side of the stop (long: `entryRef ≤ stopPrice`; short:
`entryRef ≥ stopPrice`), which would produce a broker rejection at best and a nonsensical
bracket at worst; (b) **degenerate `stopDistance`** — a near-zero distance inflates
`qtyRisk` arbitrarily, leaving the notional cap as the only effective sizer, silently
defeating the risk-based leg of §6's `min()`. **Guard, evaluated before `qtyRisk`/`qtyCap`:**
if `entryRef` is not on the correct side of `stopPrice` by at least `HOURLY_MIN_STOP_DISTANCE`
(new config, §10; default `$0.05`), the scan is `skipped:geometry_invalid` (§9) and no order
is placed — this check runs whether the failure is the inversion case or the
too-close/degenerate case, since both are "the geometry is not usable," and both are cheaper
and safer to skip than to size around.

**`qty ≤ 0` → `skipped:size_too_small`, a normal skip with a journal row** —
deliberately unlike `daily-check`'s `error:insufficient_funds`
(`daily-check/logic.ts:212-221`). For a scanner that runs every hour, a zero-size bar is
routine (a wide stop on a large-notional account, or low equity), not an error condition;
treating it as `error:*` would flood the audit log with false alarms. This is stated
explicitly so the reviewer reads it as an intentional divergence, not an inconsistency with
`daily-check`'s pattern.

### Worked numeric example

Assume: `equity = $100,000`, `SIZING_RISK_PCT = 0.01`, `SIZING_NOTIONAL_CAP_PCT = 0.10`.
Signal bar: a `bullish_harami` fires, entry reference (latest trade) = `$550.00`, pattern
stop (bar low − buffer, §7) = `$547.75` (a `$2.25` stop distance).

```
riskBudget    = 0.01 × 100,000            = $1,000
stopDistance  = |550.00 − 547.75|         = $2.25
qtyRisk       = floor(1,000 / 2.25)       = floor(444.44) = 444 shares
qtyCap        = floor(0.10 × 100,000 / 550.00) = floor(18.18) = 18 shares
qty           = min(444, 18)              = 18 shares
```

The 10% notional cap binds here — a $2.25 stop on a $550 stock is a very tight *percentage*
stop (0.41%), so the risk-sized share count is large relative to notional. Sizing purely on
risk would put 444 × $550.00 ≈ **$244,200 (244% of equity, on margin)** into a single
position, which the 10% notional cap prevents.

A second example where the risk cap binds instead: same equity and entry price, but a wider
stop of `$11.00` (`stopDistance = 11.00`): `qtyRisk = floor(1,000 / 11.00) = 90`; `qtyCap =
floor(10,000 / 550.00) = 18`; `qty = min(90, 18) = 18` — the notional cap still binds at
this instrument price; a lower-priced instrument (e.g. entry `$25.00`) with the same $11
stop would flip it: `qtyCap = floor(10,000 / 25.00) = 400`, `qtyRisk = 90`, `qty = min(90,
400) = 90` — the risk cap binds instead. Both branches of the `min()` are real and expected
in different price/stop regimes.

---

## §7 Order model

**Today's client has no bracket support.** `placeMarketOrder` posts a plain `{symbol, qty,
side, type: "market", time_in_force: "day"}` body (`supabase/functions/_shared/alpaca.ts:138-148`);
there is no `order_class` field anywhere in the repo today. Batch 2 must add a **guarded**
`placeBracketOrder` — its first statement must be `checkGuard("placeBracketOrder")`, the
same pattern `checkGuard` follows at `alpaca.ts:59-65` and is called at `:129`, `:237`,
`:244`.

**Bracket geometry — decided (lead's D2 on N2): pattern-geometry stop, frozen R = 2 target.**
The stop is the signal bar's own extreme plus a buffer (long: bar low − buffer; short: bar
high + buffer), matching `backtest/bracket.py`'s frozen contract that **the caller passes
absolute levels** — the module's own docstring: *"the caller [owns the geometry] — it never
hardcodes `entry ± k×N` internally"* (`backtest/bracket.py:17`). This is the Turtle/ORB
precedent already in the repo (#430/#431) and is self-documenting against the exact bar the
detector fired on. The target is `entry ± R × stopDistance` with **R = 2** frozen — the
conservative end of the house `R_GRID` (`(2.0, 3.0)` in `backtest/run_candlestick_study.py:93`).
No evidence ranks either value (§2); R=2 minimizes target distance and time-in-trade,
consistent with the operator's "short-lived contracts" framing (lead's D2 rationale on
#464).

**Buffer — frozen (must-fix round 1 finding 7).** Left as "a Batch 2 detail" in the prior
draft; that is a free parameter that directly sets `stopDistance` and therefore `qty` (§6),
exactly the class N2's own rationale requires be frozen in the spec. Frozen formula:
**`buffer = HOURLY_STOP_BUFFER_PCT × barRange`**, where `barRange = barHigh − barLow` for the
signal bar and `HOURLY_STOP_BUFFER_PCT` defaults to **`0.05`** (5% of the bar's own range) —
added to §10's settings table. Long: `stopPrice = barLow − buffer`; short: `stopPrice =
barHigh + buffer`. No evidence ranks this value either (§2's caveat applies here exactly as
it does to R=2); 5% is chosen only to keep the stop off the literal bar extreme (avoiding a
stop that gets grazed by the next bar's noise) without materially widening `stopDistance`.
Changing it in-flight is forbidden by the same rule as R=2 and every other frozen v1
parameter (§11) — a change requires a spec revision.

**Amendment 2026-07-31 (#494) — both bracket prices are quantized to whole cents, stop
first.** Found live on the first RTH session after the cron activated: Alpaca rejects any
equity price above $1 that is not a $0.01 multiple (HTTP 422, code 42210000), and the
geometry above produces raw floats — `buffer = 0.05 × barRange` on a 2-decimal range yields a
4-decimal stop, and `R × stopDistance` then lands on a tenth of a cent. Two live rejections:
`745.0495000000001` (float noise and sub-penny) and `746.173` (exact, genuinely a tenth of a
cent). Quantization is now part of the frozen geometry:

- `stopPrice = roundToCents(barLow − buffer)` (long) / `roundToCents(barHigh + buffer)`
  (short), nearest cent, no directional bias.
- `stopDistance` is then recomputed **from the rounded stop**, and the target is
  `roundToCents(entry ± R × stopDistance)`. **The ordering is load-bearing**, not cosmetic:
  it removes the exact half-cent tie class the ×2 creates whenever the bar range ends in
  `x.x5`, and it keeps wire R exactly R against wire risk, so the journaled `stop_price` and
  the broker's `stop_price` are the same number.
- `entry_ref_price` and `risk_per_share` are deliberately **not** quantized: neither goes on
  the wire, the first is a record of what the bot saw and the second is §11's R denominator.
- Changing R or the buffer still requires a spec revision (§11). This amendment changes
  neither; nearest-cent quantization has expected shift 0 and a half-cent bound, far below
  the slippage floor of the market entry leg.
- `placeBracketOrder` / `placeOcoExitPair` **validate** the serialized price and throw
  `SubPennyPriceError` rather than rounding it themselves — silent rounding at the wire
  would desync the broker's prices from the journal. The class extends `AlpacaError`, so
  the outcome alerts (§9); the check runs after the `CLAUDE_AGENT_NO_BROKER` guard.

**Both directions.** A `LONG` decision buys with a stop below and a target above; a `SHORT`
decision sells short with a stop above and a target below. `[to verify]` — Batch 2 must
confirm, against the live Alpaca API docs, whether `order_class: "bracket"` is accepted on a
**short** entry side. **Documented fallback if unverified or unsupported:** place a plain
market entry (long or short) via the existing guarded `placeMarketOrder`, then — once the
entry fill is confirmed — place an `order_class: "oco"` exit pair (stop + limit) against the
resulting position. Either path reconciles to the same journaled outcome (§9); the fallback
adds one extra broker round-trip and a narrower race window between entry-fill and
exit-legs-resting, which must be covered by the reconciliation step below.

**`[to verify]` — permitted `type`/`time_in_force` combinations for a bracket entry** (e.g.
whether a bracket entry must be `time_in_force: "day"` or also accepts `"gtc"`). Fallback:
default to `"day"`, matching every existing order in this repo (`alpaca.ts:146`), until
verified otherwise.

**Shortability check at deploy time, fail-closed. `[to verify]`** (must-fix round 1 finding
6 — this was the one Alpaca API assertion in this spec shipping unlabelled; corrected here).
Before the first live scan, Batch 3 (or an early Batch 2 smoke step) must check `GET
/v2/assets/SPY`, whose response is asserted here to carry `shortable` / `easy_to_borrow`
boolean fields — **like the other five `[to verify]` items in this spec (bar alignment,
bracket-on-short, bracket entry `type`/`time_in_force`, the paper-account marker, and the
`/v2/clock` `next_close` field used by the session-close flatten mechanic below), this is a
claim about Alpaca's live API surface, not a repo fact, and is not confirmed against a real
response.** This spec now carries **six** `[to verify]` Alpaca API assertions in total, each
with a documented fallback — the count is up from five as of must-fix round 2 finding 1
(the `next_close` field). Required verification step: capture a real `/v2/assets/SPY` response on the
paper account and confirm both field names and their boolean semantics before relying on
them. If SPY is not shortable per the confirmed fields, every `SHORT` decision is
`skipped:not_shortable` rather than attempting an order that would reject — fail-closed, not
fail-and-retry. **Fallback if the fields cannot be confirmed at all** (endpoint missing,
fields renamed, or response ambiguous): the failure mode must not be silent — a config flag,
`HOURLY_SHORTS_ENABLED` (default `false` **[CORRECTED #493]**, §10), must be `false` and the
reason disclosed in the deploy notes/runbook; with shorting disabled this way, every otherwise-
`SHORT`-eligible bar still journals `skipped:shorts_disabled` (§9), so the gap is visible in
the data itself, not only in a runbook note that could go stale or unread.

**Entry-leg semantics reuse the existing poll/error contract; exit legs are
broker-resident.** The entry leg uses the same poll-until-filled logic, `OrderTimeoutError`,
and `OrderRejectedError` semantics `placeMarketOrder` already implements
(`alpaca.ts:169-233`) — this is the *entry* leg only. The take-profit and stop-loss legs, once
the bracket (or OCO fallback pair) is resting, are **broker-resident**: they fill or don't
without this bot polling them tick-by-tick. **Reconciliation contract:** every scan, before
making a new decision, the function must reconcile broker order state and write any
newly-closed exit leg to `trades` (§9) — a fill discovered this way is recorded with
`reason = 'hourly_bracket_exit'` (or the specific stop/target/session-close variant, §9) —
**before** deciding whether a new entry is permitted (so the position-flat check in §5 sees
the post-fill broker truth, not a stale in-memory view).

**Position-without-legs rule (must-fix round 1 finding 3) — fail-toward-protection, chosen
and stated.** The reconciliation step above must also detect the state the OCO-fallback race
window (above) and an entry-poll timeout can both produce: an **open broker position with no
resting stop/target (or OCO) legs at all** — the exit-leg placement failed after the entry
filled, or timed out before confirmation. This state has no specified behavior elsewhere in
this spec; it is specified here:

1. Look up the bracket geometry (`stop_price`, `target_price`) from the `hourly_scans` row
   (§9) that produced the open position's entry, keyed on the entry's `bar_ts`.
2. **Re-place the missing legs once**, using that recorded geometry. On success, journal
   `success:legs_replaced` (§9) and continue the scan normally — the position now
   participates in the ordinary position-open check (§5) with legs resting as usual.
3. **If re-placement fails, or no matching `hourly_scans` row can be found** (an
   unrecoverable-provenance case — geometry to re-place against is unknown), **fail toward
   protection**: cancel any partial/rejected leg remnants and verify the cancel (the same
   verified-cancel pattern used for the orphan-leg hazard below), then market-close the
   position immediately. Journal `error:naked_position_flattened` (§9) and send a
   notification (extending `notifications.ts`'s existing pattern — reusing `notifyBrokerError`
   or adding a dedicated helper is Batch 2's call).
4. This check runs **before** §5's position-open / new-entry check on every scan, so a
   naked position is always re-legged or flattened before any new-entry decision is
   considered — and, since §5's kill-switch-flag gate is itself part of that position-open /
   new-entry check, this reconciliation contract (including the naked-position rule) also
   runs **before** §5's kill-switch-flag gate (nit, round 2 — the two "before the
   position-open check" statements at §5 and here left this relative order unstated; fixed
   now so the read is unambiguous rather than merely non-divergent). The same "reconcile
   before deciding" ordering the contract above already
   establishes for ordinary exit-leg fills.

**Session-close exit rule — decided (lead's D2 on N3): flatten at session end.** No
overnight holding for v1. Rationale (lead's D2): the operator's own framing is "short-living
contracts"; intraday-only (a) maximizes kill-switch coverage, since its cron window is
13-21 UTC and does not run overnight, (b) eliminates gap risk, and (c) eliminates overnight
short-borrow cost/availability risk entirely.

**Mechanic — decided (must-fix round 1 finding 4): the last in-session scan flattens; no
dedicated near-close check.** A separate near-close check would be a second cron job or a
second in-function schedule, contradicting §4's single-cron design (one `getClock()`-gated
scan per firing) — that alternative is rejected outright, not left open. Instead, every scan
already calls `getClock()` (§4's market-open gate); the same response's `next_close` field is
reused: if **`next_close − now ≤ 1 hour`** (the scan cadence itself — i.e., no further
`hourly-check` scan will run before the session ends), this scan **is** the flatten scan.

**`[to verify]` — Alpaca's `/v2/clock` response shape (must-fix round 2 finding 1).** Today's
shared `getClock()` helper only parses `is_open` (`_shared/alpaca.ts:93-95` returns just
`{ isOpen }`); a repo-wide grep finds no other evidence for `timestamp`/`next_open`/
`next_close` on this endpoint. That a `next_close` field exists and is populated on every
`/v2/clock` response is therefore **asserted, not verified against a live response** — the
same class of unlabelled Alpaca API claim must-fix round 1 finding 6 corrected elsewhere in
this spec (§7's shortability fields). **Required verification step:** Batch 2 must capture a
real `/v2/clock` response (paper account) when extending `getClock()` with the additive
`nextClose` field this mechanic needs — they must touch this helper anyway, so the capture
rides along with the code change, not a separate step. **Fail-closed fallback (non-silent by
construction):** a missing or unparseable `next_close` value must be a **hard error**, routed
through the same `requireNumber` boundary (`_shared/num.ts`) every other JSON→number Alpaca
field crosses in this spec — the scan throws and refuses to proceed, journaled as an
`error:${err.name}` outcome (§9). It must **never** silently evaluate the
`next_close − now ≤ 1 hour` comparison as false: a permanently-false comparison is exactly
the failure mode that would hold positions overnight with no error anywhere, defeating N3's
intraday-only decision and the kill-switch-coverage rationale below with no visible signal
that anything is wrong. This is the sixth `[to verify]` item in this spec (see the updated
count in §7's shortability discussion).

**Implementation note:** existing callers (`daily-check`, `kill-switch`) are unaffected by
the additive `nextClose` field since they only destructure `isOpen`. Using the broker's own
clock rather than a hardcoded UTC time means no DST branching is needed in code — the same
principle §4 already applies to the market-open gate. **Both DST close times are confirmed
to fall inside the `13-21 UTC` cron window:** US market close is 16:00 ET year-round; in EDT
(UTC−4) that is **20:00 UTC**, and in EST (UTC−5) that is **21:00 UTC** — both within
`13-21 UTC`.

**The flatten scan does not open new entries — flatten-only.** `decideHourly` still runs and
the bar is still journaled (§9's "one row per scan including skips") so no diagnostic data is
lost, but any `LONG`/`SHORT` action this scan produces is downgraded to
`skipped:session_close_flatten_only` (§9) rather than placed. Rationale: a fresh entry with
effectively no time remaining before the forced close cannot develop, and opening one would
immediately re-trigger the same cancel-legs-then-close sequence this rule exists to run
exactly once. Order of operations on the flatten scan: (1) run the reconciliation contract as
normal, including the position-without-legs rule above; (2) if a position remains open,
cancel the resting bracket/OCO legs and verify the cancel, then market-close the position;
(3) journal the closure as `hourly_session_close_exit` (§9); (4) do not evaluate a new entry
this scan, regardless of what `decideHourly` returned.

**Orphan-leg hazard — must be designed for, not just noted.** Closing a bracketed position
outside its own bracket (a session-close flatten, a kill-switch fire, or a panic action)
leaves the resting OCO legs live at the broker. If not cancelled, a stale leg can fire
*after* the position is already flat, opening an **unintended reverse position** (e.g. the
stop-loss SELL leg fires after the position was already manually closed, creating a fresh
short). **Requirement:** any code path that closes a bracketed position outside its own
bracket resolution — session-close flatten, kill-switch, panic — must cancel the resting
legs and **verify the cancel** (the existing `cancelAllOrders` verified-cancel pattern,
`alpaca.ts:243-259`) *before* considering the position closed.

**v2 trailing-stop variant — documented, not built.** A trailing-stop exit (ratchet the stop
as price moves favorably, instead of the fixed R=2 target) is deferred to a v2 spec
revision. Activation criteria: only after the fixed-R model has a full review cycle's worth
of data (§11, N5) showing the fixed target is being hit meaningfully often (i.e. there is
something to trail), and only via a version bump (new spec + new ADR), never as an in-flight
change.

---

## §8 Safety stack

**This section leads with the two safety findings from the sub-plan's repo read, as
requirements for the Batch 2 short-side safety-stack retrofit package (N7) — before the
paper-only guard, because these are the two places the *existing* live-trading-path code is
already wrong for a bot that can hold a short.**

**Hard sequencing requirement (must-fix round 1 finding 5).** The short-side safety-stack
retrofit package **MUST be merged and deployed before `hourly-check` can place any trade —
at minimum, before any `SHORT` entry is possible.** §14's "two packages, reviewed
separately" is not merely a review-organization note: without this ordering enforced as a
hard precondition, the feature package could deploy while the retrofit is unmerged, and the
bot would trade into exactly the unprotected-short window §8.1 documents (kill-switch exits
`success:no_position` on a short; `liquidate`/`panic` cannot cover it). Batch 3's rollout
(§14) may not turn the `hourly-check` cron on until the retrofit package has already shipped.

### 8.1 Finding: the kill-switch is structurally blind to shorts today

- `getPosition` returns Alpaca's qty via `Math.trunc` (`supabase/functions/_shared/alpaca.ts:122`)
  — **negative** for a short position. `kill-switch/logic.ts:101-105` treats `qty <= 0` as
  "no position" and exits `success:no_position`. **A short position held by this bot would be
  entirely unprotected by the kill-switch as it exists today.**
- `liquidate` returns `null` when `qty <= 0` (`alpaca.ts:236-241`) — it **cannot cover a
  short** (covering a short is a BUY, not the SELL `liquidate` always issues).
- **Requirement for the retrofit package:** `getPosition`/a new short-aware position read
  must distinguish "no position" (`qty === 0`) from "short position" (`qty < 0`); a
  short-aware close/cover helper must issue a BUY for the covering quantity.
- **Short drawdown semantics are the mirror image, not a sign flip on the existing
  formula.** For a short, adverse excursion is a **rise** in price, so the reference extreme
  is the rolling **low** (not high) plus the last trade — the mirror of
  `kill-switch/logic.ts:148-167`. The implausibility guard
  (`refHigh / lastPrice > 2` at `logic.ts:156`) must mirror as its reciprocal for a short
  (`lastPrice / refLow > 2`, or equivalently checked against the same 2x bound in the
  opposite direction).
- **The dual-breach quote confirmation must flip sides.** `logic.ts:202-206`'s own comment
  states *"bid is the realizable sale price, so it confirms a down-breach"* — covering a
  short executes at the **ask**, so a short's adverse breach must be confirmed against the
  ask, not the bid. The existing fail-toward-protection behavior on a quote outage (fire on
  trade price alone rather than disarm) is preserved for both sides.
- **On a fire, this retrofit writes the `bot_config` flag `hourly-check` reads.** Per §5's
  "Post-kill-switch-fire semantics," a fire for this bot's position sets
  `hourly_kill_switch_active = true`, `hourly_kill_switch_side` to the side that was
  stopped out, and `hourly_kill_switch_fired_at` — `hourly-check` (the feature package) owns
  reading, gating on, and clearing these keys; the retrofit package owns only writing them
  on a fire. Same one-writer/one-reader split as `bar_claims` (§8.4, §9, §14).

### 8.2 Finding: `panic`'s "unchanged" framing is factually wrong as written; corrected here

`panic/logic.ts:75` calls `alpaca.liquidate(config.botTicker)` — this is **long-only** (a
SELL-only helper, per §8.1) **and keyed to `config.botTicker`**, which today is `UPRO`
(`config.ts:60`, `.env.example`). After the switch to an hourly SPY long/short bot, **panic
as it exists today cannot flatten this bot's short position, and cannot flatten a SPY
position at all** (it liquidates whatever `BOT_TICKER` is configured to, and only if that
position is long).

**Correction:** panic's *contract* — actions (`pause`/`resume`/`cancel-orders`/`liquidate`),
token auth, audit-row-before-broker-call, 500-on-failure — is unchanged and remains the
deterministic kill button described in CLAUDE.md's Architectural invariants. panic's
*implementation* needs (a) a side-aware close (BUY to cover a short, SELL to close a long,
per §8.1's short-aware helper) and (b) a symbol that matches the live bot (SPY, once this
bot is the deployed one) or the deterministic kill button is broken for exactly the position
it exists to flatten. **This is an invariant-level correction, not a nicety** — the panic
Edge Function is named in CLAUDE.md's Architectural invariants as "the deterministic kill
button," and a kill button that cannot close half the position space it is meant to protect
against is a broken invariant, not a missing feature.

### 8.3 Paper-only guard — three layers, all fail-closed

- **Layer A (per-call, no network, precedent-matching).** A `checkPaperOnly(op)` function
  beside the existing `checkGuard`, enabled per client
  (`createAlpacaClient({ paperOnly: true })`, so the existing `daily-check`/`kill-switch`/
  `panic` clients are untouched — only the new bot's client opts in), asserting
  `getAlpacaConfig().paper === true` **and** `cfg.tradingBaseUrl ===
  "https://paper-api.alpaca.markets"`. The URL check is load-bearing: it is literally the
  host the client is about to call (`config.ts:103`), so it cannot be defeated by a
  mis-set boolean alone. Throws a named error class so the audit outcome is deterministic
  (`error:${err.name}`, the documented pattern at `alpaca.ts:8-12`).
- **Layer B (broker-confirmed, once per run).** Read `/v2/account` at pipeline start and
  require a paper marker present in the response. **`[to verify]` — do not hardcode a field
  from memory.** Batch 2 must capture a real paper-account `/v2/account` response and pin
  the exact marker there. The commonly-cited marker is an `account_number` prefixed `PA` —
  **marked `[to verify]`, not asserted.** If no marker can be confirmed, the fallback is to
  refuse to trade (fail-closed) rather than proceed on an unverified assumption.
- **Layer C.** `CLAUDE_AGENT_NO_BROKER` unchanged — the existing mechanical guard against
  agent-spawned test/dev sessions reaching a live broker call, ported #168, restated in
  CLAUDE.md's Architectural invariants.
- **Early deterministic gate.** `hourly-check/logic.ts` produces a deterministic outcome
  before any side effect if any paper-only layer fails — the same shape as the existing
  operational-pause gate (`daily-check/logic.ts:96-100`).

### 8.4 Claim-key hazard

The existing `trade_claims` primary key is `(script_name, trade_date)` — a `date` column
(`supabase/migrations/0008_trade_claims.sql`). `kill-switch/logic.ts:240-244`'s own comment
already flags "fail-toward-no-protection" for **one fire per trading day** on the incumbent
bot; with this bot placing up to 3 entries/day (§5, N4) plus session-close flattens, that
date-granularity claim is materially worse, and an hourly entry claim **cannot be expressed
at date granularity at all** (two different hourly decisions on the same day would collide
on the same claim key). **Requirement:** a new **bar-level claim table** (e.g.
`bar_claims(script_name, bar_ts)`, same first-INSERT-wins / 23505-conflict-backs-off
pattern) rather than altering the existing `trade_claims` PK — the incumbent bot (while its
cron remains active per P1's non-goals) keeps using the existing date-keyed claim unchanged.
**Ownership (must-fix round 1 finding 9, resolved):** the `bar_claims` table and its
migration belong to the short-side safety-stack retrofit package, per N7's own scoping —
`hourly-check` (feature package) is a consumer only (it inserts a claim row per bar and reads
back `skipped:duplicate_run` on conflict) and does not own the schema. §14 states this
explicitly as part of the hard sequencing requirement (finding 5): `hourly-check` cannot
correctly claim a bar until the retrofit's migration exists.

---

## §9 Persistence

**New migrations** — next free numbers are **0011** and **0012** (`0001`–`0010` already
exist, `supabase/migrations/`). **Rule (should-fix round 2 finding 2): the retrofit package's
migration always takes the lower next-free number, because §14's hard sequencing requires
the retrofit to deploy first** — `supabase db push` applies migrations in numeric order, so
a higher-numbered retrofit migration landing after a lower-numbered feature migration would
be an out-of-order push. Concretely: `bar_claims` (retrofit) is **0011**; `hourly_scans`
(feature, below) is **0012**.

### `hourly_scans` — one row per scan, including skips

| Column | Type | Notes |
|---|---|---|
| `symbol` | `text` | part of PK |
| `bar_ts` | `timestamptz` | the completed bar's timestamp; part of PK |
| `decision` | `text check (decision in ('LONG','SHORT','SKIP'))` | |
| `skip_reason` | `text` | null unless `decision = 'SKIP'` |
| `detectors_fired` | `jsonb` | array of detector names that fired this bar |
| `context_mode` | `text` | the config value active at scan time |
| `entry_ref_price` | `numeric(14,4)` | null unless computed |
| `stop_price` | `numeric(14,4)` | null unless computed |
| `target_price` | `numeric(14,4)` | null unless computed |
| `risk_per_share` | `numeric(14,4)` | `|entry_ref_price − stop_price|`, null unless computed |
| `equity_usd` | `numeric(14,4)` | account equity read this scan |
| `qty` | `integer` | 0 on SKIP/size-too-small |
| `entry_order_id` | `text` | broker order id, null on SKIP |
| `created_at` | `timestamptz not null default now()` | |

Primary key `(symbol, bar_ts)` — a re-run on the same bar upserts idempotently, the same
`regime_state` date-PK + `onConflict` pattern the incumbent bot already uses. Money columns
are `numeric`, per `0005_numeric_money.sql`'s decimal-fidelity precedent, read back through a
`coerce*Row`-style helper — PostgREST returns numerics as strings
(`supabase/functions/_shared/db.ts`'s `coerceRegimeRow`/`coerceTradeRow` precedent).

**"Null unless computed," not "null on SKIP" (should-fix round 1 finding 14).** The prior
draft's "null on SKIP" was wrong: `skipped:size_too_small` and `skipped:geometry_invalid`
(§6) both compute `entry_ref_price`/`stop_price`/`target_price`/`risk_per_share` before
deciding to skip, and those sizing inputs are exactly the values worth keeping for the
weekly review (§11) to explain *why* a bar was skipped. The four sizing columns are null
only for decisions where no geometry was ever computed at all (e.g. `skipped:signal_conflict`,
`skipped:market_closed`) — "null unless computed" is the accurate rule.

RLS enabled, no policies — the standing deny-all pattern
(`0001_init.sql:61-66`, `0009_equity_snapshots.sql`, `0010_notification_outbox.sql`).

### `trades` — reused, with an extended `reason` check

Fills reuse the existing `trades` table. The `reason` CHECK constraint is inline and
**unnamed** in `0001_init.sql:24-25` (`check (reason in ('regime_flip_long',
'regime_flip_cash','kill_switch','panic_cli'))`), so extending it means the migration must
first find (Postgres auto-names it, typically `trades_reason_check`) and drop the
auto-generated constraint name, then re-add it with the new values (`hourly_long_entry`,
`hourly_short_entry`, `hourly_bracket_exit`, `hourly_session_close_exit`,
`hourly_kill_switch`, plus whatever the short-side retrofit needs). **Flagged as a detail to
verify at implementation** — the exact auto-generated name should be confirmed against the
live schema (`\d trades` or `information_schema.check_constraints`) before the `alter table
... drop constraint` statement is written, rather than assumed.

### `audit_log` — unchanged contract, new outcome vocabulary

`audit_log` keeps its existing one-row-per-invocation contract (open before any side effect,
close in a `finally` with a deterministic outcome). New `hourly-check` outcomes, all
following the existing `success` / `success:*` / `skipped:*` / `error:*` vocabulary:

- `success` — a decision was made and (if LONG/SHORT) an order placed and journaled.
- `success:no_action` — decision was SKIP for a reason other than a hard skip (e.g. no
  detector fired at all).
- `success:legs_replaced` — the position-without-legs rule (§7, finding 3) re-placed a
  missing bracket/OCO pair successfully.
- `success:auto_paused` — the −15% equity floor (§11, finding 11) fired and set
  `bot_config.paused = true` this scan.
- `skipped:market_closed`, `skipped:trading_paused` (mirrors `daily-check`'s existing gates).
- `skipped:stale_data`, `skipped:partial_bar` (§4; precedence between the two is fixed,
  finding 1).
- `skipped:signal_conflict` (§5).
- `skipped:size_too_small` (§6).
- `skipped:geometry_invalid` (§6, finding 12).
- `skipped:not_shortable` (§7).
- `skipped:shorts_disabled` (§7, finding 6 — the shortability fields were unconfirmable and
  `HOURLY_SHORTS_ENABLED` was flipped off, distinct from `skipped:not_shortable`'s
  confirmed-not-shortable case).
- `skipped:position_open` (§5's at-most-one-position rule blocked a new entry).
- `skipped:max_entries_reached` (§5, N4's 3/day cap).
- `skipped:kill_switch_active` (§5, §8.1, finding 2 — the post-fire flag blocked this
  scan's entry).
- `skipped:session_close_flatten_only` (§7, finding 4 — the flatten scan downgraded what
  would otherwise have been a LONG/SHORT entry).
- `skipped:duplicate_run` (the new bar-level claim, §8.4, conflicted).
- `error:AlpacaError`, `error:OrderTimeoutError`, `error:OrderRejectedError`,
  `error:BrokerCallBlockedError`, `error:PaperGuardFailed` (§8.3's new named error),
  `error:SubPennyPriceError` (#494 — an order leg price is not a whole-cent multiple, or
  does not serialize as a plain decimal; the class extends `AlpacaError`, so this outcome
  alerts), `error:naked_position_flattened` (§7, finding 3 — the position-without-legs rule
  could not re-place legs and flattened instead) — the existing `error:${err.name}` pattern.

### New claim table — `bar_claims`

Per §8.4: `bar_claims(script_name text, bar_ts timestamptz, claimed_at timestamptz not null
default now(), primary key (script_name, bar_ts))`, RLS deny-all, no policies — structurally
identical to `trade_claims` (`0008_trade_claims.sql`) but keyed on the bar timestamp instead
of the trade date.

### Rejected alternative

Stuffing per-scan detail into `audit_log.notes` was considered and rejected: CLAUDE.md keeps
`audit_log` "a clean record of trading actions" (the same reasoning that keeps `status`'s
reads out of it), and the weekly review (§11) needs typed, queryable columns (per-detector
firing rates, decision distributions) that a free-text `notes` field cannot support without
ad-hoc parsing.

**`regime_state` is not extended.** Its CHECK constraints admit only `LONG`/`CASH`
(`0001_init.sql:8-9`) and it belongs to the retired 200-DMA bot (deprecated by P1, #465);
extending it would couple this bot's persistence to a table the retired bot still writes
during its own decommission window.

---

## §10 Config settings

Following `.claude/skills/add-or-extend-agent/SKILL.md` and `config.ts`'s existing
throw-on-out-of-range pattern (`supabase/functions/_shared/config.ts:39-71`), each setting
below is read + range-validated at function start, with a default and, where the change is
risk-relevant, an opt-in/default-OFF-style safe default (per the skill's rule 7):

| Setting | Default | Valid range | Notes |
|---|---|---|---|
| `HOURLY_BOT_TICKER` | `SPY` | non-empty string | the traded symbol; separate from `BOT_TICKER` (UPRO, the retired bot) so both can coexist during P1's soak-then-decommission window |
| `SIZING_RISK_PCT` | `0.01` | `(0, 0.05]` | risk budget per trade as a fraction of equity |
| `SIZING_NOTIONAL_CAP_PCT` | `0.10` | `(0, 1.0]` | notional cap per position as a fraction of equity |
| `HOURLY_BRACKET_R_MULTIPLE` | `2` | fixed at `2` for v1 (validated `=== 2`; a change requires a spec revision, §7) | |
| `HOURLY_STOP_BUFFER_PCT` | `0.05` | `(0, 0.5]` | frozen stop-buffer fraction of the signal bar's range, §7 (must-fix round 1 finding 7) |
| `HOURLY_MIN_STOP_DISTANCE` | `0.05` (USD) | `> 0` | minimum `|entryRef − stopPrice|`; below this or on the wrong side ⇒ `skipped:geometry_invalid`, §6 (should-fix round 1 finding 12) |
| `HOURLY_MAX_ENTRIES_PER_DAY` | `3` | `[1, 10]` | N4 cap |
| `HOURLY_STALENESS_TOLERANCE_MIN` | `10` | `[1, 60]` | minutes past a completed bar's end before the scan treats it as stale; coupled to the cron minute pin (§4, finding 1 — `cronMinuteOffset + expectedFeedLatencyMin` must stay under this value) |
| `HOURLY_CONTEXT_MODE` | `none` | `{"none","reversal","continuation"}` | §5; masked warm-up applies in all three |
| `HOURLY_SHORTS_ENABLED` | `false` **[CORRECTED #493]** | boolean | fail-closed override, §7 finding 6 — as-shipped this defaulted to `true`, which armed shorts whenever the secret was unset; #493 flipped the default so absent means off and enabling needs an explicit `"true"`. A present but unparseable value still throws |
| `HOURLY_BOT_PAPER_ONLY` | `true` | must be `true`; throws if unset or `false` for this bot's client (§8.3 Layer A) | the mechanical paper-only gate — not a normal tunable, listed here so it is not missed |

`.env.example` gains a new commented block mirroring the existing `--- Bot strategy
parameters ---` section; `README.md`'s Settings section gains a row per setting, per the
skill's checklist items 5-6.

---

## §11 Weekly review loop

Precedent: `backtest/weekly_review.py` is a **deterministic generator** with a documented
`PROPOSAL_RULE` (`backtest/weekly_review.py:67`), no network, no LLM — and its own docstring
already fixes the filing split: research reviews go to `docs/research/reviews/YYYY-Www.md`;
**live trading weeks go to `docs/trading-journal/`**
(`backtest/weekly_review.py:29-30`: *"reviews live in `docs/research/reviews/YYYY-Www.md`,
not in `docs/trading-journal/`. That directory's README explicitly excludes research
artefacts"*).

Spec a **separate**, read-only aggregator over `hourly_scans` + `trades`, rendering to
`docs/trading-journal/YYYY-Www.md` (not reusing `weekly_review.py`'s research-artefact
target directory).

**"Propose adjustments between versions," concretely:**
- At most **one** ranked proposal per week, in a fixed format.
- The proposal names the exact frozen, §-numbered parameter it would change (e.g. "§7
  `HOURLY_BRACKET_R_MULTIPLE`: 2 → 3").
- It states the statistic that triggered the rule (e.g. "target hit rate 8% over N=40
  trades, below the X% floor").
- It states the **minimum sample** the rule requires before it may fire at all — no proposal
  is generated below that sample size, so a single lucky/unlucky week cannot trigger a
  change recommendation.
- The proposal is an **input to a human-approved version bump** (a new spec revision + a
  new ADR) — it is never applied in-flight. This is #464's standing constraint, restated
  here because the review loop is exactly the mechanism that must not violate it.

**"Multiplicity-aware," concretely:** every accepted parameter change increments a recorded
trial counter (the same discipline `backtest/tested_cells.py` / #398's DSR gate applies to
research grids, cited by reference, not re-derived here); selecting the best-performing
parameter value from a set evaluated on the *same* paper-trading history, without
re-registering the selection as its own trial, is forbidden by the same reasoning that
closed the candlestick daily grids in §2 — post-hoc selection from your own results is
exactly the overfitting mode #398 exists to catch, applied to a live paper account instead
of a backtest.

**The stopping rule — defaults set by the lead's D2 on N5, flagged prominently as
operator-amendable at the spec's own merge:**

> **Review checkpoint:** at **4 weeks or 30 closed trades, whichever comes first.**
> **Hard floor:** **−15% account equity from the paper experiment's start ⇒ auto-pause (set
> `bot_config.paused = true` via the same mechanism `panic action=pause` uses) + mandatory
> review** before any further entry is permitted.
>
> **These are defaults, not final numbers.** The lead set them so this spec is complete
> end-to-end, but the operator owns the final numbers when merging this spec's PR — this
> paragraph exists specifically so that decision is visible and easy to change in one place,
> rather than buried in a config default a reviewer might not notice.

**Enforcing component, named (should-fix round 1 finding 11).** "Auto-pause" above names an
outcome, not a mechanism — a weekly document cannot enforce anything intra-week. The
enforcing component is **`hourly-check`'s own pipeline**, not the weekly review script: on
every scan, after reading equity (§6), `hourly-check` compares it to a stored experiment
baseline — a new `bot_config` key, `hourly_experiment_start_equity` (numeric, set once at
Batch 3 deploy time when the paper experiment begins, read-only thereafter for v1). If
current equity has fallen ≥15% below that baseline, the scan itself sets
`bot_config.paused = true` (the same key `panic action=pause` sets) **before** evaluating any
new entry, and journals the trigger as `success:auto_paused` (nit, round 2: pinned to §9's
vocabulary entry — the outcome is a successful pipeline run that happens to end in a pause,
not an error, so `success:auto_paused` is the only candidate name; no alternative is left
open). The weekly review script (§14, Batch 3) reports this after the fact; it does not
itself enforce the floor.

---

## §12 Proposed CLAUDE.md amendment

The following block is a draft only. It is **not authoritative** — CLAUDE.md forbids this
spec from becoming a second source of truth for the Architectural invariants — and is
applied verbatim (or as amended in review) **in Batch 2, with the code that makes it true**,
never merged as part of this docs-only package.

````
PROPOSED — applied in Batch 2, not authoritative until merged into CLAUDE.md itself.

## Architectural invariants (amendment)

- **One decision rule.** The bot trades on exactly one signal: the composite hourly
  candlestick decision `decideHourly` (`supabase/functions/_shared/hourly_signal.ts` or
  equivalent — Batch 2 names the module), sitting on P3's frozen 14-detector registry
  (`_shared/candlestick.ts`), with its tie-break and cooldown rules frozen together as a
  single configuration. Do not add a second decision rule (a sentiment overlay, a second
  scanner, a parallel strategy) without a fresh brainstorm and design spec — the
  rules-engine pivot exists precisely because the LLM-driven multi-signal v1.14 bot was
  indistinguishable from a coin flip on 5y data, and a second live rule reintroduces the
  same audit problem even without an LLM in the loop. `decideHourly` is a single pure
  function of its bar history and frozen config, so the **signal** stays fully
  bar-reproducible; whether a signal becomes an entry additionally depends on
  broker/journal state (open position, cooldown, kill-switch flag, bar claim), so **entry
  gating is state-dependent and audit-log-reproducible, not SPY-history-reproducible alone**
  (§13 narrows the original invariant text's reproducibility clause on exactly this point).
- **No LLM in the trading path.** Unchanged in intent. The `hourly-check`, `kill-switch`,
  and `panic` Edge Functions import no model SDK and instantiate no agent. (Restated
  verbatim from the pre-amendment text; `daily-check` is removed from this list once P1's
  deprecation completes its decommission window.)
- **Mechanical paper-only guard.** [NEW] The hourly bot's Alpaca client MUST refuse to place
  any order unless (a) `getAlpacaConfig().paper === true`, (b) the trading base URL is
  `https://paper-api.alpaca.markets`, and (c) the broker's own `/v2/account` response
  carries a confirmed paper-account marker. All three checks are enforced in code, not
  procedure; a failure throws before any broker call. See
  `docs/superpowers/specs/2026-07-27-hourly-bot-design.md` §8.
- **Operational kill switch.** Unchanged in intent — `bot_config.paused=true` halts new
  entries for every bot sharing this flag.
- **Panic is the deterministic kill button.** Unchanged contract (actions, token auth,
  audit-before-broker-call, 500-on-failure). [CORRECTED] Its implementation is side-aware
  (closes a short via BUY, a long via SELL) and targets the symbol of whichever bot is
  currently live, not a hardcoded long-only `BOT_TICKER` liquidate. See §8.2 of the design
  spec cited above for the finding this corrects.
- **Engineer subagents must never execute against the live broker.** Unchanged mechanism
  (`CLAUDE_AGENT_NO_BROKER`, `checkGuard()` on every mutating Alpaca helper including the new
  bracket-order and short-side helpers this bot adds).

## Architecture / Daily flow / Intraday kill-switch / Key constraints (deprecation marker)

The sections below describing `daily-check`'s post-open cadence and the SPY-close-vs-200-DMA
signal are marked **deprecated — superseded by the hourly candlestick bot** as of the Batch
2 merge. They are kept in this file as record, per this repo's own historical-layering
convention (`docs/architecture/2026-07-05-codebase-map.md`'s documented practice of keeping
retired architecture "as record rather than removed"), not deleted — a future reader can
still reconstruct exactly what the bot did before this change.

## Commands / Testing conventions (additions)

- `deno test --allow-env --allow-net supabase/functions/hourly-check/logic.test.ts` — the new
  function's test file, following the existing per-function test convention.
- The Testing conventions section's broker-mocking rule extends verbatim to the new guarded
  `placeBracketOrder` and any short-side helper: all Alpaca calls MUST be mocked in any test
  exercising a path that would reach them.
````

---

## §13 Invariant analysis

Mirrors the giveback spec's §10 structure
(`docs/superpowers/specs/2026-07-24-giveback-exit-design.md` §10), argued explicitly rather
than assumed, because §5's N1 resolution is the one place this spec **redefines** an
invariant's meaning rather than merely satisfying it as written.

**One decision rule (invariant #1).** A 14-detector registry could be read as 14 rules.
This spec adopts the lead-ratified position (N1(a)): **the rule is the composite pure
function `decideHourly`** — one function, one frozen configuration (registry + tie-break +
cooldown + cap, all frozen together, no parameter changeable in-flight per §11's
never-in-flight constraint). This is structurally identical to how `computeTargetState`
is "one rule" despite internally comparing two numbers (close vs SMA) — the invariant
protects against **parallel, independently-evolving decision paths** (the v1.14 failure
mode: sentiment overlay + technical rule + LLM narration, each capable of overriding the
others unpredictably), not against internal complexity in a single deterministic function.
`decideHourly` has exactly one output per bar, is fully determined by its inputs, and is
mechanically invariant-scanned the same way `regime.ts` is — it satisfies the invariant by
the same argument that qualified `computeTargetState`, extended to a larger but still
single, frozen, deterministic function.

**Reproducibility clause is narrowed, stated explicitly (should-fix round 1 finding 13).**
The original invariant text also says every decision is "reproducible from the SPY history
alone." For this bot that clause narrows and must not be allowed to silently vanish: the
**pure signal** (`decideHourly(bars, cfg)`) remains fully bar-reproducible — same bars and
config in, same `{action, reason, detectorsFired}` out, with no hidden state. But whether a
signal **becomes an entry** now additionally depends on state outside the bar history: the
broker-sourced open position (§5), the journal-derived cooldown/day-cap (§5), the
post-kill-switch-fire flag and side (§5, §8.1), and the bar-level claim (§8.4). None of that
state is itself non-deterministic or hidden — it is all recorded in `hourly_scans` /
`bot_config` / `bar_claims` and could in principle be replayed — but it is not *purely*
"the SPY history," and pretending otherwise would misstate what this invariant now
guarantees. The correct restatement: the **signal** is bar-reproducible; **entry gating**
is state-dependent and audit-log-reproducible, not SPY-history-reproducible alone.

**No LLM in the trading path (invariant #2).** No model SDK is imported by any module this
spec describes; `decideHourly`, `scanCandles`, the sizing math, and the bracket order
placement are all deterministic TypeScript. Unaffected.

**Operational kill switch (invariant #3).** `bot_config.paused` continues to gate new
entries for this bot exactly as it does for `daily-check` today; §8's paper-only guard and
the panic correction (§8.2) strengthen, not weaken, this invariant's practical force for a
bot that can hold either side of a position.

**Panic as the deterministic kill button (invariant #4).** §8.2 states plainly that panic's
*current implementation* already fails this invariant for the position shape this bot
introduces (long-only, `BOT_TICKER`-keyed) — this is a **correction to a factual claim**,
not a weakening of the invariant text. The invariant itself (deterministic, token-authed,
audit-before-broker-call, 500-on-failure) is preserved; the retrofit (its own Batch 2
package per N7) brings the implementation back into compliance with an invariant the code
currently violates for this bot's position shape.

**Engineer subagent broker guard (invariant #5).** Unaffected — `CLAUDE_AGENT_NO_BROKER` and
`checkGuard()` extend automatically to any new guarded helper (`placeBracketOrder`, the
short-side close helper) by construction, since they are new call sites of the same guard
function, not a new mechanism.

**Satisfies all CLAUDE.md Architectural invariants; any violation is a must-fix review
finding** — the standing acceptance criterion, restated per CLAUDE.md's instruction that
every code-touching work package carry it.

---

## §14 Rollout

1. **Batch 1 (this batch).** P1 (#465) deprecates the UPRO bot's *entries* (kill-switch keeps
   guarding until flat). P2 (this spec + its ADR). P3 (#467) ports the 14 detectors + context
   logic to `_shared/candlestick.ts` with golden parity. P4 (#468) runs the forex research
   leg in parallel (signal v2 track, not this bot).
2. **Batch 2 — build, against this spec.** Two packages, reviewed separately per N7, **and
   sequenced (must-fix round 1 finding 5): the retrofit package MUST be merged and deployed
   before `hourly-check` can place any trade — at minimum, before any `SHORT` entry is
   possible.** The feature package may be developed and reviewed in parallel, but its cron
   is not turned on (Batch 3) until the retrofit has shipped.
   - **The feature build:** `hourly-check/{logic,handler,index}.ts`, `_shared/hourly_signal.ts`
     (or equivalent module name; consumes P3's `scanCandles`), `_shared/alpaca.ts` additions
     (`placeBracketOrder`, `checkPaperOnly`, short-side position/close helpers per §8.1),
     `_shared/config.ts` additions (§10), `0012_hourly_scans.sql` (the `hourly_scans` table
     and the `trades.reason` check extension only — **not** `bar_claims`, see below), a new
     cron migration for the `hourly-check` job (§4). The CLAUDE.md amendment (§12) lands with
     this package's PR, not before.
   - **The short-side safety-stack retrofit (own package, per N7):** short-aware
     `getPosition`/close in `_shared/alpaca.ts`, the short-aware `kill-switch/logic.ts`
     drawdown mirror (§8.1, including writing the `hourly_kill_switch_active` /
     `hourly_kill_switch_side` / `hourly_kill_switch_fired_at` `bot_config` keys per §5's
     post-fire semantics), `panic/logic.ts`'s side-aware + symbol-aware fix (§8.2), **and the
     `bar_claims` migration (must-fix round 1 finding 9 — one owner, resolved: the retrofit
     package owns the `bar_claims` table and its migration, since it is the safety-relevant
     claim key the sub-plan's N7 already scoped to this package; `hourly-check` in the
     feature package consumes it (writes claim rows, reads for `skipped:duplicate_run`) but
     does not own its schema**. This is the same reconciliation the hard-sequencing
     requirement above already implies: `hourly-check` cannot correctly claim a bar, or gate
     on the kill-switch flag, until the retrofit's migration and `bot_config` keys exist —
     one more reason the ordering in finding 5 is load-bearing, not just a review-hygiene
     preference. Reviewed as a safety change to *existing* live-path code, not buried inside
     the feature build's review.
3. **Batch 3 — deploy + first paper trades.** Deploy the retrofit package first (per finding
   5); only then deploy the feature package and turn the `hourly-check` cron on. Confirm the
   §4 bar-alignment `[to verify]` item on a live RTH session before the first scan that could
   place an order. Run the weekly review loop (§11) starting from week 1 via a new,
   dedicated aggregator script (must-fix round 1 finding 10 — assigned here, to Batch 3, not
   left unowned): a read-only script over `hourly_scans` + `trades` rendering to
   `docs/trading-journal/YYYY-Www.md` (§11), run manually by the operator each week — **not**
   a cron'd Edge Function (no auth surface is needed for a read-only, operator-triggered
   report) and **not** a reuse of `backtest/weekly_review.py` (that script's target directory
   and inputs are research-artefact-scoped, §11). Language/location (a `scripts/*.ts` run via
   `deno run`, matching `scripts/status.sh`'s standalone-tool precedent, or a Python script
   alongside `backtest/`) is Batch 3's call. The exact `PROPOSAL_RULE` trigger statistics
   (e.g. the target-hit-rate floor) and the trial-counter's storage location are **deferred
   to Batch 3's implementation, with the operator as owner at that time** — same
   operator-amendable-default pattern already used for N5's stopping rule (§11) — subject to
   the two constraints §11 already fixes: at most one proposal/week, and a stated minimum
   sample before any proposal may fire. The trial counter is stored as a `bot_config` key
   (e.g. `hourly_param_trial_count`), incremented on every accepted version bump, reusing the
   existing key/value store rather than a new migration.
4. **Stopping rule (§11, N5).** The 4-week/30-trade checkpoint, or the −15%-equity hard
   floor, whichever comes first, triggers a mandatory human review before any further entry.
   The floor is enforced mechanically, not just documented in the weekly review — see §11's
   enforcing-component note (must-fix round 1 finding 11).

**Batch 2 file-set self-test (per the sub-plan's §D verification step (e)) — an architect
should be able to sub-plan Batch 2 from this spec alone.** The implied file set:

- `supabase/functions/_shared/candlestick.ts` — consumed, not built here (P3, #467).
- `supabase/functions/_shared/alpaca.ts` — extended: `placeBracketOrder`, `checkPaperOnly`,
  short-side position read + close (safety package).
- `supabase/functions/_shared/config.ts` — extended per §10.
- `supabase/functions/hourly-check/{logic.ts,handler.ts,index.ts}` — new function, following
  the `daily-check`/`kill-switch` three-file shape.
- `supabase/migrations/0011_bar_claims.sql` (retrofit package: `bar_claims` only),
  `0012_hourly_scans.sql` (feature package: `hourly_scans` + `trades.reason` extension +
  the `hourly-check` cron) — **the retrofit's migration takes the lower next-free number**
  (should-fix round 2 finding 2), matching the required deploy order: `supabase db push`
  applies migrations in numeric order, so `0011` (retrofit) must exist before `0012`
  (feature) is pushed, which is also exactly the order finding 5 already requires operationally.
  Exact numbers are confirmed against the live migrations directory at implementation time,
  but the *lower-number-deploys-first* rule is fixed here so the numbering can never again
  contradict the deploy order.
- `supabase/functions/kill-switch/logic.ts` — short-aware retrofit (safety package).
- `supabase/functions/panic/logic.ts` — side-aware + symbol-aware fix (safety package).
- A new weekly-review aggregator script (Batch 3, per finding 10 above) — not part of
  Batch 2, listed here so its absence from Batch 2's file set is not mistaken for an
  oversight.
- Each of the above has enough detail above (§4-§9) to build without inventing a new
  decision the spec should have made.

---

## §15 Acceptance criteria

- Satisfies all CLAUDE.md Architectural invariants; any violation is a must-fix review
  finding.
- Spec answers every question Batch 2's developer would otherwise have to invent — an
  architect could sub-plan the Batch 2 build from this spec alone (§14 self-test).
- ADR (`docs/decisions/2026-07-27-hourly-candlestick-signal.md`) cross-references P1's
  deprecation ADR and the batch #464 decision log, and explicitly ratifies N1(a) (the
  composite-pure-function reading of "one decision rule").
- CLAUDE.md amendment text is drafted in §12, clearly fenced and labelled PROPOSED, and is
  **not** applied by this package.
- All safety-stack invariants are preserved or strengthened: §8 leads with the two safety
  findings (kill-switch blind to shorts; panic long-only + `BOT_TICKER`-keyed) as
  requirements for a Batch 2 retrofit package, and the paper-only guard (§8.3) is specified
  as mechanical (code-enforced), never procedural.
- No new backtest claims are made; §2 cites the existing research record only.
- No code, no migration, no CLAUDE.md edit ships in this package.
