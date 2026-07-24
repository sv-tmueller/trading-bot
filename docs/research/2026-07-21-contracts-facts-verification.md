# Contracts direction: verifying the pre-registration's "to verify before survey" facts

**Issue:** #415 · **Batch:** #413 · **Date:** 2026-07-21
**Cross-ref:** verifies six markers in the frozen `docs/research/2026-07-21-leveraged-contracts-preregistration.md`
(merged via PR #411). That document is **not edited by this one** — this note only resolves its
own explicitly-flagged "to verify before survey" markers, or records them honestly as still
unverified, per its own §7 revision clause.
**Author:** Analyst (web-research verification only; no backtest run, no broker account opened, no
price history inspected, no production code touched).

---

## §0 Method + no-fabrication rule

Every numeric or factual claim below is exactly one of two kinds:

1. **Verified** — a primary source (CME Group, IBKR/Interactive Brokers, EUR-Lex, bafin.de, Alpaca's
   own docs) was successfully fetched. The claim carries the value, the source URL, the access date,
   and — where the exact wording is load-bearing — a short quote. Access dates: **2026-07-21** for
   the original pass; fetches added or re-run in **fix round 1** carry **2026-07-24** and are marked
   as such inline.
2. **Still unverified** — every URL attempted is listed with its failure mode (HTTP 403 / timeout /
   HTTP 202-empty JS-challenge shell / 404 / rate-limited search / geo-gate / paywall / login-wall).
   No such item is filled from model memory, blogs, or broker-comparison sites. Where a secondary
   source (a blog, a comparison site, or a broker page that is not the specific entity in question)
   surfaced a lead, it is labeled explicitly **"secondary indication — not verification."**

WebSearch-style discovery (DuckDuckGo/Bing HTML result pages) was used **only** to locate candidate
primary URLs, never as a citation for a fact. Where a search engine itself was rate-limited or
returned no usable organic links, that is logged as part of the relevant item's attempt log, not
silently dropped.

This note performs genuinely new web research — it fetches URLs the frozen pre-registration
explicitly declined to fetch (§0 of that document: "This document performs no web research of its
own").

---

## §1 Marker map

All six `grep -n -i "verify"` hits in the frozen pre-registration, per the architect's SUB_PLAN, and
where each is resolved below:

| Frozen-doc anchor | Marker content | Group | Resolved in |
|---|---|---|---|
| Line 35, §0 | Definitional — declares the "to verify before survey" label category itself. No fact to verify. | — | **Definition, no action** — confirmed by reading §0 of the frozen doc; it is a category label, not a claim. |
| Lines 94–96, §2.1 | Whether a German resident can hold a self-directed US-domiciled Alpaca account; if not, which EU-retail broker offers comparable index-options access. | Group 3 | §4.1–§4.2 — **both halves still unverified**: whether a German resident can hold a self-directed US Alpaca account is still unverified (§4.1 — the primary was reached but declines to answer), and the comparable-index-options-access half is the exact claim **withdrawn in fix round 1** (§4.2 resolves only the fee-schedule half; the access half remains unverified). |
| Lines 119–121, §2.1 | The exact EU-retail options-access venue and its per-contract commission/fee schedule. | Group 3 | **Resolved on the fee-schedule half only** — §4.2 (venue named, per-contract commission + OCC fee + Cboe SPX/SPXW exchange fees verified at the entity from §3.1). The access half — that a German retail client of that entity is actually granted US index-option permissions — is **still unverified**, together with the PRIIPs/KID question in §4.3. |
| Lines 185–188, §2.3 | MES's exact contract multiplier and margin requirement; whether IBKR extends EU-retail futures access on the same terms found for 6E/M6E. | Groups 1 + 2 | §2 (spec/margin), §3 (IBKR access) |
| Lines 213–216, §2.4 | Per-tier margin precision for the ESMA 20:1/10:1/5:1/2:1 tiers; any national BaFin-level post-2018 tightening. | Group 4 | §5 |
| Line 242, §2.5 | MES's own per-trip cost is unpriced in this repo. | Group 1 | §2.3 |

---

## §2 Group 1 — MES contract spec, margin, per-trip cost

### §2.1 CME Group primary sources — blocked

Every attempt against `cmegroup.com` was blocked at the network layer, not merely slow:

| URL | Method | Result |
|---|---|---|
| `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.contractSpecs.html` | WebFetch | Timeout (60s) |
| `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.contractSpecs.html` | curl | HTTP 403 |
| `https://www.cmegroup.com` | curl | HTTP 403 |
| `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.html` | curl | HTTP 403 |
| `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.contract_specifications.html` | curl | HTTP 403 |
| `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.margins.html` | curl | HTTP 403 |
| `https://www.cmegroup.com/clearing/margins/outright-vol-scans.html` | curl | HTTP 403 |
| `https://www.cmegroup.com/trading/equity-index/files/cme-micro-e-mini-futures-fact-card.pdf` | curl | HTTP 403, body is a JSON block message |
| `https://www.cmegroup.com/CmeWS/mvc/ProductSlate/V2/Detail/440/G` | curl | HTTP 403 |

The fact-card PDF fetch returned an explicit anti-scraping response body (not an empty page — a
named block), quoted here as it is itself informative about the failure mode:

> "This IP address is blocked due to suspected web scraping activity associated with it on this
> CMEgroup.com page. Use of scripts, software, spiders, robots, avatars, agents, tools or other
> scraping mechanisms is strictly prohibited by CME Group's website Data Terms of Use..."

This extends the repo's existing precedent (`2026-07-13-forex-short-horizon-feasibility-gate.md` §4.3:
cmegroup.com "timed out on every fetch attempt") from a timeout to an explicit, named IP block —
the same underlying fact (CME's own site is not fetch-accessible to this research process), stated
more precisely this session.

**Verdict — MES contract multiplier / tick size / tick value: still unverified from CME primary.**
**Verdict — MES exchange margin requirement: still unverified from CME primary.**

### §2.2 IBKR as fallback (per sub-plan §(b) Group 1, item 3) — margin also blocked, commission succeeded

Per the sub-plan's allowance, IBKR's own contract-spec/margin pages were tried as broker-authoritative
fallback:

| URL | Result |
|---|---|
| `https://www.interactivebrokers.com/en/index.php?f=marginnew&p=fut` | HTTP 200, but the page body is a pure JS-driven margin-lookup widget (`FP_PAGE_ID`, AJAX search calls) with **no static MES figure in the fetched HTML** — an empty-JS-shell failure, not a block |
| `https://www.interactivebrokers.com/en/index.php?f=2222&exch=cme&showcategories=FUTGRP` | HTTP 200, same JS-shell shape (contract search requires client-side AJAX) |
| `https://www.interactivebrokers.com/en/trading/products-futures.php` | HTTP 200, same JS-shell shape |
| `https://www.interactivebrokers.com/webrest/search/products-by-filters?filter=...MES...` | HTTP 403 ("Error 403 - Access Denied") |
| `https://www.interactivebrokers.com/webrest/search/products-by-filters?symbol=MES` | HTTP 500 |

**Verdict — MES margin requirement via IBKR: also still unverified** (JS shell / API 403+500, honestly
distinct from CME's outright block).

The IBKR **commission** and **exchange-fee pass-through** pages, by contrast, are server-rendered and
did resolve.

**Entity note (fix round 1).** §3.1 establishes that a German retail resident contracts with
**Interactive Brokers Ireland Limited**, so every cost figure below is now cited from that entity's
own `interactivebrokers.ie` pricing pages rather than the `interactivebrokers.com` (IB LLC) pages
used in the first pass. Both were fetched; the figures are identical, so this is a provenance
correction, not a value correction.

- **IBKR Ireland MES commission (≤1,000 contracts/month tier): USD 0.25/contract, on both the
  Tiered and the Fixed schedule.**
  Source: [interactivebrokers.ie/en/pricing/commissions-futures.php](https://www.interactivebrokers.ie/en/pricing/commissions-futures.php)
  (page title: "Commissions Futures | Interactive Brokers Ireland"), fetched 2026-07-24, HTTP 200,
  296,862 bytes. Quote: "Spot-Quoted Futures, E-micro Futures and Futures Options (MES, MNQ, M2K,
  VOLQ, ...) ... Monthly Volume (Contracts) | Tiered | Fixed ... ≤ 1,000 | USD 0.25 /contract | USD
  0.25 /contract." The equivalent `interactivebrokers.com` page carries the same figure (fetched
  2026-07-21). This is a **primary upgrade** of the figure the feasibility-gate doc (§4.3) sourced
  secondarily from brokerage-review.com ("E-micro $0.25/contract") — now confirmed directly on
  IBKR's own, entity-correct page.
- **IBKR Ireland CME exchange-fee pass-through for MES: USD 0.35/contract.**
  Source: [interactivebrokers.ie/en/accounts/fees/CME.php](https://www.interactivebrokers.ie/en/accounts/fees/CME.php)
  (page title: "Fees Charged to Offset CME (Electronic-Globex) Exchange and Regulatory Fees Paid by
  IBKR | Interactive Brokers Ireland"), fetched 2026-07-24, HTTP 200. Quote: "Micro E-Mini Futures
  Products MES, MNQ, M2K, VOLQ USD 0.35". The equivalent `interactivebrokers.com` page carries the
  same figure (fetched 2026-07-21). This line item was explicitly flagged as unquantified in the
  feasibility-gate doc's IBKR commission citation ("Exchange/regulatory pass-through fees are
  mentioned... but not quantified") — now filled with a primary figure.
- **Composite IBKR-side cost: USD 0.60/contract/side = USD 1.20/contract round trip**
  (commission $0.25 + exchange fee $0.35, doubled for round trip). This is commission+fee only — it
  excludes the bid/ask spread and any residual NFA/regulatory fee not broken out on the fee page.

### §2.3 Per-trip cost in bp — cannot be computed; inputs shown individually

Formula per the sub-plan: `bp = (2 × commission_and_fees + spread_$) / notional × 10000`, with
`notional = multiplier × index level`.

| Input | Status | Value |
|---|---|---|
| Round-trip commission + exchange fee | **Verified** | USD 1.20/contract (§2.2) |
| Contract multiplier | **Still unverified** (CME + IBKR both blocked, §2.1–§2.2) | — |
| Tick value (spread-floor input) | **Still unverified** (same) | — |
| 1-tick spread floor | **Not computable** — depends on tick value | — |
| Notional | **Not computable** — depends on multiplier | — |
| S&P 500 / SPX index level, dated | **Still unverified — secondary indication only** | 7510.39 on 2026-07-21 per [tradingeconomics.com/united-states/stock-market](https://tradingeconomics.com/united-states/stock-market) (embedded quote widget: `"ticker":"SPX:IND"..."last":7510.390000000000`). **Trading Economics is an aggregator, not a primary source under §0** — this is a *secondary indication, not verification*. See the correction note below. |

**Per the sub-plan's own rule ("the composite bp figure is 'verified-derived' only if every input is
verified; otherwise present it with each input's individual status"): the composite per-trip bp cost
cannot be computed this session.** The dollar-terms commission+fee figure ($1.20/contract round trip)
is verified and is a genuine update to the repo's cost picture, but without a verified multiplier the
notional — and therefore the bp figure §2.5 of the frozen doc would need to compare against the CFD
base case (0.79–1.75 bp) — cannot be derived. **Line-242's marker ("MES's own per-trip cost is
unpriced") is resolved only partially: commission+fee side is now priced in dollar terms; the bp
figure remains still unverified.**

**Correction (fix round 1, 2026-07-24) — index level was mislabeled.** The first pass marked the SPX
level `7510.39` as *Verified* on a `tradingeconomics.com` citation. Trading Economics is a data
aggregator and is not in this note's own §0 primary whitelist (CME Group, IBKR, EUR-Lex, bafin.de,
Alpaca docs); under the sub-plan's rule such a source may *locate* a fact but never *verify* it. The
row is therefore relabeled **secondary indication — not verification**, and removed from the
Verified log in §7. One bounded attempt was made to replace it with a primary from the index
administrator: `https://www.spglobal.com/spdji/en/indices/equity/sp-500/` returned **HTTP 403**
(2,011-byte block body) on 2026-07-24. Materiality is low and unchanged: this input feeds no computed
number, because the notional is not computable without a verified multiplier (row 5 above), so the
relabel does not alter any verdict in this note.

---

## §3 Group 2 — IBKR EU-retail futures access

### §3.1 Entity and account minimum — verified

A German retail resident contracts with **Interactive Brokers Ireland Limited**, not the US entity.
Source: [interactivebrokers.ie/en/home.php](https://www.interactivebrokers.ie/en/home.php), fetched
2026-07-21. Quote: "Interactive Brokers Ireland Limited Is regulated by the Central Bank of Ireland
(CBI, reference number C423427), registered with the Companies Registration Office (CRO, registration
number 657406), and is a member of the Irish [Investor Compensation scheme]."

**No account minimum.** German-language page (targeted at German visitors — "Handeln Sie mit IBKR an
Märkten in Deutschland und auf der ganzen Welt"), source
[interactivebrokers.ie/de/home.php](https://www.interactivebrokers.ie/de/home.php), fetched
2026-07-21. Quote: "Niedrige Provisionen ohne zusätzliche Spreads, Ticket- bzw. Plattformgebühren
oder **Mindesteinlagen**." ("Low commissions with no additional spreads, ticket or platform fees, or
**minimum deposits**.") English equivalent on the `.ie/en/` page: "Low commissions with no added
spreads, ticket charges, platform fees, or account minimums."

### §3.2 CME market-data subscription pricing for non-professionals — verified

Source: [interactivebrokers.ie/en/pricing/market-data-pricing.php](https://www.interactivebrokers.ie/en/pricing/market-data-pricing.php)
(page title: "Market Data Pricing | Interactive Brokers Ireland" — the entity-correct page, fetched
2026-07-24, HTTP 200, 398,890 bytes; the `interactivebrokers.com` page fetched 2026-07-21 carries the
same three CME rows). The table's own column headers: "Market Data Package | Country | **Non-Pro
Fees/month** | Pro Fees/month". Extracted row: "CME Real-Time (L1) ... United States USD 1.55 N/A" —
**USD 1.55/month, non-professional, for top-of-book CME real-time data**.

**Honest ambiguity, flagged rather than resolved — and it covers two rows, not one (corrected in fix
round 1).** Of the three CME rows, only "CME Real-Time (L1)" carries **two** cell values in the
flattened extraction (`USD 1.55` and `N/A`), which is what makes its Non-Pro/Pro column assignment
readable. Both "CME Real-Time (L1, L2)" (`USD 145.00`) and "CME Real-Time (L2)" (`USD 12.10`) carry a
**single** value, so for each of those it is not possible from the extracted text alone to confirm
whether the figure sits in the Non-Pro or the Pro column. The first pass called the $145.00 row
ambiguous while asserting the $12.10 L2 figure was unambiguous; that was inconsistent — the two rows
have the same shape and the same uncertainty. **Only the L1 figure of USD 1.55/month non-pro is
verified as a Non-Pro figure here; the L2 (USD 12.10) and combined L1,L2 (USD 145.00) figures are
recorded as values on the page with their column assignment still unverified**, resolvable only
against the live rendered table rather than the flattened HTML. This does not affect any conclusion:
a single MES outright plausibly needs only the L1 package (an operational inference — the cited "CME
Real-Time (L1)" row does not enumerate its products), and only that L1 figure is verified here
regardless.

### §3.3 Futures trading permissions / EU-specific restrictions for German retail — verified, with a material new fact

**BaFin's 2022-09-30 Allgemeinverfügung on futures product intervention** — not previously cited
anywhere in this repo — restricts marketing, distribution, and sale of exchange-traded futures
(MiFID II Annex I Section C Nos. 4–7 and 10 — a broad category that includes equity-index futures
like MES) to German retail clients, effective **2023-01-01**. Source:
[bafin.de — vf_20220930_Allgemeinverfuegung_Produktintervention_bezueglich_Futures](https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Aufsichtsrecht/Verfuegung/vf_20220930_Allgemeinverfuegung_Produktintervention_bezueglich_Futures.html),
fetched 2026-07-21, HTTP 200. Quote (operative Tenor): "Die Vermarktung, der Vertrieb und der Verkauf
von Futures an Kleinanleger im Sinne des Art. 4 Abs. 1 Nr. 11 MiFID II mit Sitz in Deutschland wird
Wertpapierfirmen vorbehaltlich der unter Ziffer 2. geregelten Ausnahmen untersagt. Die Beschränkung
wird mit Wirkung zum 01.01.2023 wirksam." The restriction has three exceptions (Ziffer 2), the
relevant one being: brokers may still market/sell futures to German retail if they **contractually
exclude the Nachschusspflicht** (the obligation to cover losses beyond deposited funds), capping the
retail client's loss at the funds deposited for futures trading. No expiry/"befristet" language was
found; the order reserves only a discretionary right of revocation ("Ich behalte mir den Widerruf
dieser Allgemeinverfügung vor"), i.e. it is open-ended, not time-limited.

**Does IBKR implement the Nachschusspflicht-exclusion exception, and on what terms?** Verified via
[lynxbroker.de — futureshandel-kleinanleger](https://www.lynxbroker.de/service/produkte-und-regularien/regularien/futureshandel-kleinanleger/),
fetched 2026-07-21, HTTP 200. **Source-class note, stated honestly: this is LYNX's own page, an
IBKR-network German-facing broker, describing IBKR's mechanism by name** — repeated attempts to
locate an IBKR-Ireland-branded first-party page stating the identical mechanism did not succeed this
session (search-engine rate-limiting, §3.4) — so this is treated as **broker-authoritative for what
IBKR requires**, one tier below a direct IBKR-Ireland citation, per the honesty-labeling rule. Quote:
"Kleinanleger in Deutschland müssen IBKR nicht für Verluste im Zusammenhang mit Futures entschädigen,
die über die speziell für den Futures-Handel hinterlegten Mittel hinausgehen." ("Retail investors in
Germany do not have to compensate IBKR for futures-related losses that exceed the funds specifically
deposited for futures trading.") The mechanism has real operational conditions: "Die anfänglichen
Margin-Anforderungen für Futures müssen mit freien Barmitteln erfüllt werden" (initial futures margin
must be met with **free cash only** — margin loans cannot be used to fund futures margin; an account
with a margin loan cannot trade futures at all), and a separate standard futures trading permission
("Handelsfreigabe") must also be requested, independent of the BaFin mechanism.

**Margin increase and the EUR 50,000 doubling rule (added in fix round 1 — omitted from the first
pass, same page, same block).** The same LYNX page states that IBKR raised margin requirements for
German retail futures positions under this regime, under the heading "Marginänderungen durch IB",
fetched again 2026-07-24, HTTP 200. Quotes: "Interactive Brokers (IBKR) hat die Marginanforderungen
für neue Futures-Positionen nach dem 1. Januar 2023 erhöht, die von Kleinanlegern mit Wohnsitz in
Deutschland eröffnet werden." ("IBKR has raised the margin requirements for new futures positions
opened after 1 January 2023 by retail investors resident in Germany.") The mechanics stated on the
same page:

- "Der Intraday-Ersteinschuss gilt nicht mehr, nur die Anforderungen für die Overnight-Margin werden
  für die Berechnung verwendet." — the reduced intraday initial margin no longer applies; the
  overnight requirement is used for the calculation.
- "Bei einer Margin-Anforderung von über 50.000 EUR werden die Anforderungen über diesem Schwellenwert
  verdoppelt." — margin requirement above EUR 50,000 is doubled on the excess, with the page's own
  worked example: "Beträgt die übliche Margin-Anforderung 75.000 EUR, dann benötigen Sie 100.000 EUR
  Margin: (50.000 + (2 x 25.000))".
- "Futures mit dem gleichen Basiswert (z.B. S&P 500, DAX usw.) werden zusammen als eine Klasse
  betrachtet. Die Erhöhung der Margin und deren Berechnung gilt für diese gruppierte Position
  (Klasse) einheitlich." — same-underlying futures are aggregated into one class for that
  calculation.

Same source-class caveat as above: LYNX, not IBKR Ireland first-party. Whether the EUR 50,000
doubling rule binds at single-contract size cannot be checked here, because the MES margin
requirement is still unverified (§2.1–§2.2); it is unlikely to bind at micro size, but that is an
inference, not a verified fact. The loss of intraday margin relief and the free-cash-only funding
condition apply at any size. All belong to the §6 capital-efficiency flag.

**This applies to all exchange-traded futures uniformly (not MES-specifically), so it does not change
the *relative* standing of MES vs. 6E/M6E** — the same free-cash-only, Nachschusspflicht-excluded
condition would bind a 6E/M6E position at IBKR exactly as it binds MES. It is, however, a genuinely
new fact about the terms of EU-retail futures access at IBKR that the frozen pre-registration did not
have — see §6.

### §3.4 Search-engine rate-limiting attempt log

DuckDuckGo HTML search (`html.duckduckgo.com` and `duckduckgo.com/html`) was used successfully
several times earlier in this session (locating the BaFin futures Allgemeinverfügung and the LYNX
page), then began returning HTTP 202 with an empty body on later queries in the same session
(discovery-only tool, not itself a citation) — logged for transparency, not as a verification gap:
a Bing HTML search (`bing.com/search`) for the same later queries returned HTTP 200 but no usable
organic result links in the fetched markup (JS-rendered results). No claim in this note depends on
these later, unsuccessful discovery attempts.

**Verdict — "does IBKR extend EU-retail futures access on the same terms found for 6E/M6E?":
verified on the access-terms leg, qualified yes.** Same entity, and the newly-verified condition
(cash-only funding, Nachschusspflicht exclusion, since 2023-01-01) applies uniformly across futures
products, so it does not differentiate MES from 6E/M6E. Two of the three legs in the original verdict
are **not** established by a fetch and are scoped down here: the "same commission-schedule shape" leg
is **unfetched for 6E/M6E specifically** — the cited `.ie` futures-commission page (§2.2) lists the
E-micro row `(MES, MNQ, M2K, VOLQ, ...)` and contains no `6E`/`M6E` entry, so per-contract commission
parity with 6E/M6E is not shown here; and "same API" is a **repo cross-reference** (the forex
feasibility gate §8), not a fetch. The verified access condition is a real, previously-unpriced
constraint on capital efficiency for *any* futures candidate under this direction. Flagged in §6.

---

## §4 Group 3 — EU-retail options access path

### §4.1 Can a German resident open a self-directed US-domiciled Alpaca account?

**Still unverified — but the primary source itself was successfully reached and declines to answer.**
Source: [alpaca.markets/support/countries-alpaca-is-available](https://alpaca.markets/support/countries-alpaca-is-available),
fetched 2026-07-21, HTTP 200, page dated "February 2026", tagged "International (Non-US Tax
Residents)". Full substantive content of the page, quoted verbatim: "Please contact support at
[email protected] for more information regarding whether your country is supported." No countries
are enumerated on the page in either direction; Germany is neither confirmed nor excluded. This is
distinct from a blocked/empty fetch — the fetch succeeded, and the page's own content is a deferral
to a non-public support channel, which this research process does not have access to (no login-walled
or account-specific content was pursued, per the sanitization rule).

Cross-reference (not restated): `docs/research/alpaca-eu-expansion.md` already establishes that
Alpaca's 2026-04-21 EU launch (via WealthKernel, "Alpaca Europe") is Broker-API-only with no
self-directed EU Trading-API surface — that finding stands unchanged. This note adds only the
US-side eligibility question, which remains open.

### §4.2 One concrete venue with fee schedule (access half unverified)

Per the frozen doc's own wording ("the exact venue," singular), IBKR is the concrete candidate, using
the same entity established in §3.1 (Interactive Brokers Ireland Limited).

**Verdict up front: the line-119 marker is resolved on its fee-schedule half only.** The venue is
named and its per-contract commission, clearing fee, and index-option exchange fees are verified at
the entity a German resident actually contracts with. Whether that entity grants a German retail
client US index-option trading permissions is **still unverified** — see the withdrawn claim below
and the PRIIPs/KID verdict in §4.3.

- **IBKR Ireland US options commission (Tiered, United States, ≤10,000 contracts/month): USD
  0.65/contract for premium ≥ USD 0.10**, plus **OCC clearing fee USD 0.025/contract**. Source:
  [interactivebrokers.ie/en/pricing/commissions-options.php](https://www.interactivebrokers.ie/en/pricing/commissions-options.php)
  (page title: "Commissions Options | Interactive Brokers Ireland"), fetched 2026-07-24, HTTP 200,
  189,669 bytes. Quotes: "United States ... Monthly Volume (Contracts) | Tiered ... ≤ 10,000 ...
  Premium < USD 0.05 → USD 0.25 /contract; Premium ≥ USD 0.05 and <0.10 → USD 0.50 /contract; Premium
  ≥ USD 0.10 → USD 0.65 /contract" and "OCC Clearing Fees All Contracts: 0.025 /contract." The
  `interactivebrokers.com` page fetched 2026-07-21 carries the same USD 0.65 and USD 0.025 figures;
  the `.ie` page is cited here because §3.1 establishes IBKR Ireland as the contracting entity.
- **Product/fee-schedule scope for index options — verified, narrowly.** IBKR **Ireland**'s own
  published Cboe options exchange-fee schedule contains an **"Index"** block itemizing per-contract
  fees for **SPX** and **SPXW** (and VIX). Source:
  [interactivebrokers.ie/en/accounts/fees/CBOEoptfee.php](https://www.interactivebrokers.ie/en/accounts/fees/CBOEoptfee.php)
  (page title: "CBOE Options Fees | Interactive Brokers Ireland"; reached from the "United States –
  Third Party Fees → Exchange Fees → CBOE" link on the `.ie` options-commissions page above), fetched
  2026-07-24, HTTP 200, 229,101 bytes. The equivalent
  `interactivebrokers.com/en/accounts/fees/CBOEoptfee.php` page (title "Cboe Options Fees |
  Interactive Brokers LLC") publishes the identical schedule — this Cboe exchange-fee table is not
  Ireland-specific; the `.ie` page is cited because §3.1 establishes IBKR Ireland as the contracting
  entity, not because the fee schedule is entity-scoped product access. Column headers: "Public
  Customer | Broker-Dealer | Firm | Away
  MM | Joint Back Office | Professional", each split "Remove Liquidity | Add Liquidity". Quoted rows
  under "Index": "SPX, Premium >=$1.00 — USD 0.45 [Public Customer, Remove] / USD 0.45 [Add]" and
  "SPXW, Premium >=$1.00 — USD 0.45 / USD 0.45". **What this does and does not establish:** it
  establishes that SPX/SPXW index options sit inside the *fee schedule published by the entity a
  German resident contracts with*, which is exactly the fee-schedule half of the line-119 marker. It
  does **not** establish that a German retail client of that entity is granted US index-option
  trading permissions — that, and the PRIIPs/KID question (§4.3), remain still unverified.
- **Withdrawn claim (fix round 1): the options *marketing* page does not support index-options
  access.** The first pass cited
  [interactivebrokers.ie/en/trading/products-options.php](https://www.interactivebrokers.ie/en/trading/products-options.php)
  as "lists CBOE and US index-option products (SPX referenced)". Re-fetched 2026-07-24 (HTTP 200,
  210,550 bytes): the string `SPX` occurs **zero** times anywhere in the HTML including inline JS,
  and the only `Cboe` occurrence is in the Australian AFSL 453554 regulatory footer ("...is a
  participant of ASX, ASX 24 and Cboe Australia"), not a product listing. The page's only relevant
  content is the generic marketing line "Access 10,000+ US Stocks and ETFs day and night. Plus US
  futures, index options and global bonds." — which is **not** treated here as evidence of
  index-options access. The claim is withdrawn and replaced by the fee-schedule finding above.
- **Bounded search for further entity-level evidence, then stop.** One additional `.ie` page was
  tried: `https://www.interactivebrokers.ie/en/trading/products-exchanges.php` (HTTP 200, 169,873
  bytes) is an AJAX-driven exchange-listing widget with zero `SPX` occurrences in the fetched markup —
  an empty-JS-shell failure, the same shape as the futures product-search pages in §2.2. No further
  hunting was done.

### §4.3 PRIIPs/KID restriction on EU-retail access to US-listed options — still unverified

Attempted:

| URL | Result |
|---|---|
| `https://www.interactivebrokers.ie/en/general/regulation/priips-kids.php` | HTTP 404 |
| `https://www.interactivebrokers.com/en/general/regulation/priips-kids.php` | HTTP 404 |
| `https://www.interactivebrokers.ie/en/index.php?f=priips` | HTTP 200, body is IBKR's own "PAGE NOT FOUND" soft-error template |
| DuckDuckGo HTML search for `interactivebrokers.ie PRIIPs KID US options EU retail` | HTTP 202, empty (rate-limited, §3.4) |
| Bing HTML search, same query | HTTP 200, no usable organic result links in fetched markup |

**Verdict: still unverified.** Whether PRIIPs/KID requirements restrict IBKR-Ireland EU-retail clients
from US-listed single-name or index options is not resolved by any primary source reached this
session — this is a real, practically-important open question, but it
is not asserted here without a fetched primary confirmation, per the no-fabrication rule.

---

## §5 Group 4 — ESMA tier precision + BaFin tightening

### §5.1 EUR-Lex — verified (first pass used the wrong CELEX identifier)

**Verified: the ESMA Decision (EU) 2018/796 text on EUR-Lex, with the per-tier initial-margin
percentages read directly from the designated primary.** Source:
[eur-lex.europa.eu — CELEX:32018X0601(02)](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32018X0601\(02\)),
fetched 2026-07-24, HTTP 200, 291,716 bytes. Document header, quoted: "Official Journal of the
European Union L 136/50 — EUROPEAN SECURITIES AND MARKETS AUTHORITY DECISION (EU) 2018/796 of 22 May
2018 to temporarily restrict contracts for differences in the Union in accordance with Article 40 of
Regulation (EU) No 600/2014". The tier table is **ANNEX I, "INITIAL MARGIN PERCENTAGES BY TYPE OF
UNDERLYING"**, quoted verbatim:

> "(a) 3,33 % of the notional value of the CFD when the underlying currency pair is composed of any
> two of the following currencies: US dollar, Euro, Japanese yen, Pound sterling, Canadian dollar or
> Swiss franc; (b) 5 % of the notional value of the CFD when the underlying index, currency pair or
> commodity is: (i) any of the following equity indices: Financial Times Stock Exchange 100 (FTSE
> 100); Cotation Assistée en Continu 40 (CAC 40); Deutsche Bourse AG German Stock Index 30 (DAX30);
> Dow Jones Industrial Average (DJIA); Standard & Poors 500 (S&P 500); NASDAQ Composite Index
> (NASDAQ), NASDAQ 100 Index (NASDAQ 100); Nikkei Index (Nikkei 225); Standard & Poors / Australian
> Securities Exchange 200 (ASX 200); EURO STOXX 50 Index (EURO STOXX 50); (ii) a currency pair
> composed of at least one currency that is not listed in point (a) above; or (iii) gold; (c) 10 % of
> the notional value of the CFD when the underlying commodity or equity index is a commodity or any
> equity index other than those listed in point (b) above; (d) 50 % of the notional value of the CFD
> when the underlying is a cryptocurrency; or (e) 20 % of the notional value of the CFD when the
> underlying is: (i) a share; or ..."

This maps exactly onto the frozen doc's §2.4 table (30:1/3.33%, 20:1/5%, 10:1/10%, 5:1/20%, 2:1/50%)
and is identical to the German-language BaFin transposition quoted in §5.2.

**Correction (fix round 1, 2026-07-24) — the first pass's "site-wide bot-detection gate" diagnosis
was wrong and is withdrawn.** All seven first-pass attempts used CELEX **`32018R0796`**. That is not
this document's identifier: `R` denotes a *regulation*, whereas an ESMA decision published in the L
series carries an `X` sector code — the correct identifier is **`32018X0601(02)`**. Re-checked on
2026-07-24:

| URL | Result (2026-07-24) |
|---|---|
| `https://eur-lex.europa.eu` (bare root) | **HTTP 200, 11,912 bytes** — the site answers normally; the first pass's "HTTP 202, 0 bytes" for this same root is not reproducible |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0796` (wrong identifier) | **HTTP 404, 82,957 bytes** — a rendered "not found" page, i.e. a content response, not a gate |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32018X0601(02)` (correct identifier) | **HTTP 200, 291,716 bytes** — full decision text |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018X0601(02)` | **HTTP 200** |

So the failure was a **wrong CELEX identifier**, not a site-wide gate, and the diagnosis in the first
pass overstated a lookup error into a blocked-primary verdict. Whatever produced the first pass's
202-empty responses (a transient edge, or the tooling used), it did not survive re-testing and cannot
be used to conclude the site is gated. The substantive Group-4 tier values were never in doubt — they
were already independently verified verbatim from BaFin in §5.2 — so this correction is about
provenance and about a false failure diagnosis, not about the numbers. The designated primary is now
fetched and quoted above.

### §5.2 BaFin — verified, exact tier table

The per-tier margin percentages are independently and precisely confirmed a second time on BaFin's own
site — the national transposition, and the source the repo already partially cited for the 30:1
FX-major figure. Together with §5.1 the tiers now rest on **two** mutually corroborating primaries
(EU-level decision text and national Allgemeinverfügung). Source:
[bafin.de — vf_190801_allgvfg_Differenzgeschaefte](https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Aufsichtsrecht/Verfuegung/vf_190801_allgvfg_Differenzgeschaefte.html),
fetched 2026-07-21, HTTP 200, 456,863 bytes. Full operative tier list, quoted verbatim (German
original, Ziffer 2.a):

> "aa) 3,33 % des Nominalwerts des CFD, wenn der Währungspaar-Basiswert aus zwei der folgenden
> Währungen besteht: US-Dollar, Euro, japanischer Yen, Pfund Sterling, kanadischer Dollar oder
> Schweizer Franken; bb) 5 % des Nominalwerts des CFD, wenn der Index, das Währungspaar oder der
> Rohstoff des Basiswerts besteht aus: (1) einem der folgenden Aktienindizes: [FTSE 100; CAC 40; DAX
> 30; Dow Jones; S&P 500; NASDAQ/NASDAQ 100; Nikkei 225; ASX 200; EURO STOXX 50]; (2) einem
> Währungspaar, das aus mindestens einer Währung besteht, die nicht unter [aa)] oben angeführt ist,
> oder (3) Gold; cc) 10 % des Nominalwerts des CFD, wenn der Rohstoff oder der Aktienindex des
> Basiswerts ein anderer Rohstoff oder ein anderer Aktienindex als die vorstehend unter [bb)]
> aufgeführten ist; dd) 50 % des Nominalwerts des CFD, wenn der Basiswert eine Kryptowährung ist;
> oder ee) 20 % des Nominalwerts des CFD, wenn der Basiswert (1) eine Aktie ist oder (2) nicht an
> anderer Stelle unter [Ziffer 2.a)] angeführt ist."

This maps exactly onto the frozen doc's §2.4 table (30:1/3.33%, 20:1/5%, 10:1/10%, 5:1/20%, 2:1/50%),
confirming the frozen doc's "settled regulatory knowledge" figures are precisely correct, now with a
directly fetched primary citation rather than only the previously-cited 30:1 FX line.

**Alignment with ESMA, no independent CFD tightening:** the same page states the order corresponds
in essence to ESMA Decision (EU) 2018/796 and its extensions, and exists specifically to make the
ESMA measure permanent in Germany once the temporary EU-level measure lapsed: "Die vorliegende
Allgemeinverfügung greift lediglich die bereits seit dem Inkrafttreten des ESMA-Beschlusses (EU)
2018/796 am 01.08.2018 bestehende Rechtslage auf und hält diese aufrecht." **No CFD-tier deviation
beyond the ESMA schedule was found in this document.**

### §5.3 BaFin post-2018 tightening — verified, but on futures, not CFDs

Searching BaFin's product-intervention history (per the sub-plan's instruction to check while already
on bafin.de) surfaced a measure **not on CFDs at all**: the 2022-09-30 futures Allgemeinverfügung
detailed in full at §3.3 above. This is genuine national tightening beyond the original 2018/2019 CFD
measure, but it targets a different instrument class (exchange-traded futures, MiFID II Annex I C
4–7/10) than the CFD tiers in §2.4 of the frozen doc. **The CFD tiers themselves show no tightening**
(§5.2); **futures access, previously unregulated at the BaFin-retail level, gained a new,
condition-based restriction effective 2023-01-01.**

---

## §6 Closing flag

**Does any verified fact challenge the frozen §2.5 MES recommendation?**

**Yes — one flag, raised on the access axis but proportionate to what the evidence shows: a
funding-mechanics and capital-efficiency disclosure, not a challenge to §2.5's structural legs.**
(Label corrected in fix round 1: the first pass declared a binary "challenge triggered" on the access
axis while its own text said the measure is not an access denial and does not change the relative
standing of MES vs. 6E/M6E. The flag stands and still resolves in one direction — it is raised, not
withdrawn — but it is labeled for what it is.)

- **Cost axis (challenge shape (i) in the sub-plan): no challenge triggered.** The MES per-trip bp
  cost could not be computed this session (§2.3) — CME's contract-spec pages remain fully blocked and
  IBKR's margin/contract-search tools are JS-shells with no fallback static figure. A verified
  dollar-terms commission+fee figure ($1.20/contract round trip) exists but, without a verified
  multiplier, cannot be turned into the bp figure §2.5 would need to compare against the 0.79 bp CFD
  base case. **This is an open question, not a resolved challenge** — it neither confirms nor
  contradicts §2.5's cost-competitiveness framing.

- **Access axis (challenge shape (ii) in the sub-plan): flag raised — an undisclosed funding-mechanics
  and capital-efficiency regime, not an access barrier.** §3.3 verifies the named example — "a BaFin
  futures-directed measure" — a real, German-specific, post-2018 regulatory restriction on retail
  futures (BaFin's 2022-09-30 Allgemeinverfügung), not discussed anywhere in the frozen document.
  Stated precisely, so the flag is neither overstated nor softened:
  - **It is not an access denial.** IBKR already implements the BaFin-provided exception (contractual
    exclusion of the Nachschusspflicht), so MES and 6E/M6E both remain tradable by German retail
    clients through IBKR. §2.5's "real, automatable, EU-reachable API" leg therefore stands: nothing
    verified here removes MES from reach.
  - **It does not change the relative standing of MES vs. 6E/M6E** (§3.3) — the regime binds all
    exchange-traded futures uniformly, so it does not discriminate between the frozen doc's candidates.
  - **What is genuinely new, and unpriced anywhere in the frozen doc's §2.3/§2.5/§5, is a package of
    funding-mechanics conditions** that change how much capital an MES position ties up, versus the
    plain SPAN-margin framing §2.3 uses: (a) futures margin must be met with **free cash only** (no
    margin loan); (b) a separate futures **Handelsfreigabe** must be requested; (c) IBKR **raised**
    margin requirements for German-retail futures positions opened after 2023-01-01; (d) the reduced
    **intraday** initial margin no longer applies — the overnight requirement is used; and (e) margin
    requirement **above EUR 50,000 is doubled on the excess**, aggregated per underlying class. Items
    (c)–(e) were omitted from the first pass and are added here from the same cited page (§3.3, which
    is broker-authoritative — LYNX, an IBKR-network broker — one tier below a direct IBKR-Ireland
    citation). Whether (e) binds at the single-contract micro size the frozen doc contemplates cannot
    be verified here, because the MES margin requirement is still unverified (§2.1–§2.2); the flag
    carries it as an open item rather than as a condition shown not to apply. (a)–(d) apply at any
    size.

  Per the sub-plan's instruction to flag a verified EU-retail futures access finding whenever found,
  this is recorded rather than silently absorbed — as a disclosure that the frozen doc's capital
  assumptions need restating, not as a fact that undermines §2.5's recommendation.

**Disposition: flag as requiring a committed revision per the frozen document's own §7 revision
clause, if and when this direction is carried forward to a survey batch.** This note does not, and
per its scope cannot, edit `2026-07-21-leveraged-contracts-preregistration.md` — the flag is recorded
here only. A future committed revision, should one be made, would need to (a) re-state §2.3's access
finding to include the free-cash-only funding condition, the Nachschusspflicht-exclusion mechanism,
the post-2023 IBKR margin increase, the loss of intraday margin relief, and the EUR 50,000 doubling
rule, and (b) either compute the MES bp cost once a CME- or IBKR-primary multiplier/tick figure
becomes reachable, or explicitly carry the still-unverified status forward.

No other frozen element is contradicted by anything verified in this note.

---

## §7 Attempt-log summary (all primary-source fetches this session)

Rows marked **[fix-1]** were fetched or re-fetched on **2026-07-24** during fix round 1; all others
are from the 2026-07-21 pass.

| Source | Outcome |
|---|---|
| cmegroup.com (9 distinct URLs) | All HTTP 403 or timeout |
| eur-lex.europa.eu — CELEX:32018X0601(02), EN/TXT/HTML **[fix-1]** | **Verified** (ESMA Decision (EU) 2018/796, ANNEX I tier percentages) — HTTP 200, 291,716 bytes |
| eur-lex.europa.eu — bare root **[fix-1]** | HTTP 200, 11,912 bytes (site reachable) |
| eur-lex.europa.eu — CELEX:32018R0796 (7 first-pass URL shapes, **wrong identifier**) | First pass recorded HTTP 202/empty; on re-test **[fix-1]** the wrong identifier returns HTTP 404 with a rendered page. Diagnosis corrected in §5.1 — lookup error, not a site gate |
| interactivebrokers.ie — pricing/commissions-futures.php **[fix-1]** | **Verified** (MES commission, entity-correct) |
| interactivebrokers.ie — accounts/fees/CME.php **[fix-1]** | **Verified** (MES exchange-fee pass-through, entity-correct) |
| interactivebrokers.ie — pricing/commissions-options.php **[fix-1]** | **Verified** (US options commission + OCC fee, entity-correct) |
| interactivebrokers.ie — accounts/fees/CBOEoptfee.php **[fix-1]** | **Verified** (Cboe "Index" fee rows: SPX, SPXW, VIX) |
| interactivebrokers.ie — pricing/market-data-pricing.php **[fix-1]** | **Verified** (CME L1 non-pro data fee, entity-correct; L2 / L1+L2 column assignment unverified) |
| interactivebrokers.com — commissions-futures.php, accounts/fees/CME.php, commissions-options.php, market-data-pricing.php, accounts/fees/CBOEoptfee.php | Same figures/schedule as the `.ie` pages above; superseded as citations by the entity-correct `.ie` sources |
| interactivebrokers.com — index.php?f=marginnew&p=fut | JS shell, no static figure |
| interactivebrokers.com — index.php?f=2222&exch=cme... | JS shell, no static figure |
| interactivebrokers.com — trading/products-futures.php | JS shell, no static figure |
| interactivebrokers.com — webrest/search/products-by-filters (×2) | HTTP 403, HTTP 500 |
| interactivebrokers.ie — en/home.php, de/home.php | Verified (entity, no account minimum) |
| interactivebrokers.ie — de/trading/products-futures.php | Reached, no Nachschuss/Kleinanleger content (marketing page only) |
| interactivebrokers.ie — en/trading/products-options.php **[fix-1]** | Reached (HTTP 200, 210,550 bytes) but **does not support the product claim made in the first pass** — zero `SPX` occurrences; sole `Cboe` string is the Australian AFSL footer. Claim withdrawn (§4.2) |
| interactivebrokers.ie — trading/products-exchanges.php **[fix-1]** | HTTP 200, AJAX-driven exchange listing, zero `SPX` in markup (JS shell) |
| interactivebrokers.ie — PRIIPs pages (×3 URL guesses) | 404 / soft-404 |
| bafin.de — vf_190801_allgvfg_Differenzgeschaefte | Verified (CFD tier table) |
| bafin.de — vf_20220930_Allgemeinverfuegung...Futures | Verified (2022 futures measure) |
| lynxbroker.de — futureshandel-kleinanleger **[re-fetched fix-1]** | Verified — broker-authoritative for IBKR's mechanism, one tier below a direct IBKR-Ireland citation (the margin-increase / EUR 50k doubling block added to §3.3 in fix round 1) |
| alpaca.markets/support/countries-alpaca-is-available | Reached; page itself states no policy |
| spglobal.com/spdji — S&P 500 index page **[fix-1]** | HTTP 403 (2,011-byte block body) — bounded attempt to source the index level from a primary |
| tradingeconomics.com/united-states/stock-market | **Not a verification** — aggregator, outside the §0 primary whitelist; recorded as a *secondary indication* for the SPX level (relabeled in fix round 1, §2.3) |
| DuckDuckGo / Bing HTML (discovery only, ~10 queries) | Mixed — several yielded the BaFin-futures and LYNX URLs; later queries rate-limited (202) or returned no usable links |

---

## §8 Sanitization confirmation

No account numbers, API keys, or personal data appear anywhere in this note. The operator is referred
to only as "a German retail resident" throughout, consistent with the frozen document. All cited URLs
are public marketing/regulatory pages; no login-walled content was fetched or referenced.
