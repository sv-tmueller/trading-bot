import { serviceClient } from "@/lib/supabase";

// Always render fresh at request time — this is a live status page.
export const dynamic = "force-dynamic";

type RegimeState = {
  date: string;
  spy_close: number;
  spy_sma200: number;
  target_state: string;
  current_state: string;
  position_drawdown_pct: number | null;
  kill_switch_active: boolean;
  kill_switch_fired_at: string | null;
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

async function getData() {
  const sb = serviceClient();
  const [rs, cfg, tr, al] = await Promise.all([
    sb.from("regime_state").select("*").order("date", { ascending: false }).limit(1).maybeSingle(),
    sb.from("bot_config").select("value").eq("key", "paused").maybeSingle(),
    sb.from("trades").select("*").order("id", { ascending: false }).limit(10),
    sb.from("audit_log").select("*").order("id", { ascending: false }).limit(15),
  ]);
  return {
    regime: (rs.data as RegimeState | null) ?? null,
    paused: (cfg.data as { value: string } | null)?.value === "true",
    trades: (tr.data as Trade[] | null) ?? [],
    audit: (al.data as Audit[] | null) ?? [],
  };
}

const pct = (n: number | null) => (n == null ? "—" : `${(n * 100).toFixed(2)}%`);
const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const fmt = (s: string | null) =>
  s ? `${new Date(s).toISOString().replace("T", " ").slice(0, 19)}Z` : "—";

export default async function Page() {
  const { regime, paused, trades, audit } = await getData();
  const bullish = regime ? regime.spy_close > regime.spy_sma200 : false;

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Trading Bot — Status</h1>
        <span className="text-xs text-zinc-500">read-only · refresh to update</span>
      </header>

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Position" value={regime?.current_state ?? "—"} accent={regime?.current_state === "LONG" ? "emerald" : "zinc"} />
        <Stat label="Regime (SPY vs 200-DMA)" value={regime ? (bullish ? "BULLISH" : "BEARISH") : "—"} accent={bullish ? "emerald" : "amber"} />
        <Stat label="Drawdown" value={pct(regime?.position_drawdown_pct ?? null)} accent={(regime?.position_drawdown_pct ?? 0) <= -0.15 ? "red" : "zinc"} />
        <Stat label="Kill-switch" value={regime?.kill_switch_active ? "ACTIVE" : "off"} accent={regime?.kill_switch_active ? "red" : "zinc"} />
      </section>

      {paused && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/15 px-4 py-2 text-sm text-amber-300">
          ⏸ Trading is PAUSED (bot_config.paused = true)
        </div>
      )}

      {regime && (
        <p className="text-sm text-zinc-400">
          As of <span className="text-zinc-200">{regime.date}</span>: SPY {money(regime.spy_close)} vs 200-DMA{" "}
          {money(regime.spy_sma200)} · target {regime.target_state}
          {regime.kill_switch_fired_at ? ` · kill-switch fired ${fmt(regime.kill_switch_fired_at)}` : ""}
        </p>
      )}

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
    </main>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent: string }) {
  const color: Record<string, string> = {
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    red: "text-red-400",
    zinc: "text-zinc-100",
  };
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${color[accent] ?? "text-zinc-100"}`}>{value}</div>
    </div>
  );
}

function Table({ title, cols, rows, empty }: { title: string; cols: string[]; rows: string[][]; empty: string }) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-medium text-zinc-300">{title}</h2>
      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-900/60 text-[11px] uppercase tracking-wide text-zinc-500">
            <tr>
              {cols.map((c) => (
                <th key={c} className="px-3 py-2 font-medium">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={cols.length} className="px-3 py-4 text-zinc-500">{empty}</td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={i} className="hover:bg-zinc-900/40">
                  {r.map((c, j) => (
                    <td key={j} className="whitespace-nowrap px-3 py-2 text-zinc-300">{c}</td>
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
