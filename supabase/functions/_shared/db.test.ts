import { assertEquals, assertThrows } from "@std/assert";
import { createClient } from "@supabase/supabase-js";
import { Client as PgClient } from "https://deno.land/x/postgres@v0.19.3/mod.ts";
import {
  coerceRegimeRow,
  getConfig,
  getLatestRegimeState,
  insertAuditLog,
  insertTrade,
  setConfig,
  updateAuditLog,
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

// Direct Postgres connection for privilege assertions. supabase-js/PostgREST does not
// expose pg_catalog built-ins via RPC, so has_function_privilege must be called over
// a native Postgres connection. Defaults match `supabase status` for a local stack.
function pgConnectionString(): string {
  const host = Deno.env.get("SUPABASE_DB_HOST") ?? "127.0.0.1";
  const port = Deno.env.get("SUPABASE_DB_PORT") ?? "54322";
  const user = Deno.env.get("SUPABASE_DB_USER") ?? "postgres";
  const password = Deno.env.get("SUPABASE_DB_PASSWORD") ?? "postgres";
  const database = Deno.env.get("SUPABASE_DB_NAME") ?? "postgres";
  return `postgres://${user}:${password}@${host}:${port}/${database}`;
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

// Asserts that the 0007_vault_fn_grants.sql revoke took effect: neither `anon`
// nor `authenticated` may EXECUTE the Vault-read helpers. The service-role key
// used by localClient() bypasses this revoke, so we cannot call the function as
// the connected role and expect a permission error. Instead we query Postgres's
// privilege catalogue directly via has_function_privilege, running as superuser
// but checking the privilege of the other roles.
Deno.test({
  name: "0007: anon and authenticated lack EXECUTE on Vault helpers (has_function_privilege)",
  ignore: !RUN,
  fn: async () => {
    const pg = new PgClient(pgConnectionString());
    await pg.connect();
    try {
      for (const role of ["anon", "authenticated"]) {
        for (const fn of ["public._service_role_key()", "public._functions_base_url()"]) {
          const result = await pg.queryObject<{ priv: boolean }>(
            `SELECT has_function_privilege($1, $2, 'EXECUTE') AS priv`,
            [role, fn],
          );
          assertEquals(
            result.rows[0].priv,
            false,
            `expected ${role} to lack EXECUTE on ${fn}`,
          );
        }
      }
    } finally {
      await pg.end();
    }
  },
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
