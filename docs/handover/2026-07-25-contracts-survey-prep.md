**Date:** 2026-07-25 (UTC)
**Slug:** contracts-survey-prep
**Author:** Claude Code session (claude-fable-5)

## 1. Sit-rep

Production is unchanged: the deterministic UPRO 200-DMA regime bot on Supabase Edge Functions + Alpaca, one decision rule, no LLM in the trading path. This session ran two `/tm-advisor` batches to completion — **#405** (colleague-adopt-list + contracts pre-registration) and **#413** (contracts-survey-prep) — all PRs merged (#407–#411, #414/#417/#418/#419) and both batch issues closed. The contracts/leveraged-futures direction now has a frozen pre-registration (`#406`/PR #411), a facts-verification note (`#415`/PR #419), and a data-feasibility note (`#416`/PR #418) on `main`; the survey itself was **not** run. Since then the repo has pivoted toward short-horizon **candlestick / ORB / Turtle** equity strategies (#420–#436, incl. open draft PRs #435 and #437), so the contracts direction is currently **parked, not active**. Active branch when this was written: `main`, clean, synced at `60a9d77`. This handover exists to preserve the two open items on the contracts direction so they survive the parking.

## 2. In-flight branches & PRs

_None from this session — every batch PR merged._ For the record, the merged deliverables were:

- **PR #417** (`b61c0c7`) — post-merge nit sweep (#414), full tester+reviewer pipeline + a lead doc-accuracy fix.
- **PR #418** (`8048ffc`) — contracts survey data-feasibility spike (#416), **developer-complete, merged without the independent tester+reviewer pass** (see §4).
- **PR #419** (`3161157`) — contracts facts-verification (#415), same assurance caveat as #418.

Two PRs are open on `main` but belong to the **candlestick thread, not this session** — do not touch them here: **#435** (`claude/bot-candlestick-strategy-8m0hoc`, daily candlestick 28-cell pre-registration) and **#437** (`handover/candlestick-search-egress-blocked-2026-07-25`, that thread's own handover).

## 3. Open issues being worked

This session opened and closed all its own issues (#395–#398, #406, #414–#416 — all CLOSED COMPLETED). No open issue tracks the contracts direction's remaining decisions — that is itself a gap (see §5).

- **`#230` — MVP 2.0: go-live to prod (Alpaca live)** — labels `enhancement`, `status: blocked`. Untouched this session; still the standing gate before any live change.
- **`#436` — Batch: candlestick strategy search + research self-improvement loop** — `enhancement`. The current active batch; **owned by the candlestick thread**, listed here only so the next session knows where the repo's attention actually is.
- **`#420`/`#421`/`#422`** (giveback exit / UPRO-concentration / short-horizon feasibility) — `enhancement`. Also the candlestick/short-horizon thread, not this session.
- **Contracts direction — no tracking issue exists.** The §6 flag (§5 below) lives only inside the merged facts-verification doc. **Next move:** if the contracts direction is un-parked, file a tracking issue for the §6 decision before any survey work.

## 4. Decisions made this session

- **UPRO stays live until a candidate clears the pre-registered bar.** Rationale: the regime bot costs ~nothing to run; deprecating it on "boring" alone is a move to cash on no signal. Consequence: no research in this thread touches the live bot; a replacement needs to clear the #398 gate **and** after-tax Calmar vs SPY (~1.31 median, exactly `1.3085475049604838`), then a fresh ADR.
- **Contracts pre-reg freeze granularity:** `#406`/PR #411 freezes the promotion **bar** and the **instrument recommendation** (MES-class micro futures) at its merge SHA; it only **proposes** survey cells. Rationale: mirrors the forex staging precedent (feasibility gate → grid-frozen pre-reg → verdict). Consequence: the exact cell grid must be frozen in the *survey batch's own* pre-registration, not lifted from #406.
- **#415/#416 merged developer-complete**, without the independent tester+reviewer pass that #414 and the whole #405 batch received (they were merged directly on the other machine). Consequence: treat their numbers — especially the MES specs — as developer-verified only, not independently reviewed. The unverified MES multiplier (§5) is the concrete risk.
- **`_ZERO_VARIANCE_ATOL = 1e-12`** in `backtest/overfitting_gate.py`: the zero-variance Sharpe guard is a tolerance, not strict `> 0.0` — a strict guard let a constant column produce Sharpe ≈5.6e15 (caught by the #398 tester). Consequence: do not "simplify" it back to `== 0`.
- **No scipy** in the gate: normal CDF via stdlib `math.erfc`, inverse via Acklam's approximation — the repo deliberately avoids scipy (`docs/architecture/2026-07-05-codebase-map.md:91`). Do not add it.

## 5. Open questions

- **Does the MES-via-IBKR recommendation survive the §6 access-barrier flag?** `docs/research/2026-07-21-contracts-facts-verification.md` §6 raises a **committed-revision flag** (per the pre-reg's own §7 clause) against `#406`'s §2.5 "real, automatable, EU-reachable API" leg: a **BaFin 2022-09-30 futures-specific Allgemeinverfügung** (national tightening on retail *futures*, not just CFDs) plus IBKR's cash-only funding condition for German retail — both previously unpriced. **What blocks the answer:** a human decision, and first a confirmation the direction is still being pursued at all (the repo has pivoted to candlestick/ORB). **Suggested next step:** `/tm-advisor` brainstorm — decide un-park vs stay-parked; the frozen doc must NOT be edited except via a committed §7 revision.
- **MES contract specs (multiplier / tick value / margin) are still unverified.** CME's site IP-blocks fetches from this MacBook (9 URLs failed, proxy egress block); `#415` leaves them still-unverified and `#416` §4 fell back to Wikipedia for the multiplier + a secondary blog for the launch date, so the composite MES per-trip cost could not be computed and §2.5's cost-competitiveness claim is open. **What blocks the answer:** network access to `cmegroup.com`. **Suggested next step:** re-verify from an un-proxied machine/network, then reconcile #416 §4.

## 6. Files to read first

- `docs/research/2026-07-21-contracts-facts-verification.md` — the §6 committed-revision flag + the verified/still-unverified fact ledger (start here).
- `docs/research/2026-07-21-leveraged-contracts-preregistration.md` — the frozen bar, the §2.5 MES recommendation, and the §7 revision clause any change must go through.
- `docs/research/2026-07-21-contracts-survey-data-feasibility.md` — the data recommendation (SPY daily via Alpaca) and the intraday-floor probe results.
- `backtest/overfitting_gate.py` — the DSR + PBO/CSCV + block-bootstrap gate any candidate must clear; `docs/research/2026-07-21-overfitting-gate-usage.md` for when each sub-gate applies.
- `docs/research/2026-07-20-colleague-repo-audit.md` — why intraday, multi-signal-voting, and SL/TP-overlay shapes are already killed (do not re-propose them).
- `CLAUDE.md` — the Architectural invariants section (the safety contract; §7 below).

## 7. Don't forget

Session-specific first, then the current standing invariants.

- The §6 flag on `#406` is a **flag, not an edit** — the frozen pre-registration was deliberately left unchanged. Any revision goes through its §7 clause as a committed change, before results under the changed config are examined.
- `cmegroup.com`, EUR-Lex, and `stooq.com` are **egress-blocked from this MacBook** (Zscaler proxy). Broker/regulatory primary-source verification for the contracts direction must run from an un-proxied network.
- Operator action still open from batch #405: set the `NOTIFY_WEBHOOK_URL` GitHub Actions secret so `deadman-watchdog.yml` can post to Discord — until then a real incident opens a latch issue + a red run but sends **no** ping.

Current architectural invariants (from `CLAUDE.md` — **note:** the standing list in `docs/handover/README.md` §7 predates the 2026-05-07 pivot and references the retired IBKR/`tools/risk.py`/`TeamLeaderAgent` design; the items below supersede it and are the ones that actually apply):

- **No LLM in the trading path.** `daily-check`, `kill-switch`, `panic` import no model SDK. All strategy research (contracts, candlestick, ORB, Turtle) is research-only; nothing an LLM produces reaches order placement.
- **One decision rule.** SPY close vs SPY 200-DMA, modulated by the kill-switch flag, computed by the pure `computeTargetState`. A second rule (a contracts signal, a candlestick signal, anything) requires a fresh brainstorm + design spec and does **not** auto-go-live.
- **The live UPRO regime bot is unchanged by all this research.** Replacing it needs a candidate that clears the #398 gate + after-tax Calmar vs SPY (~1.31 median), then a fresh ADR — never an implicit swap.
- **Engineer subagents must never execute against the live broker.** `CLAUDE_AGENT_NO_BROKER` guards the mutating Alpaca helpers; all broker calls in agent-run tests must be mocked.

## 8. Suggested next prompts

Ordered by priority — paste the first if you only have time for one.

1. `/tm-advisor The candlestick/ORB direction (#436) is now active and the MES-contracts direction is parked. Decide: do we un-park the contracts direction to resolve the §6 access-barrier flag in docs/research/2026-07-21-contracts-facts-verification.md (BaFin 2022-09-30 futures Allgemeinverfügung + IBKR cash-only funding), or formally shelve it? If shelving, note it in the frozen pre-registration via its §7 revision clause.`
2. `On an un-proxied network, verify the MES contract multiplier, tick value, and exchange margin from CME primary sources, then reconcile the Wikipedia fallback used in docs/research/2026-07-21-contracts-survey-data-feasibility.md §4 and the still-unverified block in docs/research/2026-07-21-contracts-facts-verification.md.`
3. `/tm-advisor If the contracts direction is un-parked and MES survives the §6 flag: scope the contracts survey batch using the SPY-daily-via-Alpaca data path from docs/research/2026-07-21-contracts-survey-data-feasibility.md, cells cleared against backtest/overfitting_gate.py, grid frozen in this batch's own pre-registration.`
4. `Set the NOTIFY_WEBHOOK_URL GitHub Actions secret for sv-tmueller/trading-bot so deadman-watchdog.yml can post Discord alerts, then run one workflow_dispatch smoke test to confirm delivery.`
