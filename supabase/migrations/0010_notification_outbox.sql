-- #397: durable notification outbox. notifyDurable() (outbox.ts) enqueues a
-- row here whenever a direct-to-Discord post (postEvent in notifications.ts)
-- comes back "failed" (non-2xx or fetch rejection); flushOutbox() retries
-- pending rows from daily-check/kill-switch, bounded by a TTL + attempts cap
-- (both named constants in outbox.ts, not env settings — no config sprawl).
create table if not exists notification_outbox (
    id bigint generated always as identity primary key,
    event_type text not null,
    event jsonb not null,
    attempts integer not null default 0,
    last_attempt_at timestamptz,
    created_at timestamptz not null default now()
);

-- Edge Functions connect with the service-role key (bypasses RLS). Enable RLS
-- and add no policies so anon/public access is denied by default (same
-- deny-all pattern as 0001_init.sql / 0009_equity_snapshots.sql).
alter table notification_outbox enable row level security;
