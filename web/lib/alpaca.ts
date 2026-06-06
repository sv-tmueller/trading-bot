import "server-only";

// Server-side, READ-ONLY Alpaca access for the dashboard (account + positions).
// Uses only GET endpoints — no order placement. Keys are read from the
// environment and never reach the browser. Degrades gracefully: if keys are
// missing or a request fails, returns null/[] so the page still renders.

const paper = (process.env.ALPACA_PAPER ?? "true").toLowerCase() !== "false";
const BASE = paper ? "https://paper-api.alpaca.markets" : "https://api.alpaca.markets";

function headers(): Record<string, string> | null {
  const id = process.env.ALPACA_API_KEY;
  const secret = process.env.ALPACA_SECRET_KEY;
  if (!id || !secret) return null;
  return { "APCA-API-KEY-ID": id, "APCA-API-SECRET-KEY": secret };
}

// Coerce a value to a finite number, or null if it is missing/NaN/Infinity.
// A malformed-but-200 Alpaca payload would otherwise yield NaN and render $NaN.
function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export interface AlpacaAccount {
  equity: number | null;
  buyingPower: number | null;
  cash: number | null;
  paper: boolean;
}

export interface AlpacaPosition {
  symbol: string;
  qty: number | null;
  avgEntry: number | null;
  currentPrice: number | null;
  marketValue: number | null;
  unrealizedPl: number | null;
  unrealizedPlpc: number | null;
}

export async function getAccount(): Promise<AlpacaAccount | null> {
  const h = headers();
  if (!h) return null;
  try {
    const r = await fetch(`${BASE}/v2/account`, { headers: h, cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    return { equity: num(j.equity), buyingPower: num(j.buying_power), cash: num(j.cash), paper };
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
      qty: num(p.qty),
      avgEntry: num(p.avg_entry_price),
      currentPrice: num(p.current_price),
      marketValue: num(p.market_value),
      unrealizedPl: num(p.unrealized_pl),
      unrealizedPlpc: num(p.unrealized_plpc),
    }));
  } catch {
    return [];
  }
}
