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

Deno.test("rejects out-of-range KILL_SWITCH_LOOKBACK_DAYS", () => {
  clearEnv();
  Deno.env.set("KILL_SWITCH_LOOKBACK_DAYS", "3");
  assertThrows(() => getStrategyConfig(), Error, "KILL_SWITCH_LOOKBACK_DAYS");
  clearEnv();
});

Deno.test("rejects empty BOT_TICKER", () => {
  clearEnv();
  Deno.env.set("BOT_TICKER", "  ");
  assertThrows(() => getStrategyConfig(), Error, "BOT_TICKER");
  clearEnv();
});

import { getAlpacaConfig, getN8nWebhookUrl, isClaudeAgentNoBroker } from "./config.ts";

Deno.test("getAlpacaConfig throws when keys missing", () => {
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  assertThrows(() => getAlpacaConfig(), Error, "ALPACA_API_KEY");
});

Deno.test("getAlpacaConfig defaults to paper base URL", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.delete("ALPACA_PAPER");
  const c = getAlpacaConfig();
  assertEquals(c.paper, true);
  assertEquals(c.tradingBaseUrl, "https://paper-api.alpaca.markets");
  assertEquals(c.dataBaseUrl, "https://data.alpaca.markets");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
});

Deno.test("getAlpacaConfig honours ALPACA_PAPER=false", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_PAPER", "false");
  assertEquals(getAlpacaConfig().tradingBaseUrl, "https://api.alpaca.markets");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  Deno.env.delete("ALPACA_PAPER");
});

Deno.test("getN8nWebhookUrl empty when unset", () => {
  Deno.env.delete("N8N_WEBHOOK_URL");
  assertEquals(getN8nWebhookUrl(), "");
});

Deno.test("isClaudeAgentNoBroker reads env fresh", () => {
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
  assertEquals(isClaudeAgentNoBroker(), false);
  Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
  assertEquals(isClaudeAgentNoBroker(), true);
  Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
});
