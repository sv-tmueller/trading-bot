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
