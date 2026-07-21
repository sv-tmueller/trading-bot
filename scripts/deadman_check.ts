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
  daily_check: { started_at: string; outcome: string | null } | null;
  kill_switch: { started_at: string; outcome: string | null } | null;
}

// ---------------------------------------------------------------------------
// Constants — derived from the pg_cron schedules (CLAUDE.md "Daily flow" /
// "Intraday kill-switch"). No trading-day/holiday calendar is needed
// anywhere in this script: both daily-check and kill-switch write their
// audit_log row *before any gate* (market-closed, paused, etc.), so even a
// holiday leaves a fresh row with a `skipped:*` outcome — staleness here is
// measured purely against the UTC cron schedule, and outcome content is
// never inspected (see the "skipped:market_closed" test case).
// ---------------------------------------------------------------------------

// daily-check pg_cron: "37 13 * * 1-5" and "37 14 * * 1-5" UTC (two slots,
// DST-invariant). The finding only arms once both slots have had a chance to
// run — 14:37 + a short grace window, rounded up to 15:00 UTC (audit rows
// are written at run *start*, so the grace only needs to cover scheduling
// jitter, not a full run's duration).
const DAILY_CHECK_ARM_UTC = { hour: 15, minute: 0 } as const;
// A daily-check row counts as "ran today" once its started_at is at or after
// today's first slot (13:37 UTC) with a little headroom — 13:30 UTC. Any row
// older than that must be from a prior day (rows are append-only, ordered by
// started_at), meaning neither of today's slots has fired yet.
const DAILY_CHECK_CUTOFF_UTC = { hour: 13, minute: 30 } as const;

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

  // daily-check
  if (
    now.getTime() >= todayAt(now, DAILY_CHECK_ARM_UTC.hour, DAILY_CHECK_ARM_UTC.minute).getTime()
  ) {
    const dc = lastRuns.daily_check;
    if (dc == null) {
      findings.push(
        "daily-check: no audit_log row at all (last_runs.daily_check is null) — the scheduled pg_cron job appears to have stopped invoking daily-check.",
      );
    } else {
      const startedAt = parseTimestamp(dc.started_at, "last_runs.daily_check.started_at");
      const cutoff = todayAt(now, DAILY_CHECK_CUTOFF_UTC.hour, DAILY_CHECK_CUTOFF_UTC.minute);
      if (startedAt.getTime() < cutoff.getTime()) {
        findings.push(
          `daily-check: stale — latest run started ${dc.started_at}, before today's ${cutoff.toISOString()} cutoff (neither scheduled slot has run today).`,
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
