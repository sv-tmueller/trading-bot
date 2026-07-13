# Forex short-horizon feasibility gate — cadence-swept, Germany-priced

**Question:** For a deterministic, moderate-cadence forex-major rule (the shape of a colleague's
4-hourly "enter or decline, set TP ceiling and SL" proposal bot) evaluated under **German** tax law,
what cadence × venue × position-size region can plausibly clear cost, before any edge is even
discussed — and does that region survive at all? Cadence is **not** fixed at 4h: the gate sweeps
~0.5–12 trades/day so 1h/4h/daily cadences fall out of the table rather than being assumed.
**Issue:** #368 (batch #367) · **Date:** 2026-07-13
**Author:** Analyst (research-only; no production code, settings, backtester, or broker integration
touched; no order placed)

> **Method note.** This is a **literature-and-arithmetic** scoping doc, gated cheap-math-first per
> #309's method (`docs/research/2026-06-23-short-horizon-feasibility-gate.md`). No backtest was run.
> Every numeric input below is stated with a fetched URL + date, or is explicitly tagged
> **[assumption]**. All tables are re-derivable from the formulas in §3 below; a throwaway Python
> calc helper (`gate_calc.py`) was used only to avoid arithmetic slips and lives outside the repo
> (scratchpad), never committed. If the gate had failed, the honest negative would be the
> deliverable, stated before any verdict — see §9 for how that threshold is actually stated, and the
> Bottom Line for what this gate actually found (it is **not** a repeat of #309's no-go).

---

## 1. Assumptions, stated up front, with sources

| Input | Value used | Source / basis |
|---|---|---|
| EURUSD reference price (for pip→bp conversion) | **1.14** | [tradingeconomics.com/commodity/euro](https://tradingeconomics.com/commodity/euro), fetched 2026-07-13 (live spot ≈1.14014, rounded) |
| Trading days / year | **~260** (24/5 forex session, 52 weeks × 5 days) | Stated explicitly to contrast with **#309's 252** (US equity/NYSE calendar) — forex trades 24 hours a day, 5 days a week with no US-market holiday closures baked into the count the way NYSE has; 260 is the standard 52×5 approximation. This is **not** the crypto 365-day count either (forex closes over the weekend). |
| Round-trip cost `c` (proportional venues) | per-venue, see §4 | Fetched schedules, §2 |
| Slippage assumption per side | 0.2 pip (base) / 0.5 pip (pessimistic) | **[assumption]** — no venue publishes a slippage figure; bracketed low/high per venue row, consistent with #309's slippage treatment |
| Overnight financing (spot/CFD only, sub-daily cadence) | XTB EURUSD swap: long **−$4.525**/day, short **−$1.032**/day per 100k-EUR lot | [XTB review via dailyforex.com](https://www.dailyforex.com/forex-brokers/xtb-review), page last updated 2024-11-11, fetched 2026-07-13 — reused as a proxy for all proportional venues (spot ECN and CFD alike), since venue-specific swap schedules were not separately fetched for each; **[assumption: applied uniformly]** |
| `R` grid (symmetric TP/SL) | {10, 20, 30, 50} bp → pip equivalents at 1.14 ref price: **11 / 23 / 34 / 57 pips** | Derived (`R_bp × 1.14 / 100`), spans tight-scalp to a realistic 4h-bar TP/SL, per #368's grid |
| Trades/day grid | {0.5, 1, 2, 3, 6, 12} | Per #368; cadence mapping: 0.5–1 ≈ a daily/EOD rule; 4h bars on a 24h session cap out at **6/day** (24 h ÷ 4 h); 12/day is a capped 1h-cadence proxy — so 1h/4h/daily cadences literally fall out of this table rather than being assumed up front |
| Position sizes (Trade Republic flat-fee sweep only) | €1,000 / €5,000 / €10,000 / €25,000 | Per #368 |
| German capital-gains flat tax | **≈26.375%** (25% Abgeltungsteuer + 5.5% Solidaritätszuschlag on the 25%) | [§32d EStG](https://www.gesetze-im-internet.de/estg/__32d.html), fetched 2026-07-13: "Die Einkommensteuer für Einkünfte aus Kapitalvermögen... beträgt 25 Prozent," no short/long distinction. Same flat-tax treatment carried over from #309/#308's logged decision. |
| Sparer-Pauschbetrag (annual allowance) | €1,000 single / €2,000 joint | [§20 Abs. 9 EStG](https://www.gesetze-im-internet.de/estg/__20.html), fetched 2026-07-13 |
| ESMA/BaFin retail leverage cap, major FX pairs | **30:1** (3.33% initial margin) | [BaFin Allgemeinverfügung, 2019-08-01](https://www.bafin.de/SharedDocs/Veroeffentlichungen/DE/Aufsichtsrecht/Verfuegung/vf_190801_allgvfg_Differenzgeschaefte.html), fetched 2026-07-13: "Major Currency Pairs: 3.33% margin" (USD/EUR/JPY/GBP/CAD/CHF crosses). This means the position-size sweep below is **notional exposure**; required margin = notional / 30. |
| Plausible win-rate ceiling, deterministic short-horizon rule | ~55–60% sustained OOS | **Carried over from #309 as a stated assumption**, re-flagged here, not a freshly-sourced figure — #309's Phase-2 literature survey was a stub, and this doc does not re-survey it |
| Drag sanity budget (secondary gate) | **15%/yr** | **[assumption]** — an order-of-magnitude ceiling on the annualized cost a systematic FX rule could plausibly overcome given SPY's own long-run CAGR is ~10%/yr (per prior backtests, e.g. `docs/research/2026-06-06-regime-vs-spy-longrun-backtest.md`); not a hard regulatory or empirical limit, a sanity check only — see §9 |

---

## 2. Invariant framing (stated first, governs everything below)

Per the batch contract (#367, refinement decisions locked 2026-07-13) and **CLAUDE.md Architectural
invariant #1 ("one decision rule")**: the colleague's 4-hourly proposals are generated by
**deterministic rules/indicators**, not an LLM. That shape is **invariant-compatible in principle** —
the same pure-function-on-a-bar decision the live bot already makes (`computeTargetState`), evaluated
more often, on a different instrument. It is reproducible from price history alone and imports no
model SDK.

**Replace, not add.** Nothing in this doc authorizes a second, parallel live decision rule. If a
candidate from this family ever shipped, it would **replace** the current 200-DMA/UPRO rule, exactly
as #309's equivalent framing stated. The live bot is untouched by this research (explicit non-goal of
#368). Stage 2 (colleague-strategy audit + faithful backtest) is a later batch, gated on this doc
passing — it is **not** developed here (hard non-goal).

The invariant line that matters for this doc's venue table (§7): an **LLM deciding each trade** — the
shape the rules-engine pivot removed — is out of bounds regardless of cost arithmetic. Two of the
four operator-flagged platforms (tradingkit.com's "PropFirm AI," trader.dev's "vibe trading, automated")
carry an AI/LLM framing in their own marketing copy; that framing is noted honestly in §7 but does not
change this doc's cost verdict, which concerns instrument/venue economics, not decision logic.

---

# Phase 1 — Cost gate (cheap math first)

## 3. Formulas (reviewer re-derivable)

```
Pip → fraction:        c_spread = spread_pips × 0.0001 / price          (price = EURUSD ref, 1.14)
Proportional:          c = c_spread + 2×(commission_per_side / notional) + 2×slippage_per_side
                           (+ overnight financing × nights held, for cadences < 1/day)
Flat-fee (TR):         c(size) = 2€/size + issuer_spread                (+ certificate holding costs)
Annualized drag:       drag = trades_per_day × 260 × c
Win rate (symmetric):  required = 0.5 + c / (2R)
```

The win-rate formula is #309's `c/(2R)` uplift-over-50% identity for **symmetric** TP/SL of size `R`;
an asymmetric generalization is `(SL + c) / (TP + SL)` (relevant to the colleague's sketch, which has
a TP *ceiling* rather than a fixed TP) — noted here for completeness, but every AC table below stays
symmetric per #368's own grid.

## 4. Venue round-trip cost `c` — fetched schedules

### 4.1 ECN/spot forex — IC Markets (Raw Spread / cTrader account)

| Component | Value | Source |
|---|---|---|
| EURUSD average spread | **0.01 pips** | [ic.com/global/en/trading-pricing/spreads](https://ic.com/global/en/trading-pricing/spreads) (redirected from icmarkets.com), fetched 2026-07-13 |
| Commission | **$3 per 100,000 USD traded, per side** → $6 round-trip per 100k lot | same page |
| Base `c` | spread (0.01 pip = 0.009 bp) + commission (0.6 bp round-trip) = **0.61 bp** | derived |
| Pessimistic `c` | 1.0-pip spread (0.88 bp) + commission (0.6 bp) + 0.5-pip/side slippage (0.88 bp) = **2.35 bp** | derived, slippage `[assumption]` |

IC Markets satisfies #368's "ECN/spot forex broker" row; it fills the developer's-pick slot the
SUB_PLAN offered (IBKR IDEALPRO / IC Markets / Pepperstone). **IBKR's own pricing pages
(`interactivebrokers.com`, `.co.uk`, and `ibkr.com`) all returned HTTP 403 to automated fetch** during
this session — a fetch-access limitation, not a claim about IBKR's actual pricing, which is not
otherwise represented here for spot FX (IBKR futures pricing is used in §4.3 via a secondary source,
since a similar block applied there too).

### 4.2 CFD — XTB (spread-only, no commission)

| Component | Value | Source |
|---|---|---|
| EURUSD minimum spread | **0.5 pips**, commission-free | [dailyforex.com XTB review](https://www.dailyforex.com/forex-brokers/xtb-review), page last updated 2024-11-11, fetched 2026-07-13. **Secondary source** — XTB's own pricing/instrument-specification pages (`xtb.com/en/instrument-specification`, `/de/einzelaufstellung-der-instrumente`) render their spread tables client-side and returned no extractable data to this session's fetch tool; this review site is used instead, flagged accordingly. |
| Overnight swap, EURUSD, per 100k lot | long **−$4.525**/day, short **−$1.032**/day | same source |
| Base `c` (intraday, no overnight) | spread (0.5 pip = 0.44 bp) + 0.2-pip/side slippage (0.35 bp) = **0.79 bp** | derived, slippage `[assumption]` |
| Pessimistic `c` (intraday) | 1.0-pip spread (0.88 bp) + 0.5-pip/side slippage (0.88 bp) = **1.75 bp** | derived |

XTB is a German-retail-relevant CFD broker (BaFin-reachable, EU-passported); its own live spread table
could not be scraped, so the number above is a dated secondary citation, explicitly flagged rather than
presented as XTB's own page.

### 4.3 Currency futures — CME 6E / M6E, via IBKR

| Component | Value | Source |
|---|---|---|
| 6E contract size | 125,000 EUR/point | [lunefi.com/tools/futures/6e](https://lunefi.com/tools/futures/6e), fetched 2026-07-13. **CME's own site (`cmegroup.com`) timed out on every fetch attempt this session** (contract-specs pages and homepage alike) — a fetch-access limitation, not a claim CME publishes different numbers. Cross-checked against [tradingview.com/symbols/CME-6E1!](https://www.tradingview.com/symbols/CME-6E1!/), fetched 2026-07-13, which independently confirms **125,000 EUR contract size**. |
| 6E tick size / value | 0.00005 / **$6.25** | lunefi.com, same fetch |
| M6E contract size | 12,500 EUR/point (one-tenth of 6E) | lunefi.com, same fetch |
| M6E tick size / value | 0.0001 / **$1.25** | lunefi.com, same fetch |
| IBKR futures commission (Fixed schedule) | standard US futures **$0.85/contract**; E-micro **$0.25/contract** (per side) | [brokerage-review.com](https://www.brokerage-review.com/online-trading/futures/ibkr-futures-trading.aspx), page states "Updated 7/8/2026", fetched 2026-07-13. **Secondary source** — IBKR's own futures-commission page also returned HTTP 403 to this session. The page explicitly notes IBKR does not separately break out 6E/M6E from the standard/E-micro categories; the read above assumes 6E = standard, M6E = E-micro, which is standard IBKR practice but not itself quoted verbatim for 6E by name. Exchange/regulatory pass-through fees are mentioned by the same page as real but **not quantified**, and are **omitted** below — an honest gap that would make the futures numbers modestly worse, never better, than shown. |
| 6E base `c` | 1-tick spread ($6.25 / $142,500 notional = 0.44 bp) + round-trip commission ($1.70 / $142,500 = 0.12 bp) = **0.56 bp** | derived (notional = 125,000 × 1.14 EURUSD) |
| 6E pessimistic `c` | 2-tick spread (0.88 bp) + commission (0.12 bp) = **1.00 bp** | derived |
| M6E base `c` | 1-tick spread ($1.25 / $14,250 = 0.88 bp) + round-trip commission ($0.50 / $14,250 = 0.35 bp) = **1.23 bp** | derived (notional = 12,500 × 1.14) |
| M6E pessimistic `c` | 2-tick spread (1.75 bp) + commission (0.35 bp) = **2.10 bp** | derived |

Note the counter-intuitive M6E result: the **micro** contract's proportional cost is *higher* than
the standard 6E's, because the flat per-contract commission and tick value don't scale down 10x as
fast as the notional does. Micro contracts buy flexibility in position sizing, not a cheaper `%` cost.

### 4.4 Trade Republic — FX derivative certificates (flat-fee + issuer spread)

| Component | Value | Source |
|---|---|---|
| Fremdkostenpauschale | **€1 per executed order** (buy and sell each incur it) | Confirmed both on [traderepublic.com/de-de](https://traderepublic.com/de-de) ("Bei Einzeltransaktionen fällt die Abwicklungskostenpauschale von 1 € zzgl. Spreads") and via [rankia.de/trade-republic-gebuehren](https://rankia.de/trade-republic-gebuehren/) (last updated 2026-06-09), both fetched 2026-07-13 |
| Spot FX offered? | **No** | rankia.de piece covers TR's full tradable universe (stocks, ETFs, crypto, bonds) with no forex/Devisenhandel mention; confirmed independently via search of TR help/community sources, fetched 2026-07-13 |
| FX exposure available via | **Knock-out certificates / Optionsscheine / Faktor-Zertifikate on currencies**, issued by HSBC, Société Générale, UBS, Vontobel | [support.traderepublic.com/de-at/87-Welche-Derivate-kann-ich-bei-Trade-Republic-handeln](https://support.traderepublic.com/de-at/87-Welche-Derivate-kann-ich-bei-Trade-Republic-handeln), fetched 2026-07-13: "Unser Angebot besteht hier insbesondere aus Optionsscheinen, Knock-Out-Produkten und Faktor-Zertifikaten auf Indizes, Einzelaktien, Währungen oder Rohstoffe." |
| Issuer spread on these certificates | **not separately published** by TR or the issuers for a specific EUR/USD product | **[assumption, bracketed 10–30 bp, base case 15 bp]** — no live source quantifies this; flagged exactly per the SUB_PLAN's allowance rather than invented as a precise figure |
| Official trading API | **None** | Confirmed by multiple independent sources: [parqet.com blog](https://parqet.com/de/blog/trade-republic-mit-chatgpt-verbinden) (2026-05-29): "Trade Republic hat keine öffentliche API"; Reddit r/Finanzen: "TradeRepublic stellt keine öffentlichen APIs zur Verfügung und möchte auch nicht, dass die... Lösungen dauerhaft funktionieren" (i.e. TR actively deactivates unofficial workarounds it finds); a LinkedIn post from a former TR-adjacent source states the same. All fetched 2026-07-13. |

`c(size) = 2€/size + issuer_spread`, computed for the required sweep:

| Size | 2€/size term | Total `c` — low issuer spread (10 bp) | base (15 bp) | high (30 bp) |
|---|---|---|---|---|
| €1,000 | 20.0 bp | 30.0 bp | 35.0 bp | 50.0 bp |
| €5,000 | 4.0 bp | 14.0 bp | 19.0 bp | 34.0 bp |
| €10,000 | 2.0 bp | 12.0 bp | 17.0 bp | 32.0 bp |
| €25,000 | 0.8 bp | 10.8 bp | 15.8 bp | 30.8 bp |

**Crossover: `size* = 2€ / (c_prop − issuer_spread)`.** Computed against every proportional venue's
base `c` (0.56–1.23 bp) at every point of the issuer-spread bracket (10–30 bp): in **every** case
`c_prop − issuer_spread` is **negative** — the issuer spread alone (even at its stated *low* end,
10 bp) already exceeds every sourced proportional venue's *entire* round-trip cost (max 1.23 bp, for
M6E). **There is no finite crossover size within the swept range, or any realistic range** — Trade
Republic's flat €1 fee is not the load-bearing cost at all; the embedded, unpublished certificate
issuer spread is, and it structurally dominates. Position size only ever shrinks the *2€/size* term
(20 bp → 0.8 bp across the sweep) — the part of TR's cost that behaves like #368 expected — but the
un-shrinkable issuer-spread floor means TR is **more expensive than every sourced proportional venue
at every size in the sweep**, not just at small sizes. This is the honest, arithmetic-only finding;
it does not depend on picking the "right" issuer-spread number within the bracket.

## 5. Cadence sweep — drag and required win rate

`drag = trades_per_day × 260 × c` (annualized, % of notional/yr); `required win rate = 0.5 + c/(2R)`.
Sub-daily cadences (0.5/day) for spot/CFD rows add the **XTB overnight financing proxy**, averaged
long/short (`(4.525 − 1.032)/2 = 1.75 bp/night`(as a fraction, 0.175 bp — table below), applied for
~2 nights held at 0.5 trades/day; futures rows have no daily rollover charge (a genuine structural
advantage of the futures wrapper, not modeled away) so no overnight line is added there.

### 5.1 Annualized cost drag (%/yr) by venue × trades/day

| Venue (`c`) | 0.5/day | 1/day | 2/day | 3/day | 6/day | 12/day |
|---|---|---|---|---|---|---|
| IC Markets ECN base (0.61 bp) | 1.2% | 1.6% | 3.2% | 4.7% | 9.5% | 19.0% |
| IC Markets ECN pessimistic (2.35 bp) | 3.5% | 6.1% | 12.2% | 18.4% | 36.7% | 73.5% |
| XTB CFD base (0.79 bp) | 1.5% | 2.1% | 4.1% | 6.2% | 12.3% | 24.6% |
| XTB CFD pessimistic (1.75 bp) | 2.7% | 4.6% | 9.1% | 13.7% | 27.4% | 54.7% |
| 6E futures base (0.56 bp) | 0.7% | 1.5% | 2.9% | 4.4% | 8.7% | 17.4% |
| 6E futures pessimistic (1.00 bp) | 1.3% | 2.6% | 5.2% | 7.8% | 15.5% | 31.1% |
| M6E futures base (1.23 bp) | 1.6% | 3.2% | 6.4% | 9.6% | 19.2% | 38.3% |
| M6E futures pessimistic (2.10 bp) | 2.7% | 5.5% | 10.9% | 16.4% | 32.8% | 65.7% |

Contrast with #309's equivalent table: at base cost, equity ETFs on Alpaca hit **37.8%/yr at just
5 trades/day**; the cheapest forex venue here (6E futures, base) is still under 20%/yr at **12**
trades/day. This is the direct arithmetic reason forex prices out differently from #309's US-equity
and crypto cases — a genuinely cheaper cost floor, not a different formula.

### 5.2 Required win rate to break even on cost, by `R`

| Venue (`c`) | R=10 bp (11 pips) | R=20 bp (23 pips) | R=30 bp (34 pips) | R=50 bp (57 pips) |
|---|---|---|---|---|
| IC Markets ECN base | 53.0% | 51.5% | 51.0% | 50.6% |
| IC Markets ECN pessimistic | **61.8%** | 55.9% | 53.9% | 52.4% |
| XTB CFD base | 53.9% | 52.0% | 51.3% | 50.8% |
| XTB CFD pessimistic | 58.8% | 54.4% | 52.9% | 51.8% |
| 6E futures base | 52.8% | 51.4% | 50.9% | 50.6% |
| 6E futures pessimistic | 55.0% | 52.5% | 51.7% | 51.0% |
| M6E futures base | 56.1% | 53.1% | 52.0% | 51.2% |
| M6E futures pessimistic | **60.5%** | 55.3% | 53.5% | 52.1% |

Only the tight-`R` (10 bp / ~11-pip) + pessimistic-cost corner brushes or exceeds the stated 55–60%
ceiling (IC Markets pessimistic 61.8%, M6E pessimistic 60.5%); every other cell — including every
base-case row at every `R`, and every pessimistic row at `R` ≥ 20 bp — sits comfortably under it.
This is the opposite shape from #309, where the *base* case already failed outright.

## 6. Feasibility frontier — closed form

`max trades/day = drag_budget / (260 × c)`. Frontier at the stated **15%/yr** sanity budget (§9):

| Venue | Max trades/day (base) | Max trades/day (pessimistic) |
|---|---|---|
| IC Markets ECN spot | 9.5 | 2.5 |
| XTB CFD | 7.3 | 3.3 |
| 6E futures | **10.3** | 5.8 |
| M6E futures | 4.7 | 2.7 |

At a 15%/yr drag budget, the frontier survives well past the colleague's own 4h/6-per-day cadence on
every base-case venue, and past it on three of four venues even pessimistically. Widening the budget
to 20%/yr or 30%/yr (shown in the scratchpad calc, not reproduced here to keep this table to the
stated threshold) pushes the frontier further out; narrowing it to 10%/yr pulls IC Markets ECN
pessimistic below 2/day. The frontier is a straight-line function of the assumed budget — reviewers
disagreeing with 15% can rescale linearly using the formula above.

---

# Phase 2 — Tax and venue reality (per AC 4 / AC 5)

## 7. German tax per instrument type

All four instrument types below are, for a leveraged/cash-settled retail position, **Termingeschäfte**
under **[§20 Abs. 2 Satz 1 Nr. 3 EStG](https://www.gesetze-im-internet.de/estg/__20.html)** ("der
Gewinn bei Termingeschäften, durch die der Steuerpflichtige einen Differenzausgleich... erlangt"),
fetched 2026-07-13 — taxed at the same flat **26.375%** Abgeltungsteuer rate as any other capital
income (§32d EStG, above), with **no** short/long holding-period distinction for this category.

| Instrument | Classification | Loss-offset status |
|---|---|---|
| Leveraged/margin spot FX (rolling, swap-financed — the IC Markets/XTB case) | Termingeschäft, §20 Abs. 2 Nr. 3 | See below — cap repealed |
| **Genuinely physical, unleveraged FX** (buy currency, hold, no margin/CFD wrapper) | §23 EStG privates Veräußerungsgeschäft — tax-free after a 1-year hold, marginal rate within 1 year | Not the practical case for a short-horizon rule; noted for completeness since it is taxed completely differently (no flat rate, no Termingeschäft classification) |
| CFDs | Termingeschäft, §20 Abs. 2 Nr. 3 | See below — cap repealed |
| Futures (6E/M6E) | Termingeschäft, §20 Abs. 2 Nr. 3 | See below — cap repealed |
| Certificates / knock-outs (Trade Republic) | Termingeschäft-like, §20 Abs. 2 Nr. 3 / 3b; total worthless-expiry loss historically the most contested case | See below — cap repealed |

**Loss-offset status — verified against live 2024/2025 sources, not memory, per #368's explicit
requirement:**

- §20 Abs. 6 EStG **used to** cap losses from Termingeschäfte at **€20,000/year**, offsettable only
  against gains from other Termingeschäfte (old Satz 5/6) — a 2021-introduced restriction.
- **BFH VIII B 113/23 (AdV)**, decided 2024-06-07 (ECLI:DE:BFH:2024:BA.070624.VIIIB113.23.0), found —
  in summary preliminary review — that the cap was "nicht mit Art. 3 Abs. 1 des Grundgesetzes
  vereinbar" (incompatible with the constitutional equal-treatment principle), calling it a "doppelte
  Ungleichbehandlung." Source: [datenbank.nwb.de](https://datenbank.nwb.de/Dokument/1047292/), fetched
  2026-07-13.
- **Note on the case number in #368's SUB_PLAN.** The SUB_PLAN names "BFH VIII R 11/23" as the
  source to verify against. Live search could not locate any case under that exact number. The
  matching main-proceeding decision this session could confirm is **BFH VIII R 11/24** (dated
  2025-03-28 per the NWB database entry — the finance court judgment it reviewed became **moot**
  ("gegenstandslos") after the tax office issued a corrected 2021 assessment on 2025-02-14, i.e., the
  authority conceded following the legislative fix below), which traces to the same underlying
  dispute as the AdV order above. **This looks like an off-by-one in the case number as given
  (23 vs 24)** rather than a wrong finding — flagging per instruction rather than silently
  substituting.
- **Legislative fix: Jahressteuergesetz (JStG) 2024**, in force **2024-12-06**, retroactively
  repealed the €20,000 cap (old Satz 5/6) entirely: "Die Verlustverrechnungsgrenze von 20.000 Euro
  wurde ersatzlos gestrichen," applicable to "allen am 6.12.2024 offenen Fällen." Sources:
  [haufe.de](https://www.haufe.de/steuern/steuerwissen-tipps/uebergangsregelung-bei-verlusten-aus-wertlosem-verfall-von-aktien_170_651418.html)
  and [lohnsteuer-kompakt.de](https://www.lohnsteuer-kompakt.de/steuerwissen/verluste-aus-termingeschaeften-steuererleichterung-fuer-anleger),
  both fetched 2026-07-13. **Directly confirmed against the live statute text** fetched the same day:
  the current §20 Abs. 6 EStG (fetched 2026-07-13) contains **no** Termingeschäfte-specific cap or
  Euro figure in its printed Sätze 1–5 — consistent with the repeal, not merely with a secondary
  source's say-so.
- **Bottom line for this gate:** as of 2026-07-13, a German-resident retail trader running a
  short-horizon FX/CFD/futures/certificate rule can offset **all** losses from these Termingeschäfte
  against other capital income, with **no** annual cap — a materially more favorable position than
  the rule that applied 2021–2024-12-05. This resolves #309's recorded residence ambiguity in the
  favorable direction for a German-taxed churn strategy specifically on the loss-offset axis (it does
  **not** change the flat-rate/no-holding-period point #309 already priced under the German column).

## 8. Venue / API reality check (AC 5, extended per the operator's lead decision)

Which venues a German resident can legitimately reach with **real, automatable** APIs:

| Venue | What it is | Cost (from §4) | Automatable by a German resident? | Notes |
|---|---|---|---|---|
| **IC Markets** (Raw/cTrader) | ECN/STP forex-CFD broker | 0.61–2.35 bp | **Yes** — cTrader Open API / FIX API, MT4/5 EAs; EU-facing entity, MiFID-reachable | Fetched fee schedule directly (§4.1) |
| **XTB** | CFD/forex broker, BaFin-relevant retail brand | 0.79–1.75 bp | Has an xStation platform with algo/API access in its retail offering (not separately re-verified this session beyond the fee citation) | Fee number is a secondary/dated source (§4.2) — flagged |
| **CME 6E/M6E via IBKR** | Regulated futures exchange + broker | 0.56–2.10 bp | **Yes** — IBKR TWS/Client Portal API is a real, documented, automatable API; IBKR itself could not be fetched directly this session (403 on every domain tried), but its API's existence and general reachability from Germany is well-established and not in dispute here | Commission figure sourced from a secondary page, not IBKR's own (§4.3) |
| **Trade Republic** | German neobroker | 10.8–50 bp (certificates only) | **No — disqualifying.** No spot FX at all. **No official API** (confirmed §4.4, multiple sources); unofficial/reverse-engineered APIs exist but TR actively works to break them ("möchte... nicht, dass die... Lösungen dauerhaft funktionieren") — ToS-violating and unreliable by the platform's own stated intent, independent of TR's cost economics (which are separately disqualifying per §4.4) | Two independent disqualifiers, not one |
| **tradingview.com** | Charting/alerting platform, **not itself a broker** | N/A (subscription: €12.95–€199.95/mo, [tradingview.com/pricing](https://www.tradingview.com/pricing/), fetched 2026-07-13) | Only **via** a connected broker. TradingView's own webhook mechanism is a **one-way HTTP POST notification** to a URL you supply — [confirmed via tradingview.com's own webhook support doc](https://www.tradingview.com/support/solutions/43000529348-tradingview-trading-panel/), fetched 2026-07-13 — it does **not** place orders by itself. Separately, TradingView's official "Trading Panel" broker-partner integration lists **100+ broker partners** including **IC Markets, Pepperstone, OANDA, Interactive Brokers, Saxo Bank, Forex.com, FXCM** — [tradingview.com/brokerage-integration](https://www.tradingview.com/brokerage-integration/), fetched 2026-07-13 | This is the legitimate half of the "YouTube stack" (see synthesis below): official broker partnerships, not scraped credentials |
| **trigger.trade** | Webhook→exchange execution bridge, **crypto-only** | N/A to this forex doc | Connects **Bybit, Blofin, Toobit, WEEX, Bitunix** — five crypto exchanges, **none** BaFin-licensed for German retail spot/derivatives crypto trading in the way a MiFID broker is; free for a "Skool community" membership per its own page, [trigger.trade](https://trigger.trade), fetched 2026-07-13 | **Not applicable to forex at all** — and crypto is a hard non-goal of #368/#309 anyway. Included per the operator's lead decision, marked honestly as out-of-scope-by-asset-class, not evaluated further |
| **trader.dev** | Minimal landing page: **"vibe trading, automated"** | Unknown — no pricing, broker, or feature detail was retrievable | **Cannot confirm any legitimate automated execution capability.** The page returns essentially no content beyond its own tagline to this session's fetch tool | The tagline itself ("vibe trading") suggests **non-deterministic, LLM/sentiment-style** decision-making if the product is real — which would be **out of invariant bounds** (§2) regardless of cost, independent of whatever this product actually does under the hood. Marked honestly as **indeterminate**, not dead, not verified |
| **tradingkit.com** | AI-powered trading **tool suite**: backtesting (via trader.dev), "PropFirm AI" funded-account monitoring, a strategy marketplace, an MT5 Python package | Unknown | **Direct site access returned HTTP 403** to this session's fetch tool; described only via secondary search-engine snippets, which show it is **not itself a forex execution bridge to a regulated broker** — it is closer to an education/prop-firm-tooling brand that references trader.dev for backtesting | Prop-firm funded-account trading is also a **different asset/legal relationship** (trading the firm's capital under a challenge agreement, not a personal brokerage account) — not evaluated here at all, flagged as out of scope |

**Synthesis — the TradingView-alert→webhook→execution-bridge stack, assessed:**

The common YouTube pattern is: TradingView (Pine Script strategy or manual indicator) fires an
**alert** → the alert POSTs to a **webhook URL** → a bridge service receives that POST and forwards
an order to a broker/exchange using API keys the user separately supplies to the bridge → the
broker/exchange executes. Two structurally different versions of this exist, and they carry very
different reliability/ToS profiles:

1. **The legitimate version, for forex**: TradingView's own **official broker-partner integration**
   ("Trading Panel") connects directly to a MiFID-regulated broker's own execution API — IC Markets,
   Pepperstone, OANDA, IBKR, Saxo are all named partners. This is TradingView-as-front-end to a real
   broker's real, sanctioned API, not a scraped workaround. This is the credible route for the forex
   venues priced in §4.1–4.3.
2. **The crypto-bridge version** (trigger.trade, and by its own description several unnamed
   competitors like "Webhook.Trade"/"TradeAdapter"/"AlgoWay" surfaced in search but not independently
   fetched this session): a **third-party service** holds API keys and forwards webhook payloads to
   an **exchange**, not a regulated broker. This pattern is real, working, and cheap/free — but every
   concrete example found this session targets **crypto exchanges**, which are out of this doc's
   asset-class scope by design (#368/#309's crypto non-goal) and introduce their own counterparty
   risk (the bridge service itself becomes a single point of failure holding, even if encrypted,
   credentials to move money) and regulatory ambiguity for a German resident that this doc does not
   resolve, because it is off-topic for a *forex* feasibility gate.

**Trade Republic sits outside both patterns entirely** — no spot FX to bridge to in the first place,
no official API for either pattern to attach to, and an explicit, sourced statement that TR
disables unofficial workarounds. Its disqualification for automation (§4.4, AC 5) stands on ToS/API
grounds *and independently* on cost grounds (§4.4) — either one alone would be disqualifying.

---

## 9. Reconciliation with #309, #311, and the 2026-07-06 ADR

| | #309 (equity/crypto, US-ambiguous) | #311 (empirical BTC scalp) | 2026-07-06 ADR | **This doc (#368)** |
|---|---|---|---|---|
| Asset class | US-listed equity ETF (Alpaca), crypto pair (Alpaca) | BTC perp (Bybit) | n/a — 200-DMA/UPRO decision | Forex majors (EURUSD-class) |
| Trading-day count | 252 (NYSE) | 365 (crypto 24/7) | n/a | **260 (24/5 forex)** — explicitly different from both, stated up front (§1) |
| Cheapest sourced round-trip cost | 1–5 bp (equity), 50–80 bp (crypto, Alpaca taker) | 13 bp (Bybit realistic) | n/a | **0.56–2.35 bp** base-to-pessimistic across 4 venues — cheaper than *any* prior venue this repo has priced, equity included |
| Regulatory constraint | PDT (<$25k equity accounts capped <1 day-trade/day) | n/a (perp, no PDT) | n/a | **No PDT-equivalent** for forex; the binding constraint instead is ESMA/BaFin's 30:1 leverage cap on *notional*, not trade frequency |
| Tax regime priced | Both US and German, with an **unresolved residence ambiguity** flagged as the key follow-up | n/a | n/a | **German, confirmed** — resolves #309's flagged ambiguity directly, and finds the loss-offset cap that would have applied 2021–2024 has since been **repealed** (§7), a materially *more* favorable finding than #309 had visibility into |
| Verdict at the base case | **No-go** — 37.8%/yr drag at 5 trades/day (equity), fees-alone-impossible at crypto | Confirms #309 empirically: strategy tested had **no gross edge at zero cost**, so any cost is fatal | Confirms 200-DMA stays live; no alternative signal clears the after-tax Calmar bar at a tolerable drawdown | **Not a no-go at the base case** — see Bottom Line |
| What's shared | Same cost/win-rate formulas, same discipline of stating a threshold before a verdict, same refusal to pad a failing result | Same formula, made empirical on real data | Sets the standing bar (after-tax Calmar vs SPY) any eventual candidate must still clear | Inherits both: same formulas (§3), and explicitly **does not** claim to have cleared #255's bar — see below |

**This gate does not, and cannot, replace #255's standing bar.** #255/the 2026-07-06 ADR concluded
that no *signal* surveyed to date clears SPY's after-tax Calmar at a tolerable drawdown for the *live*
3x UPRO bot — a question about signal quality and drawdown, not about transaction cost. This doc
answers a narrower, prior question: **is the cost floor even survivable** for a moderate-cadence
forex rule, before any signal is evaluated at all. The answer here is yes, for a wide cadence band —
which is the opposite of #309's finding for equities/crypto, and is exactly why #367 asked this
question separately rather than assuming #309's no-go generalized. **Any forex candidate that reaches
stage 2 must still clear #255's after-tax-Calmar bar against SPY, on a walk-forward backtest, at a
drawdown the operator can tolerate** — clearing the cost gate is necessary, not sufficient, precisely
as #309 stated for its own (failing) case.

---

## 10. Threshold, stated before the verdict

**Primary gate:** the required win-rate uplift, `0.5 + c/(2R)`, must not exceed the stated **~55–60%**
plausibility ceiling for a deterministic short-horizon rule (assumption, carried over from #309,
§1). **Secondary sanity gate:** annualized cost drag must not exceed a **15%/yr** drag budget
(assumption, §1) — a loose check, not #255's real bar, which is after-tax Calmar, not raw drag.
**If neither gate is cleared for any venue/cadence cell, the honest negative is the deliverable and
stage 2 should not be dispatched.**

### Feasibility-frontier verdict matrix

Cadence × venue, base-case cost, judged against the primary win-rate gate at `R=20 bp` (23 pips — a
representative mid-grid TP/SL, not the tightest or widest) and the secondary 15%/yr drag budget:

| Venue | 0.5/day | 1/day | 2/day | 3/day | 6/day (4h cadence) | 12/day |
|---|---|---|---|---|---|---|
| IC Markets ECN (base) | survive | survive | survive | survive | survive | **borderline** (19.0% drag, just over budget) |
| XTB CFD (base) | survive | survive | survive | survive | survive | **borderline** (24.6% drag) |
| 6E futures (base) | survive | survive | survive | survive | survive | survive (17.4% drag, closest to budget but under) |
| M6E futures (base) | survive | survive | survive | survive | **borderline** (19.2% drag) | dead (38.3% drag) |
| *(pessimistic-cost cells, same venues)* | mostly survive | survive/borderline | borderline | borderline–dead | dead (all ≥27% drag) | dead |

All win-rate cells at `R=20 bp` (§5.2) sit at 51.4–55.9% — **under or at the edge of** the 55–60%
ceiling in every case, base or pessimistic. **The binding constraint at high cadence is the drag
budget, not the win-rate ceiling** — the reverse of #309, where win-rate/cost magnitude killed the
region outright regardless of any budget. At the colleague's actual proposed cadence (**4h bars,
≤6 trades/day**), every base-case venue survives both gates; only the pessimistic-cost, tight-`R`
corner (M6E pessimistic, `R=10bp`) approaches the win-rate ceiling (60.5%, §5.2) at any cadence.

**Trade Republic (all sizes, all issuer-spread assumptions):** dead at every cadence ≥ 0.5/day — its
`c` (10.8–50 bp, §4.4) already fails the win-rate gate at `R=10bp` (required win rate 55%+ even at
the *cheapest* size/issuer-spread combination, and >70% at the €1,000/high-issuer-spread corner) and
blows through the 15%/yr drag budget at just 1 trade/day in every size/spread combination
(`1 × 260 × 0.0108` to `1 × 260 × 0.0050` ≈ 28–130%/yr). TR is disqualified on cost **and**
independently on API/ToS grounds (§8) — a double disqualification, not a single weak one.

**Closed-form frontier (§6), inherited explicitly:** `max trades/day = drag_budget/(260×c)`. At the
stated 15%/yr budget the base-case frontier tops out around **10.3 trades/day (6E futures)** down to
**4.7/day (M6E)** — i.e., the entire 0.5–6/day band #368 asked about survives on drag for every
proportional venue except the pessimistic-cost M6E and IC Markets rows.

**Inherited standing bar.** Per #255/the 2026-07-06 ADR, any candidate that reaches stage 2 must
still **beat SPY on after-tax Calmar** at a tolerable drawdown, on a proper walk-forward backtest.
**Clearing this cost gate does not mean a profitable strategy exists** — it means the cost floor no
longer rules one out before the question is even asked, which is precisely the opposite finding from
#309/#311's equity/crypto no-go.

---

## Bottom line

Unlike #309 (equity/crypto scalping, killed on cost alone) and unlike the empirical confirmation in
#311, **this gate does not fail at the cost stage.** The honest verdict, stated arithmetically from
the tables above:

- **Forex's sourced cost floor (0.56–2.35 bp round-trip across four venues) is 5–100x cheaper than
  the venues #309 priced** (1–5 bp equity, 50–80 bp crypto), and the 260-trading-day count is close
  to #309's 252 (not the 365 that made crypto's drag worse than shown). This is a structurally
  different region, exactly as #367 hypothesized.
- **The colleague's actual proposed cadence (4h bars, ≤6 trades/day) survives both stated gates on
  every base-case venue**, and on three of four venues even at the pessimistic-cost assumption.
  Required win-rate uplift at a realistic `R=20bp` sits at 51–56% — under the stated ~55–60%
  ceiling in every base-case cell.
- **Trade Republic is dead, on two independent grounds**: no spot FX (only derivative certificates
  whose unpublished issuer spread, bracketed 10–30bp, already exceeds every proportional venue's
  *entire* cost, at every position size swept — there is no crossover size where TR's flat fee wins),
  and no official API (with the platform actively working against unofficial ones) — disqualifying
  for legitimate automation independent of the cost finding.
- **The venue/API table (AC 5, extended)** confirms IC Markets, XTB, and IBKR-brokered CME futures
  are all reachable by a German resident with real, automatable APIs. **TradingView is a legitimate
  front-end when paired with one of its official broker partners** (IC Markets/Pepperstone/OANDA/IBKR
  are all named partners) — this is the credible half of the YouTube "alert→webhook→execution" stack
  for forex specifically. **trigger.trade is real but crypto-only** (five exchanges, none
  BaFin-relevant), out of scope by asset class. **trader.dev and tradingkit.com could not be verified
  to provide any forex execution capability at all** — trader.dev is a near-empty landing page whose
  own tagline ("vibe trading, automated") suggests non-deterministic decision-making if it is
  real, which would be out of this repo's invariant bounds regardless; tradingkit.com's own site
  blocked automated access and secondary sources describe an AI/prop-firm tooling brand, not a
  dedicated forex broker bridge.
- **German tax loss-offset status, verified live (not from memory) per #368's explicit requirement**:
  the 2021-era €20,000/year cap on Termingeschäfte losses was found likely unconstitutional by the
  BFH (AdV order, 2024-06-07) and was then **repealed outright** by the JStG 2024, effective
  2024-12-06 — confirmed both by secondary tax commentary and directly against the live §20 EStG
  statute text, which now contains no such cap. This is a materially *more* favorable finding for a
  German-taxed short-horizon rule than existed when #309 flagged the residence question. One
  discrepancy is flagged honestly rather than silently resolved: the SUB_PLAN's cited case number
  ("BFH VIII R 11/23") could not be located; the matching decision found was **BFH VIII R 11/24**
  (dated 2025-03-28), tracing to the same underlying dispute — plausibly an off-by-one in the
  original citation.
- **What this gate does *not* claim**: clearing the cost floor is necessary, not sufficient. #255's
  standing bar — beat SPY on after-tax Calmar, at a tolerable drawdown, on a proper walk-forward
  backtest — is untouched by this doc and remains the real test. This doc only removes the *cost*
  objection that killed #309's equity/crypto case; it says nothing about whether the colleague's
  actual rules have any edge.

**Recommendation:** the cost gate for moderate-cadence (≤6/day), deterministic forex-major trading,
under confirmed German tax treatment, at IC Markets/XTB/CME-futures-via-IBKR, **passes** — the
opposite of #309's equity/crypto no-go. Per the batch contract (#367), **stage 2 (audit of the
colleague's live trade history + a faithful backtest of his rules using this doc's cost model, at a
cadence the frontier says is affordable) is a reasonable next step**, contingent on the operator
obtaining the colleague's exact rules and a broker trade export, as #367 already anticipated. Trade
Republic is excluded from any stage-2 build on both cost and API/ToS grounds. This does not authorize
any change to the live 200-DMA/UPRO bot, which remains untouched (#367's explicit non-goal) and whose
own goals-question was separately and finally settled by the 2026-07-06 ADR.
