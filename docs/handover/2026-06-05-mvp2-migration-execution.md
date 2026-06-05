**Date:** 2026-06-05 (UTC)
**Slug:** mvp2-migration-execution
**Author:** Claude Code session (claude-opus-4-8)

## 1. Sit-rep

Picked up #220 (MVP 2.0) post-pivot and took it from open-questions → **brainstorm → spec → 3 implementation plans → partial execution**. The bot is being migrated from Python/IBKR/SQLite/host-cron to **TypeScript on Supabase (pg_cron + Edge Functions + Postgres) + Alpaca**, deterministic strategy unchanged, **no LLM in the trade path**. Execution is **subagent-driven** (engineer + spec-reviewer + code-quality-reviewer per task). Stopped mid-Plan-2 at the user's session limit. **Production Python bot untouched.** All work is on branch `feat/220-mvp2-migration-design` (off `main` @ `449bee0`).

## 2. Decisions locked (brainstorm 2026-06-05)

Full record in the spec. Quick table:
- **Scope:** core deterministic bot only; LLM read-only advisor = separate later spec.
- **Language:** TypeScript (Deno).
- **Vehicle:** **UPRO** (3× S&P) replaces `WSPL.DE` (Alpaca is US-listed-only); benchmark stays SPY.
- **Stack:** Supabase-only (pg_cron + Edge Functions + Postgres) + Alpaca REST; n8n→Discord unchanged. **No Vercel.**
- **Market data:** Alpaca data API (IEX feed), drop yfinance.
- **Kill-switch:** every **5 min** intraday, last-trade price vs rolling high incl. today.
- **Panic:** token-auth `panic` Edge Function; pause flag → `bot_config` DB row.
- **PR #93:** not reusable (Python).
- **Account currency:** USD (Alpaca), was EUR (IBKR).
- **No dry-run mode:** the paper account *is* the soak (Plan 3 decision).

## 3. Key files

- **Spec:** `docs/superpowers/specs/2026-06-05-mvp2-infra-migration-design.md` (approved).
- **Plans:** `docs/plans/2026-06-05-mvp2-infra-migration-plan-1-foundation.md`, `-plan-2-io-modules.md`, `-plan-3-functions-rollout.md`. Plans are the source of truth and were kept in sync with review-driven fixes (with one noted post-review amendment in Plan 2 Task 2).
- **Code so far:** `supabase/` (config.toml, migrations/0001_init.sql, functions/_shared/{config,regime,notifications,test_helpers}.ts + tests), `deno.json`.
- **Handover PR #225** (separate, draft) holds the *previous* session's handover — unrelated to this branch.

## 4. Execution status (15 tasks total)

**Plan 1 — Foundation: ✅ COMPLETE**
- P1-T1 scaffold (deno 2.8.2 via brew, supabase init, deno.json) ✅
- P1-T2 schema `0001_init.sql` ✅ (apply/verify **deferred — Docker**)
- P1-T3 config.ts (getStrategyConfig + validation) ✅
- P1-T4 regime.ts (1:1 pure port) ✅

**Plan 2 — I/O modules: 2 of 5 done**
- P2-T1 config accessors (getAlpacaConfig/getN8nWebhookUrl/isClaudeAgentNoBroker) ✅
- P2-T2 notifications.ts + test_helpers.ts ✅
- **P2-T3 alpaca.ts (broker client + CLAUDE_AGENT_NO_BROKER guard) — NEXT**
- P2-T4 marketdata.ts — pending
- P2-T5 db.ts — pending (its `deno task test:db` integration tests need **Docker — deferred**)

**Plan 3 — Functions + rollout: 0 of 6 done** (P3-T0 service client, P3-T1 daily-check, P3-T2 kill-switch, P3-T3 panic, P3-T4 pg_cron SQL [verify deferred — Docker], P3-T5 runbook).

Current test state: **`deno task test` → 31 passed / 0 failed.**

## 5. Deferred — Docker unavailable this session (user approved deferring)

Docker isn't installed; needed for these (do them once Docker is up, e.g. `brew install colima docker && colima start`, or Docker Desktop):
1. **Plan 1 T2 Steps 2–3:** `supabase start` → `supabase db reset` → psql CHECK-constraint verification of `0001_init.sql`.
2. **Plan 2 T5:** `deno task test:db` (db.ts integration tests vs local Postgres) — after db.ts exists.
3. **Plan 3 T4 Step 2:** verify the two `pg_cron` jobs register (`select * from cron.job`).

Everything else (all TS modules + unit tests, the SQL files) is Docker-independent and is what's being built now.

## 6. How to resume

Next action: **dispatch the P2-T3 engineer** (alpaca.ts) following the subagent-driven loop already in motion. Pattern used:
1. Dispatch `engineer` (model sonnet) — point it at the exact task in the plan file, give scene + env notes (deno installed; Docker not needed for unit tests; never run pytest/live broker; branch in place), TDD order, surgical scope.
2. Dispatch `spec-reviewer` (sonnet) on the commit SHA.
3. After spec ✅, dispatch `code-quality-reviewer` (sonnet) — it verifies the architectural invariants (esp. for alpaca.ts: the guard must throw `BrokerCallBlockedError` on mutating calls before any fetch).
4. Apply review fixes, re-verify `deno task test`, mark task complete, continue.

The task list (TaskList) tracks remaining items #18–#26.

## 7. Gotchas / notes

- **`SendMessage` tool is NOT available** in this environment despite the agent-result hint. So review-driven fixes were applied by the controller directly and self-verified with `deno task test` (rather than re-dispatching the same engineer). The reviews caught real issues each time — keep the review discipline.
- Reviews already fixed: a `strEnv` blank-string bug (blank env must raise, not default — mirrors settings.py), `real`→`double precision` price columns + a `bot_config.updated_at` trigger in the schema, and **n8n payload `message`/`title` parity** (the structured TS payloads now carry the human-readable `message` the Discord node renders — confirm the n8n flow still reads `body.message` at deploy).
- **For alpaca.ts (P2-T3):** the guard is the safety-critical bit — mutating methods (`placeMarketOrder`, `liquidate`, `cancelAllOrders`) must call `checkGuard()` first and throw before any network call. There's a dedicated "no network hit under guard" test in the plan. There are NO real Alpaca keys locally, and tests stub `fetch`, so there's no live-broker risk — but keep the guard faithful.
- **Hard prerequisites before any paper/live deploy** (in spec + Plan 3 runbook): (1) confirm UPRO is buyable on the Alpaca account; (2) **rotate the Alpaca paper keys** exposed in a prior session.
- Reviewers (read-only) decline to run tests themselves; the controller runs `deno task test` to confirm green.

## 8. Suggested next prompt

`Resume MVP 2.0 execution on branch feat/220-mvp2-migration-design — continue subagent-driven from P2-T3 (alpaca.ts) per docs/plans/2026-06-05-mvp2-infra-migration-plan-2-io-modules.md. deno is installed; Docker is not (defer the 3 Docker-gated verification steps). Keep the engineer→spec-reviewer→code-quality-reviewer loop.`
