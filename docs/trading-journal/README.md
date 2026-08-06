# Weekly Trading Journal

Format and conventions for `docs/trading-journal/YYYY-Www.md` files. Each entry covers one ISO trading week and is written after the week's final candle closes (Friday US market close).

## Why these exist

The North Star for this bot is beating buy-and-hold on risk-adjusted terms — higher net gain, solid win/loss ratio, minimized drawdown — with every trading week documented. The journal is the audit trail that makes that claim verifiable: for any week, you can open the entry and read exactly what the signal was, what the bot did, how it performed, and how that compared to the benchmark. It also captures the human reasoning layer that the audit log cannot — why a config change was made mid-week, what market context surrounded a regime flip, whether a week's underperformance was expected given the signal.

A journal entry is **not**:
- A research artefact (those live in `docs/research/<topic>/`).
- A development decision (those live in `docs/decisions/`).
- A deployment runbook or incident post-mortem (those live in `docs/runbooks/`).
- A replacement for the `audit_log` table — the database row is the source of truth for what the bot did; the journal is the human-readable interpretation alongside it.

## When to write one

Write an entry for every completed ISO trading week in which the bot was live. If the bot was paused or not deployed for a full week, write a brief entry noting that and why — the gap in the record is information.

Write the entry after the Friday US market close so the full week's data is available. If `YYYY-Www.md` for the current week already exists as a draft started mid-week, complete and commit it on Friday.

## File contract

One Markdown file per ISO trading week. Use `TEMPLATE.md` as the starting point for the daily
regime bot's entries (superseded by the hourly candlestick bot as of P1, #465). Hourly-era entries
are instead rendered by `scripts/render_weekly_journal.ts` (#481) -- see
`docs/runbooks/weekly-review.md` for the invocation. Either way, an existing entry is never
overwritten silently.

## Naming and location

- Path: `docs/trading-journal/YYYY-Www.md`.
- ISO week notation: `YYYY` is the ISO year (which may differ from the calendar year for weeks spanning 31 Dec / 1 Jan), `W` is literal, `ww` is the two-digit week number zero-padded. Example: `2026-W24.md` for the week of 8–12 June 2026.
- To find the current ISO week in the shell: `date +%G-W%V`.

## Existing entries

See the files in this directory (`2026-W25.md` was the first live week; `2026-W31.md` records the
daily regime bot's deprecation). This line is intentionally not an exhaustive index — the
filesystem listing is the source of truth.

## Daily verification (#549)

Since batch #545, each trading day is verified mechanically by
`.github/workflows/daily-verification.yml` -- see
`docs/runbooks/daily-verification.md` for the full operator guide. It writes two
artifacts into this directory:

- `daily-verification.jsonl` -- one line per verified trading day (verdict, the
  seven per-check results, and the day's metrics), upserted and kept in
  ascending date order. Machine-readable, for trend queries later.
- `daily/YYYY-MM-DD.md` -- the rendered digest for that day, in the same
  seven-check layout the manual ritual below used by hand. Human-readable, and
  linked from the workflow's FAIL issue and its Discord line.

Both files are deterministic functions of their inputs -- re-running a date
reproduces byte-identical content, so the workflow's commit step is a true
no-op when nothing changed.

### Manual verification fallback

This is the seven-query SQL ritual #535 established for verifying the hourly
bot's trading days by hand, corrected and given a durable home here rather
than living only in the bodies of closable issues (#523, #535). Use it if the
automated workflow above is down, silenced, or hasn't reached a day yet. Run
the queries in the Supabase SQL editor one at a time (the editor shows only
the last result set) after the day's final kill-switch slot (21:07 UTC) has
run. Replace `YYYY-MM-DD` with the trading day being verified.

#### 1. All nine slots ran and returned

```sql
select started_at, finished_at, outcome, notes
from audit_log
where script_name = 'hourly-check' and started_at >= 'YYYY-MM-DD'
order by started_at;
```

- [ ] 9 rows (13:07 through 21:07 UTC), every row with non-null `finished_at` and `outcome`.
- Expected shape on a normal trading day: 13:07 `skipped:market_closed`, 14:07 `skipped:partial_bar`,
  15:07-19:07 scans (`success`, `success:no_action`, or `skipped:*`), 20:07/21:07
  `skipped:market_closed`.
- A row with BOTH `finished_at` and `outcome` null = that run crashed. Zero rows for a slot =
  cron did not fire. Either is a real finding.
- Any `error:*` outcome should ALSO have produced a Discord alert (post-#514 policy); a silent
  `error:*` row is itself a bug to report.
- Latency baseline observed on clean days: clock gate-exits 0.86-0.96s, full scans 1.85-2.51s,
  against migration 0015's 120s `pg_net` budget. A scan above roughly 10s is worth noting even
  though it passes, since #511's per-request deadline is 10s per call.

#### 2. Scan journaling and signal activity

```sql
select bar_ts, decision, skip_reason, detectors_fired, entry_order_id, qty
from hourly_scans
where bar_ts >= 'YYYY-MM-DD' order by bar_ts;
```

- [ ] One row per candidate bar: up to 6 rows (13:00 through 18:00), of which the 13:00 row is the
  partial. Each `HH:07` run scans the bar that completed at `HH:00`. The 19:00-20:00 closing bar
  is never a candidate, because the 20:07 slot gate-exits after the 20:00 close.
- [ ] No SHORT decisions while `HOURLY_SHORTS_ENABLED` is false.
- If a LONG row exists: `entry_order_id` must be non-null (or recovered by a later scan, see
  check 4).
- **Not a finding:** `detectors_fired` containing `inside_bar` or `doji` while `skip_reason` is
  `no_detectors_fired`. Both are NEUTRAL in `PATTERN_DIRECTIONS`, journaled in full but never
  voted (`_shared/hourly_signal.ts:61`, pinned by `_shared/hourly_signal.test.ts:44`). The reason
  string means "no voting detector was admitted", not "nothing fired". It covers three cases at
  once: nothing fired, neutral-only fires, and directional fires masked by trend context
  (`hourly_signal.ts:62-65`); separate them from `detectors_fired` plus the direction registry.
- The partial 13:00 row's empty `detectors_fired` means "not evaluated", so exclude it from any
  firing-rate denominator.

#### 3. Bracket geometry stays whole-cent (#494)

```sql
select symbol, bar_ts, stop_price, target_price
from hourly_scans
where bar_ts >= 'YYYY-MM-DD'
  and ((stop_price * 100) % 1 <> 0 or (target_price * 100) % 1 <> 0);
```

- [ ] Zero rows. Note this passes vacuously on a no-trade day; it only carries evidence once a
  bracket is actually placed.

#### 4. Journal integrity: every fill has its scan row (#480/#487/#486)

```sql
select t.broker_order_id, t.fill_time, t.side, t.qty, s.bar_ts, s.decision, s.entry_order_id
from trades t
left join hourly_scans s on s.entry_order_id = t.broker_order_id
where t.fill_time >= 'YYYY-MM-DD' and t.reason like 'hourly%';
```

- [ ] Every hourly fill joins a scan row with matching `entry_order_id`. An unmatched fill = the
  journal-degraded state; triage per the rollout runbook §10 (order id lives in
  `audit_log.notes`, format `failed=[<groups>] order=<broker_order_id>`).
- If no trades happened, zero rows is a pass.

#### 5. Hourly-check stall check (hourly-check only)

```sql
select count(*) from net._http_response r
where r.timed_out and r.created >= 'YYYY-MM-DD'
  and extract(minute from r.created) = 7;
```

- [ ] 0. Nonzero = an hourly-check invocation exceeded the 120s pg_net budget; investigate that
  slot's audit row.
- Keep the `minute = 7` filter. An unfiltered `timed_out` count picks up benign kill-switch rows,
  which still run pg_net's 5s default.
- `net._http_response` lives in the `net` schema, which PostgREST does not expose -- this query
  only runs in the SQL editor, never through the automated workflow above (D4 in the design spec).

#### 6. Bot state unchanged

```sql
select key, value from bot_config order by key;
```

- [ ] `paused` = false (unless the floor fired, which would have alerted Discord with position
  context).
- [ ] `hourly_experiment_start_equity` unchanged from the last verified day (floor is roughly
  86.5% of that value).
- [ ] `hourly_experiment_baseline_verified` byte-identical to `hourly_experiment_start_equity`.
  This is the expected post-#488 state: the plausibility check ran once against live equity,
  passed, and recorded the marker so it never re-fires on the legitimate divergence the baseline
  measures (rollout runbook §5). A value that differs from the baseline means the baseline was
  changed and the check re-armed.

#### 7. Kill-switch coverage and outcomes

```sql
select outcome, count(*) from audit_log
where script_name = 'kill-switch' and started_at >= 'YYYY-MM-DD'
group by outcome order by 2 desc;
```

- [ ] Total across all outcomes = 108, which is every 5-minute slot from 13:00 to 21:55 UTC
  inclusive (cron `*/5 13-21`). A lower total means missed slots.
- [ ] Every outcome is `success:*` or `skipped:*`. Any `error:*` is a finding.
- Expected outcome set depends on whether the bot held a position:
  - **Flat all day**: a uniform `success:no_position` x 108. `kill-switch` checks
    positions before the clock (`kill-switch/logic.ts:110-114`), so a flat account
    short-circuits on every slot and the ~30 out-of-hours slots never evaluate `/v2/clock` at all.
  - **Position held**: expect `skipped:market_closed` on the out-of-hours slots (13:00-13:25 and
    20:05-21:55 under EDT, `logic.ts:453`) plus `success:within_threshold` during the session.
- [ ] Cross-check against checks 2 and 4: a uniform `success:no_position` is only consistent with
  zero entries and zero fills. `success:no_position` on every slot *alongside* a LONG scan row
  would be a real contradiction worth investigating.

This is the `group by outcome` form of check 7 (the day-2 checklist's original `count(*)` form
could not verify its own "all `success:*`" criterion) and reflects the corrected expected-outcome
set for the position-before-clock ordering -- both corrections #535 folded in.

#### Interpretation shortcuts

- Discord silent all day + all checks green = healthy day. Silence is the designed healthy state
  post-#514; check 1 is what silence cannot prove.
- `daily-check` has zero rows by design (cron retired in migration 0013); do not report it as
  stale.
