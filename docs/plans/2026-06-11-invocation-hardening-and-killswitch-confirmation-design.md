# Invocation hardening + kill-switch price confirmation — design proposal

**Date:** 2026-06-11
**Issue:** [#269](https://github.com/sv-tmueller/trading-bot/issues/269)
**Status:** Design proposal (NOT yet brainstorm-approved — see Next steps; CLAUDE.md hard-gates every change behind `superpowers:brainstorming`)
**Source:** Findings **7** and **8** of [`docs/research/2026-06-11-code-review-findings.md`](../research/2026-06-11-code-review-findings.md), deliberately deferred from the immediate-fix batch because each needs a design decision, not just a patch.
**Scope:** Two separable proposals. They share no code and can be planned, reviewed, and shipped independently. Neither changes the decision rule — `computeTargetState` is untouched by both ("one decision rule" invariant preserved). No LLM enters any path.

File references are at the current tree (post-`adjustment=all` fix #265).

---

## Proposal A — invocation hardening for `daily-check` / `kill-switch` (finding 7)

### A.1 Problem statement

Two distinct holes, one attack/accident surface:

1. **Anyone holding the project anon key can invoke the full trading flow.** Both functions
   are deployed with `verify_jwt` (per the deploy runbook), but Supabase's `verify_jwt` only
   checks that the bearer is *a* valid project JWT — the **anon key passes**. The handlers
   ignore the request entirely (`daily-check/index.ts:38` is `Deno.serve(async () => …)`),
   so an anon-key holder can trigger order placement at will. The anon key is by design a
   low-trust, semi-public credential (it ships in any future client); it must not be able to
   move money. Contrast: `panic` has its own explicit auth (`x-panic-token`, fail-closed).

2. **No concurrency or idempotency guard around the trade section.** Two overlapping
   invocations (cron tick + a manual/dashboard invoke, or an HTTP-layer redelivery) can both
   read `current_state=CASH`, both compute `target=LONG`, and **both place a ~99%-of-account
   BUY** (`daily-check/logic.ts:130-149`). Nothing in the DB or the broker call dedupes them.
   The same applies to two overlapping `kill-switch` runs both calling `liquidate` (the
   second liquidate of a flat position returns null — mostly benign — but two *in-flight*
   liquidations can double-SELL into a short on a margin account).

#### Why overlap is realistic, not theoretical (cron/HTTP retry semantics)

- `pg_cron` fires each job once per tick; the job body is `net.http_post(...)`
  (`supabase/migrations/0002_schedule.sql:29,45`). **`pg_net` is fire-and-forget**: the cron
  transaction queues the request and returns immediately; pg_cron sees "success" regardless
  of the HTTP outcome. So the *scheduler* gives at-most-once per tick — good.
- But `net.http_post`'s default client timeout (a few seconds, version-dependent) is **far
  shorter than a daily-check run that places an order** (the fill-poll loop in
  `_shared/alpaca.ts` runs up to ~30s). The cron-side request routinely "times out" while
  the function is still executing. pg_net's timeout/retry behaviour has differed across
  shipped versions (some versions re-attempt timed-out requests); we must therefore assume
  **the HTTP layer can deliver the same tick's request more than once**, and the operator
  retrying a "timed out" manual invocation is the same hazard by hand.
- `kill-switch` runs every 5 minutes; a single run is normally <35s, so cron-vs-cron overlap
  is unlikely but not impossible during an Alpaca brownout — exactly the moment a stray
  double-liquidate hurts most.

Mid-day manual invocation of `daily-check` passing the stale-data guard via the in-progress
daily bar (flagged as plausible-unverified in the review) makes hole 1 worse: an anon-key
holder may be able to force a flip on intraday data the strategy was never validated on.

### A.2 Options considered

#### Option A1 — verify the JWT `role` claim in `index.ts` (reject non-`service_role`)

The platform's `verify_jwt` has already validated the signature before our code runs, so the
handler can decode the JWT payload (no crypto needed) and require `role === "service_role"`.
Implemented once as a shared helper (e.g. `requireServiceRole(req)` in
`_shared/auth.ts`), called at the top of both `index.ts` files; returns 401 otherwise.
A near-equivalent variant is a timing-safe comparison of the bearer against the
runtime-injected `SUPABASE_SERVICE_ROLE_KEY` env var.

- **Pros:** pure code change, no migration, no new secret, no change to
  `0002_schedule.sql` (cron already sends the service-role key from Vault). Closes hole 1
  completely. Testable as a small pure-ish helper.
- **Cons:** does nothing for hole 2 (the cron itself, or operator + cron, still overlap).
  Couples us to Supabase's legacy JWT-shaped keys — if the project migrates to the new
  publishable/secret API-key scheme, the helper needs revisiting (cheap, and the deploy
  runbook can carry a note).

#### Option A2 — shared-secret header, like `panic`

Add an `x-cron-token` header; cron jobs read it from a new Vault secret; functions compare.

- **Pros:** symmetric with the existing `panic` pattern; independent of Supabase JWT
  internals.
- **Cons:** a second secret to provision, rotate, and leak; requires editing the committed
  cron migration *and* setting a new Vault secret in every environment; duplicates a
  guarantee the service-role JWT already gives us for free. Also does nothing for hole 2.
  Strictly more moving parts than A1 for the same outcome.

#### Option A3 — Postgres advisory lock taken via an RPC function

New migration adds e.g. `claim_run_lock(script text) returns boolean` wrapping
`pg_try_advisory_lock(hashtext(script))`; the function takes it at start and releases at end
via a second RPC.

- **Pros:** a real mutual-exclusion primitive; generic across scripts.
- **Cons — disqualifying for this stack:**
  - **Session-scoped locks + PostgREST connection pooling don't mix.** The lock binds to the
    pooled backend session, not to our logical run. If the Edge Function crashes (or just
    forgets the release on an error path) the lock stays held by a pooled connection for an
    unbounded time — **a stuck lock silently blocks every subsequent daily run**, which is
    itself a risk the review explicitly tells us not to introduce. Transaction-scoped locks
    (`pg_try_advisory_xact_lock`) release at the end of the single RPC statement, i.e.
    before the broker call they're meant to protect — useless across an HTTP-spanning
    critical section.
  - **Security:** the RPC must be executable by the service role only; given finding 9
    (PUBLIC-revoke doesn't strip `anon`/`authenticated` default grants) it's one grant
    mistake away from letting an anon caller hold the trading lock hostage (cheap DoS on
    the bot).
  - Mitigations (lease tables, expiry timestamps, watchdogs) are exactly the complexity an
    idempotency key avoids.

#### Option A4 — per-date idempotency claim in the DB

Two sub-variants were analyzed:

- **A4a — unique index on `trades` (e.g. `(reason, date(fill_time))`).** Rejected as the
  primary guard: `insertTrade` runs **after** `placeMarketOrder`
  (`daily-check/logic.ts:140-144`), so the constraint fires only after the second order has
  already gone to the broker. It detects, it does not prevent. (Still worth adding as a
  cheap tripwire.)
- **A4b — claim row taken *before* the broker call.** New table:

  ```sql
  create table trade_claims (
    script_name text not null,
    trade_date  date not null,
    claimed_at  timestamptz not null default now(),
    primary key (script_name, trade_date)
  );  -- RLS deny-all, like every other table
  ```

  `daily-check` inserts `('daily-check', today)` immediately before entering the trade
  section (i.e. only when `targetState !== currentState` — no-op and `skipped:*` runs never
  consume the claim, so a morning `skipped:stale_data` cannot block the evening run).
  Insert-conflict ⇒ exit `skipped:duplicate_run` and write that to `audit_log`. PostgREST
  autocommits the insert, so the claim is visible to a racing invocation immediately.
  `kill-switch` does the same just before its `liquidate` call.

  **Wedge analysis (the fix must not be able to wedge the bot):** the failure direction is
  deliberately *fail-toward-no-trade*. If a claimant crashes after claiming but before the
  order, that day's flip is lost — and self-heals: the run exits `error:*` (operator is
  alerted via `notifyTradeFailed`/`notifyBrokerError`), and tomorrow's `daily-check` is a
  fresh `trade_date`, recomputes the regime, and reconciles against broker truth. Worst
  case is ≤1 trading day un-flipped, which is the same exposure as any single failed run
  today — versus the alternative failure direction, a double-sized 3× position. No lock is
  held across processes; nothing can block tomorrow's run. We do **not** delete the claim
  on error (the order may have reached Alpaca before the crash; releasing would re-open the
  double-order window).

- **Pros:** prevents (not just detects) double-ordering; survives crashes without any
  lock-holder cleanup; idempotency matches the function's own per-trading-day semantics;
  trivially testable through the injected `deps.db`.
- **Cons:** new migration + new `db.ts` helper; doesn't address hole 1 (auth) at all;
  per-date granularity means a *legitimate* second flip on the same date is blocked — which
  is fine, because the strategy by design trades at most once per day per script.

#### Complement (free, broker-side): deterministic Alpaca `client_order_id`

Alpaca rejects an order reusing a `client_order_id`. Setting it deterministically —
`daily-check:{YYYY-MM-DD}:{side}`, `kill-switch:{YYYY-MM-DD}` — makes the **broker itself**
the last line of dedupe even if both DB-layer guards are somehow bypassed. One-line change
in `placeMarketOrder` callers; no migration. (Note: `liquidate` uses Alpaca's
DELETE-position endpoint via `placeMarketOrder` routing — confirm during planning which leg
accepts the id; if the close-position endpoint doesn't, the claim row still covers it.)

### A.3 Decision (recommended)

**A1 + A4b + the `client_order_id` complement.** A2 is redundant with A1; A3 is rejected
outright (stuck-lock wedge risk on a pooled-connection stack).

Defense in depth, one layer per hole:

| Layer | Closes | Mechanism |
|---|---|---|
| `requireServiceRole(req)` in both `index.ts` | hole 1 (anon-key invocation) | reject non-service-role JWT, 401, before `buildDeps()` |
| `trade_claims` insert-before-order | hole 2 (overlap double-order) | unique `(script_name, trade_date)`, fail-toward-no-trade |
| deterministic `client_order_id` | residual | broker-enforced dedupe |
| unique tripwire index on `trades` (A4a) | forensics | detects what the above somehow missed |

**Effort:** ~1–1.5 engineer-days. Auth helper + tests ≈ half a day; migration
(`0003_trade_claims.sql`, including the finding-9-style explicit
`revoke ... from anon, authenticated`) + `db.ts` helper + logic-path changes + tests ≈ one
day. No change to `0002_schedule.sql`.

**New tests required (all Alpaca/DB mocked per CLAUDE.md; `CLAUDE_AGENT_NO_BROKER` backstop):**

- `requireServiceRole`: anon-role JWT → 401; service-role JWT → pass; malformed/absent
  bearer → 401; both functions' `index.ts` wired through it.
- `daily-check` logic: claim conflict → `skipped:duplicate_run`, **no** broker call (assert
  `placeMarketOrder` mock uncalled); claim taken only when a flip is due (no-op day inserts
  no claim); claim insert throws non-conflict error → `error:*` path, no order.
- `kill-switch` logic: claim conflict before `liquidate` → exits without liquidating.
- `placeMarketOrder` sends the deterministic `client_order_id`; duplicate-id 422 from the
  mocked broker surfaces as a distinct, non-retried error.
- DB-gated test (`RUN_DB_TESTS`): two concurrent claim inserts — exactly one wins.

### A.4 Consequences

- The anon key becomes harmless to the trading path; the only credentials that can move
  money are the service-role key (Vault-held, cron-only) and `PANIC_TOKEN`.
- A duplicate invocation becomes a logged no-op (`skipped:duplicate_run` in `audit_log`)
  instead of a double order — and the audit row makes the *attempt* visible, which is
  forensically better than today.
- Accepted residual: a crash between claim and order forfeits that day's flip (alerted,
  self-healing next day). This is the correct failure direction for a 3× vehicle.
- The deploy runbook gains one note: if Supabase migrates the project off JWT-shaped keys,
  `requireServiceRole` must be updated in the same change.

---

## Proposal B — kill-switch price confirmation (finding 8)

### B.1 Problem statement

`kill-switch/logic.ts:88-91` computes drawdown from **one** `getLatestTradePrice` call, and
`marketdata.ts:49` pins that to `feed=iex`. IEX is ~2% of consolidated US volume; its last
print can be a stale or odd-lot outlier, especially in fast or thin tape. A single print
≥25% below the 30-day reference high triggers a **full, irreversible liquidation** of the
3× position. The 30-day lookback highs (`getDailyCloses`, `marketdata.ts:32`) are IEX-only
too, so the reference high itself is a thin-feed estimate (less dangerous post-#265
`adjustment=all`, but it shifts the effective threshold).

Both the cost of firing late and the cost of firing falsely are real money; the design must
pick where to spend the error budget. The project's stated goal (margin-assessment doc,
CLAUDE.md): **minimize risk and drawdown**.

#### Quantifying the trade-off

- **Cost of one extra 5-minute confirmation tick (delayed true fire).** UPRO is 3× daily
  SPY. In a severe-but-ordinary crash leg, SPY moves −0.5%…−1% per 5 minutes ⇒ UPRO −1.5%…
  −3% per tick. At flash-crash velocity (May 2010: SPY ≈ −5% in minutes; the L1 7% circuit
  breaker now caps a single uninterrupted leg) a tick of delay can cost UPRO −9%…−15%
  before a halt intervenes. On a $100k account 99% invested, the position at the firing
  boundary is worth ≈ $75k; one delayed tick therefore costs **≈ $1.1k–2.2k typically,
  bounded near ≈ $7k–11k** in a limit-down-style move. This cost is paid on **every true
  fire** if confirmation is unconditional.
- **Cost of a false liquidation.** Round-trip slippage/spread on UPRO (deeply liquid):
  tens of bps ≈ $150–400 on $75k. Re-entry: the kill-switch flag does **not** block
  re-entry (`regime.ts` clears it when bullish — accepted design), so if SPY is still above
  its 200-DMA the next `daily-check` re-buys within ~24h (≈72h over a weekend); the
  whipsaw exposure is up to one UPRO daily σ ≈ 3–4% of equity, symmetric in sign but a
  *forced* coin-flip ≈ expected cost ~$0 ± $2–3k of variance, plus the realized loss
  crystallizing a taxable event in a live account at the worst possible price. Material,
  but a false fire needs a print **25% below the 30-day high** — only plausible from gross
  data error (the split-gap case is already fixed by #265) or a true dislocation.

Conclusion baked into the recommendation: an **unconditional** delay charges the
$1k–11k true-fire cost every time to insure against a rarer, smaller false-fire cost.
Confirmation should be **conditional on the data disagreeing**, not always-on.

### B.2 Options considered

#### Option B1 — cross-check the latest trade against the latest quote midpoint

Add `getLatestQuote(symbol)` to `marketdata.ts` (`/v2/stocks/{symbol}/quotes/latest`,
`feed=iex` on the free plan), midpoint = (bid+ask)/2. Two sub-variants:

- **B1a — tolerance agreement:** require `|trade − mid| / mid ≤ tol` (new env
  `KILL_SWITCH_PRICE_TOLERANCE_PCT`, range-validated in `config.ts`) before acting on the
  trade print. Weakness: in a *real* crash, quotes go wide and trade-vs-mid disagreement is
  normal, so a tight tolerance can suppress true fires repeatedly; tolerance tuning is a
  new free parameter with no backtest behind it.
- **B1b — dual-breach (recommended variant):** compute drawdown twice — once from the last
  trade, once from the quote midpoint — and **fire only if both breach the threshold**. No
  tolerance parameter. A stale/outlier print is, by definition, not where the market is
  quoted, so its midpoint drawdown won't breach; in a genuine −25% dislocation, bid/ask are
  down there too (wide quotes don't matter: if even the *ask* side has collapsed 25%, the
  midpoint breaches). If trade breaches but midpoint doesn't ⇒ exit
  `skipped:breach_unconfirmed` + `notifyError` (operator sees every suppressed fire). If the
  quote fetch **fails or returns no quote** ⇒ **fail toward protection**: proceed on the
  trade print alone (today's behaviour) + notify — a data outage must never disarm the kill
  switch.
- **Pros:** zero added latency on confirmed real crashes; no state, no migration; both
  fetches are read-only and same-tick.
- **Cons:** the quote is also IEX, so a *systematic* IEX-vs-consolidated divergence fools
  both legs (mitigated: divergence large enough to matter at a 25% threshold is far less
  likely to afflict trade *and* NBBO-ish quote simultaneously than one print).

#### Option B2 — require two consecutive breaching reads (two 5-minute cron ticks)

Persist "breach pending" state; fire on the second consecutive breach; clear on any
within-threshold tick. **Where to carry the state:**

- `regime_state` — add a nullable `kill_switch_breach_at timestamptz` column (migration).
  Right shape: the kill-switch already upserts the day's row every tick
  (`logic.ts:94-103`); typed, per-day, forensically queryable next to
  `position_drawdown_pct`. One subtlety: the row is keyed by date, so a breach pending at
  20:55 UTC and the next tick after the UTC date rollover would land on a new row — not a
  real concern inside US market hours (13–21 UTC window), but the clear-on-new-date rule
  must be explicit.
- `bot_config` KV — no migration, but it's the operational-flags namespace (`paused`);
  stuffing per-tick strategy state into an untyped KV row hides it from forensics and from
  the dashboard, and a stale leftover value (e.g. after a deploy mid-breach) is invisible.
  Rejected as the home if B2 is built.
- **Pros:** robust to *any* single-read garbage, including systematic single-tick feed
  weirdness that fools B1.
- **Cons:** **guaranteed +5 minutes on every true fire** — the $1.1k–11k/tick cost from
  §B.1, paid precisely in the scenarios the kill switch exists for; plus a migration and a
  new stateful code path (the only inter-tick state machine in the bot).

#### Option B3 — switch to the SIP feed

`marketdata.ts` hard-codes `feed=iex` in both endpoints; the MVP2 spec (§11) explicitly
chose IEX as the free feed pending confirmation. Real-time SIP (`feed=sip`) requires
Alpaca's paid market-data subscription (Algo Trader Plus, ≈ $99/month); the free
`feed=delayed_sip` is 15 minutes stale — worse than useless for a crash trigger.

- **Pros:** fixes the root cause (thin feed) for trigger *and* lookback highs; no logic
  change, no added latency.
- **Cons:** recurring cost on a bot still in paper soak on a dev project; doesn't protect
  against a single bad SIP print either (rarer, but the single-print architecture remains).
- Cheap hedge regardless of the decision: make the feed an env setting
  (`ALPACA_DATA_FEED`, default `iex`, validated against `iex|sip`) following the
  opt-in/default-unchanged recipe in `.claude/skills/add-or-extend-agent/SKILL.md`, so
  upgrading later is a `supabase secrets set`, not a deploy.

#### Option B4 — combinations

B1b + escalate-to-B2 only when quotes are unavailable, etc. Analyzed and rejected for now:
the marginal protection over B1b alone is small, while the state machine and the test
matrix grow disproportionately. B1b + B3-as-config-knob captures nearly all the value.

### B.3 Decision (recommended)

**Option B1b (dual-breach trade + quote-midpoint confirmation), plus the `ALPACA_DATA_FEED`
config knob from B3 (default `iex`, no subscription bought yet). Not B2.**

Rationale, tied to the stated goal (*minimize risk and drawdown*): the dominant risk on a
3× vehicle is the **true** crash, and B1b adds **zero delay** to confirmed true fires while
suppressing the outlier-print false fire — it spends the error budget only when the two
data sources disagree, i.e. exactly when the data is suspect. B2 inverts that: it charges
$1.1k–11k of extra drawdown per true fire as a flat premium against a rarer, smaller-loss
event. The quote outage path fails toward protection (fire on trade alone + alert), so the
new check can never disarm the switch. Revisit B3's paid SIP at the live-money cutover —
the margin-assessment doc already gates that decision on soak evidence.

**Effort:** ~1 engineer-day. `getLatestQuote` + midpoint helper, ~15 lines in
`kill-switch/logic.ts` (second drawdown + branch), `config.ts` feed knob, tests. No
migration.

**New tests required (all mocked):**

- `marketdata.getLatestQuote`: happy path; missing `quote` → `DataError`; non-numeric
  bid/ask → `DataError`; feed param honors `ALPACA_DATA_FEED`.
- `kill-switch` logic: trade and midpoint both breach → liquidates (unchanged outcome
  `success:kill_switch_fired`, notes carry both prices); trade breaches, midpoint doesn't →
  `skipped:breach_unconfirmed`, **no** liquidate call, `notifyError` called,
  `position_drawdown_pct` still persisted; quote fetch throws → liquidates on trade alone +
  notify (fail-toward-protection); neither breaches → `success:within_threshold` unchanged.
- `config.ts`: `ALPACA_DATA_FEED` default `iex`; invalid value throws.

### B.4 Consequences

- A genuine crash fires on the same tick it does today; only data-inconsistent ticks are
  deferred, and every deferral is alerted and audit-logged — silent suppression is
  impossible.
- Accepted residual: a real dislocation that IEX trades print but IEX quotes lag by one
  tick fires 5 minutes late, with the operator alerted at the first (suppressed) tick.
  Bounded by the same §B.1 numbers, but now paid only in a corner case instead of always.
- The lookback-high thinness (IEX daily highs) is *not* fixed here; it slightly perturbs
  the effective threshold, not the trigger's integrity. The `ALPACA_DATA_FEED` knob makes
  the eventual SIP upgrade a config change covering trigger and lookback at once.
- `audit_log` gains one new outcome string (`skipped:breach_unconfirmed`), consistent with
  the existing `skipped:*` taxonomy.

---

## Next steps

1. **Brainstorm sign-off** — per CLAUDE.md this design is gated on
   `superpowers:brainstorming` with the operator before any plan is written. Key questions
   to settle there: accept fail-toward-no-trade for A4b's crash residual? accept
   fail-toward-protection for B1b's quote-outage path? buy SIP now or at live cutover?
2. **Plans** — on sign-off, write two independent implementation plans via
   `superpowers:writing-plans`: `docs/plans/<date>-invocation-hardening-plan.md` and
   `docs/plans/<date>-killswitch-price-confirmation-plan.md` (separable; A touches
   `index.ts`/migrations, B touches `marketdata.ts`/`kill-switch/logic.ts` — no file
   overlap, so they can even land in parallel worktrees).
3. **Build** — `superpowers:subagent-driven-development`: engineer + spec-reviewer +
   code-quality-reviewer per task; code-quality-reviewer re-verifies the architectural
   invariants (one decision rule untouched, no LLM in path, kill button intact).
4. **Tracking** — both proposals roll up under issue **#269**; cross-reference findings 7
   and 8 in the review doc when closing.
