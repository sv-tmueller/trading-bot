From __future__ note: this is a research memo, not code. No `from __future__ import annotations` required.

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
   own docs) was successfully fetched. The claim carries the value, the source URL, the access date
   (**2026-07-21** for every fetch in this note), and — where the exact wording is load-bearing — a
   short quote.
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
| Lines 94–96, §2.1 | Whether a German resident can hold a self-directed US-domiciled Alpaca account; if not, which EU-retail broker offers comparable index-options access. | Group 3 | §4.1–§4.2 |
| Lines 119–121, §2.1 | The exact EU-retail options-access venue and its per-contract commission/fee schedule. | Group 3 | §4.2 |
| Lines 185–188, §2.3 | MES's exact contract multiplier and margin requirement; whether IBKR extends EU-retail futures access on the same terms found for 6E/M6E. | Groups 1 + 2 | §2 (spec/margin), §3 (IBKR access) |
| Lines 213–216, §2.4 | Per-tier margin precision for the ESMA 20:1/10:1/5:1/2:1 tiers; any national BaFin-level post-2018 tightening. | Group 4 | §5 |
| Line 242, §2.5 | MES's own per-trip cost is unpriced in this repo. | Group 1 | §2.4 |

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
did resolve:

- **IBKR MES commission (Fixed schedule, ≤1,000 contracts/month tier): USD 0.25/contract.**
  Source: [interactivebrokers.com/en/pricing/commissions-futures.php](https://www.interactivebrokers.com/en/pricing/commissions-futures.php),
  fetched 2026-07-21. Quote: "Spot-Quoted Futures, E-micro Futures and Futures Options (MES, MNQ,
  M2K, VOLQ, ...) ... ≤ 1,000 [contracts/month] ... Fixed USD 0.25 /contract." This is a **primary
  upgrade** of the figure the feasibility-gate doc (§4.3) sourced secondarily from brokerage-review.com
  ("E-micro $0.25/contract") — now confirmed directly on IBKR's own page.
- **IBKR CME exchange-fee pass-through for MES: USD 0.35/contract.**
  Source: [interactivebrokers.com/en/accounts/fees/CME.php](https://www.interactivebrokers.com/en/accounts/fees/CME.php)
  ("Fees Charged to Offset CME (Electronic-Globex) Exchange and Regulatory Fees Paid by IBKR"),
  fetched 2026-07-21. Quote: "Micro E-Mini Futures Products MES, MNQ, M2K, VOLQ USD 0.35" under the
  "CME Equity Product" heading. This line item was explicitly flagged as unquantified in the
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
| S&P 500 / SPX index level, dated | **Verified** | 7510.39, [tradingeconomics.com/united-states/stock-market](https://tradingeconomics.com/united-states/stock-market), fetched 2026-07-21 (embedded quote widget: `"ticker":"SPX:IND"..."last":7510.390000000000`) |

**Per the sub-plan's own rule ("the composite bp figure is 'verified-derived' only if every input is
verified; otherwise present it with each input's individual status"): the composite per-trip bp cost
cannot be computed this session.** The dollar-terms commission+fee figure ($1.20/contract round trip)
is verified and is a genuine update to the repo's cost picture, but without a verified multiplier the
notional — and therefore the bp figure §2.5 of the frozen doc would need to compare against the CFD
base case (0.79–1.75 bp) — cannot be derived. **Line-242's marker ("MES's own per-trip cost is
unpriced") is resolved only partially: commission+fee side is now priced in dollar terms; the bp
figure remains still unverified.**

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

Source: [interactivebrokers.com/en/pricing/market-data-pricing.php](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php),
fetched 2026-07-21. The table's own column headers: "Market Data Package | Country | **Non-Pro
Fees/month** | Pro Fees/month". Extracted row: "CME Real-Time (L1) ... United States USD 1.55 N/A" —
**USD 1.55/month, non-professional, for top-of-book CME real-time data** (sufficient for a single
outright like MES). A deeper "CME Real-Time (L2)" (market depth) row is separately priced at USD
12.10/month non-pro. **Honest ambiguity, flagged rather than resolved:** a combined "CME Real-Time
(L1, L2)" row shows a single USD 145.00 figure in the flattened text extraction, and it is not
possible from the extracted text alone to confirm whether that is the Non-Pro or Pro column value —
re-verification against the live rendered table (not the flattened HTML) would be needed to resolve
that specific ambiguity; the L1-only $1.55/mo and L2-only $12.10/mo figures are unambiguous.

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
verified, qualified yes.** Same entity, same commission-schedule shape, same API; the newly-verified
condition (cash-only funding, Nachschusspflicht exclusion, since 2023-01-01) applies uniformly across
futures products, so it does not differentiate MES from 6E/M6E — but it is a real, previously-unpriced
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

### §4.2 One concrete venue with comparable index-options access + fee schedule

Per the frozen doc's own wording ("the exact venue," singular), IBKR is verified as the concrete
candidate, using the same entity established in §3.1 (Interactive Brokers Ireland Limited).

- **IBKR US options commission (IBKR Pro, ≤10,000 contracts/month tier): USD 0.65/contract**, plus
  **OCC clearing fee USD 0.025/contract**. Source:
  [interactivebrokers.com/en/pricing/commissions-options.php](https://www.interactivebrokers.com/en/pricing/commissions-options.php),
  fetched 2026-07-21. Quote: "United States Monthly Volume (Contracts) ... ≤ 10,000 USD 0.65
  /contract [IBKR Pro] ... OCC Clearing Fees All Contracts: 0.025 /contract."
- **Product availability:** IBKR Ireland's own options-products marketing page lists CBOE and
  US index-option products (SPX referenced). Source:
  [interactivebrokers.ie/en/trading/products-options.php](https://www.interactivebrokers.ie/en/trading/products-options.php),
  fetched 2026-07-21, HTTP 200.

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
session — this is a real, practically-important open question (PRIIPs KID requirements are widely
understood in the industry to complicate EU-retail access to US-listed derivatives generally) but it
is not asserted here without a fetched primary confirmation, per the no-fabrication rule.

---

## §5 Group 4 — ESMA tier precision + BaFin tightening

### §5.1 EUR-Lex — unreachable

Every attempt against `eur-lex.europa.eu`, across multiple URL shapes, languages, and user agents,
returned **HTTP 202 with an empty body** (a holding/challenge response, not a normal empty page) —
including the bare domain root, which rules out a URL-specific problem:

| URL | Result |
|---|---|
| `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0796` | HTTP 202, 0 bytes |
| `https://eur-lex.europa.eu/eli/dec/2018/796/oj` | HTTP 202, 0 bytes |
| `https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32018R0796` | HTTP 202, 0 bytes |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32018R0796` | HTTP 202, 0 bytes |
| `https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32018R0796` | HTTP 202, 0 bytes |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32018R0796` | HTTP 202, 0 bytes |
| `https://eur-lex.europa.eu` (bare root) | HTTP 202, 0 bytes |
| Same URL via WebFetch | Fetch tool reported the page content as empty |

**Verdict: the ESMA Decision (EU) 2018/796 text on EUR-Lex itself is still unverified — a genuine,
site-wide bot-detection gate**, consistent in spirit with the repo's existing CME precedent but a
different failure signature (202-empty rather than 403/timeout).

### §5.2 BaFin — verified, exact tier table

The per-tier margin percentages are independently and precisely confirmed on BaFin's own site (not
EUR-Lex, but still a primary regulator source, and the one the repo already partially cited for the
30:1 FX-major figure). Source:
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

**Alignment with ESMA, no independent CFD tightening:** the same page states the order "corresponds
in essence" to ESMA Decision (EU) 2018/796 and its extensions, and exists specifically to make the
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

**Yes — one flag, on the access-barrier axis, not the cost axis.**

- **Cost axis (challenge shape (i) in the sub-plan): no challenge triggered.** The MES per-trip bp
  cost could not be computed this session (§2.3) — CME's contract-spec pages remain fully blocked and
  IBKR's margin/contract-search tools are JS-shells with no fallback static figure. A verified
  dollar-terms commission+fee figure ($1.20/contract round trip) exists but, without a verified
  multiplier, cannot be turned into the bp figure §2.5 would need to compare against the 0.79 bp CFD
  base case. **This is an open question, not a resolved challenge** — it neither confirms nor
  contradicts §2.5's cost-competitiveness framing.

- **Access axis (challenge shape (ii) in the sub-plan): challenge triggered.** §3.3 verifies exactly
  the named example — "a BaFin futures-directed measure" — a real, EU/German-specific, post-2018
  regulatory restriction on retail futures access (BaFin's 2022-09-30 Allgemeinverfügung), not
  discussed anywhere in the frozen document. Stated precisely, so the flag is neither overstated nor
  softened: **this is not an access denial** — IBKR (per the LYNX-disclosed mechanism, §3.3) already
  implements the BaFin-provided exception (contractual exclusion of Nachschusspflicht), so MES and
  6E/M6E both remain tradable by German retail clients through IBKR. What is new, and unpriced
  anywhere in the frozen doc's §2.3/§2.5/§5, is a **structural funding condition**: futures margin at
  IBKR must be funded with free cash only (no margin loan), a distinct capital-efficiency constraint
  from the SPAN-margin framing §2.3 uses, and a mandatory account-level authorization step. Per the
  sub-plan's own instruction ("a verified EU-retail futures access barrier... undermining the... API
  leg" is a live challenge shape whenever found), this fact is flagged here rather than silently
  absorbed.

**Disposition: flag as requiring a committed revision per the frozen document's own §7 revision
clause, if and when this direction is carried forward to a survey batch.** This note does not, and
per its scope cannot, edit `2026-07-21-leveraged-contracts-preregistration.md` — the flag is recorded
here only. A future committed revision, should one be made, would need to (a) re-state §2.3's access
finding to include the free-cash-only funding condition and the Nachschusspflicht-exclusion mechanism,
and (b) either compute the MES bp cost once a CME- or IBKR-primary multiplier/tick figure becomes
reachable, or explicitly carry the still-unverified status forward.

No other frozen element is contradicted by anything verified in this note.

---

## §7 Attempt-log summary (all primary-source fetches this session)

| Source | Outcome |
|---|---|
| cmegroup.com (9 distinct URLs) | All HTTP 403 or timeout |
| eur-lex.europa.eu (7 distinct URLs incl. bare root) | All HTTP 202, empty body |
| interactivebrokers.com — commissions-futures.php | Verified (MES commission) |
| interactivebrokers.com — accounts/fees/CME.php | Verified (MES exchange fee) |
| interactivebrokers.com — index.php?f=marginnew&p=fut | JS shell, no static figure |
| interactivebrokers.com — index.php?f=2222&exch=cme... | JS shell, no static figure |
| interactivebrokers.com — trading/products-futures.php | JS shell, no static figure |
| interactivebrokers.com — webrest/search/products-by-filters (×2) | HTTP 403, HTTP 500 |
| interactivebrokers.com — commissions-options.php | Verified (US options commission) |
| interactivebrokers.com — market-data-pricing.php | Verified (CME L1 non-pro data fee) |
| interactivebrokers.ie — en/home.php, de/home.php | Verified (entity, no account minimum) |
| interactivebrokers.ie — de/trading/products-futures.php | Reached, no Nachschuss/Kleinanleger content (marketing page only) |
| interactivebrokers.ie — en/trading/products-options.php | Verified (product availability) |
| interactivebrokers.ie — PRIIPs pages (×3 URL guesses) | 404 / soft-404 |
| bafin.de — vf_190801_allgvfg_Differenzgeschaefte | Verified (CFD tier table) |
| bafin.de — vf_20220930_Allgemeinverfuegung...Futures | Verified (2022 futures measure) |
| lynxbroker.de — futureshandel-kleinanleger | Verified (broker-authoritative for IBKR's mechanism) |
| alpaca.markets/support/countries-alpaca-is-available | Reached; page itself states no policy |
| tradingeconomics.com/united-states/stock-market | Verified (SPX index level, dated input) |
| DuckDuckGo / Bing HTML (discovery only, ~10 queries) | Mixed — several yielded the BaFin-futures and LYNX URLs; later queries rate-limited (202) or returned no usable links |

---

## §8 Sanitization confirmation

No account numbers, API keys, or personal data appear anywhere in this note. The operator is referred
to only as "a German retail resident" throughout, consistent with the frozen document. All cited URLs
are public marketing/regulatory pages; no login-walled content was fetched or referenced.
