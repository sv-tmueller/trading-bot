// Alpaca Market Data REST v2. Replaces yfinance. Feed controlled by ALPACA_DATA_FEED (default iex).
import { getAlpacaConfig } from "./config.ts";
import { DataError, requireNumber } from "./num.ts";

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
  // sort=asc makes oldest-first explicit rather than relying on the API default.
  // adjustment=all (#265): the backtest that validated the strategy uses fully
  // adjusted data, so the live SMA must too — and split-adjusting the bars stops
  // a forward split of the bot ticker from faking a -50% kill-switch drawdown.
  const url = `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/bars` +
    `?timeframe=1Day&start=${start}&limit=10000&adjustment=all&sort=asc&feed=${cfg.dataFeed}`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET bars ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  const bars = Array.isArray(j.bars) ? j.bars : [];
  return bars.map((b: { t: string; c: unknown; h: unknown }) => ({
    date: String(b.t).slice(0, 10),
    close: requireNumber(b.c, "bar close"),
    high: requireNumber(b.h, "bar high"),
  }));
}

export async function getLatestTradePrice(symbol: string): Promise<number> {
  const cfg = getAlpacaConfig();
  const url = `${cfg.dataBaseUrl}/v2/stocks/${
    encodeURIComponent(symbol)
  }/trades/latest?feed=${cfg.dataFeed}`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET latest trade ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  if (!j.trade) {
    throw new DataError(`no latest trade for ${symbol} (got ${JSON.stringify(j.trade)})`);
  }
  return requireNumber(j.trade.p, "trade price");
}

export async function getLatestQuote(
  symbol: string,
): Promise<{ bid: number; ask: number; mid: number }> {
  const cfg = getAlpacaConfig();
  const url = `${cfg.dataBaseUrl}/v2/stocks/${
    encodeURIComponent(symbol)
  }/quotes/latest?feed=${cfg.dataFeed}`;
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
  if (bid <= 0 || ask <= 0 || bid > ask) {
    throw new DataError(`implausible quote for ${symbol}: bid=${bid} ask=${ask}`);
  }
  return { bid, ask, mid: (bid + ask) / 2 };
}
