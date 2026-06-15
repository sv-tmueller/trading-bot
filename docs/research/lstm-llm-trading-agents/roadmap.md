# Roadmap — LSTM/LLM Autonomous Trading Agents (synthesis against the live codebase)

**Scope.** Feature candidates clustered from `strategies.md` (15 merged EN+DE entries) and
`github-projects.md` (8 repos), mapped against the MVP 2.0 architecture: three Supabase Edge
Functions (`daily-check`, `kill-switch`, `panic`) over `supabase/functions/_shared/`
(`regime.ts`, `config.ts`, `alpaca.ts`, `marketdata.ts`, `db.ts`, `notifications.ts`), with the
single decision rule as a pure function in `supabase/functions/_shared/regime.ts` (1:1 port of
`strategy/regime.py`), and the Python research layer (`backtest/`, `strategy/regime.py`,
`main.py`). Every verdict is applied against the architectural invariants in `CLAUDE.md`: one
decision rule, reproducible from SPY history alone; no LLM in the trading path; deterministic
kill-switch / panic / broker-guard stack.

**What this bundle yields.** The surveyed genre (LSTM forecasters, LLM agent ensembles,
auto-retraining, 100-agent tournaments, 1%-daily claims) produced **zero adoptable signal
candidates** — the high-quality evidence is uniformly negative and the invariants exclude the
remainder by construction. The actionable output concentrates in **evaluation infrastructure for
the Python research layer**: the machinery to honestly judge any future signal proposal
(including whatever the #255 strategy brainstorm surfaces) before it gets near a spec. The
bundle's strongest single statistic — Quantopian's R² < 0.025 between backtest Sharpe and live
Sharpe (strategies.md #13) — is an argument for building the evaluation court first and trying
every defendant in it.

**Issue-state notes (2026-06-10).**
- **#255 (open, priority: high)** — goals-first brainstorm: beat SPY return at lower drawdown,
  risk-adjusted. Its mandatory evidence bar (out-of-sample/walk-forward, costs+slippage, no
  curve-fit, risk-adjusted measurement) is exactly what Cluster 1 builds. Candidates here do not
  pre-empt the brainstorm; they make its evidence gate executable.
- **#104 (closed 2026-06-06 as obsolete)** — the old walk-forward issue targeted the pre-pivot
  multi-signal parameter grid. Its closing comment explicitly invites "a much smaller, different
  task worth a fresh issue" for out-of-sample robustness checking of the single regime rule.
  Candidate 1.1 is that successor, re-scoped to robustness checking and #255's evidence gate —
  not parameter re-tuning.
- **#256 (open, design approved 2026-06-10)** — `daily-check` moves to post-open execution with
  market-on-open semantics. `backtest/regime.py` already executes at the next day's open, so the
  research layer's execution model matches the approved design; candidate 1.1 must preserve that
  cadence fidelity.
- **#229 (open)** — paper soak, informational-only pending #255. Candidate 2.2 extends it rather
  than re-proposing it.
- **#227, #185, #230** — operational items outside this bundle's evidence base; nothing here
  touches them.

**How to read.** Every candidate has a fit verdict (**`fits`** / **`needs envelope`** /
**`violates`**), a priority (**`now`** / **`next`** / **`later`** / **`skip`**), and a rough
effort (`S` ≤ 1 day, `M` 1–5 days, `L` 1–3 weeks, `XL` multi-month/research-grade). `skip` is
the modal verdict for Cluster 3 by design — this bundle is an evidence check on a genre, and the
evidence failed.

**Date: 2026-06-10.**

| # | Candidate | Fit | Priority | Effort |
|---|---|---|---|---|
| 1.1 | Walk-forward evaluation harness (successor to closed #104) | fits | now | M |
| 1.2 | Deterministic baseline suite (B&H, persistence, 10-mo SMA, 12-mo TSM) | fits | now | M |
| 1.3 | Whipsaw + cost-drag quantification for UPRO gating | fits | now | S |
| 1.4 | Overfit-guard metrics: deflated Sharpe + PBO | fits | next | M |
| 1.5 | Python↔TypeScript signal-parity fixtures | fits | next | S |
| 1.6 | Backtest experiment record | fits | next | S |
| 2.1 | Hysteresis/band variant of the 200-DMA (research-layer eval only) | needs envelope | later | M |
| 2.2 | Paper-soak scorecard (extension of #229) | fits | next | M |
| 2.3 | Dedicated market-data validation pass in `marketdata.ts` | fits | later | S |
| 3.1 | Learned directional signal (LSTM/TSFM/RL/boosted trees) in the decision path | violates | skip | XL |
| 3.2 | LLM in the decision path (agent ensembles, sentiment scoring, LLM risk debate) | violates | skip | XL |
| 3.3 | Multi-agent tournament / N-agent showcase evaluation | violates | skip | L |
| 3.4 | Auto-retraining / drift-detection pipeline | violates | skip | L |
| 3.5 | Calendar-anomaly stacking (Stagge-style Saisonalität) | needs envelope | skip | M |

---

## Cluster 1 — Evaluation infrastructure (Python research layer)

The common thread: qlib and freqtrade — the only two surveyed projects with real users — treat
the signal as a small swappable component and pour their engineering into *evaluation*. That is
the importable lesson, and it lands entirely in `backtest/`, never in the trading path.

### 1.1 Walk-forward (rolling-window) evaluation harness for the regime rule

- **Description** — New `backtest/walkforward.py` driving the existing simulator
  (`backtest/regime.py`) through rolling in-sample/out-of-sample windows, replaying the live
  daily decision cadence (signal at close, execution next open — already matching the
  #256-approved market-on-open semantics), aggregating per-window OOS metrics (CAGR, max
  drawdown, Calmar, Sharpe); CLI wired through `main.py`.
- **Source** — github-projects.md: microsoft/qlib (rolling train/score window pattern — "the
  reference implementation"); freqtrade/FreqAI ("backtest emulates the live cadence");
  strategies.md cross-cutting ("the strongest argument yet for prioritizing the walk-forward
  harness"). Successor to closed #104, scoped per its closing comment.
- **Pros**
  - The bundle's central negative results (Quantopian R² < 0.025; FinRL's own backtest-overfitting
    concessions) say in-sample numbers in this domain are close to meaningless — OOS evaluation
    is the only defensible currency, and #255's evidence bar requires it explicitly.
  - Built once, reused for every future candidate: SMA/TSM variants (1.2), hysteresis bands
    (2.1), and anything the #255 survey proposes.
  - Replaying the production cadence (rather than vectorizing over the whole history) keeps the
    evaluated artifact equivalent to the deployed one — FreqAI's one structural insight.
- **Cons**
  - The single rule has few free parameters, so "fitting" reduces to robustness sweeps; the
    closed #104's critique (a re-tuning harness contradicts the one-rule design) still applies
    if scope drifts into optimization.
  - Window length/step are researcher degrees of freedom — they must be fixed before results are
    read, not after.
  - UPRO's real history starts 2009: no deep-bear OOS window exists on real data (PR #254's
    synthetic-data caveat carries over).
- **Fit with the deterministic-risk invariant** — **`fits`** (research layer only; pure
  simulation over price history; touches no Edge Function).
- **Priority** — `now`.
- **Rough effort** — `M`.

### 1.2 Deterministic baseline suite

- **Description** — New `backtest/baselines.py`: fee-adjusted buy-and-hold (SPY and the
  vehicle), a persistence/naive rule (long iff yesterday's close > prior close — the trading
  analog of the forecasting persistence baseline), and the live rule's two academic siblings —
  10-month SMA (Faber) and 12-month time-series momentum — reported alongside every harness run.
- **Source** — strategies.md #15 (trend-following/200-DMA family: 10-mo SMA, 12-mo TSM as the
  best-evidenced variants, ~140y record); github-projects.md: SC4RECOIN/LSTM-Crypto-Price-Prediction
  (~80% validation accuracy still lost 11% vs B&H +6.5% after fees — report fee-adjusted P&L,
  never accuracy), yacoubb/stock-trading-ml (a persistence baseline instantly disqualifies the
  next-price-LSTM class).
- **Pros**
  - Cheap and permanent: any future proposal that cannot beat fee-adjusted buy-and-hold and a
    naive baseline out-of-sample is dead before a spec is written — this single check would have
    killed the entire surveyed genre.
  - Makes #255's honest fallback ("hold 1× SPY and ship nothing") a measurable outcome rather
    than a rhetorical one.
  - 10-mo SMA and 12-mo TSM give the deployed rule its two strongest-evidenced relatives as
    robustness comparators — parameter-robustness work, not signal replacement.
- **Cons**
  - Variant baselines can quietly become a tuning grid; the suite is for benchmarking — adopting
    any variant still gates behind a fresh brainstorm + spec.
  - Monthly-resample rules (10-mo SMA, 12-mo TSM) need careful point-in-time alignment with the
    daily simulator to avoid look-ahead.
- **Fit with the deterministic-risk invariant** — **`fits`** (pure price/calendar functions,
  research layer only).
- **Priority** — `now`.
- **Rough effort** — `M`.

### 1.3 Whipsaw + cost-drag quantification for UPRO gating

- **Description** — Extend `backtest/regime.py`'s trade-ledger reporting: round-trip counts and
  loss clustering, annualized cost drag with a slippage/commission sensitivity sweep, the
  whipsaw-loss share of total P&L, and a cash-yield toggle (T-bill rate instead of 0%).
- **Source** — strategies.md #15 cons (Fairvalue: 90 losing vs 37 winning trades of 263;
  ~0.8%/yr tax+cost drag can erase the edge); codebase-driven
  (`docs/research/2026-06-05-regime-backtest-pl-winrate.md` flags its own win-rate statistics as
  coarse and its 0%-cash assumption as conservative).
- **Pros**
  - Small, direct input to #255: quantifies the rule's one documented weakness (sideways-market
    whipsaw) on the one vehicle (3×) where whipsaw is amplified.
  - The cost-sensitivity sweep doubles as honesty insurance for every later harness run — the
    genre's results die at 10–25 bps (strategies.md #4); ours should be shown to survive them.
- **Cons**
  - Daily bars only: the kill-switch interplay stays unmodelled (no intraday data in the
    yfinance feed), so drawdown figures remain approximate in the same way the 2026-06-05 doc
    already caveats.
- **Fit with the deterministic-risk invariant** — **`fits`** (reporting only).
- **Priority** — `now`.
- **Rough effort** — `S`.

### 1.4 Overfit-guard metrics: deflated Sharpe ratio + PBO

- **Description** — Add deflated-Sharpe-ratio and probability-of-backtest-overfitting (CSCV)
  computation to the harness output (`backtest/`, alongside 1.1) whenever more than one variant
  is compared, so selection bias across N trials is quantified instead of ignored.
- **Source** — keywords.md (Backtest Integrity & Overfitting Pathologies: Deflated Sharpe Ratio,
  PBO, CSCV, multiple-testing bias); strategies.md #13 (Quantopian: backtest Sharpe had
  essentially no predictive power for live performance — in-sample winners are noise).
- **Pros**
  - Turns "we tried 12 variants and picked the best" from silent overfitting into a measured
    probability — the literature's standard answer to multiple-testing bias.
  - Inoculates the in-house process against the 100-agents pattern: selecting a winner from N
    trials is the same statistical sin at any N, tournament or notebook.
- **Cons**
  - CSCV is fiddly to implement correctly and easy to mis-apply with few variants; with the
    small variant counts expected here it produces wide error bands — it informs, it does not
    decide.
  - Only meaningful once 1.1/1.2 exist; pointless standalone.
- **Fit with the deterministic-risk invariant** — **`fits`** (metrics only).
- **Priority** — `next`.
- **Rough effort** — `M`.

### 1.5 Python↔TypeScript signal-parity fixtures

- **Description** — One shared fixture file (JSON of regime-input → expected-output cases:
  NaN-SMA defensive CASH, equality-is-bearish, kill-switch flag clear/preserve) consumed by both
  `tests/test_strategy_regime.py` and `supabase/functions/_shared/regime.test.ts`, so research
  results provably describe the deployed rule.
- **Source** — github-projects.md: FinRL (train → backtest → paper as one pipeline: the artifact
  you evaluate is byte-identical to the one you deploy); codebase-driven (`regime.ts` is
  documented as a 1:1 port of `strategy/regime.py`, currently enforced by review, not fixtures).
- **Pros**
  - Cheap, permanent protection of the load-bearing claim that backtests describe production.
  - Catches silent drift if either side changes first — e.g. a future hysteresis variant (2.1)
    landing in one language before the other.
- **Cons**
  - Both functions are ~40 lines and stable, so the risk insured is small today.
  - A tiny new fixture-format convention to maintain across two test suites.
- **Fit with the deterministic-risk invariant** — **`fits`** (tests only).
- **Priority** — `next`.
- **Rough effort** — `S`.

### 1.6 Backtest experiment record

- **Description** — Append-only run record (CSV/JSONL under `docs/research/`, written by the
  harness CLI in `main.py`/`backtest/`) capturing config, git SHA, and metrics per backtest run
  — the research-side analog of `audit_log`.
- **Source** — github-projects.md: microsoft/qlib (experiment recorder — every run logged with
  config + metrics, comparable across runs); codebase-driven (results currently live in
  hand-written dated docs like `2026-06-05-regime-backtest-pl-winrate.md`, which will not scale
  to a #255 candidate survey).
- **Pros**
  - Makes runs comparable across sessions and agents; prevents quiet cherry-picking of the best
    run (failed runs get logged too — that is the point).
  - Nearly free once 1.1 exists.
- **Cons**
  - Another artifact to keep tidy; value depends entirely on the discipline of logging every
    run, not just the flattering ones.
- **Fit with the deterministic-risk invariant** — **`fits`** (bookkeeping only).
- **Priority** — `next`.
- **Rough effort** — `S`.

---

## Cluster 2 — Deterministic variants and read-only operations

### 2.1 Hysteresis / band variant of the 200-DMA (whipsaw damper) — research-layer evaluation only

- **Description** — Evaluate entry/exit bands (e.g. enter at SMA+x%, exit at SMA−y%) and/or
  N-day confirmation as pure-function variants of `strategy/regime.py`, run through 1.1/1.2/1.4
  in `backtest/` — explicitly *not* a change to `supabase/functions/_shared/regime.ts`.
- **Source** — strategies.md #15 (envelope bands / hysteresis as deterministic whipsaw dampers;
  cross-cutting: "the supported research action is parameter-robustness work, not signal
  replacement"). Relates to #255.
- **Pros**
  - Targets the rule's one documented weakness — whipsaw (1.3 will quantify ours; Fairvalue
    counted 90 losing trades of 263) — while remaining a pure function of price history:
    auditable, reproducible, zero inference cost.
  - The only candidate in this bundle with any plausible path to improving realized
    risk-adjusted performance.
- **Cons**
  - Adds two parameters — exactly the curve-fitting surface 1.4 exists to police; the literature
    expects a trade-off (fewer whipsaws bought with later entries/exits), not free return.
  - Premature before #255 fixes the target metric (Calmar vs Sharpe vs raw CAGR changes which
    variant "wins").
- **Fit with the deterministic-risk invariant** — **`needs envelope`** — envelope: evaluation
  confined to `backtest/`; any live adoption modifies the single decision rule and gates behind
  a fresh brainstorm + spec per `CLAUDE.md`.
- **Priority** — `later` (blocked on #255 goal-setting and on 1.1/1.2 existing).
- **Rough effort** — `M`.

### 2.2 Paper-soak scorecard (extension of #229)

- **Description** — Read-only script (`scripts/` or `backtest/`) that joins `audit_log`,
  `regime_state`, and `trades` from the Supabase dev project against realized SPY/UPRO prices
  and reports the live-to-backtest gap: decision-by-decision agreement with the simulator,
  realized vs modelled slippage (5 bps), fee-adjusted P&L vs the 1.2 baselines.
- **Source** — github-projects.md: FinGPT (benchmark framing — score predictions against
  realized outcomes on a held-out window), FinRL (paper-trading loop as the live end of one
  pipeline); strategies.md #13 (the backtest–live gap is the genre's graveyard). Extends #229
  (base shipped: the soak is running; this makes its data decision-grade).
- **Pros**
  - Converts the soak from uptime monitoring into evidence for #255's bar — the live-to-backtest
    gap is precisely the statistic the surveyed genre never publishes.
  - The natural place where #256's paper-vs-live fill-behavior question (paper may simulate
    outside-hours fills that live queues) becomes measurable once the fix lands.
  - Read-only: touches no trading path, no Edge Function.
- **Cons**
  - The soaked strategy is under direction review (#255), so the scorecard may end up scoring a
    strategy that gets retired — though the harness-fidelity measurement transfers to any
    successor.
  - One decision per day: statistically meaningful claims take a long soak.
- **Fit with the deterministic-risk invariant** — **`fits`** (read-only reporting).
- **Priority** — `next`.
- **Rough effort** — `M`.

### 2.3 Dedicated market-data validation pass in `marketdata.ts`

- **Description** — Factor bar-sanity checks into a validation step in
  `supabase/functions/_shared/marketdata.ts` (monotonic dates, gap tolerance, positive/finite
  prices, bar count vs requested) instead of relying solely on `daily-check/logic.ts`'s
  stale-data guard plus `requireNumber`; use the donor's edge-case test files as a coverage
  checklist for `marketdata.test.ts`.
- **Source** — github-projects.md: TauricResearch/TradingAgents (`market_data_validator` — the
  one borrowable idea from the flagship LLM repo, plus its per-edge-case test discipline).
- **Pros**
  - Deterministic hardening of the data the one decision rule consumes; garbage-bar failure
    modes (IEX feed quirks, `adjustment=raw` artifacts around splits) currently surface only if
    they happen to trip the NaN/stale checks.
- **Cons**
  - Production-path change while #256 is reworking `daily-check` execution — sequencing pressure
    for low urgency.
  - Existing guards (stale-data skip, `requireNumber`, the #242 finite guard) already cover the
    worst observed cases; no incident has demonstrated the gap — YAGNI risk.
- **Fit with the deterministic-risk invariant** — **`fits`** (a stricter deterministic guard,
  no decision change).
- **Priority** — `later`.
- **Rough effort** — `S`.

---

## Cluster 3 — Non-goals from the genre (explicit skips)

Recorded so the verdicts are citable the next time the genre resurfaces. None of these are
backlog items.

### 3.1 Learned directional signal (LSTM / GRU / TSFM / RL policy / boosted trees) in any decision path

- **Description** — Would replace or augment `computeTargetState`
  (`supabase/functions/_shared/regime.ts`, `strategy/regime.py`) with a trained model. Listed
  only to record the verdict.
- **Source** — strategies.md #1 (LSTM: below-coin-flip OOS directional accuracy, persistence
  artifact, independent negative thesis record in two languages), #2 (foundation models lose to
  boosted trees on returns), #3 (FinRL's own authors concede sim-to-real is unsolved), #5
  (cross-sectional ML edge falls 62–80% excluding untradeable names); github-projects.md:
  yacoubb, SC4RECOIN (the genre's honest member lost 11% vs B&H +6.5% after fees).
- **Pros** — None demonstrated: the bundle's entire high-quality evidence base is negative on
  this class net of costs, out-of-sample.
- **Cons** — Training is non-reproducible from price history (random init, GPU nondeterminism;
  vendor-served checkpoints add silent version drift), breaking the
  reproducible-from-SPY-history property by construction; adds a second decision rule.
- **Fit with the deterministic-risk invariant** — **`violates`** (one decision rule;
  reproducibility).
- **Priority** — `skip` — the model class fails its own academic benchmarks before the
  invariants are even consulted.
- **Rough effort** — `XL`.

### 3.2 LLM in the decision path (agent ensembles, news/sentiment scoring, LLM risk debate)

- **Description** — Any TradingAgents/FinMem/ai-hedge-fund-style persona ensemble or
  Lopez-Lira-style headline scorer feeding `daily-check`. Listed only to record the verdict.
- **Source** — strategies.md #4 (the best-evidenced LLM result is pre-cost, high-turnover,
  cross-sectional small-cap long-short — inexpressible by a single-asset regime bot), #6
  (memorization makes LLM backtests non-identified; live benchmark results don't transfer), #10
  (heise: identical prompt → five materially different portfolios); github-projects.md #1–#2
  (neither flagship repo connects to a broker; both disclaim real trading — 145k combined stars
  of authors who don't trust their own systems with execution).
- **Pros** — None that survive the evidence; even the strongest paper's profits die at realistic
  costs.
- **Cons** — Non-determinism, silent model-version drift, per-decision cost, and unauditability
  — the v1.14 failure mode this repo already retired once.
- **Fit with the deterministic-risk invariant** — **`violates`** invariant 2 ("no LLM in the
  trading path") — which has no envelope by definition.
- **Priority** — `skip` — Claude's role stays where both literatures say it adds value:
  research assistant and development tooling, never execution.
- **Rough effort** — `XL`.

### 3.3 Multi-agent tournament / N-agent showcase evaluation

- **Description** — Running N strategy variants or agents in parallel and promoting recent
  winners (the 100-agents format; Alpha Arena at the credible end). Listed only to record the
  verdict.
- **Source** — strategies.md #7 (Alpha Arena: 4 of 6 frontier LLMs −30…−63% in ~2 weeks;
  Sentient liquidated after evolving "trillions" of virtual traders), #9 (the 1%-daily/100-agent
  format: survivorship engine, zero verifiable track record), #13 (Quantopian R² < 0.025 —
  in-sample winners are noise).
- **Pros** — The format's one honest contribution (live public PnL) is already refuted by its
  own results; the sole winner's profile (lowest trade frequency, hard stops) is what this bot
  has by construction.
- **Cons** — Selection-from-N-trials is institutionalized backtest overfitting; a tournament is
  a presentation device, not an evaluation methodology.
- **Fit with the deterministic-risk invariant** — **`violates`** (the agents are model-driven;
  ex-post winner selection breaks reproducibility of the "strategy").
- **Priority** — `skip` — the legitimate kernel (comparing N variants honestly) is candidate
  1.4, done with multiple-testing corrections instead of a leaderboard.
- **Rough effort** — `L`.

### 3.4 Auto-retraining / drift-detection pipeline

- **Description** — Scheduled or drift-triggered retraining of a market model (the genre's
  "agents retrain themselves daily" pitch). Listed only to record the verdict.
- **Source** — strategies.md #8 (retraining chases a moving target; drift-triggered ≈ scheduled
  on accuracy, saves compute not alpha); github-projects.md: freqtrade/FreqAI and qlib are the
  well-engineered versions — and their borrowable idea (backtest replays the live cadence;
  rolling windows) is already captured in candidate 1.1.
- **Pros** — Legitimate MLOps hygiene *if* a model worth maintaining existed; none does (3.1).
- **Cons** — Continuous retraining destroys decision reproducibility — yesterday's decision can
  no longer be reproduced from price history plus a fixed rule; the 200-DMA has no trainable
  weights, and that is a feature, not a gap.
- **Fit with the deterministic-risk invariant** — **`violates`** (reproducibility).
- **Priority** — `skip` — borrow the evaluation cadence (1.1), not the retraining treadmill.
- **Rough effort** — `L`.

### 3.5 Calendar-anomaly stacking (Stagge-style Saisonalität)

- **Description** — Benchmarking deterministic calendar rules (Turnaround Tuesday, month-end
  effects, etc.) against the 200-DMA baseline in `backtest/`. Listed because it is the only
  genre-adjacent entry sharing the bot's reproducibility property.
- **Source** — strategies.md #14.
- **Pros** — Fully deterministic, pure calendar+price functions; auditable; philosophically
  compatible with the architecture.
- **Cons** — Public evidence is promotional (course/broker funnel; per-strategy live numbers
  undisclosed); calendar anomalies are notorious data-mining targets that decay
  post-publication; stacking N micro-edges means N decision rules and multiplied costs.
- **Fit with the deterministic-risk invariant** — **`needs envelope`** — envelope:
  research-layer benchmarking in `backtest/` only; any live adoption breaches the
  one-decision-rule invariant and gates behind a fresh brainstorm + spec.
- **Priority** — `skip` — not worth research effort ahead of #255's goal-setting, and the
  promotional evidence base does not justify queue-jumping the better-evidenced 10-mo-SMA /
  12-mo-TSM comparisons already in candidate 1.2.
- **Rough effort** — `M`.

---

## Cross-cutting recommendations

### Highest-leverage `now` items, ranked

1. **1.1 Walk-forward evaluation harness** (`backtest/walkforward.py`) — qlib's rolling-window
   pattern plus FreqAI's live-cadence-replay discipline, applied to the existing simulator. The
   bundle's strongest finding (backtests don't predict live results; Quantopian R² < 0.025)
   makes this the precondition for trusting anything else, and #255's evidence bar requires it.
2. **1.2 Deterministic baseline suite** (`backtest/baselines.py`) — fee-adjusted buy-and-hold,
   persistence, 10-month SMA, 12-month TSM. The cheapest permanent filter: any future signal
   proposal that can't clear these out-of-sample is dead on arrival, which would have disposed
   of the entire surveyed genre in one report.
3. **1.3 Whipsaw + cost-drag quantification** (extends `backtest/regime.py` reporting) — the
   numbers #255 needs about the incumbent: whipsaw share of P&L, cost sensitivity, cash-yield
   effect, on the 3× vehicle where these bite hardest.

Sequencing: 1.3 can land independently; 1.4/1.5/1.6 hang off 1.1's skeleton; 2.1 waits for #255
to fix the target metric.

### Explicit non-goals

Everything in Cluster 3, recorded as standing verdicts: **no LSTM/GRU/foundation-model/RL/
boosted-tree directional signal in any decision path** (3.1); **no LLM anywhere in the trading
path** — no agent ensembles, no sentiment scoring, no LLM "risk debate" (3.2); **no multi-agent
tournament or N-agent showcase structures** (3.3); **no auto-retraining or drift-triggered
model pipelines** (3.4); **no calendar-anomaly stacking for now** (3.5, the one `skip` that is
evidence-starved rather than invariant-violating); and categorically, **nothing from the
1%-daily / 100-agents genre** (strategies.md #9), which offers no verifiable track record to
evaluate and whose arithmetic refutes itself.

### Why the invariants rule out the otherwise-attractive candidates

The two genuinely tempting results in the survey both fail on the same two grounds. Lopez-Lira &
Tang's news-sentiment result (strategies.md #4) is the best-evidenced LLM-finance finding, but
it requires an LLM at decision time (invariant 2 has no envelope) and a cross-sectional
long-short book a single-asset SPY-regime bot cannot express; Gu–Kelly–Xiu cross-sectional ML
(#5) is peer-reviewed and replicated, but its edge lives in microcaps, dies under costs, and
would trade the one-decision-rule invariant for a near-zero net edge. The invariants are not
costing this project alpha: every scaled live test of the alternatives (AIEQ behind cheap beta,
Sentient liquidated, Alpha Arena's modal agent down 30–63%, Quantopian's backtest-live R² near
zero) shows the deterministic constraint set is filtering out *negative* expected value. The
reproducibility-from-price-history property is also what makes `audit_log` forensics and the
panic/kill-switch guarantees meaningful — a learned signal would silently void them.

### Performance vs. operational hygiene — the honest paragraph

None of the `now` items moves trading performance; they build the court in which any
performance claim must be tried, and their realistic best outcome is *preventing* a
performance-destroying adoption. The only candidate with a plausible path to better realized
numbers is 2.1 (hysteresis/band variant), and the literature's honest expectation there is a
trade-off — fewer whipsaw losses bought with later entries and exits, i.e. possibly better
Calmar, probably not better raw return. The uncomfortable backdrop, per PR #254 and #255: the
incumbent strategy roughly matched SPY's return at about twice the drawdown over the real-data
era, and nothing in this bundle fixes that — the genre surveyed here is an evidence desert, and
the strong-evidence family (trend filters, strategies.md #15) is already the deployed rule,
honestly characterized by both literatures as risk management rather than return enhancement.
If the #255 survey finds nothing that clears the 1.1/1.2/1.4 evidence gate, the infrastructure
built here is what makes "hold 1× SPY and ship nothing" a provable conclusion instead of a
disappointment — which is precisely the outcome a deterministic, auditable process should be
able to reach.
