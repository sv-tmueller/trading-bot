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
flag), 7-day (or `--days N`) `audit_log` outcome counts plus any `error:*`
rows verbatim, the last trade, the `bot_config.paused` flag, and the Alpaca
paper account equity + open position. When `--days`/`?days=` is supplied, the
digest additionally carries `trades` and `regime_history` (see above). See
`supabase/functions/status/logic.ts` (`StatusDigest`) for the exact shape —
the function is strictly read-only and writes nothing, not even its own
`audit_log` row.
