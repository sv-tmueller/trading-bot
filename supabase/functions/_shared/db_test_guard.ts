// Test-only safety rails for the RUN_DB_TESTS-gated integration suite (#485).
//
// The gated tests write to shared tables (`bot_config`, `trades`, `audit_log`,
// `regime_state`, `hourly_scans`, ...). They build their client from
// SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY, which only *default* to the local
// `supabase start` stack, so an operator who exported those vars for a hosted
// project (the rollout ops window does exactly that) would silently point a
// destructive suite at a live paper bot's database.
//
// Two rails, both mechanical:
//   - `createLocalDbClient()` refuses any host that is not this machine, before
//     a client exists, so no query can leave the box.
//   - `withConfigRestored()` puts a `bot_config` key back the way the test
//     found it, so a local run cannot leave the operational kill switch
//     (`paused`) at whatever the test wrote.
// `db_test_guard.test.ts` additionally scans db.test.ts to prove it still goes
// through both, since either could be unwired with the suite still green.
//
// This file is deliberately not named `*.test.ts` / `*_test.ts` so `deno test`
// does not collect it; it is imported by db.test.ts and db_test_guard.test.ts.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { getConfig, setConfig } from "./db.ts";

/** Hostnames that can only ever be a developer's own machine. */
const LOCAL_HOSTNAMES = new Set([
  "localhost",
  "::1",
  // Set by Docker Desktop for "the host that runs the containers" - the address
  // a suite running inside a container uses to reach a local `supabase start`.
  "host.docker.internal",
]);

/** The whole IPv4 loopback block, not just 127.0.0.1. */
const IPV4_LOOPBACK = /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/;

export class RemoteSupabaseHostError extends Error {
  /** The refused hostname, or null when the URL never parsed into one. */
  readonly host: string | null;
  constructor(message: string, host: string | null) {
    super(message);
    this.name = "RemoteSupabaseHostError";
    this.host = host;
  }
}

const ALLOWED_HOSTS_HINT = "localhost, 127.0.0.0/8, ::1, host.docker.internal";

/**
 * Allowlist, not denylist: an unrecognized host is remote by default, so a new
 * hosted project cannot become reachable by omission. The port is intentionally
 * not part of the check - local stacks legitimately move ports, and no hostname
 * in the allowlist can ever resolve to a hosted `<ref>.supabase.co` project.
 *
 * Called in isolation this predicate is looser than the entry path: it accepts
 * out-of-range octets (`127.999.0.1`) and surrounding whitespace, because the
 * only caller is `assertLocalSupabaseUrl`, where WHATWG `URL` has already
 * rejected or normalized every such input. Everything it accepts is inside
 * 127/8 regardless, so the looseness costs nothing - do not tighten the regex
 * on the strength of an isolated call.
 */
export function isLocalSupabaseHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase().replace(/^\[|\]$/g, "");
  return LOCAL_HOSTNAMES.has(host) || IPV4_LOOPBACK.test(host);
}

export function assertLocalSupabaseUrl(url: string): void {
  let hostname: string;
  try {
    hostname = new URL(url).hostname;
  } catch {
    throw new RemoteSupabaseHostError(
      `RUN_DB_TESTS refused: SUPABASE_URL "${url}" is not a parseable URL, so it cannot be ` +
        `confirmed local. The gated DB tests write to shared tables and may only run against a ` +
        `local supabase stack (${ALLOWED_HOSTS_HINT}).`,
      null,
    );
  }
  if (isLocalSupabaseHost(hostname)) return;
  // 0.0.0.0 is the one near-miss worth naming: it is a wildcard *bind* address
  // that some stacks print, not a destination, so it stays off the allowlist.
  const wildcardHint = hostname === "0.0.0.0"
    ? ` Note that 0.0.0.0 is a wildcard bind address rather than a destination; use 127.0.0.1.`
    : "";
  throw new RemoteSupabaseHostError(
    `RUN_DB_TESTS refused: SUPABASE_URL host "${hostname}" is not a local supabase stack. ` +
      `The gated DB tests write to shared tables (bot_config.paused, trades, audit_log, ` +
      `regime_state, hourly_scans) and would mutate that project - against a live project they ` +
      `can clear the operational kill switch. Allowed hosts: ${ALLOWED_HOSTS_HINT} (any port). ` +
      `Run \`supabase start\` and point SUPABASE_URL at its API URL, or unset it to use the ` +
      `http://127.0.0.1:54321 default.${wildcardHint}`,
    hostname,
  );
}

/**
 * The single entry point the gated tests use to reach Postgres. Validates the
 * host before any client is constructed, so no query can be issued against a
 * non-local project.
 */
export function createLocalDbClient(): SupabaseClient {
  // From `supabase status`: API URL + service_role key. Defaults below match a
  // standard local stack; override via env if your local ports differ.
  const url = Deno.env.get("SUPABASE_URL") ?? "http://127.0.0.1:54321";
  assertLocalSupabaseUrl(url);
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  return createClient(url, key, { auth: { persistSession: false } });
}

/**
 * Runs `fn` and puts `bot_config[key]` back exactly as it was found, including
 * when `fn` throws. A key that did not exist is deleted again rather than left
 * behind at whatever the test wrote. `bot_config.paused` is the operational
 * kill switch, so a gated test that mutates it must never be the reason it
 * ends up cleared.
 */
export async function withConfigRestored(
  sb: SupabaseClient,
  key: string,
  fn: () => Promise<void>,
): Promise<void> {
  const prior = await getConfig(sb, key);
  let bodyError: unknown;
  let bodyFailed = false;
  try {
    await fn();
  } catch (e) {
    bodyError = e;
    bodyFailed = true;
  }
  try {
    if (prior === null) {
      const { error } = await sb.from("bot_config").delete().eq("key", key);
      if (error) throw new Error(`withConfigRestored: delete ${key}: ${error.message}`);
    } else {
      await setConfig(sb, key, prior);
    }
  } catch (restoreError) {
    // The body's failure is the diagnostic that matters; a restore that also
    // failed is reported alongside it rather than replacing it.
    if (bodyFailed) console.error(`withConfigRestored: failed to restore ${key}`, restoreError);
    else throw restoreError;
  }
  if (bodyFailed) throw bodyError;
}
