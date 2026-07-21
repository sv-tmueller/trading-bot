import { assertEquals, assertRejects, assertThrows } from "@std/assert";
import { createClient } from "@supabase/supabase-js";
import {
  coerceEquitySnapshotRow,
  coerceRegimeRow,
  coerceTradeRow,
  getAuditLogSince,
  getConfig,
  getEarliestEquitySnapshot,
  getEquitySnapshotsSince,
  getLastTrade,
  getLatestAuditForScript,
  getLatestEquitySnapshot,
  getLatestRegimeState,
  getRegimeStatesSince,
  getTradesSince,
  insertAuditLog,
  insertTrade,
  setConfig,
  updateAuditLog,
  upsertEquitySnapshot,
  upsertRegimeState,
} from "./db.ts";
import { DataError } from "./num.ts";

const RUN = Deno.env.get("RUN_DB_TESTS") === "1";

function localClient() {
  // From `supabase status`: API URL + service_role key. Defaults below match a
  // standard local stack; override via env if your local ports differ.
  const url = Deno.env.get("SUPABASE_URL") ?? "http://127.0.0.1:54321";
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  return createClient(url, key, { auth: { persistSession: false } });
}

// ---------------------------------------------------------------------------
// #358 T3: stub query-builder client for getAuditLogSince's pagination loop.
// Mimics the chainable subset of the real PostgrestFilterBuilder that
// getAuditLogSince calls (select/gte/lte/order/range), stitching together
// pre-canned pages by call order. No network, no real client construction.
// ---------------------------------------------------------------------------
type StubAuditPage = { data: unknown[]; error: { message: string } | null };

function stubAuditClient(pages: StubAuditPage[]) {
  const ranges: Array<[number, number]> = [];
  const gteCalls: Array<[string, unknown]> = [];
  const lteCalls: Array<[string, unknown]> = [];
  let call = 0;
  // deno-lint-ignore no-explicit-any
  const builder: any = {
    select: () => builder,
    gte: (col: string, val: unknown) => {
      gteCalls.push([col, val]);
      return builder;
    },
    lte: (col: string, val: unknown) => {
      lteCalls.push([col, val]);
      return builder;
    },
    order: () => builder,
    range: (from: number, to: number) => {
      ranges.push([from, to]);
      const page = pages[call] ?? { data: [], error: null };
      call++;
      return Promise.resolve(page);
    },
  };
  // deno-lint-ignore no-explicit-any
  const sb = { from: () => builder } as any;
  return {
    sb,
    ranges,
    gteCalls,
    lteCalls,
    get calls() {
      return call;
    },
  };
}

function makeAuditRows(n: number, label: string): unknown[] {
  return Array.from({ length: n }, (_, i) => ({
    script_name: label,
    started_at: `2030-01-01T00:00:${String(i).padStart(2, "0")}Z`,
    finished_at: null,
    outcome: "success",
    notes: null,
  }));
}

Deno.test({
  name: "regime_state upsert + getLatest (ON CONFLICT replaces same date)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await sb.from("regime_state").delete().eq("date", "2030-01-02");
    await upsertRegimeState(sb, {
      date: "2030-01-02",
      spyClose: 400,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: null,
      killSwitchActive: false,
      killSwitchFiredAt: null,
    });
    await upsertRegimeState(sb, {
      date: "2030-01-02",
      spyClose: 401,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: -0.1,
      killSwitchActive: true,
      killSwitchFiredAt: "2030-01-02T15:00:00Z",
    });
    const latest = await getLatestRegimeState(sb);
    assertEquals(latest?.current_state, "LONG");
    assertEquals(latest?.kill_switch_active, true);
    assertEquals(Number(latest?.spy_close), 401);
    await sb.from("regime_state").delete().eq("date", "2030-01-02");
  },
});

Deno.test({
  name: "insertTrade returns id; row persists",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const id = await insertTrade(sb, {
      symbol: "UPRO",
      side: "BUY",
      qty: 100,
      fillPrice: 70.5,
      fillTime: "2030-01-02T15:00:00Z",
      brokerOrderId: "o-test",
      reason: "regime_flip_long",
    });
    assertEquals(typeof id, "number");
    await sb.from("trades").delete().eq("id", id);
  },
});

Deno.test({
  name: "audit_log insert then update",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const id = await insertAuditLog(sb, {
      scriptName: "db-test",
      startedAt: "2030-01-02T15:00:00Z",
    });
    await updateAuditLog(sb, {
      id,
      finishedAt: "2030-01-02T15:00:01Z",
      outcome: "success",
      notes: "ok",
    });
    const { data } = await sb.from("audit_log").select("outcome").eq("id", id).single();
    assertEquals(data?.outcome, "success");
    await sb.from("audit_log").delete().eq("id", id);
  },
});

Deno.test({
  name: "bot_config get/set",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await setConfig(sb, "paused", "true");
    assertEquals(await getConfig(sb, "paused"), "true");
    await setConfig(sb, "paused", "false");
    assertEquals(await getConfig(sb, "paused"), "false");
  },
});

// ---------------------------------------------------------------------------
// #354 T3: read-only helpers for the status Edge Function.
// ---------------------------------------------------------------------------

Deno.test({
  name: "getLastTrade returns the most recent trade by fill_time",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const olderId = await insertTrade(sb, {
      symbol: "UPRO",
      side: "BUY",
      qty: 100,
      fillPrice: 70.5,
      fillTime: "2030-01-02T15:00:00Z",
      brokerOrderId: "o-older",
      reason: "regime_flip_long",
    });
    const newerId = await insertTrade(sb, {
      symbol: "UPRO",
      side: "SELL",
      qty: 100,
      fillPrice: 72.25,
      fillTime: "2030-01-03T15:00:00Z",
      brokerOrderId: "o-newer",
      reason: "regime_flip_cash",
    });
    const last = await getLastTrade(sb);
    assertEquals(last?.broker_order_id, "o-newer");
    assertEquals(last?.fill_price, 72.25);
    assertEquals(last?.qty, 100);
    await sb.from("trades").delete().in("id", [olderId, newerId]);
  },
});

Deno.test({
  // #355 review finding 2b: assert newest-first ordering with >=2 qualifying
  // rows, plus a row above `untilIso` to prove the closed-window upper bound.
  name: "getAuditLogSince: filters by [since, until], orders newest-first (>=2 rows)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const oldId = await insertAuditLog(sb, {
      scriptName: "db-test",
      startedAt: "2020-01-01T00:00:00Z",
    });
    const olderInWindowId = await insertAuditLog(sb, {
      scriptName: "db-test",
      startedAt: "2030-01-02T15:00:00Z",
    });
    await updateAuditLog(sb, {
      id: olderInWindowId,
      finishedAt: "2030-01-02T15:00:01Z",
      outcome: "success",
      notes: "older",
    });
    const newerInWindowId = await insertAuditLog(sb, {
      scriptName: "db-test",
      startedAt: "2030-01-03T15:00:00Z",
    });
    await updateAuditLog(sb, {
      id: newerInWindowId,
      finishedAt: "2030-01-03T15:00:01Z",
      outcome: "success",
      notes: "newer",
    });
    const aboveUntilId = await insertAuditLog(sb, {
      scriptName: "db-test",
      startedAt: "2030-01-05T00:00:00Z",
    });
    const rows = await getAuditLogSince(sb, "2030-01-01T00:00:00Z", "2030-01-04T00:00:00Z");
    assertEquals(rows.length, 2);
    assertEquals(rows[0].notes, "newer");
    assertEquals(rows[1].notes, "older");
    await sb.from("audit_log").delete().in("id", [
      oldId,
      olderInWindowId,
      newerInWindowId,
      aboveUntilId,
    ]);
  },
});

// ---------------------------------------------------------------------------
// #396 T1: getLatestAuditForScript — used by the status digest's `last_runs`
// field (dead-man watchdog).
// ---------------------------------------------------------------------------

Deno.test({
  name:
    "getLatestAuditForScript: returns the newest row for that script only, ignores other scripts",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const otherScriptId = await insertAuditLog(sb, {
      scriptName: "db-test-other",
      startedAt: "2030-01-05T00:00:00Z",
    });
    const olderId = await insertAuditLog(sb, {
      scriptName: "db-test-target",
      startedAt: "2030-01-02T15:00:00Z",
    });
    await updateAuditLog(sb, {
      id: olderId,
      finishedAt: "2030-01-02T15:00:01Z",
      outcome: "success",
      notes: "older",
    });
    const newerId = await insertAuditLog(sb, {
      scriptName: "db-test-target",
      startedAt: "2030-01-03T15:00:00Z",
    });
    await updateAuditLog(sb, {
      id: newerId,
      finishedAt: "2030-01-03T15:00:01Z",
      outcome: "skipped:trading_paused",
      notes: null,
    });
    const latest = await getLatestAuditForScript(sb, "db-test-target");
    assertEquals(latest?.notes, null);
    assertEquals(latest?.outcome, "skipped:trading_paused");
    assertEquals(latest?.script_name, "db-test-target");
    await sb.from("audit_log").delete().in("id", [otherScriptId, olderId, newerId]);
  },
});

Deno.test({
  name: "getLatestAuditForScript: no rows for that script -> null",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const latest = await getLatestAuditForScript(sb, "db-test-nonexistent-script");
    assertEquals(latest, null);
  },
});

// ---------------------------------------------------------------------------
// #358 T3: getAuditLogSince pagination loop (D1/D2) — stub query-builder
// client, ungated (no network, no local Postgres needed).
// ---------------------------------------------------------------------------

Deno.test("getAuditLogSince: stitches 1000/1000/500 pages into 2500 rows with correct .range() calls", async () => {
  const { sb, ranges } = stubAuditClient([
    { data: makeAuditRows(1000, "p0"), error: null },
    { data: makeAuditRows(1000, "p1"), error: null },
    { data: makeAuditRows(500, "p2"), error: null },
  ]);
  const rows = await getAuditLogSince(sb, "2030-01-01T00:00:00Z", "2030-01-02T00:00:00Z");
  assertEquals(rows.length, 2500);
  assertEquals(ranges, [[0, 999], [1000, 1999], [2000, 2999]]);
});

Deno.test("getAuditLogSince: loop stops on a short first page", async () => {
  const { sb, ranges } = stubAuditClient([
    { data: makeAuditRows(3, "only"), error: null },
  ]);
  const rows = await getAuditLogSince(sb, "2030-01-01T00:00:00Z", "2030-01-02T00:00:00Z");
  assertEquals(rows.length, 3);
  assertEquals(ranges.length, 1);
});

Deno.test("getAuditLogSince: exactly-1000 total issues a second (empty) page and returns 1000", async () => {
  const { sb, ranges } = stubAuditClient([
    { data: makeAuditRows(1000, "p0"), error: null },
    { data: [], error: null },
  ]);
  const rows = await getAuditLogSince(sb, "2030-01-01T00:00:00Z", "2030-01-02T00:00:00Z");
  assertEquals(rows.length, 1000);
  assertEquals(ranges, [[0, 999], [1000, 1999]]);
});

Deno.test("getAuditLogSince: 10 full pages with no short page -> throws (page cap)", async () => {
  const pages: StubAuditPage[] = Array.from(
    { length: 10 },
    (_, i) => ({ data: makeAuditRows(1000, `p${i}`), error: null }),
  );
  const { sb } = stubAuditClient(pages);
  await assertRejects(() => getAuditLogSince(sb, "2030-01-01T00:00:00Z", "2030-01-02T00:00:00Z"));
});

Deno.test("getAuditLogSince: gte/lte receive sinceIso/untilIso", async () => {
  const { sb, gteCalls, lteCalls } = stubAuditClient([{ data: [], error: null }]);
  await getAuditLogSince(sb, "2030-01-01T00:00:00Z", "2030-01-08T00:00:00Z");
  assertEquals(gteCalls, [["started_at", "2030-01-01T00:00:00Z"]]);
  assertEquals(lteCalls, [["started_at", "2030-01-08T00:00:00Z"]]);
});

Deno.test("coerceRegimeRow: numeric strings -> numbers (PostgREST returns numeric as string)", () => {
  const row = coerceRegimeRow({
    date: "2026-06-06",
    spy_close: "412.3400",
    spy_sma200: "400.1267",
    target_state: "LONG",
    current_state: "LONG",
    position_drawdown_pct: "-0.250000",
    kill_switch_active: true,
    kill_switch_fired_at: null,
  });
  assertEquals(row.spy_close, 412.34);
  assertEquals(row.spy_sma200, 400.1267);
  assertEquals(row.position_drawdown_pct, -0.25);
  assertEquals(row.current_state, "LONG");
});

Deno.test("coerceRegimeRow: null drawdown stays null", () => {
  const row = coerceRegimeRow({
    date: "2026-06-06",
    spy_close: "400",
    spy_sma200: "380",
    target_state: "CASH",
    current_state: "CASH",
    position_drawdown_pct: null,
    kill_switch_active: false,
    kill_switch_fired_at: null,
  });
  assertEquals(row.position_drawdown_pct, null);
});

Deno.test("coerceRegimeRow: also accepts numbers (pre-migration doubles round-trip)", () => {
  const row = coerceRegimeRow({
    date: "2026-06-06",
    spy_close: 400,
    spy_sma200: 380,
    target_state: "LONG",
    current_state: "LONG",
    position_drawdown_pct: -0.1,
    kill_switch_active: false,
    kill_switch_fired_at: null,
  });
  assertEquals(row.spy_close, 400);
  assertEquals(row.position_drawdown_pct, -0.1);
});

Deno.test("coerceRegimeRow: non-numeric spy_close throws", () => {
  assertThrows(
    () =>
      coerceRegimeRow({
        date: "x",
        spy_close: "not-a-number",
        spy_sma200: "380",
        target_state: "LONG",
        current_state: "LONG",
        position_drawdown_pct: null,
        kill_switch_active: false,
        kill_switch_fired_at: null,
      }),
    DataError,
  );
});

// ---------------------------------------------------------------------------
// #358 T4: getTradesSince / getRegimeStatesSince (windowed read helpers) +
// coerceTradeRow (extracted from getLastTrade so both share one mapping).
// ---------------------------------------------------------------------------

Deno.test("coerceTradeRow: numeric strings -> numbers (PostgREST returns numeric as string)", () => {
  const row = coerceTradeRow({
    symbol: "UPRO",
    side: "BUY",
    qty: "120",
    fill_price: "71.4000",
    fill_time: "2026-07-08T13:38:00Z",
    reason: "regime_flip_long",
    broker_order_id: "o-1",
  });
  assertEquals(row.qty, 120);
  assertEquals(row.fill_price, 71.4);
  assertEquals(row.symbol, "UPRO");
  assertEquals(row.broker_order_id, "o-1");
});

Deno.test("coerceTradeRow: non-numeric qty throws", () => {
  assertThrows(
    () =>
      coerceTradeRow({
        symbol: "UPRO",
        side: "BUY",
        qty: "not-a-number",
        fill_price: "71.4",
        fill_time: "2026-07-08T13:38:00Z",
        reason: "regime_flip_long",
        broker_order_id: "o-1",
      }),
    DataError,
  );
});

Deno.test({
  name: "getTradesSince: returns fills with fill_time >= since, newest first",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const belowId = await insertTrade(sb, {
      symbol: "UPRO",
      side: "BUY",
      qty: 100,
      fillPrice: 70.5,
      fillTime: "2029-12-31T15:00:00Z",
      brokerOrderId: "o-below",
      reason: "regime_flip_long",
    });
    const olderId = await insertTrade(sb, {
      symbol: "UPRO",
      side: "BUY",
      qty: 100,
      fillPrice: 70.5,
      fillTime: "2030-01-02T15:00:00Z",
      brokerOrderId: "o-older",
      reason: "regime_flip_long",
    });
    const newerId = await insertTrade(sb, {
      symbol: "UPRO",
      side: "SELL",
      qty: 100,
      fillPrice: 72.25,
      fillTime: "2030-01-03T15:00:00Z",
      brokerOrderId: "o-newer",
      reason: "regime_flip_cash",
    });
    const rows = await getTradesSince(sb, "2030-01-01T00:00:00Z");
    assertEquals(rows.length, 2);
    assertEquals(rows[0].broker_order_id, "o-newer");
    assertEquals(rows[1].broker_order_id, "o-older");
    await sb.from("trades").delete().in("id", [belowId, olderId, newerId]);
  },
});

Deno.test({
  name: "getRegimeStatesSince: returns rows with date >= sinceDate, newest first",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await sb.from("regime_state").delete().in("date", ["2029-12-31", "2030-01-02", "2030-01-03"]);
    await upsertRegimeState(sb, {
      date: "2029-12-31",
      spyClose: 399,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: null,
      killSwitchActive: false,
      killSwitchFiredAt: null,
    });
    await upsertRegimeState(sb, {
      date: "2030-01-02",
      spyClose: 400,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: null,
      killSwitchActive: false,
      killSwitchFiredAt: null,
    });
    await upsertRegimeState(sb, {
      date: "2030-01-03",
      spyClose: 401,
      spySma200: 380,
      targetState: "LONG",
      currentState: "LONG",
      positionDrawdownPct: -0.1,
      killSwitchActive: true,
      killSwitchFiredAt: "2030-01-03T15:00:00Z",
    });
    const rows = await getRegimeStatesSince(sb, "2030-01-01");
    assertEquals(rows.length, 2);
    assertEquals(rows[0].date, "2030-01-03");
    assertEquals(rows[1].date, "2030-01-02");
    await sb.from("regime_state").delete().in("date", ["2029-12-31", "2030-01-02", "2030-01-03"]);
  },
});

// ---------------------------------------------------------------------------
// #383 T2: equity_snapshots — one row per trading day, sourced from
// alpaca.getAccountValue() via daily-check; read by status for trailing
// returns.
// ---------------------------------------------------------------------------

Deno.test("coerceEquitySnapshotRow: numeric string -> number (PostgREST returns numeric as string)", () => {
  const row = coerceEquitySnapshotRow({
    date: "2026-07-08",
    equity_usd: "101234.5600",
    created_at: "2026-07-08T13:38:00Z",
  });
  assertEquals(row.date, "2026-07-08");
  assertEquals(row.equity_usd, 101234.56);
  assertEquals(row.created_at, "2026-07-08T13:38:00Z");
});

Deno.test("coerceEquitySnapshotRow: also accepts numbers (round-trip)", () => {
  const row = coerceEquitySnapshotRow({
    date: "2026-07-08",
    equity_usd: 100000,
  });
  assertEquals(row.equity_usd, 100000);
});

Deno.test("coerceEquitySnapshotRow: non-numeric equity_usd throws", () => {
  assertThrows(
    () =>
      coerceEquitySnapshotRow({
        date: "2026-07-08",
        equity_usd: "not-a-number",
      }),
    DataError,
  );
});

Deno.test({
  name: "upsertEquitySnapshot: same-date upsert replaces equity_usd (idempotent re-run)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await sb.from("equity_snapshots").delete().eq("date", "2030-01-02");
    await upsertEquitySnapshot(sb, { date: "2030-01-02", equityUsd: 100000 });
    await upsertEquitySnapshot(sb, { date: "2030-01-02", equityUsd: 100500.25 });
    const { data } = await sb.from("equity_snapshots").select("*").eq("date", "2030-01-02")
      .single();
    assertEquals(Number(data?.equity_usd), 100500.25);
    await sb.from("equity_snapshots").delete().eq("date", "2030-01-02");
  },
});

Deno.test({
  name: "getEarliestEquitySnapshot / getLatestEquitySnapshot: return the min/max date row",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const dates = ["2030-02-01", "2030-02-02", "2030-02-03"];
    await sb.from("equity_snapshots").delete().in("date", dates);
    await upsertEquitySnapshot(sb, { date: "2030-02-01", equityUsd: 90000 });
    await upsertEquitySnapshot(sb, { date: "2030-02-02", equityUsd: 91000 });
    await upsertEquitySnapshot(sb, { date: "2030-02-03", equityUsd: 92000 });
    const earliest = await getEarliestEquitySnapshot(sb);
    const latest = await getLatestEquitySnapshot(sb);
    assertEquals(earliest?.date, "2030-02-01");
    assertEquals(earliest?.equity_usd, 90000);
    assertEquals(latest?.date, "2030-02-03");
    assertEquals(latest?.equity_usd, 92000);
    await sb.from("equity_snapshots").delete().in("date", dates);
  },
});

Deno.test({
  name: "getEquitySnapshotsSince: returns rows with date >= sinceDate, ascending",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const dates = ["2030-03-01", "2030-03-02", "2030-03-03"];
    await sb.from("equity_snapshots").delete().in("date", dates);
    await upsertEquitySnapshot(sb, { date: "2030-03-01", equityUsd: 90000 });
    await upsertEquitySnapshot(sb, { date: "2030-03-02", equityUsd: 91000 });
    await upsertEquitySnapshot(sb, { date: "2030-03-03", equityUsd: 92000 });
    const rows = await getEquitySnapshotsSince(sb, "2030-03-02");
    assertEquals(rows.length, 2);
    assertEquals(rows[0].date, "2030-03-02");
    assertEquals(rows[1].date, "2030-03-03");
    await sb.from("equity_snapshots").delete().in("date", dates);
  },
});
