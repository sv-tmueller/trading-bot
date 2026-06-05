// Alpaca Market Data REST v2. Replaces yfinance. Uses the IEX feed (free).
import { getAlpacaConfig } from "./config.ts";

export interface DailyBar {
  date: string; // YYYY-MM-DD (UTC)
  close: number;
  high: number;
}

function headers() {
  const cfg = getAlpacaConfig();
  return {
    "APCA-API-KEY-ID": cfg.apiKeyId,
    "APCA-API-SECRET-KEY": cfg.apiSecretKey,
  };
}

// Fetch the most recent `count` daily bars, oldest-first. `count` should exceed
// the SMA window (e.g. 250 for a 200-DMA) to guarantee enough history.
export async function getDailyCloses(symbol: string, count: number): Promise<DailyBar[]> {
  const cfg = getAlpacaConfig();
  // Look back generously in calendar days to cover `count` trading days.
  const startMs = Date.now() - Math.ceil(count * 1.6) * 24 * 60 * 60 * 1000;
  const start = new Date(startMs).toISOString().slice(0, 10);
  const url =
    `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/bars` +
    `?timeframe=1Day&start=${start}&limit=10000&adjustment=raw&feed=iex`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET bars ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  const bars = Array.isArray(j.bars) ? j.bars : [];
  return bars.map((b: { t: string; c: number; h: number }) => ({
    date: String(b.t).slice(0, 10),
    close: Number(b.c),
    high: Number(b.h),
  }));
}

export async function getLatestTradePrice(symbol: string): Promise<number> {
  const cfg = getAlpacaConfig();
  const url =
    `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/trades/latest?feed=iex`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET latest trade ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  return Number(j.trade.p);
}
