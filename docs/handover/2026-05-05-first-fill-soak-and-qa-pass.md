**Date:** 2026-05-05 (UTC)
**Slug:** first-fill-soak-and-qa-pass
**Author:** Claude Code session (claude-opus-4-7)

## 1. Sit-rep

The bot is on `main` at `d602ad1` (v1.13.0), deployed to the VPS. Today's 13:25 UTC cron produced the **first live fill since the v1.10–v1.13 safety stack landed** — AMD 41 sh @ $350.47 with full bracket legs live on the broker. Two other risk_review-approved candidates (AAPL, SHEL) were correctly rejected by the deterministic exposure cap (28.1% / 32.3% NAV vs 20% cap). The user explicitly chose to **soak** today rather than ship optimisations, so no code merged this session — only a QA validation pass that filed four low-priority follow-up issues (#131–#134) against gaps it found in our load-bearing claims about the new stack. AMD is the only open position; portfolio was flat at session start (META was liquidated yesterday via the new panic CLI). Tomorrow's 13:25 UTC cron will run normally.

## 2. In-flight branches & PRs

- **Branch / PR** — `handover/first-fill-soak-and-qa-pass-2026-05-05` / draft PR for this handover doc itself.
- **Purpose** — Persist this session's context for the next Claude session.
- **Status** — Doc-only. User reviews and flips to ready themselves.
- **Next action** — User decides when to merge.

Pre-existing PRs in the repo, NOT from this session and untouched:

- **#116** — `docs/readme-ssh-line` (ready, not draft) — pre-existing docs PR.
- **#93** — `claude/evaluate-mql5-trading-Kt8Os` (draft) — broker-abstraction spike, pre-existing.

Stale worktrees from yesterday's sessions (cleanup still pending; `git worktree remove --force <path>` after `git worktree unlock <path>`):

- `/opt/trading-bot/.claude/worktrees/agent-a82e1da96fb23aaaf` — feat/122 (merged)
- `/opt/trading-bot/.claude/worktrees/agent-a9aa8b6aa609e39f9` — feat/103-panic-cli (merged)
- `/opt/trading-bot/.claude/worktrees/agent-ad20a305d0e64c85c` — pr-125-review (merged)
- `/opt/trading-bot/.claude/worktrees/agent-ae56be74b1e9bdc61` — feat/123 (merged)
- `/opt/trading-bot/.claude/worktrees/docs-v1.13-panic` — docs/v1.13 (merged)
- `/opt/trading-bot/.claude/worktrees/readme-ssh-tweak` — docs/readme-ssh-line (PR #116, still open)

## 3. Open issues being worked

Issues this session opened (all from the QA validation pass — none live-affecting; default `status: triage`):

- **`#131` — Position monitor never persists MonitorAction rows — no DB audit trail** — `bug, priority: low`. Code creates `MonitorAction` objects in memory; only `monitor.log` keeps the audit trail. CLAUDE.md says "records a `hold/skipped_error` MonitorAction" — true in code, false in the database.
  - **Next move** — Lead triage; small-scope Engineer task. Add an `insert_monitor_action` call in `run_monitor`.
- **`#132` — `trades.entry_price` stores pre-order quote, not actual broker fill_price** — `bug, priority: low`. AMD today: 349.76 stored vs 350.47 actual (~0.2% drift). Biases every R-multiple and PnL row in the DB.
  - **Next move** — Lead triage; Engineer task to read fill from broker response after `place_market_order` and update the row.
- **`#133` — Bracket stop_price uses pre-order quote, not post-fill anchor — drift exceeds invariant under fill slippage** — `bug, priority: low`. CLAUDE.md "fresh quote at submission" wording is technically truthful but slightly overstates the guarantee. AMD's drift today was 0.2%, comfortably inside the ±5% R:R tolerance.
  - **Next move** — Either tighten code (re-anchor brackets after fill — non-trivial; Alpaca bracket legs are submitted with parent so amend would be required) or relax doc wording. Defer until #132 is in flight; same root cause.
- **`#134` — `MONITOR ERROR` aborts whole hourly cycle on Alpaca network blip — per-iteration try/except only covers inner loop** — `bug, priority: low`. Defense-in-depth only — server-side bracket legs still fire regardless. Three historical aborts already in monitor.log.
  - **Next move** — Lead triage; small-scope Engineer task. Wrap the outer fetch (`get_alpaca_positions`) in its own try/except and skip cleanly with notify_error.

Older issues that survived from yesterday's "next steps" (untouched today):

- **`#102` — SPY 200-SMA regime gate (master kill-switch for new longs)** — `enhancement, strategy, priority: high, status: ready`. Strategic; the next strategic guardrail.
- **`#61` — Raise MAX_PORTFOLIO_EXPOSURE from 20% to 40-50%** — `enhancement, strategy, priority: high, status: blocked`. Blocked on observation; today's 1-of-3 fill rate adds one data point but a single day is not enough.
- **`#94 / #95 / #96` — Backtest realism + broker abstraction (status: ready, priority: medium)** — untouched.
- **`#104` — Walk-forward backtest harness** — `enhancement, priority: medium, status: ready`. Untouched.

## 4. Decisions made this session

- **Decision** — Do not ship cap-aware sizing in `tools/risk.py::calculate_position` today, even though it is the most surgical fix for the structural sizer/cap mismatch (1-of-3 fills today, 0-of-4 on 04-30, ~97% reject rate in the 5y backtest).
  - **Rationale** — User explicitly requested soak; today is the first live test of bracket submission, monitor isolation, and notification paths against a real position. Shipping a sizer change mid-soak conflates variables and makes the next day's PnL unattributable.
  - **Consequence** — Issue #61 (raise MAX_PORTFOLIO_EXPOSURE) and the cap-aware-sizer lever both stay parked. Re-evaluate when soak ends — minimum a few more cron runs.
- **Decision** — File QA findings about the v1.10–v1.13 stack as `priority: low, status: triage` rather than escalating, and do not dispatch Engineer.
  - **Rationale** — None of the four findings is live-affecting (AMD bracket legs verified live on broker, notifications working, monitor running clean). Low-noise capture for after-soak triage.
  - **Consequence** — Issues #131–#134 wait. If a future session asks "should we work on #131?", default is yes when soak ends; engineer effort on each is small.
- **Decision** — Saved a new feedback memory `feedback_soak_over_tweak.md` capturing the user's preference: during named soak windows, defer code changes (even pre-approved ones) so the soak data stays attributable. Emergency fixes for safety-stack failures override; optimisations do not.
  - **Rationale** — Pattern is repeatable and not previously captured; differs from `feedback_triple_check_before_shipping` (verification-before-ship) by being about deferral-during-observation.
  - **Consequence** — Future sessions seeing "soak day", "let's wait", "let it play out" should hold engineer dispatches by default.

## 5. Open questions

- **Question** — Will AMD's bracket legs (SELL LIMIT @ $422.12, SELL STOP @ $325.64) actually fire server-side when triggered, with monitor reconciliation matching?
  - **What blocks the answer** — The trade has not exited yet. This is the first live test of the bracket exit path under the new stack.
  - **Suggested next step** — When AMD closes (any path: stop, target, or max-hold), run a QA pass against the exit: did Alpaca fire the leg? did `position_monitor` reconcile? was Discord notified? does the `trades` row reflect the actual exit price?
- **Question** — Is the structural sizer/cap mismatch a product decision to leave alone, or do we ship cap-aware sizing in `calculate_position`?
  - **What blocks the answer** — Insufficient live observation. Today is data point #2 (after 04-30); we need a few more cron runs to see whether the 1-of-3 to 0-of-4 fill cadence holds, and whether the names that *do* fit the cap are profitable.
  - **Suggested next step** — Wait for soak to end (user-defined), then either run an Analyst spike on cap-aware sizing (lever 1) vs raising the cap (lever 2 / issue #61) vs trimming the watchlist (lever 3), or proceed straight to Engineer if the user has decided.

## 6. Files to read first

- `tools/risk.py` — `calculate_position` is cap-blind; this is the source of the structural sizer/cap mismatch. Any future "more deployment frequency" work starts here.
- `agents/team_leader.py:128-138` — fresh-quote bracket anchoring path. QA #133 found it anchors to pre-fill quote, not post-fill.
- `monitor/position_monitor.py:160-192` — per-iteration try/except (PR #118). QA #134 found the *outer* wrapper still aborts on top-of-loop blip.
- `tools/broker.py:38-50` — bracket-order submission. AMD today proves the 3-leg pattern works end-to-end.
- `tools/notifications.py:9-22, 87-92, 99-120` — `_post` silent-skip, `notify_error` 240+240 truncation, `notify_panic` shape. All verified working today.
- `~/.claude/projects/-opt-trading-bot/memory/feedback_soak_over_tweak.md` — new this session; load before any optimisation dispatch.
- `~/.claude/projects/-opt-trading-bot/memory/project_2026_04_30_first_safe_run.md` — explains *why* the cap rejects so many candidates (per-candidate ATR math). Companion baseline to today's run.
- `docs/handover/2026-05-04-v1.13-panic-cli-and-dry-run-safety.md` — yesterday's handover. Context for the v1.13 stack that today exercised.
- `CLAUDE.md` — Architectural-invariants section. Re-read before touching `tools/risk.py`, `agents/team_leader.py`, or the order-placement flow.

## 7. Don't forget

Session-specific:

- **Soak window is in progress.** Today was day 1 of live observation under the v1.10–v1.13 stack. Default response to "should we ship X?" during soak is **defer**, even for pre-approved work. See `feedback_soak_over_tweak.md`.
- **AMD is the only open position.** Portfolio was flat at session start. Don't reconcile against any stale memory of held positions.
- **DB measurement bias is live.** Per #132, `trades.entry_price` is the pre-order quote (~0.2% drift on AMD today). Treat any R/PnL number from the SQLite DB as having a small systematic bias until #132 ships. Broker P/L is the truth.
- **6 stale worktrees** (5 agent worktrees from 2026-05-04, plus `readme-ssh-tweak` from PR #116). Cleanup pending; `git worktree unlock <path>` then `git worktree remove --force <path>`.
- **`TRADING_PAUSED=false` and cron is live.** Tomorrow's 13:25 UTC scan will run.
- **Issues #131–#134 are deliberately at `priority: low`.** They are validation gaps, not live-affecting bugs. Triage as a batch when soak ends.

Standing invariants (from `CLAUDE.md`):

- The LLM must never control risk parameters directly. Stops and targets come from `tools/risk.py`; the position monitor is rule-based; only `TeamLeaderAgent` places orders, and only with pre-approved values.
- Stops and take-profits execute server-side via Alpaca **bracket orders**. The position monitor is defence-in-depth, not the primary exit mechanism.
- Morning scan must run **pre-market** (cron `25 13 * * 1-5` UTC). Running after 13:30 UTC produces ~zero `volume_ratio` and kills every entry.
- `TRADING_PAUSED=true` halts new entries but does not affect the position monitor. Faster path is `python main.py panic --pause`.
- Free Alpaca paper accounts require `DataFeed.IEX`; live SIP requires a paid account. Controlled via `DATA_FEED` env var.
- Every Python file starts with `from __future__ import annotations` (Python 3.9 runtime).
- `place_order(dry_run=True)` runs the deterministic safety stack (#127). Use `python main.py scan --dry-run` as a smoke test before any production-bound change to risk/order-placement code.
- `BaseAgent._handle_tool_calls` returns tool failures as `tool_result is_error: True` (#119), so a tool exception cannot crash the morning scan.

## 8. Suggested next prompts

1. **(After AMD closes — at a stop, target, or max-hold)** `Run QA on AMD's bracket-leg exit — verify Alpaca fired the leg, monitor reconciled, Discord notified, trades row reflects actual exit price.` Highest-value next observation; this is the only untested exit path in the new stack.
2. **(When user is ready to end the soak)** `Triage open issues` — Lead pass over #131, #132, #133, #134 plus the older `status: ready` queue (#102, #94, #95, #96, #104). Set priorities for the next sprint.
3. **(After triage)** `Work on issue #102` — SPY 200-SMA regime gate. Strategic, `priority: high, status: ready`. Pairs naturally with the panic CLI as a second new-entry-blocking layer.
4. **(After a few more soak days, if the 0-1 fill cadence holds)** `Investigate cap-aware position sizing in tools/risk.py::calculate_position` — Analyst spike. Compare lever 1 (clip notional inside `calculate_position`), lever 2 (raise MAX_PORTFOLIO_EXPOSURE — issue #61), lever 3 (trim watchlist toward higher-ATR names) against the 5y portfolio backtest. Do NOT dispatch Engineer until user picks a lever.
5. **(Cleanup, low-priority)** `Clean up stale worktrees in /opt/trading-bot/.claude/worktrees/` — six worktrees from prior sessions; all branches merged except `docs/readme-ssh-line` (PR #116, still open).
