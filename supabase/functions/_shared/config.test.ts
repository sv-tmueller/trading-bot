import { assertEquals, assertThrows } from "@std/assert";
import { getStrategyConfig } from "./config.ts";

function clearEnv() {
  for (
    const k of [
      "REGIME_SMA_DAYS",
      "KILL_SWITCH_DRAWDOWN_PCT",
      "KILL_SWITCH_LOOKBACK_DAYS",
      "BOT_TICKER",
      "BOT_BENCHMARK",
    ]
  ) {
    Deno.env.delete(k);
  }
}

Deno.test("defaults when env is unset", () => {
  clearEnv();
  const c = getStrategyConfig();
  assertEquals(c.regimeSmaDays, 200);
  assertEquals(c.killSwitchDrawdownPct, 0.25);
  assertEquals(c.killSwitchLookbackDays, 30);
  assertEquals(c.botTicker, "UPRO");
  assertEquals(c.botBenchmark, "SPY");
});

Deno.test("reads valid overrides", () => {
  clearEnv();
  Deno.env.set("REGIME_SMA_DAYS", "150");
  Deno.env.set("KILL_SWITCH_DRAWDOWN_PCT", "0.30");
  Deno.env.set("BOT_TICKER", "SPXL");
  const c = getStrategyConfig();
  assertEquals(c.regimeSmaDays, 150);
  assertEquals(c.killSwitchDrawdownPct, 0.30);
  assertEquals(c.botTicker, "SPXL");
  clearEnv();
});

Deno.test("rejects out-of-range REGIME_SMA_DAYS", () => {
  clearEnv();
  Deno.env.set("REGIME_SMA_DAYS", "10");
  assertThrows(() => getStrategyConfig(), Error, "REGIME_SMA_DAYS");
  clearEnv();
});

Deno.test("rejects out-of-range KILL_SWITCH_DRAWDOWN_PCT", () => {
  clearEnv();
  Deno.env.set("KILL_SWITCH_DRAWDOWN_PCT", "0.80");
  assertThrows(() => getStrategyConfig(), Error, "KILL_SWITCH_DRAWDOWN_PCT");
  clearEnv();
});

Deno.test("rejects empty BOT_TICKER", () => {
  clearEnv();
  Deno.env.set("BOT_TICKER", "  ");
  assertThrows(() => getStrategyConfig(), Error, "BOT_TICKER");
  clearEnv();
});
