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
— see git history). See the [Verdict](#verdict) for the data situation.

_Filled in the results commit below._

---

## Verdict

_Filled in the results commit below._
