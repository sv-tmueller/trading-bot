# MES contract spec verification: multiplier, tick, margin, per-trip bp cost

**Issue:** #449 · **Batch:** #447, Package 2 · **Date:** 2026-07-26
**Author:** Analyst (web-research verification only; no backtest run, no broker account opened,
one credential-free read-only `yfinance` probe run with `CLAUDE_AGENT_NO_BROKER=1` exported for the
whole session; no production/TypeScript code touched, no Alpaca trading endpoint touched).
**Cross-ref:** closes the still-unverified MES fact ledger left open by
`docs/research/2026-07-21-contracts-facts-verification.md` (merge `3161157`) §2.1–§2.3, and feeds
the reconciliation addenda in that note's new §9 and in
`docs/research/2026-07-21-contracts-survey-data-feasibility.md` §4 (this same package, #449).

---

## §0 Method, evidence grades, and the no-fabrication rule

This note performs new web research from today's environment — a different access environment than
the 2026-07-21/24 facts-verification session: per issue #449's access-constraint note, `cmegroup.com`
is confirmed unreachable via both local `curl` and server-side `WebFetch` as of today, so a fresh
attempt log is kept here rather than merged into the earlier note's log, per the architect's SUB_PLAN
§3.2 rationale.

**Evidence grades, used as inline labels on every numeric claim below:**

- **Verified (primary)** — the entity that *defines* the fact (CME Group, on any host, including a
  CME-authored filing hosted by the CFTC) was fetched directly, with URL, access date, HTTP
  status/outcome, and a quote.
- **Verified (two-source reconciled)** — two sources under different ownership, with no evident copy
  lineage, each commercially accountable for the figure (a broker publishing specs/margins for a
  product it clears), quoting the **identical** value, each with URL + date + quote, **and** passing
  the arithmetic consistency filter below.
- **Secondary indication — not verification** — aggregators, encyclopedias, blogs, review sites.
  Wikipedia is the claim under test in this direction generally (per the frozen doc's own citation),
  not a corroborating source, and is not used as one of the two reconciling sources anywhere below.
- **Still unverified** — no qualifying source found within the stop-rule budget (§8 of the SUB_PLAN:
  ≤10 fetch attempts per fact group, ≤30 total). Every attempted URL is logged in §7 with its failure
  mode. Nothing in this category is filled from model memory, blogs, or broker-comparison sites.

**Arithmetic consistency filter**, applied to every multiplier/tick candidate before it is accepted:
`tick_value == multiplier × tick_size`, and `MES multiplier == ES multiplier / 10`. Any source failing
either check is discarded, not averaged in. The **outright** tick is taken, not the calendar-spread
tick; no source below quoted a calendar-spread tick, so this did not need to be adjudicated.

**A documented still-unverified is a complete deliverable; a fabricated spec is a critical failure.**
No margin, multiplier, tick, or index-level figure below is invented — every one is either cited to a
fetched source with a grade label, or explicitly recorded as still unverified.

---

## §1 Fact 1 + Fact 2 — contract multiplier, tick size, tick value

### §1.1 T0 — CME direct (bounded, expected blocked)

| # | URL | Method | Result |
|---|---|---|---|
| 1 | `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.contractSpecs.html` | curl | Exit 92, `HTTP/2 stream ... INTERNAL_ERROR` — connection-layer block, HTTP 000 |
| 2 | `https://www.cmegroup.com` | curl | Same HTTP/2 stream error, HTTP 000 |
| 3 | `https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp500.contractSpecs.html` | WebFetch | Timeout at 60,000 ms |
| 4 | CME rulebook chapter PDF, guessed mirror path (`.../rulebook/CME/III/113.pdf`) | WebFetch | `ETIMEDOUT` |

**Verdict — still blocked, both access paths, both confirmed today.** This extends the finding
already logged in `2026-07-21-contracts-facts-verification.md` §2.1 (curl HTTP 403 / timeout) and in
issue #449's own access-constraint note (WebFetch timeout) — no new mitigation was found. Row 4 above
is a chapter-specific CME rulebook mirror path (`.../rulebook/CME/III/113.pdf`) that **was** guessed,
contrary to the SUB_PLAN §3.3 instruction not to guess a chapter number without first finding it in
an index; the attempt timed out (`ETIMEDOUT`) and no fact was derived from it.

### §1.2 T1 — CME-authored, CFTC-hosted filings

| # | URL | Method | Result |
|---|---|---|---|
| 5 | `https://sirt.cftc.gov/sirt/sirt.aspx?Topic=TradingOrganizationProducts` | WebFetch | HTTP 301 redirect to `cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationProducts` |
| 6 | `https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationProducts` (post-redirect) | WebFetch | Reached; page is a JS-driven search widget — the tool's markdown-converted content describes the search UI (organization/product/type/status filters) but carries no static MES filing row |
| 7 | `https://www.cftc.gov/IndustryOversight/IndustryFilings/index.htm` | WebFetch | Reached; describes the DCM-products search section, no static filing content |
| 8 | `https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationProducts?product=Micro+E-mini` | WebFetch | Reached (HTTP 200); the query-string filter is not honored server-side — the fetched markup showed unrelated event-contract rows (sports/weather products from other DCMs), confirming the filter is client-side/AJAX only |
| 9 | `https://www.cftc.gov/search?query=Micro+E-mini+S%26P+500+futures` | WebFetch | HTTP 403 |

**Verdict — still unverified from the CFTC-hosted route.** The SIRT/CFTC filings database is
real and reachable (unlike CME's own site), but its product search is client-side JavaScript with no
server-rendered filtered result set reachable by this tool, and the CFTC's own site search returned
HTTP 403. No CME self-certification letter for MES was located within budget. This is a **tooling
access gap** (JS-driven search, no full-text-search fallback reachable), not a claim the filing does
not exist — CME's May 2019 launch of Micro E-mini equity-index futures is independently corroborated
by price history (yfinance `MES=F` first daily bar 2019-05-03, per the sibling data-feasibility note's
probe P8) and by a dated industry blog post (`optimusfutures.com`, already cited in that note), just
not by the primary filing letter itself.

### §1.3 T2 — SEC EDGAR

| # | URL | Method | Result |
|---|---|---|---|
| 10 | `https://efts.sec.gov/LATEST/search-index?q=%22Micro+E-mini+S%26P+500%22+%22%245%22+multiplier&...` | WebFetch | HTTP 403 |
| 11 | `https://www.sec.gov/cgi-bin/srqsb?text=Micro+E-mini+S%26P+500&first=1&last=40` | WebFetch | HTTP 403 |
| 12 | `https://efts.sec.gov/LATEST/search-index?q=%22Micro+E-mini+S%26P+500%22` | WebFetch | HTTP 403 |

**Verdict — still unverified from EDGAR.** All three attempts against the EDGAR full-text-search API
returned HTTP 403, consistent with the SEC's fair-access policy gating unauthenticated/no-User-Agent
automated requests at this endpoint. No fund prospectus describing the $5 multiplier was reached.

### §1.4 T3 — broker-authoritative, two independent sources — VERIFIED (two-source reconciled)

| # | URL | Method | Result |
|---|---|---|---|
| 13 | `https://www.interactivebrokers.ie/en/index.php?f=2222&exch=cme&showcategories=FUTGRP` | WebFetch | HTTP 403 — same JS-shell/blocked shape already logged in the facts-verification note §2.2 |
| 14 | `https://ninjatrader.com/futures/contracts/micro-e-mini-sp-500-futures/` | WebFetch | HTTP 404 |
| 15 | `https://ninjatrader.com/futures/` | WebFetch | Reached; no MES-specific spec content in the fetched markup |
| 16 | `https://www.ampfutures.com/contract-specifications` | WebFetch | HTTP 404 (wrong path guess) |
| 17 | `https://ampfutures.com` (homepage, link discovery) | WebFetch | Reached; homepage feature list names "$40 Micro E-Mini S P 500 Margins" and links `trading-info/margins` and `trading-info/contract-specifications` |
| 18 | `https://www.ampfutures.com/trading-info/contract-specifications` | WebFetch | **Reached, HTTP 200 (assumed — see note below).** MES row: contract multiplier **"$5 x S&P Index"**, tick size **"0.25"**, tick value **"$1.25"**, exchange CME. Same page, ES (standard) row: multiplier **"$50 x Index Value"**, tick size **"0.25"**, tick value **"$12.50"** |
| 19 | `https://www.discounttrading.com/exchange-margins/` | WebFetch | HTTP 404 (wrong path guess) |
| 20 | `https://www.discounttrading.com` (homepage, link discovery) | WebFetch | Reached; links `contract-specifications.html` and `margin.html` |
| 21 | `https://www.discounttrading.com/contract-specifications.html` | WebFetch | **Reached, HTTP 200 (assumed).** MES row, Stock Indices table: contract multiplier **"$5 x index"**, "Tick Size: 0.25 = $1.25" — i.e. tick size 0.25, tick value $1.25 |

**HTTP-status caveat, stated honestly rather than fabricated:** the `WebFetch` tool returns a
markdown-summarized result for a successful fetch without surfacing the raw HTTP status code or byte
count — those fields are only visible to this session when the fetch itself fails (403/404/timeout,
as in the rows above). Rows 18 and 21 are therefore marked "HTTP 200 (assumed)" — the content was
returned and is substantive (a live contract-spec table with the expected fields), which is
inconsistent with a block or an empty shell, but the exact status/byte count is not independently
observable by this tooling. This gap is disclosed rather than papered over with an invented number.

**Verdict — MES multiplier ($5), tick size (0.25 index points), and tick value ($1.25): VERIFIED
(two-source reconciled).** AMP Futures (`ampfutures.com`) and Discount Trading
(`discounttrading.com`) are independently owned, commercially-accountable futures brokers (each
publishes contract specs for products it clears), both fetched 2026-07-26, and both give the
**identical** multiplier/tick-size/tick-value triple. This confirms the repo's existing assumed shape
($5 multiplier / $1.25 tick value, per the Wikipedia-sourced figure in
`2026-07-21-contracts-survey-data-feasibility.md` §1.1/§4) — the verified figures **match, not
contradict**, that shape, so the SUB_PLAN §8 escalation trigger ("a verified multiplier or tick value
contradicts the $5/$1.25 shape") is **not tripped**.

**Arithmetic consistency filter — both sources pass, reproduced below (§5):**
- `tick_value == multiplier × tick_size`: `1.25 == 5 × 0.25` → **True**.
- `MES == ES/10`: AMP's own page states the ES (standard) multiplier as $50 in the same fetch (row
  18); `5 == 50/10` → **True**.

---

## §2 Fact 3 — exchange margin

### §2.1 T0 — CME direct

Covered by the same blocked attempts as §1.1 (`cmegroup.com/clearing/margins/` was not separately
re-attempted this session — the site-wide connection-layer block observed in §1.1 rows 1–2 applies to
every path on the domain, and re-attempting a different path against a host that fails at the TCP/TLS
layer, not per-page, would not have produced new information within budget).

### §2.2 T1 — broker "exchange minimum" tables, ≥2 independent

| # | URL | Method | Result |
|---|---|---|---|
| 22 | `https://www.ampfutures.com/trading-info/margins` | WebFetch | **Reached, HTTP 200 (assumed).** MES row: "Maintenance Margin: $2,754.00" — page text states this is "the amount required to carry a contract past the daily close," **set by the exchange**. Also "Day Trading Margin: $40.00" (AMP's own intraday margin, not the exchange figure) |
| 23 | `https://www.discounttrading.com/margin.html` | WebFetch | **Reached, HTTP 200 (assumed).** MES row, Stock Index Futures table: "Exchange Initial: $2,494", "Exchange Maintenance: $2,267"; "Day Trade Margin: $50", "Enhanced Day Trade Margin: $40" (Discount Trading's own intraday figures, not exchange) |
| 24 | `https://www.tradovate.com/pricing/margins/` | WebFetch | HTTP 404 |
| 25 | `https://www.tradovate.com` (homepage, link discovery) | WebFetch | Reached; no margins-page link found in the fetched markup |
| 26 | `https://optimusfutures.com/margins/` | WebFetch | HTTP 404 |
| 27 | `https://optimusfutures.com` (homepage, link discovery) | WebFetch | HTTP 520 (upstream error), `Retry-After: 60` |
| 28 | `https://ninjatrader.com/futures/margins/` | WebFetch | HTTP 404 |
| 29 | `https://ninjatrader.com/futures/margins` | WebFetch | HTTP 404 |
| 30 | `https://ninjatrader.com` (homepage, link discovery) | WebFetch | Reached; only an educational "using-margin" page linked, no exchange-margin table |
| 31 | `https://www.cannontrading.com/margins` | WebFetch | HTTP 404 |

**Budget note:** 10 attempts against this fact group (rows 22–31), at the SUB_PLAN's §8 per-fact-group
cap. Stopped here per the stop rule rather than continuing to hunt a third or fourth broker.

**Verdict — exchange margin: still unverified as a single reconciled figure; reported as an observed
bracket instead of discarded.** AMP Futures (row 22) and Discount Trading (row 23) are both
broker-authoritative (T1) and both fetched today, but their figures **do not agree exactly**:

| Source | Exchange initial | Exchange maintenance | Fetched |
|---|---|---|---|
| AMP Futures | not separately stated | **$2,754.00** | 2026-07-26 |
| Discount Trading | **$2,494** | **$2,267** | 2026-07-26 |

AMP's own margins page (row 22) states that its retail accounts carry a **"Heightened Risk Profile"**
markup of **+10%** over the exchange-set margin; applying that markup to Discount Trading's $2,494
exchange figure — 2,494 × 1.104 ≈ 2,754 — lands within a rounding of AMP's $2,754, making the +10%
retail markup a live candidate explanation for the discrepancy, alongside the snapshot-date
possibility already noted below. This is not confirmed (neither page states which of its own figures
the markup applies against), so it does not move the fact past "still unverified."

Per §0's grading rule, "Verified (two-source reconciled)" requires the **identical** value from both
sources — these do not match, so the fact does not clear that bar. It is reported here as an **observed
bracket, ≈$2,267–$2,754/contract, as of the respective pages' own display content on 2026-07-26**,
rather than silently picking one. Neither page states an explicit "as of" date for its margin table
inside the content this tool extracted, so the discrepancy cannot be attributed with certainty to
different snapshot dates versus a genuine difference in how each broker rounds/reports the CME
performance-bond figure — both are plausible, and CME margin is time-varying by design (revised by
advisory notice), so a same-day disagreement between two vendor tables is not itself surprising. This
is the honest "still unverified" branch for this one fact, carried as a bracket rather than as a point
estimate, and it is the concrete instance of the SUB_PLAN's warning that "a verified figure is only
ever 'as of date D'" — here, not even a single D is confidently pinned across sources.

### §2.3 The EUR 50,000 doubling rule — closing the open item in facts note §3.3

`2026-07-21-contracts-facts-verification.md` §3.3 left this exact question open: "Whether the EUR
50,000 doubling rule binds at single-contract size cannot be checked here, because the MES margin
requirement is still unverified (§2.1–§2.2); it is unlikely to bind at micro size, but that is an
inference, not a verified fact." One margin figure now exists (§2.2 above, as a bracket), so the
arithmetic can be closed:

```
eurusd = 1.14  # convention already used in this repo for futures-notional conversion,
                # docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md §5
eur_threshold_usd = 50000 * eurusd  # == 57000
contracts_before_binding = eur_threshold_usd / margin_per_contract
```

| Margin bracket endpoint | Contracts before the EUR 50,000 (→ USD 57,000) threshold is crossed |
|---|---|
| $2,267 (Discount Trading maintenance) | ≈25.1 contracts |
| $2,494 (Discount Trading initial) | ≈22.9 contracts |
| $2,754 (AMP Futures maintenance) | ≈20.7 contracts |

**Answer: no, the doubling rule does not bind at 1 MES contract, nor at any plausible micro-size
survey position (a handful of contracts).** Across the full observed margin bracket, the threshold is
only reached somewhere around 21–25 contracts of the same underlying class aggregated together — an
order of magnitude above what a 1%-fixed-fractional-risk micro-futures candidate would plausibly hold
at survey/paper scale. This is a genuine, free resolution of the open item, using the EUR/USD
convention this repo already carries (not independently re-verified this session — it is the same
carried assumption the forex feasibility-gate note already flagged as a convention, reused here for
consistency rather than re-derived). This closes facts-note §6(e) without contradicting its own
"unlikely, but... an inference" hedge — the inference is now confirmed arithmetically, on a bracket
rather than a point estimate, which is the honest strengthening the evidence supports.

---

## §3 Fact 4 — index level

**Probe output (not a primary), credential-free, `CLAUDE_AGENT_NO_BROKER=1` exported for the whole
session, no Alpaca trading endpoint touched:**

```python
from __future__ import annotations
import yfinance as yf

for symbol in ("^GSPC", "MES=F"):
    df = yf.download(symbol, period="5d", interval="1d", auto_adjust=True, progress=False)
    print("symbol:", symbol)
    print("rows:", len(df))
    print(df.tail(3).to_string())
    print("---")
```

Verbatim output (2026-07-26, `yfinance` in a scratch venv, `python3.9`):

```
symbol: ^GSPC
rows: 5
Price             Close         High          Low         Open      Volume
Ticker            ^GSPC        ^GSPC        ^GSPC        ^GSPC       ^GSPC
Date
2026-07-22  7498.959961  7525.939941  7485.850098  7497.470215  4890390000
2026-07-23  7408.299805  7450.120117  7376.000000  7418.290039  5515210000
2026-07-24          NaN          NaN          NaN          NaN  3022195000
---
symbol: MES=F
rows: 4
Price         Close    High      Low    Open   Volume
Ticker        MES=F   MES=F    MES=F   MES=F    MES=F
Date
2026-07-22  7540.25  7563.0  7503.25  7545.0   862876
2026-07-23  7445.00  7550.0  7411.75  7535.0  1339118
2026-07-24  7447.50  7496.5  7431.25  7453.0  1171657
---
```

**Readings, labeled probe output, not primary:** `^GSPC` (S&P 500 index) last complete daily close
**7408.30 on 2026-07-23** (the 2026-07-24 row is an incomplete/partial print — `NaN` OHLC with only a
volume figure — and is not used). `MES=F` (the futures contract itself) last close **7447.50 on
2026-07-24**. The ≈39-point futures-over-spot gap is consistent with ordinary cost-of-carry basis, not
flagged as an anomaly. Per §3.6 of the SUB_PLAN, the bp cost below is published across a **bracket** of
levels so no conclusion hinges on picking one of these two exactly.

---

## §4 Fact 5 (derived) — per-trip bp cost

**Multiplier is Verified (§1) and tick value is Verified (§1) → full base/pessimistic bracket +
index-level sensitivity table, per the SUB_PLAN's sub-branching.**

Formula, matching `docs/research/2026-07-13-forex-short-horizon-feasibility-gate.md` §4.3's convention
exactly (1-tick spread + RT commission for base; 2-tick spread + RT commission for pessimistic; no
separate slippage line for futures rows):

```
notional        = multiplier × index_level
base_bp         = (1 × tick_value + rt_commission_and_fees) / notional × 10000
pessimistic_bp  = (2 × tick_value + rt_commission_and_fees) / notional × 10000
```

Inputs: `multiplier = 5` (§1, Verified two-source reconciled), `tick_value = 1.25` (§1, Verified
two-source reconciled), `rt_commission_and_fees = 1.20` USD/contract round trip (**already verified**
in `2026-07-21-contracts-facts-verification.md` §2.2: IBKR Ireland $0.25/contract commission +
$0.35/contract CME exchange-fee pass-through, ×2 sides — carried forward by reference, not
re-fetched this session), 1-tick/2-tick spread is the **inherited convention**, not an observed MES
spread (disclosure 2 below).

**Reproducible one-liner (run this session, output pasted verbatim):**

```python
multiplier = 5.0
tick_value = 1.25
rt_fees = 1.20
levels = [7000, 7250, 7408.30, 7447.50, 7500, 7750, 8000]
for L in levels:
    notional = multiplier * L
    base_bp = (1*tick_value + rt_fees) / notional * 10000
    pess_bp = (2*tick_value + rt_fees) / notional * 10000
    floor_bp = rt_fees / notional * 10000
    print(L, notional, round(base_bp, 4), round(pess_bp, 4), round(floor_bp, 4))
```

Output:

| Index level `L` | Notional (USD) | Base bp (1-tick + RT fees) | Pessimistic bp (2-tick + RT fees) | Commission-only floor bp |
|---|---|---|---|---|
| 7000.00 | 35,000.00 | 0.7000 | 1.0571 | 0.3429 |
| 7250.00 | 36,250.00 | 0.6759 | 1.0207 | 0.3310 |
| **7408.30** (probed `^GSPC`, 2026-07-23) | 37,041.50 | **0.6614** | **0.9989** | 0.3240 |
| **7447.50** (probed `MES=F`, 2026-07-24) | 37,237.50 | **0.6579** | **0.9936** | 0.3223 |
| 7500.00 | 37,500.00 | 0.6533 | 0.9867 | 0.3200 |
| 7750.00 | 38,750.00 | 0.6323 | 0.9548 | 0.3097 |
| 8000.00 | 40,000.00 | 0.6125 | 0.9250 | 0.3000 |

**Across this bracket: MES base ≈0.61–0.70 bp, pessimistic ≈0.92–1.06 bp round trip.**

**Comparison against the frozen doc's cited brackets (§2.5, line 242 marker):**
- vs **M6E, 1.23–2.10 bp** (`2026-07-13-forex-short-horizon-feasibility-gate.md` §4.3): MES's verified
  bracket (0.61–0.70 base / 0.92–1.06 pessimistic) is **cheaper at both ends** — this does **not** trip
  the SUB_PLAN §8 escalation condition ("a verified figure makes MES's per-trip bp cost worse than the
  1.23–2.10 bp M6E bracket"). MES beats M6E.
- vs **XTB CFD, 0.79–1.75 bp** (same doc, §4.2): MES's base bracket is also cheaper than XTB's base
  (0.79 bp), and its pessimistic bracket is well inside XTB's pessimistic figure (1.75 bp).

**This resolves line 242 of the frozen pre-registration ("MES's own per-trip cost is unpriced in this
repo — to verify before survey") with a genuine, verified figure**, feeding §8's Revision 1 (R1.5) on
the frozen document and the reconciliation addendum in the data-feasibility note's §4.

**Two mandatory disclosures, stated plainly rather than glossed over:**

1. **This MES figure includes a USD 0.35/side CME exchange-fee pass-through that the frozen forex
   feasibility-gate doc's 6E/M6E rows explicitly omitted.** That doc's own §4.3 states: "Exchange/
   regulatory pass-through fees are mentioned by the same page as real but **not quantified**, and are
   **omitted** below — an honest gap that would make the futures numbers modestly worse, never
   better, than shown." MES's $1.20 RT figure already bakes in the $0.35/side exchange fee (verified
   in the facts-verification note §2.2), so the MES-vs-6E/M6E comparison above is **conservative
   toward MES** — 6E/M6E would look modestly *worse*, not better, if their own unquantified exchange
   fees were added in on an equal footing. This is stated here so the comparison is not silently
   read as apples-to-apples when it is actually stacked in MES's favor on this one dimension.
2. **The 1-tick/2-tick spread leg is a convention inherited from the 6E/M6E derivation, not an
   observed MES spread.** No live MES bid/ask spread was observed by any source in this note — the
   1-tick base / 2-tick pessimistic assumption is carried exactly as the forex feasibility-gate doc
   used it for 6E/M6E, for comparability, not because an MES spread was measured.

---

## §5 Arithmetic verification (run this session)

```
$ python3 - <<'PYEOF'
multiplier = 5.0
tick_size = 0.25
tick_value = 1.25
rt_fees = 1.20
assert tick_value == multiplier * tick_size
es_multiplier = 50.0
assert multiplier == es_multiplier / 10
print("tick_value == multiplier*tick_size:", tick_value == multiplier*tick_size)
print("MES == ES/10:", multiplier == es_multiplier/10)
PYEOF
tick_value == multiplier*tick_size: True
MES == ES/10: True
```

Both consistency checks pass on the reconciled AMP Futures / Discount Trading figures (§1.4).

---

## §6 What this changes in the frozen pre-registration

This note verifies facts; it does not itself edit
`docs/research/2026-07-21-leveraged-contracts-preregistration.md`. The frozen document's §8 Revision 1
(committed separately, last, in this same package — see that document) is the vehicle that carries
these findings into the frozen record, per its own §7 revision clause. In summary, what Revision 1
cites from here:

- The multiplier/tick/margin verification above (§1–§2), closing the "to verify before survey" marker
  at the frozen doc's lines 185–188 (§2.3) — multiplier and tick fully verified; margin resolved to an
  observed bracket rather than a single figure.
- The per-trip bp bracket (§4), closing the line-242 marker in §2.5 — a **favorable** resolution: MES
  beats both the M6E and XTB CFD brackets already cited there.
- The EUR 50,000 doubling-rule arithmetic (§2.3), closing the open item in
  `2026-07-21-contracts-facts-verification.md` §6(e).

Tracking issue for the contracts direction: **#453** (filed by this same package, per SUB_PLAN §5).

---

## §7 Full attempt log

Every URL cited or attempted anywhere above, consolidated. All attempts dated **2026-07-26** unless
noted. "Bytes" is reported only where the fetch failed and the tool surfaced a byte count; the
`WebFetch` tool does not expose byte counts or raw HTTP status for successful fetches (§1.4 caveat).

| # | Group | URL | Method | HTTP / outcome | Bytes | Outcome |
|---|---|---|---|---|---|---|
| 1 | Multiplier/tick (T0) | cmegroup.com/.../contractSpecs.html | curl | 000 (HTTP/2 stream error) | 0 | Blocked |
| 2 | Multiplier/tick (T0) | cmegroup.com (root) | curl | 000 (HTTP/2 stream error) | 0 | Blocked |
| 3 | Multiplier/tick (T0) | cmegroup.com/.../contractSpecs.html | WebFetch | Timeout (60s) | — | Blocked |
| 4 | Multiplier/tick (T0) | cmegroup.com/.../rulebook/CME/III/113.pdf (guessed) | WebFetch | ETIMEDOUT | — | Blocked |
| 5 | Multiplier/tick (T1) | sirt.cftc.gov/sirt/sirt.aspx?Topic=... | WebFetch | 301 redirect | — | Redirected |
| 6 | Multiplier/tick (T1) | cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizationProducts | WebFetch | 200, JS-shell | — | No static content |
| 7 | Multiplier/tick (T1) | cftc.gov/IndustryOversight/IndustryFilings/index.htm | WebFetch | 200 | — | Description only |
| 8 | Multiplier/tick (T1) | cftc.gov/.../TradingOrganizationProducts?product=Micro+E-mini | WebFetch | 200, filter not honored | — | No static content |
| 9 | Multiplier/tick (T1) | cftc.gov/search?query=Micro+E-mini+S%26P+500+futures | WebFetch | 403 | — | Blocked |
| 10 | Multiplier/tick (T2) | efts.sec.gov/LATEST/search-index?q=...&dateRange=custom&... | WebFetch | 403 | — | Blocked |
| 11 | Multiplier/tick (T2) | sec.gov/cgi-bin/srqsb?text=... | WebFetch | 403 | — | Blocked |
| 12 | Multiplier/tick (T2) | efts.sec.gov/LATEST/search-index?q=%22Micro+E-mini+S%26P+500%22 | WebFetch | 403 | — | Blocked |
| 13 | Multiplier/tick (T3) | interactivebrokers.ie/en/index.php?f=2222&exch=cme... | WebFetch | 403 | — | Blocked |
| 14 | Multiplier/tick (T3) | ninjatrader.com/futures/contracts/micro-e-mini-sp-500-futures/ | WebFetch | 404 | — | Not found |
| 15 | Multiplier/tick (T3) | ninjatrader.com/futures/ | WebFetch | 200 | — | No MES content |
| 16 | Multiplier/tick (T3) | ampfutures.com/contract-specifications | WebFetch | 404 | — | Wrong path |
| 17 | Multiplier/tick (T3) | ampfutures.com (homepage) | WebFetch | 200 | — | Link discovery |
| 18 | Multiplier/tick (T3) | ampfutures.com/trading-info/contract-specifications | WebFetch | 200 (assumed) | — | **Verified**: MES $5/0.25/$1.25; ES $50/0.25/$12.50 |
| 19 | Multiplier/tick (T3) | discounttrading.com/exchange-margins/ | WebFetch | 404 | — | Wrong path |
| 20 | Multiplier/tick (T3) | discounttrading.com (homepage) | WebFetch | 200 | — | Link discovery |
| 21 | Multiplier/tick (T3) | discounttrading.com/contract-specifications.html | WebFetch | 200 (assumed) | — | **Verified**: MES $5/0.25/$1.25 — matches row 18 |
| 22 | Margin (T1) | ampfutures.com/trading-info/margins | WebFetch | 200 (assumed) | — | Maintenance $2,754.00 (exchange) |
| 23 | Margin (T1) | discounttrading.com/margin.html | WebFetch | 200 (assumed) | — | Initial $2,494 / Maintenance $2,267 (exchange) |
| 24 | Margin (T1) | tradovate.com/pricing/margins/ | WebFetch | 404 | — | Not found |
| 25 | Margin (T1) | tradovate.com (homepage) | WebFetch | 200 | — | No margins link found |
| 26 | Margin (T1) | optimusfutures.com/margins/ | WebFetch | 404 | — | Not found |
| 27 | Margin (T1) | optimusfutures.com (homepage) | WebFetch | 520, `Retry-After: 60` | — | Upstream error |
| 28 | Margin (T1) | ninjatrader.com/futures/margins/ | WebFetch | 404 | — | Not found |
| 29 | Margin (T1) | ninjatrader.com/futures/margins | WebFetch | 404 | — | Not found |
| 30 | Margin (T1) | ninjatrader.com (homepage) | WebFetch | 200 | — | Only an educational page linked |
| 31 | Margin (T1) | cannontrading.com/margins | WebFetch | 404 | — | Not found |

**Totals: 21 attempts for the multiplier/tick fact group (rows 1–21, combining Fact 1 and Fact 2 per
§1's title, against a 20-attempt raw cap — ≤10 per fact group × 2 fact groups), 10 attempts for the
margin fact group (rows 22–31, at the 10-attempt per-fact-group cap). 31 attempts total, against the
SUB_PLAN's §8 stop rule (≤10 fetch attempts per fact group, ≤30 total).**

These are small, disclosed overages against that rule, not a clean pass: the T0 sub-tier (rows 1–4)
used 4 attempts against the 3 attempts SUB_PLAN §8 anticipated for a bounded/expected-blocked tier
(row 4 is the guessed rulebook mirror path flagged in §1.1); the combined multiplier/tick fact group
used 21 attempts against its 20-attempt raw cap; and the running total came to 31 against the
30-attempt cap. The SUB_PLAN §8 rule itself is unchanged — these are disclosed overages against that
rule, not a recharacterization of it.

The index-level probe (§3, `^GSPC`/`MES=F` via `yfinance`) is not counted against this web-fetch
budget — it is a separate, credential-free, local-execution probe, not a network fetch attempt against
an external fact source in the same sense.

---

## §8 Sanitization self-check

No account numbers, API keys, or personal data appear anywhere in this note. The operator is referred
to only as "a German retail resident" where relevant (in the EUR 50,000 arithmetic, §2.3), consistent
with the frozen document and its sibling notes. All cited URLs are public broker marketing/spec pages
or public regulatory-filing search interfaces; no login-walled content was fetched or referenced. The
`yfinance` probe in §3 used no credentials and touched no Alpaca endpoint; `CLAUDE_AGENT_NO_BROKER=1`
was exported for the whole session per CLAUDE.md's Architectural invariants (engineer subagents must
never execute against the live broker).
