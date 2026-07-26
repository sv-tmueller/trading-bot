# Candlestick study v3 — time-stop grid: pre-registration (84 cells)

**Question:** Does adding a **maximum holding period** (a time stop, orthogonal to the frozen
R-target bracket) rescue any candlestick pattern that failed both context-free (v1) and
trend-context-filtered (v2)?

**Issues:** refs #422, #431, #443, #448 · **Predecessors:** v1
(`2026-07-25-candlestick-pattern-preregistration.md`), v2
(`2026-07-25-candlestick-context-preregistration.md`) · **Batch context:** #447 (D12)
**Date:** 2026-07-26
**Author:** Claude Code session (research-only; no production/TypeScript code, no
`supabase/`, no `strategy/`, no settings, no broker integration touched; no order placed;
no network performed by any module added here; no SPY bars fetched, no grid run on real
data — see the status line below).

> **Status: PRE-REGISTRATION / FREEZE ONLY — this is PR A of #448's two-PR delivery.**
> **§7 (Results) below is deliberately EMPTY.** `main` squash-merges, so a freeze commit
> and a result commit inside one PR would collapse into a single commit on `main` and
> fail the graded pre-registration acceptance criterion. Per the lead's decision D12 on
> batch #447: PR A (this freeze — the engine's `max_bars` extension, the v3 grid runner,
> the pooled #398 gate at N=168, and this document's §0–§6/§8/§9) merges into `main`
> first; PR B (the SPY read, §7) branches from `main` only afterward. **No SPY number
> exists anywhere in this document or in the commits behind it.**

---

## §0 Invariant framing (governs everything below)

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- Any candidate this produces would be a **deterministic pure function of price history**
  that **replaces** the live 200-DMA/UPRO rule, never a second parallel rule (invariant #1,
  one decision rule). This study **authorizes nothing live** — the UPRO/200-DMA bot runs
  unchanged regardless of how this round resolves.
- **No LLM in the trading path** (invariant #2). Every module touched or added for this
  study lives in `backtest/` and is never imported by `supabase/functions/`.
- `backtest/` imports no Alpaca client and places no order; the only network is the
  read-only historical-bars pull already wired into `run_candlestick_study._fetch_daily`,
  and this PR performs none of it — see the hard rule in the status line above.
- Engineer subagents never execute against the live broker; `CLAUDE_AGENT_NO_BROKER=1` for
  the whole session per the standing rule.
- A clearing cell here would authorize a **design spec and a fresh ADR**, never a
  deployment — see §8.

---

## §1 Why this exists, and why it is not a re-run of something already killed

v1 (28 cells, context-free) and v2 (56 cells, trend-context) both returned **NO_GO** on
SPY at `PROMOTABLE` power: zero cells cleared the frozen bar in either grid, and the pooled
#398 gate failed at cumulative N=84 (`docs/research/2026-07-25-candlestick-pattern-preregistration.md`
§7, `2026-07-25-candlestick-context-preregistration.md` §7). Three decisions govern why a
third round is legitimate rather than a disguised re-test of a closed question:

**D-A. "Orthogonal to the R-target bracket" means an ADDED factor, not a REPLACEMENT one.**
The v3 cell keeps the frozen v1 geometry verbatim — the pattern-extreme stop and the
`target = entry_ref ± R·risk` bracket — and adds a maximum holding period on top. The
rejected alternative was to drop the R target and exit on stop-or-time only (a 14×3 = 42
cell grid): rejected because it would change **two** things at once relative to v1, so a
difference could no longer be attributed to the time stop specifically — the identical
reasoning the repo already used to justify the v2 random-entry twin drawing only from
context-admitted bars ("the control would differ from the real cell in two ways at once …
a gap between them could no longer be attributed to the pattern"). Under D-A, a v3 cell
differs from its v1 twin in **exactly one** respect: the time stop. This is pinned by
`tests/test_run_candlestick_study.py::test_v1_grid_is_unchanged_by_the_max_bars_parameter_default`
(the v1 geometry is untouched when the new parameter is left at its default) and by every
v3 cell sharing `build_cell`/`build_random_cell` with v1/v2 rather than a forked geometry
function.

**D-B. v3 runs `CONTEXT_NONE` only — no context × time-stop cross.** v2 already answered
the context question (NO_GO); crossing context with the time-stop axis here would put this
grid at 14×2×3×2 = 168 cells and the cumulative family at 84+168 = 252 for no new question
— the context axis is not what this round tests. Frozen in
`backtest/run_candlestick_timestop_study.TIME_STOP_GRID` (no context factor at all) and
pinned by `tests/test_run_candlestick_timestop_study.py::test_v3_runs_context_none_only`.

**D-C. The ledger family key is NEW (`candlestick_pattern_timestop`), so this is not a
re-run of a `CLOSED` cell — but that must be disclosed, not asserted by citing the novelty
check.** Run BEFORE the `PENDING` record below was added to the ledger,
`backtest.tested_cells.check_novel("candlestick_pattern_timestop", "daily", "SPY")`
returned:

```
proposed: family=candlestick_pattern_timestop cadence=daily vehicle=SPY
NOVEL — no prior record overlaps this cell.
```

But a fresh family STRING will always return `NOVEL` even if the underlying arms were
identical to a closed family — that output is a bookkeeping fact about the string, not
evidence that the *content* is new. The content-level novelty argument is D-A/D-B above:
the entry arms here are exactly the **closed** v1 arms (`run_candlestick_study.ARMS`,
`R_GRID`, imported unchanged), and what is actually new is the exit rule (the time stop).
Anyone auditing this record should read D-A/D-B, not the `NOVEL` string, to decide whether
the round is legitimate. For completeness, the two prior families both report `CLOSED`
(re-verified after this PR's ledger addition, so both checks below coexist with the new
`PENDING` record):

```
proposed: family=candlestick_pattern cadence=daily vehicle=SPY
  [CLOSED (a re-run would be a duplicate)] candlestick_pattern/daily/SPY n=28 NO_GO -> docs/research/2026-07-25-candlestick-pattern-preregistration.md

proposed: family=candlestick_pattern_context cadence=daily vehicle=SPY
  [CLOSED (a re-run would be a duplicate)] candlestick_pattern_context/daily/SPY n=56 NO_GO -> docs/research/2026-07-25-candlestick-context-preregistration.md
```

---

## §2 The bar (verbatim, unchanged from v1/v2)

> A cell clears the bar only if its **full-window after-tax US Calmar** exceeds the SPY
> buy-and-hold median-window after-tax Calmar of **1.3085475049604838** (n_w = 13
> non-overlapping 12-month windows, 2013-2025), on the same after-tax basis
> (`_after_tax_metrics(...)["calmar_us"]`).

Secondary, reported but not the verdict: CAGR, max drawdown, trade count, each cell's
**random-entry twin**, the **always-in** benchmark, and the pooled #398 gate outputs.

---

## §3 The grid and the N accounting (frozen, 84 cells)

| | |
|---|---|
| Arms | `run_candlestick_study.ARMS`, imported unchanged — 14 |
| R | `run_candlestick_study.R_GRID`, imported unchanged — `(2.0, 3.0)` |
| Time stop | **`TIME_STOP_GRID = (3, 5, 10)`** bars — 3 levels |
| Context | `CONTEXT_NONE` only (D-B) |
| **This grid** | **N = 14 × 2 × 3 = 84** |
| **Cumulative family** | **N = 28 (v1) + 56 (v2) + 84 (v3) = 168** |

Why `{3, 5, 10}` and not something tuned: 3 and 5 bars are the swing-trading horizon over
which candlestick doctrine claims a pattern "plays out"; 10 days is Bulkowski's standard
measurement horizon for pattern statistics. All three are conventional values fixed from
doctrine before any number is seen — the same justification style v1's own detector
thresholds use (§3.1 of the v1 pre-registration).

### §3.1 The 84/84 coincidence (read this before quoting either number)

**This round's own N (84) is numerically equal to the PREVIOUS round's cumulative N (84,
v1's 28 + v2's 56).** Stated once, plainly: **this is a coincidence of the grid sizes
chosen for this round, not a re-use of the same 84 trials.** The 84 cells counted for "this
grid" are the NEW v3 grid — 14 arms × R{2,3} × time-stop{3,5,10} — entirely disjoint from
the 84 already-run v1+v2 cells (which used a context factor instead of a time-stop factor
and are keyed differently in every runner and in the pooled gate — see
`backtest/run_candlestick_gate.py::build_all_cells`, whose v3 keys carry a `"timestopN"`
tag that cannot collide with v1/v2's `"none"`/`"reversal"`/`"continuation"` context labels).
The deflated-Sharpe bar for THIS round uses the **cumulative N = 168**, never 84. Both
labelled lines are always printed together by
`run_candlestick_timestop_study.format_report` (pinned by
`test_report_prints_both_this_grid_N_and_cumulative_N`), and the coincidence sentence is
part of that same printed report, not just this prose.

### §3.2 Not sourced from `cumulative_trials()`

Per repo convention (established in the v2 doc), the cumulative figure is **not** sourced
from `backtest.tested_cells.cumulative_trials()` — that function sums per-**vehicle** rows
(GOOG + SPY) and would return the wrong numbers for the two prior families (56 and 112, not
28 and 84). The frozen convention is distinct *grid cells on the primary vehicle*, computed
in code as `CUMULATIVE_N = V2_CUMULATIVE_N + N_CELLS` in
`run_candlestick_timestop_study.py`, exactly mirroring how
`run_candlestick_context_study.py:67` computed its own 84 from v1's 28.

---

## §4 Frozen time-stop engine semantics (the `max_bars` contract)

`backtest.bracket.simulate_bracket` gained a keyword-only `max_bars: Optional[int] = None`
parameter in this PR (#448 A1), additive and default-off — the same shape as the
`session_close_out` (#431) and `direction` (#434) extensions the module's own docstring
already documents as precedent. Frozen here verbatim (mirrors the engine docstring):

- `None` (default) = off; the engine is **byte-identical** to its pre-#448 behavior for
  every existing caller (turtle, ORB, giveback, candlestick v1/v2). Pinned by
  `tests/test_bracket.py::test_max_bars_default_none_is_a_no_op`.
- `max_bars < 1` raises `ValueError` at call time — an exit on the entry bar would violate
  the engine's `exit_date > entry_date` assertion. Pinned by `test_max_bars_below_one_raises`.
- `bars_held = i - entry_i`, where `entry_i` is the index of the bar whose **open** filled
  the lot. The entry bar is never tested for an exit (unchanged from the base engine).
- The time stop fires at the **close** of the bar where `bars_held >= max_bars`, with
  `exit_reason="time_stop"`, using the existing exit cost convention
  (`fill_level·(1−slip)`, `(1−comm)` haircut; mirrored for shorts). Pinned by
  `test_time_stop_exits_at_the_close_of_the_nth_bar_after_entry` and
  `test_time_stop_mirrors_onto_the_short_side`.
- **Precedence inside a bar:** natural stop/target resolution (`_resolve_bar`) first, then
  the time stop, then `session_close_out`, then `eow_close_out`. A stop or target hit on
  the same bar as the time stop resolves as `stop`/`target`, never `time_stop`. Pinned by
  `test_a_stop_or_target_hit_on_the_time_stop_bar_takes_priority`. (The candlestick cells
  run with both close-outs off — `eow_close_out=False`, `session_close_out=False` — so only
  the first two matter for this study, but the order is frozen in the engine itself and
  pinned regardless of which callers currently exercise it.)
- The final bar of the series always stays `end_of_window`, even if `bars_held` would have
  reached `max_bars` there — same convention as the other two close-out modes. Pinned by
  `test_time_stop_does_not_fire_on_the_final_bar_it_is_end_of_window`.
- Invariant the study leans on: **every** trade satisfies `bars_held ≤ max_bars`. Pinned by
  `test_no_trade_is_held_longer_than_max_bars` (engine level) and
  `tests/test_run_candlestick_timestop_study.py::test_every_trade_respects_its_cells_time_stop`
  (grid level, across all 84 cells).

`build_cell`/`build_random_cell` in `run_candlestick_study.py` gained the same
`max_bars: Optional[int] = None` keyword as a straight passthrough (#448 A2) — `ARMS`,
`R_GRID`, `bracket_levels`, `STOP_BUFFER`, `SPY_BAR`, `_fetch_daily` and `cell_status` are
all untouched.

---

## §5 Power requirement and the mechanical gate

Identical to v1/v2 and mechanically enforced: `UNDERPOWERED` ⇒ **no per-cell table at
all**, exit 2 (`intraday_data.describe_power`; `PROMOTABLE` requires n_w ≥ 13 non-overlapping
12-month windows and enough bars). NaN Calmars are classified `no-trades` (never fired —
not evidence about the pattern) vs `RUINED` (traded and the after-tax curve was destroyed —
*worse* than negative, not missing). Every cell is reported; no top-N, no silent
truncation. The pooled #398 gate (`run_candlestick_gate.py`) is likewise only defined at
`PROMOTABLE` power and refuses to run below it.

---

## §6 Negative controls (must hold on the SPY read, checked)

Two layers, mirroring v1/v2's own controls so all three are comparable:

1. **Pure-noise grid control (the required one).**
   `tests/test_run_candlestick_timestop_study.py::test_pure_noise_clears_no_cell`
   (`@pytest.mark.slow`). Construction copied **unchanged** from v1/v2:
   driftless random-walk daily OHLC (`_synth_daily(3600, seed=2026, drift=0.0)`, opens not
   pinned to the prior close), run through the full 84-cell v3 grid; asserts no cell clears
   `SPY_BAR`. Without this, an all-negative real result would be ambiguous between "time
   stops do not rescue the class" and "the new exit is wired up wrong". **This control has
   already been run in this PR (on synthetic data only) and passes** — see the CHECKS in
   the PR body; it is not itself a real-data result.
2. **Per-cell random-entry twin (inherited).** `build_random_cell` takes the same
   `max_bars` and is reported per cell exactly as in v1/v2 — the control differs from the
   real cell in entry timing only. Same `RANDOM_SEED = 42`, imported not redefined.

The pooled #398 gate keeps its own noise control
(`tests/test_run_candlestick_gate.py::test_pure_noise_frame_does_not_pass_the_gate`,
`@pytest.mark.slow`), re-verified at the extended N=168 in this PR and still holding.

---

## §7 Results

**EMPTY — not yet run. This document is the freeze (PR A of #448); see the status line at
the top.**

No numbers appear here because none exist. When PR B runs the SPY read, this section is
filled in a **strictly later commit** on a **strictly later PR**, provable from git
history, and §0–§6/§8/§9 above are not edited afterward (the same discipline #446 used:
freeze in `8d424f7`, results in the strictly later `82af278`).

Reproduce (once PR A has merged and the frame is available):

```bash
python3 -m backtest.run_candlestick_timestop_study --data data/SPY_daily.csv
python3 -m backtest.run_candlestick_gate --data data/SPY_daily.csv
```

---

## §8 What a result would authorize (pre-committed verdict mapping)

Fixed here, before any number exists, so the mapping is not chosen after seeing the read:

| Outcome | Authorizes |
|---|---|
| 0/84 clear | The time stop does not rescue the class. **Record the v3/daily/SPY row as `NO_GO`** (consistent with the sibling v1/v2 SPY rows — both `NO_GO` and `CLASS_KILL` are closing verdicts, so nothing behavioural turns on the choice), with the §9 stopping-rule invocation carried in the record's `note`. |
| 1+ clear, pooled #398 gate at cumulative N=168 fails | **Nothing.** Textbook overfit signature — the same read that closed v1 and v2. |
| 1+ clear, gate passes, cell sits on/below its random twin | **Nothing** — that is the tell that closed the Turtle (#430) and would close this cell too: capturing session volatility, not a timing edge. |
| 1+ clear, gate passes, beats its twin AND the always-in benchmark | A **design spec** and a fresh ADR. Not a deployment — see §0. Per §9, this also does not by itself authorize the vehicle-robustness round; §9's three conditions govern that separately. |
| Data cannot be reproduced at `PROMOTABLE` power | The round is `DATA_BLOCKED`/`PENDING` — **not evidence of anything**, the §9 stopping rule does not fire, and nothing is closed. A blocked round is never cited as a negative. |

**0/84 clear ⇒ NO_GO** is the pre-committed mapping this PR fixes; the numbers that decide
which row of this table applies do not exist yet.

---

## §9 Stopping rule for the candlestick widening programme (frozen, binding)

This programme has widened twice (v1 context-free geometry, v2 trend context) and this is
round 3 (exit horizon). Widening without a pre-committed end is how a search launders
multiplicity, so the end condition is fixed here, before this round runs.

**The programme continues to round 4 (the disclosed vehicle-robustness arm) if and only if
all three of these hold on the SPY `PROMOTABLE` read:**

1. at least one v3 cell's full-window after-tax US Calmar exceeds the frozen bar
   1.3085475049604838; **and**
2. the pooled #398 gate, run over the cumulative family at **N = 168**, returns a combined
   `PASS`; **and**
3. that cell's after-tax Calmar exceeds both its own random-entry twin and the always-in
   benchmark on the same frame.

**If any of the three fails, the candlestick direction is closed.** No round 4 is frozen,
no vehicle-robustness arm is run, and multi-pattern confluence — the axis the programme
itself identified as where overfitting lives — is not attempted. The closure is recorded
in `backtest/tested_cells.py` and in the weekly review. Reopening requires new
*information* (a new data source, a new instrument class, a published result), argued in a
fresh brainstorm and a new pre-registration — never a new grid over the same SPY history.

**Data failure is not a result.** If the SPY frame cannot be obtained at `PROMOTABLE`
power, this round is `DATA_BLOCKED`/`PENDING`, the stopping rule does not fire, and nothing
is closed. A blocked round is never cited as a negative.

Rationale for stopping at "0 clear" rather than one more axis: three orthogonal axes
(entry geometry, trend context, exit horizon) will have been tested over 168
pre-registered cells with zero survivors. The remaining authorized axis changes the
*vehicle*, not the signal — a survivor that appears only on a different vehicle after 168
failed cells on the primary one is indistinguishable from noise at the cumulative bar it
would have to clear.

---

## Verification run in this PR (freeze only — synthetic data throughout)

```
python3 -m pytest -m "not slow" -q                                              # full suite
python3 -m pytest -m slow tests/test_run_candlestick_timestop_study.py tests/test_run_candlestick_gate.py
python3 -m backtest.tested_cells --check candlestick_pattern_timestop daily SPY  # NOVEL before this PR's ledger add; OPEN after (see §1 D-C)
python3 -m backtest.tested_cells --check candlestick_pattern daily SPY           # expect CLOSED
python3 -m backtest.tested_cells --check candlestick_pattern_context daily SPY   # expect CLOSED
git diff --stat main -- supabase/ strategy/ web/ main.py .github/ scripts/       # expect empty
```

Outputs pasted verbatim in the PR body/description, per repo convention for this kind of
freeze (see the ORB long/short pre-registration, `2026-07-24-orb-longshort-preregistration.md`,
for the precedent of a PENDING/frozen doc with an empty results section).
