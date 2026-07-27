# MES contracts survey — pre-registration (24 cells)

**Question:** Do any of 12 classic edge-trigger arms (trend/momentum/mean-reversion, long and
short), re-parameterized for a **daily equity-index bar** with a **turtle-style ATR bracket
exit**, clear the frozen SPY buy-and-hold after-tax Calmar bar under the MES wrapper's own
verified cost bracket?

**Issue:** #457 (P1 of batch #456) · **Direction:** #453 · **Predecessors:**
`2026-07-21-leveraged-contracts-preregistration.md` (froze the promotion bar and the
instrument-class recommendation, not the cell grid — see that doc's §6 freeze-granularity
split), `2026-07-26-mes-contract-spec-verification.md` (verified the cost/margin figures this
doc consumes). **House precedent mirrored:** `2026-07-26-candlestick-timestop-preregistration.md`
(doc shape, two-PR delivery, stopping rule) and `run_turtle_breakout.py` (ATR bracket, random
twin, per-window scoring). **Date:** 2026-07-26
**Author:** Claude Code session (research-only; no production/TypeScript code, no
`supabase/`, no `strategy/`, no settings, no broker integration touched; no order placed; no
network performed by any module added in this PR; **no SPY bars fetched, no grid run on real
data anywhere in this PR** — every test in `tests/test_run_mes_swing_study.py` and
`tests/test_run_mes_swing_gate.py` runs on synthetic OHLC — see the status line below).

> **Status: PRE-REGISTRATION / FREEZE ONLY — this is PR A of #457's two-PR delivery, per the
> D12 precedent (#447) that batch #456 P1 mandates.**
> **§7 (Results) below is deliberately EMPTY.** `main` squash-merges, so a freeze commit and
> a result commit inside one PR would collapse into a single commit on `main` and fail the
> graded pre-registration acceptance criterion ("committed strictly earlier than any
> result — provable on `main` via the two-PR ordering"). PR A (this freeze — the grid runner,
> the pooled #398 gate at N=24, this document's §0–§6/§8/§9, and the `PENDING` ledger row)
> merges into `main` first, lead-merged after PASS+APPROVE; PR B (the SPY read, §7) branches
> from `main` only afterward, and stays human-merged. **No SPY number exists anywhere in this
> document or in the commits behind it.**

---

## §0 Invariant framing (governs everything below)

Per CLAUDE.md's [Architectural invariants](../../CLAUDE.md#architectural-invariants):

- Any candidate this produces would be a **deterministic pure function of price history**
  that would **replace** the live 200-DMA/UPRO rule, never a second parallel rule (invariant
  #1, one decision rule). This study **authorizes nothing live** — the UPRO/200-DMA bot runs
  unchanged regardless of how this round resolves.
- **No LLM in the trading path** (invariant #2). Every module touched or added for this study
  lives in `backtest/` and is never imported by `supabase/functions/`.
- `backtest/` imports no Alpaca client and places no order; the only network any module here
  could ever do is the read-only historical-bars pull already wired into
  `run_candlestick_study._fetch_daily` (imported unchanged for the SPY vehicle) — and this PR
  performs none of it, per the status line above.
- Engineer subagents never execute against the live broker; `CLAUDE_AGENT_NO_BROKER=1` for
  the whole session, per the standing rule.
- A clearing cell here would authorize, at most, a **design spec and a fresh ADR** — never a
  deployment. The margin re-verification precondition (§4 below) and the Handelsfreigabe
  block any paper/live step regardless of verdict — see §8.

---

## §1 The frozen grid (D1) and why it is not a re-run of anything closed

**12 arms x R in {2, 3} = 24 cells, one round, no context axis.** The #406 sketch (frozen
`2026-07-21-leveraged-contracts-preregistration.md` §3/§6) authorizes exactly two
plausibly-novel shapes on the MES wrapper: (a) killed direction-shapes **re-parameterized for
a daily equity-index bar** (with per-cell registry justification), and (b) genuinely new
shapes (vol-regime gating, cross-sectional). This grid takes (a) as round 1 and reserves (b)'s
vol-gate axis as the only pre-named round-2 axis inside the stopping rule (§6 below).

### §1.1 The frozen arm table

All arms are EDGE triggers (fire once per excursion, never re-trigger while the underlying
state persists): signal on the completed close `t`, entry at `t+1`'s open via
`signal.shift(1)` — the house convention already used by every daily-bar study in this repo.

| # | Family | Trigger (edge, not state) | Dir |
|---|---|---|---|
| T1L/T1S | trend | SMA10 crosses above / below SMA50 | long / short |
| T2L/T2S | trend | SMA20 crosses above / below SMA100 | long / short |
| M1L/M1S | momentum | ROC(63) crosses above / below 0 | long / short |
| M2L/M2S | momentum | ROC(126) crosses above / below 0 | long / short |
| V1L/V1S | mean-rev | RSI(2) crosses below 10 / above 90 | long / short |
| V2L/V2S | mean-rev | RSI(14) crosses below 30 / above 70 | long / short |

Every lookback is a doctrine/convention value fixed before any number is seen: 63/126 are
quarter/half a trading year; RSI(2) 10/90 is the Connors canonical pair; RSI(14) 30/70 is the
Wilder canonical pair; SMA 10/50 and 20/100 are standard daily swing pairs, disjoint from the
killed 4h forex set (`{5/20, 20/50, 50/200}`) and from the ADR-settled 200-day regime scale.
No new geometry parameter is invented anywhere in the grid.

Implementation note (drift-proofing): `T1`/`T2` reuse `fx_signals.sma_cross_signal` directly
— it is already edge-native (its own `cross_up`/`cross_down` boolean masks are 0 except at
the exact crossing bar), so no further derivation runs on it. `M1`/`M2`/`V1`/`V2` reuse
`fx_signals.roc_signal`/`rsi_signal` (persistent state — the sign/threshold condition holds
for every bar of an excursion) and derive the edge via `run_mes_swing_study._edge_trigger`
(first bar of each same-signed run) — this is what "crosses above/below" means in the table
above, not "is currently above/below". Pinned by
`tests/test_run_mes_swing_study.py::test_momentum_arm_does_not_retrigger_while_roc_stays_positive`
and the mean-reversion/trend siblings.

### §1.2 Exit geometry (frozen verbatim from the Turtle convention)

`run_turtle_breakout._bracket_levels`'s ATR-bracket geometry, mirrored for shorts: stop =
entry - 2*ATR(20, Wilder, read at `t-1`), target = entry + R*ATR(20), mirrored (stop above
entry, target below) for the short arms. `eow_close_out=False`, `session_close_out=False`,
`max_bars=None` — the candlestick precedent's convention: stop/target/end-of-window are the
only exits. No engine change: `backtest/bracket.py` already supports `direction="short"`
(#434) and defaults `max_bars` off (#448) — both extensions predate this PR and are consumed
unchanged.

### §1.3 Registry survival — the per-arm justification table (mandatory, read before quoting any cell)

The 4h EUR/USD `CLASS_KILL` (`ma_cross`/`momentum_roc`/`mean_reversion_rsi_bollinger`,
`docs/research/2026-07-15-forex-4h-survey-verdict.md`) covered these SAME three families **at
4h on EURUSD with fixed-bp exits**. That doc's own §3 names "lookbacks chosen for a 4h forex
bar" as the unswept region and requires per-cell justification for any re-parameterization.
Three concrete differences separate every arm here from its killed forex sibling: **daily
cadence** (roughly 6x the forex study's horizon), **equity-index vehicle** (SPY, not a
currency pair), and **ATR-bracket exits** (not the forex study's symmetric fixed-bp TP/SL
grid).

| Arm pair | Killed forex sibling | What differs here | Novelty strength |
|---|---|---|---|
| T1 (SMA10/50) | `ma_cross` (4h, SMA 5/20 20/50 50/200) | cadence, vehicle, exit; also a disjoint SMA pair | Strong — no shared parameter at all |
| T2 (SMA20/100) | `ma_cross` (4h, same set) | cadence, vehicle, exit; disjoint SMA pair | Strong |
| M1 (ROC 63) | `momentum_roc` (4h, ROC 12/24/48) | cadence, vehicle, exit; disjoint lookback | Strong |
| M2 (ROC 126) | `momentum_roc` (4h, same set) | cadence, vehicle, exit; disjoint lookback | Strong |
| V1 (RSI-2, 10/90) | `mean_reversion_rsi_bollinger` (4h, RSI-2 10/90 among others) | cadence, vehicle, exit — **same indicator parameters** | Moderate |
| **V2 (RSI-14, 30/70)** | `mean_reversion_rsi_bollinger` (4h, RSI-14 30/70) | cadence, vehicle, exit — **identical indicator parameters, nothing else new** | **Weakest — stated plainly, not buried** |

**V2 (RSI-14 30/70) is the weakest-novelty pair in this grid.** Its only difference from the
already-`CLASS_KILL`ed forex cell is cadence/vehicle/exit — exactly the axis the frozen forex
doc itself flagged as unswept, and exactly the axis a genuine re-parameterization is allowed
to change, but it is the arm with the least room to surprise. It is kept in the grid (dropping
it would shrink N without changing the stopping rule) but flagged here so a reviewer weighs a
V2 survivor accordingly.

**Nothing here collides with a ledger-`CLOSED` (family, cadence, vehicle).**
`donchian_breakout/daily/SPY`, `candlestick_pattern/daily/SPY`,
`candlestick_pattern_context/daily/SPY`, `candlestick_pattern_timestop/daily/SPY` are closed
and **not reopened** — this grid contains no Donchian-breakout or candlestick-pattern arm.
`ma_cross`/`momentum_roc`/`mean_reversion_rsi_bollinger` are closed only at `4h/EURUSD`, not at
`daily/SPY` — a different (family, cadence, vehicle) key entirely.

### §1.4 The D-C disclosure (verbatim in spirit from the #448 precedent)

Run **before** the `PENDING` record below was added to the ledger,
`backtest.tested_cells.check_novel("mes_swing", "daily", "SPY")` returned:

```
proposed: family=mes_swing cadence=daily vehicle=SPY
NOVEL — no prior record overlaps this cell.
```

**A fresh family STRING will always return `NOVEL`, even if the underlying arms were
identical to a closed family — that output is a bookkeeping fact about the string, not
evidence that the content is new.** The content-level novelty argument is §1.3 above: five of
six arm pairs differ from their closed forex siblings on cadence+vehicle+exit with a disjoint
parameter; the sixth (V2) differs only on cadence+vehicle+exit and is flagged as the weakest
pair. Anyone auditing this record should read §1.3, not the `NOVEL` string, to decide whether
the round is legitimate.

For completeness, run after this PR's ledger addition lands, the closed families this grid
does NOT collide with report `CLOSED` (re-verified so both checks below coexist with the new
`PENDING` record):

```
proposed: family=donchian_breakout cadence=daily vehicle=SPY
  [CLOSED (a re-run would be a duplicate)] donchian_breakout/daily/SPY n=3 NO_GO -> docs/research/2026-07-24-turtle-breakout-verdict.md

proposed: family=candlestick_pattern cadence=daily vehicle=SPY
  [CLOSED (a re-run would be a duplicate)] candlestick_pattern/daily/SPY n=28 NO_GO -> docs/research/2026-07-25-candlestick-pattern-preregistration.md

proposed: family=candlestick_pattern_context cadence=daily vehicle=SPY
  [CLOSED (a re-run would be a duplicate)] candlestick_pattern_context/daily/SPY n=56 NO_GO -> docs/research/2026-07-25-candlestick-context-preregistration.md
```

### §1.5 Rejected alternatives (stated, not silently dropped)

- **Vol-regime-gating axis (x2 or x3)** — would put round 1 at 48-72 cells; the candlestick
  programme just demonstrated that context axes multiply N without rescuing a class.
  Reserved as the sole pre-authorized round-2 axis inside the stopping rule (§6).
- **Cross-sectional / relative-value vs a slower reference** — needs a second instrument's
  history, breaking the frozen single-source decision (SPY daily via yfinance). Legitimate
  only under its own future pre-registration.
- **Donchian daily SPY under MES costs** — ledger-`CLOSED`; the NO-GO note says the cell
  "sits ON its random twin" (no gross edge), and a cost haircut cannot rescue zero gross
  edge. Reopening is an explicit non-goal.
- **Regime-flip signals (100/200-DMA, tsmom-12mo, Faber) on a leveraged wrapper** —
  re-litigates the 2026-07-06 keep-200dma ADR, not this direction's question.
- **Anything intraday** — #422's NO-GO stands (non-goal).
- **Candlestick anything** — the programme is closed at N=168.

---

## §2 The ledger family (D2)

**`family="mes_swing"`, `cadence="daily"`, `vehicle="SPY"`, `exit_style="bracket_2ATR_RxATR"`,
`n_cells=24`.** A fresh family with its own cumulative-N accounting: **cumulative N = 24 for
this round — explicitly not the candlestick programme's 168, and not the forex programme's
33** (disjoint families). The runner's printed report and this document both carry the
"this grid N = 24 / cumulative family N = 24" pair of lines so a future round 2 (if ever
authorized) inherits the convention mechanically
(`run_mes_swing_study.N_CELLS == run_mes_swing_study.CUMULATIVE_N == 24`, pinned by
`tests/test_run_mes_swing_study.py::test_grid_is_24_cells`).

Vehicle is honestly `SPY` — the price series actually simulated, the same discipline the
Turtle study's own `ES` row used (recording the series it ran on). The MES wrapper lives in
the family name, the cost model (§4), and the capital note (§5) — not in a fabricated
"vehicle=MES" row that would claim a simulation never run.

**Rejected:** reusing the existing `ma_cross`/`momentum_roc`/`mean_reversion_rsi_bollinger`
keys — their `cumulative_trials()` would silently merge FX multiplicity into this family, and
#457 mandates a new family.

---

## §3 The bar and the scoring rule (D3)

**The bar (frozen, verbatim):** the #398 gate's frozen SPY median after-tax Calmar,
**1.3085475049604838** (`2026-07-21-leveraged-contracts-preregistration.md` §4, sourced
verbatim from the forex 4h survey verdict). `run_mes_swing_study.MES_SURVEY_BAR` is pinned
equal to `run_candlestick_study.SPY_BAR` by
`tests/test_run_mes_swing_study.py::test_mes_survey_bar_equals_the_candlestick_spy_bar` —
drift-proof without importing a closed programme's module as a semantic dependency.

**Decision D3 — per-cell primary statistic: median-window after-tax Calmar under German
`annual_netting` (`tax.apply_annual_netting_tax`), computed on the bar's own window set
(calendar-year 12-month windows, 2013-2025, n_w=13 when the frame spans it, warm-up never
scored), and the cell clears only if median > 1.3085475049604838 AND worst scored window > 0
— at BOTH co-primary cost presets (§4).**

This deliberately deviates from the candlestick precedent (full-window `calmar_us`, US
deduct-at-exit). The reviewer should check this consciously:

- The frozen bar's own text defines it as *German `annual_netting`, median-window, n=13,
  2013-2025* — like-for-like comparison requires the same tax mode and window construction
  the bar itself was computed under.
- The frozen multiplicity discipline (binding on "any eventual survey" in this direction)
  mandates median + worst-window judging — full-window-only would violate the freeze.
- MES is a Termingeschäft (26.375% flat, calendar-year netting post-JStG-2024); the
  `annual_netting` mode is the instrument's ACTUAL tax regime for a German retail resident.
  The US deduct-at-exit model's no-loss-credit clamp materially distorts a stop-heavy bracket
  strategy's after-tax curve in a way that has nothing to do with the instrument being
  simulated.
- Machinery already exists: `tax.apply_annual_netting_tax` (the FX survey's own primary mode)
  and the windowed re-simulation pattern in `run_turtle_breakout._per_window_calmar` — reused
  in `run_mes_swing_study._per_window_scores`, mirroring the pre-roll/window-slice/NaN-drop
  convention exactly.

**Secondary columns, reported but never verdict-bearing:** full-window `calmar_us`/`calmar_de`
(deduct-at-exit — cross-family comparability with the turtle/candlestick studies) and an
all-available-window (from the frame's own start) median/worst as an era-sensitivity read.
Window conventions: NaN/no-trade windows are dropped from scoring (`n_windows`/`n_positive`
reported, the same convention `run_candidate_survey`/turtle already use — rejected
alternative "score 0.0" for consistency with those cited helpers); annualization constant
pinned at 252 (inherited from `run_candidate_survey._curve_metrics`).

---

## §4 Cost model (D4)

**Two co-primary cost presets, frozen at the conservative (low-index) end of the verified
bracket:** base **0.70 bp** and pessimistic **1.06 bp** round trip
(`2026-07-26-mes-contract-spec-verification.md` §4, at index level L=7000 — the worst-bp end
of the frozen 7000-8000 bracket). Wiring: per-side haircut = RT/2 passed as `commission_bps`
(0.35 / 0.53), `slippage_bps=0.0` — `bracket.py` divides by `10_000.0` so floats pass through
with **no engine change**; a test
(`tests/test_run_mes_swing_study.py::test_round_trip_haircut_matches_the_frozen_bp_figure`)
pins the realized round-trip haircut on a synthetic one-trade frame to each frozen bp figure.
A cell "clears" only at BOTH presets (the forex co-primary precedent).

**Mandatory cost/capital disclosures, carried from the spec-verification note and Revision 1
of the frozen pre-registration, none silently compared:**

1. **The MES figures include the USD 0.35/side CME exchange-fee pass-through that the frozen
   forex feasibility-gate doc's 6E/M6E rows explicitly omitted.** That doc's own §4.3 states
   the omission would make the futures numbers "modestly worse, never better" if corrected —
   so any MES-vs-6E/M6E comparison is stacked in MES's favor on this one dimension, not
   apples-to-apples.
2. **The 1-tick/2-tick spread leg is an inherited convention from the 6E/M6E derivation, not
   an observed MES spread.** No live MES bid/ask spread was measured by any source in the
   spec-verification note.
3. **Margin is a still-unverified observed bracket ≈$2,267-$2,754/contract** (AMP Futures vs
   Discount Trading disagree; neither pins an "as of" date). The IBKR-Ireland first-party
   re-verification remains a standing precondition before any paper/live step, tracked on
   #453.
4. **Free-cash-only funding and the Handelsfreigabe are operational prerequisites** (R1.3/R1.4
   of the frozen pre-registration): German retail futures access at IBKR requires funding the
   margin with free cash only (no margin loan) and a separate futures trading-permission
   request, independent of the BaFin Nachschusspflicht-exclusion mechanism the wrapper relies
   on.
5. **The EUR 50,000 doubling rule is non-binding at survey size** — the spec-verification
   note's §2.3 arithmetic puts the threshold at roughly 21-25 contracts of the same
   underlying class aggregated, an order of magnitude above any plausible 1%-fixed-fractional
   micro-futures survey/paper position.
6. **SPY-proxy systematic errors are a standing sensitivity risk, not a modeled effect:**
   session-hours gap (SPY trades US cash hours; MES trades nearly 24h), dividend-adjustment
   vs futures carry-basis mismatch, and ETF-vs-futures microstructure differences. Per the
   data-feasibility note's binding instruction, these are disclosed here as an explicit risk
   to any survivor's real-world MES performance, not quantified away.

---

## §5 Position sizing (D5) — capital arithmetic, not a simulated feature

**Single-lot simulation.** The frozen pre-registration's §5 is explicit that fixed-fractional
sizing does not create expectancy — it caps loss-per-trade and shapes the drawdown/growth
path, nothing more. The house Calmar conventions and the bar itself are single-lot-curve
constructions; this survey does not deviate.

**1% fixed-fractional risk arithmetic (symbolic at freeze — no simulated FFR compounding):**

```
risk_budget   = 0.01 x equity
contracts     = floor( risk_budget / (stop_distance_pts x $5) )
```

using the MES multiplier ($5/point, verified two-source-reconciled in the spec-verification
note §1). **Minimum equity for 1 contract** = `stop_distance_pts x $5 / 0.01` = `stop_distance_pts
x 500`. The measured stop-distance distribution (2*ATR(20) in index points, per §1.2's frozen
geometry) is a §7 deliverable once real data exists — this section fixes the formula, not the
number, exactly as the frozen doc's own §5 fixes the formula without a number.

Weighed against the observed margin bracket (§4.3, ≈$2,267-$2,754): a stop distance wide
enough to push the minimum-equity figure above the margin bracket would mean the
fixed-fractional sizing rule is the binding constraint rather than the broker's margin
requirement, at typical MES volatility — this is exactly the kind of arithmetic check §7 will
report once the real ATR distribution exists, never assumed here.

**Rejected: an FFR-compounding simulator.** New engine surface, breaks comparability with
every existing single-lot study in this repo, cannot change the expectancy verdict (§5's own
load-bearing statement: sizing does not create expectancy), and would push this package past
size:M (per the sub-plan's §6 size-check).

**Also out of scope, disclosed, not silently dropped:** the Alpaca 2016-present cross-check
leg (data-feasibility note §5's cheap reconciliation) — not an acceptance criterion of #457,
needs credentials, and neither candlestick read performed the analogous check either.

---

## §6 Stopping rule (frozen verbatim, binding)

**The programme continues to a round 2 (only pre-named candidate axes: vol-regime gating on
these same 12 arms; vehicle-robustness on ES=F) if and only if all three hold on the SPY
`PROMOTABLE` read:**

1. at least one cell clears the frozen bar (the D3 statistic: median > 1.3085475049604838
   AND worst scored window > 0) at **both** co-primary cost presets (§4); **and**
2. the pooled #398 gate (`run_mes_swing_gate.py`) at cumulative family N=24 returns a combined
   `PASS`; **and**
3. that cell beats both its random-entry twin and the always-in benchmark, on the same frame
   and the same basis.

**If any of the three fails, the `mes_swing` family is closed NO-GO.** The verdict is the
contracts direction's survey verdict — #453's closing condition is met, though closure itself
(updating #453) is operator/lead business, not this PR's.

**Data-failure carve-out:** if the SPY frame cannot be obtained at `PROMOTABLE` power, the
round is `DATA_BLOCKED`/`PENDING` — this is **not evidence**, fires nothing, and is never
cited as a negative.

**Reopening standard:** new information — a new data source, a new instrument class, a
published result (e.g. the paid-ES-history path or the cross-sectional shape) — argued in a
fresh brainstorm and a new pre-registration. Never a new grid over the same SPY history.

**A GO authorizes a design spec + fresh ADR + paper-first staging only** — the margin
re-verification precondition (§4, item 3) and the Handelsfreigabe (§4, item 4) block any
paper/live step regardless of verdict.

**Pre-committed verdict-mapping table**, fixed here before any number exists:

| Outcome | Authorizes |
|---|---|
| 0/24 clear at either preset | The class does not clear the bar. Record `mes_swing/daily/SPY` as `NO_GO`. |
| 1+ clear at both presets, pooled gate fails | **Nothing.** The textbook overfit signature — the same read that closed the Turtle and the candlestick programme. |
| 1+ clear at both presets, gate passes, cell sits on/below its random twin or the always-in benchmark | **Nothing** — capturing session volatility/beta, not a timing edge (the tell that closed Turtle #430). |
| 1+ clear at both presets, gate passes, beats twin AND always-in | A **design spec** and a fresh ADR — not a deployment (§0). Also does not by itself authorize the vehicle-robustness round; §6's three conditions govern that separately. |
| Data cannot be reproduced at `PROMOTABLE` power | `DATA_BLOCKED`/`PENDING` — **not evidence of anything**; nothing closes. A blocked round is never cited as a negative. |

---

## §7 Results

**EMPTY BY DESIGN — this is PR A of #457's two-PR delivery (see the status banner at the top
of this document).** No SPY number exists anywhere in this document or in the commits behind
it. §7 is filled in a strictly later commit, on a strictly later PR (PR B), branched only
after this PR merges to `main`. §0-§6/§8/§9 will be unedited from this freeze at that point —
the diff between the freeze commit and the results commit will be confined to §7 plus a dated
addendum under this document's front-matter banner (the same discipline #448/#455 used).

---

## §8 What a result would authorize / non-goals restated

See §6's pre-committed verdict-mapping table for the authorization mapping. Restated plainly:

- No broker account changes, no paper or live step — blocked on the margin re-verification
  precondition (§4, item 3) regardless of verdict.
- No reopening of any ledger-`CLOSED` family; no intraday cadence (#422's NO-GO stands).
- No edit to any frozen section of the 2026-07-21 pre-registration — further changes to that
  document go through its own §7 revision clause as a new Revision, not through this doc.
- **Blocked is not negative.** A `DATA_BLOCKED`/`PENDING` round is never cited as evidence
  either way.

---

## §9 Two-PR delivery record

| PR | Commit(s) | Content |
|---|---|---|
| A (this one) | freeze | `run_mes_swing_study.py`, `run_mes_swing_gate.py`, this document's §0-§6/§8/§9, the `PENDING` ledger row |
| B (later, branched from `main` after A merges) | results | §7 filled, the dated addendum under the front-matter banner, the ledger flip, the weekly review regenerated |

---

## Verification run in this PR (freeze only — synthetic data throughout)

```
python3 -m pytest -m "not slow" -q
python3 -m pytest -m slow tests/test_run_mes_swing_study.py tests/test_run_mes_swing_gate.py
python3 -m backtest.tested_cells --check mes_swing daily SPY          # NOVEL before this PR's ledger add; OPEN after (see §1.4)
python3 -m backtest.tested_cells --check donchian_breakout daily SPY  # expect CLOSED
python3 -m backtest.tested_cells --check candlestick_pattern daily SPY            # expect CLOSED
python3 -m backtest.tested_cells --check candlestick_pattern_context daily SPY    # expect CLOSED
git diff --stat main -- supabase/ strategy/ web/ main.py .github/ scripts/  # expect empty
```

Outputs pasted verbatim in the PR body, per repo convention for this kind of freeze (see
`2026-07-26-candlestick-timestop-preregistration.md`'s own "Verification run in this PR"
section for the precedent).
