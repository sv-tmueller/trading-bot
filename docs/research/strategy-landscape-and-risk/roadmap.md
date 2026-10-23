# Strategy Landscape and Risk -- Roadmap

**Scope.** Feature and research candidates drawn from the sibling files `strategies.md` (15 archetypes plus the risk-norm and combination sections), `github-projects.md` (8 frameworks and bots, plus its "Roadmap pattern candidates" list) and `keywords.md`, mapped against the live code in `supabase/functions/` and the repo's own verdicts. The trigger is issue #675 (raise effective risk per trade). The operator's wider question was "what do other bots and traders do, what could be good strategies, should we combine them, and what do they risk?"

**This is not an implementation plan.** It contains no code and no PR proposals. Priorities and efforts are research-grade. Each candidate that would change the trading path still goes through `superpowers:brainstorming`, a spec and, where the safety stack or trading logic changes, an ADR in `docs/decisions/`.

**Date:** 2026-10-23.

**How to read.** Each candidate has:
- a fit verdict against `CLAUDE.md` "Architectural invariants" and the README's *"LLM must never control risk parameters"* lens: **`fits`**, **`needs envelope`** (with the envelope in one sentence) or **`violates`**;
- a priority: **`now`** / **`next`** / **`later`** / **`skip`**;
- an effort: `S` (up to 1 day), `M` (1-5 days), `L` (1-3 weeks), `XL` (multi-month or research-grade).

The fit verdict answers whether something *can* be done safely. It says nothing about whether it *should* be done. The priority carries the evidence.

---

## Ground truth this roadmap builds on

**Already shipped (so not re-proposed; extensions only):**
- **Sizing.** `computeSizing` (`supabase/functions/hourly-check/logic.ts:370`) computes `min(risk leg, notional leg)`. Its settings and bounds are `SIZING_RISK_PCT` 0.01 in (0, 0.05] and `SIZING_NOTIONAL_CAP_PCT` 0.10 in (0, 1.0], range-validated in `_shared/config.ts:125-135`. The notional leg always binds on SPY hourly stops (median about 28 bp), so realised risk is about 0.025% of equity (#499, #675, `docs/research/2026-08-02-sizing-rule-live-vs-backtest.md`).
- **Equity floor.** A fixed -15% floor measured from `hourly_experiment_start_equity` (`EQUITY_FLOOR_PCT = 0.15`, `logic.ts:54`; gate 6 at `:745-825`). It writes `bot_config.paused=true`, latches and never self-clears.
- **Entry gates and exits.** A signal-bar cooldown (gate 13, `:1110`), `HOURLY_MAX_ENTRIES_PER_DAY` = 3 in [1, 10] (gate 14, `:1122`), the session-close flatten scan, R = 2 brackets (pinned at exactly 2 in `config.ts`) and the per-position `kill-switch` drawdown (`KILL_SWITCH_DRAWDOWN_PCT` 0.25).
- **Pause and panic.** `bot_config.paused` and a side-aware `panic`.
- **Panic already closes every open position, long and short.** `panic/logic.ts:83-101` iterates `getOpenPositions()`, and `panic/logic.test.ts:229` pins it. `strategies.md` lists "multi-symbol side-aware panic" as a future envelope item; the base is already shipped, and only a K-position test remains (multi-symbol verdict §7).

**Missing (the lead's verified list):**
- a daily loss limit;
- a consecutive-loss (StoplossGuard-style) pause;
- a trailing high-water-mark brake;
- cost-aware sizing;
- any portfolio-level risk budget for more than one strategy.

**Evidence anchor:**
- **The incumbent rule.** `decideHourly` measured **-0.139R/trade** at 1 bp/side on SPY 2016-2026 (95% CI -0.182 to -0.101, n = 2,478). It was already -0.031R gross, and every calendar year was negative (`2026-10-22-multi-symbol-hourly-verdict.md` §3.1, branch `research/multi-symbol-hourly`).
- **Other symbols.** 0 of 19 symbols showed EDGE.
- **Intraday momentum** was NO_EDGE (`2026-10-22-spy-intraday-momentum-verdict.md`, branch `research/spy-intraday-momentum`).
- **The research programme.** The ledger has run 364 cells with 0 survivors (`docs/research/reviews/2026-W42.md`).

**A finding this roadmap adds (verified in code, 2026-10-23):**
- **The gap.** `hourly-check` checks `paused` at step 1 and returns `skipped:trading_paused` (`logic.ts:697-700`). That happens *before* the reconcile and session-close flatten at steps 4-5 (`:718`).
- **The bracket legs.** They are placed with `time_in_force: "day"` (`_shared/alpaca.ts:555, 595, 642`).
- **The consequence.** A pause that lands while a position is open leaves no flatten scan and legs that expire at the close. The pause can come from the operator, or from the equity floor's own auto-pause, which fires at gate 6, before the gate-12 position check. The runbook documents this as the "unmanaged-position consequence" (`docs/runbooks/hourly-bot-rollout.md` §11 and the `success:auto_paused` triage note). It is disclosed, not accidental, but it is the one designed path to an overnight hourly position. See B.1.

---

## Cluster A -- Sizing and #675

### A.1 Run the spec's review checkpoint on the incumbent rule and record the outcome

- **Description.** Make a recorded decision (an ADR in `docs/decisions/`) on whether the `decideHourly` paper experiment continues, pauses (via the existing `panic?action=pause`) or is retired. Use the 2026-10-22 verdicts as the checkpoint input. No code change.
- **Source.** Codebase-driven:
  - the spec's §11 stopping rule, "4 weeks or 30 closed trades, whichever comes first" (`docs/superpowers/specs/2026-07-27-hourly-bot-design.md`);
  - the multi-symbol verdict ("a checkpoint input");
  - `strategies.md` #14 Repo status.
- **Pros**
  - Both checkpoint legs have long passed: the rollout began 2026-07-30, and the verdict counts 42 live trades. A grep of `docs/decisions/` and `docs/trading-journal/` (2026-10-23) found no recorded checkpoint outcome.
  - It turns three negative verdicts into an explicit operating decision instead of an implicit "keep running".
  - It frames #675: sizing only makes sense once it is decided what is being sized.
- **Cons**
  - The live record (+2.86R over 42 trades) looks fine and invites anchoring. The verdict places it inside the noise around a negative mean.
  - Retiring the rule leaves the bot idle until a replacement clears research. That is honest, but it gives up the paper ops rehearsal the live bot provides.
- **Fit.** **`fits`**. This is governance, and any pause uses the existing kill switch.
- **Priority.** **`now`**.
- **Effort.** `S`.

### A.2 Resolve #675 with an ADR: no risk increase on the incumbent; risk-leg-binding sizing is the default for any replacement

- **Description.** The ADR records three things:
  - the target risk-per-trade band from #675 (0.1-0.25%) and its notional backstop, as the sizing design for a *future* strategy;
  - that the incumbent stays cap-bound at about 0.025%;
  - which brakes (B.2, B.3) are prerequisites for the change.

  `computeSizing` and `config.ts` are untouched now.
- **Source.** #675's own caveat; `strategies.md` "Translating the norms to this bot" and "Kelly"; `github-projects.md` cross-cutting finding "#675 is a parameter problem, not a missing feature"; `2026-08-02-sizing-rule-live-vs-backtest.md`.
- **Pros**
  - It meets #675's first acceptance criterion ("decided and recorded in an ADR") without scaling an expected loss.
  - R-denominated evaluation loses nothing at small size. Win rate, mean R and profit factor are sizing-invariant: profit factor moved at most 0.036 across 14 arms in the 2026-08-02 memo.
  - It keeps the operator's chosen design (size by risk, cap as backstop) for the moment it can earn money.
- **Cons**
  - It defers the operator's 2026-10-22 preference.
  - Paper size stays unrealistically small, so ops at realistic size stay unrehearsed: fill quality at larger quantity and the flatten failure path.
- **Fit.** **`fits`**.
- **Priority.** **`now`**.
- **Effort.** `S`.

### A.3 Raise risk per trade on the current rule (the #675 change as written)

- **Description.** Set `SIZING_RISK_PCT` to about 0.001-0.0025 and `SIZING_NOTIONAL_CAP_PCT` to about 0.36-1.0, so that the risk leg binds. The current `config.ts` bounds already allow both, so it is a `supabase secrets set` change on dev.
- **Source.** #675; `github-projects.md` "Make the risk leg bind".
- **Pros**
  - Mechanically trivial: no code and no bound change.
  - Matches the mainstream framework shape (risk leg first, notional clamp second: nautilus, jesse, freqtrade).
  - Paper only, and the paper-only guard is unchanged.
- **Cons** (assessed head-on)
  - **It scales a measured expected loss linearly.** That is about -3.3%/yr of equity at 0.1% risk and about -8.1%/yr at 0.25% (`strategies.md` table, at -0.139R and 234 trades/yr).
  - **It would probably trip the floor.** P(15% drawdown within 5 years) is about 72% at 0.1%, and about 100% within about 1.7 years at 0.25%. The fixed equity floor would most likely latch `paused`.
  - **Kelly says zero.** The Kelly fraction is about -0.13, so the growth-optimal stake is zero, and every positive stake lowers expected log-growth.
  - **No evidence pulls the other way.** No calendar year 2016-2026 was positive.
  - **It buys no information.** The R statistics that judge the rule are sizing-invariant, so a bigger size produces bigger numbers and no new evidence.
  - **Earlier research agrees.** The 2026-08-13 sizing study found every cell breached the -15% floor at every cap tested ({0.10, 0.25, 0.50, 1.00}), under a harsher 5+5 bp cost model.
  - **It sharpens the tail.** At 89-100% notional, the worst observed SPY overnight gap (399 bp) is about 4% of equity, so B.1's pause path and any flatten failure become first-order.
- **Fit.** **`fits`**. It is deterministic, config-bounded and LLM-free. The invariants do not object; the evidence does.
- **Priority.** **`skip`** on the incumbent rule. It amplifies a negative expectancy and adds no evaluative information. The mechanism comes back only inside the spec of a replacement that has cleared the research gate, and only after B.2 and B.3 have shipped. If the operator wants to rehearse larger-size mechanics on paper, that should be a separately labelled, time-boxed ops rehearsal with its own ADR, not a sizing decision.
- **Effort.** `S`.

### A.4 Cost-aware risk budget in `computeSizing`

- **Description.** Deduct a configured round-trip cost (per-side bps × 2 × notional) from the risk budget, so that quantity is computed on net R. This touches `hourly-check/logic.ts::computeSizing` and adds one new range-validated, default-OFF setting in `_shared/config.ts`, per `.claude/skills/add-or-extend-agent/SKILL.md`.
- **Source.** `github-projects.md` (nautilus deducts 2× commission; jesse haircuts by 3× fee); `strategies.md` implication 2.
- **Pros**
  - On a 28 bp stop, 1 bp/side is about 7-8% of 1R, and the measured live cost is about 0.5 bp/side (momentum verdict). Sizing on gross R overstates risk-adjusted size by that margin.
  - Fully deterministic.
- **Cons**
  - **Zero effect while the notional leg binds**, which is always, today.
  - The cost parameter must match the research cost model, or it creates a new live-versus-backtest drift source.
- **Fit.** **`fits`**.
- **Priority.** **`next`**. Fold it into the sizing section of whatever replacement spec follows C.1.
- **Effort.** `S`.

### A.5 Gap-aware and volatility-targeted sizing for any overnight-holding replacement

- **Description.** A sizer that uses the overnight-gap distribution (for example the p99 SPY gap of 236 bp) as the risk unit when positions hold through the close, optionally under a portfolio volatility target. It would sit beside `computeSizing` with `config.ts` bounds.
- **Source.** `strategies.md` "Gap risk", #3 (volatility targeting) and Grossman-Zhou.
- **Pros**
  - The only honest risk unit when a stop can be gapped through.
  - Vol targeting is the professional analogue of "risk per trade" (AQR's 10% target) and is academically supported for risk assets (Moreira-Muir).
- **Cons**
  - Only meaningful for a strategy that does not exist yet.
  - A single-SPY 10% vol target already failed the after-tax Calmar bar (`2026-06-24-candidate-strategy-survey-second-cut.md`).
  - Adds turnover.
  - Holding overnight conflicts with the hourly bot's session-close flatten, so this lives in a replacement spec, not in `hourly-check`.
- **Fit.** **`fits`**: deterministic, config-bounded sizing math.
- **Priority.** **`later`**, as part of C.1's envelope.
- **Effort.** `M`.

### A.6 Journal which sizing leg bound

- **Description.** Record `bound_by` (risk or cap), together with `qtyRisk` and `qtyCap`, on each entry's `hourly_scans` row or audit notes (`hourly-check/logic.ts`, `_shared/db.ts`).
- **Source.** `github-projects.md` (freqtrade's "adjusting to max stake" log line).
- **Pros**
  - Makes any future sizing change observable in paper.
  - Makes #675's "binding-limit switch" criterion checkable from data instead of arithmetic.
- **Cons**
  - Today the value would always be "cap", so it carries no information until A.2's future strategy exists.
  - It may need a migration.
- **Fit.** **`fits`**.
- **Priority.** **`next`**.
- **Effort.** `S`.

---

## Cluster B -- Loss limits and brakes

**Framing.** At today's size, the planned worst day is bounded by the day cap: 3 entries × 1R ≈ 0.08% of equity, plus slippage or gap overshoot. That already matches the German retail norm of a daily stop at 2-3× per-trade risk (`strategies.md` risk table). The fixed floor sits about 600 losing trades away (`strategies.md` "The loss-limit pattern"). New brakes therefore matter only if size rises or a multi-symbol replacement arrives. They are prerequisites for those changes, not urgent on their own. The exception is B.1, which closes a tail path that exists at any size.

### B.1 Reduce-only pause: protective duties keep running while paused

- **Description.** Change `hourly-check`'s gate order so that `bot_config.paused` blocks *entries* only, while the reconcile (naked-position re-leg) and session-close flatten (steps 4-5) still run. Pin it with tests. Optionally, add an end-of-session "account flat" assertion to `scripts/daily_verify.ts`: no explicit "position open after close" check was found there by grep. This touches `hourly-check/logic.ts` (steps 1 and 4-6), `docs/runbooks/hourly-bot-rollout.md` §11, and the outcome-to-alert table at the top of `logic.ts`.
- **Source.** Codebase-driven (see "Ground truth"); `github-projects.md` ("explicit reduce-only semantics": nautilus `REDUCING`, barter `Disabled`); `strategies.md` "Gap risk".
- **Pros**
  - Removes the one designed path to an unflattened overnight hourly position: a pause or auto-pause with an open position, plus day-TIF legs.
  - Makes the existing equity floor, and every brake below that latches the same flag, safe to fire mid-session.
  - Matches the invariant's own wording: `paused=true` "halts new entries".
- **Cons**
  - It reorders the spec's gate ladder, so it needs a spec revision and an alert-policy review.
  - Operators used to "pause = hands off" need the runbook changed.
  - The paused path would now place orders. It already passes `checkGuard()` and the per-order paper guard, but this needs explicit tests.
  - At today's roughly 10% notional, a p99 gap is only about 0.24% of equity, so the urgency is modest now and grows with size.
- **Fit.** **`fits`**. It strengthens the "Operational kill switch" invariant, and `panic` is unchanged.
- **Priority.** **`now`**.
- **Effort.** `M`: small code, plus spec, runbook and tests.

### B.2 Daily loss limit (session-latching entry halt)

- **Description.** A new gate in `hourly-check`: if `equityAtStart` is at or below session-start equity × (1 - X), skip entries for the rest of the session. Session-start equity is persisted per day (a `bot_config` key or a small table). The setting is default-OFF and range-validated per the `add-or-extend-agent` recipe.
- **Source.** `strategies.md` "The loss-limit pattern":
  - FTMO 3-5% daily;
  - Topstep 2%;
  - German retail 2-3× per-trade risk.

  Also `github-projects.md`, where freqtrade's `MaxDrawdown` with a one-day lookback is the nearest analogue.
- **Pros**
  - The most universal professional loss control.
  - Deterministic; it resets per session, so no operator action is needed.
  - Becomes the binding daily control once a multi-symbol strategy can exceed 3 entries per day.
- **Cons**
  - **Redundant with the day cap for the incumbent.** A 2% limit would equal about 80R at today's size and can never bind.
  - It adds a state read per scan, and it needs a reliable session-start equity source (see E.3).
- **Fit.** **`fits`**.
- **Priority.** **`next`**. It is a hard prerequisite of any size increase or multi-symbol replacement and should ship *before* that, not after.
- **Effort.** `M`.

### B.3 Trailing high-water-mark brake (and later, a de-risking ladder)

- **Description.** Persist the running equity maximum. If equity falls to or below HWM × (1 - Y), write `paused=true`, latching and never self-clearing, exactly like `EQUITY_FLOOR_PCT`. This sits beside gate 6 in `hourly-check/logic.ts`. Optionally later: a fixed notional scale-down ladder.
- **Source.** `strategies.md`:
  - Grossman-Zhou: exposure proportional to the surplus over the floor;
  - the Turtles: -20% notional for each -10% drawdown;
  - pods: -5% halves capital.

  `github-projects.md`: Lean `isTrailing`, hummingbot `max_global_drawdown_quote`.
- **Pros**
  - Fixes the fixed floor's blind spot: a +15% run followed by a 25% giveback never trips a floor measured from the start.
  - Professional trailing caps of 4-10% are the norm the bot lacks.
- **Cons**
  - A trailing cap on noisy equity trips on variance alone. At 0.25% risk, annualised volatility is only about 3.8%, so a tight Y fires often.
  - The ladder variant is a state-dependent sizing rule that changes the trade record, so it needs a spec.
  - It needs a trustworthy equity series (E.3).
- **Fit.**
  - Latch-only: **`fits`**.
  - The ladder variant: **`needs envelope`** (a fixed, config-bounded lookup table, never self-tuning).
- **Priority.** **`next`** (latch). The ladder is `later`.
- **Effort.** `M`.

### B.4 Consecutive-loss guard (StoplossGuard-style)

- **Description.** If N losing exits occur within M bars, skip entries for K bars. It would be a stateless recompute from `trades` next to gate 13, default-OFF.
- **Source.** `github-projects.md` (freqtrade `StoplossGuard`; hummingbot `cooldown_time` 300 s).
- **Pros**
  - Standard in crypto bots.
  - Cheap, following the gate-13 pattern.
- **Cons**
  - It helps only if losses cluster (serial correlation of trade outcomes). Neither this bundle nor the verdicts show that for `decideHourly`.
  - With i.i.d. outcomes it leaves expectancy unchanged and only drops trades.
  - It makes the live record diverge from the replayed rule, which weakens the audit-log-reproducibility clause.
  - It adds three tunable parameters, which is multiplicity under the spec's §11 "multiplicity-aware" rule.
- **Fit.** **`fits`**.
- **Priority.** **`later`**. First run a cheap serial-correlation test on the existing 2,478-trade replay, and build only if clustering shows up.
- **Effort.** `S` for the test; `M` for the gate.

### B.5 Per-invocation broker-submit cap

- **Description.** Count order submissions per Edge Function invocation inside `_shared/alpaca.ts`'s guarded helpers, and throw past a small fixed N. `panic` liquidate needs an N that scales with open positions.
- **Source.** `github-projects.md` (nautilus `max_order_submit`); the CLAUDE.md incident rationale (#149).
- **Pros**
  - A third mechanical layer against runaway order loops, next to `checkGuard()` and the paper-only guard.
  - Small.
- **Cons**
  - Adds an error path to every mutating helper.
  - The panic exception must be designed carefully so the kill button is never blocked.
- **Fit.** **`fits`**.
- **Priority.** **`next`**.
- **Effort.** `S`.

### B.6 Branded "risk-approved order" type

- **Description.** `placeBracketOrder`, and the short path's market-plus-OCO pair, accept only a type that the gate-and-sizing stage can produce (`_shared/alpaca.ts`, `hourly-check/logic.ts`).
- **Source.** `github-projects.md` (barter `RiskApproved<T>`).
- **Pros.** Compile-time evidence that sizing and gates ran.
- **Cons**
  - Refactor churn.
  - The short path is two broker calls, so both need covering.
  - It adds no runtime protection beyond today's in-line gates.
- **Fit.** **`fits`**.
- **Priority.** **`later`**.
- **Effort.** `M`.

---

## Cluster C -- Research pipeline for a replacement edge

**Ranking basis.** Evidence (from `strategies.md`) × accessibility on Alpaca equities and ETFs × data feasibility × statistical power under the repo's `n_w` bar. Every item here is research only. A survivor becomes a *replacement* for `decideHourly` through the brainstorm, spec and ADR path. It is never a second live rule.

| Rank | Archetype (`strategies.md` #) | Evidence | Access | Data / power | Priority |
|---|---|---|---|---|---|
| 1 | Multi-ETF TSMOM with portfolio vol target (#1, #3) | academic, strong at breadth | daily ETFs, overnight | daily ETF bars are the easiest data class; few trend cycles in the post-2000 ETF era | `now` |
| 2 | Cross-sectional momentum on sector or country ETFs (#2) | academic (stock-level) | daily ETFs | clean (no single-stock survivorship); small cross-section | `next` |
| 3 | Turn of month, SPY (#4) | academic existence, weak after cost | daily SPY | trivial data; about 12 trades/yr, so underpowered | `later` |
| 4 | Pre-FOMC drift, SPY (#4) | academic | hourly SPY (staged) | about 8 events/yr, so underpowered; post-publication sample | `later` |
| 5 | Weekly large-cap reversal (#5) | academic, thin net | many shorts | needs a survivorship-free constituent history, not available on free feeds | `later` |
| 6 | Daily RSI(2) on index ETFs (#7) | practitioner | daily ETFs | easy data; negative skew | `later` |

### C.1 Pre-register a multi-ETF time-series momentum portfolio with volatility targeting

- **Description.** Freeze a pre-registration (the two-PR freeze/results discipline in `docs/research/README.md`) for a daily, monthly-rebalanced trend or TSMOM rule:
  - the lookback set is frozen up front;
  - the universe is a fixed multi-asset ETF list;
  - positions are inverse-volatility sized to a portfolio vol target, with per-instrument and aggregate notional caps and gap-aware costs;
  - it is evaluated through `backtest/overfitting_gate.py` (DSR and PBO) and recorded in `backtest/tested_cells.py`.

  It maps to the `multi_instrument_rotation` entry in `backtest/weekly_review.py::UNTESTED_CANDIDATES`. `backtest/baselines.py` already carries a `tsmom-12mo` baseline to build on.
- **Source.** `strategies.md` #1, #3, "What is realistically accessible", and implication 6; `2026-06-24-candidate-strategy-survey-first-cut.md`.
- **Pros**
  - The best-evidenced archetype in the bundle: Moskowitz-Ooi-Pedersen across 58 futures, and Hurst-Ooi-Pedersen positive in every decade since 1880.
  - Breadth is exactly what the repo's single-instrument kills lacked.
  - Monthly turnover is far below the hourly rule's 234 trades/yr, so the cost wall is lower.
  - Daily ETF bars are the most accessible data class here.
- **Cons**
  - ETF proxies are fewer and more correlated than 60+ futures.
  - Kim-Tse-Wald attribute much of the alpha to vol scaling, not the trend signal.
  - The post-2000 ETF history spans few trend cycles, so power is limited.
  - A 5-asset GTAA-lite already failed the after-tax Calmar bar. That is why C.2b's bar question must be settled first.
  - Passing means a different bot: overnight holds and multiple symbols, not a tweak of `hourly-check`.
- **Fit.** **`needs envelope`** for the eventual live strategy. The envelope:
  - a deterministic portfolio vol target with per-instrument and aggregate notional caps in `config.ts`;
  - gap-aware sizing (A.5);
  - per-symbol state keys (D.3);
  - B.2 and B.3 shipped first.

  The pre-registration itself touches no trading path.
- **Priority.** **`now`**, for the research step only.
- **Effort.** `L`.

### C.2 Cross-sectional momentum on sector or country ETFs

- **Description.** Rank a fixed ETF set (for example the SPDR sectors) on 12-1 month return and hold the top k behind an index regime filter. Pre-registered, sharing C.1's harness. It maps to `cross_sectional_rv` in `UNTESTED_CANDIDATES`.
- **Source.** `strategies.md` #2.
- **Pros**
  - A strongly replicated anomaly family.
  - An ETF universe sidesteps the single-stock survivorship problem the multi-symbol verdict (§5) describes.
  - Incremental on C.1's harness.
- **Cons**
  - The bundle's citations are stock-level; sector-ETF momentum is an extrapolation, not a cited result.
  - Momentum crashes (Daniel-Moskowitz).
  - About 11 names make ranks noisy.
  - The stock-level version needs survivorship-free constituent data the repo does not have.
- **Fit.** **`needs envelope`**: C.1's envelope plus a max-positions cap and a deterministic crash control (regime filter or vol scaling).
- **Priority.** **`next`**.
- **Effort.** `M` on top of C.1.

### C.2b Settle the promotion bar for diversifier candidates before C.1's results exist

- **Description.** In C.1's freeze PR, decide whether the stand-alone "after-tax Calmar vs SPY" bar (0 survivors in 364 cells, `reviews/2026-W42.md`) is the right acceptance test for a strategy whose value is low correlation to SPY. The alternative is a pre-registered portfolio-level test, for example the blend with SPY under the same DSR and PBO gate. This touches `backtest/overfitting_gate.py`, the pre-registration and the ledger docs.
- **Source.** `strategies.md` "Should we combine strategies?" (Dalio's "good, uncorrelated streams"; trend as a crisis diversifier, MOP 2012; value plus momentum, AMP 2013).
- **Pros**
  - Avoids rejecting the best-evidenced archetype on a test it was not designed to pass.
  - Settling it before results keeps the freeze discipline intact.
- **Cons**
  - Changing a bar after 364 failures looks like moving the goalposts. It must be argued on first principles and frozen before any C.1 number exists, or not at all.
  - A blended test can let a zero-edge stream through on variance reduction alone. `strategies.md` Pitfall 1 says the mean of the blend is the weighted mean, so the bar must still require a positive stand-alone mean.
- **Fit.** **`fits`**.
- **Priority.** **`now`**, inside C.1.
- **Effort.** `S`.

### C.3 Turn-of-month and C.4 pre-FOMC drift on SPY

- **Description.** Two frozen calendar rules:
  - turn of month: hold from the last trading day through the 3rd trading day;
  - pre-FOMC: hold 14:00 ET the day before to 14:00 ET on the announcement day, using a frozen calendar file.

  Daily SPY covers the first; the hourly SIP bars staged for #571 cover the second.
- **Source.** `strategies.md` #4.
- **Pros**
  - Zero discretion, a single symbol, trivial data and strong existence evidence (McConnell-Xu; Lucca-Moench).
- **Cons**
  - About 12 and about 8 events per year respectively, so roughly 120 and 85 events since 2016, which is weak power under the repo's bar.
  - Both mostly reallocate the equity premium in time. The "time out of SPY" family (Faber, GEM, vol targeting) all failed after tax.
  - Dichtl-Drobetz-style post-2003 decay for seasonality.
  - Both hold overnight, so each would be a replacement rule with its own spec.
- **Fit.** **`needs envelope`**: gap-based sizing, a hard stop plus a max hold, and frozen calendar windows (`strategies.md` #4).
- **Priority.** **`later`**.
- **Effort.** `M` each.

### C.5 Weekly large-cap reversal, C.6 daily RSI(2)

- **Description.** C.5 is a weekly market-neutral loser-minus-winner book in large caps. C.6 is a daily RSI(2) pullback on index ETFs with a mandatory stop.
- **Source.** `strategies.md` #5 and #7.
- **Pros**
  - C.5 rests on compensated liquidity provision (academic; 30-50 bp/week net in large caps, de Groot et al.).
  - C.6 is cheap to test on data the repo already has.
- **Cons**
  - **C.5:**
    - needs many simultaneous shorts and borrow checks;
    - needs a survivorship-free large-cap universe, which is data-blocked on free feeds;
    - its architecture is far from a bracket bot.
  - **C.6:**
    - practitioner-only evidence;
    - negative skew in its canonical no-stop form;
    - its family went 0/9 on 4h EUR/USD (`2026-07-15-forex-4h-survey-verdict.md`).
- **Fit.** **`needs envelope`**:
  - C.5 needs gross and net exposure caps, a per-name cap and borrow checks;
  - C.6 needs a hard stop, a time stop and gap sizing.
- **Priority.** **`later`**.
- **Effort.** C.5 `XL`; C.6 `M`.

### C.7 Pairs or stat-arb on ETF pairs

- **Source.** `strategies.md` #6.
- **Pros.** Market-neutral; academic origin (Gatev-Goetzmann-Rouwenhorst).
- **Cons**
  - Documented decay to about 0.24%/month by 2003-09 (Do-Faff).
  - A crowding blow-up (August 2007).
  - Two-legged orders and pair-break risk, the highest build complexity for the thinnest current edge.
- **Fit.** **`needs envelope`**: a pair-break stop, a max hold and a dollar-neutral gross cap.
- **Priority.** **`skip`**. The decayed edge does not justify the two-leg build.
- **Effort.** `XL`.

### C.8 The #672 mechanical proposal: full-power re-test of `donchian_breakout` / hourly / SPY

- **Description.** The W42 review's rule-derived next round (#672).
- **Source.** #672; `strategies.md` #1 ("per-instrument trend returns are weak", Kim-Tse-Wald); `2026-07-24-turtle-breakout-verdict.md` (0/12 at daily; hourly "worse than daily").
- **Pros.** Follows the documented priority rule and adds no new family multiplicity.
- **Cons**
  - The literature predicts failure for single-instrument trend.
  - Running it delays C.1, which tests the same economic source at the breadth the evidence requires.
- **Fit.** **`fits`**.
- **Priority.** **`skip`**. Override the mechanical proposal in the #672 thread in favour of C.1, and record the reason there.
- **Effort.** `M`.

### C.9 Re-tests of already-killed or weak intraday shapes

- **Description.** Intraday momentum, ORB, Ichimoku, Markttechnik's movement entry, and further candlestick or Heikin-Ashi variants.
- **Source.** `strategies.md` #9, #10, #12, #13 and #14, plus their Repo status lines.
- **Pros.** They have the same shape as the current stack (`fits`): single-symbol, intraday, bracketed.
- **Cons**
  - Each is NO_EDGE, DIRECTIONAL_NO_GO, data-blocked, or built from killed components.
  - `strategies.md`'s central finding: "the shape that fits the stack best is the shape the evidence supports least."
- **Fit.** **`fits`**.
- **Priority.** **`skip`**.
- **Effort.** `M` each.

### C.10 Volatility risk premium via defined-risk spreads, as a diversifier

- **Source.** `strategies.md` #11; `mvp2-pcs-riv-backtest.md` (KILL as a stand-alone rule); `mvp2-alpaca-options-data-spike.md`.
- **Pros**
  - The premium itself is academically established.
  - The KILL memo left a "diversifier only" thread open.
- **Cons**
  - Alpaca options history starts about 2024-01-18, and quotes are OPRA-gated on the free tier (data-blocked).
  - It needs a multi-leg options order path that neither `checkGuard()` nor the paper-only guard covers today.
  - Short-gamma tails.
- **Fit.** **`needs envelope`**: defined-risk spreads only, with max loss per spread as the risk unit, and the paper guard and `panic` extended to every options leg.
- **Priority.** **`later`**.
- **Effort.** `XL`.

---

## Cluster D -- Multi-strategy and combination architecture (design-only)

**Framing.** `strategies.md` answers the combination question directly: "Not yet." Diversification reduces variance, not the mean. The repo's own multi-symbol study moved Sharpe from -0.79 to -1.41 by spreading a negative mean. Everything in this cluster waits until at least one component clears C's gate.

### D.1 "Combine before sizing" as the only admissible combination shape

- **Description.** If a second component ever earns a place, it joins as part of **one** frozen composite rule that feeds one sizer and one risk layer. It replaces `decideHourly` rather than running beside it.
- **Source.** `github-projects.md` cross-cutting ranking (Lean `CompositeAlphaModel`, qlib ensembles); `strategies.md` "How combination is done" (Carver's forecast blending).
- **Pros**
  - Stays inside "One decision rule".
  - One risk layer, with netting before execution.
- **Cons**
  - Still a new rule, so the full brainstorm, spec and ADR path applies.
  - It requires at least two pre-registered, DSR/PBO-cleared positive components, and none exist.
- **Fit.** **`needs envelope`**: each component pre-registered and gate-cleared on its own, the composite frozen and LLM-free.
- **Priority.** **`later`**.
- **Effort.** `XL`.

### D.2 Separate sleeves under one portfolio risk budget, via a spec that amends the invariant

- **Description.**
  - Per-sleeve capital budget and per-sleeve drawdown latch (hummingbot V2 pattern).
  - A global drawdown stop.
  - A total open-risk cap, a per-direction cap and an aggregate notional cap (the Turtles' unit limits).
- **Source.** `github-projects.md`; `strategies.md` "What the invariants require" item 8.
- **Pros**
  - The safest way to run genuinely separate strategies.
  - Each sleeve stays independently auditable.
- **Cons**
  - "A second decision rule by definition."
  - Interacting sleeves weaken audit-log reproducibility.
  - Costs are paid twice.
  - One `paused` flag halts all sleeves.
- **Fit.** **`needs envelope`**: a fresh brainstorm and an ADR amending "One decision rule", per-sleeve latch keys, and a shared portfolio cap enforced in code.
- **Priority.** **`later`**.
- **Effort.** `XL`.

### D.3 Per-symbol and per-strategy state keys (prerequisite for C.1 and C.2 going live)

- **Description.** Re-key the shared state:
  - `bar_claims` has primary key `(script_name, bar_ts)` (`0011_bar_claims.sql`);
  - `hourly_kill_switch_active` / `_side` / `_fired_at` are global `bot_config` keys;
  - the equity-floor baseline is per experiment.

  Also add a K-position `panic` test.
- **Source.** The multi-symbol verdict §7; `github-projects.md` ("one latch key per signal").
- **Pros.** Required before any multi-symbol strategy can trade correctly. A fire on one symbol would otherwise block or misattribute all the others.
- **Cons**
  - Needs migrations.
  - No value until a multi-symbol strategy passes research.
- **Fit.** **`fits`**.
- **Priority.** **`later`**.
- **Effort.** `M`.

### D.4 Meta-labeling or an ML filter on `decideHourly`

- **Source.** `strategies.md` combination table.
- **Pros.** Professionals use it to filter false positives from rules that *have* edge.
- **Cons**
  - The primary rule's gross mean is about zero (-0.031R), so a filter cannot create edge from that.
  - A second fitted model brings leakage risk (QuantConnect reports) and new multiplicity.
- **Fit.** **`needs envelope`** (deterministic, frozen, non-LLM).
- **Priority.** **`skip`**.
- **Effort.** `L`.

### D.5 Regime switching between sub-strategies

- **Source.** `strategies.md` combination table; the retired 200-DMA rule (`docs/decisions/2026-07-27-deprecate-upro-regime-bot.md`).
- **Pros.** Intuitive.
- **Cons**
  - The classifier is itself a second fitted rule with its own overfitting risk.
  - No sub-strategy exists to switch between.
- **Fit.** **`needs envelope`** (a frozen deterministic classifier, behind a spec).
- **Priority.** **`skip`**.
- **Effort.** `L`.

### D.6 Spread `decideHourly` across more symbols

- **Source.** The multi-symbol verdict.
- **Cons.** DIRECTIONAL_NO_GO: 0 of 19 symbols showed EDGE, the overfitting gate failed on all three legs, and diversification made the loss more certain.
- **Fit.** **`fits`** (same rule).
- **Priority.** **`skip`**.

### D.7 Run a second strategy live beside `decideHourly` without a spec; or an LLM sentiment, regime or sizing overlay

- **Source.** `github-projects.md` (hummingbot's separate Condor LLM harness); the `swing-trading` roadmap's non-goals.
- **Pros.** Superficially attractive: "more signals", "smarter context".
- **Cons**
  - A parallel live rule breaks "One decision rule".
  - Any LLM in the decision or sizing seat breaks "No LLM in the trading path" and the README's risk-parameter rule.
- **Fit.** **`violates`**.
- **Priority.** **`skip`**.

---

## Cluster E -- Ops and hygiene

### E.1 Reconcile `docs/CURRENT_CONFIG.md`'s `HOURLY_SHORTS_ENABLED`

- **Description.** `docs/CURRENT_CONFIG.md:74` lists `false` and cites runbook statements that `false` is "non-negotiable". Yet the bot has placed SHORT entries since 2026-09-04 (13 of 42 trades, multi-symbol verdict §0, deviation 3).
  - Read the deployed value from `status` (its `shorts_enabled` field, #545) instead of inferring it.
  - Update `CURRENT_CONFIG.md` and the runbook lines it cites.
  - If no decision record exists for enabling shorts (none was found in `docs/decisions/`), record one.

  The first SHORT fills coincide with #635 (OCO body fix, 2026-09-04), so the flag may have been on earlier while the short path failed. Verify this; do not assume it.
- **Source.** #675 scope note; the multi-symbol verdict.
- **Pros**
  - The config-of-record is wrong about the bot's side exposure.
  - Short-only measured -0.165R on SPY, worse than long-only's -0.115R, which is material to A.1.
- **Cons.** Docs only, no behaviour change.
- **Fit.** **`fits`**.
- **Priority.** **`now`**.
- **Effort.** `S`.

### E.2 Alpaca's deprecated PDT fields

- **Description.** A grep on 2026-10-23 of `supabase/`, `scripts/`, `backtest/`, `strategy/`, `web/src/` and `tests/` for `pattern_day_trader`, `daytrade_count`, `daytrading_buying_power` and `multiplier` found no reads. The only `buying_power` hit is a reason string in the retired `daily-check/logic.ts:217`.
- **Source.** `strategies.md` corrections (PDT retired 2026-06-04).
- **Pros.** Nothing to fix.
- **Cons.** None.
- **Fit.** **`fits`**.
- **Priority.** **`skip`**: no action needed. Re-check only if an account-field reader is added.
- **Effort.** `S`.

### E.3 Equity series ownership after `daily-check`'s retirement

- **Description.** The only scheduled writer of `equity_snapshots` is `daily-check` (`daily-check/logic.ts:305`), whose entry crons `0013_retire_daily_check_cron.sql` unscheduled. `status` reads the table for trailing returns, and B.2, B.3 and #674 need a daily equity series.
  - First verify whether rows still accrue.
  - If they do not, move the snapshot write to `hourly-check` or to the daily-verification workflow, which already records `metrics.equity_usd`.
- **Source.** Codebase-driven.
- **Pros.** A brake or a dashboard figure built on a stale series is worse than none.
- **Cons.** It might already be handled elsewhere; this roadmap could not query the DB.
- **Fit.** **`fits`**.
- **Priority.** **`next`**. It precedes B.2 and B.3.
- **Effort.** `S`.

### E.4 Extend #674 (annualized ROI) with expectancy context

- **Description.** #674 is already filed. The extension: show mean R with its CI and SPY over the same window next to the annualized figure. The +0.12% over 3 weeks that prompted #674 is exactly the kind of short-window number the -0.139R baseline says not to over-read.
- **Source.** #674; the multi-symbol verdict §4.1.
- **Pros.** Keeps the dashboard from becoming an argument for A.3.
- **Cons.** Scope creep on an `S` issue.
- **Fit.** **`fits`**.
- **Priority.** **`next`**.
- **Effort.** `S`.

---

## Cross-cutting recommendations

### Top `now` items, ranked

1. **A.1 -- Run the review checkpoint on the incumbent and record the decision** (`S`). Every other choice depends on whether `decideHourly` keeps trading. Both checkpoint legs passed weeks ago, and three verdicts say the rule has a negative mean.
2. **A.2 -- Close #675 with an ADR: no risk increase on the incumbent; risk-leg-binding sizing is the design for any replacement** (`S`). It meets #675's own acceptance criteria and keeps the operator's chosen sizing design ready, without paying for it in expected loss.
3. **B.1 -- Reduce-only pause** (`M`). This is the only safety gap in this roadmap that exists at *any* size. Today a pause or the equity floor's auto-pause can leave an unflattened position whose day-TIF legs expire at the close. It also makes every future latching brake safe.
4. **C.1 with C.2b -- Pre-register the multi-ETF TSMOM / vol-target study, including the diversifier promotion-bar decision** (`L`). This is the only candidate in the roadmap aimed at the sign of the mean rather than the shape of the loss.
5. **E.1 -- Fix the `HOURLY_SHORTS_ENABLED` record** (`S`). The config of record is wrong about the bot's side exposure, which feeds directly into A.1.

### Explicit non-goals (`skip` / `violates`)

- **A.3** -- raising risk per trade on the current rule. It fits mechanically, but it scales a measured -0.139R/trade, a Kelly-negative bet, and it yields no information that small size does not.
- **C.8** -- #672's full-power re-test of single-SPY hourly Donchian. The literature predicts failure for single-instrument trend; spend the slot on C.1.
- **C.9** -- further re-tests of intraday momentum, ORB, Ichimoku, Markttechnik's movement entry or candlestick variants.
- **C.7** -- pairs or stat-arb (decayed edge, two-leg build).
- **D.4, D.5, D.6** -- meta-labeling the incumbent, regime switching, and spreading `decideHourly` across symbols.
- **D.7 (`violates`)** -- any second live strategy without a spec, and any LLM sentiment, regime or sizing overlay.
- **From `strategies.md` (`skip`):**
  - Wyckoff and Elliott as practised (judgement labellers in the path);
  - grid and martingale-DCA bots (no stop by design);
  - carry and market making (not accessible).

### Why the invariants rule out otherwise-attractive candidates

- **LLM overlays.** An LLM sentiment overlay, an LLM regime classifier or "conviction sizing" would put a non-deterministic model where it can set side, size or stop. That is exactly what "No LLM in the trading path" and the README's *"LLM must never control risk parameters"* forbid.
  - The v1.14 history in CLAUDE.md shows why: the model's non-determinism leaked through wherever it touched size or instrument choice.
  - The large frameworks surveyed keep LLMs at authoring or research time (jesse MCP, qlib RD-Agent). Hummingbot's one LLM-in-the-seat harness lives outside its core repo (`github-projects.md`).
- **Discretionary frameworks.** Wyckoff, Elliott and unfrozen Markttechnik need a human or model labeller in the loop, which breaks both the LLM rule and bar-reproducibility.
- **Parallel strategies.** Sleeves, regime switches, or simply "add a second bot" are attractive because diversification is real (N_eff 10.2 of 11 in the multi-symbol study). But they are a second decision rule. They also share one `paused` flag, one account and one set of global kill-switch keys, so they fail together and make entries depend on cross-sleeve state. The invariant does not forbid them forever. It forbids them *without* a brainstorm, a spec and an ADR, and the evidence says there is nothing positive to combine yet.

### What could actually move performance, and what is hygiene

Only a new edge can move trading performance. Every published sizing norm and loss limit in `strategies.md` assumes positive expectancy. Against a negative mean, sizing sets how fast the loss arrives, and brakes set how bumpy the path is and where it stops. The verdict's arithmetic says no calendar year is positive at any size. On a -0.139R rule, cost-aware sizing (A.4), a daily loss limit (B.2), a high-water-mark brake (B.3), a consecutive-loss guard (B.4), a submit cap (B.5) and typed orders (B.6) are all **hygiene**. They are worth having before size rises or a multi-symbol strategy goes live, because they cut the cost of being wrong. None of them changes the sign. B.1 is hygiene too, but it closes a tail path that exists today.

The items that could change the sign are in Cluster C, and realistically only C.1 (with C.2 as its follow-on). It is the one archetype with strong, multi-decade, multi-market evidence that this stack can reach on accessible data. Even it should be expected to fail more often than not here. ETF breadth is thinner than the futures breadth behind the evidence. Much of the documented alpha is vol scaling rather than signal. The repo's ledger stands at 0 survivors in 364 cells. An honest outcome of this roadmap may therefore be: decide the checkpoint (A.1), stop scaling the incumbent (A.2), keep the safety stack tight (B.1, E.1), and let one well-powered, pre-registered breadth study decide whether the bot has anything worth sizing up at all.
