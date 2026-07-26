**Date:** 2026-07-25 (UTC)
**Slug:** candlestick-search-egress-blocked
**Author:** Claude Code session (claude-opus-5)

---

## 1. Sit-rep

The live UPRO/200-DMA bot is **untouched and running** — every change this session was research-only under `backtest/` and `docs/`. The session set out to build a profitable candlestick strategy autonomously over 24h with a weekly review loop, and delivered the complete machinery for it: a long/short bracket engine, 14 candlestick pattern detectors, two frozen pre-registered grids (28-cell context-free + 56-cell trend-context), a firing-rate calibration diagnostic, a machine-readable tested-cell ledger, and a deterministic weekly-review generator with a Saturday cron. **It produced zero verdicts.** Every market-data host is 403-denied by this environment's egress policy, so both grids could only be run on real GOOG daily bars bundled inside the `backtesting` PyPI wheel — `DIRECTIONAL` power (n_w=8), wrong instrument, explicitly not the pre-registered read. Active branch is `claude/bot-candlestick-strategy-8m0hoc`, PR **#435** (draft, CI green on `b2b72ac`), tracked by batch issue **#436**. The single blocker is the egress allowlist; the operator has agreed to set it but as of 12:00Z it is not live.

## 2. In-flight branches & PRs

- **Branch / PR** — `claude/bot-candlestick-strategy-8m0hoc` / **#435** (state: **draft**, CI **green** on `b2b72ac`).
  - **Purpose** — the whole candlestick search: detectors, both grids, calibration diagnostic, ledger, weekly review loop.
  - **Status** — 6 commits, all CI-green, 726 local tests passing (`pytest -m "not slow"`). Everything is committed and pushed; working tree clean, no stash, no worktrees. **§7 of both pre-registrations is deliberately empty** — the SPY read has never run. The GOOG results live in clearly-fenced sections (`§7.0` in the v1 doc, `§6` in the v2 doc) that state up front they are *not* the answer.
  - **Next action** — waiting on the egress allowlist. The moment a data host opens, run the sequence in §8 prompt 1. Do **not** merge before then unless the operator wants the machinery landed independently of the verdict.

- **Branch / PR** — `handover/candlestick-search-egress-blocked-2026-07-25` / this document (state: **draft**).
  - **Purpose** — this handover.
  - **Status** — docs-only, one file.
  - **Next action** — operator flips to ready if they want it on `main`.

## 3. Open issues being worked

- **`#436` — Batch: candlestick strategy search + research self-improvement loop** — labels: `enhancement`.
  - **What we learned** — Candlestick *patterns* were genuinely untested here (they appear only as a keyword list in `docs/research/swing-trading/keywords.md:44-53`); every prior kill was an *indicator* family. On GOOG the class produced **0/28** context-free and **0/56** with a trend filter. The filter did not rescue anything. Carries a decision log D1–D6.
  - **Next move** — pick up: run the SPY read, fill both §7s, flip the ledger records from `PENDING`, then resume widening (M3).

- **`#422` — Feasibility study: short-horizon rule-based entry system** — labels: `enhancement`. Status: answered NO-GO, operator left it open.
  - **What we learned** — This session did **not** reopen it and must not be read as doing so. #422's revisit criterion asks for a *non-candle* signal shape; a candlestick pattern is plainly not one. The candlestick work sidesteps #422 on **cadence only** — both its walls (cost drag at 1-minute, free intraday history not reaching n_w=13) are properties of *frequency*, and #422 §3 itself says only *daily* clears.
  - **Next move** — leave to the operator to close. Do not cite the candlestick work as reopening it.

- **`#420` — giveback floor** / **`#421` — multi-instrument concentration** — labels: `enhancement`. Untouched this session.
  - **What we learned** — `#421` is the direction #422's own verdict names as the evidence-backed path; the new ledger reports `vol_regime_gating` / `cross_sectional_rv` / `multi_instrument_rotation` as **NOVEL**, consistent with that.
  - **Next move** — hand to Lead when the candlestick thread closes.

- **`#229` / `#230`** — MVP 2.0 soak + go-live. Untouched. **Next move** — unrelated to this thread.

## 4. Decisions made this session

- **Decision** — Engulfing/harami containment is **inclusive** (`≤`/`≥`), not strict.
  - **Rationale** — On SPY/ES the open frequently sits exactly at the prior close, so a strict test makes these patterns fire only on **gap days** — the gap, not the geometry, becomes the signal. Caught as structurally-zero trades on a *synthetic no-gap frame*.
  - **Consequence** — This was a definitional correction made **before any real-data result existed**, not a response to performance. Do not "fix" it back. Pinned by `test_engulfing_fires_when_open_equals_prior_close_no_gap`.

- **Decision** — Both `reversal` **and** `continuation` context modes frozen (v2 = 56 cells, not 28).
  - **Rationale** — The approved plan named only `reversal`. Freezing both canonical readings removes any ability to pick the flattering one after seeing results.
  - **Consequence** — A tightening of the discipline, not a loosening. Cumulative family N is **84**, not 56.

- **Decision** — Widening **PAUSED** before round 3 (time-stops, vehicle robustness).
  - **Rationale** — Another grid against the *wrong instrument* at `DIRECTIONAL` power buys no verdict while permanently raising the cumulative-N bar any real survivor must clear. "Keep widening" was authorised; inflating N for nothing was not.
  - **Consequence** — Do **not** run M3 until the SPY read has landed. Resume order: time-stops → vehicle robustness → multi-pattern confluence last (that is where overfitting lives).

- **Decision** — The weekly review is **deterministic**, not LLM-driven.
  - **Rationale** — Same ledger ⇒ byte-identical review, so weeks are comparable; and the workflow needs **no secrets**, so it cannot silently stop running when a credential rotates.
  - **Consequence** — Judgement belongs in the issue the workflow opens, not in `backtest/weekly_review.py`. Do not add a narrative generator.

- **Decision** — v2's pre-registration is **not clean on one axis**, and says so in its `§0`.
  - **Rationale** — The GOOG numbers were seen before the doc was committed. The grid itself was frozen in the approved plan beforehand and the SPY read is still unseen.
  - **Consequence** — Do not quietly upgrade that claim. `§0` carries a four-row table showing exactly which parts are clean.

- **Decision** — Firing-rate calibration mode is **exempt from the power gate**.
  - **Rationale** — Firing rates are a property of the detectors, not a performance claim, so a shallow frame answers them safely.
  - **Consequence** — `--firing-rates` returns 0 on an `UNDERPOWERED` frame where the grid returns 2. Two tests pin that it prints no Calmar and no cell table.

- **Decision** — Reviews live in `docs/research/reviews/`, **not** `docs/trading-journal/`.
  - **Rationale** — That directory's README explicitly excludes research artefacts; the journal is for weeks the live bot traded.
  - **Consequence** — `docs/research/reviews/2026-W30.md` is the first entry.

## 5. Open questions

- **Question** — Will the egress allowlist reach an already-running session, or is a fresh session required?
  - **What blocks the answer** — Undocumented. The official docs describe the setting but not its propagation to live sessions. Re-probed four times across ~30 minutes; still 403.
  - **Suggested next step** — Re-probe once; if still 403, **start a fresh session**. Everything is pushed, so nothing is lost. Exact settings path is in `/root/.claude/plans/create-a-plan-to-zany-canyon.md` and §7 below.

- **Question** — Does `hammer` survive on SPY, or is it noise?
  - **What blocks the answer** — The SPY read. `hammer` was the top cell in **both** grids (v1 R3 +0.2792 vs random twin −0.1654; v2 continuation R3 +0.2929), but on 30–45 trades at cumulative N=84 that is well inside what noise produces — and `morning_star`/R2 was *beaten* by its own twin.
  - **Suggested next step** — First cell to inspect once SPY data lands. **Not** evidence of edge today.

- **Question** — Is the `continuation` > `reversal` ordering real or a vehicle artifact?
  - **What blocks the answer** — GOOG ran ~100→800 over the test window, so "long in an uptrend" is largely beta. Notably the `reversal` arms did **not** outperform, which is the *opposite* of doctrine if the patterns rather than the trend were driving it.
  - **Suggested next step** — SPY (a much less trending vehicle over 1993–2026) discriminates this directly.

- **Question** — Can the scheduling tool be approved so the check-in timer and the Claude-side weekly loop arm?
  - **What blocks the answer** — `mcp__…__send_later` returns `requires approval`; the operator said they would approve but it had not propagated by 12:00Z.
  - **Suggested next step** — Operator approves. The GitHub Actions half of the weekly loop works **without** it.

## 6. Files to read first

- `backtest/candlestick.py:1` — 14 detectors, `PATTERNS` registry (the multiplicity source), `context_mask`, `firing_rates`. Start here.
- `backtest/run_candlestick_study.py:78` — v1 frozen grid (`ARMS`, `R_GRID`, `N_CELLS=28`), `bracket_levels`, `cell_status`, the power gate.
- `backtest/run_candlestick_context_study.py:64` — v2 grid, `CONTEXT_GRID`, `CUMULATIVE_N=84`.
- `backtest/tested_cells.py:1` — the ledger. `check_novel()` before proposing any new grid.
- `backtest/weekly_review.py:67` — `PROPOSAL_RULE` and `UNTESTED_CANDIDATES`.
- `docs/research/2026-07-25-candlestick-pattern-preregistration.md` — v1 bar/grid; `§7` empty, `§7.0` holds the GOOG read.
- `docs/research/2026-07-25-candlestick-context-preregistration.md` — v2; read `§0` (ordering disclosure) first.
- `docs/runbooks/orb-data-drop.md` — the no-egress CSV route for both studies.
- `backtest/bracket.py:158` — `simulate_bracket(..., direction=)`, the frozen fill/tie-break conventions.

## 7. Don't forget

**Session-specific:**

- **Everything above is research-only.** `backtest/` is never imported by `supabase/functions/`; `compute_target_state` is unchanged. No candlestick rule is live and none is authorised to go live.
- **Do not retune a frozen parameter in place.** v1's thresholds (`§3.1`) survived real-bar calibration (0/14 miscalibrated). Any change needs a **new** pre-registration, not an edit.
- **A §7 results commit must be strictly later than its freeze commit.** Verify with `git log --oneline -- <doc>` before opening the PR.
- **`DATA_BLOCKED` and `PENDING` are not evidence.** Never cite them as negatives. `DIRECTIONAL_NO_GO` is suggestive only and is legitimately re-testable at full power.
- **Every new grid needs its own pure-noise negative control.** A grid without one is not finished.
- **`/data/` is gitignored** (`.gitignore:37`). Cached frames work locally but cannot be committed — do not tell anyone to "commit `data/…`".
- **CI is the arbiter**: Python 3.9 + `pandas==2.2.3` + `pytest -m "not slow"`, and `deno task test` on Deno v2.8.2. Local venv here is 3.11 + pandas 3.0.5. **`jsr.io` is blocked, so `deno task test` cannot run locally** — never claim TypeScript verification from this environment.
- **Cumulative multiplicity, not per-round.** The DSR bar uses N=84 today. Widening raises it; it never lowers it.

**Standing invariants (current, per `CLAUDE.md`):**

- **No LLM in the trading path.** `daily-check`, `kill-switch` and `panic` import no model SDK. Mechanically enforced by `supabase/functions/_shared/invariants.test.ts`.
- **One decision rule.** SPY close vs SPY 200-DMA, modulated by the kill-switch flag, via `computeTargetState` in `supabase/functions/_shared/regime.ts`. A candidate must **replace** it, never run in parallel.
- **`bot_config.paused=true`** halts new entries (`skipped:trading_paused`); the kill-switch is unaffected and keeps protecting an open position. Set via the `panic` Edge Function — **not** the retired `TRADING_PAUSED` env var.
- **Engineer subagents must never execute against the live broker.** `CLAUDE_AGENT_NO_BROKER=1` makes `placeMarketOrder` / `liquidate` / `cancelAllOrders` raise `BrokerCallBlockedError`. Mock all Alpaca calls; `logic.ts` takes an injected `deps` object.
- **Every Python file starts with `from __future__ import annotations`** (3.9 runtime).

> ⚠️ **`docs/handover/README.md`'s standing "Don't forget" list is stale.** It cites `tools/risk.py`, `TeamLeaderAgent`, `TRADING_PAUSED`, `DataFeed.IEX` and a pre-market scan cron — all superseded by the 2026-05-07 rules-engine pivot and the MVP 2.0 Alpaca/Supabase migration. `CLAUDE.md` is the authority; the list above reflects it. **Worth a Docs fix.**

## 8. Suggested next prompts

1. `Re-probe the egress hosts. If any market-data host is open, pull SPY daily 1993+ on branch claude/bot-candlestick-strategy-8m0hoc, assert describe_power() returns PROMOTABLE, then run backtest.run_candlestick_study and backtest.run_candlestick_context_study against it plus the #398 gate at cumulative N=84. Fill §7 of both pre-registrations in a strictly later commit than their freeze commits, flip the affected backtest/tested_cells.py records from PENDING to the real verdict, regenerate docs/research/reviews/2026-W30.md, and push. Refs #436.`

2. `The egress allowlist did not reach this session. Read docs/runbooks/orb-data-drop.md and tell me exactly what CSV to export so backtest.run_candlestick_study can run with --data, then wait for the file.`

3. `Work on issue #436, package M3: resume the paused widening. Freeze a pre-registered time-stop-exit grid for the candlestick family, reusing backtest/candlestick.py and backtest/run_candlestick_study.py, and report BOTH the new grid's N and the cumulative family N. Only start this if §7 of both existing pre-registrations is already filled.`

4. `Ask Docs to fix the stale standing invariant list in docs/handover/README.md §7 — it references tools/risk.py, TeamLeaderAgent, TRADING_PAUSED, DataFeed.IEX and a pre-market scan cron, all superseded by the 2026-05-07 pivot and the MVP 2.0 migration. CLAUDE.md is the authority.`

5. `Review PR #435 against the CLAUDE.md architectural invariants and the pre-registration discipline, paying particular attention to §0 of docs/research/2026-07-25-candlestick-context-preregistration.md, which discloses that the GOOG numbers were seen before that document was committed.`
