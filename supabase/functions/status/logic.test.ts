// Unit tests for the status digest's pure aggregation logic (#354 T4).
// Every dep is a plain injected mock — no network, no client construction,
// no DB writes. runStatus performs zero writes: StatusDeps has no
// insert/update/upsert method at all (compile-time enforcement).
import { assertEquals, assertRejects } from "@std/assert";
import {
  computeEquityHeadroomPct,
  computeRegimeMarginPct,
  runStatus,
  type StatusDeps,
} from "./logic.ts";
import type {
  AuditLogRow,
  EquitySnapshotRow,
  HourlyScanRow,
  RegimeStateRow,
  TradeRow,
} from "../_shared/db.ts";

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

// #536: fixtures for the status digest's `hourly` block.
const HOURLY_SCAN_LONG: HourlyScanRow = {
  symbol: "SPY",
  bar_ts: "2026-07-09T14:00:00Z",
  decision: "LONG",
  skip_reason: null,
  detectors_fired: ["hammer", "bullish_pin_bar"],
  context_mode: "none",
  entry_ref_price: 550.1,
  stop_price: 547.75,
  target_price: 554.55,
  risk_per_share: 2.35,
  equity_usd: 100_000,
  qty: 18,
  entry_order_id: "o1",
};

const HOURLY_SCAN_SKIP: HourlyScanRow = {
  symbol: "SPY",
  bar_ts: "2026-07-09T13:00:00Z",
  decision: "SKIP",
  skip_reason: "no_detectors_fired",
  detectors_fired: [],
  context_mode: "none",
  entry_ref_price: null,
  stop_price: null,
  target_price: null,
  risk_per_share: null,
  equity_usd: 100_000,
  qty: 0,
  entry_order_id: null,
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
      const seen = (calls.auditLogSinceCalls as [string, string][] | undefined) ?? [];
      seen.push([sinceIso, untilIso]);
      calls.auditLogSinceCalls = seen;
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
    // #536/#546: "paused", "hourly_experiment_start_equity", and
    // "hourly_experiment_baseline_verified" share this one getConfig method —
    // branch on key so every digest read gets a sane default. Tracks the set
    // of keys queried, so a test can assert a key was (or wasn't) fetched.
    getConfig: (key: string) => {
      const seen = (calls.getConfigKeys as string[] | undefined) ?? [];
      seen.push(key);
      calls.getConfigKeys = seen;
      if (key === "hourly_experiment_start_equity") return Promise.resolve("100000");
      if (key === "hourly_experiment_baseline_verified") return Promise.resolve("100000");
      return Promise.resolve("false");
    },
    getTradesSince: (_sinceIso: string) => {
      calls.tradesSinceCalled = true;
      return Promise.resolve<TradeRow[]>([]);
    },
    getRegimeStatesSince: (_sinceDate: string) => {
      calls.regimeStatesSinceCalled = true;
      return Promise.resolve<RegimeStateRow[]>([]);
    },
    getEarliestEquitySnapshot: () => Promise.resolve<EquitySnapshotRow | null>(null),
    getLatestEquitySnapshot: () => Promise.resolve<EquitySnapshotRow | null>(null),
    getEquitySnapshotsSince: (sinceDate: string) => {
      calls.equitySnapshotsSinceArg = sinceDate;
      return Promise.resolve<EquitySnapshotRow[]>([]);
    },
    // #396 T1: last_runs — latest audit_log row per monitored script, used
    // by the dead-man watchdog. Default mock returns a fixed row regardless
    // of scriptName; tests that need per-script behavior override this.
    getLatestAuditForScript: (scriptName: string) => {
      const seen = (calls.latestAuditForScriptArgs as string[] | undefined) ?? [];
      seen.push(scriptName);
      calls.latestAuditForScriptArgs = seen;
      return Promise.resolve<AuditLogRow | null>({
        script_name: scriptName,
        started_at: "2026-07-09T13:37:00Z",
        finished_at: "2026-07-09T13:37:05Z",
        outcome: "success",
        notes: null,
      });
    },
    // #536: hourly digest block.
    getLatestHourlyScan: () => Promise.resolve<HourlyScanRow | null>(HOURLY_SCAN_LONG),
    getHourlyScansSince: (sinceIso: string) => {
      calls.hourlyScansSinceArg = sinceIso;
      return Promise.resolve<HourlyScanRow[]>([]);
    },
    // #546: verification block's day-scoped scan/trade reads.
    getHourlyScansInWindow: (sinceIso: string, untilIso: string) => {
      calls.hourlyScansInWindowCalled = true;
      calls.hourlyScansInWindowArgs = [sinceIso, untilIso];
      return Promise.resolve<HourlyScanRow[]>([]);
    },
    getTradesInWindow: (sinceIso: string, untilIso: string) => {
      calls.tradesInWindowCalled = true;
      calls.tradesInWindowArgs = [sinceIso, untilIso];
      return Promise.resolve<TradeRow[]>([]);
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
    // #546: narrow shorts-enabled reader's result, passed straight in.
    shortsEnabled: false,
    ...over,
    alpaca: { ...defaultAlpaca, ...(over.alpaca as unknown as StatusDeps["alpaca"]) },
    db: { ...defaultDb, ...(over.db as unknown as StatusDeps["db"]) },
  };
  return { deps, calls };
}

// #546: [since, until] for a verify day, matching runStatus's fixed string
// templates exactly (`${verifyDate}T00:00:00.000Z` / `T23:59:59.999Z`).
function dayWindow(verifyDate: string): [string, string] {
  return [`${verifyDate}T00:00:00.000Z`, `${verifyDate}T23:59:59.999Z`];
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
    db: {
      getConfig: (key: string) => Promise.resolve(key === "paused" ? "true" : "100000"),
    } as unknown as StatusDeps["db"],
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

Deno.test("default mode (no windowDays): shape-lock - exact current 10 keys (#396 adds `last_runs`), no trades/regime_history, windowed helpers not called", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps);
  // #384: regime_margin_pct is a new required top-level key (intended,
  // in-scope consequence of task 1 — the #358 byte-identical-shape
  // constraint was scoped to proving the windowDays param's absence didn't
  // change the response, not a permanent field freeze).
  // #396 T1: `last_runs` is the same kind of deliberate additive change
  // (precedent: `regime_margin_pct` #384, `returns` #383) — the dead-man
  // watchdog (#396) needs per-script last-run timestamps that audit_7d
  // cannot provide (its window can exclude both scripts entirely, and its
  // `errors` array only carries `error:*` rows, not the latest row overall).
  assertEquals(
    Object.keys(digest).sort(),
    [
      "alpaca",
      "audit_7d",
      "generated_at",
      // #536: `hourly` — the live hourly bot's digest block, strictly
      // additive alongside the pre-existing keys below.
      "hourly",
      "last_runs",
      "last_trade",
      "market_open",
      "paused",
      "regime",
      "regime_margin_pct",
      "returns",
    ],
  );
  assertEquals("trades" in digest, false);
  assertEquals("regime_history" in digest, false);
  assertEquals(calls.tradesSinceCalled, undefined);
  assertEquals(calls.regimeStatesSinceCalled, undefined);
  // #546: no verifyDate -> no `verification` key, and none of its four
  // conditionally-called deps fire.
  assertEquals("verification" in digest, false);
  assertEquals(calls.hourlyScansInWindowCalled, undefined);
  assertEquals(calls.tradesInWindowCalled, undefined);
  assertEquals((calls.auditLogSinceCalls as unknown[]).length, 1);
  assertEquals(
    (calls.getConfigKeys as string[]).includes("hourly_experiment_baseline_verified"),
    false,
  );
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

// ---------------------------------------------------------------------------
// #384 T1: computeRegimeMarginPct pure helper + wiring into runStatus.
// ---------------------------------------------------------------------------

Deno.test("computeRegimeMarginPct: above the 200-DMA -> positive exact value", () => {
  assertEquals(computeRegimeMarginPct(620.5, 590.25), (620.5 - 590.25) / 590.25 * 100);
});

Deno.test("computeRegimeMarginPct: below the 200-DMA -> negative exact value", () => {
  assertEquals(computeRegimeMarginPct(560.87, 601.23), (560.87 - 601.23) / 601.23 * 100);
});

Deno.test("computeRegimeMarginPct: spy_sma200 <= 0 -> null", () => {
  assertEquals(computeRegimeMarginPct(600, 0), null);
  assertEquals(computeRegimeMarginPct(600, -10), null);
});

Deno.test("computeRegimeMarginPct: non-finite inputs -> null", () => {
  assertEquals(computeRegimeMarginPct(NaN, 590.25), null);
  assertEquals(computeRegimeMarginPct(620.5, NaN), null);
  assertEquals(computeRegimeMarginPct(Infinity, 590.25), null);
  assertEquals(computeRegimeMarginPct(620.5, Infinity), null);
});

Deno.test("runStatus: regime present -> regime_margin_pct computed from spy_close/spy_sma200", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps);
  assertEquals(digest.regime_margin_pct, (620.5 - 590.25) / 590.25 * 100);
});

Deno.test("runStatus: regime null -> regime_margin_pct: null", async () => {
  const { deps } = makeDeps({
    db: { getLatestRegimeState: () => Promise.resolve(null) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.regime_margin_pct, null);
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

// ---------------------------------------------------------------------------
// #383 T4: `returns` — trailing portfolio returns computed from
// equity_snapshots, independent of the live alpaca.getAccountValue() read
// used for `alpaca.equity_usd`.
// ---------------------------------------------------------------------------

function snap(date: string, equityUsd: number): EquitySnapshotRow {
  return { date, equity_usd: equityUsd };
}

Deno.test("returns: 0 snapshots -> all null", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps);
  assertEquals(digest.returns, {
    since_inception_pct: null,
    trailing_7d_pct: null,
    trailing_30d_pct: null,
  });
});

Deno.test("returns: exactly 1 snapshot -> since_inception_pct is 0 (not null), trailing windows null", async () => {
  const only = snap("2026-07-09", 100_000);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(only),
      getLatestEquitySnapshot: () => Promise.resolve(only),
      getEquitySnapshotsSince: () => Promise.resolve([only]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.returns.since_inception_pct, 0);
  assertEquals(digest.returns.trailing_7d_pct, null);
  assertEquals(digest.returns.trailing_30d_pct, null);
});

Deno.test("returns: since_inception_pct = (latest - earliest) / earliest * 100", async () => {
  const earliest = snap("2026-01-01", 100_000);
  const latest = snap("2026-07-09", 110_000);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(earliest),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () => Promise.resolve([earliest, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.returns.since_inception_pct, 10);
});

Deno.test("returns: trailing_7d_pct uses the snapshot exactly on latest.date - 7 calendar days", async () => {
  const latest = snap("2026-07-09", 110_000);
  const sevenDaysBack = snap("2026-07-02", 100_000);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(sevenDaysBack),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () => Promise.resolve([sevenDaysBack, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.returns.trailing_7d_pct, 10);
});

Deno.test("returns: gap handling — picks the closest snapshot on-or-before the threshold, not the nearest overall", async () => {
  // latest = 2026-07-09; trailing_7d threshold = 2026-07-02. No snapshot lands
  // exactly there; candidates are 2026-06-30 (before threshold) and 2026-07-05
  // (after threshold, i.e. only 4 days back). Must pick 2026-06-30, not
  // 2026-07-05, even though 07-05 is calendar-closer to latest.
  const tooRecent = snap("2026-07-05", 105_000);
  const correct = snap("2026-06-30", 100_000);
  const latest = snap("2026-07-09", 120_000);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(correct),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () => Promise.resolve([correct, tooRecent, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.returns.trailing_7d_pct, 20); // (120000-100000)/100000*100
});

Deno.test("returns: window not old enough for trailing_30d -> null, but trailing_7d present", async () => {
  const latest = snap("2026-07-09", 110_000);
  const fiveDaysBack = snap("2026-07-04", 100_000); // covers 7d window (>=7 back? no: 5 days back < 7)
  // Use a snapshot exactly 7 days back so trailing_7d resolves, but nothing
  // 30 days back so trailing_30d stays null.
  const sevenDaysBack = snap("2026-07-02", 105_000);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(sevenDaysBack),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () => Promise.resolve([sevenDaysBack, fiveDaysBack, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.returns.trailing_7d_pct, (110_000 - 105_000) / 105_000 * 100);
  assertEquals(digest.returns.trailing_30d_pct, null);
});

Deno.test("returns: anchored on latest.date, not deps.now()", async () => {
  // deps.now() is 2026-07-09T15:00:00Z (see makeDeps), but the latest snapshot
  // is dated 2026-07-05 (e.g. daily-check hasn't run in a couple of days).
  // trailing_7d threshold must be 2026-07-05 - 7 = 2026-06-28, not
  // now() - 7 = 2026-07-02.
  const latest = snap("2026-07-05", 110_000);
  const atThreshold = snap("2026-06-28", 100_000);
  const wouldMatchIfAnchoredOnNow = snap("2026-07-02", 999_999);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(atThreshold),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () =>
        Promise.resolve([atThreshold, wouldMatchIfAnchoredOnNow, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.returns.trailing_7d_pct, 10);
});

Deno.test("returns: present in extended (?days=N) mode too", async () => {
  const earliest = snap("2026-01-01", 100_000);
  const latest = snap("2026-07-09", 110_000);
  const { deps } = makeDeps({
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(earliest),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () => Promise.resolve([earliest, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, 30);
  assertEquals(digest.returns.since_inception_pct, 10);
});

Deno.test("returns: computed strictly from equity_snapshots, independent of the live getAccountValue() mock", async () => {
  const earliest = snap("2026-01-01", 100_000);
  const latest = snap("2026-07-09", 110_000);
  const { deps } = makeDeps({
    alpaca: {
      getAccountValue: () => Promise.resolve(999_999), // deliberately different
    } as unknown as StatusDeps["alpaca"],
    db: {
      getEarliestEquitySnapshot: () => Promise.resolve(earliest),
      getLatestEquitySnapshot: () => Promise.resolve(latest),
      getEquitySnapshotsSince: () => Promise.resolve([earliest, latest]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.alpaca.equity_usd, 999_999);
  assertEquals(digest.returns.since_inception_pct, 10);
});

// ---------------------------------------------------------------------------
// #396 T1: `last_runs` — latest audit_log row per monitored script
// (daily-check, kill-switch), consumed by the dead-man watchdog
// (scripts/deadman_check.ts). Always present, both default and extended
// (`windowDays`) mode.
// ---------------------------------------------------------------------------

Deno.test("last_runs: populated from mocks for both daily-check and kill-switch", async () => {
  const { deps } = makeDeps({
    db: {
      getLatestAuditForScript: (scriptName: string) =>
        Promise.resolve<AuditLogRow>({
          script_name: scriptName,
          started_at: scriptName === "daily-check"
            ? "2026-07-09T13:37:00Z"
            : "2026-07-09T14:35:00Z",
          finished_at: null,
          outcome: scriptName === "daily-check" ? "success" : "skipped:market_closed",
          notes: null,
        }),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.last_runs.daily_check, {
    started_at: "2026-07-09T13:37:00Z",
    outcome: "success",
  });
  assertEquals(digest.last_runs.kill_switch, {
    started_at: "2026-07-09T14:35:00Z",
    outcome: "skipped:market_closed",
  });
});

Deno.test("last_runs: getLatestAuditForScript is called with exactly 'daily-check', 'kill-switch', and 'hourly-check'", async () => {
  const { deps, calls } = makeDeps();
  await runStatus(deps);
  assertEquals(
    (calls.latestAuditForScriptArgs as string[]).sort(),
    ["daily-check", "hourly-check", "kill-switch"],
  );
});

Deno.test("last_runs: no rows for a script -> null for that script", async () => {
  const { deps } = makeDeps({
    db: {
      getLatestAuditForScript: (scriptName: string) =>
        scriptName === "daily-check" ? Promise.resolve(null) : Promise.resolve<AuditLogRow>({
          script_name: "kill-switch",
          started_at: "2026-07-09T14:35:00Z",
          finished_at: "2026-07-09T14:35:01Z",
          outcome: "success",
          notes: null,
        }),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.last_runs.daily_check, null);
  assertEquals(digest.last_runs.kill_switch, {
    started_at: "2026-07-09T14:35:00Z",
    outcome: "success",
  });
});

Deno.test("last_runs: present in extended (?days=N) mode too", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps, 30);
  assertEquals(digest.last_runs.daily_check?.outcome, "success");
  assertEquals(digest.last_runs.kill_switch?.outcome, "success");
});

// ---------------------------------------------------------------------------
// #536: `hourly` block + `last_runs.hourly_check` — the live hourly bot's
// digest, sourced from hourly_scans + bot_config. Strictly additive: no
// pre-existing key is touched.
// ---------------------------------------------------------------------------

Deno.test("regression: every pre-#536 top-level key is still present (strictly additive)", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps);
  const preExistingKeys = [
    "generated_at",
    "market_open",
    "paused",
    "regime",
    "regime_margin_pct",
    "audit_7d",
    "last_trade",
    "alpaca",
    "returns",
    "last_runs",
  ];
  for (const key of preExistingKeys) {
    assertEquals(key in digest, true, `missing pre-existing key: ${key}`);
  }
});

Deno.test("hourly.latest_scan: direct pass-through, including bracket geometry, when the scan entered", async () => {
  const { deps } = makeDeps({
    db: {
      getLatestHourlyScan: () => Promise.resolve(HOURLY_SCAN_LONG),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.hourly.latest_scan, HOURLY_SCAN_LONG);
});

Deno.test("hourly: no scans, no baseline -> all-null day zero", async () => {
  const { deps } = makeDeps({
    db: {
      getLatestHourlyScan: () => Promise.resolve(null),
      getHourlyScansSince: () => Promise.resolve([]),
      getConfig: (key: string) =>
        Promise.resolve(key === "hourly_experiment_start_equity" ? null : "false"),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.hourly.latest_scan, null);
  assertEquals(digest.hourly.equity, {
    equity_usd: null,
    floor_baseline_usd: null,
    floor_price_usd: null,
    headroom_pct: null,
  });
  assertEquals(digest.hourly.skip_reason_counts, {});
  assertEquals(digest.hourly.audit_outcome_counts, {});
});

Deno.test("hourly.skip_reason_counts: groups SKIP rows by skip_reason, null -> 'unspecified', LONG/SHORT rows excluded", async () => {
  const scans: HourlyScanRow[] = [
    { ...HOURLY_SCAN_SKIP, bar_ts: "t1", skip_reason: "no_detectors_fired" },
    { ...HOURLY_SCAN_SKIP, bar_ts: "t2", skip_reason: "no_detectors_fired" },
    { ...HOURLY_SCAN_SKIP, bar_ts: "t3", skip_reason: "signal_conflict" },
    { ...HOURLY_SCAN_SKIP, bar_ts: "t4", skip_reason: null },
    HOURLY_SCAN_LONG,
  ];
  const { deps } = makeDeps({
    db: { getHourlyScansSince: () => Promise.resolve(scans) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.hourly.skip_reason_counts, {
    no_detectors_fired: 2,
    signal_conflict: 1,
    unspecified: 1,
  });
});

Deno.test("hourly.audit_outcome_counts: scoped to script_name='hourly-check' from the same already-fetched auditRows; audit_7d.outcome_counts stays mixed", async () => {
  const rows: AuditLogRow[] = [
    {
      script_name: "hourly-check",
      started_at: "t1",
      finished_at: "t1f",
      outcome: "success",
      notes: null,
    },
    {
      script_name: "hourly-check",
      started_at: "t2",
      finished_at: "t2f",
      outcome: "success",
      notes: null,
    },
    {
      script_name: "hourly-check",
      started_at: "t3",
      finished_at: null,
      outcome: null,
      notes: null,
    },
    {
      script_name: "daily-check",
      started_at: "t4",
      finished_at: "t4f",
      outcome: "success",
      notes: null,
    },
  ];
  const { deps } = makeDeps({
    db: { getAuditLogSince: () => Promise.resolve(rows) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.hourly.audit_outcome_counts, { "success": 2, "(unfinished)": 1 });
  assertEquals(digest.audit_7d.outcome_counts, { "success": 3, "(unfinished)": 1 });
});

Deno.test("hourly.equity: headroom_pct computed from equity_usd vs floor_price_usd (baseline present)", async () => {
  const scan: HourlyScanRow = { ...HOURLY_SCAN_LONG, equity_usd: 95_000 };
  const { deps } = makeDeps({
    db: {
      getLatestHourlyScan: () => Promise.resolve(scan),
      getConfig: (key: string) =>
        Promise.resolve(key === "hourly_experiment_start_equity" ? "100000" : "false"),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.hourly.equity.equity_usd, 95_000);
  assertEquals(digest.hourly.equity.floor_baseline_usd, 100_000);
  assertEquals(digest.hourly.equity.floor_price_usd, 85_000);
  assertEquals(digest.hourly.equity.headroom_pct, (95_000 - 85_000) / 95_000 * 100);
});

Deno.test("hourly.equity: baseline absent -> floor_baseline_usd/floor_price_usd/headroom_pct null, not a throw", async () => {
  const scan: HourlyScanRow = { ...HOURLY_SCAN_LONG, equity_usd: 95_000 };
  const { deps } = makeDeps({
    db: {
      getLatestHourlyScan: () => Promise.resolve(scan),
      getConfig: (key: string) =>
        Promise.resolve(key === "hourly_experiment_start_equity" ? null : "false"),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.hourly.equity.equity_usd, 95_000);
  assertEquals(digest.hourly.equity.floor_baseline_usd, null);
  assertEquals(digest.hourly.equity.floor_price_usd, null);
  assertEquals(digest.hourly.equity.headroom_pct, null);
});

Deno.test("hourly: getHourlyScansSince is called with the same `since` as audit_7d", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps);
  assertEquals(calls.hourlyScansSinceArg, digest.audit_7d.since);
});

Deno.test("hourly: present and shaped the same in extended (?days=N) mode", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps, 30);
  assertEquals("hourly" in digest, true);
  assertEquals(digest.hourly.latest_scan, HOURLY_SCAN_LONG);
  assertEquals(typeof digest.hourly.skip_reason_counts, "object");
  assertEquals(typeof digest.hourly.audit_outcome_counts, "object");
});

Deno.test("last_runs.hourly_check: populated from getLatestAuditForScript('hourly-check')", async () => {
  const { deps } = makeDeps({
    db: {
      getLatestAuditForScript: (scriptName: string) =>
        scriptName === "hourly-check"
          ? Promise.resolve<AuditLogRow>({
            script_name: "hourly-check",
            started_at: "2026-07-09T14:00:00Z",
            finished_at: "2026-07-09T14:00:05Z",
            outcome: "success",
            notes: null,
          })
          : Promise.resolve(null),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.last_runs.hourly_check, {
    started_at: "2026-07-09T14:00:00Z",
    outcome: "success",
  });
});

Deno.test("last_runs.hourly_check: no rows -> null", async () => {
  const { deps } = makeDeps({
    db: { getLatestAuditForScript: () => Promise.resolve(null) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps);
  assertEquals(digest.last_runs.hourly_check, null);
});

// ---------------------------------------------------------------------------
// #536: computeEquityHeadroomPct — pure helper, guarded like
// computeRegimeMarginPct: non-finite inputs and a non-positive equityUsd
// (division-by-zero / nonsensical domain) both -> null, never Infinity/NaN.
// ---------------------------------------------------------------------------

Deno.test("computeEquityHeadroomPct: happy path — % distance from equity down to the floor price", () => {
  assertEquals(computeEquityHeadroomPct(95_000, 85_000), (95_000 - 85_000) / 95_000 * 100);
});

Deno.test("computeEquityHeadroomPct: non-finite inputs -> null", () => {
  assertEquals(computeEquityHeadroomPct(NaN, 85_000), null);
  assertEquals(computeEquityHeadroomPct(95_000, NaN), null);
  assertEquals(computeEquityHeadroomPct(Infinity, 85_000), null);
  assertEquals(computeEquityHeadroomPct(95_000, Infinity), null);
});

Deno.test("computeEquityHeadroomPct: equityUsd <= 0 -> null (avoids division by zero / nonsensical domain)", () => {
  assertEquals(computeEquityHeadroomPct(0, 85_000), null);
  assertEquals(computeEquityHeadroomPct(-100, 85_000), null);
});

// ---------------------------------------------------------------------------
// #546: `verification` block -- present only when `verifyDate` is supplied
// to runStatus, per spec §4.3 (docs/superpowers/specs/2026-08-06-daily-
// verification-design.md). The frozen shape has no consumer in this package;
// #547's evaluator implements against it from its own fixtures, so every
// field here is load-bearing.
// ---------------------------------------------------------------------------

const VERIFY_DATE = "2026-08-05";

Deno.test("verification: window is the fixed [00:00:00.000Z, 23:59:59.999Z] template for `date`", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.date, VERIFY_DATE);
  assertEquals(digest.verification?.window, {
    since: "2026-08-05T00:00:00.000Z",
    until: "2026-08-05T23:59:59.999Z",
  });
});

Deno.test("verification: shape-lock - exact keys", async () => {
  const { deps } = makeDeps();
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(
    Object.keys(digest.verification!).sort(),
    [
      "config",
      "date",
      "hourly_check_runs",
      "kill_switch_runs",
      "scans",
      "shorts_enabled",
      "trades",
      "window",
    ],
  );
});

Deno.test("verification: day-scoped audit call uses the window bounds, distinct from audit_7d's own since/until", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  const auditCalls = calls.auditLogSinceCalls as [string, string][];
  assertEquals(auditCalls.length, 2);
  assertEquals(auditCalls[1], ["2026-08-05T00:00:00.000Z", "2026-08-05T23:59:59.999Z"]);
  // audit_7d's own since/until (the pre-existing 7-day window) must differ
  // from the day-scoped verification window -- the two calls are never
  // conflated.
  assertEquals(auditCalls[0][0] === auditCalls[1][0], false);
  assertEquals(digest.audit_7d.since, auditCalls[0][0]);
});

Deno.test("verification.hourly_check_runs: filtered to hourly-check, ascending by started_at, carries notes", async () => {
  const [since] = dayWindow(VERIFY_DATE);
  const dayRows: AuditLogRow[] = [
    {
      script_name: "hourly-check",
      started_at: "2026-08-05T20:07:00.000Z",
      finished_at: "2026-08-05T20:07:01.000Z",
      outcome: "success",
      notes: null,
    },
    {
      script_name: "hourly-check",
      started_at: "2026-08-05T13:07:02.113Z",
      finished_at: "2026-08-05T13:07:03.001Z",
      outcome: "skipped:market_closed",
      notes: "journal_degraded order o-1",
    },
    {
      script_name: "kill-switch",
      started_at: "2026-08-05T13:10:00.000Z",
      finished_at: "2026-08-05T13:10:00.500Z",
      outcome: "success:no_position",
      notes: null,
    },
  ];
  const { deps } = makeDeps({
    db: {
      getAuditLogSince: (sinceIso: string) => Promise.resolve(sinceIso === since ? dayRows : []),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(
    digest.verification?.hourly_check_runs.map((r) => r.started_at),
    ["2026-08-05T13:07:02.113Z", "2026-08-05T20:07:00.000Z"],
  );
  assertEquals(digest.verification?.hourly_check_runs[0].notes, "journal_degraded order o-1");
  assertEquals(digest.verification?.hourly_check_runs[1].notes, null);
});

Deno.test("verification.kill_switch_runs: counts only (count + outcome_counts), never rows", async () => {
  const [since] = dayWindow(VERIFY_DATE);
  const dayRows: AuditLogRow[] = [
    ...Array.from({ length: 107 }, (_, i) => ({
      script_name: "kill-switch",
      started_at: `2026-08-05T13:${String(i).padStart(2, "0")}:00.000Z`,
      finished_at: `2026-08-05T13:${String(i).padStart(2, "0")}:00.500Z`,
      outcome: "success:no_position",
      notes: null,
    })),
    {
      script_name: "kill-switch",
      started_at: "2026-08-05T21:55:00.000Z",
      finished_at: "2026-08-05T21:55:00.500Z",
      outcome: "skipped:market_closed",
      notes: null,
    },
    {
      script_name: "hourly-check",
      started_at: "2026-08-05T13:07:00.000Z",
      finished_at: "2026-08-05T13:07:01.000Z",
      outcome: "success",
      notes: null,
    },
  ];
  const { deps } = makeDeps({
    db: {
      getAuditLogSince: (sinceIso: string) => Promise.resolve(sinceIso === since ? dayRows : []),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.kill_switch_runs, {
    count: 108,
    outcome_counts: { "success:no_position": 107, "skipped:market_closed": 1 },
  });
  assertEquals("rows" in digest.verification!.kill_switch_runs, false);
});

Deno.test("verification.scans/trades: unfiltered pass-through from the window helpers", async () => {
  const scans: HourlyScanRow[] = [HOURLY_SCAN_SKIP, HOURLY_SCAN_LONG];
  const trades: TradeRow[] = [TRADE_ROW, { ...TRADE_ROW, broker_order_id: "o-2" }];
  const { deps } = makeDeps({
    db: {
      getHourlyScansInWindow: () => Promise.resolve(scans),
      getTradesInWindow: () => Promise.resolve(trades),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.scans, scans);
  assertEquals(digest.verification?.trades, trades);
});

Deno.test("verification.scans/trades: window helpers are called with the same window as `window`", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(calls.hourlyScansInWindowArgs, [
    digest.verification?.window.since,
    digest.verification?.window.until,
  ]);
  assertEquals(calls.tradesInWindowArgs, [
    digest.verification?.window.since,
    digest.verification?.window.until,
  ]);
});

Deno.test("verification.config: raw strings passed through unmangled, including a byte-identity case", async () => {
  const { deps } = makeDeps({
    db: {
      getConfig: (key: string) => {
        if (key === "paused") return Promise.resolve("false");
        // Trailing-zero formatting difference: a coercion to number would
        // destroy this, which is exactly what check 6's byte-identity
        // comparison depends on staying intact.
        if (key === "hourly_experiment_start_equity") return Promise.resolve("1017330.610");
        if (key === "hourly_experiment_baseline_verified") return Promise.resolve("1017330.610");
        return Promise.resolve(null);
      },
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.config, {
    paused: "false",
    hourly_experiment_start_equity: "1017330.610",
    hourly_experiment_baseline_verified: "1017330.610",
  });
});

Deno.test("verification.config: unset keys pass through as null, not a throw", async () => {
  const { deps } = makeDeps({
    db: { getConfig: () => Promise.resolve(null) } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.config, {
    paused: null,
    hourly_experiment_start_equity: null,
    hourly_experiment_baseline_verified: null,
  });
});

Deno.test("verification.config: reuses the already-fetched paused/baseline reads -- each key fetched exactly once, no duplicate round trip", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  const keys = calls.getConfigKeys as string[];
  assertEquals(keys.filter((k) => k === "paused").length, 1);
  assertEquals(keys.filter((k) => k === "hourly_experiment_start_equity").length, 1);
  assertEquals(keys.filter((k) => k === "hourly_experiment_baseline_verified").length, 1);
  assertEquals(digest.verification?.config.paused, "false");
});

Deno.test("verification.shorts_enabled: true when deps.shortsEnabled is true", async () => {
  const { deps } = makeDeps({ shortsEnabled: true });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.shorts_enabled, true);
});

Deno.test("verification.shorts_enabled: false when deps.shortsEnabled is false", async () => {
  const { deps } = makeDeps({ shortsEnabled: false });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.shorts_enabled, false);
});

Deno.test("verification: empty day -> scans/trades/hourly_check_runs [], kill_switch_runs zeroed", async () => {
  const { deps } = makeDeps({
    db: {
      getAuditLogSince: () => Promise.resolve([]),
      getHourlyScansInWindow: () => Promise.resolve([]),
      getTradesInWindow: () => Promise.resolve([]),
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification?.scans, []);
  assertEquals(digest.verification?.trades, []);
  assertEquals(digest.verification?.hourly_check_runs, []);
  assertEquals(digest.verification?.kill_switch_runs, { count: 0, outcome_counts: {} });
});

Deno.test("composition: verifyDate + windowDays both present -> both blocks correct and independent", async () => {
  const { deps, calls } = makeDeps();
  const digest = await runStatus(deps, 30, VERIFY_DATE);
  assertEquals("trades" in digest, true);
  assertEquals("regime_history" in digest, true);
  assertEquals(digest.verification?.date, VERIFY_DATE);
  assertEquals(digest.audit_7d.since, "2026-06-09T15:00:00.000Z");
  const auditCalls = calls.auditLogSinceCalls as [string, string][];
  assertEquals(auditCalls.length, 2);
  assertEquals(auditCalls[0], [digest.audit_7d.since, digest.generated_at]);
  assertEquals(auditCalls[1], ["2026-08-05T00:00:00.000Z", "2026-08-05T23:59:59.999Z"]);
});

// #546: the fixture must be consumed by a test, not merely committed (lead
// decision on #545: the three pre-existing sibling fixtures in
// scripts/testdata/ have zero consumers, and "a fixture nothing reads pins
// nothing"). This diffs runStatus's `verification` output, built from mocks
// reproducing the fixture's inputs, against the fixture's own
// `verification` key.
Deno.test("scripts/testdata/status-digest-verification.json: fixture's `verification` matches runStatus's output built from the same inputs", async () => {
  const fixtureRaw = await Deno.readTextFile(
    new URL("../../../scripts/testdata/status-digest-verification.json", import.meta.url),
  );
  const fixture = JSON.parse(fixtureRaw);

  const [since] = dayWindow(VERIFY_DATE);
  const killSwitchRows: AuditLogRow[] = Array.from({ length: 108 }, (_, i) => ({
    script_name: "kill-switch",
    started_at: `2026-08-05T${String(13 + Math.floor(i / 12)).padStart(2, "0")}:${
      String((i % 12) * 5).padStart(2, "0")
    }:00.000Z`,
    finished_at: `2026-08-05T${String(13 + Math.floor(i / 12)).padStart(2, "0")}:${
      String((i % 12) * 5).padStart(2, "0")
    }:00.500Z`,
    outcome: "success:no_position",
    notes: null,
  }));
  const dayRows: AuditLogRow[] = [
    {
      script_name: "hourly-check",
      started_at: "2026-08-05T13:07:02.113Z",
      finished_at: "2026-08-05T13:07:03.001Z",
      outcome: "skipped:market_closed",
      notes: null,
    },
    {
      script_name: "hourly-check",
      started_at: "2026-08-05T14:07:01.500Z",
      finished_at: "2026-08-05T14:07:02.200Z",
      outcome: "success",
      notes: null,
    },
    ...killSwitchRows,
  ];

  const { deps } = makeDeps({
    shortsEnabled: false,
    db: {
      getAuditLogSince: (sinceIso: string) => Promise.resolve(sinceIso === since ? dayRows : []),
      getHourlyScansInWindow: () => Promise.resolve([]),
      getTradesInWindow: () => Promise.resolve([]),
      getConfig: (key: string) => {
        if (key === "paused") return Promise.resolve("false");
        if (key === "hourly_experiment_start_equity") return Promise.resolve("1017330.61");
        if (key === "hourly_experiment_baseline_verified") return Promise.resolve("1017330.61");
        return Promise.resolve(null);
      },
    } as unknown as StatusDeps["db"],
  });
  const digest = await runStatus(deps, undefined, VERIFY_DATE);
  assertEquals(digest.verification, fixture.verification);
});
