# Strategy direction — goal definition (issue #255)

- **Date:** 2026-06-20
- **Status:** brainstorm complete, awaiting operator review of this spec
- **Issue:** #255 (priority: high) — blocks #230 (go-live)
- **Method:** `superpowers:brainstorming`, run interactively with the operator (six clarifying questions + search-path selection)
- **Supersedes the assumption that we ship the current leveraged-regime bot.** Direction is reset to a goal-first definition before any further strategy build.

---

## 1. Why this exists

The 2009→now backtest (#254, `docs/research/2026-06-06-regime-vs-spy-longrun-backtest.md`) showed the current 200-DMA regime + 3× UPRO bot returned ≈ SPY (15.9% vs 15.3% CAGR) at roughly **2× the drawdown** (−58% vs −34%). It did not beat SPY on a risk-adjusted basis in a no-deep-bear era, and its one demonstrated edge (crash survival) is synthetic-only.

The 2026-W25 paper soak made the point concretely: the bot turned a +1.2% SPY week into +7.3%, and would have turned a −1.2% week into roughly −7%. **The return is leveraged beta in a favourable tape, not a demonstrated edge.** (`docs/trading-journal/2026-W25.md`.)

This spec defines what we actually want instead, so the next build (if any) is measured against a falsifiable target rather than a vibe.

## 2. The goal (success definition)

Improve **risk-adjusted** return versus SPY buy-and-hold. Precisely:

| Dimension | Decision |
|---|---|
| **Benchmark** | SPY, total return |
| **Primary gate** | Beat SPY's **Calmar** ratio (CAGR ÷ max drawdown), measured on **identical out-of-sample walk-forward windows**, **net of costs and tax** |
| **Drawdown ceiling** | Max drawdown no worse than ~SPY's (~−34%). SPY-like pain is acceptable; the goal is not lower-DD-than-SPY, it is better Calmar |
| **Return** | Modest absolute excess over SPY is acceptable **if the ratio wins**. Explicitly **not** "maximum return at maximum risk" |
| **Account context** | Taxable margin: leverage and shorting are available, but turnover is taxed, so **after-tax** Calmar is the number that counts |
| **Frequency** | Multi-day swing is in scope. **Intraday day-trading is out.** Survey *across* frequencies (daily-or-slower through multi-day swing) and let evidence rank; tiebreak toward the more-active candidate when two are close on risk-adjusted terms |

**Gate is relative, not an absolute Calmar number.** A candidate passes if its Calmar exceeds SPY's on the *same* walk-forward windows, so the comparison is window-independent and like-for-like.

### Operator intent behind the frequency choice
The operator wants (a) more return via active timing, (b) a bot that is *engaged* rather than idle for months at a time, and (c) to be steered by evidence — willing to accept a slower approach if it demonstrably wins risk-adjusted. The survey honours all three: it centres on active candidates but does not exclude slower ones, and it ranks purely on the gate.

## 3. Constraints (carried-over invariants)

These are non-negotiable and carry from `CLAUDE.md` → Architectural invariants:

- **Deterministic.** No LLM in the trading path.
- **One decision rule.** Any new signal, vehicle, or allocation rule replaces or extends the single rule only via its **own** brainstorm + spec. This spec defines the *target*; it does not authorise a second live rule.
- Kill-switch, `bot_config.paused`, and `audit_log` invariants hold for whatever ships.

## 4. Non-goals / out of scope

- No strategy code in this phase. This spec defines the target only.
- **Intraday day-trading** (weak evidence base, infra/latency/cost/tax hurdles).
- **Maximum return at maximum risk** (e.g. more leverage for its own sake).
- Re-deriving the current bot's flaws — that is settled (#254).
- Choosing the strategy here. The survey (section 6) chooses candidates; survivors get their own spec.

## 5. Evidence bar (the gate a candidate MUST clear)

A candidate is only allowed to proceed to a `spec → plan → implement` cycle if, in the `backtest/` simulator via the existing walk-forward harness (#263, `backtest/walkforward.py` + `backtest/baselines.py`):

1. **Walk-forward out-of-sample**, not a single in-sample fit. Signal on completed bar T, execute T+1 open.
2. **Costs + slippage modelled** (0.05% + 0.05% frictions minimum), and **tax drag** estimated for the taxable-account case.
3. **No curve-fit**: edge stable across windows, not concentrated in one regime; sensitivity to parameter choices reported.
4. **Drawdown stress through a real bear** — 2022 and the 2020 COVID crash at minimum; deeper history (2008) where data allows.
5. **Beats SPY on after-tax Calmar** on identical windows, **and** beats the dumb baselines: fee-adjusted buy-and-hold, persistence, Faber 10-month SMA, 12-month TSMOM.

If a candidate clears all five, it earns a spec. If none clear, see section 7.

## 6. Next phase: candidate survey (approach A, operator-selected)

Run a broad, evidence-first candidate-strategy survey (the `research-bundle` / `analyst` path #255 prescribes) before committing to any single strategy:

- **Universe of archetypes to score:** time-series and cross-sectional momentum at swing/medium horizon; dual-momentum rotation; tactical asset allocation across asset classes (equities/bonds/gold); mean-reversion swing; volatility-targeting / low-beta tilts; risk-parity-lite. (Not exhaustive; the survey may add adjacent ideas.)
- **Each scored** through the #263 walk-forward harness against the section-5 bar, ranked by OOS after-tax Calmar vs SPY and the baselines.
- **Output:** a findings doc in `docs/research/` that ranks the candidates and recommends the 1–2 that clear the gate (or reports that none do). The survey may also recommend a **core-satellite structure** (a drawdown-protecting core plus a smaller active swing sleeve) if that scores better than any standalone candidate.
- **Then:** each survivor gets its own `brainstorming → spec → writing-plans → implement` cycle. Nothing reaches the trading path without clearing section 5.

**This is the terminal handoff of this brainstorm.** Because the immediate next step is research (the survey), not an implementation build, the transition is to the candidate survey rather than directly to `writing-plans`. `writing-plans` is invoked later, per surviving candidate.

## 7. The floor (a legitimate outcome)

If no candidate clears the section-5 bar out-of-sample, the correct answer is **hold 1× SPY (or a low-cost equivalent) and ship nothing further.** "Match SPY at materially lower drawdown" or "modest excess at similar drawdown" are also acceptable wins. A null result is a result, and is cheaper than shipping a coin-flip.

## 8. Deferred to the survey (not decided here)

- The specific instrument set per archetype (ETFs vs leveraged ETFs vs futures) — an output of the survey, constrained by the taxable-margin account.
- Whether the final shape is a single strategy or core-satellite (section 6).
- Position sizing / leverage level — decided per surviving candidate, in its own spec.
