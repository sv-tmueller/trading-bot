# DB Integration Tests Runbook

How to run `deno task test:db`, the `RUN_DB_TESTS`-gated suite in
`supabase/functions/_shared/db.test.ts`, against a local Postgres.

These tests are gated because they need a real database, so `deno task test` skips them. That means
they can ship green while never having executed: they are only ever exercised when an operator
follows this runbook. Two of them were written in June 2026 and first ran on 2026-07-29; two more
shipped with #536 and one with #550, each unexecuted until the run recorded on #545.

## Why local only, and why that is enforced

The gated tests write to shared tables: `bot_config`, `trades`, `audit_log`, `regime_state`,
`hourly_scans`, `bar_claims`. One of those, `bot_config.paused`, is the operational kill switch, so a
gated run against the dev or prod project could clear it.

`assertLocalSupabaseUrl` (`supabase/functions/_shared/db_test_guard.ts`) refuses any `SUPABASE_URL`
whose host is not loopback, before a client is constructed, so no query can leave for a real project.
`0.0.0.0` is deliberately off the allowlist: it is a wildcard bind address that some stacks print,
not a destination.

## Prerequisites

1. **A running Docker provider.** The Supabase CLI talks to a Docker daemon; it does not matter which
   one, but it has to be up. With OrbStack, `orb start` is enough (it may print
   `start VM: timed out waiting for VM to start` and still succeed, so check
   `docker info` rather than trusting that message). Verify with:

   ```bash
   docker info --format '{{.ServerVersion}}'
   ```

2. **The Supabase CLI.** Verified on 2.110.0.

## Running the suite

```bash
supabase start
```

First run pulls images and takes a few minutes. It applies every migration in `supabase/migrations/`,
so the schema the tests need is created for you. No `grant` step is required on CLI 2.110.0; an
earlier claim that a bare local stack needed
`grant all on all tables in schema public to service_role` did not reproduce and was retracted (see
`docs/runbooks/hourly-bot-rollout.md`'s T8(b) row, and #491).

Then export the service-role key from the running stack and run the suite:

```bash
eval "$(supabase status -o env | sed -n 's/^SERVICE_ROLE_KEY=/export SUPABASE_SERVICE_ROLE_KEY=/p')"
deno task test:db
```

`SUPABASE_URL` defaults to `http://127.0.0.1:54321`, which is what `supabase start` serves, so only
the key needs exporting. If the `eval` line sets nothing, run `supabase status -o env` and copy the
`SERVICE_ROLE_KEY` value across by hand.

To run one test while investigating:

```bash
RUN_DB_TESTS=1 deno test --allow-env \
  "--allow-net=127.0.0.1,localhost,[::1],host.docker.internal" \
  --filter "getHourlyScansInWindow" supabase/functions/_shared/db.test.ts
```

When you are done:

```bash
supabase stop
```

## Expected result

As of `6a1a67b` (2026-08-07): **52 passed, 5 failed.**

The five failures are known test-side defects tracked in **#491**, not production defects. Each
asserts that a round-tripped `timestamptz` equals the `"...Z"` spelling it was written with, while
PostgREST renders it as `+00:00`. Nothing in a trading path compares `bar_ts` as a string, so
production is unaffected.

| Failing test | Line |
|---|---|
| `hourly_scans: upsert + getHourlyScanByEntryOrderId roundtrip` | `db.test.ts:963` |
| `getLatestHourlyScan: returns the newest row by bar_ts` | `db.test.ts:1023` |
| `getHourlyScansSince: returns rows with bar_ts >= sinceIso, newest first` | `db.test.ts:1068` |
| `getHourlyScansInWindow: returns rows with since <= bar_ts <= until, ascending` | `db.test.ts:1112` |
| `getHourlyScansPendingEntry: real-Postgres round trip` | `db.test.ts:1249` |

A failure whose diff is only the timezone spelling is this known class. A failure with a different
row count, a different ordering, or a different value is not, and is worth investigating.

To check quickly whether every failure is the known class, strip the ANSI codes and compare the
actual and expected lines:

```bash
deno task test:db 2>&1 | sed -e 's/\x1b\[[0-9;]*m//g' | grep -E '^\s*[-+]\s+"20' | sort | uniq -c
```

If every pair differs only by `+00:00` versus `Z`, there is no behavioral regression.

## Troubleshooting

**`Error: supabaseKey is required.`** on every gated test, thrown before any query. There is no
`SUPABASE_SERVICE_ROLE_KEY` in the environment: `createLocalDbClient` defaults it to the empty string
and supabase-js rejects that. Run the `eval` line above in the same shell as `deno task test:db`.
Environment variables do not survive between separate shell invocations.

**`failed to connect to the docker API at unix:///...`** from `supabase start`. The Docker provider is
not running. Start it (`orb start` for OrbStack) and confirm with `docker info` before retrying.

**`RUN_DB_TESTS refused: SUPABASE_URL host "..." is not a local supabase stack`.** The guard did its
job. Point `SUPABASE_URL` at the local stack or unset it to take the default. Never point this suite
at dev or prod.

**Tests fail with `relation "..." does not exist`.** The migrations did not apply. `supabase db reset`
reapplies them to the local stack.

## Related

- `docs/runbooks/hourly-bot-rollout.md`, T8(b), the first recorded run of this suite.
- #491, the open `timestamptz` assertion defect.
- #545, the batch whose pre-merge action produced the current expected-result numbers above.
