-- Retire the daily-check ENTRY crons only (#479 T6, lead-ratified on #478).
--
-- Why this is a precondition of the hourly-bot rollout, not new scope: the
-- rollout's gate 1 requires resuming bot_config.paused=false (currently
-- true, per #479's repo-facts baseline) so hourly-check can place its first
-- entries. But daily-check (the retired UPRO/200-DMA bot, deprecated by
-- #465) still honors the same paused flag -- resuming it would re-arm
-- daily-check's own entry crons on their next 13:37/14:37 UTC slot, putting
-- two bots' entries on the same Alpaca paper account simultaneously. That is
-- exactly the "two bots, one account" case #465's deprecation ADR rejects.
-- Neutralizing daily-check's entry crons before resume is therefore required
-- by the already-approved rollout, not a new decision -- this migration is
-- the auditable, guarded form of that precondition.
--
-- Scope, deliberately narrow (per #465's "full decommission after soak"
-- non-goal -- this is NOT that):
--   - Unschedules ONLY the two daily-check entry cron jobs
--     (daily-check-1337, daily-check-1437 -- see 0006_daily_check_open_
--     schedule.sql). Guarded existence checks (0004's idempotent pattern),
--     so this migration is safe to re-run and safe to apply even if a job
--     was already removed by hand.
--   - kill-switch's cron job is UNTOUCHED -- it must keep protecting any
--     residual daily-check position (UPRO) through the decommission window,
--     per #465's explicit requirement that kill-switch coverage continues
--     until the old bot is fully flat.
--   - panic and status are Edge Functions with no cron entry; untouched.
--   - The daily-check Edge Function's CODE is untouched -- this migration is
--     schedule-only. The deployed function still exists; it simply has no
--     cron trigger left to invoke it (an operator-triggered manual run is
--     still possible if ever needed for forensics).
--
-- Operational precondition stated in the rollout runbook (docs/runbooks/
-- hourly-bot-rollout.md): resuming bot_config.paused=false is FORBIDDEN
-- before this migration has been applied.
--
-- Disclosure (per the sub-plan): applying this migration stops the no-op
-- daily-check audit_log rows that the paused gate has been writing on dev
-- (skipped:trading_paused, once per cron firing) -- an intended, harmless
-- side effect, not a data-loss concern (audit_log rows already written are
-- untouched).

do $$
begin
  if exists (select 1 from cron.job where jobname = 'daily-check-1337') then
    perform cron.unschedule('daily-check-1337');
  end if;
  if exists (select 1 from cron.job where jobname = 'daily-check-1437') then
    perform cron.unschedule('daily-check-1437');
  end if;
  -- Guard against the pre-#256 job name too, in case a project was never
  -- upgraded past 0002/0004's original single 'daily-check' job before
  -- 0006 split it into the two open-schedule slots.
  if exists (select 1 from cron.job where jobname = 'daily-check') then
    perform cron.unschedule('daily-check');
  end if;
end;
$$;
