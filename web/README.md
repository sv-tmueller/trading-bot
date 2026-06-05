# Trading Bot — read-only dashboard (#228)

A Next.js (App Router) status page for the deterministic regime bot, reading
Supabase **server-side** with the service-role key. No controls — viewing only
(the panic kill button stays the token-auth Edge Function).

Shows: current position (LONG/CASH), regime (SPY vs 200-DMA), drawdown,
kill-switch flag, paused banner, recent `trades`, and recent `audit_log` runs —
plus a **Holdings** panel (live Alpaca equity + open positions + unrealized P&L)
when read-only Alpaca keys are configured (otherwise it shows a "not connected" hint).

## Run locally
```bash
cd web
cp .env.example .env.local   # fill SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (dev project)
npm install
npm run dev                  # http://localhost:3000
```

## Deploy (Vercel)
Create a Vercel project with **Root Directory = `web`**, framework auto-detected
(Next.js). In Vercel → Settings → Environment Variables, set:
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (required) — point at **dev** during the soak, **prod** at go-live.
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER` (optional) — read-only keys for the Holdings panel.

All secrets are used only in server code (`lib/supabase.ts`, `lib/alpaca.ts`), so
they are never sent to the browser. Supabase tables are RLS-deny-all; the
service-role key bypasses RLS for these reads. Alpaca access is read-only (GET
`/v2/account` + `/v2/positions`) — no order placement.
