import { assertEquals, assertRejects } from "@std/assert";
import { jsonResponse, stubFetch, urlOf } from "./test_helpers.ts";
import { getDailyCloses, getLatestTradePrice } from "./marketdata.ts";
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
