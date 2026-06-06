# Numeric money/price columns — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the bot's price/money columns as Postgres `numeric` (exact decimals) instead of `double precision`, for audit/dashboard fidelity, without changing any trade decision.

**Architecture:** One additive migration casts four columns in place. The write path is unchanged (JS numbers serialize into `numeric` fine). The read path is the only ripple — PostgREST returns `numeric` as JSON strings, so `db.ts` coerces them back to `number` in one named helper, and the dashboard coerces them in its data-fetch boundary (critical: an un-coerced `spy_close > spy_sma200` would become a lexicographic string compare).

**Tech Stack:** Supabase Postgres migration; TypeScript/Deno (`supabase/functions/_shared/db.ts`); Next.js dashboard (`web/`). Spec: `docs/superpowers/specs/2026-06-06-numeric-money-columns-design.md`.

---

## File structure

- **Create** `supabase/migrations/0005_numeric_money.sql` — the `ALTER COLUMN … TYPE numeric` migration.
- **Modify** `supabase/functions/_shared/db.ts` — add a pure `coerceRegimeRow` helper; use it in `getLatestRegimeState`; import `requireNumber`.
- **Modify** `supabase/functions/_shared/db.test.ts` — add non-gated unit tests for `coerceRegimeRow`.
- **Modify** `web/app/page.tsx` — coerce numeric-string reads (`spy_close`, `spy_sma200`, `position_drawdown_pct`, `fill_price`) to `number` in `getData()`.

---

## Task 1: Schema migration

**Files:**
- Create: `supabase/migrations/0005_numeric_money.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Store price/money columns as exact decimals (numeric) instead of binary float
-- (double precision) for audit/dashboard/P&L fidelity (issue #242). Additive:
-- ALTER ... USING casts existing rows in place (no data loss). qty stays integer
-- (whole shares). No trade decision changes — the regime comparison is computed
-- in TypeScript before storage; these columns are forensic/dashboard only.

alter table regime_state
  alter column spy_close            type numeric(14,4) using spy_close::numeric(14,4),
  alter column spy_sma200           type numeric(14,4) using spy_sma200::numeric(14,4),
  alter column position_drawdown_pct type numeric(10,6) using position_drawdown_pct::numeric(10,6);

alter table trades
  alter column fill_price type numeric(14,4) using fill_price::numeric(14,4);
```

- [ ] **Step 2: Verify by inspection** (no local Postgres in this environment)

Confirm: four `alter column` statements, correct types (`14,4` for prices, `10,6` for the drawdown ratio), `qty` untouched, `using` casts present. The DB integration test in Task 2 (gated behind `RUN_DB_TESTS`) is the runtime check when a local stack is available.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/0005_numeric_money.sql
git commit -m "feat(db): store money/price columns as numeric (#242)"
```

---

## Task 2: `db.ts` read-path coercion (TDD)

**Files:**
- Modify: `supabase/functions/_shared/db.ts`
- Test: `supabase/functions/_shared/db.test.ts`

- [ ] **Step 1: Write the failing tests** — append to `supabase/functions/_shared/db.test.ts`

Add `coerceRegimeRow` to the existing import from `./db.ts`, add `import { DataError } from "./num.ts";` near the top, and append:

```ts
Deno.test("coerceRegimeRow: numeric strings -> numbers (PostgREST returns numeric as string)", () => {
  const row = coerceRegimeRow({
    date: "2026-06-06",
    spy_close: "412.3400",
    spy_sma200: "400.1267",
    target_state: "LONG",
    current_state: "LONG",
    position_drawdown_pct: "-0.250000",
    kill_switch_active: true,
    kill_switch_fired_at: null,
  });
  assertEquals(row.spy_close, 412.34);
  assertEquals(row.spy_sma200, 400.1267);
  assertEquals(row.position_drawdown_pct, -0.25);
  assertEquals(row.current_state, "LONG");
});

Deno.test("coerceRegimeRow: null drawdown stays null", () => {
  const row = coerceRegimeRow({
    date: "2026-06-06", spy_close: "400", spy_sma200: "380",
    target_state: "CASH", current_state: "CASH",
    position_drawdown_pct: null, kill_switch_active: false, kill_switch_fired_at: null,
  });
  assertEquals(row.position_drawdown_pct, null);
});

Deno.test("coerceRegimeRow: also accepts numbers (pre-migration doubles round-trip)", () => {
  const row = coerceRegimeRow({
    date: "2026-06-06", spy_close: 400, spy_sma200: 380,
    target_state: "LONG", current_state: "LONG",
    position_drawdown_pct: -0.1, kill_switch_active: false, kill_switch_fired_at: null,
  });
  assertEquals(row.spy_close, 400);
  assertEquals(row.position_drawdown_pct, -0.1);
});

Deno.test("coerceRegimeRow: non-numeric spy_close throws", () => {
  assertThrows(
    () =>
      coerceRegimeRow({
        date: "x", spy_close: "not-a-number", spy_sma200: "380",
        target_state: "LONG", current_state: "LONG",
        position_drawdown_pct: null, kill_switch_active: false, kill_switch_fired_at: null,
      }),
    DataError,
  );
});
```

Also add `assertThrows` to the `@std/assert` import (currently only `assertEquals`):

```ts
import { assertEquals, assertThrows } from "@std/assert";
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `deno test --allow-env --allow-net --config deno.json supabase/functions/_shared/db.test.ts`
Expected: FAIL — `coerceRegimeRow` is not exported / not a function. (The `RUN_DB_TESTS`-gated tests stay `ignored`.)

- [ ] **Step 3: Implement `coerceRegimeRow` and use it in `getLatestRegimeState`**

In `supabase/functions/_shared/db.ts`, add the import at the top (after the existing `SupabaseClient` import):

```ts
import { requireNumber } from "./num.ts";
```

Add the helper just below the `RegimeStateRow` interface:

```ts
// PostgREST returns `numeric` columns as JSON strings to preserve precision.
// Coerce the price/money fields back to number so RegimeStateRow stays
// number-typed for the bot. Accepts numbers too (pre-migration double rows).
export function coerceRegimeRow(raw: Record<string, unknown>): RegimeStateRow {
  return {
    date: raw.date as string,
    spy_close: requireNumber(raw.spy_close, "spy_close"),
    spy_sma200: requireNumber(raw.spy_sma200, "spy_sma200"),
    target_state: raw.target_state as "LONG" | "CASH",
    current_state: raw.current_state as "LONG" | "CASH",
    position_drawdown_pct: raw.position_drawdown_pct == null
      ? null
      : requireNumber(raw.position_drawdown_pct, "position_drawdown_pct"),
    kill_switch_active: raw.kill_switch_active as boolean,
    kill_switch_fired_at: (raw.kill_switch_fired_at as string | null) ?? null,
    created_at: raw.created_at as string | undefined,
  };
}
```

Change the `return` line in `getLatestRegimeState` from:

```ts
  return (data as RegimeStateRow) ?? null;
```

to:

```ts
  return data ? coerceRegimeRow(data as Record<string, unknown>) : null;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `deno test --allow-env --allow-net --config deno.json supabase/functions/_shared/db.test.ts`
Expected: PASS (4 new tests; 4 DB tests ignored).

- [ ] **Step 5: Run the full suite + lint**

Run: `CLAUDE_AGENT_NO_BROKER=1 deno test --allow-env --allow-net --config deno.json supabase/functions/`
Expected: all green (existing 87 + 4 new = 91 passed, 4 ignored).
Run: `deno lint supabase/functions/_shared/db.ts supabase/functions/_shared/db.test.ts`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add supabase/functions/_shared/db.ts supabase/functions/_shared/db.test.ts
git commit -m "feat(db): coerce numeric-string reads to number in getLatestRegimeState (#242)"
```

---

## Task 3: Dashboard coercion

**Files:**
- Modify: `web/app/page.tsx`

- [ ] **Step 1: Coerce numeric reads in `getData()`**

In `web/app/page.tsx`, replace the `return { … }` block at the end of `getData()` (currently building `regime` and `trades` via raw casts) with coerced versions. Replace:

```ts
  return {
    regime: (rs.data as RegimeState | null) ?? null,
    paused: (cfg.data as { value: string } | null)?.value === "true",
    trades: (tr.data as Trade[] | null) ?? [],
    audit: (al.data as Audit[] | null) ?? [],
    account: account as AlpacaAccount | null,
    positions: positions as AlpacaPosition[],
    dbError,
  };
```

with:

```ts
  // numeric columns arrive from PostgREST as strings — coerce so the bullish
  // comparison and money()/pct() formatters get real numbers (a string compare
  // of spy_close > spy_sma200 would be lexicographic).
  const rawRegime = rs.data as Record<string, unknown> | null;
  const regime: RegimeState | null = rawRegime
    ? {
      date: rawRegime.date as string,
      spy_close: Number(rawRegime.spy_close),
      spy_sma200: Number(rawRegime.spy_sma200),
      target_state: rawRegime.target_state as string,
      current_state: rawRegime.current_state as string,
      position_drawdown_pct: rawRegime.position_drawdown_pct == null
        ? null
        : Number(rawRegime.position_drawdown_pct),
      kill_switch_active: rawRegime.kill_switch_active as boolean,
      kill_switch_fired_at: (rawRegime.kill_switch_fired_at as string | null) ?? null,
    }
    : null;
  const trades: Trade[] = ((tr.data as Record<string, unknown>[] | null) ?? []).map((t) => ({
    id: t.id as number,
    symbol: t.symbol as string,
    side: t.side as string,
    qty: t.qty as number,
    fill_price: Number(t.fill_price),
    fill_time: t.fill_time as string,
    reason: t.reason as string,
  }));
  return {
    regime,
    paused: (cfg.data as { value: string } | null)?.value === "true",
    trades,
    audit: (al.data as Audit[] | null) ?? [],
    account: account as AlpacaAccount | null,
    positions: positions as AlpacaPosition[],
    dbError,
  };
```

- [ ] **Step 2: Build (typecheck + compile) to verify**

Run: `cd web && npm install && npm run build`
Expected: `✓ Compiled successfully`, no type errors. (`npm install` needed because this worktree has no `web/node_modules`.)

- [ ] **Step 3: Commit**

```bash
git add web/app/page.tsx
git commit -m "fix(dashboard): coerce numeric-string reads to number (#242)"
```

---

## Task 4: Final verification

- [ ] **Step 1: Full TS suite green**

Run: `CLAUDE_AGENT_NO_BROKER=1 deno task test`
Expected: 91 passed, 0 failed, 4 ignored.

- [ ] **Step 2: Spec success-criteria check** — confirm each box in the spec's "Success criteria" is satisfied (schema types, dev rows preserved by the cast, `db.ts` returns numbers, dashboard renders, coercion test + green suite). No code if all pass.

---

## Self-review notes (author)

- **Spec coverage:** migration (Task 1), write-path-unchanged (no task needed — verified by existing tests staying green in Task 2 Step 5), read-path `db.ts` (Task 2) + dashboard (Task 3), tests (Task 2 unit + gated DB), rollout (deploy dashboard + db push together — operational, not code). All covered.
- **No placeholders:** every code step shows full code.
- **Type consistency:** `coerceRegimeRow(raw: Record<string, unknown>): RegimeStateRow` used identically in Task 2 Step 3 and tested in Step 1; dashboard `RegimeState`/`Trade` shapes match `page.tsx` types.
