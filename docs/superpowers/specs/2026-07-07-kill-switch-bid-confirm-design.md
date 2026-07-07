# Design: bid-confirm the kill-switch down-breach (issue #304)

**Date:** 2026-07-07
**Status:** approved (brainstorm) — pending spec review
**Issue:** #304 (the brainstorm-gated item)
**Gated on:** #230 live-money cutover — implementation issue is filed to the backlog, **not** dispatched. This spec front-loads the design during the paper-soak window (#229).

## Motivation

The kill-switch B1b dual-breach confirmation (#299, shipped in #300) fires only if
**both** the trade-price drawdown **and** the quote-**midpoint** drawdown breach
`KILL_SWITCH_DRAWDOWN_PCT` (`kill-switch/logic.ts:190–202`).

A *successfully-returned but degraded* quote defeats this. In a fast crash the ask
can be stale-high (real bid 68, stale ask 120 → mid 94). Against a rolling high of
100 the mid-drawdown is only −6%, within a −30% threshold, so a genuinely −32%
position returns `skipped:breach_unconfirmed` and does **not** liquidate.

This is **asymmetric** with the quote-*outage* path: a thrown quote error fails
toward protection (fires on the trade alone), but a degraded-but-returned quote
*suppresses*. A partially-bad quote is thereby trusted more than an absent one,
which is backwards. On real money a ~5-minute suppression on a 3× vehicle
mid-crash is a materially larger error than on paper.

### Decisions taken in the brainstorm

1. **SIP is complementary, not the fix.** `ALPACA_DATA_FEED=sip` (consolidated
   NBBO) makes a stale-high ask far rarer but does not change the asymmetry logic,
   and even a *clean* quote leaves a structural gap: for a **down**-breach the
   realizable price is the **bid**, and `mid = (bid+ask)/2 > bid`, so mid-confirm
   is lenient by half the spread near the threshold. The logic must be correct on
   its own; SIP independently reduces how often it is exercised.
2. **Bias toward protection.** On real money, confirm the down-breach against the
   **bid** (the price you could actually sell at). The re-entry mechanics bound the
   cost of the failure this introduces (see below).
3. **Hard-swap, no config flag.** Replace the confirmation signal directly. Only
   paper exists today (prod is not live), so a flag buys nothing operationally now;
   the soak measures bid-confirm directly and a revert is one commit.

### Why bid is the right signal (preserves B1b intent *and* fixes #304)

- **Original B1b intent** — one thin low trade print must not liquidate the 3×
  alone: under bid-confirm, a low trade print with a *healthy bid* → bid not
  breached → still suppresses. **Preserved.**
- **#304 pathology** — real bid crashed, stale-high ask inflates the mid: trade
  breached **and** bid breached → fires. **Fixed** — the mid is out of the decision
  entirely.
- Because `bid ≤ mid` always, bid-confirm fires in a strict superset of the mid
  cases, so it subsumes the mid logic — no need to keep both.

### The failure this introduces, and why it is acceptable

The new risk is a stale-**low** bid causing a false fire (liquidating a healthy 3×
position). It is bounded and self-healing:

- A false fire requires **two** independent low signals — the last trade *and* the
  bid — not the bid alone; the trade-price drawdown must breach before the quote is
  even fetched.
- A spurious fire can only happen while the position is LONG, which means the
  regime is still bullish (`SPY > 200-DMA`). `computeTargetState`
  (`regime.ts:43`) clears the kill-switch flag and returns `LONG` on a bullish
  daily-check, so **the next daily-check re-enters LONG**. Cost ≈ one 3× round-trip
  + being in CASH until the next daily-check (~1 trading day), then self-heals.
- Whipsaw is capped at once/day by the `#293` `trade_claims` claim and is fully
  visible in `audit_log`.
- SIP shrinks this risk too: an all-venues-stale-low NBBO bid is very unlikely.

Weighed against a *delayed* fire — the exact catastrophic-drawdown scenario the
kill-switch exists to cap, up to ~5 min of extra 3× downside — biasing toward
protection is the chosen trade-off.

## Goal & scope (decided)

Change the returned-quote confirmation signal in the intraday kill-switch from the
quote **midpoint** to the quote **bid**. One signal swap; no new settings, no new
guards, no feed change, no schema change.

## Architecture / changes

### 1. Confirmation logic — `supabase/functions/kill-switch/logic.ts:190–202`

Inside the existing local `try` that fetches the quote (the try/catch stays — it is
what makes a quote **outage** fail toward protection):

- Replace `const midDrawdown = quote.mid / refHigh - 1;` with
  `const bidDrawdown = quote.bid / refHigh - 1;`.
- The within-threshold guard becomes `if (bidDrawdown > -config.killSwitchDrawdownPct)`.
  On that branch: keep the `notifyError` + `finish("skipped:breach_unconfirmed", …)`
  + `return "skipped:breach_unconfirmed"`; the message text references the **bid**
  (`quote-bid dd=… (bid=…) within threshold — NOT liquidating`) instead of the mid.
- On the both-breach branch: `confirmation = "confirmed"` (now meaning
  *bid-confirmed*); rename `fireMid` → `fireBid`, set `fireBid = quote.bid`.

### 2. Audit-log finish note — `supabase/functions/kill-switch/logic.ts:268–271`

`midNote` → `bidNote`: `fireBid !== null ? ` bid=${fireBid}` : ""`, so the
liquidation finish note reads `dd=… bid=… confirmation=…`.

### 3. Unchanged by design (non-goals — do not add)

- **Outage path** — a thrown quote error still fires on the trade alone
  (fail-toward-protection). The asymmetry closes because the *returned-quote* branch
  is now protective, not because the outage branch moves.
- **Trade-side `>2×` implausibility guard** stays the sole implausibility gate.
  **No bid-side implausibility guard**: a wildly-low bid cannot fire on its own (the
  trade must breach first), and a garbage-low trade print is already caught by the
  existing `refHigh/lastPrice > 2×` exit. (Matches the architect's earlier ruling
  that the implausibility guard is a non-goal for the confirm signal.)
- **`skipped:breach_unconfirmed` outcome string** is kept — same forensic/query
  surface; only the note/message text changes.
- **No config flag**; **no `ALPACA_DATA_FEED` change** (separate cutover lever).
- **No schema / migration change.**

### 4. Invariant compliance (hard review gate)

Stays inside **invariant #1 ("one decision rule")**. No new decision rule is added:
the rule is still "SPY close vs SPY 200-DMA, modulated by the kill-switch flag"; the
kill-switch trigger is still "drawdown from the rolling high breaches
`KILL_SWITCH_DRAWDOWN_PCT`," now confirmed against the realizable (bid) price rather
than the midpoint. No new signal, no LLM in the path. The reviewer treats any
deviation as a blocking `CHANGES_REQUESTED` finding.

## Testing — `supabase/functions/kill-switch/logic.test.ts`

All Alpaca/DB calls mocked; the `CLAUDE_AGENT_NO_BROKER` guard stays intact.

- **Re-express** the existing B1b mid-based confirmation tests onto the bid.
- **#304 regression (the fix):** trade breached; ask stale-high so the mid is within
  threshold; **bid breached** → asserts it now **liquidates** (today returns
  `skipped:breach_unconfirmed`).
- **Preserved-intent:** trade breached (thin low print) but **bid healthy** → still
  `skipped:breach_unconfirmed`, no liquidation.
- **Accepted-whipsaw (documented):** trade breached **and** bid breached (stale-low
  bid) → **fires** — encodes the bounded, self-healing false-fire we chose.
- **Outage unchanged:** quote fetch throws → fires on the trade alone
  (`confirmation="unverified_quote_outage"`), still green.
- Audit-note assertion updated from `mid=` to `bid=`.

Run: `deno task test` (full suite) and the single-file form for the kill-switch
logic test.

## Rollout

- Gated on the **#230 live-money cutover**. The implementation issue is **filed to
  the backlog cutover-gated, not dispatched** now.
- Paper soak (#229) exercises the bid-confirm build directly; revert is one commit
  if it whipsaws.

## Refs

#304 (this item), #299 / #300 (B1b implementation + review), #269 finding 8 (B1b
origin), #293 (per-day liquidation claim), #230 (go-live), #229 (paper soak).
