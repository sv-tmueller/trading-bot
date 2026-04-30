From __future__ note: this is a research memo, not code. No `from __future__ import annotations` required.

# Alpaca European Market Access — Vendor Investigation

- **Status**: `confirmed-shipped` (with caveats — see Verification)
- **Researched**: 2026-04-30
- **Researcher**: Claude (Team Leader subagent)
- **Branch**: `research/alpaca-eu-expansion`

---

## TL;DR

- **Confirmed shipped on 2026-04-21**: Alpaca closed its acquisition of UK/Spanish fintech WealthKernel (rebranded **Alpaca Europe**) and turned on **Xetra (Germany)** equities trading the same day. Euronext and LSE are flagged as "expected to follow" with no public ETA.
- **Regulated via WealthKernel Limited (FCA #723719)** and **WealthKernel Spain A.V., S.L.U. (CNMV #328)**. No BaFin entity — German market access is delivered through the FCA/CNMV stack via MiFID II passporting, not a separate German broker-dealer.
- **The launch is B2B Broker-API-only**, not Trading-API. Every primary and secondary source frames it as infrastructure for "fintechs, banks, and brokers" to embed European investing into their own apps. There is no announcement of EU access for self-directed Alpaca developer accounts (i.e. our use case).
- **`alpaca-py` SDK has no EU surface as of 2026-04-30.** Latest release v0.43.4 (2026-04-29, 8 days *after* the EU announcement) contains zero references to Xetra, Euronext, Europe, or EUR. Recent commits are unrelated (Broker-API document-type enum fix, pytz dep). No new base URL, no new `DataFeed` enum value, no new exchange enum.
- **Implication for our bot**: this changes nothing actionable today. We cannot trade SAP.DE on Xetra from our existing paper account or our existing `alpaca-py` install. Treat as a watch item — re-check in ~Q3 2026 once a retail Trading-API surface or SDK update lands.

---

## Verification

### What is officially announced (primary sources)

The canonical announcement is on Alpaca's own blog, published **2026-04-21**:

> **"Alpaca Expands into Europe and Launches European Equities Trading"**
> https://alpaca.markets/blog/alpaca-expands-into-europe-and-launches-european-equities-trading/

Confirmed by parallel BusinessWire press release of the same date:

> https://www.businesswire.com/news/home/20260421441080/en/Alpaca-Expands-into-Europe-with-WealthKernel-Acquisition-and-Launch-of-European-Equities-Trading

Earlier announcement of the *intent* to acquire WealthKernel (then subject to FCA/CNMV approval) was published **2025-07-10**:

> https://alpaca.markets/blog/alpaca-enters-uk-and-eu-market-through-wealthkernel-acquisition/

The 2026-04-21 post is the closing-and-launch event; the 2025-07-10 post is the deal announcement nine months earlier.

### What is rumoured but not yet supported

- **Euronext (Paris/Amsterdam/Lisbon/Brussels)** — described as "expected to follow" with no public ETA. Not live.
- **London Stock Exchange (LSE)** — same status. Not live.
- **HKEX, Tadawul, ADX** — mentioned as future expansion targets in the same announcement. Not live.

### What is unverified / not addressed in any source

The following questions are *not answered* by any of the sources I located. Marking these explicitly because the user's brief asked for them and silence is itself a finding:

- **Is the EU offering available via the existing Trading API or only via Broker API?** The wording across all sources is unambiguously B2B-Broker-API ("enable fintechs and financial institutions to offer investing"). No source confirms self-directed retail/developer access on Xetra. Inferred answer: **Broker-API only at launch.** This needs explicit confirmation from Alpaca support before we can plan any integration.
- **Do existing US Alpaca developer accounts get Xetra access automatically?** No source addresses this. Given the entity separation (Alpaca Europe = FCA-regulated WealthKernel Limited, distinct from Alpaca Securities LLC = US FINRA broker-dealer), separate KYC and a separate account is the structurally likely answer, but unconfirmed.
- **Bracket-order support on Xetra?** No source mentions order types on EU venues. Alpaca's US Trading API supports bracket orders fully (`OrderClass.BRACKET` in `alpaca-py`). Whether the Xetra venue accepts the same bracket primitive — particularly the OCO leg pair for take-profit + stop-loss — is unverified.
- **Pricing / commissions on EU markets.** No source quotes a fee schedule. The US "commission-free" framing explicitly applies to "U.S.-listed securities and options" only.
- **Data feed name (analogue of `IEX` / `SIP`).** No source names the EU market-data feed. The `DataFeed` enum in `alpaca-py` v0.43.4 still contains only `IEX`, `SIP`, `OTC` (US-equity-only).
- **EU base URL / new SDK surface.** No source mentions a new base URL or a new SDK package. The `alpaca-py` repo has had zero EU-related commits in the 8 days since the announcement.

### Scepticism check

- The 2026-04-21 announcement is corroborated by independent secondary sources published the same day (Crowdfund Insider, fintech.global, Finance Magnates, IBS Intelligence, Morningstar reprint of BusinessWire). This is not a leaked roadmap — it is a press-released, regulator-aligned launch. **The launch itself is real.**
- However, the secondary sources all *paraphrase the same press release* — they do not add independent technical detail. None of them have hands-on with the EU API. Treat all "API integration" claims as marketing language until docs land.
- The Alpaca developer-docs site (`docs.alpaca.markets`) has **no EU content** as of 2026-04-30 (verified by direct fetch). This is the single biggest red flag for treating Xetra as production-ready from a developer perspective: the public docs predate the launch.

---

## Scope (what's actually live)

### Markets / instruments

| Venue | Country | Status (2026-04-30) | Source |
|---|---|---|---|
| **Xetra** | DE | Live | Alpaca blog 2026-04-21 |
| Euronext (Paris/AMS/LIS/BRU) | EU | "Expected to follow" — no ETA | Alpaca blog 2026-04-21 |
| LSE | UK | "Expected to follow" — no ETA | Alpaca blog 2026-04-21 |
| HKEX | HK | "In development" | Alpaca blog 2026-04-21 |
| Tadawul, ADX | SA / AE | "In development" | Alpaca blog 2026-04-21 |

**Instruments**: equities only is explicit at launch. ISAs and SIPPs (UK tax wrappers) are inherited from WealthKernel but those are account *types*, not instrument types. ETFs/options/fixed-income/crypto on EU markets: **not announced**.

### Regulatory entity stack

- **Alpaca Europe** = trading name of **WealthKernel Limited** (UK).
  - FCA reference **723719**.
  - CNMV (Spain) registration **328** via the sister entity **WealthKernel Spain A.V., S.L.U.**
  - German Xetra access delivered via MiFID II passporting from FCA/CNMV. **No BaFin licence.**
- Distinct legal entity from US-side Alpaca Securities LLC. Two separate broker-dealers under one corporate parent.

### API surface (what is *not* yet there)

- No new SDK package. `alpaca-py` v0.43.4 (2026-04-29) is unchanged with respect to EU support.
- No EU base URL has been published. Existing base URLs:
  - `https://paper-api.alpaca.markets` (US paper)
  - `https://api.alpaca.markets` (US live)
  - `https://data.alpaca.markets/v2` (US market data)
- No new `DataFeed` enum value beyond `IEX` / `SIP` / `OTC`.
- No new exchange constant for Xetra in `alpaca-py` enums.
- The acquisition rationale framed in the 2025-07-10 post is "global Broker API" — the EU surface is almost certainly going to land on the Broker API first (i.e. for partners onboarding their own end users), with the developer-facing Trading API following separately or not at all.

---

## Implications for our bot

### What changes today: nothing

We cannot, today:
- Add a Xetra ticker (e.g. `SAP.DE`) to our universe and have `tools/market_data.py::fetch_bars` return data for it. The `DataFeed.IEX` / `DataFeed.SIP` enum has no EU equivalent.
- Submit a bracket order against Xetra via `tools/broker.py::place_market_order`. The `TradingClient` is hard-coded to US base URLs and US asset classes.
- Open a self-directed Alpaca Europe account and connect our existing API keys to it. The launch announcement does not describe such a flow.

### What changes for our roadmap

#### `tools/broker.py` and `alpaca-py`

No code change required now. When (if) Alpaca exposes EU markets to the Trading API, the integration is likely to be:
- A new base URL (e.g. `https://api.alpaca-europe.markets` — speculation).
- A new asset-class string in `Asset.asset_class` for EU equities, parallel to `us_equity` / `us_option` / `crypto`.
- Possibly a new `TradingClient` constructor argument or environment hint.

None of this is buildable today.

#### PR #93 / issue #95 (BaseBroker ABC + AlpacaBroker adapter)

**Confirmation: the abstraction shape in PR #93 still holds, but with a caveat.** The five abstract methods (`place_market_order`, `close_position`, `get_portfolio_value`, `get_positions`, `get_current_price`) are venue-agnostic — they do not bake in US-equity assumptions and would translate cleanly to a future `AlpacaEuropeBroker` adapter.

The caveat: **currency**. Our portfolio is USD-denominated (`get_portfolio_value() -> float` returns a single scalar). A multi-venue future would need a currency-aware shape (either fixed-base USD with FX conversion at the broker boundary, or per-currency sub-accounts). PR #93's contract document does not call this out. Recommend not blocking PR #93 on this — instead, file a follow-up issue **after** Alpaca publishes EU trading-API docs, since the right shape depends on Alpaca's own currency handling.

For now: PR #93's "preserve `tools/broker.py` byte-identical" invariant remains correct. EU support is a **new** adapter (`tools/brokers/alpaca_europe.py`) when the API surface exists, not a modification to the existing `AlpacaBroker`.

#### `tools/market_data.py` (data-feed env var)

`settings.DATA_FEED` (currently `iex` | `sip`) will need to be extended *if and when* Alpaca publishes an EU data feed name. The validation in `config/settings.py:25-27` is the single point of change:

```python
DATA_FEED = os.getenv("DATA_FEED", "iex").lower()
if DATA_FEED not in ("iex", "sip"):
    raise ValueError(...)
```

Inferred future shape: add an EU value (name TBD — neither Alpaca's blog nor any secondary source has named it). Until then, no change.

#### `config/settings.py` (currency assumptions)

Currently implicit: every dollar amount in settings (`RISK_PER_TRADE`, `MAX_PORTFOLIO_EXPOSURE` as a fraction of an implicit USD account) assumes a single currency. EU support introduces:
- EUR-denominated trades (Xetra) and GBP-denominated trades (LSE).
- FX conversion fees on settlement (not announced; flagged in user brief).
- Per-currency or single-currency-with-FX bookkeeping in `storage/schema.sql::trades`.

**No code change today.** Note this for the day Alpaca publishes commission and FX schedules.

#### Universe / morning scan

Our universe is hard-coded US-equity in the morning scan. Adding Xetra would introduce:
- **Timezone**: Xetra trades 09:00–17:30 CET (UTC+1/+2 with DST). Our cron at `25 13 * * 1-5` UTC fires 5 min before NYSE open — that's 14:25 CET, mid-Xetra-session. Running pre-Xetra-open requires a separate cron (~07:55 CET).
- **Holiday calendar**: TARGET2 / German bank holidays differ from NYSE. `pandas_market_calendars` has an `XETR` calendar; would need to be plumbed through.
- **Volume-ratio comparability**: our `volume_ratio` signal in `tools/market_data.py::compute_signals` uses 20-day average. EU equity volumes are markedly lower than US equivalents — the threshold (`VOLUME_MULTIPLIER=1.5`) likely needs re-calibration per market.
- **Currency in screening**: ATR-based stops in `tools/risk.py` need to know the trade currency to compute share-size from a USD risk budget.

This is enough work that **we should not silently bolt EU tickers onto the existing universe** when the API opens up. It warrants its own design issue.

#### Bracket-order coverage

Flagged risk: our risk model **depends on bracket orders firing server-side** (CLAUDE.md "Stops and take-profits execute server-side via Alpaca bracket orders"). If Xetra access does not support `OrderClass.BRACKET` (or supports it with a different leg semantic), our existing risk invariant breaks. The position-monitor soft-stop is defense-in-depth and not a substitute.

**Recommended posture**: when EU Trading-API docs land, the first integration test must be "submit a Xetra bracket order in paper, verify both TP and SL legs are accepted server-side." If brackets are not supported, EU access is gated until they are — we do not run EU positions on the soft-stop alone.

---

## Open questions (resolution path)

| Question | How to find out |
|---|---|
| Is EU access available on the Trading API or only Broker API? | Wait for `docs.alpaca.markets` to add an EU section, or email `support@alpaca.markets`. |
| Does an existing US developer account get Xetra access? | Same. Likely no — separate FCA-regulated entity. |
| What is the EU `DataFeed` name? | Wait for `alpaca-py` SDK update or docs publication. |
| Are bracket orders supported on Xetra? | Same. **This is the gating question for any integration work.** |
| EU commission schedule and FX fees? | Pricing page update or support enquiry. |
| Is there an EU paper-trading endpoint? | SDK / docs update. |

Suggested concrete next step: **set a calendar reminder for 2026-07-30 (Q3 start)** to re-check `docs.alpaca.markets` and `github.com/alpacahq/alpaca-py` releases for EU surface area. If still empty, no further investigation is needed until something material changes — the rumour is real, but the developer-facing surface is not.

---

## Sources

Primary (official Alpaca):
- Alpaca blog, "Alpaca Expands into Europe and Launches European Equities Trading", 2026-04-21 — https://alpaca.markets/blog/alpaca-expands-into-europe-and-launches-european-equities-trading/
- Alpaca blog, "Alpaca Enters UK and EU Market through WealthKernel Acquisition", 2025-07-10 — https://alpaca.markets/blog/alpaca-enters-uk-and-eu-market-through-wealthkernel-acquisition/
- BusinessWire press release, 2026-04-21 — https://www.businesswire.com/news/home/20260421441080/en/Alpaca-Expands-into-Europe-with-WealthKernel-Acquisition-and-Launch-of-European-Equities-Trading
- Alpaca developer docs (no EU content as of 2026-04-30) — https://docs.alpaca.markets/
- `alpaca-py` GitHub releases (latest v0.43.4 on 2026-04-29, no EU content) — https://github.com/alpacahq/alpaca-py/releases

Secondary (corroboration, all 2026-04-21 to 2026-04-23):
- Crowdfund Insider — https://www.crowdfundinsider.com/2026/04/274858-alpaca-expands-into-european-markets-with-wealthkernel-acquisition-and-equities-trading-launch/
- fintech.global — https://fintech.global/2026/04/21/alpaca-expands-into-europe-with-wealthkernel-deal/
- Finance Magnates — https://www.financemagnates.com/forex/wealthkernel-becomes-alpaca-europe-as-us-broker-plants-its-flag-in-london/
- IBS Intelligence — https://ibsintelligence.com/ibsi-news/alpaca-expands-to-europe-with-wealthkernel-acquisition/
- WealthTech Strategy — https://www.wealthtechstrategy.com/post/alpaca-completes-acquisition-of-wealthkernel-to-launch-european-equities-trading
- Morningstar (BusinessWire reprint) — https://www.morningstar.com/news/business-wire/20260421441080/alpaca-expands-into-europe-with-wealthkernel-acquisition-and-launch-of-european-equities-trading
- Portage Ventures (investor blog) — https://portageinvest.com/blog/alpaca-enters-uk-and-eu-market-through-wealthkernel-acquisition/

Reference / context:
- WealthKernel corporate site — https://www.wealthkernel.com
- Alpaca Trading API recognition (BrokerChooser 2026) — https://alpaca.markets/blog/alpaca-recognized-as-best-broker-for-algorithmic-trading-in-2026-by-brokerchooser/
- `alpaca-py` repository — https://github.com/alpacahq/alpaca-py
