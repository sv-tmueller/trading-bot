import { assertEquals, assertRejects } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import {
  getCalendarSessions,
  getDailyCloses,
  getHourlyBars,
  getLatestQuote,
  getLatestTradePrice,
} from "./marketdata.ts";
import { DataError } from "./num.ts";

function setKeys() {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
}
function clearKeys() {
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
}

Deno.test("getDailyCloses returns ordered {date, close, high}", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/stocks/SPY/bars"), true);
    assertEquals(urlOf(i).includes("feed=iex"), true);
    assertEquals(urlOf(i).includes("sort=asc"), true);
    // #265: must match the backtest's auto-adjusted data (dividends + splits).
    assertEquals(urlOf(i).includes("adjustment=all"), true);
    return Promise.resolve(jsonResponse({
      bars: [
        { t: "2026-06-03T04:00:00Z", o: 1, h: 401, l: 1, c: 400, v: 1 },
        { t: "2026-06-04T04:00:00Z", o: 1, h: 412, l: 1, c: 410, v: 1 },
      ],
      next_page_token: null,
    }));
  });
  try {
    const bars = await getDailyCloses("SPY", 250);
    assertEquals(bars.length, 2);
    assertEquals(bars[1], { date: "2026-06-04", close: 410, high: 412 });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getDailyCloses returns [] on empty history", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({ bars: null, next_page_token: null }))
  );
  try {
    assertEquals(await getDailyCloses("SPY", 250), []);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getDailyCloses throws on a null close (no silent zero)", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({
      bars: [{ t: "2026-06-04T04:00:00Z", h: 412, c: null }],
    }))
  );
  try {
    await assertRejects(() => getDailyCloses("SPY", 250), DataError, "bar close");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestTradePrice parses trade.p", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/stocks/UPRO/trades/latest"), true);
    return Promise.resolve(jsonResponse({ trade: { p: 71.25, s: 10, t: "x" } }));
  });
  try {
    assertEquals(await getLatestTradePrice("UPRO"), 71.25);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestTradePrice throws when no trade is returned", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ trade: null })));
  try {
    await assertRejects(() => getLatestTradePrice("UPRO"), DataError, "no latest trade");
  } finally {
    restore();
    clearKeys();
  }
});

// ---------------------------------------------------------------------------
// getLatestQuote (#269 finding 8)
// ---------------------------------------------------------------------------

Deno.test("getLatestQuote returns {bid, ask, mid}", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/stocks/UPRO/quotes/latest"), true);
    assertEquals(urlOf(i).includes("feed=iex"), true);
    return Promise.resolve(jsonResponse({ quote: { bp: 10, ap: 10.2 } }));
  });
  try {
    const q = await getLatestQuote("UPRO");
    assertEquals(q.bid, 10);
    assertEquals(q.ask, 10.2);
    assertEquals(q.mid, 10.1);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestQuote throws DataError when quote is missing", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ quote: null })));
  try {
    await assertRejects(() => getLatestQuote("UPRO"), DataError, "no latest quote");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestQuote throws DataError when bid is non-numeric", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ quote: { bp: "x", ap: 10 } })));
  try {
    await assertRejects(() => getLatestQuote("UPRO"), DataError, "quote bid");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestQuote throws DataError when ask is non-numeric", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ quote: { bp: 10, ap: "x" } })));
  try {
    await assertRejects(() => getLatestQuote("UPRO"), DataError, "quote ask");
  } finally {
    restore();
    clearKeys();
  }
});

// ---------------------------------------------------------------------------
// getLatestQuote: crossed / non-positive quote guard (#330)
// ---------------------------------------------------------------------------

Deno.test("getLatestQuote throws DataError on crossed market (bid > ask)", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ quote: { bp: 11, ap: 10 } })));
  try {
    await assertRejects(() => getLatestQuote("UPRO"), DataError, "implausible quote");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestQuote throws DataError on zero bid", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ quote: { bp: 0, ap: 10 } })));
  try {
    await assertRejects(() => getLatestQuote("UPRO"), DataError, "implausible quote");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestQuote throws DataError on negative ask", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ quote: { bp: 10, ap: -1 } })));
  try {
    await assertRejects(() => getLatestQuote("UPRO"), DataError, "implausible quote");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getLatestQuote uses ALPACA_DATA_FEED=sip when set", async () => {
  setKeys();
  Deno.env.set("ALPACA_DATA_FEED", "sip");
  let capturedUrl = "";
  const restore = stubFetch((i) => {
    capturedUrl = urlOf(i);
    return Promise.resolve(jsonResponse({ quote: { bp: 10, ap: 10.2 } }));
  });
  try {
    await getLatestQuote("UPRO");
    assertEquals(capturedUrl.includes("feed=sip"), true);
  } finally {
    restore();
    clearKeys();
    Deno.env.delete("ALPACA_DATA_FEED");
  }
});

Deno.test("getDailyCloses uses ALPACA_DATA_FEED (not hard-coded iex)", async () => {
  setKeys();
  Deno.env.set("ALPACA_DATA_FEED", "sip");
  let capturedUrl = "";
  const restore = stubFetch((i) => {
    capturedUrl = urlOf(i);
    return Promise.resolve(jsonResponse({ bars: [], next_page_token: null }));
  });
  try {
    await getDailyCloses("SPY", 5);
    assertEquals(capturedUrl.includes("feed=sip"), true);
    assertEquals(capturedUrl.includes("feed=iex"), false);
  } finally {
    restore();
    clearKeys();
    Deno.env.delete("ALPACA_DATA_FEED");
  }
});

Deno.test("getLatestTradePrice uses ALPACA_DATA_FEED (not hard-coded iex)", async () => {
  setKeys();
  Deno.env.set("ALPACA_DATA_FEED", "sip");
  let capturedUrl = "";
  const restore = stubFetch((i) => {
    capturedUrl = urlOf(i);
    return Promise.resolve(jsonResponse({ trade: { p: 71.25, s: 10, t: "x" } }));
  });
  try {
    await getLatestTradePrice("UPRO");
    assertEquals(capturedUrl.includes("feed=sip"), true);
    assertEquals(capturedUrl.includes("feed=iex"), false);
  } finally {
    restore();
    clearKeys();
    Deno.env.delete("ALPACA_DATA_FEED");
  }
});

// ---------------------------------------------------------------------------
// #475 T3: getHourlyBars + getCalendarSessions
// ---------------------------------------------------------------------------

Deno.test("getHourlyBars: URL uses timeframe=1Hour and the configured feed", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/stocks/SPY/bars"), true);
    assertEquals(urlOf(i).includes("timeframe=1Hour"), true);
    assertEquals(urlOf(i).includes("feed=iex"), true);
    assertEquals(urlOf(i).includes("sort=asc"), true);
    assertEquals(urlOf(i).includes("adjustment=all"), true);
    return Promise.resolve(jsonResponse({ bars: [] }));
  });
  try {
    await getHourlyBars("SPY", { count: 10 });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getHourlyBars: maps o/h/l/c/t into Bar-shaped rows", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({
      bars: [
        { t: "2026-07-27T14:00:00Z", o: 550, h: 551, l: 549, c: 550.5 },
        { t: "2026-07-27T15:00:00Z", o: 550.5, h: 552, l: 550, c: 551.5 },
      ],
    }))
  );
  try {
    const bars = await getHourlyBars("SPY", { count: 10 });
    assertEquals(bars.length, 2);
    assertEquals(bars[0], {
      timestamp: "2026-07-27T14:00:00Z",
      open: 550,
      high: 551,
      low: 549,
      close: 550.5,
    });
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getHourlyBars: throws DataError on a malformed number (no silent zero)", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse({
      bars: [{ t: "2026-07-27T14:00:00Z", o: 550, h: 551, l: null, c: 550.5 }],
    }))
  );
  try {
    await assertRejects(() => getHourlyBars("SPY", { count: 10 }), DataError, "bar low");
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getHourlyBars: empty bars array returns []", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ bars: null })));
  try {
    assertEquals(await getHourlyBars("SPY", { count: 10 }), []);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getCalendarSessions: returns {date, open, close} per day", async () => {
  setKeys();
  const restore = stubFetch((i) => {
    assertEquals(urlOf(i).includes("/v2/calendar?start=2026-07-27&end=2026-07-27"), true);
    return Promise.resolve(jsonResponse([
      { date: "2026-07-27", open: "09:30", close: "16:00" },
    ]));
  });
  try {
    const sessions = await getCalendarSessions("2026-07-27", "2026-07-27");
    assertEquals(sessions, [{ date: "2026-07-27", open: "09:30", close: "16:00" }]);
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getCalendarSessions: missing open/close is a hard error, never a permissive filter", async () => {
  setKeys();
  const restore = stubFetch(() =>
    Promise.resolve(jsonResponse([{ date: "2026-07-27", open: null, close: "16:00" }]))
  );
  try {
    await assertRejects(
      () => getCalendarSessions("2026-07-27", "2026-07-27"),
      DataError,
      "open/close",
    );
  } finally {
    restore();
    clearKeys();
  }
});

Deno.test("getCalendarSessions: throws on a non-array body", async () => {
  setKeys();
  const restore = stubFetch(() => Promise.resolve(jsonResponse({ message: "boom" })));
  try {
    await assertRejects(
      () => getCalendarSessions("2026-07-27", "2026-07-27"),
      DataError,
      "non-array",
    );
  } finally {
    restore();
    clearKeys();
  }
});
