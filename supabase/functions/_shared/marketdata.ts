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

// ---------------------------------------------------------------------------
// #475 T3: hourly bars + session bounds for the hourly-check bot.
// ---------------------------------------------------------------------------

export interface HourlyBar {
  timestamp: string; // RFC3339 bar-start timestamp, maps into candlestick.ts's Bar.timestamp
  open: number;
  high: number;
  low: number;
  close: number;
}

// Fetch depth (how far back to look, in calendar days) is a caller concern
// (logic.ts decides `count` per §4: >= CONTEXT_SMA_WINDOW + margin when
// contextMode != none, else a small fixed count). This helper just fetches
// generously enough calendar history to cover `count` hourly bars: ~6.5 RTH
// hours/session, padded 1.6x for weekends/holidays -- same convention as
// getDailyCloses's lookback.
export async function getHourlyBars(
  symbol: string,
  opts: { count: number },
): Promise<HourlyBar[]> {
  const cfg = getAlpacaConfig();
  const sessionsNeeded = Math.ceil(opts.count / 6) + 5;
  const startMs = Date.now() - Math.ceil(sessionsNeeded * 1.6) * 24 * 60 * 60 * 1000;
  const start = new Date(startMs).toISOString();
  const url = `${cfg.dataBaseUrl}/v2/stocks/${encodeURIComponent(symbol)}/bars` +
    `?timeframe=1Hour&start=${start}&limit=10000&adjustment=all&sort=asc&feed=${cfg.dataFeed}`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET hourly bars ${symbol} -> ${res.status}: ${await res.text()}`);
  }
  const j = await res.json();
  const bars = Array.isArray(j.bars) ? j.bars : [];
  return bars.map((b: { t: string; o: unknown; h: unknown; l: unknown; c: unknown }) => ({
    timestamp: String(b.t),
    open: requireNumber(b.o, "bar open"),
    high: requireNumber(b.h, "bar high"),
    low: requireNumber(b.l, "bar low"),
    close: requireNumber(b.c, "bar close"),
  }));
}

export interface CalendarSession {
  date: string; // YYYY-MM-DD
  open: string; // exchange-local HH:MM (per Alpaca's /v2/calendar semantics)
  close: string; // exchange-local HH:MM
}

// Additive extension of the trading-REST /v2/calendar endpoint already read
// by alpaca.ts's getCalendar() (a plain date-list helper, untouched). This
// helper reads the same endpoint for its open/close fields, used by the
// session-close flatten mechanic (spec §7). Missing/unparseable open/close is
// a hard error -- same anti-silent posture as the next_close guard: a
// permissive filter here could silently treat every day as having no
// session bounds and defeat the flatten-scan detection with no visible
// signal that anything is wrong.
export async function getCalendarSessions(start: string, end: string): Promise<CalendarSession[]> {
  const cfg = getAlpacaConfig();
  const url = `${cfg.tradingBaseUrl}/v2/calendar?start=${start}&end=${end}`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) {
    throw new Error(`GET calendar sessions -> ${res.status}: ${await res.text()}`);
  }
  const arr = await res.json();
  if (!Array.isArray(arr)) {
    throw new DataError("GET calendar sessions -> unexpected non-array body");
  }
  return arr.map((e: Record<string, unknown>) => {
    const date = e.date;
    const open = e.open;
    const close = e.close;
    if (typeof date !== "string" || date === "") {
      throw new DataError(`calendar session missing date: ${JSON.stringify(e)}`);
    }
    if (typeof open !== "string" || open === "" || typeof close !== "string" || close === "") {
      throw new DataError(`calendar session ${date} missing open/close: ${JSON.stringify(e)}`);
    }
    return { date, open, close };
  });
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
