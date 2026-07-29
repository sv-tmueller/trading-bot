# Hourly-Bot Rollout Runbook (dev/paper)

Rolls the hourly-candlestick long/short SPY bot (`hourly-check`, #475/#477, spec
`docs/superpowers/specs/2026-07-27-hourly-bot-design.md`) out to the Supabase **dev**
project and starts its first paper trades, per the batch #478 sub-plan (#479 T1-T12,
lead-ratified rulings on #478).

## §1 Scope banner (restated for scanners)

- **Dev/paper only.** Project ref **`qdaxxsuicyiscdvsdowc`**. Nothing in this runbook
  ever touches prod (`yomamlrozydhgleumnon`) — go-live is a separate, unrelated,
  runbook-driven decision (`docs/runbooks/mvp2-deploy-and-decommission.md`) that has
  never happened for either bot.
- **`HOURLY_SHORTS_ENABLED=false` is non-negotiable for this rollout.** The
  `/v2/assets/SPY` shortability fields **are confirmed** against a live paper response
  (§12 appendix, row 4 — `shortable: true`, `easy_to_borrow: true` for SPY itself), so
  this is **not** a capability gap; the flag stays `false` as the batch's own standing
  decision, independent of SPY being shortable. Do not set this to `true` as part of
  this runbook.
- **`bot_config.paused` starts `true`** (repo-facts baseline, #479) and must stay
  `true` until migration `0013_retire_daily_check_cron.sql` has been applied — see the
  red-letter precondition in §6. Resuming before 0013 re-arms the retired daily-check
  bot's entry crons on the same paper account.
- **Never run `deno task test:db` / `RUN_DB_TESTS=1 deno task test:db` against the
  dev project (`qdaxxsuicyiscdvsdowc`).** `supabase/functions/_shared/db.test.ts`
  builds its client from `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`, which only
  *default* to the local `supabase start` stack — those two vars must point at the
  local stack, never at the dev project, whenever `test:db` runs. Its gated
  `bot_config` test writes `paused='true'` then `paused='false'` and **never restores
  it**, so pointed at the dev project it would silently clear the operational kill
  switch and, before `0013` has applied, re-arm `daily-check-1337`/`daily-check-1437`
  on their next slot — plus write `trades`/`audit_log`/`hourly_scans` rows into the
  live paper journal #481's aggregator reads. See #485 for the follow-up that hardens
  this mechanically; until it lands this is a procedural rule only.
- This PR (PR-A) ships **no cron activation**. `0012_hourly_scans.sql`'s
  `hourly-check` cron block is fully commented out (no `cron.job` row of any kind);
  `0013` (this PR) only retires daily-check's entry crons. Activation is `0014`, a
  separate PR-B (§9), merged last, behind eight checked gates (§9).

## §2 Already-done ledger

| Item | Status | Evidence |
|---|---|---|
| Deprecation of the UPRO/200-DMA bot (entries) | Done | #465, merged |
| Design spec + ADR (hourly-candlestick bot) | Done | #466/#471 |
| 14-detector candlestick port (`_shared/candlestick.ts`) | Done | #467/#470 |
| Short-side safety-stack retrofit (kill-switch mirror, side-aware panic, `bar_claims`) | Done, merged, **deployed to dev** | #474/#476; CI run [30390432349](https://github.com/sv-tmueller/trading-bot/actions/runs/30390432349) (`deploy` job, "Apply migrations" step green) applied `0011_bar_claims.sql` to `qdaxxsuicyiscdvsdowc` |
| `hourly-check` Edge Function (signal wiring, bracket orders, paper guard) | Code: Done, merged (#475/#477). Deployment: **Done, via manual route (c)** — `supabase functions deploy hourly-check` on 2026-07-29, present on `qdaxxsuicyiscdvsdowc` as version 1, `ACTIVE`, `verify_jwt: true`, built from local tree at commit `3afdaa9`. **Drift warning (route-(c) freshness hazard, PR #484's amended gate 2):** this snapshot is current only until the next merge touching `hourly-check` or its shared dependencies — **including this very PR** (#489, which changes `_shared/alpaca.ts`'s `assertPaperAccount()`). Re-run the route-(c) deploy after #489 merges; do not treat "present" as "current" without checking the merge time of the most recent touching PR against the deployed version, per the amended gate | #475/#477 for the code; the "Capture evidence — four read-only paper GETs (T1), operator-run 2026-07-29" comment on #479 for the deploy fact; CI run [30396497143](https://github.com/sv-tmueller/trading-bot/actions/runs/30396497143) (`deploy` job, "Apply migrations" step green) applied `0012_hourly_scans.sql` to `qdaxxsuicyiscdvsdowc` — that run's "Deploy functions" step ran `daily-check kill-switch` only, not `hourly-check` (§3) |
| `hourly-check` wired into `deploy-dev.yml`'s JWT-verified deploy step | Still pending — blocked on the workflow OAuth scope (see PR #484's Deviation section). **Consequence while pending:** every merge touching `hourly-check` or its shared dependencies requires a fresh manual route-(c) redeploy (row above) to stay current — CI does not do this automatically until this hunk lands, which is why the route-(c) freshness hazard exists at all | `.github/workflows/deploy-dev.yml`; hunk staged, not applied — see §3 |
| `0013_retire_daily_check_cron.sql` | Done, merged (#479 T6), **and confirmed applied** — `deploy-dev.yml`'s "Apply migrations" step succeeded on the push run for commit `d08a25d` (the PR-A/#484 merge commit), unscheduling `daily-check-1337`/`daily-check-1437` on `qdaxxsuicyiscdvsdowc` | see §6's precondition; the "Capture evidence" comment on #479 (2026-07-29) |
| Capture evidence (T1): four read-only paper API shape captures | Done — 4/4 PASS, 0/4 FAIL | §12 appendix; "Capture evidence — four read-only paper GETs (T1), operator-run 2026-07-29" comment on #479 |
| Layer-B paper-account marker pin (spec §8.3) | **Capture done** (row above); **the pin itself is implemented in PR #489, not yet merged** — on `main` today, `assertPaperAccount()` still ships with its pre-pin unconditional fail-closed throw. Do not treat Layer B as enforced against the real marker until #489 merges | §12 appendix; PR #489 |
| §4 secrets set on `qdaxxsuicyiscdvsdowc` (incl. `HOURLY_SHORTS_ENABLED=false`, `HOURLY_BOT_PAPER_ONLY=true`) | Done | "Capture evidence" comment on #479 (2026-07-29) |
| §5 baseline (`hourly_experiment_start_equity`) | Done — `1017330.61`, after correcting a silent `insert ... on conflict do nothing` no-op that had initially left a stale pre-existing `100000.00` row in place (a wrong baseline parses fine and is invisible, unlike a missing one; follow-up filed) | "Capture evidence" comment on #479 (2026-07-29) |
| Residual-position check (§5 precondition: no leftover UPRO position) | Done — `GET /v2/positions` returned `[]`, consistent with the 2026-07-27 operator liquidation | #465; "Capture evidence" comment on #479 (2026-07-29) |

Both CI runs above are the `push`-event runs immediately following each PR's merge
commit — the `deploy` job's `Apply migrations` step succeeding is exactly T8(a)'s "DDL
applies" evidence for `0011`/`0012`; `0013`'s equivalent evidence is the `d08a25d` run
cited above.

## §3 Deploy order

`0013` ships in this PR and applies automatically to `qdaxxsuicyiscdvsdowc` on merge,
via `deploy-dev.yml`'s existing order. **The `hourly-check` function deploy wiring
does NOT ship in this PR.** The intended one-line hunk to
`.github/workflows/deploy-dev.yml` could not be pushed from the PR-A session (the
repo credential lacks the GitHub `workflow` OAuth scope; see PR #484's Deviation
section) — `deploy-dev.yml` in the merged tree is byte-identical to `origin/main` and
still deploys `daily-check kill-switch` only. Do not assume CI has deployed
`hourly-check` on the strength of this PR merging; confirm it via the explicit gate
in §9 before relying on it.

**Manual step required (operator action, does not happen automatically on merge):**
apply the following hunk to `.github/workflows/deploy-dev.yml` by one of:

- (a) the GitHub web editor, committed directly to `main`, or
- (b) a local push from a credential holding the `workflow` OAuth scope
  (`gh auth refresh -s workflow` — requires an interactive device-flow approval) —
  then let CI redeploy on the next push to `main`; or
- (c) skip the workflow file and deploy the function directly:
  `supabase functions deploy hourly-check --project-ref qdaxxsuicyiscdvsdowc`.

```diff
--- a/.github/workflows/deploy-dev.yml
+++ b/.github/workflows/deploy-dev.yml
@@ -56,7 +56,11 @@ jobs:
       # Order matters (#256 final-review finding): functions BEFORE db push.
       # New function + old cron is fail-closed (clock gate / stale guard);
       # new cron + old function could trade on a partial bar during RTH.
+      # hourly-check (#479 T5) is the same JWT-verified/requireServiceRole
+      # class as daily-check/kill-switch; deploying it here is safe before
+      # its cron exists (0013/no 0014 yet) -- config is read at invocation,
+      # fail-closed, and no cron means the deployed function is inert.
       - name: Deploy functions (JWT-verified)
-        run: supabase functions deploy daily-check kill-switch --project-ref "$PROJECT_REF"
+        run: supabase functions deploy daily-check kill-switch hourly-check --project-ref "$PROJECT_REF"
         env:
           SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}
```

Once applied (by whichever route), the deploy order is:

1. **Functions** (JWT-verified): `daily-check kill-switch hourly-check` — deploying
   `hourly-check` here is safe with no cron yet (config is read at invocation and
   fails closed; no cron trigger means the deployed function is inert until `0014`).
2. `panic` (`--no-verify-jwt`, `x-panic-token` auth).
3. `status` (`--no-verify-jwt`, `x-status-token` auth, read-only).
4. `supabase db push` — applies `0013` (retires daily-check's entry crons; leaves
   `hourly_scans`/`bar_claims`/`trades` schema from `0011`/`0012` untouched, since
   those already applied on the #474/#475 merges).

Confirm the deploy actually landed — do not rely on the assumption that CI redeployed
it — using the §9 gate ("hourly-check deployed and confirmed present in the dev
project's function list") before the operator steps that follow, starting at §4.

## §4 Secrets

Copied **verbatim** from PR #477's body (the hourly-check feature PR) — this is the
canonical list; do not re-derive it:

```bash
supabase secrets set \
  HOURLY_BOT_TICKER=SPY \
  SIZING_RISK_PCT=0.01 \
  SIZING_NOTIONAL_CAP_PCT=0.10 \
  HOURLY_BRACKET_R_MULTIPLE=2 \
  HOURLY_STOP_BUFFER_PCT=0.05 \
  HOURLY_MIN_STOP_DISTANCE=0.05 \
  HOURLY_MAX_ENTRIES_PER_DAY=3 \
  HOURLY_STALENESS_TOLERANCE_MIN=10 \
  HOURLY_CONTEXT_MODE=none \
  HOURLY_SHORTS_ENABLED=false \
  HOURLY_BOT_PAPER_ONLY=true

# Batch 3 deploy-time only (not part of this PR): the -15% equity-floor baseline
# is a bot_config row, not a secret -- set once when the paper experiment begins:
#   insert into bot_config (key, value) values ('hourly_experiment_start_equity', '<equity>');
```

`HOURLY_SHORTS_ENABLED=false` here matches §1's non-negotiable — do not override it
as part of this rollout. This is an operator step (`supabase secrets set` requires
project access this agent/CI does not have); run it against `qdaxxsuicyiscdvsdowc`
before §6's resume step, since `getHourlyConfig()` throws at function invocation if
any of these is out of range (fail-closed, not merely undocumented).

## §5 Baseline

**Before reading equity, confirm and record whether a residual UPRO position exists**
(a leftover from the retired daily-check bot) — check `GET /v2/positions` for a
`UPRO` entry, or the `status` digest's `alpaca.position` field. After `0013` applies,
the retired daily-check bot has no scheduled exit path for that position (this is
intentional — kill-switch drawdown is the retained coverage, §6), so a residual
position matters here twice over: it consumes buying power the hourly bot's sizing
reads through account equity, and it folds directly into the baseline below — a UPRO
drawdown alone could then trip the hourly bot's −15% auto-pause floor with no hourly
trade involved. Record the answer (position present/absent, and its size if present)
alongside this rollout's notes before proceeding.

Read current paper equity (`GET /v2/account`'s `equity` field, or the `status` digest's
`alpaca.account_value`) **before** running this, then set the −15% floor's baseline
once. `bot_config.value` is `NOT NULL`, so there is no "unset" representation once
inserted — re-running this must not silently move the baseline (see the `on conflict
do nothing` below).

```sql
insert into bot_config (key, value)
values ('hourly_experiment_start_equity', '<PASTE THE /v2/account EQUITY HERE>')
on conflict (key) do nothing;  -- refuses to overwrite an existing baseline
```

Verify: `select value from bot_config where key = 'hourly_experiment_start_equity';`
returns the value just set (or the original one, if this was accidentally re-run).
A missing baseline is a **hard error** at scan time (`hourly-check/logic.ts:613-617`,
`error:DataError`) — this step is not optional before the first scan that could trade.

## §6 Resume — 0013-first precondition (red letter)

> **STOP. Do not run `?action=resume` until `0013_retire_daily_check_cron.sql` has
> been applied to `qdaxxsuicyiscdvsdowc` and you have confirmed it below.** Resuming
> first re-arms daily-check's entry crons (`daily-check-1337`/`daily-check-1437`) on
> their next UTC slot — the exact "two bots, one account" case #465's deprecation ADR
> rejects, and the reason this migration exists (see its own header).

Confirm the precondition:

```sql
select jobname, schedule from cron.job where jobname like 'daily-check%';
-- Expected: ZERO rows (0013 unscheduled both daily-check-1337 and
-- daily-check-1437; the legacy single 'daily-check' job name too, if present).
```

Only once that returns zero rows:

```bash
curl -i -X POST "https://qdaxxsuicyiscdvsdowc.supabase.co/functions/v1/panic?action=resume" \
  -H "x-panic-token: $PANIC_TOKEN"
# Expect HTTP 200 {"result":"resumed"}; bot_config.paused -> 'false'.
```

`kill-switch`'s cron is unaffected by either the resume or `0013` — it keeps running
every 5 minutes, 13-21 UTC, Mon-Fri, protecting any position either bot holds,
including a residual daily-check position if §5 found one (its only exit path from
this point on).

## §7 Layer-B live smoke (T9)

**Dependency, stated plainly:** this smoke test is only meaningful **after** the
Layer-B pin has merged **and** the deployed `hourly-check` function has been rebuilt
from that merge. The T1 capture (§12 appendix) is done, but the pin itself — the code
change to `assertPaperAccount()` — is PR #489, **not yet merged as of this writing**;
PR-A (#484) shipped only the pre-pin unconditional fail-closed throw, which is what
both `main` and the currently-deployed function (route (c), built from `3afdaa9`, §2)
still carry. Running the smoke test now will legitimately return
`error:PaperGuardFailed` instead of the outcome below. That is expected, not a bug
report; it means "come back after #489 merges and `hourly-check` is redeployed," not
"something is broken."

**Run outside RTH only.** The server-side function has no `CLAUDE_AGENT_NO_BROKER`
(that guard only protects in-process/agent-spawned calls) — during RTH this curl is a
**full live scan** that could place a real (paper) order if every gate passes.

```bash
# Requires the Vault-stored service_role_key (Dashboard -> Settings -> API; a
# legacy JWT starting "eyJ", the same key pg_cron sends).
curl -i -X POST "https://qdaxxsuicyiscdvsdowc.supabase.co/functions/v1/hourly-check" \
  -H "Authorization: Bearer $SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json"
```

Expected (outside RTH, Layer-B pin merged): HTTP 200, audit outcome
`skipped:market_closed` — reachable only because Layer B (paper-account marker) and
Layer A (paper URL/config) both passed on the real account first.

```sql
select outcome, notes, finished_at
from audit_log
where script_name = 'hourly-check'
order by started_at desc
limit 1;
```

## §8 Bar-alignment (T10, spec §4 — THE activation gate)

Read-only, no order surface. Run during a live RTH session, at approximately `HH:08`
(minutes past the hour), so at least one bar is old enough to inspect its boundaries:

```bash
curl -sS "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Hour&feed=iex&limit=6" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" \
  -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY" | jq '.bars[] | {t, o, h, l, c}'
```

Four checks against the shipped `isBarPartial()` (`supabase/functions/hourly-check/logic.ts:198-209`):

1. **Interior bars are top-of-hour UTC.** Every bar's `t` except the session-open/close
   edges lands exactly on `:00:00Z`.
2. **The session-open stub is excluded.** The first RTH bar (9:30-10:30 ET) is
   shorter than a full hour and must be classified partial (excluded from the signal).
3. **Interior bars in `14:00-19:00Z` are NOT excluded.** These are full EDT-session
   hours; `isBarPartial` must return `false` for them.
4. **The newest bar is present within 8 minutes of now.** Record the observed feed
   latency: `cronMinuteOffset (7) + observedLatencyMin < HOURLY_STALENESS_TOLERANCE_MIN
   (10)` must hold — write down the actual `now - newest_bar.t` you observe. **If this
   inequality fails, the fix is a different cron minute in `0014` — never raising
   `HOURLY_STALENESS_TOLERANCE_MIN` to paper over it.**

Record this as its own evidence comment on #479 (per T10); PR-B (`0014`) links it and
re-verifies the minute pin against the observed latency before choosing the cron
schedule.

## §9 Activation (PR-B, `0014` — NOT built in this PR)

`0014_hourly_check_cron_activation.sql` uncomments the `hourly-check` schedule that
`0012` left commented out (candidate minute `:07`, i.e. `7 13-21 * * 1-5`, per the
spec's inequality in §8 above — re-verify against §8's observed latency before
merging). PR-B is **out of scope for this PR** and must not be created here; this
runbook documents its gate list so the checklist lives in one place:

**Merge gates — ALL must be checked off on #479 before PR-B merges:**

1. PR-A (#484) merged, CI green.
2. **`hourly-check` deployed and confirmed present in the dev project's function
   list** (`supabase functions list --project-ref qdaxxsuicyiscdvsdowc`, or the
   Dashboard's Edge Functions page). This gate stays **permanently** — even once the
   §3 hunk lands on `main` and CI starts deploying `hourly-check` automatically,
   "CI should have deployed it" is an assumption; this gate is the check that
   confirms it.
3. #480 (post-fill journaling failure window: bounded retry + reconciliation
   recovery) merged and deployed.
4. Layer-B pin merged from a real capture (§12 appendix) — PR #489, not PR-A (#484)'s
   pre-pin fail-closed placeholder.
5. T9 evidence (§7) posted on #479, outcome `skipped:market_closed`.
6. T10 evidence (§8) posted on #479, inequality holds with the observed latency.
7. §4's secrets set on `qdaxxsuicyiscdvsdowc`.
8. §5's baseline row present (residual-position check recorded); `bot_config.paused
   = 'false'` confirmed (§6).

Merge outside RTH recommended. After merge, verify: `select jobname, schedule, active
from cron.job where jobname = 'hourly-check';` returns exactly one active row.

## §10 First-scan verification checklist (T12)

Run once `0014` is live and the first scan has fired:

- [ ] First-of-session scan resolves `skipped:partial_bar`, **not**
  `skipped:stale_data` — live proof of the §4 guard-precedence ordering
  (`hourly-check/logic.ts`'s gate ladder).
- [ ] A `hourly_scans` row exists for the scanned bar (including SKIP rows — §9's
  "one row per scan, including skips" contract).
- [ ] `select jobname, active from cron.job where jobname = 'hourly-check';` shows
  `active = true`.
- [ ] No `error:*` outcomes in `audit_log` for `script_name = 'hourly-check'`.
- [ ] `select * from net._http_response order by created desc limit 20;` is clean
  (no cron -> function HTTP failures — a wrong project ref makes cron fire silent
  no-ops, the same failure mode documented in the daily-check runbook).
- [ ] Watch one full RTH session end-to-end. File any anomaly as a **new issue**
  (systematic-debugging triage) — do not hot-fix inside this rollout.

## §11 Rollback

Any point in this rollout can be unwound without code changes:

- **Pause new entries (fast, reversible, no broker call):**
  `curl -i -X POST ".../panic?action=pause" -H "x-panic-token: $PANIC_TOKEN"` →
  `bot_config.paused = 'true'`; `hourly-check` exits `skipped:trading_paused` before
  contacting Alpaca on its next scan.
- **Flatten the current position (broker call, RTH only):**
  `curl -i -X POST ".../panic?action=liquidate" -H "x-panic-token: $PANIC_TOKEN"` —
  side-aware and symbol-aware (#474/#476), so this correctly covers a short or closes
  a long in SPY; also sets `paused=true`.
- **Stop the cron entirely (post-`0014` only):**
  `select cron.unschedule('hourly-check');` in the SQL editor, or a follow-up guarded
  migration mirroring `0013`'s pattern. Function code and deployed Edge Function are
  untouched either way — this is schedule-only, same as `0013`.
- **Before `0014` exists** (current state — PR-B is not yet created), there is nothing
  to unschedule — the cron block ships fully commented out, so "rollback" is simply
  not merging PR-B.

## §12 Appendix — captures, citations, and what each pins

**Capture status: returned.** See the "Capture evidence — four read-only paper GETs
(T1), operator-run 2026-07-29" comment on #479 — `scripts/capture_alpaca_shapes.sh`
run against `paper-api.alpaca.markets` (hardcoded, non-overridable), **4/4 PASS, 0/4
FAIL**. Sanitized output (account `id` dropped, `account_number` masked to its 2-char
prefix):

```json
// GET /v2/clock
{ "timestamp": "2026-07-29T05:27:57.818080188-04:00", "is_open": false,
  "next_open": "2026-07-29T09:30:00-04:00", "next_close": "2026-07-29T16:00:00-04:00" }
// GET /v2/account
{ "account_number": "PA****", "status": "ACTIVE", "equity": "1017330.61", "currency": "USD" }
// GET /v2/calendar?start=2026-07-29&end=2026-08-05
[ { "close": "16:00", "date": "2026-07-29", "open": "09:30",
    "session_close": "2000", "session_open": "0400", "settlement_date": "2026-07-30" }, ... ]
// GET /v2/assets/SPY
{ "symbol": "SPY", "tradable": true, "shortable": true, "easy_to_borrow": true, "fractionable": true }
```

| # | `[to verify]` item | Code it pins | Confirmed? |
|---|---|---|---|
| 1 | `/v2/clock` `next_close` field | `supabase/functions/_shared/alpaca.ts`'s `getClock()` (`nextClose`, used by the session-close flatten mechanic) | **Yes** — `next_close` present, RFC3339-with-offset, parses via `requireNumber`/`Date.parse` as coded; no change needed |
| 2 | `/v2/account` paper-account marker | `supabase/functions/_shared/alpaca.ts`'s `assertPaperAccount()` (Layer B, spec §8.3) | **Yes — pinned.** The marker is a string `account_number` starting with `"PA"`; `assertPaperAccount()`'s unconditional throw was replaced with this check (#479 T3, `alpaca.ts`/`alpaca.test.ts` only). Fail-closed retained: missing, non-string, or non-`"PA"`-prefixed `account_number` still throws `PaperGuardFailedError` with the raw number masked to its prefix |
| 3 | `/v2/calendar` `open`/`close` HH:MM fields | `supabase/functions/_shared/marketdata.ts`'s `getCalendarSessions()` | **Yes** — response carries both `open`/`close` (`"HH:MM"`, as read) and a differently-formatted `session_open`/`session_close` (`"HHMM"`, no colon, for extended hours); `getCalendarSessions` reads only `e.open`/`e.close` and `etHHMMToUtcMs` splits on `":"`, so the no-colon extended-hours fields are never touched. No code change needed |
| 4 | `/v2/assets/SPY` `shortable`/`easy_to_borrow` fields | `supabase/functions/_shared/alpaca.ts`'s `getAssetShortability()` | **Yes** — field names confirmed; SPY itself is shortable (`shortable: true`, `easy_to_borrow: true`), so the §1 fallback (shorts disabled) was never needed on capability grounds. `HOURLY_SHORTS_ENABLED=false` (§1/§4) remains the standing rollout constraint regardless |
| 5 | Bracket-on-short support | `hourly-check/logic.ts`'s SHORT-entry path (OCO fallback) | **Resolved by docs citation, not a live capture** — see #479's T4 comment: current published Alpaca docs (`docs.alpaca.markets/docs/orders-at-alpaca`, `docs.alpaca.markets/reference/postorder`) document no restriction against `order_class: "bracket"` + `side: "sell"`, but the decision (sub-plan-ratified) is to keep the OCO fallback regardless this package; switching to a single bracket call for shorts is a follow-up, size:S, only after a live paper capture independently corroborates the docs reading |
| 6 | Bracket entry `time_in_force` | `placeBracketOrder`/`placeMarketOrder` (both default `"day"`) | **Resolved by docs citation** — same #479 T4 comment: Alpaca's docs state bracket/OCO `time_in_force` "must be `day` or `gtc`"; `"day"` (already used everywhere in this repo) is valid, no code change needed |

**Bar alignment (§8/T10)** is tracked separately as its own evidence comment on #479
(live RTH capture required, not a structural docs citation) and is not repeated here.
