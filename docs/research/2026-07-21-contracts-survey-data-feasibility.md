# Contracts survey: data feasibility spike (ES/MES vs SPY proxy, cadence, power)

**Issue:** #416 · **Batch:** #413 · **Date:** 2026-07-21
**Author:** Analyst (research-only; read-only market-data probes against
`https://data.alpaca.markets` and, in fix round 1, credential-free read-only `yfinance` depth
queries, `CLAUDE_AGENT_NO_BROKER=1` set for the whole session; no trading endpoint touched; no
broker account opened beyond the existing paper keys; no production/TypeScript code changed)
**Revised:** 2026-07-24 (fix round 1 — the recommended source was swapped from Alpaca to yfinance
after probe P6 showed Alpaca's daily floor cannot reach the frozen n_w=13 bar; see §2.1, §2.1b, §5)

## §0 Scope, the no-fabrication rule, and what this document does not do

This document does not run a backtest, does not freeze a candidate grid, and does not authorize
anything live. Every number below is exactly one of four kinds, labeled at the point of use:

1. **A live probe output** — either a `curl` call against `https://data.alpaca.markets` (GET only,
   ≤5-bar or single-page responses per the task's data-download cap), transcribed with the key values
   redacted (commands below use `$ALPACA_API_KEY`/`$ALPACA_SECRET_KEY` placeholders), or a
   credential-free `yfinance` metadata read (P6–P8, added in fix round 1) that reports only a
   symbol's first/last daily bar and row count. Full transcripts are quoted in the Appendix.
2. **A cited documentation page** — fetched via WebFetch, cited with URL and access date
   (2026-07-21 for every citation below unless noted). No price data was scraped from any of these
   pages; only availability/cadence/cost/license/methodology text.
3. **Explicitly marked "pending #415"** — the parallel batch package fact-checking MES's exact
   contract multiplier/margin/per-trip cost. No such figure is invented here.
4. **An explicitly-labeled convention or planning assumption** — a figure that is neither a probe
   output nor cited to a page, but a standard convention carried openly as an input and flagged as
   such where it is used. Two figures below are of this kind, both annotated in §3: the **nominal 78
   RTH bars/day** (6.5h × 12, distinguished there from P3's measured 82) and the **ES/MES ~23h ×
   5-day session** used for futures periods/year (unsourced because of the CME fetch-access gap,
   §1.2).

**This note recommends a data source + cadence for the survey's backtest data, never a different
instrument.** The frozen `docs/research/2026-07-21-leveraged-contracts-preregistration.md` §2.5
wrapper recommendation (MES-class micro index futures, for **live/paper trading** were a candidate
ever promoted) and §4 promotion bar (the #398 gate + SPY median after-tax Calmar
**1.3085475049604838**, n=13 windows 2013–2025) are untouched by anything below — see §5's explicit
statement. This document authorizes nothing live, restating CLAUDE.md's Architectural invariants
(no LLM in the trading path; one decision rule) exactly as the frozen pre-registration's §7 does.

**TL;DR: recommend SPY daily bars, at daily cadence, via the yfinance daily series
`backtest/walkforward.py` already fetches (`yf.download(..., auto_adjust=True)`, `walkforward.py:41`)
— the same source that computed the frozen §4 SPY Calmar bar, with 33 years of daily history
measured live (probe P6: first bar 1993-01-29). The existing Alpaca `data.alpaca.markets`
`/v2/stocks/{symbol}/bars` access (`supabase/functions/_shared/marketdata.ts`) is the
recency/cross-check leg, not the survey's primary history source.** The reason for that split is
measured, not assumed: Alpaca's daily SPY history floors at **2016-01-04** (probe P1) — ≈10 available
years, n_w≈9 — which is short of the frozen n_w=13 bar by the same margin this note disqualifies the
5Min-SIP row for (§3). Alpaca's own documentation gives `Historical data timeframe: Since 2016` on
**both** the Basic and the Algo Trader Plus tier, so this is a hard provider floor, not a free-tier
gate a survey could pay past (citation + access date in the Appendix). ES/MES-direct loses at every
free cadence (§3/§5): on power at MES-native and intraday, on unresolved splice construction at ES
daily (§5 records the latter as resolvable, not hard). SPY-proxy-intraday is disqualified
on power grounds (§3); SPY-proxy-daily via yfinance is the only (path × cadence) cell that clears the
frozen n_w=13 comparability bar for free **with no unresolved data-construction question**, using
already-existing repo infrastructure, with the systematic proxy errors (§2) reported honestly as
sensitivity risk, not glossed over.

---

## §1 Path A — ES/MES direct

### §1.1 Source table

| Source | Cadence(s) | Depth | Continuous-contract handling | License / cost | Cited |
|---|---|---|---|---|---|
| CME (native MES) | any | MES launched **2019** (secondary-sourced below; CME's own site would not load — see caveat) → **≈7 years** of *native* MES history as of 2026-07-21 | N/A (native contract, no splicing needed within its own life) | Exchange-listed; access cost depends on broker/vendor | Optimus Futures blog post, dated 2019-05-15, describing Micro E-mini equity-index futures as "newly launched" — corroborates a May-2019 CME launch (`https://optimusfutures.com/blog/micro-e-mini-futures/`, accessed 2026-07-21); Wikipedia's "E-mini" article states MES's contract multiplier is **$5** vs ES's **$50** (1/10 size), citing CME (`https://en.wikipedia.org/wiki/E-mini`, accessed 2026-07-21) |
| CME (ES, standard) | any | ES introduced **1997-09-09** per Wikipedia's "E-mini S&P 500" article, which also gives ES's **$50**-multiplier and a Dec-2024 notional figure (`https://en.wikipedia.org/wiki/E-mini_S%26P_500`, accessed 2026-07-21) | N/A within a single contract's life; splicing required to build a continuous series (§1.3) | Exchange-listed | same |
| Yahoo Finance `ES=F` / `MES=F` (via yfinance, the repo's existing fetch path in `backtest/walkforward.py`) | Daily: **probed** — `ES=F` first daily bar **2000-09-18** (6,525 bars to 2026-07-23), `MES=F` first daily bar **2019-05-03** (1,818 bars), probes P7/P8 §2.1; Intraday: capped (citation at right, **not probed**) | Daily continuous front-month, **unadjusted** (no roll back-adjustment — a raw front-month splice); **assumed / not probed** — the probes measured depth only, not splice construction | **No roll handling** — Yahoo's continuous futures series is the raw front-month print, roll gaps unhandled, per the sub-plan's own framing. **Assumed / not probed**, flagged with the same discipline as the Stooq row below: no probe here inspects roll dates or price gaps, and no citation states it | Free | Interval-limit citation: `https://algotrading101.com/learn/yfinance-guide/` (accessed 2026-07-21) states "1m data is only retrievable for the last 7 days, and anything intraday (interval <1d) only for the last 60 days" — a **more restrictive** figure than the commonly-cited "1m ≈ 30 days / 60m ≈ 730 days" planning assumption; both are noted below as the intraday depth is disqualifying either way (§3) |
| Stooq (`es.f` and similar continuous-futures symbols) | daily | **Not independently verified** — `stooq.com` did not return fetchable page content to WebFetch on repeated attempts (empty/JS-rendered response), so no depth/terms figure is reported. Treated as **unverified**, not as a data point either for or against this path. | unknown | Historically free for retail daily use, per general market knowledge; not independently sourced here | fetch attempts: `https://stooq.com/db/`, `https://stooq.com/db/h/`, `https://stooq.com/help/?id=42` — all returned empty content to WebFetch, 2026-07-21 |
| Databento (`GLBX.MDP3`, CME Globex market data) | any (tick/MBO up to any downsampled bar cadence) | **"16+ years of available history"** per Databento's pricing page (≈ back to 2010) | Vendor provides raw/normalized market-by-order data; continuous-contract construction is the consumer's responsibility (not stated as a Databento-provided derived product on the page fetched) | **"Pay as you go with usage-based pricing ($/GB)," no subscription required** for the usage-based tier, per the same page | `https://databento.com/pricing`, accessed 2026-07-21 |
| FirstRate Data (futures bars) | 1-minute, 5-minute, 30-minute, 1-hour, 1-day | **"starting back to 2007"** for "the most active 130 contracts (as of July 2026)," explicitly naming E-mini S&P 500 (ES) as a covered product | **Vendor-constructed and roll-adjusted** — the page states it provides "both individual futures contracts as well as a continuous futures series with prices adjusted for the price gaps from rolling contracts (this series is best suited to long timeframe backtesting of futures trading strategies)". The **method** (Panama/difference vs proportional/ratio, §1.3) and the roll-date trigger are not named on the page fetched | Paid (no price quoted on the page fetched) | `https://firstratedata.com`, accessed 2026-07-21, quote re-verified 2026-07-24 |
| CQG / PortaraCQG | — | not fetched (`https://www.cqg.com/data/data-sources` returned HTTP 404) | — | — | attempted, not sourced |

### §1.2 CME's own site — a repeated fetch-access limitation

Every attempted fetch of `cmegroup.com` (product-specs page, education page, and a 2019 press
release URL) either timed out or 404'd. This repeats the exact finding already disclosed in
`docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §4.3 ("CME's own site
(`cmegroup.com`) timed out on every fetch attempt") — a fetch-access limitation on this session's
tooling, not a claim about CME's actual publication practices. MES's launch date and multiplier
above are therefore secondary-sourced (Optimus Futures blog post + Wikipedia), consistent with how
the frozen pre-registration already handled the same CME-fetch-access gap for 6E/M6E contract specs
(§2.3 of that document).

### §1.3 Continuous-contract roll methodology

QuantStart's "Continuous Futures Contracts for Backtesting Purposes" describes two back-adjustment
conventions: **Panama adjustment** ("shifting each contract such that the individual deliveries
join in a smooth manner to the adjacent contracts" — an additive/difference method) and
**proportional adjustment** ("the ratio of the older settle (close) price to the newer open price
is used to proportionally adjust the prices of historical contracts" — a ratio method), plus a
fixed-days-before-expiry roll-date convention (the article's own default implementation uses
`rollover_days=5`) rather than a volume-crossover trigger
(`https://www.quantstart.com/articles/Continuous-Futures-Contracts-for-Backtesting-Purposes/`,
accessed 2026-07-21). **This is a citable methodology, not a claim that every source in §1.1 already
applies it** — Yahoo's `ES=F`/`MES=F` series is characterised as raw/unadjusted with no
back-adjustment at all (assumed, not probed — §1.1). **FirstRateData does state it back-adjusts**:
its page offers "a continuous futures series with prices adjusted for the price gaps from rolling
contracts," so splicing is *not* left to the consumer there — but **which** convention (Panama vs
proportional) and which roll trigger it uses is unnamed on the page fetched, so the convention still
has to be pinned before the series is trusted. Databento's page describes raw/normalized
market-by-order data with no continuous-contract product stated, so **on the page fetched** splicing
does remain the consumer's job there — the same hedge the §1.1 cell carries, since a page not
stating such a product is not the same as the vendor not offering one.
**Stitching-tractability judgment:** building a
correctly back-adjusted continuous ES series from raw vendor data is a real, non-trivial
methodology choice (which convention, which roll trigger) that this survey would have to pin
explicitly before any backtest — an extra degree of freedom the SPY-proxy path (§2) does not carry,
since Alpaca/yfinance already serve a single continuously-traded instrument with no contract
splicing at all.

### §1.4 MES-native vs ES-proxy-for-MES caveat

MES's ≈7-year native history (since 2019) cannot by itself clear the frozen n_w=13 comparability
bar (§3) at any cadence — 7 years of calendar-year-aligned windows yields at most n_w≈6. The
standard workaround, noted in the sub-plan and consistent with the ES/MES relationship (MES is
1/10th the notional of ES on the same underlying index, tracking the same price series to within a
scaling factor): **backtest signal generation on ES price history, then model MES's own
cost/margin structure separately** (the MES contract-economics figures themselves are **pending
#415**). This lets a survey reach the full ES depth (1997 native, ~2007–2010+ for third-party
tick-level vendors) while still targeting the MES wrapper's actual trading economics for any
eventual live/paper candidate — the wrapper choice in §2.5 is unaffected either way (§5).

---

## §2 Path B — SPY proxy via the repo's existing access (Alpaca + yfinance)

### §2.1 Alpaca probe matrix (P1–P5)

Base command shape used throughout (auth headers use env-var placeholders; no key value is ever
printed):

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=<TF>&feed=<FEED>&start=<START>&limit=<N>&adjustment=<ADJ>&sort=asc" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```

**P1 — history depth per (timeframe × feed).** `timeframe ∈ {1Min, 5Min, 15Min, 1Hour, 1Day}` ×
`feed ∈ {iex, sip}`, `start=2015-01-01T00:00:00Z&limit=5&adjustment=all&sort=asc`:

| Timeframe | Feed | HTTP | Earliest bar `t` returned |
|---|---|---|---|
| 1Min | iex | 200 | **2020-07-27T12:49:00Z** |
| 1Min | sip | 200 | **2016-01-01T00:01:00Z** |
| 5Min | iex | 200 | 2020-07-27T12:45:00Z |
| 5Min | sip | 200 | 2016-01-01T00:00:00Z |
| 15Min | iex | 200 | 2020-07-27T12:45:00Z |
| 15Min | sip | 200 | 2016-01-01T00:00:00Z |
| 1Hour | iex | 200 | 2020-07-27T12:00:00Z |
| 1Hour | sip | 200 | 2016-01-01T00:00:00Z |
| 1Day | iex | 200 | 2018-11-01T04:00:00Z (single sparse print, volume 200 — not usable as a real depth floor) then next real print **2020-07-27** |
| 1Day | sip | 200 | **2016-01-04T05:00:00Z** (first NYSE trading day of 2016) |

No historical request was rejected on the free tier — **SIP is permitted for historical (non-recent)
data on this Basic account**, contradicting a naive "SIP requires a paid subscription" assumption;
the actual gate is recency, not history depth (P2). Bisection (start dates 2016–2019-06, all
identical; Appendix P1): the IEX-feed floor of **2020-07-27T12:49:00Z is a hard floor,
independent of how far back `start` is set** — IEX intraday history simply does not exist before
that date on this account. SIP's **2016-01-01** floor is the commonly-cited Alpaca SIP-historical
floor, now confirmed live rather than assumed.

**Consequence for the survey — this is the load-bearing P1 finding.** The `1Day | sip` row above
floors at **2016-01-04**, so Alpaca's *daily* SPY depth is ≈10 available years → **n_w ≈ 9**, three
to four calendar windows short of the frozen n_w=13 bar — the same shortfall that disqualifies the
5Min-SIP row in §3. This is a **provider floor, not a tier gate**: Alpaca's own market-data
documentation lists `Historical data timeframe: Since 2016` for both the Basic and the Algo Trader
Plus tier (`https://docs.alpaca.markets/docs/about-market-data-api`, accessed 2026-07-24), so no
amount of spend on Alpaca reaches 2013. **Alpaca therefore cannot be the survey's primary history
source at any cadence**; §5 recommends it as the recency/cross-check leg instead, over the
2016→present overlap where it does have data.

**P2 — recency restriction.** `timeframe=1Min&feed=sip`, `start`=now−5min:

```
{"message":"subscription does not permit querying recent SIP data"}
HTTP 403
```

Confirmed on both the `bars` endpoint and `trades/latest?feed=sip` (`GET latest trade feed=sip` →
same 403). The `iex` feed has no such restriction (`trades/latest?feed=iex` → HTTP 200, a trade
timestamped seconds before the request). **This is the actual SIP gate on Basic**: real-time/recent
(<~15 min) SIP data is subscription-gated; historical SIP data is not.

**P3 — session coverage.** One trading day (2026-07-20), `timeframe=5Min`, both feeds:

| Feed | Bar count | First bar (UTC) | Last bar (UTC) | Session implied |
|---|---|---|---|---|
| iex | 82 | 12:00 | 20:10 | ≈RTH + narrow pre/post (close to the nominal 78 five-min RTH bars = 6.5h × 12) |
| sip | **192** | 08:00 | 23:55 | **08:00–24:00 UTC = 16h = exactly 192 five-min bars** — the full 4am–8pm ET US extended-hours session |

Neither feed carries anything resembling ES/MES's ~23h×5-day session — the SPY-proxy path's
observable trading day tops out at 16h (SIP extended) vs ES/MES's ~23h, a **>30% session-hours
shortfall even at the most generous SPY feed**, before counting the days ES/MES trades that SPY
does not (e.g. Sunday evening open). This is the quantified core of the session-hours proxy gap
(§2.2).

**P4 — adjustment semantics.** `timeframe=1Day&feed=sip`, window 2025-12-15→2025-12-23 (spans
SPY's December ex-dividend date), `adjustment=raw` vs `adjustment=all`:

| Date | raw close | all close | raw − all |
|---|---|---|---|
| 2025-12-15 | 680.73 | 675.10 | 5.63 |
| 2025-12-16 | 678.87 | 673.26 | 5.61 |
| 2025-12-17 | 671.40 | 665.85 | 5.55 |
| 2025-12-18 | 676.47 | 670.88 | 5.59 |
| **2025-12-19** | 680.59 | 676.96 | **3.63** |
| 2025-12-22 | 684.83 | 681.18 | 3.65 |
| 2025-12-23 | 687.96 | 684.29 | 3.67 |

The back-adjustment offset **steps down by ≈$1.96 exactly between 2025-12-18 and 2025-12-19** — the
probe output's own evidence that 2025-12-19 was a SPY ex-dividend date, and that
`adjustment=all` is a genuine total-return-style back-adjustment (a step function at each ex-div
date), not a flat historical rescale. This is the mechanism `marketdata.ts` already relies on
(`adjustment=all`, comment: "the backtest that validated the strategy uses fully adjusted data, so
the live SMA must too"). **Futures carry no such adjustment at all** — MES/ES prices embed no
dividend income; the economic analog on the futures side is the cost-of-carry/financing basis
priced into the forward curve, a structurally different mechanism (§2.2).

**P5 — pagination sanity.** One `limit=10000` page, `timeframe=1Min&feed=iex`,
`start=2020-07-27T00:00:00Z`: **10,000 bars returned** (2020-07-27T12:49 → 2020-09-01T18:13),
`next_page_token` **present**. Full-depth pulls are mechanically feasible via the documented
pagination contract; no full-history download was performed (per the task's data cap).

### §2.1b yfinance daily-depth probes (P6–P8)

These probes exist because the earlier revision of this note asserted yfinance's daily depth as
"full depth observed" with no probe behind it — an assumed number presented as an observation.
yfinance needs no credentials, so unlike P1–P5 these are reproducible by anyone. Each call is
`yf.download(<symbol>, period="max", interval="1d", auto_adjust=True)` — the identical fetch shape
`backtest/walkforward.py:41` already uses, so the measured series *is* the survey's candidate series,
not a near-relative of it. Accessed **2026-07-24**; full transcript in the Appendix.

| Probe | Symbol | Daily bars returned | First daily bar | Last daily bar | Calendar span |
|---|---|---|---|---|---|
| **P6** | `SPY` | **8,427** | **1993-01-29** | 2026-07-23 | **≈33 years** |
| **P7** | `ES=F` | 6,525 | **2000-09-18** | 2026-07-23 | ≈26 years |
| **P8** | `MES=F` | 1,818 | **2019-05-03** | 2026-07-23 | ≈7 years |

Readings:

- **P6 settles the primary-source question.** SPY daily via yfinance reaches 1993 — it covers the
  frozen bar's 2013–2025 windows with two decades to spare, where Alpaca's daily floor (2016, P1)
  does not reach 2013 at all. Depth in the §3 daily row is attributable to **yfinance**, not to
  Alpaca; the earlier revision credited one provider's cell with the other's number.
- **P7** replaces the unprobed "full depth observed" claim for `ES=F` with a measured 2000-09-18
  start. Depth is confirmed; the **splice quality** of that series is a separate question these
  probes do **not** answer (§1.1 marks it assumed / not probed).
- **P8** independently corroborates the secondary-sourced May-2019 MES launch date (§1.1/§1.2) from
  price data rather than a blog post: the first `MES=F` daily bar is 2019-05-03. Complete
  calendar years 2020–2025 = 6, so after the never-scored warm-up year the MES-native path yields
  n_w ≈ 5 — at or just under the "≈6 at best" upper bound §1.4/§3 already state, and either way far
  short of 13.

### §2.2 The systematic proxy error, enumerated honestly

- **Session-hours gap (quantified by P3):** SPY-proxy tops out at 16h/day (SIP extended) vs
  ES/MES's ~23h×5-day session — overnight signals, gaps, and reactions to after-hours
  macro/earnings news that occur outside 4am–8pm ET are structurally unobservable in any SPY-proxy
  series, regardless of feed.
- **Dividends vs futures financing basis (quantified by P4):** SPY's `adjustment=all` bakes
  dividend income into a back-adjusted equity series; ES/MES instead embed the risk-free-rate/
  dividend-yield **cost-of-carry basis** directly into the forward price relative to spot. These are
  economically related (both derive from the same dividend stream) but **mechanically different**
  series — a signal tuned on SPY's dividend-adjusted returns is not tuned on the same return series
  ES/MES would actually produce.
- **ETF microstructure vs futures ticks:** SPY trades as a listed ETF with its own bid/ask/print
  microstructure (creation/redemption arbitrage, NAV tracking); ES/MES trade as centrally-cleared
  futures on CME Globex with entirely different tick size, liquidity profile, and settlement
  mechanics. Neither this note nor any cited source here quantifies the resulting slippage/fill
  divergence — flagged as an unresolved proxy risk, not assumed away.
- **Both existing repo data paths already use this family.** `supabase/functions/_shared/
  marketdata.ts` (production, `/v2/stocks/{symbol}/bars`, `adjustment=all`, default `feed=iex`) and
  `backtest/walkforward.py` (research, yfinance daily) are both already SPY/UPRO-proxy paths — using
  SPY-proxy data for a survey signal is not a new methodology decision for this repo, it is the
  existing one, extended to a new candidate direction.

---

## §3 Power table

Per the frozen convention (`docs/research/2026-07-13-forex-4h-strategy-preregistration.md` §5):
12-month calendar-year-aligned test windows, one warm-up year never scored, scored windows
n_w ≈ available years − 1. **The comparability bar is n_w = 13**, matching the frozen SPY Calmar's
2013–2025 windows (`2026-07-21-leveraged-contracts-preregistration.md` §4). Bootstrap n = n_w,
block length L = round(n_w^(1/3)) — at n_w=13, L=round(2.35)=2; at n_w=6 (MES-native-only), L=
round(1.82)=2 also, but the worst-window statistic (the multiplicity control, §5/§6 of the frozen
forex pre-reg) degenerates fast as n_w shrinks — a single bad calendar year dominates a 6-window
sample far more than a 13-window one.

**DSR / PSR required-history derivation.** From `probabilistic_sharpe_ratio` in
`backtest/overfitting_gate.py`: `z = (SR_per − benchmark) * sqrt(n−1) / sqrt(psr_denom)`; ignoring
the skew/kurtosis correction term (≈1 for near-normal returns) and solving for n at the 95%
one-sided threshold (z₀.₉₅ = 1.6449): **n ≳ 1 + (z₀.₉₅ / SR_per)²**, where SR_per = SR_ann /
√(periods_per_year). **Because n scales with periods_per_year and years = n / periods_per_year,
the required *years* of history is (to first order — the "+1" is negligible at any realistic
periods/year) independent of cadence**, driven only by the assumed true annualized Sharpe:

| Assumed SR_ann | Required per-period n (daily, 252/yr) | Required years (any cadence, ≈ same) |
|---|---|---|
| 0.5 | ≈2,728 | **≈10.8 years** |
| 1.0 | ≈683 | **≈2.7 years** |
| 1.5 | ≈304 | **≈1.2 years** |

(Sensitivity check at other cadences confirms the years figure barely moves: 5Min RTH,
periods/year=19,656 → same ≈10.8/2.7/1.2 years; ES/MES-hourly, periods/year≈5,980 → same
≈10.8/2.7/1.2 years.) The **sr_star deflation for N trials** (the DSR's actual bar, above the raw
PSR benchmark) raises the effective SR_per threshold further as N grows — N itself is frozen by
the eventual survey's own pre-registration, not here; the forex precedent's 33-cell grid is the
labeled planning-assumption magnitude for what "N trials" might mean in practice.

**PBO (CSCV, S=16).** T = periods/year × years; block size = T // 16; judgment: ≥~30 obs/block for
non-noise per-block Sharpes.

| Path | Cadence | Available years (free) | Periods/year | T | Block (T//16) | PBO verdict |
|---|---|---|---|---|---|---|
| B (SPY proxy) | Daily, **yfinance** (`walkforward.py:41`) | **≈33 available (P6: 1993-01-29→2026)**; 14 spanned (2013–2026); the frozen bar's own 13 windows are 2013–2025 | 252 | 3,528 (on the 14 spanned) | 220 | **passes easily** |
| B (SPY proxy) | Daily, **Alpaca** `/v2/stocks/{symbol}/bars` | ≈10 (P1: 2016-01-04→2026) | 252 | 2,520 | 157 | passes on block size; **but n_w≈9 — fails the comparability bar below** |
| B (SPY proxy) | 5Min, SIP | ≈10 (2016→2026) | 48,384 (P3: 192 bars/day) | 483,840 | 30,240 | passes trivially on block size |
| B (SPY proxy) | 5Min, IEX | ≈6 (2020-07→2026) | 19,656 (**nominal** 78 bars/day = 6.5h RTH × 12; *not* a P3 output — P3's IEX day measured 82 bars incl. narrow pre/post) | 117,936 | 7,371 | passes trivially on block size |
| A (ES/MES) | Daily, free (yfinance `ES=F`) | **≈26 (P7: 2000-09-18→2026)**; unadjusted-roll caveat, §1.1 | 252 | large | large | passes trivially on block size |
| A (ES/MES) | Daily/intraday, paid (Databento/FirstRateData) | 16 / since-2007 (≈19) | any | large | large | passes trivially on block size |
| A (ES/MES) | Intraday, free (yfinance) | ≤60 days (§1.1 citation) | any | tiny | tiny | **fails PBO block-size floor outright** |
| A (MES-native, any cadence) | any | ≈7 (P8: first `MES=F` daily bar 2019-05-03) | any | moderate | moderate | PBO block size fine; **n_w≈5–6 fails the bootstrap comparability bar below** |

**The binding constraint is not PBO block size (every non-trivially-short source clears it) — it is
the n_w=13 calendar-window comparability bar and, secondarily, the DSR years-of-history
requirement.** Verdict by (path × cadence), against n_w=13:

| Path | Cadence | Years of free history | n_w achievable | Clears n_w=13? |
|---|---|---|---|---|
| B (SPY proxy) | **Daily, yfinance** | **≈33 (P6: 1993→2026)** — spans the frozen bar's own 2013–2025 windows with two decades to spare | **13–14 (32 at most)** | **Yes** |
| B (SPY proxy) | Daily, Alpaca | ≈10 (P1: 2016-01-04 floor; provider floor on every tier, not a free-tier gate) | ≈9 | **No** (short by ~3–4 windows) — cross-check leg only, §5 |
| B (SPY proxy) | 5Min, SIP | ≈10 | ≈9 | No (short by ~3–4 windows) |
| B (SPY proxy) | 5Min, IEX | ≈6 | ≈5 | No (short by ~7–8 windows) |
| A (ES/MES) | Daily, free (yfinance, unadjusted roll) | ≈26 for ES (P7: 2000-09-18); roll-splice quality unprobed | 13+ (quantity), quality caveat (§1.3) | Quantity yes; **quality flagged, not free of a modeling decision** |
| A (ES/MES) | Daily/intraday, paid vendor | 16 (Databento) / ≈19 (FirstRateData, since 2007) | 13+ | Yes, **at cost** (non-goal: no spend authorized here) |
| A (ES/MES) | Intraday, free (yfinance) | <1 (60-day cap, §1.1) | ~0 | **No — orders of magnitude short** |
| A (MES-native) | any cadence | ≈7 (P8: 2019-05-03) | ≈5–6 | **No** (native-only) |

**Periods/year annotation.** The 192 extended-hours figure is a genuine P3 output (08:00–23:55 UTC
inclusive = 192 five-minute slots). The 78 RTH figure is **not** — it is the nominal 6.5h × 12
convention, carried explicitly as an assumption; P3's IEX day actually measured 82 bars (RTH plus a
narrow pre/post fringe). The power arithmetic above is stated against the nominal 78, and is
self-consistent on that input (78 × 252 = 19,656; 117,936 // 16 = 7,371). Futures periods/year use
cited CME session hours (ES/MES ~23h×5-day, per this note's own framing, not independently re-verified
against a CME session-calendar citation this session — the CME-fetch-access gap, §1.2, applies
here too). **The exact annualization constant (252 vs a futures-session count) is a convention the
survey's own pre-registration must pin explicitly**, exactly as the forex precedent pinned √260 vs
√252 (`2026-07-13-forex-4h-strategy-preregistration.md` §5) — this note only establishes the
order-of-magnitude power picture, not the final constant.

---

## §4 Modeled cost inputs per path

**Path A (ES/MES).** MES's own contract multiplier, margin requirement, and per-round-trip cost are
**pending #415** — no such figure is invented here. As a bracket, not a substitute: the frozen
pre-registration's already-sourced FX-future analogues (`2026-07-13-forex-short-horizon-
feasibility-gate.md` §4.3) — **6E 0.56–1.00 bp, M6E 1.23–2.10 bp round-trip** — are cited here
purely as **FX-future cost-structure examples** (flat per-contract commission + tick value not
scaling down 10x with notional, so the *micro* contract is proportionally dearer than the standard
one), **not as MES numbers**. Wikipedia's "E-mini" article gives MES's multiplier as **$5** (vs
ES's $50), a structural fact, not a cost figure. A structural cost advantage independent of the
exact per-trip figure: no daily rollover/overnight-financing charge (§2.3 of the frozen
pre-registration).

**Path B (SPY proxy).** The repo's existing frictions: `SLIPPAGE_BPS = 5` (0.05%) and
`COMMISSION_BPS = 5` (0.05%) per side, from `backtest/regime.py` — already used by
`backtest/walkforward.py` for every SPY/UPRO backtest, including the one that computed the frozen
§4 SPY Calmar bar. No new cost model is proposed for the SPY-proxy path; it inherits the one
already in production use in this repo's research code.

This section does not block on #415 — it brackets and labels what is known, pending, or borrowed,
per the sub-plan's instruction.

---

## §5 Recommendation

**Recommended (data source, cadence) pair: SPY daily bars from the yfinance daily series
`backtest/walkforward.py:41` already fetches (`yf.download(..., auto_adjust=True)`), at daily
cadence.** That is the single (source, cadence) pair the survey runs on.

**The Alpaca `/v2/stocks/{symbol}/bars` access is retained as a secondary cross-check leg, not as
the survey's history source.** An earlier revision of this note had these two roles the other way
round; probe evidence reverses them:

- Alpaca's daily SPY history floors at **2016-01-04** (P1), ≈10 years → n_w≈9, and Alpaca's own
  documentation lists `Historical data timeframe: Since 2016` on **both** the Basic and Algo Trader
  Plus tiers — a provider floor, not a payable free-tier gate. A source that cannot reach 2013
  cannot be compared to the frozen §4 bar apples-to-apples, so it cannot be the primary.
- yfinance daily SPY reaches **1993-01-29** (P6, 8,427 bars) — it covers 2013–2025 with two decades
  of margin, and it is the **same fetch call** that produced the frozen bar.
- The cross-check leg still earns its place: production `marketdata.ts` reads SPY daily from Alpaca,
  so any candidate eventually promoted to live would run on Alpaca's series. Reconciling the two
  providers over their **2016→present overlap** is the cheap check that the survey's research series
  and the live series do not silently diverge. It is a consistency check, never the depth source.

**Why this cell and no other:**

- It is the **only (path × cadence) cell in §3 that clears the frozen n_w=13 comparability bar for
  free with no unresolved data-construction question** (the ES-daily-free cell also clears it on raw
  quantity — see disqualifier 3 below — so "only" is scoped to that qualifier, not to raw window
  count), using infrastructure this repo already has integrated (`walkforward.py` in research,
  `marketdata.ts` in production for the cross-check leg) — zero new integration work, zero new spend.
- It **directly reconciles with the frozen §4 bar's own computation** — the SPY median after-tax
  Calmar 1.3085475049604838 was itself computed on 2013–2025 calendar-year windows by
  `backtest/walkforward.py`, i.e. from this exact fetch call, not merely from the same data family
  (the pre-registration's own reproduction note: yfinance reproduced the median to
  1.3085323112253744, a ~1.2e-5 relative difference attributed to routine `auto_adjust`
  micro-revisions). Using the same family for the candidate keeps the comparison apples-to-apples,
  the exact rationale §2.5 of the frozen pre-registration already gave for choosing an
  S&P-500-tracking futures wrapper in the first place ("keeps the eventual candidate's benchmark
  comparison as close as possible to the existing after-tax-Calmar-vs-SPY bar").
- It **avoids the continuous-contract roll-methodology degree of freedom entirely** (§1.3) — no
  Panama-vs-proportional, no roll-date-trigger choice to pin before a single bar is used.

**The losing paths' disqualifiers, enumerated:**

1. **ES/MES-native-only, any cadence:** ≈7 years of history (first `MES=F` daily bar 2019-05-03,
   probe P8) cannot reach n_w=13 at all (n_w≈5–6 at best) — disqualified on power alone, independent
   of cost or access.
2. **ES/MES via free yfinance, intraday cadence:** the cited interval cap (≤60 days intraday) is
   orders of magnitude short of any usable n_w — disqualified on power alone.
3. **ES/MES via free yfinance, daily cadence (ES-proxy-for-MES):** clears n_w=13 on raw quantity,
   but carries an **unpriced continuous-contract-quality caveat** (characterised as an unadjusted
   front-month splice with no back-adjustment — assumed, not probed, §1.3) that a proper survey
   would have to resolve with an explicit, justified roll methodology (§1.3) before trusting the
   series — a real but resolvable gap, not a hard disqualifier, but strictly worse, for this
   survey's purposes, than Path B's daily series, which carries no continuous-contract construction
   question.
4. **ES/MES via paid vendors (Databento, FirstRateData), any cadence:** clears both power and
   continuous-contract quality, but requires spend this package is not authorized to make (non-goal:
   "no data downloads beyond ≤5-bar/one-page probe responses," no committed cost decision here).
5. **SPY-proxy, intraday cadence (either feed):** the best free option (SIP, back to 2016) reaches
   only n_w≈9 — short of the n_w=13 bar by 3–4 windows; IEX (back to 2020-07) is worse still
   (n_w≈5). Both are disqualified against the frozen comparability bar, even though the *path*
   (SPY-proxy) is otherwise the recommended one — it is specifically the **daily** cadence within
   that path that survives.
6. **SPY-proxy, daily cadence, sourced from Alpaca:** right path, right cadence, wrong provider —
   the 2016-01-04 floor (P1) caps it at n_w≈9, and Alpaca's documentation shows the floor is
   identical on the paid Algo Trader Plus tier, so it is not purchasable away. Demoted to the
   cross-check leg described above rather than dropped, because it is the series production actually
   trades on.

**This does not revise the frozen §2.5 wrapper or §4 bar.** §2.5 recommends MES-class futures as
the **live/paper trading instrument**, a question about broker access, leverage regime, and cost
structure for an eventual candidate that clears the bar. This document answers a different
question — which price-history feed powers the **survey's own backtest signal and power
calculation** — and nothing found here contradicts or strains the §2.5 rationale; if anything, using
SPY-proxy data to backtest a candidate destined for an MES-class wrapper is exactly the
"underlying alignment with the SPY-based promotion bar" §2.5 already argued for. **No committed-
revision flag is warranted.** The §2 proxy-error enumeration (session-hours gap, dividend-vs-basis
mismatch, ETF-vs-futures microstructure) must be carried into the eventual survey's own
pre-registration as an explicit, reported sensitivity risk — not silently assumed away — but it is
a caveat on the recommended path, not a finding that kills it.

---

## Appendix — probe transcript

All commands below were run with `CLAUDE_AGENT_NO_BROKER=1` set. The Alpaca probes (P1–P5) sourced
credentials from `.env.backfill` into shell environment variables, never printed; every response
shown is either ≤5 bars or a single non-paginated page, per the task's data-download cap, with
`sort=asc` and `adjustment` explicit throughout. The yfinance probes (P6–P8) use **no credentials at
all** and print only depth metadata, so they are re-runnable by any reviewer.

### P1 — history depth per (timeframe × feed)

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Min&feed=iex&start=2015-01-01T00:00:00Z&limit=5&adjustment=all&sort=asc" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ HTTP 200, first bar `t=2020-07-27T12:49:00Z` (redacted response; see §2.1 table for full
timeframe×feed matrix). Repeated for `timeframe ∈ {1Min,5Min,15Min,1Hour,1Day}` ×
`feed ∈ {iex,sip}` — all HTTP 200, no historical rejection observed.

Bisection of the iex floor (`start ∈ {2016-01-01, 2017-01-01, 2018-01-01, 2019-01-01,
2019-06-01}`, `timeframe=1Min&feed=iex`): every request returned the identical first bar
`t=2020-07-27T12:49:00Z` — confirming a hard floor, not an artifact of the 2015 start date.

### P2 — recency restriction

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Min&feed=sip&start=<now-5min>&limit=5&adjustment=all&sort=asc" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ HTTP 403: `{"message":"subscription does not permit querying recent SIP data"}`

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/trades/latest?feed=sip" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ HTTP 403, same message.

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/trades/latest?feed=iex" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ HTTP 200: `{"symbol":"SPY","trade":{"p":748.08,"t":"2026-07-21T16:13:13.966890832Z", ...}}`
(price/exchange fields redacted to the minimum needed to show freshness — no key material was ever
in this response).

### P3 — session coverage (2026-07-20, one trading day)

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=5Min&feed=<iex|sip>&start=2026-07-20T00:00:00Z&end=2026-07-21T00:00:00Z&limit=10000&adjustment=all&sort=asc" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ iex: 82 bars, first `12:00Z`, last `20:10Z`, `next_page_token=null`.
→ sip: **192 bars**, first `08:00Z`, last `23:55Z`, `next_page_token=null`.

### P4 — adjustment semantics (window spanning SPY's Dec-2025 ex-dividend date)

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Day&feed=sip&start=2025-12-15T00:00:00Z&end=2025-12-24T00:00:00Z&limit=10&adjustment=<raw|all>&sort=asc" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ `raw` closes: 680.73, 678.87, 671.40, 676.47, 680.59, 684.83, 687.96 (dates 2025-12-15 →
2025-12-23, trading days only).
→ `all` closes: 675.10, 673.26, 665.85, 670.88, 676.96, 681.18, 684.29 (same dates).
→ raw−all offset: 5.63, 5.61, 5.55, 5.59, **3.63**, 3.65, 3.67 — the step lands between
2025-12-18 and 2025-12-19.

### P5 — pagination sanity

```
curl -s "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Min&feed=iex&start=2020-07-27T00:00:00Z&limit=10000&adjustment=all&sort=asc" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
```
→ 10,000 bars, first `2020-07-27T12:49:00Z`, last `2020-09-01T18:13:00Z`, `next_page_token`
**present** (value not reproduced here — it is an opaque pagination cursor, not a secret, but
omitted as noise).

### P6/P7/P8 — yfinance daily depth (added 2026-07-24, fix round 1)

No credentials are involved, so unlike P1–P5 these three are reproducible by anyone with the repo's
Python dependencies. The script below was run from the session scratchpad (nothing committed) once
per symbol, with `CLAUDE_AGENT_NO_BROKER=1` set:

```python
from __future__ import annotations
import sys
import yfinance as yf

symbol = sys.argv[1]
df = yf.download(symbol, period="max", interval="1d", auto_adjust=True, progress=False)
print("symbol:", symbol)
print("rows:", len(df))
print("first:", df.index[0].date(), "last:", df.index[-1].date())
print(df.head(2).to_string())
```

`period="max", interval="1d", auto_adjust=True` mirrors `backtest/walkforward.py:41`
(`yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)`) with the date bounds
removed so the provider's own floor is what gets measured. Environment: `python3` 3.9, `yfinance`
1.2.0. Outputs verbatim (Yahoo warning lines stripped):

**P6 — `SPY`:**
```
symbol: SPY
rows: 8427
first: 1993-01-29 last: 2026-07-23
Price           Close       High        Low       Open   Volume
Ticker            SPY        SPY        SPY        SPY      SPY
Date
1993-01-29  24.113276  24.130426  24.010374  24.130426  1003200
1993-02-01  24.284773  24.284773  24.130421  24.130421   480500
```

**P7 — `ES=F`:**
```
symbol: ES=F
rows: 6525
first: 2000-09-18 last: 2026-07-23
Price        Close     High      Low     Open  Volume
Ticker        ES=F     ES=F     ES=F     ES=F    ES=F
Date
2000-09-18  1467.5  1489.75  1462.25  1485.25  104794
2000-09-19  1478.5  1482.75  1466.75  1467.00  103371
```

**P8 — `MES=F`:**
```
symbol: MES=F
rows: 1818
first: 2019-05-03 last: 2026-07-23
Price        Close    High      Low    Open  Volume
Ticker       MES=F   MES=F    MES=F   MES=F   MES=F
Date
2019-05-03  2947.5  2947.5  2947.50  2947.5  159243
2019-05-06  2932.5  2947.5  2883.75  2947.5  159243
```

**Scope of what these probes establish:** availability depth only — the earliest and latest daily bar
each symbol serves, and the row count between them. They say nothing about how the `ES=F`/`MES=F`
continuous series is spliced, which remains **assumed / not probed** (§1.1, §1.3).

### WebFetch citations (documentation only, no price data), accessed 2026-07-21 unless noted

- `https://en.wikipedia.org/wiki/E-mini_S%26P_500` — ES launch date (1997-09-09), $50 multiplier.
- `https://en.wikipedia.org/wiki/E-mini` — MES multiplier ($5, vs ES $50), citing CME.
- `https://optimusfutures.com/blog/micro-e-mini-futures/` — dated 2019-05-15, describes Micro
  E-mini equity-index futures as "newly launched" (corroborates ~May-2019 CME launch).
- `https://algotrading101.com/learn/yfinance-guide/` — yfinance interval-limit statement ("1m data
  is only retrievable for the last 7 days, and anything intraday ... only for the last 60 days").
- `https://databento.com/pricing` — GLBX.MDP3 "16+ years of available history," usage-based
  pricing, no subscription required for that tier.
- `https://firstratedata.com` — futures bars (1m/5m/30m/1h/1d) "starting back to 2007" for the most
  active 130 contracts (as of July 2026), naming ES explicitly.
- `https://www.quantstart.com/articles/Continuous-Futures-Contracts-for-Backtesting-Purposes/` —
  Panama (difference) vs proportional (ratio) back-adjustment methods; fixed-days-before-expiry
  roll convention (`rollover_days=5` default in the article's own implementation).
- `https://docs.alpaca.markets/docs/about-market-data-api` — **accessed 2026-07-24** (fix round 1).
  The tier-comparison table gives `Historical data timeframe: Since 2016` in **two** adjacent cells
  (Basic and Algo Trader Plus), i.e. the 2016 floor P1 measured is a provider-wide limit, not a
  free-tier gate. Reproduce with:
  `curl -sL -A "Mozilla/5.0" https://docs.alpaca.markets/docs/about-market-data-api | tr '<' '\n' | grep -i "Historical data timeframe" -A2`
- `https://firstratedata.com` — **quote re-verified 2026-07-24** (fix round 1): "We provide both
  individual futures contracts as well as a continuous futures series with prices adjusted for the
  price gaps from rolling contracts (this series is best suited to long timeframe backtesting of
  futures trading strategies)." Reproduce with:
  `curl -sL -A "Mozilla/5.0" https://firstratedata.com | tr '<' '\n' | grep -i "continuous futures series"`

### Fetch attempts that did not yield citable content (reported, not silently dropped)

- `cmegroup.com` (product-specs page, education page, 2019 press release URL) — timed out on every
  attempt, repeating the fetch-access gap already disclosed in
  `2026-07-13-forex-short-horizon-feasibility-gate.md` §4.3.
- `stooq.com` (`/db/`, `/db/h/`, `/help/?id=42`, `/q/d/?s=es.f`) — returned empty content to
  WebFetch on every attempt (likely JS-rendered pages); no depth/terms figure is reported for
  Stooq as a result. Treated as unverified, not as evidence against the source.
- `www.cqg.com/data/data-sources` — HTTP 404.
- Several secondary MES-launch-date candidates (Wikipedia "Micro E-mini futures"/"Micro E-mini",
  Investopedia, MarketWatch, Businesswire, IBKR guides, J.P. Morgan, Schwab, CFI) — 404, blocked,
  or timed out; not used as citations below the two that did resolve (Optimus Futures blog,
  Wikipedia "E-mini").

### Secret-hygiene self-check

Every value of `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` sourced from `.env.backfill` was checked
against every probe-transcript scratch file with `grep -qF`, in a loop that never echoes the value
itself; no match was found in any file. This document quotes no key material — only price/volume
fields, HTTP status codes, and error message bodies (the one error body quoted, "subscription does
not permit querying recent SIP data," contains no credential).
