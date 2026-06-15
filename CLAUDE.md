# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working in this repo

Before starting any task, check the available skills list (printed in your system-reminder context) and the contents of `.claude/skills/` for a workflow that matches the user's request. If one matches, invoke it via the Skill tool (main session) or read its `SKILL.md` directly (subagents — Read tool only). Skills hold the procedural how-tos; this file holds the standing rules and architectural invariants. Both are required reading.

Current skills relevant to engineering work:
- **`add-or-extend-agent`** — recipe for adding a new env-driven setting (env read, validation, `.env.example`, README, opt-in/default-OFF pattern). The historical "agent" content (BaseAgent contract, tool routing) is no longer applicable post-2026-05-07 pivot but the settings recipe is still canonical.
- **`handover`** — writing a session handover doc so a future session can resume cold.
- **`research-bundle`** — multi-agent research surveys for product-direction decisions.

## Superpowers skills are the canonical playbooks

This project uses the [`superpowers`](https://github.com/obra/superpowers) plugin (installed via `/plugin install superpowers@claude-plugins-official`). Where a `superpowers:` skill exists for a workflow, **it is the canonical playbook for this project**. The operating model is `advisor → kickoff → architect / developer / reviewer / tester`.

| Workflow | Skill | Wired into |
|---|---|---|
| Brainstorming a change (every change — HARD-GATE) | `superpowers:brainstorming` | `/tm-advisor` (main session) |
| Writing an implementation plan | `superpowers:writing-plans` | `/tm-advisor`. Plans live in `docs/plans/<date>-<slug>-plan.md`. |
| Executing a plan task-by-task | `superpowers:subagent-driven-development` | `/tm-kickoff` pipeline (architect → developer → tester → reviewer). |
| Implementing a single task | _(developer prompt)_ | `developer` subagent ([`.claude/agents/developer.md`](.claude/agents/developer.md)) |
| Test-driven discipline | `superpowers:test-driven-development` (see also `testing-anti-patterns.md` inside that skill's directory — sibling reference, not a standalone skill) | developer |
| Root-cause-first debugging | `superpowers:systematic-debugging` | qa (failed-test triage); developer (general debugging) |
| Verifying claims before completion | `superpowers:verification-before-completion` | tester + reviewer / architect |
| Wrapping up a branch | `superpowers:finishing-a-development-branch` | `/tm-kickoff` pipeline; human merge sign-off. |
| Worktree-per-task isolation | `superpowers:using-git-worktrees` | All agents (reinforces the existing "always use worktrees" rule). |

The three trading-bot-specific skills (`add-or-extend-agent`, `handover`, `research-bundle`) sit alongside the superpowers skills — they cover work the superpowers library does not.

**Where superpowers conflicts with older inline guidance in `CLAUDE.md` or in agent `.md` files, the superpowers playbook wins.** The [Architectural invariants](#architectural-invariants) section below is the single authoritative home of the repo's safety contract; nothing restates the invariant text, every enforcement artifact references this section. Non-negotiable.

**Architectural invariants are a hard review gate.** The [Architectural invariants](#architectural-invariants) section is the single source of truth — never restate it elsewhere. Every code-touching work package carries the standing acceptance criterion *"Satisfies all CLAUDE.md Architectural invariants; any violation is a must-fix review finding,"* which the advisor stamps when filing the issue. The architect, developer, and reviewer verify the change against that section; the reviewer treats any violation as a blocking `CHANGES_REQUESTED` finding. Invariant #1 ("No LLM in the trading path") is additionally enforced mechanically by `supabase/functions/_shared/invariants.test.ts`.

**Subagents do not have the `Skill` tool.** They access skill content via `Read` on the SKILL.md file. To find a SKILL.md path: `find ~/.claude/plugins -name SKILL.md -path "*<skill-name>*"`.

## Commands

The production bot is TypeScript on Supabase + Alpaca. The Python that remains is research-only
(`backtest/`, `strategy/regime.py`, `main.py`).

```bash
# Run all TS unit tests (Alpaca + DB mocked; the broker guard fails fast)
deno task test

# Run a single TS test file
deno test --allow-env --allow-net supabase/functions/_shared/regime.test.ts

# DB integration tests — needs a local Postgres (gated behind RUN_DB_TESTS)
deno task test:db

# Deploy the bot to a Supabase project (full steps: docs/runbooks/mvp2-deploy-and-decommission.md)
supabase functions deploy daily-check kill-switch     # JWT-verified; cron sends the bearer
supabase functions deploy panic --no-verify-jwt       # auth = x-panic-token header
supabase db push                                      # applies migrations 0001-0007 (schema + cron + vault fn grants)

# Panic kill button (token-auth Edge Function — deterministic, no LLM)
curl -i -X POST "https://<ref>.supabase.co/functions/v1/panic?action=pause" -H "x-panic-token: <token>"
#   actions: pause | resume | cancel-orders | liquidate   (500 + error: result = action failed)
#   liquidate also sets bot_config.paused=true (no re-buy next daily-check); clear via action=resume

# Backtest the regime strategy (Python research — not the trading path)
venv/bin/python main.py backtest --years 5
```

## Languages / runtime

The production bot is **TypeScript on Deno** (Supabase Edge Functions). Production code lives in
`supabase/functions/`; `regime.ts` is a 1:1 port of the kept `strategy/regime.py`.

The research backtester is **Python 3.9** (`backtest/`, `strategy/`, `main.py`). **Every Python
file must start with `from __future__ import annotations`** — this enables modern type hint syntax
on 3.9. Never use `list[dict]` or `dict[str, Any]` without this import.

## Architecture

The production bot is three Supabase Edge Functions (TypeScript/Deno) driven by `pg_cron`, over
shared TS modules in `supabase/functions/_shared/` (`regime`, `config`, `alpaca`, `marketdata`,
`db`, `notifications`, `num`, `supabase_client`). Each function is `logic.ts` (pure, testable) +
`index.ts` (HTTP entry). Broker + market data are Alpaca REST; persistence is Postgres.

### Daily flow

`daily-check` acts at most once per trading day, shortly after the US open (`pg_cron` `37 13 * * 1-5`
and `37 14 * * 1-5` UTC — two slots cover US DST without code changes; the function calls Alpaca
`/v2/clock` and exits `skipped:market_closed` when the US market is closed. During EDT — open 13:30
UTC — the 13:37 run acts and the 14:37 run, with the market already open, re-runs the full pipeline
as an idempotent no-op (`success`, no second trade); during EST — open 14:30 UTC — the 13:37 run
exits at the clock gate and the 14:37 run acts; on market holidays both runs gate-exit). It fetches
SPY daily bars from Alpaca, drops today's in-progress bar, and computes the 200-DMA regime filter
on the **previous completed trading day's** close — the same information set a post-close run
would have, with execution at the next open, which is exactly what the backtest models. It then
reconciles against the Alpaca position and flips between LONG (`BOT_TICKER`=UPRO) and CASH if
needed; the `regime_state` row for a given date carries the previous session's
`spy_close`/`spy_sma200`.
Account value is read in **USD** (Alpaca accounts are USD-denominated). Wraps the flow in an
`audit_log` row; every exit path writes a deterministic `outcome` string (`success`, `success:*`,
`skipped:*`, `error:*`).

### Intraday kill-switch

`kill-switch` runs every 5 minutes during US market hours (`pg_cron` `*/5 13-21 * * 1-5` UTC; it
calls Alpaca `/v2/clock` and early-exits when the market is closed, so US DST is handled without
changing the cron expression). If UPRO drawdown from its `KILL_SWITCH_LOOKBACK_DAYS` rolling high —
including today's running high / last trade — exceeds `KILL_SWITCH_DRAWDOWN_PCT`, it liquidates and
sets `kill_switch_active=true` in `regime_state`.

It sources the position from the broker (`getPosition`), **not** `regime_state.current_state`, so a
DB/broker desync can't leave a real position unprotected: a position the DB recorded as CASH (or has
no `regime_state` row for at all) is still protected — the run raises `notifyStateDesync`, records a
`state_desync` note in `audit_log`, and continues the drawdown check on the live position; only the
`regime_state` upserts are skipped when there is no row to carry forward (daily-check resyncs the DB
on its next run). A >2x refHigh/lastPrice ratio is treated as implausible (unadjusted corporate action
or bad print) and exits `error:implausible_drawdown` with an alert instead of liquidating.

### Database

Postgres in Supabase (`supabase/migrations/0001_init.sql`). Tables:
- `regime_state` — one row per trading day with `spy_close`, `spy_sma200`, `target_state`, `current_state`, `position_drawdown_pct`, `kill_switch_active`, `kill_switch_fired_at`.
- `trades` — broker fills (`symbol`, `side`, `qty`, `fill_price`, `fill_time`, `broker_order_id`, `reason`).
- `audit_log` — one row per function invocation (`script_name`, `started_at`, `finished_at`, `outcome`, `notes`). Used for forensics and partial-recovery — `outcome` is written before exit so a crashed run leaves a row with no `finished_at`.
- `bot_config` — key/value config; holds the runtime `paused` flag (replaces the old `TRADING_PAUSED` env var).

All tables are RLS-deny-all; the Edge Functions connect with the **service-role key** (bypasses RLS).
The cron jobs (`0002_schedule.sql`; daily-check rescheduled by `0006_daily_check_open_schedule.sql`)
read the service-role key and the functions base URL from **Vault** secrets (`service_role_key`,
`functions_base_url`), so the same committed migrations work for both dev and prod — only the Vault
values differ.

### Notifications

`notifications.ts` POSTs to an n8n webhook (`N8N_WEBHOOK_URL` secret) which forwards to Discord.
Silently skips if the secret is unset or the request fails, so a notification outage never crashes
the bot. The webhook must be reachable from Supabase's cloud — a `localhost` URL won't work, and a
Cloudflare-Access-protected n8n needs a path **bypass** (the bot sends no auth header).

The helpers post structured JSON dicts (`event_type` + event-specific fields, plus a `message`
field the n8n flow renders) so the flow can route on shape: `notifyRegimeFlip`,
`notifyKillSwitchFired`, `notifyTradeFailed`, `notifyStateDesync`, `notifyBrokerError`,
`notifyError`, `notifyPanic`.

### Settings

`config.ts` reads + range-validates settings from Edge Function secrets at function start and throws
on out-of-range. The recipe for adding a new setting (env read, validation, README, opt-in/default-OFF
pattern for risky changes) is in [`.claude/skills/add-or-extend-agent/SKILL.md`](.claude/skills/add-or-extend-agent/SKILL.md) — the
env-var mechanics now apply to `supabase secrets set` / `config.ts` rather than `.env` / `config/settings.py`.

## Testing conventions

The broker client `supabase/functions/_shared/alpaca.ts` exposes a client from `createAlpacaClient()`
with three mutating helpers (`placeMarketOrder`, `liquidate`, `cancelAllOrders`) that call
`checkGuard()` at the top, plus read-only helpers (`getClock`, `getAccountValue`, `getPosition`).
`liquidate` routes through `placeMarketOrder`, so the guard covers it transitively too. All Alpaca
calls MUST be mocked in any test that exercises a path which would reach them. When
`CLAUDE_AGENT_NO_BROKER` is set, the guarded helpers raise `BrokerCallBlockedError` before any HTTP
call — this is the mechanical safety net, but tests should still mock cleanly so the assertions are
meaningful. The function `logic.ts` modules take their broker/db/notification dependencies via an
injected `deps` object, so tests pass mocks directly.

## Key constraints

- `REGIME_SMA_DAYS`, `KILL_SWITCH_DRAWDOWN_PCT`, `KILL_SWITCH_LOOKBACK_DAYS`, `BOT_TICKER`, `BOT_BENCHMARK`, and the Alpaca credentials are validated by `config.ts` at function start — invalid values throw immediately.
- `daily-check` runs **post-open** (`pg_cron` `37 13 * * 1-5` and `37 14 * * 1-5` UTC). The function calls Alpaca `/v2/clock` and exits `skipped:market_closed` when the US market is closed: during EDT (open 13:30 UTC) the 13:37 run acts and the 14:37 run, with the market already open, re-runs the full pipeline as an idempotent no-op (`success`, no second trade); during EST (open 14:30 UTC) the 13:37 run gate-exits and the 14:37 run acts; on market holidays both runs gate-exit.
- The signal is the **previous completed trading day's** SPY close vs its 200-DMA. Today's in-progress bar is dropped; if the last completed SPY bar does not match the most recent trading day strictly before today per Alpaca's calendar, the run hits the stale-data guard and exits with `skipped:stale_data` in `audit_log`.
- `daily-check` is idempotent: re-running on the same trading day computes the same `target_state`, sees `current_state` already matches, and writes a no-op `regime_state` row.
- The bot has one decision rule. It is testable as a pure function (`computeTargetState` in `supabase/functions/_shared/regime.ts`). Do not add second decision rules without a fresh brainstorm and spec.
- `daily-check` honors `bot_config.paused` — the `panic` Edge Function (`action=pause`) is the operational kill switch.

## Architectural invariants

**Every reviewer and architect working on this repo MUST read and enforce this section on every change — it is the repo's safety contract and overrides any generic template review guidance that conflicts with it.**

These are non-negotiable and carry over verbatim in intent from the pre-migration bot. The MVP 2.0
migration (#220) re-pointed the *implementation* (IBKR -> Alpaca, `daily_check.py` -> `daily-check`
Edge Function, SQLite -> Supabase Postgres, `.env` -> `supabase secrets` / `bot_config`) but did not
relax a single one of these guarantees.

- **One decision rule.** The bot trades on exactly one signal: SPY close vs SPY 200-DMA, modulated by the kill-switch flag. The signal is computed by a pure function (`computeTargetState` in `supabase/functions/_shared/regime.ts`, a 1:1 port of `strategy/regime.py`) so every decision is reproducible from the SPY history alone. Do not add a second decision rule (sentiment overlay, sector tilt, etc.) without a fresh brainstorm and design spec — the rules-engine pivot exists precisely because the LLM-driven multi-signal v1.14 bot was indistinguishable from a coin flip on 5y data.
- **No LLM in the trading path.** The `daily-check`, `kill-switch`, and `panic` Edge Functions import no model SDK and instantiate no agent. The only Claude session in the repo is the operator's interactive Team Leader for development work — it never executes orders.
- **Operational kill switch.** `bot_config.paused=true` halts new entries — `daily-check` writes `skipped:trading_paused` to `audit_log` and exits 0 without contacting Alpaca. The kill-switch function is unaffected and continues protecting an open position. The flag is set via the `panic` Edge Function (`action=pause`, cleared with `action=resume`), which is also the faster incident path — it can cancel orders or liquidate in the same family of invocations.
- **Panic is the deterministic kill button.** The `panic` Edge Function (`action=pause|resume|cancel-orders|liquidate`, authenticated by the `x-panic-token` header) calls Alpaca and writes `bot_config` directly. No LLM is imported in this path. Its `audit_log` row (`script_name="panic"`) is written before the broker call and updated in a `finally` with the per-action result, so a partial run is recoverable from the DB. `runPanic` returns a typed `{ ok, result }`; a failed action returns HTTP 500 (failure is signalled by the status — the JSON body carries the raw `result` string, and the `error:` prefix lives on the `audit_log.outcome`, not the response body) — never treat a 500 as success.
- **Engineer subagents must never execute against the live broker.** Subagents spawn into worktrees that inherit the project's Alpaca secrets via the parent shell, so any `deno test`, ad-hoc script, or direct function invocation could submit real orders if it reached a live broker path. The mutating helpers on the `supabase/functions/_shared/alpaca.ts` client — `placeMarketOrder`, `liquidate`, `cancelAllOrders` — call `checkGuard()` at the top of each function and raise `BrokerCallBlockedError` when `CLAUDE_AGENT_NO_BROKER` is set. `liquidate` routes through `placeMarketOrder`, so the guard covers it transitively; the read-only helpers (`getClock`, `getAccountValue`, `getPosition`) cannot place orders. All Alpaca calls MUST be mocked in agent-spawned tests (function `logic.ts` modules take an injected `deps` object — pass mocks directly). Integration tests that need a real broker must use the Alpaca **paper** account with explicitly-set secrets, or be explicitly skipped in agent contexts. **Mechanically enforced via the `CLAUDE_AGENT_NO_BROKER` env var (ported from #168) — when set, the guarded helpers raise `BrokerCallBlockedError` before any Alpaca call. Production leaves the var unset; the test setup sets it so any forgotten mock fails fast instead of materialising a live order. Defense in depth: dev/test use Alpaca paper keys.** _Rationale: 2026-05-06 incident #149 — six SIMPLE-class market BUY orders for AMD ×4, GOOG, MSFT were submitted from an Engineer worktree at 05:56-05:57 UTC, draining buying power from $99k to $2,239 and leaving positions that would have filled unprotected at market open if not surgically cancelled. Re-materialised ~30 minutes after issue #168 was filed when a QA subagent's `pytest` reached live broker via an unmocked path and submitted 5×100 AMD parent BUYs (500-share, $-101k margin position; recovered via panic CLI). The production cron path was unaffected in both incidents; the gap was on the agent-test side and is now closed by the mechanical guard plus the docs/skill rule (defense-in-depth)._ The rule originated against the pre-pivot `tools/broker.py`, applied to the IBKR `tools/ibkr_broker.py`, and now applies to `supabase/functions/_shared/alpaca.ts` exactly the same way.

Development decisions that affect the safety stack or trading logic are recorded as ADRs in `docs/decisions/`. Weekly trading outcomes and observations are recorded in `docs/trading-journal/`.

_Rationale: deterministic rules engines are auditable; LLM outputs are not. The v1.14 incident history showed that even with deterministic guardrails wrapped around an LLM, the LLM's non-determinism leaked through at the points where it set sizes, picked instruments, or narrated outcomes. The post-pivot bot has none of that surface area — there is no decision the LLM can corrupt because there is no LLM in the path._

## Team

The operating model is `/tm-advisor` → `/tm-kickoff` → specialist subagents. You never need to switch sessions.

- **`/tm-advisor`** — refines a request, proposes a sized work package, gets one human sign-off, then runs the batch. Use it to start any meaningful change.
- **`/tm-kickoff`** — fans out to `architect` (approach) → `developer` (implement, TDD) → `tester` (verify) → `reviewer` (spec + quality, blocks on invariant violation) and posts ready-to-merge PRs.

| What you want | What to say |
|---|---|
| Start a change | `/tm-advisor <description>` |
| Implement a sized issue | `/tm-kickoff #N` |
| Run QA | Ask QA — discover bugs, open issues (with `superpowers:systematic-debugging` triage) |
| Update docs | Ask Docs — sync README, CLAUDE.md, CURRENT_CONFIG |
