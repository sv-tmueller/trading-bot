**Date:** 2026-05-08 (UTC)
**Slug:** pivot-merge-and-soak-prep
**Author:** Claude Code session (claude-opus-4-7)

## 1. Sit-rep

The rules-engine pivot is **fully merged to `main`** at `a1349f5` and tagged **`v2.0.0`** (https://github.com/sv-tmueller/trading-bot/releases/tag/v2.0.0). All 11 issues that comprised the pivot are closed. The bot's architecture is now: `daily_check.py` (cron-driven 200-DMA regime filter on SPY → IBKR market order on `BOT_TICKER`) + `monitor/kill_switch.py` (hourly drawdown circuit) + `main.py panic` (deterministic kill button). No LLM in the trading path. Production code is **2,080 lines** (down from ~5,000+ pre-pivot); 129 tests pass / 0 fail. The bot is **NOT running yet**: cron is off, IB Gateway is not yet installed on the VPS, and the user is mid-pre-flight (`.env` populated with soak-mode vars `DAILY_CHECK_DRY_RUN=true` + `TRADING_PAUSED=false`; manual `daily_check.py --dry-run` end-to-end-tested with the broker disconnected — exited with `error:tws_disconnect` audit row + Discord card, exactly as designed). Critical-path next step: **install IB Gateway** so the broker side of the pipeline can be soak-tested too. Soak target: Monday 2026-05-11 → Friday 2026-05-15; flip cron live Monday 2026-05-18 if clean.

## 2. In-flight branches & PRs

- **PR #203** — `handover/rules-engine-pivot-2026-05-08` (state: **draft, stale**). Original handover written before this session began, when only the foundation commits had landed on `main`. The work it described is now merged via PR #193. Either close as superseded or flip to ready and merge as historical record.
  - **Next action:** `gh pr close 203 --comment "Superseded by PR #193 merge to main"` OR `gh pr ready 203 && gh pr merge 203 --squash`.

- **PR #179** — `handover/superpowers-adoption-2026-05-07` (state: **draft, stale**). Handover from the session that adopted the superpowers workflow. That work has shipped (commit `556da16`). Same treatment as #203.
  - **Next action:** close or merge.

- **PR #116** — `docs/readme-ssh-line` (state: **ready, stale**). Tiny pre-pivot docs PR for a one-line README simplification. README has been completely rewritten in #213 (now on `main`); this PR's diff is no longer applicable.
  - **Next action:** `gh pr close 116 --comment "Superseded by README rewrite in #213"`.

- **PR #93** — `claude/evaluate-mql5-trading-Kt8Os` titled `feat(brokers): BaseBroker ABC + AlpacaBroker adapter` (state: **draft, stale**). Pre-pivot broker-abstraction work. Post-pivot the bot doesn't have a broker abstraction layer (it has one broker: IBKR via `tools/ibkr_broker.py`); the code this PR added is moot.
  - **Next action:** close with comment "Moot post-#193 pivot; no BaseBroker abstraction in v2.0.0".

- **PR #193** — `spec/rules-engine-pivot` (state: **merged** at `a1349f5` on 2026-05-08T21:33:34Z). Closes #190, #193, #194, #195, #196, #197, #198, #199, #200, #201, #202.
  - **Next action:** _None._ Already merged; release tagged.

- **PR #214 → spec branch** (squash sha `7a15808`), **PRs #210/#211/#212/#213 → spec branch** (squash shas `6b7a240/854dd4b/f2dcdfe/696ffc2`) — all merged into the spec branch and rolled up into PR #193.
  - **Next action:** _None._ Closed via spec→main merge.

## 3. Open issues being worked

- **`#190` — gitignore trading_bot.db** — closed by PR #210 (squash `6b7a240`).
- **`#193` — pivot spec** — closed by PR #193 merge.
- **`#194 / #195 / #196 / #197 / #198 / #199 / #200 / #201 / #202` — pivot Tasks 5/7/8/9/10/11/12-15/16/17** — all closed by PR #193 merge (or earlier sub-PR merges to spec).
- **All remaining open issues (39 of them, #61 → #191)** — pre-pivot. Most reference modules / settings / behaviour that no longer exist (`tools/risk.py`, `tools/broker.py`, `agents/`, `MAX_POSITIONS`, `RISK_PER_TRADE`, OCO brackets, `signals` table, `agent_logs` table, `monitor_actions` table, etc.). They need a triage sweep to **close-as-moot** or **port-to-post-pivot-equivalent**.
  - Examples that are clearly moot post-merge: #61 (raise `MAX_PORTFOLIO_EXPOSURE`), #66 (short-side strategy), #93/#94/#95/#96 (broker abstraction / Alpaca portfolio frictions), #102 (SPY 200-SMA gate — landed!), #138 (v1.10/v1.11 soak-week analysis — superseded by 5y backtest in `docs/research/v1.14-backtest-baseline/`), #154/#155/#157/#158/#163/#180/#181/#182/#185/#188 (all reference deleted Alpaca/agents/risk-engine paths).
  - Examples that *might* still apply: #104 (walk-forward backtester — could be ported to the regime backtester), #173 (test_main.py fails when live `.env` has `TRADING_PAUSED=true` — may still apply since `main.py` still has unit tests), #184 (fetch_bars partial intra-day — moot if `fetch_bars` is gone, but worth checking).
  - **Next move:** dispatch `lead` for a triage pass: `Triage open issues — most are pre-pivot, close as moot or port to v2.0.0 equivalents`.

## 4. Decisions made this session

- **Decision** — Bundle the remaining pivot work as 3 sub-PRs into `spec/rules-engine-pivot` then ONE PR to `main`, rather than direct-commit or one-shot. **Rationale** — matches user's preferred squash-merge-with-`(#N)`-suffix workflow and keeps per-task review discipline (Pass-1 spec + Pass-2 quality on each). **Consequence** — `main` history shows 1 squash commit (`a1349f5`); spec branch history shows 12 commits with full review trails.
- **Decision** — Add a `--dry-run` flag (`DAILY_CHECK_DRY_RUN` env var) to `daily_check.py` even though the plan didn't spec it. **Rationale** — operator wanted "code merged, cron OFF, manual runs only" for the soak week; dry-run lets the full pipeline (regime calc, audit log, Discord notification) run without any broker writes. **Consequence** — soak week can validate everything except the broker call; flip to `false` after soak to go live.
- **Decision** — Lift `DAILY_CHECK_DRY_RUN` into `config/settings.py` (with `_parse_bool` helper) rather than reading the env var inline in `daily_check.py`. **Rationale** — Pass-2 reviewer flagged the inline read as inconsistent with project convention (every env var goes through `config/settings.py`). **Consequence** — future env-var additions follow the same pattern; `_parse_bool` is reusable.
- **Decision** — `daily_check.py` honors `TRADING_PAUSED` directly (not just `main.py scan`). **Rationale** — Pass-2 reviewer flagged that post-#200 there's no `main.py scan` to honor it; if `daily_check.py` ignored it, `panic --pause` would have been a no-op for the new bot. **Consequence** — `panic --pause` actually halts new entries on the post-pivot bot.
- **Decision** — Add a `message` string field to all 5 structured-event notifier payloads (`notify_regime_flip`, `notify_kill_switch_fired`, `notify_trade_failed`, `notify_tws_disconnected`, `notify_state_desync`). **Rationale** — final integration review caught that `n8n/trading-bot-discord-notifications.json` binds card content to `{{ $json.body.message }}`, but the new helpers posted dict payloads with no `message` field — would have been silent during the soak week. **Consequence** — existing n8n flow renders all event types correctly; verified end-to-end via the dry-run smoke test (Discord card landed for `tws_disconnected`).
- **Decision** — Liquidate-failure on bearish flip aborts the cycle (return 1, audit `error:liquidate_failed`, no `current_state` advance) rather than silently advancing to CASH. **Rationale** — Pass-2 flagged the original code path advanced `current_state="CASH"` even when `liquidate()` returned `None`, which would mis-report state if a real broker-side failure happened. **Consequence** — DB stays consistent with broker truth on failed liquidations; audit row tells you exactly what happened.
- **Decision** — Tag `v2.0.0` immediately at merge time, not after the soak week. **Rationale** — matches prior tagging convention (v1.13 / v1.14 were tagged at merge time, before production observation); soak issues become `v2.0.1`. **Consequence** — clear architectural break from v1.x; any post-soak fixes are patches.

## 5. Open questions

- **Question** — Does the operator have an IBKR account already, or do they need to open one this weekend?
  - **What blocks the answer** — operator hasn't said. They're coming from Alpaca paper. The runbook in `README.md` assumes IBKR is already set up.
  - **Suggested next step** — ask the operator. If no account: paper-trading registration is free at interactivebrokers.com (~10-15 min); live trading needs identity verification + funding (multi-day).
- **Question** — Have the two leaked API keys (`ANTHROPIC_API_KEY`, `ALPACA_API_KEY`) been rotated?
  - **What blocks the answer** — operator agreed to rotate but I haven't confirmed it's done. Both keys appear in this conversation transcript and may be cached / indexed.
  - **Suggested next step** — confirm with operator. Both vars are dropped post-#200 so the bot doesn't read them; rotation is purely a security cleanup.
- **Question** — Should the 39 pre-pivot open issues be closed-en-masse as moot, or triaged individually for a "post-pivot equivalent"?
  - **What blocks the answer** — judgement call. Most are clearly moot (delete the agent / Alpaca / OCO / EMA bug); a few might have post-pivot analogues (#173 test failure, #104 walk-forward backtester, #184 partial bars).
  - **Suggested next step** — dispatch `lead` for a triage sweep with the literal prompt `Triage all 39 open issues — most are pre-pivot, close as moot or port to v2.0.0 equivalents`.
- **Question** — Does `docs/handover/README.md` need an update since its "Don't forget" template still has pre-pivot invariants (Alpaca brackets, pre-market scan timing, `tools/risk.py`, `DataFeed.IEX`)?
  - **What blocks the answer** — yes, but out of scope for this handover. Adding to the docs follow-up list.
  - **Suggested next step** — `Update docs/handover/README.md template — replace pre-pivot invariants with post-pivot equivalents (one decision rule, daily_check post-close timing, IBKR, no DataFeed)`.
- **Question** — `n8n/trading-bot-discord-notifications.json` was carried over from v1.14 unmodified; the workflow's binding to `{{ $json.body.message }}` works for the new structured payloads via the added `message` field, but does the operator want a richer flow (event-type Switch node + per-type Discord cards)?
  - **What blocks the answer** — operator preference; current single-binding works fine for the soak.
  - **Suggested next step** — defer; revisit after soak week. If the operator wants richer formatting, a follow-up enhancement issue can scope it.

## 6. Files to read first

- `README.md` — full rewrite in #213. Section `## Starting the bot — Monday 2026-05-11` is the operator runbook (Day-zero pre-flight → soak week → going-live → panic recovery).
- `CLAUDE.md` — post-pivot architectural invariants. Lines 125-131 are the safety stack (one decision rule, no LLM, kill switch, panic CLI, agent-context guard).
- `daily_check.py:1-394` — main entry point. Lines 80-95 (CLI / env parsing for dry-run), 115-124 (TRADING_PAUSED early exit), 154-168 (TWS-disconnect path), 303-344 (CASH flip / liquidate-fail path), 334-343 (outer exception path).
- `monitor/kill_switch.py` — hourly drawdown circuit. Reads `regime_state.kill_switch_active`; calls `liquidate` if drawdown breaches threshold.
- `tools/ibkr_broker.py` — broker wrapper. 4 guarded helpers (`connect_ibkr`, `place_market_order`, `liquidate`, `cancel_all_orders`) + 2 read-only (`get_position`, `get_account_value`). All require `CLAUDE_AGENT_NO_BROKER` to be unset for production cron, set for pytest (autouse).
- `strategy/regime.py:19-60` — `compute_target_state` pure function. Truth-table tested in `tests/test_strategy_regime.py`.
- `tools/notifications.py` — 5 structured-event helpers + `notify_error` + `notify_panic`. Each structured payload now includes a `message` field for the existing n8n Discord binding.
- `tools/database.py` — 5 helpers only: `upsert_regime_state`, `get_latest_regime_state`, `insert_trade`, `insert_audit_log`, `update_audit_log`.
- `config/settings.py` — env-var validation + `is_claude_agent_no_broker()` + `_parse_bool` helper.
- `docs/operations/ibkr-vps-setup.md` — IB Gateway + IBC + systemd install guide. Read end-to-end before running anything on the VPS.
- `scripts/cron_setup.sh` — installs the new cron entries (`30 22 * * 1-5` UTC for `daily_check.py`, `5 14-21 * * 1-5` UTC for `monitor/kill_switch.py`); strips legacy v1.14 entries.

## 7. Don't forget

**The handover template's "Don't forget" defaults in `docs/handover/README.md` are pre-pivot and stale (Alpaca brackets, pre-market scan, `tools/risk.py`, `DataFeed.IEX`). Replace them with the post-pivot invariants below if the next session does any code work.**

Session-specific gotchas from this session:

- **Two API keys leaked in the transcript** (`ANTHROPIC_API_KEY=sk-ant-api03-...`, `ALPACA_API_KEY=PKAEN...`). Operator was asked to rotate; status unconfirmed at handover time. Both vars are unused post-#200 (the new bot doesn't read them) — rotation is security cleanup only.
- **IB Gateway is NOT installed on the VPS yet.** `daily_check.py --dry-run` exits with `error:tws_disconnect` until installed. Until then, all pipeline soak-testing is "everything except the broker connect succeeds, then we fail at the `connect_ibkr` step and write `error:tws_disconnect`".
- **`.env` on the VPS still has v1.14 leftovers** (`ALPACA_*`, `ANTHROPIC_API_KEY`, `EMA_FAST`, `RISK_PER_TRADE`, etc.). Harmless (not read by post-pivot code) but cleanup-worthy. The 10 new vars (`IBKR_*`, `BOT_*`, `REGIME_SMA_DAYS`, `KILL_SWITCH_*`, `DAILY_CHECK_DRY_RUN`, `TRADING_PAUSED=false`) are appended at the bottom; verified working.
- **Pending kernel upgrade on the VPS** (`6.8.0-90 → 6.8.0-111-generic`). Not blocking; operator can reboot at convenience.
- **Stale worktrees in `.claude/worktrees/`** — 8 leftover dirs from prior sessions, all pointing at branches that have either been merged or abandoned. `git worktree prune` + manual `rm -rf` of orphan dirs is safe cleanup.
- **PR #203 (the prior handover) is still draft.** This new handover does not supersede it — it sits alongside, since #203 captured the pre-merge state and this one captures the post-merge state.

Standing post-pivot invariants (from `CLAUDE.md` §"Architectural invariants"):

- **One decision rule.** `strategy.regime.compute_target_state` is the only signal: SPY close vs SPY 200-DMA, modulated by the kill-switch flag. Pure function. Do not add a second decision rule (sentiment overlay, sector tilt, etc.) without a fresh brainstorm and design spec.
- **No LLM in the trading path.** `daily_check.py` and `monitor/kill_switch.py` import nothing from `anthropic` and do not instantiate any agent.
- **`TRADING_PAUSED=true` halts new entries.** `daily_check.py` writes `skipped:trading_paused` to `audit_log` and exits 0. The kill-switch monitor is unaffected. Faster path: `python main.py panic --pause`.
- **Panic CLI is the deterministic kill button.** No LLM in the path; audit row in `audit_log` (`script_name="panic"`) before broker call, updated in `finally`. `--pause` writes to `.env` anchored at repo root.
- **Engineer subagents must never execute against the live broker.** `CLAUDE_AGENT_NO_BROKER` autouse fixture (`tests/conftest.py`) guards all pytest invocations. Production cron leaves the var unset. The 4 guarded `tools/ibkr_broker.py` helpers — `connect_ibkr`, `place_market_order`, `liquidate`, `cancel_all_orders` — raise `BrokerCallBlockedError` when set. The 2 read-only helpers (`get_position`, `get_account_value`) don't call the guard themselves but cannot be reached without first calling `connect_ibkr` (which is guarded), so the fail-fast property holds end-to-end.
- **`daily_check.py` must run post-US-close.** Cron `30 22 * * 1-5` UTC (~5h after NYSE close, 1.5h after yfinance daily bar publishes). Earlier runs hit the stale-data guard and exit `skipped:stale_data`.
- **Idempotent.** Re-running `daily_check.py` on the same UTC day computes the same `target_state`, sees `current_state` matches, writes a no-op `regime_state` row.
- **Every Python file starts with `from __future__ import annotations`** (Python 3.9 runtime).
- **Always use git worktrees for non-trivial work.** Never branch/commit against the main `/opt/trading-bot` checkout. Per-task worktrees go under `.claude/worktrees/agent-<slug>` (engineer dispatches pick this up automatically via the `engineer` subagent definition).

## 8. Suggested next prompts

1. **`Help me install IB Gateway + IBC + the systemd service on the VPS following docs/operations/ibkr-vps-setup.md`** — the critical path. Do this first if the operator has time this weekend; otherwise it's the Monday-morning blocker.

2. **`Triage all 39 open issues — most are pre-pivot (#61–#191), close as moot or port to v2.0.0 equivalents`** — dispatches `lead` for a backlog cleanup sweep. Most issues reference deleted modules (`tools/risk.py`, `tools/broker.py`, `agents/`, OCO brackets, `signals` table) and should close. A few (#104 walk-forward backtester, #173 test_main.py with TRADING_PAUSED, #184 partial bars) might still apply.

3. **`Close stale PRs #93, #116, #179, #203 with appropriate "superseded by ..." comments`** — bulk PR cleanup. #93 is moot (no BaseBroker post-pivot); #116 superseded by #213 README rewrite; #179 superseded by `556da16` superpowers adoption; #203 superseded by #193 merge.

4. **`Update docs/handover/README.md — the "Don't forget" template defaults are pre-pivot (Alpaca brackets, pre-market scan, tools/risk.py, DataFeed.IEX); replace with post-pivot invariants from CLAUDE.md`** — small docs PR, ~50 lines. Dispatches `docs`.

5. **`Once IB Gateway is up, run venv/bin/python daily_check.py --dry-run and verify the audit row outcome is dry_run:would_flip_long or dry_run:no_change (not error:tws_disconnect)`** — Monday/Tuesday verification step. Confirms the broker side of the pipeline works before flipping cron live.

6. **`Clean up stale worktrees: git worktree list shows 8 dirs from prior sessions. Run git worktree prune and manually rm -rf the orphan dirs in .claude/worktrees/.`** — housekeeping, low priority.
