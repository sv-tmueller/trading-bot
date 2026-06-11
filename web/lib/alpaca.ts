// Server-side Alpaca access for the dashboard (account + positions). This
// module only calls GET endpoints — no order placement — but Alpaca API keys
// are UNSCOPED full-trading keys (Alpaca offers no read-only scope), so they
// must be treated as trading credentials: server-side env only, never
// NEXT_PUBLIC_, never shipped to the browser. Degrades gracefully: if keys are
// missing or a request fails, returns null/[] so the page still renders.

const paper = (process.env.ALPACA_PAPER ?? "true").toLowerCase() !== "false";
const BASE = paper ? "https://paper-api.alpaca.markets" : "https://api.alpaca.markets";

function headers(): Record<string, string> | null {
  const id = process.env.ALPACA_API_KEY;
  const secret = process.env.ALPACA_SECRET_KEY;
  if (!id || !secret) return null;
  return { "APCA-API-KEY-ID": id, "APCA-API-SECRET-KEY": secret };
}

export interface AlpacaAccount {
  equity: number;
  buyingPower: number;
  cash: number;
  paper: boolean;
}

export interface AlpacaPosition {
  symbol: string;
  qty: number;
  avgEntry: number;
  currentPrice: number;
  marketValue: number;
  unrealizedPl: number;
  unrealizedPlpc: number;
}

export async function getAccount(): Promise<AlpacaAccount | null> {
  const h = headers();
  if (!h) return null;
  try {
    const r = await fetch(`${BASE}/v2/account`, { headers: h, cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    return { equity: Number(j.equity), buyingPower: Number(j.buying_power), cash: Number(j.cash), paper };
  } catch {
    return null;
  }
}

export async function getPositions(): Promise<AlpacaPosition[]> {
  const h = headers();
  if (!h) return [];
  try {
    const r = await fetch(`${BASE}/v2/positions`, { headers: h, cache: "no-store" });
    if (!r.ok) return [];
    const j = await r.json();
    if (!Array.isArray(j)) return [];
    // deno-lint-ignore no-explicit-any
    return j.map((p: any) => ({
      symbol: String(p.symbol),
      qty: Number(p.qty),
      avgEntry: Number(p.avg_entry_price),
      currentPrice: Number(p.current_price),
      marketValue: Number(p.market_value),
      unrealizedPl: Number(p.unrealized_pl),
      unrealizedPlpc: Number(p.unrealized_plpc),
    }));
  } catch {
    return [];
  }
}
