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
```

Renders the JSON digest via `jq` (falls back to raw output with a warning if
`jq` is not installed). Exits non-zero if `.env.status` is missing, either
value is unset, or the HTTP request fails.

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

## Troubleshooting

- **401 Unauthorized** — token problem: either `STATUS_TOKEN` is unset/blank
  server-side (fails closed by design), or `.env.status`'s `STATUS_TOKEN`
  doesn't match what was set with `supabase secrets set`. Re-check both sides.
- **500** — function-side failure (e.g. Alpaca or DB read failed). The JSON
  body carries `{ "error": "…" }` with the underlying message; check the
  Supabase function logs for the full stack.
- **curl: connection failed / could not resolve host** — check `STATUS_URL`
  matches the deployed project ref and that `status` was actually deployed
  (step 3 above).

## What the digest contains

Latest regime state (date, target/current state, drawdown %, kill-switch
flag), 7-day `audit_log` outcome counts plus any `error:*` rows verbatim, the
last trade, the `bot_config.paused` flag, and the Alpaca paper account equity
+ open position. See `supabase/functions/status/logic.ts` (`StatusDigest`) for
the exact shape — the function is strictly read-only and writes nothing, not
even its own `audit_log` row.
