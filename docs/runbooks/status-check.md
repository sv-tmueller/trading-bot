# Status Check Runbook

One-time setup for the read-only `status` Edge Function (#354) and the local
`scripts/status.sh` check script, so an operator or advisor session can read
the bot's full runtime state on demand without holding a write-capable
credential.

## One-time setup (per Supabase project)

1. Generate a strong token: `openssl rand -hex 32`
2. Set the secret: `supabase secrets set STATUS_TOKEN=<generated token>`
3. Deploy the function (token-auth, no JWT — same pattern as `panic`):
   `supabase functions deploy status --no-verify-jwt`
4. Locally, copy the example env file and fill in both values:
   ```bash
   cp .env.status.example .env.status
   ```
   Edit `.env.status`:
   ```
   STATUS_URL=https://<ref>.supabase.co/functions/v1/status
   STATUS_TOKEN=<the same token you set in step 2>
   ```
   `.env.status` is gitignored — never commit it.

## Running the check

```bash
bash scripts/status.sh
bash scripts/status.sh --days 30   # widen the window (1-60, default 7); see below
```

Renders the JSON digest via `jq` (falls back to raw output with a warning if
`jq` is not installed). Exits non-zero if `.env.status` is missing, either
value is unset, or the HTTP request fails.

The script uses `curl --fail-with-body`, which requires **curl >= 7.76**
(check with `curl --version`). Unlike plain `-f`, it still prints the response
body before exiting non-zero, so a 400/401/500 error's `{ "error": "…" }` JSON
reaches the operator instead of just a bare `curl: (22) ...` line.

When `jq` is available and the digest has a non-null `hourly.latest_scan`,
`scripts/status.sh` prints a one-line summary for the **live** hourly bot
first — e.g. `` Hourly `SPY`: LONG @ 2026-08-05T14:00:00Z -- equity $95000,
floor headroom 10.5%. `` — built from `hourly.latest_scan` and
`hourly.equity`. The headroom fraction reads `n/a (no baseline set)` when
`bot_config.hourly_experiment_start_equity` hasn't been set yet; the whole
line is skipped when `hourly.latest_scan` is `null` (no scan has run yet).

Below that, when `jq` is available and the digest has a `regime` row with a
non-null `regime_margin_pct` (SPY's raw % distance from its 200-DMA, positive
above / negative below), `scripts/status.sh` also prints a one-line "why"
summary for the **retired** daily regime bot — e.g. `LONG \`UPRO\` because
SPY is 7.2% above its 200-DMA.` (or `CASH because SPY is 4.3% below its
200-DMA.` with no ticker when `current_state` is `CASH`) — built from
`alpaca.position.symbol` and `regime.current_state`. It's skipped when
`regime` or `regime_margin_pct` is `null`. The causal "because" phrasing only
appears when `target_state == current_state` and `kill_switch_active` is not
`true` — i.e. when the margin is genuinely why the position is held. If the
kill-switch has fired, or a flip is pending (`target_state != current_state`),
the line instead states the state and the signed margin without asserting a
cause (e.g. `CASH — SPY vs 200-DMA: +7.2% (above).`), since a
kill-switch-forced liquidation or a pending flip means the margin isn't the
real reason for the current position.

### `--days N`: history window

`--days N` (1-60; the server default is 7 when omitted) widens the
`audit_log` window used for the outcome counts and `error:*` rows, and adds
two arrays to the digest for the same window:

- `trades` — every fill (`trades` table row) in the window, newest first.
- `regime_history` — the daily `regime_state` rows in the window, newest
  first.

Both are `[]` (not omitted, not `null`) when the window holds no rows. The
no-`--days` response is unchanged in shape — `trades`/`regime_history` are
only present when `--days` (or the underlying `?days=`) is supplied. There is
no client-side range validation in the script; an out-of-range or malformed
`N` reaches the server, whose `400 { "error": "days must be an integer
between 1 and 60" }` is now visible via `--fail-with-body` above.

### `?verify=YYYY-MM-DD`: daily-verification data channel

```bash
curl -s "$STATUS_URL?verify=2026-08-05" -H "x-status-token: $STATUS_TOKEN" | jq .verification
```

Composable with `--days`/`?days=` — the two parameters are independent and
can be supplied together. `scripts/status.sh` has no dedicated flag for this
parameter; it exists for the automated daily-verification workflow (#546,
#547), not for interactive use, though the raw `curl` above works from any
shell that holds `.env.status`'s two values.

Adds a `verification` object to the digest, present only when `?verify=` is
supplied. Validation, in order (each rejection is a `400`, never a silent
fallback):

1. Must match `YYYY-MM-DD` after trimming — `400 { "error": "verify must be
   a real calendar date (YYYY-MM-DD), not in the future, and within 90
   days" }`.
2. Must parse to a real UTC calendar date — `2026-13-01` and `2026-02-30`
   (which silently rolls over to March) are both rejected, same error as
   above.
3. Must not be in the future relative to the server's clock; today (UTC) is
   allowed.
4. Must be within 90 days of today (UTC).

`?days=`'s own validation runs first when both parameters are malformed, so a
`400` for a bad `days` value never mentions `verify`.

What it contains: `verification.window` is the UTC calendar day
`[00:00:00.000, 23:59:59.999]` for the requested date — a fixed string
template, not date arithmetic, so there is no month/year-boundary bug.
`shorts_enabled` is the `HOURLY_SHORTS_ENABLED` secret's current value (a
narrow reader, independent of the unrelated `HOURLY_BOT_PAPER_ONLY` guard —
see `supabase/functions/_shared/config.ts`'s `getHourlyShortsEnabled()`).
`hourly_check_runs` is every `audit_log` row for `hourly-check` that day,
ascending by `started_at`, carrying `notes` (the journal-degraded order id,
per the hourly-bot rollout runbook). `kill_switch_runs` is counts
(`count` plus `outcome_counts`) plus the day's per-run `started_at`
timestamps ascending (#562), still never full rows, since ~108
same-outcome rows a day carry no information the counts lack beyond their
timing; the timestamps let the daily-verification evaluator name which
5-minute grid slot(s) are missing on a short day. `scans` and `trades` are the full,
unfiltered `hourly_scans`/`trades` rows for the day, ascending by
`bar_ts`/`fill_time` respectively — `trades` is not filtered by `reason`, so
a future entry/exit reason string needs no redeploy to show up here.
`config.paused`, `config.hourly_experiment_start_equity`, and
`config.hourly_experiment_baseline_verified` are the **raw** `bot_config`
strings (or `null` when unset) — deliberately not coerced to numbers, since a
downstream byte-identity comparison between the last two depends on the exact
string surviving unmangled.

This is the read-only data channel for the automated daily-verification
check (`scripts/daily_verify.ts`, #547) — see
`docs/superpowers/specs/2026-08-06-daily-verification-design.md` §4 for the
frozen contract and `docs/runbooks/daily-verification.md` for the check
itself. The manual seven-query SQL ritual it replaces stays documented (#535)
as a fallback.

## Heartbeat (GitHub Actions)

`.github/workflows/heartbeat.yml` ("heartbeat") exists because Supabase's
free-tier inactivity/pause criterion is based on user-facing API traffic, and
`pg_cron` invocations of `daily-check` /
`kill-switch` do **not** count toward it — a project can be paused for
inactivity even while the trading cron runs continuously. Dev received such a
warning on 2026-07-12 (see the Addendum in
`docs/decisions/2026-07-07-supabase-row-data-backup.md`). A paused project
silently stops protecting an open position, since the kill-switch can't fire
if the project itself is paused. This workflow pings the `status` function on
a schedule so the project sees real gateway traffic and stays active.

- **Schedule:** weekdays 12:23 UTC, plus manual `workflow_dispatch`.
- **Two independent targets, one job:**
  - **dev** — gated on the `STATUS_URL`/`STATUS_TOKEN` repo secrets (not new
    `_DEV`-suffixed secrets — see the sub-plan on #361). Already active as of
    this workflow merging.
  - **prod** — a single "Resolve prod coverage" step picks one of three
    modes, in precedence order:
    1. **status** — `STATUS_URL_PROD`/`STATUS_TOKEN_PROD` are both set
       (go-live, #230): the unchanged status ping runs. Takes precedence
       over keep-alive whenever both pairs happen to be set.
    2. **keepalive** — `KEEPALIVE_URL_PROD`/`KEEPALIVE_ANON_KEY_PROD` are both
       set: the interim pre-go-live keep-alive ping runs instead (see
       "Interim prod keep-alive" below).
    3. **none** — neither pair is fully set: inert green skip, unless the
       `HEARTBEAT_REQUIRE_PROD` repo variable is set to the exact string
       `true`, in which case the run fails red instead (see below).
- **Failure contract — inert skip vs red run:** missing coverage for prod is
  an **inert green skip** (`::notice::`, no request made) — the default-OFF
  idiom, since this workflow is meant to be safe to merge into forks or
  before secrets exist — *unless* the `HEARTBEAT_REQUIRE_PROD` repo variable
  is set to the exact string `true`, in which case a prod leg with no
  coverage configured fails the run red (`::error::` + exit 1) instead, so a
  scheduled failure notifies the operator by email. Default is unset
  (today's inert-skip behavior); this is a repo **variable**, not a secret.
  Once prod coverage resolves to `status` or `keepalive`, a non-2xx response
  or a timeout from that target **fails the run red** regardless of
  `HEARTBEAT_REQUIRE_PROD` (same `curl --fail-with-body --max-time 60` idiom
  `heartbeat.yml`'s own dev and prod ping steps use). The dev and prod steps
  are independent — a red prod run doesn't block dev's ping, and vice versa.

### Interim prod keep-alive (pre-go-live)

Prod (`yomamlrozydhgleumnon`) gets no user-initiated traffic before go-live,
so Supabase's free-tier inactivity policy pauses it every ~7 days even though
`pg_cron` is already proven not to count toward that criterion (#361) and the
`status` function isn't deployed there yet. The keep-alive is a stand-in: it
curls an anon REST read of a dedicated `public.keepalive` table, because
Supabase's pause criterion counts requests that reach the **database** —
gateway-only endpoints such as `/auth/v1/health` return `200` but don't
reliably count.

One-time operator setup (SQL editor, prod project only):

```sql
create table if not exists public.keepalive (id bigint primary key);
alter table public.keepalive enable row level security;
```

No policies are added, so RLS denies all access by default and an anon
`SELECT` returns `200 []` — no data is ever exposed. This is deliberately
**not** a repo migration: running `supabase db push` against prod before
go-live would also install the pg_cron trading schedules from
`0002_schedule.sql`, which is a non-goal until go-live (#230).

Required repo secrets (Settings -> Secrets and variables -> Actions):
- `KEEPALIVE_URL_PROD` — the `public.keepalive` table's REST endpoint (e.g.
  `https://yomamlrozydhgleumnon.supabase.co/rest/v1/keepalive?select=id&limit=1`)
- `KEEPALIVE_ANON_KEY_PROD` — the prod project's anon/publishable-class key
  (never the service-role key), sent as the `apikey` header

At go-live, setting `STATUS_URL_PROD`/`STATUS_TOKEN_PROD` supersedes the
keep-alive pair (status takes precedence per the mode order above); the
`KEEPALIVE_URL_PROD`/`KEEPALIVE_ANON_KEY_PROD` secrets and the
`public.keepalive` table can then be removed. See
`docs/runbooks/mvp2-deploy-and-decommission.md`.
- **GitHub's 60-day auto-disable caveat:** GitHub automatically disables a
  scheduled workflow after 60 days with no repository activity at all.
  Auto-disable protection here relies on regular development activity
  (commits, PRs, deploys) alone — this is a low but non-zero residual risk —
  if it ever fires, `heartbeat.yml` stops running silently (no
  notification), and re-enabling requires a manual visit to the Actions tab.

## Troubleshooting

- **401 Unauthorized** — token problem: either `STATUS_TOKEN` is unset/blank
  server-side (fails closed by design), or `.env.status`'s `STATUS_TOKEN`
  doesn't match what was set with `supabase secrets set`. Re-check both sides.
- **400 Bad Request** — only possible with `--days`/`?days=`: the value isn't
  an integer in `1..60`. The JSON body's `error` field names the constraint.
- **500** — function-side failure (e.g. Alpaca or DB read failed). The JSON
  body carries `{ "error": "…" }` with the underlying message; check the
  Supabase function logs for the full stack.
- **curl: connection failed / could not resolve host** — check `STATUS_URL`
  matches the deployed project ref and that `status` was actually deployed
  (step 3 above).

## What the digest contains

`hourly` (#536) covers the **live** hourly candlestick bot: `latest_scan` is a
direct pass-through of the newest `hourly_scans` row (bar timestamp, symbol,
decision, detectors fired, context mode, and bracket geometry when that scan
entered), `equity` reports `hourly_scans.equity_usd` against the -15% floor
computed from `bot_config.hourly_experiment_start_equity` (all four fields
`null` until a baseline is set and at least one scan has run),
`skip_reason_counts` is the bar-level SKIP distribution over the same window
as `audit_7d` (grouped exactly like `scripts/render_weekly_journal.ts`'s
weekly aggregation), and `audit_outcome_counts` is the run-level outcome
distribution for `hourly-check` only, pulled from the same `audit_log` rows
already fetched for `audit_7d` (no extra DB round trip). Equity here is
always `hourly_scans.equity_usd` — never a live Alpaca account read.

The remaining top-level fields (`regime`, `regime_margin_pct`, `returns`,
`alpaca.position`) describe the **retired** daily regime bot (superseded by
the hourly candlestick bot; see CLAUDE.md's deprecation marker) and are kept
for now — `regime_margin_pct` is SPY's raw (unrounded) % distance from
its 200-DMA, `null` when `regime` is `null`. `audit_7d` (7-day, or `--days N`,
`audit_log` outcome counts plus any `error:*` rows verbatim) and `last_trade`
span both bots' `audit_log`/`trades` rows, not just the retired one's. The
digest also carries the `bot_config.paused` flag and the Alpaca paper account
equity + open position (still on `BOT_TICKER`, the retired bot's symbol —
deferred to a later batch, see #536's non-goals). When `--days`/`?days=` is
supplied, the digest additionally carries `trades` and `regime_history` (see
above). See `supabase/functions/status/logic.ts` (`StatusDigest`) for the
exact shape — the function is strictly read-only and writes nothing, not even
its own `audit_log` row.

`last_runs` (#396) is always present alongside the above: the latest
`audit_log` row's `started_at`/`outcome` for each of `daily_check`,
`kill_switch`, and `hourly_check` (`null` if that script has never written a
row). This exists specifically so an external process can detect a stalled
`pg_cron` pipeline without having to page through `audit_7d` — see
`docs/runbooks/deadman-watchdog.md`.
