# Discord Notifications Runbook

One-time setup for direct-to-Discord notifications (#362). `notifications.ts`
posts every event (`regime_flip`, `kill_switch_fired`, `trade_failed`,
`state_desync`, `broker_error`, `panic`, `error`) straight to a Discord
incoming webhook — no n8n or other forwarder in between. This replaces the
earlier n8n-forwarded setup (#227/#232 history); there is no operator step
that survives from that setup other than "have a webhook URL".

## One-time setup (per Supabase project)

1. In Discord, create (or reuse) the channel you want alerts in, then:
   **Channel Settings → Integrations → Webhooks → New Webhook.** Name it
   (e.g. "Trading Bot"), copy the **Webhook URL**.
2. Set the secret on the Supabase project (read at runtime — no redeploy
   needed):
   ```bash
   supabase secrets set NOTIFY_WEBHOOK_URL=<the webhook URL>
   ```
3. Verify directly against Discord's webhook API (bypasses the bot entirely —
   this only proves the webhook itself is live):
   ```bash
   curl -i -X POST "<the webhook URL>" \
     -H "content-type: application/json" \
     -d '{"content":"test"}'
   ```
   A `204 No Content` response and a "test" message appearing in the channel
   confirms the webhook works. A `401`/`404` means the webhook URL is wrong or
   was deleted in Discord.

## Unset = silent skip

If `NOTIFY_WEBHOOK_URL` is unset or blank, `notify()` returns immediately
without calling `fetch` at all — no error, no log, the bot keeps trading.
This is intentional (notifications are best-effort) and is why the dev
project can soak with the secret intentionally left unset (see
`docs/CURRENT_CONFIG.md`).

## What gets posted

Every payload carries the existing structured JSON fields (`event_type` +
event-specific fields, plus a full-length `message`) **and** a Discord-native
`content` field — `message`, codepoint-safe-truncated to Discord's
2,000-character hard limit — that Discord renders directly as the message
text. The structured fields are unused by Discord itself but are kept for any
future JSON-consuming forwarder.

## Troubleshooting

- **No messages arriving, no errors anywhere** — expected if
  `NOTIFY_WEBHOOK_URL` is unset (silent skip by design). Confirm with
  `supabase secrets list` (value is masked, but presence is visible) or by
  checking `docs/CURRENT_CONFIG.md`.
- **Webhook curl in step 3 returns 401/404** — the webhook was deleted or the
  URL was mistyped when set via `supabase secrets set`; recreate it in
  Discord (step 1) and re-set the secret.
- **Webhook reachable but the bot never posts** — the webhook must be
  reachable from Supabase's cloud (it is — Discord's API is public), but
  double-check the secret name is exactly `NOTIFY_WEBHOOK_URL` (the legacy
  `N8N_WEBHOOK_URL` name is not honored, see #362).

See also
[`docs/runbooks/mvp2-deploy-and-decommission.md`](mvp2-deploy-and-decommission.md)
for where this fits in the full deploy sequence.
