**Date:** 2026-06-05 (UTC)
**Slug:** mvp2-migration-execution
**Author:** Claude Code session (claude-opus-4-8)
**Status:** ✅ Built, reviewed, **deployed to dev/paper, and soaking autonomously.**

## 1. Sit-rep

MVP 2.0 (#220) is **done and live on paper.** The deterministic 200-DMA equity bot was migrated from Python/IBKR/SQLite/host-cron to **TypeScript on Supabase (pg_cron + Edge Functions + Postgres) + Alpaca**, built brainstorm→spec→3 plans→subagent-driven execution (engineer + spec-review + code-quality review per task + a final holistic review), then **deployed to the `trading-bot-dev` Supabase project and verified end-to-end against the Alpaca paper account.** The old Python/IBKR bot is untouched and still the production system until the live cutover. Branch `feat/220-mvp2-migration-design`, draft **PR #226**.

## 2. Supabase projects (EU/Frankfurt)

- **dev / paper:** `trading-bot-dev` — ref **`qdaxxsuicyiscdvsdowc`** — schema + cron applied, 3 functions deployed, secrets + Vault set, **currently soaking on paper.**
- **prod / live:** `trading-bot` — ref **`yomamlrozydhgleumnon`** — **nothing deployed yet** (the go-live target).

## 3. What's verified on dev (2026-06-05 ~18:45 UTC)

From `audit_log`:
- `daily-check` → `success` (`target=LONG current=LONG`) — flipped to LONG, paper UPRO buy.
- `kill-switch` → `success:within_threshold` (`dd=-0.0805`) — fired **autonomously via cron**, correctly no-op (proves cron → Vault-auth → function works on its own).
- `panic` → 401 on missing/wrong token; `pause`→`resume` works (ended resumed). Auth fail-closed.
- `deno task test` → 69 passed / 4 ignored (db integration tests; they need a local Postgres). `db push` to dev applied `0001`+`0002` cleanly = the schema/cron verification.

## 4. How it's wired (deploy specifics)

- Secrets (`supabase secrets set` on dev): `ALPACA_API_KEY/SECRET`, `ALPACA_PAPER=true`, `PANIC_TOKEN`, `BOT_TICKER=UPRO`, `BOT_BENCHMARK=SPY`. **N8N_WEBHOOK_URL intentionally omitted** (see §6).
- Vault secrets (dev SQL editor, one-time per project): `service_role_key` and `functions_base_url` = `https://qdaxxsuicyiscdvsdowc.supabase.co/functions/v1`. The cron in `0002_schedule.sql` reads both via `_service_role_key()` / `_functions_base_url()` — so the **same committed migration works for dev and prod**; only the Vault secrets differ.
- `daily-check`/`kill-switch` deployed JWT-verified (cron sends the service-role bearer); `panic` deployed `--no-verify-jwt` (auth = `x-panic-token` header).
- Cron (live on dev now): `daily-check` `30 22 * * 1-5` UTC; `kill-switch` `*/5 13-21 * * 1-5` UTC.

## 5. Deploy gotchas hit + fixed (so prod go-live is smooth)

- `supabase login` is non-TTY here → use `supabase login --token <PAT>` (PAT from dashboard → Account → Access Tokens).
- The Edge **deploy bundler does NOT apply the root `deno.json` import map** → `@supabase/supabase-js` must be a full `jsr:` specifier in deployed code (`supabase_client.ts`, `db.ts`). Done. (Test files can keep the bare specifier via the map.)
- `PROJECT_REF` placeholder in the cron migration was replaced by the Vault `functions_base_url` approach (no per-project file edit).
- There is **no `supabase functions invoke`** in this CLI — invoke deployed functions via `curl` with a Bearer JWT (anon key works for the JWT-verified ones).

## 6. Remaining (in priority order)

1. **Soak ~1 week** on paper — watch `audit_log` for sane daily flips + 5-min kill-switch ticks.
2. **(Optional) Discord:** add `N8N_WEBHOOK_URL` once the n8n webhook is publicly reachable. NOTE: the old `http://localhost:5678` URL **won't work** from Supabase's cloud; needs a public URL + a Cloudflare-Access **bypass** for the `/webhook/...` path (our `notifications.ts` sends no auth header). Notifications are best-effort, so the bot runs fine without it. Then `supabase secrets set N8N_WEBHOOK_URL=...` (no redeploy needed).
3. **Go live (prod `trading-bot` / `yomamlrozydhgleumnon`):** `supabase link --project-ref yomamlrozydhgleumnon` → `supabase secrets set ... ALPACA_PAPER=false` (LIVE keys) → set the two Vault secrets in prod's SQL editor (with prod's `functions_base_url`) → `supabase db push` → `supabase functions deploy daily-check kill-switch` + `panic --no-verify-jwt`. Watch the first live run.
4. **Mark PR #226 ready / merge** after a clean soak.
5. **Decommission** the old Python/IBKR bot: stop host cron, shut IBKR Gateway/VPS, archive `trading_bot.db`, tag `v1.0`, remove the Python production modules (keep `backtest/`). See `docs/runbooks/mvp2-deploy-and-decommission.md`.

## 7. Security follow-ups (low-risk, in transcript)

- The Supabase **access token** (`sbp_…`) and the project **anon key** were printed in the session transcript. Anon key is public-by-design and RLS (enabled, no policies) blocks all table access, so impact is minimal; rotate the PAT (dashboard) if desired. The **service-role key and panic token were NOT exposed** (panic token was reset by the user during testing).

## 8. Key files

Spec: `docs/superpowers/specs/2026-06-05-mvp2-infra-migration-design.md` · Plans: `docs/plans/2026-06-05-mvp2-infra-migration-plan-{1,2,3}-*.md` (with post-review/deploy amendment notes) · Runbook: `docs/runbooks/mvp2-deploy-and-decommission.md` · App: `supabase/`.

## 9. Suggested next prompt

`The MVP 2.0 paper soak on Supabase dev (qdaxxsuicyiscdvsdowc) looks clean — let's go live: link prod (trading-bot / yomamlrozydhgleumnon), set live Alpaca keys + ALPACA_PAPER=false + the two Vault secrets, db push, deploy the 3 functions, then mark PR #226 ready and decommission the old IBKR bot.`
