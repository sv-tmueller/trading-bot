**Date:** 2026-06-04 (UTC)
**Slug:** mvp2-pivot-to-infra-only
**Author:** Claude Code session (claude-opus-4-8)

## 1. Sit-rep

The production bot is the post-pivot **deterministic 200-DMA equity regime bot on IBKR** (`daily_check.py` + `monitor/kill_switch.py`); nothing about its runtime changed this session. This session ran the **MVP 2.0 Phase 1 options research** end-to-end on issue [#220](https://github.com/sv-tmueller/trading-bot/issues/220): built an offline Put-Credit-Spread-on-Regime+IV (PCS-RIV) backtest engine, ran it, and got a decisive **KILL** — premium-selling on SPY does not beat buy-and-hold in any gate configuration (best Sharpe 0.36 vs SPY 0.83). On that result the user **pivoted MVP 2.0 to infra-only**: migrate the *existing* deterministic equity bot to Vercel + Supabase + Alpaca, with Claude as a **read-only** start/end-of-day advisor/reporter. #220 is retitled and re-scoped; the next step is a brainstorm on six infra open questions, then a plan. Repo is clean on `main` (`449bee0`), no uncommitted work, no stash, no worktree.

## 2. In-flight branches & PRs

All this session's work is **merged**. No feature branch is in flight.

- **#219** (merged, `913121c`) — removed `bypassPermissions` default mode from `.claude/settings.json`.
- **#221** (merged, `70cbf9f`) — MVP 2.0 Phase 1 plan + Alpaca options data-spike memo.
- **#222** (merged, `4423b66`) — PCS-RIV engine (Tasks 2–4): `options_pricing.py`, `options_data.py`, `pcs_riv.py` (+31 tests).
- **#223** (merged, `ce106e4`) — `run_pcs_riv.py` + findings doc; verdict KILL.
- **#224** (merged, `449bee0`) — regime-gate ablation (`regime_mode` param); gate harms premium-selling.
- **#217** (closed, not merged) — stale notification-sound hook; conflicted with #219 and not carried forward. Branch `chore/216-notification-hook` left on remote.

Pre-existing **stale** open PRs (not touched this session, all pre-pivot or old handovers): #215, #203, #179 (handover drafts), #116 (readme ssh line), **#93 (`BaseBroker` ABC + `AlpacaBroker` adapter — DRAFT)**. #93 is worth re-evaluating — it may be partially reusable for the MVP 2.0 Alpaca equities client (see Open questions).

## 3. Open issues being worked

- **[#220](https://github.com/sv-tmueller/trading-bot/issues/220) — MVP 2.0: Migrate the deterministic equity regime bot to Vercel + Supabase + Alpaca (infra-only; LLM as advisor)** — label `enhancement`. The active tracker. Decision-records posted as comments (options KILL → infra-only pivot). **Next move:** brainstorm the six open questions (§5), then `superpowers:writing-plans`.
- **Options research is complete and shelved.** `docs/research/mvp2-pcs-riv-backtest.md` (+ `mvp2-alpaca-options-data-spike.md`) hold the full record. Do **not** re-test options unless reframing as a low-correlation diversifier (a documented but out-of-scope thread).
- **#165–#191 (many low/medium issues)** — _Not engaged this session._ Most describe the **dead pre-pivot v1.14 Alpaca bot** (`compute_signals`, `fetch_bars`, OCO brackets, `MAX_POSITIONS` LLM-trust). Likely moot post-pivot; a triage pass should close the obsolete ones.

## 4. Decisions made this session

- **Decision:** MVP 2.0 drops the options layer entirely → infra-only migration. **Rationale:** PCS-RIV KILL (Sharpe 0.14) + ablation showing even gate-off vol-harvest (Sharpe 0.36) loses to SPY buy-hold (0.83); you can't out-earn a bull by selling capped premium. **Consequence:** do not build OPRA/Supabase/Vercel for options; do not re-run options backtests. Next work is migrating the *equity* bot.
- **Decision:** the LLM in MVP 2.0 is a **read-only** start/end-of-day reporter/analyst — no param-setting. **Rationale:** the deterministic 200-DMA strategy has no params for an LLM to set; keeping it read-only preserves the "no LLM in trade path" invariant cleanly. **Consequence:** the earlier "advisor proposes params within bounds" framing (from when options was in scope) is moot.
- **Decision:** broker for MVP 2.0 = **Alpaca** (equities), repo = **same-repo, replace-in-place** (tag current as `v1.0` first), DB = **Supabase**, scheduling = **Vercel Cron**, reaction cadence = **minutes** (serverless-friendly). **Rationale:** Alpaca is stateless REST (no always-on gateway → true serverless, no VPS), EU-resident options Level 3 already confirmed on the user's account. **Consequence:** IBKR (`tools/ibkr_broker.py`) is replaced; the `CLAUDE_AGENT_NO_BROKER` guard pattern must carry to the new Alpaca client.
- **Decision:** kept the options engine in-tree as research code. **Rationale:** reusable if a diversifier study is ever wanted; cheap to keep. **Consequence:** `backtest/options_pricing.py`, `options_data.py`, `pcs_riv.py`, `run_pcs_riv.py` remain on `main`.

## 5. Open questions

(All six are the gate for the infra brainstorm; posted on #220.)

- **Language — TypeScript or Python?** Blocks: user decision. Supabase Edge Functions are Deno/TS-only; Vercel supports Python as a second-class runtime. The bot's logic is tiny (`compute_target_state`), so a TS port is cheap. **Next step:** ask the user.
- **How much to port vs rebuild?** Blocks: user decision + a read of the current modules. **Next step:** inventory `daily_check.py` / `strategy/regime.py` / `monitor/kill_switch.py` and decide per-module.
- **Is PR #93 (`AlpacaBroker` adapter) reusable?** Blocks: reading #93's diff against the new stateless-REST equities need. **Next step:** review #93; it predates the IBKR pivot.
- **Supabase schema migration** — how to map `regime_state` / `trades` / `audit_log` (SQLite → Postgres)? Blocks: schema design. **Next step:** design doc from `storage/schema.sql`.
- **Kill-switch reimplementation** — Vercel Cron or Supabase Edge scheduled function, and must work when the happy path is degraded. Blocks: architecture decision. **Next step:** brainstorm.
- **LLM advisor exact I/O** — what does the start/end-of-day Claude job read (DB/positions) and write (Discord via n8n)? Blocks: scope decision. **Next step:** define read-only contract.

## 6. Files to read first

- `docs/research/mvp2-pcs-riv-backtest.md` — why options were shelved (KILL + ablation). Read before anyone suggests options again.
- `docs/research/mvp2-alpaca-options-data-spike.md` — Alpaca data reality: real options history ~2024-01, bid/ask quotes OPRA-gated ($99/mo), trade bars free.
- `daily_check.py` — the current deterministic bot to migrate (the daily flow + `audit_log` wrapping).
- `strategy/regime.py:19` — `compute_target_state`, the entire pure decision rule to port.
- `monitor/kill_switch.py` — hourly drawdown monitor to reimplement on the new stack.
- `tools/ibkr_broker.py` — current broker + the six guarded helpers; the Alpaca client must mirror the `_check_guard()` pattern.
- `storage/schema.sql` — `regime_state` / `trades` / `audit_log` to migrate to Supabase.
- `config/settings.py` — env-var validation; the "add a setting" recipe in `.claude/skills/add-or-extend-agent/SKILL.md`.
- `CLAUDE.md` — architectural invariants (authoritative, post-pivot).

## 7. Don't forget

**The handover README's standing "Don't forget" list is PRE-PIVOT and WRONG now** — it describes the dead v1.14 Alpaca bot (bracket orders, IEX/SIP `DATA_FEED`, pre-market `13:25` cron, `tools/risk.py`, `TeamLeaderAgent`). Ignore it. The current invariants (from `CLAUDE.md`) are:

- **No LLM in the trading path.** `daily_check.py` / `monitor/kill_switch.py` import nothing from `anthropic`. The planned MVP 2.0 LLM advisor must stay **read-only** (reporting only) — it never places orders and never sets the decision.
- **One decision rule:** SPY close vs SPY 200-DMA via the pure `strategy.regime.compute_target_state`. Do not add a second rule without a fresh brainstorm + spec.
- **Operational kill switch:** `TRADING_PAUSED=true` halts new entries (`daily_check.py` writes `skipped:trading_paused`). `python main.py panic --pause|--cancel-orders|--liquidate --confirm` is the deterministic kill button — no LLM in that path.
- **Engineer subagents must never hit the live broker.** `CLAUDE_AGENT_NO_BROKER` makes the six `tools/ibkr_broker.py` helpers raise `BrokerCallBlockedError`; an autouse conftest fixture sets it in tests. **Mock all six in any test.** This guard pattern must carry to the new Alpaca client. (Two live-broker incidents, #149/#168, are why.)
- `daily_check.py` runs **post-US-close** (cron `30 22 * * 1-5` UTC); earlier hits the stale-data guard.
- Python 3.9 runtime → **every file starts with `from __future__ import annotations`**.

Session-specific:
- A local `venv/` (pandas + yfinance only, **gitignored**) exists on this machine to run `backtest/run_pcs_riv.py`. A fresh checkout / the VPS won't have it: `python3 -m venv venv && venv/bin/pip install "pandas==2.2.3" "yfinance>=0.2"`. The full suite also needs `ib_insync` (not installed here → 34 `ib_insync` import errors under `python3 -m pytest`; the 109 backtest/non-broker tests pass).
- The user's Alpaca **paper** keys were pasted in plaintext mid-session — they should be rotated.

## 8. Suggested next prompts

1. `Brainstorm the MVP 2.0 infra migration on issue #220 — resolve the six open questions (language TS/Python, port-vs-rebuild, Alpaca broker, Supabase schema, kill-switch, LLM-advisor scope), then write an implementation plan in docs/plans/.`
2. `Review PR #93 (BaseBroker ABC + AlpacaBroker adapter) — decide if it's reusable for the MVP 2.0 Alpaca equities client or superseded by the IBKR pivot. Report, don't merge.`
3. `Triage open issues #165–#191 — flag which describe the dead pre-pivot v1.14 Alpaca bot and can be closed, and which still apply to the post-pivot IBKR bot.`
4. `Read docs/research/mvp2-pcs-riv-backtest.md and tell me whether the documented vol-harvest diversifier thread is worth a follow-up study before we commit fully to infra-only.`
