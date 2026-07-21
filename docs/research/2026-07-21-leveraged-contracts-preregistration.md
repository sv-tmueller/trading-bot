# Pre-registration spec: leveraged-contracts (1% fixed-fractional risk) direction

**Issue:** #406 · **Batch:** #405, Package 5 · **Date:** 2026-07-21
**Author:** Analyst (research-only; no backtest run, no price history inspected, no broker account
opened, no production/TypeScript code touched)

> **STATUS: PRE-REGISTERED** — the merge SHA of the PR closing #406 is the pre-registration
> timestamp for **the promotion bar (§4)** and **the instrument-class recommendation (§2.5)**. Any
> later change to either requires a committed revision of this document, with rationale, before
> results computed under the changed configuration are examined (§7). The candidate signal-family
> **cells proposed in §3/§6 are not frozen by this document** — see the freeze-granularity split
> stated explicitly in §6: the exact cell grid is frozen by the later survey batch's own
> pre-registration, following the same feasibility-gate → grid-frozen-pre-reg → verdict staging this
> repo already used for the 4h EUR/USD work
> (`docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` →
> `docs/research/2026-07-13-forex-4h-strategy-preregistration.md` →
> `docs/research/2026-07-15-forex-4h-survey-verdict.md`).

---

## §0 Scope and the no-fabrication rule

This document does not run a backtest, does not fetch or inspect any price history, and does not
open a broker account. It reports no backtest result of any kind, for any instrument.

Every factual claim below is exactly one of three kinds, labeled at the point of use:

1. **A fact already documented in this repo, quoted or cited by reference** — to a `docs/research/`
   or `docs/decisions/` file, with a section/line anchor where the sub-plan for this issue specified
   one.
2. **General regulatory or tax knowledge already settled and citable independent of any repo
   research** — specifically ESMA/BaFin retail CFD leverage caps and the German Termingeschäft
   flat-tax treatment (§20 Abs. 2 Nr. 3 EStG, 26.375%), both of which this repo has already sourced
   with fetched URLs and dates in the cited docs, reused here by reference rather than re-fetched.
3. **Explicitly marked "to verify before survey"** — where an EU-retail broker capability or an
   exact leverage/margin/fee figure cannot be sourced from a repo doc or from settled regulatory
   rule, it is marked this way rather than asserted. No margin, fee, or broker-capability number in
   this document is invented; every such number is either repo-cited or flagged as unverified.

This document performs **no web research of its own**. It does not fetch a single new URL. Every
citation below points at a `docs/research/` or `docs/decisions/` file already committed to this
repo (or landing in this same batch, see the colleague-audit citation below), plus the two pieces of
settled regulatory knowledge named above.

---

## §1 The operator's direction, restated

The operator's stated direction — "contracts with 1% fixed-fractional risk per trade" run on
"smaller trading windows" — is treated here as a **candidate that could eventually replace** the
live 3x-UPRO / 200-DMA regime bot, not as an instruction to build it now. Batch #405's own decision
log states the standing constraint verbatim:

> "**UPRO fate:** the live UPRO regime bot keeps running unchanged; deprecation happens only when a
> contracts strategy clears the pre-registered bar (#398 gate + after-tax Calmar vs SPY). No exit to
> cash now."

**This document authorizes nothing live.** The UPRO bot is unchanged until a candidate clears the
bar this document pre-registers (§4). This restates, and does not weaken, CLAUDE.md's Architectural
invariant #1 ("one decision rule") — see §7 for the full reaffirmation.

The incumbent-vs-alternative reasoning that keeps the 200-DMA signal live today is recorded in
`docs/decisions/2026-07-06-keep-200dma-regime-signal.md`: three research passes (a broad archetype
survey, a vol-targeting second cut, and a leveraged-regime-signal study) found no candidate clearing
the after-tax-Calmar-vs-SPY bar at a drawdown the operator tolerates, and the ADR explicitly holds
the 3x UPRO bot as "an absolute-return bet, not a risk-adjusted edge over SPY." The contracts
direction pre-registered here is a **different kind of candidate** — a short-horizon,
fixed-fractional-risk approach on a leveraged instrument, rather than a better regime signal on 3x
SPY — but it is subject to the same standing bar (§4) and the same non-negotiable consequence: a
survivor is evidence for a fresh ADR, never an automatic live change (§4, §7).

---

## §2 Instrument-class comparison

Three EU-reachable leveraged-instrument classes are compared for an EU-based retail operator:
exchange-traded equity/index options, CFDs, and micro index futures. Each sub-section states
broker access from the current stack, the cost model, and the applicable regulatory leverage
regime; §2.4 tabulates the ESMA leverage caps; §2.5 gives one recommendation.

### §2.1 Exchange-traded equity/index options

**Broker access from our stack.** Alpaca is the only broker integrated into this repo today
(`supabase/functions/_shared/alpaca.ts`). Alpaca's US-listed options are commission-free — this is
the "commission-free" framing that, per
`docs/research/alpaca-eu-expansion.md` (line 54), "explicitly applies to 'U.S.-listed securities and
options' only." Alpaca's 2026-04-21 EU launch is **Broker-API-only**, with no confirmed self-directed
EU-retail Trading API: `alpaca-eu-expansion.md` §"API surface" (lines 88–98) states there is no new
SDK package, no new EU base URL, and no new `DataFeed`/exchange enum as of the 2026-04-29 SDK
release; the same doc (lines 106–118) states plainly "we cannot... Open a self-directed Alpaca Europe
account and connect our existing API keys to it. The launch announcement does not describe such a
flow." **A German-resident operator therefore cannot reach even Alpaca's own commission-free US
options via a self-directed EU account today** — either a US-domiciled account (tax/residency
implications not analyzed here) or a different, EU-facing options broker would be required. Marked
**to verify before survey**: whether a German resident can hold a self-directed US-domiciled Alpaca
account at all, and if not, which EU-retail broker offers comparable index-options access.

**Cost model.** Long options (the only shape consistent with defined risk per trade) cap the
per-trade loss at the premium paid — the position cannot lose more than what was paid to open it,
which is structurally aligned with a fixed-fractional-risk framing (§5). Beyond premium, the
dominant cost is the bid/ask spread, which — per
`docs/research/mvp2-alpaca-options-data-spike.md` — is **not observable for free**: the TL;DR states
"Bid/ask QUOTES are OPRA-gated" and the `quotes` endpoint returns "HTTP 404... on the free tier for
every window tested," with real NBBO bid/ask requiring the $99/mo Algo Trader Plus (OPRA) tier (per
the doc's "Bottom line": "the spread — the dominant cost in a credit spread — must be *modeled*
regardless of source"). Written options (naked or covered) carry margin requirements distinct from
premium-limited long options; this document does not price a written-options cost model at all —
the fixed-fractional-risk framing in §5 is naturally long-options-only, so no such model is needed
for this candidate's shape. **Options data floor: ~2024-01-18** per the spike doc's TL;DR ("Real
options-data floor ≈ 2024-01-18... Real-data backtest window ≈ 2.4 years — statistically thin"),
which caps any eventual empirical survey's real-fill sample size, independent of broker access.

**Leverage / regulatory regime.** ESMA's retail CFD leverage caps (§2.4) do **not** apply to
exchange-traded options — options are premium-limited on the long side (max loss = premium paid) and
margin-governed on the short side under exchange/clearinghouse rules, a different regime entirely
from the CFD notional-leverage caps. Marked **to verify before survey**: the exact EU-retail
options-access venue (a Eurex-facing German/EU broker vs a US-options broker somehow reachable by an
EU resident) and its per-contract commission/fee schedule — neither is sourced in this repo.

**German tax.** Cash-settled leveraged options are a Termingeschäft under §20 Abs. 2 Nr. 3 EStG,
taxed at the flat 26.375% Abgeltungsteuer rate, per
`docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §7 (lines 292–341), which
tabulates "Certificates / knock-outs (Trade Republic)" and by direct extension any cash-settled
Termingeschäft-classified options position under the same regime, and confirms the loss-offset cap
(previously €20,000/yr) was repealed outright by the JStG 2024, effective 2024-12-06. The same §7
flags the historically most-contested edge case for this instrument class: "total worthless-expiry
loss historically the most contested case" — relevant to a long-options strategy, where a position
expiring worthless is the modal losing-trade outcome, not an edge case.

### §2.2 CFDs (colleague-style, cTrader/Pepperstone/XTB)

**Broker access from our stack.** Not on the Alpaca stack at all — CFDs require a new,
MiFID-regulated CFD broker integration (e.g. XTB, IC Markets, Pepperstone). Per
`docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §8 (lines 349–350), IC Markets is
automatable via "cTrader Open API / FIX API, MT4/5 EAs" and is "EU-facing entity, MiFID-reachable";
XTB "has an xStation platform with algo/API access in its retail offering" (same §8, same table
row), though that access was "not separately re-verified this session beyond the fee citation."

**Cost model.** Sourced round-trip costs, base-to-pessimistic: XTB CFD **0.79–1.75 bp** and IC
Markets ECN **1.04–2.35 bp**, per the same doc's §4.1–4.2 (lines 100–127). Overnight financing (swap)
applies to any position held past the daily rollover: XTB's EUR/USD swap proxy is quoted at line 121
as "long −$4.525/day, short −$1.032/day per 100k-EUR lot" — this drag is a structural feature of the
CFD wrapper for any multi-day hold, not merely a sensitivity input.

**Leverage / regulatory regime.** CFDs are squarely inside ESMA's retail leverage caps (§2.4) — 30:1
on FX majors, 20:1 on major equity indices, 5:1 on individual equities, etc. This is the binding
constraint on CFD position sizing for a retail account, separate from any broker-offered margin
schedule.

**German tax.** Termingeschäft, §20 Abs. 2 Nr. 3 EStG, same 26.375% flat rate, same repealed
loss-offset cap — `2026-07-13-forex-short-horizon-feasibility-gate.md` §7 (lines 292–341), which
names CFDs explicitly in its instrument table.

### §2.3 Micro index futures (e.g. MES / 6E / M6E)

**Broker access from our stack.** Not on the Alpaca stack — futures require IBKR (TWS/Client Portal
API), a new integration. Per the feasibility-gate doc §8 (line 351), "CME 6E/M6E via IBKR" is
automatable: "IBKR TWS/Client Portal API is a real, documented, automatable API." The same doc's §4.3
notes IBKR's own pricing pages "returned HTTP 403 to automated fetch during this session — a
fetch-access limitation, not a claim about IBKR's actual pricing," and its API's "existence and
general reachability from Germany is well-established and not in dispute here." A parallel
fetch-access limitation applies to CME's own site (§4.3, "CME's own site (`cmegroup.com`) timed out
on every fetch attempt") — the contract-spec figures below for 6E/M6E are cross-sourced from
secondary sites, not CME's own pages, per that doc's own disclosure.

**Cost model.** Sourced round-trip costs: 6E **0.56–1.00 bp**, M6E **1.23–2.10 bp**, per
`2026-07-13-forex-short-horizon-feasibility-gate.md` §4.3 (lines 129–145). The counter-intuitive
finding stated there (line 143): the *micro* contract's proportional cost is *higher* than the
standard contract's, "because the flat per-contract commission and tick value don't scale down 10x
as fast as the notional does." A structural cost advantage over CFDs applies regardless of size: **no
daily rollover/overnight-financing charge** — §5 of the same doc (lines 187–188) states "futures rows
have no daily rollover charge (a genuine structural advantage of the futures wrapper, not modeled
away)."

**Leverage / regulatory regime.** Exchange-traded futures are governed by **exchange/SPAN margin,
not ESMA's retail CFD leverage caps** — this is a load-bearing distinction, not a footnote: a
retail account trading 6E/M6E futures is not subject to the 20:1/30:1 notional caps in §2.4 at all,
because those caps are a CFD-specific ESMA product-intervention rule, not a general retail-leverage
ceiling. **MES (Micro E-mini S&P 500)** is not priced anywhere in the cited feasibility-gate doc (its
sweep covers FX-major futures — 6E/M6E — not equity-index futures), but it keeps the underlying
instrument comparable to the SPY-based after-tax-Calmar bar this document freezes in §4; this
alignment is a design point noted here, not a sourced cost figure. Marked **to verify before
survey**: MES's exact contract multiplier and margin requirement, and whether IBKR extends EU-retail
futures access on the same terms the feasibility-gate doc found for 6E/M6E (the same doc's
403-blocked-pricing-page caveat applies equally to any equity-index-futures pricing).

**German tax.** Termingeschäft, §20 Abs. 2 Nr. 3 EStG, same 26.375% flat rate, same repealed
loss-offset cap — `2026-07-13-forex-short-horizon-feasibility-gate.md` §7 (lines 292–341), which
names futures explicitly ("Futures (6E/M6E)") in its instrument table.

### §2.4 ESMA leverage-cap table

General regulatory knowledge, applicable specifically to **CFDs**, **not** to exchange-traded
futures or options (§2.1, §2.3):

| Underlying | Max retail leverage | Min margin |
|---|---|---|
| Major FX pairs | 30:1 | 3.33% |
| Non-major FX pairs, gold, major equity indices | 20:1 | 5% |
| Other commodities, non-major equity indices | 10:1 | 10% |
| Individual equities, other reference values | 5:1 | 20% |
| Cryptocurrencies | 2:1 | 50% |

The major-FX-pairs figure is already anchored in this repo:
`2026-07-13-forex-short-horizon-feasibility-gate.md` §1 sources "ESMA/BaFin retail leverage cap,
major FX pairs" at "**30:1** (3.33% initial margin)" from the BaFin Allgemeinverfügung of 2019-08-01,
and §9 (line 401) restates "ESMA/BaFin's 30:1 leverage cap on *notional*" as the binding constraint
for that instrument class (contrasted there with the PDT rule, which does not apply to forex). The
remaining tiers above (20:1/10:1/5:1/2:1) are the general ESMA product-intervention schedule and are
**not** independently re-sourced with a fetched URL in this document — they are stated as settled
regulatory knowledge per §0's category 2, and per-tier margin precision plus any national
(BaFin-level) post-2018 tightening beyond the 30:1 FX-major figure this repo has already sourced are
marked **to verify before survey**.

### §2.5 Recommendation (one class)

**Micro index futures (MES-class) are recommended as the instrument wrapper**, based on the sourced
facts above:

- **Cheapest proportional cost among the automatable venues actually priced in this repo** — 6E
  futures at 0.56–1.00 bp round-trip beats XTB CFD (0.79–1.75 bp) and IC Markets ECN (1.04–2.35 bp)
  at both base and pessimistic cost (§2.2, §2.3).
- **No overnight-financing drag** — a structural advantage over CFDs for any hold longer than a
  single session (§2.3), which matters for a "smaller trading windows" candidate that is still
  likely to hold across at least one session rather than scalp intraday (the intraday shape is
  itself already killed — see §3).
- **No ESMA CFD leverage cap** — exchange/SPAN margin governs futures instead (§2.3, §2.4), removing
  the 20:1-on-major-equity-indices ceiling that would otherwise bind an index-futures-shaped CFD
  position.
- **A real, automatable, EU-reachable API** — IBKR's TWS/Client Portal API, per
  `2026-07-13-forex-short-horizon-feasibility-gate.md` §8, is confirmed reachable and documented,
  unlike the confirmed dead ends in that same table (Trade Republic: no spot FX, no official API;
  trader.dev/tradingkit.com: confirmed LLM-based, out of invariant bounds regardless of cost).
- **Underlying alignment with the SPY-based promotion bar** (§4) — an S&P-500-tracking micro future
  (MES) keeps the eventual candidate's benchmark comparison as close as possible to the existing
  after-tax-Calmar-vs-SPY bar, rather than introducing a currency-pair benchmark mismatch the way 6E
  would.

**Options are the defined-risk runner-up**: the premium-caps-max-loss property is attractive for a
fixed-fractional-risk framing, but the in-repo evidence is thinner and less favorable — no confirmed
EU-retail self-directed access path even to Alpaca's own commission-free US options (§2.1), a spread
that must be modeled rather than observed on free data (§2.1), and a real-data floor of only ~2.4
years (§2.1). **CFDs are disfavored**: overnight-financing drag on any multi-day hold, ESMA leverage
caps that do not apply to the futures alternative, and CFDs are not reachable from the current
Alpaca-only stack any more than futures are, so the "no new broker integration" argument does not
favor CFDs over futures. This recommendation follows the sourced cost/leverage/API facts above, not
an a priori preference for futures.

---

## §3 Candidate signal families + dead-cell registry

### Dead-cell registry (lead with the killed evidence)

| Killed evidence | Source doc + anchor | Key figures |
|---|---|---|
| 4h EUR/USD 33-cell **class kill** (trend, momentum, mean-reversion families) | `docs/research/2026-07-15-forex-4h-survey-verdict.md` — Status line, §6 (line 169), §8 (lines 269–284) | Best cell median after-tax Calmar **0.337** vs SPY **1.309**; 0/33 survivors; families T (trend), M (momentum), R (mean-reversion) each dead |
| The frozen 33-cell grid (the exact killed shapes) | `docs/research/2026-07-13-forex-4h-strategy-preregistration.md` §3 (lines 106–190), §4 (lines 194–219), freeze SHA `e409bf8` | Trend: MA-cross (5/20, 20/50, 50/200), Donchian (20, 55); Momentum: ROC (12/24/48); Mean-reversion: RSI(14) 30/70, RSI(2) 10/90, Bollinger(20,2); × R ∈ {20, 30, 50} bp |
| Colleague **intraday / London-ORB kill** | `docs/research/2026-07-20-colleague-repo-audit.md` §2 "Forexbot" + §3 table row 1 (lands via PR #409, batch #405) | "every London-Open-Range-Breakout variant he tried lost... 'Intraday-Frage endgültig geschlossen'" |
| Our own **intraday cost-wall kills** | `docs/research/2026-06-23-scalping-cost-wall-demonstration.md`; `docs/research/2026-06-23-short-horizon-feasibility-gate.md` §(c) | Empirical BTC cost-wall demonstration; §(c) "Go/no-go on the high-churn end" — gate failed at cost alone for the equity/crypto high-churn case |
| **Multi-signal voting kill** | `docs/research/2026-07-20-colleague-repo-audit.md` §2 "KryptoBot" + §3 table row 4 (PR #409) | Profit factor **0.28–0.83** after costs on every variant, locked to research-only; structurally the same architecture as the pre-pivot v1.14 bot (`docs/decisions/2026-07-06-keep-200dma-regime-signal.md` for our own incumbent-vs-multi-signal reasoning) |
| **SL/TP overlay rejection** | `docs/research/2026-07-20-colleague-repo-audit.md` §2 "Forexbot" + §3 table row 6 (PR #409) | **11 variants tested over 16.5 years, all rejected**; our own survey used state-based no-TP/SL baselines instead (`2026-07-15-forex-4h-survey-verdict.md` §7) |
| Daily FX **carry** / **regime** (killed on his own gates) | `docs/research/2026-07-20-colleague-repo-audit.md` §2/§3 (PR #409) | Carry: deflated Sharpe **0.664** < his own **≥0.95** promotion gate. Regime (ADX gate → momentum/mean-reversion): full-history Sharpe **−0.25** |
| 4h **Donchian** breakout (KryptoBot V3) — same shape as our killed T2 | `docs/research/2026-07-20-colleague-repo-audit.md` §3 table row 5 (PR #409) | In-sample/undeflated profit factor **1.355 → 1.282** across fill models, never promoted, EUR 0 capital deployed |

**Note on provenance:** the colleague-audit rows above cite `docs/research/2026-07-20-colleague-repo-audit.md`, which lands via PR #409, part of this same batch (#405); it is fetched and read from branch `docs/395-colleague-repo-audit` for this citation. No colleague code is reproduced anywhere in this document, and no operational identifier (server IP, hostname, account number) from his repos appears here — this document only transcribes the sanitized figures already present in that landed doc.

### Genuinely untested space

The dead-cell registry above kills every trend/MA-cross, Donchian-breakout, ROC/TSMOM, RSI,
Bollinger, London-ORB, multi-signal-voting, and SL/TP-overlay shape it covers, **as shapes** —
independent of the instrument (EUR/USD, BTC) each was originally tested on. Because §2.5 recommends
an S&P-500-tracking wrapper (MES), any proposed family for this direction must be checked against
those killed shapes regardless of the fact that they were killed on a different underlying.

What remains genuinely untested by any evidence in the registry: **options-structure-specific
families** — defined-risk vertical or calendar spreads priced on implied volatility and term
structure, rather than a raw price-direction signal. These have no analog anywhere in the killed
33-cell trend/momentum/mean-reversion survey (which tests direction-only signals, not
volatility-surface structure) and no analog in the colleague's rule set (which is exclusively
direction-following: carry, ADX-gated momentum/mean-reversion, Donchian breakout). This is a genuine
gap, not a re-proposal of anything the registry kills.

However, §2.5 recommends **futures**, not options, as the wrapper — so an options-structure family
is not a live proposal for the eventual survey unless a future revision of this document's §2
recommendation changes. On the recommended MES wrapper, the only signal shapes with **any**
plausible novelty relative to the registry are (a) parameter regions of the killed shapes not yet
swept — e.g. shorter/longer lookbacks than the 4h EUR/USD grid tested, since the killed grid's
lookbacks were chosen for a 4h forex bar, not an equity-index futures bar at a different cadence —
and (b) genuinely different shapes not represented in either kill list, such as volatility-regime
gating (distinct from the already-killed ADX-gated *direction* families) or cross-sectional/relative
value between MES and a slower-moving reference. **This document proposes, but does not freeze,
either direction** — the freeze-granularity split in §6 governs which document eventually pins the
exact cell grid.

---

## §4 The pre-registered promotion bar (frozen now)

Two components, both stated before any result exists for this direction:

**Component 1 — the #398 mechanical overfitting gate.** GitHub issue #398 (this same batch)
specifies a clean-room, literature-derived module: deflated Sharpe ratio (Bailey & López de Prado),
probability of backtest overfitting (PBO) via combinatorially symmetric cross-validation (CSCV), and
moving-block-bootstrap confidence intervals on walk-forward window uplifts, with a pure-noise
self-test requiring random-walk strategies to fail the gate. **This document cites #398 as the bar
and does not import or depend on its code** — #398 is being built in this same batch, independently
of this pre-registration. The colleague independently converged on the same DSR/PBO-with-noise-self-test
pattern in his own private research tooling, per
`docs/research/2026-07-20-colleague-repo-audit.md` §5's "Adopt" list: "**DSR/PBO overfitting gate**
(→ Package 4, #398) — his gatekeeper-with-noise-self-test pattern... is the strongest
research-methodology idea surfaced in this audit."

**Component 2 — after-tax Calmar vs SPY buy-and-hold.** The exact bar, frozen now: SPY buy-and-hold's
median-window after-tax Calmar ratio (German `annual_netting` tax mode, n = 13 scored windows,
2013–2025) is

> **1.3085475049604838**

sourced verbatim from `docs/research/2026-07-15-forex-4h-survey-verdict.md` §6, line 169 / Table
6.1 (that doc's own reporting-only recomputation from a fresh `yfinance` fetch reproduced the median
to 1.3085323112253744, a ~1.2e-5 relative difference attributed to routine `auto_adjust` micro-revisions
between fetches, not a data-quality concern — the value frozen here is the one the survey actually
computed and used as its bar). This figure is inherited from #255 and the
`docs/decisions/2026-07-06-keep-200dma-regime-signal.md` ADR, which set the standing "beat SPY on
after-tax Calmar, at a tolerable drawdown, on a walk-forward backtest" requirement for any candidate
to the live bot. The **~1.31** shorthand is used elsewhere in this document for brevity; the exact
figure above is the one an eventual survey's cells are compared against.

**Multiplicity discipline, carried over verbatim in intent from the 4h EUR/USD pre-registration**
(`docs/research/2026-07-13-forex-4h-strategy-preregistration.md` §6 lines 348–354, §8 lines
381–384): any eventual survey must judge candidates on **both** the median-window statistic **and**
the worst-window statistic (never on a best-cell basis), report every cell including failures, and
require a survivor to clear the bar on median while staying positive on its worst window.

**No second live rule / fresh ADR.** A survivor under any eventual survey following this bar does
**not**, by itself, authorize a live change. This reaffirms CLAUDE.md Architectural invariant #1
("one decision rule"): a survivor becomes, at most, a candidate for a fresh ADR — decided after
results exist, weighing drawdown and stability the way the 2026-07-06 ADR already did for the
regime-signal question — never an automatic replacement of the live bot. See §7 for the full
invariant reaffirmation.

---

## §5 Position sizing

The mechanics of 1% fixed-fractional risk per trade:

```
risk_budget   = 0.01 × equity
contracts     = floor( risk_budget / (stop_distance × contract_multiplier) )
```

Leverage or margin mechanics (futures/CFD) versus premium (long options) change only the **capital
tied up** to hold the position — the margin or premium required — not the **per-trade loss cap**,
which the fixed-fractional formula above already sets independent of instrument wrapper. A futures
position sized this way risks the same dollar amount per trade as an option position sized this way,
even though the futures position ties up SPAN margin and the option position ties up the full
premium.

**The load-bearing statement, stated explicitly:** **fixed-fractional sizing caps loss-per-trade and
governs the geometric growth/drawdown path, but does not create expectancy.** Expectancy is

```
expectancy = win_rate × avg_win − loss_rate × avg_loss
```

a property of the **signal and the cost model alone** — it does not depend on position size.
Kelly-style or fixed-fractional sizing scales a signal that already has *positive* expectancy; on a
signal with zero or negative expectancy after costs, sizing only controls the **rate of ruin**, not
whether ruin is the eventual outcome. This is precisely the failure mode the dead-cell registry (§3)
already demonstrates on real evidence: no amount of position-sizing discipline rescues a signal that
has no edge after costs. `docs/research/2026-06-23-scalping-cost-wall-demonstration.md` shows this
empirically on real BTC data (costs-off-vs-on delta the whole finding), and
`docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §9 (lines 406–415) states the
principle directly: "clearing the cost gate is necessary, not sufficient" — a signal that survives
the cost floor still has to demonstrate expectancy on its own; sizing plays no part in that
demonstration.

---

## §6 Go/no-go recommendation

**Recommendation: dispatch a follow-up survey batch, contingent on (a) the #398 gate landing (this
same batch, Package 4) and (b) this document's §2.5 wrapper recommendation (MES-class micro index
futures) standing at the time the survey batch is scoped.**

Sketch of what the survey's cells **would** be, drawn from §3's proposed (not frozen) families
crossed with the §2.5-recommended instrument: the genuinely-untested parameter regions of the
already-killed shapes re-parameterized for a futures-appropriate cadence (not a re-run of any killed
(family, shape, R) cell), plus any volatility-regime-gating or cross-sectional shape that survives a
dead-cell check at design time. This is a sketch for scoping purposes only, not a commitment.

**The freeze-granularity split, stated explicitly.** This document freezes **two** things now: the
promotion bar (§4 — the #398 gate plus the exact SPY after-tax-Calmar figure) and the instrument-class
recommendation (§2.5 — micro index futures). It does **not** freeze the exact candidate cell grid —
that grid belongs to the later survey batch's own pre-registration document, following the same
staging this repo already used for forex: a feasibility gate first
(`2026-07-13-forex-short-horizon-feasibility-gate.md`), then a grid-frozen pre-registration
(`2026-07-13-forex-4h-strategy-preregistration.md`), then the verdict
(`2026-07-15-forex-4h-survey-verdict.md`). This is not an oversight — pinning the exact grid here,
before the #398 gate module exists and before a data source for MES-class futures history has even
been identified, would risk freezing parameters that turn out to be infeasible against whatever data
source the survey batch ends up using, the same methodology error the forex precedent avoided by
staging its own freeze in two steps.

**Recommend paper-first**, exactly as the forex staging did (`2026-07-13-forex-4h-strategy-preregistration.md`
§6, "No second live rule") and as §4's multiplicity discipline requires: any eventual survivor is
evidence for a fresh ADR weighing paper-trading results, not an instruction to change the live bot.

---

## §7 Freeze clause + non-goals + invariant reaffirmation

### What is frozen by this document's merge SHA

- **The promotion bar (§4):** the #398 mechanical gate (cited by issue number, not by code
  dependency) and the exact SPY median after-tax Calmar figure, **1.3085475049604838**.
- **The instrument-class recommendation (§2.5):** micro index futures (MES-class).

Any later change to either requires a revision of this document, committed with rationale, before
results computed under the changed configuration are examined. Results already computed under a
superseded revision must still be reported alongside the revised results, not discarded.

**Not frozen:** the candidate signal-family cells proposed in §3/§6 — see the freeze-granularity
split in §6. The later survey batch's own pre-registration freezes the exact cell grid, under its
own freeze SHA, before any result from that survey exists.

### Non-goals (verbatim from issue #406)

- No backtest runs — this package only pre-registers what a survey would test.
- No broker account opened, no broker API integration.
- No changes to the live strategy, its parameters, or any production code.
- No copied code or operational identifiers from the colleague's repos.

### Invariant reaffirmation

**Invariant #1 — one decision rule.** This document authorizes nothing live. The live bot trades on
exactly one signal (SPY close vs SPY 200-DMA, modulated by the kill-switch flag,
`computeTargetState` in `supabase/functions/_shared/regime.ts`) and continues to do so unchanged.
Nothing in §2 through §6 above is a second decision rule in production — it is a pre-registration
for research that, if it ever produces a survivor, becomes a candidate for a fresh ADR, decided after
paper-trading results exist, exactly as batch #405's own decision log states ("deprecation happens
only when a contracts strategy clears the pre-registered bar... No exit to cash now").

**Invariant #2 — no LLM in the trading path.** Every candidate family this document proposes or
could propose is a deterministic pure function of price/cost history, the same "enter or decline"
shape the live bot already uses and the forex pre-registration (`2026-07-13-forex-4h-strategy-preregistration.md`
§2) already formalized. This document explicitly excludes any LLM-driven execution product from
consideration: `2026-07-13-forex-short-horizon-feasibility-gate.md` §8 already ruled out
`trader.dev` and `tradingkit.com` on exactly this ground — both are "confirmed AI/LLM-based" by their
own site copy ("Connect to Claude," "the best LLMs compete") and are "squarely out of invariant
bounds... on the decision-logic axis, not merely on the cost/venue axis." No candidate family
proposed anywhere in this document, present or future, may cross that line without a fresh brainstorm
and design spec, per CLAUDE.md's Architectural invariants section, which remains the single
authoritative home of this repo's safety contract.
