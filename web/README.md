# Trading Bot — read-only dashboard (#228)

A Next.js (App Router) status page for the deterministic regime bot, reading
Supabase **server-side** with the service-role key. No controls — viewing only
(the panic kill button stays the token-auth Edge Function).

Shows: current position (LONG/CASH), regime (SPY vs 200-DMA), drawdown,
kill-switch flag, paused banner, recent `trades`, and recent `audit_log` runs —
plus a **Holdings** panel (live Alpaca equity + open positions + unrealized P&L)
when read-only Alpaca keys are configured (otherwise it shows a "not connected" hint).

## Auth

The dashboard is protected by HTTP Basic Auth (`middleware.ts`), required since
it shows live account equity, positions, and kill-switch state. Credentials come
from the server-side env vars `DASHBOARD_USER` and `DASHBOARD_PASSWORD`. The
middleware **fails closed**: if `DASHBOARD_PASSWORD` is unset, every request
gets a 503 ("dashboard auth not configured") instead of data. Only Next.js
static assets (`_next/static`, `_next/image`, favicon) bypass the check.

On Vercel, additionally enable **Deployment Protection** (Settings →
Deployment Protection) as a second layer in front of Basic Auth.

## Run locally
```bash
cd web
cp .env.example .env.local   # fill DASHBOARD_USER/PASSWORD + SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (dev project)
npm install
npm run dev                  # http://localhost:3000
```

## Deploy (Vercel)
Create a Vercel project with **Root Directory = `web`**, framework auto-detected
(Next.js). In Vercel → Settings → Environment Variables, set:
- `DASHBOARD_USER`, `DASHBOARD_PASSWORD` (required) — Basic Auth credentials; without them the dashboard serves 503s (fails closed).
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (required) — point at **dev** during the soak, **prod** at go-live.
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER` (optional) — keys for the Holdings panel.

All secrets are used only in server code (`middleware.ts`, `lib/supabase.ts`,
`lib/alpaca.ts`), so they are never sent to the browser. Supabase tables are
RLS-deny-all; the service-role key bypasses RLS for these reads. The dashboard
only issues GET requests to Alpaca (`/v2/account` + `/v2/positions`) — no order
placement — but note Alpaca keys are **unscoped full-trading keys** (there is no
read-only scope), so treat them as trading credentials.

Recommended: also enable **Vercel Deployment Protection** on the project for
defense in depth on top of Basic Auth.
