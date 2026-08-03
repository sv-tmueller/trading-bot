// #397: durable notification outbox orchestration. Every notify helper
// wired through this module NEVER throws into its caller, under any
// combination of webhook-down / DB-down failures -- the same contract
// notify()/postEvent() already carry in notifications.ts.
//
// `OutboxDeps` mirrors the logic.ts injected-deps pattern so unit tests pass
// plain fake objects and never mock the supabase-js fluent query builder.
//
// Delivery semantics are at-least-once: a post that was actually received by
// the webhook but answered non-2xx (or timed out after delivery) may be
// re-sent by a later flush. Acceptable for alerts (duplicate is harmless;
// dropped is not).
// `supabase functions deploy`'s bundler does not resolve the repo-root deno.json import map, so
// this inline jsr: specifier is load-bearing for deployment.
// deno-lint-ignore no-import-prefix
import type { SupabaseClient } from "jsr:@supabase/supabase-js@^2.45.0";
import { getNotifyWebhookUrl } from "./config.ts";
import {
  brokerErrorEvent,
  equityFloorFiredEvent,
  errorEvent,
  killSwitchFiredEvent,
  type NotifyStatus,
  postEvent,
  regimeFlipEvent,
  stateDesyncEvent,
  tradeFailedEvent,
} from "./notifications.ts";
import {
  deleteNotifications,
  enqueueNotification,
  getPendingNotifications,
  markNotificationAttempt,
  type OutboxRow,
} from "./db.ts";

// Retry bounds (named constants, not env settings -- no config sprawl; the
// issue doesn't ask for tunables). TTL is the primary bound: 72h survives a
// weekend-long webhook outage (a Friday kill-switch fire still alerts
// Monday). The attempts cap is a large secondary safety net -- three trading
// days at the kill-switch's 5-min flush cadence is ~240 opportunities, so the
// cap never undercuts the TTL in practice. Batch cap bounds the webhook posts
// (and therefore response latency) added to a single daily-check/kill-switch
// invocation.
const OUTBOX_TTL_MS = 72 * 60 * 60 * 1000;
const OUTBOX_MAX_ATTEMPTS = 500;
const FLUSH_BATCH = 10;

const WARN_MSG_SNIPPET_MAX_CODEPOINTS = 200;

function truncateCodepoints(s: string, max: number): string {
  return [...s].slice(0, max).join("");
}

function errMsg(e: unknown): string {
  const raw = String(e instanceof Error ? e.message : e);
  return truncateCodepoints(raw, WARN_MSG_SNIPPET_MAX_CODEPOINTS);
}

export interface OutboxDeps {
  post: (event: Record<string, unknown>) => Promise<NotifyStatus>;
  enqueue: (p: { eventType: string; event: Record<string, unknown> }) => Promise<void>;
  getPending: (limit: number) => Promise<OutboxRow[]>;
  remove: (ids: number[]) => Promise<void>;
  markAttempt: (id: number, attempts: number) => Promise<void>;
  now: () => Date;
}

// Posts immediately; on "failed" (non-2xx or fetch rejection -- see
// postEvent's contract), durably enqueues the event for a later flush. On
// "skipped_unset" (webhook deliberately disabled), does nothing -- enqueueing
// here would grow the table with rows nothing will ever flush. NEVER throws:
// a DB failure while enqueueing is logged (event_type + truncated error
// message only -- never the payload, never the URL) and swallowed.
export async function notifyDurable(
  deps: OutboxDeps,
  eventType: string,
  event: Record<string, unknown>,
): Promise<void> {
  let status: NotifyStatus;
  try {
    status = await deps.post(event);
  } catch (e) {
    // postEvent() itself never throws; this is defense-in-depth against a
    // future regression or a caller passing a different `post`.
    console.warn(`outbox: post threw for event_type=${eventType}: ${errMsg(e)}`);
    return;
  }
  if (status !== "failed") return;
  try {
    await deps.enqueue({ eventType, event });
  } catch (e) {
    console.warn(`outbox: enqueue failed for event_type=${eventType}: ${errMsg(e)}`);
  }
}

// Retries pending rows, oldest first. Never throws: the entire body runs
// under one try/catch (outer catch -> warn, return). Early-returns before
// touching the DB at all when the webhook is unset -- nothing could be
// delivered, so there is nothing useful a flush can do.
export async function flushOutbox(deps: OutboxDeps): Promise<void> {
  try {
    if (getNotifyWebhookUrl() === "") return;

    const rows = await deps.getPending(FLUSH_BATCH);
    const now = deps.now().getTime();
    const toDelete: number[] = [];

    for (const row of rows) {
      const ageMs = now - new Date(row.created_at).getTime();
      if (ageMs > OUTBOX_TTL_MS || row.attempts >= OUTBOX_MAX_ATTEMPTS) {
        console.warn(
          `outbox: dropped id=${row.id} event_type=${row.event_type} attempts=${row.attempts}`,
        );
        toDelete.push(row.id);
        continue;
      }

      const status = await deps.post(row.event);
      if (status === "sent") {
        toDelete.push(row.id);
      } else if (status === "failed") {
        await deps.markAttempt(row.id, row.attempts + 1);
      } else {
        // skipped_unset: the webhook went from set to unset mid-flush.
        // Nothing further in this batch can deliver either -- stop, leaving
        // this row and any remaining rows in the batch intact.
        break;
      }
    }

    if (toDelete.length > 0) {
      await deps.remove(toDelete);
    }
  } catch (e) {
    console.warn(`outbox: flush failed: ${errMsg(e)}`);
  }
}

// Thin wiring only (binds the db.ts helpers + postEvent), mirroring
// buildDeps() in the handlers -- no dedicated test beyond type-checking.
// The returned `notifications` shape structurally satisfies both
// DailyCheckDeps["notifications"] and KillSwitchDeps["notifications"].
export function createOutbox(sb: SupabaseClient): {
  notifications: {
    notifyRegimeFlip: (p: Parameters<typeof regimeFlipEvent>[0]) => Promise<void>;
    notifyKillSwitchFired: (p: Parameters<typeof killSwitchFiredEvent>[0]) => Promise<void>;
    notifyTradeFailed: (p: Parameters<typeof tradeFailedEvent>[0]) => Promise<void>;
    notifyStateDesync: (p: Parameters<typeof stateDesyncEvent>[0]) => Promise<void>;
    notifyBrokerError: (p: Parameters<typeof brokerErrorEvent>[0]) => Promise<void>;
    notifyError: (message: string) => Promise<void>;
    notifyEquityFloorFired: (p: Parameters<typeof equityFloorFiredEvent>[0]) => Promise<void>;
  };
  flush: () => Promise<void>;
} {
  const deps: OutboxDeps = {
    post: postEvent,
    enqueue: (p) => enqueueNotification(sb, p),
    getPending: (limit) => getPendingNotifications(sb, limit),
    remove: (ids) => deleteNotifications(sb, ids),
    markAttempt: (id, attempts) => markNotificationAttempt(sb, id, attempts),
    now: () => new Date(),
  };
  return {
    notifications: {
      notifyRegimeFlip: (p) => {
        const event = regimeFlipEvent(p);
        return notifyDurable(deps, String(event.event_type), event);
      },
      notifyKillSwitchFired: (p) => {
        const event = killSwitchFiredEvent(p);
        return notifyDurable(deps, String(event.event_type), event);
      },
      notifyTradeFailed: (p) => {
        const event = tradeFailedEvent(p);
        return notifyDurable(deps, String(event.event_type), event);
      },
      notifyStateDesync: (p) => {
        const event = stateDesyncEvent(p);
        return notifyDurable(deps, String(event.event_type), event);
      },
      notifyBrokerError: (p) => {
        const event = brokerErrorEvent(p);
        return notifyDurable(deps, String(event.event_type), event);
      },
      notifyError: (message) => {
        const event = errorEvent(message);
        return notifyDurable(deps, String(event.event_type), event);
      },
      notifyEquityFloorFired: (p) => {
        const event = equityFloorFiredEvent(p);
        return notifyDurable(deps, String(event.event_type), event);
      },
    },
    flush: () => flushOutbox(deps),
  };
}
