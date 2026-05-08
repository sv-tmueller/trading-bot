# Pivot to a Deterministic Rules-Engine Bot — Design Spec

- **Date:** 2026-05-07
- **Status:** Draft (pending user review)
- **Author:** Brainstormed with Claude (main session)
- **Supersedes:** v1.14 LLM-driven swing-trading architecture
- **Implementation status:** Not started — this spec is the input to `superpowers:writing-plans`

## 1. Context

The current bot (v1.14) is a four-agent LLM-driven swing trader on a 12-stock US large-cap watchlist. A 5-year portfolio backtest over 2021-05-07 → 2026-05-07 returned **+12.77% total / ~2.4% CAGR / −17.46% max drawdown**, against SPY's **+86% / +13.2% CAGR** and SXR8's (UCITS S&P 500 EUR) **+90% / +13.7% CAGR** over the same window. The bot underperformed passive index exposure by ~70 percentage points over five years.

The shortfall is structural: the bot's strategy (EMA crossover + RSI + volume confirmation, scored by a Claude-Sonnet "team leader") has near-zero edge after costs, while the deterministic guardrail layer that does work — exposure cap, ATR sizing, OCO brackets, panic CLI — sits idle on top of a strategy that doesn't justify trading at all.

In parallel investigation we tested the **Mebane Faber 200-DMA regime filter** applied to leveraged S&P vehicles. Backtest results over the same 5y window:

| Strategy | Total (EUR) | CAGR (EUR) | Max DD |
|---|---:|---:|---:|
| Current bot (LLM swing, 12 stocks) | +12.77% | +2.43% | −17.46% |
| SXR8 buy-and-hold | +90.09% | +13.71% | −23.32% |
| UPRO (3× SPY) buy-and-hold | +170.19% | +22.00% | −63.94% |
| **UPRO + 200-DMA filter** | **+152.16%** | **+20.32%** | **−35.47%** |

The 200-DMA-filtered leveraged strategy gives up ~1.7% CAGR vs straight UPRO buy-hold to cut max drawdown nearly in half — a profile that matches the user's stated goal of "the bot at minimum covers its own running costs" with an acceptable risk envelope.

## 2. Goals & non-goals

### Goals

1. The bot generates enough return on its allocated capital to cover its own operating costs (~€60/yr post-pivot — VPS only, no Anthropic API).
2. The strategy is deterministic, auditable, and rule-based. No LLM in the trading-decision path.
3. The bot is operable by a German resident: EUR-denominated vehicle, IBKR retail account, automatic Abgeltungsteuer handling where possible.
4. The codebase shrinks substantially. Maintenance burden drops to "weekend hobby" rather than "side job."
5. The deterministic safety stack from v1.14 is preserved where still relevant, and the architectural invariants in `CLAUDE.md` are simplified rather than violated.

### Non-goals

1. The bot does **not** replace the user's primary wealth-building path (SXR8 DCA in Trade Republic). That continues independently.
2. The bot does **not** attempt to beat SPY by margin trading, multi-asset rotation, or pair trading. It implements one well-validated rule on one instrument.
3. The bot does **not** trade intraday. The rule fires once per day after US close.
4. The bot does **not** manage multiple instruments. v1 trades exactly one symbol (3USL).
5. The bot does **not** require IBKR Professional Client status. v1 uses retail-accessible UCITS only.

## 3. Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Brain | **Deterministic rules engine, no LLM** | LLM latency (1-10s) too high for trade decisions; no edge gained vs. mechanical rule; eliminates entire failure class ("Claude misinterprets data"). |
| 2 | Execution | **Auto-execute via IBKR** | Rule fires 4-8 times per 5 years; manual would work but auto-execute reuses the existing safety-stack philosophy. |
| 3 | Vehicle | **3USL UCITS on Xetra (`WSPL.DE`)** | EUR-denominated, retail-accessible, no Pro-status threshold, simplest bot code. Trade-off: ETN structure (counterparty risk to WisdomTree's swap counterparty) and worse DE tax (no Teilfreistellung). Accepted. |
| 4 | Strategy | **Mebane Faber 200-DMA regime filter on SPY** | 100+ years of academic validation (Faber 2007). Our own 5y backtest confirmed +20% CAGR / −35% DD on UPRO. Single rule, easy to understand, easy to test. |
| 5 | Safety overlay | **Faber filter + 30-day drawdown kill-switch (Approach B)** | Defense-in-depth. A 25% intraday drawdown on the position triggers immediate exit independent of regime state. Protects against ETP failure modes and overnight gaps that bypass the daily check. |
| 6 | Re-entry rule | **No time delay; re-enter when SPY > SMA(200)** | User preference. Trade-off: theoretical "falling knife" scenario where kill-switch fires intraday and re-entry happens same evening. Mitigated by the fact that real crashes also pull SPY below 200-DMA, so the regime filter catches the dust. |
| 7 | State desync | **Auto-reconcile (trust IBKR)** | If DB and IBKR disagree, update DB to match IBKR and continue. Notify the user but do not halt. Self-healing. |
| 8 | Capital allocation | **External to bot design** | The bot trades "all available cash on regime LONG → fully invested." Capital level is whatever the user funds the IBKR account with; the bot has no `RISK_PER_TRADE` knob anymore. |

## 4. Architecture

```
┌───────────────────────────────────────────────────┐
│  cron 30 22 * * 1-5  (UTC; ≥1.5h after US close)  │
│  — gives yfinance time to publish the daily bar   │
└─────────────────────┬─────────────────────────────┘
                      ▼
            ┌───────────────────┐
            │   daily_check.py  │   ← entry point
            └─────────┬─────────┘
                      │
        ┌─────────────┼─────────────┬──────────────┐
        ▼             ▼             ▼              ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ market  │  │ strategy │  │ broker   │  │ notify   │
   │ data    │  │ rules    │  │ (IBKR)   │  │ (Discord)│
   └─────────┘  └──────────┘  └──────────┘  └──────────┘
        │            │             │             │
        └────────────┴──────┬──────┴─────────────┘
                            ▼
                     ┌─────────────┐
                     │  storage    │
                     │ (SQLite)    │
                     └─────────────┘

┌───────────────────────────────────────────────────┐
│  cron 5 14-21 * * 1-5  (UTC; hourly market hours) │
└─────────────────────┬─────────────────────────────┘
                      ▼
            ┌─────────────────────┐
            │ monitor/kill_switch │   ← drawdown protection
            └─────────────────────┘
```

### Process boundaries

- One scheduled cron entry: `daily_check.py` (post-close)
- One scheduled cron entry: `monitor/kill_switch.py` (hourly during market hours)
- One always-on daemon: IBKR TWS or IB Gateway running on the VPS for `ib_insync` to connect to
- One database: SQLite at `trading_bot.db` (schema simplified)
- One config file: `.env` (significantly fewer variables)

### Invariants preserved from v1.14

- Deterministic safety mechanisms — every order is gated by (a) idempotency-key check, (b) state reconciliation against IBKR truth, and (c) the kill-switch flag — all deterministic, all evaluated *before* any submit call
- `CLAUDE_AGENT_NO_BROKER` env-var guard (issue #168) — every IBKR submission helper checks `is_claude_agent_no_broker()` and raises `BrokerCallBlockedError` before any `ib_insync` call when the guard is active
- Panic CLI — `python main.py panic` cancels orders + liquidates + writes `TRADING_PAUSED=true`
- Idempotent daily checks — duplicate cron fires within the same trading day do not produce duplicate orders

### Invariants removed from v1.14

- "LLM must not control risk" — trivially satisfied; there is no LLM
- Agent-test triad (happy path / name check / JSON fallback) — no agents to test
- Token cost tracking in `agent_logs` — no LLM API calls

## 5. Components

### New modules

| File | Responsibility |
|---|---|
| `daily_check.py` | Entry point. Fetches SPY history, runs the regime filter, decides target state, reconciles with IBKR, places trade if needed, notifies, logs to DB. Replaces `main.py scan`. ~150 lines. |
| `strategy/regime.py` | **Pure function.** `compute_target_state(spy_close, spy_sma200, current_state, kill_switch_active) -> "LONG" \| "CASH"`. No I/O. The entire trading logic lives here. ~50 lines. |
| `monitor/kill_switch.py` | Hourly cron. Fetches 3USL last price, computes drawdown from rolling N-trading-day high (N=`KILL_SWITCH_LOOKBACK_DAYS`, default 30), exits position if breached. Writes to DB. Replaces `monitor/position_monitor.py`. ~100 lines. |
| `tools/ibkr_broker.py` | Wraps `ib_insync`. Functions: `get_position(symbol)`, `place_market_order(symbol, side, qty)`, `liquidate(symbol)`, `cancel_all_orders()`, `get_account_value()`. Honors `CLAUDE_AGENT_NO_BROKER` guard. Handles TWS reconnect retries. ~250 lines. |
| `backtest/regime.py` | Standalone backtester for the new strategy. Fetches SPY + 3USL history, applies the rule daily, computes equity curve / drawdown / CAGR / trade list. Replaces `backtest/portfolio.py` for this strategy. ~200 lines. |

### Modified files

| File | Change |
|---|---|
| `main.py` | Keep `panic`, `summary`, `backtest`. Remove `scan` (replaced by `daily_check.py` directly via cron). Remove `monitor` mode (replaced by `kill_switch.py` directly via cron). |
| `config/settings.py` | **Remove:** `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `MAX_POSITIONS`, `MAX_PORTFOLIO_EXPOSURE`, `RISK_PER_TRADE`, `RR_RATIO_MIN`, `MAX_HOLD_DAYS`, `STRICT_CROSSOVER`, `EMA_*`, `RSI_*`, `VOLUME_MULTIPLIER`, `ATR_*`, `EARNINGS_BLACKOUT_DAYS`, `TRAILING_STOP_*`, `FILL_POLL_*`. **Add:** `IBKR_HOST` (default `127.0.0.1`), `IBKR_PORT` (default `4001` live / `4002` paper), `IBKR_CLIENT_ID`, `KILL_SWITCH_DRAWDOWN_PCT` (default `0.25`), `REGIME_SMA_DAYS` (default `200`), `KILL_SWITCH_LOOKBACK_DAYS` (default `30`), `BOT_TICKER` (default `"WSPL.DE"`), `BOT_BENCHMARK` (default `"SPY"`). |
| `tools/notifications.py` | New event types: `regime_flip`, `kill_switch_fired`, `trade_filled`, `trade_failed`, `tws_disconnected`, `state_desync`. |
| `storage/schema.sql` | Drop `signals`, `monitor_actions`, `daily_stats`, `weekly_stats`, `suggestions`. Drop `agent_logs.input_tokens` / `agent_logs.output_tokens` columns; rename table to `audit_log`. Add `regime_state` table. Simplify `trades` table. |
| `requirements.txt` | Remove `anthropic`. Add `ib_insync`. |

### Deleted files

- `agents/base.py`
- `agents/market_intelligence.py`
- `agents/strategy.py`
- `agents/risk_review.py`
- `agents/team_leader.py`
- `tools/broker.py` (replaced by `tools/ibkr_broker.py`)
- `tools/risk.py` (no per-trade ATR/RR sizing — bot is binary in/out, full position)
- `monitor/position_monitor.py` (replaced by `monitor/kill_switch.py`)
- `agents/` directory entirely
- `tests/test_*_agent.py`
- `tests/test_risk.py`
- `tests/test_team_leader_*.py`

**Estimated final codebase size:** ~2,000 lines from current ~8,000.

## 6. Data flow

### Daily flow (cron `30 22 * * 1-5` UTC, ≥1.5h after US close)

```
1. daily_check.py launches
2. fetch SPY history (2 years via yfinance)
3. compute SMA(200)
4. check that today's bar is fresh (date >= today UTC); else exit
5. load regime_state.current_state from SQLite

6. compute_target_state(spy_close, sma_200, current_state, kill_switch_active):
     if SPY > SMA200:
         clear kill_switch_active flag if set
         return LONG
     else:
         return CASH

7. reconcile with IBKR:
     ibkr_position = ibkr.get_position(BOT_TICKER)
     if (ibkr_position > 0) != (current_state == "LONG"):
         # auto-reconcile: trust IBKR
         current_state = "LONG" if ibkr_position > 0 else "CASH"
         notify(state_desync)

8. if target_state != current_state:
     a. place market order via IBKR
     b. wait for fill (poll up to 30s)
     c. write trades row
     d. update regime_state.current_state
     e. notify Discord with fill details
   else:
     write today's regime_state row only
```

### Hourly flow (cron `5 14-21 * * 1-5` UTC, market hours only)

```
1. monitor/kill_switch.py launches
2. read regime_state.current_state from SQLite
3. if current_state != "LONG": exit (no position to protect)
4. fetch BOT_TICKER last price + rolling high (yfinance)
     — `high = max(close[-KILL_SWITCH_LOOKBACK_DAYS:])` over last N **trading** days (default 30)
5. drawdown = (last_price / high) - 1
6. if drawdown <= -KILL_SWITCH_DRAWDOWN_PCT:
     a. ibkr.liquidate(BOT_TICKER)
     b. update regime_state: kill_switch_active=1, kill_switch_fired_at=now(), current_state=CASH
     c. write trades row with reason='kill_switch'
     d. notify Discord (🛑 KILL SWITCH FIRED)
   else: no-op
```

### State sources of truth

| Question | Authoritative source |
|---|---|
| What's our current position? | IBKR (`get_position`) — DB reconciled to match each daily cycle |
| What was today's regime decision? | `regime_state` table |
| Is the kill-switch tripped? | `regime_state.kill_switch_active` (latest row) |
| Trade history? | `trades` table |
| Operationally alive? | `audit_log` table — every script run writes one row |

### Re-entry block after kill-switch

When the kill-switch fires, `kill_switch_active = 1` is written to `regime_state`. The next daily check re-evaluates: if `SPY > SMA(200)`, the flag is cleared and `LONG` is allowed; if `SPY <= SMA(200)`, the flag stays set and the bot remains in `CASH`. **No time-delay enforced.**

### Schema sketch

```sql
CREATE TABLE regime_state (
    date TEXT PRIMARY KEY,
    spy_close REAL NOT NULL,
    spy_sma200 REAL NOT NULL,
    target_state TEXT NOT NULL CHECK(target_state IN ('LONG','CASH')),
    current_state TEXT NOT NULL CHECK(current_state IN ('LONG','CASH')),
    position_drawdown_pct REAL,
    kill_switch_active INTEGER NOT NULL DEFAULT 0,
    kill_switch_fired_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    qty INTEGER NOT NULL,
    fill_price REAL NOT NULL,
    fill_time TEXT NOT NULL,
    ibkr_order_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('regime_flip_long','regime_flip_cash','kill_switch','panic_cli')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    script_name TEXT NOT NULL CHECK(script_name IN ('daily_check','kill_switch','panic')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,                      -- 'success' | 'error:<class>'
    notes TEXT
);
```

## 7. Error handling

### Failure mode policy

| Failure | Where | Policy | Notify? |
|---|---|---|---|
| yfinance returns no SPY data | `tools/market_data` | Skip cycle, retry on next cron fire. | ⚠️ Discord |
| yfinance returns stale data (last bar < today) | `daily_check` | Skip cycle. (Holiday or data lag — both OK to skip.) | Info-level |
| IBKR TWS connection fails | `tools/ibkr_broker` | Retry 3× with 5s backoff. If still failing, abort cycle. | 🔴 Discord |
| IBKR order rejected | `tools/ibkr_broker` | **Do not auto-retry.** Log full reject reason. Bot stays in current state. | 🔴 Discord (with code) |
| Order placed, fill not received within 30s | `tools/ibkr_broker` | Cancel open order, log timeout, abort cycle. | ⚠️ Discord |
| DB write fails | anywhere | Log to stderr (cron mail-on-error). Continue. State re-derived next cycle from IBKR. | 🔴 Discord |
| Discord/n8n webhook unreachable | `tools/notifications` | Log, continue. Audit log still records the event. | (silent — can't notify) |
| State desync (DB vs IBKR) | `daily_check` | **Auto-reconcile** — trust IBKR, update DB. | ⚠️ Discord |
| Cron fires on market holiday | `daily_check` | "Stale data" check triggers, cycle skipped. | Info-level (once per holiday) |
| Two cron instances overlap | `daily_check`, `kill_switch` | Process-level file lock — second instance exits. | (silent) |
| Kill-switch fires but liquidate fails | `monitor/kill_switch` | Retry 3×. If still failing, log + escalate loudly. | 🚨🚨🚨 Discord |

### Operational kill switch

`python main.py panic` is preserved with one change: replace Alpaca calls with IBKR equivalents (`ibkr.cancel_all_orders()`, `ibkr.liquidate(BOT_TICKER)`). Flags unchanged: `--cancel-orders`, `--liquidate --confirm`, `--pause`. `audit_log` row written before broker call, updated in `finally`. `--pause` writes `TRADING_PAUSED=true` to `.env`.

### Idempotency

- `daily_check`: one `regime_state` row per `date` (PRIMARY KEY → `INSERT OR REPLACE`). The position-flip step is gated on `target != current` after reconcile, so duplicate runs cannot double-trade.
- `kill_switch`: naturally idempotent. After firing, `current_state = CASH`; subsequent hourly fires exit early in step 3.
- Order placement: idempotency key `f"{date}-{target_state}"` tracked in `audit_log`. Duplicate request for same key rejected before reaching IBKR.

### Failure model overall

The bot is built so the worst-case failure is always *"stay flat"* or *"stay in current state."* It never accidentally double-positions or trades in the wrong direction due to a recoverable error. The only single-point-of-failure is the kill-switch liquidation itself — which is why that path retries and escalates loudly.

## 8. Testing

### Test pyramid

```
          ┌──────────────────────────┐
          │  Backtest validation     │  1-2 tests, slow (~10s)
          ├──────────────────────────┤
          │  Integration (mocked     │  ~10 tests, fast (~5s)
          │  IBKR + yfinance)        │
          ├──────────────────────────┤
          │  Unit (pure functions)   │  ~25 tests, fast (~1s)
          └──────────────────────────┘
```

### Unit tests — `tests/test_regime.py` (~15 tests)

`compute_target_state` is a pure function — every branch testable trivially:

| Test | Inputs | Expected |
|---|---|---|
| Bullish, no kill-switch | `spy=400, sma200=380, current=CASH, ks=False` | `LONG` |
| Bearish, no kill-switch | `spy=380, sma200=400, current=LONG, ks=False` | `CASH` |
| Kill-switch + bullish → re-entry | `spy=400, sma200=380, ks=True` | `LONG` (clear ks flag) |
| Kill-switch + bearish | `spy=380, sma200=400, ks=True` | `CASH` (keep ks flag) |
| Boundary: SPY == SMA200 | `spy=400, sma200=400` | `CASH` (strict `>`) |
| NaN SMA200 | `spy=400, sma200=NaN` | `CASH` (defensive default) |
| State unchanged | `current=LONG, target=LONG` | `LONG` (no flip) |

Plus 8 more covering all 16 combinations of (regime × current × ks-state).

### Unit tests — others

- `tests/test_settings.py` — validation of new env vars (`IBKR_PORT` bounds, `KILL_SWITCH_DRAWDOWN_PCT` bounds, `BOT_TICKER` non-empty)
- `tests/test_notifications.py` — payload shape for each new event type
- `tests/test_storage.py` — schema migrations, CHECK constraint enforcement, `INSERT OR REPLACE` idempotency

### Integration tests (~10 tests)

Mock `ib_insync.IB` at the module path used by `tools/ibkr_broker`. Mock `yfinance.download`. Test full flows:

- Happy path: regime flips LONG → bot places buy → fill → DB rows written → Discord called
- Order rejection: IBKR returns reject → bot logs, notifies, no retry, DB consistent
- TWS connect retry: 2 fails then success → trade placed
- TWS connect total failure: cycle aborts cleanly, no DB writes
- Kill-switch fires: drawdown −27% → liquidate → DB updated → notification
- State desync: DB says LONG, IBKR returns no position → auto-reconcile → notify
- Idempotency: same `daily_check` runs twice in 5 minutes → second run sees `current == target`, no duplicate orders

### Backtest validation — `tests/test_backtest_regime.py` (1-2 tests)

Run `backtest/regime.py` on a fixed historical sub-window with known expected output (committed as fixture). Pin to known-good results (e.g., the 2021-05 → 2026-05 window we validated in this conversation: ~152% total return EUR / −35% max DD on UPRO; equivalent target for 3USL once we have its history). Catches regressions in the rule logic.

### CI safety: `CLAUDE_AGENT_NO_BROKER` guard

Preserved unchanged from v1.14:
- `tests/conftest.py` autouse fixture sets `CLAUDE_AGENT_NO_BROKER=true` for every test
- `tools/ibkr_broker.py` reads `is_claude_agent_no_broker()` at the top of every submission helper and raises `BrokerCallBlockedError` before any `ib_insync` call

Any forgotten mock fails fast with a clear message instead of submitting to live IBKR. Non-negotiable per `CLAUDE.md` (incidents #149, #168).

### What's *not* tested

- Real IBKR API behavior — verify only via manual paper-account smoke tests, opt-in via env var
- TWS daemon uptime — operational, not testable in CI
- Discord delivery — webhook unit test sufficient
- Long-horizon strategy edge — rely on academic literature; our backtest is for regression detection

### Target metrics

- ~40 tests total (down from current 200+)
- Full suite < 30 seconds, deterministic, zero flakes, no network in CI

## 9. Migration plan

The implementation plan (writing-plans skill) will sequence this; the high-level order:

1. **Open IBKR account** — user task; gates everything else. Paper account first.
2. **Set up TWS / IB Gateway on the VPS** — install, configure auto-start, verify `ib_insync` connect from a script.
3. **Build `tools/ibkr_broker.py`** — minimal: connect, get_position, place_market_order, liquidate. Mockable for tests.
4. **Build `strategy/regime.py`** — pure function with its full unit-test suite.
5. **Build `backtest/regime.py`** — verify our 5y backtest result on 3USL specifically (we tested UPRO; 3USL has shorter history but should track UPRO with TER drag).
6. **Build `daily_check.py` + `monitor/kill_switch.py`** — wire it together against the paper account.
7. **Migrate `main.py panic` to IBKR** — preserve flags and audit-log behaviour.
8. **New schema migration script** — drop old tables, create new ones, preserve `audit_log` history with column transform.
9. **Update `.env.example`, `README.md`, `CLAUDE.md`** — reflect the new architecture, deprecate old config keys.
10. **Delete `agents/`, `tools/risk.py`, `tools/broker.py`, `monitor/position_monitor.py`, agent tests.**
11. **Update cron jobs on the VPS** — replace `scan`/`monitor` cron with `daily_check.py` and `monitor/kill_switch.py`.
12. **Paper-account soak** — minimum 1 month live on paper account, observe at least one regime flip if possible (timing-dependent), confirm Discord notifications and audit-log rows.
13. **Live cutover** — fund IBKR live account, switch ports (`4001`), pull the trigger.

## 10. Risks & open questions

### Risks

- **TWS daemon stability.** Known to be the operational pain-point of IBKR integrations. Mitigation: our crons run *outside* the TWS daily-reset window (22:30 ET ≈ 02:30/03:30 UTC); IBKR connect retries with backoff; loud Discord on connect failure.
- **3USL counterparty risk.** WisdomTree's swap counterparty failing would lose the position independent of SPY. Mitigation: kill-switch on −25% position drawdown; user accepts this as the cost of UCITS access.
- **Tax suboptimality.** No Teilfreistellung on 3USL gains. Mitigation: user explicitly chose simplicity over tax efficiency. Could revisit by switching to IBKR-margin-on-SXR8 if ever desired (separate redesign).
- **5y backtest is short.** 2021-2026 had a bull bias. Strategy could underperform in a 2000-2010-style lost decade. Mitigation: rely on Faber's 100+ year academic backtest; accept that future may differ.
- **Single-instrument concentration.** Bot's entire allocated capital is in one ETP. Mitigation: this is a satellite, not a core; user's wealth path is in SXR8 separately.
- **Re-entry into falling-knife scenario.** Kill-switch fires on −25%, SPY recovers same day to above SMA200 → bot re-enters into a recently-crashed instrument. Mitigation: real crashes also push SPY below SMA200, which holds the bot in cash; this scenario is a tail case. Accepted.

### Open questions (to resolve before implementation)

1. **3USL backtest data availability.** Need to verify yfinance has sufficient 3USL price history for backtest validation. May need to substitute or use UPRO as proxy with a TER-drag adjustment.
2. **IBKR commission structure for low-frequency trading.** 4-8 trades per 5 years. Confirm whether IBKR charges meaningful per-trade fees on EUR-Xetra orders for this instrument. (Roughly: IBKR Tiered ≈ 0.05% / EUR 1.25 minimum per Xetra order; expected fee burden ≈ <€10/year. Negligible.)
3. **Kill-switch reference: drawdown from rolling 30-day high vs from position open.** Spec currently uses rolling 30-day high (option B in earlier discussion). If position was just opened and the 30-day high is from before the open, the bot would calculate drawdown vs an unrelated high. Edge case to confirm during implementation.
4. **TWS auto-restart on the VPS.** Should TWS run as a systemd service with `Restart=always`, or just be started manually? Operationally important but not strictly part of bot code.
5. **Backtest sanity check on real 3USL data.** Run our regime-filter backtest specifically against `WSPL.DE` history once available, verify the result is in the expected range (~16-18% CAGR EUR, given TER drag).

## 11. Out of scope (explicit YAGNI list)

- Multi-instrument rotation
- Crypto, futures, options
- Sub-daily timeframes
- LLM-driven anything
- Tactical sector overlays
- Risk parity / vol targeting / dynamic position sizing (Approach C from brainstorming)
- "Continue to monitor the existing Alpaca bot in parallel as a control." Out of scope — full cutover.
- Multiple parallel strategies in one codebase
- Paper-trading sandbox after cutover
- A web UI / dashboard
- Backwards-compatible config (old `.env` keys stay deprecated, new keys required)

## 12. Success criteria

The pivot is considered successful if:

1. After 6 months of live operation, the bot has covered its own running costs (~€30 over 6 months).
2. Zero unintended trades — every fill traces back to either a regime flip or a kill-switch event in `audit_log`.
3. Codebase is < 2,500 lines (down from ~8,000).
4. Test suite runs in < 30 seconds and is deterministic.
5. The user can describe the entire trading rule in one sentence.

If any of (2)-(5) fail at any point during implementation, that's a stop-and-reassess signal.
