# Hourly bracket-geometry, cadence, and sizing study — pre-registration (6 cells)

**Question:** Across the frozen `decideHourly` composite signal, which of a 6-cell
`R ∈ {1.0, 1.5, 2.0} × cadence ∈ {60m, 30m}` bracket-geometry grid produces the best
exit-distribution/expectancy profile on SPY intraday bars, how does 30m compare to the live
60m cadence, how much of any edge is winner-truncation from the session-close flatten rule,
and how does the live `SIZING_NOTIONAL_CAP_PCT` sizing cap behave across a sensitivity sweep?

**Issue:** #571 (steps 2-5 of #566's batch, part of batch #570). **Predecessors:** #566's
architect SUB_PLAN (the frozen design), `docs/research/2026-08-13-hourly-geometry-cadence-sizing-data-feasibility.md`
(§1 — the design-authority correction on `adjustment=all`; this doc's grid/conventions are
restated from there, not re-derived), `docs/research/2026-08-02-sizing-rule-live-vs-backtest.md`
(#499 — the sizing-invariant-ledger / equity-replay method this study reuses verbatim).
**Date:** 2026-08-13. **Author:** Claude Code session (research-only;
`CLAUDE_AGENT_NO_BROKER=1` for the whole session; no network anywhere in this package — the
input bars are already staged locally, per the section below).

---

## §0 Invariant framing

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- This study **replays** the live `decideHourly` / `computeBracketGeometry` / `computeSizing`
  exports unchanged (imported directly from `supabase/functions/_shared/hourly_signal.ts` and
  `supabase/functions/hourly-check/logic.ts`, never re-derived in Python) — it does not add a
  second decision rule, and it authorizes no live parameter, cadence, or sizing change.
  Findings feed the ~Aug 26-28 checkpoint review; any live change needs its own ADR.
- No LLM anywhere in this package. Every module lives under `backtest/`, `scripts/`, `tests/`,
  and `docs/research/` — the offline research path
  (`docs/architecture/2026-07-05-codebase-map.md`) — and none of it is imported by
  `supabase/functions/`.
- **No network anywhere in this package.** The input bars are pre-staged local CSVs (§2); no
  fetch call, no Alpaca key, is read or reachable from any module this package adds.
  `scripts/emit_hourly_decisions.ts` transitively imports `supabase/functions/_shared/alpaca.ts`
  for the `AlpacaError` class only (via `hourly-check/logic.ts`) — no client is ever
  constructed, and the mechanical `CLAUDE_AGENT_NO_BROKER` guard covers every Alpaca-touching
  helper regardless. Run under `CLAUDE_AGENT_NO_BROKER=1`.
- Engineer subagents never execute against the live broker; standing rule, unaffected by
  this package (no broker call is reachable from any module added here).

---

## §1 The frozen grid (design authority: the data-feasibility doc's §1)

**6 primary cells: `R ∈ {1.0, 1.5, 2.0} × cadence ∈ {60m, 30m}`.** Restated verbatim from the
feasibility doc's §1 (itself restated from the SUB_PLAN's Q1-Q4), not re-derived:

- Signal: `decideHourly` (composite candlestick vote, `hourlyContextMode="none"`, P3's frozen
  14-detector registry), replayed against SPY bars.
- Bars: fetched `adjustment=all` (fully split/dividend adjusted — the feasibility doc's
  correction to the SUB_PLAN's inverted "raw" recommendation; matches what the live
  `hourly-check` bot's `marketdata.getHourlyBars` actually sees), `feed=sip`.
- Geometry: `computeBracketGeometry` (stop = signal bar's own low/high ± 5% of that bar's
  range; target = entry ± R·stopDistance, both quantized to whole cents, stop rounded first).
- Sizing gate: `computeSizing` (`SIZING_RISK_PCT=0.01`, `SIZING_NOTIONAL_CAP_PCT=0.10`,
  `HOURLY_MIN_STOP_DISTANCE=0.05` — the frozen `config.ts` defaults).
- Sizing-cap **replay** (not a 7th trial): `{0.10, 0.25, 0.50, 1.00}`, applied to the same 6
  per-trade ledgers per #499's established method (per-trade R-denominated stats are
  sizing-invariant; only the dollar equity curve changes with the cap). **Registered trials =
  6**, not 6×4 — the sizing-cap axis is a replay, exactly as #499 and the SUB_PLAN's Q4 both
  established for this kind of sweep.
- Long-only: `HOURLY_SHORTS_ENABLED=false` (the live rollout value) is modeled by assumption —
  a bearish `decideHourly` fire gate-skips as `shorts_disabled`, never enters.

**Ledger family:** `family="hourly_bracket_geometry_sizing"`, `vehicle="SPY"`,
`exit_style="bracket_RxRisk_flatten"`, split by `cadence` (`"hourly"` for 60m, `"30m"`),
`n_cells=3` each (the R axis) — the exact key/shape the feasibility doc's `DATA_BLOCKED`
records already used, so this round's `PENDING` records replace those without inventing a new
key (§6 below).

---

## §2 Staged-data anchor (input provenance, never re-fetched in this package)

Per the issue body: operator-approved fetch, 2026-08-13, `feed=sip`, `adjustment=all`,
2016-01-01 → 2026-08-12, 2,738 sessions, power **DIRECTIONAL** (`n_w=10 < 13` — disclosed in
§8). Files live at `data/intraday/` (gitignored, never committed — `git ls-files data/` is
empty in every commit of this package):

| File | Rows | SHA256 |
|---|---|---|
| `SPY_1hour.csv` (== `SPY_60min.csv`, the drop-in-convention copy) | 41,968 | `9971bd413ef1c08ec17414a34731ba84460f742e2ab458b1fc006702bc1e3b74` |
| `SPY_30min.csv` | 83,787 | `ebee014caeec954962af432d39bd6117ac0df1c73a3076eb46e68c63b3b7a843` |
| `SPY_5min.csv` | 489,730 | `65da7f617079260f974525a3023d7cd58d29640583d0a952f1952db5a8ea0a79` |

Verified byte-for-byte against these figures in this session (`wc -l` minus the header row;
`shasum -a 256`) before any module in this package read them. `SPY_60min.csv` and
`SPY_1hour.csv` are the SAME bytes (the drop-in-convention copy noted in the issue body) — one
SHA256, one row count, listed once.

Every raw bar in these files spans the full UTC day (pre-market/after-hours included, not
pre-filtered to regular session hours) — the emitter (§4) and the simulator (§5) own the
regular-session filtering, per their own conventions below.

---

## §3 Simulation conventions (frozen before any arm runs — SUB_PLAN Q3, restated)

- **Cadence/scan model:** the live bot scans at bar-close + 7 minutes
  (`SCAN_OFFSET_MIN = 7`). A scan is a **flatten scan** — no new entry, and any open position
  is closed — when `sessionClose − scanInstant ≤ period` (60 min for the 60m arm, 30 min for
  the 30m arm). This cadence mapping (a registered modeling decision per Q3) gives the 60m arm
  a last actionable signal bar of 13:00-14:00 ET (flatten at ~15:07 ET) and the 30m arm one
  additional actionable half-hour (flatten at ~15:37 ET).
- **Session hours (disclosed simplification):** every trading date is assumed to run
  09:30-16:00 ET. Early-close/half-day sessions are NOT specially modeled — a half-day's real
  last bar still ends at or before this assumed close (so it is never wrongly excluded), but
  its true close is not itself detected as an extra flatten trigger. Disclosed, not solved; a
  future round with a real trading-calendar source could remove this gap.
- **Fills:** entry and flatten both fill at the **open of the first 5Min bar at/after the
  action instant** (5Min SIP comes free with the same fetch and recovers the +7-minute scan
  offset). The staged `SPY_5min.csv` covers the full 2016-2026 window, so the Q3 fallback
  (next-native-bar open if 5Min is unavailable) is **not exercised** in this study.
  `SLIPPAGE_BPS=5` / `COMMISSION_BPS=5` (`backtest/regime.py`'s constants, same as #499).
  Price-level return/R statistics apply slippage only (mirrors `bracket.py`'s own
  `return_pct` convention); commission is an additional dollar haircut applied only in the
  equity-replay step (§3's sizing-cap pass), matching #499's own replay formula.
- **Exit resolution:** post-entry 5Min bars are walked through `backtest/bracket.py::_resolve_bar`
  (open-gap-first, then **STOP-first on a both-touched bar** — the frozen conservative
  tie-break). Exits are live from the entry fill bar onward (the next 5Min bar strictly after
  the fill bar is the first one checked) — a deliberate deviation from `simulate_bracket`'s
  entry-bar exemption, disclosed: live brackets are armed at fill.
- **Gates replicated bar-reproducibly:** signal + tie-break (`decideHourly`), shorts-disabled
  collapse, geometry_invalid/size_too_small (`computeSizing`'s own validity gate,
  `HOURLY_MIN_STOP_DISTANCE=0.05`) — all computed **statelessly** per bar by the TS emitter
  (§4). One-position-at-a-time, cooldown (next bar strictly after the last exit's fill time),
  day cap 3 (`HOURLY_MAX_ENTRIES_PER_DAY`'s default), and flatten-scan detection are
  **state-dependent** (they depend on the simulated ledger, which differs by R arm) and are
  owned by the Python simulator (§5), never the emitter.
- **Modeled by assumption (Q3, restated):** kill-switch flag never active; `paused`/equity
  floor never fires during the simulation itself (any replayed equity curve breaching -15%
  from its start is flagged as a finding in the verdict doc, not gated during the run); no ops
  outages (live had one missed slot on 2026-08-07, per that day's journal); context mode
  `"none"`.
- **Outcomes:** `target` / `stop` / `flatten` (+ a defensive `end_of_window` at the series'
  final bar, expected to be rare-to-never given flatten-scan coverage). Expectancy = mean
  realized R per arm (`R_realized = (exec_exit − exec_entry) / |entryRef − stopPrice|`, the
  same stop-distance denominator `computeSizing` itself uses). One registered **diagnostic**,
  not a selectable arm: the no-flatten counterfactual — every `flatten`-exited trade is
  individually continued forward (same stop/target, same `_resolve_bar` walk) until it
  naturally resolves or the data ends — isolating the winner-truncation effect the issue asks
  about.

---

## §4 The signal emitter (`scripts/emit_hourly_decisions.ts`)

Deno, file-in/file-out, `CLAUDE_AGENT_NO_BROKER=1`. Calls the real `decideHourly`,
`computeBracketGeometry`, `computeSizing` exports directly — no re-derivation in Python (Q2).
One run per cadence (not per R): `computeBracketGeometry`'s stop price and `computeSizing`'s
validity do not depend on `hourlyBracketRMultiple` at all, only the target price does, so a
single emitter run per cadence computes every R's target price in one pass and Python replays
the state machine three times (once per R) on top of the same stateless decision stream.

A **sanity gate** runs before any arm: on the staged 60m data restricted to 2026-08-03 through
2026-08-12, the emitter's raw `decideHourly` LONG-fire days are checked against the live
`hourly_scans`/journal record (entries on 2026-08-06, 07, 11, 12 only, per that week's daily
verification docs). Result and discrepancy analysis are recorded in this doc's §7 (the emitter
implementation and this gate both land in the same commit as this document per the issue's
step-3 instruction, but the RESULT of the gate is reported here rather than deferred to the
verdict doc, since it gates whether any arm may run at all — no result from an arm is computed
in this commit).

---

## §5 The simulator (`backtest/hourly_geometry.py`, `backtest/run_hourly_geometry_study.py`)

Sequential state machine over the 5Min bar timeline, with the decisions CSV (§4's output)
injecting entry/flatten-eligible events at each decision row's scan instant (bar close + 7
min). Reuses `backtest/bracket.py::_resolve_bar` unchanged for exit resolution — never
`simulate_bracket` itself, whose exits-strictly-after-entry-bar and
flatten-at-last-bar-close conventions do not match this bot (Q2). Long-only
(`HOURLY_SHORTS_ENABLED=false` modeled — the emitter never emits a tradable SHORT row, so the
simulator implements the long side only).

Per-trade stats (R-realized, exit-type distribution, expectancy) are computed directly from
executed prices and are **sizing-invariant** by construction (no `qty` enters a price-ratio
return) — the same property #499 established for the daily candlestick family. The
equity-replay step (§3's sizing-cap sweep) is a **separate pass** over the same trade ledger,
applying `qty = min(floor(SIZING_RISK_PCT·equity / stopDistance), floor(cap·equity / entryPrice))`
compounding trade-by-trade, for each `cap ∈ {0.10, 0.25, 0.50, 1.00}` — #499's own replay
formula, reused verbatim.

---

## §6 `tested_cells.py` — PENDING record (this commit; no result anywhere in it)

Two new records replace the feasibility doc's `DATA_BLOCKED` pair for the same
`(family, cadence, vehicle)` keys — the grid is now staged and about to run, so `PENDING` is
the honest state, not a fresh key:

```
family="hourly_bracket_geometry_sizing", cadence="hourly", vehicle="SPY",
exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=PENDING, power="NONE",
source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-preregistration.md",
date="2026-08-13"

family="hourly_bracket_geometry_sizing", cadence="30m", vehicle="SPY",
exit_style="bracket_RxRisk_flatten", n_cells=3, verdict=PENDING, power="NONE",
source="docs/research/2026-08-13-hourly-geometry-cadence-sizing-preregistration.md",
date="2026-08-13"
```

Flipped to the verdict (power `DIRECTIONAL`, per §8's disclosure) in the results commit
(`docs/research/2026-08-13-hourly-geometry-cadence-sizing-verdict.md`), per the module's own
"same PR as the study" rule. `cumulative_trials("hourly_bracket_geometry_sizing")` stays `0`
until that flip (`PENDING` rows are excluded from multiplicity accounting).

---

## §7 Sanity-gate outcome (recorded here, not deferred — see §4)

Filled once the emitter runs against the staged 60m data — see the results commit for the
full per-day table; this doc's own copy (frozen at pre-registration time) is intentionally
**not** duplicated here to avoid a second source of truth for the same numbers. The
pre-registration's own commit **does** include the emitter implementation and this gate's
console output as verification evidence (PR body), but the interpretive writeup of the gate
(explained/harness-bug determination) is Step 3's own deliverable and is folded into the
verdict doc's IEX/SIP concordance section (§ of that doc) rather than split across two docs.

---

## §8 Power disclosure (binding on every downstream claim)

Per the staged-data anchor (§2): 2,738 sessions, **`n_w=10 < 13`** the #398 promotion floor —
**DIRECTIONAL power only.** Every number this study produces is a **checkpoint input**, not a
gate-eligible read: no DSR/PBO/bootstrap statistic is computed or claimed, and nothing in this
package authorizes a promotion decision. The verdict doc's checkpoint framing (findings feed
the ~Aug 26-28 review; no live change) restates this explicitly next to every headline number.

---

## §9 Non-goals (restated from the issue)

- No live parameter, cadence, or sizing change — findings feed the ~Aug 26-28 checkpoint;
  any live change needs its own ADR.
- No new decision rule; `decideHourly` and the frozen detector registry are imported and
  called unchanged, never edited or re-derived.
- No re-fetching or committing of bar data — the staged local CSVs (§2) are the only input;
  `git ls-files data/` stays empty in every commit of this package.

---

## Verification run in this PR (frozen conventions above; results in the later commit)

```bash
CLAUDE_AGENT_NO_BROKER=1 deno task test
deno task lint
deno task fmt:check
venv/bin/python -m pytest tests/ -q
git diff --stat main -- supabase/functions/ supabase/migrations/ .env.example README.md  # expect empty
git ls-files data/  # expect empty
```
