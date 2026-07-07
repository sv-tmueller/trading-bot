# Code Review Findings — 2026-06-11

Full-repo review of the production TypeScript bot (Supabase Edge Functions + Alpaca), the
migrations, and the `web/` dashboard, plus answers to the operator's status questions.
Companion doc: [`2026-06-11-margin-increase-assessment.md`](2026-06-11-margin-increase-assessment.md)
(verdict: **do not increase margin** — defer pending evidence).

## Resolution status (2026-06-11)

> **Stale-base correction (2026-06-11, merge pass):** the review was performed against a stale
> clone at `70b73cd` (#236); `origin/main` was in fact 17 commits ahead. Three findings had been
> independently fixed upstream before this review: finding **2** ≈ #237 (`e49a04e`, kill-switch
> broker-truth), parts of **11** ≈ #238 (`b906e21`, audit seams), parts of **15** ≈ #239
> (`7eed6dd`, money-path tests). The review also missed #256's post-open execution rework and the
> `0003`–`0006` migrations (our Vault-grants migration is renumbered to `0007`). The branch has
> been semantically merged with `origin/main`: where upstream already fixed a finding, upstream's
> implementation was kept as the base and only the genuinely additive parts of ours (desync
> notification + protection-continuation on a missing `regime_state` row, implausible-drawdown
> guard) were layered on top. The list below reflects the post-merge state.

Fixed on branch `claude/code-review-margin-analysis-yaxilr`:

- **1** (#265) — `adjustment=all` bars + kill-switch implausible-drawdown guard (`error:implausible_drawdown`).
- **2** (#266) — broker-truth sourcing was already upstream (#237); this branch adds the `notifyStateDesync` alert + `state_desync` audit note, and continues the drawdown check (instead of `skipped:no_regime_state`) when no `regime_state` row exists, so the live position stays protected.
- **3 + 4** (#267) — poll loop breaks on `rejected`/`canceled`/`expired` (`OrderRejectedError`); timeout path re-checks after the cancel and returns full/partial fills so callers record them.
- **5** — panic requires POST; constant-time (SHA-256 digest) token comparison; HTTP-layer tests added.
- **6** (#268) — `deno task test` sets `CLAUDE_AGENT_NO_BROKER=1`; `alpaca.test.ts` only lifts the guard in the specific tests that exercise the mutating helpers' stub-fetched HTTP path.
- **9** — migration `0003_vault_fn_grants.sql` revokes EXECUTE from `anon`/`authenticated`.
- **10** — `kill_switch_fired_at` carried through on re-entry.
- **11** — paused check moved inside the try/catch.
- **13** (#185, option 1) — panic `liquidate` also sets `paused=true` by default; `?pause=false` opts out for a flatten-and-resume; the result string says which happened.
- **12** — dashboard requires HTTP Basic Auth (fail-closed `web/middleware.ts`); Alpaca key-scope wording corrected.
- **14** — `requireNumber` rejects whitespace-only strings.
- **15 (partial)** — added: rejected-order, timeout-race partial-fill, recorded-partial-fill, and panic HTTP-layer tests.

Still open (not addressed here):

_(as of 2026-07-06, #341 close-out of #269): none of the below remain open._

- ~~**7** — anon-key invocability + concurrency guard~~ — closed: authz via #291 → PR #294 (`e492105`); concurrency guard via #293 → PR #297 (`628b64e`).
- ~~**8** — kill switch fires on a single IEX print~~ — closed: #299 → PR #300 (`c525fa7`); hardened by PR #331 and PR #338.
- ~~**15 (rest)** — "order filled but DB write throws" and kill-switch "liquidate succeeds, `insertTrade` fails" tests~~ — closed: DB-failure tests via PR #272 (`b7b0c7d`); canceled/expired zero-fill terminal test via this PR (#341).

Full citations and the two open caveats (F9 privilege-test dropped per #292 closure; F12 dashboard-auth default-OFF posture) are in the evidence audit posted to #269.

## Operator questions

### Is the bot running?

Per `docs/CURRENT_CONFIG.md` (reviewed 2026-06-05): deployed on the **dev** Supabase project
(`qdaxxsuicyiscdvsdowc`) with `ALPACA_PAPER=true`, soaking since 2026-06-05. **Prod is not
deployed** — no real money is at work. This review was done from a sandbox without Supabase
credentials, so live cron health was not verified; to confirm, run in the dev SQL editor:

```sql
select script_name, started_at, finished_at, outcome
from audit_log order by started_at desc limit 10;
```

### How much money would we have made yesterday (2026-06-10)?

We would have **lost** money — on paper. SPY closed at 7,266.99, above its 200-DMA (~6,872),
so the regime was LONG and the bot held UPRO through the session. The S&P 500 fell **−1.62%**
on the hot CPI print (4.2% YoY), so UPRO (3× daily) was down roughly **−4.9% ≈ −$4,860 per
$100k** of account equity. The kill switch (25% drawdown from the 30-day high) would not have
fired. A single red day four trading days into a mandated ≥1-month paper soak carries no
signal about the strategy — see the margin assessment doc.

## Review findings

Severity: CRITICAL / HIGH / MEDIUM / LOW. File:line references are at commit `70b73cd`.

### HIGH

**1. `adjustment=raw` market data diverges from the backtested signal and can falsely fire the kill switch on a split.**
`supabase/functions/_shared/marketdata.ts:29` requests `adjustment=raw`, while the backtest
that validated the strategy uses fully adjusted data (`backtest/regime.py:42`,
`auto_adjust=True`). (a) The live SPY 200-DMA is computed on dividend-unadjusted closes, so
the live signal is not the backtested signal — quarterly ~0.3–0.4% dividend gaps shift the
SMA near crossover points. (b) Worse: the kill-switch reference high
(`kill-switch/logic.ts:88-89`) is the max over 30 days of **raw** UPRO highs — a forward
split (leveraged ETFs split regularly) makes pre-split highs 2–4× the post-split price,
producing an instant fake −50%…−75% "drawdown" and an erroneous full liquidation.
*Fix:* `adjustment=split` (minimum) for the kill-switch ticker, consider `adjustment=all`
for the benchmark; sanity-check that refHigh/lastPrice is plausible.

**2. A filled order whose DB write fails leaves a live 3× position invisible to the kill switch for up to ~72h.**
`daily-check/logic.ts:140-144`: if `placeMarketOrder` fills but `insertTrade` (or
`upsertRegimeState`, line 170) throws, the run exits `error:*` with
`regime_state.current_state` still `CASH`. The kill switch trusts the DB only
(`kill-switch/logic.ts:66` exits `success:no_position` when state ≠ LONG, never checking the
broker), so a real UPRO position sits unprotected until the next daily-check reconciliation —
24h normally, ~72h over a weekend. *Fix:* kill-switch should reconcile against
`alpaca.getPosition()` when the DB says CASH (cheap read-only call).

**3. Order-timeout path races with a concurrent fill; its cancel error handling is dead code.**
`_shared/alpaca.ts:126-132`: on poll timeout the code fires a best-effort cancel and throws
`OrderTimeoutError`. The order can fill between the last poll and the cancel; the code never
re-checks after cancelling, so a filled or **partially filled** order is reported as a
failure — shares owned, no `trades` row, DB state wrong (feeds finding 2). Also `trade()`
(line 53) never throws on non-2xx, so the `try/catch` at 127-129 can never catch anything.
*Fix:* after the cancel attempt, GET the order once more; if `filled`/`partially_filled`,
return the fill so callers record it.

### MEDIUM

**4. Order poll loop ignores terminal states** (`rejected`/`canceled`/`expired`) —
`_shared/alpaca.ts:113-125` only checks `filled`; a rejected order spins the full 30s and
reports a misleading `OrderTimeoutError`. *Fix:* break on terminal statuses with a distinct
error carrying the rejection reason.

**5. Panic token compared with non-constant-time `!==`; any HTTP method accepted.**
`panic/index.ts:13` — the single credential protecting pause/cancel/liquidate (deployed
`--no-verify-jwt`) gets an early-exit string compare, and a `GET` triggers state-changing
actions. *Fix:* timing-safe digest compare; require `POST`.

**6. The `CLAUDE_AGENT_NO_BROKER` safety net is not wired into the TS test harness — and `alpaca.test.ts` deletes it.**
CLAUDE.md says "the test setup sets it so any forgotten mock fails fast", but post-migration
nothing does: `deno.json`'s `test` task sets no env, there is no autouse-fixture equivalent,
and `_shared/alpaca.test.ts:14` (`setKeys()`) **deletes** the var for every test in the file.
The guard code itself is correct, but the mechanical enforcement that answered incidents
#149/#168 currently depends entirely on the parent shell. *Fix:* set the var in `deno task
test`; scope the deletion to the specific tests exercising the unguarded path.

**7. `daily-check`/`kill-switch` invocable by any anon-key holder; no concurrency guard.**
Supabase `verify_jwt` accepts the anon key, so anyone with it can trigger the full trading
flow (`daily-check/index.ts:38`). Verified separately: two overlapping invocations can both
compute a flip and double-order — no advisory lock or per-date idempotency key around the
trade section. (Mid-day invocation passing the stale-data guard via the in-progress daily bar
is plausible but unverified.) *Fix:* require the service-role `sub` claim; take a Postgres
advisory lock / unique-per-date guard.

**8. Kill switch liquidates on a single IEX trade print.**
`kill-switch/logic.ts:87-90` uses `getLatestTradePrice` (`marketdata.ts:46`, `feed=iex`,
~2% of consolidated volume) — one stale/outlier print below threshold triggers a full
irreversible liquidation. *Fix:* sanity-check against the quote midpoint or require two
consecutive breaching reads.

**9. Vault-helper functions revoke EXECUTE from `PUBLIC` but not `anon`/`authenticated`** (partially speculative).
`supabase/migrations/0002_schedule.sql:21-22` — Supabase default privileges grant EXECUTE
directly to `anon`/`authenticated`, which a `PUBLIC` revoke does not remove, so
`_service_role_key()` is likely callable via PostgREST RPC. No leak today (SECURITY INVOKER +
no vault access for anon), but one `security definer` refactor away from leaking the
service-role key. *Fix:* `revoke execute ... from anon, authenticated;`.

### LOW

**10. Re-entry day erases `kill_switch_fired_at`** — `daily-check/logic.ts:173` overwrites the
forensic timestamp with `null` on same-day re-entry. *Fix:* carry `latest?.kill_switch_fired_at` through.

**11. `paused` check sits outside the try/catch** — `daily-check/logic.ts:74-78`; a throw from
`db.getConfig("paused")` escapes and the audit row stays open without an `error:*` outcome.

**12. Dashboard has no authentication; "READ-ONLY" Alpaca keys are full trading keys.**
`web/app/page.tsx` renders equity/positions/trades to anyone reaching the deployment;
`web/lib/alpaca.ts:1-4` mislabels unscoped Alpaca keys as read-only. *Fix:* Vercel
protection/auth middleware; correct the wording.

**13. `panic?action=liquidate` doesn't pause** — `panic/logic.ts:46-58`; if SPY is still
bullish, the next daily-check re-buys the position the operator just dumped. *Fix:* set
`paused=true` as part of liquidate, or make the runbook's incident path one call.

**14. `requireNumber` accepts whitespace strings as 0** — `_shared/num.ts:9`; `Number(" ")`
is `0`. *Fix:* trim before the empty-string check.

**15. Test coverage gaps on the money paths:** no test for "order filled but DB write throws"
(finding 2); no `rejected`/`canceled` order-status test; no partial-fill test; zero tests for
`panic/index.ts` HTTP layer (token, method, 500 mapping); no kill-switch test for "liquidate
succeeds, `insertTrade` fails".

## Reviewed and clean

- `regime.ts` is a genuine 1:1 port of `strategy/regime.py` (validation, NaN→CASH, strict `>`,
  bullish-clears-flag). "Kill-switch flag never blocks re-entry" is an accepted design
  decision, not a bug.
- SMA window has no off-by-one (210 bars fetched, NaN-guarded twice).
- Broker guard covers all three mutating helpers; `liquidate` routes through
  `placeMarketOrder`; read-only helpers can't order.
- RLS is deny-all on all four tables; functions use the service-role client.
- Cron windows + `/v2/clock` early-exit handle US DST correctly; UTC date logic is sound.
- Single-run idempotency holds (same-day re-run upserts the same dated row).
- No secrets committed; `PANIC_TOKEN` unset fails closed; `ALPACA_PAPER` defaults to paper.
- Notifications never throw; panic's audit row is written before the broker call and updated
  in both success and error paths.
