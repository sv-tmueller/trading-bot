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
    getAuditLogSince: (sinceIso: string) => {
      calls.since = sinceIso;
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
    alpaca: { ...defaultAlpaca, ...(over.alpaca as unknown as StatusDeps["alpaca"]) },
    db: { ...defaultDb, ...(over.db as unknown as StatusDeps["db"]) },
    ...over,
  };
  if (over.alpaca) {
    deps.alpaca = { ...defaultAlpaca, ...over.alpaca as unknown as StatusDeps["alpaca"] };
  }
  if (over.db) deps.db = { ...defaultDb, ...over.db as unknown as StatusDeps["db"] };
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

Deno.test("error rows returned verbatim, newest first; non-error rows excluded", async () => {
  const errorRow: AuditLogRow = {
    script_name: "daily-check",
    started_at: "2026-07-05T13:37:00Z",
    finished_at: "2026-07-05T13:37:05Z",
    outcome: "error:AlpacaError",
    notes: "boom",
  };
  const successRow: AuditLogRow = {
    script_name: "daily-check",
    started_at: "2026-07-06T13:37:00Z",
    finished_at: "2026-07-06T13:37:05Z",
    outcome: "success",
    notes: null,
  };
  const { deps } = makeDeps({
    db: {
      getAuditLogSince: () => Promise.resolve<AuditLogRow[]>([successRow, errorRow]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.audit_7d.errors, [errorRow]);
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
