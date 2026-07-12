// Unit tests for the status digest's pure aggregation logic (#354 T4).
// Every dep is a plain injected mock — no network, no client construction,
// no DB writes. runStatus performs zero writes: StatusDeps has no
// insert/update/upsert method at all (compile-time enforcement).
import { assertEquals, assertRejects } from "@std/assert";
import { runStatus, type StatusDeps } from "./logic.ts";
import type { AuditLogRow, RegimeStateRow, TradeRow } from "../_shared/db.ts";

const REGIME_ROW: RegimeStateRow = {
  date: "2026-07-08",
  spy_close: 620.5,
  spy_sma200: 590.25,
  target_state: "LONG",
  current_state: "LONG",
  position_drawdown_pct: -0.03,
  kill_switch_active: false,
  kill_switch_fired_at: null,
};

const TRADE_ROW: TradeRow = {
  symbol: "UPRO",
  side: "BUY",
  qty: 120,
  fill_price: 71.4,
  fill_time: "2026-07-08T13:38:00Z",
  reason: "regime_flip_long",
  broker_order_id: "o-1",
};

function makeDeps(
  over: Partial<StatusDeps> = {},
): { deps: StatusDeps; calls: Record<string, unknown> } {
  const calls: Record<string, unknown> = {};
  const defaultDb: StatusDeps["db"] = {
    getLatestRegimeState: () => Promise.resolve(REGIME_ROW),
    getAuditLogSince: (sinceIso: string, untilIso: string) => {
      calls.since = sinceIso;
      calls.until = untilIso;
      return Promise.resolve<AuditLogRow[]>([
        {
          script_name: "daily-check",
          started_at: "2026-07-08T13:37:00Z",
          finished_at: "2026-07-08T13:37:05Z",
          outcome: "success",
          notes: null,
        },
      ]);
    },
    getLastTrade: () => Promise.resolve(TRADE_ROW),
    getConfig: (_key: string) => Promise.resolve("false"),
    getTradesSince: (_sinceIso: string) => {
      calls.tradesSinceCalled = true;
      return Promise.resolve<TradeRow[]>([]);
    },
    getRegimeStatesSince: (_sinceDate: string) => {
      calls.regimeStatesSinceCalled = true;
      return Promise.resolve<RegimeStateRow[]>([]);
    },
  };
  const defaultAlpaca: StatusDeps["alpaca"] = {
    getClock: () => Promise.resolve({ isOpen: true }),
    getAccountValue: () => Promise.resolve(100_000),
    getPosition: (symbol: string) => {
      calls.positionSymbol = symbol;
      return Promise.resolve(120);
    },
  };
  const deps: StatusDeps = {
    config: {
      regimeSmaDays: 200,
      killSwitchDrawdownPct: 0.25,
      killSwitchLookbackDays: 30,
      botTicker: "UPRO",
      botBenchmark: "SPY",
    },
    now: () => new Date("2026-07-09T15:00:00Z"),
    ...over,
    alpaca: { ...defaultAlpaca, ...(over.alpaca as unknown as StatusDeps["alpaca"]) },
    db: { ...defaultDb, ...(over.db as unknown as StatusDeps["db"]) },
  };
  return { deps, calls };
}

Deno.test("happy path: digest fully populated from mocks", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps);

  assertEquals(digest.generated_at, "2026-07-09T15:00:00.000Z");
  assertEquals(digest.market_open, true);
  assertEquals(digest.paused, false);
  assertEquals(digest.regime?.date, "2026-07-08");
  assertEquals(digest.regime?.target_state, "LONG");
  assertEquals(digest.regime?.position_drawdown_pct, -0.03);
  assertEquals(digest.last_trade?.broker_order_id, "o-1");
  assertEquals(digest.alpaca.equity_usd, 100_000);
  assertEquals(digest.alpaca.position, { symbol: "UPRO", qty: 120 });
});

Deno.test("since is exactly now - 7 days, and getPosition is called with config.botTicker", async () => {
  const { deps, calls } = makeDeps();
  await runStatus(deps);
  assertEquals(calls.since, "2026-07-02T15:00:00.000Z");
  assertEquals(calls.positionSymbol, "UPRO");
});

Deno.test("outcome aggregation: mixed outcomes counted, null -> (unfinished)", async () => {
  const { deps } = makeDeps({
    db: {
      getAuditLogSince: () =>
        Promise.resolve<AuditLogRow[]>([
          {
            script_name: "daily-check",
            started_at: "t3",
            finished_at: "t3f",
            outcome: "success",
            notes: null,
          },
          {
            script_name: "kill-switch",
            started_at: "t2",
            finished_at: "t2f",
            outcome: "skipped:market_closed",
            notes: null,
          },
          {
            script_name: "kill-switch",
            started_at: "t1",
            finished_at: "t1f",
            outcome: "skipped:market_closed",
            notes: null,
          },
          {
            script_name: "daily-check",
            started_at: "t0",
            finished_at: null,
            outcome: null,
            notes: null,
          },
        ]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.audit_7d.outcome_counts, {
    "success": 1,
    "skipped:market_closed": 2,
    "(unfinished)": 1,
  });
});

Deno.test("error rows returned verbatim, newest first (DB order preserved); non-error rows excluded", async () => {
  // #355 review finding 2: assert ordering with >=2 qualifying error rows,
  // interleaved with success rows, to prove .filter() preserves the DB's
  // newest-first order rather than merely happening to pass with one row.
  const newerError: AuditLogRow = {
    script_name: "kill-switch",
    started_at: "2026-07-07T13:37:00Z",
    finished_at: "2026-07-07T13:37:05Z",
    outcome: "error:implausible_drawdown",
    notes: "ratio",
  };
  const successRow: AuditLogRow = {
    script_name: "daily-check",
    started_at: "2026-07-06T13:37:00Z",
    finished_at: "2026-07-06T13:37:05Z",
    outcome: "success",
    notes: null,
  };
  const olderError: AuditLogRow = {
    script_name: "daily-check",
    started_at: "2026-07-05T13:37:00Z",
    finished_at: "2026-07-05T13:37:05Z",
    outcome: "error:AlpacaError",
    notes: "boom",
  };
  const { deps } = makeDeps({
    db: {
      getAuditLogSince: () => Promise.resolve<AuditLogRow[]>([newerError, successRow, olderError]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.audit_7d.errors, [newerError, olderError]);
});

Deno.test("no regime row -> regime: null", async () => {
  const { deps } = makeDeps({
    db: { getLatestRegimeState: () => Promise.resolve(null) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.regime, null);
});

Deno.test("no trades -> last_trade: null", async () => {
  const { deps } = makeDeps({
    db: { getLastTrade: () => Promise.resolve(null) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.last_trade, null);
});

Deno.test("paused: 'true' -> true", async () => {
  const { deps } = makeDeps({
    db: { getConfig: () => Promise.resolve("true") } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.paused, true);
});

Deno.test("paused: missing row -> false", async () => {
  const { deps } = makeDeps({
    db: { getConfig: () => Promise.resolve(null) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.paused, false);
});

Deno.test("dep rejection propagates (fail-fast, no partial digest)", async () => {
  const { deps } = makeDeps({
    alpaca: {
      getAccountValue: () => Promise.reject(new Error("alpaca down")),
    } as unknown as StatusDeps["alpaca"],
  });
  await assertRejects(() => runStatus(deps), Error, "alpaca down");
});

// ---------------------------------------------------------------------------
// #358 T5: runStatus extended mode (`windowDays` param). Default (no param)
// must stay shape-identical to the current deployment (hard constraint).
// ---------------------------------------------------------------------------

Deno.test("default mode (no windowDays): shape-lock - exact current 7 keys, no trades/regime_history, windowed helpers not called", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps);
  assertEquals(
    Object.keys(digest).sort(),
    ["alpaca", "audit_7d", "generated_at", "last_trade", "market_open", "paused", "regime"],
  );
  assertEquals("trades" in digest, false);
  assertEquals("regime_history" in digest, false);
  assertEquals(calls.tradesSinceCalled, undefined);
  assertEquals(calls.regimeStatesSinceCalled, undefined);
});

Deno.test("windowDays=30: audit_7d.since is now - 30 days; untilIso passed to getAuditLogSince equals generated_at", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps, 30);
  assertEquals(digest.audit_7d.since, "2026-06-09T15:00:00.000Z");
  assertEquals(calls.until, digest.generated_at);
});

Deno.test("windowDays set: trades + regime_history arrays populated newest-first from mocks", async () => {
  const newerTrade: TradeRow = {
    ...TRADE_ROW,
    broker_order_id: "o-2",
    fill_time: "2026-07-09T13:00:00Z",
  };
  const { deps } = makeDeps({
    db: {
      getTradesSince: () => Promise.resolve([newerTrade, TRADE_ROW]),
      getRegimeStatesSince: () => Promise.resolve([REGIME_ROW]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, 7);
  assertEquals(digest.trades, [newerTrade, TRADE_ROW]);
  assertEquals(digest.regime_history, [REGIME_ROW]);
});

Deno.test("windowDays set: empty window -> trades and regime_history are [] not null", async () => {
  const { deps } = makeDeps({
    db: {
      getTradesSince: () => Promise.resolve([]),
      getRegimeStatesSince: () => Promise.resolve([]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, 7);
  assertEquals(digest.trades, []);
  assertEquals(digest.regime_history, []);
});

Deno.test("outcome_counts sums correctly across a 1500-row page-boundary-spanning window", async () => {
  const rows: AuditLogRow[] = Array.from({ length: 1500 }, (_, i) => ({
    script_name: "daily-check",
    started_at: `t${i}`,
    finished_at: `t${i}f`,
    outcome: i % 2 === 0 ? "success" : "skipped:market_closed",
    notes: null,
  }));
  const { deps } = makeDeps({
    db: { getAuditLogSince: () => Promise.resolve(rows) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, 60);
  const total = Object.values(digest.audit_7d.outcome_counts).reduce(
    (a, b) => a + b,
    0,
  );
  assertEquals(total, 1500);
});
