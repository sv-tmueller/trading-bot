import { serviceClient } from "@/lib/supabase";
import { getAccount, getPositions, type AlpacaAccount, type AlpacaPosition } from "@/lib/alpaca";
import { getLatestVerifiedDay } from "@/lib/dailyJournal";

// Always render fresh at request time — this is a live status page.
export const dynamic = "force-dynamic";

// Mirrors supabase/functions/hourly-check/logic.ts's own EQUITY_FLOOR_PCT (also
// hand-synced in scripts/render_weekly_journal.ts). web/ deliberately does not
// import _shared/, so this stays a manually-synced constant rather than a shared
// import — see the batch's #534 lead decision accepting this duplication.
const EQUITY_FLOOR_PCT = 0.15;

// A frozen weekend gap (last run ~21:07 UTC Fri, first run ~13:07 UTC Mon) is
// about 64h. 72h gives an 8h margin against a false weekend alarm while still
// catching a real multi-day outage. Fixed and calendar-agnostic on purpose —
// this page states the fact, a human judges it; it does not replicate the
// watchdog's armed-window logic.
const STALE_HOURS_THRESHOLD = 72;

const HOURLY_TRADE_REASONS = [
  "hourly_long_entry",
  "hourly_short_entry",
  "hourly_bracket_exit",
  "hourly_session_close_exit",
  "hourly_kill_switch",
] as const;

// The traded symbol is derived from hourly_scans itself (one bot instance, one
// symbol), the same precedent scripts/render_weekly_journal.ts already set —
// web/ has no access to _shared/config.ts. Falls back to "SPY" (the documented
// HOURLY_BOT_TICKER default) when no scan has ever been recorded.
const DEFAULT_SYMBOL = "SPY";

type HourlyScan = {
  symbol: string;
  bar_ts: string;
  decision: "LONG" | "SHORT" | "SKIP";
  skip_reason: string | null;
  detectors_fired: string[];
  entry_ref_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  equity_usd: number;
};
type Trade = {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  fill_price: number;
  fill_time: string;
  reason: string;
};
type Audit = {
  id: number;
  script_name: string;
  outcome: string | null;
  notes: string | null;
  finished_at: string | null;
};

// numeric columns arrive from PostgREST as strings — coerce so comparisons and
// the money()/pct() formatters get real numbers. Small local coercion mirroring
// the pattern already used below for trades/audit rows (web/ does not import
// _shared/db.ts's coerceHourlyScanRow — see the independence constraint).
function coerceHourlyScan(raw: Record<string, unknown>): HourlyScan {
  const num = (v: unknown) => (v == null ? null : Number(v));
  return {
    symbol: raw.symbol as string,
    bar_ts: raw.bar_ts as string,
    decision: raw.decision as "LONG" | "SHORT" | "SKIP",
    skip_reason: (raw.skip_reason as string | null) ?? null,
    detectors_fired: (raw.detectors_fired as string[] | null) ?? [],
    entry_ref_price: num(raw.entry_ref_price),
    stop_price: num(raw.stop_price),
    target_price: num(raw.target_price),
    equity_usd: Number(raw.equity_usd),
  };
}

// Coerce the bot_config baseline to a finite, strictly positive number, or
// null if it is missing/blank/non-positive/non-finite. Mirrors
// _shared/num.ts's requireNumber — trim before the empty check
// (Number(" ") === 0, and Number("") === 0 too) — rather than the weaker
// web/lib/alpaca.ts `num` guard, because those are exactly the values
// hourly-check/logic.ts hard-errors the scan on (blank baseline fails the
// scan outright; "0" trips the plausibility guard). Letting them through
// here would render a floor of $0 and "100.00%" headroom: a maximally
// reassuring number on the one axis this page exists to protect, while the
// bot itself is refusing to run.
function numOrNull(v: unknown): number | null {
  if (v === null || v === undefined || (typeof v === "string" && v.trim() === "")) {
    return null;
  }
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

async function getData() {
  const sb = serviceClient();
  const [scansRes, latestEnteredRes, pausedRes, baselineRes, tradesRes, auditRes, account, positions] =
    await Promise.all([
      sb.from("hourly_scans").select("*").order("bar_ts", { ascending: false }).limit(20),
      // Dedicated read for bracket levels (spec §"bracket-level pairing"): not
      // reused from the recent-scans list above, so correctness does not
      // depend on that list's row limit.
      sb.from("hourly_scans").select("*").not("entry_order_id", "is", null)
        .order("bar_ts", { ascending: false }).limit(1).maybeSingle(),
      sb.from("bot_config").select("value").eq("key", "paused").maybeSingle(),
      sb.from("bot_config").select("value").eq("key", "hourly_experiment_start_equity").maybeSingle(),
      sb.from("trades").select("*").in("reason", HOURLY_TRADE_REASONS).order("id", { ascending: false })
        .limit(10),
      sb.from("audit_log").select("*").eq("script_name", "hourly-check").order("id", { ascending: false })
        .limit(15),
      getAccount(),
      getPositions(),
    ]);
  // A failed Supabase read returns { data: null, error } — without this check it
  // would render identically to "empty / all clear", a misleading signal on a
  // status page. Surface it as a distinct degraded banner.
  const dbError = [
    scansRes.error,
    latestEnteredRes.error,
    pausedRes.error,
    baselineRes.error,
    tradesRes.error,
    auditRes.error,
  ].some((e) => e != null);

  const recentScans = ((scansRes.data as Record<string, unknown>[] | null) ?? []).map(coerceHourlyScan);
  const latestEntered = latestEnteredRes.data
    ? coerceHourlyScan(latestEnteredRes.data as Record<string, unknown>)
    : null;
  const trades: Trade[] = ((tradesRes.data as Record<string, unknown>[] | null) ?? []).map((t) => ({
    id: t.id as number,
    symbol: t.symbol as string,
    side: t.side as string,
    qty: t.qty as number,
    fill_price: Number(t.fill_price),
    fill_time: t.fill_time as string,
    reason: t.reason as string,
  }));
  const baselineRaw = (baselineRes.data as { value: string } | null)?.value ?? null;

  return {
    recentScans,
    latestEntered,
    paused: (pausedRes.data as { value: string } | null)?.value === "true",
    baseline: baselineRaw == null ? null : numOrNull(baselineRaw),
    trades,
    audit: (auditRes.data as Audit[] | null) ?? [],
    account: account as AlpacaAccount | null,
    positions: positions as AlpacaPosition[],
    dbError,
  };
}

const pct = (n: number | null) => (n == null ? "—" : `${(n * 100).toFixed(2)}%`);
// For values already expressed in percent units (not a fraction) — used for
// computeEquityHeadroomPct's return, which is pre-scaled like its counterpart
// in supabase/functions/status/logic.ts.
const pctValue = (n: number | null) => (n == null ? "—" : `${n.toFixed(2)}%`);
const money = (n: number | null) =>
  n == null ? "—" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const fmt = (s: string | null) =>
  s ? `${new Date(s).toISOString().replace("T", " ").slice(0, 19)}Z` : "—";

// Mirrors supabase/functions/status/logic.ts's computeEquityHeadroomPct (#536,
// PR #542) exactly, guards included, so this page's floor-headroom number
// agrees with the status digest's published key for the same fact rather than
// diverging via a different denominator (#538 review finding 1: this page
// previously scaled by baseline, producing 10.0% vs A's 10.5% on the same
// equity/floor inputs).
function computeEquityHeadroomPct(equityUsd: number, floorPriceUsd: number): number | null {
  if (!Number.isFinite(equityUsd) || !Number.isFinite(floorPriceUsd) || equityUsd <= 0) {
    return null;
  }
  return ((equityUsd - floorPriceUsd) / equityUsd) * 100;
}

// Plain-fact age string, e.g. "3h 12m ago" / "2d 4h ago" — always rendered,
// never gated on the staleness threshold, per the honest-emptiness extension.
function formatAge(iso: string, now: Date): string {
  const ms = Math.max(0, now.getTime() - new Date(iso).getTime());
  const totalMinutes = Math.floor(ms / 60_000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h ago`;
  if (hours > 0) return `${hours}h ${minutes}m ago`;
  return `${minutes}m ago`;
}

export default async function Page() {
  const { recentScans, latestEntered, paused, baseline, trades, audit, account, positions, dbError } =
    await getData();
  // Synchronous, request-time read (design spec §8's accepted tension
  // resolution); no need to join the Promise.all above.
  const latestVerifiedDay = getLatestVerifiedDay();

  const latestScan = recentScans[0] ?? null;
  const now = new Date();
  const ageText = latestScan ? formatAge(latestScan.bar_ts, now) : null;
  const staleHours = latestScan ? (now.getTime() - new Date(latestScan.bar_ts).getTime()) / 3_600_000 : null;
  const isStale = staleHours != null && staleHours > STALE_HOURS_THRESHOLD;

  // Bracket-level pairing is a disclosed heuristic, not a guaranteed match:
  // Alpaca positions carry no back-reference to the order that opened them, so
  // this pairs by symbol. `symbol` is the traded symbol derived from the latest
  // scan, and only a position under this traded symbol is paired here — a
  // position under any other symbol (e.g. a legacy leftover) is not shown in
  // this section at all, though it still appears in the unfiltered Holdings
  // panel below. The "unavailable" note further down fires when the traded
  // symbol does have an open position but the latest entered-scan row is for
  // a different symbol (or none exists), so there is no bracket data to
  // attach to it.
  const symbol = latestScan?.symbol ?? DEFAULT_SYMBOL;
  const matchedPosition = positions.find((p) => p.symbol === symbol) ?? null;
  const openPosition = matchedPosition && matchedPosition.qty != null && matchedPosition.qty !== 0
    ? matchedPosition
    : null;
  const bracketRow = openPosition && latestEntered && latestEntered.symbol === openPosition.symbol
    ? latestEntered
    : null;
  // Gated on account !== null: when the account read fails, the section above
  // renders "position unknown" rather than asserting openPosition, so a note
  // that presupposes an asserted position must not render alongside it.
  const bracketUnavailable = account !== null && openPosition != null && bracketRow == null;

  const equity = latestScan?.equity_usd ?? null;
  const floorPrice = baseline != null ? baseline * (1 - EQUITY_FLOOR_PCT) : null;
  const headroomPct = equity != null && floorPrice != null
    ? computeEquityHeadroomPct(equity, floorPrice)
    : null;
  const floorBreached = equity != null && floorPrice != null && equity <= floorPrice;

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Trading Bot — Status</h1>
        <span className="text-xs text-muted">read-only · refresh to update</span>
      </header>

      {dbError && (
        <div className="rounded-md border border-neg/40 bg-neg/15 px-4 py-2 text-sm text-neg">
          ⚠ Data load partially failed — one or more Supabase reads errored. Values
          below may be stale or missing; do not treat blanks as “all clear”.
        </div>
      )}

      {isStale && ageText && (
        <div className="rounded-md border border-warn/40 bg-warn/15 px-4 py-2 text-sm text-warn">
          ⚠ Newest scan is {ageText} (older than the {STALE_HOURS_THRESHOLD}h threshold) — the bot may
          be stalled. A frozen dashboard should read as frozen, not as “all clear”.
        </div>
      )}

      {!latestScan && !dbError && (
        <div className="rounded-md border border-accent-border bg-bg-glow/50 px-4 py-2 text-sm text-muted">
          No hourly_scans rows yet — the bot has not run, or is pointed at a fresh database.
        </div>
      )}

      {paused && (
        <div className="rounded-md border border-warn/40 bg-warn/15 px-4 py-2 text-sm text-warn">
          ⏸ Trading is PAUSED (bot_config.paused = true)
        </div>
      )}

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Latest bar" value={latestScan ? fmt(latestScan.bar_ts) : "—"} accent="zinc" />
        <Stat
          label="Decision"
          value={latestScan?.decision ?? "—"}
          accent={latestScan?.decision === "LONG"
            ? "emerald"
            : latestScan?.decision === "SHORT"
            ? "amber"
            : "zinc"}
        />
        <Stat label="Paused" value={paused ? "PAUSED" : "no"} accent={paused ? "amber" : "zinc"} />
        <Stat
          label={`Equity vs -${EQUITY_FLOOR_PCT * 100}% floor`}
          value={pctValue(headroomPct)}
          accent={floorBreached ? "red" : "zinc"}
        />
      </section>

      {latestScan && (
        <p className="text-sm text-muted">
          Latest scan: <span className="text-fg-2">{fmt(latestScan.bar_ts)}</span> ({ageText}) ·{" "}
          {latestScan.symbol} {latestScan.decision}
          {latestScan.skip_reason ? ` · skip reason: ${latestScan.skip_reason}` : ""} · equity{" "}
          {money(equity)}
          {floorPrice != null ? ` · floor ${money(floorPrice)}` : ""}
        </p>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-fg-2">Open position &amp; bracket levels ({symbol})</h2>
        {account === null ? (
          <div className="rounded-lg border border-border bg-bg-glow/50 p-4 text-sm text-muted">
            Position unknown — the Alpaca account read failed. This is not a claim of "no
            position"; see the Holdings panel below for the connection details.
          </div>
        ) : openPosition === null ? (
          <div className="rounded-lg border border-border bg-bg-glow/50 p-4 text-sm text-muted">
            No open {symbol} position.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat
              label="Side"
              value={(openPosition.qty as number) > 0 ? "LONG" : "SHORT"}
              accent={(openPosition.qty as number) > 0 ? "emerald" : "amber"}
            />
            <Stat label="Qty" value={String(Math.abs(openPosition.qty as number))} accent="zinc" />
            <Stat label="Entry ref / stop" value={bracketRow ? `${money(bracketRow.entry_ref_price)} / ${money(bracketRow.stop_price)}` : "—"} accent="zinc" />
            <Stat label="Target" value={bracketRow ? money(bracketRow.target_price) : "—"} accent="zinc" />
          </div>
        )}
        {bracketUnavailable && (
          <p className="text-xs text-muted">
            Bracket levels unavailable for this symbol — Alpaca positions carry no back-reference to
            the order that opened them, so this page pairs the open position with the latest entered
            scan by symbol only; no entered scan matches {symbol}.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-fg-2">
          Holdings — Alpaca {account && account.paper === false ? "LIVE" : "paper"}
        </h2>
        {account === null ? (
          <div className="rounded-lg border border-border bg-bg-glow/50 p-4 text-sm text-muted">
            Alpaca not connected — set <code className="text-fg-2">ALPACA_API_KEY</code>,{" "}
            <code className="text-fg-2">ALPACA_SECRET_KEY</code> (and <code className="text-fg-2">ALPACA_PAPER</code>)
            in the Vercel project to show live equity + positions.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Equity" value={money(account.equity)} accent="zinc" />
              <Stat label="Cash" value={money(account.cash)} accent="zinc" />
            </div>
            <Table
              title=""
              cols={["symbol", "qty", "avg entry", "current", "market value", "unrealized P&L"]}
              rows={positions.map((p) => [
                p.symbol,
                p.qty == null ? "—" : String(p.qty),
                money(p.avgEntry),
                money(p.currentPrice),
                money(p.marketValue),
                p.unrealizedPl == null
                  ? "—"
                  : `${p.unrealizedPl >= 0 ? "+" : ""}${money(p.unrealizedPl)} (${pct(p.unrealizedPlpc)})`,
              ])}
              empty="No open positions."
            />
          </>
        )}
      </section>

      <Table
        title="Recent scans"
        cols={["bar", "symbol", "decision", "detectors fired", "skip reason"]}
        rows={recentScans.map((s) => [
          fmt(s.bar_ts),
          s.symbol,
          s.decision,
          s.detectors_fired.length > 0 ? s.detectors_fired.join(", ") : "—",
          s.skip_reason ?? "—",
        ])}
        empty="No scans yet."
      />

      <Table
        title="Recent trades"
        cols={["fill time", "side", "qty", "symbol", "price", "reason"]}
        rows={trades.map((t) => [fmt(t.fill_time), t.side, String(t.qty), t.symbol, money(t.fill_price), t.reason])}
        empty="No trades yet."
      />

      <Table
        title="Recent runs (audit log)"
        cols={["finished", "script", "outcome", "notes"]}
        rows={audit.map((a) => [fmt(a.finished_at), a.script_name, a.outcome ?? "—", a.notes ?? ""])}
        empty="No runs yet."
      />

      <a
        href="/daily"
        className="block rounded-lg border border-border bg-bg-glow/50 p-4 hover:border-accent-border"
      >
        <div className="text-[11px] uppercase tracking-wide text-muted">Daily verification</div>
        <div
          className={`mt-1 text-lg font-semibold ${
            latestVerifiedDay?.verdict === "FAIL"
              ? "text-neg"
              : latestVerifiedDay?.verdict === "WARN"
              ? "text-warn"
              : latestVerifiedDay
              ? "text-pos"
              : "text-fg"
          }`}
        >
          {latestVerifiedDay ? `${latestVerifiedDay.date} · ${latestVerifiedDay.verdict}` : "No verified days yet"}
        </div>
      </a>
    </main>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent: string }) {
  const color: Record<string, string> = {
    emerald: "text-pos",
    amber: "text-warn",
    red: "text-neg",
    zinc: "text-fg",
  };
  return (
    <div className="rounded-lg border border-border bg-bg-glow/50 p-4">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${color[accent] ?? "text-fg"}`}>{value}</div>
    </div>
  );
}

function Table({ title, cols, rows, empty }: { title: string; cols: string[]; rows: string[][]; empty: string }) {
  return (
    <section>
      {title ? <h2 className="mb-2 text-sm font-medium text-fg-2">{title}</h2> : null}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-bg-glow/60 text-[11px] uppercase tracking-wide text-muted">
            <tr>
              {cols.map((c) => (
                <th key={c} className="px-3 py-2 font-medium">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={cols.length} className="px-3 py-4 text-muted">{empty}</td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={i} className="hover:bg-bg-glow/40">
                  {r.map((c, j) => (
                    <td key={j} className="whitespace-nowrap px-3 py-2 text-fg-2">{c}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}