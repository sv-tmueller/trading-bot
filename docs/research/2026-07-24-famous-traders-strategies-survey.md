# Famous traders & strategies — survey for a rule-based hourly SL/TP candidate

**Question:** Among the well-known traders and named strategies, which reduce to a **deterministic
rule with an explicit stop-loss and take-profit** that a bot could run at **hourly (or daily)**
cadence — and which are genuinely worth pre-registering + backtesting versus which are re-badges of
rule families this repo has already class-killed, or discretionary methods that cannot be
systematized at all?

**Date:** 2026-07-24
**Author:** Analyst (research-only; `CLAUDE_AGENT_NO_BROKER=1` set for the whole session; no
production/TypeScript code, no `strategy/`, no `backtest/*.py`, no settings, no broker integration
touched; no order placed. This is a web survey — every factual claim carries a source URL + access
date; nothing is filled from memory).

> **Framing note.** This survey does **not** re-litigate the two prior verdicts it sits downstream of
> — it reconciles against them. The short-horizon rule-based-**entry** feasibility gate
> (`docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md`, #422) reached **NO-GO**, and the
> 4h EUR/USD survey (`docs/research/2026-07-15-forex-4h-survey-verdict.md`, #379) reached **CLASS KILL,
> 0/33**. The value added here is narrow and specific: take the *famous names* the operator asked
> about, map each onto the rule taxonomy, and **honestly separate** the ones that are just those
> already-killed families wearing a trader's name from the (few) that are not literally in the kill
> registry. Where a famous strategy is a re-badge of something already dead, the survey says so
> bluntly; it does not manufacture a fresh "promising direction."

---

## §0 The bar and the taxonomy every candidate is judged against

**The promotion bar** (unchanged, quoted so nothing below drifts from it): after-tax **Calmar** vs
SPY buy-and-hold's **median-window** after-tax Calmar of **1.3085475049604838** on the frozen **n_w =
13** calendar-year walk-forward windows, through the #398 overfitting gate (`DSR ≥ 0.95`, `PBO < 0.5`,
moving-block-bootstrap `CI_low > 0` on uplift vs baseline —
`docs/research/2026-07-21-overfitting-gate-usage.md`). A candidate that cannot even be *tested* to
that bar on available data is not a candidate.

**The rule taxonomy already killed** (the exact frozen grid of the 4h forex survey,
`docs/research/2026-07-13-forex-4h-strategy-preregistration.md` §3, all 0/33):

| Family | Frozen shapes killed at 4h forex |
|---|---|
| Trend / MA-cross | SMA 5/20, 20/50, 50/200 |
| Breakout | Donchian 20, Donchian 55 |
| Momentum | ROC/TSMOM 12, 24, 48 |
| Mean-reversion (oscillator) | RSI(14) 30/70, RSI(2) 10/90 |
| Mean-reversion (band) | Bollinger(20, 2) |
| Intraday breakout (colleague) | London Open-Range-Breakout — *"Intraday-Frage endgültig geschlossen"* (`docs/research/2026-07-20-colleague-repo-audit.md` §2) |

Plus the **scalping cost-wall** empirical kill: a faithful multi-confirmation ATR-trend scalp
(Supertrend + ADX + volume + MACD, `2·ATR` stop + ATR trailing take-profit) on real BTC had **no gross
edge even at zero cost** (profit factor 1.02, win rate 37%, break-even cost 0.000% —
`docs/research/2026-06-23-scalping-cost-wall-demonstration.md`), and finer cadence only deepened the
loss (−34% → −74% → −98% at 1h → 15m → 5m). And the **data wall**: no *free* intraday history reaches
n_w = 13 — only *daily* SPY (1993, n_w ≈ 33) and ES (2000, n_w ≈ 26) do
(`docs/research/2026-07-24-short-horizon-entry-feasibility-gate.md` §3).

**The load-bearing generalization** (`…leveraged-contracts-preregistration.md` §3, restated in #422
§4): *"rules-based" does not create edge — the killed candidates were all rules-based.* Edge must come
from the **entry signal**, and a MA-cross / breakout / oscillator is the same signal whether it runs on
EUR/USD, SPY, or MES, and whether a trader's name is attached to it. So the operative test for each
famous strategy below is: **does it introduce an entry signal that is NOT one of the killed families,
and can it be run deterministically at hourly/daily with an explicit SL/TP?**

---

## §1 Survey table

Legend — **Systematizable?** Yes = reduces to a deterministic rule with no human judgment; Partly =
core is mechanical but a load-bearing input (zone, level, "significant" move) needs discretion; No =
irreducibly discretionary. **Killed?** = is this essentially a rule family already class-killed in this
repo. **Hourly-coherent?** = does an hourly-candle version keep the strategy's character, or does it
collapse into the killed intraday-breakout zone. **Free-testable?** at hourly/daily given the data wall.

| # | Trader / strategy | Core rule (entry · stop · target) | Native TF | Systematizable? | Already killed? | Hourly-coherent? | Free-testable? |
|---|---|---|---|---|---|---|---|
| 1 | **Turtles / Richard Dennis & Eckhardt** | Entry: buy 20-day high (Sys 1) / 55-day high (Sys 2). **Stop: 2N** (N = 20-day ATR). **Exit: 10-day low (Sys 1) / 20-day low (Sys 2)** — a trailing channel exit, not a fixed TP. Pyramid +1 unit every ½N. [S1] | **Daily** | **Yes** | **Yes — Donchian 20/55 breakout, 0/33 at 4h** | No — "20-day" → "20-hour" = intraday breakout (killed) | **Daily: yes** (SPY/ES). Hourly: no (n_w wall) |
| 2 | **Donchian channel breakout** | Buy close > 20-period high; sell close < 20-period low; midline = (HH+LL)/2. Stop = opposite band / mid. [S2][S3] | Daily | **Yes** | **Yes — this *is* the killed breakout family** | No (same collapse as Turtles) | Daily yes / hourly no |
| 3 | **Darvas box** | Define a box (recent consolidation high/low). **Entry: break of box top on rising volume. Stop: just below box bottom. Exit: trail stop below each successive box.** [S4][S5] | Daily/weekly | **Partly** — box lookback needs a discretionary "not far from the high" rule | **Yes — consolidation-breakout = Donchian re-badge** | No (intraday box = killed intraday breakout) | Daily yes / hourly no |
| 4 | **Ed Seykota (EMA crossover TF)** | First published system: **exponential-MA crossover**, long when fast EMA > slow EMA; cut losses fast; ride trend. No fixed TP. [S6][S7] | Daily | **Yes** | **Yes — MA-cross (T1 SMA cells), 0/33 at 4h** | No (fast MA-cross at hourly = whipsaw, killed) | Daily yes / hourly no |
| 5 | **Bill Dunn / Dunn Capital** | **100% mechanical** long-term trend following, volatility-adjusted position sizing, no discretionary overrides. Signal family = breakout/MA trend. [S8] | Daily/weekly | **Yes** (by design) | **Yes — long-term trend family** | No (it is explicitly a *slow* system) | Daily yes / hourly no |
| 6 | **Time-series momentum / CTA (Moskowitz-Ooi-Pedersen 2012)** | Sign of trailing **12-month** excess return → long/short, 1-month hold, vol-scaled. [S9] | Monthly | **Yes** | **Yes — already carried as `tsmom-12mo` baseline** (strongest baseline, but *"the floor, not a survivor"*, `…first-cut` §Rec) | No — it is a 12-month signal | Daily yes / hourly no |
| 7 | **Opening-Range Breakout (ORB)** | **Entry: break of first-N-minute range high/low. Stop: opposite side of range (or k·ATR). Target: measured-move / R-multiple, or exit-at-close.** [S10][S11] | Intraday (5–30 min) | **Yes** | **Partly — colleague killed London-ORB;** but a *specific* 5-min US-equity ORB has a **published positive result** (Zarattini & Aziz 2023, see §2.2) [S11] | **Yes — intraday-native** (its whole character) | **No** — free intraday only to ~2016 (n_w ≈ 9) |
| 8 | **Wyckoff (accumulation/spring, distribution/upthrust)** | Entry after spring recovery / breakout of range on volume; stop below spring low. [S12][S13] | Daily/swing | **No** — phase & range identification is discretionary | Underlying trigger is breakout/mean-reversion | n/a | n/a |
| 9 | **ICT / Smart-Money-Concepts (order blocks, FVG, liquidity)** | Enter on retrace into an "order block" (last opposite candle before an impulse) / fair-value gap; stop beyond the block. [S14][S15] | Intraday | **No** — "significant move", "the" block, kill-zone timing are discretionary/unfalsifiable | Re-skin of supply/demand + breakout | n/a | n/a |
| 10 | **Support / resistance & supply/demand zones** | Buy at support / sell at resistance, or trade the break; stop beyond the level. | Any | **Partly/No** — level selection is discretionary | Re-badge of mean-reversion / breakout | n/a | n/a |
| 11 | **Jesse Livermore (pivotal points)** | Wait for a "pivotal point" (a level price fails to exceed), trade the break *with confirmation of price + volume*; cut losses fast; "sit" in winners. [S16][S17] | Daily/swing | **No** — pivot selection + "confirmation" are judgment calls | Discretionary breakout | n/a | n/a |
| 12 | **George Soros (reflexivity)** | Macro thesis: perception ↔ price feedback loops create then unwind mispricings; bet big when the thesis is asymmetric. [S18][S19] | Macro / months | **No** — it is a worldview, not a mechanical rule | — | n/a | n/a |
| 13 | **Paul Tudor Jones (discretionary macro)** | Global-macro fundamentals + technicals; **risk ≤ 1%/trade, target ~5:1 reward:risk** (can be wrong 80% and still win). The 5:1 / 1% are *risk-management overlays*, not an entry signal. [S20][S21] | Discretionary | **No** — entry is discretionary macro | — | n/a | n/a |

---

## §2 Shortlist — the honest 2 (both flagged with the wall they hit)

The screen for a shortlist slot: **(a) fully systematizable, (b) NOT literally in the kill registry in
this exact form, (c) coherent at hourly *or* daily, (d) testable on free data.** Only two famous
strategies clear even a charitable reading of that screen — and **neither is clean**; each is placed
here with the wall it runs into stated up front, so this is a "least-dead, cheap-to-settle" list, not a
list of promising edges.

### 2.1 Candidate A — Turtle/Donchian breakout with an *explicit* 2N stop + fixed R-multiple TP, on SPY/ES **daily**

This is the only famous, fully-mechanical, explicit-SL/TP strategy that (i) is testable to the **full
free-data depth** (SPY 1993 → n_w ≈ 33; ES 2000 → n_w ≈ 26) and (ii) is **not literally a row in the
kill registry** — the 4h forex survey killed Donchian 20/55 with a stop parameter *on 4h EUR/USD*, but
**no run in this repo has tested a Donchian breakout with a `2N` ATR stop and a fixed take-profit on
SPY/ES daily through the #398 overfitting gate**. The operator explicitly allowed "(or daily)", and
this is the daily candidate.

**Crisp rule a backtest can implement directly (freeze before running):**
- **Entry (long-only first; symmetric short as a variant):** at daily close, if `close > max(high, 55)`
  (highest high of the prior 55 completed daily bars, today's bar excluded), go long at next open.
- **N (volatility unit):** `N = ATR(20)` on daily bars (Wilder ATR).
- **Stop-loss (explicit):** `entry − 2·N`, fixed at entry (the canonical Turtle 2N stop [S1]).
- **Take-profit (explicit — this is the deliberate change that gives it the SL/TP shape the operator
  wants, replacing the Turtle's 10/20-day trailing channel exit):** `entry + 3·N` (a 1.5:1 reward:risk
  bracket; pre-register the R-multiple grid `{2N, 3N, 4N}` as the *only* free parameter and count it in
  the DSR trial count `N`).
- **No pyramiding, no discretionary overlay** — one unit, one bracket, deterministic.
- **Universe/cadence:** SPY (and ES=F as a robustness leg) **daily**; free yfinance data; costs at the
  repo's existing per-side model; after-tax Calmar vs the 1.3085 bar on n_w = 13 windows (with the
  extra deep windows reported).

**The wall, stated honestly:** this is a **trend/breakout family**, and every independent line of
evidence in the repo points the same way — the family was 0/33 at 4h forex, and the low-turnover survey
found trend variants (Faber single, tsmom-12mo) *beat SPY only marginally and did not clear the bar*
(`docs/research/2026-06-24-candidate-strategy-survey-first-cut.md`). **Expectation: this most likely
reconfirms the trend-family kill on daily US equities.** It earns a shortlist slot only because it is
(1) the single famous SL/TP strategy that is *cheap to settle for free* and (2) *not yet literally run*
in this exact bracket form — i.e. it converts "probably dead" into "measured and recorded", which is
the repo's own honesty convention. Pre-register with low prior.

### 2.2 Candidate B — Opening-Range Breakout with an explicit bracket (the one intraday setup with a *published* positive result)

ORB is the **only intraday-native** famous strategy that is fully systematizable **and** has explicit
SL/TP by construction **and** carries an external, quantified positive result: Zarattini & Aziz (2023),
*"Can Day Trading Really Be Profitable?"* backtested a **5-minute ORB on QQQ/TQQQ, 2016–2023**, reporting
QQQ total return ~675% with ~33% annualized alpha net of commissions, and ~1,484% on TQQQ [S11]. That is
the single strongest published counter-example to this repo's intraday pessimism, so it is listed rather
than silently dropped.

**Crisp rule (freeze before running):**
- **Opening range:** high/low of the first 5-minute (variant: 15-minute) bar after the US open.
- **Entry:** at the open of the next bar, in the direction of the first bar's sign (long if first bar
  closed up, short if down); skip if the first bar's open ≈ close [S11].
- **Stop-loss (explicit):** opposite side of the opening range, or `k·ATR(14)` (Zarattini used a stop
  of a fixed ATR fraction) [S10][S11].
- **Take-profit (explicit):** measured-move (range height added to breakout) or R-multiple; the paper's
  simplest variant uses **exit-at-close** with no profit target — pre-register which.
- **One trade per side per session; no re-entry after a failed break** [S10].

**The wall, stated bluntly — this is largely already answered "no" for us:**
1. **Intraday-entry class = NO-GO.** #422's feasibility gate ruled the whole hourly/minute rule-based-
   entry class NO-GO, and the colleague's own London-ORB variants *all lost* (*"Intraday-Frage endgültig
   geschlossen"*, `…colleague-repo-audit.md` §2). ORB is squarely inside that ruled-out class.
2. **Data wall.** Free intraday history reaches only ~2016 (SPY 5-min SIP → n_w ≈ 9; IEX → n_w ≈ 5),
   short of the frozen n_w = 13 bar (`…entry-feasibility-gate.md` §3). The Zarattini window (2016–2023)
   is itself too short and single-regime to clear our comparability bar, and its result is
   **instrument-and-era-specific** (QQQ/TQQQ, a historically strong tech-momentum window).
3. **PDT + cost.** Sub-$25k the 5-min variant is PDT-illegal on US equities; the leveraged-ETF (TQQQ)
   route sidesteps leverage limits but not PDT or the data wall.

**Verdict on B:** worth pre-registering **only if** the operator explicitly (i) accepts spending for
intraday data deep enough to reach n_w = 13 (Databento/FirstRate — a budget decision #422 was not
authorized to make) and (ii) accepts that it re-tests a class the repo already ruled NO-GO. On free
data it **cannot be tested to the bar**. It is the *most interesting* famous candidate and the *least
cleanly dismissable*, which is exactly why it is named — but it is not a free, defensible test today.

---

## §3 Not worth testing (with the one-line reason each)

**Re-badges of an already-killed rule family** (testing them again is re-running a dead cell with a
trader's name on it):

- **Donchian channel breakout (#2)** — *is* the killed breakout family (Donchian 20/55, 0/33 at 4h);
  Candidate A already covers the only untested slice (daily SPY/ES with 2N + fixed TP).
- **Darvas box (#3)** — consolidation-breakout = a Donchian re-skin; adds a discretionary box-lookback
  rule without adding a new entry signal.
- **Ed Seykota EMA crossover (#4)** — MA-cross, killed as the T1 SMA cells (0/33 at 4h); at hourly it is
  a whipsaw generator.
- **Bill Dunn (#5)** — long-term mechanical trend following; the *family* (breakout/MA trend), already
  killed/marginal; nothing new to test that Candidate A doesn't cover.
- **Time-series momentum / CTA (#6)** — already carried as the `tsmom-12mo` baseline; it is *the floor a
  survivor must beat, not a survivor* (`…first-cut` §Rec), and it is a 12-month, not hourly, signal.
- **Support/resistance & supply/demand (#10)** — a re-badge of breakout/mean-reversion whose only novel
  content (which level?) is discretionary.

**Discretionary — not deterministically systematizable at all** (they cannot be reduced to a rule a bot
runs without judgment, so they fail invariant-compatibility before any backtest):

- **Wyckoff (#8)** — accumulation/distribution *phase* and range identification are chart-reading
  judgment; the "spring" is only labelled a spring in hindsight.
- **ICT / Smart-Money-Concepts / order blocks (#9)** — "the" order block, "significant" impulse, and
  kill-zone timing are discretionary and, as a framework, effectively unfalsifiable; not a deterministic
  signal.
- **Jesse Livermore pivotal points (#11)** — pivot selection plus "wait for confirmation" are judgment
  calls; the durable content ("cut losses, sit in winners") is risk-management wisdom, not an entry rule.
- **George Soros reflexivity (#12)** — a macro worldview about feedback loops, not a mechanical trigger.
- **Paul Tudor Jones global macro (#13)** — discretionary macro entries; the famous **5:1 reward:risk
  and 1% risk-per-trade are position-sizing/exit overlays** (applicable to *any* system, including the
  live bot) — not a systematizable entry signal.

> Note on the risk-management overlays: PTJ's 5:1 R:R and the Turtle 2% unit are the *only* portable,
> deterministic ideas in the discretionary group — but they are **exit/sizing rules, not entry signals**,
> and edge in this repo has always failed at the *entry*, never at the sizing. An SL/TP bracket is worth
> keeping as the *execution wrapper* for Candidate A; it does not by itself manufacture edge.

---

## §4 Bottom line (blunt)

**There is no clean, defensible, genuinely-untested *hourly* SL/TP candidate in the famous-trader
canon.** The survey mostly **reconfirms that the rule families are exhausted**:

- Every famous strategy that is *fully systematizable* — Turtles, Donchian, Darvas, Seykota, Dunn, CTA
  time-series-momentum — is a **trend / breakout / momentum** system, i.e. exactly the families this
  repo class-killed at 4h forex (0/33) and found only marginal-and-non-clearing at daily. Attaching a
  legendary name does not add an entry signal.
- Every famous strategy that is *not* one of those killed families — Wyckoff, ICT/SMC/order-blocks,
  support/resistance, Livermore, Soros, PTJ — is **discretionary** and cannot be reduced to a
  deterministic bot rule at all (so it also fails the one-decision-rule invariant framing before any
  backtest).
- The *hourly* framing specifically makes the systematizable ones **worse**, not better: a Turtle
  "20-day" breakout becomes a "20-hour" intraday breakout, which is the intraday-entry class #422 ruled
  **NO-GO** and the colleague closed ("endgültig geschlossen").

**The one thing worth doing** is Candidate A: pre-register a **Turtle/Donchian daily breakout with an
explicit 2N ATR stop and a fixed R-multiple take-profit on SPY (+ ES robustness leg)**, run once through
the #398 overfitting gate against the 1.3085 after-tax-Calmar bar. Rationale is *not* optimism — it is
that this is (1) the single famous SL/TP strategy that is *free to settle* to full data depth and (2)
*not literally in the kill registry* in this bracket form, so it cheaply converts "almost certainly a
trend-family re-kill" into a measured, recorded result. **Pre-register it with a low prior; expect it to
reconfirm the trend-family kill.**

Candidate B (**ORB with an explicit bracket**) is the *most interesting* famous candidate — the only
intraday setup with a published positive result (Zarattini & Aziz 2023 [S11]) — but it is squarely
inside the intraday-entry class already ruled NO-GO, the colleague already killed the ORB variant, and
**free data cannot test it to n_w = 13**. It is worth a slot only as a "spend-to-settle" option if the
operator wants to buy intraday history and knowingly re-open the NO-GO gate; it is not a free,
defensible test today.

**So: shortlist of effectively 1 free candidate (Turtle-daily-SL/TP, low prior) + 1 paid/optional
(ORB).** This is the honest result, not padded pessimism: it holds across every famous name surveyed,
and it rests on the named strategies mapping cleanly onto families the repo already measured. The live
200-DMA/UPRO bot is untouched; nothing here is a second decision rule.

---

## Sources (all accessed 2026-07-24)

Reachability note: the canonical *Original Turtle Trading Rules* PDF
(`tradingwithrayner.com/.../OriginalTurtleRules.pdf`, a mirror of Curtis Faith's release) fetched as
**binary/undecodable** via the survey's fetch tool — the Turtle rule specifics below were taken instead
from the TrendSpider learning-center page [S1] and the search-surfaced summaries, which agree on the
20/55-day entries, 10/20-day exits, N = 20-day ATR, and 2N stop. All other sources returned as readable
text.

- **[S1]** Turtle rules (Systems 1 & 2, N = 20-day ATR, 2N stop, ½N pyramiding) — TrendSpider Learning
  Center, "Richard Dennis Turtle Trading Strategy". https://trendspider.com/learning-center/richard-dennis-turtle-trading-strategy/
- **[S2]** Donchian channel definition & 20-day breakout — QuantifiedStrategies, "Donchian Channels
  Trading Strategy". https://www.quantifiedstrategies.com/donchian-channel/
- **[S3]** Donchian / Turtle 20-day breakout, 10-day exit — Deepvue, "Donchian Channels". https://deepvue.com/indicators/donchian-channels-the-breakout-traders/
- **[S4]** Darvas box entry/stop/trail — TrendSpider Learning Center, "Darvas Box Theory Trading
  Strategy". https://trendspider.com/learning-center/darvas-box-theory-trading-strategy/
- **[S5]** Darvas box construction & volume-confirmed breakout — FXOpen, "What Is a Darvas Box Theory".
  https://fxopen.com/blog/en/what-is-a-darvas-box-theory-and-how-does-it-work-in-trading/
- **[S6]** Ed Seykota EMA-crossover trend system — DayTrading.com, "Ed Seykota Trading Strategy &
  Philosophy". https://www.daytrading.com/ed-seykota
- **[S7]** Ed Seykota exponential-MA system & "cut losses" — New Trader U, "Ed Seykota Strategy".
  https://www.newtraderu.com/2022/05/08/ed-seykota-strategy/
- **[S8]** Bill Dunn / Dunn Capital — 100% mechanical trend following, no discretionary overrides —
  TurtleTrader.com, "Bill Dunn". https://www.turtletrader.com/trader-dunn/
- **[S9]** Time-series momentum (12-month, 1-month hold, 58 futures) — Moskowitz, Ooi & Pedersen (2012),
  *Time Series Momentum*, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- **[S10]** Opening-Range Breakout rules (range, break, opposite-side stop, R-multiple target) —
  LiteFinance, "Opening Range Breakout (ORB) Strategy". https://www.litefinance.org/blog/for-beginners/trading-strategies/opening-range-breakout-strategy/
- **[S11]** Zarattini & Aziz (2023), *Can Day Trading Really Be Profitable? … Opening Range Breakout …*,
  SSRN 4416622 (5-min ORB on QQQ/TQQQ, 2016–2023, ~33% annualized alpha). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622
- **[S12]** Wyckoff phases, spring, upthrust — TradingSim, "Wyckoff Method Trading". https://www.tradingsim.com/blog/wyckoff-method-trading
- **[S13]** Wyckoff method (three laws, accumulation/distribution) — Wyckoff Analytics, "The Wyckoff
  Method". https://www.wyckoffanalytics.com/wyckoff-method/
- **[S14]** Order blocks / smart-money definition — Equiti, "Order blocks: How smart money trades in
  forex". https://www.equiti.com/sc-en/news/trading-ideas/order-blocks-how-smart-money-trades-in-forex/
- **[S15]** ICT vs SMC, order blocks / FVG / kill zones — FXOpen, "Order Blocks and Breaker Blocks of
  the Smart Money Concept". https://fxopen.com/blog/en/order-blocks-and-breaker-blocks-of-the-smart-money-concept/
- **[S16]** Jesse Livermore stock-trading rules (cut losses, sit, confirmation) — jesse-livermore.com,
  "Stock Trading Rules". https://jesse-livermore.com/trading-rules.html
- **[S17]** Livermore pivotal points & confirmation — Trade That Swing, "Swing Trading Lessons From
  *How to Trade In Stocks*". https://tradethatswing.com/swing-trading-lessons-from-how-to-trade-in-stocks-by-jesse-livermore/
- **[S18]** Soros reflexivity (perception↔price feedback) — Admiral Markets, "Theory of Reflexivity".
  https://admiralmarkets.com/education/articles/trading-psychology/theory-of-reflexivity-definition-soros
- **[S19]** Soros reflexivity, self-reinforcing mispricing then unwind — Macro-Ops, "Understanding
  George Soros's Theory of Reflexivity". https://macro-ops.com/understanding-george-soross-theory-of-reflexivity-in-markets/
- **[S20]** Paul Tudor Jones — 5:1 reward:risk, 1% risk/trade — Macro-Ops, "Lessons From a Trading
  Great: Paul Tudor Jones". https://macro-ops.com/lessons-from-a-trading-great-paul-tudor-jones-ptj/
- **[S21]** Paul Tudor Jones macro + technical, 5:1 R:R — LuxAlgo, "Paul Tudor Jones — Macro Playbook".
  https://www.luxalgo.com/blog/paul-tudor-jones-macro-playbook-for-traders/
