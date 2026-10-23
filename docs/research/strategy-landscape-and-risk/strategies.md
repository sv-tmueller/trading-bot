# Strategy Landscape and Risk -- Survey

**Question (operator, 2026-10-23).** "What are other bots and the millions of human traders doing, what's the general approach, what could be good strategies, should we combine strategies, and what do they usually risk?" Tied to issue #675: raise effective risk per trade. Today it is ~0.025% of equity, because the 10% notional cap binds on SPY hourly stops. The incumbent hourly candlestick rule (`decideHourly`) measured **-0.139R per trade** on SPY 2016-2026 at 1 bp/side (`docs/research/2026-10-22-multi-symbol-hourly-verdict.md`, branch `research/multi-symbol-hourly`).

**Date:** 2026-10-23.

**Method.** Three research agents plus this merge:
- **S-EN** covered English-language sources: 20 archetypes plus a landscape synthesis.
- **S-DE** covered German-language sources: practitioner strategies, regulator loss data, German risk norms and a repo-overlap map.
- **P** covered risk norms and strategy combination (Kelly, vol targeting, loss limits, risk of ruin, gap risk, diversification math).
- The merge also reads the sibling `github-projects.md` (framework defaults) and the repo's own verdict docs, which feed the "Repo status" lines.

**Source mix.** Academic papers (JF, JFE, RFS, QJE, JPM, FAJ, NBER/SSRN), regulator publications (ESMA, BaFin, BIS), fund filings (AQR SEC filings), official prop-firm rule pages (FTMO, Topstep), the primary Turtle rules PDF, the Alpaca PDT announcement, German practitioner and vendor pages (stock3, Kagels, WH SelfInvest, Seasonax), and English practitioner aggregators (CXO Advisory, Alpha Architect, Quantpedia).

**Honest coverage note.**
- **Most English-language numbers come from abstracts, publisher pages or secondary summaries** (CXO, Alpha Architect, Quantpedia, RePEc), not full-text reads. S-EN marks secondary-only figures inline, and this doc keeps those marks.
- **German sources** are marked "(opened)" or "(search)" in the S-DE input. Search-only items are one step less certain.
- **Agent P** grades its sources [primary] / [secondary] / [weak]. Those grades are kept where they matter.
- Nothing below is cited from memory. Every URL comes from the three agent inputs or from the repo.
- **Coverage gaps:** no public per-trade risk norm for professional desks or market makers was found; pod-shop loss rules come from the press only; and several vendor backtests (Seasonax, Gebert, Stagge) could not be independently checked.

**How to read the verdicts.** Each entry ends with **`fits`**, **`needs envelope`** (plus a one-sentence envelope), or **`skip`**. The verdict is judged through the deterministic-risk lens in `CLAUDE.md` "Architectural invariants" and the README rule that an LLM must never control risk parameters. It answers one question: can this be run with deterministic, config-bounded risk on this bot's stack (`_shared/config.ts` sizing bounds, `hourly-check` gates, the `kill-switch` function, `bot_config.paused`, side-aware `panic`, and the paper-only guard)?

The verdict is **not** an endorsement of edge. Edge is covered by the Evidence and Repo status lines.

Separately, the **One decision rule** invariant means that any strategy other than the incumbent `decideHourly` would be either a replacement or a second rule. Either way it needs a fresh brainstorm, a design spec and an ADR before it can trade.

---

## The landscape in one page

### What "the general approach" actually is

Durable trading profit comes from three economic sources (S-EN synthesis). Everything else is a delivery mechanism around one of them.

1. **Risk premia, which pay you for bearing pain.**
   - Trend and time-series momentum: long convexity, but multi-year droughts.
   - Cross-sectional momentum and value: momentum crashes.
   - Carry: crashes in global recessions.
   - The volatility risk premium: short-gamma tails such as Volmageddon.
2. **Behavioural or flow-driven mispricing.**
   - Under-reaction (momentum).
   - Paid liquidity provision (short-term reversal, pairs).
   - Calendar flows (turn of month, pre-FOMC).
   - These are real but decay after publication. McLean-Pontiff measure returns 58% lower post-publication.
3. **Structural and speed advantages.** Market making, rebates and latency. These are winner-take-all (CFTC HFT data, Virtu).

No peer-reviewed evidence found by either research agent shows pattern-recognition technical analysis (candlesticks, Wyckoff, Elliott, Ichimoku) to be an edge source in its own right.

### What profitable operators have in common

- **A named edge source** from the list above, not a chart pattern.
- **Breadth.**
  - Trend following works across 58 futures (MOP 2012) and across 67 markets since 1880 (Hurst-Ooi-Pedersen).
  - Value and momentum work across eight asset classes (Asness-Moskowitz-Pedersen).
  - Per-instrument trend returns are weak (Kim-Tse-Wald).
  - Many small, partly independent bets are what make a modest edge visible.
- **Low per-bet risk, controlled at the portfolio level.**
  - Turtles: about 2% of equity per unit at the stop.
  - ORB paper: 1% per trade with a 4x leverage cap.
  - CTAs: about 10% annualised volatility for the whole programme (AQR states 5-13%).
  - HFT: intraday inventory limits and real-time kill switches.
  - No profitable archetype in the evidence risks 5-10% per trade.
- **Cost control as the denominator of the edge.**
  - Weekly reversal survives only in large caps with turnover-aware construction.
  - The headline ORB result evaporated in one independent replication once spread and slippage were charged.
  - Post-2003 pairs profits are 20-40 bp per month (Do-Faff).
- **Blow-ups come from leverage plus negative skew plus crowding:** XIV in February 2018, the August 2007 quant unwind, grid and martingale bots in trends.

### Why most retail traders and bots lose

This is the strongest evidence in the whole survey. It is regulatory and academic, not marketing.

| Population | Finding | Source (grade) |
|---|---|---|
| Brazil, mini-index futures day traders, 300+ days (2013-2015) | **97% lost money**; 0.4% earned more than a bank teller's wage; no evidence of learning | Chague, De-Losso, Giovannetti 2019 (academic; abstract / CXO summary) |
| Taiwan, TWSE day traders (1992-2006) | **under 1%** predictably and reliably profitable net of fees; about 97% likely to lose | Barber, Lee, Liu, Odean (academic) |
| US brokerage households (1991-1996) | most active traders earned 11.4%/yr vs 17.9% for the market | Barber-Odean, JF 2000 (academic) |
| EU retail CFD accounts | **74-89% lose money**; average loss EUR 1,600-29,000 per client | ESMA 2018 (regulator) |
| German turbo / knock-out clients, 2019-2023 (543,000 clients, 113m transactions) | **74.2% lost money**; average loss about EUR 6,358; total above EUR 3.4bn | BaFin study, 2025 (regulator, via otto-schmidt.de) |
| German CFD broker disclosure | "76% of retail investor accounts lose money when trading CFDs with this provider" | WH SelfInvest mandatory disclosure |
| wikifolio social trading, copy-the-best-performers each month | **-79% over 29 months** (ayondo: -92% over 36 months); risk-adjusted selection still lost about 13% | Dorfleitner et al. 2018 (academic, via AAII summary) |
| wikifolio certificates on average | no outperformance; the best outperform only short-term | Oehler, Horn, Wendt 2016 (academic) |
| Crypto app users, Aug 2015 - Dec 2022 | a majority in nearly all economies lost money on bitcoin | BIS Bulletin 69, 2023 (regulator) |
| 888 crowd-sourced Quantopian algorithms | backtest Sharpe R² < 0.025 for out-of-sample Sharpe; worse with more backtesting | Wiecki et al. 2016 (academic) |

The mechanisms visible in that evidence (S-EN, S-DE):
- **(a) Costs and turnover** eat a thin or zero gross edge.
- **(b) Overfitting.**
  - Backtest Sharpe does not predict live Sharpe.
  - 65% of 452 anomalies fail |t| ≥ 1.96 once microcaps are controlled (Hou-Xue-Zhang).
  - Published anomalies decay after publication (McLean-Pontiff).
- **(c) Negative-skew structures sold as "high win rate".** Grid bots, martingale DCA, naked option selling and no-stop mean reversion win often and lose catastrophically.
- **(d) Leverage**, mainly through CFDs, turbos and short-vol ETNs.
- **(e) Single-market, single-rule bots** that forgo breadth.
- **(f) Retail as the counterparty** to structural edges.
- **(g) Overconfidence.** Glaser-Weber find that German online-broker clients who think they are above average trade more, without better past performance.
- **(h) Chasing past winners.** wikifolio shows past rank does not persist.

### What is realistically accessible to a single-account Alpaca bot

The bot trades US equities and ETFs on a paper account, long and short, at hourly-to-daily cadence, with REST polling and bracket orders.

**Accessible and not yet tested here at the breadth the literature requires:**
1. Multi-asset ETF trend or time-series momentum with portfolio vol targeting.
2. Cross-sectional momentum on a stock or sector-ETF universe.
3. Weekly large-cap reversal.
4. Calendar anomalies.

All of these need many symbols or overnight holding, and every one is a new decision rule.

**Accessible but already tested or killed here:**
- single-instrument trend, breakout and MA-cross;
- single-SPY vol targeting, GEM and Faber;
- intraday momentum;
- candlestick patterns;
- a put-credit-spread VRP rule.

The ORB class was ruled NO-GO by the short-horizon entry gate, and its own probe was data-blocked.

**Not accessible:** market making and HFT, futures-based CTA breadth, cross-asset carry, and crypto basis trades.

**Accessible but negative-EV by construction:** grid and martingale-DCA bots.

The one-line answer is that the general approach that works is **risk premia harvested across many markets, at low per-bet risk, with tight cost control**. The repo's string of single-instrument, pattern- or timing-based kills is what the literature predicts.

---

## Top 15 strategies

The 15 are ranked by a combination of evidence strength and accessibility to this bot. Where English and German sources cover the same canonical strategy, the deeper treatment is used and the other is folded in. Strategies outside the 15 are listed in a short table after the list.

---

## 1. Multi-asset trend following / time-series momentum (incl. Turtle-style breakout, CTA "Trendfolge")

- **Mechanism.**
  - *Academic form (Moskowitz-Ooi-Pedersen 2012):* each month, go long an instrument whose trailing 12-month excess return is positive and short it if negative. Scale each position to a constant ex-ante volatility, then sum across many futures at equal risk.
  - *Practitioner breakout form (Turtles, Clenow's "Following the Trend"):*
    - enter on a 20-day (System 1) or 55-day (System 2) Donchian breakout, or a 50-100 day channel/MA filter;
    - exit on a 10- or 20-day opposite breakout;
    - stop at 2N (N = 20-day ATR);
    - size so that 1N = 1% of equity.
- **Indicators / patterns**
  - Trailing-return sign, moving-average crosses, Donchian channels.
  - ATR stops.
  - Inverse-volatility (risk-parity) sizing across many instruments.
- **Typical timeframe.** Daily bars. Holds run from weeks to months. Lookbacks of 1, 3 and 12 months.
- **Pros**
  - The best-documented systematic family. All 58 liquid futures show positive TSMOM.
  - Hurst-Ooi-Pedersen report positive performance in every decade from 1880 to 2016 across 67 markets.
  - Low exposure to standard factors, and "performs best during extreme markets" (crisis alpha).
  - 2022 was a record year: SG Trend Index about +27%, SG CTA Index +20.1%.
  - Rules are fully mechanical (the Turtle rules were published).
- **Cons**
  - Kim-Tse-Wald: much of the alpha is **volatility scaling**, not the trend signal. Monthly alpha falls from 1.27% to 0.41% without vol scaling, and individual contracts "do not generally outperform a buy-and-hold futures strategy".
  - Long droughts. SG Trend reportedly made about 0.4-1.8%/yr over 2009-2018 with a drawdown of about 22% (secondary; not verified against SocGen data).
  - Crowding: weak CTA returns coincided with record managed-futures AUM (Gresham 2019).
  - **Needs breadth.** ETF proxies give fewer, more correlated markets than 60+ futures, with no true FX or curve exposure.
- **Fit with our bot.** A daily, multi-ETF, vol-targeted portfolio is the best-evidenced archetype this stack could run, but it is a replacement for `decideHourly`, not a tweak: multi-symbol positions, overnight holds and a portfolio-level sizer. It needs a fresh brainstorm, a spec and an ADR. **`needs envelope`** -- a deterministic portfolio vol target with per-instrument and aggregate notional caps in `config.ts`, gap-aware sizing for overnight holds, and a `panic` path that closes every open symbol side-aware.
- **Evidence quality.** `academic` (strong, multi-decade, many markets) plus `practitioner` (fund track records). The robust result is portfolio-level; per-instrument evidence is weak.
- **Repo status.** Partially tested, all at too little breadth:
  - Killed single-instrument: `2026-07-24-turtle-breakout-verdict.md` (Donchian-55 bracket, NO-GO on all 12 cells) and `2026-07-15-forex-4h-survey-verdict.md` (MA-cross, Donchian and ROC-TSMOM on 4h EUR/USD; 0/33).
  - `2026-06-24-candidate-strategy-survey-first-cut.md`: Faber single-asset and a 5-asset GTAA-lite 10-month-SMA rotation both failed the after-tax Calmar bar. The `tsmom-12mo` baseline was the strongest signal but was described as "the floor, not a survivor".
  - A 10-20 ETF, vol-targeted TSMOM portfolio is **untested**.
- **Sources**
  - https://papers.ssrn.com/abstract=2089463 (MOP 2012); https://fairmodel.econ.yale.edu/ec439/jpde.pdf
  - https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing?aqrPDF=1 (Hurst-Ooi-Pedersen, 2017); https://alphaarchitect.com/trend-following-is-everywhere/ (2020)
  - https://quantpedia.com/deconstructing-the-time-series-momentum-strategy/ ; https://alphaarchitect.com/time-series-momentum-and-volatility-scaling/ (Kim-Tse-Wald 2016)
  - https://www.hedgeweek.com/flat-december-sees-ctas-complete-record-year-2022/ ; https://alpha-week.com/2022-cta-index-performance-review
  - https://www.cmegroup.com/education/files/trends-not-dead-babbedge-kerson-2019.pdf (Gresham 2019); https://ibkrcampus.com/?p=182715 (drought claim, secondary)
  - https://www.tradingblox.com/originalturtles/originalturtlerules.pdf (Faith, Original Turtle Rules, 2003; primary)
  - https://oreilly.com/library/view/following-the-trend/9781118410844 (Clenow 2012)

---

## 2. Cross-sectional momentum (relative strength; Clenow "Stocks on the Move"; factor tilts)

- **Mechanism.**
  - *Academic form:* rank a universe on its past 3-12 month return, usually skipping the most recent month. Buy the top decile or quintile and short the bottom (or run long-only top), holding 3-12 months.
  - *Clenow's published practitioner form (German edition: "So schlagen Sie den Markt mit den Momentumstrategien der Hedgefonds"):*
    - rank index members by the annualised slope of a 90-day exponential regression times R²;
    - buy the top ranks only while the index is above its 200-day MA;
    - sell names that fall below their 100-day MA or gapped more than 15%;
    - rebalance about every two weeks.
  - Value, quality and low-vol tilts are the same "rank and tilt" machinery applied to other characteristics.
- **Indicators / patterns**
  - Trailing total return or regression slope × R², a skip-month, ranking.
  - A 200-day index regime filter.
  - ATR(20) volatility-parity sizing.
- **Typical timeframe.** Daily data with weekly, biweekly or monthly rebalance. Holds of weeks to months.
- **Pros**
  - One of the most replicated anomalies: positive over 3-12 month holds (Jegadeesh-Titman 1993), and about 1.18%/month long-short over 1927-2020 (2023 SFA paper).
  - Value and momentum appear "everywhere" and are **negatively correlated**, so combining them helps (AMP 2013).
  - Clear, published rules with vol-parity sizing.
- **Cons**
  - **Momentum crashes** (Daniel-Moskowitz 2016): long losing runs in panic states after declines (1932, 2009). Their dynamic vol scaling roughly doubles the Sharpe ratio.
  - Momentum was "unconditionally unprofitable" in the US, Japan and the Eurozone over the decade to about 2014 (Avramov-Cheng-Hameed).
  - Turnover, short-side borrow costs, and survivorship bias in index-member backtests.
  - The wider factor zoo: Harvey-Liu-Zhu require t > 3.0, 65% of 452 anomalies fail replication (Hou-Xue-Zhang), and McLean-Pontiff measure returns 58% lower post-publication.
- **Fit with our bot.** Mechanically accessible: Alpaca trades the stocks and sector ETFs, and a biweekly rebalance is far below the bot's cadence. But it is a new, multi-symbol, overnight-holding decision rule, so it is a replacement needing a fresh spec. **`needs envelope`** -- Clenow-style ATR sizing bounded by a per-name and an aggregate notional cap in `config.ts`, a deterministic crash control (index regime filter and/or vol scaling), a max-positions cap, and multi-symbol side-aware `panic`.
- **Evidence quality.** `academic` (strong for momentum; weak for most of the factor zoo). The Clenow rules are `practitioner`, reconstructed from QuantConnect and blog implementations that differ slightly.
- **Repo status.**
  - Partially tested: GEM dual momentum (a 2-3 asset relative-plus-absolute switch) failed the after-tax Calmar bar (`2026-06-24-candidate-strategy-survey-first-cut.md`).
  - A broad single-stock or sector cross-section is **untested**.
- **Sources**
  - https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html (Jegadeesh-Titman 1993)
  - https://www.nber.org/papers/w20439 (Daniel-Moskowitz)
  - https://www.aaii.com/files/images/SFA-Award-Paper-2023.pdf (2023)
  - https://www.aqr.com/library/journal-articles/value-and-momentum-everywhere (AMP 2013)
  - https://ideas.repec.org/a/cup/jfinqa/v51y2016i06p1897-1923_00.html (Avramov et al. 2016)
  - https://www.perlego.com/de/book/1045102/stocks-on-the-move-so-schlagen-sie-den-markt-mit-den-momentumstrategien-der-hedgefonds-pdf (German edition)
  - https://www.quantconnect.com/forum/discussion/16578/quot-stocks-on-the-move-quot-momentum-strategy-by-cabedovestment/
  - https://quant-investing.com/blog/how-to-find-stocks-on-the-move-with-a-better-momentum-indicator-exponential-regression
  - https://www.nber.org/papers/w20592 (Harvey-Liu-Zhu); https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html (Hou-Xue-Zhang 2020); https://alphaarchitect.com/replicating-anomalies/

---

## 3. Volatility targeting (a sizing overlay, not a signal)

- **Mechanism.** Scale exposure each day so that forecast volatility equals a target, using trailing realised volatility. Cut exposure when volatility rises and raise it when volatility falls, within a leverage cap. CTAs apply this to the whole programme. AQR's managed-futures fund "will target an annualized volatility level for the Fund of 10%", typically in a 5-13% range.
- **Indicators / patterns**
  - Trailing realised volatility (or ATR).
  - The target-vol / realised-vol ratio.
  - A leverage cap.
- **Typical timeframe.** Daily rebalance of size.
- **Pros**
  - Moreira-Muir: "Managed portfolios that take less risk when volatility is high produce large alphas." This holds across market, value, momentum, profitability and FX carry.
  - Harvey et al. (60 assets back to 1926): Sharpe improves for risk assets. US equity Sharpe moves from about 0.40 to 0.48-0.51 (secondary). Extreme returns fall in every asset class.
  - Fully deterministic, and it is the professional analogue of a "risk per trade" rule.
- **Cons**
  - The Sharpe benefit is negligible for bonds, FX and commodities.
  - With a 1x leverage cap it cannot add return; it only trims.
  - High turnover. The repo measured a 93.7x/year churn whose short-term tax drag dominated the slim pre-tax edge.
  - Even a 13-16% vol target produced about a -30% drawdown at Man AHL Diversified (secondary).
- **Fit with our bot.** This is a sizing rule, not an entry rule, so in principle it lives inside `computeSizing` (`hourly-check/logic.ts`) under `config.ts` bounds. It needs no LLM and does not add a second signal. Changing how size is computed is still a spec-level change, and it does not fix the sign of the incumbent rule's mean (see "What traders and bots typically risk"). **`fits`**.
- **Evidence quality.** `academic`. Harvey et al. 2018 figures are secondary (abstract and summaries); Moreira-Muir is primary (abstract); the AQR target is from a primary filing.
- **Repo status.** Already tested here: 10% vol targeting on SPY failed the after-tax Calmar bar (`2026-06-24-candidate-strategy-survey-second-cut.md`).
- **Sources**
  - https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538 (Harvey et al., JPM 2018)
  - https://alphaarchitect.com/volatility-targeting-improves-risk-adjusted-returns/
  - https://www.nber.org/papers/w22208 (Moreira-Muir 2016/2017)
  - https://www.sec.gov/Archives/edgar/data/1444822/000119312521145814/d331591d497.htm (AQR 497, 2021); https://www.sec.gov/Archives/edgar/data/1444822/000119312518145469/d520037d497k.htm (2018)

---

## 4. Calendar and seasonal anomalies (turn of month, pre-FOMC, overnight drift, Halloween / "Sell in May", Stagge anomaly stacking)

- **Mechanism.**
  - **Turn of month (TOM):** hold the index from the last trading day of the month through the third trading day of the next month; cash otherwise.
  - **Pre-FOMC:** hold the S&P 500 from 2 pm the day before a scheduled announcement until 2 pm on the day.
  - **Overnight drift:** hold the index close-to-open and stay flat intraday.
  - **Halloween:** hold equities November-April and cash May-October.
  - **Speck / Seasonax:** narrower mined windows, for example a year-end rally from about 14 Dec to 4 Jan.
  - **Stagge's "anomaly stacking":** combines several of these (triple witching, a Halloween plus month-end combo, "long before the Fed") into one pack. Its stated aim is to smooth the equity curve.
- **Indicators / patterns**
  - Calendar dates and event calendars (FOMC, option expiry).
  - Calendar-averaged seasonal paths and hit rates (Seasonax).
- **Typical timeframe.** Overnight, a few days (TOM, FOMC) or six-month windows (Halloween).
- **Pros**
  - Zero discretion.
  - **TOM:** captured all positive excess returns over 1926-2005, in 31 of 35 countries, not explained by risk or month-end flows (McConnell-Xu 2008).
  - **Pre-FOMC:** about 49 bp average since 1994, more than 80% of the US equity premium over 17 years (Lucca-Moench 2015).
  - **Halloween:** found in 36 of 37 markets (Bouman-Jacobsen 2002). Jacobsen-Zhang report winter minus summer = 4.52% with t = 9.69 over 319 years.
  - Low time in market.
- **Cons**
  - **Post-publication decay, documented in German academic work.** Dichtl-Drobetz: Halloween is significant over the full sample but not at 95% for DAX, S&P, FTSE, CAC or Euro Stoxx after 2003. With 0.5% switching friction, buy-and-hold significantly beat the switch after 2003.
  - Heidorn-Maier-Winker (DAX/MDAX/SDAX 1990-2015) attribute Sell-in-May mostly to being out in August and September.
  - These effects mostly **reallocate the equity premium in time** rather than create new return. Time out of the market rarely beats buy-and-hold after tax and costs.
  - The overnight effect costs the spread twice a day and has weakened in large caps (CXO).
  - Data mining. Kagels warns that a "90% over 20 years" hit rate is 18 of 20, and that freely shiftable windows over 25,000 instruments guarantee spurious patterns. The review recommends seasonality only as a filter.
  - Stagge's pack uses **no stop-loss** ("André Stagge does not place stop loss orders"). Each anomaly has few trades per year, so samples are tiny.
- **Fit with our bot.** Fully deterministic and SPY-native. But TOM, FOMC, Halloween and overnight all hold through the close, which collides with the hourly bot's session-close flatten, and a no-stop version leaves risk bounded only by holding time. It would be a new or second decision rule needing a fresh spec. **`needs envelope`** -- size on the overnight-gap distribution (for example, p99 SPY gap) rather than an intraday stop, add a hard stop and a maximum hold, and freeze the calendar windows in a pre-registration.
- **Evidence quality.**
  - `academic` for TOM, pre-FOMC, overnight and Halloween existence.
  - The strongest German out-of-sample test (Dichtl-Drobetz) is negative after costs since 2003.
  - Seasonax window-mining, Speck's annualised figures and Stagge's packaging are `marketing` / `practitioner`.
- **Repo status.** Untested (no calendar or event rule appears in the repo's verdicts). The closest analogue is the "time out of SPY" family (Faber, GEM, vol targeting), which failed after tax.
- **Sources**
  - https://ideas.repec.org/a/taf/ufajxx/v64y2008i2p49-64.html (McConnell-Xu 2008); https://docs.lib.purdue.edu/ciberwp/43 ; https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes ; https://www.cxoadvisory.com/calendar-effects/the-turn-of-the-month-effect/
  - https://cepr.org/voxeu/columns/predictable-movements-asset-prices-around-fomc-meetings ; https://www.r-bloggers.com/2015/03/update-on-the-pre-fomc-announcement-drift/
  - https://arxiv.org/pdf/2507.04481 (2025); https://robotwealth.com/overnight-and-intraday-spx-returns/ ; https://www.cxoadvisory.com/calendar-effects/momentum-happens-at-night/ ; https://joim.com/wp-content/uploads/emember/downloads/P0753.pdf
  - https://www.cxoadvisory.com/calendar-effects/halloween-indicator-out-of-sample-test (Dichtl-Drobetz 2013)
  - https://ideas.repec.org/p/zbw/fsfmwp/224.html (Heidorn-Maier-Winker 2017)
  - https://www.tias.edu/docs/default-source/Kennisartikelen/ssrn-id2154873.pdf (Jacobsen-Zhang); https://en.wikipedia.org/wiki/Sell_in_May
  - https://www.seasonax.com/?p=11626 (Speck, 2021); https://magazin.comdirect.de/maerkte-im-blick/interview-speck-jahresendrally-mitnehmen (2019); https://www.kagels-trading.de/seasonax-erfahrungen/ (2026)
  - https://www.whselfinvest.de/en-de/trading-platform/store/trading-strategies/daytrading-andre-stagge-zinshamster-surfer-superstar (Stagge pack)

---

## 5. Weekly short-term cross-sectional reversal (large-cap, market-neutral)

- **Mechanism.** Each week, buy last week's losers and short last week's winners, then hold one week. Lehmann (1990) shows weekly winners and losers reverse. The book is usually industry-neutral or residualised and is restricted to large caps with turnover-aware construction.
- **Indicators / patterns**
  - 1-week or 1-month return rank.
  - Industry or factor residualisation.
  - Turnover control.
- **Typical timeframe.** Weekly rebalance.
- **Pros**
  - Compensated liquidity provision, so the edge source is economic.
  - De Groot-Huij-Zhou (2012): with large caps only and turnover-aware construction, net returns are still **30-50 bp per week**.
  - The gross effect is large in older samples: losers +0.86 to +1.24% per week (secondary summary).
- **Cons**
  - Extremely turnover-heavy. Profits "can largely be attributed to excessively trading in small cap stocks", and a naive implementation is wiped out by costs.
  - It needs many simultaneous shorts, so borrow availability and fees matter.
  - Applications to other asset classes failed after costs.
- **Fit with our bot.** Alpaca supports shorts, and a weekly cadence is easy. But this is a many-name, market-neutral book with overnight holds, a different architecture from a single-symbol bracket bot, and it is a new decision rule. **`needs envelope`** -- gross and net exposure caps, a per-name notional cap, a borrow-availability check before each short, and a portfolio-level loss limit, all in `config.ts` and enforced in code.
- **Evidence quality.** `academic`.
- **Repo status.** Untested. The repo's mean-reversion tests were single-instrument (RSI and Bollinger on 4h EUR/USD).
- **Sources**
  - https://www.nber.org/papers/w2533 ; https://ideas.repec.org/a/oup/qjecon/v105y1990i1p1-28..html (Lehmann 1990)
  - https://alphaarchitect.com/quantitative-momentum-research-short-term-return-reversal/
  - https://ideas.repec.org/a/eee/jbfina/v36y2012i2p371-382.html (de Groot et al. 2012)

---

## 6. Statistical arbitrage / pairs trading

- **Mechanism.**
  - *Gatev-Goetzmann-Rouwenhorst (GGR) distance method:*
    - form pairs over 12 months by minimum squared distance between normalised prices;
    - over the next 6 months, open a long-short position when the spread diverges by 2 historical standard deviations (per the CXO summary);
    - close on convergence or at period end.
  - *Avellaneda-Lee:* regress each stock on sector ETFs or PCA factors, model the residual as an Ornstein-Uhlenbeck process, and trade its s-score.
- **Indicators / patterns**
  - Normalised spread and z-score.
  - Cointegration (Engle-Granger) and OU half-life.
  - Sector-ETF hedges.
- **Typical timeframe.** Daily to intraday. Holds of days to weeks.
- **Pros**
  - GGR: "up to 11%" annualised excess returns over 1962-2002, surviving conservative costs.
  - Strong in turbulent periods, including the GFC (Do-Faff).
  - Market-neutral by construction.
- **Cons**
  - **Clear decay.** The top-20-pairs excess return fell from 0.86%/month (1962-88) to 0.37% (1989-2002) and 0.24% (2003-09) (Do-Faff).
  - The Avellaneda-Lee ETF Sharpe of 1.1 shows "similar degradation since 2002".
  - **Crowding blow-up:** the August 2007 quant unwind (Khandani-Lo).
  - Pairs can break structurally, and losses are unbounded without a stop.
  - A later paper finds GGR rules lag the benchmark outside crises.
- **Fit with our bot.** Mechanically feasible at daily frequency on ETF pairs. But it is two-legged, overnight and many-pair, it is a new decision rule, and today's `panic` assumes a single live symbol. **`needs envelope`** -- a pair-break stop (spread z-score and a max adverse move), a maximum holding time, a dollar-neutral gross-exposure cap, and a `panic` that closes both legs of every pair side-aware.
- **Evidence quality.** `academic`, with a well-documented post-publication decline.
- **Repo status.** Untested.
- **Sources**
  - https://www.cxoadvisory.com/technical-trading/classic-paper-matched-pairs-trading/ ; https://alphaarchitect.com/2013/06/pairs-trading-kicks-butt/ (GGR)
  - https://ideas.repec.org/a/taf/ufajxx/v66y2010i4p83-95.html (Do-Faff 2010)
  - https://arxiv.org/pdf/2010.01157 (later critique)
  - https://ideas.repec.org/a/taf/quantf/v10y2010i7p761-782.html ; https://www.math.nyu.edu/faculty/avellane/AvellanedaLeeStatArb20090616.pdf (Avellaneda-Lee 2010)
  - https://web.mit.edu/Alo/www/Papers/august07.html (Khandani-Lo)

---

## 7. Short-term mean reversion: Connors RSI(2) family

- **Mechanism.**
  - *Common published form:* price above its 200-day SMA, and RSI(2) closes below 10 (stricter: below 5). Buy at the close and exit on a close above the 5-day SMA. Mirror rules apply for shorts below the 200-day.
  - Variants exit on RSI(2) > 70 or require 3 consecutive down days.
  - Sources disagree on stops. One says Connors "does not advocate the use of stop loss".
- **Indicators / patterns**
  - RSI(2), 200-day SMA, 5-day SMA.
  - Sometimes cumulative RSI or %b.
- **Typical timeframe.** Daily bars. Holds of about 2-7 days.
- **Pros**
  - High win rate.
  - Mechanically simple, and suits liquid index ETFs.
- **Cons**
  - Evidence is mostly the author's own books (2008/2009) and blog backtests. One ProRealCode out-of-sample test on the CAC 40 was unimpressive.
  - The edge is a few tenths of a percent per trade, so it is very cost- and slippage-sensitive.
  - **Negative skew:** many small wins and occasional large losses when no stop is used.
  - It may be specific to the post-2000 index regime and crowded.
- **Fit with our bot.** Easy to express deterministically on SPY or sector ETFs. But it holds overnight for days, and the canonical no-stop version is exactly the negative-skew structure the risk lens rejects. It would replace `decideHourly`. **`needs envelope`** -- a mandatory hard stop plus a time stop, sizing on the overnight-gap distribution rather than a stop, and a notional cap.
- **Evidence quality.** `practitioner` / `marketing`. No independent peer-reviewed out-of-sample test was found.
- **Repo status.**
  - Partially tested: RSI(2) 10/90 and Bollinger(20, 2) were killed on 4h EUR/USD (`2026-07-15-forex-4h-survey-verdict.md`, 0/33).
  - Daily RSI(2) on US equity ETFs is untested.
- **Sources**
  - https://quantifiedstrategies.substack.com/p/larry-connors-r3-strategy-it-still-795
  - https://www.prorealcode.com/prorealtime-trading-strategies/rsi-2-strategy-larry-connors
  - https://www.luxalgo.com/library/concept/rsi-2.md

---

## 8. Regime-switch filters: Weinstein stage analysis and the Gebert macro composite

- **Mechanism.**
  - **Weinstein Marktphasen (stage analysis):**
    - on weekly charts, classify each stock as Stage 1 (base), 2 (advance), 3 (top) or 4 (decline);
    - the 30-week MA is the key indicator;
    - buy the Stage-1 to Stage-2 breakout: a weekly close above resistance, with a rising 30-week MA and volume around 2x average;
    - exit when the 30-week MA flattens or price breaks below it on volume.
  - **Gebert-Börsenindikator:** checked monthly, one point each for:
    - the last ECB rate change was a cut;
    - euro-area HICP inflation is below its year-ago level;
    - EUR/USD is below its level a year ago;
    - the month falls in November-April.

    3-4 points means long DAX, 0-1 means money market, and 2 means hold the prior position. The hysteresis rule is reported inconsistently across sources.
- **Indicators / patterns**
  - 30-week SMA and its slope, volume expansion, relative strength (Weinstein).
  - Policy-rate direction, inflation trend, FX trend and the Halloween month (Gebert).
- **Typical timeframe.** Weekly or monthly. A few switches per year; holds of months.
- **Pros**
  - Simple, low-turnover and transparent.
  - Weinstein avoids "falling knives" in Stage 4.
  - Gebert is economically motivated and claims to have avoided the 2000-03 and 2008 bear markets.
- **Cons**
  - Weinstein stage labels are partly discretionary, entries and exits are late, and volume thresholds vary between implementers.
  - Gebert's four binary inputs were chosen with hindsight, and its seasonal point is the Halloween effect that decayed after 2003.
  - Gebert famously misfired: the November 2018 buy signal was about 900 DAX points underwater by January 2019.
  - **Gebert's investable live index (Jun 2021 - Aug 2026): +41.2% return, 31.3% max drawdown, 20.7% volatility, 1.2% p.a. fee.** That is not obviously better than holding the DAX.
  - Gebert's backtests (about +2,300% for 1993-2018) come only from the publishers, and the published figures conflict across articles.
- **Fit with our bot.** Both are deterministic once stage thresholds are frozen. The bot's predecessor, the UPRO 200-DMA regime bot, was exactly this class, and the kill-switch existed to bound its unstopped position. A US Gebert analogue (Fed, CPI, DXY) or a Weinstein stock leg would be a replacement rule needing a fresh spec. **`needs envelope`** -- because there is no per-trade stop, the held position needs the `kill-switch` drawdown liquidation and a notional cap ≤ 1.0x equity as its deterministic risk bound.
- **Evidence quality.** `practitioner` (Weinstein; secondary sources only, mainly TradingView, MQL5 and LuxAlgo). `practitioner` / `marketing` (Gebert; no independent academic test).
- **Repo status.**
  - Already tested in family: the 200-DMA SPY/UPRO regime rule (`2026-06-06-regime-vs-spy-longrun-backtest.md`; retired by ADR `docs/decisions/2026-07-27-deprecate-upro-regime-bot.md`), and Faber 10-month SMA (`2026-06-24-candidate-strategy-survey-first-cut.md`).
  - Macro-input composites (Gebert) and the Weinstein single-stock selection leg are untested.
- **Sources**
  - https://de.tradingview.com/chart/NFLX/LISNvoN7-Stan-Weinstein-Theory-on-Netflix ; https://www.mql5.com/en/articles/22746 ; https://www.luxalgo.com/library/indicator/BSLCP2eI-stan-weinstein-30-week-moving-average/
  - https://stock3.com/news/risk-on-oder-risk-off-investieren-auf-basis-von-4-signalen-17245414 (2026-08-17)
  - https://stock3.com/news/dieses-dax-kaufsignal-ging-so-richtig-nach-hinten-los-6753630 (2019-01-02)
  - https://www.deraktionaer.de/artikel/maerkte-forex-zinsen/boersen-indikator-von-thomas-gebert-gibt-ein-neues-kaufsignal-20240170.html ; https://www.gevestor.de/finanzwissen/boerse/strategien/gebert-indikator.html

---

## 9. Intraday momentum (first half-hour predicts last half-hour)

- **Mechanism.** If SPY's return from the previous close to 10:00 ET is positive, go long for the last 30 minutes; if negative, go short. Exit at the close.
- **Indicators / patterns**
  - Half-hour returns.
  - Optional volatility and volume conditioning.
- **Typical timeframe.** Intraday, flat at the close.
- **Pros**
  - Gao-Han-Li-Zhou (JFE 2018, SPY 1993-2013). The effect is stronger on volatile, high-volume, recession and macro-news days and appears in 10 other ETFs.
  - The mechanisms are plausible (infrequent rebalancing, late-informed trading).
  - Never holds overnight.
- **Cons**
  - The per-trade edge is small relative to the spread.
  - It was likely arbitraged after publication.
- **Fit with our bot.** Shape-identical to the hourly bot: single-symbol SPY, intraday, flat at the close, bracketable. It would be a direct replacement of `decideHourly`. **`fits`**.
- **Evidence quality.** `academic`.
- **Repo status.** Already tested here and found NO_EDGE on SPY 2016-2026: b1 = +0.016 (HAC t +0.59), no configuration positive at 0.5 or 1 bp/side, DSR 0.0014 (`docs/research/2026-10-22-spy-intraday-momentum-verdict.md`, branch `research/spy-intraday-momentum`).
- **Sources**
  - https://profiles.wustl.edu/en/publications/market-intraday-momentum/ (Gao et al. 2018)
  - https://alphaarchitect.com/2014/08/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/

---

## 10. Opening range breakout (Zarattini-Aziz-Barbon; DAX ORB nach Schäfermeier and Stagge)

- **Mechanism.**
  - **QQQ ORB (Zarattini-Aziz 2023):** if the first 5-minute bar is up (down), go long (short) at the start of the second bar. Exit at the close or on the stop.
  - **Stocks-in-Play (Zarattini-Barbon-Aziz 2024):**
    - *Universe:* the top 20 US stocks by opening relative volume, after price, volume and ATR filters.
    - *Entry:* stop order at the opening-range extreme in the direction of the first 5-minute move.
    - *Stop:* **10% of ATR**.
    - *Exit:* at the close.
    - *Sizing:* **1% of capital risked per trade, 4x leverage cap**.
  - **German DAX variants:**
    - *Schäfermeier:* 60-minute range, SuperTrend direction filter, stop at the opposite extreme, **CRV 3** target, flat by 21:59.
    - *Stagge "Morning Break Out":* 09:00-10:00 range, stop at half the range, target the full range (**CRV about 2**), break-even step at halfway, close at 21:15.
- **Indicators / patterns**
  - Opening range and relative volume.
  - ATR.
  - SuperTrend.
  - Bracket, break-even and time stops.
- **Typical timeframe.** Intraday, flat by the close.
- **Pros**
  - Fully specified bracket, one trade per day per market, and no overnight risk.
  - The academic paper states its sizing explicitly (1%, 4x).
- **Cons**
  - The paper headlines (QQQ alpha 33%/yr; Stocks-in-Play +1,600%, Sharpe 2.81) come from **authors with commercial interests**, with no out-of-sample period.
  - One independent MQL5 replication on five index CFDs (2015-2026) found net of costs "no market distinguishable from zero, four of five negative". The paper charges commission but no spread or slippage. This is a single non-peer-reviewed critique.
  - The German packages publish no statistics. Schäfermeier "will not necessarily implement his strategy to the letter every day". They are sold next to a "76% of retail investor accounts lose money" disclosure.
- **Fit with our bot.** Shape-compatible: bracket orders, intraday, flat by the close, risk-per-trade sizing. It would be a replacement for `decideHourly`. **`fits`**.
- **Evidence quality.**
  - `academic`-format working papers by practitioner authors; the headline numbers lean `marketing` until replicated net of costs.
  - German DAX ORB packages are `marketing`.
- **Repo status.**
  - Already tested here but inconclusive: the ORB free-data probe was **DATA-BLOCKED** (no usable 2016+ sample), with a recommendation not to pay for full-power data (`2026-07-24-orb-probe-verdict.md`).
  - The class sits inside the intraday rule-based-entry class ruled NO-GO (`2026-07-24-short-horizon-entry-feasibility-gate.md`). A colleague's London-ORB variants all lost (`2026-07-20-colleague-repo-audit.md`).
- **Sources**
  - https://papers.ssrn.com/abstract=4416622 ; https://ideas.repec.org/p/chf/rpseri/rp2498.html
  - https://concretumgroup.com/can-day-trading-really-be-profitable/ ; https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/
  - https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/
  - https://www.mql5.com/en/blogs/post/776235 (independent replication)
  - https://www.whselfinvest.de/en-de/trading-platform/store/trading-strategies/daytrading-birger-schaefermeier-trading-strategy-open-range-break-out
  - https://whselfinvest.com/en-ch/trading-platform/store/trading-strategies/daytrading-andre-stagge-morning-break-out
  - https://admiralmarkets.com/analytics/traders-blog/trading-dax30-open-range-breakout (generic DAX ORB variant)

---

## 11. Volatility risk premium / systematic option selling

- **Mechanism.** Sell index options, usually puts or strangles, to collect implied volatility, which on average exceeds subsequently realised volatility. The canonical benchmark is the Cboe PUT index: sell one-month at-the-money SPX puts monthly, fully cash-secured. Short-VIX ETNs are the leveraged retail variant.
- **Indicators / patterns**
  - VIX versus realised volatility, IV rank.
  - Delta and moneyness choice.
  - Roll schedule.
- **Typical timeframe.** Monthly or weekly cycles (0DTE more recently).
- **Pros**
  - Average VIX was 19.3% versus 15.1% realised over 1990-2018.
  - PUT returned 9.40% versus 9.91% for the S&P 500 (1986-2023), with standard deviation 10.3% versus 15.4% and max drawdown -32.7% versus -51.0%.
  - The flip side confirms the premium: buying protective puts is usually poor insurance (AQR "Pathetic Protection").
- **Cons**
  - Severe negative skew and a short-gamma tail.
  - **Volmageddon (5 Feb 2018):** short-vol ETPs lost more than 90% in a day, and XIV (about $2bn) was terminated.
  - Cash-secured put writing behaves like equity beta with a premium overlay.
  - Cboe figures are hypothetical index backtests with no execution costs.
  - On Alpaca, real options history starts around 2024-01-18, and bid/ask quotes are OPRA-gated on the free tier (`mvp2-alpaca-options-data-spike.md`).
- **Fit with our bot.** Defined-risk spreads give a bounded, deterministic maximum loss. But they need a multi-leg options order path that the bracket design, `checkGuard()`, the paper-only guard and side-aware `panic` do not cover today, and a stop cannot bound a short-gamma gap. **`needs envelope`** -- defined-risk spreads only, with max loss per spread as the risk unit, and the paper-only guard and `panic` extended to every options order path.
- **Evidence quality.** `academic` (that the VRP exists) plus `practitioner` (Cboe index data).
- **Repo status.** Already tested here: a put-credit spread on SPY with a regime and IV-rank gate was **KILL**. It returned -30.2% at baseline (Sharpe -0.60) and +3.0% at best across a 12-point sweep, versus +343% for SPY (`mvp2-pcs-riv-backtest.md`). The memo leaves a thread open for VRP as an uncorrelated diversifier only.
- **Sources**
  - https://www.cboe.com/insights/posts/white-paper-shows-volatility-risk-premium-facilitated-higher-risk-adjusted-returns-for-put-index
  - https://www.cboe.com/insights/posts/generating-income-and-managing-risk-cash-secured-put-writing-in-a-low-equity-return-environment
  - https://www.aqr.com/insights/research/white-papers/pathetic-protection-the-elusive-benefits-of-protective-puts
  - https://rpc.cfainstitute.org/research/financial-analysts-journal/2021/volmageddon-failure-short-volatility-products
  - https://www.bloomberg.com/news/articles/2019-02-06/the-day-the-vix-doubled-tales-of-volmageddon
  - https://arxiv.org/html/2508.16598v1

---

## 12. Voigt's Markttechnik (price-structure trend following, Punkt 1-2-3)

- **Mechanism.**
  - **Trend definition:** a trend is a sequence of impulse (*Bewegung*) and correction (*Korrektur*) legs. An uptrend is intact while higher highs and higher lows continue.
  - **Points:** in an uptrend, points 1 and 2 are successive highs and point 3 is the low between them.
  - **Entries:**
    - a "correction entry" near point 3;
    - or a "movement entry" with a stop-buy just beyond point 2.
  - **Stop:** beyond point 3, trailed to each new point 3.
  - **Context:** a higher timeframe ("Großwetterlage") sets direction, and a lower "Signallage" times the entry.
- **Indicators / patterns**
  - Swing highs and lows only (no oscillators).
  - Inside bars.
  - Multi-timeframe pairing.
  - Vendor ZigZag drawing tools.
- **Typical timeframe.** Any. German retail use is mostly DAX intraday (1-15 minutes) and swing.
- **Pros**
  - Rule-like and chart-only.
  - Stops sit at structurally meaningful levels.
  - Mechanisable with fractal swing-point detection.
- **Cons**
  - Swing-point identification is discretionary, and the first phase drawn sets every later parameter.
  - Whipsaws in ranges.
  - The point-3 stop can be wide.
  - No canonical CRV.
  - The only quantitative study (Ostaschov 2017; 800 trends on the S&P 500 10-minute chart) counts trend continuation, not P&L. Phase 1 followed Phase 0 in 67.5% of long and 59.5% of short trends; only about 28% reached Phase 2. No expectancy, cost or significance figures are given.
  - A 2026 article recirculates that count as a "2026 study", which is citation drift.
- **Fit with our bot.** Once swing points are defined by a frozen algorithm, the stop is deterministic and bracket-compatible at hourly cadence. The movement entry is a structural breakout close to the killed Donchian family. It would replace `decideHourly`. **`needs envelope`** -- a frozen, mechanical swing-point definition in the pre-registration, plus the notional cap, because the point-3 stop distance varies widely.
- **Evidence quality.** `practitioner` (rules), `marketing` (packaged tools), and one weak practitioner count. No academic test.
- **Repo status.**
  - The movement-entry variant is near the killed breakout family (`2026-07-24-turtle-breakout-verdict.md`, `2026-07-15-forex-4h-survey-verdict.md`).
  - The point-3 pullback entry is untested.
- **Sources**
  - https://www.kagels-trading.de/markttechnik-ueberblick/ (updated 2026-10-09)
  - https://www.whselfinvest.de/en/trading-platform/drawing/trend/02-zigzag-trader-michael-voigt-book-markttechnik
  - https://trading-treff.de/wissen/statistische-markttechnik (Ostaschov, 2017-03-15)
  - https://stock3.com/boersenwissen/mein-weg-zur-markttechnik-3626246

---

## 13. Ichimoku Kinko Hyo

- **Mechanism.** Hosoda's system (published 1969) with defaults 9/26/52, originally tied to a 6-day week.
  - **Lines:**
    - Tenkan-sen = (9-period high + low)/2.
    - Kijun-sen = (26-period high + low)/2.
    - Senkou Span A = (Tenkan + Kijun)/2, plotted 26 periods ahead.
    - Senkou Span B = (52-period high + low)/2, plotted 26 periods ahead.
    - The area between the spans is the cloud (Kumo).
    - Chikou = close plotted 26 periods back.
  - **Long signal:**
    - close above the cloud;
    - Tenkan crosses above Kijun (strongest above the cloud);
    - Chikou above price 26 bars ago;
    - bullish future cloud.
  - **Exit:** a close back below Kijun (trailing stop), a close into the cloud, or an opposite cross.
- **Indicators / patterns**
  - Rolling high/low midpoints (Donchian midlines).
  - A cloud regime filter.
  - Kijun trailing stop.
- **Typical timeframe.** Daily classically; 1h-4h in FX and crypto.
- **Pros**
  - Trend, momentum and support/resistance in one display.
  - Fully mechanical, so it is easy to backtest honestly.
  - Gives a natural trailing-stop level (Kijun). German counter-trend trader Gräfe also uses Kijun as one of his tools.
- **Cons**
  - Structurally a multi-horizon Donchian/MA-cross trend system with three redundant filters.
  - Whipsaws in ranges.
  - The 9/26/52 defaults have no basis on a 5-day week, and parameter sweeps invite overfitting.
- **Fit with our bot.** Deterministic and bracketable, with Kijun as the stop. It would replace `decideHourly`. **`fits`**.
- **Evidence quality.** `academic` but **weak or negative**.
  - Deng et al. (2021): rules profitable in subperiod 1 "failed to create values consistently" in subperiod 2, and none survived for FX.
  - A Wooster study found buy-and-hold beat Ichimoku on SPY-type ETFs.
  - TradingView backtests are `marketing`.
- **Repo status.**
  - Untested as such.
  - Its components (Donchian, MA-cross) were killed (`2026-07-15-forex-4h-survey-verdict.md`, 0/33; `2026-07-24-turtle-breakout-verdict.md`). Expect the same result.
- **Sources**
  - https://ideas.repec.org/a/wly/ijfiec/v26y2021i4p5321-5336.html (Deng et al. 2021)
  - https://openworks.wooster.edu/independentstudy/9433
  - https://corporatefinanceinstitute.com/resources/equities/ichimoku-cloud/
  - https://capital.com/en-ae/learn/technical-analysis/ichimoku-cloud-strategy
  - https://www.tradingview.com/script/uycyVpIq-Ichimoku-Clouds-Strategy-Long-and-Short/

---

## 14. Candlestick and Heikin-Ashi pattern rules (the incumbent's family)

- **Mechanism.**
  - Rule-based candlestick patterns (engulfing, hammer, star and so on) used as entries, with stops beyond the pattern.
  - German Heikin-Ashi teaching adds:
    - colour-flip reversals;
    - trend-pullback re-entries with stops on *real* (not HA) prices;
    - vendor composites such as WH SelfInvest "Black Candles" (an HA channel, a SuperTrend filter and a volatility trailing stop).
  - The bot's `decideHourly` is a composite over a frozen 14-detector registry (`_shared/candlestick.ts`) with an R = 2 bracket.
- **Indicators / patterns**
  - Candlestick detectors and Heikin-Ashi candles.
  - SuperTrend.
  - Swing stops.
- **Typical timeframe.** Intraday to daily.
- **Pros**
  - Fully mechanisable (as the repo proved).
  - Easy to bracket.
  - HA smooths noise visually.
- **Cons**
  - Park-Irwin: 58 of 92 modern TA studies were positive, but most suffered data snooping and ex-post rule selection, with profits concentrated in older samples.
  - HA prices are synthetic, so backtests using them are optimistic.
  - Colour flips whipsaw in ranges.
  - One vendor's "about 145% p.a." HA claim is not credible.
- **Fit with our bot.** This is what the bot runs today, so it fits the stack by construction. The problem is the sign of its mean, not its risk shape. **`fits`**.
- **Evidence quality.** `academic` for the generic TA literature (mixed, snooping-prone). `marketing` / `practitioner` for HA. No independent HA backtests exist in the German sources.
- **Repo status.** Already tested here:
  - -0.139R/trade on SPY 2016-2026 at 1 bp/side, every calendar year negative, already -0.031R gross; 0 of 19 symbols EDGE (`2026-10-22-multi-symbol-hourly-verdict.md`, branch `research/multi-symbol-hourly`).
  - The 15-minute version was DIRECTIONAL_NO_GO (`2026-09-03-15min-candlestick-study-verdict.md`).
- **Sources**
  - https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html ; https://ageconsearch.umn.edu/record/37487/files/AgMAS04_04.pdf (Park-Irwin)
  - https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/ ; https://www.cxoadvisory.com/big-ideas/in-sample-vs-out-of-sample-performance-of-888-trading-strategies (Wiecki et al. 2016)
  - https://stock3.com/news/trendumkehr-erkennen-mittels-heikin-ashi-8419638 (Jegen, 2020-05-27)
  - https://therighttrader.com/de/learn/chart-types/heikin-ashi ; https://doc.stocksharp.com/de/api-examples/0086_Heikin_Ashi_Reversal

---

## 15. Discretionary chart frameworks: Wyckoff method and Elliott Wave

- **Mechanism.**
  - **Wyckoff (1910s-1930s):**
    - A "Composite Man" is assumed to accumulate inside trading ranges before a markup and distribute before a markdown.
    - Three laws: Supply and Demand; Cause and Effect, where point-and-figure counts project the move; Effort versus Result, where volume is compared with price progress.
    - The accumulation schematic runs through Phases A-E: Selling Climax, Automatic Rally, Secondary Test, then the **Spring** (a break below support that closes back inside on low volume), then Sign of Strength and Last Point of Support, then markup.
    - Entries are on a confirmed Spring test or the LPS pullback, with a stop below the Spring low. Distribution mirrors this with an Upthrust.
  - **Elliott Wave:**
    - a 5-wave impulse followed by a 3-wave A-B-C correction, nested fractally;
    - Fibonacci targets: wave 3 often 1.618x wave 1, retracements of 38.2/50/61.8%;
    - stops at wave-rule invalidation levels.
- **Indicators / patterns**
  - Trading-range identification, volume (VSA) and point-and-figure counts (Wyckoff).
  - Wave counts and Fibonacci retracements and extensions (Elliott).
- **Typical timeframe.** Any. Classically daily or weekly; heavily used intraday in futures and crypto.
- **Pros**
  - A coherent supply/demand narrative with defined invalidation levels.
  - Wyckoff's Spring and Upthrust can be formalised as **failed-breakout** (stop-run) fades, which is a plausible liquidity mechanism.
  - Elliott gives explicit scenario invalidations.
- **Cons**
  - **Highly discretionary.** Phase labels and wave counts are assigned in hindsight and re-labelled endlessly. That is narrative overfitting and, in practice, not falsifiable.
  - No canonical numeric definition of a range, climax or "low volume".
  - Hulbert ranked the *Elliott Wave Theorist*'s trader timing **last over 20 years**, and CXO graded Prechter's forecasts at about 31% accuracy.
  - A 2023 thesis found no significant predictive power for daily FX.
  - Much of the content is course marketing.
- **Fit with our bot.** As practised, these frameworks need human (or model) judgement to label phases and waves. Putting that labeller in the trading path conflicts with "No LLM in the trading path" and with frozen, reproducible rules. Only a narrow, frozen failed-breakout fade or a deterministic wave labeller could be tested, and that would be a different strategy. **`skip`**.
- **Evidence quality.** Wyckoff: **no peer-reviewed empirical test found** (two targeted searches); `practitioner` at best, mostly `marketing`. Elliott: `marketing` / `practitioner`; academic tests are scarce and negative.
- **Repo status.**
  - Untestable (discretionary) as practised.
  - The repo holds a deterministic Elliott labeller (`backtest/elliott.py`) and an **unfrozen DRAFT** pre-registration for 1h forex (`2026-07-27-forex-1h-elliott-preregistration-DRAFT.md`); no result exists.
  - Wyckoff was screened as non-systematizable in `2026-07-24-famous-traders-strategies-survey.md`.
- **Sources**
  - https://stockcharts.com/articles/wyckoff/2015/12/the-laws-of-wyckoff.html (2015); https://articles.stockcharts.com/article/articles-wyckoff-2015-12-the-illustrated-wyckoff/
  - https://atas.net/blog/the-wyckoff-method-making-money-the-wyckoff-way/ (2024); https://www.tradingsim.com/blog/wyckoff-method-trading
  - https://www.cxoadvisory.com/individual-gurus/robert-prechter/ ; https://www.cxoadvisory.com/?p=3525
  - https://nur.nu.edu.kz/handle/123456789/7226 (2023 thesis); https://en.wikipedia.org/wiki/Robert_Prechter

---

### Considered but not ranked

| Approach | Why it is not in the top 15 | Verdict | Repo status |
|---|---|---|---|
| Cross-asset carry (FX, commodities, bonds, crypto basis) | Robust across asset classes (KMPV, JFE 2018), but crashes in global recessions and is **not accessible** on Alpaca equities/ETFs except through crude proxies | `skip` (not accessible) | Untested here. A colleague repo's daily FX carry reached DSR 0.664, short of his 0.95 gate (`2026-07-20-colleague-repo-audit.md`) |
| Market making / HFT | Winner-take-all. Relative latency explains performance (JFQA 2019). Not accessible to a REST-polling account | `skip` | Untested (infeasible) |
| Grid bots | The only study found: roughly zero EV before fees and negative after (arXiv 2025). No stop by design, so max loss is the full allocation; short gamma | `skip` | Untested; same no-edge family as killed scalpers (`2026-06-23-scalping-cost-wall-demonstration.md`) |
| Martingale "DCA" bots | Unbounded averaging-down into trends. High win rate, rare catastrophic loss. Plain DCA is behavioural: lump-sum beat it about two-thirds of the time (Vanguard 2012, via secondary summaries) | `skip` | Untested |
| Gräfe counter-trend setups | Discretionary and paid. His "CRV 2.0" risk rule is used in the risk section | `skip` (discretionary) | Untestable (discretionary); RSI/Bollinger family killed |
| Paesler indicator systems | Only a 2006 indicator textbook was confirmed; no documented system | n/a | MA/RSI/oscillator families killed |
| boerse.de "Champions" | Proprietary quality-stock selection; self-published data only | n/a | Not applicable (buy-and-hold) |
| wikifolio / copy trading | Not a strategy; it is evidence on retail skill (see the landscape table) | n/a | n/a |

Carry and market-making sources: https://www.nber.org/papers/w19325 , https://www.bis.org/publ/work1087.htm , https://ideas.repec.org/a/cup/jfinqa/v54y2019i03p993-1024_00.html , https://www.cftc.gov/idc/groups/public/@economicanalysis/documents/file/oce_riskandreturn0414.pdf .

Grid and DCA sources: https://arxiv.org/pdf/2506.11921 , https://robberger.com/lump-sum-investing-vs-dollar-cost-averaging .

---

## What traders and bots typically risk

### Typical risk parameters by trader type (sourced numbers only)

| Trader type | Per-trade risk | Portfolio / loss limits | Source (grade) |
|---|---|---|---|
| German retail norm | **1%** default. 1.5-2% tolerated for small accounts (under about EUR 2,000). **0.25-0.5%** for large accounts (from about EUR 50,000) | Daily stop at 2-3x per-trade risk; weekly about 5-6% (stop and review); monthly about 10% (halve size next month) | stock3 / Goldesel 2026 (practitioner) |
| German CRV norm | Stop at most half the target (**CRV ≥ 2:1**; break-even hit rate about 33%). ORB packages use CRV 2 (Stagge) to 3 (Schäfermeier) | Never double up; avoid concentration | Gräfe / stock3 2021; WH SelfInvest (practitioner) |
| Retail rule of thumb (Elder) | ≤ 2% of equity | Stop trading after -6% in a month | incrediblecharts summary of Elder 2002 [secondary] |
| Retail (Van Tharp) | "1-2%" attributed | none sourced | secondary only [weak] |
| Turtle trend follower | Unit sized so 1N = 1% of equity; stop at 2N, so **≤ 2% per unit** at the stop | 4 units per market, 6 closely correlated, 10 loosely correlated, 12 per direction; -20% notional for each -10% drawdown | Faith, Original Turtle Rules (2003) [primary] |
| ORB academic paper | **1%** of capital per trade | 4x gross leverage cap | Zarattini-Barbon-Aziz via CXO (academic-format) |
| Clenow stock momentum | **0.1%** of equity per ATR(20) unit per position | Index 200-day regime filter | QuantConnect/blog reconstructions (practitioner) |
| CTA, AQR Managed Futures | n/a (vol-budgeted) | **10%** annualised vol target, 5-13% range | AQR SEC filings 2021 [primary] |
| CTA, Man AHL Diversified | n/a | about 13-16% target vol; realised 16%, max DD -30% | fund page / factsheet 2026 [secondary] |
| Prop-firm evaluation, FTMO 2-Step | not prescribed | 5% daily, 10% static max | ftmo.com 2026 [primary] |
| Prop-firm evaluation, FTMO 1-Step | not prescribed | 3% daily, 10% end-of-day-trailing max | ftmo.com 2026 [primary] |
| Prop-firm futures, Topstep 50K | not prescribed | $1,000 daily (2%) [secondary]; $2,000 end-of-day-trailing max (4%) [primary] | Topstep Help Center 2026 |
| Prop-firm reference (German pages) | not prescribed | daily about 4-5%; max total about 10-12% | jptradingcapital / hyrotrader (vendor, search) |
| Multi-manager pod PM | not public | -5% halves capital; about -7.5% usually stopped out | WSJ via eFinancialCareers [press] |
| Market maker | **no public per-trade norm found** | inventory / VaR limits (no sourced numbers) | evidence gap |
| Alpaca's own intraday example bot | **0.1%** of portfolio, stop at the 5-min swing low, 3R target, no notional cap | Flat 15 min before close | `alpacahq/Momentum-Trading-Example` `algo.py` (code; `github-projects.md`) |
| jesse framework | docstring example 1%; notional capped at **100% of capital** | none built in | `jesse/utils.py::risk_to_size` (code) |
| freqtrade defaults | notional slots (`stake_amount`); example `stoploss: -0.10`, `max_open_trades: 3` (about 3.3% of balance per trade, P's arithmetic) | `tradable_balance_ratio 0.99`; protections must be configured (`MaxDrawdown` defaults to 0.0) | freqtrade docs/code (primary) |
| hummingbot directional controller | SL 3%, TP 2%, **leverage 20** (shipped defaults) | global kill switch off by default; if enabled, a +10% *profit* stop | hummingbot code (primary) |
| QuantConnect Lean | weight-based, no per-trade sizer | portfolio max drawdown 5% (non-trailing, re-arms after firing); sector cap 20% | Lean code (primary) |
| **This bot (today)** | **about 0.025%** (the 10% notional cap binds; `SIZING_RISK_PCT` 0.01 configured) | Fixed **15% equity floor** from `hourly_experiment_start_equity` that latches `bot_config.paused=true` (`EQUITY_FLOOR_PCT`, `hourly-check/logic.ts`); `HOURLY_MAX_ENTRIES_PER_DAY` 3; per-position `kill-switch` drawdown; **no daily loss limit, no trailing high-water-mark brake, no consecutive-loss guard** | `_shared/config.ts`, `hourly-check/logic.ts`, issue #675 |

**Corrections carried from the inputs.**
- **Turtles risked about 2% per unit at the stop, not 1%.** 1N = 1% was volatility per unit, and the stop sat at 2N. The primary text says: "No trade could incur more than 2% risk." The unit limits are 4/6/10/12, not the often-quoted "4/12/24".
- **The PDT rule is retired.** The SEC approved FINRA's Rule 4210 amendments effective **2026-06-04**, and Alpaca switched the same day. Intraday buying power replaces day-trade buying power, the 4x intraday minimum falls to $2,000, and the `pattern_day_trader` / `daytrade_count` fields are deprecated. PDT no longer constrains any sizing choice. Nobody has yet checked whether repo code reads the deprecated fields.
- **The stock3/Goldesel article's "ten losses at 1% cost about 40%" is wrong.** At 1% per trade, ten straight losses cost **about 9.6%** (0.99^10 = 0.904).
- **The repo does have an equity floor.** Agent P's grep reported none. In fact `EQUITY_FLOOR_PCT = 0.15` is a fixed-baseline, latching floor (`hourly-check/logic.ts:54`, `:777`). What is missing is a *daily* loss cap and a *trailing* (high-water-mark) brake.

**Where the "1-2% rule" comes from.** It is folk convention traced mainly to Elder. Van Tharp's own figure could not be found, so treat it as unsourced. Professionals mostly control risk at the book level (vol targets, loss limits, VaR), and no public per-trade norm for prop desks or market makers was found. Per-trade risk conventions **do not create edge**; they only control how fast a negative edge is expressed (P on Chague et al.).

### Risk of ruin (gambler's-ruin math, 1:1 payoff, "ruin" = 20% drawdown)

P(ruin) = (q/p)^U, where U = ruin depth / risk per trade; P(ruin) = 1 for p ≤ 0.5 (P's calculation; formula form via crosstrade.io [secondary]).

| Win rate (1:1) | 0.025% risk | 0.1% | 0.25% | 1% | 2% | 5% |
|---|---|---|---|---|---|---|
| 45% / 50% (no edge) | 1 | 1 | 1 | 1 | 1 | 1 |
| 52% | ~0 | 1e-7 | 0.17% | 20% | 45% | 73% |
| 55% | ~0 | ~0 | 1e-7 | 1.8% | 13% | 45% |
| 60% | ~0 | ~0 | ~0 | 0.03% | 1.7% | 20% |

With a positive edge, small risk per trade makes ruin vanishingly unlikely. With zero or negative edge, ruin is certain on an infinite horizon, and sizing only sets the speed.

### Translating the norms to this bot

The inputs to this table:
- a median SPY stop of about **28 bp** (verdict §4.2);
- **234 trades per year**;
- a per-trade standard deviation of about 1.0R, with trades assumed independent;
- the measured expectancy of **-0.139R/trade** at 1 bp/side (95% CI -0.182 to -0.101, n = 2,478).

Notional = risk ÷ 0.0028. Annual vol ≈ sqrt(234) × risk ≈ 15.3 × risk. Expected annual P&L = 234 × -0.139 × risk ≈ -32.5 × risk. The drawdown column is P's Monte Carlo: normal i.i.d. trades, non-compounding, a 15% drawdown from the high-water mark (about the kill-switch headroom named in #675).

| Risk per trade | Notional needed at a ~28 bp stop | Approx. annualised vol | Expected annual P&L at -0.139R | P(15% DD within 5 yrs) / median time |
|---|---|---|---|---|
| 0.025% (today) | ~9% (cap-bound at 10%) | ~0.4% | ~-0.8% | ~0 / not reached |
| 0.10% | ~36% | ~1.5% | ~-3.3% (matches the issue's -$33k/yr) | ~72% / ~4.1 yrs |
| 0.25% | ~89-100% (the `config.ts` ceiling of 1.0x) | ~3.8% | ~-8.1% | ~100% / ~1.7 yrs |
| 1.00% (the retail "rule") | ~357% (needs leverage; `config.ts` forbids it) | ~15% (CTA-like) | ~-32.5% | ~100% / ~0.35 yrs |

Reading:
- The retail 1% rule **cannot be reached on SPY hourly brackets without leverage**. The relevant professional analogue is a portfolio vol budget (10-15% for CTAs), and even 0.25% per trade is only about 3.8% annualised vol here.
- **P(any calendar year positive) ≈ 1.7% at any size**: the yearly mean is -32.5R against a yearly standard deviation of about 15.3R. This matches the verdict's "no calendar year 2016-2026 positive".
- The binding problem is the sign of the mean, not the size of the risk budget.

### Kelly: the growth-optimal stake is zero when expectancy ≤ 0

- Kelly's optimal wager is "the edge (expected return) divided by the odds" (MacLean-Thorp-Ziemba 2010 [primary]).
- For a binary bet, f* = (b·p - q)/b. With p = 0.418 and b ≈ 1.06 (chosen to reproduce -0.139R), **f* ≈ -0.13**.
  - A negative Kelly fraction means the growth-optimal stake is zero.
  - Any positive stake lowers expected log-growth, and larger stakes lower it faster.
  - This reduction of target, stop and session-close exits to a binary bet is illustrative.
- Reversing the signal does not rescue it. The gross mean is -0.031R and costs are about 0.108R per trade, so a mirrored rule nets roughly -0.08R. This is rough, because the bracket geometry is not symmetric.
- **Why practitioners bet 1/4 to 1/2 Kelly** even with a positive edge:
  - Growth at a fraction c of Kelly scales as c(2 - c), so half Kelly keeps 75% of growth at 50% of volatility. Growth reaches zero at 2x Kelly.
  - Errors in the estimated mean matter about 20:2:1 relative to errors in variances and covariances (Chopra-Ziemba, reproduced in MacLean-Thorp-Ziemba).
  - Carver: "It's far better to Half-Kelly", and Sharpe ratios "consistently greater than 1.0 are rarely achieved" [secondary, CXO].

### Gap risk

- A stop bounds risk only while the market trades continuously.
- SPY's median stop is 28 bp, but the overnight |gap| is 236 bp at p99 and 399 bp at the observed max (5-year daily, verdict §4.2).
- A risk-sized position held overnight by mistake could lose about 8R at p99 and about 14R at the max. At 0.25% risk (~90-100% notional), a 399 bp gap is **about 4% of equity in one event**.
- The bot flattens before the close (`hourly-check/logic.ts` session-close exit), so normal-operation overnight exposure is zero. **The failure path of that flatten is the tail**, and it becomes first-order at higher size. #675 already flags it.
- Historical warning: after the October 1987 crash, "in some cases, 20% to 40% of account equity was lost in a single day" by Turtles, despite their 2%-risk stops (primary PDF, p. 16).
- Every strategy above that holds overnight (ranks 1-8 and 11) must size on the gap distribution, not the stop.

### The loss-limit pattern

Across prop firms, CTAs and pod shops, practitioners pair a small per-trade risk with **a hard daily cap of roughly 2-5%** and **a max or trailing drawdown cap of roughly 4-10%** from the start or the high-water mark:
- FTMO: 5%/10% or 3%/10%.
- Topstep: 2% daily and 3-4% trailing.
- German retail: 2-3% daily, about 5-6% weekly, about 10% monthly with size halved.
- Pods: -5% halves capital and about -7.5% stops the PM out.
- Turtles: -20% notional for each -10% drawdown.

The academic basis is Grossman-Zhou (1993): to keep wealth above a fraction of its running maximum, risky exposure should be proportional to the surplus over that floor, which means de-risking as drawdown deepens [primary abstract].

**This bot has the fixed 15% equity floor (latching `paused`) and the per-position kill-switch, but no daily cap and no trailing high-water-mark brake.** At today's 0.025% risk that gap is immaterial, because the floor sits about 600 losing trades away. At 0.25% it is about 60 losses away (`github-projects.md`), and a trailing or daily brake becomes the professional norm the bot lacks.

Framework defaults are mostly illustrative or unsafe and should not be copied as calibrations (`github-projects.md`):
- Lean: 5% portfolio drawdown that re-arms itself.
- freqtrade: `MaxDrawdown` defaults to 0.0.
- hummingbot: an enabled kill switch defaults to a +10% *profit* stop, with 20x leverage.

---

## Should we combine strategies?

### The diversification math

For N equal-volatility streams with average pairwise correlation ρ, portfolio vol / single-stream vol = sqrt(ρ + (1 - ρ)/N). This is the standard result, computed here.

| N | ρ = 0 | ρ = 0.1 | ρ = 0.3 | ρ = 0.6 |
|---|---|---|---|---|
| 2 | 0.71 | 0.74 | 0.81 | 0.89 |
| 5 | 0.45 | 0.53 | 0.66 | 0.82 |
| 15 | 0.26 | 0.40 | 0.59 | 0.79 |

Most of the benefit comes from **low correlation**, not from N. At ρ = 0.6, fifteen streams only cut volatility by about a fifth.

- **Dalio's "Holy Grail".** 15-20 good, uncorrelated return streams "dramatically reduce risks without reducing expected returns" (*Principles*, 2017). The "80% less risk" figure comes from his video and interviews, not the book [secondary]. The operative word is **good**: each stream must have positive expectancy.
- **Effective number of bets** (Meucci 2009): the exponential of the entropy of risk contributions across uncorrelated bets. The repo's verdict uses a close relative (eigenvalue-participation N_eff).
- **Value plus momentum** is the canonical academic pairing, because the two premia are negatively correlated (AMP 2013). **Trend added to an equity book** is the canonical crisis diversifier (MOP 2012).

### How combination is done

| Method | What it is | Where it shows up | What it means here |
|---|---|---|---|
| **Signal blending** (one ensemble rule) | Average several forecasts into one position, netting before execution, at lower cost. Carver: weighted average of forecasts with a diversification multiplier; avoid two variants correlated above 95% | Carver (2015, via CXO); Lean `CompositeAlphaModel` to one portfolio-construction stage; qlib `AverageEnsemble` | Replaces `decideHourly` with a new composite rule (it is already a composite of 14 frozen detectors). Stays at "one rule" but is still a new rule with a full spec path |
| **Separate sleeves** | Each strategy has its own risk budget and positions, usually vol-targeted or risk-parity-sized per sleeve. Easy to reason about, but positions can offset and costs are paid twice | Turtle S1/S2 under one Unit budget; hummingbot V2 per-controller budget plus drawdown latch plus a global drawdown stop | A second decision rule by definition. Needs per-sleeve latches, a shared portfolio cap and multi-symbol `panic` |
| **Regime switching** | One classifier picks which sub-strategy is live | The repo's old 200-DMA `regime.ts` | The classifier is itself a second fitted rule, with its own overfitting risk |
| **Meta-labeling** (López de Prado 2018) | A primary model sets the side; a secondary model predicts whether the signal will be right and sets size or filters | Hudson & Thames example; QuantConnect forum reports of leakage degrading a decent strategy [weak] | It filters false positives from a rule that **already has edge**. It cannot create edge in a primary rule whose gross mean is about zero (-0.031R). Any secondary model must be deterministic, non-LLM and frozen |

Sources: https://www.cxoadvisory.com/big-ideas/a-few-notes-on-systematic-trading , https://hudsonthames.org/meta-labeling-a-toy-example/ , https://www.quantconnect.com/forum/discussion/14706/why-meta-labeling-is-not-a-silver-bullet/ , https://www.morningstar.in/posts/50327/equity-8.aspx , https://risk.net/node/1500233 .

### Pitfalls

1. **Diversification reduces variance, not the mean.**
   - The expected return of a mix is the weighted average of its components' expected returns. If every component has E ≤ 0, so does the mix.
   - Lower variance around a negative mean makes the loss *more* certain and the Sharpe ratio *more* negative.
2. **Correlations rise in crises.**
   - Longin-Solnik (JF 2001): correlation rises in bear markets, driven by market direction.
   - Khandani-Lo (August 2007): apparently independent quant equity books lost together through a forced unwind of crowded positions.
   - Diversification measured in calm periods overstates crisis diversification.
3. **Multiple testing.**
   - Each strategy added to the candidate pool raises the bar every strategy must clear.
   - Harvey-Liu-Zhu want t ≈ 3.0 for a new factor.
   - The Deflated Sharpe Ratio benchmarks against the expected maximum of N zero-skill trials (Bailey-López de Prado 2014).
   - The Probability of Backtest Overfitting (CSCV) formalises the selection trap (Bailey-Borwein-López de Prado-Zhu 2017).
4. **Shared infrastructure is a shared failure mode.** Strategies on one broker, one account, one kill switch and one pause flag fail together. Here, a single `bot_config.paused` and a single `panic` path serve every bot.

Sources: https://hal-hec.archives-ouvertes.fr/hal-00598166 , https://www.nber.org/papers/w14465 , https://www.nber.org/papers/w20592 , https://papers.ssrn.com/abstract=2460551 , https://papers.ssrn.com/abstract=2326253 .

### The in-repo worked example: multi-symbol hourly verdict (2026-10-22)

The study was pre-registered (frozen in commit `a5354e1`) and spread the unchanged live `decideHourly` across SPY's top-10 holdings or 5 ETFs (`docs/research/2026-10-22-multi-symbol-hourly-verdict.md`, branch `research/multi-symbol-hourly`).

- **No edge to spread.** On SPY at 1 bp/side the rule lost -0.139R/trade, every year was negative, and it was already -0.031R before costs. Across symbols, 0 of 19 were EDGE, 7 were NEGATIVE and 12 were NO_EDGE. Four symbols flipped sign between in-sample and out-of-sample.
- **The diversification was real.** Average pairwise daily-P&L correlation was +0.07, and N_eff was 10.15 of 11, even though 1h returns correlate 0.6-0.7 with SPY.
- **It made the loss more certain.**
  - At constant 10% total notional, Sharpe went from **-0.79 to -1.41** and total P&L from -1.38% to -2.16% over 2.9 years.
  - At 10% notional per symbol, total P&L was -23.7%.
- **The overfitting gate failed on all three legs:** DSR 0.07, PBO 0.82, and a bootstrap CI on the uplift that spans 0. Walk-forward symbol selection lost more than SPY alone.
- **A post-hoc +2.97% variant was explicitly labelled as not evidence.** Its per-trade mean was +0.007R, and it turns to -6.34% after the harness-bias correction. This is the selection trap DSR exists to catch.

This is a clean demonstration of Pitfall 1. Combining *different* strategies follows the same arithmetic unless at least one component has a demonstrated positive mean after DSR/PBO-style correction.

### What the invariants require

1. **Every form of combination is a second decision rule or a replacement of the first.** That covers sleeves, regime switches, meta-label sizers that filter or resize entries, and blended ensembles. Each needs:
   - a fresh `superpowers:brainstorming` pass (the CLAUDE.md HARD-GATE);
   - a design spec under `docs/superpowers/specs/`;
   - an ADR in `docs/decisions/`.

   An ensemble that *replaces* `decideHourly` stays at one rule, but it is still a new rule on the same path.
2. **Research gate first.** Each component must be pre-registered and show positive expectancy with multiple-testing correction (t ≈ 3, DSR, PBO, as the repo's own verdicts already apply) *before* combination is considered. Combining is not a substitute for edge.
3. **No LLM in the trading path.** Any meta-labeling or regime model must be deterministic, non-LLM and frozen.
4. **Panic** currently "targets the symbol of whichever bot is currently live". Concurrent sleeves or multi-symbol books need `panic` redesigned to close **every** open position side-aware.
5. **`bot_config.paused`** halts every bot that shares it. That is good for safety, but it means there is no per-sleeve pause. `github-projects.md` suggests one latch key per signal if a second signal ever lands.
6. **Paper-only guard** must cover every new order path, including options legs and multi-symbol orders.
7. **Reproducibility.** The invariant already narrows entry gating to "audit-log-reproducible". Interacting sleeves make that harder, because entries then depend on cross-sleeve state.
8. **A shared risk budget**, following Turtle and CTA practice:
   - a total open-risk and notional cap;
   - a per-direction cap (the Turtles' 12 units);
   - a daily or high-water-mark loss limit.

   Beyond the fixed equity floor and the per-position kill-switch, the bot has none of these today. The framework pattern most compatible with "one decision rule" is **combine signals before sizing**, so that one composite rule feeds one sizer and one risk layer (Lean, qlib; `github-projects.md`).

**Short answer to "should we combine strategies?"** Not yet. Combination is how professionals turn several *positive*-edge streams into a better Sharpe ratio. Here the only live component has a negative mean, and diversifying it measurably made results worse. The order is: find one component with a pre-registered, corrected positive edge; then design a single composite rule or a sleeve architecture through the brainstorm, spec and ADR path, with a shared portfolio risk budget.

---

## Cross-cutting observations

### Which archetypes line up with the deterministic-risk invariant

- **`fits` as-is on the current stack:**
  - volatility targeting (as a sizing function);
  - intraday momentum;
  - opening range breakout;
  - Ichimoku;
  - candlestick/HA rules.

  Every intraday `fits` entry is single-symbol, flat by the close and bracketable, the same risk shape as `decideHourly`. **Every one of them has already been tested here and failed, or rests on weak or negative evidence.** The shape that fits the stack best is the shape the evidence supports least.
- **`needs envelope`:**
  - multi-asset trend;
  - cross-sectional momentum;
  - calendar anomalies;
  - weekly reversal;
  - pairs;
  - RSI(2);
  - regime-switch filters;
  - VRP spreads;
  - Markttechnik.

  The recurring envelope items are:
  - sizing on the overnight-gap distribution rather than the stop, wherever positions hold through the close;
  - a mandatory hard stop and time stop for no-stop canonical versions (RSI(2), Stagge, Gebert);
  - per-name and aggregate notional caps plus a portfolio vol target for multi-symbol books;
  - a multi-symbol, side-aware `panic` and paper-only guard coverage of every new order path (options legs included);
  - a frozen mechanical definition of any discretionary component (swing points, stages).
- **`skip`:**
  - Wyckoff and Elliott as practised, because they need a judgement-based labeller in the trading path;
  - carry and market making, because they are inaccessible;
  - grid and martingale bots, because they have no stop by design and unbounded averaging-down.
- **The best-evidenced archetypes all need breadth and overnight holding**, which this bot does not have. The archetypes that fit the bot's shape (single-symbol intraday) are the weakest in the evidence. This tension is the main finding of the bundle.

### Where EN and DE literatures disagree

1. **Seasonality.**
   - German retail treats seasonality as a primary signal (Speck/Seasonax, Gebert's seasonal point, Stagge's combos).
   - The cleanest *German academic* test (Dichtl-Drobetz) finds Halloween insignificant after 2003 and beaten by buy-and-hold after costs, and Kagels' review recommends it only as a filter.
   - English academic work is more positive on TOM (McConnell-Xu through 2005) and pre-FOMC (Lucca-Moench 2015), but also notes these effects mostly reallocate the equity premium in time.
   - Net: the existence evidence is real, but the tradeable, post-publication, after-cost evidence is weak.
2. **Risk norm framing.**
   - German teaching is per-trade (1%, CRV ≥ 2:1, daily, weekly and monthly loss ladders).
   - English professional evidence is portfolio-level (vol targets, max drawdown); no public per-trade norm exists for professionals.
   - The bot's R = 2 bracket already implements the German CRV 2:1 norm. HSBC's caveat that realised CRV rarely equals planned CRV is borne out: the bot's realised mean is negative despite the 2:1 geometry.
3. **ORB.**
   - English sources are academic-format papers with explicit sizing (1%, 4x) and a 10%-ATR stop, plus one independent net-of-cost replication that found nothing.
   - German sources are vendor packages with wide range-based stops and CRV 2-3 targets and no statistics.
   - Both lean `marketing`. Neither has a clean independent positive replication.
4. **Trend following.**
   - The English literature is home-grown and academic.
   - The German literature is imported (translated Clenow; no confirmed German edition of *Following the Trend*) and focuses on discretionary structure (Markttechnik), not diversified CTA portfolios.
   - Both agree that single-market trend is weak.
5. **Discretionary structure reading.** Markttechnik (DE) and Wyckoff/Dow-style market structure (EN) play the same role in their communities. Neither has a P&L study; the only quantitative Markttechnik work counts continuations.
6. **Turtle risk.** S-EN's secondary sources say "about 2% per unit". P's primary read confirms that and shows the common "1%" shorthand to be a misreading. There is no EN/DE conflict, only a popular myth.
7. **Social trading as evidence.** Only the German literature has a large, measurable public dataset of retail strategies (wikifolio). Its result, no average outperformance and a catastrophic copy-the-winner strategy, matches the English day-trader studies.

### Honest evidence-quality summary

- **Strongest evidence in the bundle: how retail traders fare.** Brazil 97%, Taiwan under 1% persistently profitable, ESMA 74-89%, BaFin turbos 74.2%, wikifolio copy-the-winner -79%. This is regulatory or peer-reviewed and unambiguous.
- **Strong academic evidence for edge sources:**
  - multi-market time-series momentum;
  - cross-sectional momentum (with crash and decay caveats);
  - the existence of carry and the VRP;
  - large-cap weekly reversal, net of costs (thin);
  - vol targeting for risk assets.

  All of these are portfolio-level or breadth phenomena. Many figures here come from abstracts and secondary summaries, not full texts.
- **Decaying or crowded:** pairs/stat-arb, Halloween, intraday momentum (NO_EDGE on SPY 2016-2026 in-repo), and the factor zoo in general (McLean-Pontiff -58% post-publication; Hou-Xue-Zhang 65% fail).
- **Practitioner only:** Connors RSI(2), Weinstein, Markttechnik, Clenow's specific rules, and Turtle performance (the rules are primary, the results proprietary).
- **Marketing:**
  - ORB headline numbers until independently replicated;
  - the German ORB and anomaly packages;
  - Seasonax window-mining;
  - Gebert backtests, though the live index record is factual;
  - grid and DCA vendor claims;
  - Wyckoff and Elliott course material;
  - the boerse.de Champions material.
- **Dropped as unverifiable (by S-DE):** "Hans-Jürgen Unger" (likely Andrea Unger), Speck's "Geheimnisse des DAX", Raimund Schriek rule sets, any documented Paesler system, a German edition of *Following the Trend*, and a Benzinga DAX ORB backtest (HTTP 403).
- **Flagged as secondary or weak in the risk section:**
  - Van Tharp's exact figure;
  - Topstep's daily loss limit;
  - Apex drawdown amounts (conflicting, so omitted from the table);
  - Man AHL targets;
  - Harvey et al. 2018 exact figures;
  - Dalio's "80%";
  - pod-shop thresholds (press);
  - SG Trend's 2010s drought figures.

### Implications for the sizing / config and kill-switch modules (research input only; no live-setting recommendation)

1. **`computeSizing` (`hourly-check/logic.ts`) and `_shared/config.ts`.**
   - #675's mechanics match the mainstream framework shape: a risk leg first and a notional clamp second (jesse, nautilus, freqtrade).
   - The evidence, however, is that every published risk norm assumes positive expectancy. With Kelly at f* ≈ -0.13 and a CI entirely below zero, the literature gives no support for raising risk on the current rule.
   - Raising size scales the expected loss linearly: about -3.3%/yr at 0.1% and about -8.1%/yr at 0.25% of equity. Even on paper, it would contaminate the live record used to judge the rule.
   - `config.ts`'s 1.0x notional ceiling already makes the retail 1% rule unreachable at SPY's stop width. That is a feature, not a bug.
2. **Cost-adjusted sizing.** Mature frameworks subtract round-trip cost inside the sizer (nautilus 2x commission; jesse 3x fee). On a 28 bp stop, 1 bp/side is a material fraction of 1R. Any revised `computeSizing` would size on net R.
3. **Loss limits missing from the stack.** Every professional reference pairs per-trade risk with a daily cap (2-5%) and a trailing or high-water-mark cap (4-10%). The bot has only the fixed-baseline 15% latching floor and the per-position kill-switch. If size ever rises, the evidence points to adding, as separate, range-validated, default-OFF settings per `.claude/skills/add-or-extend-agent/SKILL.md`:
   - a daily loss limit;
   - a trailing high-water-mark brake;
   - and possibly a consecutive-loss guard next to the cooldown gate.

   All would latch via `bot_config.paused`, never self-clear, and use one-sided names. These are candidates for `roadmap.md`, not decisions.
4. **`kill-switch` and session-close flatten.** At 90-100% notional, the worst observed SPY overnight gap is about 4% of equity (about 14R) in one event. The flatten failure path and the kill-switch's coverage of a position left open through the close become first-order risks at higher size. Any overnight-holding strategy from the top 15 would need gap-based sizing as part of its envelope.
5. **`bot_config.paused` and `panic`.** Both assume one live bot and one symbol. Every multi-symbol or multi-sleeve archetype in the top 15 (ranks 1, 2, 5, 6, and any combination) requires a side-aware, all-positions `panic` and a decision on per-signal latch keys **before** it can be specified.
6. **The research path the evidence points to** is a breadth test of a well-evidenced archetype: multi-ETF time-series momentum with portfolio vol targeting, or cross-sectional momentum. Either would be pre-registered with a t ≈ 3 / DSR / PBO gate. Neither is a parameter change to the current rule; it is a replacement candidate that must go through the One-decision-rule brainstorm, spec and ADR path. The bundle's evidence does not support tuning risk on the incumbent rule as a route to profitability.
