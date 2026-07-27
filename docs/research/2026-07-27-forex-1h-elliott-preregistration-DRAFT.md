> **STATUS: DRAFT — NOT FROZEN.** No cell here is registered. **No `backtest/tested_cells.py`
> row exists for this family and none is added by this PR.** Nothing in this document may be
> cited as a pre-registration. Freezing happens in a later batch, in its own PR, strictly
> before any result is computed.

# Forex 1h Elliott Wave — pre-registration DRAFT (grid sketch, unfrozen)

**Issue:** #468 (P4 of batch #464). **Predecessors:** `backtest/elliott.py` (the labeler this
grid would test), `docs/research/2026-07-27-forex-1h-data-feasibility.md` (the feasibility
read this DRAFT depends on — `PROMOTABLE`, n_w=14, measured firing rates), the candlestick v2
FADE/FOLLOW-both-frozen precedent (`2026-07-25-candlestick-context-preregistration.md`).
**Date:** 2026-07-27. **Author:** Claude Code session (research-only; no `supabase/`, no
`strategy/`, no order placed, no LLM anywhere in the path).

---

## §0 Invariant framing

Replace-not-add: this DRAFT sketches a **future, separately-frozen** grid over
`backtest/elliott.py`'s deterministic structure labels — it does not modify, extend, or
compete with the bot's one decision rule (`computeTargetState`, SPY vs 200-DMA). No LLM is
imported anywhere in this package. Research-only: lives entirely under `backtest/`, `tests/`,
`docs/research/`. **Authorizes nothing live.** No cell in §3 below is registered, tested, or
run in this PR — freezing (adding a `tested_cells.py` row and computing §7's results) happens
in a later, separate batch, in its own PR, strictly before any result exists (the two-PR
delivery precedent: `2026-07-26-mes-contracts-survey-preregistration.md`).

---

## §1 Novelty

```
$ python3 -m backtest.tested_cells --check elliott_wave 1h EURUSD
proposed: family=elliott_wave cadence=1h vehicle=EURUSD
NOVEL — no prior record overlaps this cell.
```

**Novel by the ledger's own bar.** No `elliott_wave` family record exists at any cadence or
vehicle. The honest overlap disclosure the ledger's mechanism can't capture (it indexes by
`family`, not by functional form) is the point of this section:

**Three closed `4h/EURUSD` records exist and must be named, not silently ignored**
(`backtest/tested_cells.py`):

- `ma_cross` / 4h / EURUSD — `CLASS_KILL`, 15 cells, best 0.337 median after-tax Calmar vs
  SPY 1.309.
- `momentum_roc` / 4h / EURUSD — `CLASS_KILL`, 9 cells, zero survivors.
- `mean_reversion_rsi_bollinger` / 4h / EURUSD — `CLASS_KILL`, 9 cells, zero survivors.

**Economically, an Elliott Wave pullback/continuation entry can resemble these killed trend
families** — both ultimately bet on a directional continuation or reversal around a price
extreme. **Functionally, the labeler's form is different**: a grammar over a *confirmed pivot
sequence* with hard rules and Fibonacci-ratio constraints, not a rolling-window aggregate
(SMA cross, Donchian channel, ROC, RSI, Bollinger band) computed identically at every bar.
This is the exact argument `candlestick.py`'s own module docstring makes for why classic
candlestick patterns were untested despite the killed families: *"a different functional form
... fixed 1-to-3-bar OHLC geometry ... rather than a rolling-window aggregate."* The same
argument, scaled to a multi-pivot structure instead of a 1-3 bar geometry, is why
`elliott_wave` is a genuinely new family and not a relabeled re-run of `ma_cross`.

**Reconciliation with the repo's own recorded `skip` verdict** (full argument:
`2026-07-27-forex-1h-data-feasibility.md` §1 "Reconciling the recorded skip verdict"):
`roadmap.md:585` and `strategies.md:415` killed an **LLM-authored** wave count as
non-deterministic; this labeler has no LLM anywhere in it and is unit-tested against
synthetic fixtures with known labels. The `skip` verdict against a human/LLM analyst's
discretionary count stands unreversed; it simply does not apply to a deterministic grammar
that never existed when that verdict was written. A reviewer should treat the absence of this
paragraph as a finding — it is included here in full.

---

## §2 The bar (inherited, unchanged)

- **Primary bar**: median-window after-tax Calmar > SPY buy-and-hold's median-window
  after-tax Calmar, **1.3085475049604838**, on **13 scored windows** (2013–2025, per the
  feasibility note §2.5's `n_windows=14` / scored=13 distinction).
- **#398 overfitting gate** (pooled across cumulative trials at freeze time): `DSR >= 0.95`,
  `PBO < 0.5`, moving-block bootstrap `CI_low > 0` on the uplift — all three, combined.
- **Beat all four dumb baselines** in `backtest/fx_baselines.py`: `always_flat_state`,
  `buy_and_hold_state`, `persistence_state`, `sma200_regime_state`.
- **Co-primary cost presets**: XTB CFD base (0.79 bp) **and** CME 6E futures base (0.56 bp) —
  a survivor must clear the bar at **both**.
- **Primary tax mode**: `annual_netting` (German calendar-year netting); `de_sensitivity`
  sensitivity-only, never a survivor basis.

---

## §3 Grid axes (sketch, unfrozen)

| Axis | Values | Count |
|---|---|---|
| θ (reversal threshold) | `{0.20%, 0.30%, 0.50%}` (`elliott.THETA_GRID`) | 3 |
| Mapping | `{FADE, FOLLOW}` | 2 |
| Structure | `{impulse, zigzag, both}` | 3 |
| R (bracket multiple) | `{20, 30, 50 bp}` (`fx_signals.R_GRID`) | 3 |

**3 × 2 × 3 × 3 = 54 cells.**

**State the multiplicity cost bluntly**: 54 cells is a substantial trial count for a family
that starts at **cumulative N = 0** (no prior `elliott_wave` cells exist to pool against) —
this raises the DSR bar meaningfully relative to a smaller grid, and 0/54 clearing would be a
much less surprising result under pure multiplicity than 0/9 was for the FX mean-reversion
family. **Flag 54 as a de-scope candidate at freeze time.** The cheapest axis to drop is
**`structure` = `both`** (a combined impulse-or-zigzag reading): dropping it removes 18 cells
(54 → 36) without losing either pure reading, and `both` is also the least doctrinally clean
of the three (mixing two different completion semantics into one signal).

---

## §4 Controls

- **Pure-noise negative control** (standing rule: *"every new grid needs its own pure-noise
  negative control"*) — the labeler run on a synthetic pure-random-walk frame (no real drift,
  no real volatility clustering) at every θ; expected result is a firing rate and ratio
  distribution consistent with chance, and near-zero edge on whatever baseline comparison is
  used.
- **Random-twin control** — shuffle the completed structures' `signal_ts` values (preserving
  the count and the direction mix exactly) and re-run the mapping; a real edge should not
  survive having its own timing randomized while its rate/direction statistics are held
  fixed.
- **`fx_baselines` always-flat / buy-and-hold / persistence / SMA200** — per §2, a survivor
  must beat all four, not just the SPY bar.

---

## §5 Stopping rule (sketch)

If **0/54 clear the bar at both co-primary presets** *and* the **pooled #398 gate fails**
(any of `DSR < 0.95`, `PBO >= 0.5`, bootstrap `CI_low <= 0`) — the family is **closed**, no
round 2. (Condition 3 — "no cell exists to beat its own random-twin control" — is checked the
same way the `mes_swing` and `candlestick_pattern_timestop` stopping rules did: vacuously
satisfied if no cell clears the bar in the first place.)

---

## §6 Not in this grid

Verbatim from `backtest/elliott.py`'s module docstring (the v1 non-goals) — **loudly
declared, not hidden**: nested/fractal counting (wave 3 subdividing into its own 5-wave set —
the largest doctrinal simplification); diagonals (leading/ending, which permit W1/W4
overlap); flats and triangles (only the zigzag correction is mechanized); the alternation
guideline (W2 sharp ⇒ W4 sideways); multi-timeframe confluence; wave-2 entry ("start of wave
3", which requires signalling on an *incomplete* structure).

Plus two DRAFT-specific future grid axes, declared but not built: **H/L-extreme pivots**
(this v1 is close-basis only); **ATR-adaptive θ** (this v1 is a fixed percentage, not a
rolling-window-coupled threshold — coupling θ to ATR would dilute the novelty argument in §1,
since it would reintroduce the "rolling-window aggregate" functional form this family is
supposed to differ from).

---

## §7 Open items before freeze

1. **`n_w` is resolved**: 14 (measured, this session — `2026-07-27-forex-1h-data-feasibility.md`
   §2.5). Not an open item; recorded here for completeness since the original SUB_PLAN framed
   it as one.
2. **The measured firing rate is resolved**: pooled 538 structures / 88,112 bars ≈ 0.1219
   completions/day at θ=0.30% (feasibility note §2.6) — sets the realistic trade cadence and
   therefore the cost drag (~0.18–0.25%/yr, both co-primary presets). Not an open item at
   freeze time either, but the exact figure should be re-measured against whatever cache
   exists at freeze (the archive keeps publishing).
3. **Whether 54 cells survives triage** — open. §3's de-scope lever (`structure=both`,
   54→36) should be decided explicitly at freeze, not defaulted.
4. **Whether the depth extension to ~2003 (histdata.com / Dukascopy, n_w≈23,
   `docs/runbooks/fx-1h-data-drop.md` §4) is worth funding** — open. FXCM alone already
   clears `PROMOTABLE`; the deeper vendors would only buy a robustness check on an earlier
   era, at the cost of a full vendor-integration package. Not recommended unless the frozen
   grid's read (once run) specifically motivates it.
