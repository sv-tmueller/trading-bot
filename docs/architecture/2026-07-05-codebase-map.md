# Codebase map — 2026-07-05

*A structural map of the repository: what each area is, how the areas fit together, and how data and dependencies move across them. This is a map, not a review — it describes what is there, without findings, severities, or recommendations.*

> **Provenance.** Produced by the `orchestrai:tm-map-codebase` workflow (Sonnet scout → 18 Sonnet area workers → synthesis). The scout split the repo into 18 areas; 16 area workers returned full maps. Two workers (Web dashboard, Python backtest research engine) returned placeholder output and were re-run before synthesis, so all 18 areas are covered. The final synthesis was written by the main session (Opus) rather than the pinned Fable critic, which hit a credit limit.

---

## 1. Executive summary

This repository is a **deterministic, single-rule trading bot** plus the research, operations, and documentation scaffolding around it. The production bot trades exactly one signal — **SPY's daily close versus its 200-day moving average (the Mebane Faber 200-DMA regime filter)**, modulated by an intraday kill-switch — and holds either a leveraged long position (`BOT_TICKER`, currently UPRO) or cash. The governing design constraint, stated as a hard architectural invariant, is that **no LLM sits anywhere in the trading path**: every trading decision is reproducible from the SPY price history alone. The only Claude sessions in the repo are the operator's development tooling, which never executes orders.

The live bot is **TypeScript on Deno**, deployed as three **Supabase Edge Functions** driven by `pg_cron`:

- **`daily-check`** — runs post-open on weekdays, computes the regime signal on the previous completed session's close, reconciles the desired LONG/CASH state against both the database and the broker's actual position, and places a single order if the state must flip.
- **`kill-switch`** — runs every 5 minutes during market hours, treats the live broker position as the source of truth, and liquidates if intraday drawdown from a rolling high breaches a configured threshold.
- **`panic`** — a manually-triggered, token-authenticated "kill button" (pause / resume / cancel-orders / liquidate) for the human operator.

All three compose a shared library of narrow, dependency-injected modules under `supabase/functions/_shared/` (broker client, market data, database, config/validation, notifications, the pure regime rule, numeric guards, auth). Persistence is **Supabase Postgres** (five tables, all RLS-deny-all, reached with the service-role key); scheduling and cron-authentication secrets live in **Postgres/pg_cron + Vault**, defined by an ordered set of idempotent SQL migrations. Operator alerts flow through a best-effort, non-blocking **n8n → Discord** webhook. A read-only **Next.js dashboard** (deployed separately on Vercel) renders the same database plus live Alpaca account data.

Alongside the live bot sits a substantial **Python 3.9 research engine** (`backtest/`, `strategy/regime.py`, `main.py`) — explicitly *not* the trading path. It backtests the incumbent rule and surveys alternatives (dual-momentum, Faber GTAA, vol-targeting, options credit spreads, a scalping cost-wall demonstration), with a walk-forward out-of-sample harness, an after-tax layer, and a synthetic leveraged-ETF model that extends history back to ~1990. `strategy/regime.py` is the canonical Python statement of the decision rule that the production `regime.ts` mirrors 1:1.

The remainder of the repo is process and memory: **`.claude/`** (repo-local subagents and skill playbooks), a large **`docs/`** tree (ADRs, runbooks, dated design specs and TDD plans, session handovers, a weekly trading journal, and a timestamped research archive), a single **CI workflow** that auto-deploys the Supabase side to the dev/paper project on merge to `main`, **operational shell scripts** (all legacy, from the pre-migration IBKR/Python era), and the **root config/docs** (README, CLAUDE.md, ROADMAP, `deno.json`, `requirements.txt`) that orient every human and agent session.

A recurring theme across the whole repo is **historical layering**: the project pivoted twice — first from an LLM-driven multi-agent bot (v1.14) to a single deterministic rule (2026-05-07), then from IBKR/SQLite/Python-cron to Alpaca/Supabase/pg_cron (MVP 2.0, #220). Several areas (operational scripts, the IBKR VPS ops doc, most handovers, some research bundles) still describe the retired architectures and are kept as record rather than removed.

---

## 2. Component table

| Area | Purpose | Key modules |
|---|---|---|
| **Supabase shared modules (`_shared`)** | Every piece of I/O, config, and pure logic the three Edge Functions share — each a narrow, injectable wrapper around one external concern, plus the mechanical "no-LLM" invariant test. | `regime.ts` (the one decision rule), `alpaca.ts` (guarded broker client), `marketdata.ts`, `db.ts`, `config.ts`, `notifications.ts`, `auth.ts`, `num.ts`, `supabase_client.ts`, `invariants.test.ts` |
| **`daily-check` Edge Function** | Once-per-trading-day decision cycle: fetch SPY history, compute the 200-DMA signal on the previous close, reconcile DB + broker state, flip LONG↔CASH if needed. | `logic.ts` (`runDailyCheck` pipeline), `handler.ts` (auth + real-deps wiring), `index.ts` (Deno.serve shim), `*.test.ts` |
| **`kill-switch` Edge Function** | Intraday circuit-breaker: liquidate the live UPRO position if drawdown from its rolling high breaches the threshold; broker position is source of truth. | `logic.ts` (`runKillSwitch`), `handler.ts`, `index.ts`, `*.test.ts` |
| **`panic` Edge Function** | Deterministic, token-authenticated operator kill button: pause / resume / cancel-orders / liquidate. | `logic.ts` (`runPanic`), `handler.ts` (POST-only, constant-time token check), `index.ts`, `*.test.ts` |
| **Supabase project config & migrations** | The Postgres schema, cron schedules, and CLI/local-dev config the functions run against. | `0001_init.sql` … `0008_trade_claims.sql`, `config.toml` |
| **Web dashboard** | Read-only Next.js status page for the hourly bot (latest scan bar/decision, open position with bracket levels, paused flag, equity vs the -15% floor, recent scans/trades/audit runs, Alpaca holdings); no controls. Deployed on Vercel, typechecked and built by `web-ci.yml`. | `app/page.tsx` (server-rendered), `lib/supabase.ts`, `lib/alpaca.ts` (GET-only), `lib/auth.ts` + `middleware.ts` (optional Basic auth), `next.config.mjs` |
| **Python backtest research engine** | Research-only offline backtester for the incumbent rule and a survey of alternatives; never runs in production. | `regime.py` (simulator + `simulate_from_signal`), `baselines.py`, `families.py`, `regime_signals.py`, `walkforward.py`, `tax.py`, `synthetic.py`, `options_pricing.py`, `options_data.py`, `pcs_riv.py`, `run_*.py` CLIs |
| **Python backtest tests** | Pytest suite validating the backtest engine and `strategy/regime.py`; run manually (not in CI). | `test_strategy_regime.py`, `test_backtest_regime.py`, `test_walkforward.py`, `test_tax.py`, `test_run_candidate_survey.py`, and ~11 more, one per module |
| **Production entrypoint & kept strategy module** | Thin CLI forwarding to the backtest tool, plus the canonical Python statement of the decision rule. | `main.py` (`backtest` subcommand), `strategy/regime.py` (`compute_target_state`) |
| **Claude agents, skills & settings** | Repo-local Claude Code config: subagents and skill playbooks that operationalize CLAUDE.md's rules. | `.claude/settings.json`, `agents/{analyst,docs,qa}.md`, `skills/{add-or-extend-agent,handover,research-bundle}/SKILL.md` |
| **Docs: decisions, runbooks & operations** | ADR log + operational procedures (deploy/decommission runbook, legacy IBKR VPS setup). | `decisions/README.md` + `TEMPLATE.md`, `runbooks/mvp2-deploy-and-decommission.md`, `operations/ibkr-vps-setup.md` |
| **Docs: plans & specs** | Dated design specs (brainstorm output) and TDD implementation plans consumed by the advisor→kickoff pipeline. | `docs/plans/*-{design,plan}.md`, `docs/superpowers/{specs,plans}/*.md` |
| **Docs: handover & trading journal** | Cold-start session handovers, and the weekly narrative log over live trading. | `handover/README.md` + dated handovers, `trading-journal/README.md` + `TEMPLATE.md` + `2026-W25.md` |
| **Docs: research** | Timestamped archive of research memos and 4-file research bundles feeding build-vs-skip decisions. | `README.md`, dated `*.md` notes, `swing-trading/` & `lstm-llm-trading-agents/` bundles, `v1.14-backtest-baseline/` |
| **Notifications workflow (n8n)** | The Discord notification channel: an n8n workflow that receives event payloads over HTTP and posts to Discord. | `n8n/trading-bot-discord-notifications.json` (Webhook node → Discord node) |
| **Root project config & docs** | Repo-level orientation and toolchain config sitting above all subsystems. | `README.md`, `CLAUDE.md`, `ROADMAP.md`, `NEW-PROJECT-SETUP.md`, `.env.example`, `deno.json`, `requirements.txt`, `.gitignore` |
| **Operational scripts** | Legacy shell scripts for VPS cron setup and CLI wrapping — all pre-migration IBKR/Python era, not exercised by the live bot. | `scripts/cron_setup.sh`, `run_scan.sh`, `run_monitor.sh` |
| **CI workflows** | Auto-deploy the Supabase side to the dev/paper project on merge to `main` touching `supabase/**`; prod is manual. | `.github/workflows/deploy-dev.yml` |

---

## 3. Data-flow narrative

**Production trading path (end to end).** `pg_cron` (defined in the migrations) fires an authenticated, empty-body HTTP POST at each scheduled time — the Authorization bearer is assembled inside Postgres from two Vault secrets. The request reaches an Edge Function's `index.ts` → `handler.ts`, which enforces service-role auth (or, for `panic`, a constant-time `x-panic-token` check) and builds a typed `deps` object wiring the real Alpaca client, Supabase service client, market-data functions, and notification helpers. That `deps` object is handed to the function's pure `logic.ts` pipeline.

Inside the pipeline, all inputs are pulled from external state at run time (never from the request body):

1. **Config** (`config.ts`) supplies validated strategy knobs (`REGIME_SMA_DAYS`, `KILL_SWITCH_*`, `BOT_TICKER`, credentials).
2. **Market data** (`marketdata.ts`) supplies SPY/UPRO daily bars, latest trade price, and latest quote from Alpaca's Market Data REST.
3. **Broker state** (`alpaca.ts`) supplies the market clock and the live position from Alpaca's Trading REST.
4. **DB state** (`db.ts`) supplies the latest `regime_state` row and the `bot_config.paused` flag from Postgres.

These numbers pass through **`num.requireNumber`** at every JSON→number boundary (so a malformed field throws rather than silently becoming 0) and then through **`regime.computeTargetState`** — the single, I/O-free decision rule — to derive the target state. `daily-check` reconciles that target first against the DB's recorded state and, if the broker disagrees, recomputes against the broker-derived state (raising a `state_desync` notification). `kill-switch` computes a rolling-high drawdown against the live position and, on a breach, additionally confirms against the latest quote before firing.

If a flip is warranted, the function takes an atomic **per-trading-day claim** (`trade_claims` table — first INSERT wins; concurrent runs get a unique-violation and back off), reads account value to size the order, places a market order or liquidation via the **guarded** `alpaca.ts` helpers, writes the resulting fill to the `trades` table, upserts the new `regime_state` row, and fires a structured notification. Every invocation opens an `audit_log` row before any side effect and closes it in a `finally` with a deterministic outcome string (`success`, `success:*`, `skipped:*`, `error:*`) — so a crashed run still leaves a recoverable row. The HTTP response carries only `{outcome}` (or `{result}` for panic) for the caller to log.

**Notifications (fan-out, non-blocking).** `notifications.ts` builds an `event_type`-tagged JSON payload plus a rendered `message` string and fires a single `fetch` POST to the n8n webhook. The n8n **Webhook node** acknowledges immediately (`onReceived`) and the **Discord node** posts `$json.body.message`. The bot never reads the response; any failure is swallowed so a notification outage cannot crash trading. No data flows back.

**Dashboard (read-only).** On each request, `web/app/page.tsx` runs six Supabase reads (`hourly_scans` twice — a recent list and a dedicated latest-entered-scan lookup for bracket levels — plus `bot_config`, `trades`, `audit_log`) and two Alpaca GETs (`/v2/account`, `/v2/positions`) concurrently, coerces PostgREST string-numerics and Alpaca values to numbers, and renders stat tiles and tables. `force-dynamic` disables caching; a human reloads to refresh. Nothing is written.

**Research path (offline, separate).** External market data (yfinance for equities/indices/`^IRX`/`^VIX`; Bybit public REST for BTC; optionally Alpaca's *read-only* historical data for option marks) is fetched by small per-module `_fetch` seams → aligned into daily Series/DataFrames → a signal builder (`baselines.py` / `families.py` / `regime_signals.py`, or an inline SMA) produces a boolean/NaN signal or a target-weight frame → `simulate_from_signal` shifts the signal one day and executes at the next open with slippage+commission, yielding an equity curve, trade ledger, and metrics → optional `tax.py` (after-tax deduction at each exit) and window-slicing harnesses (`walkforward.py`, `run_candidate_survey.py`, `run_leveraged_regime_study.py`) recompute CAGR/Sharpe/Calmar per out-of-sample window → the `run_*.py` CLIs print tables/verdicts and, in one case, a matplotlib PNG. This path writes to `docs/research/`, never to Postgres, Alpaca order endpoints, or any live-bot table.

**Provenance / knowledge flow (docs).** Research verdicts feed `docs/decisions/` ADRs and `docs/plans/` specs; specs become TDD plans; plans drive developer/tester/reviewer subagents; handovers freeze session state for cold resumption; the trading journal summarizes live `audit_log`/`trades` rows weekly. The database remains authoritative throughout — docs are the interpretive layer.

**Schema/deploy flow (one-directional).** Committed `.sql` migrations apply via `supabase db push` in numeric order (idempotent) to whichever project (dev or prod) — same files, different Vault values. CI (`deploy-dev.yml`) ships functions-then-migrations to the dev/paper project on merge to `main`; prod remains a manual runbook step.

---

## 4. Dependency summary

### External dependencies (packages & services)

- **Alpaca** — Trading REST v2 (broker: clock, account, position, orders, liquidate) and Market Data REST v2 (daily bars, trades, quotes). Reached by `_shared/alpaca.ts` + `marketdata.ts` (production), the dashboard's `lib/alpaca.ts` (read-only GET), and the research engine's `options_data.py` (read-only historical data). Paper vs live is selected by config; dev/test use paper keys.
- **Supabase** — Postgres (five app tables: `regime_state`, `trades`, `audit_log`, `bot_config`, `trade_claims`, all RLS-deny-all), Vault (`service_role_key`, `functions_base_url`), Edge Functions runtime, and the CLI. Client: `jsr:@supabase/supabase-js@^2.45.0`.
- **pg_cron / pg_net** — in-database scheduling and outbound HTTP that trigger `daily-check` and `kill-switch`.
- **n8n → Discord** — external webhook workflow for operator alerts (`N8N_WEBHOOK_URL`); must be reachable from Supabase's cloud.
- **Deno** — runtime for all production TS; `deno.json` pins `@std/assert` and `@supabase/supabase-js` from JSR and defines the `test` / `test:db` / `fmt` / `lint` tasks (the `test` task sets `CLAUDE_AGENT_NO_BROKER=1`).
- **Next.js 15 / React 19 / Tailwind 3 / `server-only`** — the dashboard, deployed on **Vercel** (independent of the Supabase deploy).
- **Python 3.9 stack** (`requirements.txt`) — `pandas 2.2.3`, `numpy`, `yfinance`, `pytest` + `pytest-mock`, `matplotlib`, `requests`, `ta`. Options pricing uses stdlib `math` only (no scipy). One-off external: **Bybit** public REST (scalping cost-wall demo).
- **GitHub Actions** — `actions/checkout@v5`, `supabase/setup-cli@v2.1.1`; repo secrets `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD`.
- **`obra/superpowers` + `orchestrai` Claude Code plugins** — the canonical workflow playbooks (brainstorming, writing-plans, subagent-driven-development, TDD, systematic-debugging, etc.) and the `/tm-advisor` → `/tm-kickoff` operating model.
- **Legacy / retired** — Interactive Brokers Gateway + IBC + `ib_insync` + systemd (documented in `docs/operations/`, referenced by the legacy `scripts/`), and SQLite — all superseded by the Alpaca/Supabase migration and kept only as record.

### Cross-area dependencies

- **`_shared` is the hub.** `daily-check`, `kill-switch`, and `panic` each depend on it for the decision rule, broker, market data, DB, config, auth, and notifications; they own only their own `deps`-injection wiring and HTTP entry.
- **Migrations underpin the functions.** All three functions read/write tables defined in `supabase/migrations/`; `trade_claims` (0008) backs the concurrency guard; cron migrations (0002/0004/0006) drive the function triggers.
- **`regime.ts` ↔ `strategy/regime.py`.** The production rule is a 1:1 port of the kept Python module; the Python backtest tests are the pre-port correctness reference. `backtest/pcs_riv.py` imports `strategy.regime.compute_target_state` directly.
- **`main.py` → `backtest/`.** The CLI forwards to `backtest.regime.main_cli`; otherwise the research engine is never imported by `supabase/functions/`.
- **Dashboard → migrations' schema.** `web/` reads `hourly_scans`, `bot_config`, `trades`, and `audit_log` via its own (separate) Supabase and Alpaca clients — no shared code with `_shared`.
- **n8n ← `notifications.ts`.** The webhook path (`trading-bot-notify`) and the `event_type` + `message` payload contract are a stable interface between the two areas.
- **CI → functions + migrations.** `deploy-dev.yml` deploys both, functions-first by design.
- **Docs & `.claude/` reference, never restate, CLAUDE.md.** The Architectural invariants section is the single source of truth; every agent `.md`, skill, plan, and handover links to it. Research memos cite the `backtest/` scripts that reproduce their numbers; plans/specs quote exact file paths in the code areas they target.

---

## 5. Open questions

Items the area workers could not determine from the code alone, or that a human should confirm:

- **Legacy scripts and ops docs are live in the tree but describe retired systems.** `scripts/cron_setup.sh`, `run_scan.sh`, `run_monitor.sh` invoke `main.py scan`/`monitor` and `daily_check.py` / `monitor.kill_switch` entry points that no longer exist; `docs/operations/ibkr-vps-setup.md` documents the IBKR/systemd stack. They are unmarked as superseded. *(Confirm whether these are retained deliberately as history or are stale.)*
- **The Python backtest suite is not run by CI.** `deploy-dev.yml` only deploys `supabase/**`; the pytest suite (`tests/`) is run manually. No single canonical command for it is documented in README/CLAUDE.md (which cover only `deno task test`). *(Confirm the intended invocation and whether it should gate anything.)*
- **`.env.example` and `config.ts` are kept in sync by convention, not tooling.** The documented variable names mirror what the code reads, but nothing enforces the match. *(Human check on drift.)*
- **README and CLAUDE.md deliberately restate overlapping architecture facts** (cron schedules, schema, notification types) at different detail levels; only the Architectural invariants section is a single source of truth. *(Keeping the two in sync is a manual discipline.)*
- **`trading-journal/` has no orchestrating skill yet** — only a README, template, and one entry (dev/paper account). Cadence ("write after Friday close") is calendar-triggered by a human, not automated.
- **`notifications.ts` sends a typed `event_type` the n8n flow does not route on** — the Discord node renders only `message`; all other payload fields are received but unused by the current workflow. *(Confirm whether routing/branching is intended future work.)*
- **Cron fires unconditionally regardless of market state** — the open/closed and holiday gating lives entirely in the Edge Functions (clock gate / stale-data guard), not in the cron predicate. This is by design; noted here because it is not visible from the schedule alone.
- **Two of the original 18 area workers returned placeholder output** (Web dashboard, Python backtest research engine) and were re-mapped before synthesis; the two recovered maps were produced by separate Sonnet agents and are consistent with the code but were not part of the single original workflow run.
