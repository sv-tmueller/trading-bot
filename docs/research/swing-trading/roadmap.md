# Swing-Trading Roadmap — Research Artifact

**Scope.** A clustered map of feature candidates for this bot, derived from `strategies.md` (15 strategies, EN+DE survey) and `github-projects.md` (8 peer repos). Each candidate is graded against the architectural invariant in `CLAUDE.md` — *"the LLM must never control risk parameters directly"* — and against what is already shipped in v1.10 (exposure gate), v1.11 (trailing stop), and v1.12 (earnings blackout).

**This is not an implementation plan.** No code, no test specs, no new agents proposed. Priorities and effort estimates are research-grade, not commitments.

**How to read.** Every candidate has a fit verdict (`fits` / `needs envelope` / `violates`), a priority (`now` / `next` / `later` / `skip`), and a rough effort (`S` ≤ 1 day, `M` 1–5 days, `L` 1–3 weeks, `XL` multi-month). When a base capability is already shipped, the entry proposes the *extension*, not the base.

**Date: 2026-04-30.**

---

## Cluster 1 — Multi-timeframe confirmation

### 1.1 Weekly trend gate on top of daily entry

- **Description** — Before any approved candidate is sent to `team_leader`, require price > weekly EMA(20) and weekly EMA(20) > weekly EMA(50). Implemented as a deterministic check in `tools/market_data.py` (new `compute_weekly_trend`) and consumed by `agents/risk_review.py` as a veto.
- **Source** — strategies.md #5 (pullback-to-MA), #14 (Weinstein 30-week SMA), #11 (Ichimoku weekly bias).
- **Pros**
  - Suppresses counter-trend daily-bar entries that have hurt the 5y backtest baseline (35% win rate, 2862 max-exposure rejects per memory).
  - Pure deterministic filter — no LLM judgement involved.
  - Cheap: one extra `fetch_bars(timeframe="1Week")` call per candidate.
- **Cons**
  - Reduces signal frequency further on top of an already-thin pipeline (5y baseline already trade-starved).
  - Weekly bars need ≥ 50 weeks of history; ticker-IPO edge cases must be handled.
  - Adds a parameter (weekly EMA periods) to the grid that walk-forward must cover.
- **Fit with the deterministic-risk invariant** — Pure pre-filter computed deterministically, consumed as a boolean veto. **`fits`**.
- **Priority** — `next`.
- **Rough effort** — `M`.

### 1.2 Higher-timeframe alignment score (daily/weekly/monthly stack)

- **Description** — Compute an alignment score across daily, weekly, monthly EMAs and surface it to `risk_review` as a sizing modifier (e.g. half-size when only 2/3 align). Touches `tools/market_data.py`, `tools/risk.py`.
- **Source** — strategies.md #11 (Ichimoku), #14 (Weinstein); github-projects.md is silent on multi-TF.
- **Pros**
  - Smoother than a binary gate — keeps trades flowing in mixed regimes.
  - Empirically attractive in trend-following literature.
- **Cons**
  - Sizing modifiers couple the regime detector to the risk module, which complicates auditing.
  - Monthly bars on small symbols can be noisy / incomplete.
  - Adds two more knobs to the parameter grid.
- **Fit with the deterministic-risk invariant** — Sizing modifier touches risk math, but math is deterministic from the score. **`needs envelope`** — modifier must be a fixed lookup table, not an LLM-tunable value.
- **Priority** — `later`.
- **Rough effort** — `L`.

---

## Cluster 2 — Market-regime detector

### 2.1 SPY 200-day-SMA regime gate

- **Description** — Compute SPY-above-its-200-day-SMA once per scan and treat as a master kill-switch for new longs (or down-size to 50%). New `tools/regime.py`, consumed by `risk_review.py`.
- **Source** — strategies.md #4 (Connors 200-SMA filter), #6 (momentum crash literature), #14 (Weinstein); github-projects.md gr8monk3ys `factors/` regime detector.
- **Pros**
  - Tiny code, large historical impact: SPY-below-200 is when momentum strategies suffer their worst drawdowns.
  - One deterministic input, no LLM involved.
  - Auditable — single boolean logged in `agent_logs`.
- **Cons**
  - 200-day SMA whipsaws around regime turns (2023 H1, 2020 Q2).
  - SPY is one index — for a single-name US-equity book it's the right proxy, but not perfect.
- **Fit with the deterministic-risk invariant** — **`fits`**. This is the canonical example of a deterministic veto.
- **Priority** — `now`.
- **Rough effort** — `S`.

### 2.2 ADX-based volatility/trend regime classifier

- **Description** — Compute ADX(14) on each candidate; classify into trend / range / chop. Strategy-specific gating: trend setups only when ADX > 20, mean-reversion (if ever introduced) only when ADX < 20. New `tools/regime.py`.
- **Source** — strategies.md #7 (Bollinger MR with ADX filter), #2 (Donchian breakout robustness).
- **Pros**
  - Per-symbol regime, not just market-wide.
  - Standard, deterministic indicator — no judgement.
- **Cons**
  - ADX is a lagging indicator; threshold (20 vs 25) is a parameter to fit.
  - Most useful when paired with a mean-reversion strategy we don't currently run.
- **Fit with the deterministic-risk invariant** — **`fits`**. Pure indicator math.
- **Priority** — `next`.
- **Rough effort** — `S`.

### 2.3 Weinstein 30-week stage classifier

- **Description** — For each candidate, classify Stage 1/2/3/4 against the 30-week SMA and its slope. Veto Stage 3 and Stage 4 longs at the `risk_review` layer. New `tools/regime.py::classify_stage`.
- **Source** — strategies.md #14 (canonical).
- **Pros**
  - Cleanest single-symbol regime filter in the practitioner literature.
  - Mechanically simple — slope sign + price-vs-MA.
  - Pairs with relative-strength selection (cluster 4).
- **Cons**
  - 30-week SMA reacts slowly; entries lag.
  - 150 trading days of history needed — IPO edge cases.
- **Fit with the deterministic-risk invariant** — **`fits`** as a veto layer.
- **Priority** — `next`.
- **Rough effort** — `M`.

---

## Cluster 3 — Pattern recognition (deterministic only)

### 3.1 Bull-flag detector

- **Description** — Geometric detector for flagpole (N-bar advance ≥ X%, low retrace) + flag (M-bar tight pullback in descending channel) + breakout (close above flag high on volume ≥ 1.5× ADV). New `tools/patterns.py`. Output consumed by `strategy.py` as an additional candidate source — LLM ranks among detected flags, doesn't invent them.
- **Source** — strategies.md #9 (bull flag, verdict `fits`).
- **Pros**
  - Codifiable end-to-end.
  - Tight stops below flag low — small per-trade risk consistent with `RISK_PER_TRADE` discipline.
  - Measured-move target gives an explicit R:R input.
- **Cons**
  - Real bull flags are rare on liquid large-caps; signal scarcity.
  - "Tight pullback" is a parameterised concept (channel width) — needs walk-forward.
  - False breakouts are the modal failure mode.
- **Fit with the deterministic-risk invariant** — **`fits`**. ATR stop replaces "below flag low" with a deterministic floor; LLM only ranks.
- **Priority** — `next`.
- **Rough effort** — `M`.

### 3.2 Cup-and-handle geometric detector

- **Description** — Detector for cup geometry (depth ≤ 35%, base length ≥ 7 weeks, U-shape via simple polynomial fit) + handle (1–4 week pullback, 30–50% retrace of late-cup leg) + breakout. New `tools/patterns.py`.
- **Source** — strategies.md #8 (cup-and-handle, `needs envelope`).
- **Pros**
  - Codifies institutional accumulation behaviour.
  - O'Neil's 7–8% hard stop is deterministic and tight.
- **Cons**
  - Geometric fit is finicky; many false positives (random U-shapes).
  - Backtesting is hard because labelled training data doesn't exist; we'd be inventing the labels.
  - Bulkowski stats show meaningful failure rates — practitioner folklore overstates the edge.
- **Fit with the deterministic-risk invariant** — **`needs envelope`** — detector itself is deterministic, but parameter selection is high-dimensional. Pair with walk-forward (cluster 6).
- **Priority** — `later`.
- **Rough effort** — `L`.

### 3.3 Wyckoff Spring detector (narrow scope)

- **Description** — Detect "false breakdown of an N-week range followed by a close back inside the range on volume ≥ 1.5× ADV." Ignore the rest of the Wyckoff schematic. New `tools/patterns.py`.
- **Source** — strategies.md #10 (Wyckoff, `needs envelope`).
- **Pros**
  - Tight invalidation — stop just below the Spring low.
  - One of the highest-R:R setups when it works.
- **Cons**
  - Springs are uncommon on a small US-equity watchlist.
  - "Range" definition (lookback length, % bounds) is parameter-heavy.
  - Without the larger schematic context, false positives multiply.
- **Fit with the deterministic-risk invariant** — **`needs envelope`** — parameters must be locked, not LLM-tunable.
- **Priority** — `later`.
- **Rough effort** — `M`.

### 3.4 Donchian-20 breakout entry

- **Description** — Add Donchian(20) high-breakout as a candidate source alongside the existing EMA-cross / RSI / volume entry. New entry mode in `tools/market_data.py::is_entry_signal` gated by an `ENTRY_MODE` setting.
- **Source** — strategies.md #2 (Donchian, verdict `fits`), #3 (Turtle S1 base).
- **Pros**
  - Simplest possible breakout rule; pairs with our existing ATR stop.
  - Rule symmetry (10-day low exit) gives a deterministic alternate exit.
  - Foundational, well-understood; trivial to backtest.
- **Cons**
  - 30–40% canonical win rate — depends on R-multiple distribution; emotionally tough on a small account.
  - 20-day breakouts on liquid US large-caps are rare; signal scarcity worsens our existing trade-frequency problem.
  - Doesn't add diversity if our universe is correlated.
- **Fit with the deterministic-risk invariant** — **`fits`**. Pure rule.
- **Priority** — `next`.
- **Rough effort** — `S`.

---

## Cluster 4 — Sector rotation / relative strength

### 4.1 Cross-sectional RS rank pre-filter

- **Description** — Before `strategy.py` evaluates per-symbol signals, rank the watchlist by 6-month total return (skip-month) and only let the top decile through. New `tools/relative_strength.py`. Filter applied in `main.py` between `MarketIntelligenceAgent` and `StrategyAgent`.
- **Source** — strategies.md #6 (cross-sectional momentum — the only `academic` evidence in the survey).
- **Pros**
  - The most heavily replicated equity anomaly outside value.
  - Tiny code; deterministic.
  - Shrinks the universe each scan, reducing token spend in `strategy.py`.
- **Cons**
  - With our small watchlist (~20 symbols) the "top decile" is 2 names; granularity is poor.
  - Momentum crashes (2009 Q2, 2020 Q2) are real — pair with cluster 2.1 SPY regime gate.
  - 6-month hold horizon clashes with `MAX_HOLD_DAYS=5`. Pre-filter only, not entry/exit.
- **Fit with the deterministic-risk invariant** — **`fits`** as a pre-filter. Sizing/holds untouched.
- **Priority** — `now`.
- **Rough effort** — `S`.

### 4.2 Sector ETF relative-strength overlay

- **Description** — Compute each ticker's sector ETF (XLK, XLE, XLV, etc.) relative strength vs SPY; veto entries whose sector is in the bottom decile. Static ticker→sector map in `config/sector_map.py`.
- **Source** — strategies.md #6 cross-sectional, generalised to sector RS.
- **Pros**
  - Cheap deterministic veto — one ETF chart per sector per day.
  - Avoids the "good name in a bad sector" failure mode.
- **Cons**
  - Sector mapping is a static table that drifts (companies change sectors).
  - Rotation can lead RS, so vetoing on RS lags the regime change.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `next`.
- **Rough effort** — `S`.

---

## Cluster 5 — Trailing-stop variants (extensions of v1.11 base)

> **Base shipped in v1.11**: ATR-distance trailing stop in `monitor/position_monitor.py::_apply_trailing_stop`, opt-in via `TRAILING_STOP_ENABLED`. The candidates below extend it.

### 5.1 Chandelier exit variant

- **Description** — Replace the v1.11 fixed-distance trail with a Chandelier exit: `stop = max(stop, highest_high(N) − k × ATR(N))`. Toggle via `TRAILING_STOP_MODE=chandelier`. Touches `monitor/position_monitor.py::_apply_trailing_stop`.
- **Source** — strategies.md #2 (Donchian/ATR family); github-projects.md mathesco trailing-stop pattern.
- **Pros**
  - Anchors trail to running high, not just current price — captures more of strong moves.
  - Standard, well-known formulation; easy to backtest.
- **Cons**
  - Requires storing rolling-N-bar high per trade (currently only `trailing_high` is stored).
  - Choosing N (typically 22) is another parameter.
- **Fit with the deterministic-risk invariant** — **`fits`**. Same shape as the existing ratchet.
- **Priority** — `next`.
- **Rough effort** — `S`.

### 5.2 Donchian-lookback trailing stop

- **Description** — Trail at the lowest low of the last N bars (canonical N=10 from Turtle S1 exit). `TRAILING_STOP_MODE=donchian`.
- **Source** — strategies.md #2, #3 (Turtle S1 10-day exit).
- **Pros**
  - Indicator-free, structural.
  - Symmetric to Donchian breakout entries (cluster 3.4).
- **Cons**
  - Can be far from price in low-volatility chop; less tight than ATR-trail.
  - Needs N-bar history per trade.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `later`.
- **Rough effort** — `S`.

### 5.3 Breakeven-after-1R rule

- **Description** — Once unrealised PnL ≥ 1× initial-stop-distance, ratchet stop to entry. Composable with v1.11 base trail. New flag `BREAKEVEN_AT_1R_ENABLED`. Touches `monitor/position_monitor.py`.
- **Source** — strategies.md cross-cutting (universal practitioner rule).
- **Pros**
  - Eliminates the "winning trade turning into loser" psychological failure mode.
  - One-line rule; trivial to implement and audit.
- **Cons**
  - Breakeven stops get hit on noise far more than ATR trails — converts winners into scratches.
  - Backtest evidence is mixed; helps emotion more than expectancy.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `next`.
- **Rough effort** — `S`.

---

## Cluster 6 — Backtest extensions

### 6.1 Walk-forward optimisation harness

- **Description** — Replace the single-window backtest with a rolling walk-forward: train on year N, validate on year N+1, advance by one year. Output mean / std / IQR of trailing-30d metrics across windows. Touches `backtest/` and `main.py backtest`.
- **Source** — strategies.md cross-cutting (parameter-sensitivity warnings on #7 Bollinger, #4 RSI(2)); github-projects.md lumibot replay pattern.
- **Pros**
  - The single most important hygiene fix for any strategy claiming to "work."
  - Surfaces the curve-fit risk the current settings.py grid almost certainly carries.
  - 5y portfolio backtest baseline (memory: +8.5%, 35% WR) becomes more credible with walk-forward bands.
- **Cons**
  - 3–5× backtest runtime.
  - Requires careful look-ahead-bias review; easy to introduce subtle leaks.
  - More machinery to maintain.
- **Fit with the deterministic-risk invariant** — **`fits`**. Pure offline tooling.
- **Priority** — `now`.
- **Rough effort** — `L`.

### 6.2 Parameter-sensitivity sweep

- **Description** — Grid sweep over `RSI_LOWER`, `RSI_UPPER`, `ATR_STOP_MULTIPLIER`, `RR_RATIO_MIN`, `EMA_FAST`, `EMA_SLOW`, `VOLUME_MULTIPLIER`. Output a heatmap + best/worst/median performance per axis. New `backtest/sensitivity.py`.
- **Source** — strategies.md cross-cutting; settings.py current grid.
- **Pros**
  - Reveals which knobs actually matter and which are noise.
  - Cheap once the backtest engine is fast enough.
  - Anchors future tuning in evidence rather than vibes.
- **Cons**
  - Curve-fit risk if not paired with walk-forward (6.1).
  - Combinatorial explosion if all axes are swept densely.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `next` (after 6.1).
- **Rough effort** — `M`.

### 6.3 Monte-Carlo trade-sequence resampling

- **Description** — Take the realised trade ledger from backtest, bootstrap-resample N times with replacement, plot distribution of terminal equity / max DD. Estimates the "luck band" around the headline number.
- **Source** — strategies.md cross-cutting (the +8.5%/-17%DD baseline begs the question of variance); standard quant practice.
- **Pros**
  - Honest framing: a single +8.5% backtest could plausibly be -5% to +20% on resampled order.
  - Cheap to implement once trade ledger exists.
- **Cons**
  - Doesn't add new information when sample size is small (5y, ~hundreds of trades).
  - Bootstrap assumes trade independence, which is only roughly true.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `next`.
- **Rough effort** — `S`.

### 6.4 Deterministic agent replay in backtest

- **Description** — Cache LLM responses by `(prompt_hash, market_state_hash)` so historical agent decisions can be replayed without re-billing or model drift. Lumibot has the cleanest reference. Touches `agents/base.py` (cache layer) and `backtest/`.
- **Source** — github-projects.md lumibot, gr8monk3ys engine replay; strategies.md silent on this.
- **Pros**
  - Makes agent backtests reproducible — a precondition for honest sensitivity analysis on agent behaviour.
  - Eliminates a real cost driver (re-running agents over 5y of history).
- **Cons**
  - Cache invalidation when model or system prompt changes is non-trivial.
  - Adds storage; cache hit rates depend on prompt determinism.
- **Fit with the deterministic-risk invariant** — **`fits`**. Cache is an offline correctness aid.
- **Priority** — `later`.
- **Rough effort** — `L`.

---

## Cluster 7 — News / sentiment ingestion

### 7.1 Earnings-driven entry-quality score (extension of v1.12 blackout)

- **Description** — v1.12 already blacks out entries within `EARNINGS_BLACKOUT_DAYS`. Extension: surface "days since last earnings" and "days to next earnings" as deterministic numeric features in `MarketIntelligenceAgent`'s context, used purely as descriptive ranking inputs. No risk-parameter coupling.
- **Source** — strategies.md cross-cutting; tools/earnings.py already exists.
- **Pros**
  - Reuses v1.12 plumbing.
  - Read-only ranking input; cannot affect stops or sizing.
- **Cons**
  - Marginal value over the blackout window we already have.
  - Surface area for prompt drift.
- **Fit with the deterministic-risk invariant** — **`fits`** so long as the feature is read-only context to the LLM, not an input to `tools/risk.py`.
- **Priority** — `later`.
- **Rough effort** — `S`.

### 7.2 News headline ingestion with deterministic envelope

- **Description** — Pull recent headlines (Alpaca news API or Finnhub) into `MarketIntelligenceAgent` context. Envelope: a hard list of "blackout keywords" (acquisition, fraud, halt, SEC, going concern) computed deterministically; if any match, veto entry regardless of LLM judgement.
- **Source** — github-projects.md huygiatrng (sentiment analysts) + strategies.md cross-cutting; the envelope is our addition.
- **Pros**
  - Catches headline-driven gaps that pure technicals miss.
  - Keyword veto is deterministic and auditable.
- **Cons**
  - News APIs have cost / rate limits / partial coverage (especially small caps).
  - LLM sentiment scoring is itself non-deterministic — only the keyword veto layer can be relied on.
  - Easy to over-fit keywords to past blow-ups.
- **Fit with the deterministic-risk invariant** — **`needs envelope`** — explicit keyword veto as a pre-filter; LLM "sentiment score" is read-only context only, never a sizing input.
- **Priority** — `later`.
- **Rough effort** — `L`.

### 7.3 Free-form LLM sentiment as risk modifier

- **Description** — *Hypothetical*: let the LLM emit a "sentiment score" that scales position size or stop distance.
- **Source** — github-projects.md huygiatrng AlpacaTradingAgent (advertised but no deterministic risk layer).
- **Pros** — none worth listing.
- **Cons** — direct violation of the architectural invariant.
- **Fit with the deterministic-risk invariant** — **`violates`**. The LLM would be controlling sizing.
- **Priority** — `skip`.
- **Rough effort** — N/A.

---

## Cluster 8 — VWAP / volume-profile entries

### 8.1 Daily-bar VWAP-distance feature

- **Description** — Approximate "distance from session VWAP at close" as `(close − typical_price_volume_weighted_over_day) / atr`. Surface as a candidate-ranking input in `strategy.py`. No intraday data required — uses daily bar's high/low/close/volume as a proxy.
- **Source** — strategies.md cross-cutting; keywords.md VWAP / Anchored VWAP.
- **Pros**
  - Cheap proxy for "where is the day's volume concentrated."
  - No infra change — daily bars suffice.
- **Cons**
  - Daily-bar VWAP is a poor proxy for session VWAP; the literature edge is intraday.
  - May add noise rather than signal.
- **Fit with the deterministic-risk invariant** — **`fits`** as a ranking feature.
- **Priority** — `later`.
- **Rough effort** — `S`.

### 8.2 Intraday VWAP / volume-profile entries

- **Description** — Switch to intraday bar feed, compute session VWAP and volume profile, enter on pullbacks to VWAP in established trends. Requires a separate intraday agent loop, real-time bar subscription, and an intraday position sizer.
- **Source** — strategies.md #13 (Schäfermeier ORB), keywords.md VWAP.
- **Pros**
  - Captures the genuine edge that anchored-VWAP literature describes.
  - Opens a second strategy lane (intraday) alongside our daily swing lane.
- **Cons**
  - Multi-month build: new data feed, new agent loop, new monitor cadence.
  - Pre-market scan model fundamentally doesn't apply.
  - Conflict with `MAX_HOLD_DAYS` semantics.
- **Fit with the deterministic-risk invariant** — would need a parallel deterministic risk layer for intraday — feasible but a large surface to prove out.
- **Priority** — `later` (essentially a separate product).
- **Rough effort** — `XL`.

---

## Cluster 9 — Kill-switch hardening

### 9.1 `main.py panic` command with `--cancel-orders --liquidate`

- **Description** — New CLI subcommand that (1) cancels all open orders, (2) optionally market-closes all positions, (3) writes `TRADING_PAUSED=true` to `.env`, (4) posts a Discord alert. Operationally cleaner than the env-only kill switch we have today.
- **Source** — github-projects.md gr8monk3ys `kill_switch.py` (direct lift of pattern).
- **Pros**
  - Dramatically faster incident response than `vim .env` + restart.
  - Composable: scripted alerts can call it.
  - Existing `TRADING_PAUSED` already gates new entries; this fills the gap on existing positions.
- **Cons**
  - `--liquidate` is destructive — needs an explicit confirm flag and audit log entry.
  - Risk of accidental invocation during a panic.
- **Fit with the deterministic-risk invariant** — **`fits`**. It is the deterministic safety net.
- **Priority** — `now`.
- **Rough effort** — `S`.

### 9.2 Per-symbol cooldown after exit

- **Description** — After any exit on symbol X, block re-entry on X for N bars (or M hours). Deterministic check in `tools/risk.py::check_cooldown` consulted by `team_leader.place_order`. New setting `REENTRY_COOLDOWN_BARS`.
- **Source** — github-projects.md OpenAlice "guard pipeline" (cooldown is named primitive); not in strategies.md.
- **Pros**
  - Prevents the re-entry whipsaw failure mode where stop fires, bounce triggers re-buy, second stop fires.
  - Deterministic, cheap, auditable.
- **Cons**
  - Misses the rare legitimate re-entry on the same name.
  - Needs schema column (last_exit_date per ticker) or query against `trades`.
- **Fit with the deterministic-risk invariant** — **`fits`**. Pure rule.
- **Priority** — `now`.
- **Rough effort** — `S`.

### 9.3 Daily-loss circuit breaker (extension of `DAILY_DRAWDOWN_LIMIT`)

- **Description** — `DAILY_DRAWDOWN_LIMIT` already vetoes new entries on bad days. Extension: at -1.5× limit, also auto-trigger `panic --cancel-orders` (no liquidate). Touches `tools/risk.py` and the new panic command.
- **Source** — strategies.md cross-cutting; codebase-driven.
- **Pros**
  - Closes a real gap: today, on a bad day, existing brackets stay live but new entries stop. This adds defence on the existing exposure.
  - Deterministic, no human-in-the-loop required.
- **Cons**
  - Cancelling orders mid-day could lock in losses that would have recovered.
  - Edge case: what counts as "today's PnL" depends on intraday quote freshness.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `next`.
- **Rough effort** — `M`.

---

## Cluster 10 — Seasonality overlay

### 10.1 Turn-of-month sizing modifier

- **Description** — Up-size or pass-through entries on the last 4 / first 3 trading days of the month (TOM effect — Lakonishok & Smidt 1988, Andrade et al. 2012); down-size or skip in the dead middle of the month. Deterministic calendar lookup in `tools/seasonality.py`. Modifier is a fixed table, not LLM-tunable.
- **Source** — strategies.md anomaly-stacking footnote (TOM, Halloween).
- **Pros**
  - Statistically robust academic effect.
  - Pure deterministic calendar — no model risk.
- **Cons**
  - Effect size in dollars is small; may not survive transaction costs on a small book.
  - "Up-size" specifically interacts with `RISK_PER_TRADE` cap — we'd be modulating risk based on date, which couples seasonality to risk math.
- **Fit with the deterministic-risk invariant** — **`needs envelope`** — modifier must be a fixed table, not LLM-tunable, and must respect the RISK_PER_TRADE bound.
- **Priority** — `later`.
- **Rough effort** — `S`.

### 10.2 Halloween / Sell-in-May regime overlay

- **Description** — Suppress new entries Jun–Oct (or down-size); pass through Nov–May. Deterministic calendar in `tools/seasonality.py`.
- **Source** — strategies.md anomaly-stacking footnote (Bouman & Jacobsen 2002).
- **Pros**
  - One of the longest-replicated equity calendar effects.
  - Trivial to implement.
- **Cons**
  - Single binary cuts available trading days roughly in half — major signal-frequency hit.
  - Effect has weakened post-2010 in some replications.
- **Fit with the deterministic-risk invariant** — **`fits`** as a calendar veto.
- **Priority** — `later`.
- **Rough effort** — `S`.

---

## Cluster 11 — Agent decomposition

### 11.1 Split `MarketIntelligenceAgent` into specialist sub-analysts

- **Description** — Decompose into `MarketAnalyst` (regime), `NewsAnalyst` (headlines, with keyword veto envelope from 7.2), `MacroAnalyst` (rates, VIX, USD). Each emits structured findings consumed by `StrategyAgent`. Touches `agents/`. **Constraint: every sub-analyst output is read-only context — none touches risk parameters.**
- **Source** — github-projects.md huygiatrng AlpacaTradingAgent (5-analyst pattern), TraderAlice/OpenAlice.
- **Pros**
  - Improves traceability — each analyst's output cached and logged independently.
  - Lets us swap or A/B-test analysts without touching strategy logic.
  - Token costs become attributable per analyst.
- **Cons**
  - Multiplies the LLM surface area; more places for prompt drift.
  - Increases per-cycle token spend (more agents = more API calls).
  - Marginal performance benefit on a small watchlist.
- **Fit with the deterministic-risk invariant** — **`fits`** strictly on the analysis side. Anything that would flow into sizing/stops needs an envelope.
- **Priority** — `later`.
- **Rough effort** — `L`.

### 11.2 Bull/bear researcher pair before `RiskReviewAgent`

- **Description** — Add a single extra agent call that takes Strategy's approved candidates and forces an explicit bear-case articulation. Output is logged but does not gate trades — read-only "red team" log entry. Touches `agents/` (one new agent) and `main.py`.
- **Source** — github-projects.md huygiatrng (researcher pair).
- **Pros**
  - Cheap (one extra prompt) auditability win — every approved trade has a recorded bear case.
  - Pure logging — cannot affect risk.
- **Cons**
  - Extra token cost with no gating impact is hard to justify on expectancy grounds.
  - Sets a precedent for unbounded LLM additions ("just one more agent").
- **Fit with the deterministic-risk invariant** — **`fits`** if and only if the output is read-only.
- **Priority** — `later`.
- **Rough effort** — `M`.

### 11.3 LLM-driven order-side decisions

- **Description** — *Hypothetical*: let an LLM compose or amend the order legs (stop, target, sizing).
- **Source** — github-projects.md huygiatrng anti-pattern.
- **Pros** — none.
- **Cons** — direct violation of the invariant.
- **Fit with the deterministic-risk invariant** — **`violates`**.
- **Priority** — `skip`.
- **Rough effort** — N/A.

---

## Cluster 12 — Operational / observability

### 12.1 Heartbeat / health-check job

- **Description** — Cron job (every 15 min during market hours) that pings Alpaca, the data feed, the DB, and the n8n webhook; if N consecutive failures, post a critical Discord alert. New `monitor/heartbeat.py`.
- **Source** — github-projects.md mathesco (heartbeat) and lumibot (health checks); codebase-driven.
- **Pros**
  - Catches silent failures (cron didn't run, Alpaca rate-limited, n8n container down) before they cause missed exits.
  - Very small code; pure operational hygiene.
- **Cons**
  - Adds another cron line and another Discord channel signal to manage.
  - Alert-fatigue risk if thresholds are too tight.
- **Fit with the deterministic-risk invariant** — **`fits`**. Operational only.
- **Priority** — `now`.
- **Rough effort** — `S`.

### 12.2 Three-tier test taxonomy

- **Description** — Split `tests/` into `tests/integrity/` (no creds, schema/spec consistency), `tests/construction/` (mocked broker/anthropic), `tests/integration/` (live paper-account smoke tests, opt-in). Mirrors alpacahq/alpaca-mcp-server.
- **Source** — github-projects.md alpaca-mcp-server.
- **Pros**
  - Cleaner gating in CI — integrity always runs, integration runs nightly or on-demand.
  - Catches a class of "tests pass but production breaks" failures.
- **Cons**
  - One-time refactor cost; no immediate trading-performance benefit.
  - Risk of flaky integration tests slowing CI.
- **Fit with the deterministic-risk invariant** — **`fits`**. Out of *original prompt's* scope (no new tests proposed) but the *taxonomy* is structural, not new tests. Listed for completeness; flag as out-of-scope-of-prompt to the team.
- **Priority** — `later`.
- **Rough effort** — `M`.

### 12.3 Deterministic agent replay in backtest

- *Folded into 6.4 above. Keeping the cross-reference here so this cluster is honest about overlap.*

### 12.4 TTL-cached singleton broker clients

- **Description** — Wrap `tools/broker.py`'s account / quote calls in a TTL cache (10s for account, 15s for quotes, configurable). Reduces redundant calls in the morning scan and monitor.
- **Source** — github-projects.md mathesco.
- **Pros**
  - Cheap performance win; avoids rate-limit edge cases.
  - Useful when sub-analysts (cluster 11.1) multiply broker calls.
- **Cons**
  - Stale-cache bugs are subtle when something else changes account state mid-cycle (e.g. a manual UI trade).
  - Caches must be invalidated on order-placement to avoid acting on pre-trade state.
- **Fit with the deterministic-risk invariant** — **`fits`** if invalidation is rigorous (especially around `place_order`).
- **Priority** — `next`.
- **Rough effort** — `S`.

### 12.5 Pre-flight `go_live_precheck` artifact

- **Description** — Script that snapshots config, schema, broker connectivity, and writes a JSON checksum file before any deploy. CI rejects deploys whose checksum doesn't match a signed reference.
- **Source** — github-projects.md gr8monk3ys.
- **Pros**
  - Catches accidental config flips ("I set MAX_PORTFOLIO_EXPOSURE to 0.50 in dev and forgot").
  - Auditable deploy history.
- **Cons**
  - Adds friction to every deploy, including hot fixes.
  - Maintaining the reference checksum is its own process.
- **Fit with the deterministic-risk invariant** — **`fits`**.
- **Priority** — `later`.
- **Rough effort** — `M`.

---

## Cross-cutting recommendations

### Top 5 `now` items, ranked

1. **2.1 SPY 200-day-SMA regime gate** (`S`). Single boolean veto, biggest historical impact-to-effort ratio in the entire roadmap. Directly addresses the "we trade through everything including 2008" failure mode that the 5y backtest baseline can't even see (sample didn't include a major bear).
2. **9.1 `main.py panic --cancel-orders --liquidate`** (`S`). The 2026-04-28 day-0 incident memory is exactly the scenario this fixes. Operational must-have before any further live capital.
3. **9.2 Per-symbol cooldown after exit** (`S`). Closes a known whipsaw mode that is invisible in backtest summaries (which net it out) but real in DB trade ledgers.
4. **6.1 Walk-forward optimisation harness** (`L`). The +8.5%/-17%DD/35%WR baseline is plausibly curve-fit; until walk-forward bands exist around it, every parameter change is faith-based. This is the foundation for credible decisions on items 4.1, 5.x, and 6.2.
5. **4.1 Cross-sectional RS rank pre-filter** (`S`). The only `academic`-evidence strategy in the survey, applied as a pre-filter (no horizon mismatch). On a tiny watchlist the granularity is poor but the principle of "don't trade laggards" is durable.

### Explicitly `skip` — non-goals

- **#7.3 LLM sentiment as risk modifier** — would let the LLM scale stops or sizing. Direct violation. Skip permanently.
- **#11.3 LLM-driven order-side decisions** — same.
- **strategies.md #12 Elliott Wave** — wave-counting is non-deterministic by construction. The German practitioner literature (Tiedje, Weisenhaus) is *deeper* but no more falsifiable. Skip.
- **strategies.md #13 Schäfermeier ORB** — intraday futures strategy retrofitted onto our daily-swing engine loses the entire edge. If we ever build an intraday lane (8.2), revisit then; otherwise skip.
- Any prompt change that asks the LLM to "decide an appropriate stop distance" or "size based on conviction" — skip on sight.

### Why the deterministic-risk invariant rules things out

The invariant in `CLAUDE.md` — *the LLM must never control risk parameters directly* — rules out the otherwise-attractive multi-agent decomposition patterns from huygiatrng/AlpacaTradingAgent and the freeform sentiment ingestion patterns from countless GPT-trader projects. The reason is that v1.10 (deterministic exposure gate against broker truth), v1.11 (rule-based trailing stop in the monitor), and v1.12 (deterministic earnings blackout window) collectively make the invariant *the differentiator* of this bot vs the LLM-bot field. github-projects.md cross-cutting finding #2 is explicit: "LLM-driven bots almost universally lack a deterministic risk layer." Throwing that away to chase an LLM-debated trader pattern would be strategic self-harm. Every roadmap candidate above is graded against this lens — `needs envelope` is the polite way of saying "the wrapper is doing the work, not the LLM."

### Reality check — what is likely to move performance vs. what is hygiene

Honest framing across the roadmap:

- **Likely to move trading performance** — 2.1 (SPY regime), 4.1 (RS pre-filter), 1.1 (weekly trend gate), 3.1 (bull-flag detector), 6.1 (walk-forward, *indirectly*, by exposing the truth about current parameters). Of these, only 2.1 and 4.1 are cheap *and* high-conviction.
- **Mostly hygiene with marginal performance impact** — every item in cluster 9 (kill-switch hardening), cluster 12 (observability), 6.3 (Monte Carlo), 5.3 (breakeven-after-1R), 12.4 (TTL caches). These reduce *the cost of being wrong* rather than improving the win rate. Worth doing — but call them what they are.
- **Likely to add complexity without moving the needle** — cluster 11 (agent decomposition) on a small watchlist where the bottleneck is signal scarcity, not signal quality; 1.2 (multi-TF alignment score) layered on top of a still-unproven daily strategy; 7.1 (earnings ranking feature) given that v1.12 already covers the binary risk.
- **Real fundamental questions the roadmap cannot answer** — is the EMA-crossover + RSI + volume entry in `strategy.py` actually edge-positive on a walk-forward basis, or is the +8.5%/5y baseline a curve-fit artifact? Until 6.1 lands, every other addition is decoration on an unverified core.

The honest one-line summary: **prioritise 2.1, 9.1, 9.2, 4.1 as cheap real wins; treat 6.1 as the precondition for everything else; defer agent decomposition until the deterministic core has been re-validated.**
