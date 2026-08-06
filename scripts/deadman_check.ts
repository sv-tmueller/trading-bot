// Dead-man watchdog evaluation (#396 T2). Pure `evaluateDeadman` function
// (unit-tested in deadman_check.test.ts) plus a thin CLI that reads the
// `status` Edge Function's digest JSON from **stdin** (zero Deno permissions
// needed — no --allow-net/--allow-env/--allow-read) and exits:
//   0 - healthy (no findings)
//   2 - findings (printed to stdout, one per line)
//   1 - malformed input (bad JSON, missing/invalid last_runs, unparseable
//       timestamp)
//
// `.github/workflows/deadman-watchdog.yml` fetches the digest with curl and
// pipes it in: `deno run scripts/deadman_check.ts < digest.json`.
//
// A minimal local input type is defined below instead of importing
// StatusDigest from supabase/functions/status/logic.ts — this keeps the
// script structurally coupled to the JSON shape only, not to the Edge
// Function module (which pulls in Alpaca/Supabase client types this script
// has no business depending on).
export interface DeadmanLastRuns {
  kill_switch: { started_at: string; outcome: string | null } | null;
  // Optional: absent entirely on a status digest deployed before #536
  // shipped last_runs.hourly_check. `undefined` (key missing) and `null`
  // (key present, no audit_log row yet) are two DISTINCT findings below --
  // do not collapse them with `== null`.
  hourly_check?: { started_at: string; outcome: string | null } | null;
}

// ---------------------------------------------------------------------------
// Constants — derived from the pg_cron schedules (CLAUDE.md "Daily flow" /
// "Intraday kill-switch"). No trading-day/holiday calendar is needed
// anywhere in this script: both kill-switch and hourly-check write their
// audit_log row *before any gate* (market-closed, paused, etc. —
// hourly-check's `insertAuditLog` call at hourly-check/logic.ts precedes its
// paused/paper/clock gates, same as kill-switch), so even a holiday leaves a
// fresh row with a `skipped:*` outcome — staleness here is measured purely
// against the UTC cron schedule, and outcome content is never inspected (see
// the "skipped:market_closed" test case).
// ---------------------------------------------------------------------------

// hourly-check pg_cron: "7 13-21 * * 1-5" UTC (migration 0014) — 9 daily
// slots at :07 past each hour, 13:07 through 21:07 UTC. Stale threshold is
// the 60-minute cadence plus ~15 minutes' grace (covers the cron's own
// 7-minute minute-offset, observed feed latency, and evaluation-timing
// variance) — comfortably above kill-switch's 20-minute floor and above the
// cadence itself, so a healthy bot is never flagged mid-hour.
//
// Distinct from _shared/config.ts's HOURLY_STALENESS_TOLERANCE_MIN, which
// governs *bar* freshness inside hourly-check itself, not *audit_log-row*
// freshness as observed externally by this script — do not conflate the two.
const HOURLY_CHECK_STALE_MINUTES = 75;
// armStart = firstSlot (13:07) + staleThreshold (75min) = 14:22 UTC,
// mirroring kill-switch's exact derivation: guarantees no false alarm from
// yesterday's leftover 21:07 row before today's first slot has had a full
// threshold's grace to land.
const HOURLY_CHECK_ARM_START_UTC = { hour: 14, minute: 22 } as const;
// Reuses kill-switch's own end-of-day boundary. Satisfies
// armEnd <= lastSlot (21:07) + staleThreshold (75min) = 22:22, with 12
// minutes of margin.
const HOURLY_CHECK_ARM_END_UTC = { hour: 22, minute: 10 } as const;

// kill-switch pg_cron: "*/5 13-21 * * 1-5" UTC, i.e. 13:00-21:55 UTC. Armed
// window starts at 13:20 UTC (avoids a false alarm right at window start,
// when yesterday's 21:55 row is still the latest until the 13:00 slot
// lands) and ends at 22:10 UTC (covers the final 21:55 slot with grace). A
// jitter-delayed evaluation run past 22:10 simply skips the check rather
// than false-alarming.
const KILL_SWITCH_ARM_START_UTC = { hour: 13, minute: 20 } as const;
const KILL_SWITCH_ARM_END_UTC = { hour: 22, minute: 10 } as const;
// 4 missed 5-minute slots. Do not tighten below 20 minutes — GitHub Actions
// schedule jitter (a few minutes, sometimes up to ~1h) would false-alarm at
// a shorter threshold.
const KILL_SWITCH_STALE_MINUTES = 20;

function todayAt(now: Date, hour: number, minute: number): Date {
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, minute, 0, 0),
  );
}

function parseTimestamp(iso: string, label: string): Date {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    throw new Error(`deadman_check: invalid timestamp for ${label}: ${JSON.stringify(iso)}`);
  }
  return d;
}

// Pure evaluation: given the status digest's `last_runs` field and the
// current time, returns a list of human-readable finding messages (empty =
// healthy). Throws on structurally invalid input (missing `last_runs`,
// unparseable timestamps) — the CLI below maps that to exit code 1.
export function evaluateDeadman(lastRuns: DeadmanLastRuns, now: Date): string[] {
  if (lastRuns == null || typeof lastRuns !== "object") {
    throw new Error("deadman_check: digest is missing last_runs");
  }

  const findings: string[] = [];
  const utcDay = now.getUTCDay(); // 0 = Sunday, 6 = Saturday
  const isWeekday = utcDay >= 1 && utcDay <= 5;
  if (!isWeekday) {
    return findings;
  }

  // hourly-check
  const hourlyArmStart = todayAt(
    now,
    HOURLY_CHECK_ARM_START_UTC.hour,
    HOURLY_CHECK_ARM_START_UTC.minute,
  );
  const hourlyArmEnd = todayAt(now, HOURLY_CHECK_ARM_END_UTC.hour, HOURLY_CHECK_ARM_END_UTC.minute);
  if (now.getTime() >= hourlyArmStart.getTime() && now.getTime() <= hourlyArmEnd.getTime()) {
    const hc = lastRuns.hourly_check;
    // `undefined` (key absent -- digest predates #536) and `null` (key
    // present, no row yet) are two DISTINCT findings. Do NOT collapse with
    // `== null`.
    if (hc === undefined) {
      findings.push(
        "hourly-check: last_runs.hourly_check is absent from the digest — the deployed status function predates hourly-bot coverage (#536); redeploy status to enable this check.",
      );
    } else if (hc === null) {
      findings.push(
        "hourly-check: no audit_log row at all (last_runs.hourly_check is null) — the scheduled pg_cron job appears to have stopped invoking hourly-check.",
      );
    } else {
      const startedAt = parseTimestamp(hc.started_at, "last_runs.hourly_check.started_at");
      const ageMinutes = (now.getTime() - startedAt.getTime()) / 60_000;
      if (ageMinutes > HOURLY_CHECK_STALE_MINUTES) {
        findings.push(
          `hourly-check: stale — latest run started ${hc.started_at}, ${
            ageMinutes.toFixed(1)
          } minutes ago (> ${HOURLY_CHECK_STALE_MINUTES}m threshold).`,
        );
      }
    }
  }

  // kill-switch
  const armStart = todayAt(now, KILL_SWITCH_ARM_START_UTC.hour, KILL_SWITCH_ARM_START_UTC.minute);
  const armEnd = todayAt(now, KILL_SWITCH_ARM_END_UTC.hour, KILL_SWITCH_ARM_END_UTC.minute);
  if (now.getTime() >= armStart.getTime() && now.getTime() <= armEnd.getTime()) {
    const ks = lastRuns.kill_switch;
    if (ks == null) {
      findings.push(
        "kill-switch: no audit_log row at all (last_runs.kill_switch is null) — the scheduled pg_cron job appears to have stopped invoking kill-switch.",
      );
    } else {
      const startedAt = parseTimestamp(ks.started_at, "last_runs.kill_switch.started_at");
      const ageMinutes = (now.getTime() - startedAt.getTime()) / 60_000;
      if (ageMinutes > KILL_SWITCH_STALE_MINUTES) {
        findings.push(
          `kill-switch: stale — latest run started ${ks.started_at}, ${
            ageMinutes.toFixed(1)
          } minutes ago (> ${KILL_SWITCH_STALE_MINUTES}m threshold).`,
        );
      }
    }
  }

  return findings;
}

// ---------------------------------------------------------------------------
// CLI entry point. Not exercised by any test — everything above is
// unit-tested with explicit `now`/`lastRuns` values (deadman_check.test.ts).
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  let raw: string;
  try {
    raw = await new Response(Deno.stdin.readable).text();
  } catch (e) {
    console.error(`deadman_check: failed to read stdin: ${(e as Error).message}`);
    Deno.exit(1);
    return;
  }

  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch (e) {
    console.error(`deadman_check: malformed JSON on stdin: ${(e as Error).message}`);
    Deno.exit(1);
    return;
  }

  try {
    const lastRuns = (body as { last_runs?: unknown }).last_runs as DeadmanLastRuns;
    const findings = evaluateDeadman(lastRuns, new Date());
    if (findings.length === 0) {
      console.log("deadman_check: healthy — no findings");
      Deno.exit(0);
    }
    for (const finding of findings) {
      console.log(finding);
    }
    Deno.exit(2);
  } catch (e) {
    console.error(`deadman_check: ${(e as Error).message}`);
    Deno.exit(1);
  }
}

if (import.meta.main) {
  main();
}
