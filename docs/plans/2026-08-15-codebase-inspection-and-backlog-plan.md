# Codebase Inspection and Backlog Scoping Plan

Generated: 2026-08-15
Method: Three-agent parallel inspection (TS/migrations, Python/web, issue validation) + pygount LOC analysis + test suite verification

---

## Part 1: Codebase Inspection

### 1.1 Size and Composition (pygount)

379 analyzed files, 88,777 code lines, 32,921 doc/comment lines.

| Language | Files | Code | Docs |
|----------|------:|-----:|-----:|
| JSON | 34 | 51,185 | 0 |
| TypeScript | 72 | 18,412 | 4,376 |
| Python | 99 | 17,433 | 6,980 |
| YAML | 6 | 686 | 366 |
| TSX | 4 | 420 | 78 |
| Bash | 4 | 253 | 137 |
| Transact-SQL | 15 | 248 | 408 |
| TOML | 1 | 140 | 218 |
| Markdown | 144 | 0 | 20,358 |

Key takeaway: ~37K LOC of executable code (TS+Python+SQL+Bash+TSX), heavily documented (20K lines of Markdown). The JSON blob is mostly test fixtures and lock files.

### 1.2 Production Code (supabase/functions/)

Five Edge Functions, each split as index.ts (HTTP entry) + handler.ts (auth/routing) + logic.ts (pure, testable):

| Function | Purpose | Status |
|----------|---------|--------|
| hourly-check | Hourly candlestick bot: scans bars, decides entries/exits, places brackets | ACTIVE (cron `7 13-21 * * 1-5`) |
| kill-switch | Intraday drawdown protection, runs every 5 min during market hours | ACTIVE (cron `*/5 13-21 * * 1-5`) |
| panic | Deterministic kill button (pause/resume/cancel/liquidate), token auth | ON DEMAND |
| status | Read-only digest of bot state, positions, scans, trades | ON DEMAND |
| daily-check | Deprecated SPY 200-DMA regime bot | RETIRED (cron removed in migration 0013) |

Shared modules in _shared/ (20 source files + 14 test files):
- Core trading: hourly_signal.ts, candlestick.ts (14-detector registry), regime.ts
- Infrastructure: alpaca.ts (broker client + paper guard), db.ts, config.ts, supabase_client.ts
- Support: notifications.ts, outbox.ts, marketdata.ts, num.ts, auth.ts
- Safety: invariants.test.ts (mechanically enforces "no LLM in trading path")

Test coverage: 1059 TS tests pass, 0 fail, 24 ignored. Every source file has a corresponding test file except handler.ts files (some have tests, some don't). The test pattern is dependency injection via a `deps` object with mocked broker/db/notifications.

15 SQL migrations (0001-0015): schema init, cron schedules, vault grants, trade claims, equity snapshots, notification outbox, bar claims, hourly scans, daily-check retirement, hourly cron activation, HTTP timeout budget.

### 1.3 Research Code (backtest/, strategy/)

~16,470 LOC across 51 Python files. All research-only, not in the trading path. Includes:
- Strategy implementations: regime.py, orb.py, candlestick studies, forex survey, Elliott wave
- Backtesting infrastructure: walkforward.py, baselines.py, families.py, weighted_simulator.py
- Studies: leveraged regime, MES swing, FX EW calibration, options pricing
- Nightly reflection engine: reflection.py, run_nightly_reflection.py

Compliance: 99/102 Python files have `from __future__ import annotations`. The 3 exceptions are __init__.py files (empty, exempt). No TODO/FIXME/HACK comments found.

1017 Python tests pass, 0 fail.

### 1.4 Web Dashboard (web/)

Next.js app, ~829 LOC. Single-page dashboard showing hourly bot status, recent scans, positions, daily verification digests. Minimal -- 4 TSX files, 4 lib modules. Has its own CI workflow (web-ci.yml) for typecheck/build. No test files (CI relies on `next build` succeeding).

Known issue: #544 -- failed Alpaca API reads render as "no position" rather than surfacing the error.

### 1.5 Health Indicators

- TS tests: 1059 passed, 0 failed
- Python tests: 1017 passed, 0 failed
- Git: clean working tree on main, up to date with origin
- Stale branches: ~15 local worktree-agent-* branches (cleanup candidates)
- CI workflows: 6 (daily-verification, deadman-watchdog, deploy-dev, heartbeat, web-ci, weekly-research-review)

---

## Part 2: Issue Backlog Verification

22 open issues assessed. Classification:

### Already Fixed / Mostly Done (3 issues -- CLOSE THESE)

| Issue | Title | Verdict | Notes |
|-------|-------|---------|-------|
| #544 | Web dashboard renders failed Alpaca reads as positive claims | FIXED | Commit f0ab0db fixed this. page.tsx:303-308 now distinguishes account=null (API failure) from openPosition=null (no position). Close it. |
| #545 | Batch: automate the daily soak verification | IMPLEMENTED | scripts/daily_verify.ts (1086 lines, 115 tests) + workflow + PRs #550-553/#563 all merged. Automation is live. Remaining unchecked boxes are tracked as #554/#555/#558. Close it. |
| #479 | Rollout: deploy to dev/paper, captures, marker pin, cron | MOSTLY DONE | PR #484 merged (captures, Layer-B, deploy), migration 0014 (cron) exists, runbook (749 lines), paper bot live and soaking (9+ verified days). Checklist never updated. Close with summary comment. |

### Actionable Bugs (3 issues)

| Issue | Title | Verdict | Notes |
|-------|-------|---------|-------|
| #543 | hourly_kill_switch never written to trades | VALID | "hourly_kill_switch" is in TRADE_REASONS enum but never passed to insertTrade. Kill-switch exits use reason:"kill_switch" from kill-switch/logic.ts. Hourly bot's session-close flatten uses "hourly_session_close_exit". Exits are unattributable. |
| #513 | reconcile() adopts fills by fixed time window | VALID | logic.ts:438/489 still uses [bar_ts+1h, bar_ts+2h) window. No entry-keyed adoption. Low reachability (off-cadence only) but structurally incorrect. |
| #497 | Flatten alert misattributes "no re-leggable provenance" | VALID | logic.ts:632 still says "had no resting legs and no re-leggable provenance; flattened". Caught error at line 598 is discarded (catch (_e)). Fix not applied. |

### Documentation Gaps (3 issues)

| Issue | Title | Verdict | Notes |
|-------|-------|---------|-------|
| #539 | CLAUDE.md kill-switch section has wrong order/naming | VALID | Section describes /v2/clock before position check and names getPosition; actual code checks positions first and uses getOpenPositions. |
| #504 | CURRENT_CONFIG.md missing HOURLY_* settings | VALID | No HOURLY_* or SIZING_* entries in the doc. Deployed values unreadable via secrets list (digests only). |
| #573 | Em-dash convention sweep | VALID | Style rule says no em dashes but existing docs are saturated. Needs a policy decision before sweeping. |

### Enhancements / Feature Requests (5 issues)

| Issue | Title | Verdict | Notes |
|-------|-------|---------|-------|
| #554 | Restore pg_net stall check via security-definer RPC | VALID | Substitute latency check exists but misses HTTP-response-level timeouts. Needs SQL function + evaluator wiring. |
| #555 | Namespace daily-verification artifacts per environment | VALID | Prerequisite for prod activation. Both legs would collide on same-date paths. |
| #558 | Latency check WARNs too eagerly on entry days | DEFERRED | Deliberately not ready: needs ~5 entry days of data (currently has 1). Wait a few weeks. |
| #499 | SIZING_RISK_PCT is inert | PARTIALLY FIXED | PR #568 documented the notional cap as operative sizer (comments in logic.ts:362-365, .env.example:22-23). Documentation path taken from acceptance criteria. Could be closed. |
| #491 | Two DB-gated tests assert wrong timestamptz spelling | VALID | Tests at db.test.ts:1005 and :1300 use string equality with 'Z' suffix; PostgREST returns '+00:00'. Only fails under RUN_DB_TESTS. |

### Ops / Process Issues (3 issues)

| Issue | Title | Verdict | Notes |
|-------|-------|---------|-------|
| #535 | EOD SQL verification for 2026-08-05 | STALE | Trading day passed 10 days ago. Close as completed or expired. |
| #587 | Run first weekly reflection after a few trading days | WAITING | Needs 3-5 reflected trading days. First fully reflected week is W34 (Aug 17-21). Ready mid-next-week. |
| #479 | Rollout: deploy to dev/paper, captures, marker pin, cron | MOSTLY DONE | Paper soak is live (#229). Captures and Layer-B marker likely done. May need closure or remaining-item check. |

### Automated Trackers (5 issues -- non-actionable)

| Issue | Title | Verdict |
|-------|-------|---------|
| #589 | Research review 2026-W33 proposal | AUTO -- mechanical weekly proposal, judgement call for operator |
| #560 | Research review 2026-W32 proposal | AUTO -- same, older week |
| #500 | Research review 2026-W31 proposal | AUTO -- same, oldest |
| #564 | [daily-verify] 2026-08-07: 1 finding | AUTO -- automated daily-verify finding (kill_switch 107/108) |
| #559 | [daily-verify] 2026-08-07: 1 finding | AUTO -- duplicate of #564, same date/finding |

### Blocked / Tracking (2 issues)

| Issue | Title | Verdict |
|-------|-------|---------|
| #230 | Go-live to prod | BLOCKED -- waiting on clean paper soak + prerequisites |
| #229 | Paper soak tracking | TRACKING -- dev paper soak, close when go-live or abandon |

---

## Part 3: Prioritized Action Plan

### Tier 1: Immediate Fixes (bugs affecting correctness/attribution)

These are real bugs in production code that affect data integrity or operator visibility.

**Wave 1A (parallel, no dependencies):**

1. **#543 -- Write hourly kill-switch exits to trades table**
   - Scope: Add a trades INSERT in kill-switch/logic.ts when it liquidates
   - Risk: Medium (touches trading path, but kill-switch is protective, not entry logic)
   - Size: S (under 1h)
   - Approach: TDD via logic.ts injection pattern, mock db in tests

2. **#544 -- Surface Alpaca API failures on web dashboard**
   - Scope: Distinguish null-from-API-failure vs null-from-empty in web/app/page.tsx
   - Risk: Low (read-only dashboard, no trading impact)
   - Size: S
   - Approach: Propagate error state from alpaca.ts through to the component, render error banner

3. **#491 -- Fix timestamptz spelling in DB-gated tests**
   - Scope: Change string equality to Date.parse comparison in db.test.ts:1005 and :1300
   - Risk: Very low (test-only, RUN_DB_TESTS-gated)
   - Size: S
   - Approach: Instant-based assertion, verify against local Postgres

**Wave 1B (after 1A, slight dependency on understanding trades schema):**

4. **#513 -- Key reconcile() adoption by entry_order_id, not time window**
   - Scope: Rewrite db.ts:reconcile() to match fills by broker_order_id/entry_order_id
   - Risk: Medium-High (touches journal integrity path, needs careful preservation of #480 recovery)
   - Size: M (needs sub-plan)
   - Approach: Sub-plan first, TDD, verify #480 recovery case preserved

### Tier 2: Documentation Correctness (quick wins, prevent confusion)

Can run in parallel with Tier 1.

5. **#539 -- Fix CLAUDE.md kill-switch section ordering and naming**
   - Scope: Rewrite the Intraday kill-switch section to match actual code (positions-first, getOpenPositions)
   - Risk: None (docs only)
   - Size: S
   - Also: fix docs/CURRENT_CONFIG.md:14

6. **#504 -- Record HOURLY_* settings in CURRENT_CONFIG.md**
   - Scope: Document every HOURLY_* and SIZING_* setting with source attribution
   - Risk: None (docs only)
   - Size: S
   - Blocker: Need operator to run `supabase secrets list` and attest values (secrets show digests)

7. **#499 -- Mark SIZING_RISK_PCT as inert in .env.example**
   - Scope: Add comment in .env.example noting the notional cap is operative; PR #568 already documented this in docs
   - Risk: None
   - Size: S

8. **#573 -- Decide em-dash policy and sweep (or amend rule)**
   - Scope: Make the style decision (sweep vs tolerate), then execute
   - Risk: None (style only)
   - Size: S
   - Decision needed: which files are frozen records?

### Tier 3: Feature Enhancements (infrastructure hardening)

These strengthen observability and prepare for prod.

9. **#554 -- Security-definer RPC for pg_net stall check**
   - Scope: SQL function wrapping net._http_response query, wire into daily-verification evaluator
   - Risk: Low-Medium (new SQL function, least-privilege grants)
   - Size: M
   - Dependency: Understanding of net schema and minute=7 filter

10. **#555 -- Namespace daily-verification artifacts per environment**
    - Scope: Add environment dimension to ledger/digest paths, migrate existing artifacts
    - Risk: Medium (dashboard reader needs updating, existing data needs migration)
    - Size: M
    - Prerequisite for #230 (prod go-live)

11. **#497 -- Improve flatten alert message specificity**
    - Scope: Include caught error message in the flatten notification in logic.ts
    - Risk: Low (alert message only, no control flow change)
    - Size: S

### Tier 4: Deferred / Waiting

12. **#558 -- Calibrate latency check thresholds**
    - WAIT: Needs ~5 entry days of data (has 1). Revisit in 2-3 weeks.

13. **#587 -- Run first weekly reflection**
    - WAIT: First fully reflected week is W34 (Aug 17-21). Ready mid-next-week.

### Tier 5: Hygiene (close/stale)

14. **Close #535** -- Day 3 SQL checklist for Aug 5, trading day long passed
15. **Close #559** -- Duplicate of #564 (same date, same finding)
16. **Evaluate #479** -- Most rollout items likely complete; check remaining and close or trim
17. **Clean up local worktree-agent-* branches** -- ~15 stale local branches from agent sessions

### Execution Order

```
Immediate (today):
  CLOSE #544 (already fixed by commit f0ab0db)
  CLOSE #545 (automation implemented and live)
  CLOSE #479 (rollout substantively complete, paper bot soaking)
  CLOSE #535 (manual checklist superseded by automated verification)
  CLOSE #559 (duplicate of #564)
  CLOSE #499 (documentation path completed via PR #568)
  CLEAN UP ~15 stale local worktree-agent-* branches

Week 1 (parallel waves):
  Wave 1: #543, #491, #539, #504, #573 (all small, independent)
  Wave 2: #513 (depends on trades schema familiarity from #543)

Week 2:
  #554, #555, #497 (medium enhancements)

Week 3+:
  #558 (when data arrives), #587 (when reflections accumulate)
  Assess #229/#230 readiness for prod go-live
```

### Revised Issue Counts

- Already fixed/closeable NOW: 6 (#544, #545, #479, #535, #559, #499)
- Actionable bugs: 3 (#543, #513, #497)
- Doc gaps: 3 (#539, #504, #573)
- Enhancements: 4 (#554, #555, #558, #491)
- Auto/non-actionable: 3 (#589, #560, #500)
- Blocked/tracking: 2 (#230, #229)
- Waiting: 1 (#587)
- TOTAL: 22 --> 16 remain after immediate closures

### What NOT to do now

- Do NOT touch #230 (prod go-live) -- still blocked on paper soak confidence
- Do NOT implement #558 -- premature without entry-day data
- Do NOT action #589/#560/#500 -- automated proposals, operator judgement call
- Do NOT add a second decision rule (architectural invariant #1)
