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
  `/v2/assets/SPY` shortability fields are not yet confirmed against a live response
  (§12 appendix); shorts stay disabled until that capture lands and a follow-up change
  flips the flag deliberately. Do not set this to `true` as part of this runbook.
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
| `hourly-check` Edge Function (signal wiring, bracket orders, paper guard) | Done, merged, **deployed to dev** | #475/#477; CI run [30396497143](https://github.com/sv-tmueller/trading-bot/actions/runs/30396497143) (`deploy` job, "Apply migrations" step green) applied `0012_hourly_scans.sql` to `qdaxxsuicyiscdvsdowc` |
| `hourly-check` wired into `deploy-dev.yml`'s JWT-verified deploy step | Pending — blocked on the workflow OAuth scope (see PR #484's Deviation section) | `.github/workflows/deploy-dev.yml`; hunk staged, not applied — see §3 |
| `0013_retire_daily_check_cron.sql` | Done (this PR, #479 T6) | see §6's precondition |
| Layer-B paper-guard marker pin | **Pending operator capture** | §12 appendix; `assertPaperAccount()` ships with its fail-closed throw intact |

Both CI runs above are the `push`-event runs immediately following each PR's merge
commit — the `deploy` job's `Apply migrations` step succeeding is exactly T8(a)'s "DDL
applies" evidence for `0011`/`0012`; `0013` gets the equivalent evidence recorded on
#479 once this PR merges (the next `push`-to-`main` run's `Apply migrations` step).

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
intentional — kill-switch drawdown is the retained coverage, §11), so a residual
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
A missing baseline is a **hard error** at scan time (`hourly-check/logic.ts:428`,
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
Layer-B pin (§12 appendix) has been merged from real capture evidence. This PR (PR-A)
ships `assertPaperAccount()` with its fail-closed throw **intact** (§12) — running the
smoke test before the pin lands will legitimately return `error:PaperGuardFailed`
instead of the outcome below. That is expected, not a bug report; it means "come back
after the Layer-B pin PR merges," not "something is broken."

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

Four checks against the shipped `isBarPartial()` (`supabase/functions/hourly-check/logic.ts:153-164`):

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

1. PR-A (this PR) merged, CI green.
2. **`hourly-check` deployed and confirmed present in the dev project's function
   list** (`supabase functions list --project-ref qdaxxsuicyiscdvsdowc`, or the
   Dashboard's Edge Functions page). This gate stays **permanently** — even once the
   §3 hunk lands on `main` and CI starts deploying `hourly-check` automatically,
   "CI should have deployed it" is an assumption; this gate is the check that
   confirms it.
3. #480 (post-fill journaling failure window: bounded retry + reconciliation
   recovery) merged and deployed.
4. Layer-B pin merged from a real capture (§12 appendix) — not the fail-closed
   placeholder this PR ships.
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
- **Before `0014` exists** (this PR's state), there is nothing to unschedule — the
  cron block ships fully commented out, so "rollback" is simply not merging PR-B.

## §12 Appendix — captures, citations, and what each pins

**Capture status: pending operator.** No `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` was
present in this agent session (`env | grep ALPACA` empty) — see the "Capture evidence:
paper API shapes (T1)" handoff comment on #479 and `scripts/capture_alpaca_shapes.sh`
(this PR). Once evidence returns, this appendix should be updated with the sanitized
capture output and this table's "Confirmed?" column flipped.

| # | `[to verify]` item | Code it pins | Confirmed? |
|---|---|---|---|
| 1 | `/v2/clock` `next_close` field | `supabase/functions/_shared/alpaca.ts`'s `getClock()` (`nextClose`, used by the session-close flatten mechanic) | No — parses via `requireNumber`/`Date.parse`; missing/unparseable is already a hard error regardless |
| 2 | `/v2/account` paper-account marker | `supabase/functions/_shared/alpaca.ts`'s `assertPaperAccount()` (Layer B, spec §8.3) | **No — ships with the fail-closed throw intact** (see the ignored positive test in `alpaca.test.ts`, gated on this capture) |
| 3 | `/v2/calendar` `open`/`close` HH:MM fields | `supabase/functions/_shared/marketdata.ts`'s `getCalendarSessions()` | No — missing/unparseable `open`/`close` is already a hard error (`DataError`) regardless |
| 4 | `/v2/assets/SPY` `shortable`/`easy_to_borrow` fields | `supabase/functions/_shared/alpaca.ts`'s `getAssetShortability()` | No — `HOURLY_SHORTS_ENABLED=false` (§4) is the fail-closed override until confirmed |
| 5 | Bracket-on-short support | `hourly-check/logic.ts`'s SHORT-entry path (OCO fallback) | **Resolved by docs citation, not a live capture** — see #479's T4 comment: current published Alpaca docs (`docs.alpaca.markets/docs/orders-at-alpaca`, `docs.alpaca.markets/reference/postorder`) document no restriction against `order_class: "bracket"` + `side: "sell"`, but the decision (sub-plan-ratified) is to keep the OCO fallback regardless this package; switching to a single bracket call for shorts is a follow-up, size:S, only after a live paper capture independently corroborates the docs reading |
| 6 | Bracket entry `time_in_force` | `placeBracketOrder`/`placeMarketOrder` (both default `"day"`) | **Resolved by docs citation** — same #479 T4 comment: Alpaca's docs state bracket/OCO `time_in_force` "must be `day` or `gtc`"; `"day"` (already used everywhere in this repo) is valid, no code change needed |

**Bar alignment (§8/T10)** is tracked separately as its own evidence comment on #479
(live RTH capture required, not a structural docs citation) and is not repeated here.
