# Kill-Switch Price Confirmation (B1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **In this repo, execution is the human-triggered `/tm-kickoff #N` pipeline** (architect → developer → tester → reviewer); the architect may refine this into its sub-plan against live code.

**Goal:** Stop a single thin-feed (IEX) trade print from triggering a full, irreversible liquidation of the 3× position — confirm a kill-switch drawdown breach against the quote midpoint before firing.

**Architecture:** Dual-breach gate in `kill-switch/logic.ts`: when the trade-price drawdown breaches `KILL_SWITCH_DRAWDOWN_PCT`, fetch the latest quote and fire only if the quote-midpoint drawdown also breaches. Quote outage → fail toward protection (fire on trade alone + alert). New `ALPACA_DATA_FEED` config knob (default `iex`) makes the feed a secret-flip. The gate slots **before** the #293 `claimTradeDate`, so an unconfirmed breach burns no claim.

**Tech Stack:** TypeScript / Deno (Supabase Edge Functions); Alpaca Market Data REST v2; `deno task test` (Alpaca mocked via injected `deps`; `CLAUDE_AGENT_NO_BROKER=1`).

**Spec:** `docs/plans/2026-06-15-killswitch-price-confirmation-design.md`. **Invariants (hard gate):** no LLM; `computeTargetState` untouched; drawdown *threshold* math unchanged; no migration; all Alpaca mocked.

> **Test-code note:** test *intent + ACs* are specified per task; match the existing stub patterns in each `*.test.ts` (this repo's `/tm-kickoff` developer writes tests against live patterns). Full production code is given for the load-bearing logic.

---

## File Structure
- `supabase/functions/_shared/config.ts` *(modify)* — add `dataFeed` to `AlpacaConfig`; read `ALPACA_DATA_FEED` (default `iex`, validate `iex|sip`).
- `supabase/functions/_shared/config.test.ts` *(modify)* — default + invalid-throws.
- `supabase/functions/_shared/marketdata.ts` *(modify)* — add `getLatestQuote()`; thread `cfg.dataFeed` into all three `feed=` fetches.
- `supabase/functions/_shared/marketdata.test.ts` *(modify)* — getLatestQuote happy / missing / non-numeric / feed-honored.
- `supabase/functions/kill-switch/logic.ts` *(modify)* — add `getLatestQuote` to `KillSwitchDeps.marketdata`; insert dual-breach branch between the within-threshold return (`:178-181`) and the #293 claim (`:191`).
- `supabase/functions/kill-switch/handler.ts` *(modify)* — wire real `getLatestQuote` into `buildDeps()`.
- `supabase/functions/kill-switch/logic.test.ts` *(modify)* — the four branches + the no-claim-on-unconfirmed composition.

---

## Task 1: `ALPACA_DATA_FEED` config knob

**Files:** Modify `config.ts`; Test `config.test.ts`

- [ ] **Step 1 — failing tests** (`config.test.ts`): `getAlpacaConfig().dataFeed === "iex"` by default; with `ALPACA_DATA_FEED=sip` → `"sip"`; with `ALPACA_DATA_FEED=nasdaq` → throws `/ALPACA_DATA_FEED/`. (Set `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` like the existing `getAlpacaConfig` tests.)
- [ ] **Step 2 — run, expect FAIL** (`dataFeed` missing): `deno test --allow-env --allow-net supabase/functions/_shared/config.test.ts`
- [ ] **Step 3 — implement.** In `AlpacaConfig` add `dataFeed: "iex" | "sip";`. In `getAlpacaConfig()`, before the `return`:

```ts
  const dataFeed = (Deno.env.get("ALPACA_DATA_FEED") ?? "iex").trim().toLowerCase();
  if (dataFeed !== "iex" && dataFeed !== "sip") {
    throw new Error(`ALPACA_DATA_FEED must be "iex" or "sip", got ${JSON.stringify(dataFeed)}`);
  }
```
  and add `dataFeed: dataFeed as "iex" | "sip",` to the returned object.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `git commit -m "feat(config): add ALPACA_DATA_FEED knob (default iex) (#269 finding 8)"`

---

## Task 2: `getLatestQuote` helper + thread the feed

**Files:** Modify `marketdata.ts`; Test `marketdata.test.ts`

- [ ] **Step 1 — failing tests** (`marketdata.test.ts`, follow the existing `globalThis.fetch` stub pattern): happy path `{quote:{bp:10,ap:10.2}}` → `{bid:10, ask:10.2, mid:10.1}`; response with no `quote` → throws `DataError`; `{quote:{bp:"x",ap:10}}` → throws `DataError`; with `ALPACA_DATA_FEED=sip` the requested URL contains `feed=sip`.
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — implement.** Add to `marketdata.ts`:

```ts
export async function getLatestQuote(
  symbol: string,
): Promise<{ bid: number; ask: number; mid: number }> {
  const cfg = getAlpacaConfig();
  const url = `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/quotes/latest` +
    `?feed=${cfg.dataFeed}`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET latest quote ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  if (!j.quote) {
    throw new DataError(`no latest quote for ${symbol} (got ${JSON.stringify(j.quote)})`);
  }
  const bid = requireNumber(j.quote.bp, "quote bid");
  const ask = requireNumber(j.quote.ap, "quote ask");
  return { bid, ask, mid: (bid + ask) / 2 };
}
```
  Then replace the hard-coded `feed=iex` with `feed=${cfg.dataFeed}` in `getDailyCloses` (`:31`) and `getLatestTradePrice` (`:47`). (`getDailyCloses` is also used by `daily-check` for SPY — default `iex` keeps behaviour identical.)
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `git commit -m "feat(marketdata): add getLatestQuote + ALPACA_DATA_FEED-driven feed (#269 finding 8)"`

---

## Task 3: Kill-switch dual-breach confirmation

**Files:** Modify `kill-switch/logic.ts`, `kill-switch/handler.ts`; Test `kill-switch/logic.test.ts`

- [ ] **Step 1 — failing tests** (`kill-switch/logic.test.ts`, follow the existing injected-`deps` mock pattern; mock `marketdata.getLatestQuote`, assert on `alpaca.liquidate` / `db.claimTradeDate` call-tracking):
  - **both breach →** `success:kill_switch_fired`, `liquidate` called once (trade dd and mid dd both ≤ −pct).
  - **trade breaches, mid doesn't →** `skipped:breach_unconfirmed`, `liquidate` **not** called, `claimTradeDate` **not** called, `notifyError` called, drawdown still upserted.
  - **quote fetch throws →** `success:kill_switch_fired` (fail-toward-protection), `liquidate` called, `notifyError` called.
  - **neither breaches →** `success:within_threshold` (regression — unchanged).
- [ ] **Step 2 — run, expect FAIL** (`getLatestQuote` not on deps): `deno test --allow-env --allow-net supabase/functions/kill-switch/logic.test.ts`
- [ ] **Step 3 — implement.** (a) In `KillSwitchDeps.marketdata` add:
```ts
    getLatestQuote: (symbol: string) => Promise<{ bid: number; ask: number; mid: number }>;
```
  (b) In `kill-switch/handler.ts` `buildDeps()`, add `getLatestQuote` alongside `getLatestTradePrice` (same wiring to `marketdata.getLatestQuote`).
  (c) In `logic.ts`, insert **between** the within-threshold return (`:178-181`) and the #293 claim (`:191`):
```ts
    // B1b dual-breach confirmation (#269 finding 8): a single thin-feed (IEX)
    // trade print must not liquidate the 3x position alone. Confirm against the
    // quote midpoint; fire only if BOTH breach. The fetch is wrapped LOCALLY so a
    // quote OUTAGE fails toward protection (fire on trade alone) and never falls
    // through to the outer catch (which returns error:* and would disarm the
    // switch). Placed BEFORE the #293 claim so an unconfirmed breach consumes no
    // claim and a later real breach the same day can still fire.
    try {
      const quote = await marketdata.getLatestQuote(config.botTicker);
      const midDrawdown = quote.mid / refHigh - 1;
      if (midDrawdown > -config.killSwitchDrawdownPct) {
        const msg = `breach unconfirmed: trade dd=${drawdown.toFixed(4)} (px=${lastPrice}) ` +
          `but quote-mid dd=${midDrawdown.toFixed(4)} (mid=${quote.mid}) within threshold — NOT liquidating`;
        await notifications.notifyError(`kill-switch: ${msg}`);
        await finish("skipped:breach_unconfirmed", msg);
        return "skipped:breach_unconfirmed";
      }
      // both breach -> fall through to claim + liquidate
    } catch (e) {
      await notifications.notifyError(
        `kill-switch: quote fetch failed for ${config.botTicker} ` +
          `(${(e as Error).message.slice(0, 200)}) — liquidating on trade price alone (fail-toward-protection)`,
      );
      // fall through to claim + liquidate
    }
```
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — full suite + commit:** `deno task test` (expect 0 failed; `invariants.test.ts` green) → `git commit -m "feat(kill-switch): dual-breach price confirmation before liquidate (#269 finding 8)"`

---

## Verification (whole deliverable)
- `deno task test` green; `invariants.test.ts` green (new `marketdata`/`config`/`logic` changes scanned — no model SDK).
- `computeTargetState` and the drawdown *threshold* math untouched; no migration added.
- `grep -n "feed=iex" supabase/functions/_shared/marketdata.ts` returns nothing (all three fetches now use `cfg.dataFeed`).
- New outcome `skipped:breach_unconfirmed` present; the quote-outage path liquidates (does **not** return `error:*`).

## Self-review (against the spec)
- **Spec coverage:** helper (Task 2), config knob (Task 1), four logic branches + composition (Task 3), tests (each task) — all mapped. ✓
- **Placeholders:** load-bearing logic is full code; tests are AC-specified per the repo's architect/developer pipeline. ✓
- **Type consistency:** `{ bid; ask; mid }` shape identical in `marketdata.getLatestQuote`, the `KillSwitchDeps.marketdata` signature, and the handler wiring. ✓
