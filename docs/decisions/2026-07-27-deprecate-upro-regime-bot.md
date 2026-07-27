# Deprecate the 3x UPRO / 200-DMA regime bot

**Date:** 2026-07-27
**Status:** accepted

---

## Context

The 3x UPRO / 200-DMA regime bot has run on Alpaca paper via the Supabase dev project
(`qdaxxsuicyiscdvsdowc`) since 2026-06-05. It took its first bot-executed position on 2026-06-11
and has held or adjusted a LONG UPRO position ever since, gated on the single decision rule
(`computeTargetState`, SPY close vs its 200-DMA). #230 (go-live to prod, `yomamlrozydhgleumnon`)
has never been executed — it remains OPEN with label `status: blocked`. The most recent soak-digest
comment on #229 (2026-07-24T22:33:49.929Z) recorded the bot's final observed live state before this
decision: `target_state`/`current_state` both `LONG`, position 7,511 `UPRO`, equity $1,023,683.82,
`paused: false`, `kill_switch_active: false`, and zero `error:*` outcomes in the trailing 7 days
(`success:within_threshold` 390, `skipped:market_closed` 150, `success` 10).

A paper-verification chain was re-run on 2026-07-27 (posted as a comment on #465) confirming: CI
deploys only to the dev/paper project ref (`deploy-dev.yml`); no prod status secrets exist
(`STATUS_URL_PROD`/`STATUS_TOKEN_PROD` absent from `gh secret list`); #230 (go-live) has never been
closed and carries no go-live comment; `config.ts` defaults `ALPACA_PAPER` to `"true"` and only an
explicit `ALPACA_PAPER=false` secret — never set per the go-live runbook, itself gated on #230 —
would flip it; and the funding/position trajectory recorded in the 2026-W25 trading-journal entry
(dev paper account named explicitly) is continuous with the 2026-07-24 digest. **Residual gap:** no
check available to the developer proves the *Alpaca* account itself is Paper (that needs
`/v2/account`, the Alpaca dashboard, or the Supabase secret value directly) — E1-E6 prove the
deployed stack is the dev project and that no live-cutover path was ever executed, but the final
proof point sits outside the developer's read access. This gap is closed procedurally: the operator
handoff for the liquidation curl (recorded below) requires the operator to confirm, before running
it, that the panic URL's project ref is `qdaxxsuicyiscdvsdowc` and that the Alpaca dashboard shows
the *Paper* account.

**Honest evidence context (non-negotiable, per #464).** The bot performed as designed: a clean
soak, zero unexpected `error:*` outcomes, the kill-switch never mis-fired, and market holidays
gated correctly on both `daily-check` and `kill-switch`. It is not being retired for a defect or a
demonstrated failure. No successor has cleared any bar: #422 (short-horizon entries) verified
NO-GO, #448 (candlestick family, closed at cumulative N=168) NO-GO, #457 (MES swing contracts,
closed at N=24) NO-GO. This decision replaces a working, evidence-backed rule with an as-yet
untested one, and is a departure from the #398 pre-registration discipline that #420/#421 were
sequenced behind. Paper-first is the operator's accepted risk container for that departure — the
hourly-candle successor (#466) is built and soaked on the same paper account before any go-live
question is revisited.

## Decision

Retire the 3x UPRO / 200-DMA regime bot by operator direction recorded on #464 (2026-07-27). Flatten
the position via `panic?action=liquidate` and hold `bot_config.paused=true`, replacing the bot with
the hourly-candle long/short paper bot specced in #466 and built out in Batch 2/3 of the #464
programme.

As of this ADR being written, the liquidation has been handed to the operator (see the handoff
comment on #465) rather than executed by this agent — `panic?action=liquidate` places a real market
order and must only run during US regular trading hours with a human confirming the paper-account
pre-flight checks. The position was LONG 7,511 UPRO as of the 2026-07-24 digest at the time of
writing. This ADR will not be edited after merge (immutability rule, `docs/decisions/README.md`);
if the liquidation later fails or partially fills, that is tracked as new incident work, not a
retroactive edit here.

## Consequences

### Positive

- Frees the paper account and the operator's attention from a bot that is not the current strategy
  direction, without waiting on a defect to justify the change.
- `panic`, `kill-switch`, and `status` keep operating unchanged, so the account stays monitored and
  protected (an open position would still be defended by the kill-switch; a flat position needs no
  defense).
- The decision log stays internally consistent: the 2026-07-06 ADR that decided to *keep* this bot
  is marked superseded rather than left `accepted` alongside a contradicting decision.
- Clears the account for the #466 successor to soak without two decision rules running in parallel
  on it.

### Negative

- This is an evidence-backed working strategy being replaced by an unproven one — a real departure
  from the #398 pre-registration discipline, accepted here as the operator's stated risk rather than
  a data-driven verdict on the incumbent.
- Once paused, `daily-check` exits `skipped:trading_paused` at the pause gate
  (`supabase/functions/daily-check/logic.ts:96-99`) before contacting Alpaca, so no new
  `regime_state` rows and **no new `equity_snapshots` rows** (written later in `logic.ts:298-305`,
  after the gate) are recorded going forward — the `status` digest's `returns` block will freeze at
  its last pre-pause value.
- `regime_state.current_state` will stay stuck at `LONG` (stale — `daily-check` is paused and cannot
  resync), so the Friday #229 digest will read "LONG `UPRO`" (from the stale `regime_state` row)
  alongside `alpaca.position.qty: 0` and `paused: true` once the position is flat. This is an
  expected cosmetic artifact of pausing, not a fault, and readers of #229 should not mistake it for
  a live signal.
- No function, cron, migration, or table is removed by this decision — the dormant UPRO code and
  schema stay in place until Batch 3 does the actual decommission, so there is dead-but-monitored
  surface area in the interim.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Pause only, keep the position | Leaves 3x exposure running unattended with no daily reconciliation once `daily-check` is paused — strictly worse than flat; the kill-switch alone is not a substitute for the daily regime check. |
| Run both bots in parallel on the same paper account | Two decision rules on one account violates the repo's one-decision-rule invariant and would make P/L attribution ambiguous between the two strategies. |
| Keep UPRO live until a successor clears the #398 pre-registration bar | This is the disciplined default and was the plan sequenced behind #420/#421 — but the operator's direction on #464 (2026-07-27) explicitly overrides it, and that override is what this ADR records rather than silently deviating from #398. |
| Full decommission now (drop functions/cron/schema) | Rejected — `kill-switch` and `panic` must keep guarding the account through the transition, and teardown is explicitly Batch 3's scope, after the successor soaks. |

---

Links: #464, #465, #466, #229, #230, #420, #421, #422, #448, #457, and the superseded
[2026-07-06 ADR](2026-07-06-keep-200dma-regime-signal.md).
