-- Give the hourly-check cron an explicit net.http_post timeout (#498).
--
-- 0014 scheduled the job without a `timeout_milliseconds` argument, so pg_net's
-- 5000 ms default applied. Observed live on 2026-07-31: the session-close
-- flatten that closed the bot's first real position ran 19:07:00.708 ->
-- 19:07:05.840 = 5.132s in `audit_log`, so its `net._http_response` row records
-- `timed_out: true` with null content while the function completed normally and
-- closed a 137-share position. Skip-only scans (0.74-2.6s) stay clean, so the
-- runbook's §10 health check false-alarmed on exactly the sessions where the
-- bot traded.
--
-- The job name, schedule, URL expression, headers and body are reproduced
-- verbatim from 0014 -- the added `timeout_milliseconds` argument is the only
-- change. In particular the `:07` minute is unchanged: 0014's comment proves it
-- against spec §4's staleness inequality, and re-picking it is out of scope.
-- The guarded do-block is 0014's, itself matching 0004_cron_idempotent.sql's
-- unschedule-then-schedule pattern, so re-running this migration is a no-op
-- rather than an error on an existing job name.
--
--
-- What this timeout is actually for
--
-- Not headroom over a healthy scan. `alpaca.ts`'s `trade()` is a bare `fetch`
-- with no `AbortSignal` and no per-request timeout, and the poll loops in
-- `pollOrderUntilFilled` and `cancelOrder` accumulate `waited += intervalMs`,
-- i.e. **sleep only** -- the `await tradeJson(...)` inside each iteration is not
-- counted. So the function enforces no wall-clock bound on itself: against a
-- stalled broker connection a single request can hang indefinitely and the poll
-- loop never advances past it. That gap is filed as #511 and is deliberately
-- not fixed here.
--
-- Until #511 lands, this argument is the only bound anywhere in the cron path,
-- and the only mechanism that will ever surface a stalled invocation as an
-- observable event. It does not abort the Edge Function (see the 2026-07-31
-- evidence above); it bounds how long the pg_net worker waits, and therefore
-- when a stall gets recorded. That is what makes the number load-bearing rather
-- than cosmetic, and why it has to sit above the slowest *legitimate* scan: too
-- low and it fires on healthy trading sessions (the 5000 ms defect), too high
-- and the one stall detector in the path stays silent that much longer.
--
--
-- 120000 ms -- the derivation
--
-- Sizing off the observed 5.132s would be wrong twice over. It is one sample of
-- one flatten, measured from `started_at` (written after cold start and after
-- `insertAuditLog`) to `finished_at`, so it undercounts what pg_net sees at both
-- ends; and it is a *healthy* sample, while the case that matters is a scan
-- whose polls run to their full budget.
--
-- Bound the legitimate worst case from the code instead. Two terms, because the
-- loops count sleep and network separately:
--
--   worst legitimate elapsed = sleep budget + (round trips x per-request cost)
--
-- Sleep budget, flatten path (`hourly-check/logic.ts`, "3. Flatten scan"):
--   2 resting bracket legs x `cancelOrder` (3_000 ms of sleep each)   =  6_000
--   1 `placeMarketOrder` -> `pollOrderUntilFilled` (30_000 ms sleep)  = 30_000
--                                                                       ------
--                                                                       36_000
--
-- Round trips over the same path, counted off the loop bounds:
--   `cancelOrder` = 1 DELETE + 12 GETs (3_000/250), twice            =   26
--   `placeMarketOrder` = 1 POST + 60 GETs (30_000/500)
--                        + post-timeout DELETE + 1 status re-read    =   63
--   `getPosition`, `listOpenOrderIds`, and the gate ladder ahead of
--   the flatten branch (paper assert, clock, bars, calendar, ...)    ~   11
--                                                                       ----
--                                                                      ~ 100
--
-- At 500 ms per request -- a stressed-broker allowance, and the stressed case is
-- precisely the one that runs the polls to their full budget; the healthy
-- skip-only scans imply well under 300 ms across their handful of requests --
-- that is 36_000 + 50_000 = 86_000 ms, plus ~8 Postgres round trips for the
-- `hourly_scans`/`trades`/`audit_log` writes and the cold start ahead of
-- `started_at`. Call it 89s.
--
-- 120000 clears that with ~31s of margin. Stated as the falsifiable claim: the
-- margin survives until sustained per-request latency reaches ~800 ms
-- ((120_000 - 36_000 - 3_100) / 100). The same arithmetic is why 60000 was
-- rejected during review -- its break-even is ~210 ms per request, which a
-- merely stressed broker reaches, so it would have rebuilt this bug's own
-- failure mode at a higher threshold.
--
-- 120000 is also 1/30th of the job's own 3600s period, so the pg_net worker
-- never holds a wait into the next firing. That is a statement about the
-- worker's wait, not about the scan: a timeout does not abort the Edge
-- Function, so a slow scan can still be executing when the next hour fires.
--
-- Does a 2-minute wait delay the kill-switch job's own posts? No, but not
-- because pg_net runs everything concurrently. Only requests *already in the
-- same batch* do: the worker consumes a batch (`consume_request_queue`,
-- `src/worker.c:320`) and then drives it through a `curl_multi` event loop that
-- spins `while (running_handles > 0)` (:340-385) before the outer loop can
-- consume again (:418). A request enqueued after a batch was consumed waits
-- behind the slowest handle in that batch.
--
-- So the separation is a scheduling property, not a pg_net one. hourly-check
-- fires at :07 and kill-switch at */5 (`0004_cron_idempotent.sql`), so the two
-- are always in different batches, and the next kill-switch enqueue after a :07
-- firing is at :10. A 120s wait closes at :09:00, a minute clear.
--
-- That yields a hard constraint on any future change here: THIS VALUE MUST STAY
-- BELOW THE 180s :07-TO-:10 GAP. Past it, a stalled hourly-check batch holds the
-- kill-switch's post behind it and delays an intraday drawdown check by the
-- overrun. 120000 leaves 60s of slack against that bound.
--
-- If this ever needs revisiting, the remedy is to give `trade()` a per-request
-- `AbortSignal` (#511) and tighten the poll budgets, or to raise this number in
-- a follow-up migration -- never to loosen the runbook's health check so the
-- false alarm stops being reported, and never to touch
-- HOURLY_STALENESS_TOLERANCE_MIN, which is a different problem entirely.
--
--
-- #511 addendum (2026-08-03):
--
-- #511 landed: `alpaca.ts`'s `trade()` (and every fetch site in
-- `marketdata.ts`) now carries a per-request `AbortSignal` deadline
-- (`DEFAULT_REQUEST_TIMEOUT_MS` = 10_000ms, bounding the WHOLE round trip --
-- headers and body -- via `fetchWithTimeout`), and `pollOrderUntilFilled` /
-- `cancelOrder` were converted from accumulated-sleep counting to true
-- `Date.now()` wall-clock deadlines. The "no bound anywhere in the cron
-- path" and "the only mechanism that will ever surface a stalled
-- invocation" paragraphs above are SUPERSEDED by this: a stalled broker
-- request now surfaces as `error:BrokerRequestTimeoutError` in `audit_log`
-- and Discord (`notifyBrokerError`, since the new error class extends
-- `AlpacaError`) within 10s of the stall, not after this migration's 120s
-- pg_net wait. This value's role changes from PRIMARY detector to SECONDARY
-- backstop -- still load-bearing (see the pathological case below), just no
-- longer the only signal in the path.
--
-- SQL is byte-identical to 0014/this migration's original body -- this is a
-- comment-only addendum, per the repo's historical-layering convention
-- (kept as record rather than rewritten). No re-schedule, no value change:
-- the arithmetic below shows why.
--
-- Revised worst-case arithmetic, legitimate (stressed-but-healthy, ~500ms/
-- request) case: the wall-clock deadline means each poll loop's own elapsed
-- time is now bounded by (timeoutMs + one in-flight request), not
-- (timeoutMs of SLEEP, plus every round trip's cost stacked ADDITIONALLY on
-- top as the pre-#511 arithmetic above had to account for). So the 36_000ms
-- sleep budget (2 cancelOrder legs x 3_000 + 1 placeMarketOrder poll x
-- 30_000, unchanged from above) now also absorbs each loop's own network
-- time, rather than that time being extra. What's left additive is the
-- ~15-20 single (non-loop) requests on the flatten path -- the initial
-- DELETE per cancelOrder, placeMarketOrder's post-timeout DELETE + status
-- re-read, getPosition, listOpenOrderIds, and the gate ladder ahead of the
-- flatten branch (paper assert, clock, bars, calendar, ...) -- each still
-- independently bounded by the SAME 10_000ms D1 cap, costing ~500ms apiece
-- under stress: ~15-20 x 500ms = 7.5-10s. Add the same ~8 Postgres round
-- trips and cold start (~3s, unchanged) and the legitimate worst case is
-- ~46-50s, versus ~89s before -- 120000's margin roughly doubles (~70-74s
-- of slack now, versus ~31s before).
--
-- The ~800ms break-even claim above no longer applies the same way: the
-- function now self-bounds every request at 10s AND every poll loop at its
-- own timeoutMs, so the only way to threaten 120000 is a broker sustaining
-- close to the full 10s-per-request cap across most of the ~20 requests a
-- flatten makes -- D1's own accepted pathological case, worth roughly
-- 200-240s (2 loops' single in-flight requests plus ~15-20 non-loop reads,
-- each up to 10_000ms). That case correctly EXCEEDS 120000 and trips this
-- migration's stall detector, same as before -- but by the time it does,
-- the run has already reported `error:BrokerRequestTimeoutError` with a
-- Discord alert, so `timed_out: true` in `net._http_response` is now
-- confirmatory, not the first signal an operator sees. Only a sustained
-- near-10s-per-request broker incident can outlast 120s at all.

do $$
begin
  if exists (select 1 from cron.job where jobname = 'hourly-check') then
    perform cron.unschedule('hourly-check');
  end if;
end;
$$;

select cron.schedule(
  'hourly-check',
  '7 13-21 * * 1-5',
  $$
  select net.http_post(
    url := _functions_base_url() || '/hourly-check',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || _service_role_key(),
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 120000
  );
  $$
);
