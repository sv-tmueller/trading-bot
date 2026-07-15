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

When `jq` is available and the digest has a `regime` row with a non-null
`regime_margin_pct` (SPY's raw % distance from its 200-DMA, positive above /
negative below), `scripts/status.sh` prints a one-line "why" summary above
the raw JSON dump — e.g. `LONG \`UPRO\` because SPY is 7.2% above its
200-DMA.` (or `CASH because SPY is 4.3% below its 200-DMA.` with no ticker
when `current_state` is `CASH`) — built from `alpaca.position.symbol` and
`regime.current_state`. It's skipped when `regime` or `regime_margin_pct` is
`null`. The weekly `scripts/render_soak_digest.sh` markdown report renders
the same headline plus a signed, 1-decimal `SPY vs 200-DMA` line in the
`### Regime` section.

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

## Automated weekly soak digest (GitHub Actions)

`.github/workflows/soak-digest.yml` ("soak-digest") automates the manual
check above: once a week it fetches the digest and posts a rendered markdown
summary as a comment on the paper-soak tracking issue, replacing "watch the
SQL editor by hand."

- **Schedule:** Friday 21:30 UTC (after the US close in both EDT and EST;
  GitHub schedule jitter of a few minutes to about an hour is expected).
- **Manual dispatch:** trigger the workflow from the Actions tab with an
  optional `issue_number` input (defaults to `229`) — useful for testing
  against a scratch issue before it lands on the real tracking issue.
- **Target issue:** #229 by default.
- **Rendering:** the workflow shells out to the committed
  `scripts/render_soak_digest.sh`, which validates the digest JSON (garbled,
  partial, truncated, or missing/mistyped keys all fail the render step) and
  renders regime state, 7-day outcome counts, `error:*` rows verbatim, the
  last trade, and Alpaca equity/position, plus the raw JSON in a collapsed
  `<details>` block. It targets the current no-param `StatusDigest` shape
  in `supabase/functions/status/logic.ts` — no `?days=` parameter.
- **Required repo secrets** (Settings -> Secrets and variables -> Actions,
  same values as your local `.env.status`):
  - `STATUS_URL`
  - `STATUS_TOKEN` (read-only by design)
- **Failure contract:** unlike `backup-db.yml`, this workflow does **not**
  skip inertly when secrets are missing — it fails loudly (`::error::`),
  because a red run is itself soak signal. Any endpoint failure (401, 5xx,
  timeout, unreachable) or garbled/invalid JSON also fails the run before the
  comment step runs, so nothing is posted on failure. Re-run via manual
  dispatch once the underlying issue (missing secret, endpoint down, etc.)
  is fixed.

## Heartbeat (GitHub Actions)

`.github/workflows/heartbeat.yml` ("heartbeat") exists for a different reason
than soak-digest: Supabase's free-tier inactivity/pause criterion is based on
user-facing API traffic, and `pg_cron` invocations of `daily-check` /
`kill-switch` do **not** count toward it — a project can be paused for
inactivity even while the trading cron runs continuously. Dev received such a
warning on 2026-07-12 (see the Addendum in
`docs/decisions/2026-07-07-supabase-row-data-backup.md`). A paused project
silently stops protecting an open position, since the kill-switch can't fire
if the project itself is paused. This workflow pings the `status` function on
a schedule so the project sees real gateway traffic and stays active.

- **Schedule:** weekdays 12:23 UTC, plus manual `workflow_dispatch`.
- **Two independent targets, one job:**
  - **dev** — gated on the same `STATUS_URL`/`STATUS_TOKEN` repo secrets as
    soak-digest (deliberate reuse, not new `_DEV`-suffixed secrets — see the
    sub-plan on #361). Already active as of this workflow merging.
  - **prod** — gated on `STATUS_URL_PROD`/`STATUS_TOKEN_PROD`, which are unset
    today (prod is not yet deployed). Prod stays subject to inactivity
    warnings/manual restore until go-live (#230); setting these two secrets
    at go-live activates the prod step with no code change (see
    `docs/runbooks/mvp2-deploy-and-decommission.md`).
- **Failure contract — inert skip vs red run:** unlike soak-digest, missing
  secrets for a target make that target's steps an **inert green skip**
  (`::notice::`, no request made) — matching `backup-db.yml`'s default-OFF
  idiom, since this workflow is meant to be safe to merge into forks or
  before secrets exist. Once a target's two secrets are both set, a non-200
  response or a timeout from that target **fails the run red** (same
  `curl --fail-with-body --max-time 60` idiom as soak-digest). The dev and
  prod steps are independent — a red prod run (post go-live) doesn't block
  dev's ping, and vice versa.
- **GitHub's 60-day auto-disable caveat:** GitHub automatically disables a
  scheduled workflow after 60 days with no repository activity at all. This
  repo has weekly commits from `backup-db.yml` alone, so this is a low but
  non-zero residual risk — if it ever fires, both `heartbeat.yml` and
  `backup-db.yml` stop running silently (no notification), and re-enabling
  requires a manual visit to the Actions tab.

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

Latest regime state (date, target/current state, drawdown %, kill-switch
flag), a top-level `regime_margin_pct` — SPY's raw (unrounded) % distance
from its 200-DMA, `null` when `regime` is `null` — 7-day (or `--days N`)
`audit_log` outcome counts plus any `error:*` rows verbatim, the last trade,
the `bot_config.paused` flag, and the Alpaca paper account equity + open
position. When `--days`/`?days=` is supplied, the digest additionally
carries `trades` and `regime_history` (see above). See
`supabase/functions/status/logic.ts` (`StatusDigest`) for the exact shape —
the function is strictly read-only and writes nothing, not even its own
`audit_log` row.
