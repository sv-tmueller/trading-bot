import { assertEquals, assertThrows } from "@std/assert";
import {
  getAlpacaConfig,
  getHourlyConfig,
  getNotifyWebhookUrl,
  getStatusToken,
  getStrategyConfig,
  isClaudeAgentNoBroker,
} from "./config.ts";

const HOURLY_KEYS = [
  "HOURLY_BOT_TICKER",
  "SIZING_RISK_PCT",
  "SIZING_NOTIONAL_CAP_PCT",
  "HOURLY_BRACKET_R_MULTIPLE",
  "HOURLY_STOP_BUFFER_PCT",
  "HOURLY_MIN_STOP_DISTANCE",
  "HOURLY_MAX_ENTRIES_PER_DAY",
  "HOURLY_STALENESS_TOLERANCE_MIN",
  "HOURLY_CONTEXT_MODE",
  "HOURLY_SHORTS_ENABLED",
  "HOURLY_BOT_PAPER_ONLY",
];

function clearHourlyEnv() {
  for (const k of HOURLY_KEYS) Deno.env.delete(k);
}

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

Deno.test("rejects whitespace-only BOT_BENCHMARK", () => {
  clearEnv();
  Deno.env.set("BOT_BENCHMARK", "  ");
  assertThrows(() => getStrategyConfig(), Error, "BOT_BENCHMARK");
  clearEnv();
});

Deno.test("stores padded BOT_TICKER/BOT_BENCHMARK trimmed", () => {
  clearEnv();
  Deno.env.set("BOT_TICKER", " UPRO ");
  Deno.env.set("BOT_BENCHMARK", " SPY ");
  const c = getStrategyConfig();
  assertEquals(c.botTicker, "UPRO");
  assertEquals(c.botBenchmark, "SPY");
  clearEnv();
});

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

Deno.test("getAlpacaConfig rejects invalid ALPACA_PAPER", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_PAPER", "0"); // not true/false -> must throw, not silently stay paper
  assertThrows(() => getAlpacaConfig(), Error, "ALPACA_PAPER");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  Deno.env.delete("ALPACA_PAPER");
});

Deno.test("getNotifyWebhookUrl empty when unset", () => {
  Deno.env.delete("NOTIFY_WEBHOOK_URL");
  Deno.env.delete("N8N_WEBHOOK_URL");
  assertEquals(getNotifyWebhookUrl(), "");
});

Deno.test("getNotifyWebhookUrl reads NOTIFY_WEBHOOK_URL", () => {
  Deno.env.set("NOTIFY_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y");
  assertEquals(getNotifyWebhookUrl(), "https://discord.com/api/webhooks/x/y");
  Deno.env.delete("NOTIFY_WEBHOOK_URL");
});

Deno.test("getNotifyWebhookUrl ignores the legacy N8N_WEBHOOK_URL name", () => {
  Deno.env.delete("NOTIFY_WEBHOOK_URL");
  Deno.env.set("N8N_WEBHOOK_URL", "http://localhost:5678/hook");
  assertEquals(getNotifyWebhookUrl(), "");
  Deno.env.delete("N8N_WEBHOOK_URL");
});

// ---------------------------------------------------------------------------
// isClaudeAgentNoBroker (#509 — fails loud on unrecognised values)
// ---------------------------------------------------------------------------

Deno.test("isClaudeAgentNoBroker: unset is false", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    assertEquals(isClaudeAgentNoBroker(), false);
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

Deno.test("isClaudeAgentNoBroker: blank/whitespace-only is false", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    for (const v of ["", "   "]) {
      Deno.env.set("CLAUDE_AGENT_NO_BROKER", v);
      assertEquals(isClaudeAgentNoBroker(), false);
    }
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

Deno.test("isClaudeAgentNoBroker: recognised on-values, incl. case variants, arm the guard", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    for (const v of ["1", "true", "yes", "TRUE", "Yes"]) {
      Deno.env.set("CLAUDE_AGENT_NO_BROKER", v);
      assertEquals(isClaudeAgentNoBroker(), true);
    }
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

Deno.test("isClaudeAgentNoBroker: whitespace-padded on-values still arm the guard (core bug)", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    for (const v of [" 1", "1 ", "true\n", "\tyes "]) {
      Deno.env.set("CLAUDE_AGENT_NO_BROKER", v);
      assertEquals(isClaudeAgentNoBroker(), true);
    }
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

Deno.test("isClaudeAgentNoBroker: explicit negatives, incl. padded/cased, are false", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    for (const v of ["0", "false", "no", " False "]) {
      Deno.env.set("CLAUDE_AGENT_NO_BROKER", v);
      assertEquals(isClaudeAgentNoBroker(), false);
    }
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

Deno.test("isClaudeAgentNoBroker: unrecognised values throw with the var name and offending value", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    for (const v of ["on", "enabled", "y", "armed"]) {
      Deno.env.set("CLAUDE_AGENT_NO_BROKER", v);
      assertThrows(() => isClaudeAgentNoBroker(), Error, "CLAUDE_AGENT_NO_BROKER");
    }
    Deno.env.set("CLAUDE_AGENT_NO_BROKER", "armed");
    assertThrows(() => isClaudeAgentNoBroker(), Error, "armed");
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

Deno.test("isClaudeAgentNoBroker reads env fresh (preserves mid-test flip semantics)", () => {
  const original = Deno.env.get("CLAUDE_AGENT_NO_BROKER");
  try {
    Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    assertEquals(isClaudeAgentNoBroker(), false);
    Deno.env.set("CLAUDE_AGENT_NO_BROKER", "true");
    assertEquals(isClaudeAgentNoBroker(), true);
  } finally {
    if (original === undefined) Deno.env.delete("CLAUDE_AGENT_NO_BROKER");
    else Deno.env.set("CLAUDE_AGENT_NO_BROKER", original);
  }
});

// ---------------------------------------------------------------------------
// ALPACA_DATA_FEED knob (#269 finding 8)
// ---------------------------------------------------------------------------

Deno.test("getAlpacaConfig: ALPACA_DATA_FEED defaults to iex", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.delete("ALPACA_DATA_FEED");
  assertEquals(getAlpacaConfig().dataFeed, "iex");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
});

Deno.test("getAlpacaConfig: ALPACA_DATA_FEED=sip accepted", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_DATA_FEED", "sip");
  assertEquals(getAlpacaConfig().dataFeed, "sip");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  Deno.env.delete("ALPACA_DATA_FEED");
});

Deno.test("getAlpacaConfig: invalid ALPACA_DATA_FEED throws", () => {
  Deno.env.set("ALPACA_API_KEY", "k");
  Deno.env.set("ALPACA_SECRET_KEY", "s");
  Deno.env.set("ALPACA_DATA_FEED", "nasdaq");
  assertThrows(() => getAlpacaConfig(), Error, "ALPACA_DATA_FEED");
  Deno.env.delete("ALPACA_API_KEY");
  Deno.env.delete("ALPACA_SECRET_KEY");
  Deno.env.delete("ALPACA_DATA_FEED");
});

// ---------------------------------------------------------------------------
// STATUS_TOKEN (#354 T2): a secret has no sensible default, so unlike the
// strategy knobs above, unset/blank must THROW rather than fall back.
// ---------------------------------------------------------------------------

Deno.test("getStatusToken: unset throws", () => {
  Deno.env.delete("STATUS_TOKEN");
  assertThrows(() => getStatusToken(), Error, "STATUS_TOKEN");
});

Deno.test("getStatusToken: blank/whitespace-only throws", () => {
  Deno.env.set("STATUS_TOKEN", "   ");
  assertThrows(() => getStatusToken(), Error, "STATUS_TOKEN");
  Deno.env.delete("STATUS_TOKEN");
});

Deno.test("getStatusToken: set returns trimmed value", () => {
  Deno.env.set("STATUS_TOKEN", "  s3cr3t  ");
  assertEquals(getStatusToken(), "s3cr3t");
  Deno.env.delete("STATUS_TOKEN");
});

// ---------------------------------------------------------------------------
// #475 T1: getHourlyConfig() -- §10 settings for the hourly-check bot. Kept
// separate from getStrategyConfig() so daily-check/kill-switch are untouched.
// ---------------------------------------------------------------------------

Deno.test("getHourlyConfig: defaults when env is unset (except the mandatory paper-only flag)", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  const c = getHourlyConfig();
  assertEquals(c.hourlyBotTicker, "SPY");
  assertEquals(c.sizingRiskPct, 0.01);
  assertEquals(c.sizingNotionalCapPct, 0.10);
  assertEquals(c.hourlyBracketRMultiple, 2);
  assertEquals(c.hourlyStopBufferPct, 0.05);
  assertEquals(c.hourlyMinStopDistance, 0.05);
  assertEquals(c.hourlyMaxEntriesPerDay, 3);
  assertEquals(c.hourlyStalenessToleranceMin, 10);
  assertEquals(c.hourlyContextMode, "none");
  assertEquals(c.hourlyShortsEnabled, false);
  assertEquals(c.hourlyBotPaperOnly, true);
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: reads valid overrides", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_BOT_TICKER", "QQQ");
  Deno.env.set("SIZING_RISK_PCT", "0.02");
  Deno.env.set("SIZING_NOTIONAL_CAP_PCT", "0.20");
  Deno.env.set("HOURLY_STOP_BUFFER_PCT", "0.10");
  Deno.env.set("HOURLY_MIN_STOP_DISTANCE", "0.10");
  Deno.env.set("HOURLY_MAX_ENTRIES_PER_DAY", "5");
  Deno.env.set("HOURLY_STALENESS_TOLERANCE_MIN", "15");
  Deno.env.set("HOURLY_CONTEXT_MODE", "reversal");
  Deno.env.set("HOURLY_SHORTS_ENABLED", "false");
  const c = getHourlyConfig();
  assertEquals(c.hourlyBotTicker, "QQQ");
  assertEquals(c.sizingRiskPct, 0.02);
  assertEquals(c.sizingNotionalCapPct, 0.20);
  assertEquals(c.hourlyStopBufferPct, 0.10);
  assertEquals(c.hourlyMinStopDistance, 0.10);
  assertEquals(c.hourlyMaxEntriesPerDay, 5);
  assertEquals(c.hourlyStalenessToleranceMin, 15);
  assertEquals(c.hourlyContextMode, "reversal");
  assertEquals(c.hourlyShortsEnabled, false);
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects empty HOURLY_BOT_TICKER", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_BOT_TICKER", "  ");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_BOT_TICKER");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects SIZING_RISK_PCT out of (0, 0.05]", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("SIZING_RISK_PCT", "0.06");
  assertThrows(() => getHourlyConfig(), Error, "SIZING_RISK_PCT");
  Deno.env.set("SIZING_RISK_PCT", "0");
  assertThrows(() => getHourlyConfig(), Error, "SIZING_RISK_PCT");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects SIZING_NOTIONAL_CAP_PCT out of (0, 1.0]", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("SIZING_NOTIONAL_CAP_PCT", "1.01");
  assertThrows(() => getHourlyConfig(), Error, "SIZING_NOTIONAL_CAP_PCT");
  Deno.env.set("SIZING_NOTIONAL_CAP_PCT", "0");
  assertThrows(() => getHourlyConfig(), Error, "SIZING_NOTIONAL_CAP_PCT");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: HOURLY_BRACKET_R_MULTIPLE must be exactly 2", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_BRACKET_R_MULTIPLE", "3");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_BRACKET_R_MULTIPLE");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects HOURLY_STOP_BUFFER_PCT out of (0, 0.5]", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_STOP_BUFFER_PCT", "0.51");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_STOP_BUFFER_PCT");
  Deno.env.set("HOURLY_STOP_BUFFER_PCT", "0");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_STOP_BUFFER_PCT");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects HOURLY_MIN_STOP_DISTANCE <= 0", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_MIN_STOP_DISTANCE", "0");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_MIN_STOP_DISTANCE");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects HOURLY_MAX_ENTRIES_PER_DAY out of [1, 10]", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_MAX_ENTRIES_PER_DAY", "0");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_MAX_ENTRIES_PER_DAY");
  Deno.env.set("HOURLY_MAX_ENTRIES_PER_DAY", "11");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_MAX_ENTRIES_PER_DAY");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects HOURLY_STALENESS_TOLERANCE_MIN out of [1, 60]", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_STALENESS_TOLERANCE_MIN", "0");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_STALENESS_TOLERANCE_MIN");
  Deno.env.set("HOURLY_STALENESS_TOLERANCE_MIN", "61");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_STALENESS_TOLERANCE_MIN");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects an unknown HOURLY_CONTEXT_MODE", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_CONTEXT_MODE", "momentum");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_CONTEXT_MODE");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: rejects a non-boolean HOURLY_SHORTS_ENABLED", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_SHORTS_ENABLED", "yes");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_SHORTS_ENABLED");
  clearHourlyEnv();
});

// HOURLY_SHORTS_ENABLED fails closed (#493): a lost or never-set secret must
// leave shorts off, so the short-side path cannot be armed by the absence of a
// value. Enabling requires an explicit "true", mirroring HOURLY_BOT_PAPER_ONLY.
Deno.test("getHourlyConfig: HOURLY_SHORTS_ENABLED unset disables shorts (fail-closed)", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  assertEquals(getHourlyConfig().hourlyShortsEnabled, false);
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: HOURLY_SHORTS_ENABLED enables shorts only on an explicit true", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_SHORTS_ENABLED", "TRUE");
  assertEquals(getHourlyConfig().hourlyShortsEnabled, true);
  Deno.env.set("HOURLY_SHORTS_ENABLED", "false");
  assertEquals(getHourlyConfig().hourlyShortsEnabled, false);
  clearHourlyEnv();
});

// A present-but-blank secret is not an implicit unset: it stays a validation
// error, so it surfaces as a config failure instead of quietly picking a side.
// The empty-string case is the one broken deploy tooling actually produces, and
// it is what a `??`-to-`||` slip in the default would silently swallow.
Deno.test("getHourlyConfig: blank/whitespace-only HOURLY_SHORTS_ENABLED throws", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  Deno.env.set("HOURLY_SHORTS_ENABLED", "");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_SHORTS_ENABLED");
  Deno.env.set("HOURLY_SHORTS_ENABLED", "  ");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_SHORTS_ENABLED");
  clearHourlyEnv();
});

// HOURLY_BOT_PAPER_ONLY: strict reading (the derived T1 decision) -- throws
// unless the operator has explicitly set it to "true". Unset is NOT treated
// as the table's "default true"; a missing knob for the mechanical paper-only
// gate must fail closed, not fail open.
Deno.test("getHourlyConfig: HOURLY_BOT_PAPER_ONLY unset throws (fail-closed, not default-true)", () => {
  clearHourlyEnv();
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_BOT_PAPER_ONLY");
});

Deno.test("getHourlyConfig: HOURLY_BOT_PAPER_ONLY=false throws", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "false");
  assertThrows(() => getHourlyConfig(), Error, "HOURLY_BOT_PAPER_ONLY");
  clearHourlyEnv();
});

Deno.test("getHourlyConfig: HOURLY_BOT_PAPER_ONLY=true passes", () => {
  clearHourlyEnv();
  Deno.env.set("HOURLY_BOT_PAPER_ONLY", "true");
  assertEquals(getHourlyConfig().hourlyBotPaperOnly, true);
  clearHourlyEnv();
});
