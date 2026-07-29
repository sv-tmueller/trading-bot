import { assertEquals, assertRejects, assertThrows } from "@std/assert";
import { createClient } from "@supabase/supabase-js";
import {
  claimBar,
  coerceEquitySnapshotRow,
  coerceHourlyScanRow,
  coerceRegimeRow,
  coerceTradeRow,
  deleteNotifications,
  enqueueNotification,
  getAuditLogSince,
  getConfig,
  getEarliestEquitySnapshot,
  getEquitySnapshotsSince,
  getHourlyScanByEntryOrderId,
  getHourlyScansPendingEntry,
  getLastTrade,
  getLatestAuditForScript,
  getLatestEquitySnapshot,
  getLatestRegimeState,
  getPendingNotifications,
  getRegimeStatesSince,
  getTradesSince,
  insertAuditLog,
  insertTrade,
  markNotificationAttempt,
  setConfig,
  updateAuditLog,
  upsertEquitySnapshot,
  upsertHourlyScan,
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

// ---------------------------------------------------------------------------
// #397 T2 (optional): notification_outbox roundtrip -- requires 0010 applied
// locally. Not a gate; the unit-level orchestration coverage lives in
// outbox.test.ts against plain fake deps.
// ---------------------------------------------------------------------------

Deno.test({
  name: "notification_outbox: enqueue -> getPending -> markAttempt -> delete roundtrip",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await enqueueNotification(sb, {
      eventType: "test_event",
      event: { event_type: "test_event", foo: "bar" },
    });
    const pending = await getPendingNotifications(sb, 10);
    const row = pending.find((r) => r.event_type === "test_event");
    if (!row) throw new Error("enqueued row not found in getPendingNotifications");
    assertEquals(row.attempts, 0);
    assertEquals(row.last_attempt_at, null);
    assertEquals(row.event, { event_type: "test_event", foo: "bar" });

    await markNotificationAttempt(sb, row.id, row.attempts + 1);
    const afterMark = await getPendingNotifications(sb, 10);
    const marked = afterMark.find((r) => r.id === row.id);
    assertEquals(marked?.attempts, 1);
    assertEquals(typeof marked?.last_attempt_at, "string");

    await deleteNotifications(sb, [row.id]);
    const afterDelete = await getPendingNotifications(sb, 10);
    assertEquals(afterDelete.some((r) => r.id === row.id), false);
  },
});

// ---------------------------------------------------------------------------
// #475 T7: hourly_scans + claimBar (bar_claims, owned by the sibling #474
// package). These use lightweight mocked clients (not real Postgres) for the
// coercion / conflict-mapping / upsert-shape logic, per the sub-plan's own
// "mocked client" instruction -- the RUN_DB_TESTS-gated tests below cover the
// real round trip when a local Postgres with the 0011+0012 migrations
// applied is available.
// ---------------------------------------------------------------------------

Deno.test("coerceHourlyScanRow: round-trips numeric-string columns and defaults", () => {
  const row = coerceHourlyScanRow({
    symbol: "SPY",
    bar_ts: "2026-07-27T14:00:00Z",
    decision: "LONG",
    skip_reason: null,
    detectors_fired: ["hammer", "bullish_pin_bar"],
    context_mode: "none",
    entry_ref_price: "550.1000",
    stop_price: "547.7500",
    target_price: "554.5500",
    risk_per_share: "2.3500",
    equity_usd: "100000.0000",
    qty: "18",
    entry_order_id: "o1",
  });
  assertEquals(row.entry_ref_price, 550.1);
  assertEquals(row.stop_price, 547.75);
  assertEquals(row.target_price, 554.55);
  assertEquals(row.risk_per_share, 2.35);
  assertEquals(row.equity_usd, 100000);
  assertEquals(row.qty, 18);
  assertEquals(row.detectors_fired, ["hammer", "bullish_pin_bar"]);
});

Deno.test("coerceHourlyScanRow: 'null unless computed' -- sizing columns null on a pre-gate SKIP", () => {
  const row = coerceHourlyScanRow({
    symbol: "SPY",
    bar_ts: "2026-07-27T14:00:00Z",
    decision: "SKIP",
    skip_reason: "signal_conflict",
    detectors_fired: ["bullish_harami", "shooting_star"],
    context_mode: "none",
    entry_ref_price: null,
    stop_price: null,
    target_price: null,
    risk_per_share: null,
    equity_usd: "100000.0000",
    qty: "0",
    entry_order_id: null,
  });
  assertEquals(row.entry_ref_price, null);
  assertEquals(row.stop_price, null);
  assertEquals(row.target_price, null);
  assertEquals(row.risk_per_share, null);
  assertEquals(row.qty, 0);
});

function fakeInsertClient(
  table: string,
  response: { error: { code?: string; message: string } | null },
  // deno-lint-ignore no-explicit-any
): any {
  const calls: unknown[] = [];
  return {
    calls,
    sb: {
      from: (t: string) => {
        if (t !== table) throw new Error(`unexpected table ${t}`);
        return {
          insert: (row: unknown) => {
            calls.push(row);
            return Promise.resolve(response);
          },
        };
      },
    },
  };
}

Deno.test("claimBar: insert succeeds -> true", async () => {
  const { sb, calls } = fakeInsertClient("bar_claims", { error: null });
  const claimed = await claimBar(sb, "hourly-check", "2026-07-27T14:00:00Z");
  assertEquals(claimed, true);
  assertEquals(calls, [{ script_name: "hourly-check", bar_ts: "2026-07-27T14:00:00Z" }]);
});

Deno.test("claimBar: 23505 unique-violation -> false (another invocation already claimed this bar)", async () => {
  const { sb } = fakeInsertClient("bar_claims", { error: { code: "23505", message: "dup" } });
  const claimed = await claimBar(sb, "hourly-check", "2026-07-27T14:00:00Z");
  assertEquals(claimed, false);
});

Deno.test("claimBar: any other error re-throws (never a false skipped:duplicate_run)", async () => {
  const { sb } = fakeInsertClient("bar_claims", { error: { code: "42P01", message: "boom" } });
  await assertRejects(
    () => claimBar(sb, "hourly-check", "2026-07-27T14:00:00Z"),
    Error,
    "claimBar",
  );
});

function fakeUpsertClient(
  table: string,
  response: { error: { message: string } | null } = { error: null },
  // deno-lint-ignore no-explicit-any
): any {
  const calls: Array<{ row: unknown; opts: unknown }> = [];
  return {
    calls,
    sb: {
      from: (t: string) => {
        if (t !== table) throw new Error(`unexpected table ${t}`);
        return {
          upsert: (row: unknown, opts: unknown) => {
            calls.push({ row, opts });
            return Promise.resolve(response);
          },
        };
      },
    },
  };
}

Deno.test("upsertHourlyScan: upserts on (symbol, bar_ts), same row twice is idempotent", async () => {
  const { sb, calls } = fakeUpsertClient("hourly_scans");
  const p = {
    symbol: "SPY",
    barTs: "2026-07-27T14:00:00Z",
    decision: "LONG" as const,
    skipReason: null,
    detectorsFired: ["hammer"],
    contextMode: "none",
    entryRefPrice: 550.1,
    stopPrice: 547.75,
    targetPrice: 554.55,
    riskPerShare: 2.35,
    equityUsd: 100000,
    qty: 18,
    entryOrderId: "o1",
  };
  await upsertHourlyScan(sb, p);
  await upsertHourlyScan(sb, p);
  assertEquals(calls.length, 2);
  assertEquals(calls[0].opts, { onConflict: "symbol,bar_ts" });
  assertEquals((calls[0].row as Record<string, unknown>).bar_ts, "2026-07-27T14:00:00Z");
  assertEquals(calls[0].row, calls[1].row);
});

Deno.test("upsertHourlyScan: throws on a DB error", async () => {
  const { sb } = fakeUpsertClient("hourly_scans", { error: { message: "boom" } });
  await assertRejects(
    () =>
      upsertHourlyScan(sb, {
        symbol: "SPY",
        barTs: "t",
        decision: "SKIP",
        skipReason: "no_detectors_fired",
        detectorsFired: [],
        contextMode: "none",
        entryRefPrice: null,
        stopPrice: null,
        targetPrice: null,
        riskPerShare: null,
        equityUsd: 100000,
        qty: 0,
        entryOrderId: null,
      }),
    Error,
    "upsertHourlyScan",
  );
});

Deno.test("getHourlyScanByEntryOrderId: filters by symbol + entry_order_id", async () => {
  const calls: Array<[string, unknown]> = [];
  // deno-lint-ignore no-explicit-any
  const builder: any = {
    select: () => builder,
    eq: (col: string, val: unknown) => {
      calls.push([col, val]);
      return builder;
    },
    order: () => builder,
    limit: () => builder,
    maybeSingle: () =>
      Promise.resolve({
        data: {
          symbol: "SPY",
          bar_ts: "2026-07-27T14:00:00Z",
          decision: "LONG",
          skip_reason: null,
          detectors_fired: ["hammer"],
          context_mode: "none",
          entry_ref_price: "550.1000",
          stop_price: "547.7500",
          target_price: "554.5500",
          risk_per_share: "2.3500",
          equity_usd: "100000.0000",
          qty: "18",
          entry_order_id: "o1",
        },
        error: null,
      }),
  };
  // deno-lint-ignore no-explicit-any
  const sb = { from: () => builder } as any;
  const row = await getHourlyScanByEntryOrderId(sb, "SPY", "o1");
  assertEquals(row?.bar_ts, "2026-07-27T14:00:00Z");
  assertEquals(calls, [["symbol", "SPY"], ["entry_order_id", "o1"]]);
});

Deno.test({
  name:
    "hourly_scans: upsert + getHourlyScanByEntryOrderId roundtrip (ON CONFLICT replaces same bar)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    await sb.from("hourly_scans").delete().eq("symbol", "SPY").eq(
      "bar_ts",
      "2030-01-02T14:00:00Z",
    );
    await upsertHourlyScan(sb, {
      symbol: "SPY",
      barTs: "2030-01-02T14:00:00Z",
      decision: "LONG",
      skipReason: null,
      detectorsFired: ["hammer"],
      contextMode: "none",
      entryRefPrice: 550.1,
      stopPrice: 547.75,
      targetPrice: 554.55,
      riskPerShare: 2.35,
      equityUsd: 100000,
      qty: 18,
      entryOrderId: "o1",
    });
    await upsertHourlyScan(sb, {
      symbol: "SPY",
      barTs: "2030-01-02T14:00:00Z",
      decision: "LONG",
      skipReason: null,
      detectorsFired: ["hammer"],
      contextMode: "none",
      entryRefPrice: 550.1,
      stopPrice: 547.75,
      targetPrice: 554.55,
      riskPerShare: 2.35,
      equityUsd: 100000,
      qty: 18,
      entryOrderId: "o2",
    });
    const row = await getHourlyScanByEntryOrderId(sb, "SPY", "o2");
    assertEquals(row?.bar_ts, "2030-01-02T14:00:00Z");
    assertEquals(row?.entry_order_id, "o2");
    assertEquals(row?.qty, 18);
    await sb.from("hourly_scans").delete().eq("symbol", "SPY").eq(
      "bar_ts",
      "2030-01-02T14:00:00Z",
    );
  },
});

// ---------------------------------------------------------------------------
// #480 T2: getHourlyScansPendingEntry -- pending-entry scan lookup consumed by
// the reconciliation recovery step (logic.ts reconcile()). Round-1 finding 9
// removed the dead getHourlyScanByBar helper (a bar-oriented read with no
// consumer); this one deliberately reintroduces a bar-oriented read because
// it has a wired consumer.
// ---------------------------------------------------------------------------

function pendingEntryBuilder(
  response: { data: unknown[] | null; error: { message: string } | null },
) {
  const calls: {
    eq?: [string, unknown];
    in?: [string, unknown[]];
    is?: [string, unknown];
    gte?: [string, unknown];
    order?: [string, unknown];
  } = {};
  // deno-lint-ignore no-explicit-any
  const builder: any = {
    select: () => builder,
    eq: (col: string, val: unknown) => {
      calls.eq = [col, val];
      return builder;
    },
    in: (col: string, vals: unknown[]) => {
      calls.in = [col, vals];
      return builder;
    },
    is: (col: string, val: unknown) => {
      calls.is = [col, val];
      return builder;
    },
    gte: (col: string, val: unknown) => {
      calls.gte = [col, val];
      return builder;
    },
    order: (col: string, opts: unknown) => {
      calls.order = [col, opts];
      return builder;
    },
    limit: () => Promise.resolve(response),
  };
  return { calls, sb: { from: () => builder } };
}

Deno.test("getHourlyScansPendingEntry: selects LONG/SHORT rows with entry_order_id IS NULL, ascending bar_ts, since the cutoff", async () => {
  const { calls, sb } = pendingEntryBuilder({
    data: [
      {
        symbol: "SPY",
        bar_ts: "2026-07-27T14:00:00Z",
        decision: "LONG",
        skip_reason: null,
        detectors_fired: ["hammer"],
        context_mode: "none",
        entry_ref_price: "550.1000",
        stop_price: "547.7500",
        target_price: "554.5500",
        risk_per_share: "2.3500",
        equity_usd: "100000.0000",
        qty: "18",
        entry_order_id: null,
      },
    ],
    error: null,
  });
  // deno-lint-ignore no-explicit-any
  const rows = await getHourlyScansPendingEntry(sb as any, "SPY", "2026-07-22T00:00:00Z");
  assertEquals(rows.length, 1);
  assertEquals(rows[0].bar_ts, "2026-07-27T14:00:00Z");
  assertEquals(rows[0].entry_order_id, null);
  assertEquals(calls.eq, ["symbol", "SPY"]);
  assertEquals(calls.in, ["decision", ["LONG", "SHORT"]]);
  assertEquals(calls.is, ["entry_order_id", null]);
  assertEquals(calls.gte, ["bar_ts", "2026-07-22T00:00:00Z"]);
  assertEquals(calls.order, ["bar_ts", { ascending: true }]);
});

Deno.test("getHourlyScansPendingEntry: throws on a DB error", async () => {
  const { sb } = pendingEntryBuilder({ data: null, error: { message: "boom" } });
  await assertRejects(
    // deno-lint-ignore no-explicit-any
    () => getHourlyScansPendingEntry(sb as any, "SPY", "2026-07-22T00:00:00Z"),
    Error,
    "getHourlyScansPendingEntry",
  );
});

Deno.test({
  name:
    "getHourlyScansPendingEntry: real-Postgres round trip -- only LONG/SHORT rows with a null entry_order_id, ascending bar_ts",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const barTsPending = "2030-01-03T15:00:00Z";
    const barTsJournaled = "2030-01-03T14:00:00Z";
    const barTsSkip = "2030-01-03T16:00:00Z";
    await sb.from("hourly_scans").delete().eq("symbol", "SPY").in("bar_ts", [
      barTsPending,
      barTsJournaled,
      barTsSkip,
    ]);
    const base = {
      symbol: "SPY",
      skipReason: null,
      detectorsFired: [],
      contextMode: "none",
      entryRefPrice: 550,
      stopPrice: 547,
      targetPrice: 554,
      riskPerShare: 3,
      equityUsd: 100000,
      qty: 18,
    };
    await upsertHourlyScan(sb, {
      ...base,
      barTs: barTsPending,
      decision: "LONG",
      entryOrderId: null,
    });
    await upsertHourlyScan(sb, {
      ...base,
      barTs: barTsJournaled,
      decision: "LONG",
      entryOrderId: "o1",
    });
    await upsertHourlyScan(sb, {
      ...base,
      barTs: barTsSkip,
      decision: "SKIP",
      skipReason: "no_detectors_fired",
      entryRefPrice: null,
      stopPrice: null,
      targetPrice: null,
      riskPerShare: null,
      qty: 0,
      entryOrderId: null,
    });
    const rows = await getHourlyScansPendingEntry(sb, "SPY", "2030-01-01T00:00:00Z");
    assertEquals(rows.map((r: { bar_ts: string }) => r.bar_ts), [barTsPending]);
    await sb.from("hourly_scans").delete().eq("symbol", "SPY").in("bar_ts", [
      barTsPending,
      barTsJournaled,
      barTsSkip,
    ]);
  },
});

// claimBar consumes bar_claims (owned by #474) without owning the schema --
// this integration test must skip cleanly when the table is absent (it lands
// via #474's migration 0011, not this branch's 0012).
Deno.test({
  name:
    "claimBar: real-Postgres roundtrip (skips cleanly if bar_claims is absent -- owned by #474)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const scriptName = "hourly-check-test";
    const barTs = "2030-01-02T14:00:00Z";
    const probe = await sb.from("bar_claims").select("*").limit(1);
    if (probe.error && /relation .* does not exist/i.test(probe.error.message)) {
      console.warn("claimBar roundtrip: bar_claims table absent (lands via #474) -- skipping");
      return;
    }
    await sb.from("bar_claims").delete().eq("script_name", scriptName).eq("bar_ts", barTs);
    const first = await claimBar(sb, scriptName, barTs);
    const second = await claimBar(sb, scriptName, barTs);
    assertEquals(first, true);
    assertEquals(second, false);
    await sb.from("bar_claims").delete().eq("script_name", scriptName).eq("bar_ts", barTs);
  },
});

// ---------------------------------------------------------------------------
// #474 T1: bar_claims (0011) -- the hourly bot's bar-level concurrency guard,
// the property trade_claims' date-granularity PK cannot express: two claims
// on the same trading day, keyed on different bar timestamps, must both
// succeed. This package ships no consumer helper (D6) -- inserts go straight
// through the client, mirroring how the migration itself is tested.
// ---------------------------------------------------------------------------

Deno.test({
  name: "bar_claims: first insert wins, same (script_name, bar_ts) conflicts with 23505",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const barTs = "2030-01-02T14:00:00Z";
    await sb.from("bar_claims").delete().eq("script_name", "bar-claims-test").eq(
      "bar_ts",
      barTs,
    );
    const first = await sb.from("bar_claims").insert({
      script_name: "bar-claims-test",
      bar_ts: barTs,
    });
    assertEquals(first.error, null);
    const second = await sb.from("bar_claims").insert({
      script_name: "bar-claims-test",
      bar_ts: barTs,
    });
    assertEquals(second.error?.code, "23505");
    await sb.from("bar_claims").delete().eq("script_name", "bar-claims-test").eq(
      "bar_ts",
      barTs,
    );
  },
});

Deno.test({
  name:
    "bar_claims: a different bar_ts the same day is a separate claim (property trade_claims lacks)",
  ignore: !RUN,
  fn: async () => {
    const sb = localClient();
    const barTs1 = "2030-01-03T14:00:00Z";
    const barTs2 = "2030-01-03T15:00:00Z";
    await sb.from("bar_claims").delete().eq("script_name", "bar-claims-test").in(
      "bar_ts",
      [barTs1, barTs2],
    );
    const first = await sb.from("bar_claims").insert({
      script_name: "bar-claims-test",
      bar_ts: barTs1,
    });
    const secondSameDayDifferentBar = await sb.from("bar_claims").insert({
      script_name: "bar-claims-test",
      bar_ts: barTs2,
    });
    assertEquals(first.error, null);
    assertEquals(secondSameDayDifferentBar.error, null);
    await sb.from("bar_claims").delete().eq("script_name", "bar-claims-test").in(
      "bar_ts",
      [barTs1, barTs2],
    );
  },
});
