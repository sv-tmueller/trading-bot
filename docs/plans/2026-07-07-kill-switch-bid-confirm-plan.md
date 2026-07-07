# Kill-switch bid-confirm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the intraday kill-switch B1b confirmation signal from the quote midpoint to the quote bid, so a real down-breach with a stale-high ask (wide spread in a crash) liquidates instead of suppressing (#352, implements the #304 spec).

**Architecture:** One change to the returned-quote confirmation branch in `supabase/functions/kill-switch/logic.ts`: re-point the existing #334 implausibility guard and the drawdown check from `quote.mid` to `quote.bid`, and rename the audit note `mid=`→`bid=`. `bid ≤ mid`, so bid-confirm fires in a strict superset of the mid cases; it preserves the original thin-print protection (low print + healthy bid still suppresses) while closing the degraded-quote asymmetry. The quote-outage path (fire on the trade alone) is untouched.

**Tech Stack:** TypeScript on Deno (Supabase Edge Functions); `deno task test`; `@std/assert`.

## Global Constraints

- **Invariant #1 (one decision rule / no LLM):** no new decision rule — this refines the *confirm source* of the existing kill-switch rule; no model SDK, no agent. Any violation is a must-fix review finding.
- **Broker safety:** all Alpaca/DB calls MUST be mocked in tests; the `CLAUDE_AGENT_NO_BROKER` guard stays intact. No live broker path is reachable.
- **Surgical:** touch only the confirmation branch + its tests. Do not refactor adjacent code, do not change `getLatestQuote` (it already returns `{bid, ask, mid}`), no config/schema/feed change.
- **Threshold in tests:** `killSwitchDrawdownPct: 0.25`; bars all `100` so `refHigh = 100`.

---

### Task 1: Bid-confirm the down-breach (logic + tests, TDD)

**Files:**
- Modify: `supabase/functions/kill-switch/logic.ts:197-229` (confirmation branch) and `:288-291` (audit note)
- Test: `supabase/functions/kill-switch/logic.test.ts` (add one regression test; update one fire-note assertion; re-point comments)

**Interfaces:**
- Consumes: `marketdata.getLatestQuote(symbol) → Promise<{ bid: number; ask: number; mid: number }>` (unchanged); `config.killSwitchDrawdownPct`; local `drawdown`, `lastPrice`, `refHigh`; `DataError` (from `../_shared/num.ts`, already imported).
- Produces: no new exported symbols. Same return outcomes (`success:kill_switch_fired`, `skipped:breach_unconfirmed`, `success:within_threshold`, outage fire). Audit note token changes from ` mid=<n>` to ` bid=<n>`.

- [ ] **Step 1: Write the failing #304 regression test**

Add after the existing `B1b: trade breaches but quote-mid does not …` test in `logic.test.ts` (near line 575):

```ts
Deno.test("B1b(#352): trade + bid breach but stale-high ask keeps mid within threshold -> fires", async () => {
  // The #304 pathology: real bid has crashed to 68 (-32%) but the ask is
  // stale-high at 120, so mid=94 is only -6% (within the -25% threshold).
  // Mid-confirm suppresses (skipped:breach_unconfirmed); bid-confirm fires.
  const { deps, calls } = makeDeps({
    marketdata: {
      getDailyCloses: () => Promise.resolve(bars([100, 100, 100, 100, 100])),
      getLatestTradePrice: () => Promise.resolve(68), // -32%, breaches
      getLatestQuote: () => Promise.resolve({ bid: 68, ask: 120, mid: 94 }),
    } as unknown as KillSwitchDeps["marketdata"],
  });
  assertEquals(await runKillSwitch(deps), "success:kill_switch_fired");
  assertEquals(calls.liquidate, true);
  const notes = String((calls.audit as { notes: string }).notes);
  assertEquals(notes.includes("confirmation=confirmed"), true);
  assertEquals(notes.includes("bid=68"), true);
});
```

- [ ] **Step 2: Run the new test to verify it FAILS on the current mid-based code**

Run: `deno test --allow-env --allow-net supabase/functions/kill-switch/logic.test.ts --filter "B1b(#352)"`
Expected: FAIL — current code computes `midDrawdown = 94/100-1 = -0.06` (within threshold) and returns `skipped:breach_unconfirmed`, so `runKillSwitch` returns the wrong outcome and the assertion fails.

- [ ] **Step 3: Re-point the #334 implausibility guard from mid to bid** (`logic.ts`, inside the `try` at ~line 200)

Replace:

```ts
      // #334: a well-shaped-but-implausible mid (e.g. a ~10x fat-fingered print)
      // must not be trusted as a confirming second source — throw so it routes
      // into the local catch below and fires on the trade price alone.
      const midRatio = Math.max(quote.mid, lastPrice) / Math.min(quote.mid, lastPrice);
      if (midRatio > 2) {
        throw new DataError(
          `implausible quote mid for ${config.botTicker}: mid=${quote.mid} lastPrice=${lastPrice} (ratio ${
            midRatio.toFixed(2)
          } > 2)`,
        );
      }
```

with:

```ts
      // #334/#352: bid is the realizable sale price, so it confirms a *down*-breach.
      // A well-shaped-but-implausible bid (e.g. a ~10x fat-fingered quote) must not
      // be trusted as a confirming second source — throw so it routes into the local
      // catch below and fires on the trade price alone.
      const bidRatio = Math.max(quote.bid, lastPrice) / Math.min(quote.bid, lastPrice);
      if (bidRatio > 2) {
        throw new DataError(
          `implausible quote bid for ${config.botTicker}: bid=${quote.bid} lastPrice=${lastPrice} (ratio ${
            bidRatio.toFixed(2)
          } > 2)`,
        );
      }
```

- [ ] **Step 4: Swap the confirmation drawdown from mid to bid** (`logic.ts`, immediately below)

Replace:

```ts
      const midDrawdown = quote.mid / refHigh - 1;
      if (midDrawdown > -config.killSwitchDrawdownPct) {
        const msg = `breach unconfirmed: trade dd=${drawdown.toFixed(4)} (px=${lastPrice}) ` +
          `but quote-mid dd=${midDrawdown.toFixed(4)} (mid=${quote.mid}) within threshold — NOT liquidating`;
        await notifications.notifyError(`kill-switch: ${msg}`);
        await finish("skipped:breach_unconfirmed", msg);
        return "skipped:breach_unconfirmed";
      }
      // both breach -> fall through to claim + liquidate
      confirmation = "confirmed";
      fireMid = quote.mid;
```

with:

```ts
      const bidDrawdown = quote.bid / refHigh - 1;
      if (bidDrawdown > -config.killSwitchDrawdownPct) {
        const msg = `breach unconfirmed: trade dd=${drawdown.toFixed(4)} (px=${lastPrice}) ` +
          `but quote-bid dd=${bidDrawdown.toFixed(4)} (bid=${quote.bid}) within threshold — NOT liquidating`;
        await notifications.notifyError(`kill-switch: ${msg}`);
        await finish("skipped:breach_unconfirmed", msg);
        return "skipped:breach_unconfirmed";
      }
      // both breach -> fall through to claim + liquidate
      confirmation = "confirmed";
      fireBid = quote.bid;
```

- [ ] **Step 5: Rename the `fireMid` declaration and update the block comment** (`logic.ts`)

Change the declaration at ~line 198 from:

```ts
    let fireMid: number | null = null;
```

to:

```ts
    let fireBid: number | null = null;
```

And update the B1b block comment (~lines 190-192) from "Confirm against the quote midpoint" to "Confirm against the quote **bid** (the realizable sale price)"; append `(#352)` alongside the `#269 finding 8` reference.

- [ ] **Step 6: Update the audit note** (`logic.ts:288-291`)

Replace:

```ts
    const midNote = fireMid !== null ? ` mid=${fireMid}` : "";
    await finish(
      "success:kill_switch_fired",
      `dd=${drawdown.toFixed(4)}${midNote} confirmation=${confirmation}`,
    );
```

with:

```ts
    const bidNote = fireBid !== null ? ` bid=${fireBid}` : "";
    await finish(
      "success:kill_switch_fired",
      `dd=${drawdown.toFixed(4)}${bidNote} confirmation=${confirmation}`,
    );
```

- [ ] **Step 7: Fix the fire-note test that asserts `mid=`** (`logic.test.ts` ~line 621-638)

In the test `"fire notes: confirmed dual-breach carries confirmation=confirmed and mid"`:
- rename it to `"fire notes: confirmed dual-breach carries confirmation=confirmed and bid"`,
- change the assertion `assertEquals(notes.includes("mid="), true);` to `assertEquals(notes.includes("bid="), true);`.

- [ ] **Step 8: Re-point the stale test names/comments onto the bid** (`logic.test.ts`)

Comment-only clarity (the change is what makes them stale) — no value changes:
- Test at ~536: rename `"B1b: both trade and quote-mid breach …"` → `"… quote-bid breach …"`.
- Test at ~551: rename `"B1b: trade breaches but quote-mid does not …"` → `"… but quote-bid does not …"`; update its `// -10%, no breach` inline comment to note `bid=89 -> -0.11`.
- The `#334` block header comment (~691-693) and the two `#334` test names ("implausibly HIGH/LOW quote mid"): change "mid" → "bid". Their quote values already have `bid ≈ mid`, so they still exercise the re-pointed guard and stay green.

- [ ] **Step 9: Run the full kill-switch test file**

Run: `deno test --allow-env --allow-net supabase/functions/kill-switch/logic.test.ts`
Expected: PASS — the new #352 test passes, the fire-note test passes on `bid=`, and every re-pointed test stays green (helper builds `bid = mid`, so `#334` and both-breach cases are unaffected).

- [ ] **Step 10: Run the whole suite**

Run: `deno task test`
Expected: PASS — no other module references the kill-switch confirmation internals; `getLatestQuote` is unchanged.

- [ ] **Step 11: Commit**

```bash
git add supabase/functions/kill-switch/logic.ts supabase/functions/kill-switch/logic.test.ts
git commit -m "fix: bid-confirm the kill-switch down-breach (#352)"
```

---

## Self-Review

**Spec coverage:**
- Signal swap mid→bid (spec §1) → Steps 4-5. ✓
- #334 guard re-pointed (spec §1) → Step 3. ✓
- Audit note mid→bid (spec §2) → Step 6. ✓
- Outage path unchanged (spec §3) → not touched; asserted green by the existing outage tests in Step 9. ✓
- No config flag / no feed / no schema change (spec §3) → none present in any step. ✓
- Invariant #1 (spec §4) → Global Constraints; no decision rule added. ✓
- Tests: #304 regression (Step 1), preserved-intent re-word (Step 8), fire-note mid→bid (Step 7), outage/implausible/boundary green (Step 9); no redundant whipsaw test (spec Testing). ✓

**Placeholder scan:** none — every code step carries the actual before/after code.

**Type consistency:** `fireBid: number | null` declared (Step 5), assigned `quote.bid` (Step 4), read in the note (Step 6). `bidRatio`/`bidDrawdown` are local `const`s. `quote.bid` is `number` per the `getLatestQuote` return type. Consistent.
