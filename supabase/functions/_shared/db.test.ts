import { assertEquals } from "@std/assert";
import { createClient } from "@supabase/supabase-js";
import {
  getConfig,
  getLatestRegimeState,
  insertAuditLog,
  insertTrade,
  setConfig,
  updateAuditLog,
  upsertRegimeState,
} from "./db.ts";

const RUN = Deno.env.get("RUN_DB_TESTS") === "1";

function localClient() {
  // From `supabase status`: API URL + service_role key. Defaults below match a
  // standard local stack; override via env if your local ports differ.
  const url = Deno.env.get("SUPABASE_URL") ?? "http://127.0.0.1:54321";
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  return createClient(url, key, { auth: { persistSession: false } });
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
