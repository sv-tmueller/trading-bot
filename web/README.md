# Trading Bot — read-only dashboard (#228, repointed at the hourly bot in #538)

A Next.js (App Router) status page for the hourly candlestick bot, reading
Supabase **server-side** with the service-role key. No controls — viewing only
(the panic kill button stays the token-auth Edge Function). Answers one
question: is the bot alive, and what did it just do — strategy-performance
analysis (R-multiples, detector hit rates, equity curves) is out of scope here;
`scripts/render_weekly_journal.ts` owns that weekly.

Shows: the latest `hourly_scans` bar's timestamp and decision, the open
position with its bracket levels (entry ref / stop / target, paired with the
position by symbol — a disclosed heuristic, since Alpaca positions carry no
back-reference to the order that opened them), the paused flag, equity against
the -15% floor, a recent-scans table (decision, detectors fired, skip reason
per bar), recent `hourly_*` `trades`, and recent `hourly-check` `audit_log`
runs — plus a **Holdings** panel (live Alpaca equity + open positions +
unrealized P&L) when Alpaca keys are configured (otherwise it shows a "not
connected" hint). The page also states how stale its newest scan is (a plain
age fact, plus a banner past a fixed 72h threshold) and notes when no scan has
ever been recorded, rather than letting either read as silent "all clear".
A tile on this page shows the latest daily-verification day and its verdict,
linking to `/daily` (see below); it is the one part of this page that is not
covered by the `force-dynamic` export above it: see "Daily verification
pages" for why.

## Daily verification pages (#548)

Two additional routes render the artifacts produced by
`scripts/daily_verify.ts` (#547) and committed to
`docs/trading-journal/` by `.github/workflows/daily-verification.yml` (#549):

- `/daily`: an index of verified days, newest first, each with its verdict
  badge and headline numbers, read from `docs/trading-journal/daily-verification.jsonl`.
- `/daily/[date]`: the rendered markdown digest for one day
  (`docs/trading-journal/daily/YYYY-MM-DD.md`), via `react-markdown` +
  `remark-gfm` (GitHub-flavored tables and task lists). HTML embedded in the
  markdown stays escaped, which is react-markdown's default, and neither
  route adds `rehype-raw` or any other raw-HTML plugin.

Both routes read `docs/trading-journal/` **at build time only**
(`generateStaticParams` plus a plain `fs` read in `web/lib/dailyJournal.ts`,
the sole owner of filesystem access for these artifacts): no runtime
filesystem access, no secrets, and `next build` in `web-ci.yml` still passes
with no environment variables set. `/daily/[date]` additionally sets
`dynamicParams = false`, so a date with no rendered digest 404s through
Next's own not-found handling instead of falling through to an on-demand,
request-time filesystem read. Before any digest exists (or once `#547`'s
ledger/digest files are absent for any other reason), both routes render an
explicit "No verified days yet" empty state rather than crashing or
fabricating a row.

**Known deployment risk with a documented fallback.** With Vercel's Root
Directory set to `web`, reading `../docs` at build time requires "Include
source files outside of the Root Directory" to be enabled in the Vercel
project settings; this cannot be verified by an agent (Vercel is behind SSO).
If a deploy shows an empty `/daily` despite committed artifacts, that setting
is the first thing to check. The fallback: `web/lib/dailyJournal.ts` prefers
`web/content/daily/` and `web/content/daily-verification.jsonl` (gitignored)
over `../docs/trading-journal/**`, and `web/scripts/copy-daily-artifacts.mjs`
(plain Node `fs`/`path`, no new dependency) copies the real artifacts into
`web/content/` when it runs. Activating it is exactly one `package.json`
line, no code changes:

```json
"scripts": {
  "prebuild": "node scripts/copy-daily-artifacts.mjs"
}
```

`web/` grows from 5 to 7 runtime dependencies for this: `react-markdown`
(renders the digest markdown) and `remark-gfm` (adds table/task-list support
to it).

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
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER` (optional) — keys for the Holdings panel.
- `DASHBOARD_BASIC_AUTH` (optional, **default-OFF**) — `user:pass` to gate the whole
  dashboard behind HTTP Basic auth (see "Go-live hardening" below).

All secrets are used only in server code (`middleware.ts`, `lib/supabase.ts`,
`lib/alpaca.ts`), so they are never sent to the browser. The lib modules
`import "server-only"`, so a stray client-side import is a build error rather
than a silent secret leak. Supabase tables are RLS-deny-all; the service-role
key bypasses RLS for these reads. The dashboard only issues GET requests to
Alpaca (`/v2/account` + `/v2/positions`) — no order placement — but note Alpaca
keys are **unscoped full-trading keys** (there is no read-only scope), so treat
them as trading credentials.

## Go-live hardening
Before pointing the dashboard at **live/prod** keys (URL secrecy is not access
control), turn on an auth gate — either Vercel Access Protection (password/SSO) or
the built-in HTTP Basic gate: set `DASHBOARD_BASIC_AUTH=user:pass`. When that env
var is **unset** (the default), `middleware.ts` passes every request through, so the
current open paper soak is unaffected; when set, every request must carry matching
Basic credentials or it gets a 401 (the credential check is constant-time over
SHA-256 digests — see `lib/auth.ts`). Security headers (`X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, a CSP, `Referrer-Policy`) are always on via
`next.config.mjs`.

Recommended: also enable **Vercel Deployment Protection** on the project for
defense in depth on top of Basic Auth.
