# Swing-Trading Strategies — Survey

**Scope.** A merged English + German top-15 of swing-trading strategies. For each entry: mechanism, indicators, timeframe, pros, cons, fit with our deterministic-risk bot, evidence quality, and sources. Methodology: WebSearch + WebFetch on EN and DE practitioner / academic sources, filtered for citable URLs. **Date: 2026-04-30.**

**How to read the verdict.** Every entry ends with one of three labels:

- **`fits`** — the strategy is shape-compatible with our existing pipeline (daily bars, ATR stop, bracket orders, deterministic risk).
- **`needs envelope`** — the strategy could work, but only if we wrap the LLM's outputs in a deterministic pre/post layer (ATR-floor on stops, hard veto on max-hold, fixed sizing). The envelope is described in the entry.
- **`skip`** — fundamentally incompatible with the deterministic-risk invariant or with daily-bar swing trading.

The verdict is non-negotiable: it applies regardless of how authoritative the source is. "Practitioner consensus" does not override the architectural invariants in `CLAUDE.md`.

---

## 1. SMA 50 / 200 Golden Cross (moving-average crossover)

- **Mechanism** — Long when the 50-day SMA crosses above the 200-day SMA; flat or short on the death cross. Stop typically below a recent swing low or a fixed % below entry; many implementations don't use a stop and re-enter on the next cross. Holding is open-ended — until the opposite cross.
- **Indicators / patterns**
  - SMA(50), SMA(200)
  - Optional: ADX or 200-day slope as a regime filter
- **Typical timeframe** — Daily bars; multi-week to multi-month holds.
- **Pros**
  - Mechanically trivial to code and audit.
  - Catches most major bull legs; stays out of deep bears (max DD ~33% vs. ~56% buy-and-hold over 66 years on the S&P 500 per QuantifiedStrategies).
  - Risk-adjusted return beats buy-and-hold per the same study.
- **Cons**
  - Whipsaw in sideways markets — only ~33 signals in 66 years means it's nearly a position-trading system, not a swing system.
  - Late entry by definition; gives back a meaningful chunk of the move at exit.
  - Single-asset signal — no relative-strength selection.
- **Fit with our bot** — The crossover trigger is the kind of clean rule the StrategyAgent could emit, and the ATR stop in `tools/risk.py` would clamp the implicit "no stop" weakness of the canonical version. But the natural hold horizon (months) collides with our `MAX_HOLD_DAYS` invariant, so it would behave as an early-exit caricature of the strategy unless `MAX_HOLD_DAYS` is widened explicitly. **`needs envelope`** — extend max-hold or accept that we're harvesting only the first leg, plus a regime filter to suppress whipsaw.
- **Evidence quality** — `practitioner` (multi-decade backtests on aggregator sites; not a peer-reviewed factor literature item).
- **Sources**
  - https://www.quantifiedstrategies.com/golden-cross-trading-strategy/ (Golden Cross Trading Strategy backtest)
  - https://tosindicators.com/research/golden-cross-trading-strategy-20-year-backtest-results (20-year SPX backtest, 2024)
  - https://www.tradingheroes.com/50-200-ma-cross-strategy-v1-results/ (50/200 backtest results)

---

## 2. Donchian 20-Day Breakout

- **Mechanism** — Buy when price closes above the 20-day high; exit when price closes below the 10-day low. Stops are placed N×ATR below entry (typically 2 ATR). Long-only or symmetric short variant.
- **Indicators / patterns**
  - Donchian channel(20) for entry, Donchian(10) for exit
  - ATR(14) for stop sizing
  - Optional MA filter for trade direction
- **Typical timeframe** — Daily bars; multi-day to multi-week holds.
- **Pros**
  - The exit rule is symmetric to the entry — clean, testable, no discretion.
  - Captures persistent trends; foundational to the Turtle System (#3).
  - ATR-based sizing slots naturally into `tools/risk.py`.
- **Cons**
  - Win rate is structurally low (30–40% canonical) — relies on R-multiple distribution, not hit-rate.
  - Vulnerable to false breakouts in low-momentum markets; many sources recommend an RSI or volume filter on top.
  - Daily-bar 20-day breakouts are rare on liquid US equities — signal scarcity is real.
- **Fit with our bot** — Architecturally a near-perfect fit: ATR stops, deterministic exit rule, bracket orders are sufficient. The low hit-rate creates psychological pressure on a small account, but that's an operator problem, not a system problem. **`fits`**.
- **Evidence quality** — `practitioner` (well-documented; the underlying Turtle results were proprietary but widely replicated).
- **Sources**
  - https://trendspider.com/learning-center/donchian-channel-trading-strategies/
  - https://www.luxalgo.com/blog/donchian-channels-breakout-and-trend-following-strategy/
  - https://deepvue.com/indicators/donchian-channels-the-breakout-traders/

---

## 3. Turtle System (S1 / S2)

- **Mechanism** — S1: buy on a 20-day high, exit on the 10-day low. S2: buy on a 55-day high, exit on the 20-day low. Stop at 2 N (ATR) below entry. Pyramid: add a unit every ½ N favorable move, up to 4 units. S1 is skipped if the prior signal would have been a winner (filter to avoid late entries into stale moves).
- **Indicators / patterns**
  - Donchian(20) and Donchian(55) for entries
  - ATR (Wilder's "N") — central to sizing, stops, pyramiding
- **Typical timeframe** — Daily bars; multi-week to multi-month.
- **Pros**
  - Fully specified — every rule is testable.
  - Position sizing is volatility-normalised (1 unit = account_risk / N).
  - Pyramiding lets winners run hard.
- **Cons**
  - Designed for futures portfolios with uncorrelated markets. On a US-equity-only universe correlations cluster and the diversification math doesn't hold.
  - Drawdowns of 30–50% are baked in; emotionally brutal.
  - Pyramiding violates our `MAX_POSITIONS` discipline unless we count adds as the same slot.
- **Fit with our bot** — The base S1 entry/exit + 2 N stop is shape-compatible. The pyramiding and the 1968-style multi-asset diversification are not. We'd be running a degraded variant. **`needs envelope`** — disable pyramiding, restrict to single-unit entries, lean on `check_portfolio_guardrails` for correlation ceilings.
- **Evidence quality** — `practitioner` (the original "Original Turtle Trading Rules" PDF is the canonical source; results were proprietary).
- **Sources**
  - https://oxfordstrat.com/coasdfASD32/uploads/2016/01/turtle-rules.pdf (Original Turtle Trading Rules PDF)
  - https://trendspider.com/learning-center/richard-dennis-turtle-trading-strategy/
  - https://macro-ops.com/richard-dennis-turtle-trading-strategy-explained/

---

## 4. RSI(2) Mean Reversion (Connors)

- **Mechanism** — In a long-term uptrend (price > 200-day SMA), buy when RSI(2) drops below 10 (or 5 for a stronger edge). Exit when price closes above the 5-day SMA. Connors's canonical rules **do not use a stop-loss** — he claims stops "hurt" performance on indices in his tests.
- **Indicators / patterns**
  - RSI(2)
  - SMA(200) as regime filter
  - SMA(5) for exit
- **Typical timeframe** — Daily bars; 1–5 day holds.
- **Pros**
  - High hit-rate on broad indices (Connors reports 70–85%; replications confirm an edge but with smaller magnitudes).
  - Trades frequently — useful for compounding small edges.
  - Trend filter prevents catching falling knives in bear markets.
- **Cons**
  - **No stop-loss in the canonical version** — tail risk is unbounded; one black-swan trade can wipe months of gains.
  - The 70–85% win rate cited in marketing does not include 2008-style continuation lower; replication studies show drawdowns spike in bear regimes.
  - Originally tuned for indices and ETFs, not single names; on individual stocks earnings gaps blow up the no-stop assumption.
- **Fit with our bot** — Directly violates the architectural invariant: "stops execute server-side via Alpaca bracket orders." We must impose an ATR stop, which Connors says reduces edge — i.e. we'd be running a hobbled version. Single names compound the gap risk. **`needs envelope`** — restrict to liquid ETFs only, force an ATR floor (e.g. 2 × ATR(14)), and accept reduced edge as the price of risk control.
- **Evidence quality** — `practitioner` with marketing overtones (Connors's books, plus `quantifiedstrategies.com`'s replications).
- **Sources**
  - https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2 (StockCharts RSI-2)
  - https://www.quantifiedstrategies.com/rsi-2-strategy/
  - https://blog.elearnmarkets.com/how-to-trade-larry-connors-2-period-rsi/

---

## 5. Pullback to Moving Average in an Uptrend

- **Mechanism** — Confirm an established uptrend (HH/HL, price above 50-day SMA, 50 above 200). Wait for a pullback into the 9 / 20 EMA zone (or the 50 EMA for deeper pullbacks). Enter on the first close back above the faster MA, ideally on declining volume during the dip and rising volume on the resumption candle. Stop below the recent swing low; target a measured-move equal to the prior leg.
- **Indicators / patterns**
  - EMA(9), EMA(20), or EMA(50) as dynamic support
  - Higher-high / higher-low structure
  - Volume contraction on dip / expansion on resumption
  - Fibonacci 38.2 / 50 / 61.8 retracement as confluence
- **Typical timeframe** — Daily bars; 3–10 day holds.
- **Pros**
  - High win-rate setup with clear invalidation — stop is "swing low" by definition.
  - Aligns with our existing `EMA_FAST` / `EMA_SLOW` machinery.
  - Trades only with the dominant trend — compatible with regime filtering.
- **Cons**
  - "Established uptrend" is partly subjective; LLM may identify trends inconsistently across runs.
  - Frequent shallow pullbacks cluster around news — you can be filled into an earnings drift.
  - Pullback depth varies; rules-of-thumb (1/3 retrace) don't generalise across volatility regimes.
- **Fit with our bot** — The closest match to what `StrategyAgent` already does. The risk layer's ATR stop replaces "below swing low" with a deterministic floor, which is acceptable. **`fits`**.
- **Evidence quality** — `practitioner`.
- **Sources**
  - https://www.bullsonwallstreet.com/post/swing-trading-pullback-strategy
  - https://www.tradingsim.com/blog/20-moving-average-pullback
  - https://capital.com/en-int/learn/trading-strategies/pullback-trading

---

## 6. Cross-Sectional Momentum / Relative Strength

- **Mechanism** — Rank a stock universe by 6- or 12-month total return (skipping the most recent month to avoid short-term reversal). Long the top decile, short the bottom decile (long-only variants drop the short leg). Rebalance monthly. Hold 1–6 months.
- **Indicators / patterns**
  - 6 / 12-month price return, ranked cross-sectionally
  - Optional: skip-month, or risk-adjust by trailing volatility
- **Typical timeframe** — Daily-bar inputs but weekly/monthly rebalance horizon.
- **Pros**
  - The most heavily replicated equity anomaly outside of value — Jegadeesh & Titman (1993) and 30 years of follow-up papers.
  - Robust across asset classes, geographies, and decades (with documented "momentum crashes" the only major exception).
  - Long-only variant has been productised in countless ETFs (MTUM, etc.).
- **Cons**
  - Periodic violent drawdowns — momentum crashes (2009 Q2, 2020 Q2) wiped 30%+ in weeks.
  - Long-only on single names trades like an oscillator near regime turns; you buy at the top of bull market #1 and ride it down.
  - Requires a **universe**, not a single-name pipeline. Our scan is per-symbol.
- **Fit with our bot** — Our pipeline scans symbols one at a time; cross-sectional ranking would require a new layer that scores all candidates first and only then promotes the top K. The 1-to-6-month hold also exceeds our `MAX_HOLD_DAYS` window. **`needs envelope`** — add a universe-ranking step before `StrategyAgent`, widen max-hold for momentum trades only, and keep ATR stops as a deterministic floor.
- **Evidence quality** — `academic` (peer-reviewed; among the most-replicated factors in the literature).
- **Sources**
  - https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf (Jegadeesh & Titman, 1993, original paper)
  - https://link.springer.com/article/10.1007/s11408-022-00417-8 (Momentum: 30 years on, 2022)
  - https://www.nber.org/system/files/working_papers/w7159/w7159.pdf (NBER, Profitability of Momentum Strategies)

---

## 7. Bollinger Band Mean Reversion

- **Mechanism** — Long when price closes below the lower band (20-period SMA, ±2 σ); exit at the middle band (20 SMA). Optional ADX filter to avoid trades when the market is trending strongly. Stop is set at the lowest low of the entry candle, or 1.5–2 × ATR below entry.
- **Indicators / patterns**
  - Bollinger Bands(20, 2)
  - ATR(14) for stop
  - ADX(14) as a regime filter (trade only when ADX < ~20, i.e. range conditions)
- **Typical timeframe** — Daily bars; 1–5 day holds.
- **Pros**
  - Well-defined targets — middle band is hit far more often than the opposite band, so "target = midline" gives a high hit-rate.
  - Statistical foundation (standard deviation) makes the entry condition objective.
  - Pairs cleanly with ATR stops.
- **Cons**
  - Catastrophic in trending markets — if you fade a downtrend you ride price along the lower band for days.
  - Parameter sensitivity: a 20/2 setting is canonical but performance shifts substantially with 14/2 or 20/2.5.
  - The published 58–65% hit-rate is conditional on the ADX filter — without it the edge collapses.
- **Fit with our bot** — Architecturally fine: ATR stops, bracket orders, deterministic targets at the midline. Requires an explicit regime filter (ADX < threshold) — without it the strategy mis-fires badly. **`needs envelope`** — add a regime filter and force the take-profit to the midline rather than letting the LLM choose.
- **Evidence quality** — `practitioner` (one academic paper exists at Atlantis Press but the bulk of the documentation is practitioner).
- **Sources**
  - https://www.atlantis-press.com/article/125991306.pdf (academic paper on Bollinger mean reversion)
  - https://www.luxalgo.com/blog/mean-reversion-trading-fading-extremes-with-precision/
  - https://www.liberatedstocktrader.com/mean-reversion-trading-strategy/

---

## 8. Cup and Handle (William O'Neil / CAN SLIM)

- **Mechanism** — Identify a rounded base ("cup") of 7–65 weeks, with depth typically ≤ 33% from the prior high. After the right side recovers to near the prior high, a smaller pullback ("handle") of 1–4 weeks forms, retracing 30–50% of the late-cup rise. Buy on the handle's high being broken on volume ≥ 40–50% above average. Stop ~7–8% below entry per O'Neil's CAN SLIM rule.
- **Indicators / patterns**
  - Pure pattern recognition on daily / weekly bars
  - Volume confirmation on breakout
  - Relative-strength filter (CAN SLIM "Leader, not laggard")
- **Typical timeframe** — Cup: weeks-to-months. Handle: 1–4 weeks. Trade horizon: weeks-to-months.
- **Pros**
  - Codifies a real institutional behaviour — base, retest, breakout on volume.
  - O'Neil's 7–8% hard stop is the simplest deterministic exit rule in the literature.
  - Cup-and-handles often precede the largest individual-stock advances (per Investor's Business Daily case studies).
- **Cons**
  - Pattern recognition is subjective — two analysts will disagree on whether a base qualifies. LLM identifications are particularly inconsistent.
  - Bulkowski's pattern stats show meaningful failure rates; the 95%-success folklore is marketing.
  - Backtests are hard because the pattern is hand-labelled, not algorithmic.
- **Fit with our bot** — The 7–8% fixed stop and breakout-on-volume entry are mechanisable, but pattern detection itself can't be left to the LLM without a deterministic post-check (e.g. "cup depth ≤ 35%, base length ≥ 7 weeks, breakout volume ≥ 1.5× ADV"). **`needs envelope`** — codify the cup/handle geometry as a deterministic detector; let the LLM rank candidates, not invent them.
- **Evidence quality** — `practitioner` (O'Neil's books, Bulkowski's database; no peer-reviewed factor study).
- **Sources**
  - https://en.wikipedia.org/wiki/Cup_and_handle
  - https://traderlion.com/technical-analysis/cup-and-handle-pattern/
  - https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/cup-with-handle

---

## 9. Bull Flag Continuation

- **Mechanism** — Strong, near-vertical advance ("flagpole") on heavy volume, followed by a tight 2–4 candle pullback in a parallel descending channel ("flag") on declining volume. Enter on the close above the upper flag boundary with volume ≥ 1.5× average. Stop just below the flag's low. Target = flagpole height projected from the breakout (measured move).
- **Indicators / patterns**
  - Pure pattern with explicit geometry
  - Volume contraction in flag, expansion on breakout
- **Typical timeframe** — Daily bars; 2–10 day holds.
- **Pros**
  - Clear invalidation: break of flag low.
  - Measured-move target gives an explicit R:R from the start.
  - Tight stops mean small per-trade risk in dollar terms.
- **Cons**
  - "Strong flagpole" is subjective; what counts as "near-vertical" varies by volatility.
  - On daily bars, real bull flags are uncommon on liquid large-caps — you mostly find them on small-cap momentum names where slippage is brutal.
  - False breakouts are routine; the pattern's edge depends on volume confirmation that the data feed may not reliably surface intraday.
- **Fit with our bot** — Flag geometry is codifiable (% retrace of flagpole, candle count, volume ratio). Stops below flag low are within ATR-floor distance for tight-vol names. **`fits`** — provided the pattern detector is deterministic and the volume-confirmation rule is enforced before submission.
- **Evidence quality** — `practitioner` (Bulkowski statistics exist; no academic literature).
- **Sources**
  - https://www.warriortrading.com/bull-flag-trading/
  - https://www.thinkmarkets.com/en/trading-academy/technical-analysis/bear-bull-flag-pattern/
  - https://trendspider.com/learning-center/chart-patterns-flags/

---

## 10. Wyckoff Accumulation / Distribution

- **Mechanism** — Identify the phase of a base: PS (preliminary support) → SC (selling climax) → AR (automatic rally) → ST (secondary test) → Spring (false breakdown) → SOS (sign of strength) → LPS (last point of support) → markup. Enter on the Spring or LPS with a stop below the Spring's low; ride the markup. The mirror schematic governs distribution / shorting.
- **Indicators / patterns**
  - Price action + volume (volume-spread analysis)
  - No fixed indicator — phase detection is qualitative
  - "Composite Man" mental model
- **Typical timeframe** — Bases form over weeks-to-months; trade horizon is multi-week to multi-month.
- **Pros**
  - Deep, internally-consistent framework — explains why bases form, not just what they look like.
  - The Spring entry has an extremely tight, well-defined invalidation (below the Spring low).
  - Volume-spread analysis adds information beyond pure price.
- **Cons**
  - Highly subjective; phase labels are applied retrospectively far more reliably than in real time.
  - LLM-based phase identification is a poor fit — the model will hallucinate phases.
  - No widely-accepted automated detector exists.
- **Fit with our bot** — Wyckoff is the canonical case where "deterministic envelope" is hard to specify because the phases themselves resist formalisation. We could detect Springs as "false breakdown of an N-week range followed by a close back above the range" — that's mechanisable. The full schematic is not. **`needs envelope`** — narrow to a Spring-only detector with explicit geometric rules; ignore higher-level phase labelling entirely.
- **Evidence quality** — `practitioner` (rich tradition, no peer-reviewed validation).
- **Sources**
  - https://www.wyckoffanalytics.com/wyckoff-method/
  - https://www.kagels-trading.de/wyckoff-methode/ (DE)
  - https://www.litefinance.org/blog/for-professionals/wyckoff-method/

---

## 11. Ichimoku Kinkō Hyō (Cloud / Tenkan / Kijun)

- **Mechanism** — Long bias when price is above the Kumo (cloud, formed by Senkou Span A and B projected 26 periods forward). Tactical entry on a Tenkan-sen (9) crossing above Kijun-sen (26) confirmed by a cloud breakout above. Chikou Span (lagging close, –26) must be above price 26 periods ago. Stop below Kijun-sen or below the cloud.
- **Indicators / patterns**
  - Tenkan-sen (9-period midpoint)
  - Kijun-sen (26-period midpoint)
  - Senkou Span A and B (forming the Kumo cloud, projected +26)
  - Chikou Span (lagging close, –26)
- **Typical timeframe** — Originally weekly; daily bars are the modern default; multi-day to multi-week holds.
- **Pros**
  - Self-contained system — entry, exit, support/resistance, and trend filter are all on one chart.
  - Cloud serves as a dynamic, forward-projected support/resistance band — useful for stop placement.
  - Five components produce a high signal threshold; reduces over-trading.
- **Cons**
  - Lag is structural (26-period midpoints lag 26-period highs/lows).
  - Designed for trending markets; chops in ranges.
  - Many subjective decision points: which cross matters most? cloud thickness? Chikou clear?
- **Fit with our bot** — Each Ichimoku signal is computable from price; the "long when above cloud and Tenkan > Kijun" rule is deterministic. Substituting our ATR stop for the Kijun-stop is acceptable. **`fits`** — the indicator stack is mechanisable end-to-end.
- **Evidence quality** — `practitioner` (long Japanese tradition, modern German treatment at kagels-trading and godmode-trader).
- **Sources**
  - https://en.wikipedia.org/wiki/Ichimoku_Kink%C5%8D_Hy%C5%8D
  - https://www.kagels-trading.de/ichimoku-kinko-hyo-indikator/ (DE)
  - https://www.oanda.com/us-en/trade-tap-blog/analysis/technical/ichimoku-cloud-trading-guide-key-strategies/

---

## 12. Elliott Wave (5-3 motive / corrective)

- **Mechanism** — Decompose price into 5 motive waves in the trend direction (1, 2, 3, 4, 5) and 3 corrective waves against (A, B, C). Enter at the start of wave 3 (typically the strongest) after wave 2 retraces 50–61.8%. Stop below the wave-1 low. Targets via Fibonacci extensions of wave 1 (1.618× wave 1 from wave 2 low is the canonical wave-3 target).
- **Indicators / patterns**
  - Pure wave count + Fibonacci retracements / extensions
  - No fixed indicator
- **Typical timeframe** — Scale-invariant in theory; in practice daily and weekly are the swing horizons.
- **Pros**
  - Provides a structural narrative — entries are tied to where you are in the larger move.
  - Fibonacci extensions give explicit price targets.
  - Wave-2 stops are very tight relative to wave-3 magnitude (excellent R:R when correct).
- **Cons**
  - Wave counting is **notoriously subjective** — three analysts produce three counts; the count is often only obvious in hindsight.
  - This is the worst-fit strategy for LLM execution: the model will produce a confident wave count that disagrees between runs of the same prompt.
  - The German practitioner literature (Tiedje at godmode-trader, Weisenhaus/May at stock3) does not improve the determinism — it adds depth and discipline to a fundamentally non-deterministic process.
- **Fit with our bot** — Direct conflict with the architectural invariant. Asking the LLM to count waves is exactly the kind of high-discretion judgement the rules-engine is meant to constrain. There is no deterministic wave-counting algorithm that has stood up to scrutiny. **`skip`**.
- **Evidence quality** — `practitioner` (rich German treatment; no peer-reviewed validation that survives replication).
- **Sources**
  - https://stock3.com/boersenwissen/die-elliott-wellen-theorie-einfach-erklaert-16580426 (DE)
  - https://stock3.com/news/interview-mit-andr-tiedje-die-magie-der-elliott-wellen-1218575 (DE — Tiedje, godmode-trader)
  - https://en.wikipedia.org/wiki/Elliott_wave_principle

---

## 13. Schäfermeier Opening Range Breakout

- **Mechanism** — Define the opening range as the high/low of the first 60 minutes after the cash open. Buy on a break above the range high; short on a break below the range low. Stop at the opposite extreme of the opening range (i.e. for a long, stop = OR low). Profit target via measured-move or fixed R-multiple.
- **Indicators / patterns**
  - Opening-range high / low (first 60 minutes, sometimes 30 or 15)
  - Volume / RVOL filter
  - Optional Heikin-Ashi confirmation
- **Typical timeframe** — Intraday entry on 5- or 15-minute bars; same-day exit (in Schäfermeier's canonical version on DAX / Bund / S&P futures), though daily-bar adaptations exist.
- **Pros**
  - Precise, time-boxed entry — no hunting for setups all day.
  - Stop-loss is built into the structure (opposite extreme of the OR).
  - The opening hour is a real liquidity window; signals are statistically richer here than mid-session.
- **Cons**
  - Originally an intraday futures strategy (DAX, Bund, S&P); adapting to daily-bar US equities loses most of the edge.
  - Stop at the opposite extreme can be wide on volatile open days (full-ATR or more).
  - Heavy slippage risk on equity gaps; the OR is contaminated by the gap itself.
- **Fit with our bot** — Our pipeline runs pre-market on daily bars and submits market orders at open. We have no intraday tick infrastructure to compute a 60-minute opening range, and `MAX_HOLD_DAYS = many` means we'd be retrofitting an intraday strategy onto a swing engine. **`skip`** as currently scoped — adopting it would require a separate intraday agent and a real-time bar feed.
- **Evidence quality** — `practitioner` (Schäfermeier's books and NanoTrader / WHSelfInvest implementations; no academic paper).
- **Sources**
  - https://www.whselfinvest.at/de/Store_Birger_Schaefermeier_Trading_Strategie_Open_Range_Break_Out.php (DE)
  - https://ftmo.com/de/blog/opening-range-breakout-strategie-so-meistern-sie-die-1530-uhr-us-session/ (DE)
  - https://www.trading-fuer-anfaenger.de/open-range-breakout-strategie/ (DE)

---

## 14. Stan Weinstein Stage Analysis (Marktphasen-Modell)

- **Mechanism** — Classify each stock into one of four stages relative to its 30-week SMA: Stage 1 (basing, sideways near MA), Stage 2 (advancing, price > rising MA), Stage 3 (topping, sideways near flattening MA), Stage 4 (declining, price < falling MA). Buy only Stage 2 breakouts on volume; sell at Stage 3 confirmation or on close below the 30-week MA. Hard rule: never own Stage 4 stocks.
- **Indicators / patterns**
  - 30-week SMA (≈ 150-day SMA)
  - Slope of 30-week SMA
  - Relative-strength rating vs market
  - Volume on Stage 2 breakout
- **Typical timeframe** — Weekly bars are the canonical chart; multi-week to multi-month holds.
- **Pros**
  - Mechanically simple regime classifier — every name in the universe is in exactly one of four states.
  - Filters out the worst trades (Stage 4) and the choppiest trades (Stage 1, Stage 3).
  - Pairs well with relative-strength selection.
- **Cons**
  - Long horizon — "swing" only at the upper end (multi-week+).
  - Late entries — by the time Stage 2 is confirmed you've missed the basing-phase accumulation.
  - 30-week SMA reacts slowly to regime change; gives back significant gains at tops.
- **Fit with our bot** — The stage classifier is a clean, deterministic regime filter that could be added as a pre-condition in `RiskReviewAgent` or even at the universe-screening step: "veto any new long whose 30-week SMA is sloping down." Trade-horizon mismatch with our `MAX_HOLD_DAYS` is the same issue as #1. **`needs envelope`** — adopt the regime filter as a veto layer; don't try to mirror the multi-month hold horizon.
- **Evidence quality** — `practitioner` (Weinstein's "Secrets for Profiting in Bull and Bear Markets" is the canonical text; widely cited but not peer-reviewed).
- **Sources**
  - https://www.stageanalysis.net/
  - https://traderlion.com/trading-strategies/stage-analysis/
  - https://trendspider.com/blog/master-market-trends-with-ai-powered-weinstein-stage-analysis/

---

## 15. Voigt'sche Markttechnik (Trend / Bewegung / Korrektur, 1-2-3)

- **Mechanism** — Decompose every trend into Bewegung (impulse) and Korrektur (correction). Number the swing extremes 1, 2, 3: point 1 is the trend origin, point 2 is the first counter-swing, point 3 is the next counter-swing in the trend direction. A break of the most recent point 2 in trend direction is the entry trigger. Stop below the most recent counter-swing low (for longs).
- **Indicators / patterns**
  - Price-action only (HH/HL structure), no indicators in the canonical version
  - Optional: ADX or moving averages as secondary trend filter
- **Typical timeframe** — Scale-invariant; on daily bars the trade horizon is multi-day to multi-week.
- **Pros**
  - Indicator-free — no parameter optimisation, no curve-fitting.
  - Stop placement is structural, not numeric — "below the last point 2" is unambiguous once the count is set.
  - Strong German-language practitioner ecosystem (Voigt, Gabel, kagels-trading).
- **Cons**
  - "Bewegung vs. Korrektur" is timeframe-relative — a Bewegung on the daily can be a Korrektur on the weekly. Counts disagree across analysts.
  - Detecting swing points algorithmically requires a fractal / pivot-detection rule (e.g. ZigZag); without it the count drifts.
  - Critics argue the framework is descriptive after the fact; predictive value is contested in German practitioner circles (TradingFreaks, Kagels).
- **Fit with our bot** — Mechanisable as a swing-pivot detector + "break of last pivot 2 in trend direction" trigger. ATR stops can substitute for "below pivot." Less subjective than Wyckoff or Elliott but in the same family. **`needs envelope`** — codify pivot detection deterministically (e.g. fractal pivots over N bars) and treat the LLM only as a confirmation layer, not the count author.
- **Evidence quality** — `practitioner` (Voigt's "Das große Buch der Markttechnik"; lively German trading community; no academic backing).
- **Sources**
  - https://www.kagels-trading.de/markttechnik-ueberblick/ (DE)
  - https://www.kagels-trading.de/grosse-buch-markttechnik-michael-voigt-rezension/ (DE)
  - https://coin-flip-trading.com/2017/11/markttechnik-trading-strategie.html (DE)

---

## Cross-cutting observations

### Archetypes that fit our deterministic-risk invariant cleanly

- **Donchian breakout (#2)** and **bull-flag continuation (#9)** are the cleanest fits. Entry geometry is codifiable; ATR stops slot in directly; bracket orders cover the exit; no LLM-of-risk dependency.
- **Pullback-to-MA (#5)** is a near-fit and is essentially what `StrategyAgent` already does. ATR stop replaces the "swing-low" stop with no loss of edge.
- **Ichimoku (#11)** is mechanisable end-to-end; the only adaptation is replacing the Kijun-stop with our ATR stop.

These four are `fits`. They share a common property: every meaningful decision can be expressed as a deterministic function of price and volume.

### Strategies that need a deterministic envelope

The `needs envelope` cohort (#1, #3, #4, #6, #7, #8, #10, #14, #15) contains nine of the fifteen. Each requires a specific wrapper:

- **#1 Golden Cross** — extend `MAX_HOLD_DAYS` for crossover trades or accept early exits; add a regime filter to suppress whipsaw.
- **#3 Turtle** — disable pyramiding, single-unit entries, lean on portfolio guardrails for correlation.
- **#4 RSI(2)** — restrict to liquid ETFs; force an ATR-floor on the no-stop canonical version.
- **#6 Cross-sectional momentum** — add a universe-ranking pre-step before `StrategyAgent`; widen max-hold for momentum trades.
- **#7 Bollinger MR** — enforce an ADX regime filter; force take-profit to the midline.
- **#8 Cup-and-handle** — codify cup/handle geometry as a deterministic detector; LLM ranks, doesn't invent.
- **#10 Wyckoff** — narrow to a Spring-only detector with explicit geometric rules.
- **#14 Weinstein** — adopt as a veto layer (no Stage-4 longs), don't mirror the multi-month hold.
- **#15 Voigt-Markttechnik** — codify pivot detection; LLM confirms, doesn't author.

The recurring envelope pattern is "LLM proposes, deterministic detector verifies." This is the same shape as the existing `StrategyAgent` → `RiskReviewAgent` → `tools/risk.py` flow, just extended with strategy-specific detectors before `RiskReviewAgent` runs.

### Strategies to skip

- **#12 Elliott Wave** — non-deterministic by construction; the wave count is what's being asked of the analyst, and the LLM will produce inconsistent counts run-to-run. Direct conflict with the invariant.
- **#13 Schäfermeier ORB** — intraday strategy, our pipeline is daily-bar pre-market. Adopting it would require a separate intraday agent and tick-data feed — out of scope.

### EN vs DE literature: where they disagree

- **Wyckoff / Ichimoku / Stage analysis**: EN and DE sources agree on mechanics. The DE treatment (kagels-trading, godmode-trader) tends to be more pedagogically thorough but reaches identical conclusions.
- **Elliott Wave**: the DE practitioner literature (Tiedje at godmode-trader, Weisenhaus/May at stock3) is *deeper* and more disciplined than the typical EN treatment, but not more deterministic. Both agree on the theory; both fail the same falsifiability test.
- **Voigt Markttechnik**: essentially absent from EN literature. The closest EN cousin is "1-2-3 trading" or "structural swing trading" (HH/HL counts), but the formal Voigt vocabulary (Trendimpuls, Korrektur, Punkt 2) is German-only.
- **Schäfermeier ORB**: the EN literature treats ORB as a US-equity intraday strategy, often on small-caps or leveraged ETFs. Schäfermeier's canonical form is a German-futures (DAX, Bund) intraday strategy — different liquidity profile, different gap behaviour, but the same OR-breakout mechanics.
- **Saisonalität / Halloween effect**: not in our top-15 because it lacks a stand-alone entry/exit specification at the daily-swing level. The DE literature (kagels-trading, sell-in-may.eu) is heavier on the academic Halloween / TOM effect citations than the typical EN site, but the underlying papers (Bouman & Jacobsen 2002, Andrade et al. 2012) are EN. We documented seasonality as anomaly-stacking material below.

### Evidence-quality split

Of the 15 entries:

- **Academic** (peer-reviewed factor literature with replications): **1** — cross-sectional momentum (#6).
- **Practitioner** (well-known trader, book, or serious practitioner site, with replicated backtests): **14** — everything else. Within this bucket, RSI(2) (#4) and Cup-and-Handle (#8) lean closer to marketing on their original sites, but external replications (QuantifiedStrategies, Bulkowski) keep them out of pure marketing.
- **Marketing** (course-seller / hype only): **0** — by construction, since we required a citable practitioner or academic URL.

Honest framing: only **momentum (#6)** has the kind of peer-reviewed, multi-decade, multi-asset, multi-geography replication record that survives normal academic scrutiny. The other 14 have practitioner traction but should be treated as plausible, not proven.

### Anomaly-stacking footnote (Stagge, seasonality, TOM)

We considered listing André Stagge's anomaly-stacking strategies (Turnaround Tuesday, Friday Gold Rush, triple-witching, holiday-effect entries) and the academic Turn-of-the-Month / Halloween effect as separate top-15 entries but excluded them from the strategies-proper list because:

- They are **filters / overlays**, not stand-alone swing strategies. "Buy DAX on Monday close, exit Wednesday open" doesn't carry an entry/exit/stop specification on a per-symbol basis the way Donchian or pullback-MA do.
- The TOM and Halloween effects are statistically robust (Lakonishok & Smidt 1988, Bouman & Jacobsen 2002, Andrade et al. 2012) and would be better implemented as a regime / sizing modifier on top of one of the 14 fitting strategies than as a stand-alone trade.

Sources for the anomaly-stacking layer (kept here so the roadmap doc can pick them up):

- https://www.andre-stagge.de/wissenschaftliche-publikation/ (DE — Stagge's published material)
- https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes (TOM in equity indexes)
- https://www.sciencedirect.com/science/article/abs/pii/S0927538X22001214 (TOM effect academic)
- https://sell-in-may.eu/wissenschaft/ (DE — Halloween / Sell-in-May academic literature)
- https://www.kagels-trading.de/halloween-strategie/ (DE)
- https://business.purdue.edu/faculty/mcconnell/publications/Equity-Returns-at-the-Turn-of-the-Month.pdf (TOM, Purdue)

### Implications for `RiskReviewAgent` and `tools/risk.py`

High-level only — the roadmap document will translate these into work items.

- **Regime filters belong in `tools/risk.py`**, not in agent prompts. Stage analysis (#14), Bollinger-MR (#7), and momentum (#6) all benefit from a deterministic regime classifier (200-day-SMA slope, 30-week-SMA stage, ADX threshold) computed once and consumed by `RiskReviewAgent`.
- **Pattern detectors belong upstream of `StrategyAgent`**, not inside it. Cup-and-handle (#8), bull-flag (#9), Wyckoff Spring (#10), and Voigt pivots (#15) can each be implemented as a deterministic geometric detector that surfaces candidates; the LLM ranks among them rather than inventing them.
- **The ATR-floor on stops is the universal envelope.** Several canonical strategies (RSI(2) with no stop; Bollinger MR with "lowest low of entry candle" stop; Connors-style index trades) violate our bracket-order invariant. The fix in every case is the same: enforce `stop ≥ k × ATR` regardless of what the LLM proposes.
- **`MAX_HOLD_DAYS` is the second universal envelope.** Strategies #1, #6, and #14 have natural multi-month hold horizons. Either widen `MAX_HOLD_DAYS` for those entries (with a per-strategy override) or accept that we're harvesting only the first leg.
- **No new strategy should ship without first specifying its deterministic pre/post conditions** — this is the architectural invariant in `CLAUDE.md` applied to strategies, not just to risk parameters.
