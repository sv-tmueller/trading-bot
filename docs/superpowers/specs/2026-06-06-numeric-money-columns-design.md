# Design: money/price columns → `numeric` (issue #242)

**Date:** 2026-06-06
**Status:** approved (brainstorm) — pending spec review
**Issue:** #242 (the brainstorm-gated item)

## Motivation

The money/price columns are stored as `double precision` (IEEE-754 binary float),
which cannot represent decimal prices exactly (e.g. a `fill_price` of `70.23` is
stored as `70.2299999…`). For an audit/forensics and P&L record, exact decimal
storage is preferable.

### Reframing (important — bounds the value)

The **trade decision is computed in TypeScript** (JS doubles) from Alpaca data:
`computeTargetState` compares `spyClose > spySma200` **in JS, before anything is
written**. The DB columns are used only for:

- the `audit_log` / `regime_state` forensic record,
- the read-only dashboard, and
- the kill-switch **carry-forward** (it reads the prior row's `spy_close`/
  `spy_sma200` only to re-write them on its own upsert — no arithmetic, no
  decision).

So moving to `numeric` improves **stored fidelity**, not decision correctness. No
trade outcome changes. This is a forensics/dashboard-quality change.

## Goal & scope (decided)

Move the **price/money columns** to `numeric`; keep `trades.qty` as `integer`
(whole shares — fractional shares are a separate product decision, out of scope).

Columns changed:

| Table | Column | From | To |
|---|---|---|---|
| `regime_state` | `spy_close` | `double precision` | `numeric(14,4)` |
| `regime_state` | `spy_sma200` | `double precision` | `numeric(14,4)` |
| `regime_state` | `position_drawdown_pct` (nullable) | `double precision` | `numeric(10,6)` |
| `trades` | `fill_price` | `double precision` | `numeric(14,4)` |

`numeric(14,4)` covers any realistic equity price with sub-penny scale;
`numeric(10,6)` covers the drawdown ratio (e.g. `-0.250000`). As a bonus,
`spy_sma200` (a computed mean, today a long float) is stored cleanly rounded to
4dp.

## Architecture / changes

### 1. Migration — `supabase/migrations/0005_numeric_money.sql`

```sql
alter table regime_state
  alter column spy_close            type numeric(14,4) using spy_close::numeric(14,4),
  alter column spy_sma200           type numeric(14,4) using spy_sma200::numeric(14,4),
  alter column position_drawdown_pct type numeric(10,6) using position_drawdown_pct::numeric(10,6);

alter table trades
  alter column fill_price type numeric(14,4) using fill_price::numeric(14,4);
```

`ALTER … USING` casts existing rows **in place** — no data loss, no backfill
script. Tables are tiny so the lock is instant. One-time forward migration (not
idempotent by nature; migrations run once). Applied via `supabase db push` on dev
(has paper-soak rows → cast in place) and the pending prod (trivial).

### 2. Write path — unchanged

`db.ts` `upsertRegimeState` / `insertTrade` send JS `number`s; PostgREST routes a
JSON number into a `numeric` column fine (rounded to the column scale). No change.

### 3. Read path — the one real ripple

PostgREST returns `numeric` columns as JSON **strings** (to preserve precision).
Two read paths consume these:

- **`db.ts` `getLatestRegimeState`** — map the returned row to coerce the numeric
  fields back to `number`:
  - `spy_close`, `spy_sma200` (NOT NULL) via `requireNumber` (fail-loud on bad
    data, consistent with the existing `num.ts` philosophy);
  - `position_drawdown_pct` (nullable) via `x == null ? null : Number(x)`.

  `RegimeStateRow` stays `number`-typed, so `daily-check` (reads `current_state` /
  `kill_switch_active`) and the kill-switch carry-forward (reads the numbers and
  writes them back → round-trips exactly at the column scale) are unchanged
  downstream.

- **Dashboard `web/app/page.tsx`** — coerce the Supabase-sourced numeric fields
  (`spy_close`, `spy_sma200`, `position_drawdown_pct`, `fill_price`) to `Number`
  before the `money()` / `pct()` formatters and the drawdown-threshold
  comparison, otherwise `.toFixed` on a string breaks. Small, in keeping with the
  existing `num()` helper.

### 4. Isolation note

Factor the row coercion in `db.ts` into a small pure helper (e.g.
`coerceRegimeRow(raw)`) so it can be unit-tested without a database and so the
"numeric-comes-back-as-string" handling lives in one named place.

## Testing

- **Unit (no DB):** test the `coerceRegimeRow` helper — numeric string → number,
  `null` drawdown stays `null`, a non-numeric value throws (`DataError`/`Error`).
- **Gated integration:** `db.test.ts` (RUN_DB_TESTS, local Postgres) exercises the
  real round-trip through a `numeric` column.
- **Dashboard:** no test suite exists (confirmed during #245); `next build`
  (typecheck) is the gate.
- Full `deno task test` stays green.

## Rollout

Pure additive migration, no app downtime. No runbook change (`supabase db push`
already applies migrations). The **bot** is order-tolerant: the write path is
unchanged, and the new `db.ts` coercion is backward-compatible with the
pre-migration `double` values (a `number` also `Number()`s cleanly), while the
old `db.ts` survives a numeric column because PostgREST accepts a string back into
`numeric` on the carry-forward upsert and `daily-check` does no arithmetic on
those fields. The **dashboard** must be redeployed together with the migration —
once columns are `numeric`, the un-coerced dashboard would call `.toFixed` on a
string. Recommended order: ship the dashboard coercion + `db push` together.

## Out of scope

- `trades.qty` → fractional shares (separate product decision; touches sizing +
  order placement).
- Strings-end-to-end display fidelity (overkill for 2-dp prices).
- The other open #242 items (`placeMarketOrder` idempotency key).

## Success criteria

- [ ] The four columns are `numeric` in the schema; `qty` remains `integer`.
- [ ] Existing dev rows survive the migration (cast in place, values preserved).
- [ ] `db.ts` returns `number`-typed regime fields (coerced from the numeric
      strings); `daily-check` / kill-switch behaviour unchanged.
- [ ] Dashboard renders prices/drawdown/fill_price correctly (no `$NaN`, no
      `.toFixed`-on-string crash).
- [ ] `coerceRegimeRow` unit test + green `deno task test`.
