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
  bot's entry crons on the same paper account. **For this rollout, §6's resume has
  already happened** (`paused = 'false'` since 2026-07-29, confirmed in the "T9
  evidence" comment on #479 — see §2) — the rule above stays in this banner because it
  is the standing precondition for any future re-pause/resume cycle, not because the
  flag is still `true` today.
- **`deno task test:db` runs against a local `supabase start` stack only, and this is now
  enforced in code (#485), not just here.** `supabase/functions/_shared/db.test.ts`
  builds its client through `createLocalDbClient()`
  (`supabase/functions/_shared/db_test_guard.ts`), which refuses any `SUPABASE_URL`
  whose host is not a local-machine host (`localhost`, `127.0.0.0/8`, `::1`,
  `host.docker.internal`, any port) and throws before a client exists, naming the
  offending host; the task's `--allow-net` grant is scoped to the same hosts, so a
  code-level regression alone still cannot reach a remote project. A shell exported
  for the dev project (`qdaxxsuicyiscdvsdowc`) now fails the gated suite instead of
  writing to it. The gated `bot_config` test also restores the `paused` value it
  found, including when an assertion fails. Note that the other gated tests clean up
  only on success, so a failing one leaves its rows on the local stack. Historical
  note on why this exists: before the guard, that test wrote `paused='true'` then
  `paused='false'` and never restored it, so pointed at the dev project it would
  silently clear the operational kill switch and, before `0013` had applied, re-arm
  `daily-check-1337`/`daily-check-1437` on their next slot, plus write
  `trades`/`audit_log`/`hourly_scans` rows into the live paper journal #481's
  aggregator reads.
- PR-A (#484) shipped **no cron activation**. `0012_hourly_scans.sql`'s
  `hourly-check` cron block is fully commented out (no `cron.job` row of any kind);
  `0013` (also PR-A, #484) only retires daily-check's entry crons. Activation is
  `0014`, a separate PR-B, merged behind eight checked gates — all eight now closed
  (§9) — and merging it is what makes the schedule live; see §9's header for what
  "merging this" means operationally.

## §2 Already-done ledger

| Item | Status | Evidence |
|---|---|---|
| Deprecation of the UPRO/200-DMA bot (entries) | Done | #465, merged |
| Design spec + ADR (hourly-candlestick bot) | Done | #466/#471 |
| 14-detector candlestick port (`_shared/candlestick.ts`) | Done | #467/#470 |
| Short-side safety-stack retrofit (kill-switch mirror, side-aware panic, `bar_claims`) | Done, merged, **deployed to dev** | #474/#476; CI run [30390432349](https://github.com/sv-tmueller/trading-bot/actions/runs/30390432349) (`deploy` job, "Apply migrations" step green) applied `0011_bar_claims.sql` to `qdaxxsuicyiscdvsdowc` |
| `hourly-check` Edge Function (signal wiring, bracket orders, paper guard) | Code: Done, merged (#475/#477, plus #480/#483's post-fill recovery fix and #489's Layer-B pin). Deployment: **Done, via manual route (c), and re-confirmed current** — first deployed 2026-07-29 as version 1 (`3afdaa9`); the T9 evidence gate then caught that version 2 (`2026-07-29T08:48:32Z`) still predated #489's merge (`2026-07-29T10:56:02Z`), so it was redeployed again from `main` at `6cf3daf` — **version 3, `deployed_at 2026-07-29T11:21:51Z`, now current against every merge up to and including #489**. **Drift warning (route-(c) freshness hazard, PR #484's amended gate 2) stays permanent, not resolved by this row:** any PR merging after `2026-07-29T11:21:51Z` that touches `hourly-check` or its shared dependencies makes this row stale again until the next redeploy — check the merge time of the most recent touching PR against the deployed version before relying on "present" as "current," every time, not just once | #475/#477 for the code; the "Capture evidence" and "T9 evidence: Layer-B live smoke" comments on #479 for the deploy history; CI run [30396497143](https://github.com/sv-tmueller/trading-bot/actions/runs/30396497143) (`deploy` job, "Apply migrations" step green) applied `0012_hourly_scans.sql` to `qdaxxsuicyiscdvsdowc` — that run's "Deploy functions" step ran `daily-check kill-switch` only, not `hourly-check` (§3) |
| `hourly-check` wired into `deploy-dev.yml`'s JWT-verified deploy step | Still pending — blocked on the workflow OAuth scope (see PR #484's Deviation section). **Consequence while pending:** every merge touching `hourly-check` or its shared dependencies requires a fresh manual route-(c) redeploy (row above) to stay current — CI does not do this automatically until this hunk lands, which is why the route-(c) freshness hazard exists at all | `.github/workflows/deploy-dev.yml`; hunk staged, not applied — see §3 |
| `0013_retire_daily_check_cron.sql` | Done, merged (#479 T6), **and confirmed applied** — `deploy-dev.yml`'s "Apply migrations" step succeeded on the push run for commit `d08a25d` (the PR-A/#484 merge commit), unscheduling `daily-check-1337`/`daily-check-1437` on `qdaxxsuicyiscdvsdowc` | see §6's precondition; the "Capture evidence" comment on #479 (2026-07-29) |
| Capture evidence (T1): four read-only paper API shape captures | Done — 4/4 PASS, 0/4 FAIL | §12 appendix; "Capture evidence — four read-only paper GETs (T1), operator-run 2026-07-29" comment on #479 |
| Layer-B paper-account marker pin (spec §8.3) | **Capture done** (row above). **Enforced against the real marker from PR #489's merge commit onward** — every `alpaca.ts` before that commit (including PR-A's, #484) carries the pre-pin unconditional fail-closed throw; every commit from #489's merge forward carries the confirmed-`"PA"`-prefix check. To find out which one a given deployed build has, check that build's commit against #489's merge commit — the same check as the route-(c) drift-warning row above — rather than assuming from this row's age | §12 appendix; PR #489 |
| §4 secrets set on `qdaxxsuicyiscdvsdowc` (incl. `HOURLY_SHORTS_ENABLED=false`, `HOURLY_BOT_PAPER_ONLY=true`) | Done | "Capture evidence" comment on #479 (2026-07-29) |
| §5 baseline (`hourly_experiment_start_equity`) | Done — `1017330.61`, after correcting a silent `insert ... on conflict do nothing` no-op that had initially left a stale pre-existing `100000.00` row in place (a wrong baseline parses fine and is invisible, unlike a missing one; follow-up filed) | "Capture evidence" comment on #479 (2026-07-29) |
| Residual-position check (§5 precondition: no leftover UPRO position) | Done — `GET /v2/positions` returned `[]`, consistent with the 2026-07-27 operator liquidation | #465; "Capture evidence" comment on #479 (2026-07-29) |
| §6 resume (`bot_config.paused` -> `'false'`) | Done, 2026-07-29, after `0013` was confirmed applied per its ledger row above (the red-letter precondition) | "T9 evidence: Layer-B live smoke" comment on #479, "supporting state" block |
| T9 (§7 Layer-B live smoke) | Done — outcome `skipped:market_closed`, proving Layer A + Layer B both passed on the real paper account before the clock gate | "T9 evidence: Layer-B live smoke" comment on #479; §9 gate 5 |
| T10 (§8 bar alignment, spec §4's activation gate) | Done — all four checks PASS; observed feed latency <= 1 min, so `7 + 1 = 8 < 10` holds with two minutes of headroom; pinned minute `:07` needed no change | "T10 evidence: bar alignment" comment on #479; §9 gate 6 |
| T8(b) (gated `RUN_DB_TESTS` roundtrips against a real, local Postgres) | Done — all 13 migrations (0001-0013) apply cleanly; 41/43 roundtrip tests pass (no grant was needed on CLI 2.110.0 — the original claim that a `grant all ... to service_role` step was required on a bare local stack did not reproduce on a second run and has been retracted, #479/#491); the 2 failures are characterized `bar_ts` string-format test-assertion defects with no production-path impact (follow-up filed) — not a §9 gate, but a prerequisite this rollout satisfied before `0014` | "T8(b) evidence" comment on #479 |
| §9 merge gates (all eight) | **All closed** as of the T10 evidence comment (2026-07-29) | §9; "T9 evidence" and "T10 evidence" comments on #479 |

Both CI runs above are the `push`-event runs immediately following each PR's merge
commit — the `deploy` job's `Apply migrations` step succeeding is exactly T8(a)'s "DDL
applies" evidence for `0011`/`0012`; `0013`'s equivalent evidence is the `d08a25d` run
cited above.

## §3 Deploy order

`0013` shipped in PR-A (#484) and applied automatically to `qdaxxsuicyiscdvsdowc` on
merge, via `deploy-dev.yml`'s existing order — confirmed by the `d08a25d` push run's
"Apply migrations" step (§2, the `0013_retire_daily_check_cron.sql` row). **The
`hourly-check` function deploy wiring did NOT ship in PR-A.** The intended one-line
hunk to `.github/workflows/deploy-dev.yml` could not be pushed from the PR-A session
(the repo credential lacks the GitHub `workflow` OAuth scope; see PR #484's Deviation
section) — `deploy-dev.yml` on `origin/main` today is still byte-identical to that
merged tree and still deploys `daily-check kill-switch` only. Do not assume CI has
deployed `hourly-check` on the strength of any single PR (PR-A or #489) merging;
confirm it via the explicit gate in §9 before relying on it.

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
4. `supabase db push` — applies any pending migrations (`0013` here, retiring
   daily-check's entry crons; `0014` from PR-B's merge onward, arming the
   `hourly-check` cron — see §9). `hourly_scans`/`bar_claims`/`trades` schema from
   `0011`/`0012` is untouched by either, since those already applied on the
   #474/#475 merges.

Confirm the deploy actually landed — do not rely on the assumption that CI redeployed
it — using the §9 gate ("hourly-check deployed and confirmed present **and current**
in the dev project's function list") before the operator steps that follow, starting
at §4. The "and current" half of that gate is not decorative — it is exactly what
caught the stale version-2 deploy documented in §2/§9.

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
# is a bot_config row, not a secret -- set once when the paper experiment begins.
# Follow §5, not a bare insert: verifying the stored value against the equity you
# just read is part of the step, because `on conflict do nothing` can discard it.
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
on conflict (key) do nothing   -- refuses to overwrite an existing baseline
returning value;               -- makes the refusal visible, see below
```

**`on conflict do nothing` is retained deliberately — it is what protects a real
baseline from being moved mid-experiment — but on its own it is silent about having
done so, and that silence is exactly what produced the wrong `100000.00` baseline
during this rollout's own ops window (§2):** the `insert` appeared to succeed with no
error, but a pre-existing row meant the value pasted above was discarded. `returning
value` removes the ambiguity. **Read the row count, not just the output:**

| Result | Meaning |
|---|---|
| **1 row**, showing the value you pasted | The baseline was set by this statement. Proceed to the verification below. |
| **0 rows** (`INSERT 0 0`) | **NO-OP.** A baseline already existed and your value was discarded. The stored baseline is *not* the one you just pasted. |

Either way, do not trust the insert alone. **Verify the stored value against the
equity you just read** — this query compares the two rather than echoing the stored
value back at you, so a stale baseline cannot look like a success:

```sql
-- Paste the SAME /v2/account equity into both placeholders.
select
  value                                                       as stored_baseline,
  <PASTE THE /v2/account EQUITY HERE>                         as equity_just_read,
  round(
    abs(value::numeric - <PASTE THE /v2/account EQUITY HERE>)
      / <PASTE THE /v2/account EQUITY HERE> * 100, 2)         as deviation_pct,
  case
    when abs(value::numeric - <PASTE THE /v2/account EQUITY HERE>)
           <= 0.20 * <PASTE THE /v2/account EQUITY HERE>
    then 'OK'
    else 'STOP -- stored baseline does not match the equity just read'
  end                                                         as verdict
from bot_config
where key = 'hourly_experiment_start_equity';
```

Verify: exactly one row, `verdict = 'OK'`, and `deviation_pct` at or near `0.00` (it
is only nonzero if equity moved between the `/v2/account` read and this query).

If the verdict is `STOP`, or the deviation is anything more than a rounding
difference, **stop** — the baseline is stale from a previous run, not the one you
intended to set. Correct it with an explicit `update`, never another `insert ... on
conflict do nothing`:

```sql
update bot_config
set value = '<PASTE THE /v2/account EQUITY HERE>'
where key = 'hourly_experiment_start_equity';
-- then re-run the verification query above.
```

The 20% threshold matches `BASELINE_TOLERANCE_PCT` in `hourly-check/logic.ts`; keep the
two in step if either changes. The `abs()` here is deliberately **symmetric**, where the
scan-time check only looks below equity — this query is the only thing that catches a
baseline set too high, for the reason given below.

All three failure modes are now caught at scan time as well (#488), so this step is
belt-and-braces rather than the only line of defence:

- A **missing** baseline is a hard error (`error:DataError`).
- An **unparseable** baseline is a hard error. `bot_config.value` is text, so a paste that
  carries a thousands separator or a currency symbol (`1,017,330.61`, `$1017330.61`)
  stores cleanly and only fails when the scan tries to read it as a number.
- A **wrong** baseline — more than 20% *below* account equity — is also a hard error,
  checked once against live equity before the first scan that could trade, then recorded
  in `bot_config.hourly_experiment_baseline_verified` so it never fires again on the
  legitimate divergence the baseline exists to measure. Changing the baseline later
  re-arms the check for the new value.

All three raise a Discord alert as well as writing the `audit_log` row, so none depends on
someone reading the table. Paste a bare number above — no separators, no currency symbol —
and the verification query's `value::numeric` cast will itself fail loudly if you did not.

**Why only the *below* direction, and what that leaves to you.** A baseline below equity
is the dangerous one: it drops the floor away from the account, which is how the
2026-07-29 value would have allowed a 91.6% loss. A baseline *above* equity moves the
floor closer, which is conservative, and the floor itself already fires on it — so the
scan-time check deliberately stays out of that direction. Pre-empting the floor there
would swap a persistent `bot_config.paused` for a per-scan error (the `status` digest
would report `paused=false` while the bot sat erroring), and on a first scan a genuine
drawdown is indistinguishable from a wrong-high baseline, so the error would have
advised moving the baseline *down* onto the drawn-down equity — erasing the breach.

Two residuals follow, and this step is where they are caught:

1. **A baseline set above current equity by less than 15% is never validated at scan
   time.** The floor does not fire, and the plausibility check does not run while equity
   sits below the baseline, so the check stays armed (and dormant) until equity rises
   past it. The verification query above is the only thing that catches this case.
2. **The marker is keyed to the baseline value, not to the account.** Pointing the bot at
   a different paper account whose baseline happens to be byte-identical would skip the
   check. Account identity is not stored in `bot_config` today.

Neither failure is auto-corrected. If a flagged baseline really is intentional,
acknowledge it explicitly by setting the marker yourself — do not weaken the check:

```sql
insert into bot_config (key, value)
values ('hourly_experiment_baseline_verified', '<THE EXACT stored_baseline STRING>')
on conflict (key) do update set value = excluded.value;
```

This step is not optional before the first scan that could trade.

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
this point on). **This is a real but distant backstop for the hourly bot, not its
primary protection** — `KILL_SWITCH_DRAWDOWN_PCT` defaults to 25% off a 30-day rolling
high, near-inert for a same-day SPY move; the hourly bot's real protection is its own
per-trade bracket stop and the session-close flatten scan (§9's "merging this PR
activates the bot" and §11's rollback both assume this ordering).

## §7 Layer-B live smoke (T9)

**Status for this rollout: done.** Run 2026-07-29 outside RTH, outcome
`skipped:market_closed` — see the "T9 evidence: Layer-B live smoke" comment on #479
and §2/§9's gate 5. The procedure below stays in the runbook for any future
re-arming (e.g. after a rollback and re-resume) — it is not a step still waiting to
happen for the current rollout.

**Dependency, stated plainly:** this smoke test is only meaningful once the
**deployed** `hourly-check` build postdates the Layer-B pin's merge (PR #489). The T1
capture (§12 appendix) is done, but Layer B is enforced against the real marker only
from #489's merge commit forward — every build before it (including PR-A's, #484)
carries the pre-pin unconditional fail-closed throw. **Check the deployed function's
build against #489's merge commit before running this** (the same check as §2's
route-(c) drift-warning row) — don't assume either way from the date you're reading
this runbook.

- If the deployed build **predates** #489's merge: `error:PaperGuardFailed` is
  expected here, not a bug report. It means "redeploy `hourly-check` from a build
  that includes #489, then re-run this smoke test," not "something is broken."
- If the deployed build **postdates** #489's merge and this still returns
  `error:PaperGuardFailed`: that is a genuine Layer-B failure and an **incident** —
  report it with the response body and the `audit_log` row, do not dismiss it as
  the pre-merge case above.

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

**Status for this rollout: done.** Run 2026-07-29 during live RTH — all four checks
PASS, observed feed latency <= 1 minute, `7 + 1 = 8 < 10` holds with two minutes of
headroom. See the "T10 evidence: bar alignment" comment on #479 and §2/§9's gate 6;
`0014` ships the pinned minute `:07` unchanged as a result. The procedure below is
retained for reference (e.g. if a future minute change per §4's own rule ever needs
re-verification) — it is not outstanding for this rollout.

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

## §9 Activation (PR-B, `0014`)

`0014_hourly_check_cron_activation.sql` uncomments the `hourly-check` schedule that
`0012` left commented out, at minute `:07` (`7 13-21 * * 1-5`) — re-verified against
§8's live-measured latency (T10), not merely the spec's candidate value. This
runbook's own diff, alongside `0014`, **is** PR-B; it is no longer out of scope for
any PR — the checklist below lives in one place either way.

**Merging this PR activates the bot.** `deploy-dev.yml`'s `deploy` job runs `supabase
db push` on every push to `main`, which applies `0014` and creates a live `cron.job`
row named `hourly-check`, schedule `7 13-21 * * 1-5`. **The first live scan is the
next `:07` of any hour in that 13-21 UTC window, Mon-Fri — within the hour if merged
during that window, not "the next day's 13:07."** A weekday merge at, say, 15:30 UTC
produces a live scan 37 minutes later at 16:07Z. At that moment the newest **completed**
bar (`completed` keeps bars where `bar.timestamp + 1h <= now`, `logic.ts:629`) is the
`15:00Z` bar — its `[15:00Z, 16:00Z)` span has fully elapsed, while the `16:00Z` bar has
not — so the candidate is `15:00Z`, not `14:00Z`, and `staleMinutes = (now - barEnd) /
60000` (`logic.ts:684`) = `(16:07 - 16:00) = 7 < 10` — a scan that can place an order.
**For that reason, merge outside RTH (before 13:00 UTC or after 21:08 UTC on a weekday,
or on a weekend) is not merely a recommendation here — it is the stated procedure**, so
the first scan against this migration is a deliberately-observed one (§10), not
whatever happens to be firing when CI finishes the push. The window's upper bound is
`21:08` rather than `21:00` because the schedule's last firing of any weekday is
`21:07`; merging after `21:08` therefore leaves no firing behind it until the next
weekday's `13:07`. The bot scans SPY hourly on the Alpaca
**paper** account and can place a bracket order the first time every one of its own
gates (paper-account guard, staleness, partial-bar, signal, sizing) passes. There is no
further human step between merge and that first live scan — the gate list below is the
only thing standing between "reviewed" and "trading."

**Merge gates — all eight checked off on #479 as of 2026-07-29 (T10's close):**

1. PR-A (#484) merged, CI green. **Closed** — #484.
2. **`hourly-check` deployed and confirmed present *and current* in the dev
   project's function list** (`supabase functions list --project-ref
   qdaxxsuicyiscdvsdowc`, or the Dashboard's Edge Functions page). **Closed** —
   redeployed to version 3 (`deployed_at 2026-07-29T11:21:51Z`), postdating #489's
   merge (`2026-07-29T10:56:02Z`); see the "T9 evidence: Layer-B live smoke" comment
   on #479, which also documents this gate catching a stale version-2 deploy first.
   This gate stays **permanently re-checkable** — even once the §3 hunk lands on
   `main` and CI starts deploying `hourly-check` automatically, "CI should have
   deployed it" is an assumption; this gate is the check that confirms it. **Before
   merging this PR specifically**, re-confirm no PR touching `hourly-check` or its
   shared dependencies has merged since version 3's `2026-07-29T11:21:51Z` — if one
   has, redeploy (route (c) or CI, whichever applies) before relying on this gate
   again.
3. #480 (post-fill journaling failure window: bounded retry + reconciliation
   recovery) merged and deployed. **Closed** — included in the version-3 redeploy
   (gate 2).
4. Layer-B pin merged from a real capture (§12 appendix). **Closed** — PR #489, not
   PR-A (#484)'s pre-pin fail-closed placeholder.
5. T9 evidence (§7) posted on #479, outcome `skipped:market_closed`. **Closed** —
   see the "T9 evidence: Layer-B live smoke" comment on #479.
6. T10 evidence (§8) posted on #479, inequality holds with the observed latency.
   **Closed** — see the "T10 evidence: bar alignment" comment on #479 (observed feed
   latency <= 1 minute; `7 + 1 = 8 < 10`, two minutes of headroom; the pinned minute
   `:07` needed no change).
7. §4's secrets set on `qdaxxsuicyiscdvsdowc`, in particular
   `HOURLY_SHORTS_ENABLED=false`. **Closed on operator attestation; the fail-open
   default behind the caveat is fixed as of #493.** When this gate was assessed,
   `HOURLY_SHORTS_ENABLED` **defaulted to `"true"`** if the secret was ever unset,
   unlike `HOURLY_BOT_PAPER_ONLY`, whose being-set is mechanically proven by T9's
   `skipped:market_closed` outcome (that outcome is only reachable past the config
   read). Nothing in the evidence chain proved `HOURLY_SHORTS_ENABLED`'s value the
   same way, so this gate's evidence is the lead's 2026-07-29 re-assertion of
   `HOURLY_SHORTS_ENABLED=false` (recorded on #479, "Capture evidence" comment),
   not the original secrets set. #493 has since flipped the default to `false`
   (`config.ts`), so a lost or never-set secret leaves shorts off and enabling them
   takes an explicit `"true"`; the attestation is no longer the only thing standing
   between an unset secret and an armed short path. See the "Capture
   evidence — four read-only paper GETs (T1), operator-run 2026-07-29" comment on
   #479 for the original set, and §10's stop-signal list for the live check this
   gate cannot replace (a `hourly_scans` row with `decision = 'SHORT'` is an
   immediate stop-and-roll-back regardless of what this gate says).
8. §5's baseline row present (residual-position check recorded); `bot_config.paused
   = 'false'` confirmed (§6). **Closed** — baseline `1017330.61`, no residual
   position, resume confirmed in the "T9 evidence" comment's "supporting state"
   block on #479.

T8(b)'s gated `RUN_DB_TESTS` roundtrips are not a §9 gate but were also completed
against a local stack (never `qdaxxsuicyiscdvsdowc`) — see the "T8(b) evidence"
comment on #479: 41/43 pass, the 2 failures are characterized test-assertion defects
with no production-path impact (follow-up filed), not a schema or migration defect.

Merge outside RTH (stated procedure, not a recommendation — see above). After merge,
verify: `select jobname, schedule, active from cron.job where jobname =
'hourly-check';` returns exactly one active row.

## §10 First-scan verification checklist (T12)

Run this immediately after `0014` merges and deploys. **The first `hourly-check`
firing is the next `:07` of any hour in the `13-21` UTC window, Mon-Fri — within the
hour if merged during that window** (schedule `7 13-21 * * 1-5`), not specifically
`13:07`. §9's merge-outside-RTH procedure exists precisely so this first firing is a
deliberately-observed `skipped:market_closed` or the deliberately-observed first RTH
scan, not an unplanned mid-session scan racing the merge. This is an operator task: it
reads live `audit_log`/`hourly_scans`/`cron.job`/`net._http_response` rows on
`qdaxxsuicyiscdvsdowc`, which an agent session has no credentials for.

The `net._http_response` item below also assumes `0015_hourly_check_http_timeout.sql`
(#498) is applied, which re-schedules the same job with an explicit `net.http_post`
timeout. Against `0014` alone, expect the false alarm that item describes on any scan
that places or closes an order.

Once `0014` is live and the first scan has fired, confirm:

- [ ] First-of-session scan resolves `skipped:partial_bar`, **not**
  `skipped:stale_data` — live proof of the §4 guard-precedence ordering
  (`hourly-check/logic.ts`'s gate ladder). Exactly one `partial_bar` per session is
  correct (the session-open stub); a second consecutive one inside the same session is
  not (see the stop-and-roll-back list below).
- [ ] A `hourly_scans` row exists for the scanned bar (including SKIP rows — §9's
  "one row per scan, including skips" contract).
- [ ] `select jobname, active from cron.job where jobname = 'hourly-check';` shows
  `active = true`, exactly one row.
- [ ] `select * from net._http_response order by created desc limit 20;` shows no
  cron -> function HTTP failures. This query catches a **wrong project ref or a bad
  bearer** (cron firing silent no-ops, the same failure mode documented in the
  daily-check runbook), and those fail fast, on DNS or an HTTP status.
  **`net._http_response` is not the record of whether a scan ran: `audit_log` is.**
  See the "reading a `timed_out` row" note below before treating a timeout here as a
  failed scan.
- [ ] Watch one full RTH session end-to-end. File any anomaly as a **new issue**
  (systematic-debugging triage) — do not hot-fix inside this rollout.

**Before reading anything into a missing row:** pg_net writes `net._http_response`
inside the transaction that drives the whole batch (`insert_response` at
`src/worker.c:376`, between `StartTransactionCommand` at :302 and
`CommitTransactionCommand` at :404), so a batch's response rows become visible only
once its slowest request finishes. Querying mid-flight shows **no row yet**, which is
not the same as a lost response. With a 120s timeout on this job, wait out the
in-flight window before concluding anything from an absent row.

**Reading a `timed_out` row in `net._http_response` (#498):** a timeout there means
the *response record* was lost, not that the scan failed. pg_net timing out does not
abort the Edge Function, and pg_net does not retry `http_post`, so there is no
duplicate-invocation hazard either. `audit_log` is authoritative. For the same
invocation, check `script_name = 'hourly-check'`:

- `finished_at` populated **and** an `outcome` written -> **the scan completed.** The
  response record was lost; read the `outcome` (and any `trades` / `hourly_scans` rows)
  for what actually happened. Not a failure.
- `finished_at` null -> **this is the real failure signal.** The run died mid-flight.
  (`updateAuditLog` in `db.ts` sets `finished_at`, `outcome` and `notes` in one UPDATE,
  so a crashed run leaves *both* `finished_at` and `outcome` null, not an outcome
  without a timestamp.) Investigate, and check for an open position.
- No `audit_log` row at all for that firing -> the invocation never reached the
  function's **audit insert**. That is broader than "never reached the function":
  `insertAuditLog` runs early in `runHourlyCheck` but not first. `requireServiceRole`,
  `getHourlyConfig()` (throws on an out-of-range secret), `getServiceClient()`,
  `createAlpacaClient({ paperOnly: true })` and the insert itself all precede it, so a
  bad secret or a rejected bearer lands here too. Distinguish by the response record:
  every one of these fails **without a 2xx and without a timeout** (401 from the auth
  check, 500 from a throw, and for a wrong project ref either a connection error or an
  HTTP status depending on whether the ref resolves), whereas a **`timed_out` row with
  no audit row** means the invocation hung before its first write. The triage split
  that matters is non-2xx versus timeout: a timeout never points at the ref/bearer
  diagnosis the query above exists for.

This mattered because `0014` shipped without a `timeout_milliseconds` argument, so
pg_net's 5000 ms default applied: skip-only scans (0.74-2.6s) stayed clean while the
scans that placed or closed orders breached 5s, which inverted the check onto exactly
the sessions where the bot traded (the 2026-07-31 flatten ran 5.132s and closed a
137-share position). `0015_hourly_check_http_timeout.sql` raises the job's timeout to
120000 ms, above the worst legitimate scan derivable from the function's own poll
budgets, so a timeout row is once again a real anomaly. Treat one as worth
investigating: because `alpaca.ts`'s `trade()` has no per-request timeout (#511), this
pg_net timeout is currently the only thing in the cron path that will surface a stalled
broker connection at all. Do not respond to one by loosening this check.

**Stop signals in `audit_log.outcome` for `script_name = 'hourly-check'` — not just
`error:*`:**

- Any `error:*` outcome.
- `success:journal_degraded` (`logic.ts:992`) — a filled paper entry whose `trades`
  row or `entry_order_id` never landed; degrades the day cap, cooldown, and re-leg
  provenance for later scans even though the scan itself "succeeded." Follow-up #486
  tracks surfacing this more visibly; until then, treat every occurrence as a stop
  signal here.
- `success:auto_paused` (`logic.ts:622`) — the -15% equity floor tripped. Same
  unmanaged-position consequence as an operator-initiated pause with a position
  open (§11) — check for an open position before assuming this is inert.
- `success:legs_replaced` — not a stop signal by itself (it is the safety stack's own
  re-leg mechanism working as designed), but **investigate**: it means a naked
  position was found and re-legged, which should not happen in ordinary operation.
- `error:SubPennyPriceError` (#494) — an order leg price was not a whole-cent
  multiple, so `alpaca.ts` refused to submit it. **Check for an open position before
  assuming nothing was placed.** On the LONG path the check runs before the single
  bracket POST, so nothing reached the broker and there is no orphaned leg. On the
  SHORT path the market entry is placed first and the OCO exit pair second
  (`logic.ts:917-918`), so this error can leave a filled position with no protective
  legs. Either way **every entry stays blocked until it is fixed**: this is the
  local-failure form of the Alpaca 422 that blocked every entry on 2026-07-30. The
  class extends `AlpacaError`, so it also raises a Discord alert. Expect the price in
  the message; file a new issue rather than hot-fixing the geometry here.

**Stop and roll back immediately on any of:**

- A `hourly_scans` row with `decision = 'SHORT'` — shorts must stay disabled for this
  rollout (§9 gate 7); see #493 for the fail-open default this guards against.
- `success:journal_degraded` or `error:naked_position_flattened`.
- A second consecutive `skipped:partial_bar` inside one session (a session-bounds or
  timezone fault, not a stub — the first one per session is expected and correct).
- Any nonzero SPY position surviving past the `19:07Z` (EDT) flatten scan — the
  day-scoped (`time_in_force: "day"`) bracket legs are **assumed** (standard Alpaca
  day-order behavior, not yet observed on this account — see the first-session check
  below) to be cancelled by the broker at the close, so a position still open after
  that scan is unmanaged overnight regardless of whether that assumption holds.
- An order whose notional materially exceeds 10% of equity (`SIZING_NOTIONAL_CAP_PCT`).

**First-session check (new, round 2):** on the first morning after a session that
held a position, confirm no resting legs survived from the prior session — query
`listOpenOrderIds(SPY)` (or check the Alpaca paper-account orders page) and expect
zero open orders left over from the previous day. This is the live confirmation that
the day-`time_in_force` cancellation assumption above actually holds on this account;
until it's been observed at least once, treat the assumption as unverified.

**Roll back with `panic?action=liquidate` first if a position is open, `pause` if
flat, then `select cron.unschedule('hourly-check');`** — see §11 for the full
procedure and the token-verification precondition.

## §11 Rollback

**Pre-merge precondition: verify `$PANIC_TOKEN` before relying on either curl below.**
The token was rotated this session, and #479's evidence chain has no panic round trip
recorded since the rotation (§6's resume predates it). Before merging this PR, run:

```bash
curl -i -X POST "https://qdaxxsuicyiscdvsdowc.supabase.co/functions/v1/panic?action=pause" \
  -H "x-panic-token: $PANIC_TOKEN"
curl -i -X POST "https://qdaxxsuicyiscdvsdowc.supabase.co/functions/v1/panic?action=resume" \
  -H "x-panic-token: $PANIC_TOKEN"
```

and record both HTTP 200s on #479. This is a `bot_config`-only round trip (no broker
call either direction — `pause`/`resume` never reach Alpaca), so it is safe to run at
any time, RTH or not, and leaves `bot_config.paused` back at `'false'` afterward
(confirm this — do not leave the bot paused by accident). The independent
`cron.unschedule` lever below does **not** depend on this token; it is the fallback if
the token itself is the thing that has gone wrong.

Any point in this rollout can be unwound without code changes:

- **Pause new entries (fast, reversible, no broker call):**
  `curl -i -X POST ".../panic?action=pause" -H "x-panic-token: $PANIC_TOKEN"` →
  `bot_config.paused = 'true'`; `hourly-check` exits `skipped:trading_paused` before
  contacting Alpaca on its next scan. **Sufficient only when the bot is flat.** Pause
  returns before `reconcile()` (`logic.ts:566`, ahead of the reconciliation call at
  `:583`), so pausing with a position open also disables the session-close flatten
  scan (`:520-542`, armed at `:580`), the naked-position re-leg, and #480's recovery
  pass — none of which run once the pipeline exits at the pause check, on **every**
  invocation while `paused` stays true, this session's or any later one's. Bracket
  legs are `time_in_force: "day"` (`alpaca.ts:391`); Alpaca's own day-order semantics
  cancel unfilled `day` legs at the session close, but **this is an assumption, not
  yet observed on this account** — nothing in this repo tests it, live or otherwise
  (see the first-session check in §10). `KILL_SWITCH_DRAWDOWN_PCT` defaults to 25%
  off a 30-day rolling high and will not fire on a same-day SPY move. **Net effect:
  pausing mid-session with an open position leaves that position unmanaged and
  unhedged overnight, and it stays that way — while `paused` is `true`, nothing
  re-legs it, in this session or any subsequent one.** Recovery requires an operator:
  either `action=resume` (after which the next RTH scan's `reconcile()` re-legs it)
  or a manual flatten. The identical consequence applies to a `success:auto_paused`
  floor trip (`logic.ts:622`) — it pauses the bot the same way, with a position open
  or not, and is machine-initiated so it never self-clears; the same two recovery
  paths apply. **If a position may be open, use `action=liquidate` below, or a
  manual flatten, not `pause` alone.**
- **Flatten the current position (broker call, RTH only):**
  `curl -i -X POST ".../panic?action=liquidate" -H "x-panic-token: $PANIC_TOKEN"` —
  side-aware and symbol-aware (#474/#476), so this correctly covers a short or closes
  a long in SPY; also sets `paused=true`. **This is the correct lever whenever a
  position might be open** — pause alone is not (see above).
- **Stop the cron entirely (post-`0014` only):**
  `select cron.unschedule('hourly-check');` in the SQL editor, or a follow-up guarded
  migration mirroring `0013`'s pattern. Function code and deployed Edge Function are
  untouched either way — this is schedule-only, same as `0013`. Does not depend on
  `$PANIC_TOKEN`.
- **Before `0014` merges:** there is nothing to unschedule yet — the cron block ships
  fully commented out until this migration lands, so "rollback" before that point is
  simply not merging this PR.

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
