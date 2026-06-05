# Trading Bot — read-only dashboard (#228)

A Next.js (App Router) status page for the deterministic regime bot, reading
Supabase **server-side** with the service-role key. No controls — viewing only
(the panic kill button stays the token-auth Edge Function).

Shows: current position (LONG/CASH), regime (SPY vs 200-DMA), drawdown,
kill-switch flag, paused banner, recent `trades`, and recent `audit_log` runs.

## Run locally
```bash
cd web
cp .env.example .env.local   # fill SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (dev project)
npm install
npm run dev                  # http://localhost:3000
```

## Deploy (Vercel)
Create a Vercel project with **Root Directory = `web`**, framework auto-detected
(Next.js). Set the two env vars (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) in
Vercel → Settings → Environment Variables. Point at the **dev** project during
the soak; switch to **prod** at go-live.

The service-role key is only used in server components (`lib/supabase.ts`), so it
is never sent to the browser. Tables are RLS-deny-all; the service-role key
bypasses RLS for these reads.
