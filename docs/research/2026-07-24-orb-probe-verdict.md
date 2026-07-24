# Opening-Range Breakout (ORB) free-data probe — pre-registered verdict (#431)

**Package P2 of #429** (ORB free-data probe, reusing the #430 bracket engine). Design
authority: the SUB_PLAN comment on #431. Mirror pattern: `backtest/run_turtle_breakout.py`
+ `docs/research/2026-07-24-turtle-breakout-verdict.md`.

Research-only. No live/TypeScript code, no Alpaca **trading** import, no orders — the only
network is a **read-only** historical-bars pull. This document decides only whether the
ORB is **worth paying for full-power intraday data**; it changes no running behavior.

---

## This is an UNDERPOWERED, DIRECTIONAL probe — NOT a promotion test

State this verbatim, up front (it is graded): **free SPY 5-min history reaches only ~2016,
i.e. ~n_w ≈ 9 non-overlapping 12-month windows** (`docs/research/2026-07-21-contracts-survey-data-feasibility.md`;
`2026-07-24-famous-traders-strategies-survey.md` §2.2), short of the **n_w = 13** #398
promotion bar. So the pre-registered bar here is **not** the full Calmar promotion bar. It
is a **directional read**, and the deliverable's verdict is **"worth paying for full-power
data? yes / no"** — explicitly **not** a GO/NO-GO promotion of ORB into the trading path.

---

## Pre-registration (committed BEFORE any result is examined)

This section is frozen. It is committed in a **separate, earlier commit than the Results
and Verdict below**, and is not edited after the numbers are seen (provable from git
history, mirroring #425/#430's pre-registration → results commit ordering).

### The frozen rule — long-only ORB (verified against the source)

Verified against **Zarattini & Aziz (2023), *"Can Day Trading Really Be Profitable?"***
(SSRN 4416622; 5-min ORB on QQQ/TQQQ, 2016–2023, ~33% annualized alpha) — cited as
Candidate B [S11] in `2026-07-24-famous-traders-strategies-survey.md` §2.2. The SSRN PDF
was **HTTP-403 to the fetch tool in this sandbox**, so the rule was cross-checked against
the survey's frozen summary and an independent secondary description of the paper; both
agree on: opening range = first 5-min candle; entry on the break of that range; **stop at
the opposite side of the 5-min range**; the base model uses a large R-multiple target (the
paper: **10R**) with an **exit-at-close** variant; **one trade per day**. Any residual
uncertainty from the paywalled primary is disclosed here rather than hidden.

Frozen variant actually tested (the differences from the paper are deliberate and labelled):

- **Opening range (OR):** the **first 5-minute bar** of each US regular session — its High
  and Low. (The paper's first-5-min candle.)
- **Entry — long-only:** the first later bar of the **same session** whose **Close breaks
  above the OR high**; enter at the **next bar's open** (close-t → open-t+1 shift, no
  look-ahead). **One entry per session**, never on the OR bar, never across a session
  boundary. **Long-only** because the reused `simulate_bracket` engine is long-only v1 —
  so this probe tests the **LONG arm only** of the paper's long/short ORB. (Deviation #1,
  disclosed.)
- **Stop = OR low** (opposite side of the opening range — the paper's explicit stop). No
  k·ATR variant in this frozen grid.
- **Target — frozen 3-cell grid:** `{ None (exit-at-session-close), R = 5, R = 10 }`, where
  `target = entry + R·(entry − OR low)` (R multiples of the per-share risk). `None` is the
  paper's simplest exit-at-close variant; `R = 10` is the paper's base-model target.
  (Entry on a break-of-OR-high rather than the paper's "trade in the first candle's
  direction at the 2nd-bar open" is Deviation #2, chosen for no-look-ahead alignment with
  the frozen bracket engine and because the SUB_PLAN names "break above OR high" as the
  trigger to freeze.)
- **Session / EOD close-out:** never hold overnight — `simulate_bracket(session_close_out
  = True, eow_close_out = False)` flattens any open lot at each session's last bar
  (`exit_reason = "session"`). This is the one additive engine change #431 makes; the 28
  bracket tests stay green (additive, default-off).
- **Sizing / costs:** full available cash into one lot, integer shares, `STARTING_CASH =
  100,000`; `SLIPPAGE_BPS = 5` + `COMMISSION_BPS = 5` **per side** (20 bps round trip — the
  `regime.py` constants, the same the turtle bracket used). Intraday churn is high, so cost
  is **load-bearing** and is never omitted (cf. `run_scalping_cost_wall.py`'s cost-wall
  finding).

Absolute stop/target levels are computed by the **runner** and passed to
`simulate_bracket`; the engine never hardcodes the geometry (the reuse property #430 froze).

### Baselines (frozen)

Each ORB cell is measured against, on the **same sessions and the same bracket geometry**:

1. a **seeded random-entry bracket** (`RANDOM_SEED = 42`) — the same number of entries at
   random intra-session bars (never a session's OR bar), same OR-low-stop / R-target; and
2. an **always-in** buy-&-hold of SPY over the same bars (the beta/vol reference).

A real edge must beat **both** — otherwise the bracket is just harvesting (cost-eroded)
intraday beta.

### The directional bar (verbatim)

> ORB clears the **directional** bar only if its **after-tax US Calmar** (`_after_tax_metrics
> (...)["calmar_us"]`) exceeds **both** the seeded random-entry baseline's **and** the
> always-in baseline's, on free SPY 5-min (2016+). This is a directional read, NOT the
> n_w = 13 promotion bar; a pass means only **"full-power intraday data is worth paying
> for,"** and a fail means **"not worth paying for."**

The read is only **powered** when the fetched depth reaches the pre-registered floor
`PROBE_MIN_SESSIONS = 500` sessions (≈ 2 trading years — a bare minimum for even a
directional read toward the 2016+ intent). Below the floor the result is **DATA-BLOCKED**
and any numbers produced are an explicitly-labelled **plumbing smoke**, never the read.

### Data basis (frozen) + the honest data risk

- **Primary:** Alpaca **read-only** historical 5-min bars (`data.alpaca.markets`, 2016+),
  keyed from `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` (the data keys; **never** an
  order endpoint). `.env.backfill` is gitignored and **may be absent** in the sandbox.
- **Fallback:** yfinance 5-min — **depth-capped to ~60 calendar days from now**, far below
  the 2016+ floor, so it can only ever produce a plumbing smoke.
- **If neither reaches the floor, the honest deliverable is "DATA-BLOCKED — the probe needs
  the Alpaca paper/data keys or a paid intraday source,"** NOT a fabricated ORB edge. No
  price is ever fabricated.

### Caveats that qualify any read (frozen)

- **Long-only vs long/short.** The engine is long-only; this is the long arm only. A full
  ORB replication would need the short arm (out of scope for the reused v1 engine).
- **Underpower.** Free 5-min cannot reach n_w = 13; this is a directional read only.
- **Class already ruled NO-GO.** #422's feasibility gate ruled the intraday/minute
  rule-based-entry class NO-GO, and the colleague killed a **London**-ORB variant
  (`2026-07-20-colleague-repo-audit.md`). This is a **US-market** ORB — a *different* setup,
  which is why it is probed rather than dismissed by analogy — but it sits inside that
  ruled-out class, so a positive directional read would be a **reason to buy data and
  re-test to the bar**, not a green light.
- **PDT + leverage.** The 5-min variant is PDT-constrained sub-$25k, and this is a **1×**
  SPY test; the incumbent is 3× UPRO. Moot unless the directional read is positive.

---

## Results (filled AFTER the pre-registration commit)

`python3 -m backtest.run_orb_probe` (a strictly later commit than the frozen section above
— see git history).

### Data situation — the pre-registered read is DATA-BLOCKED

- **Alpaca 2016+ (primary): unreachable in this sandbox.** `.env.backfill` is **absent**
  (gitignored), and no `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` are set. A direct
  unauthenticated GET to `https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=5Min…`
  returns **HTTP 401 Unauthorized**, confirming the data host is key-gated. So the runner's
  `_fetch_alpaca` returns `None` and falls back.
- **yfinance (fallback): reachable but far too shallow.** The live run fetched **60
  sessions / 4,610 bars, span 2026-04-29 → 2026-07-24** — i.e. ~3 calendar months, **zero**
  complete 12-month windows (n_w = 0), and **60 sessions ≪ the 500-session power floor** and
  nowhere near the 2016+ (~n_w ≈ 9) basis the read is pre-registered on.

Therefore the pre-registered directional read **cannot be run on free data available here.**

### Plumbing smoke only (NOT the read — do not interpret)

Produced to prove the machinery runs end-to-end on the shallow fallback sample; every row
is below the power floor and is explicitly **not** the directional read:

| variant (target) | CalmarUS | CAGR (pretax) | maxDD | #trades | random | always-in | beats both? |
|---|---|---|---|---|---|---|---|
| EOD-close (None) | −3.382 | −43.3% | −12.6% | 52 | −3.583 | +2.209 | no |
| R = 5  | −3.382 | −43.3% | −12.6% | 52 | −3.568 | +2.209 | no |
| R = 10 | −3.382 | −43.3% | −12.6% | 52 | −3.554 | +2.209 | no |

(The three target variants coincide because on this brief up-drifting sample no 5R/10R
target is ever reached intraday, so all three exit at the session close — expected on 60
sessions; meaningless as a verdict.)

---

## Verdict

**DATA-BLOCKED — the pre-registered directional read is not answerable on the free data
reachable here.** The Alpaca 2016+ read-only path needs the paper/data keys (`.env.backfill`,
absent here; unauthenticated = HTTP 401), and the yfinance fallback reaches only ~60
sessions (3 months, n_w = 0), far short of the pre-registered 2016+ / 500-session floor. No
ORB edge is claimed and none is fabricated; the shallow-sample numbers above are a labelled
plumbing smoke, not the read.

### On "is full-power intraday data worth paying for?" — recommendation: **No, not on this evidence.**

The deliverable question is answered as a recommendation (the read itself being blocked):

1. **It would re-test a class already ruled NO-GO.** #422's short-horizon feasibility gate
   (`2026-07-24-famous-traders-strategies-survey.md` §2.2; `…entry-feasibility-gate.md`)
   ruled the whole intraday/minute rule-based-**entry** class NO-GO. ORB is squarely inside
   it. #422 is the named revisit trigger for the *indicator-family* question, not a
   reopening of that settled result — a positive ORB read would be a reason to *revisit*,
   not a standing reason to spend.
2. **The nearest real-world evidence is a kill.** The colleague's own **London**-ORB
   variants **all lost** ("Intraday-Frage endgültig geschlossen",
   `2026-07-20-colleague-repo-audit.md` §2). This probe is a **US-market** ORB — a genuinely
   *different* setup (different session, liquidity, open dynamics), which is exactly why it
   was worth naming and probing rather than dismissing by analogy — but the only adjacent
   empirical result points the same way as #422.
3. **The one positive citation is narrow.** Zarattini & Aziz (2023) is **instrument- and
   era-specific** (QQQ/TQQQ, a strong 2016–2023 tech-momentum window) and **long/short**;
   this engine can only test the **1× long arm**, and even the promotion bar (n_w = 13) is
   unreachable on free data — so buying data would still leave a single-regime, single-
   instrument, long-only test that cannot clear the repo's comparability bar.

Net: paying for Databento/FirstRate-class intraday data to chase ORB is **not justified by
this probe**. The defensible next step is to leave ORB filed as DATA-BLOCKED and revisit
only if the operator independently decides to fund a full-power intraday dataset for a
broader intraday program (a #422-scoped budget decision this package is not authorized to
make).

### Reconciliation (required)

- **Colleague's London-ORB kill:** a *different* market/session; this US ORB is not the same
  setup, so its kill does not by itself settle the US case — but it is the closest empirical
  read and it is negative. Noted, not over-read.
- **#422 revisit trigger:** this probe is the named ORB revisit, not a reopening of the
  settled intraday-entry-class NO-GO; a DATA-BLOCKED result leaves that settlement intact.

### What would change the verdict

Re-running `python3 -m backtest.run_orb_probe` with `ALPACA_API_KEY_ID` /
`ALPACA_API_SECRET_KEY` set (or a paid 5-min source wired into `_fetch`) would fetch the
2016+ history, cross the `PROBE_MIN_SESSIONS` floor, and produce the actual directional
read (`beats both?` per variant). Only then is the "worth paying for full-power data"
question answered from data rather than from prior-class reasoning.

### Engine note

The reusable `backtest/bracket.py` engine gained one additive, default-off
`session_close_out` mode (intraday EOD-flat) for this probe; all 28 bracket tests stay
green. The DATA-BLOCKED result is on **data access**, not the harness — which is ready to
deliver the read the moment 2016+ intraday bars are available.
