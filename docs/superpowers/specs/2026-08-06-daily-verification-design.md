# Daily verification: automating the soak-day SQL ritual

Date: 2026-08-06
Status: approved (brainstormed with the operator, 2026-08-06)
Refines: #535 (the manual day-3 checklist) and its closing question
Supersedes: nothing. The manual SQL stays documented as the fallback.

## 1. Context

Since the hourly bot went live on dev/paper (batch #478, rollout runbook
`docs/runbooks/hourly-bot-rollout.md`), each trading day has been verified by
hand: the operator pastes seven SQL queries into the Supabase SQL editor after
the 21:07 UTC slot, reads the results against a written expectation, and posts
a digest comment on that day's ops issue (#523 for day 2, #535 for day 3).

Three problems with the ritual as it stands:

1. It only happens when the operator remembers, so a bad day can pass unseen.
2. Its expectations are hardcoded per day (nine slots, 108 slots, six candidate
   bars, one specific baseline value), so each day needs a fresh checklist
   issue written by hand.
3. Nothing accumulates. Every day's result lives in a GitHub comment, so no
   trend (latency drift, skip-reason mix, detector firing rates) is queryable
   without reading prose.

`#535` itself asks the open question this spec answers: whether the daily SQL
ritual stops and hands over to automation.

## 2. Goal

Each trading day, without operator involvement:

1. Verify the day mechanically and report PASS, WARN, or FAIL.
2. Say so on Discord once, whatever the verdict.
3. Persist the day's structured metrics so later work can query trends.
4. Persist a human-readable digest, viewable both in git and on the dashboard.

Non-goal, stated up front because it bounds everything else: this is
observability. It reads. It never trades, never writes to the trading
database, and adds no decision rule.

## 3. Decisions

**D1. Data channel: the `status` digest, not a database credential.**
The check runs in GitHub Actions against `status?verify=YYYY-MM-DD` using the
existing read-only `STATUS_TOKEN`. Rejected: putting
`SUPABASE_SERVICE_ROLE_KEY` into Actions secrets (CI currently holds no
write-capable credential, and `StatusDeps` guarantees read-only at the type
level, a guarantee worth keeping). Rejected: in-database SQL plus `pg_cron`,
because `deno task test:db` has never run in CI, so the logic would ship
untested.

**D2. The digest publishes facts, the script publishes verdicts.**
The `verification` block carries rows and counts only. Every threshold,
expectation, and pass/fail rule lives in `scripts/daily_verify.ts`. Two
reasons: no judgment enters a read-only function, and a new check can ship
without redeploying an Edge Function.

**D3. Expectations are derived, never calendar-pinned.**
`hourly-check` and `kill-switch` both insert their `audit_log` row before any
gate (market-closed, paused, paper), so daily row counts are pure cron
arithmetic and hold on holidays, early closes, and across DST. The scan-row
expectation derives from the audit outcomes themselves (see §5.3). The
evaluator therefore needs no trading calendar, which is what keeps it from
false-alarming every Thanksgiving.

**D4. Manual check 5 is substituted, not implemented.**
`net._http_response` lives in the `net` schema, which PostgREST does not
expose, so it is unreachable through D1's channel. Its purpose (catch an
invocation that blew the 120s `pg_net` budget) is covered from the audit rows'
own `finished_at - started_at` latency. The true `net._http_response` read
needs a `security definer` SQL function and becomes a follow-up issue, not
part of this work.

**D5. Both artifacts, both committed.**
`docs/trading-journal/daily-verification.jsonl` (one line per trading day,
machine-readable) and `docs/trading-journal/daily/YYYY-MM-DD.md` (the rendered
digest). Committed by the workflow, following
`.github/workflows/weekly-research-review.yml`'s commit-the-artifact pattern.

**D6. Both artifacts are deterministic functions of their inputs.**
No clock reads, no run URLs, no generated-at stamps inside either artifact.
Re-running a date reproduces byte-identical content, so the commit step
no-ops and a re-run is safe. The ledger is keyed by date and upserted in date
order, which also makes backfill order-independent.

**D7. One Discord line per run, whatever the verdict.**
The operator chose a daily positive confirmation over the repo's
silence-is-healthy default (post-#514). The line carries the verdict plus the
headline numbers, and the findings when there are any.

**D8. A FAIL opens one issue per date, deduped by title.**
Not the deadman latch: a bad trading day is a dated event rather than an
ongoing incident, and `scripts/deadman_latch.sh` hardcodes watchdog wording
and posts its own Discord message, which would duplicate D7's line. Dedup by
title follows `weekly-research-review.yml`. WARN opens no issue.

**D9. Vocabulary is imported, not restated.**
`scripts/render_weekly_journal.ts` already exports the pure aggregation
helpers, and `findUnmatchedEntryTrades` is manual check 4 exactly.
`daily_verify.ts` imports `pairHourlyTrades`, `findUnmatchedEntryTrades`, and
the skip-reason grouping rather than reimplementing them. Equity headroom uses
the published `computeEquityHeadroomPct` formula from `status/logic.ts`
(`(equity - floorPrice) / equity`), per batch #534's decision 5. Batch #534's
finding 5 exists because two surfaces shipped two formulas for one metric; this
spec forbids a third.

**D10. The dashboard renders the markdown at build time.**
`react-markdown` plus `remark-gfm` (web/ grows from 5 runtime dependencies to
7), reading `docs/trading-journal/daily/` in `generateStaticParams`. No
runtime filesystem access and no secrets, so `next build` in `web-ci.yml`
still passes without credentials. The daily commit to `main` triggers the
Vercel redeploy that publishes the new day.

**D11. Explicit date parameter, so backfill is free.**
`workflow_dispatch` takes a `date` input. `audit_log` and `hourly_scans` still
hold 2026-08-03 onward, so the ledger starts with real history rather than one
row.

**D12. Weekend and future dates are refused, not evaluated.**
A Saturday or Sunday target exits 0 with verdict `SKIPPED_WEEKEND` and writes
nothing. A future date is a 400 from `status` (§4.2).

## 4. The `verification` block (owned by Package A)

### 4.1 Request

```
GET /functions/v1/status?verify=YYYY-MM-DD
  header: x-status-token: <STATUS_TOKEN>
```

Composable with the existing `?days=N`; the two parameters are independent.

### 4.2 Parameter validation

Mirrors `parseDays`'s strictness in `supabase/functions/status/handler.ts`: a
malformed parameter is a 400, never a silent fallback.

- Must match `/^\d{4}-\d{2}-\d{2}$/` after trimming.
- Must parse to a real UTC calendar date (rejects `2026-02-30`).
- Must not be in the future relative to `deps.now()`.
- Must be within 90 days of `deps.now()` (bounds the query).

### 4.3 Response shape (frozen contract)

Present only when the parameter is present, spread conditionally so the
default response stays byte-identical (the `trades`/`regime_history`
precedent in `runStatus`).

```json
{
  "verification": {
    "date": "2026-08-05",
    "window": {
      "since": "2026-08-05T00:00:00.000Z",
      "until": "2026-08-05T23:59:59.999Z"
    },
    "shorts_enabled": false,
    "hourly_check_runs": [
      {
        "started_at": "2026-08-05T13:07:02.113Z",
        "finished_at": "2026-08-05T13:07:03.001Z",
        "outcome": "skipped:market_closed",
        "notes": null
      }
    ],
    "kill_switch_runs": {
      "count": 108,
      "outcome_counts": { "success:no_position": 108 }
    },
    "scans": [],
    "trades": [],
    "config": {
      "paused": "false",
      "hourly_experiment_start_equity": "1017330.61",
      "hourly_experiment_baseline_verified": "1017330.61"
    }
  }
}
```

Contract notes, all load-bearing:

- `hourly_check_runs` is ascending by `started_at`, filtered to
  `script_name = 'hourly-check'`, and carries `notes` because the
  journal-degraded order id lives there (rollout runbook §10).
- `kill_switch_runs` is counts only. 108 rows of identical outcome carry no
  information the counts lack, and the payload stays small.
- `scans` are full `HourlyScanRow` values (numbers already coerced), ascending
  by `bar_ts`.
- `trades` are full `TradeRow` values for the day, **unfiltered by reason**,
  ascending by `fill_time`. The evaluator applies the `hourly%` filter, so a
  future reason string needs no redeploy.
- `config` values are the **raw strings** from `bot_config`, or null when
  unset. Check 6 is a byte-identity comparison between
  `hourly_experiment_start_equity` and `hourly_experiment_baseline_verified`,
  which coercion to number would destroy.
- `shorts_enabled` comes from a **narrow reader for `HOURLY_SHORTS_ENABLED`
  alone**, extracted in `_shared/config.ts` and delegated to by
  `getHourlyConfig()` so there is one parser for the variable. It must NOT come
  from `getHourlyConfig()` itself: that function throws unless
  `HOURLY_BOT_PAPER_ONLY` is explicitly `"true"`, and coupling `status` to it
  would take the endpoint down for every caller (including the deadman
  watchdog, whose only data source it is) over one unrelated secret. See the
  amendment log in §13.

### 4.4 Reads

Reuses `getAuditLogSince(sb, since, until)` for both scripts (it paginates to
10,000 rows and throws on breach, so 117 rows per day is comfortable) and
`getConfig` three times. Adds two bounded SELECT-only helpers to
`_shared/db.ts`, mirroring `getHourlyScansSince`'s defensive-cap style:

- `getHourlyScansInWindow(sb, sinceIso, untilIso)`
- `getTradesInWindow(sb, sinceIso, untilIso)`

No mutating helper is wired into `StatusDeps`, so the read-only-by-type
guarantee documented at the top of `status/logic.ts` still holds.

## 5. The evaluator (owned by Package B)

`scripts/daily_verify.ts`, shaped exactly like `scripts/deadman_check.ts`: a
pure evaluation core plus a thin CLI reading the digest JSON from **stdin**,
needing zero Deno permissions.

Exit codes: `0` PASS or WARN or SKIPPED_WEEKEND, `2` FAIL, `1` malformed input
(bad JSON, missing `verification` block, unparseable timestamp).

### 5.1 Verdict levels

- **PASS**: every check passed.
- **WARN**: something is true and worth a look but not broken (a slow scan, a
  pending entry, an unset baseline). Does not open an issue.
- **FAIL**: at least one check failed. Opens the dated issue, exits 2.

A day's verdict is the highest severity across its checks.

### 5.2 Derived constants

Named, with the derivation in a comment, following `deadman_check.ts`:

- `HOURLY_SLOTS_PER_WEEKDAY = 9` from `pg_cron` `7 13-21 * * 1-5`
  (migration 0014).
- `KILL_SWITCH_SLOTS_PER_WEEKDAY = 108` from `*/5 13-21 * * 1-5`, that is
  13:00 to 21:55 inclusive.
- `LATENCY_WARN_MS = 10_000`, the per-request deadline from #511.
- `LATENCY_FAIL_MS = 120_000`, migration 0015's `pg_net` budget.

### 5.3 The seven checks

| Key | Replaces | Rule |
|---|---|---|
| `slots` | check 1 | `hourly_check_runs.length === 9`, every row has non-null `finished_at` and non-null `outcome`, no `outcome` starting `error:`. Any breach FAILs. |
| `latency` | check 5 | Per run, `finished_at - started_at`. WARN above `LATENCY_WARN_MS`, FAIL above `LATENCY_FAIL_MS`. |
| `scans` | check 2 | `scans.length` must equal the number of runs whose outcome is **not** in `NON_SCANNING_OUTCOMES` (see below). Mismatch FAILs. A `SHORT` decision while `shorts_enabled` is false FAILs. A `LONG` row with a null `entry_order_id` WARNs (a later scan's reconcile may still adopt it). A neutral-only `detectors_fired` alongside `no_detectors_fired` is never a finding. |
| `geometry` | check 3 | For each scan with a non-null `stop_price`/`target_price`, the value must be whole cents. Test as `Math.abs(Math.round(x * 100) - x * 100) <= 1e-6`, because `123.45 * 100` is `12344.999999999998` in IEEE 754. Any breach FAILs. |
| `journal` | check 4 | `findUnmatchedEntryTrades` (imported) over the day's `hourly%` trades and the day's scans. Any unmatched fill FAILs. |
| `state` | check 6 | `paused` must be `"false"`; `hourly_experiment_baseline_verified` must be byte-identical to `hourly_experiment_start_equity`; the baseline must be byte-identical to the previous ledger row's stored raw baseline. Any breach FAILs. An unset baseline WARNs (day-zero). |
| `kill_switch` | check 7 | `count === 108`; every outcome starts `success:` or `skipped:`; a uniform `success:no_position` alongside any `LONG` scan row is a contradiction that FAILs. |

`NON_SCANNING_OUTCOMES` is the set of `hourly-check` outcomes that write no
`hourly_scans` row. **The implementer must derive this set by reading
`supabase/functions/hourly-check/logic.ts`'s gate order** (which gates precede
the journal write) and pin it with a test referencing the line numbers. Do not
guess it from the outcome names. `skipped:market_closed` is certainly in the
set; `skipped:partial_bar` is certainly not (#535 check 2 documents that the
partial bar is journaled with empty `detectors_fired`, meaning "not
evaluated").

Cross-day state (the previous ledger row) is passed into the pure evaluator as
an argument. It is never read from disk by the evaluation core.

### 5.4 Date resolution

The workflow resolves the target date before calling `status`, and the rule
lives in the tested pure layer:

- `workflow_dispatch` with a `date` input uses it verbatim.
- Otherwise: today in UTC when the UTC hour is 12 or later, else the previous
  UTC day. Actions schedule jitter only ever delays, so a run pushed past
  midnight still evaluates the day it was scheduled for.
- A Saturday or Sunday target returns `SKIPPED_WEEKEND` and writes nothing.

### 5.5 CLI contract (frozen, because two packages implement against it)

Package B owns the script; Package D owns the workflow that drives it. They are
coupled by this contract only, the same way Package B is coupled to §4.3 rather
than to Package A's code.

Invocation:

```
deno run --allow-read=docs/trading-journal --allow-write=docs/trading-journal \
  scripts/daily_verify.ts --date=YYYY-MM-DD < digest.json
```

- **Input**: the full `status` response on stdin. The script reads
  `.verification` and ignores every other key, including `generated_at`.
- **Permissions**: read and write scoped to `docs/trading-journal` and nothing
  else, matching `scripts/render_weekly_journal.ts`'s precedent. The evaluation
  and rendering core stays free of all I/O and is unit-tested directly; only
  `main()` touches disk. The zero-permission property of
  `scripts/deadman_check.ts` does not carry over, because cross-day state and
  both artifacts live on disk; the property that does carry over is that every
  judgment lives in a pure function.
- **Side effects**: upserts the ledger row and writes the day's markdown
  digest. Nothing else.
- **stdout**: exactly one JSON object, so the workflow parses it with `jq`
  rather than scraping text.

```json
{
  "date": "2026-08-05",
  "verdict": "PASS",
  "summary": "9/9 slots, 6 scans, 0 entries, 108/108 kill-switch, headroom 15.0%",
  "findings": [],
  "artifacts": {
    "ledger": "docs/trading-journal/daily-verification.jsonl",
    "digest": "docs/trading-journal/daily/2026-08-05.md"
  }
}
```

- **Exit codes**: 0 for PASS, WARN, or SKIPPED_WEEKEND; 2 for FAIL; 1 for
  malformed input. On exit 1 the JSON object above is not printed and nothing is
  written.
- On `SKIPPED_WEEKEND` no artifact is written and `artifacts` values are null.
- Selecting the previous verified day's ledger row (the newest row with a date
  strictly before `--date`) is the script's job, not the workflow's, so the
  selection rule is covered by tests rather than by shell.

## 6. Artifacts (owned by Package B)

### 6.1 Ledger row

One line appended to `docs/trading-journal/daily-verification.jsonl`, keyed by
`date`, upserted (any existing line for that date is replaced) and kept in
ascending date order. Stable key order, no clock-derived fields (D6).

```json
{
  "date": "2026-08-05",
  "verdict": "PASS",
  "checks": {
    "slots": "PASS",
    "latency": "PASS",
    "scans": "PASS",
    "geometry": "PASS",
    "journal": "PASS",
    "state": "PASS",
    "kill_switch": "PASS"
  },
  "metrics": {
    "hourly_runs": 9,
    "hourly_outcome_counts": { "skipped:market_closed": 2 },
    "latency_ms": { "max": 2510, "median": 1900 },
    "scan_rows": 6,
    "evaluated_bars": 5,
    "decision_counts": { "LONG": 0, "SHORT": 0, "SKIP": 6 },
    "skip_reason_counts": { "no_detectors_fired": 5 },
    "detector_fire_counts": { "inside_bar": 2 },
    "entries": 0,
    "fills": 0,
    "closed_trades": 0,
    "r_multiples": [],
    "equity_usd": 1017330.61,
    "floor_baseline_raw": "1017330.61",
    "floor_price_usd": 864730.0185,
    "headroom_pct": 15.0,
    "kill_switch_runs": 108,
    "kill_switch_outcome_counts": { "success:no_position": 108 }
  },
  "findings": []
}
```

`floor_baseline_raw` is the raw config string, which is what makes the
cross-day byte-identity check in §5.3 possible. `r_multiples` and
`closed_trades` come from the imported `pairHourlyTrades`, so they mean exactly
what the weekly journal means by them.

### 6.2 Markdown digest

`docs/trading-journal/daily/YYYY-MM-DD.md`, following #535's seven-check
layout so a reader who has run the ritual by hand recognises it: a verdict
header, one section per check with a pass marker and the actual numbers, the
findings, and a "changed since the previous verified day" line derived from the
previous ledger row (baseline moves, latency drift, first entry). Deterministic
per D6.

## 7. The workflow (owned by Package D)

`.github/workflows/daily-verification.yml`, structured on
`deadman-watchdog.yml`.

- Schedule `15 22 * * 1-5` UTC, after `kill-switch`'s final 21:55 slot has
  landed. Plus `workflow_dispatch` with the optional `date` input.
- `concurrency: daily-verification`, no cancel-in-progress, because it commits.
- `permissions: contents: write, issues: write`.
- Secrets: `STATUS_URL` / `STATUS_TOKEN` (dev, loud-fail when missing, since a
  silently skipping check is worthless) and `NOTIFY_WEBHOOK_URL`. No new secret
  is introduced; all three are already configured for `deadman-watchdog.yml`
  and `heartbeat.yml`.
- **Prod leg: inert check only, with no pipeline behind it even once the
  secrets exist.** This deliberately does NOT mirror
  `deadman-watchdog.yml`/`heartbeat.yml`, whose prod legs become fully
  symmetric second pipelines once `STATUS_URL_PROD` / `STATUS_TOKEN_PROD` are
  set. The reason is that neither of those workflows writes repo files, while
  this one does, and §6's artifact schema carries **no environment dimension**:
  a dev leg and a prod leg would both write
  `docs/trading-journal/daily/<date>.md` and the same date-keyed ledger row for
  the same calendar date, so whichever ran second would silently clobber the
  other. Activating prod therefore requires a schema decision (namespacing the
  artifacts per environment), which is out of scope here and recorded as a
  follow-up in §12. Until then the leg is a `::notice::` and nothing more. See
  the amendment log in §13.
- Maintenance silence: repo **variable** `DAILY_VERIFY_SILENCED` set to exactly
  `true` short-circuits every step to a green `::notice::` exit, the same idiom
  as `DEADMAN_SILENCED`.
- Never prints the digest JSON (it carries account and position data). Only the
  verdict, the metrics that go into the artifacts, and the findings reach the
  log.
- Commits both artifacts with the `github-actions[bot]` identity, no-op when
  unchanged.
- Posts exactly one Discord message per run via `curl`, content truncated to
  Discord's 2,000-character limit. Not via `_shared/notifications.ts`: CI has
  no Supabase client and must not acquire one.
- On FAIL, creates `[daily-verify][dev] <date>: N finding(s)`, deduped by exact
  title against `--state all`, labelled `daily-verify`.

Green versus red: a run that verifies a day and delivers its artifacts and its
Discord line is green **even when the verdict is FAIL**, because the dated
issue plus the Discord alert are the signal (deadman's rule, for deadman's
reason). Red is reserved for workflow-internal failure: dev secrets missing,
the commit or push failing, the Discord post failing, or the evaluator exiting
1 on a malformed digest.

## 8. The dashboard view (owned by Package C)

- `/daily`: index of verified days, newest first, each with its verdict badge
  and headline numbers, read from the ledger.
- `/daily/[date]`: the rendered markdown digest, via `react-markdown` with
  `remark-gfm` (tables and task lists), styled with the existing Tailwind
  setup. HTML in markdown stays escaped (react-markdown's default).
- A tile on the existing dashboard page showing the latest verified day and its
  verdict, linking to `/daily`.
- Both routes read `docs/trading-journal/` at build time
  (`generateStaticParams` plus a build-time read), so no runtime filesystem
  access, no secrets, and `next build` still passes in CI without credentials.
- Empty state: the routes must build and render sensibly when
  `docs/trading-journal/daily/` is empty or absent, so the package is testable
  before any digest exists.
- **Known deployment risk with a documented fallback.** With Vercel's Root
  Directory set to `web`, reading `../docs` at build time requires "Include
  source files outside of the Root Directory" to be enabled. No agent can
  verify this (Vercel is behind the operator's SSO). The package must therefore
  ship a documented fallback in `web/README.md`: a `prebuild` step that copies
  `docs/trading-journal/daily/*.md` into a gitignored `web/content/daily/`.
  Choosing the fallback is a one-line `package.json` change, not a redesign.

## 9. Testing requirements

- `scripts/daily_verify.test.ts` covers the pure core over fixtures: a clean
  day; a holiday (nine gate-exits, zero scans, still PASS); a missing slot; an
  unfinished row (null `finished_at`); an `error:*` outcome; a latency above
  each threshold; sub-cent geometry; an unmatched fill; `paused=true`; a
  baseline that moved since the previous ledger row; an unset baseline; a SHORT
  while `shorts_enabled` is false; a pending `LONG` (WARN, not FAIL); the
  uniform-`no_position`-versus-`LONG` contradiction; each date-resolution
  branch including the past-midnight case and the weekend skip; ledger upsert
  idempotence; and byte-identical re-render of both artifacts.
- `supabase/functions/status/logic.test.ts` and the handler test cover the
  `verification` block's shape, its absence without the parameter, the
  byte-identical default response, every parameter-validation rejection, and
  composition with `?days=N`.
- Fixture files live under `scripts/testdata/`. Package A owns
  `status-digest-verification.json` (its shape pin); Package B owns its own
  `daily-verify-*.json` fixtures. No shared fixture file, so the packages never
  collide.
- `web/` has no test runner and adding one is out of scope (batch #534's
  recorded open item). Package C's verification is `npm run typecheck` plus
  `npm run build` in `web-ci.yml`, and a single operator page load. This is an
  accepted pre-existing limitation, not a new one.
- Every Alpaca call in every test stays mocked. `status` reads Alpaca via
  `getClock`/`getAccountValue`/`getPosition` only, and `CLAUDE_AGENT_NO_BROKER`
  remains the mechanical backstop.

## 10. File ownership (batch slicing)

Single owner per file, so three packages can run concurrently without
collisions.

| Package | Owns |
|---|---|
| A | `supabase/functions/status/**`, `supabase/functions/_shared/db.ts`, `supabase/functions/_shared/config.ts`, `scripts/testdata/status-digest-verification.json`, `docs/runbooks/status-check.md` |
| B | `scripts/daily_verify.ts`, `scripts/daily_verify.test.ts`, `scripts/testdata/daily-verify-*.json` |
| C | `web/**` |
| D | `.github/workflows/daily-verification.yml`, `docs/runbooks/daily-verification.md`, `docs/trading-journal/README.md`, `CLAUDE.md` |

Package D is the sole owner of `CLAUDE.md` this batch. Package A documents its
new parameter in `docs/runbooks/status-check.md` only, and touches
`_shared/config.ts` only for the narrow `HOURLY_SHORTS_ENABLED` reader (§4.3).
The lead owns this spec file; no package edits it.

The packages are coupled by frozen contracts, never by code, so none blocks
another and all four can run concurrently:

- A and B by §4.3's digest shape. B implements against its own fixtures,
  exactly as `deadman_check.ts` is coupled to the digest's shape rather than to
  the Edge Function module.
- B and D by §5.5's CLI contract. D's workflow is written against the documented
  invocation and stdout envelope, and its end-to-end verification waits for B to
  merge.
- C by §6.1 and §6.2's artifact schemas, with an empty state that renders before
  any artifact exists.

## 11. Architectural invariant compliance

- **One decision rule.** Untouched. Nothing here evaluates a signal or gates an
  entry. `decideHourly` is neither imported nor modified.
- **No LLM in the trading path.** Untouched. All three surfaces are read-only
  observability, and the evaluator is a pure function with no model SDK.
- **Mechanical paper-only guard.** Untouched. No order-placing helper is
  reachable from any file in this work.
- **Operational kill switch.** Untouched. `bot_config.paused` is read, never
  written.
- **Panic is the deterministic kill button.** Untouched.
- **Engineer subagents never execute against the live broker.** Preserved: no
  test added here reaches a mutating Alpaca helper, and the guard stays armed
  by `deno task test`.

## 12. Non-goals and follow-ups

Non-goals for this work:

- No trading-path change and no second decision rule.
- No `net._http_response` reader (D4).
- No `web/` test toolchain.
- No prod-leg activation (the leg ships inert, per #230).
- No deletion of #535's manual SQL, which stays as the documented fallback.
- No change to `scripts/deadman_latch.sh` or the watchdog (D8).
- No retirement of the weekly journal. It stays the owner of weekly strategy
  judgment; this is daily plumbing verification.

Follow-ups worth filing after this lands:

- **Namespacing the artifacts per environment, before any prod leg is
  activated.** §6's ledger and digest paths are keyed by date alone, so a live
  prod leg would collide with the dev leg on every trading day. Whoever flips
  the prod switch at #230 needs this first. Recorded because the collision is
  invisible until both legs run.

- The `net._http_response` timeout check, via a `security definer` SQL function
  plus an RPC, restoring manual check 5 in full.
- Backfilling the ledger for 2026-08-03 onward by dispatching the workflow per
  date (D11), which is operator-run, not part of any package.
- Whether the daily digest should also carry the `hourly_kill_switch`
  attribution gap tracked in #543, once that lands.

## 13. Amendment log

Amendments made by the lead during batch #545's run. Each is logged in full as a
decision comment on #545; this section is the durable record.

**2026-08-06, A1: `shorts_enabled`'s source (§4.3).** The original text said the
value comes from `StrategyConfig`. It does not exist there. Corrected to a narrow
`HOURLY_SHORTS_ENABLED` reader extracted in `_shared/config.ts`, which
`getHourlyConfig()` delegates to. Package A's ownership extends to
`_shared/config.ts` for that extraction only. Rejected the alternative of
calling `getHourlyConfig()` from `status`, because it throws unless
`HOURLY_BOT_PAPER_ONLY` is explicitly `"true"`
(`_shared/config.ts:175-183`), which would take `status` down for every caller,
the deadman watchdog included, over one unrelated secret. The JSON shape is
unchanged.

**2026-08-06, A2: minor calls settled with A1.** Trades ascending by `fill_time`
(§4.3 was silent). `scripts/testdata/status-digest-verification.json` must be
consumed by a test, not merely committed: the three existing sibling fixtures
have zero consumers, and a fixture nothing reads pins nothing. Validation order
`days` before `verify`, pinned by a test. `handleStatus` may take an injectable
`now` whose default leaves `index.ts` unchanged.

**2026-08-06, B1: Package B split, and §5.5 added.** The original Package B
(evaluator, artifacts, workflow, and three doc surfaces) was larger than its
`size:M` label. Its architect recommended relabeling to `size:L` and running it
whole; overruled, because the kickoff pipeline's own gate stops on `size:L`
precisely to avoid a session dying mid-task. Split instead into Package B
(`scripts/daily_verify.ts` plus tests and fixtures) and Package D (the workflow
and the three doc surfaces), which are independent given §5.5's frozen CLI
contract, so the batch keeps its concurrency and gains no `Blocked by` edge.
§5.5 also settles the architect's open question about where disk access lives:
one scoped invocation, all judgment in pure functions, matching
`render_weekly_journal.ts` rather than `deadman_check.ts`.

**2026-08-06, D1: the prod leg is inert-check-only, and §7 said otherwise.**
§7 originally told Package D to mirror `deadman-watchdog.yml` and
`heartbeat.yml`, whose prod legs activate into full symmetric pipelines once
their secrets exist. Package D's architect found that this cannot be right for
this workflow: those two write no repo files, whereas §6's artifacts are keyed
by date with no environment dimension, so a live prod leg would clobber the dev
leg's ledger row and digest for every trading day, invisibly, whichever ran
second. Corrected §7 to inert-check-only with no pipeline behind it, and filed
the artifact-namespacing decision as a §12 follow-up that must land before
anyone activates prod at #230. The architect flagged this rather than inventing
a namespacing scheme, which was correct: the artifact schema is Package B's
contract, not Package D's file to change.

**2026-08-06, D2: end-to-end verification needs #546 deployed too, not only
#547 merged.** The batch framing described the workflow as coupled to the script
alone. Package D's architect pointed out that its fetch step targets
`status?verify=`, which the dev-deployed `status` function does not recognise
until Package A (#546) is merged and deployed. So the first real pipeline run
needs all three: #546 merged and deployed, #547 merged, then #549.

**2026-08-06, D3: #535's SQL gets a durable home.** "Keep the manual SQL as the
documented fallback" (§12) was underspecified: those seven queries currently
exist only in the body of #535 and the superseded #523, both closable. Package D
copies the corrected seven-query ritual verbatim into
`docs/trading-journal/README.md` rather than linking to an issue.

**2026-08-06, B3: a second disclosed residual, in the `state` check.** §5.3's
`state` rule requires the day's baseline to be byte-identical to the previous
ledger row's. Package B's implementation takes the day-zero WARN branch when the
baseline is unset, without comparing against the previous row, so a baseline that
gets **deleted** WARNs rather than FAILs. #547's reviewer verified that this is
transitively covered for every realistic day: a missing or blank
`hourly_experiment_start_equity` makes `hourly-check`'s gate 6 throw via
`alertAndFail`, surfacing as `error:DataError`, which the `slots` check FAILs
unconditionally, and a `paused=true` day already FAILs on `state`'s first clause.
The residual is one triple coincidence: a full-day market closure, with
`paused=false`, and the baseline deleted that same day. Gate 6 then never runs on
any of the nine slots, so `slots` passes and only a WARN surfaces. Left as
should-fix rather than must-fix on this batch's own tiebreaker (a visible WARN is
not a false all-clear), and recorded here so the boundary survives whether or not
the code comment disclosing it ever lands.

**2026-08-06, B2: the `NON_SCANNING_OUTCOMES` derivation is done.** Package B's
architect traced every return path in `hourly-check/logic.ts` against the file's
own numbered gates and found five outcomes that return before any journal call
for the run's candidate bar: `skipped:trading_paused` (gate 1),
`skipped:market_closed` (gate 3), `error:naked_position_flattened`
(`reconcile()`'s terminal branch), `success:auto_paused` (gate 6's floor fire,
which calls `finish()` directly and bypasses `done()`), and
`skipped:duplicate_run` (gate 19's bar-claim loser, whose own code comment says
it must not upsert). Confirmed not in the set: `skipped:partial_bar` and
`skipped:stale_data` (both journal through `preDecisionSkip`), every `gateSkip()`
outcome, the SKIP-decision outcomes, and `success` / `success:journal_degraded`.
One disclosed residual stays in the code as a comment plus a fixture rather than
being folded silently either way: the `completed.length === 0` path returns
before journaling and can surface as `skipped:stale_data`, so that narrow
anomaly can produce a scan-count mismatch. `error:*` outcomes are excluded
because they are dynamic and not enumerable, and the `slots` check already FAILs
any `error:*` regardless.
